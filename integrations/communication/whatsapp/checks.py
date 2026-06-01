"""System checks do app whatsapp — avisam no boot quando falta env essencial (padrão asaas).

Rodam em todo runserver/manage. Sem base_url ou api-key a Evolution não responde, então travam o
manage.py até a env ser preenchida (CONVENTION §8).

- `whatsapp.E001` (Error): sem WHATSAPP_GLOBAL_API_KEY → TRAVA.
- `whatsapp.E002` (Error): sem WHATSAPP_API_BASE_URL → TRAVA.
"""

from django.conf import settings
from django.core.checks import Error


def check_whatsapp_env(app_configs, **kwargs):
    errors = []
    if not getattr(settings, "WHATSAPP_GLOBAL_API_KEY", ""):
        errors.append(
            Error(
                "WHATSAPP_GLOBAL_API_KEY ausente no .env — o app whatsapp não fala com a Evolution.",
                hint="Cole a api-key global da Evolution em backend/.env: WHATSAPP_GLOBAL_API_KEY=...",
                id="whatsapp.E001",
            )
        )
    if not getattr(settings, "WHATSAPP_API_BASE_URL", ""):
        errors.append(
            Error(
                "WHATSAPP_API_BASE_URL ausente no .env — sem a URL da Evolution o app não envia nada.",
                hint="Defina em backend/.env: WHATSAPP_API_BASE_URL=http://...",
                id="whatsapp.E002",
            )
        )
    return errors
