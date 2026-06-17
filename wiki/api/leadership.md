# api/leadership — fluxo do coordenador do polo

> Grupo Django Ninja `leadership` (`/api/v1/leadership/`). Público: o **coordenador** de um polo
> (role `coordinator`; gate por `coordinated_by` — o hub que o user coordena, não "qualquer hub").
> Casca fina ([CONVENTION](../../../.claude/CONVENTION.md) §3) → chama `interface/` de `lead`/
> `enrollment`/`student`/`candidate`/`training`/`finance`. Doc OpenAPI viva: **`/api/v1/
> leadership/docs`** e `/api/v1/leadership/openapi.json`.
>
> ⚠️ **Esta wiki cobre o grupo inteiro do `leadership`**, mas no **escopo do plan/15** o que
> **entregou agora** foi a parte do **colaborador** (decide de candidato+treinando+materiais — ver
> §3 abaixo; **plan/15 Fatia B**: `/candidates/{ext}/document/decide` pro RG/CNH em REVIEW). A
> parte do **aluno** (RG/selfie/fee/conclude/exam/grade — plan/12/13/14) está implementada mas foi
> escrita antes e fica como **black box** aqui; o Portão 3 com o Victor é que sincroniza a wiki
> detalhada dela.

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
| GET | `/reviews` | **6 filas de análise numa chamada só** — RG/selfie de matrícula, **documento + selfie de candidato**, docs de student, candidatos aguardando aprovação. **Resiliência (2026-06-17):** ao montar, varre `pending` que estourou o TTL (worker da IA morto) → `review`, pra não sumir da vista de ninguém |
| GET | `/training/materials` | Lista de matérias **com gabarito** (visão de autoria) |

> O escopo do polo é resolvido por `coordinator.hub_coordinated` (o hub que o user coordena). Não
> há fallback de "qualquer hub" — se não é o coordenador do hub-alvo, não vê.

---

## 3. Decisões do coordenador (escopo do **colaborador** — plan/15 A6)

Estas são as rotas que o plan/15 A6 saneou (codes pt-br + envelope via `DomainError`/`TrainingError`/
`CandidateError` borbulhando; antes estavam achatadas em `ERROR`).

### 3.1. Colaborador — aprovar candidato → PROMOTOR + treino (Victor 2026-06-16)

A entrevista/Trainee SAIU: o coordenador aprova o candidato (que concluiu a coleta) e ele vira
**PROMOTOR direto**. O treino virou trava pós-promotor por matérias (fixa/transitória).

| Método | Path | Descrição |
|---|---|---|
| GET  | `/candidates` | Fila de candidatos do polo que concluíram a coleta e aguardam aprovação |
| GET  | `/candidates/{external_id}` | Detalhe (perfil + coleta) pro coord decidir **vendo** antes de aprovar |
| POST | `/candidates/{external_id}/approve` | Aprova → promove a **PROMOTOR** + atribui as matérias FIXAS (treino-overlay; nasce travado se houver obrigatória) |
| POST | `/candidates/{external_id}/reject` | `{reason}` — rejeita o candidato aguardando aprovação |
| POST | `/promoters/{external_id}/materials/{material_external_id}/approve` | Aprova matéria EM ABERTO de um promotor preso (destrava quem não tem prática digital) |
| GET/POST/PUT | `/training/materials[/{external_id}]` | Autoria de matéria (com gabarito) — o coord também autora; modelo `kind`/`blocking`/`ephemeral` em [[wiki/api/staff]] |

Codes: `CANDIDATE_NOT_FOUND` (404), `PROMOTER_NOT_FOUND` (404), `MATERIAL_NOT_FOUND` (404),
`MATERIAL_NOT_ASSIGNED` (422), `NOT_HUB_COORDINATOR` (403), `WRONG_STATUS` (409, candidato não está
aguardando aprovação — `extra: {expected_status}`).

### 3.2. Candidato (candidate)

| Método | Path | Descrição |
|---|---|---|
| GET  | `/candidates/{external_id}/selfie` | **Tela de detalhe (plan/15 D2):** foto + `analysis_status`/`analysis_reason` (motivo da IA). O coord decide **vendo**, não às cegas (antes decidia só com o nome na fila). `in_review: true` = tá na fila de decisão. |
| POST | `/candidates/{external_id}/selfie/decide` | `{approve: bool, reason?}` — decide selfie em REVIEW (sim/não) |
| POST | `/candidates/{external_id}/document/decide` | `{approve: bool, reason?}` — decide RG/CNH em REVIEW (sim/não FINAL; plan/15 B3). Aprovou → biometria + extração best-effort preenche os campos; reprovou → candidato é avisado pra reenviar. |
| POST | `/candidates/{external_id}/document/reset` | **Resgate (2026-06-17):** zera o `doc_type` do candidato que fixou o tipo errado (escolheu RG, só tem CNH) e volta pra `documents`. Perfil/endereço/pix **intactos**. Sem isso, a única saída era recomeçar tudo. |

Codes: `CANDIDATE_NOT_FOUND` (404), `NOT_HUB_COORDINATOR` (403), `SELFIE_NOT_IN_REVIEW` (422,
`extra: {selfie_status}`), `DOC_NOT_IN_REVIEW` (422, `extra: {validation_status}`), `DOC_TYPE_NOT_SET`
(422), `WRONG_STATUS` (409).

### 3.3. Destravar + agir-no-lugar (WP5, Victor 2026-06-16)

Poderes de "destravar": reativar promotor suspenso, ver o aluno por inteiro, e **agir no lugar** de um
cliente sem prática digital (postar documento/endereço/selfie por ele, auditado).

| Método | Path | Descrição |
|---|---|---|
| GET  | `/promoters` | Promotores do polo (status active/suspended + se travados no treino) |
| POST | `/promoters/{external_id}/suspend` | Suspende o promotor (não capta nem recebe) |
| POST | `/promoters/{external_id}/reactivate` | Reativa um promotor suspenso (volta a captar) |
| GET  | `/students/{external_id}` | Detalhe RICO do aluno (docs/pendências/diploma/plataforma/identidade) |
| POST | `/enrollments/{external_id}/address` | `{cep}` — **age-no-lugar**: posta o endereço (ViaCEP) pelo cliente |
| POST | `/enrollments/{external_id}/documents/rg/photo/{slot}` | foto do RG (`front`\|`back`\|`full`) pelo cliente — IA valida igual |
| POST | `/enrollments/{external_id}/selfie` | selfie (assinatura) pelo cliente — IA + biometria validam (review → `/selfie/decide`) |
| PATCH | `/enrollments/{external_id}/profile` | **corrige identidade do OCR torta** (`mother_name`/`father_name`/`marital_status`/`nationality`/`birthplace`). **NÃO** mexe em `name`/`birth_date` (CPFHub manda) nem `pix`. Sem isso, dado errado ficava gravado pra sempre. |

> "Agir-no-lugar" = mesmas funções do wizard do aluno, mas o coordenador posta POR ele (gate: coordenar
> o hub da matrícula; `acted_by` logado). Se a IA cair em revisão, cai nos `/decide` que já existem.

---

## Codes do `leadership` (subset do envelope central)

| code | status | Quando |
|---|---|---|
| `UNAUTHORIZED` | 401 | sem token |
| `SESSION_EXPIRED` | 401 | refresh expirado/inválido |
| `FORBIDDEN_ROLE` | 403 | não-coordenador tentando rota de coord |
| `NOT_HUB_COORDINATOR` | 403 | coord mas de outro polo |
| `hub_not_found` | 404 | hub-alvo inexistente |
| `<recurso>_NOT_FOUND` | 404 | por recurso (LEAD/ENROLLMENT/CANDIDATE/STUDENT/PROMOTER/MATERIAL/USER) |
| `WRONG_STATUS` | 409 | mutação fora de etapa — `extra: {expected_status}` |
| `SELFIE_NOT_IN_REVIEW` | 422 | selfie não está em REVIEW (decide) |
| `MATERIAL_INACTIVE` | 422 | matéria desativada (submit) |
| `NO_HUB` | 422 | seed não criou polo |
| `VALIDATION_ERROR` | 422 | payload do schema inválido |
| `INTERNAL` | 500 | qualquer 500 inesperado |

> A tabela completa (compartilhada com `clients`/`collaborators`/`staff`) está em
> `api/base.py` (handler central) — esta página lista só os codes **específicos** do `leadership`.

---

## O que esta wiki ainda **NÃO cobre** (detalhe fica pro Portão 3)

> Já documentado acima (WP5, Victor 2026-06-16): seção 3.3 — destravar/agir-no-lugar, reativar
> promotor, detalhe do aluno.

- **`/enrollment/*` decide** — `decide_rg`, `decide_selfie`, `decide_document` (do aluno),
  `decide_exam`, `decide_pendency`. Implementado em plan/12/13/14. **Wiki detalhada sincroniza no
  Portão 3 com o Victor** (o teste real do student→veteran já provou esses decides fim-a-fim em
  2026-06-06).
- **`/fee/pay` + `/fee/schedule` + `/conclude`** — plan/14 (taxa 2 parcelas + virada enrollment→student
  atômica). **Wiki detalhada sincroniza no Portão 3 com o Victor** (Portão 3 com dinheiro real ainda
  pendente).
- **`/students/{ext}/documents/{doc_ext}/decide`** — decide de documento do student (plan/9 A1).

> Regra: tudo que não está listado acima, mas a rota existe, foi escrito por outros planos
> (plan/9/12/13/14) e está funcional. A wiki do `clients` (`api/clients.md`) e o relatório
> `tests/14-fluxo-coordenador.md` cobrem o que está provado real; o que falta é a wiki de quem
> escreve o quê (decidir COM o Victor ao Portão 3).
