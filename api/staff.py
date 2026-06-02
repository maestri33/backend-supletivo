"""Grupo `staff` (PLACEHOLDER) — administração da plataforma (o "boss": cadastra hub, define
coordenador, vê saúde dos serviços). Hoje só o esqueleto; rotas entram com o app `staff` (§4).
"""

from api.base import build_group

api = build_group(
    "staff", "Administração da plataforma: hub, coordenador, saúde dos serviços."
)
