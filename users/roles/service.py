"""Lógica de roles — atribuição (entrada) e promoção (digivolução). Porte do legado p/ ORM Django.

Regras de transição vêm do catálogo do `.env` (`catalog`). A tabela `UserRole` guarda só quem tem
qual role agora + histórico (ativa = `revoked_at` nulo). Referência por FK ao User (§4).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from users.exceptions import Conflict, NotFound, ValidationError
from users.roles import catalog
from users.roles.models import UserRole


def _active_qs(user):
    return UserRole.objects.filter(user=user, revoked_at__isnull=True)


def active_roles(user) -> list[str]:
    """Roles ativas do usuário (ordenadas)."""
    return sorted(_active_qs(user).values_list("role", flat=True))


def assign(user, role: str) -> list[str]:
    """Atribui uma role de ENTRADA (regra com from_role=None). Aditiva. Devolve as ativas."""
    rule = catalog.find_rule(to_role=role, from_role=None)
    if not rule:
        any_rule = catalog.find_any_rule(role)
        if any_rule and any_rule.mode == "replace":
            raise ValidationError(
                f"Role '{role}' não pode ser atribuída diretamente — "
                f"é promoção a partir de '{any_rule.from_role}'.",
                code="INVALID_ROLE_ASSIGNMENT",
            )
        raise NotFound(
            f"Regra para role '{role}' não encontrada", code="ROLE_NOT_FOUND"
        )

    current = active_roles(user)

    if rule.requires_role and rule.requires_role not in current:
        raise ValidationError(
            f"Role '{role}' exige a role '{rule.requires_role}' ativa.",
            code="INVALID_ROLE_ASSIGNMENT",
        )
    if rule.forbids_role and rule.forbids_role in current:
        raise ValidationError(
            f"Role '{role}' é incompatível com a role '{rule.forbids_role}' ativa.",
            code="INVALID_ROLE_ASSIGNMENT",
        )
    if role in current:
        raise Conflict(f"Usuário já possui a role '{role}'.", code="ROLE_ALREADY_HELD")

    UserRole.objects.create(user=user, role=role)
    return active_roles(user)


def promote(user, to_role: str) -> list[str]:
    """Promove (mode=replace): revoga a from_role e adiciona a to_role. Devolve as ativas."""
    rule = catalog.find_promotion_rule(to_role)
    if not rule or not rule.from_role:
        raise ValidationError(
            f"Promoção para '{to_role}' não existe.", code="INVALID_ROLE_PROMOTION"
        )

    from_role = rule.from_role
    current = active_roles(user)

    if from_role not in current:
        raise ValidationError(
            f"Usuário não possui a role '{from_role}' ativa.",
            code="INVALID_ROLE_PROMOTION",
        )
    if rule.forbids_role and rule.forbids_role in current:
        raise ValidationError(
            f"Role '{to_role}' é incompatível com a role '{rule.forbids_role}' ativa.",
            code="INVALID_ROLE_PROMOTION",
        )
    if to_role in current:
        raise Conflict(
            f"Usuário já possui a role '{to_role}'.", code="ROLE_ALREADY_HELD"
        )

    with transaction.atomic():
        _active_qs(user).filter(role=from_role).update(revoked_at=timezone.now())
        UserRole.objects.create(user=user, role=to_role)
    return active_roles(user)


def is_blocked(user) -> bool:
    """True se alguma role ativa for `blocking` (catálogo)."""
    active = active_roles(user)
    if not active:
        return False
    blocking = catalog.blocking_roles()
    return any(r in blocking for r in active)
