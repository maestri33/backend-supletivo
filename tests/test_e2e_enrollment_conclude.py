"""E2E: coordenador conclui matrícula → enrollment vira student.

Cobre o fluxo crítico do app-v7m que mexe em R$ e credencial do aluno:
- coordenador autenticado
- enrollment em AWAITING_RELEASE
- 1ª fee PAGA + 2ª fee AGENDADA (criadas direto na fila do finance)
- POST /enrollments/{id}/conclude com login/senha da plataforma parceira
- assert: status=COMPLETED + Student criado com platform_login + role student

Regras testadas (uma asserção por regra):
1. happy path → 200 + status COMPLETED + Student existe
2. faltando 1ª paga → 409 FEES_INCOMPLETE com missing=['first_fee_paid']
3. faltando 2ª agendada → 409 FEES_INCOMPLETE com missing=['second_fee_scheduled']
4. login/senha vazios → 422
5. coordenador de OUTRO hub → 4xx NOT_HUB_COORDINATOR
6. status errado (não AWAITING_RELEASE/FEE_PAID/FEE_SCHEDULED) → 409 WRONG_STATUS
7. platform_login já usado por outro Student → conflito
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.conftest import auth_headers, _jwt_for


def _make_user(*, roles=None):
    """Variante local do helper do conftest, com profile ÚNICO por chamada
    (o do conftest hardcoda cpf/phone/email e quebra com unique constraints
    quando criamos vários users no mesmo teste)."""
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


# ── helpers de cenário ──────────────────────────────────────────────────────


def _make_address():
    from users.address.models import Address

    return Address.objects.create(zipcode="01310100", street="Av Paulista", number="1000", city="São Paulo", state="SP")


def _make_hub(coordinator_user, *, brand="supletivo", is_default=False):
    from hub.models import Hub

    return Hub.objects.create(
        address=_make_address(),
        brand=brand,
        coordinator=coordinator_user,
        is_default=is_default,
    )


def _make_promoter(db):
    return _make_user(roles=["promoter"])


def _make_enrollment(*, user, promoter, hub, status):
    from users.roles.enrollment.models import Enrollment

    return Enrollment.objects.create(
        user=user,
        promoter=promoter,
        hub=hub,
        status=status,
    )


def _seed_fee_first_paid(enr):
    """Cria PaymentRequest da 1ª parcela como PAGA (mesma referência que o service usa)."""
    from finance.models import PaymentRequest

    return PaymentRequest.objects.create(
        external_reference=f"fee_enr_{enr.external_id}_now",
        kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE,
        amount=Decimal("999.00"),
        qrcode_payload="fake-qr-1",
        supplier_name="credenciador",
        source_type=PaymentRequest.SourceType.ENROLLMENT,
        source_external_id=enr.external_id,
        status=PaymentRequest.Status.PAID,
    )


def _seed_fee_second_scheduled(enr):
    """Cria PaymentRequest da 2ª parcela como AGENDADA."""
    from datetime import datetime, timezone, timedelta
    from finance.models import PaymentRequest

    return PaymentRequest.objects.create(
        external_reference=f"fee_enr_{enr.external_id}_due",
        kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE,
        amount=Decimal("999.00"),
        qrcode_payload="fake-qr-2",
        supplier_name="credenciador",
        scheduled_for=datetime.now(tz=timezone.utc) + timedelta(days=30),
        source_type=PaymentRequest.SourceType.ENROLLMENT,
        source_external_id=enr.external_id,
        status=PaymentRequest.Status.QUEUED,
    )


@pytest.fixture
def scenario(db):
    """Cenário base: coordenador + hub + candidato com enrollment em AWAITING_RELEASE."""
    coord = _make_user(roles=["promoter", "coordinator"])
    hub = _make_hub(coord)
    promoter = _make_user(roles=["promoter"])
    candidate = _make_user(roles=["enrollment"])
    from users.roles.enrollment.models import Enrollment

    enr = _make_enrollment(
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


# ── helper de chamada ──────────────────────────────────────────────────────


def _conclude(client, enr_external_id, token, *, login="aluno_001", password="senha_inicial_123", url=None):
    body = {"platform_login": login, "platform_password": password}
    if url:
        body["platform_url"] = url
    return client.post(
        f"/api/v1/leadership/enrollments/{enr_external_id}/conclude",
        data=json.dumps(body),
        content_type="application/json",
        **auth_headers(token),
    )


# ─────────────────────────── TESTES ──────────────────────────────────────


@pytest.mark.django_db
def test_conclude_happy_path(client, scenario):
    """1ª paga + 2ª agendada + login/senha → 200, vira student."""
    enr = scenario["enr"]
    _seed_fee_first_paid(enr)
    _seed_fee_second_scheduled(enr)

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = _conclude(client, enr.external_id, scenario["coord_token"], login="aluno_42")

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data["status"] == "completed"
    assert data["external_id"] == str(enr.external_id)

    # estado real no banco
    enr.refresh_from_db()
    assert enr.status == "completed"

    from users.roles.student.models import Student
    from users.roles.models import UserRole

    student = Student.objects.filter(user=scenario["candidate"]).first()
    assert student is not None
    assert student.platform_login == "aluno_42"
    assert student.platform_password == "senha_inicial_123"
    assert student.hub_id == scenario["hub"].id

    assert UserRole.objects.filter(user=scenario["candidate"], role="student").exists()


@pytest.mark.django_db
def test_conclude_falta_primeira_paga(client, scenario):
    """só a 2ª agendada → 409 FEES_INCOMPLETE com missing=['first_fee_paid']."""
    _seed_fee_second_scheduled(scenario["enr"])

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = _conclude(client, scenario["enr"].external_id, scenario["coord_token"])

    assert resp.status_code == 409, resp.content
    body = resp.json()
    assert body.get("code") == "FEES_INCOMPLETE"
    missing = body.get("missing") or body.get("extra", {}).get("missing") or []
    assert "first_fee_paid" in missing


@pytest.mark.django_db
def test_conclude_falta_segunda_agendada(client, scenario):
    """só a 1ª paga → 409 FEES_INCOMPLETE com missing=['second_fee_scheduled']."""
    _seed_fee_first_paid(scenario["enr"])

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = _conclude(client, scenario["enr"].external_id, scenario["coord_token"])

    assert resp.status_code == 409, resp.content
    body = resp.json()
    assert body.get("code") == "FEES_INCOMPLETE"
    missing = body.get("missing") or body.get("extra", {}).get("missing") or []
    assert "second_fee_scheduled" in missing


@pytest.mark.django_db
def test_conclude_credenciais_vazias(client, scenario):
    """login ou senha vazios → 422 (validação no schema ConcludeIn).

    Defesa no backend (não só no proxy Next): o schema usa StringConstraints
    com min_length=1 + strip_whitespace, então quem bater direto na API com
    credencial vazia leva 422 antes de chegar no service. Sem isso, criaria
    Student órfão sem como entrar na plataforma."""
    _seed_fee_first_paid(scenario["enr"])
    _seed_fee_second_scheduled(scenario["enr"])

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = client.post(
            f"/api/v1/leadership/enrollments/{scenario['enr'].external_id}/conclude",
            data=json.dumps({"platform_login": "", "platform_password": ""}),
            content_type="application/json",
            **auth_headers(scenario["coord_token"]),
        )
    assert resp.status_code == 422, resp.content


@pytest.mark.django_db
def test_conclude_coordenador_de_outro_hub(client, scenario):
    """coordenador que NÃO coordena o hub da matrícula → NOT_HUB_COORDINATOR."""
    other_coord = _make_user(roles=["promoter", "coordinator"])
    _make_hub(other_coord, brand="outroPolo")
    other_token = _jwt_for(other_coord, roles=["coordinator"])
    _seed_fee_first_paid(scenario["enr"])
    _seed_fee_second_scheduled(scenario["enr"])

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = _conclude(client, scenario["enr"].external_id, other_token)

    assert resp.status_code in (400, 403, 409, 422), resp.content
    body = resp.json()
    assert "NOT_HUB_COORDINATOR" in json.dumps(body)


@pytest.mark.django_db
def test_conclude_status_errado(client, scenario):
    """enrollment ainda em RG (não chegou em AWAITING_RELEASE) → 409 WRONG_STATUS."""
    from users.roles.enrollment.models import Enrollment

    scenario["enr"].status = Enrollment.Status.RG
    scenario["enr"].save(update_fields=["status"])

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = _conclude(client, scenario["enr"].external_id, scenario["coord_token"])

    assert resp.status_code == 409, resp.content
    assert resp.json().get("code") == "WRONG_STATUS"


@pytest.mark.django_db
def test_conclude_platform_login_duplicado(client, scenario):
    """outro Student já usa o mesmo platform_login → erro antes de promover."""
    # 1º conclude — deve criar student com login "aluno_X"
    _seed_fee_first_paid(scenario["enr"])
    _seed_fee_second_scheduled(scenario["enr"])

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        ok = _conclude(client, scenario["enr"].external_id, scenario["coord_token"], login="aluno_X")
    assert ok.status_code == 200

    # 2º cenário no mesmo hub: novo candidato/enrollment tentando o mesmo login
    cand2 = _make_user(roles=["candidate"])
    enr2 = _make_enrollment(
        user=cand2,
        promoter=scenario["promoter"],
        hub=scenario["hub"],
        status=scenario["enr"].Status.AWAITING_RELEASE,
    )
    _seed_fee_first_paid(enr2)
    _seed_fee_second_scheduled(enr2)

    with patch("users.roles.enrollment.service._notify_released"), \
         patch("users.roles.enrollment.service._notify_credentials"):
        resp = _conclude(client, enr2.external_id, scenario["coord_token"], login="aluno_X")

    # tem que rejeitar antes de promover (não vira student com login duplicado).
    assert resp.status_code >= 400, resp.content
    enr2.refresh_from_db()
    assert enr2.status != "completed"
