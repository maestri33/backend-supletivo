# backend — monólito Django (MVP)

O **cérebro** da plataforma: toda a lógica de negócio + o banco moram aqui. À frente ficam
edges FastAPI finos (fora deste repo) que chamam as views DMZ por HTTP. Arquitetura completa
nas instruções do projeto (`.claude/CONVENTION.md`).

## Rodar em dev

```bash
cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Config em `backend/.env` (não versionado). Dev usa SQLite.

## Estado

- **Bootstrap (step 0):** Django sobe, migra, `/admin/` no ar. → [[wiki/core/bootstrap]]
- **integrations/asaas (§4 item 1-a):** gateway de pagamento — fundação + status/onboarding +
  webhook receiver + validação de saque. Faltam charge e payout. → [[wiki/integrations/finance/asaas]]
- **integrations/infinitepay (§4 item 1-b):** gateway de checkout — link de pagamento + webhook que
  reconfirma via payment_check. E2E real aprovado (pagou R$1 → PAID). → [[wiki/integrations/finance/infinitepay]]
- **core/fallback:** logger rastreável de evento sem destino (usado pelo webhook do asaas).
  → [[wiki/core/fallback]]
- **core/validation:** registro de validações (flags + horário) dos testes que rodamos, mostrado no
  `/status/` de cada integração. → [[wiki/core/validation]]
- **integrations/tools/cep (§4 item 1):** tool de CEP — lookup ViaCEP (API pública, sem api-key).
  Cliente async; o app `address` consome depois. → [[wiki/integrations/tools/cep]]
- **integrations/tools/cpf (§4 item 1):** tool de CPF — lookup CPFHub.io (api-key `x-api-key`,
  server-side). Cliente async; o app `profiles` consome depois. → [[wiki/integrations/tools/cpf]]
- **integrations/comunicacao/whatsapp (§4 item 1):** cliente WhatsApp (Evolution API 2.3.7) — porte
  completo, async, com resolução do 9º dígito BR. O app `notify` consome depois.
  → [[wiki/integrations/comunicacao/whatsapp]]
- **integrations/ia (§4 item 1):** engine LLM multi-provider OpenAI-compatible + fallback (DeepSeek,
  DashScope, Groq, OpenAI, OpenRouter, NVIDIA). Interface in-process (`service.py`) + auditoria
  `AiCall`; somar provider é só `.env`. O `training` consome depois (correção). → [[wiki/integrations/ia]]
- **integrations/comunicacao/mail (§4 item 1):** cliente de email (SMTP STARTTLS:587) + validador
  (formato/MX) + templates HTML. Porte do legado, async; envia inclusive imagem por URL. O `notify`
  consome depois. → [[wiki/integrations/comunicacao/mail]]

> Apps de negócio (`users`, `hub`, `notify`, `financeiro`, `integrations`...) entram um a um,
> pelo `.claude/WORKFLOW.md`.
