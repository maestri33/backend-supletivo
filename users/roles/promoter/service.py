"""Lógica do promoter (fim do funil do colaborador). Criado na aprovação da entrevista do treino.

`ref` de captação = o `external_id` do User (sem model de link). `validate_ref` é o que o funil do ALUNO
consome pra amarrar o lead ao promotor. Listagens (leads/comissões) são read-only sobre `lead`/`finance`.
"""

from __future__ import annotations

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
    """`ref` = external_id do User-promotor ATIVO → devolve o User (o lead amarra nele); senão None."""
    promoter = (
        Promoter.objects.filter(user__external_id=ref, status=Promoter.Status.ACTIVE)
        .select_related("user")
        .first()
    )
    return promoter.user if promoter else None


def ref_url(user) -> str:
    base = (
        getattr(settings, "LANDING_BASE_URL", "") or settings.EXTERNAL_URL or ""
    ).rstrip("/")
    return f"{base}/?ref={user.external_id}"


def to_dict(promoter: Promoter) -> dict:
    return {
        "external_id": str(promoter.external_id),
        "status": promoter.status,
        "hub_external_id": str(promoter.hub.external_id),
        "ref_url": ref_url(promoter.user),
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
