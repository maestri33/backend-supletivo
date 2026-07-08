"""View PÚBLICA do bot — o webhook inbound que a Evolution chama em cada mensagem recebida.

Espelha o `asaas/views.py`: `@csrf_exempt @require_POST`, auth por header-token comparado em tempo
constante (`security.check_access_token` vs `WHATSAPP_WEBHOOK_SECRET`), persiste o evento BRUTO
(idempotência por `wa_message_id`), enfileira o processamento em `transaction.on_commit` e responde
200 NA HORA (a Evolution re-tenta em não-200; o evento já está salvo antes do roteamento).
"""

import json

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from bot.models import InboundEvent
from bot.security import check_access_token
from core.net import source_ip as _source_ip

logger = structlog.get_logger()


@csrf_exempt
@require_POST
def webhook(request):
    """Receiver de mensagens do WhatsApp (PÚBLICO). Auth: x-webhook-token == WHATSAPP_WEBHOOK_SECRET.

    Token inválido/ausente → 401 (fail-closed). Autenticado → persiste o evento bruto (idempotente
    por wa_message_id), enfileira `handle_inbound` após o commit e responde 200 imediatamente.
    """
    if not check_access_token(request, settings.WHATSAPP_WEBHOOK_SECRET):
        return JsonResponse({"detail": "invalid_token"}, status=401)

    payload = _parse_json(request)
    event_name = str(payload.get("event") or "")
    wa_message_id = _wa_message_id(payload)

    # idempotência: se já temos esse wa_message_id, não recria nem reprocessa (a Evolution re-tenta).
    if wa_message_id:
        existing = InboundEvent.objects.filter(wa_message_id=wa_message_id).first()
        if existing is not None:
            logger.info("bot.webhook.idempotent_hit", wa_message_id=wa_message_id)
            return JsonResponse({"ok": True, "dedup": True})

    try:
        with transaction.atomic():
            event = InboundEvent.objects.create(
                wa_message_id=wa_message_id,
                event=event_name,
                payload=payload,
                source_ip=_source_ip(request),
            )
    except IntegrityError:
        # corrida no wa_message_id (unique): outra request criou primeiro — no-op idempotente.
        logger.info("bot.webhook.idempotent_race", wa_message_id=wa_message_id)
        return JsonResponse({"ok": True, "dedup": True})

    # enfileira só depois do commit (o worker não pode pegar a task antes da linha existir).
    transaction.on_commit(lambda: _enqueue(event.id))
    return JsonResponse({"ok": True})


def _enqueue(event_id: int) -> None:
    """Enfileira o processamento no Django-Q. Falha de enfileiramento só loga (o evento já está salvo
    e pode ser reprocessado); nunca derruba o webhook."""
    try:
        from django_q.tasks import async_task

        async_task("bot.worker.handle_inbound", event_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("bot.webhook.enqueue_failed", event=event_id, error=str(exc))


def _wa_message_id(payload):
    """Extrai key.id (id da mensagem no WhatsApp) do payload `messages.upsert`. None se não houver."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    key = data.get("key") or {}
    return key.get("id") if isinstance(key, dict) else None


def _parse_json(request):
    """Corpo JSON do request como dict (ou {} se vazio/malformado). Igual ao asaas."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
