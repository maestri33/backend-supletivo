"""Superfície in-process do finance pra DESPESAS (fees): enfileira pagamento de despesa na fila de saída.

**Mesma fila** das comissões (`PaymentRequest`) — é tudo dinheiro saindo da mesma conta Asaas (palavra do
Victor). 1º fornecedor = a instituição que credencia o aluno. Método inicial = **PIX por QR code**
(copia-e-cola), **imediato** ou **agendado**. O valor vem do CALLER (a conta real) — **nunca do `.env`**
(§8: não invento dinheiro). Ver `plan/4-financeiro-fees.md`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from django.utils import timezone

from finance.models import PaymentRequest
from integrations.finance.asaas import qrpay

logger = structlog.get_logger()

SP_TZ = ZoneInfo("America/Sao_Paulo")
# Hora do dia em que pagamos uma despesa AGENDADA pelo vencimento do QR (horário comercial SP).
# Decisão técnica (Victor delegou 2026-06-02); CONFIG depois se precisar.
_DUE_PAY_HOUR = 9


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


def _due_to_scheduled(due_date: str) -> datetime:
    """Converte o `dueDate` do Asaas no instante de pagamento: 09:00 (SP) do dia de vencimento.

    Aceita data `YYYY-MM-DD` ou datetime ISO. Se vier sem fuso (caso comum: só a data), casa às
    `_DUE_PAY_HOUR` no fuso de SP. Levanta `ValueError` em formato inesperado (não chuta data).
    """
    try:
        dt = datetime.fromisoformat(due_date.strip())
    except ValueError as e:
        raise ValueError(f"dueDate em formato inesperado: {due_date!r}") from e
    if dt.tzinfo is None:
        dt = datetime.combine(dt.date(), time(hour=_DUE_PAY_HOUR), tzinfo=SP_TZ)
    return dt


def schedule_fee_on_due_date(
    *,
    qr_payload,
    amount=None,
    supplier_name=None,
    description=None,
    external_reference=None,
) -> PaymentRequest:
    """Agenda o pagamento de uma despesa pra DATA DE VENCIMENTO lida do próprio QR (cobrança com vencimento).

    Decodifica o QR no Asaas (resolve o payload dinâmico), exige `dueDate`, e enfileira agendado pra esse
    dia (09:00 SP). O valor vem do CALLER se informado; senão usa o `value` da cobrança decodificada (§8:
    ler o valor cobrado não é inventar dinheiro). Levanta `ValueError` com motivo claro se não der pra agendar.
    """
    info = qrpay.decode_qr(qr_payload)
    if not info.get("canBePaid", False):
        reason = info.get("cannotBePaidReason") or "motivo não informado pelo Asaas"
        raise ValueError(f"QR não pode ser pago: {reason}")
    due = info.get("dueDate")
    if not due:
        raise ValueError(
            "QR sem data de vencimento (estático/imediato) — use pagamento imediato ou --at <data>."
        )
    scheduled_for = _due_to_scheduled(str(due))
    value = amount if amount is not None else info.get("value")
    if value is None:
        raise ValueError(
            "sem valor: o caller não informou e o QR decodificado não traz `value`."
        )
    # VENCIDA (dueDate no passado): não dá pra agendar no passado — paga IMEDIATO, explícito e logado
    # (não silencioso). Quem cola uma cobv vencida quer quitá-la; o worker pegaria na próxima passada de
    # qualquer forma, mas aqui deixamos claro que é pagamento imediato, não "agendado".
    overdue = scheduled_for <= timezone.now()
    logger.info(
        "finance.fee_scheduled_on_due",
        due_date=str(due),
        scheduled_for=None if overdue else str(scheduled_for),
        amount=str(value),
        from_qr_value=amount is None,
        overdue=overdue,
    )
    return request_fee_payment(
        amount=value,
        qr_payload=qr_payload,
        supplier_name=supplier_name,
        description=description,
        scheduled_for=None if overdue else scheduled_for,
        external_reference=external_reference,
    )
