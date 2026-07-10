"""baixa/#34 — o worker do bot ligava a resposta ao AiCall adivinhando pelo timestamp
(caller+created_at), e sob 2 workers simultâneos podia pegar o AiCall de OUTRO atendimento (auditoria
de custo trocada). Fix: ia.chat(return_call=True) devolve o AiCall EXATO desta chamada.
"""

from unittest.mock import MagicMock


def test_chat_sem_return_call_devolve_str(monkeypatch):
    """Compat: chat() sem return_call continua devolvendo só a string."""
    from integrations.ai import service as ai

    monkeypatch.setattr(
        ai, "_run", lambda *a, **k: (MagicMock(content="resposta"), "p", "m", object())
    )
    out = ai.chat([{"role": "user", "content": "oi"}], caller="x")
    assert out == "resposta"


def test_chat_com_return_call_devolve_o_aicall_desta_chamada(monkeypatch):
    """return_call=True → (texto, AiCall) — o AiCall exato que ESTA chamada gerou (determinístico)."""
    from integrations.ai import service as ai

    the_call = MagicMock(name="AiCall")
    monkeypatch.setattr(
        ai, "_run", lambda *a, **k: (MagicMock(content="resposta"), "p", "m", the_call)
    )
    text, call = ai.chat(
        [{"role": "user", "content": "oi"}], caller="x", return_call=True
    )
    assert text == "resposta"
    assert call is the_call, "não devolveu o AiCall desta chamada"


def test_worker_liga_por_return_call_nao_por_timestamp():
    """Regressão: o worker usa ia.chat(return_call=True), não a busca por timestamp que trocava
    o AiCall sob concorrência."""
    import inspect

    import bot.worker as w

    src = inspect.getsource(w)
    assert "return_call=True" in src, "o worker não usa o AiCall determinístico"
    assert "created_at__gte=before" not in src, (
        "o worker ainda adivinha o AiCall por timestamp"
    )
