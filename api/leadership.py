"""Grupo `leadership` — coordenador do polo (cargo de confiança). Toda ação do coordenador é
sobre o `hub/` (plan/14, Victor 2026-06-12).

- **Entrada**: `/auth/check` (diz se coordena um polo; quem não coordena é redirecionado pra área
  da própria role) + `/auth/login` (OTP → JWT; NÃO há registro — só o staff cadastra polo e
  define o coordenador) + `/auth/refresh`.
- **Consultas**: leads do polo (lista + detalhe COMPLETO), matrículas (lista + filtro + detalhe
  rico) e `/reviews` (tudo que espera análise/decisão do coordenador, num lugar só).
- **Funil do aluno**: a fase da TAXA em 2 parcelas (`fee/pay` à vista + `fee/schedule` pro
  vencimento do QR) → `conclude` (credenciais da plataforma → promove a student). O aluno NUNCA
  sabe da taxa (política interna do polo).
- **Funil do colaborador**: autoria de matéria do treino + entrevista (aprovar/rejeitar trainee).
"""

from __future__ import annotations

from ninja import Field, Router, Schema
from ninja.errors import HttpError

from api.auth import require_roles
from api.base import build_group
from users.auth import interface as auth_iface
from users.auth.jwt import service as jwt_service
from users.auth.models import User
from users.exceptions import Forbidden, NotFound, Unauthorized
from hub import interface as hub_iface
from users.roles.candidate import interface as candidate_iface
from users.roles.enrollment import interface as enrollment_iface
from users.roles.lead import interface as lead_iface
from users.roles.student import interface as student_iface
from users.roles.training import interface as training_iface

api = build_group(
    "leadership", "Coordenador do polo (hub): aprovações, acesso, taxas, diploma."
)

_NOT_COORDINATOR_DETAIL = (
    "Você não pode entrar como coordenador: não coordena nenhum polo. "
    "Faça seu login na área da sua função."
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


def _coordinator_hub(coordinator: User):
    """O polo que o coordenador COORDENA (gate duro plan/14 — sem fallback de promotor/padrão)."""
    hub = hub_iface.coordinated_by(coordinator)
    if hub is None:
        raise Forbidden(_NOT_COORDINATOR_DETAIL, code="NOT_HUB_COORDINATOR")
    return hub


# ── entrada do coordenador (público): check → login (OTP) → refresh — plan/14 ───────────────
class CheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None
    external_id: str | None = None  # re-dispara OTP de usuário já conhecido (do USER)


class HubOut(Schema):
    external_id: str
    brand: str


class CoordinatorCheckOut(Schema):
    found: bool
    external_id: str | None = Field(
        None, description="external_id do USER (é o que o /auth/login espera)"
    )
    otp_sent: bool = False
    otp_wait: int | None = None
    whatsapp: bool | None = None
    roles: list[str] | None = None
    is_coordinator: bool = False
    hub: HubOut | None = Field(
        None, description="o polo que a pessoa coordena (se coordena)"
    )
    detail: str | None = Field(
        None,
        description="presente quando a pessoa existe mas NÃO coordena polo — o front "
        "redireciona pra área de login da role dela (em `roles`), levando o external_id",
    )


class LoginIn(Schema):
    external_id: str = Field(description="external_id do USER (veio do /auth/check)")
    otp: str


class RefreshIn(Schema):
    refresh_token: str


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str


auth_router = Router(tags=["auth"])


@auth_router.post("/check", response=CoordinatorCheckOut, auth=None)
def check(request, payload: CheckIn):
    """REUSA o check geral (acha a pessoa e dispara o OTP normal — §5: vaza existência de
    propósito) e soma a resposta do coordenador: coordena um polo? Quem NÃO coordena recebe
    `detail` + `roles` — o front redireciona pra área certa levando o `external_id`, e a pessoa
    loga lá com o MESMO OTP já enviado (palavra do Victor 2026-06-12)."""
    result = auth_iface.check(
        cpf=payload.cpf, phone=payload.phone, external_id=payload.external_id
    )
    if not result.get("found"):
        return result
    user = User.objects.filter(
        external_id=result["external_id"], is_active=True
    ).first()
    hub = hub_iface.coordinated_by(user) if user else None
    if hub is None:
        return {**result, "is_coordinator": False, "detail": _NOT_COORDINATOR_DETAIL}
    return {
        **result,
        "is_coordinator": True,
        "hub": {"external_id": str(hub.external_id), "brand": hub.brand},
    }


@auth_router.post("/login", response=TokenOut, auth=None)
def login(request, payload: LoginIn):
    """Login do COORDENADOR (OTP do check → JWT). NÃO há registro neste grupo: só o staff cadastra
    o polo e define quem coordena. Quem não coordena polo → 403 com a mesma mensagem do check."""
    user = User.objects.filter(external_id=payload.external_id, is_active=True).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    if hub_iface.coordinated_by(user) is None:
        raise Forbidden(_NOT_COORDINATOR_DETAIL, code="NOT_HUB_COORDINATOR")
    return auth_iface.login(
        external_id=payload.external_id, role="coordinator", otp=payload.otp
    )


@auth_router.post("/refresh", response=TokenOut, auth=None)
def refresh(request, payload: RefreshIn):
    """Renova o par de tokens (rotação) — espelho do clients, pro front do coordenador não
    depender de outro grupo."""
    try:
        return jwt_service.refresh(payload.refresh_token)
    except jwt_service.TokenError as exc:
        raise Unauthorized(
            "Sessão expirada — faça login novamente.", code="SESSION_EXPIRED"
        ) from exc


api.add_router("/auth", auth_router)


# ── leads do polo (coordenador vê os leads do SEU hub) ──────────────────────
@api.get("/leads", tags=["lead"])
def list_hub_leads(request, status: str | None = None):
    """Lista os leads do polo do coordenador (link de pagamento + comprovante). Filtro opcional por status."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    leads = lead_iface.list_leads(hub=hub, status=status)
    return [lead_iface.lead_to_dict(lead) for lead in leads]


@api.get("/leads/{external_id}", tags=["lead"])
def get_hub_lead(request, external_id: str):
    """Detalhe COMPLETO de um lead do polo — o coordenador vê TUDO (nome, cpf, e-mail, telefone,
    promotor, checkout com link e recibo — Victor 2026-06-12). 404 se não existe OU não é do polo."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    lead = lead_iface.get_lead_for_hub(external_id=external_id, hub=hub)
    if lead is None:
        raise NotFound("Lead não encontrado neste polo.", code="LEAD_NOT_FOUND")
    return lead_iface.lead_self_dict(lead)


# ── matrículas do polo: lista + detalhe + análises pendentes (plan/14) ──────
@api.get("/enrollments", tags=["enrollment"])
def list_hub_enrollments(request, status: str | None = None):
    """Matrículas do polo: status REAL + resumo das 2 parcelas da taxa em cada item.
    `?status=awaiting_release` = quem terminou o wizard e espera ação do coordenador."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    return enrollment_iface.list_for_hub(hub=hub, status=status)


@api.get("/enrollments/{external_id}", tags=["enrollment"])
def get_hub_enrollment(request, external_id: str):
    """Detalhe COMPLETO de uma matrícula do polo: todas as seções do wizard (visão rica do /me) +
    status REAL (sem máscara) + situação das 2 parcelas da taxa."""
    coordinator = _coordinator(request)
    return enrollment_iface.detail_for_hub(
        enrollment_external_id=external_id, coordinator=coordinator
    )


@api.get("/reviews", tags=["review"])
def list_reviews(request):
    """TUDO que espera análise/decisão do coordenador no polo, num lugar só (plan/14): RG e selfie
    de matrículas em revisão, selfie de candidatos, documentos de students e entrevistas de
    trainees. Cada item aponta pro POST de decisão correspondente (que já existe)."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    enrollment_reviews = enrollment_iface.list_reviews_for_hub(hub=hub)
    return {
        "enrollment_rg": enrollment_reviews["rg"],
        "enrollment_selfie": enrollment_reviews["selfie"],
        "candidate_selfie": candidate_iface.list_selfie_reviews_for_hub(hub=hub),
        "student_documents": student_iface.list_document_reviews_for_hub(hub=hub),
        "trainees_awaiting_interview": training_iface.list_awaiting_interview_for_hub(
            hub=hub
        ),
    }


# ── funil do aluno: fase da TAXA (2 parcelas) → conclusão (plan/14) ─────────
# Substitui o `/release` antigo (QRs juntos) — descartado pelo Victor 2026-06-12 ("delírio de IA").
class FeeIn(Schema):
    qr_code: str = Field(
        description="QR code PIX (copia-e-cola) da cobrança do credenciador"
    )
    amount: str | None = Field(
        None, description="opcional — sem ele, usa o valor de DENTRO do QR"
    )


class ConcludeIn(Schema):
    # credenciais da plataforma de estudo — a instituição só as libera com a 1ª parcela PAGA.
    platform_login: str
    platform_password: str
    platform_url: str | None = None
    platform_notes: str | None = None


@api.post("/enrollments/{external_id}/fee/pay", tags=["enrollment"])
def pay_enrollment_fee(request, external_id: str, payload: FeeIn):
    """1ª parcela da taxa (À VISTA): valida o QR e dispara o PIX imediato pela fila. O status do
    matriculado muda quando o pagamento CONFIRMAR pago (`fee_paid`) — e o coordenador é avisado
    (é a deixa pra buscar as credenciais na instituição). Idempotente: repetir não paga 2×.
    O aluno NÃO fica sabendo (política interna do polo)."""
    coordinator = _coordinator(request)
    return enrollment_iface.pay_fee(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        qr_code=payload.qr_code,
        amount=payload.amount,
    )


@api.post("/enrollments/{external_id}/fee/schedule", tags=["enrollment"])
def schedule_enrollment_fee(request, external_id: str, payload: FeeIn):
    """2ª parcela da taxa (AGENDADA): o vencimento vem de DENTRO do QR (cobrança com vencimento);
    QR sem vencimento → 422. O status muda NA HORA pra `fee_scheduled`; o PIX dispara sozinho no
    dia (worker). NÃO depende da 1ª estar paga — a CONCLUSÃO é que exige as duas."""
    coordinator = _coordinator(request)
    return enrollment_iface.schedule_fee(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        qr_code=payload.qr_code,
        amount=payload.amount,
    )


@api.post("/enrollments/{external_id}/conclude", tags=["enrollment"])
def conclude_enrollment(request, external_id: str, payload: ConcludeIn):
    """CONCLUSÃO da matrícula: com a 1ª parcela PAGA e a 2ª AGENDADA, o coordenador cadastra o
    login/senha da plataforma (fornecidos pela instituição) → o aluno vira `student` (promoção
    atômica; o JWT antigo dele cai — token_version). Falta parcela → 409 FEES_INCOMPLETE dizendo
    o que falta."""
    coordinator = _coordinator(request)
    enr = enrollment_iface.conclude(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        platform_login=payload.platform_login,
        platform_password=payload.platform_password,
        platform_url=payload.platform_url,
        platform_notes=payload.platform_notes,
    )
    return {"external_id": str(enr.external_id), "status": enr.status}


# ── selfie em revisão (IA em dúvida) → coordenador decide o sim/não ──────────
class SelfieDecideIn(Schema):
    approve: bool
    reason: str | None = None


# ── RG em revisão (IA em dúvida — plan/12) → coordenador decide o sim/não ────
@api.post("/enrollments/{external_id}/rg/decide", tags=["enrollment"])
def decide_enrollment_rg(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide o RG de uma matrícula que a IA mandou pra REVISÃO (sim/não dele é FINAL).

    Aprovou → o aluno é avisado, a biometria roda e a extração best-effort preenche os campos;
    reprovou → o aluno é avisado pra reenviar a foto (com o motivo)."""
    coordinator = _coordinator(request)
    try:
        return enrollment_iface.decide_rg(
            enrollment_external_id=external_id,
            coordinator=coordinator,
            approve=payload.approve,
            reason=payload.reason,
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc


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
