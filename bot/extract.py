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
_BLOOD_TYPES = ("AB+", "AB-", "A+", "A-", "B+", "B-", "O+", "O-")

# G12/#22: forma DIRETA (A+, AB-, O+). Ancorada por fronteira (sem letra grudada antes), com o
# grupo casado como token — NÃO por substring (`"B+" in "AB+"` fazia AB nunca registrar). A
# alternância (AB|A|B|O) tenta AB primeiro (longest-match): "AB+" casa "AB", não "B".
_BLOOD_DIRECT = re.compile(r"(?<![A-Za-z])(AB|A|B|O)\s*([+-])", re.IGNORECASE)

# G12/#6: forma por EXTENSO ("A positivo") só conta COM contexto de sangue. Sem isso, "o positivo é
# que já paguei" gravava O+ — dado clínico a partir de frase que não fala de sangue (viola a regra
# de ouro do módulo: nunca chutar). Sem contexto → None → o motor pede no formato "A+".
_BLOOD_CONTEXT = re.compile(r"\b(sangue|sangu[íi]ne[oa]|tipagem)\b", re.IGNORECASE)
_BLOOD_WORD = re.compile(
    r"(?<![A-Za-z])(AB|A|B|O)\s+(positivo|negativo|pos|neg)\b", re.IGNORECASE
)


def blood_type(text: str) -> str | None:
    """Tipo sanguíneo no formato do enum (A+, O-, AB+, ...) ou None se não-achado/ambíguo.

    Forma direta (A+, AB-) é aceita direto; forma por extenso ("A positivo") exige contexto de
    sangue no texto (senão "o positivo" viraria O+). Ambíguo/sem-contexto → None (o motor pede)."""
    text = text or ""
    # 1) forma direta: A+, AB-, O+ ... (match ancorado, longest-first)
    direct = list(
        dict.fromkeys(
            m.group(1).upper() + m.group(2) for m in _BLOOD_DIRECT.finditer(text)
        )
    )
    if len(direct) == 1 and direct[0] in _BLOOD_TYPES:
        return direct[0]
    if len(direct) > 1:
        return None  # mencionou mais de um → ambíguo
    # 2) forma por extenso: "A positivo" — só com contexto de sangue
    if not _BLOOD_CONTEXT.search(text):
        return None
    found = _BLOOD_WORD.findall(text)
    if len(found) != 1:
        return None
    group, sign = found[0]
    sign_norm = "+" if sign.lower().startswith("pos") else "-"
    candidate = group.upper() + sign_norm
    return candidate if candidate in _BLOOD_TYPES else None
