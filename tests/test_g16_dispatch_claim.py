"""G16 — o dispatch fazia os envios de rede DENTRO da transação e só gravava o status no commit
final. Se o worker morria após a rede mas antes do commit, o rollback voltava o status pra PENDING
e o retry do Django-Q reenviava (áudio 2×, IA cobrada 2×, e-mail 2×). Fix: claim SENDING commitado
ANTES da rede (fase 1), envio fora da transação (fase 2), resultado (fase 3).
"""

import pytest

from notify import dispatch as d
from notify.models import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    Notification,
)

pytestmark = pytest.mark.django_db


def _notif(**kw):
    base = dict(
        caller="test",
        recipient_phone="5543999999999",
        text="oi",
        want_tts=False,
        whatsapp_status=STATUS_PENDING,
        email_status=STATUS_SKIPPED,
        tts_status=STATUS_SKIPPED,
    )
    base.update(kw)
    return Notification.objects.create(**base)


def test_g16_claim_sending_commitado_ANTES_da_rede(monkeypatch):
    """O coração do G16: quando a função de rede (_send_tts) roda, o status no banco já é SENDING —
    prova que o claim foi commitado antes. Sem isso, um crash durante a rede voltaria a PENDING e o
    retry duplicaria."""
    monkeypatch.setattr(d.settings, "TEST_MODE", False)
    notif = _notif(want_tts=True, tts_status=STATUS_PENDING)

    observed = {}

    def fake_send_tts(n):
        fresh = Notification.objects.get(
            id=notif.id
        )  # relê do banco no momento do envio
        observed["tts"] = fresh.tts_status
        observed["whatsapp"] = fresh.whatsapp_status
        n.tts_status = STATUS_SENT
        n.whatsapp_status = STATUS_SENT

    monkeypatch.setattr(d, "_send_tts", fake_send_tts)
    d.dispatch(notif.id)

    assert observed["tts"] == STATUS_SENDING, (
        "claim NÃO foi commitado antes da rede (duplicação possível)"
    )
    assert observed["whatsapp"] == STATUS_SENDING
    notif.refresh_from_db()
    assert notif.tts_status == STATUS_SENT  # fase 3 gravou o resultado


def test_g16_recover_manda_texto_SEM_regenerar_tts(monkeypatch):
    """Retry após crash (WhatsApp/TTS presos em SENDING): recupera por TEXTO e NÃO regenera o TTS
    (regra do Victor — a geração de áudio é a única coisa cara/que não pode duplicar; texto é comum
    e sem problema). Garante a entrega da mensagem sem cobrar a IA de novo."""
    monkeypatch.setattr(d.settings, "TEST_MODE", False)
    notif = _notif(
        want_tts=True,
        whatsapp_status=STATUS_SENDING,
        tts_status=STATUS_SENDING,
    )
    called = []
    monkeypatch.setattr(d, "_send_tts", lambda n: called.append("tts"))

    def fake_text(n):
        called.append("text")
        n.whatsapp_status = STATUS_SENT

    monkeypatch.setattr(d, "_send_whatsapp_text", fake_text)

    d.dispatch(notif.id)
    assert "tts" not in called, "regenerou o TTS no recover (cobraria a IA 2×)"
    assert "text" in called, "não mandou texto no recover (mensagem perdida)"
    notif.refresh_from_db()
    assert notif.whatsapp_status == STATUS_SENT
    assert notif.tts_status == STATUS_FAILED  # marcado como recuperado-por-texto


def test_g16_fluxo_normal_texto(monkeypatch):
    """Não-regressão: WhatsApp texto pendente → enviado, vira SENT."""
    monkeypatch.setattr(d.settings, "TEST_MODE", False)
    notif = _notif(whatsapp_status=STATUS_PENDING)

    def fake_text(n):
        n.whatsapp_status = STATUS_SENT

    monkeypatch.setattr(d, "_send_whatsapp_text", fake_text)
    d.dispatch(notif.id)
    notif.refresh_from_db()
    assert notif.whatsapp_status == STATUS_SENT


def test_g16_test_mode_dry_run_inalterado(monkeypatch):
    """TEST_MODE continua marcando SENT sem tocar a rede (não regride o caminho do OTP)."""
    monkeypatch.setattr(d.settings, "TEST_MODE", True)
    called = []
    monkeypatch.setattr(d, "_send_whatsapp_text", lambda n: called.append("wa"))
    notif = _notif(whatsapp_status=STATUS_PENDING)
    d.dispatch(notif.id)
    notif.refresh_from_db()
    assert notif.whatsapp_status == STATUS_SENT
    assert called == [], "TEST_MODE tocou a rede"
