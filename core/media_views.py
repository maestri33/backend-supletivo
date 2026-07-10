"""View de /media/ com split público/privado + gate de dono (Lane #4 — Victor 2026-07-08).

`core/urls.py` continua expondo `/media/<path>` (compat de URL: notify/Evolution buscam mídia
por essa rota), mas agora passa por um gate antes de servir o arquivo:

- prefixo PÚBLICO (fora de `settings.MEDIA_PRIVATE_PREFIXES` — ex.: `training/`, `ai/`) → serve
  direto, sem auth, reusando `django.views.static.serve` (mesma semântica de sempre: 404,
  If-Modified-Since, content-type por extensão).
- prefixo PRIVADO (`settings.MEDIA_PRIVATE_PREFIXES`: documents, selfie, diploma, receipt,
  student) → exige um access token JWT válido (mesma validação do `api/auth.py:JWTAuth` — RS256,
  não-expirado, `type=access`, `token_version` batendo com o do User). Sem token válido → 401 JSON
  (fail-closed, mesmo padrão dos outros handlers de `core/urls.py`).

LIMITAÇÃO DOCUMENTADA (gate é "autenticado", não "é o dono"): os paths privados são
`"<prefixo>/<token>.<ext>"` com token aleatório não-enumerável (`core/media.py`, pedido do Victor
2026-06-21 — o `external_id` NUNCA vai no path). Não existe hoje um índice `token → dono`: os
campos que guardam esses paths estão espalhados em vários apps/models (`users.documents.models`
RG/CNH/Certificate/AddressProof/Military, `StudentProfile.diploma`, selfies de auditoria do
enrollment, recibos de payout do staff) sem relação reversa indexada por path. Cruzar tudo isso
aqui infla o módulo com import de meia dúzia de apps só pra um SELECT por request — não é
"barata" no sentido do pedido original.

Por isso o gate aqui confirma SOMENTE que a requisição tem um JWT de acesso válido (usuário
autenticado no funil) — NÃO confirma que o arquivo pedido pertence a ESSE usuário. Qualquer
usuário autenticado que souber/adivinhar um token de outra pessoa ainda consegue baixar o arquivo
dela. Fechar esse gap de verdade exige (fora do escopo desta lane): (a) uma tabela/índice
`token → owner` preenchida no `save_media`, ou (b) parar de devolver o path cru pra API e passar a
devolver uma URL assinada/com expiração por recurso.
"""

from __future__ import annotations

import posixpath

from django.conf import settings
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotFound,
    JsonResponse,
)
from django.views.static import serve as _static_serve

from core.media import is_private_media
from users.auth.jwt import service as jwt_service


def _bearer_token(request: HttpRequest) -> str | None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[len("bearer ") :].strip()
    return token or None


def _has_valid_access_token(request: HttpRequest) -> bool:
    """Mesma checagem do `api/auth.py:JWTAuth`: assinatura+exp+tipo (ninja-jwt) + token_version."""
    token = _bearer_token(request)
    if not token:
        return False
    try:
        payload = jwt_service.decode(token)
    except jwt_service.TokenError:
        return False
    external_id = payload.get("external_id", "")
    return jwt_service.version_matches(external_id, payload.get("token_version"))


def media_serve(request: HttpRequest, path: str) -> HttpResponse:
    """Serve `MEDIA_ROOT/<path>`. Prefixo privado sem JWT válido → 401 (ver docstring do módulo).

    G1: normaliza o path ANTES de classificar/servir. Sem isso, `training/../documents/<tok>.jpg`
    era classificado pelo 1º segmento (`training`, público) e servido sem token — apesar de o
    arquivo final ser privado (`documents`). `normpath` resolve o `..`; se o resultado ainda escapa
    do root (`../` sobrando), 404 (não deixa `_static_serve` levantar SuspiciousFileOperation=500)."""
    norm = posixpath.normpath("/" + path).lstrip("/")
    if not norm or norm.startswith("../"):
        return HttpResponseNotFound()
    if is_private_media(norm) and not _has_valid_access_token(request):
        return JsonResponse({"detail": "Não autenticado."}, status=401)
    return _static_serve(request, norm, document_root=settings.MEDIA_ROOT)
