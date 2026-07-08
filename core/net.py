"""Helpers de rede compartilhados: IP de origem do cliente + allowlist por IP/CIDR (DMZ).

`source_ip` era TRIPLICADO em bot/views.py, integrations/bank/infinitepay/views.py e
integrations/bank/asaas/views.py — centralizado aqui (DRY), comportamento idêntico.
"""

from __future__ import annotations

import functools
import ipaddress
import types


def source_ip(request):
    """IP de origem, resolvendo X-Forwarded-For atrás do proxy (primeiro IP da lista, senão
    REMOTE_ADDR)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def ip_allowed(ip, allowlist) -> bool:
    """`ip` está em algum IP/CIDR de `allowlist`? False se `ip` ausente/inválido."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if addr in network:
            return True
    return False


def require_internal_ip(view_func):
    """Decorator de rota: 403 se `source_ip(request)` não estiver em `settings.TOOLS_ALLOWED_IPS`.

    Gate por IP (DMZ) pras rotas de negócio de `api/tools.py`, que não têm auth de usuário.

    O Ninja resolve as anotações do `view_func` original (`payload: ToolsNotifyIn` etc.) usando
    `wrapper.__globals__` (ele segue `__wrapped__` pro *signature*, mas usa os globals de quem foi
    passado pro `@api.get/post` pra resolver os forward-refs — `tools.py` usa
    `from __future__ import annotations`, então as anotações são strings). Por isso o `wrapper`
    reconstrói sua função com os globals do módulo do `view_func` (senão o Ninja não acha
    `ToolsNotifyIn` e quebra a geração do schema); os imports dentro do corpo são locais de
    propósito, pra não depender dos globals originais de `core.net` em tempo de execução.
    """

    def wrapper(request, *args, **kwargs):
        from django.conf import settings
        from ninja.errors import HttpError as _HttpError

        from core.net import ip_allowed as _ip_allowed
        from core.net import source_ip as _source_ip

        if not _ip_allowed(_source_ip(request), settings.TOOLS_ALLOWED_IPS):
            raise _HttpError(403, "IP não autorizado.")
        return view_func(request, *args, **kwargs)

    rebound = types.FunctionType(
        wrapper.__code__,
        view_func.__globals__,
        wrapper.__name__,
        wrapper.__defaults__,
        wrapper.__closure__,
    )
    functools.update_wrapper(rebound, view_func)
    return rebound
