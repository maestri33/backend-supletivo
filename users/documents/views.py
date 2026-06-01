"""Views DMZ do `documents` (CONVENTION §6) — embrulham `users/documents/interface/` em HTTP.

DMZ (rede interna, §5/§6); `external_id` no path = borda (§4). Upload de foto é multipart
(campo `file`). Erros de domínio → JSON {detail, code}.
"""

from __future__ import annotations

import json

import structlog
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.documents import interface
from users.exceptions import DomainError, ValidationError

logger = structlog.get_logger()


def _body(request) -> dict:
    if not request.body:
        return {}
    return json.loads(request.body)


def _error(exc: DomainError) -> JsonResponse:
    payload = {"detail": exc.detail, "code": exc.code}
    payload.update(exc.extra)
    return JsonResponse(payload, status=exc.status)


@csrf_exempt
@require_http_methods(["GET", "PUT", "PATCH"])
def detail(request, external_id):
    """GET = documentos do usuário; PUT/PATCH = atualiza os campos enviados de cada sub-doc."""
    try:
        if request.method == "GET":
            return JsonResponse(interface.get_by_external_id(external_id))
        try:
            data = _body(request)
        except ValueError:
            return HttpResponseBadRequest("JSON inválido.")
        return JsonResponse(interface.update(external_id, data))
    except DomainError as exc:
        return _error(exc)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def photo(request, external_id, slot):
    """POST (multipart, campo `file`) = sobe a foto do slot; DELETE = remove."""
    try:
        if request.method == "DELETE":
            interface.delete_photo(external_id, slot)
            return JsonResponse({"deleted": True, "slot": slot})
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError(
                "Envie o arquivo no campo `file`.", code="FILE_MISSING"
            )
        path = interface.upload_photo(external_id, slot, upload)
        return JsonResponse({"slot": slot, "path": path})
    except DomainError as exc:
        return _error(exc)
