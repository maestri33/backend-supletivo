"""Superfície in-process do finance pra PAGAMENTO AVULSO do staff (kind=manual).

Staff envia um pagamento a um TERCEIRO LIVRE (não precisa ser usuário da plataforma): PIX por chave
OU boleto (linha digitável), pela conta Asaas, e fica registrado na plataforma (Victor 2026-06-29).
**Mesma fila** (`PaymentRequest`) de comissões/fees — é tudo dinheiro saindo da mesma conta Asaas; o
worker (`finance.interface.payout`) paga e reconcilia. O valor vem do CALLER (a conta real), NUNCA do
`.env` (§8). Opcionalmente anexa um comprovante (recibo) — path relativo já salvo pelo endpoint.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from django.utils import timezone

from finance.models import PaymentRequest

logger = structlog.get_logger()


class ManualPaymentError(Exception):
    """Erro de borda do pagamento avulso (entrada inválida)."""


def _amount(value) -> Decimal:
    try:
        amt = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception as e:  # noqa: BLE001
        raise ManualPaymentError("invalid_amount") from e
    if amt <= 0:
        raise ManualPaymentError("amount_must_be_positive")
    return amt


def request_pix_payment(
    *, amount, pix_key, supplier_name=None, description=None, receipt=None
) -> PaymentRequest:
    """Enfileira um pagamento avulso por PIX (chave) a um terceiro livre. Idempotente por referência."""
    if not pix_key:
        raise ManualPaymentError("pix_key_required")
    ref = f"manual_{uuid.uuid4().hex[:16]}"
    pr = PaymentRequest.objects.create(
        external_reference=ref,
        kind=PaymentRequest.Kind.MANUAL,
        method=PaymentRequest.Method.PIX_KEY,
        amount=_amount(amount),
        pix_key=pix_key,
        supplier_name=supplier_name or (description or None),
        receipt=receipt,
        status=PaymentRequest.Status.QUEUED,
        next_attempt_at=timezone.now(),
    )
    logger.info(
        "finance.manual_pix_requested",
        external_reference=ref,
        amount=str(pr.amount),
        supplier=supplier_name,
        has_receipt=bool(receipt),
    )
    return pr


def request_boleto_payment(
    *, line_code, amount=None, supplier_name=None, description=None, receipt=None
) -> PaymentRequest:
    """Enfileira o pagamento avulso de um boleto pela linha digitável. `amount` opcional (o Asaas lê
    do próprio boleto). Idempotente por referência."""
    if not line_code:
        raise ManualPaymentError("line_code_required")
    ref = f"manual_{uuid.uuid4().hex[:16]}"
    pr = PaymentRequest.objects.create(
        external_reference=ref,
        kind=PaymentRequest.Kind.MANUAL,
        method=PaymentRequest.Method.BOLETO,
        amount=_amount(amount) if amount not in (None, "") else Decimal("0"),
        boleto_line=line_code,
        supplier_name=supplier_name or (description or None),
        receipt=receipt,
        status=PaymentRequest.Status.QUEUED,
        next_attempt_at=timezone.now(),
    )
    logger.info(
        "finance.manual_boleto_requested",
        external_reference=ref,
        amount=str(pr.amount),
        supplier=supplier_name,
        has_receipt=bool(receipt),
    )
    return pr
