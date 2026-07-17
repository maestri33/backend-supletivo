# notify → serviço independente multi-tenant (plano de desmembramento)

> **ESTADO: PLANO** (nada implementado ainda). Aprovação do Victor pendente nas
> [decisões assumidas](#decisões-assumidas-victor-veta) antes de qualquer código.
> Contexto: o notify hoje é um app in-process do monólito ([[wiki/notify/notify]]); a decisão é
> desmembrá-lo em um **serviço próprio, com servidor próprio**, onde cada cliente ("conta") tem
> **seu número de WhatsApp**, seu remetente de e-mail e sua voz de TTS. O backend Supletivo vira o
> **primeiro cliente** do serviço; outros serviços do Victor entram depois criando uma conta.

## Visão

```
HOJE (in-process)                          DEPOIS (serviço)
─────────────────                          ────────────────
callers (63) ──► notify/interface ──►      callers (63) ──► notify/interface (MESMA assinatura,
  Django-Q ──► dispatch ──► Evolution        vira SDK HTTP) ──► notify-server (LXC própria)
  / SMTP / ElevenLabs                          ├─ Account "supletivo" ── número X ── SMTP ── voz
  (1 número fixo no .env)                      ├─ Account "outro-serviço" ── número Y ...
                                               └─ Django-Q ──► dispatch ──► Evolution/SMTP/11Labs
```

O que o serviço **é**: um despachante de notificações estilo Twilio/Postmark — recebe conteúdo
PRONTO + destinatário, entrega por WhatsApp (texto/mídia/voice-note-TTS) e e-mail, audita status
por canal, e é dono das instâncias da Evolution (números).

O que o serviço **não é** (fica no backend): teor das mensagens (Template/Trigger, catálogo
fallback, storytelling por IA, painel staff de edição), regras de funil, perfil/contato. O bot
(inbound conversacional) está FORA deste plano — não funciona e vai sair do backend depois; o
desenho apenas **não fecha a porta** pra ele (ver Fase 3).

## Decisões assumidas (Victor veta)

| # | Decisão | Racional |
|---|---|---|
| 1 | **Stack:** Django + Ninja + Django-Q + Postgres, **repo novo** (sug.: `notify-server`), LXC própria na DMZ, database própria no CT 2100 | mesma receita provada do monólito; os clients whatsapp/mail já são async/desacoplados — portam quase 1:1; admin de graça vira o painel de operação |
| 2 | **Teor fica no backend** (dispatcher puro) | storytelling usa a engine de IA do backend; painel staff intocado; migração muito menor. Templates multi-tenant no serviço = fase futura, se virar produto |
| 3 | **Tenancy: `Account` (conta) com N números** | api-keys por conta; 1+ números WhatsApp (cada um = instância Evolution), 1 identidade de e-mail, 1 config de voz TTS. Supletivo = 1ª conta com 1 número. Já nasce pronto pra "número de vendas + número de suporte" |
| 4 | **Inbound:** o serviço vira o dono do webhook da Evolution (persiste o evento bruto), mas **relay por conta é fase 3** | o bot está morto; ninguém consome inbound hoje. O serviço só guarda; quando o bot renascer (fora do backend), pluga no relay |
| 5 | **`external_id` gerado pelo CLIENTE** (SDK) e aceito pelo serviço | preserva o contrato de hoje: `send()` devolve o handle NA HORA e nunca bloqueia (§12) mesmo se o serviço estiver fora — o SDK enfileira retry local com o mesmo UUID |
| 6 | **Validação de telefone vira endpoint** (`POST /v1/phone/check`) | o register (`users/auth/service.py`) usa `check_numbers` da Evolution; com o endpoint, o backend zera credencial de Evolution/SMTP/ElevenLabs no `.env` |
| 7 | **TTS via omnirouter** (Victor 2026-07-17): o serviço chama o omnirouter (`10.1.30.35`, LAN/DMZ) direto — NÃO embute client de provider (ElevenLabs) | keys de provider moram no omnirouter; o notify gera → recebe o áudio → serve o mp3 do próprio MEDIA_ROOT (Evolution busca pela LAN). Demais funções de IA do backend (storytelling, bot, OCR): análise CASO A CASO, fora deste ciclo |

## Fase 1 — o serviço (repo novo, sem tocar o backend)

### Models
- `Account` — slug, nome, ativo. O tenant.
- `ApiKey` — FK conta, hash (sha256) da chave, label, ativo. Auth `Authorization: Bearer`.
- `WhatsAppNumber` — FK conta, `instance_name` (Evolution), slug, default flag, status de conexão.
  A instância atual do Supletivo (já conectada) é ADOTADA, não recriada.
- `MailIdentity` — FK conta, SMTP host/port/user/senha, from_name/from_email, timeout.
- `TtsConfig` — FK conta, api-key ElevenLabs, voice-ids M/F. **Preserva a regra CRUZADA** (homem
  recebe voz feminina e vice-versa — [[wiki/notify/notify]]; NÃO "corrigir").
- `Notification` — porte do model atual **+ FK conta + FK número usado**. Mesmos status/erros por
  canal, `idempotency_key` (unique POR CONTA), `attempts`, `tts_audio_path`.
- `InboundEvent` — payload bruto da Evolution por instância (idempotente por `wa_message_id`).
  Só armazena no v1 (decisão 4).

### Ports do monólito (copiar quase 1:1)
- `integrations/communication/whatsapp/client.py` — Evolution 2.3.7, 9º dígito BR, send_text/
  send_media/send_whatsapp_audio/check_numbers. Muda só a origem da config: `.env` → row do número.
- `integrations/communication/mail` — client SMTP + templates HTML (`md_to_html`, `media_html`,
  wrappers). Config: `.env` → `MailIdentity` da conta.
- TTS: client HTTP fino pro **omnirouter** (`10.1.30.35`, decisão 7) — contrato a confirmar com o
  Victor. O mp3 é salvo e servido pelo PRÓPRIO serviço (MEDIA_ROOT dele); a Evolution busca pela
  URL LAN do serviço. Nada de `integrations/ai` portado.
- `notify/sanitize.py` (for_whatsapp/for_tts) e `notify/dispatch.py` — o claim em 3 fases
  (G16: CLAIM sob lock → envio fora da transação → resultado; recuperação por texto sem regenerar
  TTS) porta INTEIRO. É a parte mais valiosa e mais testada do app.
- Rewrite de mídia `_to_lan`: mantém, com o par (base pública → base LAN) no `.env` do serviço;
  por conta só se/quando um tenant morar fora da LAN.

### API v1 (Ninja, auth por api-key da conta)
| Rota | Uso |
|---|---|
| `POST /v1/send` | payload = args do `send()` atual (text, phone, email, title, subject, flags de canal, media_url/type, gender, mail_template, idempotency_key, caller) + `external_id` opcional do cliente + `number` opcional (default da conta). 202 → `{external_id, statuses}` |
| `GET /v1/notifications/{external_id}` | status por canal (o OTP e o painel staff consomem) |
| `GET /v1/notifications` | histórico com filtros (caller, phone, email, período) — o `staff/notify/history` do backend vira proxy disto |
| `POST /v1/phone/check` | resolve 9º dígito + existe-no-zap (substitui o uso direto no register) |
| `GET /v1/health` | saúde (padrão da casa) |
| Webhook Evolution (por instância) | persiste `InboundEvent`; 200 na hora |

Onboarding de número (criar instância + QR + status de conexão) começa **pelo admin do Django**
(operação do Victor); virar API/painel é fase 3 — no v1 a única instância já existe.

### Deploy e validação
- LXC própria (padrão `backend-v7m`): Caddy → nginx → gunicorn + qcluster; database própria no
  Postgres CT 2100; `.env` gitignored.
- Validação REAL (§8, como todo app da casa): porte do `notify_send` (management command) e prova
  dos 3 canais no aparelho/e-mail do Victor + `phone/check` + idempotência, ANTES da fase 2.

## Fase 2 — conectar o backend (cutover)

1. **SDK no lugar do miolo** — `notify/interface/send.py` mantém a MESMA assinatura (os 63
   callsites e o `send_adhoc`/`send_event` não mudam): gera `external_id` (UUID), tenta o POST
   (timeout curto, LAN); falhou → enfileira retry no Django-Q **com o mesmo UUID** e devolve o
   handle mesmo assim (§12: nunca quebra o caller). `run_sync=True` → POST síncrono sem fila.
2. **OTP** — troca a FK `otp.notification` por `notification_external_id` (CharField). Único
   consumidor do `get_by_external_id` hoje; consulta de status vira `GET /v1/notifications/{id}`.
3. **Painel staff** — `GET staff/notify/history` vira proxy do serviço (mesmo contrato pro front).
   CRUD de Template/Trigger, preview, adhoc: intocados (teor continua no backend, decisão 2).
4. **Register** — `users/auth/service.py` troca o client Evolution por `POST /v1/phone/check`.
5. **Histórico antigo** — migração one-time das rows de `Notification` do backend pra conta
   `supletivo` do serviço (o painel não perde o passado).
6. **Rollout com flag** — `NOTIFY_MODE=local|remote` no `.env` do backend: o shim escolhe o
   caminho. Produção corta pra `remote` só após E2E real (3 canais + OTP login + history);
   rollback = voltar a flag.
7. **Descomissionar depois do corte** — `notify/dispatch.py`, model `Notification` local,
   `integrations/communication/{whatsapp,mail}`, TTS do notify no `integrations/ai`, e as envs
   `WHATSAPP_*`/`MAIL_*`/`ELEVENLABS_*` do backend. (O `bot/` importa `_br_phone_variants` em
   runtime — já está quebrado e de saída; não bloqueia o boot, não seguramos o corte por ele.)

## Fase 3 — outros serviços e futuros (fora deste ciclo)
- **Novo cliente** = criar `Account` + api-key + número (instância nova via QR) no serviço.
- **Relay inbound por conta** (webhook-URL + HMAC): o novo lar do bot pluga aqui.
- **Templates multi-tenant no serviço** (se o Victor quiser virar produto), painel próprio,
  métricas, rate-limit por conta, onboarding self-service.

## Riscos / pontos de atenção
- **Um hop de rede a mais** no caminho do OTP (login). Mitigação: LAN + timeout curto + fila de
  retry no SDK; o OTP já tolera envio assíncrono.
- **Duas filas** (Django-Q no backend p/ retry do SDK + Django-Q no serviço p/ dispatch). Aceito:
  cada lado cuida da própria resiliência.
- **Segredo por conta no DB do serviço** (SMTP): avaliar criptografia at-rest simples (Fernet com
  chave no `.env`) na implementação.
- **Omnirouter fora do ar** → o dispatch já tem o fallback certo: voice-note falhou → cai pra
  TEXTO no WhatsApp (o marco nunca fica mudo). Comportamento portado como está.
- **`idempotency_key` passa a ser única POR CONTA** (hoje é global) — sem impacto pro backend.
- O serviço NÃO valida/renderiza teor: sanitização de TTS e conversão md→WhatsApp/HTML continuam
  nele (são de ENTREGA, não de teor).
