"""Grupo `leadership` (PLACEHOLDER) — coordenador do polo (cargo de confiança). Centraliza no
`hub/` (toda ação do coordenador é sobre o polo). Hoje só o esqueleto; rotas entram com o `hub` (§4).
"""

from api.base import build_group

api = build_group(
    "leadership", "Coordenador do polo (hub): aprovações, acesso, taxas, diploma."
)
