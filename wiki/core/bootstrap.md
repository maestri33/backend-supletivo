# core/bootstrap — o esqueleto do monólito

> Step **0** do MVP: o mínimo que faz o Django **subir**. Antes de qualquer app de negócio.
> Régua: `.claude/VISAO.md` + `.claude/CONVENTION.md`. Plano: `.claude/plan/0-init-django.md`.

## O que é

O `backend/` é o **monólito Django** — o cérebro (toda a lógica + o banco), conforme
[[../README|README]] e a CONVENTION. Este step só monta o esqueleto que roda: nada de
`users`/`hub`/`notify`/`integrations` ainda.

## Stack

- **uv** (deps + venv) · **Python 3.12** (baixado pelo uv via `.python-version`).
- **Django 5.2 LTS** (patch 5.2.14) · **django-environ** (config num ponto só).
- **Banco dev → SQLite** (`db.sqlite3`); prod → PostgreSQL via `DATABASE_URL` (depois).

## Layout

```
backend/
├── manage.py
├── pyproject.toml / uv.lock / .python-version
├── .env            # SECRET_KEY, DEBUG, ALLOWED_HOSTS (NÃO vai pro git)
├── .gitignore      # .env, db.sqlite3, .venv/, __pycache__/  (vivo)
└── core/           # settings, urls, wsgi, asgi
```

## Config (`backend/.env`)

`core/settings.py` lê tudo do `.env` com `django-environ`:

- `SECRET_KEY` · `DEBUG` · `ALLOWED_HOSTS`
- `DATABASE_URL` (ausente → SQLite local)
- Fuso/idioma fixos no settings: `America/Sao_Paulo` / `pt-br`.

## Rodar em dev

```bash
cd backend
uv sync                       # cria o .venv com as deps travadas
uv run python manage.py migrate
uv run python manage.py runserver
# GET /admin/ -> 302 -> /admin/login/
```

Teste real do step: `.claude/tests/0-init-django.md`.
