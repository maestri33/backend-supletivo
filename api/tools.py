"""Grupo `tools` — ferramentas internas de integração (radar de leads + gatilho de notificação).

⚠️ **SEM AUTENTICAÇÃO** (decisão do Victor, 2026-07-04): as rotas de negócio passam `auth=None` —
qualquer um com a URL lê nome/telefone dos leads e dispara WhatsApp/e-mail. A proteção assumida é
EXTERNA (VPN/proxy/firewall); não exponha este grupo direto pra internet. `caller="tools.send"`
fica auditável no histórico do notify.

Casca fina (CONVENTION §3): valida a borda e chama `lead`/`notify` in-process. Erros de domínio
borbulham pro handler central da fábrica (`api/base.py`) → `{detail, code, …extra}`.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema

from api.base import COMMON_ERROR_REGISTRY, build_group
from core.net import require_internal_ip
from users.exceptions import ValidationError
from users.roles.lead import service as lead_iface
from users.roles.lead.models import Lead

_ERROR_REGISTRY = (
    COMMON_ERROR_REGISTRY
    + """
### Códigos específicos de tools (serviços externos)

| code | quando | extras |
|---|---|---|
| `INVALID_STATUS` | `status` fora de pending/paid/failed (422) | — |
| `DATE_INVALID` | `created_after` não é ISO-8601 (422) | — |
"""
)

api = build_group(
    "tools",
    "Ferramentas internas de integração — radar de leads + disparo de notificação. "
    "SEM auth nas rotas de negócio (proteção externa via rede).\n" + _ERROR_REGISTRY,
)

_MAX_LIMIT = 500


class ToolLeadOut(Schema):
    """Linha do radar de leads (mesmo shape da listagem staff/hub)."""

    external_id: str
    status: str
    name: str | None = None
    phone: str | None = None
    promoter_external_id: str
    payment_link: str | None = None
    receipt_url: str | None = None
    created_at: str


@api.get("/leads", response=list[ToolLeadOut], auth=None, tags=["tools"])
def tools_leads(
    request,
    status: str | None = None,
    created_after: str | None = None,
    limit: int = 100,
):
    """Radar de leads: todos os leads (mais novos primeiro), com nome/telefone/link de pagamento.

    Filtros: `status` (pending/paid/failed), `created_after` (ISO-8601), `limit` (1..500, default 100)."""
    require_internal_ip(request)
    if status and status not in Lead.Status.values:
        raise ValidationError(
            f"Status inválido: {status} (use {'/'.join(Lead.Status.values)}).",
            code="INVALID_STATUS",
        )
    parsed_after = None
    if created_after:
        try:
            parsed_after = datetime.fromisoformat(created_after)
        except ValueError as exc:
            raise ValidationError(
                "created_after inválido (use ISO-8601, ex.: 2026-07-01 ou 2026-07-01T12:00:00-03:00).",
                code="DATE_INVALID",
            ) from exc
    limit = max(1, min(limit, _MAX_LIMIT))
    rows = lead_iface.list_leads(
        hub=None, status=status, created_after=parsed_after, limit=limit
    )
    return [lead_iface.lead_to_dict(lead) for lead in rows]


class ToolsNotifyIn(Schema):
    """Espelha o `StaffNotifyIn` do staff/notify: usuário cadastrado OU destino livre."""

    user_external_id: str | None = None
    phone: str | None = None
    email: str | None = None
    subject: str | None = None
    message: str
    channels: list[str] | None = None  # subconjunto de {"whatsapp","email"}


class ToolsNotifySentOut(Schema):
    external_id: str


@api.post("/notifications/send", response=ToolsNotifySentOut, auth=None, tags=["tools"])
def tools_notifications_send(request, payload: ToolsNotifyIn):
    """Gatilho de disparo: envia WhatsApp e/ou e-mail a um USUÁRIO (`user_external_id`, herda
    phone/email do Profile) OU a um destino LIVRE (`phone`/`email`). `channels` opcional (default:
    todos com destino). Devolve o `external_id` da notificação enfileirada (audit no notify)."""
    require_internal_ip(request)

    from notify.interface.send import send_adhoc

    external_id = send_adhoc(
        message=payload.message,
        to_user=payload.user_external_id,
        phone=payload.phone,
        email=payload.email,
        subject=payload.subject,
        channels=payload.channels,
        caller="tools.send",
    )
    return {"external_id": external_id}
