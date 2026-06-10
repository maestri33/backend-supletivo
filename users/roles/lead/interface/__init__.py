"""Superfície pública in-process do `lead` (CONVENTION §3): o que o grupo `clients` e o hook chamam.
Fina — reexporta a lógica do `service`.
"""

from users.roles.lead.service import (
    LeadError,
    checkout_url_for,
    create_lead,
    get_for_user_external_id,
    get_lead,
    lead_self_dict,
    lead_to_dict,
    list_leads,
    mark_paid,
    pricing,
)

__all__ = [
    "LeadError",
    "checkout_url_for",
    "create_lead",
    "get_for_user_external_id",
    "get_lead",
    "lead_self_dict",
    "lead_to_dict",
    "list_leads",
    "mark_paid",
    "pricing",
]
