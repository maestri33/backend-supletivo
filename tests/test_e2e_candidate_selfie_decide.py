"""E2E: coordenador decide selfie/documento do candidato em REVISÃO.

Quando a IA fica em dúvida (status=REVIEW), o coordenador desempata.
- POST /candidates/{external_id}/selfie/decide
- POST /candidates/{external_id}/document/decide

Regras testadas:
1. selfie/decide approve → selfie_status=APPROVED, segue fluxo.
2. selfie/decide reject → selfie_status=REJECTED + motivo gravado.
3. selfie/decide quando NÃO está em REVIEW → 4xx SELFIE_NOT_IN_REVIEW.
4. selfie/decide de outro hub → NOT_HUB_COORDINATOR.
5. selfie/decide candidato inexistente → 404 CANDIDATE_NOT_FOUND.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from tests.conftest import auth_headers, _jwt_for


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
    from users.roles.candidate.models import Candidate
    from users.roles._selfie import SelfieStatus

    coord = _make_user(roles=["promoter", "coordinator"])
    hub = _make_hub(coord)
    user = _make_user(roles=["candidate"])
    cand = Candidate.objects.create(
        user=user,
        hub=hub,
        status=Candidate.Status.SELFIE,
        selfie_status=SelfieStatus.REVIEW,
        selfie_image="media/cand/selfie.jpg",
    )
    return {
        "coord": coord,
        "coord_token": _jwt_for(coord, roles=["coordinator"]),
        "hub": hub,
        "cand": cand,
    }


def _decide_selfie(client, cand_external_id, token, *, approve, reason=None):
    body = {"approve": approve}
    if reason is not None:
        body["reason"] = reason
    return client.post(
        f"/api/v1/leadership/candidates/{cand_external_id}/selfie/decide",
        data=json.dumps(body),
        content_type="application/json",
        **auth_headers(token),
    )


# ── selfie decide ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_selfie_decide_approve(client, scenario):
    """approve=True com selfie em REVIEW → selfie_status=APPROVED + selfie_verified=True."""
    cand = scenario["cand"]

    with patch("users.roles.candidate.service._complete_candidate"):
        resp = _decide_selfie(client, cand.external_id, scenario["coord_token"], approve=True)

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data["selfie_status"] == "approved"

    cand.refresh_from_db()
    assert cand.selfie_status == "approved"
    assert cand.selfie_verified is True


@pytest.mark.django_db
def test_selfie_decide_reject_com_motivo(client, scenario):
    """approve=False com reason → selfie_status=REJECTED + descrição gravada."""
    cand = scenario["cand"]

    with patch("users.roles.candidate.service._notify_selfie_rejected"):
        resp = _decide_selfie(client, cand.external_id, scenario["coord_token"], approve=False, reason="rosto não visível")

    assert resp.status_code == 200, resp.content
    assert resp.json()["selfie_status"] == "rejected"

    cand.refresh_from_db()
    assert cand.selfie_status == "rejected"
    assert cand.selfie_verified is False
    assert "rosto não visível" in (cand.selfie_description or "")


@pytest.mark.django_db
def test_selfie_decide_fora_de_review(client, scenario):
    """selfie já APPROVED (não REVIEW) → 4xx SELFIE_NOT_IN_REVIEW."""
    from users.roles._selfie import SelfieStatus

    scenario["cand"].selfie_status = SelfieStatus.APPROVED
    scenario["cand"].save(update_fields=["selfie_status"])

    resp = _decide_selfie(client, scenario["cand"].external_id, scenario["coord_token"], approve=True)
    assert resp.status_code in (400, 409, 422), resp.content
    assert "SELFIE_NOT_IN_REVIEW" in json.dumps(resp.json())


@pytest.mark.django_db
def test_selfie_decide_outro_hub(client, scenario):
    """coordenador de outro hub → NOT_HUB_COORDINATOR."""
    outro = _make_user(roles=["promoter", "coordinator"])
    _make_hub(outro, brand="outro")
    outro_token = _jwt_for(outro, roles=["coordinator"])

    resp = _decide_selfie(client, scenario["cand"].external_id, outro_token, approve=True)
    assert resp.status_code in (400, 403, 409, 422), resp.content
    assert "NOT_HUB_COORDINATOR" in json.dumps(resp.json())


@pytest.mark.django_db
def test_selfie_decide_candidate_inexistente(client, scenario):
    """external_id inválido → CANDIDATE_NOT_FOUND."""
    resp = _decide_selfie(client, uuid.uuid4(), scenario["coord_token"], approve=True)
    assert resp.status_code in (404, 422), resp.content
    assert "CANDIDATE_NOT_FOUND" in json.dumps(resp.json())
