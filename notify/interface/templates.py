"""Acesso ao Template de notificação no DB (CONVENTION §3): cache em memória + fallback.

Fonte de verdade EDITÁVEL = DB (`Template`). Fallback = catálogo Python (`users.roles.notifications`
— `_MESSAGES`/`_TTS_EVENTS`/`_STORY_INSTRUCTIONS`), usado quando a row não existe (bootstrap,
DB fora do ar). Assim os 63 callsites legados (`msgs.text()`/`msgs.is_tts()`) passam a ler do DB
sem refactor: só esta camada sabe do DB.

Cache: por evento (`dict[event, TemplateData | None]`). Invalidado por `post_save`/`post_delete`
do Template (signal conectado em `notify.apps.ready`). `None` é cacheado também (negative cache
evita repetir o SELECT p/ eventos sem row — a maioria até o 1º seed).

Renderer: regex (não `str.format`) — suporta chaves com hífen (`{nome-completo}`) e placeholders
ausentes ficam como estão (não quebra o envio). Placeholders: `{nome}`, `{nome-completo}` e os
legados (`{name}`, `{valor}`, `{link}`, `{payload}`, `{detail}`, ...).
"""

from __future__ import annotations

import re
import structlog
from dataclasses import dataclass

from django.db.models.signals import post_delete, post_save

from notify.models import Template

logger = structlog.get_logger()

# regex de placeholder: {chave} onde chave = letra + [a-z0-9_-]*. Case-insensitive não — nomes
# de placeholder são sempre minúsculos por convenção.
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_-]*)\}")


@dataclass(frozen=True)
class TemplateData:
    """Snapshot imutável de um Template (pro cache ser seguro de compartilhar entre threads)."""

    event: str
    title: str | None
    subject: str | None
    body_md: str
    is_tts: bool
    storytelling: bool
    story_prompt: str | None
    channels: tuple[str, ...]
    media_url: str | None
    media_type: str | None
    mail_template: str

    @classmethod
    def from_model(cls, t: Template) -> "TemplateData":
        return cls(
            event=t.event,
            title=t.title,
            subject=t.subject,
            body_md=t.body_md or "",
            is_tts=t.is_tts,
            storytelling=t.storytelling,
            story_prompt=t.story_prompt,
            channels=tuple(t.channel_list),
            media_url=t.media_url or None,
            media_type=t.media_type or None,
            mail_template=t.mail_template or "default",
        )


# cache: event -> (TemplateData | None, monotonic_ts). None = "não existe no DB" (negative cache).
# G15/#24: TTL curto porque o cache é module-level e a invalidação por signal é IN-PROCESS — o
# worker do Django-Q é outro processo e NÃO recebe o post_save do web, então sem TTL um Template
# editado no painel ficava stale no worker até reiniciar. 30s limita a janela de staleness.
_CACHE: dict[str, tuple[TemplateData | None, float]] = {}
_CACHE_TTL_S = 30


def _load(event: str) -> TemplateData | None:
    """Lê do DB (1 SELECT) e cacheia com TTL. Devolve None se a row não existir. Nunca levanta: DB
    fora do ar → loga e devolve o último valor bom (ou None), sem envenenar o cache."""
    import time

    cached = _CACHE.get(event)
    if cached is not None and (time.monotonic() - cached[1]) < _CACHE_TTL_S:
        return cached[0]
    try:
        row = Template.objects.filter(event=event).first()
    except Exception as exc:  # noqa: BLE001 — DB é enfeite aqui; fallback in-memory garante a mensagem
        logger.warning(
            "notify.template_db_error", template_event=event, error=str(exc)[:160]
        )
        # G15/#26: NÃO cacheia em erro transitório — antes gravava None PERMANENTE (negative-cache
        # poison), e o evento passava a ignorar o Template do DB pra sempre. Mantém o último valor
        # bom se houver; senão None (o caller usa o fallback in-memory).
        return cached[0] if cached is not None else None
    data = TemplateData.from_model(row) if row is not None else None
    _CACHE[event] = (data, time.monotonic())
    return data


def get(event: str) -> TemplateData | None:
    """Template do evento (DB cacheado) ou None se não há row."""
    return _load(event)


def invalidate(event: str | None = None) -> None:
    """Descarta o cache do evento (ou tudo se event=None). Chamado pelos signals do Template."""
    if event is None:
        _CACHE.clear()
    else:
        _CACHE.pop(event, None)


def render(body: str, ctx: dict) -> str:
    """Substitui placeholders `{chave}` por ctx[chave]; ausentes ficam literais (não quebra envio).

    Não usa str.format: assim `{nome-completo}` (hífen) funciona e placeholders não-declarados
    no ctx não levantam (um template novo com placeholder novo roda mesmo sem o ctx trazer).
    """
    if not body:
        return ""

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        # alias hífen→underscore: `{nome-completo}` casa `ctx["nome_completo"]`.
        alias = key.replace("-", "_")
        if alias != key and alias in ctx:
            return str(ctx[alias])
        # interop legado↔novo: `{nome}` casa `ctx["name"]` e vice-versa (callsites antigos passam name=).
        if key == "nome" and "name" in ctx:
            return str(ctx["name"])
        if key == "name" and "nome" in ctx:
            return str(ctx["nome"])
        return m.group(0)  # deixa o placeholder literal

    return _PLACEHOLDER_RE.sub(_sub, body)


def render_event(event: str, ctx: dict) -> tuple[str | None, TemplateData | None]:
    """Renderiza o body do evento (DB) com ctx. Devolve (texto, data); (None, None) se sem row no DB."""
    data = _load(event)
    if data is None:
        return None, None
    return render(data.body_md, ctx), data


def is_tts(event: str) -> bool | None:
    """Flag TTS do DB; None se a row não existe (caller cai pro fallback in-memory)."""
    data = _load(event)
    return data.is_tts if data is not None else None


# ── signals: invalidam o cache quando o Template muda. Conectados em notify.apps.ready ──


def _on_template_save(sender, instance: Template, **_kwargs) -> None:
    invalidate(instance.event)


def _on_template_delete(sender, instance: Template, **_kwargs) -> None:
    invalidate(instance.event)


def connect_signals() -> None:
    """Idempotente: conecta post_save/post_delete do Template ao invalidador de cache."""
    post_save.connect(
        _on_template_save,
        sender=Template,
        dispatch_uid="notify.template.cache_invalidate",
    )
    post_delete.connect(
        _on_template_delete,
        sender=Template,
        dispatch_uid="notify.template.cache_invalidate_del",
    )
