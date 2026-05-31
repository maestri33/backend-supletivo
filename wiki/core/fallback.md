# core/fallback — logger rastreável de evento sem destino

> Pedido do Victor + CONVENTION §7.4. Quando um evento chega **validado** mas não há consumidor real
> ainda (o app destino — `fees`, `commissions`… — não existe), em vez de descartar em silêncio:
> **loga estruturado (structlog) e grava** pra auditar/reprocessar depois.

## O que é

`core` é o app base do monólito (CONVENTION §2 — "models base comuns"). Aqui mora o fallback:

- **`core/models.py` → `UnroutedEvent`** — `source` (ex.: `asaas`), `event`, `reason` (por que não
  roteou), `payload` (JSON), `received_at`, `resolved`. Migração `core/0001_initial`.
- **`core/fallback.py` → `log_unrouted_event(source, event, reason, payload)`** — loga via
  **structlog** (`warning "unrouted_event"`) **e** cria o `UnroutedEvent`.

## Quem usa

Hoje só o **webhook receiver do asaas** (1a-iii): evento que não casa com nenhum `Payment` nosso
(nem é evento conhecido) cai aqui. Ver [[../integrations/finance/asaas|asaas]].

## Quando os apps destino existirem

`fees`/`commissions` terão um dir `hooks/` (CONVENTION §7.3); o ponto de costura está marcado em
`asaas/webhooks.py` (`handle_event`). Aí o fallback passa a ser só o caso "evento mesmo sem dono".

## Teste

Print real em `.claude/tests/1a-iii-asaas-webhook.md` (2 `UnroutedEvent` gravados: `no_matching_charge`
e `unknown_event`).
