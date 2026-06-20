"""Tasks Django-Q do training: correção assíncrona da submissão pela IA (`ai.grade`).

Enfileirada por `service.submit` (após o commit). Degrade gracioso: se a IA falha, a submissão fica
`pending` (re-correção possível) — nunca derruba o fluxo do treino.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


def grade_submission(submission_id: int) -> None:
    from integrations.ai import service as ai
    from users.roles.training import service as training_service
    from users.roles.training.models import Submission

    sub = Submission.objects.select_related("material").filter(id=submission_id).first()
    if sub is None or sub.status != Submission.Status.PENDING:
        return
    try:
        grading = ai.grade(
            question=sub.material.question,
            expected_answer=sub.material.expected_answer,
            student_answer=sub.answer,
            caller="training.grade",
        )
    except Exception as exc:  # noqa: BLE001 — IA fora → fica pending (degrade gracioso)
        logger.warning(
            "training.grade_failed", submission_id=submission_id, error=str(exc)
        )
        return
    training_service.apply_grade(submission_id, grading.grade, grading.justification)
