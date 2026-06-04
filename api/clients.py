"""Grupo `clients` (PLACEHOLDER) — público do funil do ALUNO (**$$ ENTRA**):
lead → enrollment → student → veteran.

Fatia 6a (LEAD): captação pública (cria lead + checkout, devolve o pagamento na hora), check/login
por OTP. Casca fina (CONVENTION §3): valida a borda e chama o `interface/` in-process; zero regra aqui.
O funil autenticado da matrícula (enrollment) entra na 6b.
"""

from __future__ import annotations

from ninja import Schema
from ninja.errors import HttpError

from api.base import build_group
from users.auth import interface as auth_iface
from users.auth.models import User
from users.exceptions import DomainError
from users.roles import interface as roles
from users.roles.lead import interface as lead_iface

api = build_group("clients", "Funil do aluno: lead, enrollment, student, veteran.")

# roles do funil do aluno, mais avançada primeiro (login emite JWT com TODAS as ativas).
_FUNNEL_ROLES = ("veteran", "student", "enrollment", "lead")


# ── schemas ──────────────────────────────────────────────────────────────
class LeadCreateIn(Schema):
    cpf: str
    phone: str
    email: str
    payment_method: str | None = None  # default cartão (resolvido no service)
    ref: str | None = None  # external_id do promotor (landing ?ref=)


class CheckoutOut(Schema):
    payment_method: str
    provider: str
    amount: str
    is_paid: bool
    checkout_url: str | None = None
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class LeadOut(Schema):
    external_id: str
    status: str
    checkout: CheckoutOut | None = None


class CheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None


class CheckOut(Schema):
    found: bool
    external_id: str | None = None
    otp_sent: bool
    otp_wait: int | None = None


class LoginIn(Schema):
    external_id: str
    otp: str


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str


def _domain_http(exc: DomainError) -> HttpError:
    return HttpError(getattr(exc, "status", 400), exc.detail)


# ── público (captação + login) ─────────────────────────────────────────────
@api.post("/leads", response={201: LeadOut}, auth=None, tags=["lead"])
def create_lead(request, payload: LeadCreateIn):
    """Cria o lead: cadastro mínimo (cpf/phone/email + método) + checkout. Devolve o pagamento na hora."""
    try:
        result = lead_iface.create_lead(
            cpf=payload.cpf,
            phone=payload.phone,
            email=payload.email,
            payment_method=payload.payment_method,
            ref=payload.ref,
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except lead_iface.LeadError as exc:
        raise HttpError(422, str(exc)) from exc
    return 201, result


@api.post("/leads/check", response=CheckOut, auth=None, tags=["lead"])
def check_lead(request, payload: CheckIn):
    """Dispara OTP por cpf/phone (mecanismo de login do funil)."""
    try:
        return auth_iface.check(cpf=payload.cpf, phone=payload.phone)
    except DomainError as exc:
        raise _domain_http(exc) from exc


@api.post("/leads/login", response=TokenOut, auth=None, tags=["lead"])
def login_lead(request, payload: LoginIn):
    """Login passwordless (OTP) — emite JWT com as roles ativas do funil do aluno."""
    user = User.objects.filter(external_id=payload.external_id).first()
    if user is None:
        raise HttpError(404, "Usuário não encontrado.")
    active = roles.active_roles(user)
    funnel_role = next((r for r in _FUNNEL_ROLES if r in active), None)
    if funnel_role is None:
        raise HttpError(403, "Usuário não faz parte do funil do aluno.")
    try:
        return auth_iface.login(
            external_id=payload.external_id, role=funnel_role, otp=payload.otp
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
