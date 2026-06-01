from django.apps import AppConfig


class IaConfig(AppConfig):
    name = "integrations.ia"
    label = "ia"

    def ready(self):
        # Registra o system check de config no boot. Roda em todo runserver/manage, então "fica
        # printando" vermelho enquanto a config de IA estiver incompleta (ia.E001/E002/E003 travam
        # o manage.py — padrão asaas: integração não sobe sem credencial real).
        from django.core.checks import register

        from .checks import check_ia_config

        register(check_ia_config)
