"""Validação manual do SMTP: conecta + STARTTLS + login (NÃO envia). Prova auth (§8).

Uso: python manage.py mail_health
Fecha parte do Portão 3 (§8 — integração validada com chamada real).
"""

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.communication.mail.client import MailError, get_client


class Command(BaseCommand):
    help = "Conecta no SMTP (STARTTLS:587) e autentica, sem enviar email (valida credencial)."

    def handle(self, *args, **options):
        client = get_client()
        try:
            async_to_sync(client.verify_login)()
        except MailError as exc:
            self.stderr.write(self.style.ERROR(f"SMTP rejeitou login: {exc}"))
            return
        except Exception as exc:  # rede/DNS/timeout
            self.stderr.write(self.style.ERROR(f"Falha ao falar com o SMTP: {exc!r}"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"SMTP ok (auth válida): {client.from_header}")
        )
