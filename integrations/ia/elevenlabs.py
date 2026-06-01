"""Client ElevenLabs — text-to-speech (TTS), via REST (httpx, sem SDK).

API: `POST https://api.elevenlabs.io/v1/text-to-speech/<voice_id>` (header `xi-api-key`) → bytes mp3.
Config (key/base_url/voz/modelo) vem do .env via settings (CONVENTION §10). Zero regra de negócio (§8).
"""

from __future__ import annotations

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

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self._api_key, "Content-Type": "application/json"}

    async def tts(
        self, text: str, *, voice_id: str | None = None, model_id: str | None = None
    ) -> bytes:
        """Converte texto em fala. Devolve os bytes do áudio (mp3)."""
        voice = voice_id or self._voice_id
        url = f"{self._base_url}/v1/text-to-speech/{voice}?output_format={self._output_format}"
        body = {
            "text": text,
            "model_id": model_id or self._model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
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
            text_len=len(text),
            audio_kb=round(len(audio) / 1024, 1),
        )
        return audio

    async def list_voices(self) -> list[tuple[str, str]]:
        """GET /v1/voices — lista (voice_id, nome). Valida a key. §8."""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.get(f"{self._base_url}/v1/voices", headers=self._headers())
        if resp.status_code >= 400:
            raise ElevenLabsError(
                f"ElevenLabs /voices HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return [
            (v.get("voice_id", ""), v.get("name", ""))
            for v in resp.json().get("voices", [])
        ]
