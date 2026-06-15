# api/leadership — fluxo do coordenador do polo

> Grupo Django Ninja `leadership` (`/api/v1/leadership/`). Público: o **coordenador** de um polo
> (role `coordinator`; gate por `coordinated_by` — o hub que o user coordena, não "qualquer hub").
> Casca fina ([CONVENTION](../../../.claude/CONVENTION.md) §3) → chama `interface/` de `lead`/
> `enrollment`/`student`/`candidate`/`training`/`finance`. Doc OpenAPI viva: **`/api/v1/
> leadership/docs`** e `/api/v1/leadership/openapi.json`.
>
> ⚠️ **Esta wiki cobre o grupo inteiro do `leadership`**, mas no **escopo do plan/15** o que
> **entregou agora** foi só a parte do **colaborador** (decide de candidato+treinando+materiais —
> ver §3 abaixo). A parte do **aluno** (RG/selfie/fee/conclude/exam/grade — plan/12/13/14) está
> implementada mas foi escrita antes e fica como **black box** aqui; o Portão 3 com o Victor é que
> sincroniza a wiki detalhada dela.

---

## Auth (sub-router `/auth/*`)

Mesmo padrão do `clients`/`collaborators`. **Não há registro** — só staff cria polo/coordenador
(`/api/v1/staff/hubs`). O coordenador entra via `/auth/check` + `/auth/login` (OTP no WhatsApp
dele); se não for coordenador, o `check` devolve a resposta normal + `detail` de redirecionamento
pra área da role dele (front leva o `external_id`).

| Método | Path | Body | Resposta |
|---|---|---|---|
| POST | `/auth/check` | `{cpf? \| phone?}` (público) | `200 {found, external_id?, is_coordinator, hub_external_id?, roles[], detail?}` |
| POST | `/auth/login` | `{external_id, otp}` (público) | `200 {access_token, refresh_token, is_coordinator, hub_external_id?, …}` |
| POST | `/auth/refresh` | `{refresh_token}` (público) | `200 {access_token, refresh_token}` · inválido → 401 `SESSION_EXPIRED` |

Gate de role: o login só dá tokens com a role `coordinator` ativa; coordenar outro hub →
**403 `NOT_HUB_COORDINATOR`**.

## Visão do polo (escopo do polo = `coordinated_by`)

| Método | Path | Descrição |
|---|---|---|
| GET | `/leads` | Leads do polo (link de pagamento + recibo). Filtro `status`. |
| GET | `/leads/{external_id}` | Detalhe do lead (cpf/email/checkout — "coord vê tudo") |
| GET | `/enrollments` | Matrículas do polo (filtro `status`) |
| GET | `/enrollments/{external_id}` | Detalhe da matrícula (visão rica do /me do aluno + fees) |
| GET | `/reviews` | **5 filas de análise numa chamada só** — RG/selfie de matrícula, selfie de candidato, docs de student, entrevistas |
| GET | `/training/materials` | Lista de matérias **com gabarito** (visão de autoria) |

> O escopo do polo é resolvido por `coordinator.hub_coordinated` (o hub que o user coordena). Não
> há fallback de "qualquer hub" — se não é o coordenador do hub-alvo, não vê.

---

## 3. Decisões do coordenador (escopo do **colaborador** — plan/15 A6)

Estas são as rotas que o plan/15 A6 saneou (codes pt-br + envelope via `DomainError`/`TrainingError`/
`CandidateError` borbulhando; antes estavam achatadas em `ERROR`).

### 3.1. Treinamento (training)

| Método | Path | Descrição |
|---|---|---|
| POST | `/training/materials` | Cria matéria (texto+questão+gabarito+ordem) — autoria do coord |
| PUT  | `/training/materials/{external_id}` | Edita campos enviados; `active=False` desativa |
| POST | `/trainees/{external_id}/approve` | Aprova entrevista → promove `training → promoter` + cria `Promoter` no hub herdado |
| POST | `/trainees/{external_id}/reject` | Rejeita entrevista (registra motivo) |

Codes: `MATERIAL_NOT_FOUND` (404), `USER_NOT_FOUND` (404), `MATERIAL_INACTIVE` (422),
`ALREADY_GRADING` (409), `TRAINEE_NOT_FOUND` (404), `NO_HUB` (422), `NOT_HUB_COORDINATOR` (403),
`WRONG_STATUS` (409, entrevista já decidida).

### 3.2. Candidato (candidate)

| Método | Path | Descrição |
|---|---|---|
| POST | `/candidates/{external_id}/selfie/decide` | `{approve: bool, reason?}` — decide selfie em REVIEW (sim/não) |
| POST | `/candidates/{external_id}/document/decide` | *(Fatia B — ainda a fazer)* decide doc em REVIEW (sim/não) |

Codes: `CANDIDATE_NOT_FOUND` (404), `NOT_HUB_COORDINATOR` (403), `SELFIE_NOT_IN_REVIEW` (422,
`extra: {selfie_status}`), `WRONG_STATUS` (409).

---

## Codes do `leadership` (subset do envelope central)

| code | status | Quando |
|---|---|---|
| `UNAUTHORIZED` | 401 | sem token |
| `SESSION_EXPIRED` | 401 | refresh expirado/inválido |
| `FORBIDDEN_ROLE` | 403 | não-coordenador tentando rota de coord |
| `NOT_HUB_COORDINATOR` | 403 | coord mas de outro polo |
| `hub_not_found` | 404 | hub-alvo inexistente |
| `<recurso>_NOT_FOUND` | 404 | por recurso (LEAD/ENROLLMENT/CANDIDATE/TRAINEE/MATERIAL/USER) |
| `WRONG_STATUS` | 409 | mutação fora de etapa — `extra: {expected_status}` |
| `SELFIE_NOT_IN_REVIEW` | 422 | selfie não está em REVIEW (decide) |
| `MATERIAL_INACTIVE` | 422 | matéria desativada (submit) |
| `NO_HUB` | 422 | seed não criou polo |
| `VALIDATION_ERROR` | 422 | payload do schema inválido |
| `INTERNAL` | 500 | qualquer 500 inesperado |

> A tabela completa (compartilhada com `clients`/`collaborators`/`staff`) está em
> `api/base.py` (handler central) — esta página lista só os codes **específicos** do `leadership`.

---

## O que esta wiki ainda **NÃO cobre** (black box, plano futuro)

- **`/enrollment/*` decide** — `decide_rg`, `decide_selfie`, `decide_document`, `decide_candidate_selfie`
  (do aluno), `decide_exam`, `decide_pendency`. Implementado em plan/12/13/14. **Wiki detalhada
  sincroniza no Portão 3 com o Victor** (o teste real do student→veteran já provou esses decides
  fim-a-fim em 2026-06-06).
- **`/fee/pay` + `/fee/schedule` + `/conclude`** — plan/14 (taxa 2 parcelas + virada enrollment→student
  atômica). **Wiki detalhada sincroniza no Portão 3 com o Victor** (Portão 3 com dinheiro real ainda
  pendente).
- **`/students/{ext}/documents/{doc_ext}/decide`** — decide de documento do student (plan/9 A1).

> Regra: tudo que não está listado acima, mas a rota existe, foi escrito por outros planos
> (plan/9/12/13/14) e está funcional. A wiki do `clients` (`api/clients.md`) e o relatório
> `tests/14-fluxo-coordenador.md` cobrem o que está provado real; o que falta é a wiki de quem
> escreve o quê (decidir COM o Victor ao Portão 3).
