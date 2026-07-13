"""Sanitização de texto para TTS (voz) — função PURA, sem I/O.

O texto de uma Notification é escrito para LEITURA (markdown do WhatsApp, links, emojis). Lido em
voz alta pelo TTS isso vira ruído: `*` vira pausa estranha, uma URL é soletrada caractere a
caractere, emoji vira o nome do emoji. `for_tts` limpa o texto ANTES de gerar o áudio, sem alterar
o texto exibido (WhatsApp/e-mail seguem com o original).

Conservador de propósito: remove marcação/ruído, NÃO reescreve conteúdo nem expande valores (não
inventa — CONVENTION §8). A única troca semântica é URL → uma palabra falável ("o link"): uma URL
lida em voz alta é inútil pro destinatário.
"""

from __future__ import annotations

import re

# marcadores de markdown do WhatsApp/Markdown (negrito/itálico/risco/mono).
_MD_MARKERS = re.compile(r"[*_~`]+")
# URL http(s) ou www — falada é inútil; troca por uma palavra.
_URL = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
# emojis e pictogramas (faixas unicode comuns) + símbolos/dingbats/setas soltos.
_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoticons, símbolos & pictogramas, transporte, suplementares
    "\U00002600-\U000027bf"  # misc symbols & dingbats (inclui ✅ �e afins)
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U00002190-\U000021ff"  # setas
    "\U00002b00-\U00002bff"  # setas/símbolos diversos
    "\U0000200d"  # zero-width joiner (emoji compostos)
    "]+",
    flags=re.UNICODE,
)
_MULTISPACE = re.compile(r"[ \t]{2,}")

# --- WhatsApp: markdown → marcação nativa do WhatsApp ---------------------------------
# O WhatsApp usa `*x*` p/ negrito e `_x_` p/ itálico, e não renderiza `[t](u)` nem headings.
# `**x**`/`__x__` (negrito md) → `*x*`; `*x*` (itálico md) → `_x_`; `[t](u)` → `t (u)`.
_WA_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_WA_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*")
_WA_BOLD_UNDER = re.compile(r"__(.+?)__")
_WA_ITALIC = re.compile(r"\*([^*\n]+?)\*")
_WA_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*")
_WA_QUOTE = re.compile(r"(?m)^[ \t]{0,3}>[ \t]?")
_BOLD_TOKEN = "\x00"  # placeholder p/ negrito, evita colidir com a troca do itálico


def for_whatsapp(md: str | None) -> str:
    """Converte markdown (o mesmo body do e-mail) para a marcação NATIVA do WhatsApp.

    `**x**`/`__x__` → `*x*` (negrito); `*x*` → `_x_` (itálico); `[t](u)` → `t (u)`; remove
    `#`/`>` de heading/citação. Preserva emojis e quebras de linha. Entrada vazia → "".
    """
    if not md:
        return ""
    out = _WA_LINK.sub(r"\1 (\2)", md)
    # negrito primeiro, tokenizado, senão o `*` resultante seria pego pela troca do itálico.
    out = _WA_BOLD_STAR.sub(rf"{_BOLD_TOKEN}\1{_BOLD_TOKEN}", out)
    out = _WA_BOLD_UNDER.sub(rf"{_BOLD_TOKEN}\1{_BOLD_TOKEN}", out)
    out = _WA_ITALIC.sub(r"_\1_", out)
    out = out.replace(_BOLD_TOKEN, "*")
    out = _WA_HEADING.sub("", out)
    out = _WA_QUOTE.sub("", out)
    return out


def for_tts(text: str | None, *, link_word: str = "o link") -> str:
    """Limpa `text` para leitura em voz (TTS). Devolve a string pronta pro provider de TTS.

    - URLs → `link_word` (uma URL soletrada é ruído).
    - remove emojis e marcadores de markdown (asterisco, underscore, til, crase).
    - quebras de linha → pausa de frase; espaços repetidos colapsados.
    NÃO reescreve conteúdo nem expande valores (não inventa — §8). Entrada vazia → "".
    """
    if not text:
        return ""
    out = _URL.sub(link_word, text)
    out = _EMOJI.sub("", out)
    out = _MD_MARKERS.sub("", out)
    # quebras de linha viram pausa de frase (voz flui melhor que com silêncio cru).
    out = re.sub(r"\s*\n+\s*", ". ", out)
    # se a linha já terminava em pontuação, não acumula um ponto extra ("texto!. " → "texto! ").
    out = re.sub(r"([.!?;:])\.\s", r"\1 ", out)
    out = re.sub(r"\.\s*\.", ". ", out)  # ".. " → ". "
    out = _MULTISPACE.sub(" ", out)
    out = re.sub(r"\s+([.,!?;:])", r"\1", out)  # espaço antes de pontuação
    return out.strip()
