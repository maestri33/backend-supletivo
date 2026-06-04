"""Grupo `leadership` (PLACEHOLDER) — coordenador do polo (cargo de confiança). Toda ação do
coordenador é sobre o `hub/`. 6c: liberar a matrícula (`awaiting_release` → student).

⚠️ 6c NÃO TESTADO (nem in-process completo, nem com fluxo real).
"""

from __future__ import annotations

from ninja import Schema
from ninja.errors import HttpError

from api.auth import require_roles
from api.base import build_group
from users.auth.models import User
from users.roles.enrollment import interface as enrollment_iface

api = build_group(
    "leadership", "Coordenador do polo (hub): aprovações, acesso, taxas, diploma."
)


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
    require_roles(request.auth, "coordinator")
    coordinator = User.objects.filter(
        external_id=request.auth.external_id, is_active=True
    ).first()
    if coordinator is None:
        raise HttpError(403, "Coordenador não encontrado.")
    try:
        enr = enrollment_iface.release(
            enrollment_external_id=external_id,
            coordinator=coordinator,
            study_platform=payload.study_platform,
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return {"external_id": str(enr.external_id), "status": enr.status}
