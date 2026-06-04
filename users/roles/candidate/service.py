"""Lógica do candidate (funil do colaborador): captação → coleta → vira treino.

Espelho do lead+enrollment: `create_candidate` reusa o `register` (role `candidate`) + cria o `Candidate`
ligado a um HUB. Funil autenticado: perfil → endereço(ViaCEP) → RG/CNH → **Pix (validada no Asaas/DICT)** →
selfie(IA) → `COMPLETED` + promove `candidate→training` + cria o `Trainee`. ⚠️ o passo Pix MEXE DINHEIRO REAL.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.db import transaction

from hub import interface as hub_iface
from users.address import interface as address_iface
from users.auth import interface as auth_iface
from users.auth.models import User
from users.documents import interface as documents_iface
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.candidate.models import Candidate

logger = structlog.get_logger()

_S = Candidate.Status
_PERSON_TERMS = (
    "pessoa",
    "rosto",
    "homem",
    "mulher",
    "face",
    "selfie",
    "retrato",
    "cabelo",
    "cabeça",
    "olhos",
)
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class CandidateError(Exception):
    """Erro de borda do candidate (não encontrado, etapa fora de ordem, Pix inválida)."""


# ── nascimento (público) ────────────────────────────────────────────────────


def create_candidate(*, cpf: str, phone: str, email: str, hub=None) -> dict:
    """Cria o candidato: register(role candidate) + Candidate(STARTED) ligado a um hub.

    `hub` = external_id do polo (landing `?ref=` do coordenador); sem hub → hub padrão (regra dura:
    candidato↔hub).
    """
    hub_obj = hub_iface.get_by_external_id(hub) if hub else hub_iface.get_default()
    if hub_obj is None:
        raise CandidateError("no_hub")  # seed_defaults não rodou / hub inexistente

    reg = auth_iface.register(role="candidate", phone=phone, cpf=cpf, email=email)
    user = User.objects.get(external_id=reg["external_id"])
    candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
    logger.info(
        "candidate.created",
        external_id=str(candidate.external_id),
        hub=str(hub_obj.external_id),
    )
    return {"external_id": str(candidate.external_id), "status": candidate.status}


def get_for_user_external_id(user_external_id: str) -> Candidate | None:
    return (
        Candidate.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "user")
        .first()
    )


def _require(user_external_id: str, *allowed_status) -> Candidate:
    cand = get_for_user_external_id(user_external_id)
    if cand is None:
        raise CandidateError("candidate_not_found")
    if allowed_status and cand.status not in allowed_status:
        raise CandidateError(f"wrong_status:{cand.status}")
    return cand


def _set_status(cand: Candidate, to_status: str) -> None:
    cand.status = to_status
    cand.save(update_fields=["status", "updated_at"])


def to_dict(cand: Candidate) -> dict:
    return {
        "external_id": str(cand.external_id),
        "status": cand.status,
        "hub_external_id": str(cand.hub.external_id),
        "pix_validated": cand.pix_validated,
        "selfie_verified": cand.selfie_verified,
    }


# ── funil de coleta (autenticado, role candidate) ───────────────────────────


def set_profile(
    *,
    user_external_id,
    mother_name=None,
    father_name=None,
    marital_status=None,
    birthplace=None,
    nationality=None,
) -> Candidate:
    cand = _require(user_external_id, _S.STARTED, _S.PROFILE)
    for field, value in (
        ("mother_name", mother_name),
        ("father_name", father_name),
        ("marital_status", marital_status),
        ("birthplace", birthplace),
        ("nationality", nationality),
    ):
        if value is not None:
            setattr(cand, field, value)
    cand.save()
    if cand.status == _S.STARTED:
        _set_status(cand, _S.PROFILE)
    return cand


def set_address(*, user_external_id, cep, number=None, complement=None) -> dict:
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    patch = {}
    if number is not None:
        patch["number"] = number
    if complement is not None:
        patch["complement"] = complement
    if patch:
        address_iface.patch(external_id=user_external_id, **patch)
    if cand.status == _S.PROFILE:
        _set_status(cand, _S.ADDRESS)
    return address_iface.as_dict(address_iface.get_by_external_id(user_external_id))


def set_documents(*, user_external_id, doc_type: str, **fields) -> dict:
    """RG ou CNH (candidato aceita os dois). `doc_type` = 'rg'|'cnh'; `fields` = number/issuing_agency/..."""
    cand = _require(user_external_id, _S.ADDRESS, _S.DOCUMENTS)
    doc_type = doc_type.strip().lower()
    if doc_type not in ("rg", "cnh"):
        raise CandidateError("invalid_doc_type")
    payload = {doc_type: {k: v for k, v in fields.items() if v is not None}}
    result = documents_iface.update(user_external_id, payload)
    if cand.status == _S.ADDRESS:
        _set_status(cand, _S.DOCUMENTS)
    return result


def upload_document_photo(*, user_external_id, slot: str, upload) -> str:
    """Foto do documento (slots `rg_front`/`rg_back`/`cnh_front`/`cnh_back`)."""
    _require(user_external_id, _S.DOCUMENTS, _S.PIX)
    return documents_iface.upload_photo(user_external_id, slot, upload)


def set_pix(*, user_external_id, key: str, key_type: str) -> Candidate:
    """Valida a chave Pix no Asaas/DICT (confere que é do candidato, CPF do Profile) e grava. MEXE R$0,01."""
    from integrations.finance.asaas import pixkey

    cand = _require(user_external_id, _S.DOCUMENTS, _S.PIX)
    profile = profiles.find_by_external_id(user_external_id)
    if profile is None or not profile.cpf:
        raise CandidateError("profile_cpf_missing")
    try:
        pixkey.validate_pix_key(
            key=key, key_type=key_type, expected_document=profile.cpf
        )
    except pixkey.PixKeyError as exc:
        raise CandidateError(f"pix_invalid: {exc}") from exc

    profiles.set_pix(
        user_external_id, key.strip()
    )  # chave canônica no Profile (finance usa no payout)
    cand.pix_key = key.strip()
    cand.pix_key_type = key_type.strip().upper()
    cand.pix_validated = True
    cand.save(update_fields=["pix_key", "pix_key_type", "pix_validated", "updated_at"])
    if cand.status == _S.DOCUMENTS:
        _set_status(cand, _S.PIX)
    logger.info("candidate.pix_validated", external_id=str(cand.external_id))
    return cand


def set_selfie(
    *, user_external_id, image_bytes: bytes, content_type="image/jpeg"
) -> Candidate:
    """Selfie ("assinar"): valida (IA best-effort) → COMPLETED + promove candidate→training + cria Trainee."""
    cand = _require(user_external_id, _S.PIX, _S.SELFIE)
    cand.selfie_image = _save_selfie(cand, image_bytes, content_type)
    cand.selfie_verified, cand.selfie_description = _verify_selfie(
        image_bytes, content_type
    )
    cand.save()

    if cand.status == _S.PIX:
        from users.roles.training import interface as training_iface

        with transaction.atomic():
            _set_status(cand, _S.COMPLETED)
            if "training" not in roles.active_roles(cand.user):
                roles.promote(cand.user, "training")
            training_iface.create_trainee(user=cand.user)
        _notify_training_started(cand)
    return cand


def _save_selfie(cand: Candidate, image_bytes: bytes, content_type: str) -> str:
    from pathlib import Path

    ext = _SELFIE_EXT.get(content_type, "jpg")
    rel = f"candidate/{cand.external_id}/selfie.{ext}"
    fp = Path(settings.MEDIA_ROOT) / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(image_bytes)
    return rel


def _verify_selfie(image_bytes: bytes, content_type: str):
    from integrations.ai import service as ai

    try:
        desc = ai.describe_image(
            image_bytes,
            caller="candidate.selfie",
            mime_type=content_type,
            prompt="Descreva a imagem em português. Há uma pessoa/rosto humano nela?",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort (porte do legado)
        logger.warning("candidate.selfie_ai_failed", error=str(exc))
        return False, None
    low = (desc or "").lower()
    return (any(term in low for term in _PERSON_TERMS), desc)


def _notify_training_started(cand: Candidate) -> None:
    from notify.interface.send import send

    p = profiles.get(cand.user)
    try:
        send(
            text="Cadastro concluído! 🎓 Seu treinamento começou — acesse para estudar e responder.",
            caller="candidate.training_started",
            phone=p.phone if p else None,
            email=p.email if p else None,
            email_channel=bool(p and p.email),
            idempotency_key=f"candidate_done_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_failed", error=str(exc))
