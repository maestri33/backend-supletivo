"""Lead — a 1ª role do funil do ALUNO (clients): capta → paga → vira enrollment.

Porte do legado (`~/coders/backend` lead/), adaptado ao monólito: **FK real** (não external_id interno,
§4). O Lead **nasce ligado a um PROMOTER** (o `?ref=` da landing; sem ref → promotor padrão) — palavra do
Victor 2026-06-04. Ao PAGAR, vira `enrollment` (deixa de ser do promotor, passa a ser cuidado pelo hub).

Máquina de status (legado): `captured` → `waiting` (cartão, criando checkout) | `checkout` (PIX direto) →
`completed` (webhook do pagamento PAGO); `failed` = ramo de erro. Sub-pacote de `users` (app_label `users`,
1 migration set — igual address/documents; CONVENTION §2).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Lead(models.Model):
    """Um lead (aspirante a aluno). 1-1 com o User; ligado ao promotor que o captou."""

    class Status(models.TextChoices):
        CAPTURED = "captured", "captado"
        WAITING = "waiting", "aguardando checkout"
        CHECKOUT = "checkout", "em checkout"
        COMPLETED = "completed", "pago"
        FAILED = "failed", "falhou"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lead",
    )
    # o promotor que captou (ref da landing; nunca nulo — lead não existe sem promotor, Victor 2026-06-04).
    promoter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="captured_leads",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.CAPTURED,
        db_index=True,
    )
    failed_reason = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_lead"
        verbose_name = "lead"
        verbose_name_plural = "leads"

    def __str__(self) -> str:
        return f"lead<{self.external_id}:{self.status}>"


class Checkout(models.Model):
    """O checkout de pagamento de um lead (1-1). Reusa os gateways `integrations/finance/{asaas,infinitepay}`."""

    class Method(models.TextChoices):
        CREDIT_CARD = "credit_card", "cartão de crédito"
        PIX = "pix", "PIX"

    class Provider(models.TextChoices):
        ASAAS = "asaas", "Asaas"
        INFINITEPAY = "infinitepay", "InfinitePay"

    lead = models.OneToOneField(
        Lead,
        on_delete=models.CASCADE,
        related_name="checkout",
    )
    payment_method = models.CharField(max_length=12, choices=Method.choices)
    provider = models.CharField(max_length=12, choices=Provider.choices)
    provider_payment_id = models.CharField(max_length=128, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # cartão (InfinitePay): link de checkout + comprovante.
    checkout_url = models.URLField(max_length=500, null=True, blank=True)
    receipt_url = models.URLField(max_length=500, null=True, blank=True)
    # PIX (Asaas): copia-e-cola + imagem do QR + vencimento.
    qrcode_payload = models.TextField(null=True, blank=True)
    qrcode_image = models.URLField(max_length=500, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    is_paid = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_lead_checkout"
        verbose_name = "checkout do lead"
        verbose_name_plural = "checkouts do lead"

    def __str__(self) -> str:
        return f"checkout<{self.lead_id}:{self.payment_method}:{'pago' if self.is_paid else 'pendente'}>"
