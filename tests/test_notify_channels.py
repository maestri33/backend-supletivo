"""Testes PUROS de notify.models._parse_channels — parsing de canais CSV.
Função sem I/O, sem banco (nada de django_db)."""

from notify.models import _parse_channels


def test_csv_simples():
    assert _parse_channels("whatsapp,email") == ["whatsapp", "email"]


def test_espacos():
    assert _parse_channels(" whatsapp , email ") == ["whatsapp", "email"]


def test_case_insensitive():
    assert _parse_channels("WhatsApp,Email") == ["whatsapp", "email"]


def test_canal_invalido_ignorado():
    assert _parse_channels("whatsapp,fax,email") == ["whatsapp", "email"]


def test_vazio():
    assert _parse_channels("") == []
    assert _parse_channels(None) == []


def test_somente_espacos():
    assert _parse_channels("   ") == []


def test_um_canal():
    assert _parse_channels("tts") == ["tts"]


def test_todos_os_canais():
    got = _parse_channels("whatsapp,email,tts")
    assert got == ["whatsapp", "email", "tts"]
