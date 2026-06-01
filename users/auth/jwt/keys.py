"""Par de chaves RSA pra assinatura dos JWT (porte do legado `key_service`+`_ensure_keys`).

Gera um par RSA 2048 (privada PKCS8 PEM, pública SPKI PEM, sem criptografia — ambiente DMZ
controlado) no 1º uso, se os arquivos não existirem, nos paths do `.env`
(`JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, sob `keys/` gitignored). A privada NUNCA vai pro git.
Chaves carregadas uma vez e cacheadas em memória.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings

logger = structlog.get_logger()

_private_pem: str | None = None
_public_pem: str | None = None


def _generate_rsa_key_pair(key_size: int = 2048) -> tuple[str, str]:
    """Gera (privada_pem PKCS8, pública_pem SPKI). 2048 = mínimo NIST p/ tokens curtos."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def ensure_keys() -> None:
    """Gera o par se faltar. Idempotente — só cria quando ambos os arquivos não existem."""
    priv_path = Path(settings.JWT_PRIVATE_KEY_PATH)
    pub_path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if priv_path.exists() and pub_path.exists():
        return
    priv_path.parent.mkdir(parents=True, exist_ok=True)
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    priv_pem, pub_pem = _generate_rsa_key_pair()
    priv_path.write_text(priv_pem)
    pub_path.write_text(pub_pem)
    # Permissão restrita na privada (best-effort; em alguns FS não aplica).
    try:
        priv_path.chmod(0o600)
    except OSError:
        pass
    logger.info("jwt.keys_generated", priv=str(priv_path), pub=str(pub_path))


def load_private() -> str:
    global _private_pem
    if _private_pem is None:
        ensure_keys()
        _private_pem = Path(settings.JWT_PRIVATE_KEY_PATH).read_text()
    return _private_pem


def load_public() -> str:
    global _public_pem
    if _public_pem is None:
        ensure_keys()
        _public_pem = Path(settings.JWT_PUBLIC_KEY_PATH).read_text()
    return _public_pem
