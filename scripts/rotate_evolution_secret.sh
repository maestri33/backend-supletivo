#!/usr/bin/env bash
# A6.3 — Rotação de segredos da Evolution (WhatsApp).
#
# Gera DOIS segredos fortes (32 bytes, base64url sem padding) e imprime:
#   1. WHATSAPP_GLOBAL_API_KEY   — api-key global da Evolution (lado OUTBOUND: o backend usa pra
#      falar COM a Evolution). Precisa bater com a chave configurada no painel da Evolution.
#   2. WHATSAPP_WEBHOOK_SECRET   — token do webhook inbound (lado INBOUND: a Evolution manda no
#      header `x-webhook-token` a cada mensagem; o backend compara em tempo constante). A6.3 tornou
#      esse OBRIGATÓRIO (bot.E001 trava o boot se faltar).
#
# O script SÓ GERA + ORIENTA. Ele NÃO toca no .env (segredos só entram por mão do owner) e NÃO
# acessa o painel da Evolution. A rotação é coordenada: o novo valor precisa ir PRIMEIRO pro painel
# da Evolution, DEPOIS no .env, e então reinicia o backend — senão há uma janela de 401.
#
# Uso:
#   ./scripts/rotate_evolution_secret.sh            # gera ambos
#   ./scripts/rotate_evolution_secret.sh --api-only # só WHATSAPP_GLOBAL_API_KEY
#   ./scripts/rotate_evolution_secret.sh --webhook-only
set -euo pipefail

gen_token() { printf '%s' "$(openssl rand -base64 32 | tr -d '=+/' | cut -c1-40)"; }

mode="${1:-all}"
api=""; webhook=""
case "$mode" in
  --api-only)      api="$(gen_token)" ;;
  --webhook-only)  webhook="$(gen_token)" ;;
  all|"")          api="$(gen_token)"; webhook="$(gen_token)" ;;
  *) echo "uso: $0 [--api-only|--webhook-only]" >&2; exit 64 ;;
esac

echo "═══════════════════════════════════════════════════════════════════════════"
echo " A6.3 — Rotação de segredos da Evolution (NÃO é automático; runbook abaixo)"
echo "═══════════════════════════════════════════════════════════════════════════"
echo
if [[ -n "$api" ]]; then
  echo "▸ WHATSAPP_GLOBAL_API_KEY (OUTBOUND — backend → Evolution)"
  echo "  valor gerado: $api"
  echo
  echo "  1. Painel da Evolution → Settings/API Key (ou Instance > API Key): cole o novo valor."
  echo "  2. backend/.env: WHATSAPP_GLOBAL_API_KEY=$api"
  echo
fi
if [[ -n "$webhook" ]]; then
  echo "▸ WHATSAPP_WEBHOOK_SECRET (INBOUND — Evolution → webhook /bot/webhook/)"
  echo "  valor gerado: $webhook"
  echo
  echo "  1. Painel da Evolution → Webhook > Headers: x-webhook-token: $webhook"
  echo "  2. backend/.env: WHATSAPP_WEBHOOK_SECRET=$webhook"
  echo "     (obrigatório desde A6.3 — sem ele o manage.py trava com bot.E001)"
  echo
fi
echo "▸ Após atualizar painel + .env, reinicie o backend e valide:"
echo "    python manage.py check        # deve ficar 0 errors (bot.E001 some)"
echo "    python manage.py bot_test_webhook --live   # se existir; senão dispare 1 msg de teste"
echo
echo "  Ordem importa: novo valor PRIMEIRO no painel, DEPOIS no .env, então restart."
echo "═══════════════════════════════════════════════════════════════════════════"
