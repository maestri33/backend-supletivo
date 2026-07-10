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


def validate_selfie(enrollment_id: int) -> None:
    """Valida a selfie/assinatura (liveness → face-match vs documento → instruções se reprovar)."""
    service.run_selfie_validation(enrollment_id)
    logger.info("enrollment.task_selfie_validated", enrollment_id=enrollment_id)


def validate_address_proof(enrollment_id: int) -> None:
    """Valida o comprovante de endereço (visão → endereço bate? → titular bate?) — F1."""
    service.run_address_proof_validation(enrollment_id)
    logger.info("enrollment.task_address_proof_validated", enrollment_id=enrollment_id)


def age_stale_selfies() -> None:
    """Schedule (Django-Q): selfies `pending` com TTL estourado → `review` + notifica coord.

    Antes rodava DENTRO do `GET /enrollment/selfie` (mutava/notificava numa leitura — viola a
    idempotência HTTP). Registrado por `manage.py selfie_schedules`. Idempotente."""
    aged = service.age_stale_selfies()
    logger.info("enrollment.task_selfies_aged", aged=aged)
