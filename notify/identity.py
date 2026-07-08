"""Resolve identidade (whatsapp+email) por papel do usuário.
ponytail: mapeamento central por público (aluno/candidato/promotor/coordenador/staff) → canais certos.
Quando o send() não recebe phone/email explícito, ele pode passar o User e o notify deriva.
"""
from __future__ import annotations

import structlog
from users.roles import interface as roles_iface

logger = structlog.get_logger()


# mapa de público (mais avançado primeiro, igual a roles) → (whatsapp_label, email)
# v7m = institucional/contato comercial; supletivo = aluno/processo seletivo
PUBLIC_IDENTITY = {
    "veteran": ("supletivo", "contato@supletivo.org.br"),
    "student": ("supletivo", "contato@supletivo.org.br"),
    "enrollment": ("supletivo", "contato@supletivo.org.br"),
    "lead": ("v7m", "contato@v7m.org"),
    "candidate": ("v7m", "contato@v7m.org"),
    "promoter": ("v7m", "contato@v7m.org"),
    "coordinator": ("v7m", "contato@v7m.org"),
    "staff": ("v7m", "contato@v7m.org"),
    "training": ("v7m", "contato@v7m.org"),
}

DEFAULT_WHATSAPP = "default"
DEFAULT_EMAIL = "default"


def _pick_role(roles: list[str]) -> str:
    """Pega o papel mais relevante (mais avançado primeiro, igual roles.catalog).

    Regra: usuário com múltiplas roles ativas (ex.: lead promovido a enrollment + student) — pega
    a mais avançada. Se for do "caminho do aluno" (veteran/student/enrollment), manda do
    "supletivo"; senão, do "v7m" (candidatos/promotores/coordenadores/staff).
    """
    for r in ("veteran", "student", "enrollment", "lead", "candidate", "promoter", "coordinator", "staff", "training"):
        if r in roles:
            return r
    return ""


def resolve_identity(user) -> dict:
    """Deriva {whatsapp, email} do User com base nos papéis ativos.

    whatsapp/email = "default" se o papel não está mapeado (caller decide o que fazer — usa do
    profile como fallback).
    """
    active = roles_iface.active_roles(user)
    role = _pick_role(active)
    if not role or role not in PUBLIC_IDENTITY:
        return {"whatsapp": DEFAULT_WHATSAPP, "email": DEFAULT_EMAIL, "role": role or "unknown"}
    label, email = PUBLIC_IDENTITY[role]
    return {"whatsapp": label, "email": email, "role": role}


def resolve_channels_for_event(role: str) -> dict:
    """Regras de canal por público + tipo de evento. Se a chave não existe, usa default.

    Hoje: tudo vai pro mesmo whatsapp+email derivados do papel. Ponto de extensão
    (Wave 4+): aqui entram as regras de "lead só whatsapp, aluno whatsapp+email".
    """
    return {"whatsapp": PUBLIC_IDENTITY.get(role, ("v7m", "contato@v7m.org"))[0],
            "email": PUBLIC_IDENTITY.get(role, ("v7m", "contato@v7m.org"))[1]}
