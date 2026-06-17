# Lente LOG — Lógica desnecessária

Caçar ramificações, abstrações e cerimônia que não mudam o resultado.

## Procurar

- `if/else` onde os dois ramos produzem o mesmo efeito ou um nunca roda.
- Early return possível mas enterrado em nesting >3 níveis.
- Double negation, flags booleanas redundantes (`is_active and not is_revoked` quando só um campo basta).
- Loops que poderiam ser uma query (`for` + `.get()` N vezes).
- Serialização manual quando ORM/schema já faz.
- Wrappers de uma linha que só repassam (`def foo(x): return bar(x)` sem semântica).
- Retry/timeout/circuit-breaker onde a integração já é síncrona e local.
- Validação duplicada: model `clean` + service + schema com mesmas regras.
- Estado derivado persistido quando poderia ser `@property` ou annotation.
- `try/except` em volta de código que não levanta (defensive programming fantasma).

## Ignorar

- Guards de negócio reais (role catalog, biometria, fail-safe → `review`).
- Transações e locks necessários.

## Severidade

| Sev | Critério |
|-----|----------|
| 🔴 | Ramo morto ou lógica que altera comportamento errado (nunca aprova, sempre cai em default). |
| 🟡 | Complexidade medida (cyclomatic alta) sem ganho; manutenção cara. |
| 🔵 | Simplificação local possível mas legível o suficiente. |

## Fix típico

`inline`, `early return`, `delete branch`, mover regra para um só lugar.
