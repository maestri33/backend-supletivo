"""Grupo `staff` — administração da plataforma (o "boss": cadastra hub, define coordenador).

Todas as rotas exigem SUPERUSER (staff = superuser nativo do Django — Victor 2026-06-03), via
`require_superuser`. Casca fina (CONVENTION §3): valida a borda e chama o `interface/` do `hub` e do
`users/roles`. Zero regra de negócio aqui.
"""

from __future__ import annotations

from django.conf import settings
from ninja import Schema
from ninja.errors import HttpError

from api.auth import require_superuser
from api.base import build_group
from api.schemas import MaterialIn, MaterialUpdateIn
from finance import interface as finance_iface
from hub import interface as hub_iface
from integrations import status as integ_status
from integrations.bank.asaas import onboarding as asaas_onboarding
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment import interface as enrollment_iface
from users.roles.lead import interface as lead_iface
from users.roles.student import interface as student_iface
from users.roles.training import interface as training_iface

api = build_group(
    "staff", "Administração da plataforma: hub, coordenador, saúde dos serviços."
)


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


def _hub_out(hub) -> dict:
    return {
        "external_id": str(hub.external_id),
        "brand": hub.brand,
        "coordinator_external_id": (
            str(hub.coordinator.external_id) if hub.coordinator else None
        ),
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
        raise HttpError(422, str(exc)) from exc
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
    out = []
    for user in roles.users_with_role("promoter"):
        profile = profiles.get(user)
        out.append(
            {
                "external_id": str(user.external_id),
                "name": profile.name if profile else None,
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
        status = 404 if exc.args and exc.args[0] == "hub_not_found" else 422
        raise HttpError(status, str(exc)) from exc
    return _hub_out(hub)


@api.put("/hubs/{external_id}/default", response=HubOut, tags=["staff"])
def set_default_hub(request, external_id: str):
    """Marca um polo como PADRÃO (fallback de captação; único — desmarca os outros)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_default(external_id)
    except hub_iface.HubError as exc:
        status = 404 if exc.args and exc.args[0] == "hub_not_found" else 422
        raise HttpError(status, str(exc)) from exc
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
        raise HttpError(404, str(exc)) from exc
    return _hub_out(hub)


# ── autoria de matéria do treino (staff — também o coordenador, no grupo leadership) ──
# MaterialIn/MaterialUpdateIn vêm do módulo compartilhado (plan/15 A7; mesmo contrato do leadership).
@api.post("/training/materials", tags=["staff"])
def create_material(request, payload: MaterialIn):
    """Cria uma matéria do treino (texto+questão+gabarito)."""
    require_superuser(request.auth)
    m = training_iface.create_material(**payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.put("/training/materials/{external_id}", tags=["staff"])
def update_material(request, external_id: str, payload: MaterialUpdateIn):
    """Edita uma matéria (campos enviados; `active=False` desativa)."""
    require_superuser(request.auth)
    m = training_iface.update_material(external_id, **payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.get("/training/materials", tags=["staff"])
def list_materials(request):
    """Lista todas as matérias (com gabarito — visão de autoria)."""
    require_superuser(request.auth)
    return [
        training_iface.material_to_dict(m, include_answer=True)
        for m in training_iface.list_materials(active_only=False)
    ]


@api.post("/training/materials/{external_id}/publish", tags=["staff"])
def publish_material(request, external_id: str):
    """Publica uma matéria TRANSITÓRIA → atribui aos promotores JÁ existentes + re-trava + notifica.
    (As FIXAS não precisam: entram em cada novo promotor ao ser aprovado.)"""
    require_superuser(request.auth)
    return training_iface.publish_transitory(external_id)


@api.delete("/training/materials/{external_id}", tags=["staff"])
def delete_material(request, external_id: str):
    """Descarta uma matéria EFÊMERA (descartável). Não-efêmera → desative com update `active=False`."""
    require_superuser(request.auth)
    training_iface.delete_material(external_id)
    return {"deleted": external_id}


# ── leads (staff vê TODOS; filtra por polo) ──────────────────────────────────
@api.get("/leads", tags=["lead"])
def list_all_leads(request, hub: str | None = None, status: str | None = None):
    """Lista TODOS os leads (link de pagamento + comprovante). Filtros: `hub` (external_id) e `status`."""
    require_superuser(request.auth)
    hub_obj = None
    if hub:
        # hub passado mas inexistente → 404 (não cair silenciosamente em "todos os leads")
        hub_obj = hub_iface.get_by_external_id(hub)
        if hub_obj is None:
            raise HttpError(404, "hub_not_found")
    leads = lead_iface.list_leads(hub=hub_obj, status=status)
    return [lead_iface.lead_to_dict(lead) for lead in leads]


# ── financeiro (WP6: saldo Asaas + comissões + fila de payouts + resumo) ─────
@api.get("/finance/balance", tags=["staff"])
def finance_balance(request):
    """Saldo da conta Asaas (read-only — NÃO move dinheiro)."""
    require_superuser(request.auth)
    return asaas_onboarding.account_balance()


@api.get("/finance/summary", tags=["staff"])
def finance_summary(request):
    """Resumo por status (contagem + total em reais) de comissões e da fila de saída."""
    require_superuser(request.auth)
    return finance_iface.summary()


@api.get("/finance/commissions", tags=["staff"])
def finance_commissions(request, status: str | None = None):
    """Comissões (filtro opcional por status: pending/processed/paid/failed)."""
    require_superuser(request.auth)
    return finance_iface.list_commissions(status=status)


@api.get("/finance/payouts", tags=["staff"])
def finance_payouts(request, status: str | None = None, kind: str | None = None):
    """Solicitações de pagamento / payouts (filtros: status; kind=commission|fee)."""
    require_superuser(request.auth)
    return finance_iface.list_payment_requests(status=status, kind=kind)


# ── integrações (WP6: status/config + fluxo + ações setup/test) ─────────────
@api.get("/integrations", tags=["staff"])
def list_integrations(request):
    """Saúde/config de TODAS as integrações (read-only): env presente + fluxo + último do ledger."""
    require_superuser(request.auth)
    return integ_status.list_integrations()


@api.get("/integrations/{name}", tags=["staff"])
def integration_detail(request, name: str):
    """Detalhe de uma integração (asaas faz run_checks AO VIVO: saldo + webhook)."""
    require_superuser(request.auth)
    data = integ_status.integration_detail(name)
    if data is None:
        raise HttpError(404, "integration_not_found")
    return data


@api.post("/integrations/{name}/setup", tags=["staff"])
def integration_setup(request, name: str):
    """Roda o onboarding da integração (asaas: auto-cadastra o webhook). Idempotente."""
    require_superuser(request.auth)
    data = integ_status.run_setup(name)
    if data is None:
        raise HttpError(404, "integration_not_found")
    return data


@api.post("/integrations/{name}/test", tags=["staff"])
def integration_test(request, name: str):
    """Teste de saúde ao vivo (carimba o ledger; asaas faz a bateria real)."""
    require_superuser(request.auth)
    data = integ_status.run_test(name)
    if data is None:
        raise HttpError(404, "integration_not_found")
    return data


# ── status do servidor (WP6) ─────────────────────────────────────────────────
@api.get("/system", tags=["staff"])
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
@api.get("/logs/unrouted", tags=["staff"])
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


@api.get("/logs/ai-calls", tags=["staff"])
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


@api.get("/logs/checks", tags=["staff"])
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
@api.get("/enrollments", tags=["enrollment"])
def list_all_enrollments(request, hub: str | None = None, status: str | None = None):
    """Matrículas de TODOS os polos (filtros: `hub` external_id, `status`)."""
    require_superuser(request.auth)
    return enrollment_iface.list_for_staff(hub_external_id=hub, status=status)


@api.get("/students", tags=["student"])
def list_all_students(request, hub: str | None = None, status: str | None = None):
    """Alunos de TODOS os polos (filtros: `hub` external_id, `status`)."""
    require_superuser(request.auth)
    return student_iface.list_for_staff(hub_external_id=hub, status=status)


# ── usuários da plataforma (read-only; mutação de role = «PENDÊNCIA» Victor) ──
@api.get("/users", tags=["staff"])
def list_users(request, role: str | None = None, limit: int = 200):
    """Usuários + roles ativas (filtro opcional por `role`). Read-only — a mudança de role pelo staff
    fica pra depois (regra do Victor: "dentro do cabível")."""
    require_superuser(request.auth)
    from users.auth.models import User

    base = (roles.users_with_role(role) if role else list(User.objects.order_by("-id")))[
        :limit
    ]
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
