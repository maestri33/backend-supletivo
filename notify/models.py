"""Models do app notify — auditoria de notificações despachadas por canal.

Convenções (CONVENTION §4/§6/§12):
 - PK = BigAutoField interno (Django), nunca exposto.
 - `external_id` (UUID) = handle de borda/estável; é o retorno do `interface.send()`.
 - notify NÃO guarda contato (contato é do `profiles`, §4-3): o caller passa phone/email —
   dispatcher puro.
 - Envio é assíncrono (Django-Q) e nunca quebra o fluxo do caller (§12). Status por canal.
 - Mídia vai por URL: WhatsApp busca pela LAN (IP interno), e-mail embute pela URL pública (§0.2).
"""

from django.db import models

from core.models import ExternalIdModel

# Status de envio por canal.
STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED = (
    "skipped"  # canal não pedido, ou pedido sem destinatário — nada a enviar
)

_STATUS_CHOICES = [
    (STATUS_PENDING, "pendente"),
    (STATUS_SENT, "enviado"),
    (STATUS_FAILED, "falhou"),
    (STATUS_SKIPPED, "ignorado"),
]

# Tipos de mídia (espelha integrations.communication: whatsapp.send_media / mail.media_html).
MEDIA_TYPES = ("image", "video", "audio", "document")

# Canais de despacho (notify.interface.send.send). Ordem importa só pra o default de exibição.
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_EMAIL = "email"
CHANNEL_TTS = "tts"
_ALL_CHANNELS = (CHANNEL_WHATSAPP, CHANNEL_EMAIL, CHANNEL_TTS)


def _parse_channels(raw: str | None) -> list[str]:
    """'whatsapp,email' -> ['whatsapp','email']. Vazio/inválido -> [] (o caller decide default)."""
    if not raw:
        return []
    return [c.strip().lower() for c in raw.split(",") if c.strip().lower() in _ALL_CHANNELS]


class Template(ExternalIdModel):
    """Teor EDITÁVEL de um evento de notificação (fonte de verdade = DB; fallback = catálogo Python).

    O conteúdo é Markdown (`body_md`) — uma ÚNICA mensagem vira texto (WhatsApp) e HTML (e-mail).
    Placeholders por regex (não str.format): `{nome}` (1º nome), `{nome-completo}` (nome todo),
    e os do catálogo legado (`{name}`, `{valor}`, `{link}`, `{payload}`, ...). Ausentes ficam como estão.

    - `is_tts`: tenta gerar voice-note; se falhar, cai pra texto (WhatsApp). E-mail SEMPRE texto.
    - `storytelling`: o `body_md` é o FALLBACK; a IA gera o teor final (instruction = `story_prompt`).
    - `channels`: canais default (ex.: 'whatsapp,email'). `send_event()` respeita; `send()` explícito não.
    - `media_url`/`media_type`: mídia anexa default (image/video/audio/document) — sobrescrevível no call.
    """

    # chave natural do evento (ex.: "lead.paid"). Única — é o lookup de `send_event()` e `msgs.text()`.
    event = models.SlugField(max_length=80, unique=True, db_index=True)

    title = models.CharField(max_length=200, null=True, blank=True)
    subject = models.CharField(max_length=255, null=True, blank=True)  # e-mail; fallback: title
    body_md = models.TextField(help_text="Conteúdo em Markdown. Placeholders {nome}, {nome-completo}, {valor}...")

    # flags de geração
    is_tts = models.BooleanField(default=False, help_text="Tenta voice-note; falha -> texto.")
    storytelling = models.BooleanField(default=False, help_text="IA gera o teor (body_md = fallback).")
    story_prompt = models.TextField(
        null=True, blank=True, help_text="Instrução p/ o LLM (só se storytelling=True)."
    )

    # canais default e mídia default
    channels = models.CharField(
        max_length=40, default="whatsapp,email", help_text="Canais separados por vírgula."
    )
    media_url = models.CharField(max_length=500, null=True, blank=True)
    media_type = models.CharField(max_length=20, null=True, blank=True)
    mail_template = models.CharField(
        max_length=50, default="default", help_text="Slug do wrapper HTML do app mail."
    )

    notes = models.CharField(max_length=200, null=True, blank=True)  # anotação livre do Victor
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "template de notificação"
        verbose_name_plural = "templates de notificação"

    def __str__(self):
        flags = []
        if self.is_tts:
            flags.append("tts")
        if self.storytelling:
            flags.append("story")
        return f"Template({self.event}" + (f" [{','.join(flags)}]" if flags else "") + ")"

    @property
    def channel_list(self) -> list[str]:
        return _parse_channels(self.channels)


class Trigger(ExternalIdModel):
    """QUANDO o evento dispara (registro + flag `active`, NÃO motor de execução).

    Os serviços continuam chamando `send_event()`/`send()` no momento imperativo certo (reescrever pra
    observer/signal seria arriscado em prod). Este model DOCUMENTA o gatilho e permite ao Victor
    DESLIGAR um evento (`active=False`) sem tocar em código — `send_event()` honra e não despacha.
    `delay_minutes` é informativo por ora (fase 2: programar no Django-Q).
    """

    template = models.OneToOneField(Template, on_delete=models.CASCADE, related_name="trigger")
    fires_on = models.CharField(
        max_length=200, help_text="Descrição humana do gatilho (ex.: 'Após pagamento confirmado')."
    )
    source = models.CharField(
        max_length=100, null=True, blank=True, help_text="App/serviço emissor (ex.: 'users.roles.lead')."
    )
    delay_minutes = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True, db_index=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "gatilho de notificação"
        verbose_name_plural = "gatilhos de notificação"

    def __str__(self):
        state = "ativo" if self.active else "inativo"
        return f"Trigger({self.template_id}, {state}: {self.fires_on})"


class Notification(ExternalIdModel):
    """Uma notificação despachada — pode atingir vários canais (whatsapp / email / tts)."""

    # dedup opcional: o caller passa uma chave estável; a mesma chave devolve a notificação já criada.
    idempotency_key = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    # quem emitiu a notificação (ex.: "asaas.charge") — auditoria/telemetria.
    caller = models.CharField(max_length=100)

    recipient_phone = models.CharField(max_length=32, null=True, blank=True)
    recipient_email = models.EmailField(null=True, blank=True)

    title = models.CharField(max_length=200, null=True, blank=True)
    text = models.TextField()
    subject = models.CharField(max_length=255, null=True, blank=True)
    # slug do template HTML do app mail (default/welcome/parabens/receipt/checkout).
    mail_template = models.CharField(max_length=50, default="default")

    # mídia (imagem/vídeo/áudio/documento) por URL pública: WhatsApp busca pela LAN (_to_lan),
    # e-mail embute pela URL pública. media_type = image/video/audio/document.
    media_url = models.CharField(max_length=500, null=True, blank=True)
    media_type = models.CharField(max_length=20, null=True, blank=True)

    # gênero do destinatário (M/F) → voz do TTS (resolvido no integrations.ai). Vazio = voz default.
    gender = models.CharField(max_length=1, null=True, blank=True)

    want_whatsapp = models.BooleanField(default=True)
    want_email = models.BooleanField(default=False)
    want_tts = models.BooleanField(default=False)

    whatsapp_status = models.CharField(
        max_length=10, choices=_STATUS_CHOICES, default=STATUS_PENDING
    )
    email_status = models.CharField(
        max_length=10, choices=_STATUS_CHOICES, default=STATUS_PENDING
    )
    tts_status = models.CharField(
        max_length=10, choices=_STATUS_CHOICES, default=STATUS_PENDING
    )

    whatsapp_error = models.TextField(null=True, blank=True)
    email_error = models.TextField(null=True, blank=True)
    tts_error = models.TextField(null=True, blank=True)

    # caminho (relativo a MEDIA_ROOT) do mp3 gerado pelo TTS, quando houver.
    tts_audio_path = models.CharField(max_length=500, null=True, blank=True)

    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Notification({self.external_id}, caller={self.caller})"
