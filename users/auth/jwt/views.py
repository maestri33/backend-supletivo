"""View pública do JWKS — `GET /.well-known/jwks.json` (RFC 7517).

É o único endpoint JWT exposto: a chave PÚBLICA, pra qualquer um (edges/front) validar os tokens
emitidos. Emissão/refresh são in-process (chamados pelo `auth.service` no login), não têm endpoint.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from users.auth.jwt import service


@require_GET
def jwks(request):
    return JsonResponse(service.get_jwks())
