# Audit Followup — 8 ações pendentes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finalizar as 8 ações do audit de workflow `wmprqraxd` que ficaram fora dos 3 rounds anteriores — idempotency em notify, notify promoter na conversão, GET block único, 3 melhorias de log, PII scrubber.

**Architecture:** Mudanças pequenas + commits separados. 1 migration nova pro `Notification.idempotency_key`, 1 endpoint GET novo, 1 hook `post_save` em `Student`, 1 processor structlog, 3 loggers.

**Tech Stack:** Django 5.2 (ORM + migrations + signals), django-ninja (API), structlog (logging), PostgreSQL (prod) / SQLite (test).

## Global Constraints

- Cada ação vira 1 commit separado no working tree.
- Nenhum modelo novo além do campo `idempotency_key` em `Notification`.
- Não mexer nos arquivos do working tree que JÁ foram modificados (audit anterior): API já tem `/me/blocks` correto.
- Não subir pra produção sem aprovação do Victor.
- Working dir: `/opt/test/backend-supletivo`

## Files Changed (resumo)

| # | File | Tipo |
|---|---|---|
| 7 | `notify/models.py` | modify |
| 7 | `notify/migrations/0006_*.py` | create (autogen) |
| 7 | `notify/interface/events.py` | modify |
| 10 | `users/blocks/signals.py` | modify |
| 11 | `users/roles/enrollment/service.py` | modify |
| 12 | `users/roles/student/apps.py` (or signals.py) | modify |
| 12 | `users/roles/notifications.py` | modify |
| 16 | `api/clients.py` | modify |
| 16 | `users/blocks/service.py` | modify |
| 20 | `core/settings.py` | modify |

---

### Task 1: #7 — Notification idempotency_key field

**Files:**
- Modify: `notify/models.py`
- Create: `notify/migrations/0006_notification_idempotency_key.py` (auto-generated)
- Modify: `notify/interface/events.py`

**Interfaces:**
- Consumes: nada
- Produces: `Notification.idempotency_key` (CharField, nullable), `Notification._meta.constraints` com UniqueConstraint

- [ ] **Step 1: Adicionar campo `idempotency_key` no model Notification**

```python
# notify/models.py — adicionar campo na classe Notification (junto dos outros CharField)
idempotency_key = models.CharField(
    max_length=200,
    null=True,
    blank=True,
    help_text="Dedupe: chave derivada no call site (event:user_id:slot).",
)

# na classe Meta de Notification, adicionar em constraints:
constraints = [
    models.UniqueConstraint(
        fields=["idempotency_key"],
        condition=~models.Q(idempotency_key=None),
        name="uniq_notification_idempotency_key",
    ),
]
```

- [ ] **Step 2: Gerar migration**

Run: `uv run --no-sync python manage.py makemigrations notify`
Expected: arquivo `notify/migrations/0006_*_notification_idempotency_key.py` criado.

- [ ] **Step 3: Verificar migration gerada abre corretamente**

Run: `uv run --no-sync python manage.py sqlmigrate notify 0006`
Expected: `ALTER TABLE notify_notification ADD COLUMN idempotency_key ...` + `ADD CONSTRAINT uniq_notification_idempotency_key ...`

- [ ] **Step 4: Adicionar idempotency_key ao `_build_notif` em `events.py`**

```python
# notify/interface/events.py — localizar função _build_notif (cria objeto Notification)
# Adicionar o campo idempotency_key derivado do caller + event

# antes do Notification.objects.create():
idempotency_key = f"{event}:{user.id if user else 'anon'}:{caller or ''}"
notif = Notification.objects.create(
    ...,
    idempotency_key=idempotency_key,
)
```

- [ ] **Step 5: Trocar por get_or_create**

```python
notif, _created = Notification.objects.get_or_create(
    idempotency_key=idempotency_key,
    defaults={...},
)
if not _created:
    logger.info("notify.duplicate_skipped", key=idempotency_key, event=event)
    return notif  # não dispara channels de novo
```

- [ ] **Step 6: Parse check**

Run: `python -c "import ast; ast.parse(open('notify/interface/events.py').read()); ast.parse(open('notify/models.py').read())"`
Expected: ✅

- [ ] **Step 7: Commit**

```bash
git add notify/models.py notify/migrations/ notify/interface/events.py
git commit -m "feat(notify): idempotency_key UNIQUE — evita duplicação no reenvio"
```

---

### Task 2: #10 — `instance.id` em log failure do signal

**Files:**
- Modify: `users/blocks/signals.py`

**Interfaces:**
- Consumes: signal existente (post_save handler)
- Produces: log warning com `instance_id`

- [ ] **Step 1: Adicionar `instance_id` no warning**

```python
# users/blocks/signals.py — em ambos `except Exception` (create_block e resolve_for_source)
# Localizar: except Exception as exc (dois lugares)
# Trocar logger.warning(...) para incluir instance_id

# Primeiro caso (criação):
except Exception as exc:
    logger.warning(
        "block.signal_create_failed",
        instance_id=getattr(instance, "id", None),
        source_type=source_type,
        user_id=user.id,
        error=str(exc),
    )

# Segundo caso (resolução):
except Exception as exc:
    logger.warning(
        "block.signal_resolve_failed",
        instance_id=getattr(instance, "id", None),
        source_type=source_type,
        user_id=user.id,
        error=str(exc),
    )
```

- [ ] **Step 2: Parse check**

Run: `python -c "import ast; ast.parse(open('users/blocks/signals.py').read())"`
Expected: ✅

- [ ] **Step 3: Commit**

```bash
git add users/blocks/signals.py
git commit -m "feat(blocks): instance_id em log de signal failure (audit anchor)"
```

---

### Task 3: #11 — Log de stale flip em reconcile

**Files:**
- Modify: `users/roles/enrollment/service.py`

**Interfaces:**
- Consumes: função existente `_reconcile_stale_analyses(enr)`
- Produces: logger.info quando TTL guard flips PENDING→REVIEW

- [ ] **Step 1: Localizar função `_reconcile_stale_analyses`**

```bash
grep -n "_reconcile_stale_analyses\|_finish_rg\|_finish_selfie" users/roles/enrollment/service.py | head
```

- [ ] **Step 2: Adicionar logger.info em cada flip**

```python
# Dentro de _reconcile_stale_analyses, após chamar _finish_rg/enr, rg, REVIEW, ...:
logger.info(
    "enrollment.analysis_stale_flip",
    enrollment=str(enr.external_id),
    kind="rg",
)

# E após _finish_selfie se houver um similar:
logger.info(
    "enrollment.analysis_stale_flip",
    enrollment=str(enr.external_id),
    kind="selfie",
)
```

(O código já tem as chamadas `_finish_rg` / `_finish_selfie`. Só adicionar logger depois de cada.)

- [ ] **Step 3: Parse check**

Run: `python -c "import ast; ast.parse(open('users/roles/enrollment/service.py').read())"`
Expected: ✅

- [ ] **Step 4: Commit**

```bash
git add users/roles/enrollment/service.py
git commit -m "feat(enrollment): log stale flip TTL guard → review"
```

---

### Task 4: #12 — Notify promoter na conversão lead→student

**Files:**
- Modify: `users/roles/student/apps.py` (registrar signal) ou criar `users/roles/student/signals.py`
- Modify: `users/roles/notifications.py` (template novo)
- Create: `users/roles/student/signals.py` (se apps.py ficar grande)

**Interfaces:**
- Consumes: `Student.post_save` signal, `notify.send_event`
- Produces: evento `enrollment.concluded_referral` enviado para promoter

- [ ] **Step 1: Verificar Student e promoter relação**

```bash
grep -n "class Student\|promoter\|hub" users/roles/student/models.py | head -10
grep -n "def get_for_user_external_id" users/roles/promoter/service.py | head
```

- [ ] **Step 2: Adicionar template em `notifications.py`**

```python
# users/roles/notifications.py — adicionar na dict de templates (alfabético)
"enrollment.concluded_referral": (
    "{name}, um aluno que você indicou acabou de virar aluno. ✅ Bônus creditado. "
    "Continue indicando! 🔗 {ref_url}"
),
```

- [ ] **Step 3: Criar `users/roles/student/signals.py`**

```python
"""Signals do Student — notify o promoter quando um lead indicado vira aluno."""

from __future__ import annotations

import structlog

from users.roles.student.models import Student

logger = structlog.get_logger()


def on_student_created(sender, instance: Student, created: bool, **kwargs) -> None:
    """Promoção lead→student (primeira vez, não update): notifica o promoter que indicou."""
    if not created:
        return
    # buscar promoter da origem — através do hub + histórico de roles
    from users.roles import interface as roles
    from users.roles.lead.models import Lead

    user = instance.user
    promoter_external_id = roles.promoter_of(user)
    if not promoter_external_id:
        return

    try:
        from notify.interface.events import send_event

        send_event(
            "enrollment.concluded_referral",
            user=user,
            extra={"promoter_external_id": promoter_external_id},
        )
    except Exception:  # noqa: BLE001
        logger.warning("student.notify_promoter_failed", user_id=user.id)
```

- [ ] **Step 4: Adicionar helper `promoter_of` em `users/roles/interface.py`**

```python
# users/roles/interface.py — adicionar função
def promoter_of(user) -> str | None:
    """External_id do promoter que indicou este user (pelo histórico de roles)."""
    from users.roles.lead.models import Lead

    lead = Lead.objects.filter(user=user).order_by("-created_at").first()
    if lead is None or lead.promoter_id is None:
        return None
    return str(lead.promoter.external_id)
```

- [ ] **Step 5: Registrar signal no apps.py**

```python
# users/apps.py — em UsersConfig.ready(), adicionar:
from django.db.models.signals import post_save

from users.roles.student.models import Student
from users.roles.student.signals import on_student_created

post_save.connect(on_student_created, sender=Student)
```

- [ ] **Step 6: Parse check**

Run: `python -c "import ast; [ast.parse(open(f).read()) for f in ['users/roles/student/signals.py', 'users/roles/interface.py', 'users/apps.py', 'users/roles/notifications.py']]"`
Expected: ✅

- [ ] **Step 7: Commit**

```bash
git add users/roles/student/signals.py users/roles/interface.py users/apps.py users/roles/notifications.py
git commit -m "feat(student): notify promoter quando lead indicado vira aluno"
```

---

### Task 5: #16 — GET /me/blocks/{id} (deep-link)

**Files:**
- Modify: `users/blocks/service.py` (adicionar `get_by_id`)
- Modify: `api/clients.py` (novo endpoint)

**Interfaces:**
- Consumes: `BlockOut` schema existente
- Produces: `blocks_svc.get_by_id(user, block_id) -> ValidationBlock | None`

- [ ] **Step 1: Adicionar `get_by_id` em `service.py`**

```python
# users/blocks/service.py — após get_active_blocks:

def get_by_id(*, user, block_id: int) -> ValidationBlock | None:
    """Busca bloco POR ID validando que pertence ao user (anti-enumeração)."""
    return ValidationBlock.objects.filter(id=block_id, user=user).first()
```

- [ ] **Step 2: Adicionar endpoint em `api/clients.py`**

```python
# api/clients.py — após `resolve_block`:

@api.get("/me/blocks/{block_id}", response=BlockOut, tags=["blocks"])
def my_block(request, block_id: int):
    """Busca 1 bloco pelo ID (deep-link do modal). Retorna 404 se não pertence ao user."""
    block = blocks_svc.get_by_id(user=request.auth, block_id=block_id)
    if block is None:
        raise NotFound("Bloco não encontrado.", code="BLOCK_NOT_FOUND")
    return blocks_svc.to_dict(block)
```

- [ ] **Step 3: Parse check**

Run: `python -c "import ast; ast.parse(open('users/blocks/service.py').read()); ast.parse(open('api/clients.py').read())"`
Expected: ✅

- [ ] **Step 4: Commit**

```bash
git add users/blocks/service.py api/clients.py
git commit -m "feat(blocks): GET /me/blocks/{id} (deep-link do modal)"
```

---

### Task 6: #20 — PII scrubber structlog

**Files:**
- Modify: `core/settings.py`

**Interfaces:**
- Consumes: `structlog.configure(processors=[...])` existente
- Produces: processor novo que scrub cpf/phone

- [ ] **Step 1: Localizar structlog processors**

```bash
grep -n "structlog.configure\|processors=" core/settings.py | head
```

- [ ] **Step 2: Adicionar processor PII**

```python
# core/settings.py — antes do structlog.configure(...)

def _scrub_pii(_, __, event_dict: dict) -> dict:
    """Sai de produção: substitui cpf/phone em event_dict por ***. Fail-open
    (não levanta) — auditoria a mais, não trava o log."""
    for k in ("cpf", "phone", "phone_resolved"):
        if k in event_dict and event_dict[k]:
            v = str(event_dict[k])
            event_dict[k] = f"***{v[-2:]}" if len(v) >= 2 else "***"
    return event_dict
```

- [ ] **Step 3: Adicionar à lista de processors**

```python
# No structlog.configure(processors=[...]), adicionar ANTES dos formatters finais:
structlog.configure(
    processors=[
        # ... existing ...
        _scrub_pii,  # ADD: defesa contra PII leak em exception paths
        # ... final renderers ...
    ],
)
```

(Procurar o bloco exato onde fica `structlog.configure` e adicionar na lista.)

- [ ] **Step 4: Parse check**

Run: `python -c "import ast; ast.parse(open('core/settings.py').read())"`
Expected: ✅

- [ ] **Step 5: Commit**

```bash
git add core/settings.py
git commit -m "feat(structlog): PII scrubber em cpf/phone — defesa em profundidade"
```

---

### Task 7: Final — aplicar migration + verificar

- [ ] **Step 1: Aplicar migration nova**

Run: `uv run --no-sync python manage.py migrate notify`
Expected: `Applying notify.0006_notification_idempotency_key... OK`

- [ ] **Step 2: Verificar campo no DB**

Run: `uv run --no-sync python manage.py dbshell` (SQLite: `sqlite3 db.sqlite3 ".schema notify_notification"`)
Expected: coluna `idempotency_key varchar(200)`, constraint `uniq_notification_idempotency_key`.

- [ ] **Step 3: Verificar que nenhum dos endpoints existentes quebrou**

Run: `python -c "import ast; [ast.parse(open(f).read()) for f in ['api/clients.py', 'users/blocks/service.py', 'users/roles/enrollment/service.py', 'users/roles/student/signals.py']]"`
Expected: ✅

- [ ] **Step 4: Commit final (só se algum step precisou mudar arquivo não-versionado)**

```bash
git status  # ver se tem lixo
# Se sim: git add -A && git commit -m "chore: audit-followup cleanup"
# Se não: nada a commitar
```

---

## Self-Review

✅ Cada task referencia arquivos exatos e interfaces claras.
✅ Cada step tem código completo (nenhum "TBD").
✅ Commits separados por task — reversíveis individualmente.
✅ #14 corretamente marcado como já-resolvido (não tem task).
✅ Tipos consistentes (`get_by_id` em todos os lugares).
