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
from api.base import build_group
from users.auth import interface as auth_iface
from users.auth.jwt import service as jwt_service
from users.auth.models import User
from users.exceptions import Forbidden, NotFound, Unauthorized
from users.roles import interface as roles
from users.roles.candidate import interface as candidate_iface
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
    hub: str | None = None  # external_id do polo (ref do coordenador); senão hub padrão


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


class RefreshIn(Schema):
    refresh_token: str


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str


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


# Erros de domínio (`DomainError`, incl. CandidateError/TrainingError) NÃO são capturados aqui:
# sobem pro handler central da fábrica (`api/base.py`) → JSON `{detail, code, …extra}` no status certo.


# ── collaborators/auth — entrada do colaborador (pública): cadastro + login ───
# plan/15 A4: captação/login são ENTRADA → vivem em /auth (aposenta os /candidates*).
auth_router = Router(tags=["auth"])


@auth_router.post("/register", response={201: CandidateOut}, auth=None)
def register(request, payload: CandidateCreateIn):
    """Cadastro do candidato: cria o user (role `candidate`) + o Candidate ligado a um polo (`hub`
    = external_id do coordenador na landing `?ref=`; senão o polo padrão). Devolve o external_id do
    CANDIDATO e do USER (este o /auth/login consome)."""
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


@auth_router.post("/refresh", response=TokenOut, auth=None)
def refresh(request, payload: RefreshIn):
    """Troca o `refresh_token` por um par NOVO (rotação) — o front renova silencioso quando o access
    expira no meio do funil, sem voltar pro OTP. Refresh inválido/expirado OU role trocada desde a
    emissão (`token_version`) → **401** (aí sim é re-login)."""
    try:
        return jwt_service.refresh(payload.refresh_token)
    except jwt_service.TokenError as exc:
        raise Unauthorized(
            "Sessão expirada — faça login novamente.", code="SESSION_EXPIRED"
        ) from exc


api.add_router("/auth", auth_router)


# ── candidato: funil de coleta (autenticado, role candidate) ────────────────
# Ordem do wizard (plan/15 #4 — mantém a do promotor): perfil → endereço → documento → pix → selfie.
# Convenção: o /me e TODA mutação devolvem o `me_dict` canônico (status + seções + missing_fields).
@api.get("/candidate/me", tags=["candidate"])
def candidate_me(request):
    """Estado COMPLETO do candidato pro resume do wizard: status + cada seção já preenchida +
    `missing_fields` por seção, numa chamada só."""
    ext = _guard(request, "candidate")
    cand = candidate_iface.get_for_user_external_id(ext)
    if cand is None:
        raise NotFound("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    return candidate_iface.me_dict(cand)


@api.post("/candidate/profile", tags=["candidate"])
def candidate_profile(request, payload: ProfileIn):
    """Dados do perfil que o documento NÃO traz (estado civil, nacionalidade) — filiação/naturalidade
    vêm da extração do documento (Fatia B). Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_profile(user_external_id=ext, **payload.dict())


@api.get("/candidate/address", tags=["candidate"])
def candidate_get_address(request):
    """GET do endereço + `missing_fields` (o front renderiza input só do que falta)."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_address(user_external_id=ext)


@api.post("/candidate/address", tags=["candidate"])
def candidate_address(request, payload: AddressCepIn):
    """Body só `{cep}`: acha no ViaCEP, grava o endereço e devolve o `me_dict` canônico —
    `address.missing_fields` JÁ AVISA o que falta (`["number"]` = só o número; rua/bairro na lista =
    cidade de CEP único, digite no PATCH)."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_address_cep(user_external_id=ext, cep=payload.cep)


@api.patch("/candidate/address", tags=["candidate"])
def candidate_address_patch(request, payload: AddressDataIn):
    """Preenche os demais campos — SÓ os que estão VAZIOS (não sobrescreve o que o CEP trouxe).
    Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_address_data(
        user_external_id=ext, **payload.dict(exclude_none=True)
    )


@api.post("/candidate/documents", tags=["candidate"])
def candidate_documents(request, payload: DocumentsIn):
    """RG ou CNH (o candidato aceita os dois). Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    fields = payload.dict()
    doc_type = fields.pop("doc_type")
    return candidate_iface.set_documents(
        user_external_id=ext, doc_type=doc_type, **fields
    )


@api.post("/candidate/documents/photo/{slot}", tags=["candidate"])
def candidate_document_photo(request, slot: str, file: UploadedFile = File(...)):
    """Foto do documento (slots `rg_front`/`rg_back`/`cnh_front`/`cnh_back`). Na frente o rosto vira
    biometria do documento (best-effort)."""
    ext = _guard(request, "candidate")
    path = candidate_iface.upload_document_photo(
        user_external_id=ext, slot=slot, upload=file
    )
    return {"slot": slot, "stored": path}


@api.post("/candidate/pix", tags=["candidate"])
def candidate_pix(request, payload: PixIn):
    """Valida a chave Pix no Asaas/DICT (confere o titular) e grava. Devolve o `me_dict` canônico.
    ⚠️ MEXE R$0,01 real (DICT)."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_pix(
        user_external_id=ext, key=payload.key, key_type=payload.key_type
    )


@api.post("/candidate/selfie", tags=["candidate"])
def candidate_selfie(request, file: UploadedFile = File(...)):
    """Envia a selfie (assinatura): valida por IA (3 estados) + biometria vs documento. Aprovada →
    promove a treino. Devolve o `me_dict` canônico."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_selfie(
        user_external_id=ext,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
    )


# ── treino (autenticado, role training) ─────────────────────────────────────
@api.get("/training/materials", tags=["training"])
def training_materials(request):
    _guard(request, "training")
    return [
        training_iface.material_to_dict(m)  # sem gabarito pro trainee
        for m in training_iface.list_materials(active_only=True)
    ]


@api.get("/training/progress", tags=["training"])
def training_progress(request):
    ext = _guard(request, "training")
    return training_iface.progress(ext)


@api.post("/training/submissions", tags=["training"])
def training_submit(request, payload: SubmissionIn):
    ext = _guard(request, "training")
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


@api.get("/promoter/me", tags=["promoter"])
def promoter_me(request):
    return promoter_iface.to_dict(_promoter(request))


@api.get("/promoter/me/leads", tags=["promoter"])
def promoter_leads(request):
    return promoter_iface.list_leads(_promoter(request).user)


@api.get("/promoter/me/commissions", tags=["promoter"])
def promoter_commissions(request):
    return promoter_iface.list_commissions(_promoter(request).user)
