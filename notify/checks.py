"""System check do app notify — avisa (não trava) quando falta config p/ um canal.

notify é consumidor: whatsapp/mail/ia já têm seus próprios checks E* que travam o boot. Aqui só
um Warning — sem uma base de URL a mídia do WhatsApp e o voice-note (TTS) não montam a URL pra
Evolution buscar, mas os outros canais funcionam, então não trava o manage.py (canal de apoio).

- `notify.W001` (Warning): sem MEDIA_LAN_BASE nem EXTERNAL_URL → o WhatsApp não tem como buscar
  a mídia/áudio por URL interna.
"""

from django.conf import settings
from django.core.checks import Warning as DjangoWarning


def check_notify_env(app_configs, **kwargs):
    warnings = []
    if not (getattr(settings, "MEDIA_LAN_BASE", "") or getattr(settings, "EXTERNAL_URL", "")):
        warnings.append(
            DjangoWarning(
                "MEDIA_LAN_BASE/EXTERNAL_URL ausentes — o WhatsApp do notify não monta a URL "
                "interna p/ a Evolution buscar a mídia/áudio (TTS).",
                hint="Defina MEDIA_LAN_BASE em backend/.env (ex.: http://10.1.20.30).",
                id="notify.W001",
            )
        )
    return warnings
