"""Leituras SEGURAS do PRÓPRIO usuário pro contexto do bot (allowlist estrito).

PERIGO conhecido: os dicts ricos das interfaces VAZAM dado sensível —
`lead_self_dict` traz CPF/e-mail/URL de checkout, `enrollment.me_dict` traz filiação/RG,
`student.to_dict` traz LOGIN E SENHA da plataforma. O bot NUNCA pode receber isso.

Por isso aqui NÃO espalhamos o dict. Cada leitura extrai uma frase de status COARSE (a etapa
geral, em pt-br) por allowlist explícito — só o que é seguro o LLM ver e parafrasear pro próprio
dono. Sem números de documento, sem credencial, sem dado de terceiro.

Cada função recebe o `external_id` do User (resolvido no worker via Profile→User) e devolve uma
string curta pro contexto, ou `None` se não houver o que ler.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

# Mapas status-técnico → frase pt-br segura. O que NÃO está no mapa cai num texto genérico
# ("em andamento") — nunca expomos o código cru de status nem campo fora desta lista.
_LEAD_STATUS_PT = {
    "pending": "cadastro feito, pagamento da matrícula ainda pendente",
    "paid": "pagamento da matrícula confirmado",
    "failed": "houve um problema no pagamento da matrícula",
    "expired": "o link de pagamento da matrícula expirou",
    "cancelled": "a matrícula foi cancelada",
}

_ENROLLMENT_STATUS_PT = {
    "documents": "enviando os documentos da matrícula",
    "address": "preenchendo o endereço da matrícula",
    "education": "informando a escolaridade",
    "selfie": "na etapa da selfie (assinatura da matrícula)",
    "review": "matrícula em análise pela equipe",
    "fee": "matrícula em andamento",
    "done": "matrícula concluída",
}

_STUDENT_STATUS_PT = {
    "active": "aluno com matrícula ativa",
    "documentation": "aluno enviando a documentação final",
    "exam": "aluno na etapa de provas",
    "diploma": "aluno na etapa de diploma",
    "concluded": "curso concluído",
}


def _phrase(mapping: dict, status, fallback: str) -> str:
    """Frase segura pro status (ou um fallback genérico). NUNCA devolve o código cru desconhecido."""
    return mapping.get(str(status or "").lower(), fallback)


def lead_status(user_external_id: str) -> str | None:
    """Etapa COARSE do lead do próprio usuário (sem CPF, sem URL, sem e-mail)."""
    from users.roles.lead import interface as lead_iface

    lead = lead_iface.get_for_user_external_id(user_external_id)
    if lead is None:
        return None
    return _phrase(
        _LEAD_STATUS_PT, getattr(lead, "status", None), "matrícula em andamento"
    )


def enrollment_status(user_external_id: str) -> str | None:
    """Etapa COARSE da matrícula do próprio usuário (sem filiação, sem RG, sem dado pessoal)."""
    from users.roles.enrollment import interface as enr_iface

    enr = enr_iface.get_for_user_external_id(user_external_id)
    if enr is None:
        return None
    return _phrase(
        _ENROLLMENT_STATUS_PT, getattr(enr, "status", None), "matrícula em andamento"
    )


def student_status(user_external_id: str) -> str | None:
    """Situação COARSE do aluno (sem credenciais da plataforma, sem documentos, sem tipo sanguíneo)."""
    from users.roles.student import interface as student_iface

    student = student_iface.get_for_user_external_id(user_external_id)
    if student is None:
        return None
    return _phrase(
        _STUDENT_STATUS_PT,
        getattr(student, "status", None),
        "aluno com matrícula ativa",
    )


# Despacho por chave de leitura permitida (ver router.READ_*).
_READERS = {
    "lead_status": lead_status,
    "enrollment_status": enrollment_status,
    "student_status": student_status,
}


def collect(user_external_id: str, allowed_reads) -> list[str]:
    """Coleta as frases de status das leituras PERMITIDAS pra esse público.

    `allowed_reads` vem da `AudiencePolicy.allowed_reads`. Cada leitura é isolada: erro numa NÃO
    derruba as outras nem o atendimento (o bot degrada pra FAQ). Devolve só as frases não-vazias.
    """
    facts: list[str] = []
    for key in allowed_reads or ():
        reader = _READERS.get(key)
        if reader is None:
            continue
        try:
            phrase = reader(user_external_id)
        except Exception as exc:  # noqa: BLE001 — leitura nunca derruba o atendimento
            logger.warning("bot.reads.failed", read=key, error=str(exc)[:160])
            continue
        if phrase:
            facts.append(phrase)
    return facts
