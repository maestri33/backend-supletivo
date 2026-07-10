"""G9 — bypass de KYC: o chain-skip de ADDRESS pulava a etapa checando só `is_complete`, sem exigir
o comprovante de residência APROVADO (que a transição normal `_advance_address` exige). Como o
Address é compartilhado por external_id entre funis, um endereço preenchido em outro funil fazia o
aluno pular a validação do comprovante.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


class _Enr:
    class user:
        external_id = "u1"

    status = None


def _run_advance_to_address(*, is_approved: bool) -> str:
    from users.roles.enrollment import service as es

    captured = {}
    with (
        patch.object(es.address_iface, "is_complete", return_value=True),
        patch.object(es.address_iface, "get_by_external_id", return_value=object()),
        patch("users.roles._address_proof.is_approved", return_value=is_approved),
        patch.object(es, "_has_education", return_value=False),
        patch.object(
            es, "_set_status", side_effect=lambda enr, st: captured.update(st=st)
        ),
    ):
        es._advance_to(_Enr(), es._S.ADDRESS)
    return captured["st"]


def test_g9_nao_pula_address_sem_comprovante_aprovado():
    """Endereço completo mas comprovante NÃO aprovado → PARA em ADDRESS (não pula o gate KYC)."""
    from users.roles.enrollment import service as es

    assert _run_advance_to_address(is_approved=False) == es._S.ADDRESS


def test_g9_pula_address_com_comprovante_aprovado():
    """Não-regressão: com comprovante aprovado, o chain-skip pula ADDRESS normalmente."""
    from users.roles.enrollment import service as es

    assert _run_advance_to_address(is_approved=True) == es._S.EDUCATION
