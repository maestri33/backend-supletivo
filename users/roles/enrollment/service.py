"""Lógica do enrollment (matrícula).

- **6a** — nascimento (`create_from_lead`, chamado pelo hook do lead pago). ✅ smoke in-process.
- **6b** — funil de coleta (perfil → endereço → RG → educação → selfie até `awaiting_release`).
- **6c** — liberação do coordenador (`awaiting_release` → promove `enrollment→student` + COMPLETED).

⚠️ **6b/6c NÃO TESTADOS** (nem in-process completo, nem com aluno real). Reusa `users/address`,
`users/documents`, `integrations/ai` (visão da selfie, best-effort), `users/roles`, `notify`.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.db import transaction

from users.address import interface as address_iface
from users.documents import interface as documents_iface
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment.models import EducationalData, Enrollment

logger = structlog.get_logger()

_S = Enrollment.Status
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class EnrollmentError(Exception):
    """Erro de borda do enrollment (não encontrada, etapa fora de ordem, gate de status/coordenador)."""


# ── 6a: nascimento (chamado pelo hook do lead) ──────────────────────────────


def create_from_lead(*, user, promoter, hub) -> Enrollment:
    """Cria o Enrollment(STARTED) ligado ao HUB herdado + promove a role `lead→enrollment`. Idempotente.

    Chamado DENTRO da transação do hook de pagamento (lead pago). Se o enrollment já existe (webhook
    re-tentou), devolve o existente sem duplicar nem re-promover.
    """
    existing = Enrollment.objects.filter(user=user).first()
    if existing is not None:
        return existing

    enrollment = Enrollment.objects.create(
        user=user,
        promoter=promoter,
        hub=hub,
        status=Enrollment.Status.STARTED,
    )
    if "enrollment" not in roles.active_roles(user):
        roles.promote(user, "enrollment")

    logger.info(
        "enrollment.created_from_lead",
        external_id=str(enrollment.external_id),
        hub=str(hub.external_id),
    )
    return enrollment


def get_by_user(user) -> Enrollment | None:
    return (
        Enrollment.objects.filter(user=user).select_related("hub", "promoter").first()
    )


def get_by_external_id(external_id: str) -> Enrollment | None:
    return (
        Enrollment.objects.filter(external_id=external_id)
        .select_related("hub", "promoter", "user")
        .first()
    )


def get_for_user_external_id(user_external_id: str) -> Enrollment | None:
    """A matrícula do usuário logado (borda autenticada do funil)."""
    return (
        Enrollment.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "promoter", "user")
        .first()
    )


def _require(user_external_id: str, *allowed_status) -> Enrollment:
    """Carrega a matrícula do usuário e exige (se `allowed_status`) que esteja numa etapa permitida."""
    enr = (
        Enrollment.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "promoter", "user")
        .first()
    )
    if enr is None:
        raise EnrollmentError("enrollment_not_found")
    if allowed_status and enr.status not in allowed_status:
        raise EnrollmentError(f"wrong_status:{enr.status}")
    return enr


def _set_status(enr: Enrollment, to_status: str) -> None:
    enr.status = to_status
    enr.save(update_fields=["status", "updated_at"])


def to_dict(enr: Enrollment) -> dict:
    return {
        "external_id": str(enr.external_id),
        "status": enr.status,
        "hub_external_id": str(enr.hub.external_id),
        "selfie_verified": enr.selfie_verified,
        "selfie_status": enr.selfie_status,
    }


# ── 6b: funil de coleta (cada POST avança 1 etapa; idempotente — aceita re-post na etapa atual) ──


def set_profile(
    *,
    user_external_id: str,
    mother_name=None,
    father_name=None,
    marital_status=None,
    birthplace=None,
    nationality=None,
) -> Enrollment:
    enr = _require(user_external_id, _S.STARTED, _S.PROFILE)
    for field, value in (
        ("mother_name", mother_name),
        ("father_name", father_name),
        ("marital_status", marital_status),
        ("birthplace", birthplace),
        ("nationality", nationality),
    ):
        if value is not None:
            setattr(enr, field, value)
    enr.save()
    if enr.status == _S.STARTED:
        _set_status(enr, _S.PROFILE)
    return enr


def get_address(*, user_external_id: str) -> dict:
    """GET do endereço (o front vê o que está vazio p/ saber o que ainda pode preencher)."""
    _require(user_external_id)
    return address_iface.as_dict(address_iface.get_by_external_id(user_external_id))


def set_address_cep(*, user_external_id: str, cep: str) -> dict:
    """Busca o CEP (ViaCEP) e preenche o endereço. Em cidade de CEP único a rua fica vazia p/ digitar."""
    enr = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    _advance_address(enr, user_external_id)
    return address_iface.as_dict(address_iface.get_by_external_id(user_external_id))


def set_address_data(*, user_external_id: str, **fields) -> dict:
    """Preenche os demais campos do endereço — SÓ os que estão VAZIOS (não sobrescreve o que o CEP trouxe)."""
    enr = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.fill_empty(external_id=user_external_id, **fields)
    _advance_address(enr, user_external_id)
    return address_iface.as_dict(address_iface.get_by_external_id(user_external_id))


def _advance_address(enr: Enrollment, user_external_id: str) -> None:
    """Avança PROFILE→ADDRESS quando o endereço fica completo (campos essenciais preenchidos)."""
    if enr.status == _S.PROFILE and address_iface.is_complete(
        address_iface.get_by_external_id(user_external_id)
    ):
        _set_status(enr, _S.ADDRESS)


def set_documents_rg(
    *, user_external_id: str, number: str, issuing_agency=None, issue_date=None
) -> dict:
    enr = _require(user_external_id, _S.ADDRESS, _S.DOCUMENTS)
    rg = {"number": number}
    if issuing_agency is not None:
        rg["issuing_agency"] = issuing_agency
    if issue_date is not None:
        rg["issue_date"] = issue_date
    result = documents_iface.update(user_external_id, {"rg": rg})
    if enr.status == _S.ADDRESS:
        _set_status(enr, _S.DOCUMENTS)
    return result


def upload_rg_photo(*, user_external_id: str, slot: str, upload) -> str:
    """Foto do RG (slot `rg_front`/`rg_back`). Permitido enquanto coleta documentos/educação."""
    _require(user_external_id, _S.DOCUMENTS, _S.EDUCATION)
    return documents_iface.upload_photo(user_external_id, slot, upload)


def set_education(
    *,
    user_external_id: str,
    last_year_studied: str,
    last_school: str,
    last_year_when=None,
) -> Enrollment:
    enr = _require(user_external_id, _S.DOCUMENTS, _S.EDUCATION)
    EducationalData.objects.update_or_create(
        enrollment=enr,
        defaults={
            "last_year_studied": last_year_studied,
            "last_year_when": last_year_when,
            "last_school": last_school,
        },
    )
    if enr.status == _S.DOCUMENTS:
        _set_status(enr, _S.EDUCATION)
    return enr


def set_selfie(
    *, user_external_id: str, image_bytes: bytes, content_type: str = "image/jpeg"
) -> Enrollment:
    """Selfie ("assinar a matrícula"): valida por IA (3 estados). APROVADA → AWAITING_RELEASE (avisa o
    coordenador). REPROVADA → refazer (avisa o aluno). REVISÃO (IA fora/dúvida) → o coordenador decide."""
    from users.roles import _selfie

    enr = _require(user_external_id, _S.EDUCATION, _S.SELFIE, _S.AWAITING_RELEASE)
    enr.selfie_image = _save_selfie(enr, image_bytes, content_type)
    status, desc = _selfie.verify(image_bytes, content_type, caller="enrollment.selfie")
    enr.selfie_status = status
    enr.selfie_verified = status == _selfie.APPROVED
    enr.selfie_description = desc
    if enr.status == _S.EDUCATION:
        enr.status = _S.SELFIE  # avança pra etapa selfie (aguarda veredito)
    enr.save()
    _resolve_selfie(enr)
    return enr


def _resolve_selfie(enr: Enrollment) -> None:
    """Reage ao veredito: aprovada→aguarda liberação; reprovada→avisa o aluno; revisão→avisa o coordenador."""
    from users.roles import _selfie

    if enr.selfie_status == _selfie.APPROVED:
        _advance_to_release(enr)
    elif enr.selfie_status == _selfie.REJECTED:
        _notify_selfie_rejected(enr)
    elif enr.selfie_status == _selfie.REVIEW:
        _notify_selfie_review(enr)


def _advance_to_release(enr: Enrollment) -> None:
    """Selfie aprovada → AWAITING_RELEASE + avisa o coordenador. Idempotente (só sai de SELFIE)."""
    if enr.status != _S.SELFIE:
        return
    _set_status(enr, _S.AWAITING_RELEASE)
    _notify_coordinator_awaiting(enr)


def decide_selfie(
    *,
    enrollment_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> Enrollment:
    """Coordenador do hub decide a selfie em REVISÃO (sim/não). aprova→aguarda liberação; reprova→refazer."""
    from users.roles import _selfie

    enr = get_by_external_id(enrollment_external_id)
    if enr is None:
        raise EnrollmentError("enrollment_not_found")
    if enr.hub.coordinator_id != coordinator.id:
        raise EnrollmentError("not_hub_coordinator")
    if enr.selfie_status != _selfie.REVIEW:
        raise EnrollmentError(f"selfie_not_in_review:{enr.selfie_status}")
    note = (reason or "").strip() or (
        "aprovada pelo coordenador" if approve else "reprovada pelo coordenador"
    )
    enr.selfie_status = _selfie.APPROVED if approve else _selfie.REJECTED
    enr.selfie_verified = approve
    enr.selfie_description = note
    enr.save(
        update_fields=[
            "selfie_status",
            "selfie_verified",
            "selfie_description",
            "updated_at",
        ]
    )
    if approve:
        _advance_to_release(enr)
    else:
        _notify_selfie_rejected(enr)
    return enr


def _notify_selfie_rejected(enr: Enrollment) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    p = profiles.get(enr.user)
    try:
        send(
            text=msgs.text(
                "enrollment.selfie_rejected",
                name=msgs.first_name(p.name if p else None),
            ),
            caller="enrollment.selfie_rejected",
            phone=p.phone if p else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_selfie_rejected_failed", error=str(exc))


def _notify_selfie_review(enr: Enrollment) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    coord = enr.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send(
            text=msgs.text(
                "enrollment.selfie_in_review",
                name=msgs.first_name(cp.name if cp else None),
            ),
            caller="enrollment.selfie_in_review",
            phone=cp.phone if cp else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_selfie_review_failed", error=str(exc))


def _save_selfie(enr: Enrollment, image_bytes: bytes, content_type: str) -> str:
    from pathlib import Path

    ext = _SELFIE_EXT.get(content_type, "jpg")
    rel = f"enrollment/{enr.external_id}/selfie.{ext}"
    fp = Path(settings.MEDIA_ROOT) / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(image_bytes)
    return rel


def _notify_coordinator_awaiting(enr: Enrollment) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    coord = enr.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send(
            text=msgs.text(
                "enrollment.awaiting_release",
                name=msgs.first_name(cp.name if cp else None),
            ),
            caller="enrollment.awaiting_release",
            phone=cp.phone if cp else None,
            idempotency_key=f"enr_awaiting_{enr.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_coord_failed", error=str(exc))


# ── 6c: liberação do coordenador → student ──────────────────────────────────


def release(
    *,
    enrollment_external_id: str,
    coordinator,
    platform_url=None,
    platform_login=None,
    platform_password=None,
    platform_notes=None,
) -> Enrollment:
    """Coordenador do hub libera a matrícula: promove `enrollment→student`, marca COMPLETED e CRIA o
    `Student` (§4 item 9) já com os dados estruturados da plataforma de estudo + o hub herdado."""
    from users.roles.student import interface as student_iface

    enr = get_by_external_id(enrollment_external_id)
    if enr is None:
        raise EnrollmentError("enrollment_not_found")
    if enr.hub.coordinator_id != coordinator.id:
        raise EnrollmentError("not_hub_coordinator")
    if enr.status != _S.AWAITING_RELEASE:
        raise EnrollmentError(f"wrong_status:{enr.status}")

    with transaction.atomic():
        if "student" not in roles.active_roles(enr.user):
            roles.promote(enr.user, "student")
        enr.status = _S.COMPLETED
        enr.save(update_fields=["status", "updated_at"])
        student_iface.create_from_enrollment(
            user=enr.user,
            hub=enr.hub,
            platform_url=platform_url,
            platform_login=platform_login,
            platform_password=platform_password,
            platform_notes=platform_notes,
        )

    _notify_released(enr)
    logger.info("enrollment.released", external_id=str(enr.external_id))
    return enr


def _notify_released(enr: Enrollment) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    p = profiles.get(enr.user)
    try:
        send(
            text=msgs.text(
                "enrollment.released", name=msgs.first_name(p.name if p else None)
            ),
            caller="enrollment.released",
            phone=p.phone if p else None,
            email=p.email if p else None,
            email_channel=bool(p and p.email),
            tts=msgs.is_tts(
                "enrollment.released"
            ),  # virou aluno = momento especial (voz)
            gender=p.gender if p else None,
            idempotency_key=f"enr_released_{enr.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_released_failed", error=str(exc))
