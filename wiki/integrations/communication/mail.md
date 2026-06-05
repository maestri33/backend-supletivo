# mail — integrations/communication/mail (SMTP)

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

Evidência: `.claude/tests/1-communication-mail.md` (login real + 2 envios reais aprovados pelo Victor).

## Rabo pra trás (vira spec/feature nova com o `notify`)
- App `notify` (§4-item-2): contatos, logs em DB, orquestração multicanal (WhatsApp+email), flags
  ai/tts/img, webhook de status, e templates por contexto/CRUD/edição-por-IA.
- Anexo binário real (CID inline) — hoje a mídia vai por URL pública (`<img src>`).

## ⚠️ Troubleshooting de rede — LEIA se o email PARAR de sair (recorrente)

**Sintoma:** `mail_health`/`mail_send` falham com **timeout** conectando em `mail.v7m.org:587`
(ou o app loga erro de conexão SMTP). Auth e senha estão certas — o problema é **rede**, não credencial.

**Causa raiz (já mordeu 3x — diagnosticado e resolvido em 2026-06-05):**
`mail.v7m.org` resolve pro **IP público** da VM de email (`135.181.216.147`, e AAAA `::147`). De dentro
do parque (LXC/VM em vmbr1/vmbr2, ex.: este workspace `10.1.20.30`), o host Proxmox **não faz o hairpin**
pra esse IP público: a `vmbr_wan` tem `pointopoint 135.181.216.129`, então o `/32` do mail é mandado pro
gateway da Hetzner em vez de entregue on-link, e (com NIC `firewall=1`) a conntrack zone não casa → a
conexão fica `[UNREPLIED]` → timeout. Do *host* funciona; de *dentro* não.

**O que conserta (no HOST pve-prod, não no app):** uma rota on-link pro IP do mail —
```bash
ip route add 135.181.216.147/32 dev vmbr_wan      # entrega direta na bridge, sem desvio pelo .129
```
✅ **Tornada PERSISTENTE em 2026-06-05** como `post-up` no stanza `vmbr_wan` do
`/etc/network/interfaces` do host. ANTES disso ela era adicionada na mão e **sumia todo reboot do host**
— por isso o email "quebrava sozinho" de tempos em tempos (cada reboot = quebra).

**Diagnóstico rápido (de dentro do workspace):**
```bash
getent hosts mail.v7m.org                          # deve mostrar o IP público 135.181.216.147 (e ::147)
timeout 6 bash -c '</dev/tcp/135.181.216.147/587' && echo OK || echo TIMEOUT   # se TIMEOUT => rota caiu
timeout 6 bash -c '</dev/tcp/10.1.30.150/587'   && echo OK || echo TIMEOUT     # interno: deve ser OK
```
- Público TIMEOUT **e** interno OK → a rota on-link no host caiu. **Fix:** no host pve-prod, conferir
  `ip route get 135.181.216.147` (se aparecer `via 135.181.216.129`, a rota sumiu) e rodar o
  `ip route add ...` acima. Se sumiu mesmo após reboot, conferir se o `post-up` ainda está no
  `/etc/network/interfaces` (stanza `vmbr_wan`).
- Ambos TIMEOUT → problema na VM de email / Mailcow, não na rota (checar a VM 150).

**Plano B (não depende da rota):** apontar internamente pro mail pela perna interna `10.1.30.150`
(bridge vmbr2) ou pelo tailnet `mail` — ambos alcançáveis de dentro sem hairpin. ⚠️ NÃO trocar
`MAIL_SMTP_HOST` pro IP cru (quebra a verificação de hostname do TLS no STARTTLS); o certo é manter
`mail.v7m.org` (o SNI casa o cert) e resolver o nome pro IP interno (ex.: linha em `/etc/hosts` do
guest: `10.1.30.150 mail.v7m.org`).

> Infra/host: este é um gotcha do servidor pve-prod, documentado também na memória de ops do Claude
> (`gotchas` / `vm-150-mail` / `ct-3050-typebot`). Última quebra+fix: 2026-06-05.
