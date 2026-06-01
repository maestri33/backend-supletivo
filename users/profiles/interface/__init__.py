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


def get(user) -> Profile | None:
    """Profile do User (ou None se ainda não tem)."""
    return Profile.objects.filter(user=user).first()


def create(
    *, user, cpf: str, phone: str, email: str | None = None, gender: str | None = None
) -> Profile:
    """Cria o Profile 1-1 do User. Chamado DENTRO da transação atômica do register (auth)."""
    return Profile.objects.create(
        user=user,
        cpf=cpf,
        phone=phone,
        email=email,
        gender=gender,
    )


__all__ = [
    "exists_cpf",
    "exists_phone",
    "exists_email",
    "find_by_cpf",
    "find_by_phone",
    "get",
    "create",
]
