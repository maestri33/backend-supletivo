"""Auth dos endpoints que o Asaas chama de volta (webhook de eventos + validação de saque).

Mecanismo REAL do Asaas (doc oficial): header `asaas-access-token` = um authToken definido no
painel e ecoado em toda chamada. NÃO existe HMAC `asaas-signature` (era delírio do legado). Um
token só pros dois endpoints: `ASAAS_WEBHOOK_SECRET` no `.env` (fonte de verdade).
"""

import hmac

ACCESS_TOKEN_HEADER = "asaas-access-token"


def check_access_token(request, expected):
    """True se o header asaas-access-token bate com o token esperado (comparação tempo-constante)."""
    if not expected:
        return False
    got = request.headers.get(ACCESS_TOKEN_HEADER, "")
    return hmac.compare_digest(got, expected)
