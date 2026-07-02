from django.apps import AppConfig


class NotifyConfig(AppConfig):
    name = "notify"
    label = "notify"

    def ready(self):
        # Registra o system check de env (padrão dos integrations): avisa se falta a base de URL
        # (MEDIA_LAN_BASE/EXTERNAL_URL) que o canal de áudio (TTS) e a mídia do WhatsApp precisam.
        from django.core.checks import register

        from .checks import check_notify_env
        from .interface.templates import connect_signals

        register(check_notify_env)
        # invalida o cache de Template quando uma row muda/sai (mantém msgs.text() sempre fresco).
        connect_signals()
