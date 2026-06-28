"""E2E: coordenador aprova/rejeita candidato → vira promoter.

Cobre o portão de entrada da rede de promotores:
- POST /candidates/{external_id}/approve  — vira promoter + recebe treino
- POST /candidates/{external_id}/reject   — fica rejected (soft, pode aprovar depois)

Regras testadas:
1. approve happy → promote candidate→promoter + cria Promoter + role 'promoter'.
2. approve em quem ainda não concluiu coleta → 409 WRONG_STATUS.
3. approve de outro hub → NOT_HUB_COORDINATOR.
4. approve de candidate inexistente → 404 CANDIDATE_NOT_FOUND.
5. approve em candidato REJECTED → ainda permite (rejeição é soft).
6. reject happy → status REJECTED, sem role nova.
7. reject de quem não concluiu → 409 WRONG_STATUS.
"""

from __future__ import annotations

import json
import uuid
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


def _make_candidate(*, hub, status):
    from users.roles.candidate.models import Candidate

    user = _make_user(roles=["candidate"])
    return Candidate.objects.create(user=user, hub=hub, status=status)


@pytest.fixture
def scenario(db):
    from users.roles.candidate.models import Candidate

    coord = _make_user(roles=["promoter", "coordinator"])
    hub = _make_hub(coord)
    cand = _make_candidate(hub=hub, status=Candidate.Status.COMPLETED)
    return {
        "coord": coord,
        "coord_token": _jwt_for(coord, roles=["coordinator"]),
        "hub": hub,
        "cand": cand,
    }


def _approve(client, cand_external_id, token):
    return client.post(
        f"/api/v1/leadership/candidates/{cand_external_id}/approve",
        data="{}",
        content_type="application/json",
        **auth_headers(token),
    )


def _reject(client, cand_external_id, token, reason="não passou"):
    return client.post(
        f"/api/v1/leadership/candidates/{cand_external_id}/reject",
        data=json.dumps({"reason": reason}),
        content_type="application/json",
        **auth_headers(token),
    )


# ── approve ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_approve_happy(client, scenario):
    """COMPLETED → APPROVED + Promoter criado + role 'promoter' + treino atribuído."""
    cand = scenario["cand"]

    with patch("users.roles.candidate.service._notify_became_promoter"), \
         patch("users.roles.training.interface.on_became_promoter", return_value=True):
        resp = _approve(client, cand.external_id, scenario["coord_token"])

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data["status"] == "approved"
    assert data["external_id"] == str(cand.external_id)

    cand.refresh_from_db()
    assert cand.status == "approved"

    from users.roles.promoter.models import Promoter
    from users.roles.models import UserRole

    promoter = Promoter.objects.filter(user=cand.user).first()
    assert promoter is not None
    assert promoter.hub_id == scenario["hub"].id

    # role candidate revogada + promoter ativa
    active = list(UserRole.objects.filter(user=cand.user, revoked_at__isnull=True).values_list("role", flat=True))
    assert "promoter" in active
    assert "candidate" not in active


@pytest.mark.django_db
def test_approve_quem_nao_concluiu(client, scenario):
    """status=SELFIE (não COMPLETED nem REJECTED) → 409 WRONG_STATUS."""
    from users.roles.candidate.models import Candidate

    scenario["cand"].status = Candidate.Status.SELFIE
    scenario["cand"].save(update_fields=["status"])

    resp = _approve(client, scenario["cand"].external_id, scenario["coord_token"])
    assert resp.status_code == 409, resp.content
    assert resp.json().get("code") == "WRONG_STATUS"


@pytest.mark.django_db
def test_approve_outro_hub(client, scenario):
    """coordenador de outro hub → NOT_HUB_COORDINATOR."""
    outro = _make_user(roles=["promoter", "coordinator"])
    _make_hub(outro, brand="outro")
    outro_token = _jwt_for(outro, roles=["coordinator"])

    resp = _approve(client, scenario["cand"].external_id, outro_token)
    assert resp.status_code in (400, 403, 409, 422), resp.content
    assert "NOT_HUB_COORDINATOR" in json.dumps(resp.json())


@pytest.mark.django_db
def test_approve_candidate_inexistente(client, scenario):
    """external_id que não existe → 404 CANDIDATE_NOT_FOUND."""
    fake = uuid.uuid4()
    resp = _approve(client, fake, scenario["coord_token"])
    assert resp.status_code in (404, 422), resp.content
    assert "CANDIDATE_NOT_FOUND" in json.dumps(resp.json())


@pytest.mark.django_db
def test_approve_apos_rejeicao(client, scenario):
    """REJECTED ainda é APROVÁVEL (rejeição é soft, Victor 2026-06-17)."""
    from users.roles.candidate.models import Candidate

    scenario["cand"].status = Candidate.Status.REJECTED
    scenario["cand"].save(update_fields=["status"])

    with patch("users.roles.candidate.service._notify_became_promoter"), \
         patch("users.roles.training.interface.on_became_promoter", return_value=False):
        resp = _approve(client, scenario["cand"].external_id, scenario["coord_token"])

    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "approved"


# ── reject ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_reject_happy(client, scenario):
    """COMPLETED → REJECTED (sem role nova)."""
    cand = scenario["cand"]

    with patch("users.roles.candidate.service._notify_candidate_rejected"):
        resp = _reject(client, cand.external_id, scenario["coord_token"])

    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "rejected"

    cand.refresh_from_db()
    assert cand.status == "rejected"

    # role candidate continua, sem promoter
    from users.roles.models import UserRole

    active = list(UserRole.objects.filter(user=cand.user, revoked_at__isnull=True).values_list("role", flat=True))
    assert "candidate" in active
    assert "promoter" not in active


@pytest.mark.django_db
def test_reject_quem_nao_concluiu(client, scenario):
    """status=SELFIE → 409 WRONG_STATUS (não pode rejeitar quem ainda está coletando)."""
    from users.roles.candidate.models import Candidate

    scenario["cand"].status = Candidate.Status.SELFIE
    scenario["cand"].save(update_fields=["status"])

    resp = _reject(client, scenario["cand"].external_id, scenario["coord_token"])
    assert resp.status_code == 409, resp.content
    assert resp.json().get("code") == "WRONG_STATUS"
