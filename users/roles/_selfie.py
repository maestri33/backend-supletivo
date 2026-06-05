"""Verificação de selfie por IA — compartilhada por `candidate` e `enrollment` (best-effort).

"Do jeito melhor" (Victor 2026-06-05): em vez de casar termos soltos ("pessoa"/"rosto"/...) numa
descrição livre da imagem, pede um VEREDITO direto à visão — é selfie de pessoa real (não foto-de-foto,
tela, papel ou documento)? — e lê o começo da resposta (VALIDA/INVALIDA).

Best-effort (§12): IA fora do ar ou resposta ambígua → `(False, texto)` — NÃO trava o funil (a selfie
sempre foi best-effort; o coordenador confere depois). Uma implementação só, reusada (CONVENTION §12).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

_PROMPT = (
    "Esta imagem é uma SELFIE de uma pessoa real, fotografada ao vivo — e NÃO uma foto de outra foto, "
    "de tela, de papel ou de documento? Responda em português começando OBRIGATORIAMENTE com a palavra "
    "VALIDA (se for selfie de pessoa real) ou INVALIDA (caso contrário), seguida de um motivo curto."
)


def verify(
    image_bytes: bytes, content_type: str, *, caller: str
) -> tuple[bool, str | None]:
    """(verificada?, descrição_bruta). `verificada` = a IA respondeu VALIDA. Best-effort."""
    from integrations.ai import service as ai

    try:
        desc = ai.describe_image(
            image_bytes, caller=caller, mime_type=content_type, prompt=_PROMPT
        )
    except Exception as exc:  # noqa: BLE001 — validação é best-effort (porte do legado)
        logger.warning("selfie_ai_failed", caller=caller, error=str(exc))
        return False, None
    head = (desc or "").strip().upper()[:16]
    # "INVALIDA" NÃO começa com "VALIDA" (começa com I) → startswith resolve sem ambiguidade.
    return head.startswith("VALIDA"), desc
