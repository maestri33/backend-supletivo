from django.apps import AppConfig


class WhatsappConfig(AppConfig):
    name = "integrations.comunicacao.whatsapp"
    label = "whatsapp"

    def ready(self):
        # Registra os system checks de env no boot (padrão asaas): sem base_url/api-key a Evolution
        # não responde, então o app avisa em vermelho e trava o manage.py.
        from django.core.checks import register

        from .checks import check_whatsapp_env

        register(check_whatsapp_env)
