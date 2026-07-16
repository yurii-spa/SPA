# SPA — Smart Passive Aggregator · CLAUDE.md

> **Источник правды — файлы в git.** Nimbalyst / Obsidian / дашборды — только окна в них.
> Полная топология и two-agent separation: [`PROJECT_CONTROL/00_START_HERE.md`](PROJECT_CONTROL/00_START_HERE.md).
>
> **Снимок состояния** (git-committed `data/golive_status.json`; ЖИВЫЕ числа — `docs/SYSTEM_BRIEFING.md` /
> `docs/STATE.md`): GoLive **27/29** · трек **13/30** evidenced (anchor **2026-06-22**) · kill-switch SOFT −5% / HARD −10%.

## Что это (5 строк)

SPA — автономный DeFi yield-optimizer на стадии **paper trading**. Виртуальный капитал
**$100,000 USDC**: ежедневный цикл берёт живые APY/TVL из whitelisted-протоколов, прогоняет
через детерминированный RiskPolicy и ребалансирует виртуальный портфель. Цель — честный
30-дневный трек → go-live. Всё, что не в live-треке (sleeves, дески, рой) — **advisory / paper,
капитал не двигает**. Финмодель — `MASTER_PLAN_v1.md` (задачи MP-xxx).

---

## 🟢 Протокол сессии (ОБЯЗАТЕЛЬНО)

1. **В начале каждой сессии** (и после сжатия контекста / в новом окне) прочитать — чтобы НЕ быть
   «новым сотрудником без понятия что за агенты и что за dev-слой» (owner-directive 2026-07-16):
   - **`docs/SYSTEM_MAP.md`** — живая карта ВСЕЙ системы: каждый из 58 агентов (по ролям), страницы сайта,
     код по подсистемам, ПОЧЕМУ так устроено (+ `data/agent_registry.json` / дашборд `/admin/agents`);
   - **`nimbalyst-local/tracker/_BOARD.md`** — ЕДИНЫЙ ОБЗОР всех карточек одним взглядом (по типу+статусу,
     вверху «ждёт владельца»); авто-индекс, регенерится `scripts/build_tracker_board.py` + сам на каждой
     мутации карточки. Читать ЕГО первым, не открывая 56 файлов. Сами карточки — `nimbalyst-local/tracker/*.md`:
     `own-*`/`owner-decision-*` = Owner Decisions (ждёт владельца) · `agent-*` = Agent Tasks (что делает
     агент: backlog/in-progress/blocked/done) · `inbox-*` = задания;
   - **`docs/OWNER_BACKLOG_<дата>.md`** — свежие решения владельца из Q&A-сессий;
   - **агент-архитектура (2 слоя):** `docs/ADR_004_two_layer_agents.md` (dev vs product), `docs/10_agent_architecture.md`
     + `docs/08_ai_investment_os_architecture.md` (16 аналитиков), `docs/CMO_EDITORIAL_LAYER.md` (продвижение) —
     СПРОЕКТИРОВАНЫ, ждут активации (AAA-таск «продуктовый слой / супер-студия»);
   - `docs/STATE.md` — фокус, активные задачи, последние решения; `docs/decisions/INDEX.md` — реестр ADR;
   - `docs/SYSTEM_BRIEFING.md` — живой оперативный статус (auto, 30 мин). Без него нельзя утверждать
     «всё работает / агенты живы / portfolio в порядке».
2. **Перед изменением risk-логики** (`spa_core/risk/`, kill-switch, gates) — прочитать
   соответствующий ADR в `docs/decisions/` и правило `.claude/rules/risk-engine.md`.
3. **В конце цикла оркестратор ОБЯЗАН** обновить `docs/STATE.md` и дописать `docs/journal/<неделя>.md`.
4. **Ничего «в воздухе» — фиксировать до конца сессии.** Если в ЛЮБОЙ сессии (интерактивной или
   фоновой) с владельцем принято решение, достигнута договорённость или высказано пожелание — сессия
   ОБЯЗАНА записать это ПЕРЕД завершением:
   - **решение** → ADR (`docs/decisions/`) + строка в `docs/STATE.md`;
   - **задача** → карточка Inbox (`nimbalyst-local/tracker/`, через `orchestrator_queue.py create`);
   - **идея** → `docs/ideas/<дата-slug>.md`.
   Устных договорённостей быть не должно. **Не записано — работа сессии НЕ считается завершённой.**
5. **Path-специфичные правила** — читать перед работой в области:
   `.claude/rules/risk-engine.md` · `.claude/rules/site-copy.md` · `.claude/rules/adapters.md`.

## 🧭 Маршрутизация «идея ≠ инструкция»

- `docs/ideas/` (свободные идеи владельца) и `docs/rules-draft/` (черновики правил) — **агенты
  по ним НЕ действуют.** Идея становится инструкцией только после **промоушена владельцем**
  (пометка `#promote` в заметке или явная карточка-задание).
- **Промоушен (§7.3):** `#promote` → оркестратор превращает заметку в правило (`.claude/rules/` /
  `CLAUDE.md`), ADR (`docs/decisions/`) или задачу-карточку, затем метит исходник `#promoted`
  (скан: `scripts/orchestrator_queue.py promotions`).
- Действующие правила живут только в `CLAUDE.md` / `.claude/rules/`; решения — в
  `docs/decisions/`; задачи — в inbox / трекерах (`nimbalyst-local/tracker/`).

---

## 🔒 Инварианты (нарушать нельзя)

1. **Детерминированный RiskPolicy v1.0 — единственный hard-гейт исполнения.** `approved=False`
   не переопределяется никем. Version остаётся `v1.0` весь paper-период (изменение → новый ADR).
   Risk Scoring v2 — **только advisory**, никогда не гейт.
2. **Refusal-first / fail-CLOSED** — при недоборе кворума, расхождении фидов или нехватке
   истории система ОТКАЗЫВАЕТ / держит, а не угадывает.
3. **LLM запрещён** в risk / execution / monitoring / kill компонентах.
4. **Только stdlib** Python в runtime (исключение — FastAPI/uvicorn для API-сервера).
5. **Атомарные записи** — `spa_core.utils.atomic.atomic_save` (tmp в той же директории +
   `os.replace`), никогда прямой `open(..., "w")` на state-файлы.
6. **Не импортировать `spa_core/execution/`** из read-only / paper-кода.
7. **Никаких секретов в файлах** — PAT/токены/ключи читать из Keychain в рантайме
   (инцидент 2026-06-10: PAT утёк в 90+ файлов). Не создавать `push_*.html`.
8. **Никакого solicitation-языка на сайте** — продукт на paper-стадии, внешний капитал закрыт
   до legal-clearance. Не выдавать paper/backtest за live; каждая APY-claim имеет
   evidence-level (L0–L6, `docs/37`) + источник + risk-категория + last-verified дата.
9. **IS_ADVISORY=True** для всех новых стратегий/sleeve'ов T2/T3 до go-live.
10. **Sky/sUSDS = 0%** до подтверждённого GSM Pause Delay ≥ 48h on-chain.
11. **Атомарный KANBAN** — перечитывать с диска перед записью (конкурентный писатель — цикл).
12. **Деплой агента только через gate** — `scripts/check_agent_before_deploy.sh <name>` перед
    `launchctl bootstrap`; bash-wrapper (не прямой `python3 -m`), логи в `/tmp/` (не `~/Documents`)
    → иначе exit-78. Деплоить ≤3 агентов за раз.
13. **Notion / любое приложение — НЕ источник правды.** Только файлы в git.
14. **Агентам ЗАПРЕЩЕНО переводить карточку решения в `owner-done`.** Только владелец. Агент
    двигает лишь `needs-owner → ingested` (после инжеста ответа).
15. **Формат карточек владельцу (§2.4, обязателен для ВСЕХ карточек `needs-owner`):**
    - **Язык — русский, включая НАЗВАНИЕ карточки.** Просто, по-человечески, без жаргона.
      Технические имена (`ETHERSCAN_API_KEY`, Railway, cron) оставлять как есть, но словами
      объяснять, что это. Плохо: «ETHERSCAN_API_KEY на прод Railway». Хорошо: «Добавить ключ
      Etherscan на сервер — без него не работает проверка кошельков».
    - **Четыре секции в теле, ровно эти заголовки:**
      1. `## Что случилось и почему это важно` — 2–3 строки простым языком.
      2. `## Что от тебя нужно` — либо пошагово (шаг 1, шаг 2…), либо, если решение за владельцем —
         варианты + рекомендация агента и почему.
      3. `## Как понять, что готово` — одна строка.
      4. `## Что будет после` — что агент сделает, получив ответ.
16. **Запрещено МОЛЧА ослаблять или отключать тесты.** Нельзя удалять/скипать/сужать проверку,
    чтобы «покрасить CI зелёным». Намеренное изменение теста допустимо ТОЛЬКО с (а) явным
    обоснованием в теле изменения и (б) записью в `docs/journal/<неделя>.md` (что и почему).
    Есть сомнение, что тест устарел или мешает по делу → НЕ трогать молча, а завести карточку
    `needs-owner`. Красный тест — сигнал, а не помеха.

### 🛑 Two-tier kill-switch (ADR-034 + ADR-048)

Ответ на drawdown — одна лестница над evidenced peak-to-current drawdown
(`spa_core/governance/kill_switch.py`):

| Tier | Порог | Эффект |
|---|---|---|
| **SOFT_DERISK** | drawdown ∈ **[5%, 10%)** | halt new / no INCREASE (hold+reduce OK); НЕ ликвидирует |
| **HARD_KILL** | drawdown ≥ **10%** (inclusive) | full kill → all-cash |

RiskPolicy version = v1.0 (two-tier живёт в governance-слое, не в `RiskConfig`).

---

## ⚙️ Команды

```bash
# Дневной цикл вручную (НИКОГДА против live data/ в dev — только sandbox):
python3 -m spa_core.paper_trading.cycle_runner --verbose
# GoLive check:
python3 -m spa_core.paper_trading.golive_checker
# System health:
python3 -m spa_core.monitoring.system_health_monitor
# Обновить SYSTEM_BRIEFING сейчас:
python3 scripts/update_system_briefing.py
# Все тесты:
python3 -m pytest spa_core/tests/ -v
# Статус агентов:
launchctl list | grep spa    ·    bash scripts/verify_fleet_after_reboot.sh
# Переустановить агентов:
bash scripts/install_all_agents.sh
# Push (ABSOLUTE пути, PAT из Keychain GITHUB_PAT_SPA):
python3 push_to_github.py --files /abs/path/file.py --message "vX.XX: desc"
```

Python: `/Users/yuriikulieshov/miniconda3/bin/python3` (всегда). Секреты:
`security find-generic-password -s GITHUB_PAT_SPA -w` (и `TELEGRAM_BOT_TOKEN_SPA` /
`TELEGRAM_CHAT_ID_SPA`).

---

## 🏗️ Структура репо (10 строк)

| Путь | Назначение |
|---|---|
| `spa_core/adapters/` | Read-only адаптеры протоколов + DeFiLlama feed (`ADAPTER_REGISTRY`) |
| `spa_core/paper_trading/` | cycle_runner, golive_checker, gap_monitor, cycle_gates, pre_cutover_gate |
| `spa_core/risk/` | policy.py — детерминированный гейт (LLM FORBIDDEN) |
| `spa_core/governance/` | kill_switch.py (two-tier drawdown ladder) |
| `spa_core/strategy_lab/` | Pluggable sleeve harness + дески (rates_desk / rwa_backstop / swarm …) advisory |
| `spa_core/monitoring/` | health / agent_health / RTMR sense-loop / resilience |
| `spa_core/execution/` | **НЕ импортировать** из read-only кода |
| `spa_core/api/` | FastAPI сервер (api.earn-defi.com:8765) |
| `landing/` | Astro-сайт → Cloudflare Pages (earn-defi.com); canonical дашборд `/dashboard` |
| `data/` | Все JSON-state (runtime-only в .gitignore, часть owner-gated tracked) |
| `docs/` | STATE.md, decisions/, journal/, ideas/, rules-draft/, SYSTEM_BRIEFING.md, ADR-набор |
| `nimbalyst-local/tracker/` | Files-first очереди (git-tracked): карточки `own-*` (Owner Decisions), `inbox-*` (задания). Рендерятся в Nimbalyst как kanban |
| `.nimbalyst/trackers/` | Определения типов трекеров (owner-decision.yaml, inbox.yaml) |
| `inbox/` | Быстрый захват заданий из Obsidian (заметка → `ingest-notes` → карточка). Три входа заданий: Nimbalyst · `inbox/` · Telegram `/task`/голосовое (whisper офлайн) |
| `scripts/` · `launchd/` | LaunchAgent plists, install/verify, push_v*.sh |
| `KANBAN.json` | Kanban (источник MP-xxx задач) |

**Runtime:** Mac Mini · launchd fleet (~56 `com.spa.*` агентов, source of truth — `launchctl list`)
· daily_cycle 08:00 local → cycle_runner · apiserver:8765 через Cloudflare Tunnel · сайт на CF Pages.

---

## 📌 Ключевые ADR (полный реестр — `docs/decisions/INDEX.md`)

- **ADR-034 / ADR-048** — two-tier kill-switch (SOFT −5% / HARD −10% inclusive).
- **ADR-050** — RiskPolicy → governance-слой; API auth; exec-bypass закрыт.
- **ADR-053** — RTMR real-time monitoring sense-loop.
- **ADR-YL-011** — Site Custodian (защита earn-defi.com от stale-чисел) + freshness monitor.
- **ADR-YL-012** — SPA Swarm (5-слойный рой над aggressive-доменом, advisory).

---

## 🧪 Yield Lab / research-слой (docs-first, non-runtime)

Документационный слой (`docs/00_index.md` — индекс; `docs/06_spa_core_invariants.md` — читать
перед связанной работой) формализует уже существующий research-код
(`spa_core/strategy_lab/{aggressive_lab,rates_desk,rwa_backstop,liquidator,underwriting}`,
`redteam/`, `riskwire/`, `compliance/`). **Никогда не трогает** runtime-путь исполнения,
RiskPolicy, публичный дашборд или деплой. НЕ дублировать существующий код — формализовать.

**Стоп-правило:** остановиться и спросить владельца (карточкой `nimbalyst-local/tracker/own-*`) перед
изменением runtime / RiskPolicy / дашборда / деплоя. Одна задача за итерацию, без big-bang рерайтов.
