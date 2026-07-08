"""Client ElevenLabs — text-to-speech (TTS), via REST (httpx, sem SDK).

API: `POST https://api.elevenlabs.io/v1/text-to-speech/<voice_id>` (header `xi-api-key`) → bytes mp3.
Config (key/base_url/voz/modelo/voice_settings) vem do .env via settings (CONVENTION §10). Os
voice_settings (stability/similarity_boost/style/speaker_boost/speed) e a voz são sobrescrevíveis por
request. Zero regra de negócio (§8). Consumido pelo `notify` (áudio quando contato sem WhatsApp).
"""

from __future__ import annotations

import os

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class ElevenLabsError(Exception):
    """Erro ao falar com o ElevenLabs."""


class ElevenLabsClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
    ):
        self._api_key = api_key if api_key is not None else settings.ELEVENLABS_API_KEY
        self._base_url = (base_url or settings.ELEVENLABS_BASE_URL).rstrip("/")
        self._voice_id = settings.ELEVENLABS_VOICE_ID
        self._model_id = settings.ELEVENLABS_MODEL_ID
        self._output_format = settings.ELEVENLABS_OUTPUT_FORMAT
        self._timeout = timeout
        # Lane #7 (2026-07-08): ELEVENLABS_GATEWAY_MODE=1 (lido direto do ambiente, sem tocar
        # settings.py) liga o modo gateway — ELEVENLABS_BASE_URL aponta pro OmniRoute interno,
        # que fala /v1/audio/speech OpenAI-compatible (Authorization: Bearer) em vez do path
        # nativo /v1/text-to-speech/{voice} (xi-api-key). Flag OFF por default => nativo intacto.
        self._gateway_mode = os.environ.get(
            "ELEVENLABS_GATEWAY_MODE", ""
        ).strip().lower() in ("1", "true", "yes")

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self._api_key, "Content-Type": "application/json"}

    def _voice_settings(self, override: dict | None = None) -> dict:
        """Defaults do .env (stability/similarity/style/speaker_boost/speed); request pode sobrescrever."""
        vs = {
            "stability": settings.ELEVENLABS_STABILITY,
            "similarity_boost": settings.ELEVENLABS_SIMILARITY_BOOST,
            "style": settings.ELEVENLABS_STYLE,
            "use_speaker_boost": settings.ELEVENLABS_SPEAKER_BOOST,
            "speed": settings.ELEVENLABS_SPEED,
        }
        if override:
            vs.update(override)
        return vs

    async def tts(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
        output_format: str | None = None,
        voice_settings: dict | None = None,
    ) -> bytes:
        """Converte texto em fala. Devolve os bytes do áudio (mp3)."""
        voice = voice_id or self._voice_id
        if self._gateway_mode:
            return await self._tts_gateway(text, voice=voice, model_id=model_id)
        fmt = output_format or self._output_format
        url = f"{self._base_url}/v1/text-to-speech/{voice}?output_format={fmt}"
        body = {
            "text": text,
            "model_id": model_id or self._model_id,
            "voice_settings": self._voice_settings(voice_settings),
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body, headers=self._headers())
        if resp.status_code >= 400:
            raise ElevenLabsError(
                f"ElevenLabs HTTP {resp.status_code}: {resp.text[:300]}"
            )
        audio = resp.content
        logger.info(
            "elevenlabs.tts_done",
            voice=voice,
            model=body["model_id"],
            text_len=len(text),
            audio_kb=round(len(audio) / 1024, 1),
        )
        return audio

    async def _tts_gateway(
        self, text: str, *, voice: str, model_id: str | None = None
    ) -> bytes:
        """TTS via OmniRoute (`/v1/audio/speech`, OpenAI-compatible). Modelo exige prefixo
        `elevenlabs/`; auth `Authorization: Bearer` (não `xi-api-key`, que é só do path nativo)."""
        mdl = model_id or self._model_id
        if not mdl.startswith("elevenlabs/"):
            mdl = f"elevenlabs/{mdl}"
        body = {"model": mdl, "input": text, "voice": voice}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/v1/audio/speech"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body, headers=headers)
        if resp.status_code >= 400:
            raise ElevenLabsError(
                f"ElevenLabs (gateway) HTTP {resp.status_code}: {resp.text[:300]}"
            )
        audio = resp.content
        if not audio:
            raise ElevenLabsError("ElevenLabs (gateway) não retornou áudio")
        logger.info(
            "elevenlabs.tts_done",
            voice=voice,
            model=mdl,
            gateway=True,
            text_len=len(text),
            audio_kb=round(len(audio) / 1024, 1),
        )
        return audio
