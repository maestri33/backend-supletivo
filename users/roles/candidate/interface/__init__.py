"""Superfície pública in-process do `candidate` (CONVENTION §3): o que o grupo `collaborators` chama.
Fina — reexporta a lógica do `service`.
"""

from users.roles.candidate.service import (
    CandidateError,
    create_candidate,
    decide_selfie,
    get_for_user_external_id,
    set_address,
    set_documents,
    set_pix,
    set_profile,
    set_selfie,
    to_dict,
    upload_document_photo,
)

__all__ = [
    "CandidateError",
    "create_candidate",
    "get_for_user_external_id",
    "to_dict",
    "set_profile",
    "set_address",
    "set_documents",
    "upload_document_photo",
    "set_pix",
    "set_selfie",
    "decide_selfie",
]
