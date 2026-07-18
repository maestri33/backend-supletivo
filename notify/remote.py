"""Cliente HTTP do notify-server — o caminho REMOTO do notify (Fase 2 do desmembramento).

Com NOTIFY_MODE=remote, `interface.send.send()` roteia pra cá: POST /v1/send no notify-server
(LAN/VPN) com o `external_id` GERADO PELO CLIENTE (decisão 6 do plano) — o caller recebe o handle
NA HORA e nunca bloqueia (§12). Falha de rede → enfileira retry no Django-Q com o MESMO payload
(mesmo external_id; o server é idempotente por external_id, então o retry não duplica envio).

O register usa `phone_check()` (substitui o client Evolution direto — decisão 6 do plano).

⚠️ Contrato conforme wiki/notify/servico-multi-tenant.md (tabela API v1). VALIDAR os nomes de
campo contra o notify-server REAL antes do corte de produção — o repo notify-server é a fonte.
"""

from __future__ import annotations

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


def is_remote() -> bool:
    """True quando o notify deve falar com o notify-server (NOTIFY_MODE=remote)."""
    return getattr(settings, "NOTIFY_MODE", "local") == "remote"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.NOTIFY_API_KEY}"}


def post_send(payload: dict) -> None:
    """POST /v1/send. Levanta em não-2xx/erro de rede (o caller decide: retry ou propagar)."""
    with httpx.Client(
        base_url=settings.NOTIFY_SERVER_URL,
        headers=_headers(),
        timeout=settings.NOTIFY_TIMEOUT,
    ) as client:
        resp = client.post("/v1/send", json=payload)
        resp.raise_for_status()


def send_with_retry(payload: dict) -> None:
    """Best-effort: tenta o POST; falhou → enfileira `retry_send` no Django-Q com o MESMO payload.

    O external_id já está no payload, então o retry entrega a MESMA notificação (server-side
    idempotente) e o caller nunca percebe a falha (§12).
    """
    try:
        post_send(payload)
    except Exception as exc:  # noqa: BLE001 — nunca quebra o caller; a fila garante a entrega
        logger.warning(
            "notify.remote_post_failed_queueing_retry",
            external_id=payload.get("external_id"),
            error=f"{type(exc).__name__}: {exc}",
        )
        from django_q.tasks import async_task

        async_task("notify.remote.retry_send", payload)


def retry_send(payload: dict) -> None:
    """Task do Django-Q: re-tenta o POST. Erro não tratado → o próprio Django-Q re-executa."""
    post_send(payload)
    logger.info("notify.remote_retry_sent", external_id=payload.get("external_id"))


def phone_check(phone: str) -> tuple[bool, str]:
    """POST /v1/phone/check → (existe_no_zap, número_resolvido). Levanta em erro (caller trata)."""
    with httpx.Client(
        base_url=settings.NOTIFY_SERVER_URL,
        headers=_headers(),
        timeout=settings.NOTIFY_TIMEOUT,
    ) as client:
        resp = client.post("/v1/phone/check", json={"phone": phone})
        resp.raise_for_status()
        data = resp.json()
    return bool(data.get("exists")), str(data.get("resolved") or phone)
