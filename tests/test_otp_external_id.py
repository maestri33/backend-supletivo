"""OTP × notify (Fase 2): OtpCode guarda a STRING devolvida por send(), não mais a FK.

- Serviço: generate_and_send grava exatamente o retorno de send() em notification_external_id
  (funciona igual nos modos local e remote — send devolve str nos dois).
- Migração 0033 (reverso da 0012): copia a FK notification -> string preservando a auditoria.
"""

import uuid

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from users.auth.otp import service as otp_service
from users.auth.otp.models import STATUS_SENT, OtpCode

pytestmark = pytest.mark.django_db


def _user_com_phone(phone="11999990010"):
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    Profile.objects.create(user=user, phone=phone)
    return user


def test_model_sem_fk_para_notify():
    """A FK notification saiu do model; ficou a coluna solta CharField(64, null, blank)."""
    fields = {f.name for f in OtpCode._meta.get_fields()}
    assert "notification" not in fields
    f = OtpCode._meta.get_field("notification_external_id")
    assert f.max_length == 64
    assert f.null is True
    assert f.blank is True


def test_otp_grava_string_devolvida_pelo_send(monkeypatch):
    """generate_and_send persiste EXATAMENTE o retorno de send() (str), sem lookup de model."""
    import notify.interface.send as notify_send

    sentinel = str(uuid.uuid4())
    monkeypatch.setattr(notify_send, "send", lambda **kwargs: sentinel)

    otp = otp_service.generate_and_send(_user_com_phone("11999990011"))

    assert otp.status == STATUS_SENT
    otp.refresh_from_db()
    assert otp.notification_external_id == sentinel


def test_otp_fluxo_real_aponta_pra_notification_local():
    """Modo local de verdade: a string gravada resolve a Notification criada pelo send()."""
    from notify.models import Notification

    otp = otp_service.generate_and_send(_user_com_phone("11999990012"))

    assert otp.notification_external_id
    notif = Notification.objects.get(external_id=otp.notification_external_id)
    assert notif.caller == "users.auth.otp"
    assert otp.notification_external_id == str(notif.external_id)


@pytest.mark.django_db(transaction=True)
def test_migracao_0033_copia_fk_para_string():
    """Aplica a 0033 sobre uma row com FK preenchida e confere a cópia str(external_id)."""
    executor = MigrationExecutor(connection)
    try:
        # volta pro estado pré-0033 (FK notification ainda existe)
        old_state = executor.migrate([("users", "0032_validationblock")])
        old_apps = old_state.apps
        user = old_apps.get_model("users", "User").objects.create(
            external_id=uuid.uuid4(), password="!"
        )
        notif = old_apps.get_model("notify", "Notification").objects.create(
            caller="users.auth.otp", text="codigo 123456"
        )
        otp = old_apps.get_model("users", "OtpCode").objects.create(
            user=user, code_hash="x" * 64, notification_id=notif.id
        )

        # re-aplica a 0033 (AddField + RunPython copy + RemoveField) — grafo recarregado
        executor = MigrationExecutor(connection)
        new_state = executor.migrate(
            [("users", "0033_otpcode_notification_external_id_and_more")]
        )
        saved = new_state.apps.get_model("users", "OtpCode").objects.get(id=otp.id)
        assert saved.notification_external_id == str(notif.external_id)
    finally:
        # garante o schema final pros demais testes, mesmo se algo acima falhar
        call_command("migrate", verbosity=0)
