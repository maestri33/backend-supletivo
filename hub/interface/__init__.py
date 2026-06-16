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
    """Garante a role `coordinator` ativa no user (idempotente). A regra exige promoter (já validado).

    Troca de role → notifica o novo coordenador (Victor: toda troca de role avisa os envolvidos)."""
    if "coordinator" not in roles.active_roles(user):
        roles.assign(user, "coordinator")
        _notify_coordinator_assigned(user)


def _notify_coordinator_assigned(user: User) -> None:
    """Avisa o usuário que acabou de virar coordenador de um polo (best-effort, §12)."""
    from notify.interface.send import send
    from users.profiles import interface as profiles
    from users.roles import notifications as msgs

    p = profiles.get(user)
    try:
        send(
            text=msgs.text(
                "hub.coordinator_assigned", name=msgs.first_name(p.name if p else None)
            ),
            caller="hub.coordinator_assigned",
            phone=p.phone if p else None,
            idempotency_key=f"hub_coord_assigned_{user.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("hub.notify_coordinator_failed", error=str(exc))


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


def hub_of(user) -> Hub | None:
    """O polo de um promotor (herança do plano §6-lead-funil): a responsabilidade passa pro HUB do
    promotor que indicou quando o lead vira matrícula (Victor 2026-06-04).

    Preferência (corrigido 2026-06-05 — auditoria): o hub a que o promotor **PERTENCE** (`Promoter.hub`);
    senão o hub que ele **coordena**; senão o **padrão**. Antes resolvia só por coordenação → promotor
    comum (não-coordenador) caía no padrão e a comissão da matrícula/veteran ia pro polo ERRADO. Como a
    conta-mãe tem `Promoter.hub` = hub padrão, o caso atual não muda; o promotor comum (Fatia 2) já fica certo.
    """
    from users.roles.promoter import interface as promoter_iface

    promoter = promoter_iface.get_for_user(user)
    if promoter is not None:
        return promoter.hub
    coordinated = (
        Hub.objects.select_related("coordinator")
        .filter(coordinator=user)
        .order_by("created_at")
        .first()
    )
    return coordinated or get_default()


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


def set_default(external_id: str) -> Hub:
    """Marca o polo como PADRÃO (fallback de captação; único — desmarca os outros, atômico)."""
    hub = get_by_external_id(external_id)
    if hub is None:
        raise HubError("hub_not_found")
    with transaction.atomic():
        Hub.objects.filter(is_default=True).exclude(pk=hub.pk).update(is_default=False)
        if not hub.is_default:
            hub.is_default = True
            hub.save(update_fields=["is_default", "updated_at"])
    logger.info("hub.set_default", external_id=external_id)
    return hub


def coordinated_by(user):
    """O hub que `user` COORDENA de fato (FK `Hub.coordinator`) — ou None.

    Diferente do `hub_of` (que resolve o polo de um PROMOTOR com fallback pro padrão): aqui é o
    gate duro do coordenador (plan/14) — sem hub coordenado, não há login de coordenador."""
    return Hub.objects.filter(coordinator=user).order_by("created_at").first()
