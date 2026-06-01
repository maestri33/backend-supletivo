"""Validação manual do validador de email: formato + MX [+ SMTP RCPT com --smtp].

Uso:
  python manage.py mail_validate victormaestri@gmail.com
  python manage.py mail_validate alguem@dominio.com --smtp
"""

import dataclasses
import json

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.comunicacao.mail.validator import validate_email


class Command(BaseCommand):
    help = "Valida um email: formato + MX (e RCPT TO no MX com --smtp)."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email a validar")
        parser.add_argument(
            "--smtp", action="store_true", help="Também tenta RCPT TO no MX (lento; opcional)"
        )

    def handle(self, *args, **options):
        result = async_to_sync(validate_email)(options["email"], smtp_check=options["smtp"])
        self.stdout.write(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
