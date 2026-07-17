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

## O que falta pra Fase 2 (cutover do backend)
NÃO iniciar sem validação real da Fase 1 aprovada pelo Victor.

1. **SDK no monólito** — `notify/interface/send.py` vira HTTP client (mesma assinatura, 63 callsites intocados)
2. **Seed dos templates** — migração one-time do backend pro serviço
3. **OTP** — trocar FK por `notification_external_id` (CharField)
4. **Painel staff** — front passa a falar com notify-server direto
5. **Register** — trocar client Evolution por `POST /v1/phone/check`
6. **Rollout com flag** — `NOTIFY_MODE=local|remote` no backend

## Fatos do monólito que a implementação NÃO pode esquecer
- `users/auth/service.py:98` — register usa `resolve_br_number`+`check_numbers` → vira `/v1/phone/check`
- `users/auth/otp/service.py:165` — OTP guarda FK pra Notification (Fase 2 troca por string)
- `api/staff_notify.py` — painel staff atual: é o contrato a reproduzir no serviço
- `bot/` — NÃO tocar: quebrado, sai depois; só não fechar porta do relay inbound
- Django-Q re-executa task em erro: claim G16 preservado (recuperação por TEXTO sem regenerar TTS)

## Branch do monólito
`claude/notify-multi-tenant-refactor-0q6if1` — PR #45 (só wiki). Mergear quando Victor aprovar o texto.
