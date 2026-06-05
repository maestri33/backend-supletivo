"""Lógica do training (LMS): autoria de matéria (staff+coordenador), submissão+correção por IA, entrevista.

Fluxo: o candidato vira `Trainee(TRAINING)` (criado pela transição candidate→training). Ele responde as
matérias → cada `Submission` é corrigida pela IA (Django-Q `tasks.grade_submission` → `ai.grade`) → ≥ nota
de corte aprova. Aprovou TODAS as matérias ativas → `Trainee` vira `awaiting_interview` (notifica o
coordenador). O coordenador aprova → promove `training→promoter` + cria o `Promoter`.
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from django.db import transaction
from django.utils import timezone

from users.roles import interface as roles
from users.roles.training.config import pass_score
from users.roles.training.models import Material, Submission, Trainee

logger = structlog.get_logger()


class TrainingError(Exception):
    """Erro de borda do training (matéria/trainee não encontrado, etapa fora de ordem, gate)."""


# ── autoria de matéria (staff + coordenador) ────────────────────────────────


def create_material(
    *, title, text_content, question, expected_answer, order=0
) -> Material:
    return Material.objects.create(
        title=title,
        text_content=text_content,
        question=question,
        expected_answer=expected_answer,
        order=order,
        active=True,
    )


def _material(external_id: str) -> Material:
    m = Material.objects.filter(external_id=external_id).first()
    if m is None:
        raise TrainingError("material_not_found")
    return m


def update_material(external_id: str, **fields) -> Material:
    m = _material(external_id)
    allowed = {
        "title",
        "text_content",
        "question",
        "expected_answer",
        "order",
        "active",
        "video",
        "photo",
    }
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(m, key, value)
    m.save()
    return m


def list_materials(*, active_only: bool = True) -> list[Material]:
    qs = Material.objects.all()
    if active_only:
        qs = qs.filter(active=True)
    return list(qs.order_by("order", "id"))


def material_to_dict(m: Material, *, include_answer: bool = False) -> dict:
    data = {
        "external_id": str(m.external_id),
        "title": m.title,
        "text_content": m.text_content,
        "question": m.question,
        "video": m.video,
        "photo": m.photo,
        "order": m.order,
        "active": m.active,
    }
    if include_answer:  # só pra autoria (staff/coordenador), nunca pro trainee
        data["expected_answer"] = m.expected_answer
    return data


# ── trainee ─────────────────────────────────────────────────────────────────


def create_trainee(*, user) -> Trainee:
    """Cria o Trainee(TRAINING). Chamado pela transição candidate→training. Idempotente."""
    existing = Trainee.objects.filter(user=user).first()
    if existing is not None:
        return existing
    trainee = Trainee.objects.create(user=user, status=Trainee.Status.TRAINING)
    logger.info("training.trainee_created", external_id=str(trainee.external_id))
    return trainee


def get_trainee_for_user_external_id(external_id: str) -> Trainee | None:
    return (
        Trainee.objects.filter(user__external_id=external_id)
        .select_related("user")
        .first()
    )


def trainee_to_dict(t: Trainee) -> dict:
    return {"external_id": str(t.external_id), "status": t.status}


# ── submissão (autenticado, role training) ──────────────────────────────────


def submit(
    *, user_external_id: str, material_external_id: str, answer: str
) -> Submission:
    from users.auth.models import User

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise TrainingError("user_not_found")
    material = _material(material_external_id)
    if not material.active:
        raise TrainingError("material_inactive")
    # bloqueia 2ª pending na mesma matéria (não gasta IA em dobro)
    if Submission.objects.filter(
        user=user, material=material, status=Submission.Status.PENDING
    ).exists():
        raise TrainingError("already_grading")

    sub = Submission.objects.create(
        user=user, material=material, answer=answer, status=Submission.Status.PENDING
    )

    def _queue():
        from django_q.tasks import async_task

        async_task("users.roles.training.tasks.grade_submission", sub.id)

    transaction.on_commit(_queue)
    logger.info("training.submitted", external_id=str(sub.external_id))
    return sub


def submission_to_dict(s: Submission) -> dict:
    return {
        "external_id": str(s.external_id),
        "material_external_id": str(s.material.external_id),
        "grade": str(s.grade) if s.grade is not None else None,
        "justification": s.justification,
        "status": s.status,
    }


def progress(user_external_id: str) -> list[dict]:
    """Por matéria ativa: última submissão (status/nota/justificativa) ou `not_started`."""
    from users.auth.models import User

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise TrainingError("user_not_found")
    out = []
    for m in list_materials(active_only=True):
        last = (
            Submission.objects.filter(user=user, material=m)
            .order_by("-created_at")
            .first()
        )
        out.append(
            {
                "material_external_id": str(m.external_id),
                "title": m.title,
                "status": last.status if last else "not_started",
                "grade": str(last.grade) if last and last.grade is not None else None,
                "justification": last.justification if last else None,
            }
        )
    return out


# ── correção (chamada pela task Django-Q após a IA) ─────────────────────────


def apply_grade(submission_id: int, grade_value, justification: str) -> None:
    sub = (
        Submission.objects.select_related("material", "user")
        .filter(id=submission_id)
        .first()
    )
    if sub is None or sub.status != Submission.Status.PENDING:
        return  # idempotente (re-grade não re-aplica)
    sub.grade = Decimal(str(grade_value))
    sub.justification = justification
    sub.status = (
        Submission.Status.APPROVED
        if sub.grade >= pass_score()
        else Submission.Status.REJECTED
    )
    sub.save(update_fields=["grade", "justification", "status", "updated_at"])
    logger.info(
        "training.graded",
        external_id=str(sub.external_id),
        grade=str(sub.grade),
        status=sub.status,
    )
    if sub.status == Submission.Status.APPROVED:
        _maybe_awaiting_interview(sub.user)


def _maybe_awaiting_interview(user) -> None:
    """Aprovou TODAS as matérias ativas → Trainee vira awaiting_interview + notifica o coordenador."""
    active_ids = set(Material.objects.filter(active=True).values_list("id", flat=True))
    if not active_ids:
        return
    approved_ids = set(
        Submission.objects.filter(
            user=user, status=Submission.Status.APPROVED
        ).values_list("material_id", flat=True)
    )
    if not active_ids.issubset(approved_ids):
        return
    trainee = Trainee.objects.filter(user=user).first()
    if trainee is None or trainee.status != Trainee.Status.TRAINING:
        return
    trainee.status = Trainee.Status.AWAITING_INTERVIEW
    trainee.awaiting_interview_at = timezone.now()
    trainee.save(update_fields=["status", "awaiting_interview_at", "updated_at"])
    _notify_coordinator_interview(trainee)


def _hub_of_trainee(trainee: Trainee):
    """O hub do candidato que virou trainee (origem da herança pro promoter)."""
    from users.roles.candidate.models import Candidate

    cand = (
        Candidate.objects.filter(user=trainee.user)
        .select_related("hub", "hub__coordinator")
        .first()
    )
    return cand.hub if cand else None


def _notify_coordinator_interview(trainee: Trainee) -> None:
    from notify.interface.send import send
    from users.profiles import interface as profiles

    hub = _hub_of_trainee(trainee)
    coord = hub.coordinator if hub else None
    if coord is None:
        return
    cp = profiles.get(coord)
    from users.roles import notifications as msgs

    try:
        send(
            text=msgs.text(
                "training.awaiting_interview",
                name=msgs.first_name(cp.name if cp else None),
            ),
            caller="training.awaiting_interview",
            phone=cp.phone if cp else None,
            idempotency_key=f"trainee_interview_{trainee.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("training.notify_coord_failed", error=str(exc))


# ── entrevista (coordenador, grupo leadership) ──────────────────────────────


def approve_interview(*, trainee_external_id: str, coordinator) -> Trainee:
    """Coordenador do hub aprova → promove `training→promoter` + cria o `Promoter` (hub herdado)."""
    from users.roles.promoter import interface as promoter_iface

    trainee = (
        Trainee.objects.filter(external_id=trainee_external_id)
        .select_related("user")
        .first()
    )
    if trainee is None:
        raise TrainingError("trainee_not_found")
    hub = _hub_of_trainee(trainee)
    if hub is None:
        raise TrainingError("no_hub")
    if hub.coordinator_id != coordinator.id:
        raise TrainingError("not_hub_coordinator")
    if trainee.status != Trainee.Status.AWAITING_INTERVIEW:
        raise TrainingError(f"wrong_status:{trainee.status}")

    with transaction.atomic():
        if "promoter" not in roles.active_roles(trainee.user):
            roles.promote(trainee.user, "promoter")
        promoter_iface.create_promoter(user=trainee.user, hub=hub)
        trainee.status = Trainee.Status.APPROVED
        trainee.coordinator = coordinator
        trainee.decision_at = timezone.now()
        trainee.save(
            update_fields=["status", "coordinator", "decision_at", "updated_at"]
        )

    _notify_approved(trainee)
    logger.info("training.approved", external_id=str(trainee.external_id))
    return trainee


def reject_interview(*, trainee_external_id: str, coordinator, reason: str) -> Trainee:
    trainee = (
        Trainee.objects.filter(external_id=trainee_external_id)
        .select_related("user")
        .first()
    )
    if trainee is None:
        raise TrainingError("trainee_not_found")
    hub = _hub_of_trainee(trainee)
    if hub is None or hub.coordinator_id != coordinator.id:
        raise TrainingError("not_hub_coordinator")
    if trainee.status != Trainee.Status.AWAITING_INTERVIEW:
        raise TrainingError(f"wrong_status:{trainee.status}")
    trainee.status = Trainee.Status.REJECTED
    trainee.coordinator = coordinator
    trainee.decision_at = timezone.now()
    trainee.rejection_reason = (reason or "")[:255]
    trainee.save(
        update_fields=[
            "status",
            "coordinator",
            "decision_at",
            "rejection_reason",
            "updated_at",
        ]
    )
    logger.info("training.rejected", external_id=str(trainee.external_id))
    return trainee


def _notify_approved(trainee: Trainee) -> None:
    from notify.interface.send import send
    from users.profiles import interface as profiles
    from users.roles import notifications as msgs

    p = profiles.get(trainee.user)
    try:
        send(
            text=msgs.text(
                "training.approved", name=msgs.first_name(p.name if p else None)
            ),
            caller="training.approved",
            phone=p.phone if p else None,
            email=p.email if p else None,
            email_channel=bool(p and p.email),
            tts=msgs.is_tts(
                "training.approved"
            ),  # virou promotor = momento especial (voz)
            gender=p.gender if p else None,
            idempotency_key=f"trainee_approved_{trainee.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("training.notify_approved_failed", error=str(exc))
