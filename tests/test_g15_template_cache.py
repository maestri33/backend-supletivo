"""G15 — cache de Template: (#26) um erro transitório de DB gravava None PERMANENTE no negative
cache, e o evento passava a ignorar o Template do DB pra sempre; (#24) o cache module-level não é
invalidado no worker (o signal é in-process), então sem TTL um Template editado ficava stale.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.django_db


def test_g15_erro_db_nao_envenena_cache(monkeypatch):
    from notify.interface import templates as t

    t.invalidate()
    calls = {"n": 0}

    def flaky_filter(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db blip transitório")
        m = MagicMock()
        m.first.return_value = None  # 2ª: DB ok, evento sem row
        return m

    monkeypatch.setattr(t.Template.objects, "filter", flaky_filter)

    assert t.get("evt.x") is None  # 1ª: erro → None, mas NÃO cacheia
    assert t.get("evt.x") is None  # 2ª: re-tenta o DB (não ficou preso no None)
    assert calls["n"] == 2, (
        "erro de DB envenenou o cache — a 2ª chamada não re-consultou o DB"
    )


def test_g15_valor_bom_e_cacheado_dentro_do_ttl(monkeypatch):
    """Não-regressão: um valor válido é cacheado (não consulta o DB toda vez dentro do TTL)."""
    from notify.interface import templates as t

    t.invalidate()
    calls = {"n": 0}

    def counting_filter(**kw):
        calls["n"] += 1
        m = MagicMock()
        m.first.return_value = None
        return m

    monkeypatch.setattr(t.Template.objects, "filter", counting_filter)

    t.get("evt.y")
    t.get("evt.y")
    assert calls["n"] == 1, "valor cacheado foi re-consultado dentro do TTL"


def test_g15_tem_ttl():
    """O cache tem TTL (limita staleness cross-process — o worker não recebe o signal)."""
    from notify.interface import templates as t

    assert t._CACHE_TTL_S > 0
