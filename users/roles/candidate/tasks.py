"""Tasks Django-Q do `candidate` — validação do documento por IA (assíncrona, plan/15 B3).

Espelho do `enrollment/tasks.py` (plan/12): a IA roda fora do request (≤10s/req; visão+OCR+LLM
levam 10–60s); o upload responde ack e o front acompanha pelo `/candidate/me`. Degrada com
graça: IA fora/inconclusiva → `review` (coordenador decide).
"""

from __future__ import annotations

import structlog

from users.roles.candidate import service

logger = structlog.get_logger()


def validate_document(candidate_id: int, slot: str) -> None:
    """Valida a foto recém-subida (visão) e, com a seção completa, extrai os dados. Enfileirada no upload."""
    service.run_document_validation(candidate_id, slot)
    logger.info("candidate.task_doc_validated", candidate_id=candidate_id, slot=slot)


def fill_document_data(candidate_id: int) -> None:
    """Pós-aprovação humana (decide): OCR+extração best-effort SÓ pra preencher campos — sem veto."""
    service.run_document_fill(candidate_id)
    logger.info("candidate.task_doc_filled", candidate_id=candidate_id)


def validate_candidate_selfie(candidate_id: int) -> None:
    """Valida a selfie/assinatura (liveness → face-match vs documento → instruções se reprovar)."""
    service.run_selfie_validation(candidate_id)
    logger.info("candidate.task_selfie_validated", candidate_id=candidate_id)
