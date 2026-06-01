"""Render de template de email — arquivos HTML em disco, troca de placeholders (sem DB).

Cada template é um arquivo `templates/<slug>.html` no app. `render()` troca `{{title}}`,
`{{content}}` e `{{service_name}}`, portando a higienização do legado (escape + bold markdown +
nl2br). Sem model/migração/CRUD — alinhado à CONVENTION §12 (a mensagem mora no app emissor) e §8
(integration fino). Quem decide qual slug usar é o futuro notify.
"""

from __future__ import annotations

import html as _html
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

DEFAULT_SLUG = "default"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")


class TemplateNotFound(Exception):
    """Slug inexistente e sem o fallback `default` em disco (estado inválido)."""


MEDIA_TYPES = {"image", "video", "audio", "document"}


def _md_bold_to_html(text: str) -> str:
    """Converte bold markdown ('**x**' e '*x*') em <strong> DEPOIS do html.escape.

    Ordem importa: '**x**' (específico) antes de '*x*' (geral). O '*x*' só casa quando abre/fecha em
    caractere não-espaço, evitando falso-positivo em '5 * 5 = 25' ou listas '* item'.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.DOTALL)
    text = re.sub(
        r"(?<![*\w])\*([^*\s](?:.*?[^*\s])?)\*(?![*\w])",
        r"<strong>\1</strong>",
        text,
        flags=re.DOTALL,
    )
    return text


def text_to_html(text: str) -> str:
    """Texto humano → HTML seguro: html.escape + bold markdown → <strong> + `\\n` → `<br>`."""
    return _md_bold_to_html(_html.escape(text)).replace("\n", "<br>")


def media_html(media_url: str, media_type: str, caption: str = "") -> str:
    """Snippet HTML pra embutir mídia no email por URL (porte do legado `_email_media_html`).

    image → `<img src=URL>` inline; video/audio/document → ícone + link clicável. O cliente de email
    (ex.: Gmail) busca a URL pública. Usado como `content` com `render(..., content_is_html=True)`.
    """
    if media_type not in MEDIA_TYPES:
        media_type = "document"
    safe_url = _html.escape(media_url)
    safe_caption = _html.escape(caption)

    if media_type == "image":
        return (
            '<div style="margin:20px 0;text-align:center">'
            f'<img src="{safe_url}" alt="{safe_caption}" '
            'style="max-width:100%;height:auto;border-radius:4px">'
            '<p style="margin:8px 0 0;color:#666;font-size:14px;font-family:Arial,sans-serif">'
            f"{safe_caption}</p>"
            "</div>"
        )
    if media_type == "video":
        return (
            '<div style="margin:20px 0;text-align:center">'
            '<p style="font-size:40px;margin:0">&#9654;&#65039;</p>'
            f'<p style="margin:8px 0;font-family:Arial,sans-serif;font-size:15px;color:#333">'
            f"{safe_caption}</p>"
            f'<a href="{safe_url}" target="_blank" '
            'style="color:#1a73e8;font-family:Arial,sans-serif;font-size:14px">'
            "Assistir v&iacute;deo</a>"
            "</div>"
        )
    if media_type == "audio":
        return (
            '<div style="margin:20px 0;text-align:center">'
            '<p style="font-size:36px;margin:0">&#127911;</p>'
            f'<p style="margin:8px 0;font-family:Arial,sans-serif;font-size:15px;color:#333">'
            f"{safe_caption}</p>"
            f'<a href="{safe_url}" target="_blank" '
            'style="color:#1a73e8;font-family:Arial,sans-serif;font-size:14px">'
            "Ouvir &aacute;udio</a>"
            "</div>"
        )
    safe_name = _html.escape(
        media_url.rsplit("/", 1)[-1] if "/" in media_url else "arquivo"
    )
    return (
        '<div style="margin:20px 0;text-align:center">'
        '<p style="font-size:36px;margin:0">&#128206;</p>'
        f'<p style="margin:4px 0;font-family:Arial,sans-serif;font-size:13px;color:#666">'
        f"{safe_name}</p>"
        f'<p style="margin:8px 0;font-family:Arial,sans-serif;font-size:15px;color:#333">'
        f"{safe_caption}</p>"
        f'<a href="{safe_url}" target="_blank" '
        'style="color:#1a73e8;font-family:Arial,sans-serif;font-size:14px">Baixar arquivo</a>'
        "</div>"
    )


@lru_cache(maxsize=32)
def _load(slug: str) -> str:
    return (_TEMPLATES_DIR / f"{slug}.html").read_text(encoding="utf-8")


def render(
    slug: str | None,
    *,
    title: str,
    content: str,
    content_is_html: bool = False,
) -> str:
    """Renderiza o template do slug (fallback `default`), trocando os placeholders.

    title/content são humanos → escapados (XSS-safe). content em texto recebe bold markdown →
    <strong> e `\\n` → `<br>`. content_is_html=True quando o caller já montou HTML.
    `{{service_name}}` = settings.MAIL_FROM_NAME.
    """
    resolved = slug if (slug and _SLUG_RE.match(slug)) else DEFAULT_SLUG
    try:
        template = _load(resolved)
    except FileNotFoundError:
        if resolved == DEFAULT_SLUG:
            raise TemplateNotFound("template 'default' ausente em templates/") from None
        try:
            template = _load(DEFAULT_SLUG)
        except FileNotFoundError:
            raise TemplateNotFound("template 'default' ausente em templates/") from None

    safe_title = _html.escape(title)
    if content_is_html:
        safe_content = content
    else:
        safe_content = _md_bold_to_html(_html.escape(content)).replace("\n", "<br>")
    return (
        template.replace("{{title}}", safe_title)
        .replace("{{content}}", safe_content)
        .replace("{{service_name}}", _html.escape(settings.MAIL_FROM_NAME))
    )
