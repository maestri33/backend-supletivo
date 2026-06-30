"""Models do app `bot` — atendimento por IA no WhatsApp (FASE 0 + FASE 1 MVP).

Telemetria/estado INTERNO (CONVENTION §4: external_id só na borda da API — aqui não há borda
pública além do webhook). Quatro tabelas:

- `InboundEvent`: payload BRUTO de cada mensagem recebida da Evolution + `wa_message_id` UNIQUE
  (idempotência — a Evolution re-tenta o webhook; nunca processamos a mesma msg 2x). Espelha o
  `WebhookEvent` do asaas.
- `Conversation`: o fio de conversa por telefone (profile FK NULLABLE — estranho não tem cadastro),
  com `audience` (público resolvido), `state` (open/awaiting_human/closed) e marcas de tempo.
- `Message`: cada turno (inbound/outbound), com `wa_message_id` e FK opcional pro `AiCall` que
  gerou a resposta (auditoria/custo).
- `BotRateLimit`: rate-limit por TELEFONE em DB (sem Redis — Django-Q usa o banco), porte do
  padrão do `OtpRateLimit`. Chaveado por phone (não por User) porque o estranho não tem User.
"""

from __future__ import annotations

from django.db import models

# ── estados da conversa ──────────────────────────────────────────────────
STATE_OPEN = "open"  # bot atendendo normalmente
STATE_AWAITING_HUMAN = "awaiting_human"  # escalado: um humano precisa assumir
STATE_CLOSED = "closed"  # encerrada

# ── direção da mensagem ──────────────────────────────────────────────────
DIRECTION_INBOUND = "inbound"  # do usuário pro bot
DIRECTION_OUTBOUND = "outbound"  # do bot pro usuário


class InboundEvent(models.Model):
    """Payload BRUTO de uma mensagem recebida do webhook da Evolution.

    `wa_message_id` UNIQUE = idempotência: a Evolution re-tenta o webhook em não-200, e o mesmo
    evento `messages.upsert` pode chegar duplicado. Persistimos o cru ANTES de qualquer
    processamento (igual ao `WebhookEvent` do asaas: se o roteamento falhar, o evento não some).
    """

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # id da mensagem no WhatsApp (key.id do payload da Evolution). UNIQUE => idempotência.
    # null=True: evento sem id (ex.: status/ack que não é mensagem) ainda é gravado pra auditoria.
    wa_message_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True, db_index=True
    )
    event = models.CharField(max_length=64, db_index=True)  # ex.: messages.upsert
    payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    source_ip = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["received_at"])]

    def __str__(self) -> str:
        return (
            f"{self.event}:{self.wa_message_id} @ {self.received_at:%Y-%m-%d %H:%M:%S}"
        )


class Conversation(models.Model):
    """Fio de conversa por telefone (1 ativo por phone). Profile NULLABLE: estranho não tem cadastro.

    `audience` é o público RESOLVIDO no momento do atendimento (lead/student/promoter/coordinator/
    staff/unknown — ver `router.AUDIENCE_*`); guardamos pra auditoria e pra não re-resolver a cada
    msg. `state` controla se o bot responde (open) ou se um humano assumiu (awaiting_human).
    """

    profile = models.ForeignKey(
        "users.Profile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bot_conversations",
    )
    # telefone canônico (DDI+DDD+número), o mesmo formato do Profile/notify (resolve_br_number).
    phone = models.CharField(max_length=20, db_index=True)
    audience = models.CharField(max_length=20, default="unknown", db_index=True)
    state = models.CharField(max_length=20, default=STATE_OPEN, db_index=True)
    last_activity = models.DateTimeField(auto_now=True, db_index=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["phone", "state"])]

    def __str__(self) -> str:
        return f"conv<{self.phone}:{self.audience}:{self.state}>"


class Message(models.Model):
    """Um turno da conversa (inbound do usuário / outbound do bot).

    `ai_call` (FK opcional) liga a resposta do bot à linha de `AiCall` que a gerou (custo/tokens).
    `wa_message_id` correlaciona com o WhatsApp (inbound = key.id recebido; outbound pode ficar
    nulo — o notify despacha async e não devolve o id da Evolution de volta pra cá).
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    direction = models.CharField(max_length=10)  # inbound | outbound
    text = models.TextField()
    wa_message_id = models.CharField(max_length=255, null=True, blank=True)
    ai_call = models.ForeignKey(
        "ai.AiCall",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self) -> str:
        return f"msg<{self.conversation_id}:{self.direction}>"


class BotRateLimit(models.Model):
    """Rate-limit por TELEFONE em DB (sem Redis), porte do `OtpRateLimit`.

    Chaveado por phone (não por User) porque o estranho não tem cadastro. Janela curta (1 a cada
    `BOT_RATELIMIT_WINDOW_S`) + janela horária (máx `BOT_RATELIMIT_HOURLY_MAX`/h). Anti-abuso de
    custo de IA/WhatsApp; alto o bastante pra nunca trancar usuário legítimo.
    """

    phone = models.CharField(max_length=20, unique=True, db_index=True)
    last_seen_at = models.DateTimeField()
    hourly_count = models.PositiveIntegerField(default=0)
    hourly_window_start = models.DateTimeField()

    def __str__(self) -> str:
        return f"bot_rl<{self.phone}>"
