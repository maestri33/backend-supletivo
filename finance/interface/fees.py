"""Superfície in-process do finance pra DESPESAS (fees): enfileira pagamento de despesa na fila de saída.

**Mesma fila** das comissões (`PaymentRequest`) — é tudo dinheiro saindo da mesma conta Asaas (palavra do
Victor). 1º fornecedor = a instituição que credencia o aluno. Método inicial = **PIX por QR code**
(copia-e-cola), **imediato** ou **agendado**. O valor vem do CALLER (a conta real) — **nunca do `.env`**
(§8: não invento dinheiro). Ver `plan/4-financeiro-fees.md`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from django.utils import timezone

from finance.models import PaymentRequest

logger = structlog.get_logger()


def request_fee_payment(
    *,
    amount,
    qr_payload,
    supplier_name=None,
    description=None,
    scheduled_for=None,
    external_reference=None,
) -> PaymentRequest:
    """Enfileira uma despesa pra pagamento via PIX QR code (imediato ou agendado).

    `scheduled_for=None` ⇒ **imediato** (o worker pega na próxima passada). Com data ⇒ **agendado**
    (a fila não pega até lá, via `next_attempt_at`). Idempotente por `external_reference` (default gerado).
    O `description` é guardado no Payment do Asaas no momento do envio (via supplier_name na fila).
    """
    ref = external_reference or f"fee_{uuid.uuid4().hex[:16]}"
    existing = PaymentRequest.objects.filter(external_reference=ref).first()
    if existing is not None:
        return existing

    pr = PaymentRequest.objects.create(
        external_reference=ref,
        kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE,
        amount=Decimal(str(amount)).quantize(Decimal("0.01")),
        qrcode_payload=qr_payload,
        supplier_name=supplier_name or (description or None),
        scheduled_for=scheduled_for,
        status=PaymentRequest.Status.QUEUED,
        next_attempt_at=scheduled_for or timezone.now(),
    )
    logger.info(
        "finance.fee_requested",
        external_reference=ref,
        amount=str(pr.amount),
        supplier=supplier_name,
        scheduled_for=str(scheduled_for) if scheduled_for else None,
    )
    return pr
