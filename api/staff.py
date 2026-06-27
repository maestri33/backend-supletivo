"""Grupo `staff` — administração da plataforma (o "boss": cadastra hub, define coordenador).

Todas as rotas exigem SUPERUSER (staff = superuser nativo do Django — Victor 2026-06-03), via
`require_superuser`. Casca fina (CONVENTION §3): valida a borda e chama o `interface/` do `hub` e do
`users/roles`. Zero regra de negócio aqui.
"""

from __future__ import annotations

from django.conf import settings
from ninja import Schema

from api.auth import require_superuser
from api.base import build_group
from api.schemas import MaterialIn, MaterialOut, MaterialUpdateIn
from users.exceptions import NotFound, ValidationError as DomainValidationError
from finance import interface as finance_iface
from hub import interface as hub_iface
from integrations import status as integ_status
from integrations.bank.asaas import onboarding as asaas_onboarding
from users.auth import interface as auth_iface
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment import interface as enrollment_iface
from users.roles.lead import interface as lead_iface
from users.roles.student import interface as student_iface
from users.roles.training import interface as training_iface

api = build_group("staff", "Administração da plataforma: hub, coordenador, saúde dos serviços.")


# ── schemas ──────────────────────────────────────────────────────────────
class HubCreateIn(Schema):
    brand: str
    coordinator_external_id: str | None = None


class SetCoordinatorIn(Schema):
    coordinator_external_id: str


class HubAddressIn(Schema):
    cep: str
    number: str | None = None
    complement: str | None = None


class HubOut(Schema):
    external_id: str
    brand: str
    coordinator_external_id: str | None
    is_default: bool


class PromoterOut(Schema):
    external_id: str
    name: str | None


# ── schemas de SAÍDA (response=) — espelham 1:1 o snake_case real das interfaces que o staff chama.
# Antes vários GET devolviam dict solto e o front tipava no escuro; agora o OpenAPI publica o
# contrato (mesma régua do grupo leadership). Shapes dinâmicos (saldo Asaas, setup/test) seguem dict.
class MaterialPublishOut(Schema):
    """Ack de publicar matéria transitória (`training_iface.publish_transitory`)."""

    external_id: str
    assigned: int


class MaterialDeletedOut(Schema):
    """Ack de descarte de matéria efêmera."""

    deleted: str


class StaffLeadRowOut(Schema):
    """Lead na visão global do staff (`lead_iface.lead_to_dict`)."""

    external_id: str
    status: str
    name: str | None = None
    phone: str | None = None
    promoter_external_id: str
    payment_link: str | None = None
    receipt_url: str | None = None


class FinanceSummaryOut(Schema):
    """Resumo financeiro: por status → `{count, total}`. As chaves de status são dinâmicas
    (dependem dos status existentes), por isso os buckets ficam `dict` (honesto)."""

    commissions: dict
    payment_requests: dict


class CommissionRowOut(Schema):
    """Comissão (`finance_iface.list_commissions`). `amount` = Decimal em string (reais)."""

    external_id: str
    payee_external_id: str | None = None
    payee_role: str
    source_type: str
    amount: str
    status: str
    external_reference: str | None = None
    created_at: str


class PaymentRequestRowOut(Schema):
    """Solicitação de pagamento/payout (`finance_iface.list_payment_requests`)."""

    external_id: str
    kind: str
    method: str
    amount: str
    status: str
    supplier_name: str | None = None
    week_of: str | None = None
    scheduled_for: str | None = None
    asaas_status: str | None = None
    external_reference: str | None = None
    created_at: str


class IntegrationOut(Schema):
    """Saúde/config de uma integração (`integrations.status`). `config` (bool por env — NUNCA o
    valor do secret), `checks` (ledger) e `live` (asaas ao vivo) têm chaves dinâmicas → dict/list."""

    name: str
    configured: bool
    config: dict
    flow: str
    checks: list = []
    live: dict | None = None


class SystemStatusOut(Schema):
    """Saúde do servidor (`/system`)."""

    db_ok: bool
    migrations_pending: list[str] = []
    qcluster_alive: bool
    qcluster_count: int
    queued_tasks: int | None = None
    debug: bool
    external_url: str | None = None


class UnroutedEventOut(Schema):
    """Evento sem consumidor (fallback rastreável do core)."""

    source: str
    event: str
    reason: str | None = None
    resolved: bool
    received_at: str


class AiCallOut(Schema):
    """Chamada de IA do ledger `AiCall`. `cost` = Decimal em string (ou null)."""

    provider: str
    model: str
    operation: str
    caller: str | None = None
    status: str
    cost: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    created_at: str


class ValidationCheckOut(Schema):
    """Linha do ledger de validação (`ValidationCheck`)."""

    scope: str
    name: str
    passed: bool
    mode: str | None = None
    detail: str | None = None
    checked_at: str


class StaffFunnelRowOut(Schema):
    """Linha de matrícula/aluno na visão global do staff (`enrollment`/`student.list_for_staff`)."""

    external_id: str
    status: str
    self_study: bool
    hub_external_id: str
    name: str | None = None


class StaffUserRowOut(Schema):
    """Usuário + roles ativas (visão read-only do staff)."""

    external_id: str
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    is_superuser: bool
    roles: list[str] = []


class ExternalIdStatusOut(Schema):
    """Ack genérico `{external_id, status}` (ex.: platform-credentials)."""

    external_id: str
    status: str


class PhoneChangedOut(Schema):
    """Ack do resgate de telefone (`auth_iface.change_phone`)."""

    external_id: str
    phone: str


def _hub_out(hub) -> dict:
    return {
        "external_id": str(hub.external_id),
        "brand": hub.brand,
        "coordinator_external_id": (str(hub.coordinator.external_id) if hub.coordinator else None),
        "is_default": hub.is_default,
    }


# ── rotas (todas exigem superuser) ─────────────────────────────────────────
@api.post("/hubs", response=HubOut, tags=["staff"])
def create_hub(request, payload: HubCreateIn):
    """Cria um polo: marca (do catálogo) + coordenador opcional (um promotor)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.create_hub(
            brand=payload.brand,
            coordinator_external_id=payload.coordinator_external_id,
        )
    except hub_iface.HubError as exc:
        raise DomainValidationError(str(exc), code="HUB_ERROR") from exc
    return _hub_out(hub)


@api.get("/hubs", response=list[HubOut], tags=["staff"])
def list_hubs(request):
    """Lista todos os polos."""
    require_superuser(request.auth)
    return [_hub_out(h) for h in hub_iface.list_hubs()]


@api.get("/promoters", response=list[PromoterOut], tags=["staff"])
def list_promoters(request):
    """Lista os promotores (pra escolher quem será coordenador de um polo)."""
    require_superuser(request.auth)
    base = roles.users_with_role("promoter")
    pmap = profiles.get_map(base)
    out = []
    for user in base:
        p = pmap.get(user.id)
        out.append(
            {
                "external_id": str(user.external_id),
                "name": p.name if p else None,
            }
        )
    return out


@api.put("/hubs/{external_id}/coordinator", response=HubOut, tags=["staff"])
def set_coordinator(request, external_id: str, payload: SetCoordinatorIn):
    """Designa/troca o coordenador de um polo (um promotor)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_coordinator(
            hub_external_id=external_id,
            coordinator_external_id=payload.coordinator_external_id,
        )
    except hub_iface.HubError as exc:
        if exc.args and exc.args[0] == "hub_not_found":
            raise NotFound(str(exc), code="HUB_NOT_FOUND") from exc
        raise DomainValidationError(str(exc), code="HUB_ERROR") from exc
    return _hub_out(hub)


@api.put("/hubs/{external_id}/default", response=HubOut, tags=["staff"])
def set_default_hub(request, external_id: str):
    """Marca um polo como PADRÃO (fallback de captação; único — desmarca os outros)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_default(external_id)
    except hub_iface.HubError as exc:
        if exc.args and exc.args[0] == "hub_not_found":
            raise NotFound(str(exc), code="HUB_NOT_FOUND") from exc
        raise DomainValidationError(str(exc), code="HUB_ERROR") from exc
    return _hub_out(hub)


@api.patch("/hubs/{external_id}/address", response=HubOut, tags=["staff"])
def set_hub_address(request, external_id: str, payload: HubAddressIn):
    """Preenche o endereço do polo pelo CEP (ViaCEP) — o polo nasce com endereço vazio. CEP
    inexistente → 422 `CEP_NOT_FOUND` (envelope central)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_address(
            hub_external_id=external_id,
            cep=payload.cep,
            number=payload.number,
            complement=payload.complement,
        )
    except hub_iface.HubError as exc:
        raise NotFound(str(exc), code="HUB_NOT_FOUND") from exc
    return _hub_out(hub)


# ── autoria de matéria do treino (staff — também o coordenador, no grupo leadership) ──
# MaterialIn/MaterialUpdateIn vêm do módulo compartilhado (plan/15 A7; mesmo contrato do leadership).
@api.post("/training/materials", response=MaterialOut, tags=["staff"])
def create_material(request, payload: MaterialIn):
    """Cria uma matéria do treino (texto+questão+gabarito)."""
    require_superuser(request.auth)
    m = training_iface.create_material(**payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.put("/training/materials/{external_id}", response=MaterialOut, tags=["staff"])
def update_material(request, external_id: str, payload: MaterialUpdateIn):
    """Edita uma matéria (campos enviados; `active=False` desativa)."""
    require_superuser(request.auth)
    m = training_iface.update_material(external_id, **payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.get("/training/materials", response=list[MaterialOut], tags=["staff"])
def list_materials(request):
    """Lista todas as matérias (com gabarito — visão de autoria)."""
    require_superuser(request.auth)
    return [
        training_iface.material_to_dict(m, include_answer=True)
        for m in training_iface.list_materials(active_only=False)
    ]


@api.post(
    "/training/materials/{external_id}/publish",
    response=MaterialPublishOut,
    tags=["staff"],
)
def publish_material(request, external_id: str):
    """Publica uma matéria TRANSITÓRIA → atribui aos promotores JÁ existentes + re-trava + notifica.
    (As FIXAS não precisam: entram em cada novo promotor ao ser aprovado.)"""
    require_superuser(request.auth)
    return training_iface.publish_transitory(external_id)


@api.delete("/training/materials/{external_id}", response=MaterialDeletedOut, tags=["staff"])
def delete_material(request, external_id: str):
    """Descarta uma matéria EFÊMERA (descartável). Não-efêmera → desative com update `active=False`."""
    require_superuser(request.auth)
    training_iface.delete_material(external_id)
    return {"deleted": external_id}


# ── leads (staff vê TODOS; filtra por polo) ──────────────────────────────────
@api.get("/leads", response=list[StaffLeadRowOut], tags=["lead"])
def list_all_leads(request, hub: str | None = None, status: str | None = None):
    """Lista TODOS os leads (link de pagamento + comprovante). Filtros: `hub` (external_id) e `status`."""
    require_superuser(request.auth)
    hub_obj = None
    if hub:
        hub_obj = hub_iface.get_by_external_id(hub)
        if hub_obj is None:
            raise NotFound("Polo não encontrado.", code="HUB_NOT_FOUND")
    leads = lead_iface.list_leads(hub=hub_obj, status=status)
    return [lead_iface.lead_to_dict(lead) for lead in leads]


# ── financeiro (WP6: saldo Asaas + comissões + fila de payouts + resumo) ─────
@api.get("/finance/balance", tags=["staff"])
def finance_balance(request):
    """Saldo da conta Asaas (read-only — NÃO move dinheiro)."""
    require_superuser(request.auth)
    return asaas_onboarding.account_balance()


@api.get("/finance/summary", response=FinanceSummaryOut, tags=["staff"])
def finance_summary(request):
    """Resumo por status (contagem + total em reais) de comissões e da fila de saída."""
    require_superuser(request.auth)
    return finance_iface.summary()


@api.get("/finance/commissions", response=list[CommissionRowOut], tags=["staff"])
def finance_commissions(request, status: str | None = None):
    """Comissões (filtro opcional por status: pending/processed/paid/failed)."""
    require_superuser(request.auth)
    return finance_iface.list_commissions(status=status)


@api.get("/finance/payouts", response=list[PaymentRequestRowOut], tags=["staff"])
def finance_payouts(request, status: str | None = None, kind: str | None = None):
    """Solicitações de pagamento / payouts (filtros: status; kind=commission|fee)."""
    require_superuser(request.auth)
    return finance_iface.list_payment_requests(status=status, kind=kind)


# ── integrações (WP6: status/config + fluxo + ações setup/test) ─────────────
@api.get("/integrations", response=list[IntegrationOut], tags=["staff"])
def list_integrations(request):
    """Saúde/config de TODAS as integrações (read-only): env presente + fluxo + último do ledger."""
    require_superuser(request.auth)
    return integ_status.list_integrations()


@api.get("/integrations/{name}", response=IntegrationOut, tags=["staff"])
def integration_detail(request, name: str):
    """Detalhe de uma integração (asaas faz run_checks AO VIVO: saldo + webhook)."""
    require_superuser(request.auth)
    data = integ_status.integration_detail(name)
    if data is None:
        raise NotFound("Integração não encontrada.", code="INTEGRATION_NOT_FOUND")
    return data


@api.post("/integrations/{name}/setup", tags=["staff"])
def integration_setup(request, name: str):
    """Roda o onboarding da integração (asaas: auto-cadastra o webhook). Idempotente."""
    require_superuser(request.auth)
    data = integ_status.run_setup(name)
    if data is None:
        raise NotFound("Integração não encontrada.", code="INTEGRATION_NOT_FOUND")
    return data


@api.post("/integrations/{name}/test", tags=["staff"])
def integration_test(request, name: str):
    """Teste de saúde ao vivo (carimba o ledger; asaas faz a bateria real)."""
    require_superuser(request.auth)
    data = integ_status.run_test(name)
    if data is None:
        raise NotFound("Integração não encontrada.", code="INTEGRATION_NOT_FOUND")
    return data


# ── status do servidor (WP6) ─────────────────────────────────────────────────
@api.get("/system", response=SystemStatusOut, tags=["staff"])
def system_status(request):
    """Saúde do servidor: DB, migrações pendentes, qcluster (Django-Q) + fila, DEBUG, EXTERNAL_URL."""
    require_superuser(request.auth)
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    db_ok = True
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        db_ok = False
    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    clusters: list = []
    queued = None
    try:
        from django_q.models import OrmQ
        from django_q.status import Stat

        clusters = [s.cluster_id for s in Stat.get_all()]
        queued = OrmQ.objects.count()
    except Exception:  # noqa: BLE001
        pass
    return {
        "db_ok": db_ok,
        "migrations_pending": [f"{m.app_label}.{m.name}" for m, _ in pending],
        "qcluster_alive": bool(clusters),
        "qcluster_count": len(clusters),
        "queued_tasks": queued,
        "debug": settings.DEBUG,
        "external_url": settings.EXTERNAL_URL,
    }


# ── logs / ledgers (WP6) ─────────────────────────────────────────────────────
@api.get("/logs/unrouted", response=list[UnroutedEventOut], tags=["staff"])
def logs_unrouted(request, resolved: bool | None = None, limit: int = 100):
    """Eventos que chegaram mas não tinham consumidor (fallback rastreável do core)."""
    require_superuser(request.auth)
    from core.models import UnroutedEvent

    qs = UnroutedEvent.objects.order_by("-received_at")
    if resolved is not None:
        qs = qs.filter(resolved=resolved)
    return [
        {
            "source": e.source,
            "event": e.event,
            "reason": e.reason,
            "resolved": e.resolved,
            "received_at": e.received_at.isoformat(),
        }
        for e in qs[:limit]
    ]


@api.get("/logs/ai-calls", response=list[AiCallOut], tags=["staff"])
def logs_ai_calls(request, status: str | None = None, limit: int = 100):
    """Chamadas de IA (provider/modelo/operação/custo/erro/latência) — o ledger `AiCall`."""
    require_superuser(request.auth)
    from integrations.ai.models import AiCall

    qs = AiCall.objects.order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    return [
        {
            "provider": a.provider,
            "model": a.model,
            "operation": a.operation,
            "caller": a.caller,
            "status": a.status,
            "cost": str(a.cost) if a.cost is not None else None,
            "latency_ms": a.latency_ms,
            "error": a.error,
            "created_at": a.created_at.isoformat(),
        }
        for a in qs[:limit]
    ]


@api.get("/logs/checks", response=list[ValidationCheckOut], tags=["staff"])
def logs_checks(request, scope: str | None = None, limit: int = 100):
    """Histórico do ledger de validação (`ValidationCheck` — testes carimbados)."""
    require_superuser(request.auth)
    from core.models import ValidationCheck

    qs = ValidationCheck.objects.order_by("-checked_at")
    if scope:
        qs = qs.filter(scope=scope)
    return [
        {
            "scope": c.scope,
            "name": c.name,
            "passed": c.passed,
            "mode": c.mode,
            "detail": c.detail,
            "checked_at": c.checked_at.isoformat(),
        }
        for c in qs[:limit]
    ]


# ── visão global (todos os polos) — WP6-D ────────────────────────────────────
@api.get("/enrollments", response=list[StaffFunnelRowOut], tags=["enrollment"])
def list_all_enrollments(request, hub: str | None = None, status: str | None = None):
    """Matrículas de TODOS os polos (filtros: `hub` external_id, `status`)."""
    require_superuser(request.auth)
    return enrollment_iface.list_for_staff(hub_external_id=hub, status=status)


@api.get("/students", response=list[StaffFunnelRowOut], tags=["student"])
def list_all_students(request, hub: str | None = None, status: str | None = None):
    """Alunos de TODOS os polos (filtros: `hub` external_id, `status`)."""
    require_superuser(request.auth)
    return student_iface.list_for_staff(hub_external_id=hub, status=status)


# ── credenciais da plataforma (SÓ staff altera após a conclusão — Victor 2026-06-23) ──
class PlatformCredentialsIn(Schema):
    platform_login: str
    platform_password: str
    platform_url: str | None = None
    platform_notes: str | None = None


@api.put(
    "/students/{external_id}/platform-credentials",
    response=ExternalIdStatusOut,
    tags=["student"],
)
def set_student_platform_credentials(request, external_id: str, payload: PlatformCredentialsIn):
    """Staff corrige login/senha (e url/notes) da plataforma de um aluno JÁ concluído. SÓ staff
    altera depois de concluído (Victor 2026-06-23: coordenador/bot não mexem). Login é ÚNICO por
    matrícula → 409 `PLATFORM_LOGIN_TAKEN` se repetir; aluno inexistente → 404."""
    require_superuser(request.auth)
    student = student_iface.set_platform_credentials(
        student_external_id=external_id,
        platform_login=payload.platform_login,
        platform_password=payload.platform_password,
        platform_url=payload.platform_url,
        platform_notes=payload.platform_notes,
    )
    return {"external_id": str(student.external_id), "status": student.status}


# ── bot matriculador (MOCK — o gatilho real é o signal enrollment_ready_for_matricula) ──
class BotMatriculadorIn(Schema):
    enrollment_external_id: str


@api.post("/bot-matriculador", tags=["todo"])
def bot_matriculador(request, payload: BotMatriculadorIn):
    """STUB do bot matriculador — ainda NÃO implementado (Victor 2026-06-23). Reserva de interface;
    o gatilho de verdade é o Django signal `enrollment_ready_for_matricula` (core/todo). Responde 501."""
    require_superuser(request.auth)
    from django.http import JsonResponse

    return JsonResponse(
        {
            "detail": "Bot matriculador ainda não implementado.",
            "code": "NOT_IMPLEMENTED",
        },
        status=501,
    )


# ── usuários da plataforma (read-only; mutação de role = «PENDÊNCIA» Victor) ──
@api.get("/users", response=list[StaffUserRowOut], tags=["staff"])
def list_users(request, role: str | None = None, limit: int = 200):
    """Usuários + roles ativas (filtro opcional por `role`). Read-only — a mudança de role pelo staff
    fica pra depois (regra do Victor: "dentro do cabível")."""
    require_superuser(request.auth)
    from users.auth.models import User

    if role:
        base = roles.users_with_role(role)[:limit]
    else:
        base = list(User.objects.order_by("-id")[:limit])
    pmap = profiles.get_map(base)
    out = []
    for u in base:
        p = pmap.get(u.id)
        out.append(
            {
                "external_id": str(u.external_id),
                "name": p.name if p else None,
                "cpf": p.cpf if p else None,
                "phone": p.phone if p else None,
                "is_superuser": u.is_superuser,
                "roles": roles.active_roles(u),
            }
        )
    return out


class PhoneIn(Schema):
    phone: str


@api.put("/users/{external_id}/phone", response=PhoneChangedOut, tags=["staff"])
def set_user_phone(request, external_id: str, payload: PhoneIn):
    """RESGATE DE LOGIN (Victor 2026-06-17): o usuário perdeu o número/chip e não recebe mais o OTP
    → fica trancado fora, sem rota nem pro coordenador. O staff troca o telefone (valida formato +
    WhatsApp ativo no novo número + unicidade). É a ponta da hierarquia de resgate user→coord→staff;
    trocar o canal de login é poder do staff, não do coordenador. Auditado."""
    require_superuser(request.auth)
    return auth_iface.change_phone(user_external_id=external_id, new_phone=payload.phone)
