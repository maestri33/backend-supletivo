"""Superfície pública in-process do `candidate` (CONVENTION §3): o que o grupo `collaborators` chama.
Fina — reexporta a lógica do `service`.
"""

from users.roles.candidate.service import (
    CandidateError,
    candidate_selfie_for_coordinator,
    create_candidate,
    decide_document,
    decide_selfie,
    get_address,
    get_document_section,
    get_for_user_external_id,
    get_selfie,
    list_document_reviews_for_hub,
    list_selfie_reviews_for_hub,
    me_dict,
    patch_document_section,
    set_address_cep,
    set_address_data,
    set_documents,
    set_pix,
    set_profile,
    set_selfie,
    to_dict,
    upload_document_photo,
)
from users.roles.candidate.tasks import (
    fill_document_data,
    validate_candidate_selfie,
    validate_document,
)

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
    "get_selfie",
    "decide_document",
    "decide_selfie",
    "list_document_reviews_for_hub",
    "list_selfie_reviews_for_hub",
    "candidate_selfie_for_coordinator",
    "validate_document",
    "fill_document_data",
    "validate_candidate_selfie",
]
