"""Prova de vida (liveness) — stub local.

Hoje é um stub local que sempre passa (`{"passed": True, "provider": "local"}`). O funil chama
`check_liveness()` e só olha o `passed`. Quando entrar um provider real (FaceTec/Unico/CAF), a
decisão de COMO validar mora aqui.
"""

from __future__ import annotations


def check_liveness(*, image_path: str | None = None) -> dict:
    """Veredito de prova de vida. Hoje: stub local (passa sempre).

    Retorno: `{"passed": bool, "provider": str}` — o funil só precisa do `passed`.
    """
    return {"passed": True, "provider": "local"}
