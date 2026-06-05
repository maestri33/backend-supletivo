"""Config do lead — preço da matrícula por gateway + descrição (lido do `.env`, CONVENTION §10).

DEV (Victor 2026-06-04): **Cartão R$1** / **PIX R$5** (mínimo do Asaas). PROD = pedir ao Victor (§8).
Valores em REAIS (Decimal); o InfinitePay converte pra centavos internamente (×100).
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings


def _money(name: str, default: str) -> Decimal:
    return Decimal(str(getattr(settings, name, default)))


def price_card() -> Decimal:
    """Preço da matrícula no cartão (InfinitePay). DEV=1."""
    return _money("ENROLLMENT_PRICE_CARD", "1")


def price_pix() -> Decimal:
    """Preço da matrícula no PIX (Asaas). DEV=5 (mínimo do gateway)."""
    return _money("ENROLLMENT_PRICE_PIX", "5")


def description() -> str:
    """Descrição da cobrança (aparece pro pagador)."""
    return getattr(settings, "ENROLLMENT_DESCRIPTION", "Matrícula Supletivo")


def frontend_url() -> str:
    """URL do FRONT pra onde o gateway redireciona APÓS o pagamento (`.env` FRONTEND_URL).

    Vazia enquanto o front não existe — **NÃO** cai em EXTERNAL_URL: a raiz da API dá 404, e mandar
    esse redirect ao Asaas (`callback.successUrl`) faria o gateway exigir um domínio cadastrado na
    conta à toa (erro real visto 2026-06-05). Sem front → sem redirect: o Asaas não recebe `callback`
    (a cobrança PIX passa) e o InfinitePay usa o próprio fallback (`INFINITEPAY_REDIRECT_URL`/EXTERNAL_URL).
    Quando o front existir, basta setar `FRONTEND_URL` (e cadastrar o domínio no Asaas p/ o callback).
    """
    return getattr(settings, "FRONTEND_URL", "") or ""
