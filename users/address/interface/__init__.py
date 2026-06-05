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
    """Serializa o Address pro JSON da view DMZ."""
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
]
