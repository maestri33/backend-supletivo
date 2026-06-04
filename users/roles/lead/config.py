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
