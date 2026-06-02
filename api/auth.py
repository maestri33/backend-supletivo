"""Autenticador JWT compartilhado dos grupos da API Ninja (CONVENTION §1/§5).

Casca fina (§3): valida o Bearer token reusando o JWT que já roda (`users/auth/jwt`), exige
`type=access`, e devolve um `Principal` em `request.auth`. O gate de role por rota usa
`require_roles`. SEM regra de negócio aqui.

Valida via `users/auth/jwt/service` (django-ninja-jwt, RS256, chaves em `keys/`). Mudança
2026-06-02 (Victor): o swap pro ninja-jwt foi feito; grupos e rotas não mudaram (trocou só as
tripas do `decode`/`issue`). O `AccessToken` do ninja-jwt já rejeita token expirado/refresh/inválido.
"""

from __future__ import annotations

import structlog
from ninja.errors import HttpError
from ninja.security import HttpBearer

from users.auth.jwt import service as jwt_service

logger = structlog.get_logger()


class Principal:
    """Quem está autenticado, derivado dos claims do token (sem tocar o banco no gate)."""

    def __init__(self, external_id: str, roles: list[str]) -> None:
        self.external_id = external_id
        self.roles = roles

    def has_any(self, roles: tuple[str, ...]) -> bool:
        return any(r in self.roles for r in roles)


class JWTAuth(HttpBearer):
    """Valida o access token (assinatura+exp+tipo, via ninja-jwt). Inválido → 401 (retorna None)."""

    def authenticate(self, request, token):
        try:
            payload = jwt_service.decode(token)
        except jwt_service.TokenError:
            return None
        return Principal(payload.get("external_id", ""), payload.get("roles", []))


def require_roles(principal: Principal, *roles: str) -> None:
    """Gate de role por rota: 403 se o principal não tem nenhuma das `roles`."""
    if roles and not principal.has_any(roles):
        raise HttpError(403, "Acesso negado para o seu papel.")
