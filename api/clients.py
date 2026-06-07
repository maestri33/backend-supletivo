"""Grupo `clients` (PLACEHOLDER) — público do funil do ALUNO (**$$ ENTRA**):
lead → enrollment → student → veteran.

Fatia 6a (LEAD): captação pública (cria lead + checkout, devolve o pagamento na hora), check/login
por OTP. Casca fina (CONVENTION §3): valida a borda e chama o `interface/` in-process; zero regra aqui.
O funil autenticado da matrícula (enrollment) entra na 6b.
"""

from __future__ import annotations

from ninja import File, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from api.auth import require_roles
from api.base import build_group
from users.auth import interface as auth_iface
from users.auth.models import User
from users.exceptions import DomainError
from users.roles import interface as roles
from users.roles.enrollment import interface as enrollment_iface
from users.roles.lead import interface as lead_iface
from users.roles.student import interface as student_iface

api = build_group("clients", "Funil do aluno: lead, enrollment, student, veteran.")

# roles do funil do aluno, mais avançada primeiro (login emite JWT com TODAS as ativas).
_FUNNEL_ROLES = ("veteran", "student", "enrollment", "lead")


# ── schemas ──────────────────────────────────────────────────────────────
class LeadCreateIn(Schema):
    cpf: str
    phone: str
    email: str
    payment_method: str | None = None  # default cartão (resolvido no service)
    ref: str | None = None  # external_id do promotor (landing ?ref=)


class CheckoutOut(Schema):
    payment_method: str
    provider: str
    amount: str
    is_paid: bool
    checkout_url: str | None = None
    short_url: str | None = None  # link curto no nosso domínio (manda por WhatsApp)
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class LeadOut(Schema):
    external_id: str
    status: str
    checkout: CheckoutOut | None = None


class CheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None


class CheckOut(Schema):
    found: bool
    external_id: str | None = None
    otp_sent: bool
    otp_wait: int | None = None
    whatsapp: bool | None = None
    roles: list[str] | None = None


class LoginIn(Schema):
    external_id: str
    otp: str


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str


def _domain_http(exc: DomainError) -> HttpError:
    return HttpError(getattr(exc, "status", 400), exc.detail)


# ── público (captação + login) ─────────────────────────────────────────────
@api.post("/leads", response={201: LeadOut}, auth=None, tags=["lead"])
def create_lead(request, payload: LeadCreateIn):
    """Cria o lead: cadastro mínimo (cpf/phone/email + método) + checkout. Devolve o pagamento na hora."""
    try:
        result = lead_iface.create_lead(
            cpf=payload.cpf,
            phone=payload.phone,
            email=payload.email,
            payment_method=payload.payment_method,
            ref=payload.ref,
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except lead_iface.LeadError as exc:
        raise HttpError(422, str(exc)) from exc
    return 201, result


@api.post("/leads/check", response=CheckOut, auth=None, tags=["lead"])
def check_lead(request, payload: CheckIn):
    """Dispara OTP por cpf/phone (mecanismo de login do funil)."""
    try:
        return auth_iface.check(cpf=payload.cpf, phone=payload.phone)
    except DomainError as exc:
        raise _domain_http(exc) from exc


@api.post("/leads/login", response=TokenOut, auth=None, tags=["lead"])
def login_lead(request, payload: LoginIn):
    """Login passwordless (OTP) — emite JWT com as roles ativas do funil do aluno."""
    user = User.objects.filter(external_id=payload.external_id).first()
    if user is None:
        raise HttpError(404, "Usuário não encontrado.")
    active = roles.active_roles(user)
    funnel_role = next((r for r in _FUNNEL_ROLES if r in active), None)
    if funnel_role is None:
        raise HttpError(403, "Usuário não faz parte do funil do aluno.")
    try:
        return auth_iface.login(
            external_id=payload.external_id, role=funnel_role, otp=payload.otp
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc


# ── matrícula: funil de coleta (autenticado, role enrollment) — 6b ──────────
# ⚠️ 6b NÃO TESTADO (nem in-process completo, nem com aluno real).
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


class RgIn(Schema):
    number: str
    issuing_agency: str | None = None
    issue_date: str | None = None


class EducationIn(Schema):
    last_year_studied: str
    last_school: str
    last_year_when: str | None = None


class EnrollmentOut(Schema):
    external_id: str
    status: str
    hub_external_id: str
    selfie_verified: bool


def _enr_guard(request) -> str:
    """Gate role enrollment + devolve o external_id do aluno logado."""
    require_roles(request.auth, "enrollment")
    return request.auth.external_id


@api.get("/enrollment/me", response=EnrollmentOut, tags=["enrollment"])
def enrollment_me(request):
    ext = _enr_guard(request)
    enr = enrollment_iface.get_for_user_external_id(ext)
    if enr is None:
        raise HttpError(404, "Matrícula não encontrada.")
    return enrollment_iface.to_dict(enr)


@api.post("/enrollment/profile", response=EnrollmentOut, tags=["enrollment"])
def enrollment_profile(request, payload: ProfileIn):
    ext = _enr_guard(request)
    try:
        enr = enrollment_iface.set_profile(user_external_id=ext, **payload.dict())
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return enrollment_iface.to_dict(enr)


@api.get("/enrollment/address", tags=["enrollment"])
def enrollment_get_address(request):
    """GET do endereço (o front vê o que está vazio p/ saber o que ainda pode preencher)."""
    ext = _enr_guard(request)
    try:
        return enrollment_iface.get_address(user_external_id=ext)
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/enrollment/address/cep", tags=["enrollment"])
def enrollment_address_cep(request, payload: AddressCepIn):
    """Busca o CEP (ViaCEP) e preenche o endereço. Em cidade de CEP único a rua fica vazia p/ digitar."""
    ext = _enr_guard(request)
    try:
        return enrollment_iface.set_address_cep(user_external_id=ext, cep=payload.cep)
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/enrollment/address/data", tags=["enrollment"])
def enrollment_address_data(request, payload: AddressDataIn):
    """Preenche os demais campos — SÓ os que estão VAZIOS (não sobrescreve o que o CEP trouxe)."""
    ext = _enr_guard(request)
    try:
        return enrollment_iface.set_address_data(
            user_external_id=ext, **payload.dict(exclude_none=True)
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc


@api.post("/enrollment/documents/rg", response=EnrollmentOut, tags=["enrollment"])
def enrollment_rg(request, payload: RgIn):
    ext = _enr_guard(request)
    try:
        enrollment_iface.set_documents_rg(
            user_external_id=ext,
            number=payload.number,
            issuing_agency=payload.issuing_agency,
            issue_date=payload.issue_date,
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return enrollment_iface.to_dict(enrollment_iface.get_for_user_external_id(ext))


@api.post("/enrollment/documents/rg/photo/{slot}", tags=["enrollment"])
def enrollment_rg_photo(request, slot: str, file: UploadedFile = File(...)):
    ext = _enr_guard(request)
    try:
        path = enrollment_iface.upload_rg_photo(
            user_external_id=ext, slot=slot, upload=file
        )
    except DomainError as exc:
        raise _domain_http(exc) from exc
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return {"slot": slot, "stored": path}


@api.post("/enrollment/education", response=EnrollmentOut, tags=["enrollment"])
def enrollment_education(request, payload: EducationIn):
    ext = _enr_guard(request)
    try:
        enr = enrollment_iface.set_education(
            user_external_id=ext,
            last_year_studied=payload.last_year_studied,
            last_school=payload.last_school,
            last_year_when=payload.last_year_when,
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return enrollment_iface.to_dict(enr)


@api.post("/enrollment/selfie", response=EnrollmentOut, tags=["enrollment"])
def enrollment_selfie(request, file: UploadedFile = File(...)):
    ext = _enr_guard(request)
    try:
        enr = enrollment_iface.set_selfie(
            user_external_id=ext,
            image_bytes=file.read(),
            content_type=getattr(file, "content_type", "image/jpeg"),
        )
    except enrollment_iface.EnrollmentError as exc:
        raise HttpError(422, str(exc)) from exc
    return enrollment_iface.to_dict(enr)


# ── aluno: funil final student→veteran (autenticado, role student) — §4 item 9 ──
# ⚠️ NÃO TESTADO (nem in-process completo, nem com aluno/IA real).
class BloodTypeIn(Schema):
    blood_type: str  # A+/A-/B+/B-/AB+/AB-/O+/O-


class ExamScheduleIn(Schema):
    subject: str
    scheduled_at: str  # ISO 8601 (ex.: 2026-06-10T14:00:00-03:00)


def _student_guard(request) -> str:
    """Gate role student + devolve o external_id do aluno logado."""
    require_roles(request.auth, "student")
    return request.auth.external_id


def _student_dict(ext: str):
    s = student_iface.get_for_user_external_id(ext)
    if s is None:
        raise HttpError(404, "Aluno não encontrado.")
    return student_iface.to_dict(s)


@api.get("/student/me", tags=["student"])
def student_me(request):
    return _student_dict(_student_guard(request))


@api.post("/student/blood-type", tags=["student"])
def student_blood_type(request, payload: BloodTypeIn):
    ext = _student_guard(request)
    try:
        student_iface.set_blood_type(
            user_external_id=ext, blood_type=payload.blood_type
        )
    except student_iface.StudentError as exc:
        raise HttpError(422, str(exc)) from exc
    return _student_dict(ext)


@api.post("/student/documents/{doc_type}", tags=["student"])
def student_document(request, doc_type: str, file: UploadedFile = File(...)):
    ext = _student_guard(request)
    try:
        student_iface.upload_document(
            user_external_id=ext,
            doc_type=doc_type,
            image_bytes=file.read(),
            content_type=getattr(file, "content_type", "image/jpeg"),
        )
    except student_iface.StudentError as exc:
        raise HttpError(422, str(exc)) from exc
    return _student_dict(ext)


@api.post("/student/exam/schedule", tags=["student"])
def student_exam_schedule(request, payload: ExamScheduleIn):
    ext = _student_guard(request)
    try:
        student_iface.schedule_exam(
            user_external_id=ext,
            subject=payload.subject,
            scheduled_at=payload.scheduled_at,
        )
    except student_iface.StudentError as exc:
        raise HttpError(422, str(exc)) from exc
    return _student_dict(ext)


@api.get("/student/pendencies", tags=["student"])
def student_pendencies(request):
    ext = _student_guard(request)
    pends = student_iface.list_pendencies(ext, open_only=True)
    return [
        {
            "external_id": str(p.external_id),
            "kind": p.kind,
            "description": p.description,
            "amount_cents": p.amount_cents,
        }
        for p in pends
    ]


@api.post("/student/diploma/pickup", tags=["student"])
def student_diploma_pickup(request, file: UploadedFile = File(...)):
    """Aluno posta a foto tirando o diploma → vira veteran + dispara a comissão do coordenador."""
    ext = _student_guard(request)
    try:
        student_iface.register_pickup(
            user_external_id=ext,
            image_bytes=file.read(),
            content_type=getattr(file, "content_type", "image/jpeg"),
        )
    except student_iface.StudentError as exc:
        raise HttpError(422, str(exc)) from exc
    return _student_dict(ext)
