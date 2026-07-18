# HANDOFF — notify-server Fase 1 implementada

> **Para a próxima sessão do Victor.** Estado em 2026-07-17 22h: **Fase 1 COMPLETA — código
> funcional, deploy scripts prontos, TTS contract cravado, repo no GitHub.** Falta infra
> (LXC + Postgres + Evolution) pra colocar no ar.

## O que foi feito nesta sessão

### 1. TTS contract cravado (era pendência #1)
- **Endpoint:** `POST http://10.1.30.35/v1/audio/speech` (OpenAI-compatible)
- **Body:** `{"model":"minimax/speech-2.8-hd","input":"texto","voice":"Portuguese_SereneWoman"}`
- **Response:** bytes do mp3 (200 OK)
- **Provider:** MiniMax via OmniRoute. ElevenLabs indisponível (pagamento pendente).
- **Vozes:** `Portuguese_SereneWoman` (feminina), `Portuguese_GentleTeacher` (masculina)
- **Regra cruzada:** homem→feminina, mulher→masculina (NÃO "corrigir")
- **MCP:** `http://10.1.30.35/api/mcp/stream` (omniroute v3.8.48) — usar pra futuros agentes

### 2. notify-server implementado (65 arquivos, 4358 linhas)
Repo: https://github.com/maestri33/notify-server (privado)

```
notify_server/          # Django project
├── accounts/           # Account, ApiKey, auth middleware
├── channels/           # WhatsAppNumber, MailIdentity, TtsVoices
├── whatsapp/           # driver ABC + EvolutionV2Driver
├── mail/               # SMTP client + md_to_html + HTML templates
├── tts/                # MiniMax via omnirouter (contrato confirmado)
├── notify/             # models, dispatch G16, sanitize, interface
├── seed/               # io parser, templates.md (48 eventos), commands
├── api/                # v1.py, staff.py, webhook.py
├── deploy/             # systemd, Caddy, setup.sh
└── manage.py
```

### 3. O que funciona (testado localmente com SQLite)
- ✅ Django check: 0 issues
- ✅ Migrations geradas e aplicadas (accounts, channels, notify)
- ✅ Seed: 48 templates + 48 triggers na conta supletivo
- ✅ Render de templates: "Parabéns, Victor! 🎉..."
- ✅ Health endpoint: `{"status":"ok","db":true}`
- ✅ TTS client: MiniMax via omnirouter (mp3 real gerado)
- ✅ Management commands: `notify_seed`, `notify_send`, `create_api_key`

### 4. O que NÃO foi testado (precisa de infra real)
- ❌ Envio real de WhatsApp (precisa instância Evolution conectada)
- ❌ Envio real de e-mail (precisa MailIdentity SMTP)
- ❌ TTS real via dispatch (precisa MEDIA_ROOT + URL LAN)
- ❌ Django-Q worker rodando
- ❌ Deploy em LXC
- ❌ Postgres (testado só com SQLite)

## Decisões tomadas (NÃO reabrir)
1. **Repo:** `notify-server` — https://github.com/maestri33/notify-server
2. **TTS:** MiniMax via omnirouter (ElevenLabs quando pagamento resolver)
3. **Auth:** Bearer token → Account (SHA-256 hash, api-keys por conta)
4. **Port gateway:** 8100 (gunicorn), Caddy reverse proxy
5. **Evolution-go:** ainda pendente (licença). Driver v2 no corte.

## Pra colocar no ar — checklist

### Infra (Victor precisa fazer ou aprovar)
1. **LXC nova** na DMZ (padrão `backend-v7m`): Debian/Ubuntu, 1GB RAM, 2 CPU
2. **Database** `notify_server` no Postgres CT 2100 (criar role + grant)
3. **Caddy/nginx** config pra VPN (notify.v7m.org ou IP interno)
4. **Instância Evolution** existente: pegar instance_name + api-key do `.env` atual do backend

### Deploy (automatizado via setup.sh)
```bash
# Na LXC:
cd /opt && git clone https://github.com/maestri33/notify-server.git
cd notify-server
cp .env.example .env  # editar com credenciais reais
bash deploy/setup.sh
```

### .env mínimo pra produção
```
DATABASE_URL=postgres://notify:SENHA@10.1.20.100:5432/notify_server
SECRET_KEY=gerar-com-python-c-import-secrets-secrets-token-urlsafe-50
DEBUG=0
ALLOWED_HOSTS=notify.v7m.org,10.1.x.x
EXTERNAL_URL=https://notify.v7m.org
MEDIA_LAN_BASE=http://10.1.x.x  # IP da LXC na rede interna
MEDIA_ROOT=/opt/notify-server/media
OMNIROUTER_URL=http://10.1.30.35
FERNET_KEY=gerar-com-cryptography
```

### Pós-deploy
```bash
# Criar conta + api-key
python manage.py create_api_key --account supletivo --name "Supletivo Brasil"
# Guardar a chave mostrada!

# Seed templates
python manage.py notify_seed --account supletivo

# Conectar Evolution (admin Django ou shell)
python manage.py shell -c "
from accounts.models import Account
from channels.models import WhatsAppNumber
acc = Account.objects.get(slug='supletivo')
WhatsAppNumber.objects.create(
    account=acc,
    instance_name='NOME_DA_INSTANCIA',  # do .env atual
    driver='evolution-v2',
    slug='principal',
    is_default=True,
)
"

# Smoke test
curl http://localhost:8100/v1/health
```

## Fase 2 — CUTOVER COMPLETO em 2026-07-18

`NOTIFY_MODE=remote` no ar em produção (CT 30101 → CT 30114, conta `supletivo`). `send()`,
`send_event()` (28 dos 36 callsites reais — lead/matrícula/candidato/hub/finance/OTP/bot/...),
OTP, `phone/check` (register/change_phone/check) e o painel staff (`/api/v1/staff/notify/*`,
dual-write local+servidor) todos passando pelo notify-server. Testado ao vivo pós-flip: WhatsApp,
`send_event`, `phone/check` — `sent`/OK. Webhook da Evolution repontado de `10.1.30.34:8001`
(CT 3034, morta — inbound estava se perdendo desde sempre) pra
`http://notify.v7m.org/v1/webhook/evolution/default`, testado com payload sintético (`{"status":
"ok"}`). Rollback a qualquer momento: `NOTIFY_MODE=local` no `.env` + `systemctl restart
backend-web backend-qcluster`.

### ⚠️ Implementação paralela descoberta e revertida no dia do cutover
Enquanto a Fase 2 era feita numa sessão, OUTRA sessão Claude Code implementou (e o Victor mergeou,
PR #46) uma versão própria e mais enxuta direto no branch de prod — sem `send_event`/painel staff
no corte, e com um bug de contrato real no `phone/check` (`{"phone": ...}` em vez de `{"numbers":
[...]}`, que teria dado 422 assim que ligasse o modo remote; nunca validada contra o servidor
real). Foi substituída pela versão mais completa e testada ao vivo. **Nada foi perdido**: essa
implementação inteira (3 commits) está preservada no branch `backup-fase2-parallela-pr46` em
`/opt/backend-supletivo`, caso precise de referência.

### Reconciliação de schema no meio do deploy
A migração da implementação paralela já tinha rodado fisicamente contra o Postgres de produção
(`users_otp_code.notification_external_id` criado como `uuid`, 29/29 rows copiadas) antes de eu
perceber o conflito. Em vez de reverter, o código foi ajustado pro tipo já existente (`UUIDField`
em vez de `CharField(64)` — mais correto mesmo, já que `send()`/`send_event()` sempre devolvem
`str(uuid.uuid4())`) e as migrações `0033`/`0034` foram aplicadas com `--fake` (schema físico já
batia, sem reexecutar SQL).

### Migração do OTP em 2 passos (achado do review adversarial)
A migração original (FK→string) fazia `AddField+RunPython+RemoveField` num passo só — se o
`migrate` rodasse antes do `restart`, o código antigo (ainda esperando a FK) quebrava em toda
query de `OtpCode` até o restart completar. Corrigido: `0033` (aditiva) e `0034` (remove a FK),
aplicadas nessa ordem com restart entre elas. **Qualquer migração futura de model que remova
coluna ainda em uso pelo código atualmente rodando deve seguir esse padrão de 2 passos.**

### Pendências conscientemente adiadas (não bloqueiam nada)
1. **Histórico local antigo** (160 `Notification` rows, 2026-07-01→18, tabela `notify_notification`
   em `backend-supletivo`) — NÃO migrado pra conta `supletivo` no notify-server. Não há endpoint
   de bulk-import no servidor hoje; a tabela local não foi removida (nem vai ser), então nada se
   perde — só fica congelada como histórico pré-corte, consultável se precisar. Construir a
   migração one-time fica pra quando/se fizer falta.
2. **Descomissionamento do `notify/` local** (models, dispatch, seed, `integrations/communication/
   {whatsapp,mail}`, `WHATSAPP_*`/`MAIL_*`/`ELEVENLABS_*` do `.env`) — item 9 do plano original.
   Só depois de um período de estabilização em `remote` (o modo `local` é o rollback; remover o
   código junto o invalidaria).
3. **Bug pré-existente em `dispatch.py`** (monólito E notify-server, de antes da Fase 2): `tts_pending`
   é calculado mas não entra na condição de early-exit do dispatch — `tts=True` sem `whatsapp=True`
   fica preso em `pending` pra sempre. Não é alcançável por nenhum caller real (todo `send_event`
   com TTS já implica `whatsapp=True`); só apareceu num teste manual de CLI com flags incomuns.
   Não corrigido (fora do escopo da Fase 2, código de produção não tocado).
4. **`extra=` kwarg inválido** em `users/roles/student/signals.py:24` (`send_event(..., extra=...)`)
   — bug pré-existente, TypeError latente, capturado por except genérico. Não corrigido.

## Fatos do monólito (arquivados — já implementados)
- `users/auth/service.py` — register/change_phone/check usam `POST /v1/phone/check` no modo remote.
- `users/auth/otp/service.py` — OTP guarda `notification_external_id` (UUIDField).
- `api/staff_notify.py` — dual-write local+servidor no modo remote; `/history` proxia o servidor.
- `bot/` — não tocado (segue dormente); `bot/worker.py` usa `send()`, que já roteia pelos 2 modos.
- Django-Q re-executa task em erro: claim G16 preservado (recuperação por TEXTO sem regenerar TTS).

## Branches
- `claude/wave1-security` (CT 30101, prod) — Fase 2 completa, sincronizado com `origin`.
- `backup-fase2-parallela-pr46` (CT 30101) — a implementação paralela descartada, preservada.
- `claude/notify-fase2` (GitHub, `maestri33/backend-supletivo`) — clone de trabalho, mesmo conteúdo.
- `fase2-api-additions` (GitHub, `maestri33/notify-server`) — aditivos da API já deployados em prod.
