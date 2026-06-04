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
