# HANDOFF — desmembramento do notify (continuar em sessão local)

> **Para a próxima sessão (local) do Victor.** Estado em 2026-07-17: **plano fechado e aprovado;
> Fase 1 IMPLEMENTADA (scaffold + models + ports + API + TTS + deploy scripts).** Repo:
> https://github.com/maestri33/notify-server. A fonte de verdade do plano é
> [[wiki/notify/servico-multi-tenant]] (mesmo diretório) — leia ELE antes de codar; este handoff
> é só o mapa de "onde paramos + o que fazer primeiro".
> Branch: `claude/notify-multi-tenant-refactor-0q6if1` · PR draft: **#45** (só wiki; mergear
> quando o Victor aprovar o texto).

## Resumo em 5 linhas
O app `notify` do monólito vira um **serviço independente multi-tenant** (`notify-server`, nome a
confirmar): Django + Ninja + Django-Q, LXC própria na DMZ, database no Postgres geral (CT 2100),
uso só dentro da VPN. Cada `Account` tem api-keys, N números de WhatsApp (instâncias Evolution),
e-mail próprio no mailcow, vozes TTS próprias e **Templates/Triggers próprios** (teor + painel
MIGRAM pro serviço — notify é universal, staff comanda). Backend = primeiro cliente via SDK com
as MESMAS assinaturas de `send()`/`send_event()` (63 callsites intocados).

## Decisões já tomadas (Victor 2026-07-17) — NÃO reabrir
1. Templates + painel staff **no serviço**, por conta (o catálogo do backend vira só seed).
2. Conta `default` com número + e-mail padrão da casa; cada app com e-mail (mailcow) + número seus.
3. TTS: notify → **omnirouter** (`10.1.30.35`) direto; vozes **por conta no notify** (opção "a" —
   passa `voice` pronto; regra CRUZADA M/F preservada: homem recebe voz feminina — NÃO "corrigir").
4. Demais funções de IA (storytelling, bot, OCR): caso a caso — no corte, storytelling fica no
   backend via `body_md_override`.
5. Evolution: interface `WhatsAppDriver` abstraída; corte na **v2 atual**; **evolution-go** como
   driver pra números novos QUANDO a licença destravar (PTT via `/send/media` type audio e check
   via `/user/check` já confirmados na doc; detalhes na avaliação dentro do plano).
6. `external_id` gerado pelo cliente (SDK) — `send()` devolve handle na hora, retry com o mesmo
   UUID, nunca bloqueia o caller (§12).
7. Infra confirmada: LXC nova (padrão `backend-v7m`), Postgres geral CT 2100, VPN-only.

## ✅ Omnirouter — contrato CRAVADO (2026-07-17, sessão local)

Contrato confirmado via LAN (`10.1.30.35`):

- **Endpoint:** `POST http://10.1.30.35/v1/audio/speech` (OpenAI-compatible)
- **Body:** `{"model":"minimax/speech-2.8-hd","input":"texto","voice":"Portuguese_SereneWoman"}`
- **Response:** bytes do mp3 (200 OK, Content-Type: audio/mpeg)
- **Provider:** MiniMax via OmniRoute. ElevenLabs indisponível (pagamento pendente).
- **Vozes:** `Portuguese_SereneWoman` (feminina), `Portuguese_GentleTeacher` (masculina)
- **Regra cruzada:** homem recebe voz feminina, mulher recebe voz masculina (NÃO "corrigir")
- **MCP:** disponível em `http://10.1.30.35/api/mcp/stream` (omniroute v3.8.48)
- **Auth:** não necessária para TTS (MiniMax rota direta). ElevenLabs precisa resolver pagamento.

Client implementado em `tts/client.py` do notify-server.

## Pendências que destravam código (perguntar/verificar primeiro)
1. ~~**Contrato TTS do omnirouter**~~ ✅ CRAVADO (ver acima)
2. **Licença do evolution-go** (preço/termos; aceitamos heartbeat externo em prod?).
3. ~~**Nome do repo**~~ ✅ `notify-server` — https://github.com/maestri33/notify-server

## Ordem de trabalho sugerida (Fase 1 — detalhes no plano)
1. Cravar contrato do omnirouter (pendência 1).
2. Criar o repo novo + scaffold Django/Ninja/Django-Q + `.env` + checks de boot (padrão da casa).
3. Models: `Account` (+row `default`), `ApiKey`, `WhatsAppNumber` (driver field), `MailIdentity`,
   `TtsVoices`, `Template`+`Trigger` (por conta), `Notification` (por conta), `InboundEvent`.
4. Ports deste repo (copiar quase 1:1, mudando config `.env`→row):
   - `integrations/communication/whatsapp/client.py` → driver `evolution-v2` (atrás de `WhatsAppDriver`)
   - `integrations/communication/mail/` (client + templates HTML)
   - `notify/dispatch.py` (**o claim em 3 fases G16 porta INTEIRO** — parte mais valiosa/testada)
   - `notify/sanitize.py`, `notify/interface/templates.py` (cache TTL 30s), `notify/interface/events.py`
   - `notify/seed/` (vira o seed da conta supletivo)
5. API v1 (tabela no plano): `/v1/send`, `/v1/send-event`, `/v1/notifications`, `/v1/phone/check`,
   staff (templates CRUD/adhoc/preview/stats/seed), health, webhook Evolution (persiste inbound).
6. `TEST_MODE` dry-run + porte do management command `notify_send`.
7. Deploy LXC + database + adotar a instância atual do Supletivo + **validação REAL §8**
   (3 canais no aparelho do Victor, TTS via omnirouter, send-event por conta, phone/check).

Fase 2 (cutover do backend — SDK, seed dos templates, OTP FK→string, register→phone/check,
flag `NOTIFY_MODE`, descomissionamento) está passo a passo no plano. **Não iniciar a Fase 2 sem a
validação real da Fase 1 aprovada pelo Victor.**

## Fatos do monólito que a implementação NÃO pode esquecer
- `users/auth/service.py:98` — register usa `resolve_br_number`+`check_numbers` (vira `/v1/phone/check`).
- `users/auth/otp/service.py:165` — OTP guarda **FK** pra `Notification` (fase 2 troca por string).
- `api/staff_notify.py` — painel staff atual (histórico/CRUD/adhoc/preview/seed): é o contrato a
  reproduzir no serviço; o front do staff (VPN) passará a falar direto com o notify-server.
- `bot/` — NÃO tocar: quebrado, sai do backend depois; só não fechar a porta do relay inbound (fase 3).
- Mídia: WhatsApp busca por URL LAN (`_to_lan`), e-mail pela URL pública; áudio TTS será gerado e
  servido pelo PRÓPRIO serviço.
- Django-Q re-executa task em erro: por isso o claim G16 e a recuperação por TEXTO sem regenerar
  TTS (não duplicar custo de IA) — comportamento a preservar literalmente.
