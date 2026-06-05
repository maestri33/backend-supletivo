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
from hub import interface as hub_iface
from users.roles.candidate import interface as candidate_iface
from users.roles.enrollment import interface as enrollment_iface
from users.roles.lead import interface as lead_iface
from users.roles.student import interface as student_iface
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


# ── leads do polo (coordenador vê os leads do SEU hub) ──────────────────────
@api.get("/leads", tags=["lead"])
def list_hub_leads(request, status: str | None = None):
    """Lista os leads do polo do coordenador (link de pagamento + comprovante). Filtro opcional por status."""
    coordinator = _coordinator(request)
    hub = hub_iface.hub_of(coordinator)
    leads = lead_iface.list_leads(hub=hub, status=status)
    return [lead_iface.lead_to_dict(lead) for lead in leads]


# ── funil do aluno: liberação da matrícula ──────────────────────────────────
class ReleaseIn(Schema):
    # dados de acesso à plataforma de estudo (campos estruturados — Victor 2026-06-04).
    platform_url: str | None = None
    platform_login: str | None = None
    platform_password: str | None = None
    platform_notes: str | None = None


class ReleaseOut(Schema):
    external_id: str
    status: str


@api.post(
    "/enrollments/{external_id}/release", response=ReleaseOut, tags=["enrollment"]
)
def release_enrollment(request, external_id: str, payload: ReleaseIn):
    """O coordenador do hub libera a matrícula → promove o aluno a `student` (cria o Student)."""
    coordinator = _coordinator(request)
    try:
        enr = enrollment_iface.release(
            enrollment_external_id=external_id,
            coordinator=coordinator,
            platform_url=payload.platform_url,
            platform_login=payload.platform_login,
            platform_password=payload.platform_password,
            platform_notes=payload.platform_notes,
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return {"external_id": str(enr.external_id), "status": enr.status}


# ── selfie em revisão (IA em dúvida) → coordenador decide o sim/não ──────────
class SelfieDecideIn(Schema):
    approve: bool
    reason: str | None = None


@api.post("/enrollments/{external_id}/selfie/decide", tags=["enrollment"])
def decide_enrollment_selfie(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a selfie de uma matrícula que a IA mandou pra REVISÃO."""
    coordinator = _coordinator(request)
    try:
        enr = enrollment_iface.decide_selfie(
            enrollment_external_id=external_id,
            coordinator=coordinator,
            approve=payload.approve,
            reason=payload.reason,
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return {
        "external_id": str(enr.external_id),
        "selfie_status": enr.selfie_status,
        "status": enr.status,
    }


@api.post("/candidates/{external_id}/selfie/decide", tags=["candidate"])
def decide_candidate_selfie(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a selfie de um candidato que a IA mandou pra REVISÃO."""
    coordinator = _coordinator(request)
    try:
        cand = candidate_iface.decide_selfie(
            candidate_external_id=external_id,
            coordinator=coordinator,
            approve=payload.approve,
            reason=payload.reason,
        )
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc
    return {
        "external_id": str(cand.external_id),
        "selfie_status": cand.selfie_status,
        "status": cand.status,
    }


# ── funil do aluno: coordenador conduz student→veteran (§4 item 9) ───────────
# ⚠️ NÃO TESTADO (nem in-process completo, nem com fluxo real).
class ExamGradeIn(Schema):
    passed: bool
    notes: str | None = None


class PendencyIn(Schema):
    kind: str  # "document" | "fee"
    description: str
    amount_cents: int | None = None  # só kind=fee (registro; NÃO move dinheiro aqui)


class DocDecideIn(Schema):
    approve: bool  # sim/não do coordenador sobre o documento em REVISÃO
    reason: str | None = None


def _student_action(external_id: str, coordinator, fn, **kw):
    try:
        return fn(student_external_id=external_id, coordinator=coordinator, **kw)
    except student_iface.StudentError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/students/{external_id}/exam/grade", tags=["student"])
def grade_exam(request, external_id: str, payload: ExamGradeIn):
    """Coordenador do hub corrige a prova: passou → conferência; reprovou → refazer."""
    coordinator = _coordinator(request)
    exam = _student_action(
        external_id,
        coordinator,
        student_iface.grade_exam,
        passed=payload.passed,
        notes=payload.notes,
    )
    return {"external_id": str(exam.external_id), "result": exam.result}


@api.post(
    "/students/{external_id}/documents/{document_external_id}/decide", tags=["student"]
)
def decide_document(
    request, external_id: str, document_external_id: str, payload: DocDecideIn
):
    """Coordenador decide um documento que a IA mandou pra REVISÃO (o sim/não dele)."""
    coordinator = _coordinator(request)
    doc = _student_action(
        external_id,
        coordinator,
        student_iface.decide_document,
        document_external_id=document_external_id,
        approve=payload.approve,
        reason=payload.reason,
    )
    return {
        "external_id": str(doc.external_id),
        "validation_status": doc.validation_status,
    }


@api.post("/students/{external_id}/pendencies", tags=["student"])
def open_pendency(request, external_id: str, payload: PendencyIn):
    """Coordenador lança uma pendência (documento OU taxa) → aluno vai pra PENDING."""
    coordinator = _coordinator(request)
    pend = _student_action(
        external_id,
        coordinator,
        student_iface.open_pendency,
        kind=payload.kind,
        description=payload.description,
        amount_cents=payload.amount_cents,
    )
    return {"external_id": str(pend.external_id), "kind": pend.kind}


@api.post("/pendencies/{external_id}/resolve", tags=["student"])
def resolve_pendency(request, external_id: str):
    """Coordenador resolve a pendência; sem pendência aberta o aluno segue pro diploma."""
    coordinator = _coordinator(request)
    try:
        pend = student_iface.resolve_pendency(
            pendency_external_id=external_id, coordinator=coordinator
        )
    except student_iface.StudentError as exc:
        raise HttpError(422, str(exc)) from exc
    return {
        "external_id": str(pend.external_id),
        "resolved": pend.resolved_at is not None,
    }


@api.post("/students/{external_id}/documentation/clear", tags=["student"])
def clear_documentation(request, external_id: str):
    """Coordenador confirma que não há pendência → libera a emissão do diploma."""
    coordinator = _coordinator(request)
    s = _student_action(external_id, coordinator, student_iface.clear_documentation)
    return {"external_id": str(s.external_id), "status": s.status}


@api.post("/students/{external_id}/diploma/issue", tags=["student"])
def issue_diploma(request, external_id: str):
    """Coordenador emite o diploma (certificado + histórico) → aluno fica AGUARDANDO RETIRADA."""
    coordinator = _coordinator(request)
    diploma = _student_action(external_id, coordinator, student_iface.issue_diploma)
    return {
        "external_id": str(diploma.external_id),
        "issued_at": diploma.issued_at.isoformat(),
    }


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
