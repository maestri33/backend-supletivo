"""Fase 2 do desmembramento — o caminho REMOTO do send() (NOTIFY_MODE=remote).

Cobre o contrato do shim (wiki/notify/servico-multi-tenant.md, Fase 2 item 1):
 - external_id gerado no CLIENTE e devolvido NA HORA;
 - payload do POST /v1/send leva o mesmo external_id (idempotência do retry);
 - NENHUMA row local é criada (auditoria mora no notify-server);
 - falha de rede → enfileira retry no Django-Q com o MESMO payload e não quebra o caller (§12);
 - modo local (default) segue intocado.
Sem rede real: `notify.remote.post_send`/`async_task` são monkeypatchados.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def remote_mode(settings):
    settings.NOTIFY_MODE = "remote"
    settings.NOTIFY_SERVER_URL = "http://notify-server.test"
    settings.NOTIFY_API_KEY = "test-key"
    settings.TEST_MODE = (
        False  # queremos exercitar o caminho remoto de verdade (mockado)
    )
    return settings


def test_remote_send_devolve_uuid_e_posta_mesmo_external_id(remote_mode, monkeypatch):
    from notify import remote
    from notify.interface.send import send
    from notify.models import Notification

    sent = {}
    monkeypatch.setattr(remote, "post_send", lambda payload: sent.update(payload))

    ext = send(text="oi", caller="test.remote", phone="5511999990001", run_sync=True)

    assert uuid.UUID(ext)  # handle válido, na hora
    assert sent["external_id"] == ext  # o POST leva o MESMO handle (retry idempotente)
    assert sent["caller"] == "test.remote"
    assert sent["phone"] == "5511999990001"
    assert Notification.objects.count() == 0  # sem row local no modo remoto


def test_remote_send_falha_de_rede_enfileira_retry_e_nao_quebra(
    remote_mode, monkeypatch
):
    from notify import remote
    from notify.interface.send import send

    def _boom(payload):
        raise ConnectionError("notify-server fora")

    queued = {}
    monkeypatch.setattr(remote, "post_send", _boom)
    monkeypatch.setattr(
        "django_q.tasks.async_task",
        lambda task, payload, **kw: queued.update({"task": task, "payload": payload}),
    )

    ext = send(text="oi", caller="test.remote", phone="5511999990001")  # não levanta

    assert queued["task"] == "notify.remote.retry_send"
    assert queued["payload"]["external_id"] == ext  # retry entrega a MESMA notificação


def test_remote_media_type_autodetect(remote_mode, monkeypatch):
    from notify import remote
    from notify.interface.send import send

    sent = {}
    monkeypatch.setattr(remote, "post_send", lambda payload: sent.update(payload))
    send(
        text="qr",
        caller="test.remote",
        phone="5511999990001",
        media_url="https://x.test/qr.png",
        run_sync=True,
    )
    assert sent["media_type"] == "image"  # _guess_media_type roda antes do POST


def test_remote_test_mode_e_dry_run(remote_mode, monkeypatch):
    """TEST_MODE + remote: devolve handle sem tocar a rede (espelho do dry-run local)."""
    from notify import remote
    from notify.interface.send import send

    remote_mode.TEST_MODE = True

    def _explode(payload):
        raise AssertionError("não deveria tocar a rede em TEST_MODE")

    monkeypatch.setattr(remote, "post_send", _explode)
    ext = send(text="oi", caller="test.remote", phone="5511999990001")
    assert uuid.UUID(ext)


def test_local_mode_segue_intocado(settings):
    """Default local: cria a row e o dry-run do dispatch marca SENT (comportamento de sempre)."""
    from notify.interface.send import send
    from notify.models import Notification

    settings.NOTIFY_MODE = "local"
    settings.TEST_MODE = True
    ext = send(text="oi", caller="test.local", phone="5511999990001", run_sync=True)
    notif = Notification.objects.get(external_id=ext)
    assert notif.whatsapp_status == "sent"


def test_otp_guarda_handle_como_uuid(settings):
    """OTP grava o external_id (UUID) direto — funciona igual nos dois modos (Fase 2 item 4)."""
    from users.auth.models import User
    from users.auth.otp import service as otp_service
    from users.profiles.models import Profile

    settings.TEST_MODE = True
    settings.OTP_ACTIVE = True
    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="5511999990002")

    otp = otp_service.generate_and_send(user)
    assert otp.status == "sent"
    assert otp.notification_external_id is not None
    assert uuid.UUID(str(otp.notification_external_id))
