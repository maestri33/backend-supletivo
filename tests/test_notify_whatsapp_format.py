"""Testes PUROS de notify.sanitize.for_whatsapp — conversão de markdown p/ marcação nativa do
WhatsApp. Função sem I/O, sem banco (nada de django_db)."""

from notify.sanitize import for_whatsapp


def test_negrito_asterisco_duplo():
    assert for_whatsapp("**oi**") == "*oi*"


def test_negrito_underscore_duplo():
    assert for_whatsapp("__oi__") == "*oi*"


def test_italico_vira_underscore():
    assert for_whatsapp("*oi*") == "_oi_"


def test_negrito_e_italico_juntos():
    # negrito não pode ser convertido pra itálico por engano
    assert for_whatsapp("**forte** e *leve*") == "*forte* e _leve_"


def test_link_markdown():
    assert (
        for_whatsapp("[clique aqui](https://m33.live/x)")
        == "clique aqui (https://m33.live/x)"
    )


def test_heading_e_quote_removidos():
    assert for_whatsapp("# Titulo\n> citacao") == "Titulo\ncitacao"


def test_preserva_emoji_e_quebras():
    assert for_whatsapp("linha1 ✅\nlinha2") == "linha1 ✅\nlinha2"


def test_vazio():
    assert for_whatsapp("") == ""
    assert for_whatsapp(None) == ""


def test_titulo_prefixado_no_body_do_whatsapp():
    """Quando há title, o body do WhatsApp vira `*{title}*\\n\\n{corpo convertido}`."""

    class _Notif:
        title = "Boleto disponível"
        text = "Seu **boleto** já está [aqui](https://m33.live/b)."

    from notify.dispatch import _whatsapp_body

    out = _whatsapp_body(_Notif())
    assert out == (
        "*Boleto disponível*\n\nSeu *boleto* já está aqui (https://m33.live/b)."
    )
