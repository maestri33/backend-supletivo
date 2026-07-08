"""Helper de fallback IA — OmniRoute primário, MiniMax direto como fallback.
ponytail: garante que o caminho de áudio/visão não dependa de gateway só — se OmniRoute cair,
cai direto pro MiniMax (com a chave própria). Não há cascata de 3+ níveis.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


async def try_gateway_or_direct(*, gateway_call, direct_call, caller: str, op: str):
    """Tenta o OmniRoute primeiro (gateway unificado). Se falhar retryable, tenta MiniMax direto.

    gateway_call: corotina async() que fala com OmniRoute.
    direct_call: corotina async() que fala com MiniMax API direto (com MINIMAX_DIRECT_*).
    Retorna o resultado da primeira que succeed.
    """
    try:
        result = await gateway_call()
        logger.debug("ai.gateway_ok", op=op, caller=caller)
        return result
    except Exception as exc:
        logger.warning(
            "ai.gateway_failed_fallback_direct",
            op=op,
            caller=caller,
            error=str(exc)[:160],
        )
        return await direct_call()