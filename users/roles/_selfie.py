"""Verificação de selfie por IA — compartilhada por `candidate` e `enrollment`.

"Do jeito melhor" (Victor 2026-06-05): pede um VEREDITO direto à visão — é selfie de pessoa real (não
foto-de-foto, tela, papel ou documento)? — e lê o começo da resposta (VALIDA/INVALIDA).

Mesma régua dos documentos do student (3 estados + revisão humana): a IA classifica em
**approved** (VALIDA) · **rejected** (INVALIDA → refazer) · **review** (IA fora do ar OU resposta
ambígua → o coordenador decide o sim/não). A IA sempre devolve um motivo (guardado como justificativa).
Uma implementação só, reusada (CONVENTION §12).
"""

from __future__ import annotations

import structlog
from django.db import models

logger = structlog.get_logger()


class SelfieStatus(models.TextChoices):
    """Estados da validação da selfie (espelha StudentDocument.Validation). Usado por candidate/enrollment."""

    PENDING = "pending", "aguardando IA"
    APPROVED = "approved", "aprovada"
    REJECTED = "rejected", "reprovada (refazer)"
    REVIEW = "review", "em revisão (coordenador decide)"


APPROVED = SelfieStatus.APPROVED
REJECTED = SelfieStatus.REJECTED
REVIEW = SelfieStatus.REVIEW

_PROMPT = (
    "Esta imagem é uma SELFIE de uma pessoa real, fotografada ao vivo — e NÃO uma foto de outra foto, "
    "de tela, de papel ou de documento? Responda em português começando OBRIGATORIAMENTE com a palavra "
    "VALIDA (se for selfie de pessoa real) ou INVALIDA (caso contrário), seguida de um motivo curto."
)


def verify(
    image_bytes: bytes, content_type: str, *, caller: str
) -> tuple[str, str | None]:
    """(status, justificativa). status ∈ approved|rejected|review. IA fora/ambígua → review (humano decide)."""
    from integrations.ai import service as ai

    try:
        desc = ai.describe_image(
            image_bytes, caller=caller, mime_type=content_type, prompt=_PROMPT
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar → review (coordenador resolve)
        logger.warning("selfie_ai_failed", caller=caller, error=str(exc))
        return (
            REVIEW,
            "IA indisponível no momento — enviado para revisão manual do coordenador.",
        )
    head = (desc or "").strip().upper()[:16]
    # "INVALIDA" NÃO começa com "VALIDA" (começa com I) → startswith resolve sem ambiguidade.
    if head.startswith("VALIDA"):
        return APPROVED, desc
    if head.startswith("INVALIDA"):
        return REJECTED, desc
    return REVIEW, desc  # resposta inconclusiva → revisão humana
