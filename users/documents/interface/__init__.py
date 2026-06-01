"""Superfície pública in-process do `documents` (CONVENTION §3): o que as views DMZ (e o auth) chamam.

Fina de propósito — reexporta a lógica do `service`. A view (`users/documents/views.py`) embrulha
isto em HTTP; `auth` chama `create_empty` no provisionamento.
"""

from users.documents.service import (
    create_empty,
    delete_photo,
    get_by_external_id,
    update,
    upload_photo,
)

__all__ = [
    "create_empty",
    "get_by_external_id",
    "update",
    "upload_photo",
    "delete_photo",
]
