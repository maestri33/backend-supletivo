"""Testes do grupo staff — administração (superuser-only).

Valida: gate de superuser, envelope de erro uniforme (fix dos HttpError),
operações de hub e integrações.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import auth_headers


# ── gate de superuser ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_staff_sem_token_retorna_401(client):
    resp = client.get("/api/v1/staff/hubs")
    assert resp.status_code == 401
    assert resp.json().get("code") == "UNAUTHORIZED"


@pytest.mark.django_db
def test_staff_usuario_comum_retorna_403(client, lead_user, lead_token):
    """User com role=lead não é staff → 403 STAFF_ONLY."""
    resp = client.get(
        "/api/v1/staff/hubs",
        **auth_headers(lead_token),
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "STAFF_ONLY"


# ── hubs ──────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_hubs_retorna_lista(client, staff_user, staff_token):
    """GET /staff/hubs retorna lista de hubs."""
    with patch("hub.interface.list_hubs") as mock_list:
        mock_hub = MagicMock()
        mock_hub.external_id = uuid.uuid4()
        mock_hub.brand = "standard"
        mock_hub.coordinator = None
        mock_hub.is_default = True
        mock_list.return_value = [mock_hub]

        resp = client.get(
            "/api/v1/staff/hubs",
            **auth_headers(staff_token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["brand"] == "standard"


@pytest.mark.django_db
def test_create_hub_marca_invalida_retorna_422_envelope(client, staff_user, staff_token):
    """POST /staff/hubs com marca inválida → 422 com envelope {detail, code} (fix do HttpError)."""
    from hub.interface import HubError

    with patch("hub.interface.create_hub") as mock_create:
        mock_create.side_effect = HubError("Marca inválida.")
        resp = client.post(
            "/api/v1/staff/hubs",
            data=json.dumps({"brand": "marca_inexistente"}),
            content_type="application/json",
            **auth_headers(staff_token),
        )

    assert resp.status_code == 422
    data = resp.json()
    # CRUCIAL: valida que o envelope é consistente com o resto da API (fix do HttpError cru)
    assert "detail" in data
    assert "code" in data
    assert data["code"] == "HUB_ERROR"


@pytest.mark.django_db
def test_get_hub_inexistente_retorna_404_envelope(client, staff_user, staff_token):
    """PUT /staff/hubs/{id}/coordinator com hub inexistente → 404 com envelope."""
    from hub.interface import HubError

    with patch("hub.interface.set_coordinator") as mock_set:
        mock_set.side_effect = HubError("hub_not_found")
        resp = client.put(
            f"/api/v1/staff/hubs/{uuid.uuid4()}/coordinator",
            data=json.dumps({"coordinator_external_id": str(uuid.uuid4())}),
            content_type="application/json",
            **auth_headers(staff_token),
        )

    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "code" in data
    assert data["code"] == "HUB_NOT_FOUND"


# ── integrações ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_integration_inexistente_retorna_404_envelope(client, staff_user, staff_token):
    """GET /staff/integrations/{name} com nome inválido → 404 com envelope (fix do HttpError)."""
    with patch("integrations.status.integration_detail") as mock_detail:
        mock_detail.return_value = None
        resp = client.get(
            "/api/v1/staff/integrations/nao_existe",
            **auth_headers(staff_token),
        )

    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "code" in data
    assert data["code"] == "INTEGRATION_NOT_FOUND"


@pytest.mark.django_db
def test_list_all_leads_hub_inexistente_retorna_404_envelope(client, staff_user, staff_token):
    """GET /staff/leads?hub=<invalido> retorna 404 com envelope."""
    with patch("hub.interface.get_by_external_id") as mock_get:
        mock_get.return_value = None
        resp = client.get(
            f"/api/v1/staff/leads?hub={uuid.uuid4()}",
            **auth_headers(staff_token),
        )

    assert resp.status_code == 404
    data = resp.json()
    assert data.get("code") == "HUB_NOT_FOUND"


# ── system status ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_system_status_retorna_shape_correto(client, staff_user, staff_token):
    """GET /staff/system retorna os campos esperados de saúde do servidor."""
    resp = client.get(
        "/api/v1/staff/system",
        **auth_headers(staff_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "db_ok" in data
    assert "migrations_pending" in data
    assert "qcluster_alive" in data
    assert "debug" in data
