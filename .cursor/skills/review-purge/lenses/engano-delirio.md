# Lente ENG — Engano e delírio

Caçar **fantasias arquiteturais**: abstrações que não existem na prática, código teatral, promessas futuras vivendo como se fossem reais.

## Engano (decepção consciente ou acidental)

- Factory/strategy/registry com uma implementação só — indirection sem segunda variante.
- Feature flag sempre `True`/`False`; env var lida e ignorada.
- "Async" que só enfileira mas ninguém consome a fila no path crítico.
- Hook/callback registrado que nunca é invocado.
- Métrica/audit gravada que ninguém lê; campo `source_ip` sempre vazio.
- Abstração `BankProvider` com um banco — interface maior que o uso.
- Exception type hierarchy usada só uma vez.

## Delírio (cargo cult / desconexão da realidade)

- Camadas `interface`/`service`/`models` onde `service` só delega 100% sem regra.
- "Domain events" sem subscriber.
- Plano futuro (`plan/17`) codificado como branch morto no main.
- Generalização para N roles/integrações quando catálogo tem 2 entradas.
- AI/biometria "fail-safe → review" documentado mas código aprova silenciosamente.
- Testes de integração mockando tudo — validam o mock, não o sistema.
- Config `.env` com dezenas de keys; metade sem leitura no código.

## Severidade

| Sev | Critério |
|-----|----------|
| 🔴 | Delírio de segurança/compliance — sistema **parece** proteger e não protege. |
| 🟡 | Custo cognitivo alto; próximo dev acredita na abstração e estende errado. |
| 🔵 | YAGNI claro; remover quando tocar no arquivo. |

## Fix típico

`delete layer`, `collapse`, `implement for real or remove claim`, `wire queue or go sync`.
