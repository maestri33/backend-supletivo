"""Cliente para Evolution API 2.3.7 (WhatsApp) — porte do micro legado (notify/whats).

API alvo: settings.WHATSAPP_API_BASE_URL. Auth: header `apikey`
(settings.WHATSAPP_GLOBAL_API_KEY). Instância default em settings.WHATSAPP_INSTANCE_NAME,
sobreponível no construtor (ex.: "ieadpg").

Regras (CONVENTION §8/§10):
 - base_url/api-key/instance vêm do .env via settings. Zero regra de negócio aqui.
 - httpx puro (sem retry): qualquer não-2xx vira WhatsAppError; quem chama (notify, async) decide.
 - resolve_br_number() resolve a variante BR com/sem o 9º dígito (evita silent-fail da Evolution).

Endpoints: health · check_numbers/get_jid · resolve_br_number · fetch_profile ·
fetch_business_profile · reject_call · send_text · send_media · send_whatsapp_audio ·
send_sticker · send_location · send_contact · send_poll · send_buttons · send_reaction · send_status.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()

MEDIA_TYPES = {"image", "video", "audio", "document"}

# ── Cache de resolução de JID BR (nono dígito) ─────────────────────────────
# Mapeia phone-original -> (resolved_number, monotonic_ts). TTL 1h. Evita pagar 1 HTTP extra a
# cada send pro mesmo contato.
_BR_JID_TTL_S = 3600
_br_jid_cache: dict[str, tuple[str | None, float]] = {}


def _br_phone_variants(phone: str) -> list[str]:
    """Para mobile BR, gera as duas variantes (com 9 / sem 9).

    Mobile BR moderno: `55` + DDD(2) + `9` + 8 dígitos = 13 dígitos. Legado: `55` + DDD(2) +
    8 dígitos = 12. Alguns números só estão registrados no WhatsApp em UMA das formas, o que faz
    o `formatJid` automático da Evolution errar a normalização. Para não-BR/non-mobile, retorna
    apenas [phone].
    """
    digits = "".join(c for c in phone if c.isdigit())
    if not digits.startswith("55") or len(digits) not in (12, 13):
        return [phone]
    country, ddd, rest = digits[:2], digits[2:4], digits[4:]
    if len(rest) == 9 and rest.startswith("9"):
        return [country + ddd + rest, country + ddd + rest[1:]]  # com 9, sem 9
    if len(rest) == 8:
        return [country + ddd + "9" + rest, country + ddd + rest]  # com 9, sem 9
    return [phone]


class WhatsAppError(Exception):
    """Evolution API respondeu não-2xx. Quem chama decide o que fazer."""

    def __init__(self, status_code: int, body: Any, message: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(message or f"WhatsApp API {status_code}: {body!r}")


class WhatsAppClient:
    """Cliente de alto nível para a Evolution API v2 (WhatsApp)."""

    def __init__(self, *, instance: str | None = None, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.WHATSAPP_API_BASE_URL,
            headers={"apikey": settings.WHATSAPP_GLOBAL_API_KEY},
            timeout=timeout,
        )
        self._instance = instance or settings.WHATSAPP_INSTANCE_NAME

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self.aclose()

    # ---------- helpers ----------
    def _msg_path(self, endpoint: str) -> str:
        """POST /message/<endpoint>/<instance>"""
        return f"/message/{endpoint}/{self._instance}"

    def _chat_path(self, endpoint: str) -> str:
        """POST /chat/<endpoint>/<instance>"""
        return f"/chat/{endpoint}/{self._instance}"

    async def _post(
        self, path: str, json: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = httpx.Timeout(timeout, connect=5.0)
        resp = await self._client.post(path, json=json, **kwargs)
        if resp.status_code >= 400:
            raise WhatsAppError(resp.status_code, resp.text)
        return resp.json()

    async def _get(self, path: str) -> Any:
        resp = await self._client.get(path)
        if resp.status_code >= 400:
            raise WhatsAppError(resp.status_code, resp.text)
        return resp.json()

    def _build_quoted(
        self, message_id: str | None, participant: str | None = None
    ) -> dict[str, str] | None:
        """Monta o objeto quoted (reply) se houver message_id."""
        if not message_id:
            return None
        quoted: dict[str, str] = {"messageId": message_id}
        if participant:
            quoted["participant"] = participant
        return quoted

    # ---------- health ----------
    async def health(self) -> Any:
        """Status global da Evolution. v2.3.7 não tem /instance/status — usa fetchInstances."""
        return await self._get("/instance/fetchInstances")

    # ---------- chat / user ----------
    async def check_numbers(self, numbers: list[str]) -> list[dict[str, Any]]:
        """Verifica se números possuem WhatsApp. POST /chat/whatsappNumbers/{instance}.

        numbers: formato DDI+DDD+número (ex.: "5543996648750"). Resposta: lista de
        {jid, exists, number, name}.
        """
        result = await self._post(self._chat_path("whatsappNumbers"), {"numbers": numbers})
        logger.info("whatsapp.check", count=len(numbers))
        return result

    async def get_jid(self, number: str) -> str | None:
        """JID de um número (ou None se não tem WhatsApp). Usa check_numbers."""
        result = await self.check_numbers([number])
        if not result or not result[0].get("exists"):
            logger.info("whatsapp.jid_not_found", number=number)
            return None
        jid = result[0].get("jid")
        logger.info("whatsapp.jid_resolved", number=number, jid=jid)
        return jid

    async def resolve_br_number(self, phone: str) -> str:
        """Resolve qual variante BR (com/sem 9º dígito) está no WhatsApp.

        Retorna o `number` efetivamente registrado, ou o `phone` original como fallback. Cache em
        memória (TTL 1h) por `phone`. Pré-resolver evita silent-fail (Evolution responde 201 sem
        entregar quando o número só existe na outra variante).
        """
        cached = _br_jid_cache.get(phone)
        if cached is not None:
            value, ts = cached
            if time.monotonic() - ts < _BR_JID_TTL_S:
                return value or phone
            del _br_jid_cache[phone]

        variants = _br_phone_variants(phone)
        if len(variants) == 1:
            return phone  # não é BR mobile — sem variantes a testar.

        try:
            result = await self.check_numbers(variants)
        except Exception as exc:
            logger.warning(
                "whatsapp.resolve_br.check_failed",
                phone=phone,
                error=f"{type(exc).__name__}: {exc!r}",
            )
            return phone  # fallback: tenta com o original

        chosen: str | None = None
        for item in result or []:
            if item.get("exists"):
                chosen = item.get("number") or item.get("jid", "").split("@")[0]
                break

        _br_jid_cache[phone] = (chosen, time.monotonic())

        if chosen is None:
            logger.warning("whatsapp.resolve_br.none_exists", phone=phone, tried=variants)
            return phone  # fallback
        if chosen != phone:
            logger.info("whatsapp.resolve_br.normalized", phone_original=phone, phone_resolved=chosen)
        return chosen

    async def fetch_profile(self, number: str) -> dict[str, Any]:
        """Perfil de um usuário (foto, nome, status). POST /chat/fetchProfile/{instance}."""
        result = await self._post(self._chat_path("fetchProfile"), {"number": number})
        logger.info("whatsapp.profile_fetched", number=number, has_picture=bool(result.get("picture")))
        return result

    async def fetch_business_profile(self, number: str) -> dict[str, Any]:
        """Perfil comercial (WhatsApp Business). POST /chat/fetchBusinessProfile/{instance}."""
        result = await self._post(self._chat_path("fetchBusinessProfile"), {"number": number})
        logger.info("whatsapp.business_profile_fetched", number=number, is_business=result.get("isBusiness", False))
        return result

    # ---------- call ----------
    async def reject_call(self, call_id: str, call_creator: str) -> dict[str, Any]:
        """Rejeita uma chamada entrante. POST /call/reject/{instance}.

        call_id: ID recebido via webhook. call_creator: JID do originador.
        """
        result = await self._post(
            f"/call/reject/{self._instance}",
            {"callId": call_id, "callCreator": call_creator},
        )
        logger.info("whatsapp.call_rejected", call_id=call_id, creator=call_creator)
        return result

    # ---------- send text ----------
    async def send_text(
        self,
        number: str,
        text: str,
        *,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
        mention_all: bool = False,
        mentioned_jid: list[str] | None = None,
        format_jid: bool | None = None,
    ) -> dict[str, Any]:
        """Envia mensagem de texto. POST /message/sendText/{instance}.

        delay: ms de "digitando...". quoted_*: reply. mention_all/mentioned_jid: menções (grupos).
        format_jid=False pula a validação/formatação do número.
        """
        payload: dict[str, Any] = {"number": number, "text": text}
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted
        if mention_all:
            payload["mentionAll"] = True
        if mentioned_jid:
            payload["mentionedJid"] = mentioned_jid
        if format_jid is not None:
            payload["formatJid"] = format_jid

        result = await self._post(self._msg_path("sendText"), payload)
        logger.info("whatsapp.text_sent", number=number, text_preview=text[:50])
        return result

    # ---------- send media ----------
    async def send_media(
        self,
        number: str,
        media_url: str,
        media_type: str,
        *,
        caption: str | None = None,
        filename: str | None = None,
        mimetype: str | None = None,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
        mention_all: bool = False,
        mentioned_jid: list[str] | None = None,
        format_jid: bool | None = None,
    ) -> dict[str, Any]:
        """Envia mídia. POST /message/sendMedia/{instance}.

        media_type ∈ {image, video, audio, document}. media_url: URL pública ou base64 PURO
        (sem prefixo). filename obrigatório p/ document. caption: legenda (image/video/document).
        """
        if media_type not in MEDIA_TYPES:
            raise WhatsAppError(0, media_type, f"media_type inválido: {media_type}. Use: {', '.join(sorted(MEDIA_TYPES))}")

        payload: dict[str, Any] = {"number": number, "mediatype": media_type, "media": media_url}
        if caption:
            payload["caption"] = caption
        if filename:
            payload["fileName"] = filename
        if mimetype:
            payload["mimetype"] = mimetype
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted
        if mention_all:
            payload["mentionAll"] = True
        if mentioned_jid:
            payload["mentionedJid"] = mentioned_jid
        if format_jid is not None:
            payload["formatJid"] = format_jid

        result = await self._post(self._msg_path("sendMedia"), payload)
        logger.info("whatsapp.media_sent", number=number, type=media_type, url=media_url[:80])
        return result

    # ---------- send whatsapp audio (nota de voz nativa / PTT) ----------
    async def send_whatsapp_audio(
        self,
        number: str,
        audio_url: str,
        *,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
    ) -> dict[str, Any]:
        """Áudio como nota de voz nativa (PTT). POST /message/sendWhatsAppAudio/{instance}.

        audio_url: URL pública (mp3/wav/ogg...). Força UI de áudio (waveform), diferente do
        send_media(mediatype="audio").
        """
        payload: dict[str, Any] = {"number": number, "audio": audio_url}
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted

        result = await self._post(self._msg_path("sendWhatsAppAudio"), payload, timeout=60.0)
        logger.info("whatsapp.audio_sent", number=number, url=audio_url[:80])
        return result

    # ---------- send sticker ----------
    async def send_sticker(
        self,
        number: str,
        sticker_url: str,
        *,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
    ) -> dict[str, Any]:
        """Sticker (WebP). POST /message/sendSticker/{instance}. sticker_url: URL ou base64 PURO."""
        payload: dict[str, Any] = {"number": number, "sticker": sticker_url}
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted

        result = await self._post(self._msg_path("sendSticker"), payload)
        logger.info("whatsapp.sticker_sent", number=number, url=sticker_url[:80])
        return result

    # ---------- send location ----------
    async def send_location(
        self,
        number: str,
        latitude: float,
        longitude: float,
        *,
        name: str | None = None,
        address: str | None = None,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
    ) -> dict[str, Any]:
        """Localização (pin). POST /message/sendLocation/{instance}."""
        payload: dict[str, Any] = {"number": number, "latitude": latitude, "longitude": longitude}
        if name:
            payload["name"] = name
        if address:
            payload["address"] = address
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted

        result = await self._post(self._msg_path("sendLocation"), payload)
        logger.info("whatsapp.location_sent", number=number, lat=latitude, lon=longitude)
        return result

    # ---------- send contact (vCard) ----------
    async def send_contact(
        self,
        number: str,
        contacts: list[dict[str, str]],
        *,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
    ) -> dict[str, Any]:
        """Um ou mais contatos (vCard). POST /message/sendContact/{instance}.

        Cada contato: fullName + phoneNumber (obrigatórios); organization/email opcionais.
        """
        payload: dict[str, Any] = {"number": number, "contact": contacts}
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted

        result = await self._post(self._msg_path("sendContact"), payload)
        logger.info("whatsapp.contact_sent", number=number, contact_count=len(contacts))
        return result

    # ---------- send poll ----------
    async def send_poll(
        self,
        number: str,
        name: str,
        values: list[str],
        *,
        selectable_count: int = 1,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
    ) -> dict[str, Any]:
        """Enquete interativa. POST /message/sendPoll/{instance}. values: até 12 opções."""
        payload: dict[str, Any] = {
            "number": number,
            "name": name,
            "selectableCount": selectable_count,
            "values": values,
        }
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted

        result = await self._post(self._msg_path("sendPoll"), payload)
        logger.info("whatsapp.poll_sent", number=number, name=name, options=len(values))
        return result

    # ---------- send buttons ----------
    async def send_buttons(
        self,
        number: str,
        title: str,
        buttons: list[dict[str, Any]],
        *,
        description: str | None = None,
        footer: str | None = None,
        thumbnail_url: str | None = None,
        delay: int | None = None,
        quoted_msg_id: str | None = None,
        quoted_participant: str | None = None,
    ) -> dict[str, Any]:
        """Botões interativos (máx 3). POST /message/sendButtons/{instance}.

        Cada botão: type ∈ {reply, url, copy} + displayText; reply→id, url→url, copy→copyText.
        """
        payload: dict[str, Any] = {"number": number, "title": title, "buttons": buttons}
        if description:
            payload["description"] = description
        if footer:
            payload["footer"] = footer
        if thumbnail_url:
            payload["thumbnailUrl"] = thumbnail_url
        if delay is not None:
            payload["delay"] = delay
        if quoted := self._build_quoted(quoted_msg_id, quoted_participant):
            payload["quoted"] = quoted

        result = await self._post(self._msg_path("sendButtons"), payload)
        logger.info("whatsapp.buttons_sent", number=number, title=title, button_count=len(buttons))
        return result

    # ---------- send reaction ----------
    async def send_reaction(
        self,
        number: str,
        key: dict[str, Any],
        reaction: str,
        *,
        delay: int | None = None,
    ) -> dict[str, Any]:
        """Reação (emoji) a uma mensagem. POST /message/sendReaction/{instance}.

        key: {remoteJid, id, fromMe}. reaction: emoji (string vazia remove).
        """
        payload: dict[str, Any] = {"number": number, "key": key, "reaction": reaction}
        if delay is not None:
            payload["delay"] = delay

        result = await self._post(self._msg_path("sendReaction"), payload)
        logger.info("whatsapp.reaction_sent", number=number, reaction=reaction)
        return result

    # ---------- send status (story) ----------
    async def send_status(
        self,
        number: str,
        status_type: str,
        content: str,
        *,
        status_jid_list: list[str] | None = None,
        all_contacts: bool = False,
        background_color: str | None = None,
        font: int | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Publica status (story). POST /message/sendStatus/{instance}.

        status_type ∈ {text, image}. content: texto ou URL. background_color/font p/ texto;
        caption p/ imagem. status_jid_list/all_contacts: audiência.
        """
        payload: dict[str, Any] = {"number": number, "type": status_type, "content": content}
        if status_jid_list is not None:
            payload["statusJidList"] = status_jid_list
        if all_contacts:
            payload["allContacts"] = True
        if background_color:
            payload["backgroundColor"] = background_color
        if font is not None:
            payload["font"] = font
        if caption:
            payload["caption"] = caption

        result = await self._post(self._msg_path("sendStatus"), payload)
        logger.info("whatsapp.status_sent", number=number, type=status_type)
        return result


def get_client(*, instance: str | None = None) -> WhatsAppClient:
    """Constrói o client com base_url/api-key/instance do .env (config via settings — §10)."""
    return WhatsAppClient(instance=instance)
