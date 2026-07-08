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

from ninja import Field, File, Form, Router, Schema
from ninja.files import UploadedFile

from api.auth import require_roles
from api.base import add_auth_refresh, add_funnel_login, build_group
from api.schemas import CheckIn, CheckOut, TokenOut
from users.auth import interface as auth_iface
from users.exceptions import NotFound
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
| `INVALID_AUDIO_TYPE` | áudio fora de mp3/m4a/aac/ogg/webm/wav (422) | — |
| `AUDIO_TOO_LARGE` | áudio acima de MAX_UPLOAD_MB (422) | — |
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


class ProfileIn(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    birthplace: str | None = None
    nationality: str | None = None


class AddressCepIn(Schema):
    cep: str


class AddressDataIn(Schema):
    # PATCH — sobrescreve o que vier no payload (corrige valor errado); vazio/None é ignorado.
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
    # CPF | CNPJ | EMAIL | PHONE | EVP — apelidos PT também valem (celular→PHONE, aleatoria→EVP…)
    key_type: str


class SubmissionIn(Schema):
    material_external_id: str
    answer: str


# ── schemas de SAÍDA (response=) — espelham o snake_case real dos services (candidate/promoter/training)
class CandidateProfileOut(Schema):
    """Perfil do candidato como aparece no /me (inclui name/birth_date que o CPFHub manda).
    `locked_fields` = campos autoritativos (CPFHub) que o candidato NÃO edita — o front trava
    e destaca esses inputs (sombra verde + ✓)."""

    mother_name: str | None = None
    father_name: str | None = None
    birthplace: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    name: str | None = None
    birth_date: str | None = None
    locked_fields: list[str] = []


class CandidateAddressOut(Schema):
    """Endereço do candidato (público) com `cep`/`zipcode` e `missing_fields`."""

    cep: str | None = None
    zipcode: str | None = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    missing_fields: list[str] = []


class CandidateDocumentSubOut(Schema):
    """Sub-documento genérico (RG/CNH/certidão/militar) — foto + número básico + validação."""

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


class AddressProofOut(Schema):
    """Comprovante de residência (opcional, foto só)."""

    photo: str | None = None


class CandidateDocumentsOut(Schema):
    """Bloco de documentos do candidato."""

    external_id: str
    rg: CandidateDocumentSubOut | None = None
    cnh: CandidateDocumentSubOut | None = None
    certificate: CandidateDocumentSubOut | None = None
    military: CandidateDocumentSubOut | None = None
    address_proof: AddressProofOut | None = None


class CandidateSelfieOut(Schema):
    """Bloco da selfie no /me e no GET /candidate/selfie."""

    exists: bool
    photo: str | None = None
    taken_at: str | None = None
    status: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    expires_at: str | None = None
    verified: bool
    description: str | None = None


class CandidateMeOut(Schema):
    """/me RICO do candidato — devolvido por TODA mutação do wizard."""

    external_id: str
    status: str
    hub_external_id: str
    pix_validated: bool
    selfie_verified: bool
    selfie_status: str | None = None
    profile: CandidateProfileOut | None = None
    address: CandidateAddressOut | None = None
    documents: CandidateDocumentsOut | None = None
    selfie: CandidateSelfieOut | None = None


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


class AnalysisAckOut(Schema):
    """Ack de upload que dispara análise assíncrona (documento ou selfie)."""

    stored: bool | str
    analysis_status: str | None = None
    poll_after_ms: int
    expires_at: str | None = None


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
    audio: str | None = None
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
    """Lead captado pelo promotor (read-only). name/phone vêm do Profile do lead
    (card de leads + link de WhatsApp no app do promotor)."""

    external_id: str
    status: str
    name: str | None = None
    phone: str | None = None
    created_at: str


class PromoterCommissionOut(Schema):
    """Comissão do promotor (read-only)."""

    external_id: str
    amount: str
    source: str
    status: str
    created_at: str


class PromoterLifetimeOut(Schema):
    """Totais vitalícios do promotor (alunos pagos, bônus batidos, total recebido)."""

    total_students: int
    goals_hit: int
    total_received: str


class PromoterSummaryOut(Schema):
    """Resumo do painel do promotor: semana corrente (mesma janela do fechamento) + vitalício.
    Valores monetários em string decimal (reais)."""

    week_start: str
    week_end: str
    week_paid_leads: int
    week_goal: int
    goal_reached: bool
    week_commission_total: str
    bonus_amount: str
    next_closing_at: str
    lifetime: PromoterLifetimeOut


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
    """**O check NORMAL: dispara OTP** por cpf/phone e **VAZA existência** (CONVENTION §5): devolve
    `found`+`roles` honestos — o front decide cadastro novo × login.

    `send_otp=false` = modo sem OTP (integração do ex-/auth/check-bot): mesma função sem gastar o
    OTP, devolvendo `token` (JWT) direto."""
    from core.webhook_auth import service_secret_ok

    return auth_iface.check(
        cpf=payload.cpf,
        phone=payload.phone,
        external_id=payload.external_id,
        send_otp=payload.send_otp,
        service_authed=service_secret_ok(request),
    )


add_funnel_login(
    auth_router,
    funnel_roles=_FUNNEL_ROLES,
    not_in_funnel_msg="Usuário não faz parte do funil do colaborador.",
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
    """Preenche/CORRIGE os demais campos — sobrescreve o que vier no payload (vazio/None é
    ignorado). Devolve o `me_dict` canônico."""
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


@api.post(
    "/candidate/documents/address-proof", response=CandidateMeOut, tags=["candidate"]
)
def candidate_address_proof(request, file: UploadedFile = File(...)):
    """Comprovante de residência (JPEG/PNG/WEBP/PDF, multipart) — documento OPCIONAL: não define
    `doc_type`, não passa pela IA e não gateia o wizard. Devolve o `me_dict` canônico (a foto
    aparece em `documents.address_proof.photo`)."""
    ext = _guard(request, "candidate")
    return candidate_iface.upload_address_proof(user_external_id=ext, upload=file)


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


@api.post("/training/submissions/audio", response=SubmissionOut, tags=["training"])
def training_submit_audio(
    request,
    material_external_id: str = Form(...),
    file: UploadedFile = File(...),
):
    """Resposta em ÁUDIO (multipart, espelha os uploads de documento/selfie): o backend transcreve
    (Gemini STT) e corrige na mesma task assíncrona. mp3/m4a/aac/ogg/webm/wav, até MAX_UPLOAD_MB."""
    ext = _guard(request, "promoter")
    sub = training_iface.submit_audio(
        user_external_id=ext,
        material_external_id=material_external_id,
        data=file.read(),
        content_type=getattr(file, "content_type", ""),
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


@api.get("/promoter/me/summary", response=PromoterSummaryOut, tags=["promoter"])
def promoter_summary(request):
    """Agregado da semana (matrículas pagas × meta, comissão acumulada, bônus, próximo fechamento
    sexta 18h SP) + totais vitalícios — o front não precisa mais calcular isso."""
    return promoter_iface.summary(_promoter(request).user)


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
