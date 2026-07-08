"""Tools do CrewAI — envolvem o Actor existente para os agentes do bot.
ponytail: reusa Actor (JWT in-process + require_roles), sem duplicar lógica de escrita.
"""
from __future__ import annotations

import structlog
from crewai.tools import BaseTool

from bot.actor import Actor

logger = structlog.get_logger()


class GetStatusTool(BaseTool):
    name: str = "get_status"
    description: str = "Lê o status atual do usuário (lead, enrollment, student) e retorna a etapa do wizard."

    actor: Actor | None = None

    def _run(self, *args, **kwargs) -> str:
        if not self.actor:
            return "erro: ator não inicializado"
        try:
            parts = []
            lead = self.actor.lead()
            if lead:
                parts.append(f"lead: {lead.status}")
            enrollment = self.actor.enrollment()
            if enrollment:
                parts.append(f"enrollment: {enrollment.status}")
            student = self.actor.student()
            if student:
                parts.append(f"student: {student.status}")
            return "\n".join(parts) if parts else "usuário sem funil ativo"
        except Exception as e:
            logger.warning("crew.tool.get_status_failed", error=str(e)[:120])
            return f"erro ao ler status: {e}"


class GetCheckoutUrlTool(BaseTool):
    name: str = "get_checkout_url"
    description: str = "Retorna a URL de checkout/pagamento do lead (se houver)."

    actor: Actor | None = None

    def _run(self, *args, **kwargs) -> str:
        if not self.actor:
            return "erro: ator não inicializado"
        try:
            url = self.actor.checkout_url()
            return url or "sem checkout pendente"
        except Exception as e:
            return f"erro: {e}"


class SetAddressCepTool(BaseTool):
    name: str = "set_address_cep"
    description: str = "Define o CEP do endereço na matrícula. Ex.: '01310100'."

    actor: Actor | None = None

    def _run(self, cep: str = "", *args, **kwargs) -> str:
        if not self.actor:
            return "erro: ator não inicializado"
        try:
            result = self.actor.set_address_cep(cep.strip())
            return f"CEP {cep} salvo. Endereço: {result}"
        except Exception as e:
            return f"erro ao salvar CEP: {e}"


class SetBloodTypeTool(BaseTool):
    name: str = "set_blood_type"
    description: str = "Define o tipo sanguíneo do aluno. Ex.: 'A+', 'O-'."

    actor: Actor | None = None

    def _run(self, blood_type: str = "", *args, **kwargs) -> str:
        if not self.actor:
            return "erro: ator não inicializado"
        try:
            self.actor.set_blood_type(blood_type.strip().upper())
            return f"tipo sanguíneo {blood_type.strip().upper()} salvo"
        except Exception as e:
            return f"erro ao salvar tipo sanguíneo: {e}"


class EscalateToHumanTool(BaseTool):
    name: str = "escalate_to_human"
    description: str = "Escala a conversa para um atendente humano. Use quando o usuário pede para falar com uma pessoa."

    def _run(self, reason: str = "", *args, **kwargs) -> str:
        return f"escalado: {reason}" if reason else "escalado para atendente humano"


def build_tools(actor: Actor | None) -> list[BaseTool]:
    """Constrói as tools do CrewAI com o Actor injetado (ponytail: mesma instância por mensagem)."""
    return [
        GetStatusTool(actor=actor),
        GetCheckoutUrlTool(actor=actor),
        SetAddressCepTool(actor=actor),
        SetBloodTypeTool(actor=actor),
        EscalateToHumanTool(),
    ]
