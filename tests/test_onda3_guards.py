"""Onda 3 da auditoria: G20 (gate staff-health), G18 (CoT truncado), G12 (blood_type)."""

import pytest


# ───────────────────────── G12: blood_type ─────────────────────────
@pytest.mark.parametrize(
    "texto,esperado",
    [
        # #22: AB voltou a registrar (antes colidia com "B+" por substring)
        ("AB+", "AB+"),
        ("AB-", "AB-"),
        ("meu tipo é AB+", "AB+"),
        # forma direta comum, sem contexto necessário
        ("A+", "A+"),
        ("O-", "O-"),
        ("é B+", "B+"),
        # #6: frase com artigo "o"/"a" + adjetivo NÃO é tipo sanguíneo (era o pior: gravava errado)
        ("o positivo é que já paguei", None),
        ("a negativa foi a resposta", None),
        # forma por extenso SÓ com contexto de sangue
        ("meu tipo sanguineo é A positivo", "A+"),
        ("sangue O negativo", "O-"),
        # forma por extenso SEM contexto → None (motor pede no formato A+)
        ("A positivo", None),
        # ambíguo / vazio
        ("tenho A+ ou B+, não sei", None),
        ("não faço ideia", None),
        ("", None),
    ],
)
def test_g12_blood_type(texto, esperado):
    from bot.extract import blood_type

    assert blood_type(texto) == esperado


# ───────────────────────── G18: CoT truncado não vaza ─────────────────────────
def test_g18_think_fechado_removido():
    from integrations.ai.service import _strip_think

    assert _strip_think("<think>raciocínio</think>Olá!") == "Olá!"


def test_g18_think_truncado_sem_fechamento_removido():
    """<think> aberto sem </think> (resposta cortada por max_tokens) — o raciocínio cru não pode
    chegar ao WhatsApp. Antes vazava (o regex não casava o par)."""
    from integrations.ai.service import _strip_think

    truncado = "Resposta parcial <think>agora vou pensar: o cliente pediu"
    out = _strip_think(truncado)
    assert "pensar" not in out
    assert out == "Resposta parcial"


# ───────────────────────── G20: gate de staff-health ─────────────────────────
def test_g20_health_usa_require_superuser():
    """O gate estava `require_roles(..., 'staff')`, que sempre 403 (staff não é role, é
    is_superuser) — barrava até o superuser. Deve usar require_superuser."""
    import inspect

    import api.health as health

    src = inspect.getsource(health)
    assert "require_superuser(request.auth)" in src
    assert 'require_roles(request.auth, "staff")' not in src
