from django.apps import AppConfig


class BotConfig(AppConfig):
    name = "bot"
    label = "bot"

    def ready(self):
        # Registra o system check de env no boot (padrão whatsapp.E001/E002): A6.3 elevou o
        # WHATSAPP_WEBHOOK_SECRET de Warning p/ Error — o webhook inbound é exposto à internet,
        # então sem o segredo o manage.py TRAVA (igual ao lado outbound da Evolution).
        from django.core.checks import register

        from .checks import check_bot_webhook_secret

        register(check_bot_webhook_secret)
