---
name: review-purge
description: >
  Orquestra agentes de revisão de código focados em duplicação, ruído, lógica
  desnecessária, mentiras (doc/código divergente), dualidade (dois caminhos
  conflitantes), enganos e delírios arquiteturais. Use quando o usuário pedir
  /review-purge, "revisar duplicação", "caçar ruído", "mentira no código",
  "dualidade", "engano", "delírio", ou auditoria de limpeza/refatoração.
---

# Review Purge — agentes de caça ao lixo cognitivo

Revisão **estrutural e semântica**, não de bugs (use `review-bugbot`) nem segurança (use `review-security`).

## Escopo padrão

| Diff | Quando |
|------|--------|
| `branch changes` | padrão — merge-base com `main` |
| `uncommitted changes` | só working tree sujo |
| path ou módulo | usuário apontou pasta/arquivo |

Repositório: raiz ativa do workspace (`/home/maestri33/mvp/backend`).

## Lentes (6 agentes)

Cada lente = um subagent `generalPurpose`, `readonly: true`, `run_in_background: true`.

| ID | Lente | Arquivo de prompt |
|----|-------|-------------------|
| DUP | Duplicação | [lenses/duplicacao.md](lenses/duplicacao.md) |
| NOZ | Ruído | [lenses/ruido.md](lenses/ruido.md) |
| LOG | Lógica desnecessária | [lenses/logica.md](lenses/logica.md) |
| MEN | Mentira | [lenses/mentira.md](lenses/mentira.md) |
| DUA | Dualidade | [lenses/dualidade.md](lenses/dualidade.md) |
| ENG | Engano e delírio | [lenses/engano-delirio.md](lenses/engano-delirio.md) |

Leia o arquivo da lente **antes** de montar o prompt do subagent.

## Workflow

1. **Determinar escopo** — diff, paths, ou módulo (`users/`, `api/`, `integrations/`…).
2. **Lentes pedidas** — se o usuário citou só algumas, rode só essas. Senão, rode as 6 em paralelo.
3. **Lançar subagents** — um `Task` por lente, mesma mensagem com variáveis:

```text
Full Repository Path: <abs path>
Scope: <branch changes | uncommitted changes | paths: a,b,c>
Base Branch: <só se branch changes contra base não-main>
Lens: <DUP|NOZ|LOG|MEN|DUA|ENG>
Instructions: <conteúdo integral do arquivo lenses/*.md correspondente>
Output contract: ver seção abaixo
```

4. **Aguardar** todos terminarem.
5. **Consolidar** no template de saída (português).
6. **Não corrigir** código salvo pedido explícito.

## Contrato de saída (cada subagent)

Ordenar por severidade (🔴 → 🟡 → 🔵). Máx. 15 achados por lente; se houver mais, agrupar os 🔵.

```
<LENS_ID> totals: N🔴 N🟡 N🔵

| Sev | Location | Finding | Fix |
|-----|----------|---------|-----|
| 🔴 | path:line | problema em 1 frase | ação concreta (delete/extract/unify/doc) |
```

Se nada encontrado: `<LENS_ID>: limpo.`

## Relatório consolidado (main thread)

```markdown
# Review Purge — <escopo>

## Resumo
- Duplicação: N achados (N🔴 …)
- Ruído: …
- …

## 🔴 Remover / unificar já
<tabela compacta só 🔴>

## 🟡 Simplificar em seguida
<tabela 🟡>

## 🔵 Opcional
<tabela 🔵 ou "nenhum">

## Padrões transversais
1-3 bullets se a mesma raiz aparecer em várias lentes (ex.: dois services fazendo a mesma coisa).
```

## Regras do projeto (contexto)

- Django backend MVP: `users/`, `api/`, `finance/`, `integrations/`, `hub/`.
- Roles em `users/roles/*/service.py`; interfaces em `*/interface/__init__.py`.
- Wiki em `wiki/` — comparar código com docs quando a lente for MEN ou ENG.
- Comentários em PT-BR no código são normais; mentira = **afirmação falsa**, não estilo.

## Quando NÃO usar

- Bug/regressão → `review-bugbot`
- CVE/auth/injection → `review-security`
- Review one-liner de PR → `caveman-review`

## Lentes parciais

| Pedido do usuário | Lentes |
|-------------------|--------|
| "duplicação" / "DRY" | DUP |
| "ruído" / "limpar" | NOZ, LOG |
| "mentira" / "doc mente" | MEN, ENG |
| "dualidade" / "dois jeitos" | DUA, DUP |
| "delírio" / "over-engineering" | ENG, LOG |
| tudo (padrão) | DUP NOZ LOG MEN DUA ENG |
