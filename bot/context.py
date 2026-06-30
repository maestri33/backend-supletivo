"""Montagem do contexto do LLM: system prompt (público + lista dura) + FAQ + fatos do próprio
usuário (leitura segura) + últimas N mensagens. Tudo o que o LLM vê passa por aqui.

NENHUMA função de escrita é exposta ao LLM — o contexto é só TEXTO (instruções + fatos coarse +
histórico). A separação de capacidade é estrutural: o worker chama `ia.service.chat`, que só gera
texto; não há tool-calling nem acesso a finance/asaas. Isto aqui é a camada de instrução.
"""

from __future__ import annotations

from bot import faq, reads
from bot.models import DIRECTION_INBOUND


def build_messages(
    *, policy, user_external_id: str | None, history, user_text: str
) -> list[dict]:
    """Monta a lista de mensagens (formato OpenAI-compatible) pro `ia.service.chat`.

    - system: prompt do público (com a lista dura) + FAQ do público + fatos seguros do próprio
      usuário (só se `allowed_reads` e houver `user_external_id`).
    - histórico: últimas N mensagens já recortadas pelo caller (inbound=user, outbound=assistant).
    - última: a mensagem atual do usuário.
    """
    system_parts = [policy.system_prompt]

    faq_block = faq.for_audience(policy.audience)
    if faq_block:
        system_parts.append(faq_block)

    if user_external_id and policy.allowed_reads:
        facts = reads.collect(user_external_id, policy.allowed_reads)
        if facts:
            system_parts.append(
                "SITUAÇÃO ATUAL DO PRÓPRIO USUÁRIO (use só para responder a ELE, em linhas gerais; "
                "não cite dados sensíveis):\n- " + "\n- ".join(facts)
            )

    messages: list[dict] = [{"role": "system", "content": "\n\n".join(system_parts)}]

    for msg in history:
        role = "user" if msg.direction == DIRECTION_INBOUND else "assistant"
        messages.append({"role": role, "content": msg.text})

    messages.append({"role": "user", "content": user_text})
    return messages
