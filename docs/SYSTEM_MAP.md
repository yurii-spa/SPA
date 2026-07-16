# SYSTEM MAP — живая карта SPA (что где, зачем, статус)

> Durable-память проекта: чтобы любая сессия заходила как CEO+архитектор, а не «новый сотрудник».
> Растёт инкрементально по мере аудита (программа: `docs/SYSTEM_AUDIT_AND_ARCHITECTURE_PROGRAM.md`).
> Источник правды — git. Каждая подсистема получает секцию: **что · зачем · статус · проблемы**.
> Обновляется после каждого прохода архитектора. Начато 2026-07-16.

## Легенда статусов
🟢 живой/используется · 🟡 частично/сомнительно · 🔴 мёртвый/дубль/лишний (→ карантин `attic/`) ·
🔵 нужен-но-не-работает (чинить) · ⚪ не проверен (ждёт прохода).

---

## WS-B · Флот агентов + инфра (аудит 2026-07-16)
**SSOT: `data/agent_registry.json`** (авто-генерится `scripts/build_agent_registry.py`) + визуальный
дашборд `/admin/agents`. **58 агентов загружено, exit-78 антипаттерн полностью вычищен** (все bash-wrapper,
/tmp логи), нет `-9`/`78`. По ролям: monitoring 28 · allocation 9 · research 8 · infra 7 · reporting 6.
Живых KeepAlive-демонов с PID: apiserver:8765, cloudflared, dashboard:8767, familyfund:8766, cc-kanban,
rtmr_sense, telegram_bot.

**Проблемы (7, → карточки):**
- 🔴 **5 swarm + golive_freshness + resilience — загружены, но НЕ переживут reboot** (нет plist в
  `~/Library`; `self_heal.py:107` глобит только оттуда → не оживит). Инсталлер починен (swarm добавлены);
  golive_freshness/resilience — plist отсутствуют в репо (нужна реконструкция). → карточка fleet-hardening.
- 🟢 **morning_digest — ПОЧИНЕНО:** переиспользованный ретайренный лейбл → переименован в `work_digest` (attic).
- 🟡 **orchestrator 1ч** (owner 2026-07-16, осознанно) — ARMED code-writer, ежечасно.
- **install_all_agents.sh** — баг битого пути (aggressive_lab/rates_desk_paper) ПОЧИНЕН + 5 swarm добавлены.
- **Рассинхрон:** plists лежат и в `scripts/`, и в `launchd/` (installer читает из `scripts/`) — почистить.
- **SPOF:** весь live-слой на одном Mac Mini (owner-gated: offsite/HA).

**GitHub/CI (`yurii-spa/SPA`):** ci.yml + test.yml (частичный дубль) + ci-lite (cron-дубль) + spa-lint +
proof-gate + owner-gate + numbers-lint + site_freshness + site_content_audit + spa_alerts. `deploy-landing.yml`
= НЕ canonical (mirror, dispatch-only). Канонический деплой сайта = CF Pages git-integration (не workflow).

## WS-A · Файлы репо (PASS 1: money-path + risk, аудит 2026-07-16)
Подсистемы pass-1: `adapters`(57) · `risk`(22) · `governance`(6) · `paper_trading`(96) · `execution`(30)
= **211 модулей**. Метод: import-граф по репо + `-m` entry-points. ~110 🟢 живых · ~40 🟡 · ~60 🔴.

- 🟢 **Инвариант подтверждён:** `risk/policy.py` — единственный hard-гейт RiskPolicy v1.0 («approved=False
  не переопределяется»); `governance/policy.py` — это authority-table (НЕ конкурирующий гейт, но имя путает).
  `kill_switch.py`, `ssot.py`, ядро cycle_runner, зарегистрированные адаптеры — живы.
- 🔴 **Крупнейший жир: ~45 аналитических модулей в `paper_trading/`** (advanced_ratios, deflated_sharpe,
  tail_risk, monte_carlo_projection … — построены+тестированы, но 0 live-импортов, не подключены к циклу/
  репортингу/API). → развязать в `spa_core/analytics_lab/` ИЛИ подключить в один tear-sheet.
- 🔴 **Явно мёртвые (0/0 или помечены REMOVED):** `adapters/{gmx_glp_arbitrum_adapter, radiant_arbitrum_adapter}`
  (в `__init__` прямо «REMOVED/dead»), `adapters/{config, l2_adapters, base_migration}`,
  `risk/{position_validator, strategy_stress_ranking}`, `execution/cutover_scorecard`, `governance/cpa_governance_watcher`.
- 🔴 **Дубли:** `adapters/compound_v3.py` vs `compound_v3_adapter.py` (один рынок); `execution/defillama_apy_feed.py`
  vs `adapters/defillama_feed.py`.
- 🟡 **Архитектура:** ТРИ параллельных реестра адаптеров (`__init__.ADAPTER_REGISTRY` / `adapter_registry.py`
  / `registry.py`) → свести к 1; `risk/policy_enforcer.py` caps сверить с `policy.py` (memory: stale caps);
  naming-коллизии `policy` (risk/governance/enforcer/hy/lp); 4 имени Pendle PT; execution помечать `frozen@paper`.
- ⚠️ **Инвариант #16:** test-only модули НЕ двигать молча — attic = переместить модуль+тест ВМЕСТЕ или подключить.

### WS-A PASS 2 (strategy_lab · monitoring · api · reporting · telegram · owner_queue · alerts · shadow · scripts, аудит 2026-07-16)
~294 модуля + ~340 скриптов. ~230 🟢 · ~30 🟡 · ~20 мёртвых модулей + ~64 мёртвых скрипта.
- 🟢 **Живы:** весь strategy_lab (4 деска + swarm + aggressive_lab), все 23 API-роутера, monitoring-агенты +
  sensors, telegram-дерево, alerts-ядро, reporting-спайн, owner_queue.
- 🔴 **Мёртвые модули:** `api/whitelabel_api`; monitoring `{adapter_watchdog, data_trust_monitor, posture,
  posture_gate, signal, sensors/_multisource}`; reporting HF-остров `{tear_sheet_hf, performance_attributor,
  benchmark_comparator, investor_report, pnl_attribution}` (MP-1236 дубль-attribution); alerts orphans
  `{apy_feed_monitors, protocol_report, risk_monitor, run_alerts, email_sender}`; `shadow/{allocator,registry}`;
  swarm `{leverage_brain, funding_regime}`.
- 🔴 **scripts/ — 2/3 осадок:** уже в `scripts/archive/` = 594; сверх них ~64 кандидата (push_*.sh ~39 +
  install_*.sh ~13 + migrate/backfill run-once + `.command` GUI-хелперы + `.plist.disabled`) — 0-ref,
  вытеснены `push_to_github.py`/`install_all_agents.sh`. Живой surface scripts/ ≈ 90 (59 wrappers + CI-гейты + ops).
- 🟡 **Дубли/архитектура:** gas-monitor триплет (arbitrum/optimism/unified vs живой base_gas_monitor);
  reporting HF-стек vs живой tear_sheet-спайн; `shadow/` (MP-106 vs Sprint-A); `command_handler` (вытеснён router);
  4 модуля «daily report» (alerts/reporting×2/telegram) — легко спутать.
- ⚠️ **Ловушка:** tuple-import `from routers import (a,b,…)` выглядит как 0-import (наивный grep врёт) — все 23
  роутера живы. File-contract (JSON verbatim) тоже недосчитывается import-графом — сверять с launchd.
- ⚠️ **Инвариант #16:** dead-модули с тестами (tear_sheet_hf, pnl_attribution, apy_* …) — двигать модуль+тест ВМЕСТЕ.

**Не проверено (pass 3):** `spa_core/{analytics, tournament, dfb, redteam, riskwire, compliance}`, docs/, root.

_ИТОГ АУДИТА: система полностью откартографирована (агенты · сайт · код). Чистка (attic) — фаза исполнения:
безопасные скрипты → `scripts/archive/`; модули с тестами → attic вместе с тестом; крупные развязки
(analytics_lab, реестры, HF-стек) — по greenlight владельца. Ничего не удаляется, всё обратимо._

## WS-C · Сайт (аудит 2026-07-16)
**~103 `.astro`-страницы** + 2 генератора (sitemap/rss, детерминированные). noindex через meta: 12
(404, cockpit-kit, cockpit, dashboard-preview, 3 redirect-стаба тиров, 6×admin).

**Проблемы (→ карточки):**
- 🟢 **`/admin/*` ЗА Cloudflare Access** — проверено curl → «Sign in · CF Access». Настроено в CF-дашборде
  (не видно из репо → аудит по коду ошибочно решил «no auth»; была ложная 🔴-тревога, снята). Открытой дыры
  НЕТ. Косметика: убрать устаревший коммент «access control = Phase 5, no auth yet» в `admin/index.astro`.
- 🔴 **Осиротевшие leftover-страницы (0 входящих ссылок):** `/cockpit-kit` (синтетические фикстур-числа —
  trust-liability для «never fabricated» продукта) + `/dashboard-preview` (leftover app-shell). → в attic.
- 🟡 **`/board/*` + `/cockpit/*` подстраницы** отдают `index,follow` вопреки robots-Disallow (несогласов. noindex).
- 🟡 **Числа не сходятся:** conservative цитируется 7+ способами (2.7…6%), RWA-floor 3.3 vs 3.4, /packages
  LIVE-бейдж на волатильном дневном APY. + две таксономии тиров (Preserve/Core/Max vs Cons/Bal/Aggr). → owner-gated.
- 🟡 **`/pilot`** — конверсия без контактного механизма + вне top-nav (orphaned из главной).
Ключевые: `SiteHeader/SiteFooter/Layout.astro`, `pages/admin/index.astro`, `public/robots.txt`, `SITE_UIUX_BACKLOG.md`.

## WS-D · Архитектурная память
_Этот файл + PROJECT_CONTROL/ + Claude-memory + Obsidian-зеркало. Как всё связано и ПОЧЕМУ так устроено._

⚪ _в процессе (этот документ — начало)_
