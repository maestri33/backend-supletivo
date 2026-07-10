"""Guardas de dinheiro do TIER 1 da auditoria (G5, G6, G7). Cada teste reproduz o cenário exato
que a auditoria descreveu e verifica que a guarda fecha.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ───────────────────────── G5: webhook não rebaixa PAID ─────────────────────────
def test_g5_overdue_tardio_nao_rebaixa_paid():
    """PAYMENT_OVERDUE reentregue sobre uma cobrança já PAID não pode virar EXPIRED (travaria o
    reembolso). Só PENDING/EXPIRED -> PAID (pagamento tardio) é permitido."""
    from integrations.bank.asaas.models import Payment
    from integrations.bank.asaas.webhooks import _apply_charge

    pay = Payment.objects.create(
        payment_id="chg_g5",
        kind=Payment.Kind.CHARGE,
        status="PAID",
        amount=100,
    )
    payload = {"payment": {"externalReference": "chg_g5", "id": "asaas_1"}}
    row, reason = _apply_charge(payload, "PAYMENT_OVERDUE")
    pay.refresh_from_db()
    assert pay.status == "PAID", "PAID foi rebaixado por evento tardio"
    assert row is None and reason.startswith("terminal_")


def test_g5_pagamento_tardio_ainda_confirma():
    """Não-regressão: PENDING -> PAID (pagamento que chega depois) continua funcionando."""
    from integrations.bank.asaas.models import Payment
    from integrations.bank.asaas.webhooks import _apply_charge

    Payment.objects.create(
        payment_id="chg_g5b", kind=Payment.Kind.CHARGE, status="PENDING", amount=100
    )
    payload = {"payment": {"externalReference": "chg_g5b", "id": "a2"}}
    row, reason = _apply_charge(payload, "PAYMENT_CONFIRMED")
    assert row is not None and row.status == "PAID"


# ─────────────────── G6: comissão de fim de semana não some ───────────────────
def test_g6_comissao_de_semana_passada_entra_no_fechamento():
    """Comissão PENDING criada ANTES da janela desta semana (o caso do fim de semana) deve ser
    varrida pelo fechamento atual — antes ficava PENDING pra sempre."""
    from finance.interface.commissions import run_weekly_closing
    from finance.models import Commission, PaymentRequest
    from users.auth.models import User

    payee = User.objects.create_user(external_id=uuid.uuid4())
    c = Commission.objects.create(
        payee=payee,
        payee_role=Commission.Role.PROMOTER,
        source_type=Commission.Source.LEAD,
        source_external_id=uuid.uuid4(),
        amount=1,
        status=Commission.Status.PENDING,
    )
    # força o created_at pra 10 dias atrás (semana anterior), driblando o auto_now_add
    old = timezone.now() - timedelta(days=10)
    Commission.objects.filter(pk=c.pk).update(created_at=old)

    run_weekly_closing()

    c.refresh_from_db()
    assert c.status == Commission.Status.PROCESSED, "comissão atrasada ficou órfã"
    assert PaymentRequest.objects.filter(payee=payee).exists()


# ─────────────────── G7: promotor suspenso não recebe ───────────────────
def test_g7_suspenso_pula_comissao_ativo_credita():
    """`_apply_effects` de lead pago: promotor SUSPENSO → credit_commission NÃO é chamado; promotor
    ATIVO → é chamado. O resto do efeito (enrollment/hub) é mockado — só a guarda está sob teste."""
    from unittest.mock import patch

    from users.auth.models import User
    from users.roles.lead import service as lead_service

    promoter_user = User.objects.create_user(external_id=uuid.uuid4())
    client = User.objects.create_user(external_id=uuid.uuid4())

    class _Lead:
        self_study = False
        promoter = promoter_user
        user = client
        external_id = uuid.uuid4()

    def run(suspenso: bool) -> bool:
        with (
            patch("users.roles.promoter.models.Promoter.objects") as pobj,
            patch("finance.interface.commissions.credit_commission") as credit,
            patch.object(lead_service.hub_iface, "hub_of", return_value=object()),
            patch("users.roles.enrollment.service.create_from_lead"),
            patch("users.roles.promoter.service.maybe_auto_enroll_bolsista"),
        ):
            pobj.filter.return_value.exists.return_value = suspenso
            lead_service._apply_effects(_Lead())
            return credit.called

    assert run(suspenso=True) is False, "promotor suspenso recebeu comissão"
    assert run(suspenso=False) is True, "promotor ativo não recebeu comissão"
