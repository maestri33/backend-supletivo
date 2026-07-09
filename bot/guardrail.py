"""Guardrail do bot — injeção de prompt (entrada) e vazamento de PII (saída). FAIL-CLOSED.

CONTEXTO ARQUITETURAL (honestidade, Victor revisar): o plano pedia `aidefence` via MCP do ruflo.
As ferramentas MCP rodam no runtime do AGENTE (sessão de IA), NÃO no processo Django de produção —
o backend não pode depender de uma chamada MCP que só existe na sessão. Então o guardrail é:

  1. um DETECTOR LOCAL heurístico (sempre ligado) — injeção + PII por regex/padrões pt-br/en. É o
     PISO de segurança que nunca depende de rede externa.
  2. um GANCHO EXTERNO opcional (`settings.BOT_GUARDRAIL_URL`) — se o Victor subir um serviço HTTP
     de aidefence real, plugamos aqui. Contrato FAIL-CLOSED: serviço configurado mas inalcançável
     ou resposta inválida => BLOQUEIA (não passa cru). Sem serviço configurado => decide o detector
     local.

`scan_inbound` roda ANTES de qualquer chamada de IA (defesa contra injeção). `has_pii` roda na
SAÍDA antes de mandar pro usuário (não vaza dado sensível que o LLM possa ter regurgitado).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


@dataclass(frozen=True)
class ScanResult:
    """Resultado de um scan: `safe` (passa?) + `reason` (por que bloqueou, pra log/escalonar)."""

    safe: bool
    reason: str = ""


# ── injeção de prompt: padrões pt-br + en (entrada do usuário) ──────────────
# Não é antivírus — é o piso que pega o óbvio. O system prompt e a separação de dados (o LLM
# NUNCA recebe função de escrita) são a defesa real; isto é cinto + suspensório.
_INJECTION_PATTERNS = [
    r"ignor(e|ar|e as|e todas)\s+(as\s+)?(instru|ordens|regras|mensagens|coment)",
    r"ignore\s+(all\s+)?(previous|prior|above|the)\s+(instruction|prompt|message|rule)",
    r"esque(ç|c)a\s+(tudo|as instru|o que)",
    r"forget\s+(everything|all|previous|your)\s",
    r"voc(ê|e)\s+(agora|passa a)\s+(é|e|ser)\b",
    r"you\s+are\s+now\s+(a|an|the)\b",
    r"(novo|new)\s+(system\s+prompt|prompt do sistema|conjunto de regras)",
    r"(revele|mostre|me diga|imprima|repita)\s+(seu|o)\s+(prompt|system|sistema|instru)",
    r"(reveal|show|print|repeat|tell me)\s+(your|the)\s+(system\s+prompt|prompt|instruction)",
    r"\bdeveloper\s+mode\b",
    r"\bmodo\s+desenvolvedor\b",
    r"\bDAN\b",
    r"\bjailbreak\b",
    r"act\s+as\s+(if\s+you|a|an)\b",
    r"finja\s+(que|ser)\b",
    r"disregard\s+(all\s+)?(previous|prior|the)\b",
    r"override\s+(your|the|all)\b",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


# ── PII: padrões da SAÍDA (não vazar dado sensível regurgitado pelo LLM) ─────
# CPF: 11 dígitos (com ou sem máscara). Cartão: 13–16 dígitos agrupados. E-mail. Chave longa
# tipo token. NÃO bloqueamos telefone solto (o usuário já mandou o dele; o bot pode confirmar o
# canal) — foco em CPF/cartão/e-mail/segredo, que o bot NUNCA deve emitir.
_PII_PATTERNS = {
    "cpf": r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
    "cnpj": r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b",
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "card": r"\b(?:\d[ -]?){13,16}\b",
    "secret_token": r"\b(?:sk|pk|aact|api[_-]?key|bearer)[\w$.\-]{12,}\b",
}
_PII_RE = {name: re.compile(pat, re.IGNORECASE) for name, pat in _PII_PATTERNS.items()}


def _external_scan(text: str, *, mode: str) -> ScanResult | None:
    """Chama o serviço externo de guardrail (se configurado). FAIL-CLOSED.

    Retorna:
      - ScanResult(safe=...) com a decisão do serviço, OU
      - ScanResult(safe=False, ...) se o serviço está configurado mas falhou (fail-closed), OU
      - None se NÃO há serviço configurado (cabe ao detector local decidir).

    Contrato esperado do serviço: POST {text, mode} -> {"safe": bool, "reason": str}.
    """
    url = getattr(settings, "BOT_GUARDRAIL_URL", "")
    if not url:
        return None
    try:
        resp = httpx.post(
            url,
            json={"text": text, "mode": mode},
            timeout=getattr(settings, "BOT_GUARDRAIL_TIMEOUT", 5.0),
        )
        if resp.status_code >= 400:
            logger.warning(
                "bot.guardrail.external_http_error", status=resp.status_code, mode=mode
            )
            return ScanResult(False, f"guardrail_http_{resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict) or "safe" not in data:
            logger.warning("bot.guardrail.external_bad_contract", mode=mode)
            return ScanResult(False, "guardrail_bad_contract")
        return ScanResult(bool(data["safe"]), str(data.get("reason", "")))
    except Exception as exc:  # noqa: BLE001 — serviço configurado mas caiu => fail-closed
        logger.warning("bot.guardrail.external_failed", mode=mode, error=str(exc)[:160])
        return ScanResult(False, "guardrail_unreachable")


def scan_inbound(text: str) -> ScanResult:
    """Escaneia a ENTRADA do usuário por injeção de prompt. FAIL-CLOSED.

    Ordem: serviço externo (se houver) tem a palavra final; senão o detector local. Entrada vazia
    é tratada como insegura (não há o que processar; força escalonamento em vez de chamar a IA com
    nada).
    """
    text = (text or "").strip()
    if not text:
        return ScanResult(False, "empty_input")

    external = _external_scan(text, mode="inbound")
    if external is not None:
        if not external.safe:
            logger.info(
                "bot.guardrail.blocked", layer="external", reason=external.reason
            )
        return external

    if _INJECTION_RE.search(text):
        logger.info("bot.guardrail.blocked", layer="local", reason="prompt_injection")
        return ScanResult(False, "prompt_injection")
    return ScanResult(True)


def has_pii(text: str) -> bool:
    """True se a SAÍDA contém PII que o bot NUNCA deve emitir (CPF/CNPJ/cartão/e-mail/segredo).

    Roda no texto que o bot vai mandar. Se houver serviço externo, ele decide (fail-closed: caiu =>
    trata como TENDO pii, pra não vazar). Senão, o detector local por regex.
    """
    text = (text or "").strip()
    if not text:
        return False

    url = getattr(settings, "BOT_GUARDRAIL_URL", "")
    if url:
        # mode=outbound: o serviço externo devolve safe=False quando há PII a vazar.
        external = _external_scan(text, mode="outbound")
        if external is not None:
            return not external.safe

    for name, rx in _PII_RE.items():
        if rx.search(text):
            logger.info("bot.guardrail.pii_detected", layer="local", kind=name)
            return True
    return False
