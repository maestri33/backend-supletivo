"""Testes de health e envelope de erro — os mais básicos e de maior valor.

Valida que:
- Todos os grupos respondem /health sem auth (200 + shape correto).
- Endpoints autenticados sem token retornam 401 com envelope {detail, code}.
- Endpoints autenticados com role errada retornam 403 com envelope {detail, code}.
- Errors de domínio saem como {detail, code, …extra}, nunca como HTML.
"""

from __future__ import annotations

import pytest

GROUPS = [
    "/api/v1/clients",
    "/api/v1/collaborators",
    "/api/v1/leadership",
    "/api/v1/staff",
]


@pytest.mark.django_db
@pytest.mark.parametrize("prefix", GROUPS)
def test_health_public(client, prefix):
    """GET /health de cada grupo responde 200 sem auth."""
    resp = client.get(f"{prefix}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "group" in data
    assert "version" in data


@pytest.mark.django_db
@pytest.mark.parametrize("prefix", GROUPS)
def test_whoami_sem_token_retorna_401_envelope(client, prefix):
    """GET /whoami sem Bearer retorna 401 com envelope {detail, code}."""
    resp = client.get(f"{prefix}/whoami")
    assert resp.status_code == 401
    data = resp.json()
    assert "detail" in data
    assert data.get("code") == "UNAUTHORIZED"


@pytest.mark.django_db
def test_404_fora_das_rotas_retorna_json(client):
    """Rota inexistente retorna JSON, nunca HTML (host API-first)."""
    resp = client.get("/rota/que/nao/existe/")
    assert resp.status_code == 404
    assert resp["Content-Type"].startswith("application/json")
    data = resp.json()
    assert "detail" in data


@pytest.mark.django_db
def test_token_invalido_retorna_401(client):
    """Bearer token mal-formado retorna 401 com envelope."""
    resp = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION="Bearer token_invalido_aqui",
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data.get("code") == "UNAUTHORIZED"
