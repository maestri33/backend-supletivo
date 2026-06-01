"""Lógica do `documents` (CONVENTION §3) — DMZ. Cria/atualiza documentos e guarda fotos.

`create_empty` é chamado na transação do provisionamento (auth §9): nasce Document + RG/CNH/
Certificate/Military null. Foto vai pro filesystem (`media/documents/<external_id>/<slot>.<ext>`)
e o path relativo fica no campo do sub-doc. Militar só preenche pra `gender='M'` (Q4 do plano).
"""

from __future__ import annotations

from datetime import date

import structlog
from django.conf import settings
from django.core.files.storage import default_storage

from users.documents.models import CNH, RG, Certificate, Document, Military
from users.exceptions import NotFound, ValidationError
from users.profiles import interface as profiles

logger = structlog.get_logger()

# Campos editáveis por sub-doc (foto NÃO entra aqui — vai pelo upload). Datas parseadas à parte.
_TEXT_FIELDS = {
    "rg": ("number", "issuing_agency"),
    "cnh": ("number", "category", "national_register"),
    "certificate": ("kind", "number", "registry_office", "book", "page", "entry"),
    "military": ("number", "series", "category", "ra"),
}
_DATE_FIELDS = {
    "rg": ("issue_date",),
    "cnh": ("date_of_birth", "expires_on"),
    "certificate": ("issue_date",),
    "military": (),
}

# slot de foto → (atributo do sub-doc no Document, campo de path no sub-doc)
_PHOTO_SLOTS = {
    "rg_front": ("rg", "front_photo"),
    "rg_back": ("rg", "back_photo"),
    "cnh_front": ("cnh", "front_photo"),
    "cnh_back": ("cnh", "back_photo"),
    "certificate_photo": ("certificate", "photo"),
    "military_photo": ("military", "photo"),
}

# MIME aceito → extensão do arquivo salvo.
_ALLOWED_IMAGE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def create_empty(user) -> Document:
    """Cria o Document + os 4 sub-docs vazios. DENTRO da transação do provisionamento (auth)."""
    document = Document.objects.create(user=user)
    RG.objects.create(document=document)
    CNH.objects.create(document=document)
    Certificate.objects.create(document=document)
    Military.objects.create(document=document)
    return document


def _get_document(external_id: str) -> Document:
    document = (
        Document.objects.filter(user__external_id=external_id)
        .select_related("rg", "cnh", "certificate", "military")
        .first()
    )
    if document is None:
        raise NotFound(
            "Documentos não encontrados para este usuário.", code="DOCUMENT_NOT_FOUND"
        )
    return document


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "Data inválida (use AAAA-MM-DD).", code="DATE_INVALID"
        ) from exc


def as_dict(document: Document) -> dict:
    """Serializa Document + sub-docs aninhados pro JSON da view."""

    def _photo(sub, *fields):
        return {f: getattr(sub, f) for f in fields}

    rg, cnh, cert, mil = (
        document.rg,
        document.cnh,
        document.certificate,
        document.military,
    )
    return {
        "external_id": str(document.user.external_id),
        "rg": {
            "number": rg.number,
            "issuing_agency": rg.issuing_agency,
            "issue_date": rg.issue_date.isoformat() if rg.issue_date else None,
            **_photo(rg, "front_photo", "back_photo"),
        },
        "cnh": {
            "number": cnh.number,
            "category": cnh.category,
            "date_of_birth": cnh.date_of_birth.isoformat()
            if cnh.date_of_birth
            else None,
            "expires_on": cnh.expires_on.isoformat() if cnh.expires_on else None,
            "national_register": cnh.national_register,
            **_photo(cnh, "front_photo", "back_photo"),
        },
        "certificate": {
            "kind": cert.kind,
            "number": cert.number,
            "registry_office": cert.registry_office,
            "book": cert.book,
            "page": cert.page,
            "entry": cert.entry,
            "issue_date": cert.issue_date.isoformat() if cert.issue_date else None,
            "photo": cert.photo,
        },
        "military": {
            "number": mil.number,
            "series": mil.series,
            "category": mil.category,
            "ra": mil.ra,
            "photo": mil.photo,
        },
    }


def get_by_external_id(external_id: str) -> dict:
    return as_dict(_get_document(external_id))


def update(external_id: str, payload: dict) -> dict:
    """Atualiza os campos enviados de cada sub-doc. Militar só pra `gender='M'` (Q4)."""
    document = _get_document(external_id)

    if "military" in payload and payload["military"]:
        profile = profiles.find_by_external_id(external_id)
        if profile is None or profile.gender != "M":
            raise ValidationError(
                "Documento militar só se aplica a usuários do gênero masculino.",
                code="MILITARY_NOT_APPLICABLE",
            )

    for sub_name, text_fields in _TEXT_FIELDS.items():
        sub_payload = payload.get(sub_name)
        if not sub_payload:
            continue
        sub = getattr(document, sub_name)
        for field in text_fields:
            if field in sub_payload:
                setattr(sub, field, sub_payload[field])
        for field in _DATE_FIELDS[sub_name]:
            if field in sub_payload:
                setattr(sub, field, _parse_date(sub_payload[field]))
        sub.save()

    logger.info(
        "documents.updated", external_id=external_id, parts=list(payload.keys())
    )
    return as_dict(document)


def upload_photo(external_id: str, slot: str, upload) -> str:
    """Salva a imagem do slot em media/documents/<external_id>/<slot>.<ext> e grava o path no DB."""
    if slot not in _PHOTO_SLOTS:
        raise ValidationError(f"Slot de foto inválido: {slot}.", code="SLOT_INVALID")

    content_type = getattr(upload, "content_type", "")
    if content_type not in _ALLOWED_IMAGE:
        raise ValidationError(
            "Imagem deve ser JPEG, PNG ou WEBP.", code="IMAGE_TYPE_INVALID"
        )

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if upload.size > max_bytes:
        raise ValidationError(
            f"Imagem maior que {settings.MAX_UPLOAD_MB} MB.", code="IMAGE_TOO_LARGE"
        )

    document = _get_document(external_id)
    sub_name, field = _PHOTO_SLOTS[slot]

    if sub_name == "military":
        profile = profiles.find_by_external_id(external_id)
        if profile is None or profile.gender != "M":
            raise ValidationError(
                "Documento militar só se aplica a usuários do gênero masculino.",
                code="MILITARY_NOT_APPLICABLE",
            )

    ext = _ALLOWED_IMAGE[content_type]
    path = f"documents/{external_id}/{slot}.{ext}"
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, upload)

    sub = getattr(document, sub_name)
    setattr(sub, field, path)
    sub.save(update_fields=[field])
    logger.info("documents.photo_uploaded", external_id=external_id, slot=slot)
    return path


def delete_photo(external_id: str, slot: str) -> None:
    if slot not in _PHOTO_SLOTS:
        raise ValidationError(f"Slot de foto inválido: {slot}.", code="SLOT_INVALID")
    document = _get_document(external_id)
    sub_name, field = _PHOTO_SLOTS[slot]
    sub = getattr(document, sub_name)
    path = getattr(sub, field)
    if path and default_storage.exists(path):
        default_storage.delete(path)
    setattr(sub, field, None)
    sub.save(update_fields=[field])
    logger.info("documents.photo_deleted", external_id=external_id, slot=slot)
