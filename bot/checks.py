"""System check do app bot — avisa no boot quando falta o segredo do webhook (padrão asaas.W001).

Roda em todo runserver/manage. Sem WHATSAPP_WEBHOOK_SECRET o webhook inbound responde 401
(fail-closed) e o bot nunca recebe mensagem — mas, como no asaas, NÃO travamos a migração por
falta de token de webhook: é Warning recorrente até o `.env` ser preenchido.

- `bot.W001` (Warning): sem WHATSAPP_WEBHOOK_SECRET → webhook do bot dá 401.
"""

from django.conf import settings
from django.core.checks import Warning


def check_bot_webhook_secret(app_configs, **kwargs):
    """Avisa (não trava) se WHATSAPP_WEBHOOK_SECRET faltar — sem ele o webhook do bot dá 401."""
    warnings = []
    if not getattr(settings, "WHATSAPP_WEBHOOK_SECRET", ""):
        warnings.append(
            Warning(
                "WHATSAPP_WEBHOOK_SECRET ausente no .env — o webhook inbound do bot vai responder "
                "401 (fail-closed) e nenhuma mensagem será processada.",
                hint="Gere um segredo forte, cole em backend/.env como WHATSAPP_WEBHOOK_SECRET=... "
                "e configure o MESMO valor no header x-webhook-token do webhook da Evolution.",
                id="bot.W001",
            )
        )
    return warnings
