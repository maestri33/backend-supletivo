"""Emissão / refresh / JWKS dos JWT — RS256, config do `.env`, zero banco (porte do legado).

Claims do token: `external_id` (a identidade na borda) + `roles` (papéis ativos no momento da
emissão) + `iat`/`exp`/`type`(+`iss`/`aud`). Access e refresh têm expirações distintas (`.env`).
A view pública `/.well-known/jwks.json` publica a chave pública — os edges validam o token por ela.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import structlog
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from django.conf import settings

from users.auth.jwt import keys
from users.exceptions import ValidationError

logger = structlog.get_logger()


def _base_payload(
    claims: dict, *, minutes: int, token_type: str, with_audience: bool
) -> dict:
    now = datetime.now(tz=UTC)
    payload = {
        **claims,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "type": token_type,
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if with_audience and settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE
    return payload


def _kid() -> str:
    """Key id estável = sha256(chave pública)[:16]. Vai no header do token E no JWKS (casa os dois)."""
    return hashlib.sha256(keys.load_public().encode()).hexdigest()[:16]


def _encode(payload: dict) -> str:
    # `kid` no header → cliente JWKS (edge) acha a chave certa (RFC 7515 §4.1.4).
    return jwt.encode(
        payload,
        keys.load_private(),
        algorithm=settings.JWT_ALGORITHM,
        headers={"kid": _kid()},
    )


def issue(external_id: str, roles: list[str]) -> dict:
    """Emite o par access + refresh para `external_id` com as `roles` ativas."""
    claims = {"external_id": str(external_id), "roles": roles}
    access = _encode(
        _base_payload(
            claims,
            minutes=settings.JWT_ACCESS_EXPIRE_MINUTES,
            token_type="access",
            with_audience=True,
        )
    )
    refresh = _encode(
        _base_payload(
            claims,
            minutes=settings.JWT_REFRESH_EXPIRE_MINUTES,
            token_type="refresh",
            with_audience=False,
        )
    )
    logger.info("jwt.issued", external_id=str(external_id), roles=roles)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


def refresh(refresh_token: str) -> dict:
    """Valida um refresh token (assinatura + tipo) e reemite um par novo."""
    try:
        # Lê os claims sem verificar p/ inspecionar o tipo antes de validar a assinatura.
        unverified = jwt.decode(
            refresh_token,
            options={"verify_signature": False},
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise ValidationError(
            "Refresh token inválido.", code="REFRESH_INVALID"
        ) from None

    if unverified.get("type") != "refresh":
        raise ValidationError("Token não é do tipo refresh.", code="REFRESH_WRONG_TYPE")

    try:
        jwt.decode(
            refresh_token, keys.load_public(), algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise ValidationError(
            "Refresh token expirado.", code="REFRESH_EXPIRED"
        ) from None
    except jwt.PyJWTError:
        raise ValidationError(
            "Token não foi emitido por este servidor.", code="REFRESH_BAD_SIGNATURE"
        ) from None

    drop = {"iat", "exp", "type", "iss", "aud"}
    claims = {k: v for k, v in unverified.items() if k not in drop}
    logger.info("jwt.refreshed", external_id=claims.get("external_id"))
    return issue(claims.get("external_id", ""), claims.get("roles", []))


def decode(token: str) -> dict:
    """Decodifica e valida (assinatura+exp) um token com a chave pública. Levanta PyJWTError."""
    return jwt.decode(token, keys.load_public(), algorithms=[settings.JWT_ALGORITHM])


def _int_to_base64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return (
        base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()
    )


def get_jwks() -> dict:
    """Chave pública no formato JWKS (RFC 7517). Só RSA (RS*)."""
    if not settings.JWT_ALGORITHM.startswith("RS"):
        return {"keys": []}
    public_pem = keys.load_public()
    public_key = serialization.load_pem_public_key(
        public_pem.encode(), backend=default_backend()
    )
    numbers = public_key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _kid(),
                "n": _int_to_base64url(numbers.n),
                "e": _int_to_base64url(numbers.e),
                "alg": settings.JWT_ALGORITHM,
                "use": "sig",
            }
        ]
    }
