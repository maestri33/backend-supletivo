# integrations/ai — engine LLM multi-provider

> Engine de IA do monólito (§4 item 1 "ai"). **Multi-provider OpenAI-compatible com fallback.**
> Consumido **in-process** (sem HTTP interno) pelos apps do Django via `service.py`.
> Plano: `.claude/plan/1-ia-i-deepseek-core.md` · Testes: `.claude/tests/1-ia-i-deepseek-core.md`.

## O que é

Um único ponto que fala com IA. Os providers (hoje **MiniMax**, **DeepSeek** e **Gemini** — Victor
2026-06-05; os demais ficaram dormentes) usam o **mesmo protocolo OpenAI-compatible**
(`POST /chat/completions`), então um provider é só `{base_url, api_key}` no `.env` — **somar um novo
não exige código**. (Gemini é injetado pelo `settings.py` reusando a `GEMINI_API_KEY`, via o endpoint
OpenAI-compatible do Google.) Respostas com bloco de raciocínio `<think>...</think>` (ex.: MiniMax-M3)
são limpas pelo `service` antes de usar/parsear.

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
- **`checks.py`** — `ai.E001/E002/E003` travam o boot se não houver provider/cadeia (padrão asaas).
- **`management/commands/`** — `ai_providers` (valida cada key real via `/models`) e `ai_ping`
  (exercita a cadeia).

## Config (`.env`)

```
IA_PROVIDERS=deepseek,minimax        # gemini é injetado pelo settings (reusa GEMINI_API_KEY)
IA_FALLBACK_CHAIN=minimax:MiniMax-M3,deepseek:deepseek-v4-pro,gemini:gemini-3-flash-preview
IA_<NAME>_BASE_URL=...      # por provider
IA_<NAME>_API_KEY=...       # por provider (gitignored)
IA_DEFAULT_TEMPERATURE / IA_MAX_TOKENS / IA_TIMEOUT
```

`IA_FALLBACK_CHAIN` é a **ordem de tentativa** `provider:model` (1º = default). Falha retryável num
provider → cai pro próximo da cadeia.

## Como um app consome (in-process)

```python
from integrations.ai import service

data = service.generate_json("...", schema_description="...", caller="training")
nota = service.grade(question=..., expected_answer=..., student_answer=..., caller="training")
```

## Validado (real, §8)

As 6 keys validadas via `/models`; geração real em DeepSeek e DashScope (JSON mode); fallback real
(provider morto → próximo) com as 2 linhas `AiCall` gravadas. Prints em `.claude/tests/1-ia-i-...`.

## Mídia (single-provider, SEM cadeia de fallback)

Além do chat LLM, o engine tem 4 modalidades de mídia (clients httpx REST próprios, 1 provider cada).
Cada uma grava `AiCall` (provider/operation, tokens=0). Imagem/áudio gerados vão pro `media/ai/`.

| função (`service.py`) | provider | client |
|---|---|---|
| `describe_image(bytes, caller=...)` → texto | **MiniMax-M3** (visão) → Gemini (fallback) | `minimax.py` / `gemini.py` |
| `generate_image(prompt, caller=...)` → caminho media | Gemini (imagem) | `gemini.py` |
| `tts(text, caller=...)` → caminho media (mp3) | **MiniMax** (t2a_v2) → ElevenLabs (fallback) | `minimax.py` / `elevenlabs.py` |
| `ocr(bytes, caller=..., document=False)` → texto | Google Vision | `vision_ocr.py` |

> **TTS e visão têm fallback** (MiniMax primário; ElevenLabs/Gemini cobrem queda). O TTS escolhe a voz
> **cruzada** por gênero (homem→voz feminina `Portuguese_SereneWoman`, mulher→voz masculina
> `Portuguese_GentleTeacher`). O MiniMax-M3 roda com `thinking` desligado (sem `<think>`).
> **OCR fica só no Google Vision** (não entrou no MiniMax).

Config no `.env`: `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `GOOGLE_VISION_API_KEY` (+ defaults de
modelo/voz no settings). São **opcionais**: sem a key, o check só **avisa** (`ai.W001/W002/W003`),
não trava (≠ a cadeia LLM, que é o núcleo e trava). **Validado real (§8):** OCR + visão leram texto de
uma imagem; TTS gerou áudio; Gemini gerou imagem. Consumidores: `student`/`documents` (selfie/RG/recibo,
visão), `notify` (áudio), `training` (correção, LLM).
