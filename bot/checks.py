"""System check do app bot — TRAVA o boot se faltar o segredo do webhook inbound.

A6.3 (segurança — plataforma exposta à internet): o webhook `/bot/webhook/` é o ponto de entrada
PÚBLICO do bot. Sem `WHATSAPP_WEBHOOK_SECRET`, o endpoint existe mas rejeita tudo (401 fail-closed),
matando o bot silenciosamente — e deixando um endpoint vivo exposto na internet. Antes era só
Warning (`bot.W001`, espelhava o asaas.W001); A6.3 eleva pra **Error** pra falhar LITERAL no boot,
igual ao `whatsapp.E001`/`E002` (que já travam o lado outbound). Assim um deploy mal-configurado
não sobe com a porta aberta e o bot mudo.

- `bot.E001` (Error): sem WHATSAPP_WEBHOOK_SECRET → TRAVA o manage.py até preencher o `.env`.
"""

from django.conf import settings
from django.core.checks import Error


def check_bot_webhook_secret(app_configs, **kwargs):
    """Trava o boot (Error) se WHATSAPP_WEBHOOK_SECRET faltar — webhook inbound é exposto à internet."""
    errors = []
    if not getattr(settings, "WHATSAPP_WEBHOOK_SECRET", ""):
        errors.append(
            Error(
                "WHATSAPP_WEBHOOK_SECRET ausente no .env — o webhook inbound do bot (exposto à "
                "internet) não pode operar sem segredo. Sem ele o endpoint responde 401 a tudo.",
                hint="Gere um segredo forte (ex.: scripts/rotate_evolution_secret.sh), cole em "
                "backend/.env como WHATSAPP_WEBHOOK_SECRET=... e configure o MESMO valor no header "
                "x-webhook-token do webhook da Evolution.",
                id="bot.E001",
            )
        )
    return errors
