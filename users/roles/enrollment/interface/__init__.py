"""Superfície pública in-process do `enrollment` (CONVENTION §3): o que o hook do lead e os
grupos `clients`/`leadership` chamam. Fina — reexporta a lógica do `service`.
"""

from users.roles.enrollment.service import (
    EnrollmentError,
    create_from_lead,
    decide_rg,
    decide_selfie,
    get_address,
    get_by_external_id,
    get_education,
    get_for_user_external_id,
    get_rg_section,
    get_selfie,
    me_dict,
    patch_rg_section,
    release,
    set_address_cep,
    set_address_data,
    set_education,
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
    "get_rg_section",
    "patch_rg_section",
    "upload_rg_photo",
    "get_address",
    "set_address_cep",
    "set_address_data",
    "get_education",
    "set_education",
    "get_selfie",
    "set_selfie",
    "decide_rg",
    "decide_selfie",
    "release",
]
