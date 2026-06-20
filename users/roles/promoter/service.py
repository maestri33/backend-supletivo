"""Lógica do promoter (fim do funil do colaborador). Criado quando o coordenador aprova o candidato.

`ref` de captação = o `external_id` do User (sem model de link). `validate_ref` é o que o funil do ALUNO
consome pra amarrar o lead ao promotor. Listagens (leads/comissões) são read-only sobre `lead`/`finance`.
"""

from __future__ import annotations

import uuid

import structlog
from django.conf import settings

from users.exceptions import Forbidden, NotFound
from users.roles.promoter.models import Promoter

logger = structlog.get_logger()


def create_promoter(*, user, hub) -> Promoter:
    """Cria o Promoter(ACTIVE) ligado ao hub herdado do candidato. Idempotente."""
    existing = Promoter.objects.filter(user=user).first()
    if existing is not None:
        return existing
    promoter = Promoter.objects.create(
        user=user, hub=hub, status=Promoter.Status.ACTIVE
    )
    logger.info(
        "promoter.created",
        external_id=str(promoter.external_id),
        hub=str(hub.external_id),
    )
    return promoter


def get_for_user(user) -> Promoter | None:
    return Promoter.objects.filter(user=user).select_related("hub").first()


def get_by_user_external_id(external_id: str) -> Promoter | None:
    return (
        Promoter.objects.filter(user__external_id=external_id)
        .select_related("user", "hub")
        .first()
    )


def validate_ref(ref: str):
    """`ref` = external_id do User-promotor ATIVO → devolve o User (o lead amarra nele); senão None.

    O `ref` chega CRU da landing (`?ref=`) — malformado (não-UUID) conta como inválido → None,
    NUNCA exceção solta (o caller cai no promotor padrão). Antes estourava 500 e quebrava o
    cadastro de quem clicou num link com ref estragado (bug reportado pelo Victor 2026-06-10)."""
    try:
        ref_uuid = uuid.UUID(str(ref))
    except (TypeError, ValueError):
        return None
    promoter = (
        Promoter.objects.filter(
            user__external_id=ref_uuid, status=Promoter.Status.ACTIVE
        )
        .select_related("user")
        .first()
    )
    if promoter is None:
        return None
    # promotor TRAVADO no treino obrigatório ainda NÃO capta (Victor 2026-06-16) — cai no padrão.
    from users.roles.training import interface as training_iface

    if training_iface.is_locked(promoter.user):
        return None
    return promoter.user


def ref_url(user) -> str:
    base = (
        getattr(settings, "LANDING_BASE_URL", "") or settings.EXTERNAL_URL or ""
    ).rstrip("/")
    return f"{base}/?ref={user.external_id}"


def to_dict(promoter: Promoter) -> dict:
    """Painel do promotor. `locked` + `pending_materials` = a trava do treino (lida do banco, não do
    JWT): se travado, o front mostra só o treino. Liberado → painel cheio + captação ativa."""
    from users.roles.training import interface as training_iface

    return {
        "external_id": str(promoter.external_id),
        "status": promoter.status,
        "hub_external_id": str(promoter.hub.external_id),
        "ref_url": ref_url(promoter.user),
        "locked": training_iface.is_locked(promoter.user),
        "pending_materials": training_iface.pending_materials(promoter.user),
    }


def list_leads(user) -> list[dict]:
    """Leads captados por este promotor (read-only, do funil do aluno)."""
    from users.roles.lead.models import Lead

    rows = Lead.objects.filter(promoter=user).order_by("-created_at")[:200]
    return [
        {
            "external_id": str(row.external_id),
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def list_commissions(user) -> list[dict]:
    """Comissões do promotor (read-only, do finance)."""
    from finance.models import Commission

    rows = Commission.objects.filter(payee=user).order_by("-created_at")[:200]
    return [
        {
            "external_id": str(row.external_id),
            "amount": str(row.amount),
            "source": row.source_type,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


# ── coordenador: suspender / reativar / listar promotores do polo (WP5, Victor 2026-06-16) ──


def _coordinated_promoter(user_external_id: str, coordinator) -> Promoter:
    """Carrega o promotor (por external_id do User) e exige que `coordinator` coordene o hub dele."""
    promoter = get_by_user_external_id(user_external_id)
    if promoter is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")
    if promoter.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste promotor.", code="NOT_HUB_COORDINATOR"
        )
    return promoter


def suspend(*, user_external_id: str, coordinator) -> Promoter:
    """Coordenador suspende o promotor do polo (não capta nem recebe). Idempotente."""
    promoter = _coordinated_promoter(user_external_id, coordinator)
    if promoter.status != Promoter.Status.SUSPENDED:
        promoter.status = Promoter.Status.SUSPENDED
        promoter.save(update_fields=["status", "updated_at"])
        _notify_status(promoter, "promoter.suspended")
        logger.info("promoter.suspended", external_id=str(promoter.external_id))
    return promoter


def reactivate(*, user_external_id: str, coordinator) -> Promoter:
    """Coordenador reativa um promotor suspenso (volta a captar). Idempotente."""
    promoter = _coordinated_promoter(user_external_id, coordinator)
    if promoter.status != Promoter.Status.ACTIVE:
        promoter.status = Promoter.Status.ACTIVE
        promoter.save(update_fields=["status", "updated_at"])
        _notify_status(promoter, "promoter.reactivated")
        logger.info("promoter.reactivated", external_id=str(promoter.external_id))
    return promoter


def list_for_hub(hub) -> list[dict]:
    """Promotores do polo (pro painel do coordenador): status + se estão travados no treino."""
    from users.profiles import interface as profiles
    from users.roles.training import interface as training_iface

    promoters = list(
        Promoter.objects.filter(hub=hub).select_related("user").order_by("created_at")
    )
    pmap = profiles.get_map([pr.user for pr in promoters])
    out = []
    for promoter in promoters:
        p = pmap.get(promoter.user_id)
        out.append(
            {
                "external_id": str(promoter.user.external_id),
                "name": p.name if p else None,
                "status": promoter.status,
                "locked": training_iface.is_locked(promoter.user),
            }
        )
    return out


def _notify_status(promoter: Promoter, event: str) -> None:
    from notify.interface.send import send
    from users.profiles import interface as profiles
    from users.roles import notifications as msgs

    p = profiles.get(promoter.user)
    try:
        send(
            text=msgs.text(event, name=msgs.first_name(p.name if p else None)),
            caller=event,
            phone=p.phone if p else None,
            # chave por toggle (updated_at muda a cada mudança real de status) → retry dedupa, toggles não.
            idempotency_key=f"{event}_{promoter.user.external_id}_{int(promoter.updated_at.timestamp())}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("promoter.notify_status_failed", event=event, error=str(exc))
