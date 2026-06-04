"""Grupo `leadership` (PLACEHOLDER) — coordenador do polo (cargo de confiança). Toda ação do
coordenador é sobre o `hub/`.

- Funil do aluno: liberar a matrícula (`awaiting_release` → student).
- Funil do colaborador: autoria de matéria do treino (também) + **entrevista** (aprovar/rejeitar o trainee
  do seu polo → promove a promotor).

⚠️ NÃO TESTADO (nem in-process completo, nem com fluxo real).
"""

from __future__ import annotations

from ninja import Schema
from ninja.errors import HttpError

from api.auth import require_roles
from api.base import build_group
from users.auth.models import User
from users.roles.enrollment import interface as enrollment_iface
from users.roles.training import interface as training_iface

api = build_group(
    "leadership", "Coordenador do polo (hub): aprovações, acesso, taxas, diploma."
)


def _coordinator(request) -> User:
    """Gate role coordinator + devolve o User do coordenador logado."""
    require_roles(request.auth, "coordinator")
    user = User.objects.filter(
        external_id=request.auth.external_id, is_active=True
    ).first()
    if user is None:
        raise HttpError(403, "Coordenador não encontrado.")
    return user


# ── funil do aluno: liberação da matrícula ──────────────────────────────────
class ReleaseIn(Schema):
    study_platform: dict | None = (
        None  # dados de acesso à plataforma externa (schema livre por ora)
    )


class ReleaseOut(Schema):
    external_id: str
    status: str


@api.post(
    "/enrollments/{external_id}/release", response=ReleaseOut, tags=["enrollment"]
)
def release_enrollment(request, external_id: str, payload: ReleaseIn):
    """O coordenador do hub libera a matrícula → promove o aluno a `student`."""
    coordinator = _coordinator(request)
    try:
        enr = enrollment_iface.release(
            enrollment_external_id=external_id,
            coordinator=coordinator,
            study_platform=payload.study_platform,
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return {"external_id": str(enr.external_id), "status": enr.status}


# ── funil do colaborador: autoria de matéria (coordenador também — Victor) ──
class MaterialIn(Schema):
    title: str
    text_content: str
    question: str
    expected_answer: str
    order: int = 0


class MaterialUpdateIn(Schema):
    title: str | None = None
    text_content: str | None = None
    question: str | None = None
    expected_answer: str | None = None
    order: int | None = None
    active: bool | None = None


@api.post("/training/materials", tags=["training"])
def create_material(request, payload: MaterialIn):
    _coordinator(request)
    m = training_iface.create_material(**payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.put("/training/materials/{external_id}", tags=["training"])
def update_material(request, external_id: str, payload: MaterialUpdateIn):
    _coordinator(request)
    try:
        m = training_iface.update_material(external_id, **payload.dict())
    except training_iface.TrainingError as exc:
        raise HttpError(404, str(exc)) from exc
    return training_iface.material_to_dict(m, include_answer=True)


# ── funil do colaborador: entrevista (aprovar/rejeitar trainee → promotor) ──
class RejectIn(Schema):
    reason: str


@api.post("/trainees/{external_id}/approve", tags=["training"])
def approve_trainee(request, external_id: str):
    """Aprova a entrevista do trainee do seu polo → promove a promotor."""
    coordinator = _coordinator(request)
    try:
        t = training_iface.approve_interview(
            trainee_external_id=external_id, coordinator=coordinator
        )
    except training_iface.TrainingError as exc:
        raise HttpError(422, str(exc)) from exc
    return training_iface.trainee_to_dict(t)


@api.post("/trainees/{external_id}/reject", tags=["training"])
def reject_trainee(request, external_id: str, payload: RejectIn):
    """Rejeita a entrevista do trainee (com motivo) — não promove."""
    coordinator = _coordinator(request)
    try:
        t = training_iface.reject_interview(
            trainee_external_id=external_id,
            coordinator=coordinator,
            reason=payload.reason,
        )
    except training_iface.TrainingError as exc:
        raise HttpError(422, str(exc)) from exc
    return training_iface.trainee_to_dict(t)
