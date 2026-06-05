"""Views do asaas.

- `status` (DMZ, <servico>.prod): onboarding/health da integração (1a-ii). Padrão reusável p/ TODA
  integração. Zero regra de negócio de pagamento.
- `webhook` e `transfer_validation` (PÚBLICOS): o que o Asaas chama de volta (1a-iii). Auth = só o
  header `asaas-access-token` == ASAAS_WEBHOOK_SECRET no .env (sem HMAC — não existe no Asaas).
"""

import json
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.validation import latest_checks

from . import charge as charge_service
from . import customers
from . import onboarding
from . import payout as payout_service
from . import transfer_validation as tv
from . import url_verify
from . import webhooks
from .security import check_access_token


@require_GET
def status(request):
    """Status read-only do asaas (JSON, só DMZ). Roda a bateria de prontidão SEM mutar o Asaas:
    flags de env + testa a key via saldo (leitura) + diz se o nosso webhook já está cadastrado.

    O auto-cadastro do webhook é efeito colateral -> fica no POST /setup/ (não num GET). Sem o
    ASAAS_WEBHOOK_SECRET no .env, sugere um valor (gera) pra você colar.
    """
    out = onboarding.run_checks()
    out["validation_checks"] = latest_checks("asaas")
    if out["api_key_in_env"] and not out["webhook_secret_in_env"]:
        out["generated_webhook_secret"] = secrets.token_hex(32)
        out["hints"].append(
            "Cole generated_webhook_secret em ASAAS_WEBHOOK_SECRET no .env (o MESMO valor que o "
            "auto-cadastro usa como authToken)."
        )
    return JsonResponse(out)


@csrf_exempt
@require_POST
def setup(request):
    """Roda a bateria + ping REAL da EXTERNAL_URL + AUTO-CADASTRA o webhook no Asaas (DMZ).

    É o "endpoint pra repetir" os testes. `?force=1` deleta+recria o webhook (resync do authToken).
    Efeito colateral no Asaas -> por isso é POST, não GET.
    """
    force = request.GET.get("force") in ("1", "true", "yes")
    out = onboarding.setup(force=force)
    out["validation_checks"] = latest_checks("asaas")
    return JsonResponse(out)


@require_GET
def url_verify_echo(request, nonce):
    """Echo PÚBLICO do ping de verificação de URL: consome o nonce single-use e responde 200.

    Auth = o próprio nonce secreto single-use + TTL (CONVENTION §5 público). Que o nonce seja
    consumido prova que a chamada à EXTERNAL_URL chegou NESTE backend.
    """
    ok, reason = url_verify.consume_nonce(nonce)
    return JsonResponse({"ok": ok, "reason": reason}, status=200 if ok else 404)


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
        return JsonResponse(
            {"detail": str(e)}, status=404 if str(e) == "not_found" else 400
        )
    return JsonResponse(charge_service.to_dict(row))


@csrf_exempt
@require_POST
def charge_refund(request, payment_id):
    """Estorna uma cobrança paga (DMZ)."""
    try:
        row = charge_service.refund_charge(payment_id)
    except charge_service.ChargeError as e:
        return JsonResponse(
            {"detail": str(e)}, status=404 if str(e) == "not_found" else 400
        )
    return JsonResponse(charge_service.to_dict(row))


# ── payout PIX (saída, DMZ) — 1a-vi ───────────────────────────────────────────────────


@csrf_exempt
@require_POST
def payout(request):
    """Cria um payout PIX (DMZ). Body: {amount, pix_key (ou cpf), description?, payment_id?}.

    Status segue o webhook (TRANSFER_DONE -> PAID). Idempotente por payment_id (não reenvia)."""
    data = _parse_json(request)
    try:
        row = payout_service.create_payout(
            amount=data.get("amount"),
            pix_key=data.get("pix_key") or data.get("cpf"),
            description=data.get("description"),
            payment_id=data.get("payment_id"),
        )
    except payout_service.PayoutError as e:
        return JsonResponse({"detail": str(e)}, status=400)
    return JsonResponse(payout_service.to_dict(row))


@require_GET
def payout_detail(request, payment_id):
    """Lê um payout pelo payment_id (DMZ)."""
    try:
        row = payout_service.get_payout(payment_id)
    except payout_service.PayoutError as e:
        return JsonResponse({"detail": str(e)}, status=404)
    return JsonResponse(payout_service.to_dict(row))


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
