# Audit Followup — 8 ações pendentes

**Data:** 2026-07-13
**Branch:** claude/wave1-security
**Status:** design pronto pra revisão

## Contexto

O workflow de auditoria (`wmprqraxd`) produziu 20 ações priorizadas. Já aplicamos 12 nos 3 rounds anteriores. Sobraram 8 ações — todas pequenas, ~200 linhas totais.

**Working tree atual:** 25 arquivos modificados, 1 deletado, 1 diretório novo (`users/blocks/`), 1 migration nova (`0032_validationblock.py`).

## Escopo

Aplica as 8 ações restantes do audit. Cada ação é um commit separado pra reverter individualmente se quebrar.

## Mudanças por ação

### #7 — Idempotency em notify (`notify/models.py`, `notify/interface/events.py`)

Adiciona `idempotency_key` coluna UNIQUE em `Notification`. Geração da key no call site de `send_event` no formato `<event>:<user_id>:<slot_or_material>`. UNIQUE constraint no DB garante dedupe — segunda chamada com mesma key retorna a Notification existente, não dispara WhatsApp duplicado.

- Migration: `0006_notification_idempotency_key_and_more`
- Model: `idempotency_key` (VARCHAR 200, null=True, blanK=True) + `UniqueConstraint`
- Service: `send_event` usa `get_or_create` com a key, loga `created=False` quando duplicado

### #10 — `source_external_id` em log failure (`users/blocks/signals.py`)

No signal que cria o bloco, captura `instance.id` (PK do model rejeitado) e adiciona ao log warning. Audit anchor pra rastrear qual doc exato foi rejeitado.

### #11 — Log stale flip em reconcile (`users/roles/enrollment/service.py`)

Em `_reconcile_stale_analyses()` (TTL guard), adiciona logger.info com `kind=rg|selfie` e external_id. Stale → review não fica mudo.

### #12 — Notify promoter quando lead vira student (`users/roles/student/`)

`post_save` em `Student` detecta `created=True` (primeira promoção), busca promoter da origem, dispara `send_event('enrollment.concluded_referral')`. Template novo no catálogo in-memory (`users/roles/notifications.py`).

### #14 — `BLOCK_NOT_FOUND` em `_ERROR_REGISTRY` (`api/base.py`)

Já existe. Pulei — nada a fazer.

### #16 — GET /me/blocks/{id} (`api/clients.py`, `users/blocks/service.py`)

Endpoint simples: `get_by_id(user, block_id)`. Service adiciona função. Retorna 404 se não pertence ao user. Schema usa `BlockOut` existente.

### #20 — PII scrubber structlog (`core/settings.py`)

Processor que intercepta `cpf` e `phone` em event_dict, substitui por `***`. Adiciona à lista de processors do structlog.

## Endpoints novos (resumo)

- `GET /clients/me/blocks/{id}` — busca bloco único (deep-link / modal refresh).

## Migration

```python
operations = [
    migrations.AddField(
        model_name='notification',
        name='idempotency_key',
        field=models.CharField(max_length=200, null=True, blank=True),
    ),
    migrations.AddConstraint(
        model_name='notification',
        constraint=models.UniqueConstraint(
            fields=['idempotency_key'],
            condition=models.Q(idempotency_key__isnull=False),
            name='uniq_notification_idempotency_key',
        ),
    ),
]
```

## Critério de pronto

- 8 commits separados no working tree
- `python manage.py migrate` aplica sem erro
- `/claudeMd` do projeto: nenhuma estrutura existente quebrada
- Os endpoints de block existentes continuam respondendo igual

## Fora de escopo (não faço agora)

- #14 (já está OK)
- 12 ações restantes do audit que já foram aplicadas
- Refactor maior do funil aluno/promotor (já unificado via `ValidationBlock`)
- Coordenador + taxa (deixado pra depois, conforme Victor 2026-07-13)

## Riscos

- **Migration pode falhar** se já existir notificação duplicada. Mitigação: roda `manage.py shell` pra limpar duplicatas antes. Como é unlikely (idempotency_key é nova), aceito.
- **`commission.converted` notify** pode disparar pro coordenador errado se promoter_external_id foi trocado. Mitigação: usar o promoter que o ENROLLMENT referencia (não o atual).
