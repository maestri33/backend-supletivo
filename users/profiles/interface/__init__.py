"""Superfície pública in-process do `profiles` (CONVENTION §3): o que o auth (e futuros apps) chamam.

Escopo mínimo: criação do Profile + lookups de unicidade/contato. Sem service separado — o Profile
ainda é só dados; quando o `profiles` completo chegar (Pix/Asaas, address), a lógica vira `service.py`.
"""

from __future__ import annotations

from users.profiles.models import Profile


def exists_cpf(cpf: str) -> bool:
    return Profile.objects.filter(cpf=cpf).exists()


def exists_phone(phone: str) -> bool:
    return Profile.objects.filter(phone=phone).exists()


def exists_email(email: str) -> bool:
    return Profile.objects.filter(email=email).exists()


def find_by_cpf(cpf: str) -> Profile | None:
    return Profile.objects.filter(cpf=cpf).select_related("user").first()


def find_by_phone(phone: str) -> Profile | None:
    return Profile.objects.filter(phone=phone).select_related("user").first()


def find_by_external_id(external_id: str) -> Profile | None:
    """Profile pelo external_id do User (uso de borda, §4)."""
    return (
        Profile.objects.filter(user__external_id=external_id)
        .select_related("user", "address")
        .first()
    )


def get(user) -> Profile | None:
    """Profile do User (ou None se ainda não tem)."""
    return Profile.objects.filter(user=user).first()


_IDENTITY_FIELDS = (
    "name",
    "birth_date",
    "mother_name",
    "father_name",
    "marital_status",
    "nationality",
    "birthplace",
    "pix_key",
    "pix_key_type",
)


def fill_identity(user, **fields) -> Profile | None:
    """Grava campos de IDENTIDADE no Profile — o lugar ÚNICO da pessoa (Victor 2026-06-16). SÓ os
    que estão VAZIOS (não sobrescreve o que já existe). Usado pelo `set_profile`, pela extração do
    OCR do documento e pela validação do Pix. Ignora chaves desconhecidas e valores None."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    changed = []
    for field, value in fields.items():
        if (
            field in _IDENTITY_FIELDS
            and value is not None
            and not getattr(p, field, None)
        ):
            setattr(p, field, value)
            changed.append(field)
    if changed:
        p.save(update_fields=[*changed, "updated_at"])
    return p


def update_identity(user, **fields) -> Profile | None:
    """Atualiza campos de IDENTIDADE no Profile — SOBRESCREVE (correção do usuário/coordenador). Par
    do `fill_identity` (que só preenche vazios). Ignora chaves desconhecidas e valores None."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    changed = []
    for field, value in fields.items():
        if field in _IDENTITY_FIELDS and value is not None:
            setattr(p, field, value)
            changed.append(field)
    if changed:
        p.save(update_fields=[*changed, "updated_at"])
    return p


def get_map(users) -> dict:
    """Profiles de vários Users numa query só — evita N+1 nas listagens. Devolve `{user_id: Profile}`."""
    return {p.user_id: p for p in Profile.objects.filter(user__in=list(users))}


def create(
    *,
    user,
    cpf: str,
    phone: str,
    email: str | None = None,
    gender: str | None = None,
    name: str | None = None,
    birth_date=None,
) -> Profile:
    """Cria o Profile 1-1 do User. Chamado DENTRO da transação atômica do register (auth).

    `name`/`birth_date` chegam do CPFHub (brinde da validação de identidade). O `address` é
    vinculado depois, no mesmo provisionamento, via `attach_address` (Address nasce vazio).
    """
    return Profile.objects.create(
        user=user,
        cpf=cpf,
        phone=phone,
        email=email,
        gender=gender,
        name=name,
        birth_date=birth_date,
    )


def attach_address(profile: Profile, address) -> Profile:
    """Liga o Profile a um Address (Profile→Address, §4). Usado no provisionamento (auth)."""
    profile.address = address
    profile.save(update_fields=["address"])
    return profile


def get_address(external_id: str):
    """Endereço do usuário (via `profile.address`), ou None."""
    profile = find_by_external_id(external_id)
    return profile.address if profile else None


def set_pix(
    external_id: str, pix_key: str, pix_key_type: str | None = None
) -> Profile | None:
    """Grava a chave Pix (+ tipo) no profile — o lugar canônico (finance usa no payout)."""
    profile = find_by_external_id(external_id)
    if profile is None:
        return None
    profile.pix_key = pix_key
    fields = ["pix_key"]
    if pix_key_type is not None:
        profile.pix_key_type = pix_key_type
        fields.append("pix_key_type")
    profile.save(update_fields=fields)
    return profile


def set_phone(user, phone: str) -> Profile | None:
    """Grava o telefone de login no profile — usado pelo resgate do staff (`auth.change_phone`)
    quando o usuário perde o número e fica trancado fora do OTP. None se não tem profile."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    p.phone = phone
    p.save(update_fields=["phone", "updated_at"])
    return p


__all__ = [
    "exists_cpf",
    "exists_phone",
    "exists_email",
    "find_by_cpf",
    "find_by_phone",
    "find_by_external_id",
    "get",
    "fill_identity",
    "update_identity",
    "get_map",
    "create",
    "attach_address",
    "get_address",
    "set_pix",
    "set_phone",
]
