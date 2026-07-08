"""Wrapper CrewAI para o bot — feature-flag BOT_USE_CREW.
ponytail: default desligado; quando ligado, usa CrewAI em vez do motor determinístico.
"""
from __future__ import annotations

import structlog
from django.conf import settings

logger = structlog.get_logger()


def crew_available() -> bool:
    """True se o caminho CrewAI deve ser usado (config + crewai instalado)."""
    if not getattr(settings, "BOT_USE_CREW", False):
        return False
    try:
        import crewai  # noqa: F401
        return True
    except ImportError:
        logger.warning("bot.crew.unavailable", reason="crewai não instalado")
        return False


def send_to_crew(actor, reads, message: str, profile: dict | None = None) -> str:
    """Roda o CrewAI e devolve a resposta. Caller (worker.py) decide o que fazer com ela.

    actor: Actor instance (None se usuário não cadastrado).
    reads: módulo bot.reads (status dictionaries).
    message: texto do aluno.
    profile: dict com keys tipo do usuário (lead/enrollment/student/...).
    """
    from bot.crew_flow import build_crew

    policy = {
        "publico": (profile or {}).get("publico", "desconhecido"),
        "status": (profile or {}).get("status", "indefinido"),
        "text": message,
    }
    crew = build_crew(actor, reads, policy)
    try:
        result = crew.kickoff(inputs=policy)
        return str(result) if result else "..."
    except Exception as exc:
        logger.warning("bot.crew.failed", error=str(exc)[:200])
        return "Tive um problema pra processar agora. Pode repetir em alguns minutos?"