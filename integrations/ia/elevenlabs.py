"""Client ElevenLabs — text-to-speech (TTS), via REST (httpx, sem SDK).

API: `POST https://api.elevenlabs.io/v1/text-to-speech/<voice_id>` (header `xi-api-key`) → bytes mp3.
Config (key/base_url/voz/modelo/voice_settings) vem do .env via settings (CONVENTION §10). Os
voice_settings (stability/similarity_boost/style/speaker_boost/speed) e a voz são sobrescrevíveis por
request. Zero regra de negócio (§8). Consumido pelo `notify` (áudio quando contato sem WhatsApp).
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
