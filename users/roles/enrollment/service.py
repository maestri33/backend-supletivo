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
from users.exceptions import Conflict, DomainError, NotFound
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment.models import EducationalData, Enrollment

logger = structlog.get_logger()

_S = Enrollment.Status
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class EnrollmentError(DomainError):
    """Erro de borda do enrollment (não encontrada, etapa fora de ordem, gate de status/coordenador).

    É `DomainError` (422): o handler central da API converte em JSON `{detail, code, …extra}`."""

    status = 422


# ── 6a: nascimento (chamado pelo hook do lead) ──────────────────────────────


def create_from_lead(*, user, promoter, hub) -> Enrollment:
    """Cria o Enrollment(RG — documento primeiro, plan/13) ligado ao HUB herdado + promove a role
    `lead→enrollment`. Idempotente.

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
        status=Enrollment.Status.RG,
    )
    if "enrollment" not in roles.active_roles(user):
        roles.promote(user, "enrollment")

    logger.info(
        "enrollment.created_from_lead",
        external_id=str(enrollment.external_id),
        hub=str(hub.external_id),
    )
    return enrollment


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
        raise NotFound("Matrícula não encontrada.", code="ENROLLMENT_NOT_FOUND")
    if allowed_status and enr.status not in allowed_status:
        # 409 + expected_status = a etapa ATUAL no servidor — o front roteia o wizard com isso.
        raise Conflict(
            "Sua matrícula está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": enr.status},
        )
    return enr


def _set_status(enr: Enrollment, to_status: str) -> None:
    enr.status = to_status
    enr.save(update_fields=["status", "updated_at"])


def _rg_started_at(rg):
    """Quando a análise do RG (re)começou — do JSON do reset (proposta #2). None = sem referência."""
    from datetime import datetime

    raw = (rg.validation_result or {}).get("analysis_started_at") if rg else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _reconcile_stale_analyses(enr: Enrollment) -> None:
    """TTL guard (proposta #2): `pending` que estourou o prazo vira `review` — o aluno nunca fica
    preso em "analisando…" se a task da IA morreu. Persiste o flip (cai na fila do coordenador) e
    avisa, reusando os mesmos caminhos do review da IA. Idempotente; roda nas LEITURAS do funil."""
    from users.roles import _analysis, _selfie

    if _analysis.is_stale(enr.selfie_status, enr.selfie_taken_at):
        enr.selfie_status = _selfie.REVIEW
        enr.selfie_description = (
            enr.selfie_description or ""
        ).strip() or _analysis.stale_reason()
        enr.save(update_fields=["selfie_status", "selfie_description", "updated_at"])
        _notify_selfie_review(enr)

    rg = documents_iface.get_rg(str(enr.user.external_id))
    if rg is not None and _analysis.is_stale(rg.validation_status, _rg_started_at(rg)):
        _finish_rg(
            enr,
            rg,
            _analysis.REVIEW,
            _analysis.stale_reason(),
            rg.validation_result or {},
        )


def to_dict(enr: Enrollment) -> dict:
    return {
        "external_id": str(enr.external_id),
        "status": enr.status,
        "hub_external_id": str(enr.hub.external_id),
        "selfie_verified": enr.selfie_verified,
        "selfie_status": enr.selfie_status,
        # canônico unificado (proposta #4): a análise da SELFIE/assinatura sob o nome `analysis_status`.
        # `selfie_status` segue como alias (compat) até o front migrar.
        "analysis_status": enr.selfie_status,
    }


def me_dict(enr: Enrollment) -> dict:
    """GET /me RICO (auditoria do front 2026-06-10): o resume do wizard pré-preenche TODAS as seções
    numa chamada só. Bloco `None` = seção ainda não preenchida; `address_complete` = endereço pronto."""
    _reconcile_stale_analyses(
        enr
    )  # TTL guard (proposta #2): pending estourado → review, aqui também
    user_ext = str(enr.user.external_id)

    profile = None
    if any(
        (
            enr.mother_name,
            enr.father_name,
            enr.marital_status,
            enr.birthplace,
            enr.nationality,
        )
    ):
        profile = {
            "mother_name": enr.mother_name,
            "father_name": enr.father_name,
            "marital_status": enr.marital_status,
            "birthplace": enr.birthplace,
            "nationality": enr.nationality,
        }

    rg_data = (documents_iface.get_by_external_id(user_ext) or {}).get("rg") or {}
    rg = None
    if any(
        rg_data.get(k) for k in ("number", "front_photo", "back_photo", "full_photo")
    ):
        rg = {
            "number": rg_data.get("number"),
            "issuing_agency": rg_data.get("issuing_agency"),
            "issue_date": rg_data.get("issue_date"),
            "front_photo": rg_data.get("front_photo"),
            "back_photo": rg_data.get("back_photo"),
            "full_photo": rg_data.get("full_photo"),
            # validação IA (plan/12): o front mostra "analisando…"/motivo e o que falta digitar.
            # `analysis_status`/`analysis_reason` = nome CANÔNICO (proposta #4); os `validation_*`
            # seguem como alias (compat) até o front migrar.
            "analysis_status": rg_data.get("validation_status"),
            "analysis_reason": rg_data.get("validation_reason"),
            "validation_status": rg_data.get("validation_status"),
            "validation_reason": rg_data.get("validation_reason"),
            "missing_fields": [
                f
                for f in ("number", "issuing_agency", "issue_date")
                if not rg_data.get(f)
            ],
        }

    try:
        edu = enr.educational_data
    except EducationalData.DoesNotExist:
        edu = None
    education = None
    if edu is not None:
        education = {
            "last_year_studied": edu.last_year_studied,
            "last_school": edu.last_school,
            "last_year_when": edu.last_year_when,
        }

    address = address_iface.get_by_external_id(user_ext)
    return {
        **to_dict(enr),
        "profile": profile,
        "address_complete": address_iface.is_complete(address),
        "rg": rg,
        "education": education,
    }


# ── 6b: funil de coleta ──────────────────────────────────────────────────────
# `status` = a seção que o aluno preenche AGORA (vocabulário do wizard do front).
# Ordem nova (plan/13, Victor 2026-06-11): DOCUMENTO primeiro — a extração povoa o perfil.
# rg → address → education → selfie → awaiting_release → completed.
# Gates ESTRITOS nos POSTs de seção; fora de hora → 409 {detail, code:WRONG_STATUS,
# expected_status}. GETs são leitura (qualquer etapa). Avanço com CHAIN-SKIP: se a próxima
# seção já está completa, pula — ninguém fica preso numa etapa sem nada a fazer.


def _has_education(enr: Enrollment) -> bool:
    try:
        return enr.educational_data is not None
    except EducationalData.DoesNotExist:
        return False


def _advance_to(enr: Enrollment, target: str) -> None:
    """Avança pra `target` PULANDO seções já completas (chain-skip, plan/13)."""
    user_ext = str(enr.user.external_id)
    status = target
    while True:
        if status == _S.ADDRESS and address_iface.is_complete(
            address_iface.get_by_external_id(user_ext)
        ):
            status = _S.EDUCATION
            continue
        if status == _S.EDUCATION and _has_education(enr):
            status = _S.SELFIE
            continue
        break
    _set_status(enr, status)


# ── seção ENDEREÇO (plan/13): POST só com CEP · PATCH só-vazios · GET ────────
# `missing_fields` em toda resposta: o front renderiza input SÓ do que está na lista
# (ex.: ["number"] = ViaCEP achou tudo, falta o número; rua/bairro na lista = CEP único).
_ADDRESS_FIELDS = (
    "street",
    "number",
    "neighborhood",
    "city",
    "state",
)  # complement opcional


def _address_dict(user_external_id: str) -> dict:
    data = address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )
    data["missing_fields"] = [f for f in _ADDRESS_FIELDS if not data.get(f)]
    return data


def get_address(*, user_external_id: str) -> dict:
    """GET do endereço + `missing_fields` (o que ainda falta preencher)."""
    _require(user_external_id)
    return _address_dict(user_external_id)


def set_address_cep(*, user_external_id: str, cep: str) -> dict:
    """POST do endereço (plan/13): body só `{cep}`. Acha no ViaCEP, grava, e a resposta JÁ AVISA
    o que falta: rua achada → `missing_fields=["number"]`; cidade de CEP único → rua/bairro/número."""
    enr = _require(user_external_id, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    _advance_address(enr, user_external_id)
    return _address_dict(user_external_id)


def set_address_data(*, user_external_id: str, **fields) -> dict:
    """PATCH do endereço — preenche SÓ o que está VAZIO (não sobrescreve o que o CEP trouxe)."""
    enr = _require(user_external_id, _S.ADDRESS)
    address_iface.fill_empty(external_id=user_external_id, **fields)
    _advance_address(enr, user_external_id)
    return _address_dict(user_external_id)


def _advance_address(enr: Enrollment, user_external_id: str) -> None:
    """Endereço completo → EDUCATION (ordem plan/13), com chain-skip."""
    if enr.status == _S.ADDRESS and address_iface.is_complete(
        address_iface.get_by_external_id(user_external_id)
    ):
        _advance_to(enr, _S.EDUCATION)


# ── seção DOCUMENTO (plan/13): GET rico · PATCH completa/corrige ─────────────
# Campos editáveis: do RG (number/órgão/emissão) + os de perfil que o documento povoa
# (filiação/naturalidade) ou não traz (estado civil/nacionalidade). `name`/`birth_date`
# vêm do CPFHub/extração — NÃO editáveis pelo aluno.
_RG_DOC_FIELDS = ("number", "issuing_agency", "issue_date")
_RG_PROFILE_FIELDS = (
    "mother_name",
    "father_name",
    "birthplace",
    "marital_status",
    "nationality",
)


def _rg_section_dict(enr: Enrollment) -> dict:
    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    p = profiles.get(enr.user)
    fields = {
        "number": rg.number if rg else None,
        "issuing_agency": rg.issuing_agency if rg else None,
        "issue_date": rg.issue_date.isoformat() if (rg and rg.issue_date) else None,
        "mother_name": enr.mother_name,
        "father_name": enr.father_name,
        "birthplace": enr.birthplace,
        "marital_status": enr.marital_status,
        "nationality": enr.nationality,
    }
    result = (rg.validation_result or {}) if rg else {}
    return {
        **fields,
        "name": p.name if p else None,
        "birth_date": p.birth_date.isoformat() if (p and p.birth_date) else None,
        "front_photo": rg.front_photo if rg else None,
        "back_photo": rg.back_photo if rg else None,
        "full_photo": rg.full_photo if rg else None,
        # canônico unificado (proposta #4) + alias `validation_*` (compat) até o front migrar.
        "analysis_status": rg.validation_status if rg else None,
        "analysis_reason": result.get("reason"),
        "validation_status": rg.validation_status if rg else None,
        "validation_reason": result.get("reason"),
        "missing_fields": [
            k for k in (*_RG_DOC_FIELDS, *_RG_PROFILE_FIELDS) if not fields[k]
        ],
    }


def get_rg_section(*, user_external_id: str) -> dict:
    """GET da seção documento (plan/13): fotos + validação + TODOS os campos (extraídos pela IA
    ou digitados) + `missing_fields` (o que o aluno ainda precisa completar)."""
    enr = _require(user_external_id)
    _reconcile_stale_analyses(enr)  # TTL guard (proposta #2)
    return _rg_section_dict(enr)


def patch_rg_section(*, user_external_id: str, **fields) -> dict:
    """PATCH da seção documento (plan/13): completa/CORRIGE o que a extração não trouxe — campos
    do doc e do perfil. Aceito em qualquer etapa da coleta (é dado do aluno, não progressão);
    a foto do documento segue sendo a fonte de verdade pra auditoria do coordenador."""
    enr = _require(user_external_id, _S.RG, _S.ADDRESS, _S.EDUCATION, _S.SELFIE)
    doc_payload = {k: fields[k] for k in _RG_DOC_FIELDS if fields.get(k) is not None}
    if doc_payload:
        documents_iface.update(user_external_id, {"rg": doc_payload})
    enr_changed = [k for k in _RG_PROFILE_FIELDS if fields.get(k) is not None]
    for k in enr_changed:
        setattr(enr, k, fields[k])
    if enr_changed:
        enr.save(update_fields=[*enr_changed, "updated_at"])
    _advance_rg(enr, user_external_id)
    return _rg_section_dict(enr)


def upload_rg_photo(*, user_external_id: str, slot: str, upload) -> str:
    """Foto do RG (slot `rg_front`/`rg_back`/`rg_full`), dentro da seção `rg` — plan/12.

    Salva (PDF vira JPEG no `documents`), re-zera a validação e ENFILEIRA o pipeline de IA
    (visão → OCR → extração → biometria). O upload responde na hora; o veredito (e o motivo,
    se reprovar) sai pelo `/enrollment/me`. Aluno: RG é obrigatório (Victor)."""
    from users.roles import _analysis

    enr = _require(user_external_id, _S.RG)
    path = documents_iface.upload_photo(user_external_id, slot, upload)
    _reset_rg_validation(user_external_id, slot)
    from django_q.tasks import async_task

    async_task("users.roles.enrollment.tasks.validate_rg", enr.id, slot)
    # ack de polling (proposta #2): a análise acabou de (re)começar → started_at = agora.
    rg = documents_iface.get_rg(user_external_id)
    return {"stored": path, **_analysis.ack(_analysis.PENDING, _rg_started_at(rg))}


def selfie_ack(enr: Enrollment) -> dict:
    """Ack de polling da selfie (proposta #2) — pro POST devolver junto com o estado."""
    from users.roles import _analysis

    return _analysis.ack(enr.selfie_status, enr.selfie_taken_at)


def _advance_rg(enr: Enrollment, user_external_id: str) -> None:
    """Avança RG→ADDRESS (ordem plan/13) quando a seção fecha: validação IA APROVADA (frente+verso
    OU inteira) + `number` presente (extraído pelo OCR ou digitado no PATCH). Com chain-skip."""
    from users.roles import _document_ai as doc_ai

    if enr.status != _S.RG:
        return
    rg = documents_iface.get_rg(user_external_id)
    if rg is not None and rg.validation_status == doc_ai.APPROVED and rg.number:
        _advance_to(enr, _S.ADDRESS)


# ── validação do RG por IA (plan/12): visão → OCR → extração → biometria ────
# Roda na task Django-Q (`tasks.validate_rg`); aqui é a orquestração (status no RG, notifies,
# avanço do wizard). As chamadas de IA moram em `users/roles/_document_ai.py` (compartilhável).

_RG_SLOT_FIELD = {
    "rg_front": "front_photo",
    "rg_back": "back_photo",
    "rg_full": "full_photo",
}
_RG_SLOT_SIDE = {"rg_front": "front", "rg_back": "back", "rg_full": "full"}
_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _reset_rg_validation(user_external_id: str, slot: str) -> None:
    """Re-upload de um slot re-zera o veredito daquela foto + a extração (re-analisa tudo)."""
    from users.roles import _document_ai as doc_ai

    rg = documents_iface.get_rg(user_external_id)
    if rg is None:
        return
    from django.utils import timezone

    result = rg.validation_result or {}
    photos = dict(result.get("photos") or {})
    photos.pop(slot, None)
    for key in ("extracted", "name_match", "reason", "human"):
        result.pop(key, None)
    result["photos"] = photos
    # marca o INÍCIO da análise (proposta #2): o re-upload reinicia o relógio do TTL. Guardado no
    # JSON (sem migração); só vale enquanto `pending` (o `_finish_rg` reescreve o result ao concluir).
    result["analysis_started_at"] = timezone.now().isoformat()
    rg.validation_status = doc_ai.PENDING
    rg.validation_result = result
    rg.validated_at = None
    rg.save(update_fields=["validation_status", "validation_result", "validated_at"])


def run_rg_validation(enrollment_id: int, slot: str) -> None:
    """Pipeline da task (plan/12). Idempotente: só age com validação `pending`.

    a) visão na foto do `slot` (é RG? lado certo? legível?) → reprovou/dúvida = para e notifica;
    b) seção completa (inteira aprovada OU frente+verso aprovadas) → OCR + extração (1 LLM);
    c) nome de outra pessoa → reprova; dúvida → review; ok → povoa campos VAZIOS →
       biometria → avança o wizard."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    enr = (
        Enrollment.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=enrollment_id)
        .first()
    )
    if enr is None:
        return
    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    if rg is None or rg.validation_status != doc_ai.PENDING:
        return

    result = rg.validation_result or {}
    photos = dict(result.get("photos") or {})

    field = _RG_SLOT_FIELD.get(slot)
    path = getattr(rg, field, None) if field else None
    if path and (photos.get(slot) or {}).get("status") != doc_ai.APPROVED:
        fp = Path(settings.MEDIA_ROOT) / path
        if not fp.exists():
            return
        mime = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
        # pré-tratamento (Victor 2026-06-11): endireita a foto ANTES de validar — EXIF + auto-rotação
        # por IA. Melhora visão/OCR/biometria e deixa o documento guardado reto. Best-effort.
        doc_ai.fix_orientation(str(fp), mime_type=mime, caller="enrollment.rg")
        status, reason = doc_ai.check_photo(
            fp.read_bytes(),
            side=_RG_SLOT_SIDE[slot],
            mime_type=mime,
            caller="enrollment.rg",
        )
        # merge FRESCO: a visão leva 10–60s e frente+verso viram 2 tasks em workers paralelos —
        # re-lê antes de gravar pra não perder o veredito que o outro worker salvou no meio tempo.
        rg.refresh_from_db()
        if rg.validation_status != doc_ai.PENDING:
            return  # outro worker (ou re-upload) já mudou o estado — não sobrescrever
        result = rg.validation_result or {}
        photos = dict(result.get("photos") or {})
        photos[slot] = {"status": status, "reason": reason}
        result["photos"] = photos
        if status != doc_ai.APPROVED:
            _finish_rg(enr, rg, status, reason, result)
            return

    images = _rg_approved_images(rg, photos)
    if images is None:
        # esta foto passou, mas falta a outra — guarda o veredito e espera o resto da seção
        rg.validation_result = result
        rg.save(update_fields=["validation_result"])
        return
    _rg_extract_and_finish(enr, rg, result, images)


def _rg_approved_images(rg, photos: dict) -> list | None:
    """Imagens da seção completa e aprovada (inteira OU frente+verso), ou None se ainda falta."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    def ok(slot: str) -> bool:
        return (photos.get(slot) or {}).get("status") == doc_ai.APPROVED

    if rg.full_photo and ok("rg_full"):
        return [Path(settings.MEDIA_ROOT) / rg.full_photo]
    if rg.front_photo and rg.back_photo and ok("rg_front") and ok("rg_back"):
        return [
            Path(settings.MEDIA_ROOT) / rg.front_photo,
            Path(settings.MEDIA_ROOT) / rg.back_photo,
        ]
    return None


def _rg_extract_and_finish(enr: Enrollment, rg, result: dict, images: list) -> None:
    """OCR + extração (1 LLM): confere o nome (tolerância de casamento) e povoa os campos."""
    from users.roles import _document_ai as doc_ai

    p = profiles.get(enr.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="enrollment.rg"
        )
        data = doc_ai.extract_rg(
            ocr_text, holder_name=(p.name if p else None), caller="enrollment.rg"
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar na extração → review (humano decide)
        logger.warning(
            "enrollment.rg_extract_failed",
            enrollment=str(enr.external_id),
            error=str(exc)[:200],
        )
        _finish_rg(
            enr,
            rg,
            doc_ai.REVIEW,
            "IA indisponível na extração dos dados — enviado para revisão manual do coordenador.",
            result,
        )
        return
    result["extracted"] = data
    match = str(data.get("name_match") or "").strip().lower()
    name_reason = (data.get("name_reason") or "").strip()
    if match in ("nao", "não", "no"):
        _finish_rg(
            enr,
            rg,
            doc_ai.REJECTED,
            f"O nome no documento não confere com o do cadastro. {name_reason}".strip(),
            result,
        )
        return
    if match not in ("sim", "yes"):
        _finish_rg(
            enr,
            rg,
            doc_ai.REVIEW,
            f"Não deu pra confirmar o nome do titular. {name_reason}".strip(),
            result,
        )
        return
    _apply_rg_extracted(enr, rg, data)
    _finish_rg(enr, rg, doc_ai.APPROVED, name_reason or "Documento validado.", result)
    _notify_rg_approved(enr)  # notify também no aprovado automático (plan/13)
    _rg_post_approval(enr, rg)


def _apply_rg_extracted(enr: Enrollment, rg, data: dict) -> None:
    """Povoa SÓ campos vazios (Victor: não sobrescrever): doc RG + perfil da matrícula + nascimento."""
    from datetime import date

    def _clean(value, limit: int):
        s = str(value).strip()
        return s[:limit] if s else None

    def _date(value):
        try:
            return date.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

    changed = []
    if not rg.number and data.get("number"):
        rg.number = _clean(data["number"], 30)
        changed.append("number")
    if not rg.issuing_agency and data.get("issuing_agency"):
        rg.issuing_agency = _clean(data["issuing_agency"], 50)
        changed.append("issuing_agency")
    if not rg.issue_date:
        d = _date(data.get("issue_date"))
        if d:
            rg.issue_date = d
            changed.append("issue_date")
    if changed:
        rg.save(update_fields=changed)

    enr_changed = []
    for field, limit in (
        ("mother_name", 255),
        ("father_name", 255),
        ("birthplace", 128),
    ):
        if not getattr(enr, field) and data.get(field):
            setattr(enr, field, _clean(data[field], limit))
            enr_changed.append(field)
    if enr_changed:
        enr.save(update_fields=[*enr_changed, "updated_at"])

    p = profiles.get(enr.user)
    if p and not p.birth_date:
        bd = _date(data.get("birth_date"))
        if bd:
            p.birth_date = bd
            p.save(update_fields=["birth_date"])


def _finish_rg(
    enr: Enrollment, rg, status: str, reason: str | None, result: dict
) -> None:
    """Grava o veredito (justificativa SEMPRE — plan/9) + dispara o notify do estado."""
    from django.utils import timezone

    from users.roles import _document_ai as doc_ai

    result["reason"] = reason
    rg.validation_status = status
    rg.validation_result = result
    rg.validated_at = timezone.now()
    rg.save(update_fields=["validation_status", "validation_result", "validated_at"])
    logger.info(
        "enrollment.rg_validated", enrollment=str(enr.external_id), status=status
    )
    if status == doc_ai.REJECTED:
        _notify_rg_rejected(enr, reason)
    elif status == doc_ai.REVIEW:
        _notify_rg_review(enr, reason)


def _rg_post_approval(enr: Enrollment, rg) -> None:
    """Aprovado → rosto do documento vira biometria (best-effort) + tenta avançar o wizard.

    Recorte (plan/13): InsightFace direto (já detecta/recorta); NÃO achou rosto → a visão
    localiza a região da foto do titular, o Pillow recorta e tenta de novo. Nunca trava o fluxo."""
    from pathlib import Path

    from integrations.tools.biometric import service as biometric

    from users.roles import _document_ai as doc_ai

    face_path = rg.front_photo or rg.full_photo
    face_slot = "rg_front" if rg.front_photo else "rg_full"
    if face_path:
        full = Path(settings.MEDIA_ROOT) / face_path
        enrolled = biometric.try_enroll_document(
            user=enr.user,
            slot=face_slot,
            image_path=str(full),
            caller="enrollment.document",
        )
        if enrolled is None and full.exists():
            cropped = doc_ai.crop_face(full.read_bytes(), caller="enrollment.rg")
            if cropped:
                crop_path = full.with_name("rg_face_crop.jpg")
                crop_path.write_bytes(cropped)
                biometric.try_enroll_document(
                    user=enr.user,
                    slot="rg_front",
                    image_path=str(crop_path),
                    caller="enrollment.document_crop",
                )
    _advance_rg(enr, str(enr.user.external_id))


def run_rg_fill(enrollment_id: int) -> None:
    """Pós-aprovação do coordenador: OCR+extração best-effort SÓ pra preencher campos vazios.

    A aprovação humana é FINAL — aqui não há veto (o `name_match` fica só registrado). Falhou
    a IA → o aluno digita o que faltou (`missing_fields` no /me)."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    enr = (
        Enrollment.objects.select_related("user", "hub")
        .filter(id=enrollment_id)
        .first()
    )
    if enr is None:
        return
    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    if rg is None or rg.validation_status != doc_ai.APPROVED:
        return
    result = rg.validation_result or {}
    if result.get("extracted"):
        return
    images = [
        Path(settings.MEDIA_ROOT) / p
        for p in ([rg.full_photo] if rg.full_photo else [rg.front_photo, rg.back_photo])
        if p
    ]
    images = [fp for fp in images if fp.exists()]
    if not images:
        return
    p = profiles.get(enr.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="enrollment.rg_fill"
        )
        data = doc_ai.extract_rg(
            ocr_text, holder_name=(p.name if p else None), caller="enrollment.rg_fill"
        )
    except Exception as exc:  # noqa: BLE001 — best-effort: falhou → o aluno digita
        logger.warning(
            "enrollment.rg_fill_failed",
            enrollment=str(enr.external_id),
            error=str(exc)[:200],
        )
        return
    result["extracted"] = data
    rg.validation_result = result
    rg.save(update_fields=["validation_result"])
    _apply_rg_extracted(enr, rg, data)
    _advance_rg(enr, user_ext)


def decide_rg(
    *,
    enrollment_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> dict:
    """Coordenador do hub decide o RG em REVISÃO (sim/não). A decisão humana é FINAL sobre a
    validade: aprovou → avisa o aluno + biometria + extração best-effort preenche os campos
    (sem veto); reprovou → volta pro aluno refazer (com o motivo)."""
    from users.roles import _document_ai as doc_ai

    enr = get_by_external_id(enrollment_external_id)
    if enr is None:
        raise EnrollmentError("enrollment_not_found")
    if enr.hub.coordinator_id != coordinator.id:
        raise EnrollmentError("not_hub_coordinator")
    rg = documents_iface.get_rg(str(enr.user.external_id))
    if rg is None or rg.validation_status != doc_ai.REVIEW:
        raise EnrollmentError(
            f"rg_not_in_review:{rg.validation_status if rg else 'missing'}"
        )
    note = (reason or "").strip() or (
        "aprovado pelo coordenador" if approve else "reprovado pelo coordenador"
    )
    result = rg.validation_result or {}
    result["human"] = {
        "approve": approve,
        "reason": note,
        "by": str(coordinator.external_id),
    }
    if not approve:
        _finish_rg(enr, rg, doc_ai.REJECTED, note, result)
        return {
            "external_id": str(enr.external_id),
            "status": enr.status,
            "rg_validation_status": rg.validation_status,
        }
    # aprovação humana: as fotos presentes valem como aprovadas (fica registrado por foto)
    photos = dict(result.get("photos") or {})
    for slot, field in _RG_SLOT_FIELD.items():
        if getattr(rg, field, None):
            photos[slot] = {"status": doc_ai.APPROVED, "reason": note}
    result["photos"] = photos
    _finish_rg(enr, rg, doc_ai.APPROVED, note, result)
    _notify_rg_approved(enr)
    if result.get("extracted"):
        # a revisão veio da dúvida de NOME — extração já existe, povoa agora
        _apply_rg_extracted(enr, rg, result["extracted"])
    else:
        # a revisão veio da visão/IA fora do ar — extração roda best-effort em 2º plano
        from django_q.tasks import async_task

        async_task("users.roles.enrollment.tasks.fill_rg_data", enr.id)
    _rg_post_approval(enr, rg)
    return {
        "external_id": str(enr.external_id),
        "status": enr.status,
        "rg_validation_status": rg.validation_status,
    }


def _notify_rg_rejected(enr: Enrollment, reason: str | None) -> None:
    from notify.interface.send import send

    from users.roles import notifications as msgs

    p = profiles.get(enr.user)
    try:
        send(
            text=msgs.text(
                "enrollment.rg_rejected",
                name=msgs.first_name(p.name if p else None),
                detail=(reason or "").strip(),
            ),
            caller="enrollment.rg_rejected",
            phone=p.phone if p else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_rg_rejected_failed", error=str(exc))


def _notify_rg_review(enr: Enrollment, reason: str | None) -> None:
    from notify.interface.send import send

    from users.roles import notifications as msgs

    coord = enr.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send(
            text=msgs.text(
                "enrollment.rg_in_review",
                name=msgs.first_name(cp.name if cp else None),
                detail=(reason or "").strip(),
            ),
            caller="enrollment.rg_in_review",
            phone=cp.phone if cp else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_rg_review_failed", error=str(exc))


def _notify_rg_approved(enr: Enrollment) -> None:
    from notify.interface.send import send

    from users.roles import notifications as msgs

    p = profiles.get(enr.user)
    try:
        send(
            text=msgs.text(
                "enrollment.rg_approved",
                name=msgs.first_name(p.name if p else None),
            ),
            caller="enrollment.rg_approved",
            phone=p.phone if p else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_rg_approved_failed", error=str(exc))


def get_education(*, user_external_id: str) -> dict:
    """GET dos dados educacionais (plan/13). Tudo None = ainda não preenchido."""
    enr = _require(user_external_id)
    try:
        edu = enr.educational_data
    except EducationalData.DoesNotExist:
        edu = None
    return {
        "last_year_studied": edu.last_year_studied if edu else None,
        "last_school": edu.last_school if edu else None,
        "last_year_when": edu.last_year_when if edu else None,
    }


def set_education(
    *,
    user_external_id: str,
    last_year_studied: str,
    last_school: str,
    last_year_when=None,
) -> Enrollment:
    enr = _require(user_external_id, _S.EDUCATION)
    EducationalData.objects.update_or_create(
        enrollment=enr,
        defaults={
            "last_year_studied": last_year_studied,
            "last_year_when": last_year_when,
            "last_school": last_school,
        },
    )
    _set_status(enr, _S.SELFIE)
    return enr


def get_selfie(*, user_external_id: str) -> dict:
    """GET da selfie/ASSINATURA (plan/13): foto, quando foi enviada, status e os comentários da
    IA/biometria (inclusive as instruções de como ser aprovada). `exists: false` = não enviada."""
    from users.roles import _analysis

    enr = _require(user_external_id)
    _reconcile_stale_analyses(enr)  # TTL guard (proposta #2)
    status = enr.selfie_status if enr.selfie_image else None
    return {
        "exists": bool(enr.selfie_image),
        "photo": enr.selfie_image,
        "taken_at": enr.selfie_taken_at.isoformat() if enr.selfie_taken_at else None,
        "status": status,
        # canônico unificado (proposta #4): `analysis_status`/`analysis_reason` + alias `status`/
        # `description` (compat). `expires_at` = até quando o `pending` vale (proposta #2).
        "analysis_status": status,
        "analysis_reason": enr.selfie_description,
        "expires_at": (
            _analysis.expires_at(enr.selfie_taken_at).isoformat()
            if status == _analysis.PENDING and enr.selfie_taken_at
            else None
        ),
        "verified": enr.selfie_verified,
        "description": enr.selfie_description,
    }


def set_selfie(
    *, user_external_id: str, image_bytes: bytes, content_type: str = "image/jpeg"
) -> Enrollment:
    """Selfie = a ASSINATURA da matrícula (plan/13). Salva a foto e ENFILEIRA a análise: IA
    pré-analisa (vale ir pra biometria?) → face-match vs rosto do DOCUMENTO → reprovou? a IA
    INSTRUI como ser aprovada. Responde na hora; o front acompanha pelo GET /selfie (status)."""
    from django.utils import timezone

    from users.roles import _selfie

    enr = _require(user_external_id, _S.SELFIE)
    enr.selfie_image = _save_selfie(enr, image_bytes, content_type)
    enr.selfie_taken_at = timezone.now()
    enr.selfie_status = _selfie.SelfieStatus.PENDING
    enr.selfie_verified = False
    enr.selfie_description = None
    enr.save()
    from django_q.tasks import async_task

    async_task("users.roles.enrollment.tasks.validate_selfie", enr.id)
    return enr


def run_selfie_validation(enrollment_id: int) -> None:
    """Pipeline da task da selfie (plan/13). Idempotente: só age com `selfie_status` pending.

    a) liveness (é selfie real? adianta ir pra biometria?) → b) face-match vs rosto do DOCUMENTO
    (biometria do RG) → c) reprovou? a visão olha DE NOVO e gera INSTRUÇÕES práticas de como ser
    aprovada (vão no GET e no notify) → d) notifies: aprovada→aluno; reprovada→aluno; review→coord."""
    from pathlib import Path

    from users.roles import _selfie

    enr = (
        Enrollment.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=enrollment_id)
        .first()
    )
    if enr is None or not enr.selfie_image or enr.status != _S.SELFIE:
        return
    if enr.selfie_status != _selfie.SelfieStatus.PENDING:
        return
    fp = Path(settings.MEDIA_ROOT) / enr.selfie_image
    if not fp.exists():
        return
    content_type = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
    image_bytes = fp.read_bytes()
    status, desc = _selfie.verify(image_bytes, content_type, caller="enrollment.selfie")
    # SOMAR (Victor 2026-06-05): face-match biométrico selfie × documento. Avança só se os dois passarem.
    status, desc = _selfie.add_face_match(
        user=enr.user,
        selfie_image_path=str(fp),
        caller="enrollment.selfie",
        liveness_status=status,
        liveness_desc=desc,
    )
    if status == _selfie.REJECTED:
        tips = _selfie.instructions(
            image_bytes, content_type, reason=desc, caller="enrollment.selfie"
        )
        if tips:
            desc = f"{desc}\n\nComo resolver: {tips}"
    enr.refresh_from_db(fields=["selfie_status"])
    if enr.selfie_status != _selfie.SelfieStatus.PENDING:
        return  # re-upload no meio tempo — este veredito é de foto velha, descarta
    enr.selfie_status = status
    enr.selfie_verified = status == _selfie.APPROVED
    enr.selfie_description = desc
    enr.save(
        update_fields=[
            "selfie_status",
            "selfie_verified",
            "selfie_description",
            "updated_at",
        ]
    )
    logger.info(
        "enrollment.selfie_validated", enrollment=str(enr.external_id), status=status
    )
    _resolve_selfie(enr)


def _resolve_selfie(enr: Enrollment) -> None:
    """Reage ao veredito: aprovada→avisa o aluno + aguarda liberação; reprovada→avisa o aluno
    (com as instruções); revisão→avisa o coordenador."""
    from users.roles import _selfie

    if enr.selfie_status == _selfie.APPROVED:
        _notify_selfie_approved(enr)  # notify também no aprovado (plan/13)
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
        _notify_selfie_approved(enr)  # notify também no aprovado (plan/13)
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
                detail=(enr.selfie_description or "").strip(),
            ),
            caller="enrollment.selfie_rejected",
            phone=p.phone if p else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_selfie_rejected_failed", error=str(exc))


def _notify_selfie_approved(enr: Enrollment) -> None:
    from notify.interface.send import send
    from users.roles import notifications as msgs

    p = profiles.get(enr.user)
    try:
        send(
            text=msgs.text(
                "enrollment.selfie_approved",
                name=msgs.first_name(p.name if p else None),
            ),
            caller="enrollment.selfie_approved",
            phone=p.phone if p else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_selfie_approved_failed", error=str(exc))


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
    fee_qr_codes=None,
) -> Enrollment:
    """Coordenador do hub libera a matrícula: promove `enrollment→student`, marca COMPLETED e CRIA o
    `Student` (§4 item 9) já com os dados estruturados da plataforma de estudo + o hub herdado.

    `fee_qr_codes` (opcional): QR(s) PIX da taxa do parceiro credenciador que o coordenador cola na hora da
    liberação. Cada QR é roteado pelo PRÓPRIO QR — COM vencimento → agendado, SEM → imediato — e a taxa sai
    pela MESMA fila Asaas das comissões (`finance.fees`). A promoção é SÍNCRONA e **não espera o pagamento**
    (o aluno já sai estudando — palavra do Victor); o PIX real ocorre depois, no worker. O ALUNO NÃO SABE da
    taxa (sem notify de fee). Os QR são validados (decodificados) ANTES de promover: QR inválido aborta a
    liberação sem criar o aluno (o coordenador corrige e tenta de novo)."""
    from finance.interface import fees
    from users.roles.student import interface as student_iface

    enr = get_by_external_id(enrollment_external_id)
    if enr is None:
        raise NotFound("Matrícula não encontrada.", code="ENROLLMENT_NOT_FOUND")
    if enr.hub.coordinator_id != coordinator.id:
        raise EnrollmentError("not_hub_coordinator")
    if enr.status != _S.AWAITING_RELEASE:
        raise Conflict(
            "A matrícula está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": enr.status},
        )

    # 1) Valida/decodifica os QR FORA da transação (chamada de rede ao Asaas, READ-ONLY): um QR ruim aborta
    #    a liberação ANTES de promover — não cria aluno meia-boca. Não move dinheiro aqui.
    fee_plans = []
    for qr in fee_qr_codes or []:
        if not (qr or "").strip():
            continue
        try:
            fee_plans.append((qr, fees.plan_qr_payment(qr_payload=qr)))
        except ValueError as exc:
            raise EnrollmentError(f"fee_qr_invalid:{exc}") from exc

    # 2) Promoção + criação do Student + enfileiramento das fees: tudo ATÔMICO (só escrita local, sem rede).
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
        for i, (qr, plan) in enumerate(fee_plans):
            fees.request_fee_payment(
                amount=plan["amount"],
                qr_payload=qr,
                supplier_name="credenciador",
                scheduled_for=plan["scheduled_for"],
                external_reference=f"fee_enr_{enr.external_id}_{i}",
                # relaciona a fee à matrícula (interno; o aluno NÃO sabe da taxa — palavra do Victor).
                source_type=fees.SourceType.ENROLLMENT,
                source_external_id=enr.external_id,
            )

    _notify_released(enr)
    logger.info(
        "enrollment.released", external_id=str(enr.external_id), fees=len(fee_plans)
    )
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
