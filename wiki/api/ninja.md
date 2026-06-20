# api/ — API pública Django Ninja (in-process)

> **Estado: rotas de negócio escritas + documentadas** nos 4 grupos. O que cada grupo expõe está na
> **sua própria página**: [[wiki/api/clients]] · [[wiki/api/collaborators]] · [[wiki/api/leadership]] ·
> [[wiki/api/staff]]. **O estado de TESTE varia por rota** (provado real vs casca não-exercida com
> dinheiro/OTP real) — ver a página de cada grupo. Régua: [[CONVENTION]] §1/§3/§5.

A API pública do MVP **vive dentro do monólito Django**, via **Django Ninja** (in-process —
sem serviço separado, sem hop HTTP). Decisão do Victor 2026-06-01 (edges externos descartados).
O router é casca fina: recebe a request (auth + gate de role + validação de borda) → chama o
`interface/` do módulo **no mesmo processo** → devolve. **Zero regra de negócio no router.**

## Os 4 grupos (por público)

Cada grupo é um `NinjaAPI` próprio, montado em [core/urls.py](../../core/urls.py) sob
`/api/v1/<grupo>/`:

| Grupo | Público | Funil / papel |
|---|---|---|
| `clients` | aluno (**$$ ENTRA**) | lead → enrollment → student → veteran |
| `collaborators` | promotor | candidate → (coord aprova) → promoter (+ treino-overlay que trava o painel) |
| `leadership` | coordenador do polo | centraliza no `hub/`: aprova candidato→promotor, destrava/age-no-lugar, taxa→conclui |
| `staff` | administração ("boss") | hub/coordenador + financeiro + integrações + servidor + logs |

> Os nomes dos 4 grupos (`clients`/`collaborators`/`leadership`/`staff`) foram **FIXADOS** (Victor
> 2026-06-16) — são definitivos.

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

As rotas de negócio existem e estão documentadas nos 4 grupos. O que ainda falta:

1. **Provar de verdade o que é casca** — várias rotas existem mas faltam **testes com dinheiro/OTP
   reais** (E2E dos funis novos: candidato→promotor pelo path novo, promotor-estuda, student→veteran).
   O estado real está na página de cada grupo.
2. **Fast-follow do staff** — preencher o endereço do polo, marcar polo padrão, views globais de
   enrollment/student, gestão de usuários/roles.

> Já feito (não confundir com pendência): o gate de role (`require_roles`), a máquina de status por
> role, o E2E `register → OTP → login → Bearer` **provado real** (lead cartão/PIX + colaborador), o
> **PK do `Address` fora da borda Ninja** (`as_public_dict`), o JWT `django-ninja-jwt`. **DMZ FECHADA**
> (Victor 2026-06-16): a superfície HTTP sem-auth (`users/auth|address|documents` + `charge/payout/
> status/setup` dos gateways) saiu — sobraram só os **webhooks públicos** + o reexpose da **saúde das
> integrações no grupo `staff`** ([[wiki/api/staff]]).

## Ver também

- [[CONVENTION]] §1 (arquitetura), §3 (acoplamento: router só chama `interface/`), §5 (tipos
  de endpoint), §10 (stack: django-ninja-jwt).
- `plan/api-ninja-transicao.md` (plano de transição) · `users/auth/jwt` (o JWT reusado).
