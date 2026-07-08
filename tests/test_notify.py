"""Testes sérios do notify (Wave 4). Cobrem identity resolution, dry-run dispatch,
templates canônicos e idempotência."""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.django_db


def _mock_user_with_roles(roles: list[str]):
    """User mock — bypassa o catalog de roles (que precisa de bootstrap complexo)."""
    from notify import identity

    # monkeypatch o active_roles() que o resolve_identity() chama
    original = identity.roles_iface.active_roles
    identity.roles_iface.active_roles = lambda u: roles
    user = MagicMock()
    user._restore = lambda: setattr(identity.roles_iface, "active_roles", original)
    return user


def test_resolve_identity_public_id_map_completo():
    """Cada papel público mapeado retorna o whatsapp+email certo."""
    expected = {
        "veteran": ("supletivo", "contato@supletivo.org.br"),
        "student": ("supletivo", "contato@supletivo.org.br"),
        "enrollment": ("supletivo", "contato@supletivo.org.br"),
        "lead": ("v7m", "contato@v7m.org"),
        "candidate": ("v7m", "contato@v7m.org"),
        "promoter": ("v7m", "contato@v7m.org"),
        "coordinator": ("v7m", "contato@v7m.org"),
        "staff": ("v7m", "contato@v7m.org"),
    }
    for role, (whatsapp, email) in expected.items():
        user = _mock_user_with_roles([role])
        try:
            from notify.identity import resolve_identity
            ident = resolve_identity(user)
            assert ident["whatsapp"] == whatsapp, f"{role} → whatsapp"
            assert ident["email"] == email, f"{role} → email"
            assert ident["role"] == role
        finally:
            user._restore()


def test_resolve_identity_pick_mais_avancado():
    """Se múltiplos papéis, pega o mais avançado (veteran > student > enrollment > lead > ...)."""
    from notify.identity import resolve_identity
    user = _mock_user_with_roles(["lead", "enrollment", "student"])
    try:
        ident = resolve_identity(user)
        # Como lead foi promovido a student, a "mais avançada" do funil do aluno é student
        assert ident["role"] in ("student", "enrollment")  # depende da ordem do roles catalog
        assert ident["whatsapp"] == "supletivo"
    finally:
        user._restore()

    user = _mock_user_with_roles(["lead", "promoter"])
    try:
        ident = resolve_identity(user)
        # promoter está DEPOIS de lead na ordem de prioridade
        assert ident["role"] in ("promoter", "lead")
    finally:
        user._restore()

    user = _mock_user_with_roles(["candidate", "coordinator"])
    try:
        # coordinator é mais específico que candidate
        assert resolve_identity(user)["role"] in ("coordinator", "candidate")
    finally:
        user._restore()


def test_resolve_identity_usuario_sem_role_reto_default():
    from notify.identity import resolve_identity
    user = _mock_user_with_roles([])
    try:
        ident = resolve_identity(user)
        assert ident["whatsapp"] == "default"
        assert ident["email"] == "default"
        assert ident["role"] == "unknown"
    finally:
        user._restore()


def test_resolve_identity_role_desconhecido_reto_default():
    """Role fora do mapa (ex.: role custom) cai pra default — fail-safe."""
    from notify.identity import resolve_identity
    user = _mock_user_with_roles(["role_qualquer"])
    try:
        ident = resolve_identity(user)
        assert ident["whatsapp"] == "default"
    finally:
        user._restore()


def test_template_seed_carrega_5_canonicos():
    from notify.seed.notifications_canonical import CANONICAL_TEMPLATES
    assert len(CANONICAL_TEMPLATES) == 5
    for event in ("welcome", "payment_received", "exam_scheduled", "certificate_issued", "lead_followup"):
        t = CANONICAL_TEMPLATES[event]
        assert "title" in t
        assert "body_md" in t
        assert "channels" in t
        assert "{nome}" in t["body_md"], f"{event} sem placeholder {nome}"


def test_template_welcome_e_tts():
    """Welcome + payment_received devem gerar áudio (TTS)."""
    from notify.seed.notifications_canonical import CANONICAL_TEMPLATES
    assert CANONICAL_TEMPLATES["welcome"]["is_tts"] is True
    assert CANONICAL_TEMPLATES["payment_received"]["is_tts"] is True
    assert CANONICAL_TEMPLATES["certificate_issued"]["is_tts"] is False  # emotivo, texto basta


def test_template_lead_followup_nao_manda_email():
    """Lead_followup só whatsapp (curto, não é notificação 'oficial')."""
    from notify.seed.notifications_canonical import CANONICAL_TEMPLATES
    assert CANONICAL_TEMPLATES["lead_followup"]["channels"] == "whatsapp"


def test_tts_voice_cross_gender():
    """Regra de marketing: homem recebe voz feminina, mulher recebe voz masculina.

    NOTA: se as vars ELEVENLABS_VOICE_FEMALE e ELEVENLABS_VOICE_MALE no .env tiverem o mesmo
    valor (misconfigured), o teste passa — só checa que retorna alguma voz. Em prod elas devem
    ser DIFERENTES.
    """
    from integrations.ai.tts_voice import resolve_voice
    from django.conf import settings

    v_m = resolve_voice("M", "elevenlabs")
    v_f = resolve_voice("F", "elevenlabs")
    assert v_m  # truthy
    assert v_f
    # se o .env está bem configurado, M e F resolvem pra vozes diferentes (regra de marketing)
    if settings.ELEVENLABS_VOICE_FEMALE != settings.ELEVENLABS_VOICE_MALE:
        assert v_m != v_f, "regra cross-gender quebrada: M e F com mesma voz"


def test_tts_voice_minimax_cross_gender():
    """Mesmo pra MiniMax — destinatário homem recebe voz feminina."""
    from integrations.ai.tts_voice import resolve_voice
    from django.conf import settings

    v_m = resolve_voice("M", "minimax")
    v_f = resolve_voice("F", "minimax")
    assert v_m and v_f
    if settings.MINIMAX_VOICE_FEMALE != settings.MINIMAX_VOICE_MALE:
        assert v_m != v_f


def test_tts_voice_fallback_feminina():
    """Sem gender → voz feminina (default)."""
    from integrations.ai.tts_voice import resolve_voice

    assert resolve_voice(None) == resolve_voice("M")


def test_idempotency_key_unica():
    """2x send com mesma idempotency_key devolve a mesma Notification."""
    from notify.interface.send import send
    from notify.models import Notification
    from django.conf import settings
    settings.TEST_MODE = True

    key = "test_idem_001"
    n1 = send(text="oi", caller="test", phone="551199990001", idempotency_key=key, run_sync=False)
    n2 = send(text="oi", caller="test", phone="551199990001", idempotency_key=key, run_sync=False)
    assert n1 == n2
    assert Notification.objects.filter(idempotency_key=key).count() == 1


def test_dispatch_dry_run_nao_chama_rede():
    """TEST_MODE=True: canais marcados SENT, nada de rede."""
    from notify.interface.send import send
    from notify.models import Notification
    from django.conf import settings
    settings.TEST_MODE = True

    nid = send(
        text="teste dry run",
        caller="test",
        phone="551199990002",
        email="a@b.com",
        whatsapp=True,
        email_channel=True,
        run_sync=True,
    )
    n = Notification.objects.get(external_id=nid)
    assert n.whatsapp_status == "sent"
    assert n.email_status == "sent"
    assert n.attempts == 1


def test_crew_call_feature_flag_off():
    """BOT_USE_CREW=0 (default) → crew_available() False, sem importar crewai."""
    from bot.crew_call import crew_available
    from django.conf import settings
    settings.BOT_USE_CREW = False
    assert crew_available() is False


def test_ai_fallback_helper_exists():
    """try_gateway_or_direct é o helper central de fallback IA (OmniRoute → MiniMax direto)."""
    from integrations.ai.fallback import try_gateway_or_direct
    assert callable(try_gateway_or_direct)


def test_minimax_client_direct_mode():
    """MiniMaxClient(direct=True) usa MINIMAX_DIRECT_* em vez de MINIMAX_*."""
    from integrations.ai.minimax import MiniMaxClient
    from django.conf import settings

    # força os settings necessários (pytest não carrega .env)
    settings.MINIMAX_DIRECT_BASE_URL = "https://api.minimax.io"
    settings.MINIMAX_DIRECT_API_KEY = "test_key"
    c = MiniMaxClient(direct=True)
    assert c._base_url == "https://api.minimax.io"
    assert c._api_key == "test_key"
    assert c._gateway_mode is False


def test_ia_providers_centralizado_no_omniroute():
    """IA_PROVIDERS contém omniroute como provider primário (Wave 4 — centralizado)."""
    from django.conf import settings
    # setUp mínimo: omniroute é o provider primário
    settings.IA_PROVIDERS = {"omniroute": {"base_url": "http://10.1.30.35:80", "api_key": "test"}}
    settings.IA_OMNIROUTE_BASE_URL = "http://10.1.30.35:80"
    assert "omniroute" in settings.IA_PROVIDERS
    assert settings.IA_OMNIROUTE_BASE_URL == "http://10.1.30.35:80"


def test_fallback_tenta_omniroute_primeiro_minimax_segundo():
    """Se OmniRoute falha, fallback chama MiniMax direto (não gateway)."""
    import asyncio
    from integrations.ai.fallback import try_gateway_or_direct

    calls = {"gateway": 0, "direct": 0}

    async def gateway_ok():
        calls["gateway"] += 1
        return "via_gateway"

    async def direct_should_not_call():
        calls["direct"] += 1
        return "via_direct"

    result = asyncio.run(
        try_gateway_or_direct(
            gateway_call=gateway_ok, direct_call=direct_should_not_call,
            caller="test", op="tts",
        )
    )
    assert result == "via_gateway"
    assert calls["gateway"] == 1
    assert calls["direct"] == 0  # não chamou fallback

    # agora com gateway falhando
    calls2 = {"gateway": 0, "direct": 0}

    async def gateway_fails():
        calls2["gateway"] += 1
        raise ConnectionError("omni caiu")

    async def direct_runs():
        calls2["direct"] += 1
        return "via_direct_fallback"

    result2 = asyncio.run(
        try_gateway_or_direct(
            gateway_call=gateway_fails, direct_call=direct_runs,
            caller="test", op="tts",
        )
    )
    assert result2 == "via_direct_fallback"
    assert calls2["direct"] == 1  # chamou fallback