from django.apps import AppConfig


class MailConfig(AppConfig):
    name = "integrations.comunicacao.mail"
    label = "mail"

    def ready(self):
        # Registra os system checks de env no boot (padrão whatsapp/asaas): sem host/user/senha o
        # SMTP não autentica, então o app avisa em vermelho e trava o manage.py.
        from django.core.checks import register

        from .checks import check_mail_env

        register(check_mail_env)
