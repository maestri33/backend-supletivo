"""Lógica do auth — register · check · recover · login. Porte do legado p/ o monólito Django.

Fonte de verdade da identidade (VISAO): ao registrar, cria User + Profile + role inicial numa
**transação atômica** (§9) e dispara o OTP. Unicidade absoluta "nem falsos" (spec): `unique` no
banco + formato (validation) + **veracidade REAL** — CPFHub (a identidade existe) e WhatsApp
check_numbers (o número existe no zap). Login é passwordless por OTP → emite JWT com as roles ativas.

Os clientes de integração são async (httpx); chamamos com `async_to_sync` (padrão do monólito).
Estas funções são a LÓGICA — não sabem de HTTP; a view (`views.py`) traduz pra JSON/status.
"""

from __future__ import annotations

import random
import time

import structlog
from asgiref.sync import async_to_sync
from django.db import IntegrityError, transaction

from integrations.communication.whatsapp.client import WhatsAppError, get_client
from integrations.tools.cpf.scripts import cpfhub
from users.auth import validation
from users.auth.models import User
from users.auth.otp import service as otp_service
from users.auth.jwt import service as jwt_service
from users.exceptions import (
    Conflict,
    Forbidden,
    IntegrationError,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationError,
)
from users.profiles import interface as profiles
from users.roles import interface as roles

logger = structlog.get_logger()

# Jitter (s) p/ mascarar timing de lookup não-encontrado (anti-enumeração, COD-32 do legado).
_JITTER_MIN = 0.10
_JITTER_MAX = 0.30


# ── helpers de integração (async → sync) ──────────────────────────────────


def _lookup_cpf(cpf: str):
    """CPFHub: identidade real do CPF. None = não encontrado/ inválido; erro real → IntegrationError."""
    try:
        return async_to_sync(cpfhub.lookup)(cpf)
    except cpfhub.CpfHubError as exc:
        raise IntegrationError(
            "Serviço de validação de CPF indisponível.", code="CPF_SERVICE_DOWN"
        ) from exc


async def _wa_check(phone: str) -> tuple[bool, str]:
    async with get_client() as wa:
        resolved = await wa.resolve_br_number(phone)
        result = await wa.check_numbers([resolved])
    exists = bool(result and result[0].get("exists"))
    return exists, resolved


def _check_phone_whatsapp(phone: str) -> tuple[bool, str]:
    """WhatsApp: (existe_no_zap, número_resolvido). Erro real → IntegrationError."""
    try:
        return async_to_sync(_wa_check)(phone)
    except WhatsAppError as exc:
        raise IntegrationError(
            "Serviço de validação de telefone indisponível.", code="PHONE_SERVICE_DOWN"
        ) from exc


def _jitter() -> None:
    time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))


def _dispatch_otp(user) -> None:
    """Dispara OTP best-effort — não quebra o fluxo do caller se falhar."""
    try:
        otp_service.generate_and_send(user)
    except RateLimited:
        pass  # logo após criar, raro; o front pode pedir reenvio depois
    except Exception as exc:  # noqa: BLE001 — best-effort, só loga o tipo (sem PII)
        logger.warning(
            "auth.otp_dispatch_failed",
            external_id=str(user.external_id),
            error=type(exc).__name__,
        )


# ── register ───────────────────────────────────────────────────────────────


def register(*, role: str, phone: str, cpf: str) -> dict:
    """Cria usuário (entry role) e provisiona Profile + role numa transação; dispara OTP. Retorna external_id."""
    if not roles.is_entry_role(role):
        raise ValidationError(
            f"Role '{role}' não é uma role de entrada válida.",
            code="INVALID_ENTRY_ROLE",
        )

    try:
        cpf = validation.validate_cpf(cpf)
    except ValueError as exc:
        raise ValidationError(str(exc), code="CPF_INVALID") from exc
    try:
        phone = validation.validate_phone(phone)
    except ValueError as exc:
        raise ValidationError(str(exc), code="PHONE_INVALID") from exc

    # unicidade local (barato) antes da chamada externa
    if profiles.exists_cpf(cpf):
        raise Conflict("CPF já cadastrado.", code="CPF_EXISTS")
    if profiles.exists_phone(phone):
        raise Conflict("Telefone já cadastrado.", code="PHONE_EXISTS")

    # veracidade REAL (§8) — CPF existe (identidade) + telefone existe no WhatsApp
    identity = _lookup_cpf(cpf)
    if identity is None:
        raise ValidationError("CPF não encontrado ou inválido.", code="CPF_NOT_FOUND")

    phone_exists, resolved_phone = _check_phone_whatsapp(phone)
    if not phone_exists:
        raise ValidationError(
            "Telefone sem WhatsApp ativo.", code="PHONE_NOT_ON_WHATSAPP"
        )

    # resolved_phone pode colidir com outro já salvo (variante 9º dígito) — checa de novo
    if profiles.exists_phone(resolved_phone):
        raise Conflict("Telefone já cadastrado.", code="PHONE_EXISTS")

    try:
        with transaction.atomic():
            user = User.objects.create_user()
            profiles.create(
                user=user, cpf=cpf, phone=resolved_phone, gender=identity.gender
            )
            roles.assign(user, role)
    except IntegrityError as exc:
        # corrida na unicidade (cpf/phone) — outra request criou primeiro
        raise Conflict("CPF ou telefone já cadastrado.", code="DUPLICATE") from exc

    logger.info("auth.registered", external_id=str(user.external_id), role=role)
    _dispatch_otp(user)
    return {"external_id": str(user.external_id)}


# ── check / recover ──────────────────────────────────────────────────────


def _find_user(
    *, cpf: str | None = None, phone: str | None = None, external_id: str | None = None
):
    if external_id:
        return User.objects.filter(external_id=external_id).first()
    if cpf:
        p = profiles.find_by_cpf(cpf)
        return p.user if p else None
    if phone:
        p = profiles.find_by_phone(phone)
        return p.user if p else None
    return None


def _send_or_wait(user) -> dict:
    """Dispara OTP; se rate-limitado, devolve otp_wait. Usado por check/recover (achou usuário)."""
    try:
        otp_service.generate_and_send(user)
    except RateLimited as exc:
        return {"otp_sent": False, "otp_wait": exc.retry_after_s}
    return {"otp_sent": True, "otp_wait": None}


def check(
    *, cpf: str | None = None, phone: str | None = None, external_id: str | None = None
) -> dict:
    """Acha o usuário por cpf/phone/external_id e dispara OTP se existir.

    Resposta com `found`+`external_id` (o front decide OTP de usuário existente vs cadastro novo).
    Não-encontrado: jitter de timing + resposta com shape de sucesso (anti-enumeração). Rate-limit
    forte por IP fica no edge público (§5). Validação só de FORMATO aqui (não vaza existência).
    """
    if cpf:
        try:
            cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
    elif phone:
        try:
            phone = validation.validate_phone(phone)
        except ValueError as exc:
            raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    elif not external_id:
        raise ValidationError(
            "Informe cpf, phone ou external_id.", code="MISSING_FIELD"
        )

    user = _find_user(cpf=cpf, phone=phone, external_id=external_id)
    if user is None:
        _jitter()
        return {"otp_sent": True, "otp_wait": None, "found": False, "external_id": None}

    result = _send_or_wait(user)
    return {**result, "found": True, "external_id": str(user.external_id)}


def recover(*, cpf: str | None = None, phone: str | None = None) -> dict:
    """Recupera acesso por cpf/phone: dispara OTP no canal conhecido. NUNCA devolve o external_id."""
    if cpf:
        try:
            cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
    elif phone:
        try:
            phone = validation.validate_phone(phone)
        except ValueError as exc:
            raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    else:
        raise ValidationError("Informe cpf ou phone.", code="MISSING_FIELD")

    user = _find_user(cpf=cpf, phone=phone)
    if user is None:
        _jitter()
        return {"found": True, "otp_sent": True, "otp_wait": None}  # shape uniforme

    result = _send_or_wait(user)
    return {"found": True, **result}


# ── login ────────────────────────────────────────────────────────────────


def login(*, external_id: str, role: str, otp: str) -> dict:
    """Confere role ativa → valida OTP → emite JWT com TODAS as roles ativas (passwordless)."""
    user = User.objects.filter(external_id=external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    active = roles.active_roles(user)
    if role not in active:
        logger.warning(
            "auth.login_role_denied", external_id=external_id, requested=role
        )
        raise Forbidden(f"Usuário não possui a role '{role}'.", code="ROLE_NOT_HELD")

    if not otp_service.verify(user, otp):
        raise Unauthorized("OTP inválido ou expirado.", code="OTP_INVALID")

    tokens = jwt_service.issue(external_id, active)
    logger.info("auth.login_ok", external_id=external_id, role=role)
    return tokens
