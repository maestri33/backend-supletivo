# Análise e Implementação do `want_sanitize`

## Contexto

O campo `want_sanitize` foi adicionado em produção durante um hotfix (migração `0002_notification_want_sanitize.py`) mas nunca foi implementado no código. O campo existe na tabela `notify_notification` mas sempre fica com valor `False` (default) e nunca é usado.

## Propósito Original

Conforme comentário no model: "sanitização do conteúdo antes do envio (remove markdown/emojis p/ TTS, etc.)"

O objetivo era limpar o texto para text-to-speech (TTS), pois:
- **Emojis** não fazem sentido em voz (🎉 = silêncio ou "emoji palmas")
- **Markdown** (`**bold**`, `*italic*`) não tem significado em áudio
- **URLs completas** ficam longas e confusas quando lidas em voz

## Análise do Código Atual

### Mensagens do Sistema

As notificações em `users/roles/notifications.py` contêm:
- Emojis frequentes: 🎉, 💚, ✅, 💸, 👊, 📚, etc.
- Markdown: `**texto**` para negrito
- URLs completas em PIX copia-e-cola e links de checkout

Exemplo:
```python
"lead.captured": (
    "Olá, {name}! 🎉 Que bom ter você com a gente. Seu cadastro está pronto, {name} — "
    "falta só um passo pra garantir sua vaga: concluir o pagamento. Em instantes envio o link. "
    "Bora juntos nessa jornada!"
)
```

### Canais de Envio

1. **WhatsApp**: Emojis e markdown são BONS (melhoram a leitura visual)
2. **E-mail**: Formatação é convertida para HTML (OK também)
3. **TTS (voz)**: Emojis e markdown são RUINS (poluem o áudio)

### Padrão de Uso

TTS só é usado em "momentos especiais" (catálogo `_TTS_EVENTS`):
- `lead.paid` - matrícula começou
- `enrollment.selfie_approved` - assinatura com selfie
- `student.diploma_issued` - diploma emitido
- `training.approved` - virou promotor
- `training.cleared` - treino concluído

## Decisão de Design

### ❌ Opção 1: Manter campo `want_sanitize`
**Contra**:
- Campo nunca é usado (sempre `False`)
- Adiciona complexidade sem benefício
- Requer que o caller decida quando sanitizar

### ✅ Opção 2: Sanitização automática para TTS
**A favor**:
- TTS **sempre** precisa de sanitização
- WhatsApp/e-mail **nunca** precisam (formatação é boa)
- Decisão é óbvia baseada no canal, não precisa de flag
- Código mais simples e direto

## Implementação Escolhida

### 1. Criado módulo `notify/sanitize.py`

Função `sanitize_for_tts()` que:
- Remove emojis (ranges Unicode completos)
- Remove markdown bold/italic (`**texto**`, `*texto*`)
- Simplifica URLs (substitui por "link")
- Normaliza espaços e quebras de linha extras
- Preserva pontuação (importante para prosódia)

### 2. Integrado em `notify/dispatch.py`

Na função `_send_tts()`:
```python
from notify.sanitize import sanitize_for_tts

text = sanitize_for_tts(notif.text)
rel_path = ai_service.tts(text, caller=f"notify:{notif.caller}", gender=notif.gender or None)
```

Sanitização é **automática** quando o canal é TTS - sem flag necessária.

### 3. Removido campo `want_sanitize`

- Removido do `notify/models.py`
- Criada migração `0003_remove_notification_want_sanitize.py`
- Campo nunca foi usado, remoção é segura

### 4. Testes Completos

Criado `tests/test_notify_sanitize.py` com 9 testes:
- Remove emojis ✓
- Remove markdown (bold/italic) ✓
- Simplifica URLs ✓
- Normaliza whitespace ✓
- Testa notificações reais ✓
- Preserva pontuação ✓

Todos os testes passam.

## Benefícios da Implementação

1. **Simples**: Sem flag booleana, decisão baseada no canal
2. **Correto**: TTS sempre recebe texto limpo
3. **Transparente**: Caller não precisa se preocupar com sanitização
4. **Testado**: Cobertura completa com casos reais
5. **Manutenível**: Lógica isolada em módulo próprio

## Exemplos de Transformação

### Antes (texto original):
```
Olá, João! 🎉 Que bom ter você com a gente. Acesse: https://example.com/link
```

### Depois (sanitizado para TTS):
```
Olá, João! Que bom ter você com a gente. Acesse: link
```

### WhatsApp/E-mail (sem sanitização):
```
Olá, João! 🎉 Que bom ter você com a gente. Acesse: https://example.com/link
```
(Mantém emojis e URL completa - bom para leitura visual)

## Migração em Produção

1. ✅ Campo `want_sanitize` já existe em produção (migração 0002)
2. ✅ Campo nunca foi usado (sempre False)
3. ⏳ Deploy da nova lógica de sanitização
4. ⏳ Aplicar migração 0003 que remove o campo

**Risco**: Zero - campo não é usado, remoção é segura.

## Conclusão

A implementação **remove o campo `want_sanitize`** e substitui por **sanitização automática baseada em canal**. É mais simples, correto e manutenível que uma flag booleana. TTS sempre recebe texto limpo, WhatsApp/e-mail mantêm a formatação rica.
