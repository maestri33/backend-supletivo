# Lente MEN — Mentira

Caçar afirmações falsas: código, comentário, docstring, wiki ou nome que **promete** algo que o comportamento **não entrega**.

## Procurar

- Docstring/wiki diz X; implementação faz Y (status, TTL, quem decide, sync vs async).
- Nome de função/campo enganoso: `validate_*` que só persiste; `get_*` que muta; `is_*` que faz I/O.
- Enum/choices documentados ≠ valores aceitos no código.
- Response schema promete campos que o handler não preenche (sempre omitidos ou hardcoded).
- Comentário "chamado em TODA troca" mas call site falta em algum fluxo.
- `# deprecated` sem remoção nem redirect; API marcada na wiki mas rota inexistente.
- Teste que asserta comportamento ideal, não o comportamento real (teste mente pro CI).
- Mensagem de erro mentirosa ("não encontrado" quando é forbidden).

## Fontes a cruzar

- `wiki/**/*.md` vs `api/*.py` vs `users/roles/*/service.py`
- OpenAPI/Ninja schema vs handler
- Comentários de plano (`plan/15`, `Victor 2026-…`) vs código atual

## Severidade

| Sev | Critério |
|-----|----------|
| 🔴 | Operador/cliente toma decisão errada (compliance, pagamento, aprovação). |
| 🟡 | Dev/oncall confia na doc e perde tempo debugando. |
| 🔵 | Comentário desatualizado sem impacto operacional. |

## Fix típico

`rename`, `doc fix`, `align behavior`, ou `delete false claim`.
