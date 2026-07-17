"""Testes PUROS de notify.interface.templates.render — substituição de placeholders.
Função sem I/O, sem banco (nada de django_db)."""

from notify.interface.templates import render


def test_placeholder_simples():
    assert render("Olá {nome}!", {"nome": "João"}) == "Olá João!"


def test_placeholder_hifen():
    """{nome-completo} funciona via alias hífen→underscore."""
    assert render("Sr. {nome-completo}", {"nome_completo": "João Silva"}) == "Sr. João Silva"


def test_placeholder_ausente_fica_literal():
    """Placeholder não-declarado no ctx fica como está (não quebra envio)."""
    assert render("Oi {nome}, valor {valor}", {"nome": "João"}) == "Oi João, valor {valor}"


def test_alias_nome_name():
    """{nome} casa ctx['name'] e vice-versa (interop legado↔novo)."""
    assert render("Oi {nome}", {"name": "Maria"}) == "Oi Maria"
    assert render("Oi {name}", {"nome": "Maria"}) == "Oi Maria"


def test_alias_hifen_underscore():
    """{nome-completo} casa ctx['nome_completo']."""
    assert render("{nome-completo}", {"nome_completo": "A B"}) == "A B"


def test_multiplos_placeholders():
    got = render("{nome} pagou {valor}", {"nome": "João", "valor": "R$ 50"})
    assert got == "João pagou R$ 50"


def test_vazio():
    assert render("", {"x": "y"}) == ""
    assert render(None, {"x": "y"}) == ""


def test_sem_ctx():
    assert render("texto fixo", {}) == "texto fixo"


def test_placeholder_numerico_ignorado():
    """{123} não é placeholder (regex exige letra inicial)."""
    assert render("{123}", {}) == "{123}"


def test_placeholder_com_underscore():
    """{meu_campo} funciona normalmente."""
    assert render("{meu_campo}", {"meu_campo": "ok"}) == "ok"
