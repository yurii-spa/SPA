# AAA Product-Layer Super-Studio — Activation Plan (2026-07-16)

> ⚠️ **ПОПРАВКА 2026-07-17:** скоуп-субагент сканировал ЛОКАЛЬНОЕ дерево и пропустил, что **прошлая
> сессия УЖЕ построила интегрированный CMO-слой на origin** (`spa_core/cmo/{honesty_gate,draft_store,
> template_rewriter,pipeline}.py` + `api/routers/cmo.py` approve/reject + server.py). Мои пуши Шага 1/3
> ошибочно ПЕРЕЗАПИСАЛИ `honesty_gate.py` дублем (сломал `check_draft`, нужный `template_rewriter`).
> ИСПРАВЛЕНО: восстановил prior `honesty_gate`+тест; `editorial_agent` переписан в тонкий ЖИВОЙ RUNNER,
> делегирующий в prior `pipeline.run_pipeline` (не дублирует — это недостающие живой агент+launchd).
> УРОК: ВСЕГДА `git show origin/main:<path>` перед созданием файла (origin > local — дрейф). Шаг 2
> (investment_os harness) — genuinely new, конфликтов нет.

> Owner AAA-таск: построить ПРОДУКТОВЫЙ слой агентов, который следит за САМИМ продуктом (развитие · R&D ·
> продвижение), не только за цифрами. «Супер-студия, которая РЕАЛЬНО трудится (не имитирует) и работает
> С УМОМ». Архитектура уже спроектирована в доках; задача — **АКТИВИРОВАТЬ** её в живых агентов (как
> строили swarm), НЕ проектировать заново, НЕ дублировать. Скоуп-проход: 2026-07-16 (read-only).

## Три под-слоя
- **A · Head-of-Product / Architect** — house-view + allocation-proposal. Designed: `docs/08 §2.1`
  (Chief Investment Agent). Код-шаблон: `spa_core/agents/architect_agent.py` (analyze→propose→dump→bus).
  Dev-layer architect (LLM) уже жив: `spa_core/dev_agents/architect.py`. **Chief Investment agent — код отсутствует.**
- **B · 16 аналитиков / AI Investment OS** — `docs/08_ai_investment_os_architecture.md` (роли/входы/выходы/
  FORBIDDEN на все 16). Промпты есть (12/16) в `prompts/agents/`; отсутствуют 4-5 (Chief Investment,
  On-chain, News&Narrative, Quant&Backtesting, Portfolio Monitoring). **Код агентов — отсутствует.**
  Рантайм-каркас ГОТОВ (не пересобирать): `spa_core/agent_runtime/`, `redteam/`, `riskwire/`,
  `agents/llm_agent.py` (urllib Anthropic + canned-fallback + `is_llm_forbidden`), `agents/model_config.py`.
- **C · CMO / Editorial** — `docs/CMO_EDITORIAL_LAYER.md` (flow B: raw journal → CMO rewrite → honesty-gate
  → draft → owner-approve → publish). Факты есть: `scripts/generate_research_changelog.py`. Отсутствовали:
  honesty-gate, rewrite-агент, draft-store, approval-Kanban, publish.

## Шаблон активации = SWARM (доказанный)
Каждая capability = один маленький модуль по рецепту swarm (`docs/SWARM_ARCHITECTURE.md`):
1. Движок stdlib, детерминизм-by-default, fail-closed → `UNKNOWN`.
2. Пишет в НОВУЮ namespaced-папку (`data/{cmo_drafts,investment_os}/`), НЕ в runtime-state; atomic + hash-proof.
3. bash-wrapper `scripts/agent_<x>.sh` (через `agent_template.sh`).
4. launchd plist `launchd/com.spa.<x>.plist`, логи `/tmp/` (не ~/Documents — exit-78).
5. Деплой ТОЛЬКО через `scripts/check_agent_before_deploy.sh` (sandbox run-once + canonical-track hash guard), ≤3 за раз.
6. Read-only роутер отдаёт артефакт verbatim, fail-closed (missing→honest «unavailable» 200, не 500, не выдумка).
**Отличие продуктового слоя:** аналитики/CMO advisory и МОГУТ использовать LLM — но LLM ВСЕГДА за
детерминированным гейтом (evidence/abstain у аналитиков; honesty-gate у CMO). Без ключа → всё равно живой
агент (детерминированный digest), как canned-fallback в `llm_agent.py`. LLM — ВОКРУГ, никогда ВНУТРИ risk/exec/monitoring/kill.

## Staged-план (по одному агенту/шагу, ≤3 деплоя за раз, никакого big-bang)
**Phase 0 — фундамент (библиотеки, без деплоя, без owner-gate):**
- **Шаг 1 — CMO Honesty-Gate** (`spa_core/cmo/honesty_gate.py`) — детерминированный fail-CLOSED: числа-
  совпадают · дисклеймеры-на-месте · нет promissory · нет solicitation. ✅ **СДЕЛАНО 2026-07-16** (11 тестов).
- **Шаг 2 — Product-agent harness** (`spa_core/investment_os/harness.py`) — feed-read-fail-closed +
  evidence-tag (L0-L6) + UNKNOWN-on-stale + atomic + proof + advisory-stamp + optional-LLM-за-гейтом.

**Phase 1 — CMO/Editorial (самый готовый, высокая видимая ценность, owner-gate только на publish):**
- **Шаг 3 — CMO draft-агент** (`spa_core/cmo/editorial_agent.py`, первый ЖИВОЙ продуктовый агент,
  детерминированный rewrite, ключ не нужен): journal → template-rewrite → honesty-gate → `data/cmo_drafts/`
  (status draft). Wire: wrapper+plist+gate. Owner-gate: НЕТ (publish отложен).
- **Шаг 4 — CMO draft read-router** (`spa_core/api/routers/cmo.py`, read-only, verbatim, advisory).
- **Шаг 5 — LLM-rewrite drop-in** за тем же гейтом (нужен ключ владельца — §риски).
- **Шаг 6 — Publish-on-approval + Kanban** (owner-gate HARD; отложить до желания владельца).

**Phase 2 — 16 аналитиков (funnel снизу-вверх, каждый = модуль на harness Шага 2):**
- Шаг 7 Stablecoin Yield · 8 Reporting · 9 Red Team (движок готов) · 10 Market Regime (**reshape не
  дублировать** — уже есть `analysis/market_regime.py` + swarm `funding_regime.py`) · 11+ остальные ·
  Capital Allocation (owner-gate).

**Phase 3 — Head of Product (последним, зависит от всех):**
- Шаг N — Chief Investment Agent (шаблон `agents/architect_agent.py`; house-view memo + allocation
  **proposal**; конфликты показывает, не усредняет; owner-gate HARD).

## Owner-gates / решения владельца
1. **LLM-провайдер + ключ** для CMO-rewrite и reasoning аналитиков. Митигация: строим deterministic-first
   (Шаги 1-3,7) — пайплайн жив БЕЗ ключа; LLM падает за готовый гейт (Шаг 5). Не блокировать активацию на ключ.
2. **CMO publish (Шаг 6)** — HARD owner-gate (flow B: draft→approve→publish, никогда авто-publish).
3. **Chief Investment / Capital Allocation proposals** — HARD owner-gate (агент рекомендует, человек решает).
4. **Registry/launchd** — инвариант #12: bash-wrapper + /tmp логи, ≤3 агента за раз, через gate.

**Риски → митигация:** overstatement→honesty-gate (Шаг 1, до любого rewrite); дублирование→reshape
market_regime/redteam/riskwire/agent_runtime; advisory-boundary→новые data-папки, IS_ADVISORY, никогда
не трогает RiskPolicy/kill/live-трек/execution; exit-78→gate+wrapper+/tmp; live-track→sandbox hash-guard.
