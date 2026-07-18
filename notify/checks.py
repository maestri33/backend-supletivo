"""System check do app notify — avisa (não trava) quando falta config p/ um canal.

notify é consumidor: whatsapp/mail/ia já têm seus próprios checks E* que travam o boot. Aqui só
um Warning — sem uma base de URL a mídia do WhatsApp e o voice-note (TTS) não montam a URL pra
Evolution buscar, mas os outros canais funcionam, então não trava o manage.py (canal de apoio).

- `notify.W001` (Warning): sem MEDIA_LAN_BASE nem EXTERNAL_URL → o WhatsApp não tem como buscar
  a mídia/áudio por URL interna.
- `notify.E002`/`E003` (Error, TRAVAM): NOTIFY_MODE inválido, ou `remote` sem NOTIFY_SERVER_URL —
  no modo remoto TODA notificação passa pelo notify-server; sem URL nada sai.
"""

from django.conf import settings
from django.core.checks import Error
from django.core.checks import Warning as DjangoWarning


def check_notify_env(app_configs, **kwargs):
    warnings = []
    mode = getattr(settings, "NOTIFY_MODE", "local")
    if mode not in ("local", "remote"):
        warnings.append(
            Error(
                f"NOTIFY_MODE inválido ({mode!r}) — use 'local' ou 'remote'.",
                hint="Ajuste NOTIFY_MODE em backend/.env.",
                id="notify.E002",
            )
        )
    if mode == "remote" and not getattr(settings, "NOTIFY_SERVER_URL", ""):
        warnings.append(
            Error(
                "NOTIFY_MODE=remote sem NOTIFY_SERVER_URL — o notify não sabe onde está o "
                "notify-server; nenhuma notificação sairia.",
                hint="Defina NOTIFY_SERVER_URL em backend/.env (ex.: http://10.1.30.40).",
                id="notify.E003",
            )
        )
    if not (
        getattr(settings, "MEDIA_LAN_BASE", "") or getattr(settings, "EXTERNAL_URL", "")
    ):
        warnings.append(
            DjangoWarning(
                "MEDIA_LAN_BASE/EXTERNAL_URL ausentes — o WhatsApp do notify não monta a URL "
                "interna p/ a Evolution buscar a mídia/áudio (TTS).",
                hint="Defina MEDIA_LAN_BASE em backend/.env (ex.: http://10.1.20.30).",
                id="notify.W001",
            )
        )
    return warnings
