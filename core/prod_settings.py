"""Overlay de produção — herda core.settings.

Hoje é PROPOSITALMENTE fino: DEBUG, ALLOWED_HOSTS, DATABASE_URL, CORS e os valores de
negócio vêm todos do `.env` (CONVENTION §6/§8), então `core.settings` já serve prod como
está. STATIC_ROOT também já vem do base (settings.py) — não se redefine aqui.

Este módulo existe como o ÚNICO ponto versionado e auditável de configuração prod-only
(substitui o antigo `prod_settings.py` que vivia hand-edited, fora do git, na raiz do
deploy — fragilidade de DR: sumia num clone novo / rebuild da LXC).

ADIADO (Victor 2026-06-16: "/admin não é usado em prod agora"). Estes cookies-Secure
afetam SÓ o /admin do Django — a API pública é 100% JWT Bearer (token no header, sem
cookie de sessão), então o funil (aluno/promotor/coordenador) não depende disto.

Topologia real (2026-07-14): Cloudflare (TLS) → Caddy LXC 10.1.30.10 (manda
`X-Forwarded-Proto: https`) → nginx local 10.1.30.101:80 → Django :8000. O Caddy já
manda o proto certo; o buraco é o nginx local, que sobrescreve com `$scheme` (=http)
em vez de repassar o header do Caddy. Antes de ligar os cookies abaixo:
  1. nginx (`/etc/nginx/sites-enabled/backend.conf`): trocar
     `proxy_set_header X-Forwarded-Proto $scheme;` por `$http_x_forwarded_proto;`
  2. validar `request.is_secure()` == True
  3. SÓ ENTÃO descomentar (inverter a ordem quebra o login do /admin):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = ["https://backend.v7m.live"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # Caddy termina o TLS
"""

from core.settings import *  # noqa: F401,F403
