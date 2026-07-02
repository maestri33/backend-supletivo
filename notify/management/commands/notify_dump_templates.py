"""Gera `notify/seed/templates.md` a partir do catálogo in-memory (`users.roles.notifications`).

Centraliza as 48 mensagens existentes num .md editável, base do seed do DB. Rodar quando o
catálogo Python mudir, para o .md refletir (depois o `notify_seed_templates` põe no DB).

Uso:
    python manage.py notify_dump_templates              # escreve notify/seed/templates.md
    python manage.py notify_dump_templates --stdout     # imprime no stdout (pipe-friendly)

`source` é derivado do prefixo do evento (lead.* → users.roles.lead, hub.* → hub.interface, ...).
`fires_on` fica em branco — o Victor preenche ao editar (é só documentação do gatilho de negócio).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from notify.seed import io as seed_io
from users.roles import notifications as msgs

# prefixo do evento → módulo que dispara (documentação p/ o Victor achar o callsite).
_SOURCE_BY_PREFIX = {
    "lead": "users.roles.lead",
    "enrollment": "users.roles.enrollment",
    "candidate": "users.roles.candidate",
    "training": "users.roles.training",
    "student": "users.roles.student",
    "promoter": "users.roles.promoter",
    "hub": "hub.interface",
}

# título/assunto default quando o catálogo não traz (a maioria dos eventos não tem — só corpo).
# Branco é honesto: o Victor preenche ao editar; o e-mail cai no fallback "(sem assunto)".
_DEFAULT_TITLE = ""
_DEFAULT_SUBJECT = ""


class Command(BaseCommand):
    help = "Gera notify/seed/templates.md a partir do catálogo in-memory de notificações."

    def add_arguments(self, parser):
        parser.add_argument(
            "--stdout",
            action="store_true",
            help="Imprime no stdout em vez de escrever o arquivo.",
        )
        parser.add_argument(
            "--path",
            default=None,
            help="Caminho de saída (default: notify/seed/templates.md).",
        )

    def handle(self, *args, **opts) -> None:
        specs = []
        for event, body in sorted(msgs._MESSAGES.items()):
            prefix = event.split(".", 1)[0]
            spec = seed_io.TemplateSpec(
                event=event,
                body_md=body,
                is_tts=event in msgs._TTS_EVENTS,
                storytelling=event in msgs._STORY_EVENTS,
                channels="whatsapp,email",
                title=_DEFAULT_TITLE,
                subject=_DEFAULT_SUBJECT,
                mail_template="default",
                story_prompt=msgs._STORY_INSTRUCTIONS.get(event),
                fires_on="",
                source=_SOURCE_BY_PREFIX.get(prefix, ""),
                delay_minutes=0,
                active=True,
            )
            specs.append(spec)

        text = seed_io.serialize(specs)
        if opts["stdout"]:
            self.stdout.write(text, ending="")
            return
        from pathlib import Path

        path = Path(opts["path"]) if opts["path"] else Path(__file__).resolve().parents[2] / "seed" / "templates.md"
        path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"{len(specs)} eventos → {path}"))