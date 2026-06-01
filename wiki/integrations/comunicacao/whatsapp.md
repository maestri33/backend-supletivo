# whatsapp — integrations/comunicacao/whatsapp (Evolution API)

> **ESTADO:** cliente WhatsApp (Evolution API 2.3.7) — **porte completo** do micro legado, feito e
> **testado com chamadas REAIS** (health + envio pro número do Victor, 2026-06-01). §4-item-1,
> subgrupo **comunicação**. Label do app: `whatsapp`. É **só o cliente** — quem orquestra
> template/contato/log/inbound é o app `notify` (§4-item-2, ainda não existe).

App Django que porta o `WhatsAppClient` da Evolution do micro legado (`~/coders/backend/notify`,
FastAPI) pro monólito. **Evolution é gateway self-hosted; auth = header `apikey`.** Sem models/
migração/endpoint (cliente stateless; cache do 9º dígito é em memória). Consumo in-process pelo `notify`.

## Config (.env, CONVENTION §8/§10)

| Chave | Exemplo | O que é |
|---|---|---|
| `WHATSAPP_API_BASE_URL` | `http://10.1.20.200` | URL da Evolution (interna/tailnet) |
| `WHATSAPP_GLOBAL_API_KEY` | `ePha...` | api-key global (header `apikey`) |
| `WHATSAPP_INSTANCE_NAME` | `default` | instância default (também existe `ieadpg`) |

Sem base_url/api-key → checks `whatsapp.E001`/`whatsapp.E002` **travam** o boot (padrão asaas).

## Cliente (`client.py`)

`WhatsAppClient` (httpx puro, `AsyncClient` próprio com `base_url`+header `apikey`; erro não-2xx →
`WhatsAppError`). `get_client(instance=None)` constrói com a config do `.env`. Métodos (porte 1:1):

- **leitura/perfil:** `health`, `check_numbers`, `get_jid`, `fetch_profile`, `fetch_business_profile`
- **envio:** `send_text`, `send_media`, `send_whatsapp_audio`, `send_sticker`, `send_location`,
  `send_contact`, `send_poll`, `send_buttons`, `send_reaction`, `send_status`
- **chamada:** `reject_call`
- **🔑 `resolve_br_number(phone)`** — resolve a variante BR com/sem o **9º dígito** (cache em memória,
  TTL 1h). A Evolution às vezes responde 201 sem entregar quando o número só existe na outra variante;
  pré-resolver evita esse silent-fail. **Provado real:** input `5543996648750` → entregou em
  `554396648750@s.whatsapp.net`.

## Como validar (§8 — chamada real)

```bash
python manage.py whatsapp_health                          # lista instâncias (auth + conectividade)
python manage.py whatsapp_send 5543996648750 "texto"      # envio real (resolve 9º dígito antes)
python manage.py whatsapp_send 5543996648750 "txt" --instance ieadpg
```

Evidência: `.claude/tests/1-comunicacao-whatsapp.md`.

## Rabo pra trás

- App `notify` (§4-item-2): templates, contatos, logs, orquestração async e **webhook inbound** de
  WhatsApp (mensagens/chamadas recebidas).
- Cliente de **mail** (`integrations/comunicacao/mail`) — o outro do subgrupo comunicação.
