"""Extratores DETERMINÍSTICOS de campos do texto do usuário (FASE 2 — motor do funil).

REGRA DE OURO (guardrail da escrita): a IA NÃO decide a ação nem extrai o dado — o MOTOR é quem
escreve, e só escreve quando um extrator DETERMINÍSTICO (regex/enum/parse de data) tira do texto um
valor NÃO-AMBÍGUO. Se a extração falhar ou ficar em dúvida, o motor NÃO escreve: a IA só pede o
campo de forma focada (ou o app finaliza). Nada aqui chama LLM.

Cada extrator recebe o texto cru do usuário e devolve o valor tipado ou `None` (não achei /
ambíguo). `None` => o motor pede o campo; nunca chuta.
"""

from __future__ import annotations

import re

# ── CEP: 8 dígitos (com ou sem máscara 00000-000) ───────────────────────────
# Exige EXATAMENTE 8 dígitos isolados (fronteira) pra não casar pedaço de telefone/CPF. Se houver
# mais de um CEP plausível no texto, é ambíguo → None (o motor pede de novo).
_CEP_RE = re.compile(r"(?<!\d)(\d{5})-?\.?\s?(\d{3})(?!\d)")


def cep(text: str) -> str | None:
    """CEP normalizado (8 dígitos, sem máscara) ou None. Mais de um CEP no texto => ambíguo => None."""
    matches = _CEP_RE.findall(text or "")
    if len(matches) != 1:
        return None  # zero achados, ou ambíguo (vários) → não escreve
    return matches[0][0] + matches[0][1]


# ── Tipo sanguíneo: enum fechado (mesma lista do Student.BloodType) ─────────
_BLOOD_TYPES = (
    "AB+",
    "AB-",
    "A+",
    "A-",
    "B+",
    "B-",
    "O+",
    "O-",
)  # AB antes de A/B (prefixo)
# Aceita "A positivo", "o negativo", "AB+", "tipo sanguíneo b-" etc. Normaliza p/ o código do enum.
_BLOOD_WORD = re.compile(
    r"\b(ab|a|b|o)\s*(positivo|negativo|pos|neg|\+|-)\b", re.IGNORECASE
)


def blood_type(text: str) -> str | None:
    """Tipo sanguíneo no formato do enum (A+, O-, AB+, ...) ou None se não-achado/ambíguo."""
    t = (text or "").upper().replace(" ", "")
    # 1) forma direta colada: A+, AB-, O+ ...
    direct = [bt for bt in _BLOOD_TYPES if bt in t]
    if len(direct) == 1:
        return direct[0]
    if len(direct) > 1:
        return None  # mencionou mais de um → ambíguo
    # 2) forma por extenso: "A positivo", "O negativo"
    found = _BLOOD_WORD.findall(text or "")
    if len(found) != 1:
        return None
    group, sign = found[0]
    sign_norm = "+" if sign.lower() in ("positivo", "pos", "+") else "-"
    candidate = group.upper() + sign_norm
    return candidate if candidate in _BLOOD_TYPES else None
