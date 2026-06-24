"""Testes do grupo collaborators — funil do colaborador (candidato/treino/promotor).

Cobre: gates de role, candidate/me, promoter/me, training, register.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import auth_headers, _make_user, _jwt_for


# ── gates de role ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_candidate_me_sem_token_retorna_401(client):
    resp = client.get("/api/v1/collaborators/candidate/me")
    assert resp.status_code == 401
    assert resp.json().get("code") == "UNAUTHORIZED"


@pytest.mark.django_db
def test_promoter_me_sem_role_promoter_retorna_403(client, candidate_user, candidate_token):
    """candidate sem role promoter → 403 ao tentar /promoter/me."""
    resp = client.get(
        "/api/v1/collaborators/promoter/me",
        **auth_headers(candidate_token),
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "FORBIDDEN_ROLE"


@pytest.mark.django_db
def test_training_materials_sem_role_promoter_retorna_403(client, candidate_user, candidate_token):
    """candidate não pode acessar /training/materials (exige promoter)."""
    resp = client.get(
        "/api/v1/collaborators/training/materials",
        **auth_headers(candidate_token),
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "FORBIDDEN_ROLE"


# ── candidate/me ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_candidate_me_retorna_dados_do_candidato(client, candidate_user, candidate_token):
    """GET /candidate/me retorna o me_dict do candidato."""
    mock_cand = MagicMock()
    mock_me = {
        "external_id": str(uuid.uuid4()),
        "status": "profile",
        "hub_external_id": str(uuid.uuid4()),
        "pix_validated": False,
        "selfie_verified": False,
        "selfie_status": None,
        "profile": None,
        "address": None,
        "documents": None,
        "selfie": None,
    }

    with patch("users.roles.candidate.interface.get_for_user_external_id") as mock_get, \
         patch("users.roles.candidate.interface.me_dict") as mock_dict:
        mock_get.return_value = mock_cand
        mock_dict.return_value = mock_me

        resp = client.get(
            "/api/v1/collaborators/candidate/me",
            **auth_headers(candidate_token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "external_id" in data
    assert data["status"] == "profile"


@pytest.mark.django_db
def test_candidate_me_sem_candidato_retorna_404(client, candidate_user, candidate_token):
    """GET /candidate/me sem candidato associado → 404 CANDIDATE_NOT_FOUND."""
    with patch("users.roles.candidate.interface.get_for_user_external_id") as mock_get:
        mock_get.return_value = None
        resp = client.get(
            "/api/v1/collaborators/candidate/me",
            **auth_headers(candidate_token),
        )
    assert resp.status_code == 404
    assert resp.json().get("code") == "CANDIDATE_NOT_FOUND"


# ── promoter/me ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_promoter_me_retorna_dados_do_promotor(client, promoter_user, promoter_token):
    """GET /promoter/me retorna o painel do promotor."""
    mock_promoter = MagicMock()
    mock_promoter_dict = {
        "external_id": str(uuid.uuid4()),
        "status": "active",
        "hub_external_id": str(uuid.uuid4()),
        "ref_url": "https://example.com/?ref=abc",
        "locked": False,
        "pending_materials": [],
    }

    with patch("users.roles.promoter.interface.get_by_user_external_id") as mock_get, \
         patch("users.roles.promoter.interface.to_dict") as mock_dict:
        mock_get.return_value = mock_promoter
        mock_dict.return_value = mock_promoter_dict

        resp = client.get(
            "/api/v1/collaborators/promoter/me",
            **auth_headers(promoter_token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "external_id" in data
    assert data["locked"] is False


@pytest.mark.django_db
def test_promoter_me_sem_promotor_retorna_404(client, promoter_user, promoter_token):
    """GET /promoter/me sem promotor → 404 PROMOTER_NOT_FOUND."""
    with patch("users.roles.promoter.interface.get_by_user_external_id") as mock_get:
        mock_get.return_value = None
        resp = client.get(
            "/api/v1/collaborators/promoter/me",
            **auth_headers(promoter_token),
        )
    assert resp.status_code == 404
    assert resp.json().get("code") == "PROMOTER_NOT_FOUND"


# ── register candidato ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_register_candidato_phone_duplicado_retorna_409(client):
    """POST /collaborators/auth/register com phone já existente → 409 PHONE_EXISTS."""
    from users.exceptions import Conflict

    with patch("users.roles.candidate.interface.create_candidate") as mock_create:
        mock_create.side_effect = Conflict("Telefone já cadastrado.", code="PHONE_EXISTS")
        resp = client.post(
            "/api/v1/collaborators/auth/register",
            data=json.dumps({
                "cpf": "11111111111",
                "phone": "11999990000",
                "email": "novo@example.com",
            }),
            content_type="application/json",
        )
    assert resp.status_code == 409
    assert resp.json().get("code") == "PHONE_EXISTS"


# ── training/submit ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_training_submit_ja_em_correcao_retorna_409(client, promoter_user, promoter_token):
    """POST /training/submissions quando já há submissão em correção → 409 ALREADY_GRADING."""
    from users.exceptions import Conflict

    with patch("users.roles.training.interface.submit") as mock_submit:
        mock_submit.side_effect = Conflict(
            "Já há uma submissão em correção.", code="ALREADY_GRADING"
        )
        resp = client.post(
            "/api/v1/collaborators/training/submissions",
            data=json.dumps({
                "material_external_id": str(uuid.uuid4()),
                "answer": "minha resposta",
            }),
            content_type="application/json",
            **auth_headers(promoter_token),
        )
    assert resp.status_code == 409
    assert resp.json().get("code") == "ALREADY_GRADING"
