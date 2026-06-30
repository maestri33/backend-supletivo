"""Triagem da fila do coordenador (`/reviews`) — função PURA, determinística, read-only.

O `/reviews` já junta TUDO que espera o coordenador, mas em baldes separados, sem ordem entre si: o
coordenador não sabe o que atacar primeiro. `prioritize` achata os baldes numa fila ÚNICA ordenada
por urgência, com um score determinístico (sem IA: barato, previsível, explicável).

Score = peso-base do tipo + bônus por tempo de espera (quanto mais antigo, mais urgente). Os pesos
são um DEFAULT conservador (Victor ajusta): priorizam o que TRAVA um fluxo de dinheiro/pessoa —
promotor preso no treino (não vende) e candidato aguardando virar promotor — acima de uma revisão de
documento de rotina. NÃO inventa dados: lê só `type`/`kind`/`since` que o `/reviews` já normaliza.
"""

from __future__ import annotations

from datetime import datetime, timezone as _tz

# peso-base por (type, kind) — quanto MAIOR, mais no topo. Default conservador; o Victor calibra.
_BASE_WEIGHT: dict[tuple[str, str], float] = {
    (
        "promoter",
        "locked_training",
    ): 30.0,  # promotor travado no treino = não vende (gargalo $$)
    (
        "candidate",
        "awaiting_approval",
    ): 25.0,  # candidato pronto a virar promotor (destrava venda)
    ("candidate", "selfie"): 15.0,
    ("candidate", "document"): 15.0,
    ("enrollment", "selfie"): 12.0,  # matrícula em andamento (cliente esperando)
    ("enrollment", "rg"): 12.0,
    ("student", "document"): 10.0,
}
_DEFAULT_WEIGHT = 8.0
# bônus por hora de espera, com teto (uma espera de 1 semana não enterra tudo o mais pra sempre).
_AGE_BONUS_PER_HOUR = 0.5
_AGE_BONUS_CAP = 72.0  # ~6 pontos no teto (12h*0.5 ... 144h alcança o cap)

# todos os baldes que o list_reviews (`api/leadership.py`) devolve.
_BUCKETS = (
    "enrollment_rg",
    "enrollment_selfie",
    "candidate_document",
    "candidate_selfie",
    "student_documents",
    "candidates_awaiting_approval",
    "locked_promoters",
)


def _age_hours(since: str | None, *, now: datetime) -> float:
    """Horas desde `since` (ISO). Sem data ou ilegível → 0 (não inventa espera)."""
    if not since:
        return 0.0
    try:
        dt = datetime.fromisoformat(since)
    except (ValueError, TypeError):
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    delta = (now - dt).total_seconds() / 3600.0
    return max(0.0, delta)


def _score(item: dict, *, now: datetime) -> float:
    """Score de urgência do item: peso-base do (type, kind) + bônus de espera (com teto)."""
    base = _BASE_WEIGHT.get(
        (item.get("type", ""), item.get("kind", "")), _DEFAULT_WEIGHT
    )
    age = _age_hours(item.get("since"), now=now)
    return base + min(age, _AGE_BONUS_CAP) * _AGE_BONUS_PER_HOUR


def prioritize(reviews: dict, *, now: datetime | None = None) -> list[dict]:
    """Achata os baldes do `/reviews` numa fila ÚNICA ordenada por urgência (mais urgente primeiro).

    Cada item ganha `priority_score` (float) e `waiting_hours` (int) — o front pode mostrar e o
    coordenador entende a ordem. Determinística: mesmo input → mesma ordem (desempate por external_id
    pra ser estável). PURA: não toca DB; recebe o dict que o endpoint já montou.
    """
    now = now or datetime.now(_tz.utc)
    flat: list[dict] = []
    for bucket in _BUCKETS:
        for item in reviews.get(bucket, []) or []:
            score = _score(item, now=now)
            flat.append(
                {
                    **item,
                    "priority_score": round(score, 2),
                    "waiting_hours": int(_age_hours(item.get("since"), now=now)),
                }
            )
    flat.sort(
        key=lambda it: (-it["priority_score"], str(it.get("external_id") or "")),
    )
    return flat
