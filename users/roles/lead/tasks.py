"""Task Django-Q do lead: cria a cobrança no GATEWAY fora do request do register.

Auditoria front 2026-06-11 (item 6): o register responde <2s com o link curto próprio; o provider
(Asaas/InfinitePay) é resolvido aqui, com retry espaçado. Gateway fora do ar → o register continua
201 e o clique no link curto também tenta na hora (lazy — `checkout_links.checkout_redirect`).
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.utils import timezone

logger = structlog.get_logger()

_MAX_ATTEMPTS = 5
_RETRY_DELAY_S = 60


def build_checkout(checkout_pk: int, attempt: int = 1) -> str:
    """Preenche o Checkout no gateway (idempotente). Falhou → reagenda (até _MAX_ATTEMPTS, 60s entre
    tentativas); esgotou → loga e desiste (o lazy do link curto continua cobrindo)."""
    from users.roles.lead import service
    from users.roles.lead.models import Checkout

    checkout = Checkout.objects.select_related("lead__user").filter(pk=checkout_pk).first()
    if checkout is None:
        return "gone"
    if checkout.checkout_url:
        return "already_filled"

    try:
        service.fill_checkout_from_provider(checkout)
    except Exception as exc:  # noqa: BLE001 — gateway fora/instável: retry espaçado
        if attempt >= _MAX_ATTEMPTS:
            logger.error(
                "lead.checkout_build_exhausted",
                checkout=checkout_pk,
                attempts=attempt,
                error=str(exc),
            )
            return "exhausted"
        from django_q.models import Schedule
        from django_q.tasks import schedule

        schedule(
            "users.roles.lead.tasks.build_checkout",
            checkout_pk,
            attempt + 1,
            schedule_type=Schedule.ONCE,
            next_run=timezone.now() + timedelta(seconds=_RETRY_DELAY_S),
        )
        logger.warning(
            "lead.checkout_build_retry",
            checkout=checkout_pk,
            attempt=attempt,
            error=str(exc),
        )
        return f"retry_scheduled_{attempt}"
    return "ok"
