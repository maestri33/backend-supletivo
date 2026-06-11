"""Superfície pública in-process do `enrollment` (CONVENTION §3): o que o hook do lead e os
grupos `clients`/`leadership` chamam. Fina — reexporta a lógica do `service`.
"""

from users.roles.enrollment.service import (
    EnrollmentError,
    create_from_lead,
    decide_selfie,
    get_by_external_id,
    get_address,
    get_for_user_external_id,
    me_dict,
    release,
    set_address_cep,
    set_address_data,
    set_documents_rg,
    set_education,
    set_profile,
    set_selfie,
    to_dict,
    upload_rg_photo,
)

__all__ = [
    "EnrollmentError",
    "create_from_lead",
    "get_by_external_id",
    "get_for_user_external_id",
    "to_dict",
    "me_dict",
    "set_profile",
    "get_address",
    "set_address_cep",
    "set_address_data",
    "set_documents_rg",
    "upload_rg_photo",
    "set_education",
    "set_selfie",
    "decide_selfie",
    "release",
]
