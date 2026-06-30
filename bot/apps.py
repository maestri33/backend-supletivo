from django.apps import AppConfig


class BotConfig(AppConfig):
    name = "bot"
    label = "bot"

    def ready(self):
        # Registra o system check de env no boot (padrão asaas/whatsapp): sem WHATSAPP_WEBHOOK_SECRET
        # o webhook do bot dá 401 (fail-closed), então avisa recorrente — NÃO trava (não faz sentido
        # travar migração por falta de token de webhook; o asaas.W001 segue a mesma régua).
        from django.core.checks import register

        from .checks import check_bot_webhook_secret

        register(check_bot_webhook_secret)
