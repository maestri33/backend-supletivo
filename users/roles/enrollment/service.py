"""Lógica do enrollment. Fatia 6a: criação a partir do lead pago (chamada pelo hook do lead).

O funil de coleta (perfil→endereço→RG→educação→selfie, 6b) e a liberação do coordenador (6c) entram
nas próximas etapas. Aqui só o nascimento da matrícula + a promoção da role.
"""

from __future__ import annotations

import structlog

from users.roles import interface as roles
from users.roles.enrollment.models import Enrollment

logger = structlog.get_logger()


def create_from_lead(*, user, promoter, hub) -> Enrollment:
    """Cria o Enrollment(STARTED) ligado ao HUB herdado + promove a role `lead→enrollment`. Idempotente.

    Chamado DENTRO da transação do hook de pagamento (lead pago). Se o enrollment já existe (webhook
    re-tentou), devolve o existente sem duplicar nem re-promover.
    """
    existing = Enrollment.objects.filter(user=user).first()
    if existing is not None:
        return existing

    enrollment = Enrollment.objects.create(
        user=user,
        promoter=promoter,
        hub=hub,
        status=Enrollment.Status.STARTED,
    )
    # role lead→enrollment (replace). Guarda idempotência: webhook re-tentado não re-promove.
    if "enrollment" not in roles.active_roles(user):
        roles.promote(user, "enrollment")

    logger.info(
        "enrollment.created_from_lead",
        external_id=str(enrollment.external_id),
        hub=str(hub.external_id),
    )
    return enrollment


def get_by_user(user) -> Enrollment | None:
    return (
        Enrollment.objects.filter(user=user).select_related("hub", "promoter").first()
    )


def get_by_external_id(external_id: str) -> Enrollment | None:
    return (
        Enrollment.objects.filter(external_id=external_id)
        .select_related("hub", "promoter", "user")
        .first()
    )
