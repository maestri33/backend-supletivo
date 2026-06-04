"""Registry mínimo de hooks in-process (CONVENTION §7.3).

O webhook de um app de `integrations/` valida o evento, mexe só no próprio estado e então
**dispara o hook do app destino** — sem importar o app consumidor (desacoplado). Aqui mora a
engrenagem: o consumidor (ex.: `users/roles/lead`) registra um handler por NOME de evento no boot
(AppConfig.ready()); o webhook chama `dispatch(evento, **kw)`.

Regra §7.4: o que ninguém consome NÃO some em silêncio — o webhook mantém o `log_unrouted_event`
(fallback rastreável) quando `dispatch` retorna `False` (nenhum handler consumiu).
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

logger = structlog.get_logger()

_HOOKS: dict[str, list[Callable]] = {}


def register(event: str, handler: Callable) -> None:
    """Registra um handler para um evento (idempotente: não duplica o mesmo handler)."""
    handlers = _HOOKS.setdefault(event, [])
    if handler not in handlers:
        handlers.append(handler)


def dispatch(event: str, **kwargs) -> bool:
    """Chama os handlers do evento. Retorna True se ALGUM consumiu (handler retornou truthy).

    Exceção de handler é logada e NÃO propaga — um consumidor com bug não pode derrubar o webhook
    (o Asaas/InfinitePay re-tentaria à toa). Quem precisa de atomicidade abre a transação dentro do
    próprio handler.
    """
    consumed = False
    for handler in _HOOKS.get(event, ()):
        try:
            if handler(**kwargs):
                consumed = True
        except Exception as exc:  # noqa: BLE001 — isola o webhook de bug do consumidor
            logger.error(
                "hook_failed",
                event=event,
                handler=getattr(handler, "__name__", repr(handler)),
                error=str(exc),
            )
    return consumed


def registered_events() -> tuple[str, ...]:
    """Eventos com pelo menos um handler (introspecção/testes)."""
    return tuple(_HOOKS.keys())
