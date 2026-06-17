# Lente DUA — Dualidade

Caçar **dois (ou mais) caminhos** para a mesma operação, com regras divergentes — o sistema vive em dois mundos.

## Procurar

- Dois endpoints/services fazendo a mesma transição de status (enrollment vs candidate vs student).
- Leitura por `external_id` num sítio e por PK noutro, sem camada única.
- Status strings diferentes para o mesmo conceito (`pending` vs `in_review` vs `review`).
- Auth/permissão checada no router num lugar e só no service noutro.
- Integração Asaas vs InfinitePay com fluxos paralelos não abstraídos quando deveriam ser.
- Notificação disparada em hook num fluxo e manualmente noutro.
- Cache invalidation em um path; stale read no outro.
- `interface/__init__.py` expõe contrato A; `service.py` implementa contrato B.
- Sync task vs inline call para mesma validação de documento/selfie.

## Ignorar

- Dualidade **intencional** documentada (ex.: leadership vs collaborators API surfaces).
- Camadas view → service → model (não é dualidade, é layering).

## Severidade

| Sev | Critério |
|-----|----------|
| 🔴 | Comportamento inconsistente em produção (um path aprova, outro rejeita). |
| 🟡 | Só um path recebe bugfix; o outro vai driftar na próxima mudança. |
| 🔵 | Duplicação de surface API com mesma semântica (deprecate um). |

## Fix típico

`unify entrypoint`, `single source of truth` para status/nome, extrair `shared` module.
