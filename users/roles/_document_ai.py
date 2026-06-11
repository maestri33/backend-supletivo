"""Validação de documento de identidade por IA — visão + OCR + extração JSON (plan/12).

Compartilhada: nasce no `enrollment` (RG) e foi desenhada pra ser reusada pelo `candidate`
(RG/CNH) num ciclo futuro — uma implementação só (CONVENTION §12). Mesma régua de 3 estados
do student/selfie (plan/9): **approved** · **rejected** (motivo SEMPRE) · **review** (IA fora
do ar OU em dúvida → o coordenador decide). Quem orquestra (status no model, notifies, avanço
do wizard) é o serviço do funil; aqui moram só as chamadas de IA.

Os valores de status espelham `RG.Validation` (pending/approved/rejected/review) — strings
compartilhadas, sem import do model (evita ciclo documents↔roles).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
REVIEW = "review"

_AI_DOWN = "IA indisponível no momento — enviado para revisão manual do coordenador."

# lado da foto → o que a visão deve enxergar (front/back = par tradicional; full = documento inteiro)
_SIDE_DESC = {
    "front": (
        "a FRENTE de uma carteira de identidade brasileira (RG ou CIN) — o lado que "
        "contém a FOTO do titular"
    ),
    "back": (
        "o VERSO de uma carteira de identidade brasileira (RG ou CIN) — o lado com os "
        "dados (número do registro, filiação, naturalidade, data de expedição)"
    ),
    "full": (
        "uma carteira de identidade brasileira (RG ou CIN) COMPLETA — frente E verso "
        "visíveis na mesma imagem"
    ),
}

# Campos que a extração devolve (todos podem vir null — a IA NÃO inventa).
EXTRACT_FIELDS = (
    "number",
    "issuing_agency",
    "issue_date",
    "name",
    "birth_date",
    "mother_name",
    "father_name",
    "birthplace",
)

_EXTRACT_SCHEMA = (
    "{"
    '"number": "número do RG (registro geral), string ou null", '
    '"issuing_agency": "órgão emissor com UF (ex.: SSP/SP), string ou null", '
    '"issue_date": "data de expedição no formato AAAA-MM-DD ou null", '
    '"name": "nome completo do titular ou null", '
    '"birth_date": "data de nascimento no formato AAAA-MM-DD ou null", '
    '"mother_name": "nome da mãe (filiação) ou null", '
    '"father_name": "nome do pai (filiação) ou null", '
    '"birthplace": "naturalidade (cidade/UF) ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)


def check_photo(
    image_bytes: bytes,
    *,
    side: str,
    mime_type: str = "image/jpeg",
    caller: str,
) -> tuple[str, str]:
    """Visão: a foto é mesmo o lado `side` de um RG e está legível? → (status, motivo).

    Veredito direto (padrão `_selfie`): APROVADO/REPROVADO no começo da resposta; ambíguo ou
    IA fora do ar → REVIEW (humano decide). O motivo SEMPRE volta (plan/9)."""
    from integrations.ai import service as ai

    prompt = (
        f"Esta imagem mostra {_SIDE_DESC[side]}? Avalie também a LEGIBILIDADE: a imagem deve "
        "estar nítida, com o documento inteiro (sem cortes) e sem reflexos ou sombras que "
        "escondam os dados. Responda em português começando OBRIGATORIAMENTE com a palavra "
        "APROVADO (se for esse documento e estiver legível) ou REPROVADO (caso contrário), "
        "seguida de um motivo curto e claro (ex.: 'não é um RG', 'imagem desfocada', "
        "'documento cortado')."
    )
    try:
        desc = ai.describe_image(
            image_bytes, caller=caller, mime_type=mime_type, prompt=prompt
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar → review (coordenador resolve)
        logger.warning("document_ai.vision_failed", caller=caller, error=str(exc)[:200])
        return REVIEW, _AI_DOWN
    head = (desc or "").strip().upper()[:24]
    if "REPROVADO" in head:  # antes de APROVADO — "REPROVADO" contém "APROVADO"
        return REJECTED, desc
    if "APROVADO" in head:
        return APPROVED, desc
    return REVIEW, desc or "IA não foi conclusiva — enviado para revisão manual."


def ocr_images(images: list[bytes], *, caller: str) -> str:
    """OCR (Google Vision, modo documento) de cada imagem; devolve o texto junto."""
    from integrations.ai import service as ai

    parts = [ai.ocr(img, caller=caller, document=True) for img in images]
    return "\n\n--- PRÓXIMA IMAGEM ---\n\n".join(p for p in parts if p)


def extract_rg(ocr_text: str, *, holder_name: str | None, caller: str) -> dict:
    """1 chamada LLM (JSON): extrai os campos do RG + confere o nome do titular.

    `name_match`: 'sim' = mesmo titular (variação por CASAMENTO — sobrenome acrescentado/
    alterado — ou abreviação conta como 'sim'); 'nao' = claramente OUTRA pessoa; 'duvida' =
    ilegível/incompleto. A IA não inventa: campo ausente no OCR = null. Erro de IA sobe
    (o orquestrador decide o que fazer — em regra, REVIEW)."""
    from integrations.ai import service as ai

    expected = holder_name or "(nome não informado)"
    prompt = (
        f"Texto OCR de uma carteira de identidade brasileira (RG/CIN):\n\n{ocr_text}\n\n"
        f"O titular esperado desta conta é: {expected}.\n"
        "Compare o nome impresso no documento com o esperado: variações por CASAMENTO "
        "(sobrenome acrescentado, removido ou alterado) ou abreviações contam como 'sim', "
        "desde que seja claramente a MESMA pessoa; nome de OUTRA pessoa = 'nao'; nome "
        "ilegível ou ausente no texto = 'duvida'. Explique a comparação em name_reason. "
        "NÃO invente: qualquer campo que não estiver no texto = null."
    )
    data = ai.generate_json(
        prompt,
        caller=caller,
        instruction=(
            "Você extrai dados de carteiras de identidade brasileiras (RG/CIN) a partir de "
            "texto OCR. Responda APENAS o JSON pedido."
        ),
        schema_description=_EXTRACT_SCHEMA,
    )
    if not isinstance(data, dict):
        data = {}
    return data
