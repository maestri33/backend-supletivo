"""Client MiniMax — TTS (t2a_v2) + visão (descrever imagem com MiniMax-M3), via REST (httpx, sem SDK).

API: base `https://api.minimax.io`, auth `Authorization: Bearer <key>`.
- TTS:    `POST /v1/t2a_v2` → corpo `{model, text, voice_setting, audio_setting}`; o áudio volta em
          `data.audio` como string **hexadecimal** (decodificar com `bytes.fromhex`).
- Visão:  `POST /v1/chat/completions` (OpenAI-compatible) com `MiniMax-M3` + a imagem inline
          (data-URL base64) + `thinking: disabled` (mata o bloco <think> do raciocínio) → texto.

Config (key/base_url/modelos/vozes) vem do .env via settings (CONVENTION §10). Zero regra de
negócio (§8): só fala com o provider e devolve o resultado cru. Consumido pelo `service.py` (mídia).
"""

from __future__ import annotations

import base64
import os

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class MiniMaxError(Exception):
    """Erro ao falar com o MiniMax (TTS ou visão)."""


class MiniMaxClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        direct: bool = False,
    ):
        # ponytail: se direct=True, fala DIRETO com MiniMax (sem gateway).
        # Usado pelo fallback quando OmniRoute cai.
        if direct and getattr(settings, "MINIMAX_DIRECT_API_KEY", ""):
            self._api_key = api_key or settings.MINIMAX_DIRECT_API_KEY
            self._base_url = (
                base_url
                or getattr(
                    settings, "MINIMAX_DIRECT_BASE_URL", "https://api.minimax.io"
                )
            ).rstrip("/")
            self._gateway_mode = False  # direto, sem gateway
        else:
            self._api_key = api_key if api_key is not None else settings.MINIMAX_API_KEY
            self._base_url = (base_url or settings.MINIMAX_BASE_URL).rstrip("/")
            # Lane #7 (2026-07-08): MINIMAX_GATEWAY_MODE=1 liga o modo gateway — fala o
            # /v1/audio/speech OpenAI-compatible via OmniRoute. Default OFF = API nativa.
            self._gateway_mode = os.environ.get(
                "MINIMAX_GATEWAY_MODE", ""
            ).strip().lower() in (
                "1",
                "true",
                "yes",
            )
        self._tts_model = settings.MINIMAX_TTS_MODEL
        self._vision_model = settings.MINIMAX_VISION_MODEL
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        api_key = str(self._api_key or "").strip()
        if not api_key:
            raise MiniMaxError("MiniMax API key não configurada.")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def tts(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model: str | None = None,
        output_format: str = "mp3",
    ) -> bytes:
        """Converte texto em fala (t2a_v2). Devolve os bytes do áudio (mp3)."""
        if self._gateway_mode:
            return await self._tts_gateway(text, voice_id=voice_id, model=model)
        url = f"{self._base_url}/v1/t2a_v2"
        body = {
            "model": model or self._tts_model,
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice_id or settings.MINIMAX_VOICE_FEMALE,
                "speed": 1,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": output_format,
                "channel": 1,
            },
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body, headers=self._headers())
        if resp.status_code >= 400:
            raise MiniMaxError(
                f"MiniMax TTS HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        base = data.get("base_resp") or {}
        if base.get("status_code") not in (0, None):
            raise MiniMaxError(
                f"MiniMax TTS status {base.get('status_code')}: {base.get('status_msg')}"
            )
        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            raise MiniMaxError("MiniMax TTS não retornou áudio")
        audio = bytes.fromhex(audio_hex)
        logger.info(
            "minimax.tts_done",
            model=body["model"],
            voice=body["voice_setting"]["voice_id"],
            text_len=len(text),
            audio_kb=round(len(audio) / 1024, 1),
        )
        return audio

    async def _tts_gateway(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model: str | None = None,
    ) -> bytes:
        """TTS via OmniRoute (`/v1/audio/speech`, OpenAI-compatible). Modelo exige prefixo
        `minimax/`; resposta é o áudio cru (sem hex, diferente do t2a_v2 nativo)."""
        mdl = model or self._tts_model
        if not mdl.startswith("minimax/"):
            mdl = f"minimax/{mdl}"
        body = {
            "model": mdl,
            "input": text,
            "voice": voice_id or settings.MINIMAX_VOICE_FEMALE,
        }
        url = f"{self._base_url}/v1/audio/speech"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body, headers=self._headers())
        if resp.status_code >= 400:
            raise MiniMaxError(
                f"MiniMax TTS (gateway) HTTP {resp.status_code}: {resp.text[:300]}"
            )
        audio = resp.content
        if not audio:
            raise MiniMaxError("MiniMax TTS (gateway) não retornou áudio")
        logger.info(
            "minimax.tts_done",
            model=mdl,
            voice=body["voice"],
            gateway=True,
            text_len=len(text),
            audio_kb=round(len(audio) / 1024, 1),
        )
        return audio

    async def describe(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        prompt: str | None = None,
    ) -> str:
        """Descreve/analisa uma imagem com MiniMax-M3 (visão). Devolve o texto, sem o bloco <think>."""
        instruction = (
            prompt
            or "Descreva esta imagem em portugues brasileiro de forma clara e objetiva."
        )
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
        body = {
            "model": self._vision_model,
            "thinking": {"type": "disabled"},  # sem o bloco <think> de raciocínio
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_completion_tokens": 800,
        }
        url = f"{self._base_url}/v1/chat/completions"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body, headers=self._headers())
        if resp.status_code >= 400:
            raise MiniMaxError(
                f"MiniMax visão HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            base = data.get("base_resp") or {}
            raise MiniMaxError(
                f"MiniMax visão sem resposta (status {base.get('status_code')}: "
                f"{base.get('status_msg')})"
            )
        text = (choices[0].get("message") or {}).get("content") or ""
        logger.info(
            "minimax.vision_done",
            model=self._vision_model,
            bytes=len(image_bytes),
            chars=len(text),
        )
        return text.strip()
