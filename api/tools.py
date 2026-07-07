"""Grupo `tools` — ferramentas internas de integração (radar de leads + gatilho de notificação).

🔒 **A6.2**: rotas de negócio exigem header `X-Tools-Token` validado contra
`settings.TOOLS_API_TOKEN` (tempo constante). Sem o token configurado, FAIL-CLOSED (qualquer
acesso cai em 503 `TOOLS_DISABLED`). Casca fina (CONVENTION §3): valida a borda e chama
`lead`/`notify` in-process. Erros de domínio borbulham pro handler central da fábrica
(`api/base.py`) → `{detail, code, …extra}`.

Motivação: o radar (`GET /tools/leads`) vaza nome+telefone+link de checkout de TODOS os leads, e
o gatilho (`POST /tools/notifications/send`) dispara WhatsApp/e-mail pra QUALQUER destino. Antes,
a proteção era assumida como EXTERNA (VPN/proxy/firewall) — A6.2 MOVE essa proteção pro app:
mesmo se a rede falhar, o token continua segurando (defense-in-depth).
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema

from api.base import build_group
from users.exceptions import Forbidden, ValidationError
from users.roles.lead import interface as lead_iface
from users.roles.lead.models import Lead

_ERROR_REGISTRY = """
### Códigos de erro (`{detail, code, …extra}`)

| code | quando | extras |
|---|---|---|
| `TOOLS_DISABLED` | `TOOLS_API_TOKEN` ausente no .env (503) | — |
| `TOOLS_TOKEN_REQUIRED` | sem `X-Tools-Token` no header (403) | — |
| `TOOLS_TOKEN_INVALID` | `X-Tools-Token` não bate (403) | — |
| `INVALID_STATUS` | `status` fora de pending/paid/failed (422) | — |
| `DATE_INVALID` | `created_after` não é ISO-8601 (422) | — |
| `MISSING_FIELD` | mensagem vazia ou nenhum destino no envio (422) | — |
| `USER_NOT_FOUND` | `user_external_id` sem cadastro (404) | — |
| `VALIDATION_ERROR` | body/query fora do schema (422) | `detail` = lista do pydantic |
"""

api = build_group(
    "tools",
    "Ferramentas internas de integração — radar de leads + disparo de notificação. "
    "A6.2: auth por header X-Tools-Token (TOOLS_API_TOKEN no .env).\n" + _ERROR_REGISTRY,
)

_MAX_LIMIT = 500


def _check_tools_token(request) -> None:
    """A6.2: gate por header X-Tools-Token, validado em tempo constante contra
    settings.TOOLS_API_TOKEN. Sem o token no .env → FAIL-CLOSED (503 TOOLS_DISABLED) — o
    grupo tools não roda sem secret configurado."""
    import hmac

    from django.conf import settings

    expected = getattr(settings, "TOOLS_API_TOKEN", "") or ""
    if not expected:
        raise Forbidden(
            "Grupo tools desabilitado (TOOLS_API_TOKEN ausente no .env).",
            code="TOOLS_DISABLED",
        )
    provided = request.headers.get("X-Tools-Token")
    if not provided:
        raise Forbidden(
            "X-Tools-Token obrigatório.", code="TOOLS_TOKEN_REQUIRED"
        )
    if not hmac.compare_digest(provided, expected):
        raise Forbidden("X-Tools-Token inválido.", code="TOOLS_TOKEN_INVALID")


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

    Filtros: `status` (pending/paid/failed), `created_after` (ISO-8601), `limit` (1..500, default 100).
    Auth: header `X-Tools-Token` validado contra `settings.TOOLS_API_TOKEN` (A6.2)."""
    _check_tools_token(request)
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
    todos com destino). Devolve o `external_id` da notificação enfileirada (audit no notify).

    Auth: header `X-Tools-Token` validado contra `settings.TOOLS_API_TOKEN` (A6.2)."""
    _check_tools_token(request)
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
