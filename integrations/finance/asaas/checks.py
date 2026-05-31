"""System check do app asaas — falha VERMELHA no boot se faltar env essencial.

Roda em todo runserver/manage (framework de checks do Django), então fica "printando" em
vermelho até a env ser preenchida. Padrão pedido pelo Victor: integração não sobe silenciosa
sem a key real (CONVENTION §8).
"""

from django.conf import settings
from django.core.checks import Error


def check_asaas_env(app_configs, **kwargs):
    """Erra se ASAAS_API_KEY não estiver no .env — sem ela o app não fala com o Asaas."""
    errors = []
    if not getattr(settings, "ASAAS_API_KEY", ""):
        errors.append(
            Error(
                "ASAAS_API_KEY ausente no .env — o app asaas não consegue falar com o Asaas.",
                hint="Cole a api-key do Asaas em backend/.env: ASAAS_API_KEY=...",
                id="asaas.E001",
            )
        )
    return errors
