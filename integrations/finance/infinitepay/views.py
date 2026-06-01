"""Views do infinitepay.

- `status` (DMZ, <servico>.prod): onboarding/health da integração, mesmo padrão do asaas
  (specs/asaas2.md). Zero regra de negócio.
- `checkout`/`checkout_detail` (DMZ): cria/lê link de pagamento. Consumido depois por lead/enrollment
  via a interface/ do infinitepay (quando esses apps existirem).
- `webhook` (PÚBLICO): o que a InfinitePay chama de volta. Sem auth de header (a doc oficial não tem);
  a trava é o `order_nsu` opaco + a reconfirmação via payment_check dentro do handle_event.
"""

import json

import structlog
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.validation import latest_checks

from . import checkout as checkout_service
from . import webhooks

logger = structlog.get_logger()


@require_GET
def status(request):
    """Status/onboarding do infinitepay (JSON, só DMZ) — padrão reusável das integrações.

    1. `handle_in_env`: INFINITEPAY_HANDLE no .env? (senão o boot já erra — infinitepay.E001)
    2. `external_url_in_env`: EXTERNAL_URL no .env? (o webhook_url do checkout aponta pra ela)
    Não há "testar o handle" barato sem criar um link real, então `handle_tested_ok` reflete o último
    teste E2E carimbado (`record_check("infinitepay","checkout_e2e",...)`).
    """
    checks = latest_checks("infinitepay")
    out = {
        "integration": "infinitepay",
        "handle_in_env": bool(settings.INFINITEPAY_HANDLE),
        "base_url": settings.INFINITEPAY_BASE_URL,
        "external_url_in_env": bool(settings.EXTERNAL_URL),
        "handle_tested_ok": bool(checks.get("checkout_e2e", {}).get("passed")),
        "ready": False,
        "hints": [],
        "validation_checks": checks,
    }
    if not out["handle_in_env"]:
        out["hints"].append(
            "Cole INFINITEPAY_HANDLE no .env (a InfinitePay autentica só pelo handle; sem ele: "
            "infinitepay.E001)."
        )
    if not out["external_url_in_env"]:
        out["hints"].append(
            "Defina EXTERNAL_URL no .env — o webhook_url do checkout aponta pra EXTERNAL_URL + "
            "/integrations/infinitepay/webhook/."
        )
    out["ready"] = out["handle_in_env"] and out["external_url_in_env"]
    return JsonResponse(out)


@csrf_exempt
@require_POST
def checkout(request):
    """Cria um link de checkout (DMZ). Body: {amount_cents|amount, description, customer?, redirect_url?}.
    Retorna o Checkout (status PENDING) + checkout_url."""
    data = _parse_json(request)
    try:
        row = checkout_service.create_checkout(
            amount_cents=data.get("amount_cents"),
            amount=data.get("amount"),
            description=data.get("description"),
            customer=data.get("customer"),
            redirect_url=data.get("redirect_url"),
        )
    except checkout_service.CheckoutError as e:
        return JsonResponse({"detail": str(e)}, status=400)
    return JsonResponse(checkout_service.to_dict(row))


@require_GET
def checkout_detail(request, external_id):
    """Lê um checkout pelo external_id (DMZ)."""
    try:
        row = checkout_service.get_checkout(external_id)
    except checkout_service.CheckoutError as e:
        return JsonResponse({"detail": str(e)}, status=404)
    return JsonResponse(checkout_service.to_dict(row))


@csrf_exempt
@require_POST
def webhook(request):
    """Receiver de eventos da InfinitePay (PÚBLICO). Sem auth de header (a doc não tem).

    O `order_nsu` (UUID opaco) chega na query; o pagamento é reconfirmado via payment_check antes de
    marcar pago. Responde sempre 200 (a InfinitePay re-tenta se não-200; o evento bruto já fica salvo).
    """
    order_nsu = request.GET.get("order_nsu")
    payload = _parse_json(request)
    _, result = webhooks.handle_event(
        order_nsu,
        payload,
        source_ip=_source_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return JsonResponse(result)


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
