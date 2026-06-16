"""Overlay de produção — herda core.settings.

Hoje é PROPOSITALMENTE fino: DEBUG, ALLOWED_HOSTS, DATABASE_URL, CORS e os valores de
negócio vêm todos do `.env` (CONVENTION §6/§8), então `core.settings` já serve prod como
está. STATIC_ROOT também já vem do base (settings.py) — não se redefine aqui.

Este módulo existe como o ÚNICO ponto versionado e auditável de configuração prod-only
(substitui o antigo `prod_settings.py` que vivia hand-edited, fora do git, na raiz do
deploy — fragilidade de DR: sumia num clone novo / rebuild da LXC).

ADIADO (Victor 2026-06-16: "/admin não é usado em prod agora") — quando o /admin sobre
HTTPS entrar em uso, ligar AQUI, e só DEPOIS de o nginx repassar o X-Forwarded-Proto real
(hoje ele sobrescreve com $scheme=http, então is_secure() é False e cookie-secure quebraria
o login):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = ["https://backend.v7m.live"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # Caddy/nginx já terminam o TLS
"""

from core.settings import *  # noqa: F401,F403
