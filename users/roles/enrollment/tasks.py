"""Tasks Django-Q do `enrollment` — validação do RG por IA (assíncrona, plan/12).

A IA roda fora do request (regra dos ≤10s por requisição; visão+OCR+LLM levam 10–60s): o upload
responde "em análise" e o front acompanha pelo `/enrollment/me`. Degrada com graça: IA fora do
ar/inconclusiva → `review` (coordenador decide) — nunca trava o aluno em silêncio.
"""

from __future__ import annotations

import structlog

from users.roles.enrollment import service

logger = structlog.get_logger()


def validate_rg(enrollment_id: int, slot: str) -> None:
    """Valida a foto recém-subida (visão) e, com a seção completa, extrai os dados. Enfileirada no upload."""
    service.run_rg_validation(enrollment_id, slot)
    logger.info("enrollment.task_rg_validated", enrollment_id=enrollment_id, slot=slot)


def fill_rg_data(enrollment_id: int) -> None:
    """Pós-aprovação humana (decide): OCR+extração best-effort SÓ pra preencher campos — sem veto."""
    service.run_rg_fill(enrollment_id)
    logger.info("enrollment.task_rg_filled", enrollment_id=enrollment_id)
