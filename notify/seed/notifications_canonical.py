"""Templates canônicos das 5 principais notificações (pt-BR, curtas, acolhedoras).
ponytail: corpo = o que o aluno recebe. Fala com a pessoa, não com papel.
"""
from __future__ import annotations

CANONICAL_TEMPLATES = {
    "welcome": {
        "title": "Bem-vindo(a)!",
        "subject": "Bem-vindo(a) ao caminho do diploma",
        "body_md": "Oi, {nome}! 👋\n\nSua matrícula tá confirmada. A gente tá junto daqui pra frente — pode me chamar se travar em qualquer parte.\n\nQuando sair a prova, você recebe um aviso aqui. 📚",
        "channels": "whatsapp,email",
        "is_tts": True,
        "tone": "acolhedor",
    },
    "payment_received": {
        "title": "Pagamento confirmado",
        "subject": "Sua matrícula tá ativa",
        "body_md": "Beleza, {nome}! 💚\n\nRecebemos o pagamento. Sua matrícula tá ativa — falta só o RG e a selfie pra terminar a inscrição.\n\nQuer continuar agora? É rapidinho.",
        "channels": "whatsapp,email",
        "is_tts": True,
        "tone": "celebratório",
    },
    "exam_scheduled": {
        "title": "Prova marcada",
        "subject": "Data da sua prova",
        "body_md": "Oi, {nome}! 📅\n\nSua prova tá marcada: {data} às {horario} em {local}.\n\nChega 30 min antes com documento com foto. Bom estudo!",
        "channels": "whatsapp,email",
        "is_tts": False,
        "tone": "direto",
    },
    "certificate_issued": {
        "title": "🎓 Diploma pronto",
        "subject": "Seu diploma tá pronto",
        "body_md": "{nome}! 🎉\n\nSeu diploma foi emitido. A gente avisa quando tiver disponível pra retirada.\n\nParabéns — você chegou lá.",
        "channels": "whatsapp,email",
        "is_tts": False,
        "tone": "celebratório",
    },
    "lead_followup": {
        "title": "Bora continuar?",
        "subject": "Sua inscrição tá esperando",
        "body_md": "Oi, {nome}! Tudo bem?\n\nVi que você começou a inscrição e não terminou — ficou com dúvida? Posso te ajudar rapidinho aqui.\n\nSe não fizer mais sentido, sem problema também. Só me avisa. 🙂",
        "channels": "whatsapp",
        "is_tts": False,
        "tone": "acolhedor",
    },
}
