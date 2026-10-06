# Director OS v2: design (RM-TRUTH-01 · C9). Implementation-ready, built on Mission Control

> **Status:** design for ADR-571 (draft: `ADR_DIRECTOR_OS_V2_DRAFT.md`). Measured on 2026-10-05 by HTTP GET to
> `127.0.0.1:8790` and `127.0.0.1:8788`, plus reading the candidate tree `/tmp/spa_rmtruth01` (HEAD `223e0dca4`)
> and `/tmp/spa_rmt_w2trd`. Read-only: nothing was posted, executed or written outside `D/`.
> Copy deck: `copy_deck_ru.json`. Work packages: `work_packages.json`.

---

## 0. What is live today, and what to keep or change

The live bundle is `b-20261005T143018Z-8f293397`. Its `mission.json` is 305 KB, schema `mission-control/1`. It is rebuilt every 300 s by `com.spa.mission_control` (`mission_build.py`) and served by `com.spa.mission_server` (fixed routes, GET/HEAD only, two loopback listeners, Access JWT on `:8792`). The UI has five tabs: Обзор · Капитал · Studio · Решения · Система.

| # | Live observation (2026-10-05 ~14:30Z) | Verdict | Change |
|---|---|---|---|
| K1 | **Hardened server:** fixed route map, GET/HEAD only, atomic bundle swap, proxy-header refusal, Access JWT | KEEP as is | none |
| K2 | **`CONTRACT` declares the UNKNOWN form for 30 rows.** `_meta{state,sources,observed_at,age_min,stale_after_min,reason}` and colour come from HEALTH only (ADR-537) | KEEP | Extend with a cell-level `canon` and `metric_type` (§2.0) |
| K3 | **Real capital** `LIVE_NOT_APPROVED $0` is derived from readable `execution_mode` plus engine constants | KEEP | Promote to a permanent header chip |
| K4 | **Capital cards:** packages (work/data/decision/evidence/live), CIO, live_readiness (Capital Shadow), research_universe + Sherlock, trading_research | KEEP | Re-group under CAPITAL sub-tabs (§2.2). Trading Lab switches to `trading_lab_view` cells |
| K5 | **`safe_text` redaction** of paths, tokens, e-mails and long numbers | KEEP | Also apply on first level: no hashes or labels (§2.5) |
| C1 | **`overview.now.current_epic` = "#10 Later engines — QUEUED"** | **WRONG** | RM-TRUTH-01 is not on `docs/ROADMAP.md`, and `_roadmap()` falls back to the first QUEUED item. Make `current` mean **IN_PROGRESS only**; otherwise show "эпик в работе не объявлен". Add RM-TRUTH-01 to the ROADMAP as in progress (WP3) |
| C2 | **`overview.now.in_progress = 37`** | MISLEADING | `orphan_report.stale_in_progress = 33`. 37 is a card inventory, not work. Replace with "Что делает Claude" (§3). Keep 37 in drill-down as "карточек в статусе in-progress (из них 33 залежались)" |
| C3 | **`system.backups` is `HEALTHY` with `offsite_is_real_remote=false`** | **DISHONEST (C10)** | Split into LOCAL_BACKUP / OFF_HOST_BACKUP / RECOVERY_TESTED. OFF_HOST = `SAME_HOST` (amber, never green) |
| C4 | **`overview.system` = "CRITICAL — agents CRITICAL"**, a single rollup over 5 parts, and raw enum keys "CRITICAL: 1, HEALTHY: 4" on the first level | CHANGE (C3) | Show the six `readiness_scopes` side by side. Any worst-of badge carries the label "худшее из 6 — не оценка здоровья" |
| C5 | **`critical_agents: ["com.spa.novel_edge_rnd"]`** and release items with `commit: bbb127730` on Overview | CHANGE | Show the human agent name from `manifest.role` and the alert text. Labels, shas and paths go to "Доказательства" only |
| C6 | **Decisions: 11 NEEDS_OWNER + 1 ACCEPTED.** Live `risk_class` is keyword-based. The candidate replaces it with declared `subject:`, and today **no card declares it**, so all 11 become `UNKNOWN` | CHANGE (C5) | Carry Director's triage: "ваш предмет" / "тема не объявлена — разбирает агент" / "предпосылку надо перемерить". Show the prod-only count separately |
| C7 | **No Problems, no readiness scopes, no product domain** | ADD | Problems from `problem_store.load_store` (`data/problems.json` is **absent in prod** today, so that card shows UNKNOWN). PRODUCT domain from the shelf, snapshot, freshness report and scopes |
| C8 | **`capital.live_readiness.owner_decisions_pending=4`** (go-live preconditions without a card) shown next to decisions 11 | CHANGE | Rename to "условия выхода на реальные деньги, ещё не выполненные: 4" under CAPITAL › Готовность. It is never a "decisions" number |
| C9 | **Five tabs** (Обзор/Капитал/Studio/Решения/Система) | CHANGE | Five tabs: Главная · Капитал · Студия · Продукт · Решения. Система merges into Студия |

**Director OS `:8788`** (70 KB RU page; sections CAPITAL / STUDIO / BUILD):

| Item | Verdict |
|---|---|
| Owner triage "6 ждут вашего решения · 11 это работа системы · 1 предпосылку надо перемерить", with source and age per item | **PORT** the semantics into MC Decisions. The heuristic itself is not ported, only the declared subject (C5) |
| "Где останавливается автономия" (where autonomy stops) | PORT as a static explainer in Решения › "Как это устроено" |
| Gate "приёмка не получена 107 дней" from `data/gate_status.json`, which is frozen since 06-20 | DROP. A dead source is shown as a live gate, which is C3(c) |
| Its own collector over the prod tree, `owner_blockers`, `live_trading_gate`, `KANBAN.json` | DROP. MC reads the same canons through the primitives |

---

## 1. Doctrine

See `ADR_DIRECTOR_OS_V2_DRAFT.md`. Operative rules for implementers:

1. **One module computes.** `spa_core/studio_os/company_truth.py` holds pure functions with injected `now` and paths. It never writes, never runs a subprocess itself, and never imports execution or telegram.
   - `mission_control.build()` is its only caller.
   - Host probes (`ps`, `launchctl`) are passed in by `build()`, which already obtains them through `director_report.collect`, behind the existing `measure_host` switch.
2. **Every cell carries its canon.** The UI shows a "откуда это" link that opens drill-down evidence: canon path or function, `as_of`, and the freshness rule.
3. **No consumer except the server.** An import ratchet enforces this, together with a path ratchet on `studio-os-serve/mission`.
4. **No actions.** Links go out to the SPA bot (answer a decision) or the Bridge bot (ask, idea, voice), the same as today's `intake` and `telegram_link`. These are `https://t.me/...` anchors and never POSTs.

---

## 2. Information architecture

### 2.0 Cell contract (shared by every card)

```json
{"value": <number|string|object|null>, "display_ru": "…", "display_en": "…",
 "metric_type": "OPERATIONAL|COUNT|REALIZED_PAPER|OBSERVED|BACKTEST|TARGET|MODELLED|POLICY|DECISION|TIMESTAMP|READINESS",
 "state": "MEASURED|MEASURED_ZERO|NOT_MEASURED|NOT_ENOUGH_HISTORY|STALE|CORRUPT",
 "as_of": "ISO|null", "canon": "<repo-relative path or module.function>",
 "freshness": {"age_min": n|null, "stale_after_min": n|null, "rule": "declared:manifest|declared:<mod>.<CONST>|fallback"},
 "unknown_ru": "<the Russian text rendered when state ∈ NOT_MEASURED/STALE/CORRUPT>"}
```

**Where the vocabulary comes from:**
- `state` reuses the vocabulary of `trading_research.read_model._cell` (MEASURED / MEASURED_ZERO / NOT_MEASURED / NOT_ENOUGH_HISTORY) and adds STALE and CORRUPT from `readiness_scopes`. CORRUPT means `as_of > now + 10 min`.
- Freshness thresholds are asked of the producer: manifest `produces[].slo_hours` or a module constant. A fallback is labelled `fallback`, the same rule as `readiness_scopes._slo_for`.

**Display rules:**
- Rates are always shown with their window and next to their drawdown (`rateWithTail` rule, inv. #8).
- BACKTEST, TARGET and MODELLED are never shown in the same row as REALIZED_PAPER or OBSERVED.
- Colour follows HEALTH/state only.

**Bundle shape.** One new top-level key `truth` sits alongside the existing keys. It is additive, and the existing tests stay valid:

```text
truth.schema = "company-truth/1" · truth.computed_at
truth.home.strip[5] · truth.home.money_chip · truth.home.attention[≤3]
truth.capital.{defi, trading_lab, btc, basis, treasury_rwa, sherlock, oracle, readiness}
truth.studio.{claude_work, roadmap, tasks, fleet, incidents, problems, self_heal, releases, memory, backups, decisions_summary, scopes}
truth.product.{public_release, website_health, profiles, public_metrics[], truth_incidents, backlog, next_release}
```

### 2.1 Owner Home (Главная): plain Russian, no scroll needed for the strip

**Header chip (permanent, every tab):** `Реальные деньги: $0 · не разрешены`.
- Source: the existing `capital.real_capital`.
- If the state is UNKNOWN, the chip reads "Реальные деньги: не измерено" in red-amber, never "$0".

**Five-tile strip, in this order:**

| Tile (RU) | What it answers | Canon / function | Fields shown | metric_type | Freshness | UNKNOWN text (RU) |
|---|---|---|---|---|---|---|
| **Система** | Does Studio OS work? | `readiness_scopes.scoped_readiness(data)` → `STUDIO_OS_HEALTH` (canon `data/agent_health.json`) + typed fleet headline (§4) | "в норме 86 из 92 · 1 авария · 2 предупреждения"; the tile colour is this scope's status | READINESS + COUNT | manifest slo of `agent_health.json` (3 h) | «Состояние агентов не измерено — отчёт сторожа не прочитан или устарел» |
| **Доходность** | How is the paper money doing? | `reporting.compound_apy.compound_annualized_pct` + `max_drawdown_pct` over `evidenced_bars(data/equity_curve_daily.json)` (the same function as the public hero; C1: no second formula). Balanced/Aggressive: `paper_trading.sleeve_track.sleeve_track_view` over `data/hy_paper_trading.json` / `data/lp_paper_trading.json` | "Консервативный: 4,9 % годовых · худшая просадка −0,04 % · 104 дня (бумага)". Balanced/Aggressive: "копится: 4 из 30 дней" | REALIZED_PAPER (+ window_days, annualisation) | 26 h (daily cycle), labelled `fallback` unless declared | «Доходность не измерена — дневной цикл не записал кривую капитала». Below maturity: «копится — N из 30 дней» (NOT_ENOUGH_HISTORY, never a number) |
| **Продукт** | Is the public site honest and fresh? | `readiness_scopes` → `PUBLICATION_HEALTH` (`data/site_freshness_report.json`) + `PUBLIC_SURFACE` | Status of each scope plus the one-line reason, e.g. «публикация застряла: сайт показывает данные от 01.10» | READINESS | `site_freshness_report` manifest slo | «Свежесть сайта не измерена — отчёт сторожа сайта не прочитан» |
| **Что делает Claude** | What is being built now, and is it stuck? | §3 derivation | «Эпик: RM-TRUTH-01 · активных сессий: 1 · карточка: … · стадия: ARTIFACT · блокер: нет» | OPERATIONAL | announcement log: live liveness probe; ROADMAP has no TTL | «Неизвестно, что делает Claude — журнал объявлений не прочитан» / «Claude работает, но не объявил над чем (процессов: N)» |
| **Нужно от меня** | What must I decide or do? | `decisions` (origin cards + prod answers) + `owner_queue.subject.subject_of` | «Ваших вопросов: X · тема не объявлена: Y (разбирает агент) · отвечено, едет в git: Z» + top 3 owner items | DECISION / COUNT | mirror sync ≤ 90 min (`MIRROR_STALE_MIN`) | «Очередь решений не измерена — трекер не прочитан» |

**`home.attention` (≤3 lines under the strip).** Plain-language items, chosen deterministically in this order:
1. any CORRUPT cell;
2. kill switch armed or soft de-risk active (from `system.kill_switch` / `derisk`);
3. owner items older than 7 days;
4. open Problems of severity CRITICAL;
5. OFF_HOST_BACKUP ≠ OK.

Each line links into its domain card.

### 2.2 CAPITAL (Капитал)

**Sub-tabs:** DeFi · Trading Lab · BTC · Базис · Казначейство/RWA · Sherlock · Oracle · Готовность.

| Card | Source function / artifact | Fields (first level) | metric_type | Freshness | UNKNOWN (RU) |
|---|---|---|---|---|---|
| DeFi · Консервативный | `compound_apy` over `data/equity_curve_daily.json`; `package_status.public_view(...).packages.conservative` | rate + window + max DD; evidenced days; work/data state; «реальные деньги: не разрешены» | REALIZED_PAPER, COUNT, OPERATIONAL | 26 h | «Трек не измерен — кривая капитала не прочитана» |
| DeFi · Сбалансированный / Агрессивный | `sleeve_track_view(hy_/lp_paper_trading.json)`; `package_status` `history.valid_periods` | «копится: N из 30» or rate + DD (only after maturity); mechanism in RU (`mechanism_ru`); `live_reason_ru` | REALIZED_PAPER or NOT_ENOUGH_HISTORY | 26 h | «Книга не прочитана — состояние неизвестно» |
| DeFi · Целевые ориентиры (drill-down only) | `landing/src/lib/tier_bands.json` / `constitution.json` | 6/12/20 % **TARGET**, never in the same row as realized | TARGET | by ADR | «Ориентир не записан» |
| Trading Lab | `trading_research.read_model.trading_lab_view(data/trading_research)` (cells) | engine health; candidates 138; forward-paper 5; champions 0; forward periods; evidence chain VERIFIED; drawdown_forward | OPERATIONAL / COUNT / FORWARD_PAPER_* (backtest cells drill-down only, labelled БЭКТЕСТ) | `STALE_AFTER_H` = 2 h | «Лаборатория не измерена — статус движка не прочитан» |
| BTC | Same `trading_lab_view.btc_signal_consensus_by_timeframe` + `latest_btc_signal_forward`; earn-defi engine as `related_products` (EXTERNAL_PRODUCT_REFERENCE) | consensus per timeframe; «канон BTC-сигнала не назван ADR» banner until it is | OBSERVED / EXTERNAL | 2 h | «BTC-сигнал не измерен». The external engine is shown separately: «внешний продукт, не суммируется» |
| Базис / фандинг | `research_factory.read.latest` → `research_universe.by_mechanism["FUNDING_CAPTURE"]`, `basis_track` | candidates by status (DATA_INSUFFICIENT 40 …), blocker «нет данных о комиссиях» | COUNT / RESEARCH | ~26 h (`CIO_READ_MODEL_MAX_AGE_H`) | «Фабрика исследований ещё не запускалась» |
| Казначейство / RWA / кэш | `research_universe` (USYC/OUSG/USDY/BUIDL rows) + cash from `current_positions.json` via `package_status` | USYC «бумажный эталон, 0 из 30 периодов»; others' status; cash $ and its yield | COUNT / REALIZED_PAPER | 26 h | «Нет данных по казначейству» |
| Sherlock | `research_universe.sherlock` (`research_evidence`, ADR-564) | facts usable 43 of 56; awaiting independent review 13 | COUNT | by event, no TTL; `as_of` shown | «Реестр фактов не прочитан» |
| Oracle (CIO) | `investment_cio.read.latest(Path("data"))` | stance (INSUFFICIENT_EVIDENCE → «данных недостаточно»), confidence, date; weights only if non-empty | DECISION (advisory) | 1800 min (contract) | «Рекомендаций ещё не было» |
| Готовность к реальным деньгам | `readiness_scopes` → `INVESTMENT_ENGINE_READINESS`; `capital_shadow.read.latest` sleeves | NOT_READY + blockers in RU (custody, audit, execution mode); per-sleeve BLOCKED/NOT_READY; «условий не выполнено: 4»; inventory «29/29 — это инвентарь, не готовность» in small print | READINESS | execution_readiness manifest slo; shadow 1800 min | «Готовность не измерена — не трогать деньги» (fail-closed wording) |

### 2.3 STUDIO OS (Студия)

| Card | Source | Fields | metric_type | Freshness | UNKNOWN (RU) |
|---|---|---|---|---|---|
| Что делает Claude | §3 | epic · active sessions (announced) · running claude processes · card title · stage · blocker · next step | OPERATIONAL | live probe | see §3 |
| Дорожная карта | `_roadmap(mirror)` (fixed: current = IN_PROGRESS only) | epics with DONE/IN_PROGRESS/QUEUED; «подтверждено владельцем: <date>» | DECISION | mirror ≤ 90 min | «Дорожная карта не прочитана» / «эпик в работе не объявлен» |
| Задачи | `build_loop.board(tdir)` + `orphan_report.stale_in_progress` | queued (new+backlog), in progress (and how many stale), blocked, recently done (titles) | COUNT | mirror ≤ 90 min | «Доска задач не прочитана» |
| Агенты (типизированный флот) | §4 | headline + six typed counts + list of failing agents by **human name** | COUNT | agent_health 3 h | «Состав флота не измерен» |
| Инциденты | `data/telegram/push_state.json` events in `bad` state | open incident count + plain titles (event key → RU via copy deck, otherwise «событие без описания») + since | OPERATIONAL | push_state has no TTL; age shown | «Состояние тревог не прочитано» |
| Проблемы | `problem_store.load_store(data)` (`data/problems.json`) | OPEN / MITIGATED (no RCA) / CLOSED in 7 d; per problem: agent name, cause in RU, occurrences, «RCA: есть/нет», linked agent card | COUNT / OPERATIONAL | written hourly by `agent_health_monitor` tail → 3 h | «Реестр проблем ещё не запущен» (today: file absent in prod) |
| Самовосстановление | `data/self_heal_status.json` | last run, restarts done, failures (names) | OPERATIONAL | manifest slo | «Самовосстановление не измерено» |
| Релизы | `release_feed` (git origin via mirror + `code_sync_status`) + `system.code` | «в проде то, что принято: да/нет»; today N changes (summaries in RU); the release state word (IN_PROD_TREE/…); shas drill-down | OPERATIONAL | code_sync 120 min | «Неизвестно, что сейчас в проде» |
| Память | `architecture/memory_truth.json` + `data/memory/index.db` manifest `built_at` (read-only sqlite URI) | newest indexed ADR vs newest ADR on origin → «индекс отстаёт на N решений» | OPERATIONAL | rule: lag > 0 ADRs = amber | «Индекс памяти не прочитан» |
| Бэкапы и восстановление | `data/backups/spa_state_*.tar.gz` (mtime), `data/dr_offsite_status.json`, `data/resilience_status.json.restore_drill` | **three separate rows:** LOCAL_BACKUP (last archive age); OFF_HOST_BACKUP (`is_real_remote` true ⇒ OK, false ⇒ `SAME_HOST`, missing ⇒ UNKNOWN); RECOVERY_TESTED (drill OK/STALE/FAILED/NEVER_RUN) | OPERATIONAL | local 1800 min; drill per its own `stale` flag | «Бэкап не измерен» per row. Never one green over three |
| Решения владельца (сводка) | → Решения tab | counts as on Home | DECISION | — | — |
| Области готовности | `readiness_scopes.scoped_readiness` | all six scopes, each with status, reason, as_of, «что это блокирует / не блокирует» | READINESS | per scope | per-scope «не измерено — <reason>» |
| Машина | existing `system.resources`, `heavy_jobs`, `cleanup`, `services` | disk free, memory pressure, heavy jobs | OPERATIONAL | 20 min | «Ресурсы не измерены» |

### 2.4 EARN DEFI PRODUCT (Продукт)

| Card | Source | Fields | metric_type | Freshness | UNKNOWN (RU) |
|---|---|---|---|---|---|
| Публичный релиз | `landing/src/data/site_numbers.json` on **origin** (mirror): `measured_at`, `published_at`, `next_publication`; `track_snapshot.json.generated_at` | «на сайте замер от 01.10, опубликован 01.10, следующий 08.10» | TIMESTAMP | weekly cadence; overdue = after `next_publication` | «Неизвестно, что опубликовано» |
| Здоровье сайта | `PUBLICATION_HEALTH` scope (`site_freshness_report.json`: `fails[].code`, `publisher_stuck`, `site_as_of`) | status + plain reason, e.g. «сборщик снимка падает с 02.10» | READINESS | manifest slo | «Свежесть сайта не измерена» |
| Профили | shelf `packages.*` (kind) + `tier_bands.json` (TARGET) + `package_status` | Conservative / Balanced / Aggressive: public label, number with **kind** («замер» / «бэктест» / «ориентир»), reportable or «копится» | REALIZED_PAPER / BACKTEST / TARGET (never mixed) | weekly | «Профиль не прочитан» |
| Публичные метрики | shelf `headline`, `track`, `books` + `track_snapshot` (`paper_apy_pct`, `max_drawdown_pct`, `real_track_days`) | one row per public number: value · metric_type · window · `measured_at` · source | per number | weekly (shelf) / daily (snapshot) | per row «нет в витрине — на сайте печатается „данные недоступны“» |
| Инциденты правды продукта | `problem_store` entries in `SITE_PUBLICATION_FAMILY` + `typed_numbers` ladder-conflict over shelf (TARGET-only) + `PUBLIC_SURFACE` scope | open items in RU (e.g. «на главной „29/29“ — это инвентарь») with the owner subject when it is №2 | OPERATIONAL | 3 h | «Не измерено» |
| Бэклог продукта | origin tracker, open cards whose **declared** `domain:` or `tags:` contain `site`/`landing`/`product`/`earn-defi` | count + top titles; «карточек без объявленной области не считаем» | COUNT | mirror ≤ 90 min | «Бэклог не прочитан» |
| Следующий релиз | shelf `next_publication` + C12 gate state (sequencing check) | «следующая публикация 08.10 · пройдёт после проверки типов чисел: да/нет» | TIMESTAMP / DECISION | weekly | «Дата следующей публикации не записана» |

### 2.5 First-level hygiene (enforced by test)

- **Forbidden on Главная and on every domain's first level:**
  - commit shas (`\b[0-9a-f]{7,40}\b`);
  - `com.spa.` / `com.studiobridge.` labels;
  - `pid`;
  - paths `data/…`, `.json`, `/Users`, `/tmp`;
  - raw enum keys (`CRITICAL:`, `NOT_MEASURED`): the UI renders them through the copy deck.
- **These live under «Доказательства»** (a collapsed `<details>` at the end of each card): `canon`, `as_of`, freshness rule, labels, shas.
- **Agent display names** are `manifest.agents[].role` + intent rendered through the copy deck. If none is declared, show «агент без описания» plus the label in drill-down. Free text keeps going through `safe_text`.

### 2.6 Решения (Decisions) tab

- **Groups:**
  1. «Ваш предмет» (`subject_of` ∈ MONEY / PUBLIC_NUMBERS_NAMING_LEGAL / IRREVERSIBLE / PHYSICAL_ACTION);
  2. «Тема не объявлена — разбирает агент» (UNKNOWN);
  3. «Отвечено, едет в git» (ANSWERED);
  4. «Принято, в работе» (ACCEPTED);
  5. «Только в проде, не на origin» (prod-only cards, read from `inp.repo` tracker minus mirror). The live surface misses these today, which is A5 §1.1.
- **Per card:** title, reason, requested action, done-when, age, subject, and the "Ответить в Telegram" deep link. The link already exists in `decision_item.telegram_link`.
- **No inline buttons.** Answers happen in the SPA bot only.
- **Live data:** today the first group is 0 and the second is 11, because no card declares `subject:`. This is correct and expected. The owner sees that the agent owes triage.

---

## 3. "What is Claude working on": canonical derivation (no new store)

**Candidates measured:**

| Candidate | What it actually answers | Why it is not the canon |
|---|---|---|
| Tracker `in-progress` cards (origin) | cards whose status was set to in-progress at some point | 37 today, of which 33 are stale (`orphan_report.stale_in_progress`). Status is not activity |
| `build_loop.lineage(card)` (ADR-551) | stage of ONE card, from IDEA to MEMORY | needs a card to be given. It is the **stage** source, not the "who/what now" source |
| `data/orchestrator_cycle.lock/holder.json` | the one autonomous cycle holding the lock (`session: cycle-19528`, pid, start) | covers only the orchestrator, not interactive or parallel sessions |
| `director_report.count_claude_sessions(ps)` | number of `claude -p` processes | a count with no subject |
| **`data/session_changes.jsonl`** (writer `scripts/log_session_change.py`, the house ANNOUNCE protocol, always in the main tree via `_shared_log`) | every session's claims: `session`, `session_pid` + `session_pid_start`, `card`, `card_state ∈ claim\|done`, `summary`, `ts` | **CHOSEN.** It is the only existing record that links *a live process* to *a card* and *a human summary*. Steps 0a/0b and `check_card_claim.py` already read it, so it is the house's own answer to "who holds what" |

**Derivation (pure, in `company_truth.claude_work(log_rows, ps_probe, tracker, roadmap, lineage_fn, problems)`):**

1. **Parse** the last ≤ 2000 lines of `data/session_changes.jsonl` (prod tree `inp.repo`), tolerating bad lines and counting them.
2. **Group by `session`** and keep the last record per session.
3. **Determine liveness** with the existing `scripts/check_undelivered_work.session_state(entry, self_session="", ps=…)`, which returns ACTIVE / NOT_CONFIRMED / UNKNOWN.
   - It is loaded by `importlib` from its file. Do not copy it: copying would create a second liveness rule.
   - The `ps` probe is injected; tests pass a fake.
   - **Active work** = sessions with `state == ACTIVE` and last `card_state != "done"`.
4. **Fill fields for each active session:**
   - **Card:** `card` → tracker title (origin, falling back to prod), status.
   - **Stage:** the first `build_loop.STAGES` entry in `lineage(card)` whose state ≠ DONE. Render it through the copy deck, for example «ARTIFACT → «нет коммита»».
   - **Blocker:** card `status == blocked`, or a `blocked_by:` field, or an open Problem whose agent equals the card's declared `owner`/`claimed_by`, or a `needs-owner` card with `blocks: <card>`. The fields `blocks` (32 cards) and `blocked_by` already exist.
   - **Next step:** the card body section `## Следующий шаг` if present; otherwise «следующая стадия: <next lineage stage>».
   - **Summary:** `summary`, through `safe_text`, capped at 140 characters.
5. **Epic:** the `docs/ROADMAP.md` item with state IN_PROGRESS (after the C1 fix). If none, show «эпик в работе не объявлен».
6. **Undeclared work:** `count_claude_sessions(ps)` minus the number of ACTIVE announced sessions, floored at 0. If greater than 0, show «Claude работает без объявления: N процессов». This is a measurement, not a guess.
7. **Outcomes:**
   - log unreadable ⇒ the whole cell is NOT_MEASURED;
   - log readable and zero active ⇒ MEASURED_ZERO «сейчас никто не работает»;
   - `ps` unavailable (`measure_host=False`) ⇒ liveness UNKNOWN, rendered as «не удалось проверить, жива ли сессия».

**Live check (2026-10-05 14:11Z):**
- The last claim is `cycle-19528`, card `inbox-task-portfolio-cio-dynamic-capital-alloc`, «цикл #779 / заказ G99 п. 1 (ADR-568)…». It matches `orchestrator_cycle.lock/holder.json`.
- The interactive RM-TRUTH-01 sessions have **no** entries in the log. Today they would appear only as «без объявления». The protocol fix belongs to the session, not the cockpit: epic sessions announce with `--card`.

---

## 4. Typed fleet counts (S1, C11)

**Canon:** `architecture/manifest.json` (`agents[]`: `label`, `intent ∈ active|retired|designed`, `schedule`, `role`, `layer`).

**Observations:**
- `launchctl list`, read once by `director_report.collect` → `rep["services"]` / its parsed launchctl map;
- `data/agent_health.json.agents[]` (status, category, loaded);
- `architecture/roles.json.roles[]`;
- live workers (§3).

| Type | Definition (deterministic) | 2026-10-05 value |
|---|---|---|
| `runtime_services` | manifest `intent=active` ∧ `schedule == "daemon"` (KeepAlive long-livers: api, bot, MC server, tunnel, …), shown as loaded/declared | 9 / 9 loaded (`apiserver, cc-kanban, cloudflared, dashboard, director_server, familyfund, mission_server, rtmr_sense, telegram_bot`) |
| `managed_agents` | manifest `intent=active` ∧ `schedule != "daemon"` (interval/calendar/event/manual), shown as loaded/declared | 82 / 83 loaded (missing: `mission_tick`, plist outside repo) |
| `configured_roles` | `architecture/roles.json.roles[]` with `implemented=true`. These are logical roles (Oracle …), **not processes**, and never summed with the above | 3 |
| `active_workers` | §3 ACTIVE announced sessions + undeclared Claude processes (two numbers, shown as «объявлено A · без объявления U») | A=1 (cycle-19528), U = count − A |
| `retired_loaded` | manifest `intent=retired` ∧ label in launchctl. **Violation of C11**: red, plus a Problem | 0 |
| `unknown_orphans` | label in launchctl with prefix `com.spa.` or `com.studiobridge.` ∧ not in manifest. Cross-check: `orphan_report.counts.worker_not_in_manifest` | 3 (`com.studiobridge.activation-engine`, `.coordinator`, `.telegram`; Bridge is a known neighbour per ADR-521. WP3 declares it in the manifest as `layer: studio_bridge`, after which it counts as runtime_services) |

**Single headline (Home and Студия):** `в норме X из Y объявленных`.
- Y = `runtime_services.declared + managed_agents.declared` (92).
- X = the number of those labels with `agent_health` status `OK` (86).
- Suffix «· аварий C · предупреждений W». If `retired_loaded > 0` or `unknown_orphans > 0`, add «· вне учёта: N».
- `agent_health` stale or absent ⇒ «в норме ? из 92 — состояние не измерено». Y stays, because it comes from canon.

All other fleet numbers (89 agent_health · 88 self_heal · 83 installer · 99 registry · 94 loaded) appear only in drill-down as «другие счётчики и почему они другие».

---

## 5. Mobile

**Widths 375 / 390 / 430 (CSS px).** Single column with a 16 px side gutter, so content is 343 / 358 / 398 px. `html,body{overflow-x:hidden}` is a guard only: the real requirement is that no element exceeds the content width. Long tokens use `overflow-wrap:anywhere`, and tables become stacked key/value lists below 600 px.

**Home strip:**
- 5 full-width tiles, each ≥ 64 px high.
- Line 1: label, 15 px semibold, ≤ 18 characters RU.
- Line 2: value, 17 px, ≤ 34 characters RU at 375; the copy deck enforces max_len.
- Line 3: optional reason, 13 px, ≤ 2 lines then clamped.
- The whole strip fits in ≤ 1.6 screens at 390×844.
- At ≥ 430 Система/Продукт may sit 2-up only if both values are ≤ 16 characters; otherwise stay stacked.

**Bottom nav:**
- 5 items × ≥ 68 px, icon plus label ≤ 8 characters: Главная · Капитал · Студия · Продукт · Решения.
- Tap targets ≥ 44×44.
- Respect `env(safe-area-inset-bottom)`.

**Capital sub-tabs:** a horizontal scroll chip row *inside* its own container. This is the only allowed horizontal scroller, and it has `scroll-snap`.

**Language and colour:**
- Russian is the default. EN is via the existing `lang-toggle`, as the secondary language.
- Numbers use the RU format: decimal comma, NBSP before `%`, dates `05.10`.
- No colour-only signal: every state chip has a word.
- Dark and light both come from the existing tokens.

**Performance:** the first paint must not wait for the 305 KB model. The server keeps serving `mission.json` whole. WP2 renders the Home from `truth.home` first, and the bundle can later add `home.json` as a second file built in the same step. This is optional and listed in WP1 as a stretch.

**30-second comprehension test (script).**

Setup:
- Phone at 390×844, Russian.
- Open `mc.earn-defi.com` cold.
- Start a timer.
- The owner (or a stand-in reading only the screen) must answer aloud without tapping into drill-down. One scroll is allowed.

| # | Question | Where the answer must be | Pass if |
|---|---|---|---|
| 1 | Двигаются ли реальные деньги? | header chip | «$0 · не разрешены» seen within 3 s |
| 2 | Что-то сломано прямо сейчас? | tile Система + attention | names the failing thing in words (e.g. «1 агент упал: исследования новых идей») |
| 3 | Сколько зарабатывает бумажный портфель и какая худшая просадка? | tile Доходность | rate, window and drawdown together; Balanced/Aggressive «копится N/30» |
| 4 | Сайт показывает свежие и честные цифры? | tile Продукт | yes/no + date of the data on the site |
| 5 | Что сейчас делает Claude и не застрял ли он? | tile Что делает Claude | epic, card in plain words, stage, blocker («нет» or what) |
| 6 | Что нужно от меня и сколько этого? | tile Нужно от меня | count of real owner items vs «разбирает агент» |
| 7 | Есть ли копия данных вне этого Мака? | attention line or Студия › Бэкапы in one tap | «нет — копия на том же диске» |

Record time-to-answer per question. Fail if any answer needs a JSON key, a hash or a launchd label, or exceeds 30 s total. The deterministic part is automated as `test_home_answers_the_seven_questions` (§6), which checks that every answer string is present in the rendered Home text for a fixture scene.

---

## 6. Acceptance tests (deterministic, no LLM, no network, no host probes)

All tests build scenes in `tmp_path` with an injected `now`. They never read prod `data/` (C8).

| Test (file) | Asserts |
|---|---|
| `spa_core/tests/test_company_truth_import_ratchet.py` | AST scan of `spa_core/`, `scripts/` and `studio_shell/`: only `spa_core/studio_os/mission_control.py` (+ `spa_core/tests/test_company_truth*.py`, `test_mission_*`) imports `company_truth`. No file outside `mission_server.py` / `mission_build.py` / their tests contains `studio-os-serve/mission` or opens `mission.json`. Positive control: a planted importer in a disposable tree turns it red and names the file. The baseline is empty and can only shrink |
| `spa_core/tests/test_mission_rebuild_from_canon.py` | Build a scene, run `mission_build` into root A, delete root A entirely, rebuild into root B with the same `now` and inputs. Expect `mission.json` identical (excluding bundle id) and the first-level text rendered by a stdlib HTML-free renderer of `truth.home` identical. Also: `company_truth` writes nothing (`os.listdir` before == after, and no `open(...,'w')` in its AST) |
| `spa_core/tests/test_company_truth_unknown.py` | Parametrised over every canon in the cell table (equity curve, books, agent_health, site_freshness_report, session_changes, tracker, problems.json, dr_offsite_status, backups dir, resilience_status, trading_research/status.json, cio ledger, shadow ledger, research_factory, memory index, manifest, roles): remove it, then the cell `state ∈ {NOT_MEASURED, STALE}`, `value is None`, `display_ru == unknown_ru` from the copy deck, and the tile is never green. Future `as_of` ⇒ CORRUPT. Stale ⇒ STALE, not the content's status |
| `spa_core/tests/test_mission_no_money_action.py` | Static: `mission_ui/*.html\|js` contain no `<form`, no `method=` other than GET, no `fetch(` with a `method` option, no `XMLHttpRequest`, no `act:`, `/pause`, `/resume`, `kill`, `set_status`, `record_owner_answer`. Every `href` is `#…` or `https://t.me/`. Server: POST/PUT/DELETE/PATCH ⇒ 405 on both listeners. Model: `company_truth` AST imports neither `spa_core.execution` nor `spa_core.telegram` nor `governance.kill_switch` writers |
| `spa_core/tests/test_scoped_readiness_never_collapsed.py` | `truth.studio.scopes` has exactly the six `readiness_scopes.SCOPES`, in order. No key `overall`/`ready`/`all_green` exists outside a scope item. The UI copy for any worst-of badge contains «худшее из». A scene with STUDIO OK + INVESTMENT NOT_READY never renders green on the Система tile combined with READY text. Inventory 29/29 never appears in the READINESS row |
| `spa_core/tests/test_typed_fleet_counts.py` | Fixture manifest + launchctl text + agent_health give the six counts exactly. Retired-but-loaded ⇒ `retired_loaded=1` + red. An unknown `com.spa.x` ⇒ `unknown_orphans=1`. Roles are never added to processes. agent_health absent ⇒ headline «? из Y», Y unchanged |
| `spa_core/tests/test_claude_work_derivation.py` | Fixture log + fake `ps`: an ACTIVE claim gives card, stage and blocker. A `done` record gives no active work. A dead pid is NOT_CONFIRMED and is not shown as active. No log ⇒ NOT_MEASURED. 2 claude processes with 1 announced ⇒ «без объявления: 1». The epic is the IN_PROGRESS ROADMAP item. No IN_PROGRESS ⇒ «эпик в работе не объявлен», never the first QUEUED item (regression of live C1) |
| `spa_core/tests/test_backups_three_facts.py` | `is_real_remote=false` ⇒ OFF_HOST `SAME_HOST`, the card is not green even with local OK and drill OK. Absence of each file ⇒ its own row UNKNOWN |
| `spa_core/tests/test_decisions_triage.py` | Declared subjects go to «ваш предмет»; missing go to «разбирает агент»; prod-only cards are shown in their own group; the count on Home equals the Решения tab count (one function) |
| `spa_core/tests/test_mission_ui_static.py` (extend) | i18n key parity RU/EN equals `copy_deck_ru.json` keys. First-level render of a fixture contains no sha / `com.spa.` / `pid` / `data/` / `.json`. Viewport meta present. CSS has the `max-width:100%` and `overflow-wrap:anywhere` rules. No fixed widths > 343 px outside `@media (min-width:600px)` |
| `spa_core/tests/test_home_answers_the_seven_questions.py` | For a fixture scene, the rendered Home text contains the answers to the seven questions of §5, with the expected strings from the copy deck templates |

**Probe for the card (ADR-208).** Register `director_os_v2_home_complete` in `card_acceptance.PROBES`:
- **Green when:** a disposable-tree build of the MC model contains `truth.home.strip` with 5 tiles, each with a `canon`; `truth.studio.scopes` has 6 items; the ratchet test file exists and is wired into CI.
- **Red, naming the link, on:** each missing tile, a missing canon, a missing scope, or an unwired ratchet.

---

## 7. Implementation plan

The plan is three non-overlapping Sonnet work packages; details and file lists are in `work_packages.json`.

| WP | Scope | Files (exclusive) | Depends on |
|---|---|---|---|
| **WP1 · Company Truth read model** | `company_truth.py` (cells, home strip, typed fleet, claude_work, capital/studio/product cards); `mission_control.py` integration (`truth` key, CONTRACT rows, `_roadmap` IN_PROGRESS-only fix, backups three facts, decisions triage groups incl. prod-only, live_readiness rename); all model-side tests | `spa_core/studio_os/company_truth.py` (new) · `spa_core/studio_os/mission_control.py` · `spa_core/tests/test_company_truth*.py`, `test_mission_rebuild_from_canon.py`, `test_mission_no_money_action.py` (model + server part), `test_scoped_readiness_never_collapsed.py`, `test_typed_fleet_counts.py`, `test_claude_work_derivation.py`, `test_backups_three_facts.py`, `test_decisions_triage.py`, `test_mission_control_contract.py` (amend, journaled per inv. #16) | candidate tree merged (`readiness_scopes`, `problem_store`, `subject`, `typed_numbers`, `compound_apy`, `sleeve_track`) + `trading_research/read_model.py` from `/tmp/spa_rmt_w2trd` |
| **WP2 · Mobile UI** | New IA (Главная/Капитал/Студия/Продукт/Решения), header money chip, home strip + attention, domain cards, evidence drawers, first-level hygiene, RU copy deck → `i18n.js` | `spa_core/studio_os/mission_ui/{index.html,app.js,i18n.js,styles.css,manifest.webmanifest}` · `spa_core/tests/test_mission_ui_static.py` · `spa_core/tests/test_home_answers_the_seven_questions.py` | the JSON shape in §2.0 (frozen here), so it can be built in parallel against a fixture |
| **WP3 · Canon, doctrine, retirement paperwork** | ADR-571 (+ INDEX), ROADMAP adds RM-TRUTH-01 IN_PROGRESS + Director OS v2 line, manifest declares Studio Bridge labels (`layer: studio_bridge`) and marks `director_server`/`director_build`/`dashboard`/`dashboard_watcher` with `retire_pending_owner: true` (intent stays `active` until unloaded, per C11), `card_acceptance` probe `director_os_v2_home_complete` + its two-sided test, owner card (RU, 4 sections, `subject: physical_action`) for the unloads and the 4.8 GB delete, STATE.md line + journal | `docs/decisions/ADR-571-*.md`, `docs/decisions/INDEX.md`, `docs/ROADMAP.md`, `architecture/manifest.json`, `spa_core/monitoring/card_acceptance.py` (probe only), `spa_core/tests/test_director_os_v2_probe.py`, `nimbalyst-local/tracker/owner-decision-*.md` (via `orchestrator_queue.py create`), `docs/STATE.md`, `docs/journal/2026-W41.md` | none (the probe goes red until WP1 and WP2 land, by design) |

**Order:**
1. WP3 first: it gives the ROADMAP fix and the probe.
2. WP1 and WP2 in parallel.
3. Integration: run the CI-prescribed four-directory command, then `deployment_acceptance` before and after.

**Hand-offs that stay with the owner** (deployment.md p. 6 and ADR-285): restarting `com.spa.mission_control`/`mission_server` after delivery, and the unload and delete actions listed in the ADR.

---

## 8. Risks

1. **Import cycle.** `mission_control` → `company_truth` → `director_report`. Keep `company_truth` free of `director_report` imports and pass `rep` in.
2. **Heavy host probes in `build()` every 300 s.** `session_state` runs `ps -p` once per session. Cap it at the last 50 sessions, which bounds runtime.
3. **Copy deck drift.** The `test_mission_ui_static` parity test locks `i18n.js` to the deck's keys.
4. **Prod-only decisions group.** It needs the prod tracker read, which `_cards(inp.repo)` already does. Never write.
5. **ADR numbers.** 567 and 568 may collide with in-flight cycles #778/#779. Re-allocate at landing (ADR draft, "Number hygiene").
