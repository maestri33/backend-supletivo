"""Superfície pública in-process do `promoter` (CONVENTION §3): o que o grupo `collaborators`, o
`leadership` (cria na aprovação do candidato) e o funil do aluno (`validate_ref`) chamam. Fina — reexporta o `service`.
"""

from users.roles.promoter.service import (
    create_promoter,
    get_by_user_external_id,
    get_for_user,
    list_commissions,
    list_for_hub,
    list_leads,
    reactivate,
    ref_url,
    suspend,
    to_dict,
    validate_ref,
)

__all__ = [
    "create_promoter",
    "get_for_user",
    "get_by_user_external_id",
    "validate_ref",
    "ref_url",
    "to_dict",
    "list_leads",
    "list_commissions",
    "list_for_hub",
    "suspend",
    "reactivate",
]
