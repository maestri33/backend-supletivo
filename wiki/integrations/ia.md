# integrations/ia — engine LLM multi-provider

> Engine de IA do monólito (§4 item 1 "ia"). **Multi-provider OpenAI-compatible com fallback.**
> Consumido **in-process** (sem FastAPI, sem HTTP interno) pelos apps do Django via `service.py`.
> Plano: `.claude/plan/1-ia-i-deepseek-core.md` · Testes: `.claude/tests/1-ia-i-deepseek-core.md`.

## O que é

Um único ponto que fala com IA. Todos os providers (DeepSeek, DashScope/Alibaba, Groq, OpenAI,
OpenRouter, NVIDIA, …) usam o **mesmo protocolo OpenAI-compatible** (`POST /chat/completions`), então
um provider é só `{base_url, api_key}` no `.env` — **somar um novo não exige código**.

## Peças

- **`client.py` → `LLMClient`** — client fino sobre um provider (httpx async). Métodos: `text`, `json`,
  `chat`, `summarize`, `extract`, `list_models`. Erro tipado **`LLMError(retryable=...)`**: rede/
  timeout/429/5xx = retryable; 4xx de input = não. Zero regra de negócio (CONVENTION §8).
- **`providers.py`** — registry montado do `.env` (`get_client`, `enabled_providers`) + a **cadeia de
  fallback** (`fallback_chain`).
- **`service.py`** — a **interface in-process** (única superfície pública, CONVENTION §3). Funções
  **síncronas** (`async_to_sync`, casa com workers django-q): `generate_text/json/chat/summarize/
  extract` + **`grade`** (correção do training: nota 0–10 + justificativa, ≥6 aprovado). Caminha a
  cadeia de fallback e **grava 1 `AiCall` por tentativa**.
- **`models.py` → `AiCall`** — auditoria/custo de cada chamada (provider, model, tokens, latência,
  status). `cost` fica `null` até a tabela de preços ser definida (CONVENTION §8 — não inventa $$).
  Tabela `ia_aicall`.
- **`checks.py`** — `ia.E001/E002/E003` travam o boot se não houver provider/cadeia (padrão asaas).
- **`management/commands/`** — `ia_providers` (valida cada key real via `/models`) e `ia_ping`
  (exercita a cadeia).

## Config (`.env`)

```
IA_PROVIDERS=deepseek,dashscope,groq,openai,openrouter,nvidia
IA_FALLBACK_CHAIN=deepseek:deepseek-v4-pro,dashscope:qwen3.7-max,groq:llama-3.3-70b-versatile,...
IA_<NAME>_BASE_URL=...      # por provider
IA_<NAME>_API_KEY=...       # por provider (gitignored)
IA_DEFAULT_TEMPERATURE / IA_MAX_TOKENS / IA_TIMEOUT
```

`IA_FALLBACK_CHAIN` é a **ordem de tentativa** `provider:model` (1º = default). Falha retryável num
provider → cai pro próximo da cadeia.

## Como um app consome (in-process)

```python
from integrations.ia import service

data = service.generate_json("...", schema_description="...", caller="training")
nota = service.grade(question=..., expected_answer=..., student_answer=..., caller="training")
```

## Validado (real, §8)

As 6 keys validadas via `/models`; geração real em DeepSeek e DashScope (JSON mode); fallback real
(provider morto → próximo) com as 2 linhas `AiCall` gravadas. Prints em `.claude/tests/1-ia-i-...`.

## Próximas etapas (mesmo padrão)

ii Gemini (visão/imagem) · iii ElevenLabs (TTS) · iv Google Vision (OCR) — modalidades diferentes,
mesma casa `integrations/ia/`.
