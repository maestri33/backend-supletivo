# api/staff — administração da plataforma

Grupo Django Ninja do **boss** (`/api/v1/staff/`). Todas as rotas exigem **superuser** (staff =
superuser nativo do Django — Victor 2026-06-03), via `require_superuser` (`api/auth.py`), que confere
a flag `is_superuser` no banco — o JWT só carrega `roles`. Casca fina (CONVENTION §3) → chama
`hub/interface` e `users/roles`; zero regra de negócio no router.

## Rotas (autenticadas + superuser)
- `POST /hubs` `{brand, coordinator_external_id?}` → cria um polo (nasce com endereço vazio).
- `GET  /hubs` → lista todos os polos.
- `GET  /promoters` → lista os promotores (pra escolher coordenador).
- `PUT  /hubs/{external_id}/coordinator` `{coordinator_external_id}` → designa/troca o coordenador.
- `PUT  /hubs/{external_id}/default` → marca o polo PADRÃO (fallback de captação; único).
- `PATCH /hubs/{external_id}/address` `{cep, number?, complement?}` → preenche o endereço do polo (ViaCEP; CEP inexistente → 422 `CEP_NOT_FOUND`).

Respostas de erro: **401** (sem token), **403** (não-superuser), **422** (marca inválida /
coordenador não-promotor / CEP inexistente), **404** (polo inexistente). Doc OpenAPI viva em `/api/v1/staff/docs`.

## Visão global (todos os polos) + usuários
- `GET /enrollments?hub=&status=` → matrículas de TODOS os polos.
- `GET /students?hub=&status=` → alunos de TODOS os polos.
- `GET /leads?hub=&status=` → leads de TODOS (já existia).
- `GET /users?role=&limit=` → usuários + roles ativas (read-only). **MUTAÇÃO de role pelo staff =
  «PENDÊNCIA» do Victor** ("dentro do cabível").

> O domínio (entidade, seed, regras de negócio) está em [[wiki/hub/hub]].

## Autoria de matéria do treino (plan/15 A7)

`MaterialIn`/`MaterialUpdateIn` viraram **schemas compartilhados** (`api/schemas.py`) — staff e
leadership importam do mesmo lugar (defs locais removidas).

| Método | Path | Descrição |
|---|---|---|
| POST | `/training/materials` | Cria matéria (`{title, question, expected_answer, text_content?, content_blocks?, kind?, blocking?, ephemeral?, video?, photo?, order?}`). `kind`=**fixed** (todo promotor novo recebe) \| **transitory** (publicar p/ existentes); `blocking`=obrigatória (trava o painel); `content_blocks`=conteúdo rico (texto/imagem/vídeo/arquivo) |
| PUT  | `/training/materials/{external_id}` | Edita campos enviados; `active=False` desativa |
| GET  | `/training/materials` | Lista TODAS (com gabarito — visão de autoria) |
| POST | `/training/materials/{external_id}/publish` | Publica TRANSITÓRIA → atribui aos promotores JÁ existentes + re-trava + notifica |
| DELETE | `/training/materials/{external_id}` | Descarta matéria **EFÊMERA** (não-efêmera → use `active=False`; senão `MATERIAL_NOT_EPHEMERAL`) |

> Modelo novo (Victor 2026-06-16): o treino virou **trava pós-promotor** por matérias (não há mais
> entrevista). O staff é o dono das matérias; o **coordenador** também autora (`/api/v1/leadership/
> training/materials`) e aprova matéria em aberto; o **promotor em treino** vê só as ATRIBUÍDAS a ele
> em `/api/v1/collaborators/training/materials` (gated por role `promoter`; a trava é lida do `/me`).
> Codes: `MATERIAL_NOT_FOUND` (404), `MATERIAL_NOT_EPHEMERAL`/`MATERIAL_NOT_TRANSITORY` (422).

## Leads (staff vê TODOS)

| Método | Path | Descrição |
|---|---|---|
| GET | `/leads?hub=&status=` | Lista TODOS os leads (link de pagamento + recibo). Filtros por `hub` (external_id) e `status`. |

- 401 sem token · 403 não-superuser · 404 `hub_not_found` (hub passado mas inexistente — não
  cai silenciosamente em "todos").

## Financeiro (WP6)

| Método | Path | Descrição |
|---|---|---|
| GET | `/finance/balance` | Saldo da conta Asaas (read-only; erro de rede → `{error}` estruturado, nunca 500) |
| GET | `/finance/summary` | Resumo por status (contagem + total R$) de comissões e da fila de saída |
| GET | `/finance/commissions?status=` | Comissões (pending/processed/paid/failed) |
| GET | `/finance/payouts?status=&kind=` | Fila de saída (PaymentRequest); `kind`=commission\|fee |

> Leitura via `finance/interface` (ORM read-only) + `asaas.onboarding.account_balance`. **NÃO move dinheiro.**

## Integrações — status/config/fluxo + ações (WP6)

8 serviços: asaas · infinitepay · whatsapp · mail · ai · biometric · cep · cpf.

| Método | Path | Descrição |
|---|---|---|
| GET  | `/integrations` | Lista TODAS: `{name, configured, config (bool por env), flow, checks}` — **nunca o valor do secret**, só se a env está presente |
| GET  | `/integrations/{name}` | Detalhe; **asaas** faz `run_checks` AO VIVO (saldo + webhook) |
| POST | `/integrations/{name}/setup` | Onboarding (asaas: auto-cadastra o webhook). Idempotente |
| POST | `/integrations/{name}/test` | Teste de saúde (asaas: bateria real → ledger; demais: último do ledger) |

> Registry em `integrations/status.py`. 404 `integration_not_found`. O health ao vivo dos serviços
> não-asaas roda pelos commands de `manage.py` (assíncrono/pesado) — o GET reporta o último resultado
> do ledger `ValidationCheck`.

## Status do servidor (WP6)

| Método | Path | Descrição |
|---|---|---|
| GET | `/system` | `{db_ok, migrations_pending[], qcluster_alive, qcluster_count, queued_tasks, debug, external_url}` |

## Logs / ledgers (WP6)

| Método | Path | Descrição |
|---|---|---|
| GET | `/logs/unrouted?resolved=&limit=` | Eventos que chegaram sem consumidor (fallback do core) — sem o payload bruto |
| GET | `/logs/ai-calls?status=&limit=` | Chamadas de IA (provider/modelo/operação/custo/erro/latência) |
| GET | `/logs/checks?scope=&limit=` | Histórico do ledger de validação (`ValidationCheck`) |

> **Feito** (WP6-D): endereço do polo, polo padrão, views globais de enrollment/student, leitura de
> usuários. **Falta só**: a MUTAÇÃO de role pelo staff (regra do Victor: "dentro do cabível").
