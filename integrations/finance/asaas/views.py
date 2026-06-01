"""Views do asaas.

- `status` (DMZ, <servico>.prod): onboarding/health da integração (1a-ii). Padrão reusável p/ TODA
  integração. Zero regra de negócio de pagamento.
- `webhook` e `transfer_validation` (PÚBLICOS): o que o Asaas chama de volta (1a-iii). Auth = só o
  header `asaas-access-token` == ASAAS_WEBHOOK_SECRET no .env (sem HMAC — não existe no Asaas).
"""

import asyncio
import json
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.validation import latest_checks

from . import charge as charge_service
from . import customers
from . import transfer_validation as tv
from . import webhooks
from .client import AsaasError, get_client
from .security import check_access_token


@require_GET
def status(request):
    """Status/onboarding do asaas (JSON, só DMZ) — sequência pedida pelo Victor (specs/asaas2.md):

    1. `api_key_in_env`: ASAAS_API_KEY no .env? (senão o boot já erra vermelho — asaas.E001)
    2. `api_key_tested_ok`: a key é válida? puxa o saldo (LEITURA, zero movimento de valor)
    3. key ok e ainda sem token de webhook no .env → **gera um e retorna** (DMZ): o Victor cola o
       MESMO valor em ASAAS_WEBHOOK_SECRET no .env e no painel do Asaas (webhook + mecanismo de saque)
    4. `external_url_in_env`: EXTERNAL_URL no .env? (registrar o webhook no painel é manual por ora)
    """
    out = {
        "integration": "asaas",
        "api_key_in_env": bool(settings.ASAAS_API_KEY),
        "api_key_tested_ok": False,
        "webhook_secret_in_env": bool(settings.ASAAS_WEBHOOK_SECRET),
        "external_url_in_env": bool(settings.EXTERNAL_URL),
        "ready": False,
        "hints": [],
        # flags dos testes/validações que já rodamos (pedido do Victor: rastrear no futuro)
        "validation_checks": latest_checks("asaas"),
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

    # 3. token do webhook: o .env é a fonte de verdade (palavra do Victor).
    #    Tem no .env → use ESTE MESMO no painel. Não tem → gera e retorna pra colar nos dois lugares.
    if out["webhook_secret_in_env"]:
        out["hints"].append(
            "ASAAS_WEBHOOK_SECRET já está no .env — use ESTE MESMO valor como authToken no painel do "
            "Asaas (webhook de eventos E mecanismo de saque)."
        )
    else:
        out["generated_webhook_secret"] = secrets.token_hex(32)
        out["hints"].append(
            "Cole generated_webhook_secret em ASAAS_WEBHOOK_SECRET no .env E como authToken no painel "
            "do Asaas (o MESMO token no webhook de eventos e no mecanismo de saque)."
        )

    # 4. external_url (registrar o webhook no painel do Asaas é manual por ora — 'expandimos depois')
    if not out["external_url_in_env"]:
        out["hints"].append(
            "Defina EXTERNAL_URL no .env e registre o webhook no painel do Asaas apontando p/ "
            "EXTERNAL_URL + /integrations/asaas/webhook/."
        )

    out["ready"] = (
        out["api_key_tested_ok"]
        and out["webhook_secret_in_env"]
        and out["external_url_in_env"]
    )
    return JsonResponse(out)


@csrf_exempt
@require_POST
def webhook(request):
    """Receiver de eventos do Asaas (PÚBLICO). Auth: asaas-access-token == ASAAS_WEBHOOK_SECRET.

    Token inválido/ausente → 401. Autenticado → persiste+roteia e responde 200 (Asaas re-tenta se
    não-200; o evento bruto já fica salvo antes do roteamento).
    """
    if not check_access_token(request, settings.ASAAS_WEBHOOK_SECRET):
        return JsonResponse({"detail": "invalid_token"}, status=401)
    payload = _parse_json(request)
    webhooks.handle_event(
        payload,
        source_ip=_source_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def transfer_validation(request):
    """Mecanismo de validação de saque do Asaas (PÚBLICO). Auth: asaas-access-token == .env.

    Token inválido/ausente → 401 (Asaas cancela a saída após 3 falhas = seguro). Autenticado →
    decide APPROVED/REFUSED contra o nosso DB (hoje recusa tudo: payout 1a-v ainda não existe).
    """
    if not check_access_token(request, settings.ASAAS_WEBHOOK_SECRET):
        return JsonResponse({"detail": "invalid_token"}, status=401)
    return JsonResponse(tv.decide(_parse_json(request)))


# ── cobrança PIX (DMZ) — consumida depois por fees/enrollment via interface/ ──────────


@csrf_exempt
@require_POST
def charge(request):
    """Cria uma cobrança PIX (DMZ). Body: {amount, description?, due_date?, payment_id?,
    payer:{name, cpf, email?, phone?}}. Retorna o Payment (status PENDING) + QR."""
    data = _parse_json(request)
    payer_d = data.get("payer") or {}
    try:
        payer = customers.PayerData(
            name=payer_d.get("name") or "",
            cpf_cnpj=payer_d.get("cpf") or payer_d.get("cpf_cnpj") or "",
            email=payer_d.get("email"),
            mobile_phone=payer_d.get("phone") or payer_d.get("mobile_phone"),
        )
        row = charge_service.create_charge(
            amount=data.get("amount"),
            payer=payer,
            description=data.get("description"),
            due_date=data.get("due_date"),
            payment_id=data.get("payment_id"),
        )
    except (charge_service.ChargeError, customers.CustomerError) as e:
        return JsonResponse({"detail": str(e)}, status=400)
    return JsonResponse(charge_service.to_dict(row))


@require_GET
def charge_detail(request, payment_id):
    """Lê uma cobrança pelo payment_id (DMZ)."""
    try:
        row = charge_service.get_charge(payment_id)
    except charge_service.ChargeError as e:
        return JsonResponse({"detail": str(e)}, status=404)
    return JsonResponse(charge_service.to_dict(row))


@csrf_exempt
@require_POST
def charge_cancel(request, payment_id):
    """Cancela uma cobrança (DMZ)."""
    try:
        row = charge_service.cancel_charge(payment_id)
    except charge_service.ChargeError as e:
        return JsonResponse({"detail": str(e)}, status=404 if str(e) == "not_found" else 400)
    return JsonResponse(charge_service.to_dict(row))


@csrf_exempt
@require_POST
def charge_refund(request, payment_id):
    """Estorna uma cobrança paga (DMZ)."""
    try:
        row = charge_service.refund_charge(payment_id)
    except charge_service.ChargeError as e:
        return JsonResponse({"detail": str(e)}, status=404 if str(e) == "not_found" else 400)
    return JsonResponse(charge_service.to_dict(row))


def _parse_json(request):
    """Corpo JSON do request como dict (ou {} se vazio/malformado)."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _source_ip(request):
    """IP de origem, resolvendo X-Forwarded-For atrás do proxy."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


async def _get_balance():
    async with get_client() as c:
        return await c.get_balance()
