"""Views DMZ do asaas (internas — <servico>.prod; segurança é na borda da rede, CONVENTION §5).

1a-ii: endpoint de status/onboarding da integração. É o **padrão reusável p/ TODA integração**:
retorna JSON com flags de config, testa a key (leitura) e gera o webhook-secret pra colar no
painel do Asaas. Zero regra de negócio de pagamento aqui.
"""

import asyncio
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .client import AsaasError, get_client


@require_GET
def status(request):
    """Status/onboarding do asaas (JSON, só DMZ) — sequência pedida pelo Victor (specs/asaas2.md):

    1. `api_key_in_env`: ASAAS_API_KEY no .env? (senão o boot já erra vermelho — asaas.E001)
    2. `api_key_tested_ok`: a key é válida? puxa o saldo (LEITURA, zero movimento de valor)
    3. key ok e ainda sem webhook-secret no .env → **gera um e retorna** (DMZ): o Victor cola no
       painel do Asaas e em ASAAS_WEBHOOK_SECRET no .env
    4. `external_url_in_env`: EXTERNAL_URL no .env? (true por ora; configurar o webhook é 1a-iii)
    """
    out = {
        "integration": "asaas",
        "api_key_in_env": bool(settings.ASAAS_API_KEY),
        "api_key_tested_ok": False,
        "webhook_secret_in_env": bool(settings.ASAAS_WEBHOOK_SECRET),
        "external_url_in_env": bool(settings.EXTERNAL_URL),
        "ready": False,
        "hints": [],
    }

    if not out["api_key_in_env"]:
        out["hints"].append(
            "Cole ASAAS_API_KEY no .env (sem ela o boot erra: asaas.E001)."
        )
        return JsonResponse(out)

    # 2. valida a key puxando o saldo (leitura pura, nenhum valor movimentado)
    try:
        balance = asyncio.run(_get_balance())
        out["api_key_tested_ok"] = True
        out["balance"] = balance.get("balance")
    except AsaasError as e:
        out["error"] = {"status_code": e.status_code, "body": e.body}
        out["hints"].append(
            "A key não validou no Asaas (ver error). Confira ASAAS_API_KEY."
        )
        return JsonResponse(out)

    # 3. key ok e sem secret no .env → gera e retorna pra colar (painel Asaas + .env)
    if not out["webhook_secret_in_env"]:
        out["generated_webhook_secret"] = secrets.token_hex(32)
        out["hints"].append(
            "Cole generated_webhook_secret no painel do Asaas E em ASAAS_WEBHOOK_SECRET no .env."
        )

    # 4. external_url (configurar o webhook de fato é 1a-iii)
    if not out["external_url_in_env"]:
        out["hints"].append(
            "Defina EXTERNAL_URL no .env p/ configurar o webhook (1a-iii)."
        )

    out["ready"] = (
        out["api_key_tested_ok"]
        and out["webhook_secret_in_env"]
        and out["external_url_in_env"]
    )
    return JsonResponse(out)


async def _get_balance():
    async with get_client() as c:
        return await c.get_balance()
