"""Testes PUROS de notify.sanitize.for_tts — limpeza de texto pra leitura em voz (TTS).
Função sem I/O, sem banco (nada de django_db)."""

from notify.sanitize import for_tts


def test_url_vira_o_link():
    assert for_tts("veja https://m33.live/x agora") == "veja o link agora"


def test_url_www():
    assert for_tts("acesse www.exemplo.com") == "acesse o link"


def test_multiplas_urls():
    got = for_tts("https://a.com e http://b.com")
    assert "https://" not in got
    assert "http://" not in got
    assert "o link" in got


def test_emoji_removido():
    assert for_tts("parabéns 🎉") == "parabéns"


def test_markdown_removido():
    assert for_tts("**negrito** e _itálico_") == "negrito e itálico"


def test_til_crase_removidos():
    assert for_tts("`code` e ~strike~") == "code e strike"


def test_quebra_vira_pausa():
    assert for_tts("linha1\nlinha2") == "linha1. linha2"


def test_multiplas_quebras_viram_uma_pausa():
    got = for_tts("a\n\n\nb")
    assert got == "a. b"


def test_pontuacao_nao_acumula():
    # "texto!.\s" → "texto! " (não "texto!.")
    assert for_tts("tudo bem!\nok") == "tudo bem! ok"


def test_espacos_repetidos_colapsam():
    assert for_tts("muito  espaços   aqui") == "muito espaços aqui"


def test_espaco_antes_pontuacao_removido():
    assert for_tts("oi , tudo ?") == "oi, tudo?"


def test_link_word_customizavel():
    assert for_tts("veja https://x.com", link_word="o site") == "veja o site"


def test_vazio():
    assert for_tts("") == ""
    assert for_tts(None) == ""


def test_texto_limpo_passa_igual():
    assert for_tts("oi tudo bem") == "oi tudo bem"


def test_pontuacao_final_nao_acumula_ponto():
    """'frase1.\\sfrase2' não vira 'frase1.\\s.sentece2'."""
    assert for_tts("fim.\ninício") == "fim. início"
