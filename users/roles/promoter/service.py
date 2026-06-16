"""Lógica do promoter (fim do funil do colaborador). Criado na aprovação da entrevista do treino.

`ref` de captação = o `external_id` do User (sem model de link). `validate_ref` é o que o funil do ALUNO
consome pra amarrar o lead ao promotor. Listagens (leads/comissões) são read-only sobre `lead`/`finance`.
"""

from __future__ import annotations

import uuid

import structlog
from django.conf import settings

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
