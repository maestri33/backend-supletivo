"""Superfície pública in-process do `candidate` (CONVENTION §3): o que o grupo `collaborators` chama.
Fina — reexporta a lógica do `service`.
"""

from users.roles.candidate.service import (
    CandidateError,
    create_candidate,
    decide_document,
    decide_selfie,
    list_document_reviews_for_hub,
    list_selfie_reviews_for_hub,
    get_address,
    get_document_section,
    get_for_user_external_id,
    patch_document_section,
    set_address_cep,
    set_address_data,
    set_documents,
    set_pix,
    set_profile,
    me_dict,
    set_selfie,
    to_dict,
    upload_document_photo,
)
from users.roles.candidate.tasks import fill_document_data, validate_document

__all__ = [
    "CandidateError",
    "create_candidate",
    "get_for_user_external_id",
    "to_dict",
    "me_dict",
    "set_profile",
    "get_address",
    "set_address_cep",
    "set_address_data",
    "set_documents",
    "get_document_section",
    "patch_document_section",
    "upload_document_photo",
    "set_pix",
    "set_selfie",
    "decide_document",
    "decide_selfie",
    "list_document_reviews_for_hub",
    "list_selfie_reviews_for_hub",
    "validate_document",
    "fill_document_data",
]
