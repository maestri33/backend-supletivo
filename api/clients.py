"""Grupo `clients` (PLACEHOLDER) — público do funil do ALUNO (**$$ ENTRA**):
lead → enrollment → student → veteran. Hoje só o esqueleto (health + whoami); as rotas de
negócio entram com cada role (§4), chamando o `interface/` in-process.
"""

from api.base import build_group

api = build_group("clients", "Funil do aluno: lead, enrollment, student, veteran.")
