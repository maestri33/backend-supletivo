"""FAQ por público — base factual que a IA usa pra parafrasear (NUNCA inventa além disto).

TEOR (Victor 2026-06-30): conteúdo conservador e seguro. Por construção, nada aqui cita valor,
prazo, comissão, data de prova ou a instituição parceira — esses são proibidos pela lista dura do
`router` E pela regra de negócio (o aluno não pode ser direcionado a se matricular direto na
parceira). Onde aparece `# ⚠️ CONFIRMAR:` é um ponto que depende de política operacional que só o
Victor fecha — o texto já está redigido de forma segura (encaminha a humano), o comentário só marca
o que revisar quando testar. Cada bloco vira parte do system prompt do público; `unknown` é a FAQ
pública do estranho (a mais enxuta — não expõe nada interno).

Estrutura: dict {audience: [ (pergunta_guia, resposta_factual) ]}.
"""

from __future__ import annotations

from bot import router

_FAQ: dict[str, list[tuple[str, str]]] = {
    router.AUDIENCE_UNKNOWN: [
        (
            "O que é o Supletivo Brasil?",
            "O Supletivo Brasil ajuda adultos a concluírem os estudos pela modalidade supletivo (EJA) "
            "— tanto o ensino fundamental quanto o ensino médio. A gente apoia em cada passo, da "
            "matrícula até a conclusão, com acompanhamento de perto.",
        ),
        (
            "Para quem é? Tenho idade?",
            "É para quem não conseguiu terminar os estudos na idade regular e quer concluir o "
            "fundamental ou o médio. As regras de idade seguem a legislação da EJA; um promotor "
            "confirma se você já se enquadra e te orienta no que for preciso.",
        ),
        (
            "Como faço para me matricular?",
            "A matrícula é feita com o apoio de um dos nossos promotores, que tira todas as dúvidas e "
            "acompanha você no processo. Se quiser, posso te encaminhar para falar com um promotor "
            "agora mesmo.",
        ),
        (
            "Quanto custa? / Quero valores",
            "Os valores e as condições são passados por um promotor, que monta o melhor caminho pra "
            "você. Vou te encaminhar para um atendente humano que explica tudo direitinho.",
        ),
        (
            "É reconhecido? O certificado vale?",
            "Sim, a conclusão pela modalidade supletivo/EJA dá direito a certificado válido em todo o "
            "país. Os detalhes do seu caso são confirmados por um atendente.",
            # ⚠️ CONFIRMAR: teor da validade/credenciamento que o Victor quer comunicar (sem citar a parceira).
        ),
    ],
    router.AUDIENCE_LEAD: [
        (
            "Como pago a matrícula?",
            "O pagamento é feito pelo link enviado no seu cadastro. Se você não encontrou o link ou "
            "teve algum problema, eu reenvio o link e, se precisar, um atendente humano resolve com você.",
        ),
        (
            "Já paguei, e agora?",
            "Assim que o pagamento é confirmado, ele aparece automaticamente no sistema e você avança "
            "para a etapa de matrícula. Se quiser, eu verifico a situação geral do seu cadastro; se "
            "tiver demorado, um atendente humano acompanha pra você.",
        ),
        (
            "Posso pagar de outra forma?",
            "As formas de pagamento disponíveis aparecem no próprio link. Para combinar algo "
            "diferente, um atendente humano é quem pode te orientar.",
            # ⚠️ CONFIRMAR: formas de pagamento aceitas (PIX/cartão/boleto) — hoje o texto remete ao link.
        ),
    ],
    router.AUDIENCE_ENROLLMENT: [
        (
            "O que falta na minha matrícula?",
            "A matrícula tem algumas etapas (endereço, documentos, dados escolares e uma selfie de "
            "confirmação). Posso te dizer em qual etapa você está agora; o avanço de cada etapa é "
            "feito por você mesmo, aqui pelo WhatsApp quando dá, ou pelo aplicativo.",
        ),
        (
            "Enviei o documento e está em análise",
            "Quando algo fica em análise, nossa equipe confere e te dá o retorno. Se estiver demorando "
            "mais que o normal, um atendente humano acompanha o seu caso de perto.",
        ),
        (
            "Posso terminar pelo WhatsApp?",
            "Algumas etapas simples dá pra resolver por aqui (como o endereço, pelo CEP). As que "
            "precisam de câmera — fotos de documento e a selfie — são feitas pelo aplicativo, que "
            "confere a qualidade na hora. Eu te mando o link e te guio.",
        ),
    ],
    router.AUDIENCE_STUDENT: [
        (
            "Como acesso a plataforma de estudos?",
            "O acesso é feito com as credenciais que foram enviadas a você. Por segurança, eu não "
            "repasso login nem senha por aqui — se você perdeu o acesso, um atendente humano resolve "
            "isso rapidinho com você.",
        ),
        (
            "Como funcionam as provas?",
            "As provas seguem o calendário do seu polo. Posso te informar a situação geral da sua "
            "matrícula; a data e o local certinhos são confirmados pela equipe, para não haver "
            "nenhuma confusão.",
        ),
        (
            "Quando recebo meu certificado?",
            "O certificado é emitido após a conclusão e a aprovação das etapas previstas. A situação "
            "do seu caso é confirmada pela equipe — posso te encaminhar para um atendente verificar.",
            # ⚠️ CONFIRMAR: fluxo/prazo de emissão do certificado que o Victor quer comunicar.
        ),
    ],
    router.AUDIENCE_PROMOTER: [
        (
            "Como divulgo / consigo meu link?",
            "Seu link de divulgação fica no seu painel de promotor. Com ele, as pessoas que você "
            "indica já entram ligadas a você. Dúvidas sobre como divulgar melhor, um atendente humano "
            "detalha pra você.",
        ),
        (
            "Quando recebo minha comissão?",
            "O fechamento e o pagamento das comissões são feitos pelo sistema, no ciclo do financeiro. "
            "Eu não confirmo valores nem datas por aqui; quando o pagamento sai, você é avisado "
            "automaticamente. Para qualquer dúvida específica, encaminho ao financeiro.",
        ),
        (
            "Como acompanho minhas indicações?",
            "O seu painel de promotor mostra o andamento das suas indicações. Se algo parecer fora do "
            "lugar, um atendente humano confere com você.",
        ),
    ],
    router.AUDIENCE_COORDINATOR: [
        (
            "Como aprovo matrículas / promotores?",
            "As aprovações são feitas por você no painel de coordenação. Posso tirar dúvidas gerais "
            "sobre o processo; a ação em si é sempre feita por você no sistema.",
        ),
        (
            "Como acompanho meu polo / minha equipe?",
            "O painel de coordenação reúne o andamento do seu polo e da sua equipe. Para um ponto "
            "específico, um atendente humano apoia você.",
        ),
    ],
    router.AUDIENCE_STAFF: [
        (
            "Dúvidas operacionais",
            "Posso ajudar com orientações gerais. As ações e confirmações são feitas nos painéis "
            "internos ou com um humano da equipe.",
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
