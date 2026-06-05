"""Prova de vida (liveness) — SEAM plugável.

Hoje é um stub local que sempre passa (`{"passed": True, "provider": "local"}`). A arquitetura existe
pra trocar o provider por FaceTec/Unico/CAF **sem mexer no negócio**: o funil chama `check_liveness()`
e só olha o `passed` — quem decide COMO é este módulo. Quando entrar um provider real, é só implementar
um novo `LivenessProvider` e apontar `BIOMETRIC_LIVENESS_PROVIDER` (config) pra ele.
"""

from __future__ import annotations

from django.conf import settings


def check_liveness(*, image_path: str | None = None) -> dict:
    """Veredito de prova de vida. Hoje: stub local (passa). Futuro: FaceTec/Unico/CAF pelo mesmo contrato.

    Retorno: `{"passed": bool, "provider": str}` — o funil só precisa do `passed`.
    """
    provider = getattr(settings, "BIOMETRIC_LIVENESS_PROVIDER", "local")
    if provider == "local":
        return {"passed": True, "provider": "local"}
    # Providers externos entram aqui (FaceTec/Unico/CAF) — ainda não implementados; cai no stub seguro.
    return {"passed": True, "provider": provider, "stub": True}
