# api/collaborators — funil do colaborador (promotor: candidate → training → promoter)

> Grupo Django Ninja `collaborators` (`/api/v1/collaborators/`). Público: o **colaborador**, ao longo
> da vida `candidate → training → promoter`. Casca fina ([CONVENTION](../../../.claude/CONVENTION.md) §3):
> o router valida a borda + gate de role e chama o `interface/` de `candidate`/`training`/`promoter`/
> `auth` in-process. Doc OpenAPI viva: **`/api/v1/collaborators/docs`** (Swagger) e
> `/api/v1/collaborators/openapi.json`.
>
> ⚠️ **Estado real (não confiar cego — régua: o código de hoje):**
> - **Funil completo** (`/auth/*` + `/candidate/*` + `/training/*` + `/promoter/*`) → ✅ **provado real
>   fim-a-fim em 2026-06-05** (Identidade B: register→OTP no zap→login→perfil→endereço(ViaCEP)→docs→
>   Pix-DICT R$0,01 REAL→selfie(IA)→training→`ai.grade` real nota 10→entrevista(conta-mãe)→PROMOTOR).
> - **API reorganizada** (plan/15 A) → ✅ **provada in-process em 2026-06-15** (envelope/codes,
>   `/me` canônico, refresh rotação, address POST/PATCH, gates). **Ainda NÃO re-testada fim-a-fim no
>   path novo** com identidade real — re-teste agendado junto com a Fatia B (RG/CNH) e a C (selfie async).
> - **Fatia B** (doc foto+OCR RG _e_ CNH) e **Fatia C** (selfie async) do plan/15 → ⏳ a fazer; a CNH-e
>   do Victor (`/CNH Digital.pdf` na raiz do projeto) é o alvo do OCR.

---

## Como o frontend autentica

Mesmo padrão do `clients`: **passwordless por OTP no WhatsApp**. Fluxo:

1. `POST /auth/check` com `cpf` **ou** `phone` → dispara o OTP e **diz honestamente** se já existe
   cadastro (`found`) + os papéis. Decisão cadastro × login fica no front.
2. `POST /auth/login` com `external_id` + `otp` → devolve `access_token` + `refresh_token`.
3. `POST /auth/refresh` `{refresh_token}` → rotaciona (devolve novo par). Token expirado ou inválido
   → **401 SESSION_EXPIRED**.
4. Nas rotas autenticadas: `Authorization: Bearer <access_token>`.

## Auth (sub-router `/auth/*`)

| Método | Path | Body | Resposta |
|---|---|---|---|
| POST | `/auth/register` | `{cpf, phone, email, hub?}` (público) | `201 {external_id (Candidate), user_external_id, status, hub_external_id}` |
| POST | `/auth/check` | `{cpf? \| phone?}` (público, vaza) | `200 {found, external_id?, roles[]?, otp_sent, detail?}` |
| POST | `/auth/login` | `{external_id, otp}` (público) | `200 {access_token, refresh_token, …}` |
| POST | `/auth/refresh` | `{refresh_token}` (público) | `200 {access_token, refresh_token}` · inválido → 401 `SESSION_EXPIRED` |

> O `register` aceita `hub` (external_id do polo — vem do `?ref=` da landing) e cai no hub padrão se
> não vier. O `check` **vaza existência de propósito** (§5 CONVENTION: found+roles honestos, sem
> anti-enumeração).

## Funil do candidato (autenticado, role `candidate`)

`/candidate/*` é a **coleta**: o candidato vai montando `Profile → Address → Documents → Pix → Selfie`
e o backend decide a **etapa atual** (`status`) que o wizard renderiza. **Toda mutação devolve o
`me_dict` canônico** (mesmo shape do GET `/candidate/me`) → o front roteia sem re-fetch.

| Método | Path | Descrição |
|---|---|---|
| GET | `/candidate/me` | Devolve o canônico: `status` + blocos `profile/address/documents/selfie` + `missing_fields` por seção. |
| POST | `/candidate/profile` | `{marital_status?, nationality?, mother_name?, father_name?, birthplace?}` (etapa `profile`) |
| GET | `/candidate/address` | Endereço + `missing_fields` |
| POST | `/candidate/address` | `{cep}` → ViaCEP preenche; se cidade de CEP único, `missing_fields` lista o que falta |
| PATCH | `/candidate/address` | demais campos (street/number/neighborhood/city/state) — **só preenche vazios**, não sobrescreve o CEP |
| POST | `/candidate/documents` | `{doc_type, number, issuing_agency?, ...}` (etapa `documents`; `doc_type` ∈ `rg`\|`cnh`) |
| GET | `/candidate/document` | Seção rica do doc: `doc_type` + fotos + `analysis_status`/`reason` (canônico) + campos extraídos + `missing_fields` |
| PATCH | `/candidate/document` | Completa/corrige campos que o OCR não trouxe (RG ou CNH, conforme `doc_type`); aceito em qualquer etapa da coleta |
| POST | `/candidate/documents/photo/{slot}` | `slot` ∈ `rg_front`\|`rg_back`\|`rg_full`\|`cnh_front`\|`cnh_back`\|`cnh_full` (multipart) — salva foto, enfileira IA async; devolve **ack** (`{stored, analysis_status, poll_after_ms, expires_at}`) |
| POST | `/candidate/pix` | `{key, key_type}` — valida no Asaas/DICT (R$0,01 REAL; confere CPF do titular) |
| POST | `/candidate/selfie` | (multipart) — **assíncrono** (plan/15 C): salva, enfileira `validate_candidate_selfie` (Django-Q) e responde **ack** `{stored, analysis_status:"pending", poll_after_ms, expires_at}`. Aprovada→promove training; reprovada→avisa candidato; review→coord decide. |
| GET | `/candidate/selfie` | Seção rica da selfie/assinatura (plan/15 C, espelha `/enrollment/selfie`): foto + `analysis_status`/`analysis_reason` (canônico, com instruções da IA se reprovou) + `expires_at` (TTL do `pending`). Aplica TTL: pending estourado vira `review` + notifica o coord. |

> **Sub-decisão Portão 2 do plan/15:** a etapa `profile` coleta **só o que o documento não traz**
> (estado civil, nacionalidade). Filiação/naturalidade/nascimento virão da **extração do documento**
> (Fatia B). O front pode mandar esses campos no `POST /candidate/profile` mas a IA do documento é
> a fonte da verdade.

### Documento (RG **ou** CNH) — pipeline IA (plan/15 Fatia B)

O candidato escolhe **RG ou CNH** no 1º upload (`POST /candidate/documents/photo/{slot}` infere o
tipo do prefixo do slot). O `doc_type` é **imutável** depois do 1º upload (tentar enviar do outro
tipo → **422 `DOC_TYPE_LOCKED`**). Slots:

- **RG inteiro** (`rg_full`): frente+verso numa foto só (PDF de 1-2 páginas vira JPEG empilhado)
- **RG frente+verso** (`rg_front` + `rg_back`): 2 fotos separadas
- **CNH inteira** (`cnh_full`): idem
- **CNH frente+verso** (`cnh_front` + `cnh_back`): idem

A 1ª foto retorna ack `{stored, analysis_status:"pending", poll_after_ms, expires_at}`. O front
acompanha pelo `GET /candidate/document` até virar `approved`/`rejected`/`review`. TTL: pending
estourado (default 120s) → vira `review` (coordenador decide) na próxima leitura.

- `approved` → biometria do documento + extração preenche os campos (filiação/naturalidade no
  candidato, nº/órgão/etc no sub-doc RG/CNH) → wizard avança pra `PIX` automaticamente.
- `rejected` → motivo da IA no WhatsApp; candidato reenvia a foto pelo app.
- `review` → coordenador do polo decide em `POST /leadership/candidates/{ext}/document/decide`
  (`{approve: bool, reason?}`).

### Máquina de status (Candidate)

```
STARTED → PROFILE → ADDRESS → DOCUMENTS → PIX → SELFIE → COMPLETED
```

| status | O que libera |
|---|---|
| `STARTED` | acabou de registrar; primeiro POST em `/candidate/profile` |
| `PROFILE` | estado civil/nacionalidade (e filiação se já vier por aqui) |
| `ADDRESS` | CEP via ViaCEP + complemento do número/rua |
| `DOCUMENTS` | RG **ou** CNH (escolhe o tipo) + número + fotos |
| `PIX` | chave validada no Asaas/DICT (CPF confere) |
| `SELFIE` | selfie analisada por IA (liveness + face-match) — APPROVED → `COMPLETED` |
| `COMPLETED` | coleta concluída; **aguarda o COORDENADOR aprovar** → vira PROMOTOR direto (`/api/v1/leadership/candidates/{ext}/approve`). Não há mais entrevista/Trainee (Victor 2026-06-16). |

Gates: POST em etapa errada → **409 `WRONG_STATUS` + `expected_status`** (o front lê o
`expected_status` e roteia o wizard pra seção certa).

## Treinamento (autenticado, role `promoter` — a TRAVA do painel; Victor 2026-06-16)

Modelo novo: o candidato vira **promotor** quando o coordenador aprova. Se houver matéria
OBRIGATÓRIA pendente, o promotor nasce **travado** (role overlay `training`) e o front mostra só o
treino. As rotas `/training/*` são gated por role `promoter`; a trava é lida do `/promoter/me`
(`locked` + `pending_materials`). Zerou as obrigatórias → destrava (**sem OTP** — a role overlay não
dá bump de token).

| Método | Path | Descrição |
|---|---|---|
| GET | `/training/materials` | Matérias **ATRIBUÍDAS a este promotor** (fixas do onboarding + transitórias publicadas pra ele) — conteúdo (sem gabarito) + status de cada |
| GET | `/training/progress` | Status por matéria atribuída |
| POST | `/training/submissions` | `{material_external_id, answer}` — enfileira `ai.grade` async; aprovou a última obrigatória → destrava + notifica |

> Matéria não atribuída → `MATERIAL_NOT_ASSIGNED` (422). O coordenador pode aprovar matéria EM ABERTO
> de um promotor preso (`POST /leadership/promoters/{ext}/materials/{mat}/approve`). Autoria da matéria
> (com gabarito, `kind` fixa/transitória, `blocking`) é do `staff`/`leadership`.

## Promotor (autenticado, role `promoter`)

`/promoter/*` é a fase ativa: ver o próprio cadastro, leads que trouxe, comissões.

| Método | Path | Descrição |
|---|---|---|
| GET | `/promoter/me` | `{external_id, hub_external_id, status (active/suspended), ref_url, locked, pending_materials[]}` — `locked` = travado no treino (front mostra só o treino) |
| GET | `/promoter/me/leads` | Leads atribuídos a este promotor (link de pagamento + status) |
| GET | `/promoter/me/commissions` | Comissões do promotor (pagas/pendentes) |

### Promotor que quer ESTUDAR (preço próprio, sem comissão — Victor 2026-06-16)

| Método | Path | Descrição |
|---|---|---|
| GET | `/promoter/study/pricing` | Preço da auto-matrícula do promotor (preço PRÓPRIO, ≠ vitrine pública do aluno) |
| POST | `/promoter/study/start` | `{payment_method?}` — cria a auto-matrícula (preço promotor, **SEM comissão a ninguém**) + devolve o checkout. Ele paga pelo link e segue o wizard do aluno (grupo `clients`; role de aluno somada no pagamento). 2ª tentativa → `LEAD_ALREADY_EXISTS`; promotor travado no treino → bloqueado |

## Envelope de erro (codes pt-br)

Toda resposta 4xx/5xx sai como **`{detail, code, …extra}`** (handler central em `api/base.py`).
Codes do `collaborators`:

| code | status | Quando |
|---|---|---|
| `UNAUTHORIZED` | 401 | sem token / token inválido |
| `SESSION_EXPIRED` | 401 | refresh expirado/inválido |
| `FORBIDDEN_ROLE` | 403 | autenticado mas a role não bate (ex.: `coordinator` em `/candidate/me`) |
| `NOT_HUB_COORDINATOR` | 403 | coordenador não é o do polo-alvo |
| `CANDIDATE_NOT_FOUND` | 404 | candidato inexistente |
| `MATERIAL_NOT_FOUND` | 404 | matéria inexistente (training) |
| `PROMOTER_NOT_FOUND` | 404 | promotor inexistente |
| `USER_NOT_FOUND` | 404 | user inexistente (training) |
| `WRONG_STATUS` | 409 | mutação fora de etapa — `extra: {expected_status}` |
| `ALREADY_GRADING` | 409 | já existe submission em correção pra essa matéria |
| `MATERIAL_NOT_ASSIGNED` | 422 | submeter matéria que não está atribuída ao promotor |
| `INVALID_DOC_TYPE` | 422 | `doc_type` ∉ {rg, cnh} |
| `NO_HUB` | 422 | nenhum polo disponível (seed não rodou) |
| `PROFILE_CPF_MISSING` | 422 | CPF do perfil ausente (cadastro inconsistente) |
| `PIX_INVALID` | 422 | chave Pix inválida / não é do titular — `extra: {reason}` |
| `SELFIE_NOT_IN_REVIEW` | 422 | coordenador tentou decidir selfie que não está em REVIEW — `extra: {selfie_status}` |
| `MATERIAL_INACTIVE` | 422 | matéria desativada |
| `VALIDATION_ERROR` | 422 | payload do schema inválido |
| `INTERNAL` | 500 | qualquer 500 inesperado (nunca vaza traceback) |

> Codes extras compartilhados com outros grupos vivem em [[wiki/api/clients]] (mesma fábrica).

## Estado de teste

- ✅ provado real (2026-06-16): candidato→promotor pelo path antigo (CNH real + Pix-DICT + selfie +
  `ai.grade` + promoção). ⚠️ **falta E2E real** do path novo (`candidato concluído → coordenador
  aprova → promotor → treino-overlay`) com dinheiro/OTP reais, e do `promoter/study/*`.
- A inversão do treino (Victor 2026-06-16: candidato→promotor direto; treino = trava overlay por
  matérias fixa/transitória) foi provada por smoke in-process (20/20) + revisão adversarial (0 blocker).
