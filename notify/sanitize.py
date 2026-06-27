"""Sanitização de conteúdo de notificações para diferentes canais.

O TTS (text-to-speech) precisa de texto limpo: sem emojis, sem markdown, sem URLs longas.
WhatsApp e e-mail podem ter a formatação completa.
"""

import re


def sanitize_for_tts(text: str) -> str:
    """Remove emojis, markdown e limpa URLs para síntese de voz.

    Transformações:
    - Remove emojis (caracteres Unicode de símbolos/emojis)
    - Remove markdown bold/italic (**texto**, *texto*)
    - Simplifica URLs (mantém só "link" em vez da URL completa)
    - Remove quebras de linha extras
    - Normaliza espaços múltiplos
    """
    if not text:
        return text

    # Remove emojis (ranges Unicode de símbolos e emojis)
    # Ranges principais: emoticons, símbolos diversos, emojis modernos
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # símbolos & pictogramas
        "\U0001f680-\U0001f6ff"  # transporte & símbolos de mapa
        "\U0001f1e0-\U0001f1ff"  # bandeiras (iOS)
        "\U00002702-\U000027b0"  # dingbats
        "\U000024c2-\U0001f251"
        "\U0001f900-\U0001f9ff"  # suplemento de símbolos e pictogramas
        "\U0001fa00-\U0001fa6f"  # símbolos estendidos-A
        "\U00002600-\U000026ff"  # símbolos diversos
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)

    # Remove markdown bold (**texto** ou __texto__)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)

    # Remove markdown italic (*texto* ou _texto_) — cuidado com não pegar *s normais
    text = re.sub(r"\*([^*\s][^*]*?)\*", r"\1", text)
    text = re.sub(r"_([^_\s][^_]*?)_", r"\1", text)

    # Simplifica URLs: substitui URLs completas por "link"
    # Captura http:// ou https:// até o próximo espaço/quebra
    text = re.sub(r"https?://[^\s]+", "link", text)

    # Remove quebras de linha múltiplas (max 2 consecutivas = 1 parágrafo)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Normaliza espaços múltiplos
    text = re.sub(r" {2,}", " ", text)

    # Remove espaços no início/fim de cada linha
    text = "\n".join(line.strip() for line in text.split("\n"))

    return text.strip()
