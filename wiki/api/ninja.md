# api/ — API pública Django Ninja (in-process)

> **Estado: rotas de negócio JÁ escritas** nos 4 grupos (lead/enrollment/student ·
> candidate/training/promoter · coordenador · staff). O que cada grupo expõe está na **sua
> própria página**: [[wiki/api/clients]] · [[wiki/api/staff]] · (collaborators e leadership: a
> documentar). **O estado de TESTE varia por rota** (provado real vs casca não-exercida) — ver a
> página de cada grupo. Régua: [[CONVENTION]] §1/§3/§5.

A API pública do MVP **vive dentro do monólito Django**, via **Django Ninja** (in-process —
sem serviço separado, sem hop HTTP). Decisão do Victor 2026-06-01 (FastAPI/edges descartados).
O router é casca fina: recebe a request (auth + gate de role + validação de borda) → chama o
`interface/` do módulo **no mesmo processo** → devolve. **Zero regra de negócio no router.**

## Os 4 grupos (por público)

Cada grupo é um `NinjaAPI` próprio, montado em [core/urls.py](../../core/urls.py) sob
`/api/v1/<grupo>/`:

| Grupo | Público | Funil / papel |
|---|---|---|
| `clients` | aluno (**$$ ENTRA**) | lead → enrollment → student → veteran |
| `collaborators` | promotor | candidate → training → promoter |
| `leadership` | coordenador do polo | centraliza no `hub/` |
| `staff` | administração ("boss") | cadastra hub, define coordenador, vê saúde |

> ⚠️ **Os nomes dos 4 grupos são PLACEHOLDER** — o Victor não bateu o martelo neles
> («PENDÊNCIA», decidir depois). O que vale é a **lógica** (qual público cada um serve),
> não o nome. Trocar o nome = trocar a string em `api/<grupo>.py` + `core/urls.py`.

## Estrutura

- [api/base.py](../../api/base.py) — `build_group(name, description)`: fábrica do `NinjaAPI`
  versionado, com auth JWT default e as 2 rotas de esqueleto. Toda a config comum mora aqui
  (um lugar só, não repete por grupo).
- [api/auth.py](../../api/auth.py) — autenticação compartilhada:
  - `JWTAuth(HttpBearer)` — valida o Bearer **reusando o JWT que já roda** (`users/auth/jwt`,
    `django-ninja-jwt`, RS256, chaves em `keys/`). Exige `type=access`. Token inválido/
    expirado/refresh → **401**.
  - `Principal` — quem está autenticado, derivado dos **claims** do token (`external_id` +
    `roles`). O gate **não toca o banco** (lê do token).
  - `require_roles(principal, *roles)` — gate de papel por rota: **403** se o principal não
    tem nenhum dos papéis exigidos.
- `api/clients.py` · `api/collaborators.py` · `api/leadership.py` · `api/staff.py` — cada um
  chama `build_group(...)` e declara as **rotas de negócio** do seu público.

## Rotas comuns a todo grupo (esqueleto compartilhado)

Toda página de grupo herda estas 2 da fábrica `build_group` (as rotas de **negócio** estão na
página de cada grupo). `<grupo>` ∈ clients, collaborators, leadership, staff:

| Método | Caminho | Auth | O que faz |
|---|---|---|---|
| GET | `/api/v1/<grupo>/health` | **pública** | liveness: `{group, version, status:"ok"}` |
| GET | `/api/v1/<grupo>/whoami` | **JWT** | eco do principal: `{external_id, roles}` — prova o JWT fim-a-fim |

Cada grupo também serve a doc OpenAPI: `/api/v1/<grupo>/docs` (Swagger) e
`/api/v1/<grupo>/openapi.json`.

## Versionamento

Toda a API carrega versão ([CONVENTION](../../../.claude/CONVENTION.md) §1): o caminho tem
`v1` e `NinjaAPI(version="1.0")` versiona a doc OpenAPI por grupo. **Quebra de contrato = nova
versão**; a anterior segue no ar até migrar os consumidores.

## O que FALTA terminar

As rotas de negócio JÁ existem nos 4 grupos. O que ainda falta:

1. **Documentar `collaborators` e `leadership`** — só `clients` e `staff` têm página de wiki
   (`wiki/api/`). Cada uma deve passar pela análise + doc pro front ([[WORKFLOW]] Portão 3).
2. **Provar de verdade o que é casca** — várias rotas existem mas **nunca rodaram** (ex.: todo o
   `/enrollment/*` no `clients`). O estado real está na página de cada grupo.
3. **Nome dos 4 grupos** — placeholder; decisão do Victor.
4. **Reexpor os `/status/` das integrações dentro do Ninja** — hoje `asaas`/`infinitepay`
   expõem status em `/integrations/.../status/` (views DMZ legadas). Migrar pro grupo `staff`
   (saúde dos serviços). **Deferido.**

> Já feito (não confundir com pendência): o gate de role (`require_roles`), a máquina de status
> por role, o E2E `register → OTP → login → Bearer` **provado real** (lead cartão/PIX +
> colaborador), e o **PK do `Address` fora da borda Ninja** (`as_public_dict`, Victor 2026-06-07 —
> ver [[wiki/api/clients]]). O JWT é `django-ninja-jwt` (swap concluído).

## Ver também

- [[CONVENTION]] §1 (arquitetura), §3 (acoplamento: router só chama `interface/`), §5 (tipos
  de endpoint), §10 (stack: django-ninja-jwt).
- `plan/api-ninja-transicao.md` (plano de transição) · `users/auth/jwt` (o JWT reusado).
