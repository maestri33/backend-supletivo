"""Rate-limit por TELEFONE (DB, sem Redis) + teto diário de orçamento de IA. Porte do OTP.

`check_and_record(phone)`: janela curta (1 a cada `BOT_RATELIMIT_WINDOW_S`) + janela horária
(máx `BOT_RATELIMIT_HOURLY_MAX`/h), idêntico ao `OtpRateLimit`, mas chaveado por PHONE (o estranho
não tem User). Retorna `(allowed, reason)` — nunca levanta (o worker decide degradar, não erra pro
usuário). Chave por phone porque o atendimento atende cadastrado E estranho.

`budget_exceeded()`: soma os `AiCall` do DIA (qualquer caller do bot) contra `BOT_DAILY_AI_CAP`.
Estourou => o worker entra em modo degradado (só FAQ estática), sem chamar a IA. Defaults
conservadores no settings.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bot.models import BotRateLimit

logger = structlog.get_logger()

# caller usado em TODA chamada de IA do bot — o teto diário soma por este prefixo.
AI_CALLER = "bot_atendimento"


def check_and_record(phone: str) -> tuple[bool, str]:
    """Janela curta + janela horária por telefone. Retorna (allowed, reason). NÃO levanta.

    Espelha `otp.service._check_and_record_rate_limit`, mas devolve em vez de levantar: o bot
    prefere degradar (responder devagar/encaminhar) a estourar erro pro usuário no WhatsApp.
    """
    now = timezone.now()
    window_s = settings.BOT_RATELIMIT_WINDOW_S
    hourly_max = settings.BOT_RATELIMIT_HOURLY_MAX

    with transaction.atomic():
        rl = BotRateLimit.objects.select_for_update().filter(phone=phone).first()
        if rl is None:
            BotRateLimit.objects.create(
                phone=phone,
                last_seen_at=now,
                hourly_count=1,
                hourly_window_start=now,
            )
            return True, ""

        elapsed = (now - rl.last_seen_at).total_seconds()
        if elapsed < window_s:
            logger.info("bot.rate_limit.window_blocked", phone_tail=phone[-4:])
            return False, "window"

        hourly_elapsed = (now - rl.hourly_window_start).total_seconds()
        if hourly_elapsed < 3600:
            if rl.hourly_count >= hourly_max:
                logger.info(
                    "bot.rate_limit.hourly_blocked",
                    phone_tail=phone[-4:],
                    count=rl.hourly_count,
                )
                # ainda marca o last_seen pra não reprocessar em rajada, mas sinaliza bloqueio.
                rl.last_seen_at = now
                rl.save(update_fields=["last_seen_at"])
                return False, "hourly"
            rl.hourly_count += 1
        else:
            rl.hourly_count = 1
            rl.hourly_window_start = now
        rl.last_seen_at = now
        rl.save(update_fields=["last_seen_at", "hourly_count", "hourly_window_start"])
        return True, ""


def budget_exceeded() -> bool:
    """True se as chamadas de IA do bot HOJE já bateram `BOT_DAILY_AI_CAP` (modo degradado).

    Conta `AiCall` do dia com `caller=AI_CALLER` (a marca de toda chamada do bot). Cap <= 0
    desliga o teto (sem limite). Erro de DB aqui NÃO trava — assume não-estourado e loga (o
    rate-limit por telefone já protege custo no pior caso).
    """
    cap = getattr(settings, "BOT_DAILY_AI_CAP", 0)
    if cap <= 0:
        return False
    try:
        from integrations.ai.models import AiCall

        start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        used = AiCall.objects.filter(
            caller=AI_CALLER, created_at__gte=start_of_day
        ).count()
        if used >= cap:
            logger.warning("bot.budget.exceeded", used=used, cap=cap)
            return True
        return False
    except Exception as exc:  # noqa: BLE001 — contagem nunca trava o atendimento
        logger.warning("bot.budget.check_failed", error=str(exc)[:160])
        return False
