"""Tests para sanitização de conteúdo de notificações (TTS)."""

from notify.sanitize import sanitize_for_tts


def test_sanitize_removes_emojis():
    """Remove emojis do texto para TTS."""
    text = "Olá! 🎉 Bem-vindo, João! 💚 Sua matrícula foi aprovada. ✅"
    result = sanitize_for_tts(text)
    assert "🎉" not in result
    assert "💚" not in result
    assert "✅" not in result
    assert "Olá!" in result
    assert "Bem-vindo, João!" in result
    assert "Sua matrícula foi aprovada." in result


def test_sanitize_removes_markdown_bold():
    """Remove formatação markdown bold (**texto**)."""
    text = "Sua **matrícula** está **aprovada**."
    result = sanitize_for_tts(text)
    assert "**" not in result
    assert "Sua matrícula está aprovada." == result


def test_sanitize_removes_markdown_italic():
    """Remove formatação markdown italic (*texto*)."""
    text = "Este é um *teste* de *sanitização*."
    result = sanitize_for_tts(text)
    assert result == "Este é um teste de sanitização."


def test_sanitize_simplifies_urls():
    """Substitui URLs completas por 'link'."""
    text = "Acesse: https://example.com/path?query=1 para mais informações"
    result = sanitize_for_tts(text)
    assert "https://" not in result
    assert "example.com" not in result
    assert "Acesse: link para mais informações" == result


def test_sanitize_normalizes_whitespace():
    """Remove espaços múltiplos e quebras de linha extras."""
    text = "Texto  com    espaços\n\n\n\nvárias linhas"
    result = sanitize_for_tts(text)
    assert "  " not in result
    assert "\n\n\n" not in result
    assert result == "Texto com espaços\n\nvárias linhas"


def test_sanitize_real_notification():
    """Testa com exemplo real de notificação do sistema."""
    text = (
        "Olá, João! 🎉 Que bom ter você com a gente. Seu cadastro está pronto, João — "
        "falta só um passo pra garantir sua vaga: concluir o pagamento. Em instantes envio o link. "
        "Bora juntos nessa jornada!"
    )
    result = sanitize_for_tts(text)
    assert "🎉" not in result
    assert "Olá, João!" in result
    assert "Que bom ter você com a gente" in result
    assert "Seu cadastro está pronto, João" in result


def test_sanitize_with_urls_and_emojis():
    """Testa texto com URLs e emojis juntos."""
    text = "João, aqui está o link: https://example.com/payment 💸 Pague quando puder! ✅"
    result = sanitize_for_tts(text)
    assert "https://" not in result
    assert "💸" not in result
    assert "✅" not in result
    assert "João, aqui está o link: link Pague quando puder!" == result


def test_sanitize_empty_text():
    """Texto vazio ou None retorna sem erro."""
    assert sanitize_for_tts("") == ""
    assert sanitize_for_tts(None) is None


def test_sanitize_preserves_punctuation():
    """Preserva pontuação importante para TTS."""
    text = "Olá, João! Como vai? Tudo bem. Sua matrícula: aprovada."
    result = sanitize_for_tts(text)
    assert "," in result
    assert "!" in result
    assert "?" in result
    assert "." in result
    assert ":" in result
