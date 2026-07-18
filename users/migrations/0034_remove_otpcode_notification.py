# Fase 2 (notify cutover) — passo 2/2: remove a FK antiga.
#
# Rodar SÓ DEPOIS do restart que carrega o código sem a FK (a 0033 já copiou o vínculo pra
# notification_external_id). Nunca no mesmo `migrate` que antecede o restart — senão o código
# ANTIGO (ainda em execução até o restart completar) quebra em qualquer query de OtpCode.
#
# Sequência de deploy: migrate users 0033 -> restart -> migrate (aplica esta) -> sanity.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0033_otpcode_notification_external_id"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="otpcode",
            name="notification",
        ),
    ]
