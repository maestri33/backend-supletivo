"""Gate de /media/ privado (G1 da auditoria): o classificador olhava só o 1º segmento do path,
então `training/../documents/<tok>.jpg` era classificado como público (`training`) e servido SEM
token — apesar de o arquivo final ser privado (`documents`). Reproduzido end-to-end na auditoria:
acesso direto → 401, mesmo arquivo via `../` → 200 com o conteúdo do RG.

O gate de DONO (o mesmo token servir só pro dono) é uma limitação de design declarada na docstring
do módulo (não há índice token→owner) — fora do escopo deste fix. Aqui travamos o acesso
NÃO-AUTENTICADO por normalização de path, que é o vetor crítico.
"""

import os
import tempfile

import pytest
from django.conf import settings
from django.test import RequestFactory

from core.media_views import media_serve


@pytest.fixture
def media_root(monkeypatch):
    root = tempfile.mkdtemp()
    monkeypatch.setattr(settings, "MEDIA_ROOT", root)
    os.makedirs(f"{root}/documents")
    os.makedirs(f"{root}/training")
    with open(f"{root}/documents/rg_secreto.jpg", "wb") as fh:
        fh.write(b"RG PRIVADO DE TERCEIRO")
    with open(f"{root}/training/publico.jpg", "wb") as fh:
        fh.write(b"material publico")
    return root


def _status(path):
    return media_serve(RequestFactory().get(f"/media/{path}"), path).status_code


def test_privado_direto_sem_token_401(media_root):
    assert _status("documents/rg_secreto.jpg") == 401


def test_traversal_para_privado_sem_token_bloqueado(media_root):
    """O CORE do G1: mudar de prefixo com `../` não pode escapar do gate."""
    assert _status("training/../documents/rg_secreto.jpg") == 401


def test_publico_serve_sem_token(media_root):
    assert _status("training/publico.jpg") == 200


def test_traversal_para_fora_do_root_nao_vaza(media_root):
    """`../../etc/passwd` normaliza pra dentro do root e não acha nada → Http404 (=404 no stack),
    nunca serve /etc/passwd nem estoura SuspiciousFileOperation (500)."""
    from django.http import Http404

    with pytest.raises(Http404):
        _status("../../../../etc/passwd")
