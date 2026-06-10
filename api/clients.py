"""Grupo `clients` (PLACEHOLDER) — público do funil do ALUNO (**$$ ENTRA**):
lead → enrollment → student → veteran.

Fatia 6a (LEAD): captação pública (cria lead + checkout, devolve o pagamento na hora), check/login
por OTP. Casca fina (CONVENTION §3): valida a borda e chama o `interface/` in-process; zero regra aqui.
O funil autenticado da matrícula (enrollment) entra na 6b.
"""

from __future__ import annotations

from ninja import File, Router, Schema
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


class CardPriceOut(Schema):
    installments: int
    installment: str  # valor da parcela em reais (string), ex.: "99.00"
    total: str  # valor cheio em reais (string), ex.: "1188.00"


class PricingOut(Schema):
    pix: str  # valor cheio do PIX em reais (string), ex.: "999.00"
    card: CardPriceOut


def _domain_http(exc: DomainError) -> HttpError:
    return HttpError(getattr(exc, "status", 400), exc.detail)


# ── preço de vitrine (público) — o front exibe na landing ────────────────────
@api.get("/pricing", response=PricingOut, auth=None, tags=["pricing"])
def pricing(request):
    """Preço de VITRINE público (sem login): PIX (valor cheio) + cartão em 12x. ≠ a cobrança real."""
    return lead_iface.pricing()


# ── clients/auth — entrada do cliente (pública): cadastro + login por OTP ─────
# Victor 2026-06-07: captação/login são ENTRADA → vivem em /auth. TODO cliente entra como `lead`.
auth_router = Router(tags=["auth"])
lead_router = Router(tags=["lead"])


@auth_router.post("/register", response={201: LeadOut}, auth=None)
def register(request, payload: LeadCreateIn):
    """Cadastro do cliente: **TODO cliente entra OBRIGATORIAMENTE como `lead`.** Cria o lead (cpf/phone/
    email + método) + o checkout e devolve o pagamento na hora."""
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


@auth_router.post("/check", response=CheckOut, auth=None)
def check(request, payload: CheckIn):
    """Dispara OTP por cpf/phone e **VAZA existência** (CONVENTION §5): devolve `found`+`roles` honestos —
    o front decide cadastro novo × login e pra qual fase do funil mandar."""
    try:
        return auth_iface.check(cpf=payload.cpf, phone=payload.phone)
    except DomainError as exc:
        raise _domain_http(exc) from exc


@auth_router.post("/login", response=TokenOut, auth=None)
def login(request, payload: LoginIn):
    """Login passwordless (OTP) — resolve o papel mais avançado do funil do cliente (lead→enrollment→
    student; veteran exige student) e emite JWT com TODAS as roles ativas."""
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


# ── clients/lead — a fase LEAD (autenticada, role `lead`): estado + a URL ─────
def _lead_guard(request):
    """Gate role lead + devolve o lead do usuário logado (404 se não houver)."""
    require_roles(request.auth, "lead")
    lead = lead_iface.get_for_user_external_id(request.auth.external_id)
    if lead is None:
        raise HttpError(404, "Lead não encontrado.")
    return lead


@lead_router.get("/me")
def lead_me(request):
    """TODOS os dados do lead do cliente logado, incl. a URL (✦ checkout se não pagou / recibo se pagou)."""
    return lead_iface.lead_self_dict(_lead_guard(request))


@lead_router.get("/checkout-url")
def lead_checkout_url(request):
    """Só a URL de pagamento/recibo do lead (link único ✦ que redireciona checkout↔recibo)."""
    url = lead_iface.checkout_url_for(_lead_guard(request))
    if url is None:
        raise HttpError(404, "Checkout não encontrado.")
    return {"url": url}


api.add_router("/auth", auth_router)
api.add_router("/lead", lead_router)


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
    selfie_status: str  # pending/approved/rejected/review — front sabe quando caiu p/ revisão do coord


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
