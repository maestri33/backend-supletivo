"""Config do `student` — documentos obrigatórios + prompts da validação por IA.

Sem valores de dinheiro aqui (a comissão do coordenador é `finance.config.coordinator_amount`, §8).
Os tipos de documento e suas exigências vêm do `specs/student.md` (palavra do dono) + legado.
"""

from __future__ import annotations

from users.roles.student.models import StudentDocument

_T = StudentDocument.Type

# Documentos exigidos de TODO aluno (foto, validados por IA). O militar é condicional ao gênero
# (só homens) — tratado no service, não aqui. Todos precisam estar APROVADOS pra liberar a prova.
# Fotos exigidas (validadas por IA). O TIPO SANGUÍNEO obrigatório é o VALOR (`Student.blood_type`,
# checado no `_maybe_release_exam`), não a foto — então BLOOD_TYPE NÃO entra aqui (spec: "obrigatório
# especificar" = valor). A foto de tipo sanguíneo segue aceita como documento opcional.
REQUIRED_DOC_TYPES: tuple[str, ...] = (
    _T.CERTIFICATE,  # certificado do último ano (obrigatório — spec)
    _T.TRANSCRIPT,  # histórico (obrigatório — spec)
    _T.ADDRESS_PROOF,  # comprovante de endereço (foto, validado por IA)
    _T.ID_CARD,  # documento pessoal / RG (foto, obrigatório)
    _T.BIRTH_CERTIFICATE,  # certidão
)

# Documento exigido só de homens (gate de gênero no service).
MALE_ONLY_DOC_TYPES: tuple[str, ...] = (_T.MILITARY,)

# Prompt por tipo: a IA descreve a foto e decide. O service espera a resposta começar com
# "APROVADO" ou "REPROVADO". Best-effort: IA fora do ar/ambígua → fica REVIEW (coordenador decide; não auto-aprova).
_BASE_PROMPT = (
    "Você valida o documento de um aluno. Responda em português começando OBRIGATORIAMENTE "
    "com a palavra APROVADO ou REPROVADO, seguida de uma justificativa curta. "
    "Aprove só se a imagem for legível e claramente {desc}."
)

_DOC_DESC = {
    _T.MILITARY: "um documento de serviço militar (reservista/dispensa)",
    _T.CERTIFICATE: "um certificado de conclusão escolar",
    _T.TRANSCRIPT: "um histórico escolar",
    _T.BLOOD_TYPE: "um documento/cartão indicando o tipo sanguíneo",
    _T.ADDRESS_PROOF: "um comprovante de endereço (conta de consumo/correspondência recente)",
    _T.ID_CARD: "um documento de identidade com foto (RG ou equivalente)",
    _T.BIRTH_CERTIFICATE: "uma certidão (nascimento/casamento)",
}


def validation_prompt(
    doc_type: str, *, holder_name: str | None = None, holder_birth: str | None = None
) -> str:
    """Prompt de validação. Se vier o titular esperado (nome/nascimento que o CPFHub deu no cadastro),
    a IA confere se o documento é DAQUELA pessoa e REPROVA se o nome for de outra (Victor 2026-06-05:
    'comparar com os dados do CPFHub; se não bater, reprova de imediato')."""
    desc = _DOC_DESC.get(doc_type, "o documento solicitado")
    prompt = _BASE_PROMPT.format(desc=desc)
    if holder_name:
        ident = f" Este documento deve pertencer a {holder_name}"
        if holder_birth:
            ident += f" (nascido(a) em {holder_birth})"
        ident += (
            ". Leia o NOME DO TITULAR impresso na imagem: se for de OUTRA pessoa "
            "(diferente do nome informado), responda REPROVADO."
        )
        prompt += ident
    return prompt
