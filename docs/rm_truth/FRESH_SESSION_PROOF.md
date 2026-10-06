# FRESH SESSION PROOF — 30 вопросов из канона (только чтение)

**Сессия:** новая, без контекста · **время замера:** 2026-10-06 ~16:58–17:05 UTC.

**Откуда брались ответы:**
- Зеркало `~/Documents/SPA_mirror`: HEAD `7228b19de`, отстаёт от origin на 1 коммит. Поэтому весь канон читался с **origin/main `688f2c4b9`** (2026-10-06 18:56 +0200, «RM-TRUTH-01 Wave 2»). Для этого `git archive` распакован в scratchpad, в рабочие деревья ничего не писалось.
- Живое состояние — `~/Documents/SPA_Claude/data` (только чтение; sqlite открывался с `mode=ro`) и живой `docs/SYSTEM_BRIEFING.md` (auto 2026-10-06 16:40 UTC).
- Память компании — CLI `spa_core.studio_os.memory assemble`, индекс в scratchpad (`SPA_MEMORY_INDEX`).
- Сайт и публичный API — проверены одним GET-запросом.

**Как помечена уверенность:**
- **MEASURED** — сам прочитал или посчитал из живого артефакта.
- **DERIVED** — взято из канонического документа или ADR, сам не перемерял.
- **UNKNOWN** — канон не отвечает.

---

### 1. Какие три домена у владельца?
Термин «домены владельца» в каноне означает две разные тройки:
- **Три предмета, которые решает только владелец** (ADR-285, `CLAUDE.md`):
  1. движение реальных денег;
  2. публичные числа доходности, названия тиров, юридические формулировки;
  3. необратимые действия.
- **Три домена кокпита владельца:** CAPITAL · STUDIO OS · EARN DEFI PRODUCT. Так устроены ADR-592 §6 и `docs/rm_truth/MASTER_CURRENT_STATE_MAP.md` §1–3.

Источник: `CLAUDE.md` (origin 688f2c4b9); ADR-285; ADR-592 (2026-10-05/06). **DERIVED.** Канон не говорит, какая из двух троек имелась в виду.

### 2. Что сейчас работает в DeFi?
Три бумажных портфеля по $100k, реального капитала $0:
- **Conservative** — кредитование стейблкоинов под RiskPolicy v1.0. Движок `cycle_runner` / `com.spa.daily_cycle`. Мандат `conservative-lending-v1`. NAV $101 538.01, 5 позиций, кэш $5 000, решение дня HOLD.
- **Balanced** — Pendle PT с фиксированной ставкой до погашения плюс плавающее кредитование. Движок `hy_cycle`, мандат `balanced-fixed-carry-v1`.
- **Aggressive** — СИМУЛИРОВАННЫЙ луп sUSDe/PYUSD. Движок `lp_cycle`, мандат `aggressive-susde-loop-v1`.

Над ними ежечасно работает советательный `defi_engine` (ADR-532), денежный путь он не трогает. Все три пакета: work RUNNING, data HEALTHY, режим PAPER_ONLY. Balanced и Aggressive: live REFUSED.

Источник: `data/defi_engine/status.json` (generated 2026-10-06T16:04:19Z); ADR-533 и ADR-548; `docs/ROADMAP.md` п. 3. **MEASURED.**

### 3. Сколько лет каждой бумажной книге (evidenced дни / валидные периоды)?
- **Conservative:** 105 валидных периодов, с 2026-06-22 по 2026-10-06, состояние REPORTABLE, наблюдённая просадка −0.0393 %.
- **Balanced:** 5 валидных периодов (2026-10-02…10-06), состояние ACCUMULATING, порог отчётности 30 периодов. 39 строк прежнего эксперимента сохранены, но в счёт не идут.
- **Aggressive:** 5 периодов (2026-10-02…10-06), ACCUMULATING, 39 прежних строк сохранены.
- **Справочно, Trading Lab** (forward-paper): 1D-кандидаты — 5 баров, 4h — 34 бара.
- **Справочно, USYC:** 0 из 30 forward-периодов.

Источник: `data/defi_engine/status.json` → `packages.*.history` (16:04Z); брифинг: «105/30 evidenced». **MEASURED.**

### 4. Какое сейчас публичное соответствие продукта (публичные профили)?
- **Conservative** = главная evidenced-книга (`cycle_runner`, якорь 2026-06-22). Решение владельца 2026-07-11 22:30, задним числом оформлено ADR-593.
- **Balanced** = `hy_cycle` → `hy_paper_trading.json`.
- **Aggressive** = `lp_cycle` → `lp_paper_trading.json`.
- Старые имена Preserve / Core / Max Yield заменены 2026-07-11 (ADR-OWN-2026-07-owner-decisions-batch). Их адреса — безвредные noindex-редиректы.
- Цифры 6/12/20 % — только исследовательские ЦЕЛИ (TARGET, ADR-548 п. 6a), а не ожидаемая и не реализованная доходность.

Источник: `docs/rm_truth/P1_profile_lineage.md` §1 (замер 2026-10-05); ADR-593 (2026-10-06). **DERIVED.**

### 5. Чем публичные профили отличаются от внутренних книг?
Профиль — это имя и витрина: имя тира, TARGET-полоса из `tier_bands.json`, число на полке `site_numbers.json`. Книга — это движок со своим мандатом, файлом, экспериментом и часами (`experiment_id`, `valid_periods`). Соответствие не один к одному:
- Под ярлыком «Conservative» на полке живёт ВТОРОЕ число: **3.7 % из бэктеста** (`tier1_packages.json`, смесь s61/s27/s62/s77), и подписано оно `kind:"замер"`. Это дефект R3, предмет №2.
- Внутри файла `paper_evidence.json` строки помечены `S7`, хотя книга работает с мандатом `conservative-lending-v1`.
- Мёртвый `tier_paper_rollup.py` зовёт Balanced/Aggressive именами стратегий aggressive_lab.
- Aggressive Lab — отдельная исследовательская система, не книга Aggressive.
- Balanced и Aggressive вне трека go-live, для live «refused».

Источник: P1 §1–2 (2026-10-05); origin `landing/src/data/site_numbers.json` (measured_at 2026-10-01) → `packages.conservative.apy = 3.7, kind "замер"`. **DERIVED + MEASURED** (полка).

### 6. Что сейчас представляет собой Trading Lab?
SPA Trading Research Engine v0:
- код `spa_core/trading_research/`, агент `com.spa.trading_research`, запуск каждые 15 мин;
- 138 BTC-кандидатов на 1h / 4h / 1D;
- стадии: FORWARD_PAPER 5, REJECTED 133, чемпионов 0;
- 559 тиков, неудачных 0;
- режим `PAPER_RESEARCH_ONLY`, `live_capital_usd 0`;
- evidence `verified`, разрывов цепочки 0.

Источник: `data/trading_research/status.json` (generated 2026-10-06T16:56Z) + `evidence.db` (ro). **MEASURED.**

### 7. Откуда он взялся (решение)?
- **ADR-525** (Trading Research Engine v0, директива владельца). Forward-paper идёт с 2026-09-30T21:22:52Z.
- **ADR-590** (2026-10-06) объявил его ЕДИНСТВЕННОЙ активной линией Trading Lab.

Источник: `docs/decisions/INDEX.md` (ADR-590); `docs/rm_truth/C1_trading_canon.md` §2; `docs/ROADMAP.md`. **DERIVED.**

### 8. Какой сейчас BTC-сигнал?
Forward-набор: **4 LONG / 1 FLAT** по последней цели каждого кандидата.

| Кандидат | Бар | BTC close | Цель |
|---|---|---|---|
| supertrend 1D | 2026-10-06 00:00Z | 85 766.87 | LONG |
| supertrend_and_ma 1D | 2026-10-06 00:00Z | 85 766.87 | LONG |
| donchian 1D | 2026-10-06 00:00Z | 85 766.87 | LONG |
| supertrend 4h | 2026-10-06 16:00Z | 85 720.65 | LONG |
| donchian 4h | 2026-10-06 16:00Z | 85 720.65 | FLAT |

Оговорки:
- Три 1D-кандидата идут одним путём, то есть фактически это 3 независимые ставки, а не 5.
- Это исследовательский бумажный сигнал, а не торговое указание.
- Отдельная BTC-линия earn-defi — другой продукт, в Lab не суммируется (ADR-590).

Источник: `data/trading_research/evidence.db` (`observations`, последний `target`). **MEASURED** (Q8–Q10 — 2026-10-06 ~17:00Z).

### 9. Сколько forward-наблюдений?
- Реальных строк forward-набора — **83**: 3 кандидата 1D × 5 + 2 кандидата 4h × 34.
- Всего наблюдений по всем 138 цепочкам — 8 142. Опозданий 0, пропущенных баров 0.
- `status.json` печатает `forward_bars` 6 и 35. Это известный дефект D1: +1 синтетическая точка, ADR-580 C7, на 2026-10-06 не исправлен.
- Закрытых сделок у forward-пятёрки на 10-05 было 0 (C1). Сегодня я это не перемерял.

Источник: `evidence.db` + `status.json`; C1 §1. **MEASURED.**

### 10. Сбрасывались ли часы?
- **Trading Lab — НЕТ.** У всех 138 кандидатов одна отметка `registered_at_ms`. 559 тиков идут подряд, ok=0 нет ни у одного. После регистрации нет ни одного lifecycle-события.
- **Conservative — нет.** 105 дней от якоря 2026-06-22.
- **Balanced и Aggressive — да, дважды, оба раза осознанно:**
  - 2026-08-24 — чистый перезапуск $100k с одобрения владельца (ADR-125);
  - 2026-10-02 — новые версии экспериментов (ADR-531/533). Старые строки закрыты как `*-legacy-lending` и сохранены, не удалены.

Оговорка C1 D6: цепочки не привязаны к внешнему якорю, поэтому подмена всего файла старой копией прошла бы `verify()`. Это пробел в доказательстве, а не сброс.

Источник: `evidence.db`; `hy_/lp_paper_trading.json` → `experiments`; P1 §0; C1 §1. **MEASURED** (Lab, книги) + **DERIVED** (причины).

### 11. Что делает Sherlock?
Sherlock — роль `head_of_research` (Head of Research), ADR-560/564. Полномочие одно: PAPER_ADMISSION.
- Детерминированными гейтами допускает кандидата на бумагу (симулированный капитал), держит его или отклоняет: evidence bundles, роли контрагентов, Paper Admission v2 на 20 гейтов, UNKNOWN закрывает гейт.
- Не вправе: распределять капитал, менять политику Oracle, двигать деньги.

Сегодня (07:05Z): `evidence_ready 1`, `paper_active 1`, `cio_eligible 0`, `counterparty_unknown 66`. Главные блокеры — `fees_measured` / `net_return_computable` / `paper_accounting_feasible` (по 72).

Источник: `architecture/roles.json`; `data/research_factory/status.json` → `sherlock`. **MEASURED + DERIVED.**

### 12. Какой статус у USYC?
**PAPER_ACTIVE**, forward-периодов **0 из 30**.
- Базовая ставка 3.41 % APY — MEASURED, но из одного агрегатора, DefiLlama, второго независимого источника нет.
- Не названы обязательные роли контрагента: custodian, legal_entity.
- Комиссии только DOCUMENTED, не MEASURED.
- Реального капитала $0.

Источник: `data/research_factory/status.json` (generated 2026-10-06T07:05:05Z), candidate `3e20c5e906f2f728e378`. **MEASURED.**

### 13. Что делает Oracle?
Oracle — `chief_investment_officer`. До 2026-10-04 назывался «Штирлиц», ADR-554.
- Даёт СОВЕТАТЕЛЬНУЮ межрукавную бумажную рекомендацию и пишет неизменяемый ledger. Сам ничего не исполняет, полномочий `NONE`.
- Сегодня: `stance INSUFFICIENT_EVIDENCE`, `recommended_weights {}`, confidence LOW.
- Подходит только 1 зрелый рукав — `defi_conservative`; для MEDIUM нужно ≥2. Balanced/Aggressive — IMMATURE (5/30). Basis и trading_research — observe-only.
- В ledger 3 записи.

Источник: `data/investment_cio/latest.json` (generated 2026-10-06T07:30:05Z), `ledger.jsonl`; `architecture/roles.json`. **MEASURED.**

### 14. Что CIO-eligible и сколько?
- В Research Factory статус `CIO_ELIGIBLE` у **0** кандидатов. Знаменатели: обнаружено 90, `paper_active` 1, observe_only 5.
- У Oracle «годным зрелым рукавом» считается **1** — `defi_conservative`, но его вес обрезан потолком 0.5, и рекомендация пустая.

Источник: `research_factory/status.json` → `denominators` (07:05Z); `investment_cio/latest.json` → `rationale`. **MEASURED.**

### 15. Каково общее здоровье Studio OS?
STUDIO_OS_HEALTH = **WARN**.
- Агенты: 87 OK / 5 WARN / 0 CRIT из 92 (snapshot agent_health 16:40Z).
- System health: WARNING, OK 34 / WARN 12 / CRIT 0, свежесть 10 ч.
- Флот: DRIFT — 5 выведенных из флота, но всё ещё установленных; 8 plist без агента.

Источник: живой `docs/SYSTEM_BRIEFING.md` (2026-10-06 16:40 UTC) + `data/agent_health.json` (18:40 local). **MEASURED.**

### 16. Почему готовность инвестиций может отличаться от здоровья Studio?
Это разные области с разными канонами, и общего «зелёного» нет (ADR-580 C3):
- INVESTMENT_ENGINE_READINESS = `execution_readiness` ∧ `owner_blockers`. Сейчас **NOT_READY**:
  - `ready_for_live=false`;
  - нет custody/MPC;
  - внешний аудит не проведён;
  - режим исполнения выключен;
  - open-блокеров 3 — custody, audit, legal.
- STUDIO_OS_HEALTH = `agent_health`. Это флот, к деньгам отношения не имеет.
- «29/29» — инвентарь критериев, а не готовность.

Флот может быть в норме при полной неготовности к деньгам, и наоборот.

Источник: ADR-580 §C3; брифинг «Готовность по областям» (16:40Z). **MEASURED + DERIVED.**

### 17. Какие агенты сломаны?
По `agent_health` (16:40Z):
- `com.spa.resource_guard` — exit 1;
- `com.spa.swarm_health` — exit 1;
- `digest_weekly`, `tier1_digest`, `weekly_backup` — retired_but_loaded: числятся выведенными из флота, но загружены.

Не загружены, хотя ожидаются: `governance_watcher`, `bts-feed`, `bts-monitor`.

Работают на старом коде (долгожители, перезапуск — решение владельца):
- `apiserver` — 2.4 суток;
- `rtmr_sense` — 6.4 суток.

Вне флота SPA, по замеру 2026-10-05:
- LOGOS desk — зомби, рынков 0 с 2026-07-29 (C1);
- `mission_tick` мёртв с 09-30 (MASTER_MAP §3);
- earn-defi в состоянии INCIDENT с 2026-09-19.

Источник: брифинг (16:40Z); C1 (2026-10-05). **MEASURED** (флот) / **DERIVED** (вне флота).

### 18. Какие Problems открыты?
В `data/problems.json` (generated 2026-10-06T16:40:12Z) 7 записей, **ни у одной нет RCA**:

| Статус | Запись | Повторов |
|---|---|---|
| OPEN | `com.spa.resource_guard` exit_nonzero:1 | ×8 |
| OPEN | `com.spa.swarm_health` exit_nonzero:1 | ×8 |
| OPEN | `fleet` retired_but_loaded | ×8 |
| OPEN | `system_health` domains_degraded | ×8 |
| INCIDENT | `com.spa.telegram_health` exit_nonzero:2 | ×1 |
| MITIGATED | `com.spa.site_freshness` exit_nonzero:1 | — |
| MITIGATED | `site_freshness` publication_behind | — |

Хранилище Problems появилось только с Wave 0 (ADR-580 C6), история начинается 2026-10-06 09:39Z.

**MEASURED.**

### 19. Какие решения ждут владельца?
На origin/main 688f2c4b9 со статусом `needs-owner` **12 карточек**: 11 `own-`/`owner-decision-` и 1 `inbox-`. Брифинг считает «ждёт владельца 11».
- Оптимум проигрывает решению «ничего не делать» 6 раз.
- Диск Mac Mini забит под ноль. Кнопок нет: в карточке несколько вопросов.
- Два тира у одного протокола.
- Telegram-канал для earn-defi.
- Перепроверка перед сделкой: два числа — свежесть ставок и срок жизни решения.
- Потолок Base в трёх местах.
- 5 % кэша в двух местах.
- «Продержится ли выгода».
- Стоимость перекладки ×134.
- Закрыть три черновых PR.
- Защита от качелей сравнивает не то.
- inbox: очередь показывает 20 из 23.

Ни у одной карточки нет поля `subject:`. По ADR-580 C5 тема у всех = UNKNOWN, и разбирать их сначала обязан агент.

Брифинг отдельно отмечает: 3 карточки origin не доходят до прод-дерева, и 1 карточка — без кнопок.

Источник: `git grep "^status: needs-owner" origin/main -- nimbalyst-local/tracker`; брифинг (16:40Z). **MEASURED.**

### 20. Над чем работает Claude?
- **Интерактивная сессия, эпик RM-TRUTH-01** (ROADMAP п. 10, «in progress»): Wave 0 доставлена `96a935fda` (10-06 11:29 +0200), Wave 2 — `688f2c4b9` (18:56 +0200: ADR-590/591/592/593).
- **Автономный цикл:** последняя запись журнала объявлений — цикл **#788** (2026-10-06T16:38:44Z), заказ G103 п. 1, прибор `site_source_registry_truth`, только чтение.

Источник: `data/session_changes.jsonl` (mtime 18:38 local); `git log origin/main`; `docs/ROADMAP.md`. **MEASURED.**

### 21. Какой сейчас роадмап?
Единственный роадмап — `docs/ROADMAP.md`, последнее подтверждение владельца 2026-10-01.
- Закрыто: п. 1–9 — Memory v1, DeFi audit, DeFi vNext, Build Loop, Mission Control v1, Oracle, RM-LIVE-01, RM-EXPAND-01, RM-EVIDENCE-01.
- В работе: **п. 10 RM-TRUTH-01** — правда компании и восстановление Director OS.
- Дальше: п. 11 — традиционные рынки, волатильность/опционы.
- Остальные `*ROADMAP*.md` — SUPERSEDED (ADR-527).

Источник: origin `docs/ROADMAP.md` (688f2c4b9). **DERIVED.**

### 22. Что показывает публичный сайт?
Главная earn-defi.com, GET 2026-10-06 ~17:00Z:
- в статике: APY «~4.9%», 100 дней, «Go-live progress 29/29»;
- после загрузки JS заменяет APY значением `ytd_apy_pct` из `/api/health-public` = 4.2973 → «4.3%»;
- max drawdown — «—» (`max_drawdown_pct: null`).

Полка `site_numbers.json` (measured_at = published_at = 2026-10-01):
- headline APY 4.9165 % (печатается вниз до 4.9, ADR-563);
- NAV $101 476.26;
- просадка −0.0393 %;
- 100 evidenced дней;
- `packages.conservative` 3.7 % — бэктест с меткой «замер»;
- Balanced/Aggressive — `null` («идёт paper-тест»).

Источник: `curl https://earn-defi.com/`; `curl https://api.earn-defi.com/api/health-public` (generated 17:01:17Z); origin `landing/src/data/site_numbers.json`. **MEASURED.**

### 23. Откуда берётся APY сайта?
Канон:
1. `equity_curve_daily.json` (evidenced-бары).
2. `generate_track_snapshot.py` → `track_snapshot.json` → `paper_apy_pct`. Это сложный процент от якоря: `(NAV/NAV_якоря)^(365/дни) − 1`.
3. `build_site_numbers.py` → недельная полка `site_numbers.json`.
4. `lib/site_numbers.js`.

Но на главной JS перезаписывает это число **однодневной** аннуализированной ставкой `ytd_apy_pct` из `/api/health-public` — дефект HIGH из MASTER_MAP §2. На 17:00Z он всё ещё жив: 4.9 → 4.3. Wave 0 заморозила поля, которые читает сайт, до переключения владельцем (предмет №2).

Источник: `.claude/rules/site-numbers.md`; полка `_sources`; MASTER_MAP §2/§5; живой HTML. **MEASURED + DERIVED.**

### 24. Свежий ли сайт?
По его собственному недельному такту — да:
- `site_freshness_report.json` (2026-10-06T11:02:50Z): `ok:true`, `publisher_stuck:false`, `publish_lag_days 0`;
- полка от 2026-10-01, следующая публикация 2026-10-12;
- PUBLICATION_HEALTH ✅ OK (брифинг 16:40Z).

Но по содержанию сайт отстаёт от живых данных на 5 дней:
- 100 дней против 105;
- $101 476 против $101 538;
- `site_as_of_age_h` 131.

Поломка публикатора с 10-02 (`ModuleNotFoundError`) исправлена в Wave 0 (коммит `96a935fda`). Публикацию после неё в живых данных я не наблюдал.

**MEASURED.**

### 25. Что входит в бэкап?
- **Ежедневный архив** `data/backups/spa_state_YYYY-MM-DD.tar.gz` (`scripts/daily_backup.py`, 05:30): MUST_HAVE (`golive_status`, `equity_curve_daily`, `paper_evidence_history`, `current_positions`, `track.db`) плюс sqlite-копии.
- Сегодняшний архив (2026-10-06 05:30) содержит `trading_research/evidence.db`, но **НЕ** содержит `market.db`, `investment_cio/`, `research_factory/` и `capital_shadow/`.
- В код origin эти пункты добавлены Wave 0 (ADR-580 C10), коммит в 09:29Z — уже ПОСЛЕ сегодняшнего прогона. Попадут ли они в архив 10-07, НЕ ИЗМЕРЕНО. Прод-копия скрипта эти имена уже содержит.
- **«Offsite» копия** — `~/spa_offsite_backups/spa_state_*.tar.gz`, ~2.5 МБ, на том же диске.
- Restore drill и fleet drill 2026-10-06 — passed.

Источник: `tar -tzf` последнего архива; origin `scripts/daily_backup.py`; `data/resilience_status.json` (16:56Z). **MEASURED.**

### 26. Реален ли DR вне хоста?
**НЕТ.**
- `resilience_status.json`: `offsite.is_real_remote:false`, `status SAME_HOST`, `overall SAME_HOST`. Запись: «dest is the LOCAL stand-in (no real remote configured) [owner-flagged]».
- Потеря Mac mini означает потерю и бэкапа.
- Выбор внешнего DR-адреса — за владельцем (ADR-580).

Источник: `data/resilience_status.json` (2026-10-06T16:56:11Z); брифинг. **MEASURED.**

### 27. Что стало с дублирующими BTC-движками?
ADR-590 (2026-10-06):

| Движок | Решение |
|---|---|
| SPA Trading Research Engine v0 | **CANONICAL_ACTIVE** |
| earn-defi BTC Signal Engine | **SEPARATE_PRODUCT**: не заменён, в Lab не суммируется, показывается только внешней строкой с `system_mode`. Состояние INCIDENT с 2026-09-19, снимает его владелец |
| `research/btc_cycle` (ADR-102) | SUPERSEDED_HISTORY, хранится как доказательство |
| SPA `btc_nav` (ADR-118, ни разу не запускался) | SUPERSEDED_HISTORY |
| LOGOS desk | BROKEN-зомби, вне Lab. KILL или REPAIR — решение владельца |
| BTC/ETH-рукава strategy_lab | LEGACY_REFERENCE |

Два разных «v0.3» требуют пространств имён: `btc_cycle:v0.3` (отклонённый вариант) и `earn-defi:btc_engine@0.3` (живой конфиг).

Источник: INDEX ADR-590; `docs/rm_truth/C1_trading_canon.md` §2 (замер 2026-10-05). **DERIVED.**

### 28. Какой кокпит канонический?
**Mission Control** (ADR-552, развит на месте как Director OS v2 по ADR-592 от 2026-10-06):
- локально `127.0.0.1:8790`;
- с телефона `mc.earn-defi.com` → `:8792` за Cloudflare Access;
- только чтение, Company Truth вычисляется при чтении.

Остальные кокпиты — только SUPERSEDED-представления: Director OS `:8788`, `studio_shell` `:8778`, dashboard `:8767` (раздаёт репозиторий). Их выгрузка — действие владельца.

Отдельно остаются: Telegram-текст `director_report` (`/report`, `/needs`) и доска Nimbalyst.

Источник: ADR-592; ROADMAP п. 5. **DERIVED.**

### 29. Что стало с MemPalace?
**Не внедрён.**
- ADR-527 (2026-10-01): оценён — «заимствовать идеи, не зависимость».
- ADR-591 (2026-10-05, решение HYBRID_BORROW_COMPONENTS): stdlib FTS5-память остаётся единственным исполняемым слоем.
- MemPalace проиграл по всем измеренным осям: top-5 12/51 против 31/51, русский язык, воспроизводимость восстановления (34 мин против 5 с), 81 зависимость против 0 — нарушает инвариант #4.
- Взяты две идеи: пересборка при изменении источника (`ensure-fresh`) и слой сущностей/алиасов.

Источник: ADR-591; ROADMAP «Closed epics». **DERIVED.** CLI памяти на коде origin нашёл ADR-591 первым источником, SUFFICIENT.

### 30. Что действительно нужно от владельца?
Только то, что попадает в три предмета (ADR-580 «Что остаётся владельцу», ADR-592, ADR-590).

**№1 — деньги:**
- любой пилот реальными деньгами: custody/MPC, аудит, legal — 3 открытых `owner_blockers`;
- подключение `counterparty_registry` к Capital Shadow;
- пороги перепроверки перед сделкой (карточка в очереди);
- любая переписка истории главного трека, включая own-32.

**№2 — публичное:**
- формулировка «Go-live progress 29/29»;
- бэктест 3.7 % с меткой «замер»;
- переключение главной с однодневной ставки 4.3 % на канон;
- «Join early-access»;
- монотонная лестница REALIZED и вторая лестница TARGET;
- ручные APY протоколов.

**№3 — необратимое и внешнее:**
- ротация или отключение токена OpenClaw (INC-2, токен скомпрометирован);
- выбор внешнего DR-адреса;
- снятие INCIDENT earn-defi;
- KILL или REPAIR для LOGOS;
- удаление Director OS, его билда на 4.8 ГБ и worktree.

**Действия над прод-агентами** (deployment.md п. 6):
- выгрузить `digest_weekly`, `tier1_digest`, `weekly_backup`, `:8767`, director_server/build;
- перезапустить `apiserver` и `rtmr_sense`.

Плюс ответить на 12 карточек очереди — но у всех тема не объявлена, и по C5 агент сначала обязан отсеять дефекты очереди. По замеру 10-05 из 12 карточек 7 были такими дефектами.

Источник: ADR-580 §«Что остаётся владельцу»; ADR-592; брифинг (16:40Z); MASTER_MAP §3. **DERIVED.**

---

## Итог: на что канон ответить НЕ смог, пропуски и противоречия

**UNKNOWN:** ни один из 30 вопросов полностью неотвеченным не остался. Частично UNKNOWN:
- **Q1** — термин «домены владельца» в каноне означает две разные тройки (ADR-285 и ADR-592).
- **Q9** — закрытые сделки forward-пятёрки сегодня не перемерены (на 10-05 их было 0).
- **Q24** — после починки публикатора, которая уже на origin, новая публикация не наблюдалась.
- **Q25** — войдут ли ledger'ы Oracle, Research Factory, Capital Shadow и `market.db` в архив 10-07: не измерено, сегодняшний архив их НЕ содержит.

**Противоречия и устаревшие источники:**
1. `docs/STATE.md` (origin) — «Оперативный снимок» датирован **2026-08-27**: «60/30» и «65/30» дней, другие позиции. В разделе «Текущий фокус» нет ни RM-TRUTH-01, ни Oracle, ни Trading Lab. Новой сессии STATE.md на эти вопросы почти не отвечает. Ответили `docs/rm_truth/`, ROADMAP, ADR и живой брифинг.
2. Шапка `CLAUDE.md`: «трек 100 evidenced дней», замер 2026-10-01. Живые данные: 105.
3. Sherlock: ROADMAP п. 9 — «30 of 43 usable», MASTER_MAP §1 — «43/56 фактов usable». Из живого `research_factory/status.json` ни одно из этих чисел не воспроизводится.
4. Очередь владельца: брифинг — 11, `needs-owner` на origin — 12 (одна из них `inbox-`). Ни у одной карточки нет `subject:`, обещанного C5.
5. Следующая публикация полки: MASTER_MAP (10-05) — 2026-10-08, живой `site_freshness_report` — 2026-10-12.
6. Trading Lab `status.json` `forward_bars` (6 и 35) против реальных строк (5 и 34) — дефект D1 по-прежнему жив.
7. Главная сайта: статика 4.9 %, после JS — 4.3 %. Дефект INC «однодневная ставка подменяет годовую» на 2026-10-06 17:00Z не устранён.
8. Книги Balanced/Aggressive несут `start_date: 2026-06-22`, хотя ряды начинаются 2026-08-24, а текущий эксперимент — 2026-10-02.
9. Память компании:
   - на коде зеркала (7228b19de, без ADR-591) запрос про MemPalace дал **PARTIAL** без единого попадания в ADR-527;
   - на коде origin запросы про кокпит и BTC-дубли вернули SUFFICIENT, но ADR-592 и ADR-590 в топ-3 не попали. Это ложный SUFFICIENT по словам, а не по предмету.
10. Зеркало отстаёт от origin на 1 коммит. Брифинг говорит «читать из зеркала», но Wave 2 (ADR-590…593) есть только на origin.
11. Вне флота SPA (LOGOS, `mission_tick`, earn-defi INCIDENT, OpenClaw) свежего замера нет — только срезы RM-TRUTH от 2026-10-05.
