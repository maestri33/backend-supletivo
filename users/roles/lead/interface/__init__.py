"""Superfície pública in-process do `lead` (CONVENTION §3): o que o grupo `clients` e o hook chamam.
Fina — reexporta a lógica do `service`.
"""

from users.roles.lead.service import LeadError, create_lead, get_lead, mark_paid

__all__ = ["LeadError", "create_lead", "get_lead", "mark_paid"]
