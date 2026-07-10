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
from django.conf import settings
from django.db import IntegrityError, transaction

from integrations.communication.whatsapp.client import WhatsAppError, get_client
from integrations.tools.cpf.scripts import cpfhub
from users.auth import validation
from users.auth.models import User
from users.auth.otp import service as otp_service
from users.auth.otp.models import STATUS_SENT
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
from users.address import interface as address_iface
from users.documents import service as documents_iface
from users.profiles import interface as profiles
from users.roles import interface as roles

logger = structlog.get_logger()

# Jitter (s) p/ mascarar timing de lookup não-encontrado (anti-enumeração, COD-32 do legado).
_JITTER_MIN = 0.10
_JITTER_MAX = 0.30

# A4 — TEST_MODE: nomes sintéticos determinísticos p/ a identidade fake (não chama CPFHub).
_FAKE_NAMES_M = ("João da Silva", "Pedro Almeida", "Lucas Pereira")
_FAKE_NAMES_F = ("Maria Oliveira", "Ana Souza", "Carla Lima")


def _synthetic_identity(cpf: str):
    """Monta uma CpfIdentity determinística a partir do CPF (TEST_MODE=1). Gênero/nome pelo
    11º dígito — mesmo CPF gera mesma identidade, pra reproducibilidade de teste."""
    from datetime import date as _date

    from integrations.tools.cpf.scripts.cpfhub import CpfIdentity

    digit = int(cpf[-1])
    male = digit % 2 == 0
    name = _FAKE_NAMES_M[digit % 3] if male else _FAKE_NAMES_F[digit % 3]
    return CpfIdentity(
        cpf=cpf,
        name=name,
        name_upper=name.upper(),
        gender="M" if male else "F",
        birth_date=_date(1990 + (digit % 20), 1, 1),
    )


# ── helpers de integração (async → sync) ──────────────────────────────────


def _lookup_cpf(cpf: str):
    """CPFHub: identidade real do CPF. None = não encontrado/ inválido; erro real → IntegrationError.

    TEST_MODE=1: devolve identidade sintética (não chama a API) — aceita qualquer CPF bem formado."""
    if getattr(settings, "TEST_MODE", False):
        logger.info("auth.test_mode.cpf_lookup_mock")
        return _synthetic_identity(cpf)
    try:
        return async_to_sync(cpfhub.lookup)(cpf)
    except cpfhub.CpfHubError as exc:
        raise IntegrationError(
            "Serviço de validação de CPF indisponível.", code="CPF_SERVICE_DOWN"
        ) from exc


async def _wa_check(phone: str) -> tuple[bool, str]:
    if getattr(settings, "TEST_MODE", False):
        return (
            True,
            phone,
        )  # TEST_MODE=1: número "existe" no zap sem chamar a Evolution API.
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


def _dispatch_otp(user) -> bool:
    """Dispara OTP best-effort — não quebra o fluxo do caller se falhar.

    Retorna se o OTP foi REALMENTE enviado (não mente): False em rate-limit, falha de dispatch
    ou envio impossível (sem telefone). O caller (register) propaga isso como `otp_sent` — o
    resultado precisa ser honesto mesmo quando o envio é best-effort (não derruba a criação)."""
    try:
        otp = otp_service.generate_and_send(user)
    except RateLimited:
        return False  # logo após criar, raro; o front pode pedir reenvio depois
    except Exception as exc:  # noqa: BLE001 — best-effort, só loga o tipo (sem PII)
        logger.warning(
            "auth.otp_dispatch_failed",
            external_id=str(user.external_id),
            error=type(exc).__name__,
        )
        return False
    return otp.status == STATUS_SENT


# ── register ───────────────────────────────────────────────────────────────


def register(*, role: str, phone: str, cpf: str, email: str | None = None) -> dict:
    """Cria usuário (entry role) e provisiona Profile + role numa transação; dispara OTP. Retorna external_id.

    `email` (opcional, aditivo — Victor 2026-06-04 p/ o lead) é gravado no Profile. Continua opcional pra
    não quebrar os chamadores atuais (`users/auth/views.py`).
    """
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
    if email is not None:
        email = email.strip().lower() or None

    # unicidade local (barato) antes da chamada externa
    if profiles.exists_cpf(cpf):
        raise Conflict("CPF já cadastrado.", code="CPF_EXISTS")
    if profiles.exists_phone(phone):
        raise Conflict("Telefone já cadastrado.", code="PHONE_EXISTS")
    if email and profiles.exists_email(email):
        raise Conflict("E-mail já cadastrado.", code="EMAIL_EXISTS")

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
            # provisionamento (§9): Profile + Address vazio + Documents (sub-docs null) + role,
            # tudo na MESMA transação. name/birth_date vêm de brinde do CPFHub (identity).
            profile = profiles.create(
                user=user,
                cpf=cpf,
                phone=resolved_phone,
                email=email,
                gender=identity.gender,
                name=identity.name,
                birth_date=identity.birth_date,
            )
            profiles.attach_address(profile, address_iface.create_empty())
            documents_iface.create_empty(user)
            roles.assign(user, role)
    except IntegrityError as exc:
        # corrida na unicidade (cpf/phone) — outra request criou primeiro
        raise Conflict("CPF ou telefone já cadastrado.", code="DUPLICATE") from exc

    logger.info("auth.registered", external_id=str(user.external_id), role=role)
    otp_sent = _dispatch_otp(user)
    if not otp_sent:
        logger.warning(
            "auth.registered.otp_not_sent", external_id=str(user.external_id)
        )
    return {"external_id": str(user.external_id), "otp_sent": otp_sent}


def change_phone(*, user_external_id: str, new_phone: str) -> dict:
    """Troca o telefone de LOGIN de um usuário — resgate do STAFF (Victor 2026-06-17).

    Cenário de beco-sem-saída em prod: o usuário perdeu o número/chip e não recebe mais o OTP →
    fica TRANCADO fora do login, sem nenhuma rota (nem o staff tinha; só um db-edit destravava, o
    que o Victor não quer). Aqui o staff atualiza o telefone, com as MESMAS garantias do register:
    formato válido + o NOVO número tem WhatsApp ativo (senão o OTP não chega) + unicidade.

    Trocar o canal de login é poder do STAFF (is_superuser), não do coordenador — é a ponta da
    hierarquia de resgate user→coord→staff. Auditado no log (sem PII)."""
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    try:
        new_phone = validation.validate_phone(new_phone)
    except ValueError as exc:
        raise ValidationError(str(exc), code="PHONE_INVALID") from exc

    phone_exists, resolved_phone = _check_phone_whatsapp(new_phone)
    if not phone_exists:
        raise ValidationError(
            "Telefone sem WhatsApp ativo.", code="PHONE_NOT_ON_WHATSAPP"
        )
    other = profiles.find_by_phone(resolved_phone)
    if other is not None and other.user_id != user.id:
        raise Conflict("Telefone já cadastrado em outra conta.", code="PHONE_EXISTS")

    if profiles.set_phone(user, resolved_phone) is None:
        raise NotFound("Perfil não encontrado.", code="PROFILE_NOT_FOUND")
    logger.info("auth.phone_changed", external_id=str(user.external_id))
    return {"external_id": str(user.external_id), "phone": resolved_phone}


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
    """Dispara OTP p/ um user CONHECIDO (check/recover/staff). Devolve o resultado REAL, não finge:

    - `otp_sent True`  → foi mesmo pro WhatsApp.
    - `otp_sent False` + `otp_wait` → rate-limitado; um código recente já saiu, peça reenvio depois.
    - `otp_sent False` + `otp_wait=None` → falha real (sem telefone / dispatch). O caller interativo
      (check) deve levantar OTP_NOT_SENT em vez de mentir que enviou.
    """
    try:
        otp = otp_service.generate_and_send(user)
    except RateLimited as exc:
        return {"otp_sent": False, "otp_wait": exc.retry_after_s}
    except Exception as exc:  # noqa: BLE001 — falha de dispatch não pode virar sucesso silencioso
        logger.warning(
            "auth.otp_send_failed",
            external_id=str(user.external_id),
            error=type(exc).__name__,
        )
        return {"otp_sent": False, "otp_wait": None}
    return {"otp_sent": otp.status == STATUS_SENT, "otp_wait": None}


def check(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
) -> dict:
    """Acha o usuário por cpf/phone/external_id. **O NORMAL é disparar OTP** (`send_otp=True`).

    `send_otp=False` = o antigo `check_bot` integrado como parâmetro (Victor 2026-07-04): mesma
    função, mas NÃO dispara OTP e devolve o `token` (JWT) direto. **Exige `service_authed=True`** —
    o segredo de serviço interno checado na view (a rota é pública, então o "canal do chamador" NÃO
    é prova de identidade sozinho). Sem o segredo, recusa com `SERVICE_SECRET_REQUIRED` (fail-closed).

    **VAZA existência DE PROPÓSITO (CONVENTION §5):** devolve `found` honesto — se existe, manda OTP e
    retorna `external_id`+`roles`; se NÃO existe, `found:false`+`otp_sent:false`. O front decide cadastro
    novo × login. **NÃO anti-enumeração.** Rate-limit por IP fica no reverse proxy. Validação só de FORMATO aqui.
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
        # VAZA existência (CONVENTION §5): não existe → found:false + otp_sent:false (honesto).
        whatsapp: bool | None = None
        if phone:
            try:
                exists, _ = _check_phone_whatsapp(phone)
                whatsapp = exists
            except IntegrationError:
                whatsapp = None  # WhatsApp fora do ar → não bloqueia o check
        return {
            "otp_sent": False,
            "otp_wait": None,
            "found": False,
            "external_id": None,
            "whatsapp": whatsapp,
            "token": None,
        }

    active = roles.active_roles(user)
    if not send_otp:
        # modo sem OTP (bot_v2): JWT direto — SÓ com o segredo de serviço (service_authed).
        # Sem o segredo, a rota pública `/auth/check` viraria bypass de OTP: recusa fail-closed.
        if not service_authed:
            raise Unauthorized(
                "Login sem OTP exige segredo de serviço interno.",
                code="SERVICE_SECRET_REQUIRED",
            )
        tokens = jwt_service.issue(str(user.external_id), active)
        logger.info(
            "auth.check_no_otp", external_id=str(user.external_id), roles=active
        )
        return {
            "otp_sent": False,
            "otp_wait": None,
            "found": True,
            "external_id": str(user.external_id),
            "whatsapp": None,
            "roles": active,
            "token": tokens["access_token"],
        }

    result = _send_or_wait(user)
    # Fluxo interativo: o usuário ESPERA o código. Se não deu pra enviar (sem telefone / falha de
    # dispatch, e NÃO rate-limit), não finge sucesso — devolve erro claro pro front (CONVENTION §5:
    # existência já é vazada por design, então levantar aqui não vaza nada novo).
    if not result["otp_sent"] and result["otp_wait"] is None:
        raise IntegrationError(
            "Não foi possível enviar o código OTP.", code="OTP_NOT_SENT"
        )
    return {
        **result,
        "found": True,
        "external_id": str(user.external_id),
        "whatsapp": None,
        "roles": active,
        "token": None,
    }


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


# ── check_bot (WhatsApp bot — sem OTP) ────────────────────────────────────


def check_bot(*, phone: str) -> dict:
    """DEPRECATED (Victor 2026-07-04): virou `check(phone=..., send_otp=False)`. Alias fino
    **in-process** (só chamável de dentro do Django = confiável), por isso já entra com
    `service_authed=True`. O bot_v2 externo NÃO usa isto — ele bate na view HTTP `/auth/check`,
    que exige o header de segredo (`service_secret_ok`)."""
    return check(phone=phone, send_otp=False, service_authed=True)


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


# ── login de STAFF (superuser puro, sem role de funil — Victor 2026-06-30) ──
# O staff é superuser NATIVO do Django (api/auth.require_superuser confere is_superuser no DB). O
# login normal (acima) EXIGE uma role de funil em active_roles → um superuser PURO tomava
# NOT_IN_FUNNEL. Aqui o gate é is_superuser, não role: espelha check/login do cliente, mas só
# enxerga staff. O JWT sai com as roles ativas (pode ser vazio — o gate de staff lê o DB, não claims).


def _is_staff_user(user) -> bool:
    """True se o user existe, está ativo e é superuser (mesma semântica de require_superuser)."""
    return bool(user and user.is_active and user.is_superuser)


def check_staff(
    *, cpf: str | None = None, phone: str | None = None, external_id: str | None = None
) -> dict:
    """Acha o STAFF (superuser) por cpf/phone/external_id e dispara OTP se for staff.

    Diferente do `check` do cliente (que VAZA existência por design, §5), aqui um usuário comum
    (ou inexistente) sai `found:false` IGUAL — não vaza quem é staff. Validação só de FORMATO.
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
    if not _is_staff_user(user):
        # não-staff (ou inexistente) → found:false honesto, sem vazar quem é staff.
        _jitter()
        return {
            "otp_sent": False,
            "otp_wait": None,
            "found": False,
            "external_id": None,
        }

    result = _send_or_wait(user)
    return {**result, "found": True, "external_id": str(user.external_id)}


def login_staff(*, external_id: str, otp: str) -> dict:
    """Login do STAFF: exige is_superuser (NÃO role de funil) → valida OTP → emite JWT.

    Não-superuser → 403 `NOT_STAFF`. As roles do JWT são as ativas do user (pode ser vazio); o
    gate de staff (`require_superuser`) confere is_superuser no banco, não nos claims.
    """
    user = User.objects.filter(external_id=external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    if not _is_staff_user(user):
        logger.warning("auth.login_staff_denied", external_id=external_id)
        raise Forbidden("Acesso restrito ao staff.", code="NOT_STAFF")

    if not otp_service.verify(user, otp):
        raise Unauthorized("OTP inválido ou expirado.", code="OTP_INVALID")

    active = roles.active_roles(user)
    tokens = jwt_service.issue(external_id, active)
    logger.info("auth.login_staff_ok", external_id=external_id)
    return tokens
