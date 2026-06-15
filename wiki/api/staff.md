# api/staff — administração da plataforma

Grupo Django Ninja do **boss** (`/api/v1/staff/`). Todas as rotas exigem **superuser** (staff =
superuser nativo do Django — Victor 2026-06-03), via `require_superuser` (`api/auth.py`), que confere
a flag `is_superuser` no banco — o JWT só carrega `roles`. Casca fina (CONVENTION §3) → chama
`hub/interface` e `users/roles`; zero regra de negócio no router.

## Rotas (autenticadas + superuser)
- `POST /hubs` `{brand, coordinator_external_id?}` → cria um polo.
- `GET  /hubs` → lista todos os polos.
- `GET  /promoters` → lista os promotores (pra escolher coordenador).
- `PUT  /hubs/{external_id}/coordinator` `{coordinator_external_id}` → designa/troca o coordenador.

Respostas de erro: **401** (sem token), **403** (não-superuser), **422** (marca inválida /
coordenador não-promotor), **404** (polo inexistente). Doc OpenAPI viva em `/api/v1/staff/docs`.

> O domínio (entidade, seed, regras de negócio) está em [[wiki/hub/hub]].

## Autoria de matéria do treino (plan/15 A7)

`MaterialIn`/`MaterialUpdateIn` viraram **schemas compartilhados** (`api/schemas.py`) — staff e
leadership importam do mesmo lugar (defs locais removidas).

| Método | Path | Descrição |
|---|---|---|
| POST | `/training/materials` | Cria matéria (`{title, text_content, question, expected_answer, order?}`) |
| PUT  | `/training/materials/{external_id}` | Edita campos enviados; `active=False` desativa |
| GET  | `/training/materials` | Lista TODAS (com gabarito — visão de autoria) |

> O **coordenador** tem a mesma lista com gabarito em `/api/v1/leadership/training/materials`;
> o **treinando** tem a versão sem gabarito (só `active=true`) em
> `/api/v1/collaborators/training/materials`. Codes: `MATERIAL_NOT_FOUND` (404),
> `WRONG_STATUS` (409), `VALIDATION_ERROR` (422).

## Leads (staff vê TODOS)

| Método | Path | Descrição |
|---|---|---|
| GET | `/leads?hub=&status=` | Lista TODOS os leads (link de pagamento + recibo). Filtros por `hub` (external_id) e `status`. |

- 401 sem token · 403 não-superuser · 404 `hub_not_found` (hub passado mas inexistente — não
  cai silenciosamente em "todos").
