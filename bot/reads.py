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

# Mapas status-técnico → frase pt-br segura. As CHAVES são derivadas dos enums REAIS dos models
# (users.roles.*.models.*.Status), nunca strings soltas retypeadas à mão — isso já divergiu e
# derrubou `student_status()` 100% no fallback genérico. O que NÃO está no mapa cai num texto
# genérico ("em andamento") — nunca expomos o código cru de status nem campo fora desta lista.


def _lead_status_pt() -> dict:
    from users.roles.lead.models import Lead

    S = Lead.Status
    return {
        S.PENDING: "cadastro feito, pagamento da matrícula ainda pendente",
        S.PAID: "pagamento da matrícula confirmado",
        S.FAILED: "houve um problema no pagamento da matrícula",
    }


def _enrollment_status_pt() -> dict:
    from users.roles.enrollment.models import Enrollment

    S = Enrollment.Status
    # FEE_PAID/FEE_SCHEDULED = fase da TAXA, interna do polo (o aluno nunca vê — mesma máscara de
    # `enrollment.service.public_status`), por isso caem na mesma frase de AWAITING_RELEASE.
    return {
        S.RG: "enviando o RG (documento) da matrícula",
        S.ADDRESS: "preenchendo o endereço da matrícula",
        S.EDUCATION: "informando a escolaridade",
        S.SELFIE: "na etapa da selfie (assinatura da matrícula)",
        S.AWAITING_RELEASE: "matrícula em análise pela equipe",
        S.FEE_PAID: "matrícula em análise pela equipe",
        S.FEE_SCHEDULED: "matrícula em análise pela equipe",
        S.COMPLETED: "matrícula concluída",
    }


def _student_status_pt() -> dict:
    from users.roles.student.models import Student

    S = Student.Status
    return {
        S.AWAITING_DOCUMENTS: "aluno enviando a documentação final",
        S.DOCUMENTS_UNDER_REVIEW: "aluno com documentação em análise",
        S.EXAM_RELEASED: "aluno liberado para agendar a prova",
        S.EXAM_SCHEDULED: "aluno com prova agendada",
        S.EXAM_FAILED: "aluno reprovado na prova (vai refazer)",
        S.AWAITING_DOCUMENTATION_DISPATCH: "aluno aguardando envio de documentação",
        S.PENDING: "aluno com uma pendência",
        S.AWAITING_DIPLOMA_ISSUANCE: "aluno aguardando emissão do diploma",
        S.AWAITING_PICKUP: "aluno aguardando retirada do diploma",
        S.VETERAN: "curso concluído",
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
        _lead_status_pt(), getattr(lead, "status", None), "matrícula em andamento"
    )


def enrollment_status(user_external_id: str) -> str | None:
    """Etapa COARSE da matrícula do próprio usuário (sem filiação, sem RG, sem dado pessoal)."""
    from users.roles.enrollment import interface as enr_iface

    enr = enr_iface.get_for_user_external_id(user_external_id)
    if enr is None:
        return None
    return _phrase(
        _enrollment_status_pt(), getattr(enr, "status", None), "matrícula em andamento"
    )


def student_status(user_external_id: str) -> str | None:
    """Situação COARSE do aluno (sem credenciais da plataforma, sem documentos, sem tipo sanguíneo)."""
    from users.roles.student import interface as student_iface

    student = student_iface.get_for_user_external_id(user_external_id)
    if student is None:
        return None
    return _phrase(
        _student_status_pt(),
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
