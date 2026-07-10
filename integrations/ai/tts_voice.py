"""TTS voice resolution — mapeamento centralizado de vozes (cross-gender marketing).
ponytail: service.py:432-460 já tem a lógica inline; aqui centraliza + adiciona fallback MiniMax.
"""

from __future__ import annotations

from django.conf import settings


def resolve_voice(gender: str | None, provider: str = "elevenlabs") -> str:
    """Resolve a voz pelo GÊNERO DO DESTINATÁRIO (M→feminina, F→masculina, regra de marketing).

    provider = "elevenlabs" (primário) ou "minimax" (fallback). Sem gender → voz default feminina.
    """
    g = (gender or "").strip().upper()
    is_male = g == "F"  # destinatário mulher recebe voz masculina
    is_female = g == "M"  # destinatário homem recebe voz feminina

    if provider == "minimax":
        if is_male:
            return settings.MINIMAX_VOICE_MALE
        return settings.MINIMAX_VOICE_FEMALE  # default + female

    # elevenlabs (primary)
    if is_male:
        return settings.ELEVENLABS_VOICE_MALE
    if is_female:
        return settings.ELEVENLABS_VOICE_FEMALE
    return settings.ELEVENLABS_VOICE_FEMALE  # default
