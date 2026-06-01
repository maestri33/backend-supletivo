"""Views DMZ do `address` (CONVENTION §6) — embrulham `users/address/interface/` em HTTP.

São DMZ (rede interna, `<servico>.prod`): segurança é a borda da rede (§5). `external_id` no path
= uso de borda (§4). Hoje sem edge ainda, testadas direto (curl/host). Erros → JSON {detail, code}.
"""

from __future__ import annotations

import json

import structlog
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.address import interface
from users.exceptions import DomainError, NotFound

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
@require_http_methods(["GET", "PATCH"])
def detail(request, external_id):
    """GET = endereço do usuário; PATCH = demais dados (number, complement, ...)."""
    if request.method == "GET":
        address = interface.get_by_external_id(external_id)
        if address is None:
            return _error(
                NotFound("Endereço não encontrado.", code="ADDRESS_NOT_FOUND")
            )
        return JsonResponse(interface.as_dict(address))

    try:
        data = _body(request)
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    try:
        address = interface.patch(external_id=external_id, **data)
    except DomainError as exc:
        return _error(exc)
    return JsonResponse(interface.as_dict(address))


@csrf_exempt
@require_http_methods(["GET"])
def by_id(request, address_id):
    address = interface.get_by_id(address_id)
    if address is None:
        return _error(NotFound("Endereço não encontrado.", code="ADDRESS_NOT_FOUND"))
    return JsonResponse(interface.as_dict(address))


@csrf_exempt
@require_http_methods(["GET"])
def listing(request):
    limit = int(request.GET.get("limit", 100))
    offset = int(request.GET.get("offset", 0))
    items = interface.list_all(limit=limit, offset=offset)
    return JsonResponse({"results": [interface.as_dict(a) for a in items]})


@csrf_exempt
@require_http_methods(["POST"])
def set_cep(request, external_id):
    """Valida o CEP, busca no ViaCEP, salva no endereço e devolve o resultado (spec address)."""
    try:
        data = _body(request)
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    try:
        address = interface.set_by_cep(external_id=external_id, cep=data.get("cep", ""))
    except DomainError as exc:
        return _error(exc)
    return JsonResponse(interface.as_dict(address))
