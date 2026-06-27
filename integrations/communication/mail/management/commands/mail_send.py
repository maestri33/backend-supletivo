"""Validação manual de ENVIO: manda um email real (teste de entrega §8).

Uso:
  python manage.py mail_send victormaestri@gmail.com --slug welcome \\
      --title "Bem-vindo" --content "Olá! Sua conta foi criada."
  python manage.py mail_send dest@x.com --html "<h1>cru</h1>" --subject "Assunto"
"""

import json

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.communication.mail import templates
from integrations.communication.mail.client import MailError, get_client


class Command(BaseCommand):
    help = "Envia um email real via SMTP (template por slug OU html cru)."

    def add_arguments(self, parser):
        parser.add_argument("to_email", help="Destinatário (ex.: victormaestri@gmail.com)")
        parser.add_argument("--slug", default="default", help="Slug do template (default: default)")
        parser.add_argument("--title", default="Teste — Supletivo Brasil", help="Título/assunto")
        parser.add_argument(
            "--content",
            default="Mensagem de teste enviada pelo app mail do mvp.",
            help="Texto do corpo (markdown bold suportado)",
        )
        parser.add_argument("--html", default=None, help="HTML cru (ignora template/--slug)")
        parser.add_argument("--subject", default=None, help="Assunto (default: --title)")
        parser.add_argument(
            "--media-url",
            default=None,
            help="URL pública de mídia a embutir (ex.: PNG)",
        )
        parser.add_argument(
            "--media-type",
            default="image",
            choices=sorted(templates.MEDIA_TYPES),
            help="Tipo da mídia (default: image)",
        )

    def handle(self, *args, **options):
        to_email = options["to_email"]
        subject = options["subject"] or options["title"]
        if options["html"]:
            html_body = options["html"]
            plain_body = None
        elif options["media_url"]:
            # Texto acima + mídia embutida por URL abaixo (content_is_html: não re-escapar o snippet).
            content_html = templates.text_to_html(options["content"]) + templates.media_html(
                options["media_url"], options["media_type"], caption=""
            )
            html_body = templates.render(
                options["slug"],
                title=options["title"],
                content=content_html,
                content_is_html=True,
            )
            plain_body = f"{options['content']}\n\n{options['media_url']}"
        else:
            html_body = templates.render(
                options["slug"], title=options["title"], content=options["content"]
            )
            plain_body = options["content"]

        client = get_client()

        async def _run():
            return await client.send_email(
                to_email, subject, html_body=html_body, plain_body=plain_body
            )

        try:
            result = async_to_sync(_run)()
        except MailError as exc:
            self.stderr.write(self.style.ERROR(f"SMTP recusou o envio: {exc}"))
            return
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Falha ao enviar: {exc!r}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Email enviado para {to_email}:"))
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
