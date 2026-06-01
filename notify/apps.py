from django.apps import AppConfig


class NotifyConfig(AppConfig):
    name = "notify"
    label = "notify"

    def ready(self):
        # Registra o system check de env (padrão dos integrations): avisa se falta a base de URL
        # (MEDIA_LAN_BASE/EXTERNAL_URL) que o canal de áudio (TTS) e a mídia do WhatsApp precisam.
        from django.core.checks import register

        from .checks import check_notify_env

        register(check_notify_env)
