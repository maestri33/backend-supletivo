"""FAQ por público — conteúdo factual MÍNIMO, pensado pra REVISÃO do dono.

⚠️ VICTOR REVISAR O TEOR: as respostas abaixo são um esqueleto conservador (nada de valor, prazo,
comissão ou promessa — esses são proibidos pela lista dura do `router`). Ajuste o texto à realidade
do Supletivo Brasil antes de ligar em produção. Cada bloco vira parte do contexto do system prompt
do público correspondente; o LLM usa como base factual e parafraseia.

Estrutura: dict {audience: [ (pergunta_guia, resposta_factual) ]}. `unknown` é a FAQ pública
genérica do estranho (a mais enxuta — sem expor nada interno).
"""

from __future__ import annotations

from bot import router

# ⚠️ PLACEHOLDER PARA REVISÃO — teor factual mínimo. Victor ajusta.
_FAQ: dict[str, list[tuple[str, str]]] = {
    router.AUDIENCE_UNKNOWN: [
        (
            "O que é o Supletivo Brasil?",
            "O Supletivo Brasil ajuda pessoas a concluírem os estudos (ensino fundamental e médio) "
            "pela modalidade supletivo/EJA, com apoio na matrícula e no acompanhamento.",
        ),
        (
            "Como faço para me matricular?",
            "A matrícula é feita com o apoio de um de nossos promotores, que tira todas as dúvidas "
            "e acompanha o processo. Posso te encaminhar para falar com um promotor.",
        ),
        (
            "Quanto custa? / Quero valores",
            "Os valores e condições são passados por um promotor, que monta o melhor caminho pra "
            "você. Vou te encaminhar para um atendente humano.",
        ),
    ],
    router.AUDIENCE_LEAD: [
        (
            "Como pago a matrícula?",
            "O pagamento é feito pelo link enviado no seu cadastro. Se você não encontrou o link "
            "ou teve algum problema, um atendente humano resolve isso pra você.",
        ),
        (
            "Já paguei, e agora?",
            "Assim que o pagamento é confirmado, você avança para a etapa de matrícula. Se quiser "
            "que eu confirme a situação do seu cadastro, posso verificar o status geral.",
        ),
    ],
    router.AUDIENCE_ENROLLMENT: [
        (
            "O que falta na minha matrícula?",
            "A matrícula tem etapas (documentos, endereço, escolaridade e selfie). Posso te dizer "
            "em qual etapa você está; o avanço é feito por você no aplicativo.",
        ),
        (
            "Enviei o documento e está em análise",
            "Quando algo está em análise, nossa equipe verifica e te retorna. Se demorar, um "
            "atendente humano pode acompanhar pra você.",
        ),
    ],
    router.AUDIENCE_STUDENT: [
        (
            "Como acesso a plataforma de estudos?",
            "O acesso à plataforma é feito com as credenciais enviadas a você. Por segurança, eu "
            "não repasso login nem senha por aqui — um atendente humano ajuda com o acesso.",
        ),
        (
            "Como funcionam as provas?",
            "As provas seguem o calendário do seu polo. Posso te informar a situação geral da sua "
            "matrícula; detalhes de data e local são confirmados por um atendente.",
        ),
    ],
    router.AUDIENCE_PROMOTER: [
        (
            "Como divulgo / consigo meu link?",
            "Seu link de divulgação fica disponível no seu painel de promotor. Dúvidas sobre o "
            "processo de divulgação, um atendente humano detalha pra você.",
        ),
        (
            "Quando recebo minha comissão?",
            "O fechamento e o pagamento das comissões são feitos pelo sistema/financeiro. Eu não "
            "confirmo valores nem datas por aqui; vou te encaminhar ao financeiro.",
        ),
    ],
    router.AUDIENCE_COORDINATOR: [
        (
            "Como aprovo matrículas / promotores?",
            "As aprovações são feitas por você no painel de coordenação. Posso tirar dúvidas "
            "gerais; a ação em si é sempre feita por você no sistema.",
        ),
    ],
    router.AUDIENCE_STAFF: [
        (
            "Dúvidas operacionais",
            "Posso ajudar com orientações gerais. Ações e confirmações são feitas nos painéis "
            "internos ou por um humano.",
        ),
    ],
}

# Convite padrão do estranho a falar com um promotor (sem captura agressiva).
PROMOTER_INVITE = (
    "Se quiser, posso te encaminhar para um de nossos promotores, que tira todas as suas dúvidas "
    "e te acompanha na matrícula."
)


def for_audience(audience: str) -> str:
    """Bloco de FAQ (texto) do público, pronto pra entrar no system prompt. Vazio se não houver."""
    items = _FAQ.get(audience, [])
    if not items:
        return ""
    lines = [
        "PERGUNTAS FREQUENTES (use como base factual; parafraseie, não invente além disto):"
    ]
    for question, answer in items:
        lines.append(f"- P: {question}\n  R: {answer}")
    return "\n".join(lines)


def static_fallback(audience: str) -> str:
    """Resposta ESTÁTICA (sem IA) pro modo degradado (teto de orçamento estourado / IA caída no
    caminho da FAQ). Primeira resposta da FAQ do público + convite, ou um genérico seguro."""
    items = _FAQ.get(audience, [])
    if items:
        base = items[0][1]
    else:
        base = "Recebi sua mensagem! Posso ajudar com dúvidas gerais sobre o Supletivo Brasil."
    if audience == router.AUDIENCE_UNKNOWN:
        return f"{base}\n\n{PROMOTER_INVITE}"
    return base
