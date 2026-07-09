"""Worker do bot (Django-Q): processa UMA mensagem inbound ponta a ponta.

Fluxo (defesa em profundidade, tudo fail-safe pro usuário — nunca erro cru, nunca silêncio total):

  parse → resolve telefone→Profile→roles → GUARDRAIL entrada (fail-closed) → carrega/cria Conversa
  + histórico → rate-limit (DB) → teto de orçamento → monta contexto → IA chat → GUARDRAIL saída
  (PII) → decide responder/escalar → notify.send → grava Message.

Garantias:
- Idempotência: a view já criou o InboundEvent com wa_message_id UNIQUE; aqui só processamos o que
  não foi processado.
- O LLM NUNCA recebe função de escrita — só texto (system+FAQ+fatos coarse+histórico). Separação de
  capacidade estrutural.
- Injeção detectada → escala (não chama IA). PII na saída → escala (não manda a saída). IA caída →
  canned + awaiting_human. Orçamento estourado → FAQ estática.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.utils import timezone

from bot import context as ctx
from bot import engine, faq, guardrail, ratelimit, router
from bot.actor import Actor
from bot.models import (
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    STATE_AWAITING_HUMAN,
    STATE_CLOSED,
    STATE_OPEN,
    Conversation,
    InboundEvent,
    Message,
)

logger = structlog.get_logger()

# resposta canned quando escalamos pra humano (IA caída, injeção, PII, ação pedida). Nunca silêncio.
_CANNED_ESCALATE = (
    "Recebi sua mensagem! Para te ajudar com isso, vou encaminhar para um de nossos "
    "atendentes, que retorna em breve. 🙏"
)

_HISTORY_LIMIT = 10  # últimas N mensagens no contexto (recorte de custo/janela)


# ── parse do payload da Evolution (messages.upsert) ────────────────────────
def _extract(payload: dict) -> tuple[str | None, str | None, str | None]:
    """Extrai (phone, text, wa_message_id) de um payload `messages.upsert` da Evolution.

    A Evolution aninha em `data` (ou manda o objeto direto). Texto pode vir como `conversation`
    (texto puro) ou `extendedTextMessage.text`. `key.fromMe=True` => mensagem NOSSA (eco) — ignora.
    Retorna (None, ...) quando não é uma mensagem de texto inbound utilizável.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None, None, None

    key = data.get("key") or {}
    if key.get("fromMe"):
        return None, None, None  # eco da nossa própria mensagem

    wa_message_id = key.get("id")
    remote_jid = key.get("remoteJid") or ""
    # JID de grupo termina em @g.us — atendimento é 1:1, ignora grupo.
    if remote_jid.endswith("@g.us"):
        return None, None, wa_message_id
    phone = remote_jid.split("@", 1)[0] if remote_jid else None

    message = data.get("message") or {}
    text = None
    if isinstance(message, dict):
        text = message.get("conversation")
        if not text:
            ext = message.get("extendedTextMessage") or {}
            text = ext.get("text") if isinstance(ext, dict) else None
    return phone, (text or "").strip() or None, wa_message_id


def _resolve_profile(phone: str):
    """Acha o Profile pelo telefone tentando as variantes BR (com/sem 9º dígito).

    A Evolution manda o número como registrado no WhatsApp; o Profile guarda a variante resolvida.
    Pode divergir no 9º dígito, então tentamos as variantes (mesma lógica do client) antes de
    desistir. None => estranho (sem cadastro).
    """
    from integrations.communication.whatsapp.client import _br_phone_variants
    from users.profiles import interface as profiles

    for candidate in [phone, *_br_phone_variants(phone)]:
        prof = profiles.find_by_phone(candidate)
        if prof is not None:
            return prof
    return None


def _send(*, text: str, phone: str, conversation: Conversation, ai_call=None) -> None:
    """Despacha a resposta pelo notify (WhatsApp) e grava o Message outbound."""
    from notify.interface.send import send

    send(text=text, caller=ratelimit.AI_CALLER, phone=phone, whatsapp=True)
    Message.objects.create(
        conversation=conversation,
        direction=DIRECTION_OUTBOUND,
        text=text,
        ai_call=ai_call,
    )


def _escalate(
    conversation: Conversation, phone: str, *, reason: str, notify: bool = True
) -> None:
    """Marca a conversa pra humano e (na 1ª vez) manda o canned. Re-escala não respamma."""
    first_time = conversation.state != STATE_AWAITING_HUMAN
    conversation.state = STATE_AWAITING_HUMAN
    if conversation.escalated_at is None:
        conversation.escalated_at = timezone.now()
    conversation.save(update_fields=["state", "escalated_at", "last_activity"])
    logger.info(
        "bot.escalated",
        conv=conversation.id,
        reason=reason,
        notified=first_time and notify,
    )
    if notify and first_time:
        _send(text=_CANNED_ESCALATE, phone=phone, conversation=conversation)


def handle_inbound(inbound_event_id: int) -> str:
    """Processa um InboundEvent. Retorna um código curto do desfecho (pra log/teste). NUNCA levanta
    pro Django-Q de forma que perca o evento — erros inesperados escalam pra humano."""
    event = InboundEvent.objects.filter(pk=inbound_event_id).first()
    if event is None:
        return "gone"
    if event.processed:
        return "already_processed"

    phone, text, _wa_id = _extract(event.payload)
    event.processed = True
    event.processed_at = timezone.now()
    event.save(update_fields=["processed", "processed_at"])

    if not phone or not text:
        logger.info("bot.skip_non_text", event=inbound_event_id)
        return "not_text_inbound"

    # resolve quem fala (cadastrado ou estranho) + roles
    profile = _resolve_profile(phone)
    user = getattr(profile, "user", None) if profile else None
    user_external_id = str(user.external_id) if user is not None else None
    roles_active: list[str] = []
    blocked = False
    if user is not None:
        from users.roles import interface as roles_iface

        roles_active = roles_iface.active_roles(user)
        blocked = roles_iface.is_blocked(user)
    policy = router.resolve(profile=profile, roles=roles_active, blocked=blocked)

    # carrega/cria conversa + grava a mensagem inbound (sempre, pra auditoria)
    conversation = (
        Conversation.objects.filter(phone=phone)
        .exclude(state=STATE_CLOSED)
        .order_by("-last_activity")
        .first()
    )
    if conversation is None:
        conversation = Conversation.objects.create(
            phone=phone, profile=profile, audience=policy.audience
        )
    else:
        # re-resolve público a cada msg (a role pode ter mudado) e religa profile se cadastrou agora.
        updates = []
        if conversation.audience != policy.audience:
            conversation.audience = policy.audience
            updates.append("audience")
        if profile is not None and conversation.profile_id != profile.id:
            conversation.profile = profile
            updates.append("profile")
        if updates:
            conversation.save(update_fields=updates)

    Message.objects.create(
        conversation=conversation,
        direction=DIRECTION_INBOUND,
        text=text,
        wa_message_id=_wa_id,
    )

    # já está com humano → registra e fica quieto (humano conduz; não respamma)
    if conversation.state == STATE_AWAITING_HUMAN:
        logger.info("bot.awaiting_human_silent", conv=conversation.id)
        return "awaiting_human"

    # usuário BLOQUEADO (role bloqueante ativa) → nunca a política normal do público: escala pra
    # humano direto, sem guardrail/rate-limit/engine/IA.
    if policy.audience == router.AUDIENCE_BLOCKED:
        _escalate(conversation, phone, reason="blocked_user")
        return "blocked_user"

    # GUARDRAIL entrada (fail-closed): injeção → escala, não chama IA
    scan = guardrail.scan_inbound(text)
    if not scan.safe:
        _escalate(conversation, phone, reason=f"inbound_guardrail:{scan.reason}")
        return "blocked_inbound"

    # rate-limit por telefone (DB). window=rajada → silêncio (resposta em voo cobre); hourly → estática
    allowed, rl_reason = ratelimit.check_and_record(phone)
    if not allowed:
        if rl_reason == "hourly":
            _send(
                text=faq.static_fallback(policy.audience),
                phone=phone,
                conversation=conversation,
            )
            return "rate_limited_hourly"
        logger.info("bot.rate_limited_window", conv=conversation.id)
        return "rate_limited_window"

    # teto diário de orçamento de IA → modo degradado (só FAQ estática, sem IA)
    if ratelimit.budget_exceeded():
        _send(
            text=faq.static_fallback(policy.audience),
            phone=phone,
            conversation=conversation,
        )
        logger.warning("bot.degraded_budget", conv=conversation.id)
        return "degraded_budget"

    # ── MOTOR DETERMINÍSTICO DA ETAPA (FASE 2) ───────────────────────────────
    # O bot age COMO O USUÁRIO (JWT interno, mesma superfície da API). O CÓDIGO decide a ação
    # canônica da etapa; a IA só conversa. Cadastrado → Actor (token emitido+validado pelo gate da
    # API); estranho → sem actor (engine vira no-op, segue na FAQ pública).
    actor = Actor.for_user(user) if user is not None else None

    decision = engine.run(actor, policy, text)

    # Escrita falhou na API → humano assume (NUNCA finge que fez).
    if decision.escalate:
        _escalate(conversation, phone, reason=f"engine:{decision.escalate}")
        return "engine_escalated"

    # Resposta DETERMINÍSTICA (ex.: confirmação de escrita): pula a IA — o desfecho é verdade que o
    # motor conhece; não deixamos a IA inventar "salvei"/"não salvei". Conta no rate-limit, não no
    # orçamento de IA (não houve AiCall).
    if decision.reply is not None:
        conversation.state = STATE_OPEN
        conversation.save(update_fields=["last_activity"])
        _send(text=decision.reply, phone=phone, conversation=conversation)
        return "engine_replied"

    # histórico (últimas N, ordem cronológica), sem a inbound atual já gravada
    history = list(
        conversation.messages.order_by("-created_at")[: _HISTORY_LIMIT + 1][::-1]
    )
    if (
        history
        and history[-1].direction == DIRECTION_INBOUND
        and history[-1].text == text
    ):
        history = history[:-1]

    messages = ctx.build_messages(
        policy=policy,
        user_external_id=user_external_id,
        history=history,
        user_text=text,
        engine_directive=decision.directive,
        engine_facts=decision.facts,
    )

    # IA chat — caída (cadeia esgotada) → canned + awaiting_human (fallback, nunca erro cru)
    from integrations.ai import service as ia
    from integrations.ai.client import LLMError

    before = timezone.now()
    try:
        answer = ia.chat(
            messages,
            caller=ratelimit.AI_CALLER,
            temperature=getattr(settings, "BOT_AI_TEMPERATURE", 0.3),
            max_tokens=getattr(settings, "BOT_AI_MAX_TOKENS", 500) or None,
        )
    except Exception as exc:  # noqa: BLE001 — IA fora → escala, nunca quebra pro usuário
        logger.warning("bot.ai_failed", conv=conversation.id, error=str(exc)[:160])
        _escalate(conversation, phone, reason="ai_unavailable")
        return "ai_failed"

    answer = (answer or "").strip()
    if not answer:
        _escalate(conversation, phone, reason="ai_empty")
        return "ai_empty"

    # GUARDRAIL saída (PII): a IA regurgitou dado sensível → NÃO manda; escala
    if guardrail.has_pii(answer):
        _escalate(conversation, phone, reason="outbound_pii")
        return "blocked_pii"

    # liga (best-effort) a resposta ao AiCall que a gerou — auditoria/custo
    ai_call = None
    try:
        from integrations.ai.models import AiCall

        ai_call = (
            AiCall.objects.filter(caller=ratelimit.AI_CALLER, created_at__gte=before)
            .order_by("-id")
            .first()
        )
    except Exception:  # noqa: BLE001 — link de auditoria nunca trava o envio
        ai_call = None

    conversation.state = STATE_OPEN
    conversation.save(update_fields=["last_activity"])
    _send(text=answer, phone=phone, conversation=conversation, ai_call=ai_call)
    return "answered"
