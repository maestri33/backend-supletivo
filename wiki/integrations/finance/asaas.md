# asaas — integrations/finance/asaas

> ⚠️ **ESTADO: NÃO APROVADO formalmente** (Victor não deu "SIM" no Portão 3). Feito e testado:
> a **fundação (1a-i)** + o **endpoint de status/onboarding (1a-ii)**. Ainda faltam: configurar
> o webhook, webhook receiver, charge, payout e o **E2E 1-centavo** (ver "O que NÃO foi feito").
> Doc honesto de propósito — **não tratar como "asaas pronto".**

App Django que porta o gateway de pagamento **Asaas** do micro legado (`~/coders/backend/asaas`,
FastAPI) pro monólito. Caminho do MVP §4 item 1-a. Label do app: `asaas`
(`integrations.finance.asaas`).

## O que FOI feito e testado (1a-i — fundação) ✅

- **App + data layer:** 6 models portados (`Customer`, `PixKey`, `Payment`, `WebhookEvent`,
  `OutboundJob`, `UrlVerifyNonce`) + `migrations/0001_initial.py` aplicada (`migrate` OK).
- **Client HTTP** (`client.py`): porte ~1:1 do `asaas_client.py` legado (httpx async, métodos
  mapeiam 1:1 a API v3, levanta `AsaasError` em não-2xx). `get_client()` monta o client lendo
  key/base_url do `.env`.
- **Boot red-check** (`checks.py` + `apps.py`): sem `ASAAS_API_KEY` no `.env`, o system check
  `asaas.E001` **erra em vermelho e — por escolha do Victor — TRAVA todo `manage.py`** (mono,
  1 banco: ninguém migra sem a key).
- **`django-q2`** instalado (fila async, broker no banco, sem Redis) — `Q_CLUSTER` no settings.
  Ainda **sem nenhuma tarefa** (qcluster só faz sentido no payout, 1a-v).
- **Teste real (leitura pura):** `get_client().get_balance()` → `{'balance': 102.51}`. Conta
  real dedicada a testes, pouco dinheiro. **Zero movimento de valor.** Print em
  `.claude/tests/1a-i-asaas-fundacao.md`.

## O que FOI feito e testado (1a-ii — endpoint de status/onboarding) ✅

- **View DMZ** `GET /integrations/asaas/status/` (`views.py`, JSON) — é o **padrão reusável p/
  TODA integração**. Testada de verdade (print em `.claude/tests/1a-i-asaas-fundacao.md`):
  flags `api_key_in_env` / `api_key_tested_ok` (puxa o saldo real) / `webhook_secret_in_env` /
  `external_url_in_env` / `ready` + `hints`.
- Key ok e sem webhook-secret no `.env` → **gera `generated_webhook_secret` e retorna no JSON
  (só DMZ)** — Victor cola no painel do Asaas e em `ASAAS_WEBHOOK_SECRET`.
- `.env`: adicionados `ASAAS_WEBHOOK_SECRET` e `EXTERNAL_URL` (vazios).

## O que NÃO foi feito nem testado ❌ (pedidos do Victor — ver `.claude/specs/asaas2.md`)

O endpoint de status (1a-ii) **já existe**. Ainda faltam:

- ❌ **Configurar o webhook de fato** no Asaas a partir do `EXTERNAL_URL` (o status só sinaliza a
  flag; registrar o webhook no Asaas é 1a-iii).
- ❌ **Webhook receiver** (HMAC `asaas-signature` + CIDR) e os `hooks/` de destino.
- ❌ **Charge** (PIX inbound) e **payout** (PIX-out/transfer + fila drenando).
- ❌ **Teste E2E de 1 centavo** (CPF=chave PIX → R$0,01 → webhook valida → prova secret+HMAC).
- ❌ Fallback hook-logger no `core`.

Tudo isso é o **fatiamento 1a-ii…1a-v** (ver `.claude/plan/1a-i-asaas-fundacao.md` §1 e a
memória do projeto). **Não testado de forma alguma.**

## Decisões / desvios do legado (feitos por CONVENTION, registrados)

- `Payment` → `Customer`/`PixKey` viraram **FK real** (CONVENTION §4: referência interna é FK,
  não `external_id`-cola como no micro).
- `external_id` = **UUID de borda** (§4/§6); `Payment` mantém `payment_id` como ref pública.
- `Payment.amount` = **Decimal** (dinheiro nunca é float, §8).
- `raw_dict`/`payload` = **JSONField** (idiomático Django).

## Gotchas achados na fundação (já corrigidos)

- **`httpx`** não estava nas deps → adicionado (`uv add httpx`).
- **django-environ trata `$` como proxy de variável** e a api-key do Asaas começa com `$aact_…`
  → `env('ASAAS_API_KEY')` quebrava o settings. A key é lida via `os.environ` (literal),
  centralizado no `settings.py`.

## Config (`.env`)

- `ASAAS_API_KEY` — api-key (`$aact_prod_…`), colada à mão, gitignored. Sem ela: `asaas.E001`.
- `ASAAS_BASE_URL` — `https://api.asaas.com` (prod) / `https://api-sandbox.asaas.com` (sandbox).
- *(1a-ii+ vão precisar de `ASAAS_SECURITY_TOKEN`, `ASAAS_WEBHOOK_SECRET`, `EXTERNAL_URL` — ainda
  não usados.)*

## Próximo

`1a-iii` — receber o webhook do Asaas (HMAC `asaas-signature` + CIDR) e configurar o webhook a
partir do `EXTERNAL_URL`; depois charge (1a-iv) e payout + E2E 1-centavo (1a-v). Ver
`specs/asaas2.md` (palavra do dono) e `plan/1a-i-asaas-fundacao.md`.
