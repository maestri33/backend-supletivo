"""Testes do fluxo de autenticação (check/login/whoami/refresh).

Mocka as integrações externas (WhatsApp OTP, CPFHub) para validar
apenas a lógica da camada API em isolamento.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from tests.conftest import auth_headers, _make_user


# ── /auth/check ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_check_usuario_inexistente_retorna_not_found(client):
    """check com CPF/phone desconhecido retorna found=False."""
    with patch("users.auth.interface.check") as mock_check:
        mock_check.return_value = {
            "found": False,
            "external_id": None,
            "otp_sent": False,
            "otp_wait": None,
            "whatsapp": None,
            "roles": None,
        }
        resp = client.post(
            "/api/v1/clients/auth/check",
            data=json.dumps({"cpf": "99999999999"}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["external_id"] is None


@pytest.mark.django_db
def test_check_usuario_existente_retorna_found_e_otp(client):
    """check com CPF/phone conhecido retorna found=True + otp_sent=True."""
    with patch("users.auth.interface.check") as mock_check:
        mock_check.return_value = {
            "found": True,
            "external_id": str(uuid.uuid4()),
            "otp_sent": True,
            "otp_wait": None,
            "whatsapp": True,
            "roles": ["lead"],
        }
        resp = client.post(
            "/api/v1/clients/auth/check",
            data=json.dumps({"cpf": "00000000000"}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["otp_sent"] is True
    assert "external_id" in data


@pytest.mark.django_db
def test_login_otp_invalido_retorna_erro_dominio(client):
    """login com OTP errado propaga DomainError → envelope {detail, code}."""
    from users.exceptions import ValidationError as DomainValidationError

    user = _make_user(roles=["lead"])

    with patch("users.auth.interface.login") as mock_login:
        mock_login.side_effect = DomainValidationError("OTP inválido.", code="OTP_INVALID")
        resp = client.post(
            "/api/v1/clients/auth/login",
            data=json.dumps({"external_id": str(user.external_id), "otp": "000000"}),
            content_type="application/json",
        )
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == "OTP_INVALID"
    assert "detail" in data


@pytest.mark.django_db
def test_login_usuario_nao_no_funil_retorna_403(client):
    """login de user sem role do funil (ex.: só superuser) → 403 NOT_IN_FUNNEL."""
    user = _make_user(is_superuser=True)  # sem roles de funil

    resp = client.post(
        "/api/v1/clients/auth/login",
        data=json.dumps({"external_id": str(user.external_id), "otp": "123456"}),
        content_type="application/json",
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["code"] == "NOT_IN_FUNNEL"


# ── /whoami ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_whoami_retorna_principal_correto(client, lead_user, lead_token):
    """whoami com token válido retorna external_id + roles."""
    resp = client.get(
        "/api/v1/clients/whoami",
        **auth_headers(lead_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["external_id"] == str(lead_user.external_id)
    assert "lead" in data["roles"]


@pytest.mark.django_db
def test_whoami_token_expirado_retorna_401(client):
    """Token expirado (manipulado) retorna 401 UNAUTHORIZED."""
    resp = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION="Bearer eyJhbGciOiJSUzI1NiJ9.invalido.assinatura",
    )
    assert resp.status_code == 401
    assert resp.json().get("code") == "UNAUTHORIZED"


# ── /auth/refresh ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_refresh_token_invalido_retorna_401(client):
    """refresh com token inválido retorna 401 SESSION_EXPIRED."""
    resp = client.post(
        "/api/v1/clients/auth/refresh",
        data=json.dumps({"refresh_token": "token_fake_invalido"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == "SESSION_EXPIRED"
