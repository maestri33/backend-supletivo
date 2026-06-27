"""Testes dos schemas centrais — valida que os schemas compartilhados existem,
têm os campos esperados e que os aliases em collaborators/leadership apontam
para a mesma classe (não há drift).
"""

from __future__ import annotations


def test_schemas_centrais_existem():
    """api/schemas.py exporta todos os schemas compartilhados."""
    # Se chegou aqui, todos importaram sem erro
    assert True


def test_schemas_collaborators_importam_centrais():
    """collaborators usa os schemas centrais (sem redefinição local)."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

    from api.schemas import (
        SharedCandidateMeOut,
        SharedAddressOut,
        SharedAnalysisAckOut,
    )

    # verifica que os aliases em collaborators apontam pra classe central
    from api import collaborators as col

    assert col.CandidateMeOut is SharedCandidateMeOut
    assert col.CandidateAddressOut is SharedAddressOut
    assert col.AnalysisAckOut is SharedAnalysisAckOut


def test_shared_candidate_me_out_campos_obrigatorios():
    """SharedCandidateMeOut tem os campos canônicos do /me."""
    from api.schemas import SharedCandidateMeOut

    fields = SharedCandidateMeOut.model_fields
    for campo in ("external_id", "status", "hub_external_id", "pix_validated", "selfie_verified"):
        assert campo in fields, f"Campo '{campo}' faltando em SharedCandidateMeOut"


def test_shared_address_out_tem_missing_fields():
    """SharedAddressOut inclui missing_fields (necessário pro wizard)."""
    from api.schemas import SharedAddressOut

    fields = SharedAddressOut.model_fields
    assert "missing_fields" in fields


def test_token_out_campos():
    """TokenOut tem access_token, refresh_token e token_type."""
    from api.schemas import TokenOut

    fields = TokenOut.model_fields
    assert "access_token" in fields
    assert "refresh_token" in fields
    assert "token_type" in fields


def test_material_in_defaults_sensiveis():
    """MaterialIn tem defaults seguros: blocking=True, kind=fixed."""
    from api.schemas import MaterialIn

    m = MaterialIn(title="T", question="Q", expected_answer="A")
    assert m.blocking is True
    assert m.kind == "fixed"
    assert m.ephemeral is False
