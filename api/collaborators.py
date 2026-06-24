"""Grupo `collaborators` (PLACEHOLDER) — funil do COLABORADOR: candidato → treino → promotor.

Captação pública do candidato + funil autenticado (perfil→endereço→docs→pix→selfie), o treino (matérias +
submissões corrigidas por IA) e a área do promotor (link `?ref=` + leads/comissões). Casca fina (§3): valida
a borda e chama o `interface/` in-process. Autoria de matéria e entrevista vivem em `staff`/`leadership`.

Padrão (plan/15, espelha o grupo `clients`): rotas FINAS — os erros de domínio (`DomainError` e filhos,
incl. `CandidateError`/`TrainingError`) BORBULHAM pro handler central da fábrica (`api/base.py`) → JSON
`{detail, code, …extra}` no status certo. Toda mutação devolve o `me_dict` canônico (o front roteia o
wizard sem re-fetch).
"""

from __future__ import annotations

from ninja import Field, File, Router, Schema
from ninja.files import UploadedFile

from api.auth import require_roles
from api.base import add_auth_refresh, build_group
from api.schemas import (
    SharedAnalysisAckOut,
    SharedAddressOut,
    SharedCandidateDocumentsOut,
    SharedCandidateDocSubOut,
    SharedCandidateMeOut,
    SharedCandidateProfileOut,
    SharedCandidateSelfieOut,
    TokenOut,
)
from users.auth import interface as auth_iface
from users.auth.models import User
from users.exceptions import Forbidden, NotFound
from users.roles import interface as roles
from users.roles.candidate import interface as candidate_iface
from users.roles.lead import interface as lead_iface
from users.roles.promoter import interface as promoter_iface
from users.roles.training import interface as training_iface

# Registry de `code` de erro (plan/15 A1, espelha o clients): TODO 4xx sai `{detail, code, …extra}` — o
# front roteia por `switch(code)`, nunca parseando `detail`. Vai na descrição do grupo → OpenAPI.
_ERROR_REGISTRY = """
### Códigos de erro (`{detail, code, …extra}`)

| code | quando | extras |
|---|---|---|
| `WRONG_STATUS` | ação fora da etapa do wizard (409) | `expected_status` (etapa a abrir) |
| `VALIDATION_ERROR` | body/query fora do schema (422) | `detail` = lista do pydantic |
| `NO_HUB` | nenhum polo disponível pro cadastro (422) | — |
| `INVALID_DOC_TYPE` | tipo de documento ≠ rg/cnh (422) | — |
| `PIX_INVALID` | chave Pix inválida ou não é do titular (422) | `reason` |
| `PROFILE_CPF_MISSING` | perfil sem CPF (refazer cadastro) (422) | — |
| `MATERIAL_NOT_FOUND` / `TRAINEE_NOT_FOUND` / `CANDIDATE_NOT_FOUND` / `PROMOTER_NOT_FOUND` / `USER_NOT_FOUND` | recurso não existe (404) | — |
| `MATERIAL_INACTIVE` | submissão em matéria desativada (422) | — |
| `ALREADY_GRADING` | já há uma resposta em correção (409) | — |
| `SELFIE_NOT_IN_REVIEW` | decisão de selfie fora de revisão (422) | `selfie_status` |
| `NOT_HUB_COORDINATOR` | coordenador não é do polo (403) | — |
| `CPF_EXISTS` / `PHONE_EXISTS` / `EMAIL_EXISTS` | cadastro duplicado (409) | — |
| `CPF_INVALID` / `PHONE_INVALID` / `CPF_NOT_FOUND` | dado rejeitado na validação (422) | — |
| `UNAUTHORIZED` / `SESSION_EXPIRED` | sem token ou token vencido (401) | — |
| `FORBIDDEN_ROLE` / `NOT_IN_FUNNEL` | papel sem acesso à rota (403) | — |
| `RATE_LIMITED` | espera do OTP (429) | `retry_after_s` |
| `ERROR` | fallback (erro sem code próprio) | — |
"""

api = build_group(
    "collaborators",
    "Funil do colaborador: candidato, treino, promotor.\n" + _ERROR_REGISTRY,
)

# roles do funil do colaborador, mais avançada primeiro (login emite JWT com TODAS as ativas).
_FUNNEL_ROLES = ("coordinator", "promoter", "training", "candidate")


def _guard(request, *allowed: str) -> str:
    """Gate de role por rota + devolve o external_id do USER logado."""
    require_roles(request.auth, *allowed)
    return request.auth.external_id


# ── schemas ──────────────────────────────────────────────────────────────
class CandidateCreateIn(Schema):
    cpf: str
    phone: str
    email: str
    hub: str | None = (
        None  # ?ref= da landing: external_id de POLO ou PROMOTOR; ruim/ausente → polo padrão
    )


class CandidateOut(Schema):
    external_id: str = Field(description="external_id do CANDIDATO (≠ do user)")
    user_external_id: str = Field(
        description="external_id do USER — é o que o /auth/login espera"
    )
    status: str


class CheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None
    external_id: str | None = None  # re-dispara OTP de usuário já conhecido (do USER)


class CheckOut(Schema):
    found: bool
    external_id: str | None = Field(
        None, description="external_id do USER (é o que o /auth/login espera)"
    )
    otp_sent: bool
    otp_wait: int | None = None
    whatsapp: bool | None = None
    roles: list[str] | None = None


class LoginIn(Schema):
    external_id: str = Field(description="external_id do USER (veio do /auth/check)")
    otp: str


class ProfileIn(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    birthplace: str | None = None
    nationality: str | None = None


class AddressCepIn(Schema):
    cep: str


class AddressDataIn(Schema):
    # PATCH — o backend só preenche os que estão VAZIOS (não sobrescreve o que o CEP trouxe).
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None


class DocumentsIn(Schema):
    doc_type: str  # rg | cnh
    number: str
    issuing_agency: str | None = None
    issue_date: str | None = None
    category: str | None = None
    national_register: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None


class PixIn(Schema):
    key: str
    key_type: str  # CPF | CNPJ | EMAIL | PHONE | EVP


class SubmissionIn(Schema):
    material_external_id: str
    answer: str


# ── schemas de SAÍDA (response=) — espelham o snake_case real dos services (candidate/promoter/training)
# Aliases dos schemas centrais (api/schemas.py) — fonte única, sem drift entre collaborators/leadership.
CandidateProfileOut = SharedCandidateProfileOut
CandidateAddressOut = SharedAddressOut
CandidateDocumentSubOut = SharedCandidateDocSubOut
CandidateDocumentsOut = SharedCandidateDocumentsOut
CandidateSelfieOut = SharedCandidateSelfieOut
CandidateMeOut = SharedCandidateMeOut
AnalysisAckOut = SharedAnalysisAckOut


class CandidateDocumentSectionOut(Schema):
    """Seção rica do documento (GET /candidate/document): tipo + fotos + validação IA + extraídos + missing_fields."""

    doc_type: str | None = None
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    category: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None
    national_register: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    extracted: dict = {}
    missing_fields: list[str] = []


class TrainingMaterialOut(Schema):
    """Matéria atribuída ao promotor em treino (COM conteúdo)."""

    material_external_id: str
    title: str
    blocking: bool
    kind: str
    assignment_status: str
    submission_status: str
    grade: str | None = None
    justification: str | None = None
    text_content: str = ""
    content_blocks: list[dict] = []
    question: str = ""
    video: str | None = None
    photo: str | None = None


class TrainingMaterialProgressOut(Schema):
    """Resumo de status por matéria atribuída (SEM conteúdo)."""

    material_external_id: str
    title: str
    blocking: bool
    kind: str
    assignment_status: str
    submission_status: str
    grade: str | None = None
    justification: str | None = None


class SubmissionOut(Schema):
    """Resultado da submissão de resposta de treino."""

    external_id: str
    material_external_id: str
    grade: str | None = None
    justification: str | None = None
    status: str


class PromoterMeOut(Schema):
    """Painel do promotor: status + trava do treino + link de captação."""

    external_id: str
    status: str
    hub_external_id: str
    ref_url: str
    locked: bool
    pending_materials: list[dict] = []


class PromoterLeadOut(Schema):
    """Lead captado pelo promotor (read-only)."""

    external_id: str
    status: str
    created_at: str


class PromoterCommissionOut(Schema):
    """Comissão do promotor (read-only)."""

    external_id: str
    amount: str
    source: str
    status: str
    created_at: str


class StudyPricingCardOut(Schema):
    installments: int
    installment: str
    total: str


class StudyPricingOut(Schema):
    """Preço da auto-matrícula do promotor."""

    pix: str
    card: StudyPricingCardOut


class StudyCheckoutOut(Schema):
    """Checkout da auto-matrícula do promotor."""

    payment_method: str | None = None
    provider: str | None = None
    amount: str | None = None
    is_paid: bool | None = None
    checkout_url: str | None = None
    short_url: str | None = None
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class StudyStartOut(Schema):
    """Resultado da criação da auto-matrícula do promotor."""

    external_id: str
    user_external_id: str
    status: str
    checkout: StudyCheckoutOut | None = None


# Erros de domínio (`DomainError`, incl. CandidateError/TrainingError) NÃO são capturados aqui:
# sobem pro handler central da fábrica (`api/base.py`) → JSON `{detail, code, …extra}` no status certo.


# ── collaborators/auth — entrada do colaborador (pública): cadastro + login ───
# plan/15 A4: captação/login são ENTRADA → vivem em /auth (aposenta os /candidates*).
auth_router = Router(tags=["auth"])


@auth_router.post("/register", response={201: CandidateOut}, auth=None)
def register(request, payload: CandidateCreateIn):
    """Cadastro do candidato: cria o user (role `candidate`) + o Candidate ligado a um polo.

    `hub` = `?ref=` da landing: aceita external_id de POLO **ou** de PROMOTOR (resolvido pro hub dele).
    Ref ausente/inválido/sem-coordenador cai no polo padrão — tolerante, não bloqueia o cadastro
    (`resolve_capture_hub`). Devolve o external_id do CANDIDATO e do USER (este o /auth/login consome)."""
    return 201, candidate_iface.create_candidate(
        cpf=payload.cpf, phone=payload.phone, email=payload.email, hub=payload.hub
    )


@auth_router.post("/check", response=CheckOut, auth=None)
def check(request, payload: CheckIn):
    """Dispara OTP por cpf/phone e **VAZA existência** (CONVENTION §5): devolve `found`+`roles`
    honestos — o front decide cadastro novo × login."""
    return auth_iface.check(
        cpf=payload.cpf, phone=payload.phone, external_id=payload.external_id
    )


@auth_router.post("/login", response=TokenOut, auth=None)
def login(request, payload: LoginIn):
    """Login passwordless (OTP) — resolve o papel mais avançado do funil do colaborador
    (coordinator→promoter→training→candidate) e emite JWT com TODAS as roles ativas."""
    user = User.objects.filter(external_id=payload.external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    active = roles.active_roles(user)
    funnel_role = next((r for r in _FUNNEL_ROLES if r in active), None)
    if funnel_role is None:
        raise Forbidden(
            "Usuário não faz parte do funil do colaborador.", code="NOT_IN_FUNNEL"
        )
    return auth_iface.login(
        external_id=payload.external_id, role=funnel_role, otp=payload.otp
    )


add_auth_refresh(auth_router)


api.add_router("/auth", auth_router)


# ── candidato: funil de coleta (autenticado, role candidate) ────────────────
# Ordem do wizard (plan/15 #4 — mantém a do promotor): perfil → endereço → documento → pix → selfie.
# Convenção: o /me e TODA mutação devolvem o `me_dict` canônico (status + seções + missing_fields).
@api.get("/candidate/me", response=CandidateMeOut, tags=["candidate"])
def candidate_me(request):
    """Estado COMPLETO do candidato pro resume do wizard: status + cada seção já preenchida +
    `missing_fields` por seção, numa chamada só."""
    ext = _guard(request, "candidate")
    cand = candidate_iface.get_for_user_external_id(ext)
    if cand is None:
        raise NotFound("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    return candidate_iface.me_dict(cand)


@api.post("/candidate/profile", response=CandidateMeOut, tags=["candidate"])
def candidate_profile(request, payload: ProfileIn):
    """Dados do perfil que o documento NÃO traz (estado civil, nacionalidade) — filiação/naturalidade
    vêm da extração do documento (Fatia B). Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_profile(user_external_id=ext, **payload.dict())


@api.get("/candidate/address", response=CandidateAddressOut, tags=["candidate"])
def candidate_get_address(request):
    """GET do endereço + `missing_fields` (o front renderiza input só do que falta)."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_address(user_external_id=ext)


@api.post("/candidate/address", response=CandidateMeOut, tags=["candidate"])
def candidate_address(request, payload: AddressCepIn):
    """Body só `{cep}`: acha no ViaCEP, grava o endereço e devolve o `me_dict` canônico —
    `address.missing_fields` JÁ AVISA o que falta (`["number"]` = só o número; rua/bairro na lista =
    cidade de CEP único, digite no PATCH)."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_address_cep(user_external_id=ext, cep=payload.cep)


@api.patch("/candidate/address", response=CandidateMeOut, tags=["candidate"])
def candidate_address_patch(request, payload: AddressDataIn):
    """Preenche os demais campos — SÓ os que estão VAZIOS (não sobrescreve o que o CEP trouxe).
    Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_address_data(
        user_external_id=ext, **payload.dict(exclude_none=True)
    )


@api.post("/candidate/documents", response=CandidateMeOut, tags=["candidate"])
def candidate_documents(request, payload: DocumentsIn):
    """RG ou CNH (o candidato aceita os dois). Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    fields = payload.dict()
    doc_type = fields.pop("doc_type")
    return candidate_iface.set_documents(
        user_external_id=ext, doc_type=doc_type, **fields
    )


@api.get(
    "/candidate/document", response=CandidateDocumentSectionOut, tags=["candidate"]
)
def candidate_get_document(request):
    """Seção rica do documento (plan/15 B3): `doc_type` + fotos + validação IA canônica
    (`analysis_status`/`analysis_reason`/`analysis_started_at`) + campos extraídos + `missing_fields`
    (o que a IA não trouxe E o candidato precisa digitar). Espelha o `enrollment.get_rg_section`."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_document_section(user_external_id=ext)


@api.patch("/candidate/document", response=CandidateMeOut, tags=["candidate"])
def candidate_patch_document(request, payload: DocumentsIn):
    """Completa/corrige campos que a extração OCR não trouxe. Aceito em qualquer etapa da coleta
    (a foto segue sendo a fonte de verdade pra auditoria). Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    fields = payload.dict(exclude_none=True)
    fields.pop("doc_type", None)  # PATCH não muda o tipo; veio do upload
    return candidate_iface.patch_document_section(user_external_id=ext, **fields)


@api.post(
    "/candidate/documents/photo/{slot}", response=AnalysisAckOut, tags=["candidate"]
)
def candidate_document_photo(request, slot: str, file: UploadedFile = File(...)):
    """Foto do documento (slots `rg_front`/`rg_back`/`rg_full`/`cnh_front`/`cnh_back`/`cnh_full`).
    Plan/15 B3: na frente o rosto vira biometria do documento (best-effort) e a foto entra no
    pipeline de IA (visão+OCR+extração assíncrono). Devolve **ack** pra o front acompanhar
    (`stored` + `analysis_status`/`poll_after_ms`/`expires_at`).

    O **1º slot** (rg_* OU cnh_*) define o `doc_type` do candidato — imutável depois
    (`DOC_TYPE_LOCKED`). RG inteiro (`rg_full`) ou CNH inteira (`cnh_full`) cabem numa só foto;
    frente+verso (2 fotos) também."""
    ext = _guard(request, "candidate")
    return candidate_iface.upload_document_photo(
        user_external_id=ext, slot=slot, upload=file
    )


@api.post("/candidate/pix", response=CandidateMeOut, tags=["candidate"])
def candidate_pix(request, payload: PixIn):
    """Valida a chave Pix no Asaas/DICT (confere o titular) e grava. Devolve o `me_dict` canônico.
    ⚠️ MEXE R$0,01 real (DICT)."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_pix(
        user_external_id=ext, key=payload.key, key_type=payload.key_type
    )


@api.post("/candidate/selfie", response=AnalysisAckOut, tags=["candidate"])
def candidate_selfie(request, file: UploadedFile = File(...)):
    """Envia a selfie (assinatura) — **assíncrona** (plan/15 C, espelha `/enrollment/selfie`):

    salva a foto + enfileira `validate_candidate_selfie` (Django-Q) e responde na hora com o
    **ack** `{stored, analysis_status:"pending", poll_after_ms, expires_at}`. O front acompanha
    pelo `GET /candidate/selfie` até virar `approved`/`rejected`/`review`. Aprovada→promove
    training; reprovada→avisa candidato; review→coordenador decide."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_selfie(
        user_external_id=ext,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
    )


@api.get("/candidate/selfie", response=CandidateSelfieOut, tags=["candidate"])
def get_candidate_selfie(request):
    """GET da selfie/assinatura (plan/15 C): foto + `analysis_status`/`analysis_reason` (canônico)
    + `expires_at` (TTL do `pending`). Aplica o TTL na leitura: pending estourado vira `review`
    + notifica o coordenador. Espelha `GET /enrollment/selfie`."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_selfie(user_external_id=ext)


# ── treino (autenticado, role PROMOTER — a trava do painel; Victor 2026-06-16) ──
# O candidato vira promotor quando o coordenador aprova; se houver matéria obrigatória pendente, o
# promotor nasce TRAVADO e só vê o treino. As rotas são gated por `promoter` (ele já é promotor); a
# trava em si é lida do `/promoter/me` (campo `locked`).
@api.get("/training/materials", response=list[TrainingMaterialOut], tags=["training"])
def training_materials(request):
    """Matérias ATRIBUÍDAS ao promotor (fixas do onboarding + transitórias publicadas pra ele):
    conteúdo (sem gabarito) + status de cada. NÃO é a lista global — só o treino dele."""
    ext = _guard(request, "promoter")
    return training_iface.assigned_materials(ext)


@api.get(
    "/training/progress", response=list[TrainingMaterialProgressOut], tags=["training"]
)
def training_progress(request):
    ext = _guard(request, "promoter")
    return training_iface.progress(ext)


@api.post("/training/submissions", response=SubmissionOut, tags=["training"])
def training_submit(request, payload: SubmissionIn):
    ext = _guard(request, "promoter")
    sub = training_iface.submit(
        user_external_id=ext,
        material_external_id=payload.material_external_id,
        answer=payload.answer,
    )
    return training_iface.submission_to_dict(sub)


# ── promotor (autenticado, role promoter) ───────────────────────────────────
def _promoter(request):
    ext = _guard(request, "promoter")
    p = promoter_iface.get_by_user_external_id(ext)
    if p is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")
    return p


@api.get("/promoter/me", response=PromoterMeOut, tags=["promoter"])
def promoter_me(request):
    return promoter_iface.to_dict(_promoter(request))


@api.get("/promoter/me/leads", response=list[PromoterLeadOut], tags=["promoter"])
def promoter_leads(request):
    return promoter_iface.list_leads(_promoter(request).user)


@api.get(
    "/promoter/me/commissions", response=list[PromoterCommissionOut], tags=["promoter"]
)
def promoter_commissions(request):
    return promoter_iface.list_commissions(_promoter(request).user)


# ── promotor ESTUDA (entra no funil do aluno por endpoint logado; Victor 2026-06-16) ──
# Preço PRÓPRIO de promotor, fluxo próprio, SEM comissão a ninguém. Não pelo registro público: aqui,
# autenticado. Depois de pagar, o promotor segue o wizard do aluno (role enrollment somada no pagamento).
class StudyStartIn(Schema):
    payment_method: str | None = None  # "card" (default) | "pix"


@api.get("/promoter/study/pricing", response=StudyPricingOut, tags=["promoter"])
def promoter_study_pricing(request):
    """Preço da auto-matrícula do promotor (preço próprio, ≠ vitrine pública do aluno)."""
    _guard(request, "promoter")
    return lead_iface.promoter_pricing()


@api.post("/promoter/study/start", response=StudyStartOut, tags=["promoter"])
def promoter_study_start(request, payload: StudyStartIn):
    """Promotor quer estudar: cria a auto-matrícula (preço promotor, SEM comissão) e devolve o checkout.
    Ele paga pelo link; no pagamento ganha a role de aluno e segue o wizard do aluno (grupo clients)."""
    promoter = _promoter(request)
    return lead_iface.create_self_study_lead(
        user=promoter.user, payment_method=payload.payment_method
    )
