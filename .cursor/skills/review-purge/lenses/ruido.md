# Lente NOZ — Ruído

Caçar tudo que ocupa espaço mental sem comprar comportamento.

## Procurar

- Imports mortos, variáveis atribuídas e nunca lidas.
- Logs/debug (`print`, `logger.debug` sem valor operacional) em hot path.
- Comentários que repetem o código linha a linha ("incrementa contador").
- Docstrings de uma linha óbvias em getters/setters triviais.
- `# TODO`/`# FIXME`/`# HACK` antigos sem issue ou plano.
- Código comentado (blocos `#` ou `if False:`).
- Parâmetros de função nunca usados; `**kwargs` que engolem tudo.
- Exceções genéricas capturadas só para `pass`.
- Campos de model/schema expostos na API mas sempre `null`/default.
- Camadas vazias: `interface/__init__.py` que só re-exporta sem contrato.

## Ignorar

- Comentários que explicam **regra de negócio** não óbvia (Victor, TTL, coord decide).
- Type hints e `# noqa` com justificativa.
- Wiki — escopo da lente MEN, não NOZ.

## Severidade

| Sev | Critério |
|-----|----------|
| 🔴 | Ruído esconde bug (except swallow, log único sinal de falha removível). |
| 🟡 | Arquivo difícil de ler; >5 itens de ruído no mesmo módulo. |
| 🔵 | Nit estético isolado. |

## Fix típico

`delete`, enxugar comentário, remover parâmetro, colapsar camada.
