"""Tokens JWT da plataforma — via `django-ninja-jwt` (swap do JWT escrito à mão, Victor 2026-06-02).

Mantém o "seam" histórico (`issue`/`refresh`/`decode`) pra NÃO mexer nos chamadores (login em
`users/auth/service.py` e o `HttpBearer` em `api/auth.py`). Só as tripas trocaram: a config (RS256,
chaves de `keys/`, expirações, issuer/audience) vive em `settings.NINJA_JWT` (CONVENTION §10). Sem
consumidor externo → o JWKS foi removido (não há mais `get_jwks` nem `/.well-known/jwks.json`).

Claims no token: `external_id` (str) e `roles` (list[str]) — o gate da API lê deles, sem tocar o
banco. O ninja-jwt copia os claims custom do refresh pro access automaticamente.
"""

from __future__ import annotations

import structlog
from ninja_jwt.exceptions import (
    TokenError,
)  # re-exportado p/ o api/auth capturar sem conhecer o ninja
from ninja_jwt.tokens import AccessToken, RefreshToken

logger = structlog.get_logger()

__all__ = ["issue", "refresh", "decode", "TokenError"]


def issue(external_id: str, roles: list[str]) -> dict:
    """Emite o par access + refresh para `external_id` com as `roles` ativas (passwordless)."""
    rt = RefreshToken()
    rt["external_id"] = str(external_id)
    rt["roles"] = roles
    logger.info("jwt.issued", external_id=str(external_id), roles=roles)
    return {
        "access_token": str(
            rt.access_token
        ),  # ninja-jwt copia external_id/roles do refresh
        "refresh_token": str(rt),
        "token_type": "bearer",
    }


def refresh(refresh_token: str) -> dict:
    """Valida um refresh token e reemite um par novo (rotação). Levanta `TokenError` se inválido."""
    token = RefreshToken(refresh_token)
    external_id = token.get("external_id", "")
    roles = token.get("roles", [])
    logger.info("jwt.refreshed", external_id=external_id)
    return issue(external_id, roles)


def decode(token: str) -> dict:
    """Valida (assinatura + exp + tipo `access`) e devolve os claims. Levanta `TokenError` se inválido."""
    return dict(AccessToken(token).payload)
