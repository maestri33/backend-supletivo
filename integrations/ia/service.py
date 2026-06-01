"""Interface in-process do app `ia` — a única superfície pública (CONVENTION §3).

Os outros apps do monólito chamam ESTAS funções (nunca o client direto). Cada função:
 1. caminha a **cadeia de fallback** `(provider, model)` (providers.fallback_chain) — em falha
    retryável (rede/timeout/429/5xx) cai pro próximo; em erro de input/contrato (4xx) para e erra;
 2. embrulha o client async em `async_to_sync` (Portão 2: interface SÍNCRONA, casa com django-q);
 3. **grava 1 `AiCall` por tentativa** (provider+model+status+tokens+latência) — auditoria/custo;
 4. devolve o resultado já no formato útil (str/dict/Grading).

`grade()` mora aqui por decisão do Victor (correção do training: nota 0–10 + justificativa, ≥6 ok).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import structlog
from asgiref.sync import async_to_sync

from . import providers
from .client import ChatResult, LLMError
from .models import AiCall

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Contrato de correção do training (porte do legado training/integrations/ai.py).
# Invariante de negócio: "toda nota gravada tem justificativa".
# ---------------------------------------------------------------------------
_GRADE_SCHEMA = (
    "Objeto JSON com exatamente dois campos: `nota` (numero inteiro de 0 a 10) e "
    "`justificativa` (string em portugues explicando a nota com base no que o trainee "
    "escreveu vs o gabarito)."
)
_GRADE_INSTRUCTION = (
    "Voce e corretor de uma plataforma de treinamento. Compare a resposta do trainee com o "
    "gabarito da materia e atribua uma nota inteira de 0 a 10. 6 ou mais significa aprovado; "
    "menor que 6 significa reprovado. Seja justo, exigente com o conteudo mas tolerante com a "
    "forma. Responda APENAS o JSON pedido — sem texto fora dele."
)


@dataclass(frozen=True)
class Grading:
    """Resultado de uma correção: nota 0–10 + justificativa pt-br (≥6 = aprovado)."""

    grade: float
    justification: str


def _record(
    *,
    operation: str,
    provider: str,
    model: str,
    caller: str,
    result: ChatResult | None,
    error: Exception | None,
    started_at: float,
) -> None:
    """Grava uma linha AiCall com as métricas de UMA tentativa (cost null — CONVENTION §8)."""
    AiCall.objects.create(
        provider=provider,
        operation=operation,
        model=model,
        caller=caller,
        status=AiCall.Status.ERROR if error is not None else AiCall.Status.SUCCESS,
        prompt_tokens=getattr(result, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(result, "completion_tokens", 0) or 0,
        cache_hit_tokens=getattr(result, "cache_hit_tokens", 0) or 0,
        cache_miss_tokens=getattr(result, "cache_miss_tokens", 0) or 0,
        cost=None,
        latency_ms=int((time.monotonic() - started_at) * 1000),
        finish_reason=getattr(result, "finish_reason", None),
        error=str(error)[:1000] if error is not None else None,
    )


def _run(operation: str, caller: str, attempt, chain) -> tuple[ChatResult, str, str]:
    """Caminha a cadeia: tenta cada (provider, model), grava AiCall por tentativa, para na 1ª que dá
    certo. `attempt` é uma corrotina `attempt(client, model) -> ChatResult`. Falha retryável => próximo;
    não-retryável (4xx/inesperada) => levanta na hora. Cadeia esgotada => levanta a última falha."""
    last_err: Exception | None = None
    for provider, model in chain:
        client = providers.get_client(provider)
        started = time.monotonic()
        try:
            result: ChatResult = async_to_sync(attempt)(client, model)
        except LLMError as exc:
            _record(
                operation=operation,
                provider=provider,
                model=model,
                caller=caller,
                result=None,
                error=exc,
                started_at=started,
            )
            last_err = exc
            if exc.retryable:
                logger.warning(
                    "ia.fallback_next",
                    provider=provider,
                    model=model,
                    reason=str(exc)[:160],
                )
                continue
            raise
        except Exception as exc:
            _record(
                operation=operation,
                provider=provider,
                model=model,
                caller=caller,
                result=None,
                error=exc,
                started_at=started,
            )
            raise
        _record(
            operation=operation,
            provider=provider,
            model=model,
            caller=caller,
            result=result,
            error=None,
            started_at=started,
        )
        return result, provider, model
    raise last_err or LLMError("IA_FALLBACK_CHAIN vazia", retryable=False)


# ---------------------------------------------------------------------------
# Capacidades genéricas do engine
# ---------------------------------------------------------------------------


def generate_text(
    prompt: str,
    *,
    caller: str,
    instruction: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """Gera texto natural. Devolve a string já limpa."""

    async def attempt(client, m):
        return await client.text(
            prompt,
            model=m,
            instruction=instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    result, _p, _m = _run(
        AiCall.Operation.TEXT, caller, attempt, providers.fallback_chain(model)
    )
    return result.content.strip().strip('"')


def generate_json(
    prompt: str,
    *,
    caller: str,
    instruction: str | None = None,
    schema_description: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> dict:
    """Gera JSON estruturado. Devolve o dict já parseado (erra não-retryável se fugir do contrato)."""

    async def attempt(client, m):
        return await client.json(
            prompt,
            model=m,
            instruction=instruction,
            schema_description=schema_description,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    result, _p, _m = _run(
        AiCall.Operation.JSON, caller, attempt, providers.fallback_chain(model)
    )
    try:
        return json.loads(result.content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"resposta não é JSON válido: {exc}", retryable=False) from exc


def chat(
    messages: list[dict],
    *,
    caller: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    """Chat multi-turn. Devolve o conteúdo da resposta do assistente."""

    async def attempt(client, m):
        return await client.chat(
            messages,
            model=m,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    result, _p, _m = _run(
        AiCall.Operation.CHAT, caller, attempt, providers.fallback_chain(model)
    )
    return result.content


def summarize(
    text: str,
    *,
    caller: str,
    format: str = "paragraph",
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """Resume um texto (paragraph / bullets / headline). Devolve o resumo."""

    async def attempt(client, m):
        return await client.summarize(
            text, model=m, format=format, temperature=temperature, max_tokens=max_tokens
        )

    result, _p, _m = _run(
        AiCall.Operation.SUMMARIZE, caller, attempt, providers.fallback_chain(model)
    )
    return result.content.strip()


def extract(
    text: str,
    *,
    json_schema: dict,
    caller: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> dict:
    """Extrai dados estruturados do texto conforme um JSON Schema. Devolve o dict parseado."""

    async def attempt(client, m):
        return await client.extract(
            text,
            model=m,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    result, _p, _m = _run(
        AiCall.Operation.EXTRACT, caller, attempt, providers.fallback_chain(model)
    )
    try:
        return json.loads(result.content)
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"resposta não é JSON válido na extração: {exc}", retryable=False
        ) from exc


# ---------------------------------------------------------------------------
# Correção do training (grade() dentro da IA — decisão do Victor)
# ---------------------------------------------------------------------------


def grade(
    *,
    question: str,
    expected_answer: str,
    student_answer: str,
    caller: str,
    model: str | None = None,
) -> Grading:
    """Corrige a resposta de um trainee contra o gabarito: nota 0–10 + justificativa (≥6 = aprovado).

    Porte do contrato do legado. Nota grampeada em [0, 10]; sem justificativa => erra (não-retryável).
    """
    prompt = (
        f"ENUNCIADO DA MATERIA:\n{question.strip()}\n\n"
        f"GABARITO (resposta esperada):\n{expected_answer.strip()}\n\n"
        f"RESPOSTA DO TRAINEE:\n{student_answer.strip()}"
    )

    async def attempt(client, m):
        return await client.json(
            prompt,
            model=m,
            instruction=_GRADE_INSTRUCTION,
            schema_description=_GRADE_SCHEMA,
            temperature=0.2,
        )

    result, _p, _m = _run(
        AiCall.Operation.GRADE, caller, attempt, providers.fallback_chain(model)
    )
    try:
        data = json.loads(result.content)
        grade_value = max(0.0, min(10.0, float(data["nota"])))
        justification = str(data["justificativa"]).strip()
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise LLMError(
            f"resposta fora do contrato de correção: {exc}", retryable=False
        ) from exc
    if not justification:
        raise LLMError("IA devolveu nota sem justificativa", retryable=False)
    return Grading(grade=grade_value, justification=justification)
