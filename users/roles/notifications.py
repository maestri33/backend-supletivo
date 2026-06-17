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
        "training.approved",  # virou promotor (sem treino obrigatório pendente — já pode captar)
        "training.cleared",  # concluiu o treino obrigatório → painel liberado (já pode captar)
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
    "enrollment.selfie_rejected": (
        "{name}, sua selfie não pôde ser confirmada: {detail}\n"
        "Envie uma nova foto pelo aplicativo, {name}."
    ),
    "enrollment.selfie_approved": (
        "Tudo certo, {name}! ✅ Sua foto foi aprovada e sua matrícula está assinada. "
        "Agora é com a gente, {name} — avisamos assim que sua matrícula for liberada."
    ),
    "enrollment.selfie_in_review": (
        "{name}, a selfie de uma matrícula precisa da sua análise — a IA ficou em dúvida. "
        "Aprove ou reprove no painel, {name}."
    ),
    # RG da matrícula — validação por IA (plan/12). {detail} = motivo dado pela IA/coordenador.
    "enrollment.rg_rejected": (
        "{name}, precisamos de uma nova foto do seu RG: {detail} "
        "Reenvie pelo aplicativo, {name} — é rapidinho. 📄"
    ),
    "enrollment.rg_in_review": (
        "{name}, o RG de uma matrícula precisa da sua análise: {detail} "
        "Aprove ou reprove no painel, {name}."
    ),
    "enrollment.rg_approved": (
        "Boa notícia, {name}! ✅ Seu RG foi aprovado e sua matrícula segue em frente. "
        "Continue o preenchimento, {name}."
    ),
    # Ciclo da TAXA da matrícula (plan/14, Victor 2026-06-12) — TODOS pro COORDENADOR, nunca pro
    # aluno (política interna do polo). Sem TTS (não é momento especial). {student_name} = o aluno.
    "enrollment.fee_paid": (
        "{name}, a 1ª parcela da taxa de {student_name} foi PAGA ({valor}). ✅ "
        "A instituição já pode liberar o login e a senha — conclua a matrícula no painel, {name}."
    ),
    "enrollment.fee_scheduled": (
        "{name}, a 2ª parcela da taxa de {student_name} ({valor}) foi agendada para {due_date}. "
        "O pagamento sai sozinho no vencimento, {name}."
    ),
    "enrollment.fee_due_paid": (
        "{name}, a 2ª parcela da taxa de {student_name} ({valor}) foi PAGA no vencimento. ✅ "
        "Taxa quitada, {name} — nada mais a fazer."
    ),
    "enrollment.fee_problem": (
        "{name}, deu problema na taxa de {student_name}: {detail} "
        "Confira no painel, {name}, e tente de novo se for o caso."
    ),
    # ── CANDIDATE → PROMOTER → (treino overlay) (funil do colaborador, Victor 2026-06-16) ──
    "candidate.selfie_rejected": (
        "{name}, sua selfie não pôde ser confirmada. Envie uma nova foto, nítida e mostrando o rosto, {name}."
    ),
    "candidate.rejected": (
        "{name}, seu cadastro de colaborador não foi aprovado neste momento. "
        "Fale com o coordenador do seu polo para entender os próximos passos, {name}."
    ),
    "candidate.selfie_approved": (
        "Boa notícia, {name}! ✅ Sua selfie foi aprovada e o cadastro segue em frente. "
        "Continue o preenchimento, {name}."
    ),
    "candidate.selfie_in_review": (
        "{name}, a selfie de um candidato precisa da sua análise — a IA ficou em dúvida. "
        "Aprove ou reprove no painel, {name}."
    ),
    # Documento do CANDIDATO (plan/15 B) — espelho do aluno; mesmo catálogo, chaves próprias.
    "candidate.document_rejected": (
        "{name}, precisamos de uma nova foto do seu documento: {detail} "
        "Reenvie pelo aplicativo, {name} — é rapidinho. 📄"
    ),
    "candidate.document_in_review": (
        "{name}, o documento de um candidato precisa da sua análise — a IA ficou em dúvida. "
        "Aprove ou reprove no painel, {name}."
    ),
    "candidate.document_approved": (
        "Boa notícia, {name}! ✅ Seu documento foi aprovado e o cadastro segue em frente. "
        "Continue o preenchimento, {name}."
    ),
    # coordenador destravou o tipo de documento (candidato escolheu RG/CNH errado). → candidato.
    "candidate.doc_type_reset": (
        "{name}, liberamos o reenvio do seu documento — pode mandar a foto do tipo certo (RG ou CNH). "
        "É só subir de novo pelo aplicativo, {name}. 📄"
    ),
    # candidato concluiu a coleta e aguarda a APROVAÇÃO do coordenador (vira promotor). → coordenador.
    "candidate.awaiting_approval": (
        "{name}, um candidato concluiu o cadastro e aguarda a sua aprovação para virar promotor. "
        "Confira no painel, {name}."
    ),
    # coordenador aprovou → virou PROMOTOR e NÃO há treino obrigatório pendente (já pode captar). TTS.
    "training.approved": (
        "Parabéns, {name}! 🎉 Você foi aprovado e agora é PROMOTOR. "
        "{name}, seu link de captação já está ativo — comece a indicar e a ganhar!"
    ),
    # virou promotor MAS há treino obrigatório pendente → painel travado até concluir. Sem TTS.
    "training.must_train": (
        "Parabéns, {name}! Você foi aprovado e agora é PROMOTOR. Antes de liberar seu painel, {name}, "
        "conclua o treinamento obrigatório no aplicativo — assim que terminar, tudo é liberado."
    ),
    # concluiu TODAS as matérias obrigatórias → painel liberado (já pode captar). TTS.
    "training.cleared": (
        "Treinamento concluído, {name}! 🎉 Seu painel está liberado e seu link de captação ativo. "
        "Agora é com você, {name} — comece a indicar e a ganhar!"
    ),
    # staff publicou uma nova matéria obrigatória → o promotor é re-travado até concluí-la. Sem TTS.
    "training.new_material": (
        "{name}, há um novo treinamento obrigatório no aplicativo. "
        "Conclua a atividade para continuar usando o painel, {name}."
    ),
    # ── STUDENT → VETERAN ────────────────────────────────────────────────────
    "student.document_rejected": (
        "{name}, seu documento ({doc_type}) precisa ser reenviado. "
        "Envie uma nova foto, nítida e legível, {name}."
    ),
    "student.document_in_review": (
        "{name}, um documento de aluno ({doc_type}) precisa da sua análise — a IA ficou em dúvida. "
        "Aprove ou reprove no painel, {name}."
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
    # coordenador suspende / reativa um promotor do polo (WP5).
    "promoter.suspended": (
        "{name}, sua atuação como promotor foi temporariamente suspensa pelo coordenador do polo. "
        "Fale com o coordenador para regularizar, {name}."
    ),
    "promoter.reactivated": (
        "Boa notícia, {name}! Sua atuação como promotor foi reativada. "
        "{name}, seu link de captação está ativo de novo — bora!"
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
