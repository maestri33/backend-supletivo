"""Validação manual de ENVIO: manda um texto real pra um número (teste de entrega §8).

Uso: python manage.py whatsapp_send 5543996648750 "olá do mvp"
Resolve a variante BR (9º dígito) antes de enviar. Opcional: --instance ieadpg.
"""

import json

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.comunicacao.whatsapp.client import WhatsAppError, get_client


class Command(BaseCommand):
    help = "Envia uma mensagem de texto real via Evolution (resolve o 9º dígito BR antes)."

    def add_arguments(self, parser):
        parser.add_argument("number", help="Destinatário DDI+DDD+número (ex.: 5543996648750)")
        parser.add_argument("text", help="Texto da mensagem")
        parser.add_argument("--instance", default=None, help="Instância da Evolution (default: do .env)")

    def handle(self, *args, **options):
        number, text, instance = options["number"], options["text"], options["instance"]

        async def _run():
            async with get_client(instance=instance) as wa:
                resolved = await wa.resolve_br_number(number)
                return resolved, await wa.send_text(resolved, text)

        try:
            resolved, result = async_to_sync(_run)()
        except WhatsAppError as exc:
            self.stderr.write(self.style.ERROR(f"Evolution respondeu erro: {exc}"))
            return
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Falha ao enviar: {exc!r}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Enviado para {resolved}:"))
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
