from django.apps import AppConfig


class AsaasConfig(AppConfig):
    name = "integrations.finance.asaas"
    label = "asaas"

    def ready(self):
        # Registra os system checks de env no boot. Rodam em todo runserver/manage, então "ficam
        # printando" enquanto faltar env essencial (E001 = api-key trava; W001 = webhook-secret avisa).
        from django.core.checks import register

        from .checks import check_asaas_env, check_asaas_webhook_secret

        register(check_asaas_env)
        register(check_asaas_webhook_secret)
