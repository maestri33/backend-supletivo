"""System check do app ia — avisa no boot quando a config de IA está incompleta.

Roda em todo runserver/manage (framework de checks do Django), então fica "printando" vermelho até o
.env ser preenchido. Padrão pedido pelo Victor (igual asaas, CONVENTION §8): integração não sobe
silenciosa sem credencial real.

- `ia.E001` (Error): nenhum provider habilitado com base_url+api_key → o engine não fala com IA.
- `ia.E002` (Error): IA_FALLBACK_CHAIN vazia → não há o que chamar.
- `ia.E003` (Error): a cadeia referencia provider sem credencial no .env.
Qualquer um TRAVA o manage.py (padrão asaas: integração não sobe sem credencial real).
"""

from django.conf import settings
from django.core.checks import Error


def check_ia_config(app_configs, **kwargs):
    errors = []
    providers = getattr(settings, "IA_PROVIDERS", {})
    chain = getattr(settings, "IA_FALLBACK_CHAIN", [])

    if not providers:
        errors.append(
            Error(
                "Nenhum provider de IA configurado — o app ia não consegue falar com nenhuma IA.",
                hint="No .env: IA_PROVIDERS=deepseek,... e, p/ cada um, IA_<NAME>_BASE_URL + "
                "IA_<NAME>_API_KEY.",
                id="ia.E001",
            )
        )
    if not chain:
        errors.append(
            Error(
                "IA_FALLBACK_CHAIN vazia — sem cadeia (provider:model) não há o que chamar.",
                hint="No .env: IA_FALLBACK_CHAIN=deepseek:deepseek-v4-pro,dashscope:qwen3.7-max,...",
                id="ia.E002",
            )
        )
    missing = sorted({p for (p, _m) in chain if p not in providers})
    if missing:
        errors.append(
            Error(
                f"IA_FALLBACK_CHAIN referencia provider(s) sem base_url/api_key no .env: {missing}.",
                hint="Adicione IA_<NAME>_BASE_URL + IA_<NAME>_API_KEY ou tire da cadeia.",
                id="ia.E003",
            )
        )
    return errors
