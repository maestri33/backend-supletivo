"""Agentes CrewAI do bot — 4 agentes especializados no wizard do WhatsApp.
ponytail: agentes enxutos, delegam escrita ao Actor (ferramentas), leitura ao reads.py.
"""
from __future__ import annotations

from crewai import Agent, Task, Crew, Process
from bot.crew_tools import build_tools


def build_crew(actor, reads, router_policy: dict):
    """Constrói o Crew com 4 agentes e tools injetadas. Chamado por worker.py quando BOT_USE_CREW=1."""
    tools = build_tools(actor)

    lead_agent = Agent(
        role="Captador de Leads",
        goal="Qualificar o lead, explicar o supletivo e enviar o link de pagamento quando pronto.",
        backstory=(
            "Você é o primeiro contato do candidato no WhatsApp. Sua missão é acolher, "
            "explicar como funciona o supletivo/EJA, tirar dúvidas sobre preço e prazo, "
            "e quando o lead estiver pronto, enviar o link de checkout."
        ),
        tools=tools,
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )

    enrollment_agent = Agent(
        role="Orientador de Matrícula",
        goal="Guiar o aluno pelas etapas da matrícula (RG, endereço, escolaridade, selfie).",
        backstory=(
            "Você ajuda o aluno a completar a matrícula. Para etapas que exigem câmera "
            "(RG, selfie), você envia o link do app. Para etapas de texto (endereço/CEP, "
            "tipo sanguíneo), você coleta os dados por chat."
        ),
        tools=tools,
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )

    student_agent = Agent(
        role="Suporte ao Aluno",
        goal="Ajudar o aluno com dúvidas sobre provas, documentos, certificado e próximos passos.",
        backstory=(
            "Você é o suporte contínuo do aluno após a matrícula. Responde dúvidas sobre "
            "ENCCEJA, agendamento de prova, emissão de certificado, segunda via e renovação."
        ),
        tools=tools,
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )

    handoff_agent = Agent(
        role="Encaminhador",
        goal="Identificar quando o usuário precisa de atendimento humano e escalar.",
        backstory=(
            "Você é o último recurso. Quando o usuário pede para falar com uma pessoa, "
            "ou quando os outros agentes não conseguem resolver, você escala para um humano."
        ),
        tools=[t for t in tools if t.name == "escalate_to_human"],
        verbose=False,
        allow_delegation=False,
        max_iter=1,
    )

    task = Task(
        description=(
            f"Usuário: {router_policy.get('publico', 'desconhecido')}. "
            f"Status: {router_policy.get('status', 'indefinido')}. "
            f"Mensagem: {router_policy.get('text', '')}. "
            "Responda de forma acolhedora, em português brasileiro, usando linguagem simples. "
            "Se for uma pergunta que os dados não cobrem, diga que vai verificar com a equipe."
        ),
        expected_output="Resposta em português brasileiro, acolhedora e direta, em até 3 frases.",
        agent=lead_agent,  # default; o worker decide roteamento
    )

    crew = Crew(
        agents=[lead_agent, enrollment_agent, student_agent, handoff_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    return crew
