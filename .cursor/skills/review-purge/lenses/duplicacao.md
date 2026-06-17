# Lente DUP — Duplicação

Caçar código copiado, espelhado ou quase idêntico que deveria ser um só lugar.

## Procurar

- Funções/métodos com corpo ≥80% igual em arquivos diferentes.
- Schemas Pydantic/Ninja duplicados (`api/schemas.py` vs `*/interface`).
- Validações repetidas (CPF, status, TTL, biometria) em services distintos.
- Queries ORM copy-paste (`filter`/`select_related`/`prefetch` iguais).
- Constantes/magic strings repetidas sem `config` ou `catalog`.
- Handlers de webhook/polling com a mesma máquina de estados.
- Testes que duplicam setup em vez de fixture/factory.

## Ignorar (não é achado)

- Similaridade superficial (<30 linhas, lógica de domínio diferente).
- Duplicação intencional documentada (ex.: fail-safe isolado por integração).
- Padrão Django boilerplate (migrations, `Meta`, `__str__`).

## Severidade

| Sev | Critério |
|-----|----------|
| 🔴 | Bug fix precisa ser aplicado N vezes; divergência já visível (um path trata edge case, outro não). |
| 🟡 | 2–3 cópias estáveis; risco de drift na próxima feature. |
| 🔵 | Micro-duplicação (<10 linhas) ou só em testes. |

## Fix típico

`extract` para helper/module, `unify` via base class/mixin, ou `catalog`/config central.
