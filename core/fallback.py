"""Fallback logger rastreável (CONVENTION §7.4 + pedido do Victor).

Quando um evento chega validado mas não há consumidor real ainda (o app destino — fees,
commissions etc. — não existe), em vez de descartar em silêncio: loga estruturado (structlog) e
grava um UnroutedEvent pra auditoria/reprocesso futuro.
"""

import structlog

from .models import UnroutedEvent

logger = structlog.get_logger()


def log_unrouted_event(source, event, reason, payload):
    """Loga + persiste um evento sem destino válido. Retorna o UnroutedEvent criado."""
    logger.warning(
        "unrouted_event",
        source=source,
        provider_event=event,
        reason=reason,
    )
    return UnroutedEvent.objects.create(
        source=source,
        event=event or "",
        reason=reason,
        payload=payload if isinstance(payload, dict) else {"_raw": payload},
    )
