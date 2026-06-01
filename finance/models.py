"""Models do app finance — motor de comissão (`Commission`) + solicitação de pagamento (`PaymentRequest`).

Convenções (CONVENTION §4/§6/§8/§12):
 - PK = BigAutoField interno; nunca exposto. `external_id` (UUID) = handle de borda.
 - **`payee` = FK real pro `users.User`** (decisão Victor 2026-06-01; `users` existe). A chave PIX do
   destino sai de `payee.profile.pix_key`, resolvida no fechamento (snapshot na PaymentRequest).
 - Dinheiro em **REAIS (Decimal, 2 casas)**, igual ao asaas — NUNCA float.
 - Idempotência no banco: `unique(source_type, source_external_id)` no crédito (à prova de corrida,
   corrige o bug do legado que só checava em Python); `unique(external_reference)` na solicitação.
 - `source_external_id` é UUID puro: lead/student (§4-8/9) não existem ainda → sem FK pra eles.
"""

import uuid

from django.conf import settings
from django.db import models


class Commission(models.Model):
    """Uma comissão creditada a um beneficiário, aguardando o fechamento semanal."""

    class Role(models.TextChoices):
        PROMOTER = "promoter", "promotor"
        COORDINATOR = "coordinator", "coordenador"

    class Source(models.TextChoices):
        LEAD = "lead", "lead pagou"  # comissão direta pro promotor que indicou
        VETERAN = "veteran", "student→veteran"  # comissão pro coordenador do hub
        BONUS = "bonus", "bônus de meta"  # >= threshold indicações na semana (flat)

    class Status(models.TextChoices):
        PENDING = "pending", "pendente"  # creditada, aguardando o fechamento
        PROCESSED = "processed", "processada"  # entrou numa PaymentRequest
        PAID = "paid", "paga"  # o PIX da PaymentRequest saiu (reconciliado)
        FAILED = "failed", "falhou"  # o PIX falhou em definitivo

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="commissions",
    )
    payee_role = models.CharField(max_length=12, choices=Role.choices, db_index=True)
    source_type = models.CharField(max_length=10, choices=Source.choices, db_index=True)
    # lead/student que disparou; bônus = UUID determinístico (uuid5 da semana+promotor).
    source_external_id = models.UUIDField(db_index=True)
    # reais; lido do .env no credit (corrige o bug do legado: valor vinha do caller).
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    payment_request = models.ForeignKey(
        "PaymentRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commissions",
    )
    external_reference = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_external_id"],
                name="uniq_commission_source",
            ),
        ]

    def __str__(self):
        return f"Commission({self.payee_role}/{self.source_type} R${self.amount} {self.status})"


class PaymentRequest(models.Model):
    """A "solicitação de pagamento" do fechamento: 1 por beneficiário/semana → 1 PIX.

    Idempotência do payout = `unique(external_reference)` (= o `payment_id` que mandamos ao asaas).
    `awaiting_pix`/`awaiting_balance` são NÃO-terminais: esperam na fila, não falham (não perde
    dinheiro). O PIX-out real é executado pelo `integrations.finance.asaas.payout` (provado no 1a-vi).
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "na fila"  # pronta pra enviar
        AWAITING_PIX = (
            "awaiting_pix",
            "sem chave PIX",
        )  # junta o valor, espera a chave do profile
        SUBMITTED = (
            "submitted",
            "enviada",
        )  # PIX submetido ao asaas, aguarda reconciliação
        AWAITING_BALANCE = (
            "awaiting_balance",
            "sem saldo",
        )  # asaas sem saldo, espera (não falha)
        PAID = "paid", "paga"  # reconciliada como PAID
        FAILED = "failed", "falhou"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # {ordinal-sexta-no-mês}_{MM}_{AAAA}_{payee.external_id} — idempotência do fechamento e do payout.
    external_reference = models.CharField(max_length=128, unique=True, db_index=True)
    payee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_requests",
    )
    payee_role = models.CharField(
        max_length=12, choices=Commission.Role.choices, db_index=True
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2
    )  # soma da semana, reais
    week_of = models.DateField(db_index=True)  # segunda-feira da semana
    # snapshot de payee.profile.pix_key resolvido no fechamento (auditável/estável).
    pix_key = models.CharField(max_length=140, null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    asaas_payment_id = models.CharField(max_length=128, null=True, blank=True)
    asaas_status = models.CharField(max_length=32, null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)  # só falhas de envio
    max_attempts = models.PositiveSmallIntegerField(default=7)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"PaymentRequest({self.external_reference} R${self.amount} {self.status})"
        )
