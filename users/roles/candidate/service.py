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
from users.exceptions import Conflict, DomainError, NotFound
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.candidate.models import Candidate

logger = structlog.get_logger()

_S = Candidate.Status
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class CandidateError(DomainError):
    """Erro de borda do candidate (não encontrado, etapa fora de ordem, Pix inválida).

    É `DomainError` (422): o handler central da API converte em JSON `{detail, code, …extra}`."""

    status = 422


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
        raise NotFound("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if allowed_status and cand.status not in allowed_status:
        # 409 + expected_status = a etapa ATUAL no servidor — o front roteia o wizard com isso.
        raise Conflict(
            "Seu cadastro está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": cand.status},
        )
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
        "selfie_status": cand.selfie_status,
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


def get_address(*, user_external_id) -> dict:
    """GET do endereço (o front vê o que está vazio p/ saber o que ainda pode preencher)."""
    _require(user_external_id)
    return address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )


def set_address_cep(*, user_external_id, cep) -> dict:
    """Busca o CEP (ViaCEP) e preenche o endereço. Em cidade de CEP único a rua fica vazia p/ digitar."""
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    _advance_address(cand, user_external_id)
    return address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )


def set_address_data(*, user_external_id, **fields) -> dict:
    """Preenche os demais campos do endereço — SÓ os que estão VAZIOS (não sobrescreve o que o CEP trouxe)."""
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.fill_empty(external_id=user_external_id, **fields)
    _advance_address(cand, user_external_id)
    return address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )


def _advance_address(cand: Candidate, user_external_id) -> None:
    """Avança PROFILE→ADDRESS quando o endereço fica completo (campos essenciais preenchidos)."""
    if cand.status == _S.PROFILE and address_iface.is_complete(
        address_iface.get_by_external_id(user_external_id)
    ):
        _set_status(cand, _S.ADDRESS)


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
    """Foto do documento (slots `rg_front`/`rg_back`/`cnh_front`/`cnh_back`).

    Na FRENTE (rg_front/cnh_front) o rosto vira biometria do documento, salva no perfil (best-effort —
    não quebra o upload; rosto ruim cai em review na selfie). Candidato aceita RG OU CNH (Victor)."""
    from pathlib import Path

    from integrations.tools.biometric import service as biometric

    cand = _require(user_external_id, _S.DOCUMENTS, _S.PIX)
    path = documents_iface.upload_photo(user_external_id, slot, upload)
    biometric.try_enroll_document(
        user=cand.user,
        slot=slot,
        image_path=str(Path(settings.MEDIA_ROOT) / path),
        caller="candidate.document",
    )
    return path


def set_pix(*, user_external_id, key: str, key_type: str) -> Candidate:
    """Valida a chave Pix no Asaas/DICT (confere que é do candidato, CPF do Profile) e grava. MEXE R$0,01."""
    from integrations.bank.asaas import pixkey

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
    """Selfie ("assinar"): valida por IA (3 estados). APROVADA → COMPLETED + promove candidate→training.
    REPROVADA → refazer (avisa o candidato). REVISÃO (IA fora/dúvida) → o coordenador decide o sim/não."""
    from users.roles import _selfie

    from pathlib import Path

    cand = _require(user_external_id, _S.PIX, _S.SELFIE)
    cand.selfie_image = _save_selfie(cand, image_bytes, content_type)
    status, desc = _selfie.verify(image_bytes, content_type, caller="candidate.selfie")
    # SOMAR (Victor 2026-06-05): face-match biométrico selfie × documento. Avança só se os dois passarem.
    status, desc = _selfie.add_face_match(
        user=cand.user,
        selfie_image_path=str(Path(settings.MEDIA_ROOT) / cand.selfie_image),
        caller="candidate.selfie",
        liveness_status=status,
        liveness_desc=desc,
    )
    cand.selfie_status = status
    cand.selfie_verified = status == _selfie.APPROVED
    cand.selfie_description = desc
    if cand.status == _S.PIX:
        cand.status = _S.SELFIE  # avança pra etapa selfie (aguarda veredito)
    cand.save()
    _resolve_selfie(cand)
    return cand


def _save_selfie(cand: Candidate, image_bytes: bytes, content_type: str) -> str:
    from pathlib import Path

    ext = _SELFIE_EXT.get(content_type, "jpg")
    rel = f"candidate/{cand.external_id}/selfie.{ext}"
    fp = Path(settings.MEDIA_ROOT) / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(image_bytes)
    return rel


def _resolve_selfie(cand: Candidate) -> None:
    """Reage ao veredito da selfie: aprovada→promove; reprovada→avisa candidato; revisão→avisa coordenador."""
    from users.roles import _selfie

    if cand.selfie_status == _selfie.APPROVED:
        _promote_to_training(cand)
    elif cand.selfie_status == _selfie.REJECTED:
        _notify_selfie_rejected(cand)
    elif cand.selfie_status == _selfie.REVIEW:
        _notify_selfie_review(cand)


def _promote_to_training(cand: Candidate) -> None:
    """Selfie aprovada → COMPLETED + promove candidate→training + cria Trainee. Idempotente (só em SELFIE)."""
    if cand.status != _S.SELFIE:
        return
    from users.roles.training import interface as training_iface

    with transaction.atomic():
        _set_status(cand, _S.COMPLETED)
        if "training" not in roles.active_roles(cand.user):
            roles.promote(cand.user, "training")
        training_iface.create_trainee(user=cand.user)
    _notify_training_started(cand)


def decide_selfie(
    *, candidate_external_id: str, coordinator, approve: bool, reason: str | None = None
) -> Candidate:
    """Coordenador do hub decide a selfie em REVISÃO (sim/não). aprova→promove; reprova→avisa refazer."""
    from users.roles import _selfie

    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("candidate_not_found")
    if cand.hub.coordinator_id != coordinator.id:
        raise CandidateError("not_hub_coordinator")
    if cand.selfie_status != _selfie.REVIEW:
        raise CandidateError(f"selfie_not_in_review:{cand.selfie_status}")
    note = (reason or "").strip() or (
        "aprovada pelo coordenador" if approve else "reprovada pelo coordenador"
    )
    cand.selfie_status = _selfie.APPROVED if approve else _selfie.REJECTED
    cand.selfie_verified = approve
    cand.selfie_description = note
    cand.save(
        update_fields=[
            "selfie_status",
            "selfie_verified",
            "selfie_description",
            "updated_at",
        ]
    )
    if approve:
        _promote_to_training(cand)
    else:
        _notify_selfie_rejected(cand)
    return cand


def _notify_selfie_rejected(cand: Candidate) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    p = profiles.get(cand.user)
    try:
        send(
            text=msgs.text(
                "candidate.selfie_rejected", name=msgs.first_name(p.name if p else None)
            ),
            caller="candidate.selfie_rejected",
            phone=p.phone if p else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_rejected_failed", error=str(exc))


def _notify_selfie_review(cand: Candidate) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    coord = cand.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send(
            text=msgs.text(
                "candidate.selfie_in_review",
                name=msgs.first_name(cp.name if cp else None),
            ),
            caller="candidate.selfie_in_review",
            phone=cp.phone if cp else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_review_failed", error=str(exc))


def _notify_training_started(cand: Candidate) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    p = profiles.get(cand.user)
    try:
        send(
            text=msgs.text(
                "candidate.training_started",
                name=msgs.first_name(p.name if p else None),
            ),
            caller="candidate.training_started",
            phone=p.phone if p else None,
            email=p.email if p else None,
            email_channel=bool(p and p.email),
            idempotency_key=f"candidate_done_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_failed", error=str(exc))
