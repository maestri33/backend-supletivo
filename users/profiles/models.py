"""Profile — dados pessoais/contato, 1-1 com o User (CONVENTION §4: "contato mora em profiles").

ESCOPO MÍNIMO de hoje (Portão 1/2 2026-06-01): só o que o `auth` precisa pra cumprir a spec —
unicidade absoluta de **cpf, phone, email** (§9) + `gender` (vem de brinde do CPFHub; usado depois
p/ voz do TTS e doc de reservista). O `profiles` COMPLETO (chave Pix + validação Asaas, nome
detalhado, FK pro address) é ciclo próprio mais pra frente — NÃO inventar campo aqui.

Unicidade "nem falsos" (spec auth) = `unique` no banco + validação de formato (auth.validation) +
veracidade real no register (CPFHub p/ cpf, WhatsApp check_numbers p/ phone).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Profile(models.Model):
    """1-1 com o User. Guarda os campos de unicidade/contato exigidos pelo auth."""

    GENDER_CHOICES = (("M", "masculino"), ("F", "feminino"))

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    cpf = models.CharField("CPF", max_length=11, unique=True)
    # telefone no formato canônico DDI+DDD+número (55+DDD+9+8 = 13 díg) — o mesmo que o WhatsApp/
    # notify usam (resolve_br_number). Guardamos o número resolvido (variante registrada no zap).
    phone = models.CharField("telefone", max_length=13, unique=True)
    email = models.EmailField("e-mail", unique=True, null=True, blank=True)
    gender = models.CharField(
        "gênero",
        max_length=1,
        choices=GENDER_CHOICES,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_profile"
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self) -> str:
        return f"profile<{self.cpf}>"
