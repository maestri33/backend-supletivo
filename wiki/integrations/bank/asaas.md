# asaas — integrations/bank/asaas

> **ESTADO:** fundação (1a-i) + status/onboarding (1a-ii) + **webhook receiver, validação de saque e
> fallback logger (1a-iii)** — feitos e testados. **1a-iii aprovado no Portão 3** (Victor 2026-05-31);
> 1a-i/1a-ii ficaram com aprovação formal "pra depois" (palavra dele), mas estão feitos e testados.
> + **charge (1a-iv)** — aprovado com **E2E real** (pagamento real → webhook → PAID). Falta **payout
> + E2E de saída (1a-v)**. Doc honesto — **não é "asaas pronto".**

App Django que porta o gateway de pagamento **Asaas** do micro legado (`~/coders/backend/asaas`,
FastAPI) pro monólito. Caminho do MVP §4 item 1-a. Label do app: `asaas`.

## ⚠️ Anti-delírio (importante)

O legado validava o webhook com **HMAC `asaas-signature`**. A **doc oficial do Asaas** (Context7
`/llmstxt/asaas_llms_txt`) mostra que **esse header não existe** — era delírio de IA. A auth real de
**tudo que o Asaas chama de volta** é **só o header `asaas-access-token`** (um authToken definido no
painel, ecoado em toda chamada). Asaas recomenda também filtrar por IP oficial — **dispensado agora**
pelo Victor (só o token). Ver `.claude/plan/1a-iii-asaas-webhook.md §0`.

## 1a-i — fundação ✅ (testado; Portão 3 formal "depois")

- **Data layer:** 6 models (`Customer`, `PixKey`, `Payment`, `WebhookEvent`, `OutboundJob`,
  `UrlVerifyNonce`) + migração aplicada.
- **Client HTTP** (`client.py`): porte ~1:1 do legado (httpx async, API v3, `AsaasError`).
- **Boot red-check** (`checks.py`): sem `ASAAS_API_KEY` → `asaas.E001` (Error) **trava** `manage.py`.
- **`django-q2`** instalado (fila no banco, sem Redis) — sem tarefa ainda (payout é 1a-v).
- **Teste real (leitura):** `get_balance()` → `{'balance': 102.51}`. Zero movimento de valor.

## 1a-ii — status/onboarding (DMZ) ✅ (testado; Portão 3 formal "depois")

- **View DMZ** `GET /integrations/asaas/status/` (JSON) — **padrão reusável p/ TODA integração**.
  Flags `api_key_in_env` / `api_key_tested_ok` (puxa saldo real) / `webhook_secret_in_env` /
  `external_url_in_env` / `ready` + `hints`.
- Key ok e sem token de webhook no `.env` → **gera `generated_webhook_secret` e retorna (DMZ)**.

## 1a-iii — webhook receiver + validação de saque + fallback ✅ (Portão 3 aprovado)

Tudo que o **Asaas chama de volta**. Auth = só `asaas-access-token` == `ASAAS_WEBHOOK_SECRET` no
`.env` (**um token só** pros dois endpoints — palavra do Victor; o `.env` é a fonte de verdade).

- **`POST /integrations/asaas/webhook/` (público)** — receiver de eventos (`webhooks.py`). Persiste o
  `WebhookEvent` bruto → mapeia `PAYMENT_*`/`TRANSFER_*` pra `Payment.status` (mapas portados do
  legado) → o que não casa com nada nosso vai pro **fallback logger do core**. Responde sempre **200**
  quando autenticado (Asaas re-tenta em não-200); **401** sem token.
- **`POST /integrations/asaas/transfer-validation/` (público)** — mecanismo de validação de saque
  (`transfer_validation.py`). Asaas chama ~5s após cada saída pedindo `APPROVED`/`REFUSED`. Aprova
  **só** saída que nós iniciamos e bate com o DB; como payout (1a-v) ainda não existe, **recusa tudo**
  — lado seguro do dinheiro. 3 falhas → Asaas cancela. Toda decisão é logada (structlog).
- **`security.py`** — `check_access_token()` (comparação tempo-constante).
- **system check `asaas.W001` (Warning):** sem `ASAAS_WEBHOOK_SECRET` os webhooks dão 401 → avisa
  recorrente no boot, **não trava** `manage.py` (diferente do E001 da api-key).
- **Fallback logger no core:** ver [[../../../core/fallback|core/fallback]].
- **Teste real** (curl em runserver local): 401 sem token, 200 + `UnroutedEvent` quando nada casa,
  saque REFUSED, `/status/` ready+saldo. Print em `.claude/tests/1a-iii-asaas-webhook.md`.

### Registrar o webhook no Asaas (manual, por ora)

No painel do Asaas: webhook de eventos apontando p/ `EXTERNAL_URL` + `/integrations/asaas/webhook/`,
authToken = o valor de `ASAAS_WEBHOOK_SECRET`. O mecanismo de saque (Menu > Integrações > Mecanismos
de Segurança) usa o **mesmo** token; **só habilitar quando 1a-v existir** (senão barra toda saída via
API). Auto-registro via API do Asaas = **deferido** ("expandimos depois", `asaas2.md`).

## 1a-iv — charge (cobrança PIX inbound) ✅ (Portão 3 aprovado, E2E real)

Cria cobrança PIX e recebe o pagamento. `charge.py` (create/get/cancel/refund), `customers.py`
(find-or-create por **CPF**), `qr.py` (PNG do Asaas no `/media/`). Endpoints **DMZ**:
`POST /integrations/asaas/charge/` + `GET`/`cancel`/`refund` em `charge/<payment_id>/...`.

- **Criar:** find-or-create customer → `POST /v3/payments` (billingType PIX) → `GET .../pixQrCode`
  (copia-e-cola + PNG base64) → grava o PNG em `/media/qrcodes/<pid>.png` → persiste
  `Payment(kind=charge, PENDING)`. `externalReference = payment_id` (idempotência). **Sem migração**
  (os campos de charge já existem desde 1a-i).
- **Webhook registrado via API** (`POST /v3/webhooks`, `sendType=SEQUENTIALLY`, `authToken` = nosso
  `ASAAS_WEBHOOK_SECRET`, 13 eventos) apontando pro nosso `/webhook/`. O legado `asaas-app-managed`
  (`api.v7m.org`) está caindo **502** — a desabilitar.
- **E2E REAL:** cobrança de **R$5,00** (mínimo do Asaas) paga pelo Victor → Asaas (`ip 54.94.183.101`)
  entregou `PAYMENT_RECEIVED` no `/webhook/` → status virou **PAID sozinho**. Print em
  `.claude/tests/1a-iv-asaas-charge.md`.
- **Gotchas:** (1) `EXTERNAL_URL` no `.env` **não pode ter comentário inline** (django-environ
  engole). (2) **Registrar o webhook é pré-requisito** — pagar antes do webhook existir = evento
  perdido (reconciliamos por `GET /payments`). (3) `/media/` ligado (settings + `core/urls` em DEBUG;
  em prod é a infra). Pillow instalado (o Asaas já manda o PNG pronto; fica disponível).

## Decisões / desvios do legado (por CONVENTION)

- `Payment` → `Customer`/`PixKey` = **FK real** (§4). `external_id` = UUID de borda; `Payment` usa
  `payment_id` como ref pública. `amount` = **Decimal** (§8). `payload`/`raw_dict` = **JSONField**.

## Gotchas (corrigidos)

- **`httpx`** faltava nas deps → `uv add httpx` (1a-i).
- **django-environ trata `$` como proxy** e a api-key começa com `$aact_…` → lida via `os.environ`
  (literal), centralizado no `settings.py` (1a-i).
- **structlog usa `event` como 1º argumento posicional** → kwarg `event=` colidia → renomeado p/
  `asaas_event=` em `fallback.py`/`webhooks.py` (1a-iii).

## Config (`.env`)

- `ASAAS_API_KEY` — api-key (`$aact_…`), à mão, gitignored. Sem ela: `asaas.E001`.
- `ASAAS_BASE_URL` — `https://api.asaas.com` (prod) / `https://api-sandbox.asaas.com` (sandbox).
- `ASAAS_WEBHOOK_SECRET` — **um token só** p/ os webhooks (`asaas-access-token`). Sem ele: `asaas.W001`.
- `EXTERNAL_URL` — base pública p/ montar a URL do webhook no painel.

## Próximo

`1a-v` — **payout** (PIX-out/transfer) + fila (Django-Q) + mecanismo de saque (APPROVED/REFUSED) ao
vivo + **E2E de saída**. Régua: `.claude/specs/asaas2.md`.
