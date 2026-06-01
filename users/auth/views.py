"""Views DMZ do auth (CONVENTION §6) — embrulham `users/auth/interface/` em HTTP.

São DMZ (rede interna, `<servico>.prod`): a segurança é a borda da rede (§5). Hoje, sem edge ainda,
são testadas direto (curl/host). O edge FastAPI público virá depois (§4 item 13) e chamará estas
por HTTP. `register`/`check`/`recover`/`login` (Portão 1). Erros de domínio → JSON {detail, code}.
"""

from __future__ import annotations

import json

import structlog
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from users.auth import interface
from users.exceptions import DomainError

logger = structlog.get_logger()


def _body(request) -> dict:
    """Lê o JSON do corpo. Corpo inválido → ValueError (a view devolve 400)."""
    if not request.body:
        return {}
    return json.loads(request.body)


def _error(exc: DomainError) -> JsonResponse:
    payload = {"detail": exc.detail, "code": exc.code}
    payload.update(exc.extra)
    return JsonResponse(payload, status=exc.status)


@csrf_exempt
@require_POST
def register(request):
    try:
        data = _body(request)
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    try:
        result = interface.register(
            role=data.get("role", ""),
            phone=data.get("phone", ""),
            cpf=data.get("cpf", ""),
        )
    except DomainError as exc:
        return _error(exc)
    return JsonResponse(result, status=201)


@csrf_exempt
@require_POST
def check(request):
    try:
        data = _body(request)
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    try:
        result = interface.check(
            cpf=data.get("cpf"),
            phone=data.get("phone"),
            external_id=data.get("external_id"),
        )
    except DomainError as exc:
        return _error(exc)
    return JsonResponse(result)


@csrf_exempt
@require_POST
def recover(request):
    try:
        data = _body(request)
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    try:
        result = interface.recover(cpf=data.get("cpf"), phone=data.get("phone"))
    except DomainError as exc:
        return _error(exc)
    return JsonResponse(result)


@csrf_exempt
@require_POST
def login(request):
    try:
        data = _body(request)
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    try:
        result = interface.login(
            external_id=data.get("external_id", ""),
            role=data.get("role", ""),
            otp=data.get("otp", ""),
        )
    except DomainError as exc:
        return _error(exc)
    return JsonResponse(result)
