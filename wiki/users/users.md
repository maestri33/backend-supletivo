# users — identidade, papéis e dados pessoais (§4 item 3)

> O "quem" da plataforma. Um **app Django** com sub-módulos (pacotes): `auth/` (+ `jwt/`, `otp/`),
> `profiles/`, `roles/`. `documents/` e `address/` ficam pra ciclos futuros.
> Fonte de verdade da identidade (VISAO). Modelo B (CONVENTION §1): a lógica vive no Django; os
> edges FastAPI (depois) chamam as **views DMZ** por HTTP.

## Decisões que mandam aqui
- **Custom `AUTH_USER_MODEL = users.User`** (Victor 2026-06-01) — o `User` carrega o `external_id`
  (UUID na borda) e é âncora pura de identidade. `USERNAME_FIELD = external_id`; admin loga por UUID.
- **Login passwordless por OTP** — `User` nasce com `set_unusable_password()`; OTP **é** o login.
- **Unicidade absoluta** de `cpf`/`phone`/`email` (spec auth) — no `Profile`, com `unique` + formato
  + **veracidade real** (CPFHub + WhatsApp).
- **`external_id` só na borda**; dentro é **FK de verdade** (roles/otp → `User`).

## Models (app_label `users`, um migration set)
- **`User`** (`auth/models.py`): `external_id` (UUID unique), flags admin, senha (inutilizável p/ user normal).
- **`Profile`** (`profiles/models.py`): 1-1 `User` — `cpf`(11,unique), `phone`(13,unique, formato
  `55`+DDD+`9`+8), `email`(unique,null), `gender`(M/F — vem do CPFHub).
- **`UserRole`** (`roles/models.py`): FK `User`, `role`, `assigned_at`, `revoked_at` (ativa = nulo;
  histórico nas revogadas).
- **`OtpCode`** + **`OtpRateLimit`** (`auth/otp/models.py`): auditoria (hash SHA256, nunca plaintext)
  + rate-limit em DB (sem Redis).

## auth — endpoints DMZ (`/users/auth/…`)
- `POST register/` `{role, phone, cpf}` → valida entry-role + formato + **CPFHub** (identidade real)
  + **WhatsApp `check_numbers`** (número real) → transação atômica `User`+`Profile`+role inicial →
  dispara OTP → `{external_id}`.
- `POST check/` `{cpf|phone|external_id}` → acha + dispara OTP. Resposta com `found`/`external_id`;
  não-encontrado = jitter + shape de sucesso (anti-enumeração). Rate-limit forte de IP fica no edge (§5).
- `POST recover/` `{cpf|phone}` → OTP no canal conhecido; **nunca** devolve `external_id`.
- `POST login/` `{external_id, role, otp}` → confere role ativa → valida OTP → **JWT** com as roles ativas.

## jwt (`auth/jwt/`)
RS256. Par de chaves PEM gerado no 1º boot em `keys/` (**gitignored**, privada nunca commitada).
`issue` (access 30min + refresh 1440min, claims `external_id`+`roles`, header com `kid`), `refresh`,
`get_jwks`. View pública **`GET /.well-known/jwks.json`** (RFC 7517) — os edges validam o token por ela.

## otp (`auth/otp/`)
Código 6 díg, hash SHA256, TTL 300s, máx 3 tentativas, rate-limit 30s + 5/h (DB). Enviado por
**WhatsApp via `notify`** (despachante puro; o `phone` vem do Profile). Template em `otp.md` (pt-br).

## roles (`roles/`)
Catálogo de transições no **`.env`** (`ROLE_RULES`, §9), validado no boot (`catalog.py`). Cadeias:
`lead→enrollment→student` (+`veteran` aditivo) e `candidate→training→promoter` (+`coordinator` aditivo).
`assign` (entrada, `from_role=None`), `promote` (replace = digivolução: revoga a anterior), `active_roles`.

## Config (`.env`)
`JWT_*` (paths das chaves, alg, expirações, issuer), `OTP_*` (dígitos, TTL, tentativas, rate-limit),
`ROLE_RULES` (JSON). Defaults = porte do legado.

## Reusa (sem duplicar)
[[wiki/integrations/tools/cpf]] (CPFHub) · [[wiki/integrations/communication/whatsapp]] (check + envio)
· [[wiki/notify/notify]] (despacho do OTP).

## Rabo pra trás (specs novas)
- `specs/log_otp_mask.md` — o código do OTP aparece no `text_preview` do log do cliente WhatsApp.
- `documents`/`address` (sub-módulos do `users`) e `profiles` completo (Pix/Asaas) = ciclos futuros.

## Teste real
`.claude/tests/3-users-auth-jwt-otp-roles.md` — register (CPFHub+WhatsApp) → OTP no zap → login →
JWT validado pelo JWKS → unicidade 409 → promote com histórico. Tudo REAL.
