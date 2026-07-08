"""Contrato de adesão versionado no BACKEND (LGPD, lane #6).

Fonte da verdade do texto do contrato (antes hardcoded no front). Cada contrato carrega uma
VERSÃO (str) e o HASH SHA-256 do texto — é o que provamos ter sido aceito no ato da selfie
(a selfie É a assinatura). Bump `version` sempre que o texto mudar; o hash é derivado, nunca
digitado à mão.

Dois contratos: ALUNO (matrícula) e PROMOTOR (adesão do colaborador). Para publicar uma versão
"final", troque o texto e suba a `version`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# str do topo (spec da lane): versão canônica atual dos contratos.
CONTRACT_VERSION = "2026-07-08"


@dataclass(frozen=True)
class Contract:
    """Um contrato versionado. `hash` = sha256(text), derivado — prova a versão aceita."""

    version: str
    text: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        """Payload do GET /contract/current: {version, hash, text}."""
        return {"version": self.version, "hash": self.hash, "text": self.text}


_STUDENT_TEXT = """CONTRATO DE PRESTAÇÃO DE SERVIÇOS EDUCACIONAIS E TRATAMENTO DE DADOS

Pelo presente instrumento, o(a) ALUNO(A) adere ao serviço de preparação e certificação supletiva,
autorizando o tratamento dos seus dados pessoais (inclusive documento de identidade e imagem/selfie
biométrica) para as finalidades de matrícula, identificação e emissão de certificado, nos termos da
Lei nº 13.709/2018 (LGPD).

Ao enviar a selfie, o(a) ALUNO(A) declara ter lido e aceito integralmente este contrato, sendo a
selfie a assinatura eletrônica deste aceite. O aceite é registrado com data, hora, endereço IP e
navegador utilizados.

Versão final a definir — este texto é um placeholder e deve ser substituído pela redação jurídica
oficial antes da produção.
"""

_PROMOTER_TEXT = """CONTRATO DE ADESÃO DO COLABORADOR (PROMOTOR) E TRATAMENTO DE DADOS

Pelo presente instrumento, o(a) COLABORADOR(A) adere ao programa de captação como promotor,
autorizando o tratamento dos seus dados pessoais (inclusive documento de identidade, chave Pix e
imagem/selfie biométrica) para as finalidades de cadastro, identificação, pagamento de comissões e
verificação, nos termos da Lei nº 13.709/2018 (LGPD).

Ao enviar a selfie, o(a) COLABORADOR(A) declara ter lido e aceito integralmente este contrato,
sendo a selfie a assinatura eletrônica deste aceite. O aceite é registrado com data, hora, endereço
IP e navegador utilizados.

Versão final a definir — este texto é um placeholder e deve ser substituído pela redação jurídica
oficial antes da produção.
"""

STUDENT_CONTRACT = Contract(version=CONTRACT_VERSION, text=_STUDENT_TEXT)
PROMOTER_CONTRACT = Contract(version=CONTRACT_VERSION, text=_PROMOTER_TEXT)
