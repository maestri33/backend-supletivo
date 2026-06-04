"""Superfície pública in-process do `enrollment` (CONVENTION §3): o que o hook do lead e os
grupos `clients`/`leadership` chamam. Fina — reexporta a lógica do `service`.
"""

from users.roles.enrollment.service import (
    create_from_lead,
    get_by_external_id,
    get_by_user,
)

__all__ = ["create_from_lead", "get_by_user", "get_by_external_id"]
