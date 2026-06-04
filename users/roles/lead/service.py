"""Lógica do lead (funil do aluno, Fatia 6a): captação → checkout → pago.

`create_lead`: reusa o `register` do `auth` (valida CPFHub+WhatsApp+unicidade, cria User+Profile+
Address+Documents+role `lead`+OTP) + `Lead(PENDING)` + `Checkout` SÍNCRONO (PIX Asaas / Cartão InfinitePay).
`mark_paid`: chamado pelo **hook** de pagamento (CONVENTION §7) — marca pago e dispara os efeitos
(comissão do promotor + cria enrollment ligado ao hub HERDADO do promotor + notify). Idempotente.
"""

from __future__ import annotations

import structlog
from django.db import transaction

from hub import interface as hub_iface
from users.auth import interface as auth_iface
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.lead import config
from users.roles.lead.models import Checkout, Lead

logger = structlog.get_logger()

# método da API (Victor: default cartão) → normalizado.
_API_METHODS = {"card": "card", "credit_card": "card", "pix": "pix"}


class LeadError(Exception):
    """Erro de borda do lead (método inválido, sem promotor padrão, falha ao gerar checkout)."""


def create_lead(
    *, cpf: str, phone: str, email: str, payment_method=None, ref=None
) -> dict:
    """Cria o lead: register + Lead(PENDING) + Checkout síncrono. Retorna external_id+status+checkout.

    Mínimo (Victor 2026-06-04): método (default cartão), cpf, phone, email. `ref` = external_id do
    promotor (landing); sem ref → promotor padrão (coordenador do hub padrão).
    """
    method = _API_METHODS.get((payment_method or "card").strip().lower())
    if method is None:
        raise LeadError("invalid_payment_method")

    promoter = _resolve_promoter(ref)

    reg = auth_iface.register(role="lead", phone=phone, cpf=cpf, email=email)
    user = User.objects.get(external_id=reg["external_id"])

    lead = Lead.objects.create(user=user, promoter=promoter, status=Lead.Status.PENDING)
    try:
        checkout = _build_checkout(lead, method)
    except Exception as exc:  # noqa: BLE001 — falha do gateway vira FAILED auditável (não orfã o user)
        lead.status = Lead.Status.FAILED
        lead.failed_reason = str(exc)[:64]
        lead.save(update_fields=["status", "failed_reason", "updated_at"])
        logger.warning(
            "lead.checkout_failed", external_id=str(lead.external_id), error=str(exc)
        )
        raise LeadError(f"checkout_failed: {exc}") from exc

    logger.info(
        "lead.created",
        external_id=str(lead.external_id),
        method=method,
        promoter=str(promoter.external_id),
    )
    return {
        "external_id": str(lead.external_id),
        "status": lead.status,
        "checkout": _checkout_dict(checkout),
    }


def _resolve_promoter(ref) -> User:
    """`ref` (external_id) → promotor; ref inválido/ausente/não-promotor → promotor padrão (hub padrão)."""
    if ref:
        u = User.objects.filter(external_id=ref).first()
        if u is not None and "promoter" in roles.active_roles(u):
            return u
        logger.info("lead.ref_fallback_default", ref=str(ref))
    ext = hub_iface.default_coordinator_external_id()
    u = User.objects.filter(external_id=ext).first() if ext else None
    if u is None:
        raise LeadError(
            "no_default_promoter"
        )  # seed_defaults não rodou (sem hub padrão/coordenador)
    return u


def _build_checkout(lead: Lead, method: str) -> Checkout:
    profile = profiles.get(lead.user)
    if profile is None:
        raise LeadError("profile_missing")
    return _build_pix(lead, profile) if method == "pix" else _build_card(lead, profile)


def _build_pix(lead: Lead, profile) -> Checkout:
    from integrations.finance.asaas import charge as asaas_charge
    from integrations.finance.asaas.customers import PayerData
    from integrations.finance.asaas.qr import qr_url_for

    amount = config.price_pix()
    pid = f"lead_{lead.external_id.hex[:16]}"  # = externalReference que o webhook do asaas casa
    payer = PayerData(
        name=profile.name or "Aluno",
        cpf_cnpj=profile.cpf,
        email=profile.email,
        mobile_phone=profile.phone,
    )
    payment = asaas_charge.create_charge(
        amount=amount, payer=payer, description=config.description(), payment_id=pid
    )
    return Checkout.objects.create(
        lead=lead,
        payment_method=Checkout.Method.PIX,
        provider=Checkout.Provider.ASAAS,
        provider_payment_id=payment.payment_id,
        amount=amount,
        qrcode_payload=payment.qrcode_payload,
        qrcode_image=qr_url_for(payment.payment_id),
        due_date=payment.due_date,
    )


def _build_card(lead: Lead, profile) -> Checkout:
    from integrations.finance.infinitepay import checkout as ip_checkout

    amount = config.price_card()
    # customer=None: o pagador preenche os dados na página hospedada da InfinitePay (não chuto o schema).
    row = ip_checkout.create_checkout(
        amount=amount, description=config.description(), customer=None
    )
    return Checkout.objects.create(
        lead=lead,
        payment_method=Checkout.Method.CREDIT_CARD,
        provider=Checkout.Provider.INFINITEPAY,
        provider_payment_id=str(
            row.external_id
        ),  # = order_nsu que o webhook do infinitepay casa
        amount=amount,
        checkout_url=row.checkout_url,
    )


def _checkout_dict(c: Checkout) -> dict:
    return {
        "payment_method": c.payment_method,
        "provider": c.provider,
        "amount": str(c.amount),
        "is_paid": c.is_paid,
        "checkout_url": c.checkout_url,
        "qrcode_payload": c.qrcode_payload,
        "qrcode_image": c.qrcode_image,
        "due_date": c.due_date.isoformat() if c.due_date else None,
    }


# ── pagamento (chamado pelo hook do webhook, CONVENTION §7) ─────────────────


def mark_paid(*, provider: str, provider_payment_id: str) -> bool:
    """Casa o Checkout do lead por (provider, provider_payment_id). Se for nosso → marca pago + efeitos.

    Idempotente (lead já PAID → no-op). Devolve True se consumiu (era checkout de lead), senão False (o
    webhook cai no fallback rastreável — pode ser cobrança de `fees`, não nossa).
    """
    checkout = (
        Checkout.objects.select_related("lead", "lead__user", "lead__promoter")
        .filter(provider=provider, provider_payment_id=provider_payment_id)
        .first()
    )
    if checkout is None:
        return False

    lead = checkout.lead
    if lead.status == Lead.Status.PAID:
        return True  # idempotente (webhook re-tentou)

    with transaction.atomic():
        if not checkout.is_paid:
            checkout.is_paid = True
            checkout.save(update_fields=["is_paid", "updated_at"])
        lead.status = Lead.Status.PAID
        lead.save(update_fields=["status", "updated_at"])
        hub = _apply_effects(lead)

    _notify_paid(
        lead, hub
    )  # fora da transação: best-effort, não desfaz comissão/enrollment
    logger.info("lead.paid", external_id=str(lead.external_id), provider=provider)
    return True


def _apply_effects(lead: Lead):
    """Dentro da transação: comissão do promotor + cria enrollment ligado ao hub herdado. Retorna o hub."""
    from finance.interface import commissions
    from finance.models import Commission
    from users.roles.enrollment import interface as enrollment_iface

    commissions.credit_commission(
        payee_external_id=lead.promoter.external_id,
        payee_role=Commission.Role.PROMOTER,
        source_type=Commission.Source.LEAD,
        source_external_id=lead.external_id,
    )
    hub = hub_iface.hub_of(lead.promoter)
    if hub is None:
        raise LeadError("no_hub_for_promoter")
    enrollment_iface.create_from_lead(user=lead.user, promoter=lead.promoter, hub=hub)
    return hub


def _notify_paid(lead: Lead, hub) -> None:
    """Avisa lead + coordenador do hub + promotor (best-effort; cada canal isolado, §12)."""
    from notify.interface.send import send

    profile = profiles.get(lead.user)
    base = str(lead.external_id)

    def _safe(label, **kw):
        try:
            send(**kw)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"lead.notify_{label}_failed", external_id=base, error=str(exc)
            )

    _safe(
        "lead",
        text="Pagamento confirmado! 🎉 Sua matrícula começou — acesse para continuar.",
        caller="lead.paid",
        phone=profile.phone if profile else None,
        email=profile.email if profile else None,
        email_channel=bool(profile and profile.email),
        idempotency_key=f"lead_paid_{base}",
    )
    coord = hub.coordinator if hub else None
    if coord is not None:
        coord_profile = profiles.get(coord)
        _safe(
            "coordinator",
            text="Nova matrícula no seu polo. Acompanhe quando o aluno preencher os dados.",
            caller="lead.paid.coordinator",
            phone=coord_profile.phone if coord_profile else None,
            idempotency_key=f"lead_paid_coord_{base}",
        )
    promoter_profile = profiles.get(lead.promoter)
    _safe(
        "promoter",
        text="Seu indicado pagou a matrícula — comissão no fechamento de sexta. 💸",
        caller="lead.paid.promoter",
        phone=promoter_profile.phone if promoter_profile else None,
        idempotency_key=f"lead_paid_promoter_{base}",
    )


def get_lead(external_id: str) -> Lead | None:
    return (
        Lead.objects.select_related("user", "promoter", "checkout")
        .filter(external_id=external_id)
        .first()
    )
