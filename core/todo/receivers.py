"""Receiver do signal `enrollment_ready_for_matricula` → tenta o bot matriculador (mock).

Hoje o bot levanta `BotNotImplemented`; o receiver registra a métrica e retorna SEM efeito
colateral (atômico: nenhum estado tocado) — o `_notify_coordinator_awaiting` do enrollment é o
fallback que avisa o coordenador. Quando o bot real existir, é aqui que ele orquestra a
matrícula automática (e, no futuro, suprime o notify de fallback em caso de sucesso).
"""

from __future__ import annotations

import structlog
from django.dispatch import receiver

from core.todo.bot import BotNotImplemented, run_bot_matriculador
from users.roles.enrollment.signals import enrollment_ready_for_matricula

logger = structlog.get_logger()


@receiver(enrollment_ready_for_matricula)
def try_bot_matriculador(sender, enrollment, **kwargs):
    """Best-effort: o bot NUNCA quebra o fluxo do enrollment (§12). Mock → métrica + retorna."""
    ext = str(getattr(enrollment, "external_id", ""))
    try:
        run_bot_matriculador(enrollment)
    except BotNotImplemented:
        logger.info("todo.bot_matriculador.unimplemented", enrollment=ext)
    except Exception as exc:  # noqa: BLE001 — bot nunca derruba o enrollment
        logger.warning("todo.bot_matriculador.failed", enrollment=ext, error=str(exc))
