"""Superfície pública in-process do `hub` (CONVENTION §3): o que os grupos `staff`/`leadership`
chamam. Sem regra de negócio no router — ela mora aqui.

Cria/lista polos, designa coordenador (um promotor — spec hub: "coordenador (external_id)"), e
resolve o **hub padrão** (fallback de captação). A marca é validada contra o catálogo do `.env`
(`hub.config`); o coordenador exige a role `promoter` ativa e ganha a role `coordinator`.
"""

from __future__ import annotations

import structlog
from django.db import transaction

from hub import config
from hub.models import Hub
from users.auth.models import User
from users.address import interface as address_iface
from users.roles import interface as roles

logger = structlog.get_logger()


class HubError(Exception):
    """Erro de borda do hub (marca inválida, coordenador não-promotor, polo inexistente, ...)."""


def _coordinator_by_external_id(external_id: str) -> User:
    """Resolve o User do coordenador por external_id e exige que seja PROMOTOR (spec hub/coordinator)."""
    user = User.objects.filter(external_id=external_id).first()
    if user is None:
        raise HubError("coordinator_not_found")
    if "promoter" not in roles.active_roles(user):
        raise HubError("coordinator_not_promoter")
    return user


def _ensure_coordinator_role(user: User) -> None:
    """Garante a role `coordinator` ativa no user (idempotente). A regra exige promoter (já validado)."""
    if "coordinator" not in roles.active_roles(user):
        roles.assign(user, "coordinator")


def create_hub(
    *, brand: str, coordinator_external_id: str | None = None, is_default: bool = False
) -> Hub:
    """Cria um polo: Address vazio + marca (validada contra o .env). Coordenador é opcional."""
    if not config.is_valid_brand(brand):
        raise HubError(f"invalid_brand:{brand}")
    coordinator = (
        _coordinator_by_external_id(coordinator_external_id)
        if coordinator_external_id
        else None
    )
    with transaction.atomic():
        address = address_iface.create_empty()
        hub = Hub.objects.create(
            address=address,
            brand=brand,
            coordinator=coordinator,
            is_default=is_default,
        )
        if coordinator is not None:
            _ensure_coordinator_role(coordinator)
    logger.info(
        "hub.created",
        external_id=str(hub.external_id),
        brand=brand,
        has_coordinator=coordinator is not None,
    )
    return hub


def list_hubs() -> list[Hub]:
    """Todos os polos (mais antigos primeiro)."""
    return list(
        Hub.objects.select_related("coordinator", "address").order_by("created_at")
    )


def get_by_external_id(external_id: str) -> Hub | None:
    return (
        Hub.objects.select_related("coordinator", "address")
        .filter(external_id=external_id)
        .first()
    )


def get_default() -> Hub | None:
    """O polo padrão (fallback de captação: candidato sem `ref` cai nele)."""
    return Hub.objects.filter(is_default=True).select_related("coordinator").first()


def default_coordinator_external_id() -> str | None:
    """external_id do coordenador do hub padrão (fallback de captação). None se não há padrão/coordenador."""
    hub = get_default()
    if hub is None or hub.coordinator is None:
        return None
    return str(hub.coordinator.external_id)


def set_coordinator(*, hub_external_id: str, coordinator_external_id: str) -> Hub:
    """Designa/troca o coordenador do polo (um promotor); garante a role `coordinator` nele."""
    hub = get_by_external_id(hub_external_id)
    if hub is None:
        raise HubError("hub_not_found")
    coordinator = _coordinator_by_external_id(coordinator_external_id)
    with transaction.atomic():
        hub.coordinator = coordinator
        hub.save(update_fields=["coordinator", "updated_at"])
        _ensure_coordinator_role(coordinator)
    logger.info(
        "hub.coordinator_set",
        external_id=str(hub.external_id),
        coordinator=coordinator_external_id,
    )
    return hub
