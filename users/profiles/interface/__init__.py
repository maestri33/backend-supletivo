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


def set_pix(external_id: str, pix_key: str) -> Profile | None:
    """Grava a chave Pix no profile. Só o campo — validação Asaas/DICT é ciclo do `candidate`."""
    profile = find_by_external_id(external_id)
    if profile is None:
        return None
    profile.pix_key = pix_key
    profile.save(update_fields=["pix_key"])
    return profile


__all__ = [
    "exists_cpf",
    "exists_phone",
    "exists_email",
    "find_by_cpf",
    "find_by_phone",
    "find_by_external_id",
    "get",
    "create",
    "attach_address",
    "get_address",
    "set_pix",
]
