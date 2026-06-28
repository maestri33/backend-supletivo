"""E2E: coordenador despacha as parcelas da taxa de matrícula.

Cobre os outros 2 endpoints críticos do fluxo financeiro (irmãos do `conclude`):

- POST /enrollments/{id}/fee/pay      — 1ª parcela (à vista)
- POST /enrollments/{id}/fee/schedule — 2ª parcela (agendada pelo vencimento do QR)

Regras testadas:
1. pay_fee happy → 200, status preserva, PaymentRequest criado com ref `_now`.
2. pay_fee idempotente — 1ª já paga → 409 FEE_ALREADY_PAID.
3. pay_fee de outro hub → 422 NOT_HUB_COORDINATOR.
4. pay_fee status errado → 409 WRONG_STATUS.
5. schedule_fee happy → 200, status vira FEE_SCHEDULED, PaymentRequest agendado.
6. schedule_fee QR sem vencimento → 422 FEE_QR_NO_DUE_DATE.
7. schedule_fee já agendada → 409 FEE_ALREADY_SCHEDULED.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.conftest import auth_headers, _jwt_for


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_user(*, roles=None):
    from users.auth.models import User
    from users.profiles.models import Profile
    from users.roles.models import UserRole

    ext = uuid.uuid4()
    short = ext.hex[:10]
    user = User.objects.create_user(external_id=ext)
    Profile.objects.create(
        user=user,
        name=f"Teste {short}",
        cpf=short.ljust(11, "0")[:11],
        phone=f"119{short[:8]}",
        email=f"{short}@example.com",
    )
    for role in roles or []:
        UserRole.objects.create(user=user, role=role)
    return user


def _make_address():
    from users.address.models import Address

    return Address.objects.create(zipcode="01310100", city="São Paulo", state="SP")


def _make_hub(coord, *, brand="supletivo"):
    from hub.models import Hub

    return Hub.objects.create(address=_make_address(), brand=brand, coordinator=coord)


@pytest.fixture
def scenario(db):
    from users.roles.enrollment.models import Enrollment

    coord = _make_user(roles=["promoter", "coordinator"])
    hub = _make_hub(coord)
    promoter = _make_user(roles=["promoter"])
    candidate = _make_user(roles=["enrollment"])
    enr = Enrollment.objects.create(
        user=candidate,
        promoter=promoter,
        hub=hub,
        status=Enrollment.Status.AWAITING_RELEASE,
    )
    return {
        "coord": coord,
        "coord_token": _jwt_for(coord, roles=["coordinator"]),
        "hub": hub,
        "promoter": promoter,
        "candidate": candidate,
        "enr": enr,
    }


def _seed_first_paid(enr):
    from finance.models import PaymentRequest

    return PaymentRequest.objects.create(
        external_reference=f"fee_enr_{enr.external_id}_now",
        kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE,
        amount=Decimal("999.00"),
        supplier_name="credenciador",
        source_type=PaymentRequest.SourceType.ENROLLMENT,
        source_external_id=enr.external_id,
        status=PaymentRequest.Status.PAID,
    )


def _seed_second_scheduled(enr):
    from finance.models import PaymentRequest

    return PaymentRequest.objects.create(
        external_reference=f"fee_enr_{enr.external_id}_due",
        kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE,
        amount=Decimal("999.00"),
        scheduled_for=datetime.now(tz=timezone.utc) + timedelta(days=30),
        source_type=PaymentRequest.SourceType.ENROLLMENT,
        source_external_id=enr.external_id,
        status=PaymentRequest.Status.QUEUED,
    )


def _call_fee(client, enr_id, token, action, qr="fake-qr", amount=None):
    """action ∈ {'pay', 'schedule'}"""
    body = {"qr_code": qr}
    if amount is not None:
        body["amount"] = str(amount)
    return client.post(
        f"/api/v1/leadership/enrollments/{enr_id}/fee/{action}",
        data=json.dumps(body),
        content_type="application/json",
        **auth_headers(token),
    )


# ── plan_qr_payment mock helpers ────────────────────────────────────────────


def _plan_imediato():
    return {"amount": Decimal("999.00"), "scheduled_for": None, "due_date": None}


def _plan_agendado():
    return {
        "amount": Decimal("999.00"),
        "scheduled_for": datetime.now(tz=timezone.utc) + timedelta(days=30),
        "due_date": "2026-07-28",
    }


# ── pay_fee ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_pay_fee_happy(client, scenario):
    """pay /fee/pay sem nenhuma fee → enfileira PaymentRequest com ref `_now`."""
    enr = scenario["enr"]

    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_imediato()), \
         patch("finance.interface.fees.request_fee_payment") as req:
        from finance.models import PaymentRequest

        req.return_value = PaymentRequest(
            external_reference=f"fee_enr_{enr.external_id}_now",
            amount=Decimal("999.00"),
            status=PaymentRequest.Status.QUEUED,
        )
        resp = _call_fee(client, enr.external_id, scenario["coord_token"], "pay")

    assert resp.status_code == 200, resp.content
    data = resp.json()
    # EnrollmentFeesOut só expõe os fatos das parcelas (sem external_id/status).
    assert "first_paid" in data and "second_scheduled" in data
    # Verifica que o caller passou source_type=ENROLLMENT + ref `_now`.
    call_kwargs = req.call_args.kwargs
    assert call_kwargs["external_reference"] == f"fee_enr_{enr.external_id}_now"
    assert call_kwargs["scheduled_for"] is None  # imediato


@pytest.mark.django_db
def test_pay_fee_ja_paga(client, scenario):
    """1ª já PAGA → 409 FEE_ALREADY_PAID (idempotência)."""
    _seed_first_paid(scenario["enr"])

    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_imediato()):
        resp = _call_fee(client, scenario["enr"].external_id, scenario["coord_token"], "pay")

    assert resp.status_code == 409, resp.content
    assert resp.json().get("code") == "FEE_ALREADY_PAID"


@pytest.mark.django_db
def test_pay_fee_outro_hub(client, scenario):
    """coordenador de outro hub → 422 NOT_HUB_COORDINATOR."""
    outro = _make_user(roles=["promoter", "coordinator"])
    _make_hub(outro, brand="outro")
    outro_token = _jwt_for(outro, roles=["coordinator"])

    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_imediato()):
        resp = _call_fee(client, scenario["enr"].external_id, outro_token, "pay")

    assert resp.status_code in (400, 403, 409, 422), resp.content
    assert "NOT_HUB_COORDINATOR" in json.dumps(resp.json())


@pytest.mark.django_db
def test_pay_fee_status_errado(client, scenario):
    """enrollment ainda em RG → 409 WRONG_STATUS."""
    from users.roles.enrollment.models import Enrollment

    scenario["enr"].status = Enrollment.Status.RG
    scenario["enr"].save(update_fields=["status"])

    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_imediato()):
        resp = _call_fee(client, scenario["enr"].external_id, scenario["coord_token"], "pay")

    assert resp.status_code == 409, resp.content
    assert resp.json().get("code") == "WRONG_STATUS"


# ── schedule_fee ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_schedule_fee_happy(client, scenario):
    """schedule /fee/schedule com QR que TEM vencimento → muda status pra FEE_SCHEDULED."""
    enr = scenario["enr"]

    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_agendado()), \
         patch("finance.interface.fees.request_fee_payment") as req, \
         patch("users.roles.enrollment.service._notify_fee_event"):
        from finance.models import PaymentRequest

        req.return_value = PaymentRequest(
            external_reference=f"fee_enr_{enr.external_id}_due",
            amount=Decimal("999.00"),
            status=PaymentRequest.Status.QUEUED,
        )
        resp = _call_fee(client, enr.external_id, scenario["coord_token"], "schedule")

    assert resp.status_code == 200, resp.content
    # A regra principal: status do enrollment muda NA HORA pra fee_scheduled
    # (Victor 2026-06-12). second_scheduled lê da fila real do finance,
    # então depende da PaymentRequest ter sido persistida — aqui mocamos request_fee_payment.
    enr.refresh_from_db()
    assert enr.status == "fee_scheduled"

    call_kwargs = req.call_args.kwargs
    assert call_kwargs["external_reference"] == f"fee_enr_{enr.external_id}_due"
    assert call_kwargs["scheduled_for"] is not None


@pytest.mark.django_db
def test_schedule_fee_qr_sem_vencimento(client, scenario):
    """QR sem due_date → 422 FEE_QR_NO_DUE_DATE."""
    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_imediato()):
        resp = _call_fee(client, scenario["enr"].external_id, scenario["coord_token"], "schedule")

    assert resp.status_code in (400, 422), resp.content
    assert resp.json().get("code") == "FEE_QR_NO_DUE_DATE"


@pytest.mark.django_db
def test_schedule_fee_ja_agendada(client, scenario):
    """2ª já agendada → 409 FEE_ALREADY_SCHEDULED."""
    _seed_second_scheduled(scenario["enr"])

    with patch("users.roles.enrollment.service._plan_fee_qr", return_value=_plan_agendado()):
        resp = _call_fee(client, scenario["enr"].external_id, scenario["coord_token"], "schedule")

    assert resp.status_code == 409, resp.content
    assert resp.json().get("code") == "FEE_ALREADY_SCHEDULED"
