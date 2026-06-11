"""Fábrica dos grupos da API Ninja (CONVENTION §1).

Cada grupo é um `NinjaAPI` **versionado** (`/api/v1/<grupo>/`, montado no `core/urls.py`), com
auth JWT default e duas rotas de esqueleto: `health` (pública) e `whoami` (autenticada, prova o
JWT fim-a-fim). As rotas de negócio entram com cada role/módulo (§4), chamando o `interface/`.

Versão: o caminho carrega `v1` e o `NinjaAPI(version=...)` versiona a doc OpenAPI por grupo
(CONVENTION §1 — toda API é versionada). Quebra de contrato = nova versão.
"""

from __future__ import annotations

import structlog
from django.http import JsonResponse
from ninja import NinjaAPI, Schema

from api.auth import JWTAuth
from users.exceptions import DomainError

logger = structlog.get_logger()

API_VERSION = "1.0"


class WhoamiOut(Schema):
    external_id: str
    roles: list[str]
    name: str | None = None  # do Profile — o front saúda pelo nome


def build_group(name: str, description: str) -> NinjaAPI:
    """Cria o `NinjaAPI` de um público: versionado, auth JWT default, com health + whoami."""
    api = NinjaAPI(
        version=API_VERSION,
        urls_namespace=f"api-{name}",
        title=f"API {name}",
        description=description,
        auth=JWTAuth(),
    )

    @api.exception_handler(DomainError)
    def domain_error(request, exc: DomainError):
        """Erro de DOMÍNIO → JSON padronizado `{detail, code, …extra}` no status do erro. Ex.: etapa
        errada do funil → **409** + `expected_status` (o front roteia o wizard sozinho com isso)."""
        return JsonResponse(
            {"detail": exc.detail, "code": exc.code, **exc.extra}, status=exc.status
        )

    @api.exception_handler(Exception)
    def unhandled_error(request, exc: Exception):
        """Erro NÃO tratado → SEMPRE JSON `{detail}` 500 — nunca traceback/URLconf em HTML, nem com
        DEBUG ligado (auditoria do front 2026-06-10). O traceback completo vai pro log do server."""
        logger.exception("api.unhandled_error", group=name, path=request.path)
        return JsonResponse({"detail": "Erro interno do servidor."}, status=500)

    @api.get("/health", auth=None, tags=["health"])
    def health(request):
        """Liveness público do grupo (sem auth)."""
        return {"group": name, "version": API_VERSION, "status": "ok"}

    @api.get("/whoami", response=WhoamiOut, tags=["auth"])
    def whoami(request):
        """Eco do principal autenticado + `name` do Profile — o front saúda pelo nome (exige Bearer)."""
        from users.models import Profile

        principal = request.auth
        profile = (
            Profile.objects.filter(user__external_id=principal.external_id)
            .only("name")
            .first()
        )
        return {
            "external_id": principal.external_id,
            "roles": principal.roles,
            "name": profile.name if profile else None,
        }

    return api
