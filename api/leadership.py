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
- **Funil do colaborador**: aprovar/rejeitar candidato (concluiu a coleta → vira PROMOTOR), autoria
  de matéria do treino e aprovar matéria em aberto de um promotor travado no treino.
"""

from __future__ import annotations

import structlog
from ninja import Field, File, Router, Schema
from ninja.files import UploadedFile

from api.auth import require_roles
from api.base import add_auth_refresh, build_group, resolve_rg_slot
from api.schemas import CheckIn, LoginIn, MaterialIn, MaterialUpdateIn, TokenOut
from users.auth import interface as auth_iface
from users.auth.models import User
from users.exceptions import Forbidden, NotFound
from hub import interface as hub_iface
from users.roles.candidate import interface as candidate_iface
from users.roles.enrollment import interface as enrollment_iface
from users.roles.lead import interface as lead_iface
from users.roles.promoter import interface as promoter_iface
from users.roles.student import interface as student_iface
from users.roles.training import interface as training_iface

api = build_group(
    "leadership", "Coordenador do polo (hub): aprovações, acesso, taxas, diploma."
)

logger = structlog.get_logger()

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
        raise Forbidden("Coordenador não encontrado.", code="FORBIDDEN_ROLE")
    return user


def _coordinator_hub(coordinator: User):
    """O polo que o coordenador COORDENA (gate duro plan/14 — sem fallback de promotor/padrão)."""
    hub = hub_iface.coordinated_by(coordinator)
    if hub is None:
        raise Forbidden(_NOT_COORDINATOR_DETAIL, code="NOT_HUB_COORDINATOR")
    return hub


# ── entrada do coordenador (público): check → login (OTP) → refresh — plan/14 ───────────────
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


add_auth_refresh(auth_router)

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
    de matrículas em revisão, selfie de candidatos, documentos de students, candidatos aguardando
    aprovação (→ promotor) e promotores travados no treino (matéria em aberto a aprovar). Cada item
    aponta pro POST de decisão correspondente."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    enrollment_reviews = enrollment_iface.list_reviews_for_hub(hub=hub)
    return {
        "enrollment_rg": enrollment_reviews["rg"],
        "enrollment_selfie": enrollment_reviews["selfie"],
        # documentos (RG/CNH) de CANDIDATOS em review — a IA fora do ar/em dúvida cai aqui pro
        # coordenador decidir (fix da auditoria 2026-06-17: estava ausente → candidato travado
        # em `documents` sem ninguém pra destravar; agora segue a hierarquia user→coord→staff).
        "candidate_document": candidate_iface.list_document_reviews_for_hub(hub=hub),
        "candidate_selfie": candidate_iface.list_selfie_reviews_for_hub(hub=hub),
        "student_documents": student_iface.list_document_reviews_for_hub(hub=hub),
        "candidates_awaiting_approval": candidate_iface.list_awaiting_approval_for_hub(
            hub=hub
        ),
        "locked_promoters": training_iface.list_locked_promoters_for_hub(hub=hub),
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
    return enrollment_iface.decide_rg(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )


@api.post("/enrollments/{external_id}/selfie/decide", tags=["enrollment"])
def decide_enrollment_selfie(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a selfie de uma matrícula que a IA mandou pra REVISÃO."""
    coordinator = _coordinator(request)
    enr = enrollment_iface.decide_selfie(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )
    return {
        "external_id": str(enr.external_id),
        "selfie_status": enr.selfie_status,
        "status": enr.status,
    }


@api.post("/candidates/{external_id}/selfie/decide", tags=["candidate"])
def decide_candidate_selfie(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a selfie de um candidato que a IA mandou pra REVISÃO."""
    coordinator = _coordinator(request)
    cand = candidate_iface.decide_selfie(
        candidate_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )
    return {
        "external_id": str(cand.external_id),
        "selfie_status": cand.selfie_status,
        "status": cand.status,
    }


@api.get("/candidates/{external_id}/selfie", response=dict, tags=["candidate"])
def get_candidate_selfie_for_coordinator(request, external_id: str):
    """Tela de DETALHE da selfie do candidato em REVISÃO pro coordenador decidir (plan/15 D2):
    foto + `analysis_status`/`analysis_reason` (motivo da IA). O coord decide VENDO, não às
    cegas (antes decidia só com o nome na fila). Gate: o coord precisa ser o do polo."""
    coordinator = _coordinator(request)
    return candidate_iface.candidate_selfie_for_coordinator(
        candidate_external_id=external_id, coordinator=coordinator
    )


@api.post("/candidates/{external_id}/document/decide", tags=["candidate"])
def decide_candidate_document(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide o documento (RG ou CNH) de um candidato que a IA mandou pra REVISÃO
    (plan/15 B3). Decisão humana é FINAL.

    Aprovou → o candidato é avisado, a biometria roda e a extração best-effort preenche os campos
    (filiação/naturalidade → candidato; nº/órgão/etc → sub-doc RG/CNH). Reprova → o candidato é
    avisado pra reenviar a foto (com o motivo)."""
    coordinator = _coordinator(request)
    return candidate_iface.decide_document(
        candidate_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )


@api.post("/candidates/{external_id}/document/reset", tags=["candidate"])
def reset_candidate_doc_type(request, external_id: str):
    """Coordenador DESTRAVA o candidato que fixou o tipo de documento errado (escolheu RG, só tem
    CNH — ou vice-versa): zera o `doc_type` e volta pra etapa `documents`, perfil/endereço/pix
    intactos. Sem isso, a única saída seria recomeçar tudo (Victor 2026-06-17: user→coord, sem dev)."""
    coordinator = _coordinator(request)
    return candidate_iface.reset_doc_type(
        candidate_external_id=external_id, coordinator=coordinator
    )


# ── funil do aluno: coordenador conduz student→veteran (§4 item 9) ───────────
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
    return fn(student_external_id=external_id, coordinator=coordinator, **kw)


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
    pend = student_iface.resolve_pendency(
        pendency_external_id=external_id, coordinator=coordinator
    )
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
# MaterialIn/MaterialUpdateIn vêm do módulo compartilhado (plan/15 A7; mesmo contrato do staff).
@api.get("/training/materials", tags=["training"])
def list_materials(request):
    """Lista todas as matérias COM gabarito (visão de autoria — o coordenador também autora)."""
    _coordinator(request)
    return [
        training_iface.material_to_dict(m, include_answer=True)
        for m in training_iface.list_materials(active_only=False)
    ]


@api.post("/training/materials", tags=["training"])
def create_material(request, payload: MaterialIn):
    _coordinator(request)
    m = training_iface.create_material(**payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.put("/training/materials/{external_id}", tags=["training"])
def update_material(request, external_id: str, payload: MaterialUpdateIn):
    _coordinator(request)
    m = training_iface.update_material(external_id, **payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


# ── funil do colaborador: aprovar candidato → PROMOTOR (Victor 2026-06-16) ──
# A entrevista/Trainee saiu: o coordenador aprova o candidato (que concluiu a coleta) e ele vira
# PROMOTOR direto. O treino passou a ser uma trava pós-promotor por matérias.
class RejectIn(Schema):
    reason: str


@api.get("/candidates", tags=["candidate"])
def list_candidates_awaiting(request):
    """Fila de candidatos do polo que concluíram a coleta e aguardam a APROVAÇÃO do coordenador."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    return candidate_iface.list_awaiting_approval_for_hub(hub=hub)


@api.get("/candidates/{external_id}", response=dict, tags=["candidate"])
def get_candidate_for_coordinator(request, external_id: str):
    """Detalhe do candidato (perfil + coleta) pro coordenador decidir VENDO antes de aprovar."""
    coordinator = _coordinator(request)
    return candidate_iface.candidate_detail_for_coordinator(
        candidate_external_id=external_id, coordinator=coordinator
    )


@api.post("/candidates/{external_id}/approve", tags=["candidate"])
def approve_candidate(request, external_id: str):
    """Aprova o candidato do seu polo → promove a PROMOTOR (e atribui o treino obrigatório)."""
    coordinator = _coordinator(request)
    cand = candidate_iface.approve_candidate(
        candidate_external_id=external_id, coordinator=coordinator
    )
    return {"external_id": str(cand.external_id), "status": cand.status}


@api.post("/candidates/{external_id}/reject", tags=["candidate"])
def reject_candidate(request, external_id: str, payload: RejectIn):
    """Rejeita o candidato aguardando aprovação (com motivo) — não promove."""
    coordinator = _coordinator(request)
    cand = candidate_iface.reject_candidate(
        candidate_external_id=external_id,
        coordinator=coordinator,
        reason=payload.reason,
    )
    return {"external_id": str(cand.external_id), "status": cand.status}


@api.post(
    "/promoters/{external_id}/materials/{material_external_id}/approve",
    tags=["training"],
)
def approve_open_material(request, external_id: str, material_external_id: str):
    """Coordenador aprova uma matéria EM ABERTO de um promotor preso (destrava quem não tem prática
    digital). `external_id` = do promotor; `material_external_id` = da matéria."""
    coordinator = _coordinator(request)
    return training_iface.coordinator_approve_material(
        promoter_external_id=external_id,
        material_external_id=material_external_id,
        coordinator=coordinator,
    )


# ── coordenador: PROMOTORES do polo (listar/suspender/reativar) + DETALHE do aluno (WP5) ──
@api.get("/promoters", tags=["promoter"])
def list_hub_promoters(request):
    """Promotores do polo (status + se travados no treino) — pro painel do coordenador."""
    coordinator = _coordinator(request)
    hub = _coordinator_hub(coordinator)
    return promoter_iface.list_for_hub(hub)


@api.post("/promoters/{external_id}/suspend", tags=["promoter"])
def suspend_promoter(request, external_id: str):
    """Suspende um promotor do polo (não capta nem recebe). `external_id` = do User-promotor."""
    coordinator = _coordinator(request)
    p = promoter_iface.suspend(user_external_id=external_id, coordinator=coordinator)
    return {"external_id": external_id, "status": p.status}


@api.post("/promoters/{external_id}/reactivate", tags=["promoter"])
def reactivate_promoter(request, external_id: str):
    """Reativa um promotor SUSPENSO do polo (volta a captar) — destrava quem ficou preso."""
    coordinator = _coordinator(request)
    p = promoter_iface.reactivate(user_external_id=external_id, coordinator=coordinator)
    return {"external_id": external_id, "status": p.status}


@api.get("/students/{external_id}", response=dict, tags=["student"])
def get_student_for_coordinator(request, external_id: str):
    """Detalhe RICO do aluno (docs/pendências/diploma/plataforma/identidade) pro coordenador — antes
    ele agia no aluno (grade/decide/pendency) mas não tinha um GET completo dele."""
    coordinator = _coordinator(request)
    return student_iface.detail_for_coordinator(
        student_external_id=external_id, coordinator=coordinator
    )


# ── coordenador AGE NO LUGAR do cliente sem prática digital (proxy auditado; Victor 2026-06-16) ──
# Mesmas ações do wizard do aluno, mas o coordenador posta POR ele (gate: coordenar o hub da matrícula;
# `acted_by` logado). A IA valida igual; review → cai pros decides que já existem.


class ProxyCepIn(Schema):
    cep: str


class CorrectIdentityIn(Schema):
    # campos de identidade derivados do DOCUMENTO (OCR) que o coordenador pode corrigir.
    # name/birth_date NÃO entram (CPFHub é a fonte); pix tem validação própria.
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    birthplace: str | None = None


def _proxy_user(request, external_id: str):
    """Gate do proxy: o coordenador coordena o hub da matrícula → devolve (coordinator, user_external_id)."""
    coordinator = _coordinator(request)
    user_ext = enrollment_iface.coordinated_user_ext(
        enrollment_external_id=external_id, coordinator=coordinator
    )
    return coordinator, user_ext


@api.post("/enrollments/{external_id}/address", tags=["enrollment"])
def coord_proxy_address(request, external_id: str, payload: ProxyCepIn):
    """Coordenador grava o ENDEREÇO (por CEP, ViaCEP) NO LUGAR do cliente. Auditado."""
    coordinator, user_ext = _proxy_user(request, external_id)
    logger.info(
        "leadership.acted_for",
        action="address_cep",
        enrollment=external_id,
        by=str(coordinator.external_id),
    )
    return enrollment_iface.set_address_cep(user_external_id=user_ext, cep=payload.cep)


@api.post("/enrollments/{external_id}/documents/rg/photo/{slot}", tags=["enrollment"])
def coord_proxy_rg_photo(
    request, external_id: str, slot: str, file: UploadedFile = File(...)
):
    """Coordenador ENVIA a foto do RG (`front`|`back`|`full`) NO LUGAR do cliente. A IA valida normal;
    se cair em revisão, o coordenador decide pelo `/rg/decide` que já existe. Auditado."""
    coordinator, user_ext = _proxy_user(request, external_id)
    real_slot = resolve_rg_slot(slot)
    logger.info(
        "leadership.acted_for",
        action="rg_photo",
        enrollment=external_id,
        by=str(coordinator.external_id),
    )
    return enrollment_iface.upload_rg_photo(
        user_external_id=user_ext, slot=real_slot, upload=file
    )


@api.post("/enrollments/{external_id}/selfie", tags=["enrollment"])
def coord_proxy_selfie(request, external_id: str, file: UploadedFile = File(...)):
    """Coordenador ENVIA a selfie (assinatura) NO LUGAR do cliente. IA + biometria validam normal;
    review → decide pelo `/selfie/decide`. Auditado."""
    coordinator, user_ext = _proxy_user(request, external_id)
    logger.info(
        "leadership.acted_for",
        action="selfie",
        enrollment=external_id,
        by=str(coordinator.external_id),
    )
    enr = enrollment_iface.set_selfie(
        user_external_id=user_ext,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
    )
    # mesmo contrato do wizard do cliente: o coordenador também recebe o ack de análise (poll/TTL).
    return {**enrollment_iface.me_dict(enr), **enrollment_iface.selfie_ack(enr)}


@api.patch("/enrollments/{external_id}/profile", tags=["enrollment"])
def coord_correct_identity(request, external_id: str, payload: CorrectIdentityIn):
    """Coordenador CORRIGE a identidade que o OCR extraiu torta (filiação/estado civil/naturalidade/
    nacionalidade) — sem isso o dado errado fica gravado pra sempre e só um db-edit conserta. NÃO
    mexe em nome/nascimento (CPFHub manda) nem em pix. Auditado (Victor 2026-06-17: user→coord)."""
    coordinator = _coordinator(request)
    return enrollment_iface.coordinator_correct_identity(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        **payload.dict(exclude_none=True),
    )
