"""Onda 4 da auditoria: G17 (teto de IA conta só sucesso) e G13 (re-upload não deixa PII órfã)."""

import os
import tempfile

import pytest

pytestmark = pytest.mark.django_db


# ───────────────────────── G17: teto de IA ─────────────────────────
def test_g17_budget_conta_so_sucesso(monkeypatch):
    """`budget_exceeded` deve contar só AiCall SUCCESS. Antes contava tentativas de fallback que
    falharam (ERROR), derrubando o bot em ~metade do orçamento real."""
    from django.conf import settings

    from bot.ratelimit import AI_CALLER, budget_exceeded
    from integrations.ai.models import AiCall

    monkeypatch.setattr(settings, "BOT_DAILY_AI_CAP", 2)

    # 3 tentativas ERROR (fallback que falhou) + 1 SUCCESS = 1 gasto real, abaixo do cap 2
    for _ in range(3):
        AiCall.objects.create(
            caller=AI_CALLER,
            provider="p",
            operation=AiCall.Operation.TEXT,
            model="m",
            status=AiCall.Status.ERROR,
            latency_ms=0,
        )
    AiCall.objects.create(
        caller=AI_CALLER,
        provider="p",
        operation=AiCall.Operation.TEXT,
        model="m",
        status=AiCall.Status.SUCCESS,
        latency_ms=0,
    )

    assert budget_exceeded() is False, "erros de fallback contaram no teto"

    # +2 SUCCESS → 3 >= cap 2 → estourou
    for _ in range(2):
        AiCall.objects.create(
            caller=AI_CALLER,
            provider="p",
            operation=AiCall.Operation.TEXT,
            model="m",
            status=AiCall.Status.SUCCESS,
            latency_ms=0,
        )
    assert budget_exceeded() is True


# ───────────────────────── G13: re-upload não deixa órfã ─────────────────────────
def test_g13_replace_media_deleta_antigo(monkeypatch):
    from django.conf import settings
    from django.core.files.storage import default_storage

    from core.media import replace_media

    root = tempfile.mkdtemp()
    monkeypatch.setattr(settings, "MEDIA_ROOT", root)

    old = replace_media(old=None, prefix="selfie", data=b"foto A", ext="jpg")
    assert default_storage.exists(old)

    new = replace_media(old=old, prefix="selfie", data=b"foto B", ext="jpg")
    assert default_storage.exists(new)
    assert not default_storage.exists(old), "selfie antiga ficou órfã no storage"
    assert new != old


def test_g13_primeiro_upload_sem_antigo():
    """old=None (1º upload) não quebra."""
    import tempfile as _t

    from django.conf import settings
    from django.core.files.storage import default_storage

    from core.media import replace_media

    settings.MEDIA_ROOT = _t.mkdtemp()
    p = replace_media(old=None, prefix="selfie", data=b"x", ext="jpg")
    assert default_storage.exists(p)
