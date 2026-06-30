"""Envio AVULSO do staff via CLI: notificação (whatsapp e/ou e-mail) a um usuário OU destino livre.

Uso:
  # destino livre (não-usuário): telefone e/ou e-mail direto
  python manage.py send_notify --phone 5543996648750 --message "Olá!"
  python manage.py send_notify --email a@b.com --subject "Aviso" --message "Olá!"
  python manage.py send_notify --phone 55... --email a@b.com --message "Olá nos dois canais"
  # usuário existente (herda phone/email do Profile)
  python manage.py send_notify --user <external_id> --message "Olá!" --channels whatsapp

Enfileira no Django-Q (NÃO bloqueia, NÃO espera o envio). Imprime o external_id da notificação.
"""

from django.core.management.base import BaseCommand, CommandError

from notify.interface.send import send_adhoc
from users.exceptions import DomainError


class Command(BaseCommand):
    help = (
        "Dispara uma notificação avulsa (whatsapp/email) a um usuário ou destino livre."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", default=None, help="external_id de um usuário (herda phone/email)"
        )
        parser.add_argument(
            "--phone", default=None, help="Telefone livre (DDI+DDD+nº) p/ whatsapp"
        )
        parser.add_argument("--email", default=None, help="E-mail livre")
        parser.add_argument("--subject", default=None, help="Assunto/título do e-mail")
        parser.add_argument("--message", required=True, help="Corpo da mensagem")
        parser.add_argument(
            "--channels",
            default=None,
            help="Canais separados por vírgula (whatsapp,email). Default: todos com destino.",
        )

    def handle(self, *args, **o):
        channels = (
            [c for c in (o["channels"] or "").split(",") if c.strip()]
            if o["channels"]
            else None
        )
        try:
            external_id = send_adhoc(
                message=o["message"],
                to_user=o["user"],
                phone=o["phone"],
                email=o["email"],
                subject=o["subject"],
                channels=channels,
                caller="send_notify",
            )
        except DomainError as exc:
            raise CommandError(f"{exc.code}: {exc.detail}") from exc
        self.stdout.write(
            self.style.SUCCESS(f"Notification {external_id} enfileirada.")
        )
