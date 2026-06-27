"""Client Gemini — visão (descrever imagem) + geração de imagem, via REST (httpx, sem SDK).

API: generativelanguage.googleapis.com/v1beta — `POST /models/<model>:generateContent?key=...`.
Visão = manda a imagem inline (base64) + um prompt → texto. Imagem = prompt → bytes (inlineData).
Config (key/base_url/modelos) vem do .env via settings (CONVENTION §10). Zero regra de negócio (§8).
"""

from __future__ import annotations

import base64

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class GeminiError(Exception):
    """Erro ao falar com o Gemini."""


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
    ):
        self._api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self._base_url = (base_url or settings.GEMINI_BASE_URL).rstrip("/")
        self._vision_model = settings.GEMINI_VISION_MODEL
        self._image_model = settings.GEMINI_IMAGE_MODEL
        self._timeout = timeout

    async def _generate(self, model: str, body: dict) -> dict:
        url = f"{self._base_url}/models/{model}:generateContent?key={self._api_key}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0)) as c:
            resp = await c.post(url, json=body)
        if resp.status_code >= 400:
            raise GeminiError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def describe(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        prompt: str | None = None,
    ) -> str:
        """Descreve/analisa uma imagem (visão). Devolve o texto. Usado p/ validar selfie/documento/recibo."""
        instruction = (
            prompt or "Descreva esta imagem em portugues brasileiro de forma clara e objetiva."
        )
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": instruction},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(image_bytes).decode(),
                            }
                        },
                    ]
                }
            ]
        }
        data = await self._generate(self._vision_model, body)
        text = self._first_text(data)
        logger.info(
            "gemini.vision_done",
            model=self._vision_model,
            bytes=len(image_bytes),
            chars=len(text),
        )
        return text.strip()

    async def generate_image(self, prompt: str) -> tuple[bytes, str]:
        """Gera uma imagem a partir de um prompt. Devolve (bytes, mime_type)."""
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        data = await self._generate(self._image_model, body)
        for part in self._parts(data):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                raw = base64.b64decode(inline["data"])
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                logger.info(
                    "gemini.image_done",
                    model=self._image_model,
                    mime=mime,
                    size=len(raw),
                )
                return raw, mime
        raise GeminiError("Gemini não retornou imagem")

    @staticmethod
    def _parts(data: dict) -> list[dict]:
        candidates = data.get("candidates") or [{}]
        return (candidates[0].get("content") or {}).get("parts") or []

    def _first_text(self, data: dict) -> str:
        for part in self._parts(data):
            if part.get("text"):
                return part["text"]
        return ""
