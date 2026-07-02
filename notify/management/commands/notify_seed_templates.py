"""Carrega `notify/seed/templates.md` no DB (Template + Trigger).

Default: cria só o que falta (create-if-missing) — NÃO sobrescreve edições do Victor. Use
`--force` para sobrescrever todos os campos a partir do .md (útil em dev, perigoso em prod: apaga
ajustes manuais do DB). `--active-only` pula eventos com `active: false` no .md (não cria Trigger).

Idempotente: roda quantas vezes quiser; no modo default só cria rows novas, as existentes ficam.

Uso:
    python manage.py notify_seed_templates                  # cria o que falta
    python manage.py notify_seed_templates --force          # sobrescreve tudo pelo .md
    python manage.py notify_seed_templates --path X.md      # fonte alternativa
    python manage.py notify_seed_templates --dry-run        # só relata, não grava
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from notify.interface import templates as _db_cache
from notify.models import Template, Trigger
from notify.seed import io as seed_io

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "seed" / "templates.md"


class Command(BaseCommand):
    help = "Carrega notify/seed/templates.md no DB (Template + Trigger). Default cria só o que falta."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(_DEFAULT_PATH), help=f"Arquivo .md (default: {_DEFAULT_PATH})")
        parser.add_argument("--force", action="store_true", help="Sobrescreve rows existentes pelo .md (perde edições manuais).")
        parser.add_argument("--dry-run", action="store_true", help="Só relata o que faria, não grava.")
        parser.add_argument("--active-only", action="store_true", help="Pula eventos marcados active: false no .md.")

    def handle(self, *args, **opts) -> None:
        path = Path(opts["path"])
        text = path.read_text(encoding="utf-8")
        specs = seed_io.parse(text)
        force = opts["force"]
        dry = opts["dry_run"]
        active_only = opts["active_only"]

        created = updated = skipped = unchanged = triggers = 0
        with transaction.atomic():
            for spec in specs:
                if active_only and not spec.active:
                    skipped += 1
                    continue
                fields = dict(
                    body_md=spec.body_md,
                    is_tts=spec.is_tts,
                    storytelling=spec.storytelling,
                    channels=spec.channels,
                    title=spec.title,
                    subject=spec.subject,
                    media_url=spec.media_url,
                    media_type=spec.media_type,
                    mail_template=spec.mail_template,
                    story_prompt=spec.story_prompt,
                )
                existing = Template.objects.filter(event=spec.event).first()
                if existing is None:
                    if dry:
                        tpl = Template(event=spec.event, **fields)  # instância fictícia (não gravada)
                    else:
                        tpl = Template.objects.create(event=spec.event, **fields)
                    created += 1
                else:
                    if force:
                        changed = False
                        for k, v in fields.items():
                            if getattr(existing, k) != v:
                                setattr(existing, k, v)
                                changed = True
                        if changed:
                            if not dry:
                                existing.save()
                                _db_cache.invalidate(spec.event)  # atualiza cache em memória
                            updated += 1
                        else:
                            unchanged += 1
                    else:
                        unchanged += 1
                    tpl = existing

                # Trigger (OneToOne com o Template): cria se não existir; --force atualiza fires_on/source/delay/active.
                if not dry:
                    tfields = dict(
                        fires_on=spec.fires_on or "",
                        source=spec.source or "",
                        delay_minutes=spec.delay_minutes,
                        active=spec.active,
                    )
                    tr = Trigger.objects.filter(template=tpl).first()
                    if tr is None:
                        Trigger.objects.create(template=tpl, **tfields)
                        triggers += 1
                    elif force:
                        changed = any(getattr(tr, k) != v for k, v in tfields.items())
                        if changed:
                            for k, v in tfields.items():
                                setattr(tr, k, v)
                            tr.save()
                            triggers += 1

        verb = "DRY-RUN " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{verb}{len(specs)} specs: {created} criados, {updated} atualizados, "
            f"{unchanged} unchanged, {skipped} pulados (active=false). Triggers: {triggers}."
        ))