"""Superfície pública in-process do `auth` (CONVENTION §3): o que as views DMZ (e futuros apps) chamam.

Fina de propósito — reexporta a lógica do `service`. A view (`users/auth/views.py`) embrulha isto em
HTTP; o edge FastAPI (depois) chama a view por HTTP. A lógica não sai do Django (modelo B, §1).
"""

from users.auth.service import change_phone, check, login, recover, register

__all__ = ["register", "check", "recover", "login", "change_phone"]
