"""Fixtures compartilhadas dos testes.

Estratégia: usar o TestClient do Django Ninja (sem servidor real) + banco SQLite em memória
(transacional, isolado por teste). Integrações externas (Asaas, WhatsApp, IA, CPFHub, etc.)
são mockadas por patch — os testes validam a CAMADA DA API, não os serviços externos.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client


# ── helpers de autenticação ─────────────────────────────────────────────────

def _make_user(*, is_superuser=False, roles: list[str] | None = None):
    """Cria um User + Profile mínimo pro banco de teste."""
    from users.auth.models import User
    from users.profiles.models import Profile

    ext = uuid.uuid4()
    user = User.objects.create_user(
        external_id=ext,
        password="irrelevant" if is_superuser else None,
        is_staff=is_superuser,
        is_superuser=is_superuser,
    )
    Profile.objects.create(
        user=user,
        name="Teste",
        cpf="00000000000",
        phone="11999990000",
        email="teste@example.com",
    )
    if roles:
        from users.roles.models import UserRole

        for role in roles:
            UserRole.objects.create(user=user, role=role)
    return user


def _jwt_for(user, roles: list[str]):
    """Emite um access token válido pro user (via jwt service real)."""
    from users.auth.jwt import service as jwt_service

    return jwt_service.issue(
        external_id=str(user.external_id),
        roles=roles,
    )["access_token"]


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def staff_user(db):
    return _make_user(is_superuser=True, roles=["coordinator"])


@pytest.fixture
def staff_token(staff_user):
    return _jwt_for(staff_user, roles=[])  # staff usa is_superuser, não roles


@pytest.fixture
def lead_user(db):
    return _make_user(roles=["lead"])


@pytest.fixture
def lead_token(lead_user):
    return _jwt_for(lead_user, roles=["lead"])


@pytest.fixture
def candidate_user(db):
    return _make_user(roles=["candidate"])


@pytest.fixture
def candidate_token(candidate_user):
    return _jwt_for(candidate_user, roles=["candidate"])


@pytest.fixture
def promoter_user(db):
    return _make_user(roles=["promoter"])


@pytest.fixture
def promoter_token(promoter_user):
    return _jwt_for(promoter_user, roles=["promoter"])


@pytest.fixture
def coordinator_user(db):
    return _make_user(roles=["promoter", "coordinator"])


@pytest.fixture
def coordinator_token(coordinator_user):
    return _jwt_for(coordinator_user, roles=["coordinator"])


def auth_headers(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}
