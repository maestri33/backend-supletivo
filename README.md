# backend — monólito Django (MVP)

O **cérebro** da plataforma: toda a lógica de negócio + o banco moram aqui. À frente ficam
edges FastAPI finos (fora deste repo) que chamam as views DMZ por HTTP. Arquitetura completa
nas instruções do projeto (`.claude/CONVENTION.md`).

## Rodar em dev

```bash
cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Config em `backend/.env` (não versionado). Dev usa SQLite.

## Estado

- **Bootstrap (step 0):** Django sobe, migra, `/admin/` no ar. → [[wiki/core/bootstrap]]

> Apps de negócio (`users`, `hub`, `notify`, `financeiro`, `integrations`...) entram um a um,
> pelo `.claude/WORKFLOW.md`.
