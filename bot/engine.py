"""Motor DETERMINÍSTICO do funil (FASE 2): trava-na-etapa → destrava. A IA gera só o TEXTO.

VISÃO DO DONO: "um bot que faz o mesmo fluxo do app e trava onde o lead está". Aqui o CÓDIGO
decide, por etapa, qual é a ÚNICA ação canônica permitida; a IA só conversa (gera o texto), nunca
escolhe ação nem extrai dado. A escrita é feita pelo motor, via `Actor` (o bot agindo COMO O
USUÁRIO pela mesma superfície da API), e só quando um extrator determinístico tira do texto um
valor não-ambíguo.

SPLIT chat × app (dono confirmou):
- ESCREVE POR CHAT (simples, idempotente, sem câmera): endereço por CEP (matrícula) e tipo
  sanguíneo (aluno). É o que dá pra extrair com segurança de uma frase.
- ENTREGA O APP (câmera/liveness/biometria ou muitos campos): fotos de RG, selfie (assinatura),
  dados escolares, agendamento de prova. O bot GUIA e manda o link do app pra finalizar — não
  tenta validar foto/biometria por WhatsApp.
- NUNCA no checkout: o bot REENVIA o link JÁ gerado (leitura), nunca confirma pagamento nem gera
  cobrança.

Resultado por turno (`EngineResult`):
- `reply` setado  → resposta DETERMINÍSTICA (pula a IA). Usado após uma escrita: o desfecho é
  verdade que o motor conhece, então não deixamos a IA inventar ("salvei"/"não salvei").
- `escalate`      → a escrita falhou na API → humano assume (nunca finge que fez).
- senão           → `directive` + `facts` entram no contexto e a IA conversa focada na etapa.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from django.conf import settings

from bot import extract, router
from bot.actor import Actor

logger = structlog.get_logger()


@dataclass(frozen=True)
class EngineResult:
    """O que o motor decidiu pra este turno (ver docstring do módulo)."""

    directive: str = ""  # foco da etapa, anexado ao system prompt (a IA conversa)
    facts: tuple[
        str, ...
    ] = ()  # fatos seguros do contexto (ex.: link de pagamento/app)
    reply: str | None = (
        None  # resposta determinística (pula a IA) — confirmação de escrita
    )
    escalate: str | None = None  # motivo de escalonamento (escrita falhou)


_NOOP = EngineResult()


def _app_link() -> str | None:
    """Link do app pra finalizar a etapa (o app retoma o passo certo pela situação do usuário).
    Sem FRONTEND_URL configurado → None (o texto então só pede pra abrir o app)."""
    url = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    return url or None


def _go_to_app(focus: str) -> EngineResult:
    """Etapa que se finaliza no APP (câmera/liveness/muitos campos): guia + entrega o link."""
    link = _app_link()
    facts = (f"Link do app para finalizar esta etapa: {link}",) if link else ()
    suffix = (
        " Direcione a pessoa a finalizar pelo app (o link está no contexto)."
        if link
        else " Direcione a pessoa a finalizar pelo aplicativo."
    )
    return EngineResult(directive=focus + suffix, facts=facts)


# ── LEAD: trava no checkout — reenviar o link JÁ gerado, nunca confirmar pagamento ──
def _lead(actor: Actor) -> EngineResult:
    lead = actor.lead()
    status = getattr(lead, "status", None)

    if status in ("pending", "failed"):
        url = actor.checkout_url()  # leitura: link curto já existente (checkout↔recibo)
        facts = (
            (f"Link de pagamento da matrícula (reenvio, JÁ gerado): {url}",)
            if url
            else ()
        )
        directive = (
            "ETAPA ATUAL: pagamento da matrícula PENDENTE. Foque SÓ em ajudar a pagar: explique "
            "que o pagamento é pelo link e REENVIE o link que está no contexto (tal e qual). NÃO "
            "confirme nem negue pagamento, NÃO gere cobrança nova — se a pessoa diz que já pagou, "
            "diga que a confirmação é automática e que um atendente verifica se demorar."
        )
        if not url:
            directive += (
                " (O link ainda não está disponível; encaminhe a um atendente.)"
            )
        return EngineResult(directive=directive, facts=facts)

    if status == "paid":
        return EngineResult(
            directive=(
                "ETAPA ATUAL: pagamento CONFIRMADO; o próximo passo é iniciar a matrícula no app. "
                "Parabenize de forma breve e oriente a continuar a matrícula pelo aplicativo."
            ),
            facts=(f"Link do app: {_app_link()}",) if _app_link() else (),
        )

    return _NOOP


# ── ENROLLMENT: trava em OBTER INFORMAÇÕES — endereço por CHAT, resto pelo app ──
_ENR_DONE = ("awaiting_release", "fee_paid", "fee_scheduled", "completed")


def _enrollment(actor: Actor, text: str) -> EngineResult:
    status = actor.enrollment_status()

    if status == "address":
        cep = extract.cep(text)
        if cep is None:
            return EngineResult(
                directive=(
                    "ETAPA ATUAL: matrícula na fase de ENDEREÇO. Foque em obter o CEP: peça o CEP "
                    "(8 dígitos) de forma simples. Quando a pessoa mandar o CEP, o sistema registra "
                    "automaticamente. Não peça outros dados de endereço por aqui."
                )
            )
        try:
            me = actor.set_address_cep(cep)  # idempotente: mesmo CEP → mesmo estado
        except Exception as exc:  # noqa: BLE001 — escrita falhou → humano, nunca finge
            logger.warning("bot.engine.address_write_failed", error=str(exc)[:160])
            return EngineResult(escalate="address_write_failed")
        return EngineResult(reply=_address_saved_reply(me))

    if status == "rg":
        return _go_to_app(
            "ETAPA ATUAL: matrícula na fase do RG (fotos do documento). As fotos do RG são feitas "
            "no app, que confere a qualidade e extrai os dados."
        )
    if status == "education":
        return _go_to_app(
            "ETAPA ATUAL: matrícula na fase de DADOS ESCOLARES (escolaridade, série, escola). Esses "
            "dados são preenchidos no app."
        )
    if status == "selfie":
        return _go_to_app(
            "ETAPA ATUAL: matrícula na fase da SELFIE (assinatura da matrícula, com biometria). A "
            "selfie é feita no app (a câmera valida o rosto); não dá pra fazer por foto no WhatsApp."
        )
    if status in _ENR_DONE:
        return EngineResult(
            directive=(
                "ETAPA ATUAL: matrícula AVANÇADA (etapas principais concluídas; em análise/liberação "
                "pela equipe). Confirme o progresso de forma geral e diga que a equipe dá o próximo "
                "passo; qualquer detalhe específico, encaminhe a um atendente."
            )
        )
    return _NOOP


def _address_saved_reply(me: dict) -> str:
    """Confirmação DETERMINÍSTICA pós-CEP. O `me_dict` é a verdade do estado; deriva o próximo passo
    sem deixar a IA inventar. Faltando número/complemento → finaliza no app (PATCH multi-campo)."""
    base = "Pronto! Localizei seu endereço pelo CEP. ✅"
    address = (me or {}).get("address") or {}
    missing = address.get("missing_fields") or []
    link = _app_link()
    if missing:
        tail = " Falta confirmar alguns detalhes (como número/complemento)"
        tail += f" — finalize pelo app: {link}" if link else " — finalize pelo app."
        return base + tail
    if link:
        return base + f" Continue sua matrícula pelo app: {link}"
    return base + " Pode continuar sua matrícula pelo app."


# ── STUDENT: dispara informações + tipo sanguíneo por CHAT, resto pelo app ──
def _student(actor: Actor, text: str) -> EngineResult:
    status = actor.student_status()

    if status in ("awaiting_documents", "documents_under_review"):
        bt = extract.blood_type(text)
        if bt is not None:
            try:
                actor.set_blood_type(bt)  # idempotente: mesmo tipo → mesmo estado
            except Exception as exc:  # noqa: BLE001 — escrita falhou → humano, nunca finge
                logger.warning("bot.engine.blood_write_failed", error=str(exc)[:160])
                return EngineResult(escalate="blood_write_failed")
            link = _app_link()
            tail = (
                f" Os demais documentos você envia pelo app: {link}"
                if link
                else (" Os demais documentos você envia pelo app.")
            )
            return EngineResult(reply=f"Anotado seu tipo sanguíneo: {bt}. ✅" + tail)
        return _go_to_app(
            "ETAPA ATUAL: aluno enviando os DOCUMENTOS finais. As fotos dos documentos são enviadas "
            "no app, que confere e analisa. (Se a pessoa só informar o tipo sanguíneo por texto, o "
            "sistema registra automaticamente.)"
        )

    if status in ("exam_released", "exam_failed"):
        return _go_to_app(
            "ETAPA ATUAL: aluno liberado para AGENDAR A PROVA. O agendamento (matéria + data) é feito "
            "no app."
        )
    if status == "exam_scheduled":
        return EngineResult(
            directive=(
                "ETAPA ATUAL: prova AGENDADA. Confirme de forma geral que está agendada e que os "
                "detalhes de data/local são confirmados pela equipe; não invente data nem local."
            )
        )
    return EngineResult(
        directive=(
            "ETAPA ATUAL: aluno com matrícula ativa. Informe a situação geral e oriente o próximo "
            "passo em linhas gerais; qualquer detalhe ou ação, encaminhe a um atendente."
        )
    )


def run(actor: Actor | None, policy, text: str) -> EngineResult:
    """Decide o turno pela ETAPA do usuário. PURA quanto a roteamento; a única escrita possível é a
    canônica da etapa (via Actor), e só com extração não-ambígua. Sem actor (estranho) → no-op.

    NUNCA levanta: erro inesperado degrada pra no-op (a IA segue na FAQ do público). Erro de
    ESCRITA é tratado dentro de cada etapa como `escalate` (humano assume)."""
    if actor is None:
        return _NOOP
    try:
        if policy.audience == router.AUDIENCE_LEAD:
            return _lead(actor)
        if policy.audience == router.AUDIENCE_ENROLLMENT:
            return _enrollment(actor, text)
        if policy.audience == router.AUDIENCE_STUDENT:
            return _student(actor, text)
    except Exception as exc:  # noqa: BLE001 — motor nunca derruba o atendimento
        logger.warning(
            "bot.engine.failed", audience=policy.audience, error=str(exc)[:160]
        )
        return _NOOP
    return _NOOP
