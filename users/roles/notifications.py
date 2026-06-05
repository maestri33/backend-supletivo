"""Catálogo central das mensagens de notificação dos funis (TEOR + regra de TTS).

Regras (Victor 2026-06-05):
- **Toda troca de role notifica os envolvidos.** Cada serviço dispara no seu ponto; o TEOR mora AQUI.
- **O primeiro nome do destinatário aparece pelo menos 2× em cada mensagem** (proximidade/calor).
- **TTS (voz) só em MOMENTOS ESPECIAIS** (acolhimento/conquista do aluno/colaborador). O resto é texto.
- O teor é **editável pelo Victor**; o mapa fica em `wiki/notify/notify.md` (só cita as chaves daqui).

Como usar (serviços):
    from users.roles import notifications as msgs
    name = msgs.first_name(profile.name)
    send(text=msgs.text("lead.paid", name=name), caller="lead.paid",
         tts=msgs.is_tts("lead.paid"), gender=profile.gender if msgs.is_tts("lead.paid") else None, ...)

`{name}` = primeiro nome do DESTINATÁRIO (sempre ≥2×). Placeholders extras conforme o evento
(`{valor}`, `{link}`, `{payload}`, `{lead_name}`, `{detail}`, `{doc_type}`, `{ref_url}`).
"""

from __future__ import annotations

# Eventos que vão por VOZ (TTS). Tudo que não está aqui é só texto (regra "TTS só em momento especial").
# São os marcos de acolhimento/conquista do aluno/colaborador.
_TTS_EVENTS = frozenset(
    {
        "lead.captured",  # boas-vindas ao novo lead
        "lead.paid",  # parabéns: matrícula começou (o recibo vai à parte, em texto)
        "enrollment.released",  # virou aluno
        "training.approved",  # virou promotor
        "student.exam_passed",  # passou na prova
        "student.veteran",  # formou / virou veterano
    }
)

_FALLBACK_NAME = "tudo bem"  # quando não há nome (raro: CPFHub quase sempre traz)

# Teor por evento. ALUNO/LEAD/colaborador = caloroso e personalizado; promotor/coordenador = direto,
# mas SEMPRE com o primeiro nome do destinatário 2×.
_MESSAGES: dict[str, str] = {
    # ── LEAD (funil do aluno) ────────────────────────────────────────────────
    "lead.captured": (
        "Olá, {name}! 🎉 Que bom ter você com a gente. Seu cadastro está pronto, {name} — "
        "falta só um passo pra garantir sua vaga: concluir o pagamento. Em instantes envio o link. "
        "Bora juntos nessa jornada!"
    ),
    "lead.captured.promoter": (
        "Boa notícia, {name}! {lead_name} acaba de entrar na sua rede pela sua indicação. "
        "Incentive a concluir o pagamento, {name}. 👊"
    ),
    "lead.checkout.pix": (
        "{name}, para concluir sua matrícula pague o PIX de {valor}:\n{link}\n\n"
        "Ou use o PIX copia-e-cola, {name}:\n{payload}"
    ),
    "lead.checkout.card": (
        "{name}, para concluir sua matrícula pague {valor} no cartão:\n{link}\n\n"
        "Qualquer dúvida é só chamar, {name}."
    ),
    "lead.paid": (
        "Parabéns, {name}! 🎉 Seu pagamento foi confirmado e sua matrícula começou. "
        "Você deu um passo importante, {name} — em breve enviamos os próximos passos."
    ),
    "lead.paid.receipt": (
        "{name}, aqui está o comprovante do seu pagamento de {valor}:\n{link}\n"
        "Guarde para referência, {name}."
    ),
    "lead.paid.coordinator": (
        "{name}, uma nova matrícula entrou no seu polo. "
        "Acompanhe quando o aluno preencher os dados, {name}."
    ),
    "lead.paid.promoter": (
        "{name}, seu indicado pagou a matrícula! ✅ "
        "Sua comissão entra no fechamento de sexta, {name}. 💸"
    ),
    # ── ENROLLMENT (coleta → liberação) ──────────────────────────────────────
    "enrollment.awaiting_release": (
        "{name}, uma matrícula concluiu o envio de dados e aguarda a sua liberação no painel. "
        "Confira quando puder, {name}."
    ),
    "enrollment.released": (
        "Parabéns, {name}! 🎓 Sua matrícula foi liberada e você já é nosso aluno. "
        "Seja muito bem-vindo(a), {name}!"
    ),
    # ── CANDIDATE → TRAINING → PROMOTER (funil do colaborador) ────────────────
    "candidate.training_started": (
        "Cadastro concluído, {name}! 🎓 Seu treinamento começou — acesse para estudar e responder "
        "as atividades, {name}."
    ),
    "training.awaiting_interview": (
        "{name}, um candidato concluiu o treino e aguarda a sua entrevista de aprovação. "
        "Dê uma olhada quando puder, {name}."
    ),
    "training.approved": (
        "Parabéns, {name}! 🎉 Você foi aprovado e agora é PROMOTOR. "
        "{name}, seu link de captação já está ativo — comece a indicar e a ganhar!"
    ),
    # ── STUDENT → VETERAN ────────────────────────────────────────────────────
    "student.document_rejected": (
        "{name}, seu documento ({doc_type}) precisa ser reenviado. "
        "Envie uma nova foto, nítida e legível, {name}."
    ),
    "student.exam_released": (
        "{name}, seus documentos foram aprovados! Você já pode agendar a sua prova quando quiser, {name}."
    ),
    "student.exam_scheduled": (
        "{name}, um aluno do seu polo agendou a prova e aguarda a sua correção. Confira no painel, {name}."
    ),
    "student.exam_passed": (
        "Você foi APROVADO na prova, {name}! 🎉 Estamos finalizando a sua documentação, {name}. Falta pouco!"
    ),
    "student.exam_failed": (
        "{name}, você não atingiu a nota desta vez — mas não desanime. "
        "Reagende para uma nova tentativa, {name}, você consegue!"
    ),
    "student.pendency_opened": (
        "{name}, há uma pendência na sua matrícula: {detail}. "
        "Resolva para seguir com a emissão do diploma, {name}."
    ),
    "student.diploma_issued": (
        "{name}, seu diploma foi emitido e está disponível para retirada! "
        "Procure o coordenador do seu polo, {name}."
    ),
    "student.veteran": (
        "Parabéns, {name}, você se formou! 🎓 Agora você é veterano da plataforma. "
        "Bem-vindo ao clube, {name}!"
    ),
    "student.veteran.coordinator": (
        "{name}, um aluno do seu polo se formou e foi diplomado. ✅ "
        "Sua comissão entra no próximo fechamento, {name}. 💸"
    ),
    # ── HUB / ROLES (designação de coordenador) ──────────────────────────────
    "hub.coordinator_assigned": (
        "Parabéns, {name}! Você agora é COORDENADOR de um polo. "
        "{name}, acompanhe as matrículas e libere os alunos pelo painel."
    ),
}


def first_name(full_name: str | None) -> str:
    """Primeiro nome do destinatário (para personalizar). Sem nome → fallback neutro."""
    if not full_name or not full_name.strip():
        return _FALLBACK_NAME
    return full_name.strip().split()[0]


def text(event: str, **ctx) -> str:
    """Renderiza o teor do evento. `name` (1º nome do destinatário) deve vir no ctx (≥2× no texto)."""
    template = _MESSAGES.get(event)
    if template is None:
        raise KeyError(f"notify event sem teor no catálogo: {event}")
    ctx.setdefault("name", _FALLBACK_NAME)
    return template.format(**ctx)


def is_tts(event: str) -> bool:
    """True se o evento é um MOMENTO ESPECIAL (vai por voz). Default = texto."""
    return event in _TTS_EVENTS
