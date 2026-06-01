"""System checks do app mail — avisam no boot quando falta env de SMTP (padrão whatsapp/asaas).

Rodam em todo runserver/manage. Sem host/user/senha o SMTP não autentica, então travam o manage.py
até a env ser preenchida (CONVENTION §8).

- `mail.E001` (Error): sem MAIL_SMTP_HOST → TRAVA.
- `mail.E002` (Error): sem MAIL_SMTP_USER → TRAVA.
- `mail.E003` (Error): sem MAIL_SMTP_PASSWORD → TRAVA.
"""

from django.conf import settings
from django.core.checks import Error


def check_mail_env(app_configs, **kwargs):
    errors = []
    if not getattr(settings, "MAIL_SMTP_HOST", ""):
        errors.append(
            Error(
                "MAIL_SMTP_HOST ausente no .env — o app mail não conecta no servidor SMTP.",
                hint="Defina em backend/.env: MAIL_SMTP_HOST=mail.v7m.org",
                id="mail.E001",
            )
        )
    if not getattr(settings, "MAIL_SMTP_USER", ""):
        errors.append(
            Error(
                "MAIL_SMTP_USER ausente no .env — sem login o SMTP não autentica.",
                hint="Defina em backend/.env: MAIL_SMTP_USER=noreply@v7m.org",
                id="mail.E002",
            )
        )
    if not getattr(settings, "MAIL_SMTP_PASSWORD", ""):
        errors.append(
            Error(
                "MAIL_SMTP_PASSWORD ausente no .env — sem senha o SMTP não autentica.",
                hint="Cole a senha do noreply em backend/.env: MAIL_SMTP_PASSWORD=...",
                id="mail.E003",
            )
        )
    return errors
