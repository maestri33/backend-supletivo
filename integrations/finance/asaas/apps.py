from django.apps import AppConfig


class AsaasConfig(AppConfig):
    name = "integrations.finance.asaas"
    label = "asaas"

    def ready(self):
        # Registra o system check de env no boot. Roda em todo runserver/manage, então
        # "fica printando" em vermelho enquanto faltar a env essencial (padrão p/ integrações).
        from django.core.checks import register

        from .checks import check_asaas_env

        register(check_asaas_env)
