"""Superfície pública in-process do `address` (CONVENTION §3): o que as views DMZ (e o auth) chamam.

Fina de propósito — reexporta a lógica do `service`. A view (`users/address/views.py`) embrulha
isto em HTTP. Inclui `as_dict` p/ serializar o Address no payload das views.
"""

from __future__ import annotations

from users.address.models import Address
from users.address.service import (
    create_empty,
    fill_empty,
    get_by_external_id,
    get_by_id,
    is_complete,
    list_all,
    patch,
    set_by_cep,
)


def as_dict(address: Address) -> dict:
    """Serializa o Address pro JSON da view DMZ (legada) — inclui o PK (`id`)."""
    return {
        "id": address.pk,
        "zipcode": address.zipcode,
        "street": address.street,
        "number": address.number,
        "complement": address.complement,
        "neighborhood": address.neighborhood,
        "city": address.city,
        "state": address.state,
        "country": address.country,
    }


def as_public_dict(address: Address) -> dict:
    """Serializa o Address pra borda pública (API Ninja) — SEM o PK (CONVENTION §4: só `external_id`
    na borda; nunca expor PK) e com **`cep`** (não `zipcode`): mesmo nome no GET e no POST (auditoria
    do front 2026-06-10). O endereço é acessado pelo contexto do user logado, não tem id próprio."""
    data = as_dict(address)
    data.pop("id", None)
    data["cep"] = data.pop("zipcode", None)
    return data


__all__ = [
    "create_empty",
    "get_by_external_id",
    "get_by_id",
    "list_all",
    "patch",
    "fill_empty",
    "is_complete",
    "set_by_cep",
    "as_dict",
    "as_public_dict",
]
