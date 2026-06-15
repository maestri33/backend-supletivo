"""Schemas compartilhados entre grupos da API Ninja (CONVENTION §12: reusar, não duplicar).

A autoria de matéria do treino é feita por DOIS públicos — `staff` (administração) e `leadership`
(o coordenador também autora, palavra do Victor) — com o MESMO contrato. Os schemas vivem aqui pra
não duplicar (plan/15 A7).
"""

from __future__ import annotations

from ninja import Schema


class MaterialIn(Schema):
    """Criação de uma matéria do treino (texto + questão + gabarito)."""

    title: str
    text_content: str
    question: str
    expected_answer: str
    order: int = 0


class MaterialUpdateIn(Schema):
    """Edição de uma matéria — só os campos enviados; `active=False` desativa."""

    title: str | None = None
    text_content: str | None = None
    question: str | None = None
    expected_answer: str | None = None
    order: int | None = None
    active: bool | None = None
