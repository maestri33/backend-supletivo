"""Auth do webhook inbound do WhatsApp (Evolution) — espelha o `asaas/security.py`.

Mecanismo: header-token. A Evolution NÃO assina HMAC os webhooks (ela manda o payload cru pro
endpoint configurado), então autenticamos por um segredo compartilhado: um header que só nós e a
Evolution conhecemos, comparado em tempo constante. Fonte de verdade = `WHATSAPP_WEBHOOK_SECRET`
no `.env`. Sem o segredo configurado, `check_access_token` retorna False (fail-closed: o webhook
dá 401 e nada é processado).
"""

import hmac

# Header onde o segredo compartilhado viaja. A Evolution permite configurar headers customizados
# no webhook (Webhook > Headers); o owner cola WHATSAPP_WEBHOOK_SECRET aqui.
ACCESS_TOKEN_HEADER = "x-webhook-token"


def check_access_token(request, expected: str) -> bool:
    """True se o header `x-webhook-token` bate com o segredo esperado (comparação tempo-constante).

    `expected` vazio (segredo não configurado no .env) => False: fail-closed, o webhook 401a e nada
    é processado. Espelha exatamente o `asaas.security.check_access_token`.
    """
    if not expected:
        return False
    got = request.headers.get(ACCESS_TOKEN_HEADER, "")
    return hmac.compare_digest(got, expected)
