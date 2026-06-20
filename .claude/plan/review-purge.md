# Review-purge — status e follow-up (backend)

> **Para que serve:** registro do que a auditoria `review-purge` achou, o que foi
> corrigido (PR #3) e o que ficou **adiado de propósito** (refactors grandes/sensíveis).
> Abrir sessão nova pra terminar = usar este doc. Lentes em `.cursor/skills/review-purge/`.

## Diagnóstico inicial

6 lentes (DUP, NOZ, LOG, MEN, DUA, ENG) no backend inteiro → **6🔴 · 21🟡 · 27🔵**,
concentrados em 3 eixos: **funis `candidate↔enrollment` espelhados que driftaram**,
**PSPs `asaas↔infinitepay` sem abstração**, **parsers de IA com vocabulário divergente**.

## ✅ Feito (PR #3, ~16 commits, CI verde)

**Os 6 🔴:**
1. `candidate/service.py` `_apply_doc_extracted` — lia `sub.date_of_birth` (campo só CNH) em RG → `AttributeError`. **Removido.**
2. `candidate/service.py` `_selfie_ack` — cravava `PENDING`, ignorava flip TTL→review. **Delega a `_analysis.ack`.**
3. **Liveness teatral** (`integrations/tools/biometric/liveness.py`) — `passed:True` sempre, ninguém lê. **Deletado** (seam + coluna `FaceVerification.liveness` + setting `BIOMETRIC_LIVENESS_PROVIDER` + migration 0002). Decisão do Victor.
4. `wiki/api/clients.md` — `POST /enrollment/profile` (rota inexistente) → **wiki alinhada ao router real.**
5. `wiki/api/clients.md` — status `started` (morto) → **máquina corrigida** (`rg→address→education→selfie→awaiting_release→completed`).
6. **InfinitePay "estados terminais"** — ⚠️ **PREMISSA FALSA** (ver abaixo). **Documentado**, sem código.

**🟡/🔵 feitos:** 2 mentiras de dinheiro (`credit_commission` sig, `transfer_validation` "recusa tudo");
4 codes faltando no `collaborators` (`DOC_TYPE_NOT_SET/LOCKED`, `SLOT_INVALID`, `DOC_NOT_IN_REVIEW`);
doc-TTL notifica coord (igual selfie); `_fee_dict` usa enum; `CheckIn/LoginIn`→`api/schemas.py`;
`_apply_viacep`/`_pricing` extraídos; `address.get_by_id` morto removido; settings mortos
(`GOOGLE_VISION_SERVICE_ACCOUNT_JSON`, `LANDING_BASE_URL`); `find_any_rule` órfã; `profiles.__all__`;
docstrings entrevista/Trainee; scaffold do `core/urls`; FastAPI exterminado (11 menções); `/whoami` name.

## ⏳ ADIADO — refactors grandes/sensíveis (o follow-up)

Tocam selfie/doc/IA/auth — fazer com cuidado, cada um verificado (`manage.py check` +
`makemigrations --check --skip-checks` + `ruff`), em commit pequeno.

| # | Achado | Local | Abordagem |
|---|---|---|---|
| 🟡 | `run_selfie_validation` espelhado | `candidate/service.py:1136-1195` ↔ `enrollment/service.py:1050-1106` (+ `_save_selfie`/`_resolve_selfie`/`decide_selfie`) | extrair `_selfie.run_validation(obj, *, caller, on_resolve)` parametrizado por model/caller |
| 🟡 | parser de veredito IA divergente | `_selfie.verify` (`VALIDA/INVALIDA`, `startswith`, `[:16]`) vs `_document_ai.check_photo:156` (`APROVADO/REPROVADO`, `in`, `[:24]`) | `parse_verdict(desc, *, positive, negative, match, head_len)` único; cuidado: 3 funções compliance-sensíveis |
| 🟡 | `student` re-implementa parser de doc | `student/service.py:303-309` ↔ `_document_ai.check_photo` | student chama o helper compartilhado (prompts diferem — extrair SÓ o parser) |
| 🟡 | `login` double-query | `api/clients.py:275-286` + `api/collaborators.py:184-195` re-resolvem User+`active_roles` que `auth/service.py:312-326` re-resolve | não pré-resolver role no router; corrigir o contrato de `auth.login` |
| 🔵 | `name_match` schema vs parser | `_document_ai.py:76,91` promete `sim\|nao\|duvida`, parser nunca casa `duvida` | alinhar tokens schema↔parser |
| 🔵 | material handlers dup | `api/staff.py:157-180` ↔ `api/leadership.py:488-505` | extrair helper em `training_iface` |
| 🔵 | `decide_document` 3× | candidate/enrollment/student services | decisor compartilhado parametrizado por funil |
| 🔵 | `AiCall.cost` teatral | sempre `None`, exposto em `staff.py:356` | remover campo (+migration) ou computar tokens×preço |
| 🔵 | vocabulário Literal | `api/clients.py:348` | `AnalysisStatus` de `_analysis.STATUS_VALUES` |
| 🔵 | `mail/templates.py` dup | `:46-48` `text_to_html` ↔ inline em `render():142` | `render` chama `text_to_html` |
| 🔵 | `HubOut` colisão + `DecideIn` dup | `leadership` vs `staff` | renomear/unificar |

## 🟦 NÃO mexer — determinados como NÃO-bug (a auditoria errou; documentado)

- **InfinitePay estados terminais:** o PSP **não emite** evento de estorno/expiração (grep zero;
  webhook é só aprovação; model `PENDING→PAID` de propósito). Mapear seria **dead-code**. Doc em
  `wiki/integrations/bank/infinitepay.md` (seção Anti-delírio).
- **"Unificar CPF" (3 lugares):** regras **legitimamente diferentes** — `auth` (CPF de pessoa,
  rejeita dígito-repetido) vs `asaas/customers` (CPF **ou CNPJ**, 14 díg) vs `pixkey` (CPF-chave-PIX).
  Unificar **quebraria o CNPJ**. Só o `only_digits()` é dup real (baixo valor, acopla apps — pulei).
- **3 mapas de status de payout:** alfabetos diferentes (`TRANSFER_DONE` evento vs `DONE` status PIX
  vs status interno) em camadas diferentes; o `qrpay` é **provisório por falta de teste real de PIX**
  (`plan/4` §5). Auto-documentado no docstring.
- **Guardas defensivas:** `student/service.py:736` e `cpfhub.py:103` try/except em volta de
  dinheiro/rede com comentário explícito — **deixar** (robustez > remover 🔵).
- **`external_id`:** auditado — **borda-only, FK nativo interno** (zero `to_field=external_id`).
  Não é delírio; é CONVENTION §4. Não mexer.

## Como rodar o gate local (sem `.env` real)

```bash
echo 'SECRET_KEY=dev-dummy' > .env   # gitignored; SQLite default
uv run --frozen python manage.py makemigrations --check --dry-run --skip-checks   # "No changes"
uvx ruff@0.15.14 check . && uvx ruff@0.15.14 format --check .
```
> `manage.py check` SEM `--skip-checks` dá 9 erros E-level de keys de integração ausentes —
> são do `.env` dummy, **não** do código (no CI real passam). Use `--skip-checks` pro migration-check.
