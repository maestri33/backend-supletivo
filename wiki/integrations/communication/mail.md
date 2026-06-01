# mail — integrations/comunicacao/mail (SMTP)

> **ESTADO:** cliente de email (SMTP STARTTLS:587) + validador + templates — porte do micro legado
> (`~/coders/backend/notify`), **testado com chamadas REAIS** (login + envio pro Gmail do Victor +
> envio com imagem/QR, 2026-06-01). §4-item-1, subgrupo **comunicação**. Label do app: `mail`. É **só
> o cliente** — quem orquestra contato/log/template-por-contexto/inbound é o `notify` (ainda não existe).

App Django que porta o envio de email do legado pro monólito. **Uma via:** SMTP STARTTLS na porta 587,
autenticado como `noreply@v7m.org` no `mail.v7m.org` (Mailcow aplica DKIM/SPF/DMARC na submissão). Sem
models/migração/endpoint (cliente stateless; templates são arquivos em disco). Consumo in-process pelo `notify`.

## Config (.env, CONVENTION §8/§10)

| Chave | Exemplo | O que é |
|---|---|---|
| `MAIL_SMTP_HOST` | `mail.v7m.org` | host do servidor SMTP |
| `MAIL_SMTP_PORT` | `587` | porta (STARTTLS) |
| `MAIL_SMTP_USER` | `noreply@v7m.org` | login (autentica o envio) |
| `MAIL_SMTP_PASSWORD` | `••••` | senha do noreply (lida via `os.environ` literal) |
| `MAIL_FROM_EMAIL` | `noreply@v7m.org` | remetente (default = user) |
| `MAIL_FROM_NAME` | `Supletivo Brasil` | nome exibido no `From` e `{{service_name}}` |
| `MAIL_TIMEOUT` | `30` | timeout (s) |

Sem host/user/senha → checks `mail.E001/E002/E003` **travam** o boot (padrão whatsapp/asaas).

## Cliente (`client.py`)

`MailClient` — `smtplib` é bloqueante, então roda em `asyncio.to_thread`; a API é **async** (consumo
in-process pelo `notify`, async). `get_client()` constrói com a config do `.env`.
- `send_email(to, subject, *, html_body, plain_body=None)` → monta `MIMEMultipart("alternative")`
  (plain + html), `From: Supletivo Brasil <noreply@v7m.org>`, STARTTLS + login + envia. Retorna
  `{to, subject, from, refused}`. Falha de SMTP → `MailError` (guarda `recipients_refused`).
- `verify_login()` → conecta + STARTTLS + login **sem enviar** (usado pelo `mail_health`).

## Templates (`templates.py`) — arquivos HTML em disco, sem DB

5 wrappers em `templates/` (porte literal do legado): `default` (neutro) + `welcome`/`checkout`/
`receipt`/`parabens` (variam só cor de destaque + rótulo do rodapé). `render(slug, *, title, content,
content_is_html=False)` carrega o arquivo (fallback `default`) e troca `{{title}}`/`{{content}}`/
`{{service_name}}`; texto humano é escapado + bold markdown → `<strong>` + `\n` → `<br>`.
- `text_to_html(text)` — a mesma higienização, exposta pra reuso.
- `media_html(media_url, media_type, caption="")` — snippet pra **embutir mídia por URL** (image →
  `<img src=URL>` inline; video/audio/document → ícone + link). Provado real com o QR de pagamento.

> Alinhado à CONVENTION §12 (mensagem mora no app emissor) e §8 (integration fino). Sem CRUD/edição-
> por-IA de template — adiado pro `notify`.

## Validador (`validator.py`)

`validate_email(email, *, smtp_check=False) -> EmailValidation`: (1) regex formato; (2) DNS MX
(`dnspython`); (3) opcional RCPT TO no MX. `is_valid = has_mx` (ou `smtp_valid` quando o probe roda).
Corrige um bug do legado (`mailfrom()` → método real `mail()`). Log mascara o email (sem PII). Serve à
unicidade do §9 (consumo futuro por `users/auth`). `smtp_check` off por default (Gmail bloqueia o probe).

## Como validar (§8 — chamada real)

```bash
python manage.py mail_health                                   # conecta + login (auth), sem enviar
python manage.py mail_validate victormaestri@gmail.com         # formato + MX (--smtp p/ RCPT)
python manage.py mail_send victormaestri@gmail.com --slug welcome --title "..." --content "..."
# imagem/QR embutida por URL pública:
python manage.py mail_send victormaestri@gmail.com --slug receipt --title "Seu QR" \
    --content "Escaneie:" --media-url https://dev.m33.live/media/qrcodes/pay_xxx.png --media-type image
```

Evidência: `.claude/tests/1-comunicacao-mail.md` (login real + 2 envios reais aprovados pelo Victor).

## Rabo pra trás (vira spec/feature nova com o `notify`)
- App `notify` (§4-item-2): contatos, logs em DB, orquestração multicanal (WhatsApp+email), flags
  ai/tts/img, webhook de status, e templates por contexto/CRUD/edição-por-IA.
- Anexo binário real (CID inline) — hoje a mídia vai por URL pública (`<img src>`).
