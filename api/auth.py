"""Autenticador JWT compartilhado dos grupos da API Ninja (CONVENTION §1/§5).

Casca fina (§3): valida o Bearer token reusando o JWT que já roda (`users/auth/jwt`), exige
`type=access`, e devolve um `Principal` em `request.auth`. O gate de role por rota usa
`require_roles`. SEM regra de negócio aqui.

⚠️ Transição (`plan/api-ninja-transicao.md`): hoje valida o JWT custom (RS256 em `keys/`). O
swap pra `django-ninja-jwt` é ciclo supervisionado (código money-path, E2E precisa do celular
do Victor) — quando entrar, muda só o `decode` abaixo; grupos e rotas não mudam.
"""

from __future__ import annotations

import jwt as pyjwt
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
    """Valida o access token. Inválido/expirado/tipo errado → 401 (retorna None)."""

    def authenticate(self, request, token):
        try:
            payload = jwt_service.decode(token)
        except pyjwt.PyJWTError:
            return None
        if payload.get("type") != "access":
            return None
        return Principal(payload.get("external_id", ""), payload.get("roles", []))


def require_roles(principal: Principal, *roles: str) -> None:
    """Gate de role por rota: 403 se o principal não tem nenhuma das `roles`."""
    if roles and not principal.has_any(roles):
        raise HttpError(403, "Acesso negado para o seu papel.")
