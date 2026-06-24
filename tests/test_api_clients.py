"""Testes do grupo clients — funil do aluno.

Cobre: pricing (público), lead/me, enrollment/me, gates de role.
Integrações externas mockadas.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import auth_headers, _make_user, _jwt_for


# ── pricing público ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_pricing_publico_sem_auth(client):
    """GET /pricing retorna preços sem autenticação."""
    with patch("users.roles.lead.interface.pricing") as mock_pricing:
        mock_pricing.return_value = {
            "pix": "999.00",
            "card": {"installments": 12, "installment": "99.00", "total": "1188.00"},
        }
        resp = client.get("/api/v1/clients/pricing")
    assert resp.status_code == 200
    data = resp.json()
    assert "pix" in data
    assert "card" in data


# ── gate de role ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_enrollment_me_sem_token_retorna_401(client):
    """GET /enrollment/me sem token → 401."""
    resp = client.get("/api/v1/clients/enrollment/me")
    assert resp.status_code == 401
    assert resp.json().get("code") == "UNAUTHORIZED"


@pytest.mark.django_db
def test_enrollment_me_role_errada_retorna_403(client, lead_user, lead_token):
    """GET /enrollment/me com role=lead (sem enrollment) → 403 FORBIDDEN_ROLE."""
    resp = client.get(
        "/api/v1/clients/enrollment/me",
        **auth_headers(lead_token),
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "FORBIDDEN_ROLE"


@pytest.mark.django_db
def test_student_me_sem_role_student_retorna_403(client, lead_user, lead_token):
    """GET /student/me com role=lead → 403."""
    resp = client.get(
        "/api/v1/clients/student/me",
        **auth_headers(lead_token),
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "FORBIDDEN_ROLE"


# ── lead/me ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_lead_me_retorna_lead_do_usuario(client, lead_user, lead_token):
    """GET /lead/me retorna os dados do lead do usuário logado."""
    mock_lead = MagicMock()
    mock_lead_dict = {
        "external_id": str(uuid.uuid4()),
        "status": "pending",
        "failed_reason": None,
        "created_at": "2026-01-01T00:00:00",
        "customer": {"name": "Teste", "phone": "11999990000", "email": "t@e.com", "cpf": "00000000000"},
        "promoter": {"external_id": str(uuid.uuid4()), "name": "Promotor"},
        "checkout": None,
    }

    with patch("users.roles.lead.interface.get_for_user_external_id") as mock_get, \
         patch("users.roles.lead.interface.lead_self_dict") as mock_dict:
        mock_get.return_value = mock_lead
        mock_dict.return_value = mock_lead_dict

        resp = client.get(
            "/api/v1/clients/lead/me",
            **auth_headers(lead_token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "external_id" in data
    assert data["status"] == "pending"


@pytest.mark.django_db
def test_lead_me_sem_lead_retorna_404(client, lead_user, lead_token):
    """GET /lead/me quando usuário não tem lead → 404 LEAD_NOT_FOUND."""
    with patch("users.roles.lead.interface.get_for_user_external_id") as mock_get:
        mock_get.return_value = None
        resp = client.get(
            "/api/v1/clients/lead/me",
            **auth_headers(lead_token),
        )
    assert resp.status_code == 404
    assert resp.json().get("code") == "LEAD_NOT_FOUND"


# ── register ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_register_cpf_duplicado_retorna_409(client):
    """POST /auth/register com CPF já existente → 409 CPF_EXISTS."""
    from users.exceptions import Conflict

    with patch("users.roles.lead.interface.create_lead") as mock_create:
        mock_create.side_effect = Conflict("CPF já cadastrado.", code="CPF_EXISTS")
        resp = client.post(
            "/api/v1/clients/auth/register",
            data=json.dumps({
                "cpf": "00000000000",
                "phone": "11999990000",
                "email": "novo@example.com",
            }),
            content_type="application/json",
        )
    assert resp.status_code == 409
    data = resp.json()
    assert data["code"] == "CPF_EXISTS"


@pytest.mark.django_db
def test_register_body_invalido_retorna_422(client):
    """POST /auth/register com body incompleto → 422 VALIDATION_ERROR."""
    resp = client.post(
        "/api/v1/clients/auth/register",
        data=json.dumps({"cpf": "00000000000"}),  # falta phone e email
        content_type="application/json",
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == "VALIDATION_ERROR"
