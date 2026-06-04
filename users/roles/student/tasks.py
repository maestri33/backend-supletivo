"""Tasks Django-Q do `student` — validação de documento por IA (assíncrona).

A IA roda fora do request (spec: "validada por IA, inclusive de forma assíncrona — só muda status se
aprovar"). Degrada com graça: se a IA falhar/indecidir, o documento fica PENDING (não auto-aprova).
"""

from __future__ import annotations

import structlog

from users.roles.student import service

logger = structlog.get_logger()


def validate_document(student_document_id: int) -> None:
    """Valida 1 documento do aluno pela IA e grava o veredito. Enfileirada no upload."""
    from users.roles.student.models import StudentDocument

    doc = StudentDocument.objects.filter(id=student_document_id).first()
    if doc is None:
        return
    status, raw = service._ai_validate(doc)
    service.apply_validation(student_document_id, status=status, raw=raw)
    logger.info(
        "student.task_validated", student_document_id=student_document_id, status=status
    )
