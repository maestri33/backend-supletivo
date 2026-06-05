"""Grupo `collaborators` (PLACEHOLDER) — funil do COLABORADOR: candidato → treino → promotor.

Captação pública do candidato + funil autenticado (perfil→endereço→docs→pix→selfie), o treino (matérias +
submissões corrigidas por IA) e a área do promotor (link `?ref=` + leads/comissões). Casca fina (§3): valida
a borda e chama o `interface/` in-process. Autoria de matéria e entrevista vivem em `staff`/`leadership`.
"""

from __future__ import annotations

from ninja import File, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from api.base import build_group
from users.auth import interface as auth_iface
from users.auth.models import User
from users.exceptions import DomainError
from users.roles import interface as roles
from users.roles.candidate import interface as candidate_iface
from users.roles.promoter import interface as promoter_iface
from users.roles.training import interface as training_iface

api = build_group("collaborators", "Funil do colaborador: candidato, treino, promotor.")

_FUNNEL_ROLES = ("coordinator", "promoter", "training", "candidate")


def _domain_http(exc: DomainError) -> HttpError:
    return HttpError(getattr(exc, "status", 400), exc.detail)


def _guard(request, *allowed: str) -> str:
    from api.auth import require_roles

    require_roles(request.auth, *allowed)
    return request.auth.external_id


# ── schemas ──────────────────────────────────────────────────────────────
class CandidateCreateIn(Schema):
    cpf: str
    phone: str
    email: str
    hub: str | None = None  # external_id do polo (ref do coordenador); senão hub padrão


class CheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None


class LoginIn(Schema):
    external_id: str
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
    # demais campos — o backend só preenche os que estão VAZIOS (não sobrescreve o CEP).
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


# ── público (captação + login) ──────────────────────────────────────────────
@api.post("/candidates", auth=None, tags=["candidate"])
def create_candidate(request, payload: CandidateCreateIn):
    try:
        return candidate_iface.create_candidate(
            cpf=payload.cpf, phone=payload.phone, email=payload.email, hub=payload.hub
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/candidates/check", auth=None, tags=["candidate"])
def check_candidate(request, payload: CheckIn):
    try:
        return auth_iface.check(cpf=payload.cpf, phone=payload.phone)
    except DomainError as exc:
        raise _domain_http(exc) from exc


@api.post("/candidates/login", auth=None, tags=["candidate"])
def login_candidate(request, payload: LoginIn):
    user = User.objects.filter(external_id=payload.external_id).first()
    if user is None:
        raise HttpError(404, "Usuário não encontrado.")
    active = roles.active_roles(user)
    funnel_role = next((r for r in _FUNNEL_ROLES if r in active), None)
    if funnel_role is None:
        raise HttpError(403, "Usuário não faz parte do funil do colaborador.")
    try:
        return auth_iface.login(
            external_id=payload.external_id, role=funnel_role, otp=payload.otp
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc


# ── candidato: funil de coleta (autenticado, role candidate) ────────────────
@api.get("/candidate/me", tags=["candidate"])
def candidate_me(request):
    ext = _guard(request, "candidate")
    cand = candidate_iface.get_for_user_external_id(ext)
    if cand is None:
        raise HttpError(404, "Candidato não encontrado.")
    return candidate_iface.to_dict(cand)


@api.post("/candidate/profile", tags=["candidate"])
def candidate_profile(request, payload: ProfileIn):
    ext = _guard(request, "candidate")
    try:
        cand = candidate_iface.set_profile(user_external_id=ext, **payload.dict())
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc
    return candidate_iface.to_dict(cand)


@api.get("/candidate/address", tags=["candidate"])
def candidate_get_address(request):
    """GET do endereço (o front vê o que está vazio p/ saber o que ainda pode preencher)."""
    ext = _guard(request, "candidate")
    try:
        return candidate_iface.get_address(user_external_id=ext)
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/candidate/address/cep", tags=["candidate"])
def candidate_address_cep(request, payload: AddressCepIn):
    """Busca o CEP (ViaCEP) e preenche o endereço. Em cidade de CEP único a rua fica vazia p/ digitar."""
    ext = _guard(request, "candidate")
    try:
        return candidate_iface.set_address_cep(user_external_id=ext, cep=payload.cep)
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/candidate/address/data", tags=["candidate"])
def candidate_address_data(request, payload: AddressDataIn):
    """Preenche os demais campos — SÓ os que estão VAZIOS (não sobrescreve o que o CEP trouxe)."""
    ext = _guard(request, "candidate")
    try:
        return candidate_iface.set_address_data(
            user_external_id=ext, **payload.dict(exclude_none=True)
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/candidate/documents", tags=["candidate"])
def candidate_documents(request, payload: DocumentsIn):
    ext = _guard(request, "candidate")
    fields = payload.dict()
    doc_type = fields.pop("doc_type")
    try:
        candidate_iface.set_documents(user_external_id=ext, doc_type=doc_type, **fields)
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc
    return candidate_iface.to_dict(candidate_iface.get_for_user_external_id(ext))


@api.post("/candidate/documents/photo/{slot}", tags=["candidate"])
def candidate_document_photo(request, slot: str, file: UploadedFile = File(...)):
    ext = _guard(request, "candidate")
    try:
        path = candidate_iface.upload_document_photo(
            user_external_id=ext, slot=slot, upload=file
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc
    return {"slot": slot, "stored": path}


@api.post("/candidate/pix", tags=["candidate"])
def candidate_pix(request, payload: PixIn):
    ext = _guard(request, "candidate")
    try:
        cand = candidate_iface.set_pix(
            user_external_id=ext, key=payload.key, key_type=payload.key_type
        )
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc
    return candidate_iface.to_dict(cand)


@api.post("/candidate/selfie", tags=["candidate"])
def candidate_selfie(request, file: UploadedFile = File(...)):
    ext = _guard(request, "candidate")
    try:
        cand = candidate_iface.set_selfie(
            user_external_id=ext,
            image_bytes=file.read(),
            content_type=getattr(file, "content_type", "image/jpeg"),
        )
    except candidate_iface.CandidateError as exc:
        raise HttpError(422, str(exc)) from exc
    return candidate_iface.to_dict(cand)


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
    try:
        return training_iface.progress(ext)
    except training_iface.TrainingError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/training/submissions", tags=["training"])
def training_submit(request, payload: SubmissionIn):
    ext = _guard(request, "training")
    try:
        sub = training_iface.submit(
            user_external_id=ext,
            material_external_id=payload.material_external_id,
            answer=payload.answer,
        )
    except training_iface.TrainingError as exc:
        raise HttpError(422, str(exc)) from exc
    return training_iface.submission_to_dict(sub)


# ── promotor (autenticado, role promoter) ───────────────────────────────────
@api.get("/promoter/me", tags=["promoter"])
def promoter_me(request):
    ext = _guard(request, "promoter")
    p = promoter_iface.get_by_user_external_id(ext)
    if p is None:
        raise HttpError(404, "Promotor não encontrado.")
    return promoter_iface.to_dict(p)


@api.get("/promoter/me/leads", tags=["promoter"])
def promoter_leads(request):
    ext = _guard(request, "promoter")
    p = promoter_iface.get_by_user_external_id(ext)
    if p is None:
        raise HttpError(404, "Promotor não encontrado.")
    return promoter_iface.list_leads(p.user)


@api.get("/promoter/me/commissions", tags=["promoter"])
def promoter_commissions(request):
    ext = _guard(request, "promoter")
    p = promoter_iface.get_by_user_external_id(ext)
    if p is None:
        raise HttpError(404, "Promotor não encontrado.")
    return promoter_iface.list_commissions(p.user)
