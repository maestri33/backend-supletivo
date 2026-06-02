"""Fábrica dos grupos da API Ninja (CONVENTION §1).

Cada grupo é um `NinjaAPI` **versionado** (`/api/v1/<grupo>/`, montado no `core/urls.py`), com
auth JWT default e duas rotas de esqueleto: `health` (pública) e `whoami` (autenticada, prova o
JWT fim-a-fim). As rotas de negócio entram com cada role/módulo (§4), chamando o `interface/`.

Versão: o caminho carrega `v1` e o `NinjaAPI(version=...)` versiona a doc OpenAPI por grupo
(CONVENTION §1 — toda API é versionada). Quebra de contrato = nova versão.
"""

from __future__ import annotations

from ninja import NinjaAPI

from api.auth import JWTAuth

API_VERSION = "1.0"


def build_group(name: str, description: str) -> NinjaAPI:
    """Cria o `NinjaAPI` de um público: versionado, auth JWT default, com health + whoami."""
    api = NinjaAPI(
        version=API_VERSION,
        urls_namespace=f"api-{name}",
        title=f"API {name}",
        description=description,
        auth=JWTAuth(),
    )

    @api.get("/health", auth=None, tags=["health"])
    def health(request):
        """Liveness público do grupo (sem auth)."""
        return {"group": name, "version": API_VERSION, "status": "ok"}

    @api.get("/whoami", tags=["auth"])
    def whoami(request):
        """Eco do principal autenticado — prova o caminho do JWT (exige Bearer válido)."""
        principal = request.auth
        return {"external_id": principal.external_id, "roles": principal.roles}

    return api
