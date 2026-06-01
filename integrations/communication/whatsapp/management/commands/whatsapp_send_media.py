"""Validação manual de ENVIO DE MÍDIA: manda imagem/vídeo/áudio/documento real (§8).

Uso:
  python manage.py whatsapp_send_media 5543996648750 image https://picsum.photos/400
  python manage.py whatsapp_send_media 5543996648750 document ./arquivo.pdf --filename matricula.pdf
  python manage.py whatsapp_send_media 5543996648750 audio https://.../som.mp3            # áudio transmitido
  python manage.py whatsapp_send_media 5543996648750 audio https://.../som.mp3 --voice    # nota de voz (PTT)

source: URL pública (http...) OU caminho de arquivo local (vira base64). Resolve o 9º dígito BR antes.
"""

import base64
import json
from pathlib import Path

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError

from integrations.communication.whatsapp.client import (
    MEDIA_TYPES,
    WhatsAppError,
    get_client,
)


class Command(BaseCommand):
    help = "Envia mídia real via Evolution (image/video/audio/document; --voice = nota de voz PTT)."

    def add_arguments(self, parser):
        parser.add_argument(
            "number", help="Destinatário DDI+DDD+número (ex.: 5543996648750)"
        )
        parser.add_argument(
            "media_type", choices=sorted(MEDIA_TYPES), help="image|video|audio|document"
        )
        parser.add_argument(
            "source", help="URL pública (http...) ou caminho de arquivo local"
        )
        parser.add_argument(
            "--caption", default=None, help="Legenda (image/video/document)"
        )
        parser.add_argument(
            "--filename", default=None, help="Nome do arquivo (document)"
        )
        parser.add_argument(
            "--voice", action="store_true", help="Áudio como nota de voz nativa (PTT)"
        )
        parser.add_argument(
            "--instance", default=None, help="Instância da Evolution (default: do .env)"
        )

    def _resolve_source(self, source: str) -> str:
        """URL passa direto; caminho local vira base64 PURO (sem prefixo data:)."""
        if source.startswith(("http://", "https://")):
            return source
        path = Path(source)
        if not path.is_file():
            raise CommandError(f"source não é URL nem arquivo existente: {source}")
        return base64.b64encode(path.read_bytes()).decode()

    def handle(self, *args, **options):
        number = options["number"]
        media_type = options["media_type"]
        media = self._resolve_source(options["source"])
        voice = options["voice"]
        instance = options["instance"]

        if voice and media_type != "audio":
            raise CommandError("--voice só vale para media_type=audio")

        async def _run():
            async with get_client(instance=instance) as wa:
                resolved = await wa.resolve_br_number(number)
                if voice:
                    result = await wa.send_whatsapp_audio(resolved, media)
                else:
                    result = await wa.send_media(
                        resolved,
                        media,
                        media_type,
                        caption=options["caption"],
                        filename=options["filename"],
                    )
                return resolved, result

        try:
            resolved, result = async_to_sync(_run)()
        except WhatsAppError as exc:
            self.stderr.write(self.style.ERROR(f"Evolution respondeu erro: {exc}"))
            return
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Falha ao enviar: {exc!r}"))
            return

        kind = "nota de voz (PTT)" if voice else media_type
        self.stdout.write(self.style.SUCCESS(f"Enviado [{kind}] para {resolved}:"))
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
