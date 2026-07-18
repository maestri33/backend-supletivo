# Fase 2 (notify cutover) — passo 1/2: adiciona a coluna nova e copia o vínculo.
#
# A FK OtpCode.notification só é removida na migração seguinte (0034), depois do deploy
# reiniciar os workers. Assim o código ANTIGO (que ainda declara a FK) continua rodando contra
# um schema que ainda tem a coluna durante a janela migrate→restart, sem quebrar o login por OTP
# no meio do deploy (achado do review adversarial: migração única quebrava OtpCode ali).

from django.db import migrations, models


def copy_otp_notification_external_id(apps, schema_editor):
    """Copia a FK notification -> string notification_external_id (não perde auditoria de OTP)."""
    OtpCode = apps.get_model("users", "OtpCode")
    Notification = apps.get_model("notify", "Notification")
    for otp in OtpCode.objects.exclude(notification__isnull=True):
        notif = Notification.objects.filter(id=otp.notification_id).first()
        if notif is not None:
            otp.notification_external_id = str(notif.external_id)
            otp.save(update_fields=["notification_external_id"])


def restore_otp_notification(apps, schema_editor):
    """Reverso: reata a FK notification a partir da string notification_external_id."""
    OtpCode = apps.get_model("users", "OtpCode")
    Notification = apps.get_model("notify", "Notification")
    for otp in OtpCode.objects.exclude(notification_external_id__isnull=True):
        notif = Notification.objects.filter(
            external_id=otp.notification_external_id
        ).first()
        if notif is not None:
            otp.notification_id = notif.id
            otp.save(update_fields=["notification"])


class Migration(migrations.Migration):
    dependencies = [
        ("notify", "0001_initial"),
        ("users", "0032_validationblock"),
    ]

    operations = [
        migrations.AddField(
            model_name="otpcode",
            name="notification_external_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.RunPython(
            copy_otp_notification_external_id, restore_otp_notification
        ),
    ]
