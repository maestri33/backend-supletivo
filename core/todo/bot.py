"""Bot matriculador — MOCK (Victor 2026-06-23).

Um dia automatiza a matrícula na instituição parceira (SIGA, `INSTITUTION_LOGIN_URL`): loga
como administração, abre Nova Matrícula > Aluno Novato, preenche Identificação/Documentação/
Contato com os dados já coletados, e devolve os 2 QR PIX (à vista + agendado) + o login/senha.
Por ora **levanta `BotNotImplemented`** → o fluxo cai no coordenador (notify atual).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class BotNotImplemented(NotImplementedError):
    """O bot matriculador ainda não foi implementado (mock)."""


def run_bot_matriculador(enrollment) -> None:
    """Tenta a matrícula no SIGA. MOCK: sempre levanta `BotNotImplemented`.

    Quando implementado: ação ATÔMICA com timeout; se não conseguir, reporta a métrica de
    falha e NÃO deixa estado parcial — o coordenador assume (palavra do Victor 2026-06-23)."""
    logger.info(
        "todo.bot_matriculador.invoked",
        enrollment=str(getattr(enrollment, "external_id", "")),
    )
    raise BotNotImplemented("bot_matriculador ainda não implementado")
