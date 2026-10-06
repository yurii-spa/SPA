# RM-TRUTH-01 · Master Current-State Map (Phase 1, forensic, read-only)

> **Статус:** ПРИНЯТ после независимого ревью `REVIEW_1.md` (APPROVE_WITH_AMENDMENTS; поправки внесены ниже) — контракты заморожены в ADR-580 · замер 2026-10-05 08:00–08:45Z · origin `b36acda46`
> Регистр: `MASTER_REGISTER.json` (141 компонент · 26 кластеров дублей · 56 обещаний · 22 паспорта
> экспериментов · 19 строк стратегий · 27 публичных полей · 12 дефектов флота · 17 гейтов владельца).
> Доказательства по каждой строке — в срезах `A1…A6_*.md` (каждое утверждение с путём / коммитом / командой).
> Этот документ — НЕ новый источник правды; он карта, где лежит правда и где она расходится.

Инварианты аудита: REAL CAPITAL = $0 · NO LIVE EXECUTION · ни одна история paper не сброшена этим аудитом ·
UNKNOWN_PURPOSE ≠ obsolete.

---

## 0. Главный вывод в пяти строках

1. **Почти всё, что владелец просил, построено — часто по 2–7 раз.** Кокпит владельца строился 7 раз
   (4 из них 20.09–03.10), BTC-движок — 4 раза, «флот» считают 7 разных чисел (83…107), readiness-гейтов ~12.
2. **Ломается не код, а проводка правды:** одно и то же значение имеет 2–5 активных неназванных
   источника (флот, очередь владельца, APY, тиры, BTC-сигнал, «READY»).
3. **Денежные истории целы.** Главный трек 104 evidenced дня без сброса; Trading Research Engine
   428/428 тиков без сброса часов; сбросы Balanced/Aggressive — оба осознанные и задокументированы.
4. **Цикл надёжности обрывается на «алерте».** PROBLEM и RCA не существуют для ops-отказов;
   владелец остаётся процессором алертов (14+14 флапов, 7 «bootstrap failed» за 35 мин).
5. **Публичная/владельческая APY-картина неоднородна по типу числа:** бэктест подписан «замер»,
   однодневная ставка подменяет годовую в браузере, `books_summary` показывает инвертированную лестницу.

---

## 1. CAPITAL

| Контур | Что есть (замер) | Канон | Здоровье | Главный дефект |
|---|---|---|---|---|
| **DeFi Yield — Conservative** (главный трек) | 104 evidenced дня с 2026-06-22, equity $101 525.98, худшая просадка −0.0393% | `data/equity_curve_daily.json` (+`current_positions`, `trades`), writer `cycle_runner` | RUNNING | `paper_evidence.json` покрывает 76 из 104 evidenced дней (12 из 88 строк — до якоря), дыры 06-22..29 и 08-03..22 (причина НЕ ИЗМЕРЕНА); 17 дат расходятся до $55.82 (два писателя одного дня, own-32); все строки помечены `S7` вместо `conservative-lending-v1` |
| **DeFi — Balanced / Aggressive** | книги $100k, эксперименты v1 с 2026-10-02 (ADR-533), 4 валидных периода | `data/hy_paper_trading.json`, `data/lp_paper_trading.json` | RUNNING, незрелые | `start_date: 2026-06-22` в книгах вводит в заблуждение (ряды с 08-24); «realized» Aggressive исключает день 1 (+0.0685% vs −0.108%) |
| **Indicator & Directional Trading Lab** | ADR-525 Trading Research Engine v0: 138 кандидатов BTC (1h/4h/1D), 5 в forward-paper, 133 отклонены (122 — по DD < −55%), чемпионов 0 | `data/trading_research/evidence.db` (append-only триггеры, хэш-цепи) | RUNNING 428/428, late=0, gap=0, без сброса | D1 `forward_bars` +1 (синтетическая точка); D2 бэктест перезаписывается ежедневно и OOS поглощает forward-бары; D3 `market.db` без бэкапа |
| **BTC (прочие)** | `research/btc_cycle` (ADR-102, чемпион v0.1 утерян — код не передан) · SPA `btc_nav` (ADR-118, никогда не запускался) · earn-defi BTC Signal Engine (отдельный репо, live paper +6.5%, **INCIDENT с 09-19** ложный KC-1, фикс есть, снятие — владелец) · LOGOS desk (зомби, рынков 0 с 07-29) | разные; **канон BTC-сигнала НЕ назван ни одним ADR** | смешанное | два «v0.3» означают разное |
| **Market-neutral / Basis / Funding** | 42 кандидата FUNDING_CAPTURE: 40 DATA_INSUFFICIENT, 2 SUPERSEDED | `data/research_factory/status.json` | BLOCKED на fee-evidence (подтверждено) | `susde_dn` «forward» = реплей бэктеста (61/62 одинаковых дневных доходности), `swarm/blend_forward` его считает и не метит stale |
| **Treasury / RWA / Cash** | USYC PAPER_ACTIVE (REFERENCE_TRACK), 0/30 forward периодов; OUSG/USDY DATA_INSUFFICIENT; BUIDL COUNTERPARTY_UNKNOWN; кэш $5 000 под 0% | `data/research_factory/ledger.jsonl` | как в RM-EVIDENCE | запись USYC сама себе противоречит по custodian/legal entity |
| **Sherlock** | 43/56 фактов usable (13 без независимого ревью) | registry facts + content-hash reviews | KEEP | — (регрессии нет) |
| **Oracle (CIO)** | 2 записи в ledger, INSUFFICIENT_EVIDENCE, веса {} | `data/investment_cio/ledger.jsonl` | RUNNING | ADR-554 всё ещё зовёт «Штирлиц», `roles.json` — Oracle |
| **Capital Shadow (RM-LIVE-01)** | DeFi-рукава BLOCKED, прочие NOT_READY | capital_shadow ledger | REPAIR | гейт контрагента — захардкоженное «нет» (`readiness.py:195`), не читает `counterparty_registry` |

Подтверждено: PAPER_ACTIVE Research Factory **не** используется как системный paper-счётчик
(читают только CIO research view и Mission Control с меткой research).

## 2. EARN DEFI PRODUCT

**Профили.** Preserve/Core/Max Yield (создано 2026-06-19, `0d3139e49`, Core = флагман 10% target)
**заменены владельцем 2026-07-11** на Conservative/Balanced/Aggressive (ADR-OWN-2026-07-owner-decisions-batch,
исполнено `c1207ac26`). Остатки старых имён: alt_en-метки, legacy-id, редиректы, «Core» в
`tier_paper_rollup.py`. Решение «Conservative = evidenced book» — только в сообщении коммита `6ca6cf282`
(ADR нет). Цифры 6/12/20% — **только research TARGET** (ADR-548 п. 6a); **принятого решения о
монотонной лестнице REALIZED/OBSERVED нет нигде.**

**Корень APY-инверсии** (три механизма, все доказаны):
1. cost-model v1 начислял газ на ежедневный ресайз (ADR-530 P0-1) → недельные полки сайта
   09-13…09-27 инвертированы; с сайта сняты 10-01 (ADR-531).
2. **Сейчас инвертировано у владельца:** `spa_core/reporting/books_summary.py` → `/api/live/books` →
   `/admin/portfolio-summary` и Telegram «📚 Пакеты»: C 4.15% / B −4.36% / A 1.36% — **и это публично**: `/api/live/books` без авторизации, `/admin/portfolio-summary` отдаёт 200 всем (ревью) — линейная
   аннуализация + 39 искажённых v1-дней + нет 30-дневного гейта зрелости. **PRODUCT_TRUTH_INCIDENT (HIGH).**
3. Структурно: вселенная даёт ~5% gross всем трём книгам (ADR-292/125), любые издержки переворачивают порядок.

**Расхождения публичных полей (из 27 сверенных):** 4.9% → 4.2% после загрузки (однодневная ставка
«ytd annualized» из `/api/health-public`) — HIGH · Conservative 3.7 «замер» = бэктест tier1 — MEDIUM
(предмет №2) · `/packages` drawdown «realized» = бэктест · округление вверх вопреки ADR-563 ·
max DD «—» (tear_sheet заморожен с 06-30) · `/api/strategy-lab` 101 день, бейдж «Active» ·
ручные APY протоколов · «Join early-access…» (legal, предмет №2).

**Публикация сломана с 2026-10-02:** `deploy_site_snapshot.py` → `ModuleNotFoundError: spa_core`
(ленивый импорт `generate_track_snapshot.py:159`, коммиты `c673b3df3`/`1a2d79252`, класс ADR-148).
`site_freshness` кричит PUBLISHER_STUCK каждые 6 ч и **винит CF Pages — неверно**. Вердикт ревью: дефектов ДВА — (а) генератор падает на импорте; (б) сторож сравнивает сайт с ПРОД-ЛОКАЛЬНОЙ полкой (10-04, не на origin), а origin-полка (10-01, следующая 10-08) в своём такте; `deploy_site_snapshot` полку вообще не возит. Починка одного импорта опубликует `packages` 3.7→5.4 с меткой «замер» — поэтому публикация идёт ПОСЛЕ типизации (C12).

## 3. STUDIO OS

**Флот:** 91 загружено · 92 plist (+5 `.disabled`) · agent_health 89 · self_heal 88 · инсталлер 83 ·
registry 99 · manifest 107. **Семь определений «флота», ни одно не совпадает.**
- `novel_edge_rnd` CRIT — **ложный**: `classify_agent` не понимает массив `StartCalendarInterval`.
- `site_freshness` WARN — настоящий, но причина в репо (см. §2).
- `swarm_health` WARN 130/130 — норма-предупреждение, карточки нет.
- `orchestrator` exit 124 — полный pytest внутри LLM-цикла, 2/17 таймаутов.
- `weekly_backup` — **невидим всем сторожам** (числится RETIRED, но загружен; упал 10-03, архивы
  1.7/2.6 GB против 3.0–3.9 — вероятно усечены, НЕ проверено).
- `rtmr_sense` исполняет код 3.7 дня давности. `mission_tick` мёртв с 09-30 (plist вне репо).
- `:8767 dashboard` раздаёт весь прод-репо (вкл. `.git/config`) на loopback.

**Цикл надёжности:** ERROR ✅ · INCIDENT частично · RESTORE ✅ · RECURRENCE частично · **PROBLEM ❌ ·
RCA ❌** · FIX/REGRESSION частично · MONITOR/KNOWLEDGE/CLOSED частично. `findings_bridge` — единственная
машина «одна запись на причину с критерием закрытия», но не читает agent_health/system_health/self_heal/
site_freshness и шлёт находки о флоте **владельцу** (вне трёх предметов ADR-285).
5 систем выносят вердикт по флоту и сейчас расходятся (CRITICAL / WARNING / healthy / CRITICAL-с-HEALTHY-секциями).

**Очередь владельца:** origin 11 · прод/SPA-бот 12 · Director OS 6 · Mission Control 11 + ещё «4».
Причина: интейки Telegram и писатель ответов пишут в прод-дерево; переноса прод→origin нет;
**17** закрытий владельца существуют только в проде (ревью; срез давал 13). 1 карточка без кнопок (диск, «(а)(б)(в)»).
Из 12: 4 принадлежат владельцу, 1 частично, **7 — дефекты очереди** (вернуть агенту).

**Telegram — три контура, не два:** SPA-бот (решения/kill-switch книги в кэш; `/resume` только своего
стопа), Bridge-бот (без денежной власти, пишет в SPA только через `owner_remote.cli` confirm-first),
**OpenClaw** (`ai.openclaw.gateway`, назначение неизвестно; токен в открытом виде в `~/.openclaw/`
и **засвечен в транскрипте этого аудита** — ротация за владельцем). Рекомендация: KEEP_SEPARATE (ADR-521).

**Кокпиты:** Mission Control :8790 (KEEP+REPAIR, в целом честно рисует UNKNOWN) · Director OS :8788
(MERGE в MC; ADR-552 сам зовёт дублем; публикация заморожена с 09-20; гейт «107 дней» из файла 06-20;
4.8 GB билд) · studio_shell (SUPERSEDED) · :8767 (SUPERSEDED, опасен) · Nimbalyst board (KEEP).
«ADR-469 Director OS doctrine», на которую ссылаются ADR-492/552, на origin — **другой ADR**
(доктрина живёт только в off-origin worktree со статусом PROPOSED).

**Планирование:** живых хранилищ три — `docs/ROADMAP.md`, трекер (1193 карточки), `docs/decisions/`.
8 старых роадмапов помечены SUPERSEDED только в `memory_truth.json` (баннеров в файлах нет);
9 планов не помечены вовсе; `KANBAN.json` заморожен с 06-22, но кормит брифинг и GoLive-критерий.
ADR-номера: 3 места, **11 коллизий** по перемеру ревью (срез давал 16; CLAUDE.md — 5); «ADR-034» kill-switch файла не имеет.

**Память:** v1 (ADR-527) 0.744 на 39 запросах (провенанс 0.89, полнота 0.68); MemPalace 10/35 top-5
против 22/35. Дефекты v1: индекс не пересобирается (новейший ADR-551 — ADR-552…565 невидимы),
вердикт SUFFICIENT мерит покрытие слов (SUFFICIENT на ловушке про несуществующий запуск Solana),
нет `docs/adr`, MASTER_PLAN, OWNER_BACKLOG, алиасов (Oracle/Штирлиц), git first-seen.
**Решение-кандидат: HYBRID_BORROW_COMPONENTS** (не интегрировать MemPalace; чинить v1).

## 4. Readiness — объяснение «READY и CRITICAL одновременно»

Ни одно из значений не ложно — они про разные области, а брифинг печатает одно как общее:
- 29/29 = `golive_status.json` — **paper-evidence + инвентарь** (~13 проверок «файл/импорт есть»),
  нет поля `ready_for_live`, custody/site не покрыты.
- `data/execution_readiness.json` **`ready_for_live:false`** (custody/MPC, внешний аудит, режим исполнения),
  `owner_blockers.json` open 3, capital_shadow — всё BLOCKED/NOT_READY.
- Agents CRITICAL — единственный CRIT ложный (классификатор).

| Scope | Канон (существующий) | Сейчас |
|---|---|---|
| INVESTMENT_ENGINE_READINESS | `execution_readiness` ∧ `owner_blockers` (golive_status — вход) | NOT_READY |
| STUDIO_OS_HEALTH | `agent_health.json` | CRITICAL (ложный) → WARN после фикса |
| PRODUCT_DATA_HEALTH | `cycle_health.json` (evidence_vs_curve) | WARNING 17/88 |
| PUBLICATION_HEALTH | `site_freshness_report.json` | CRITICAL (publisher broken в репо) |
| OWNER_CONTROL_HEALTH | bot beacon + `owner_decision_pending` + `push_state` | DEGRADED |

## 5. Truth-Source Matrix (Phase B)

| Домен | Сущность | Канон | Писатель | Производные | Свежесть | Конфликт | Куда владельцу |
|---|---|---|---|---|---|---|---|
| CAP | определение стратегии | `spa_core/strategies/strategy_registry.py` + конфиги книг (ADR-125/533) | ADR/код | `tier_paper_rollup.json`, legacy registries, `S7` в evidence | по ADR | **да**: rollup мапит Balanced/Aggressive на aggressive_lab (противоречит ADR-125/533); `S7` | Capital › DeFi |
| CAP | доходность стратегии (paper) | `equity_curve_daily.json` / `hy_`/`lp_paper_trading.json` | cycle_runner / книги | `paper_evidence.json`, `rates_desk/equity_track.jsonl` (копия), `books_summary`, `strategy_lab_paper` engine_b/c (дубль B/C) | ежедневно | **да**: 3 разных кумулятивных (1.526/1.3893/1.3733%); evidence 17/88 | Capital › DeFi |
| CAP | paper state | те же + `current_positions.json` | cycle_runner | brief, MC | ежедневно | brief считает warmup как evidenced | Capital |
| CAP | BTC-сигнал | **НЕ НАЗВАН**: `trading_research/evidence.db` vs `earn-defi/data/earn_defi.db` | 2 движка | `/api/btc-engine`, MC | 1ч / день | **да, два активных неназванных** | Capital › BTC |
| CAP | Trading Lab | `data/trading_research/evidence.db` + `status.json` | `com.spa.trading_research` | director_report, research_factory scanner | 1ч | `forward_bars` +1 наследуется | Capital › Trading Lab |
| CAP | Oracle рекомендация | `data/investment_cio/ledger.jsonl` | investment_cio | latest.json, MC | ежедневно | имя Штирлиц/Oracle | Capital › Oracle |
| CAP | Sherlock решение | registry facts + reviews (ADR-564) | research_evidence | factory ledger, MC | по событию | нет | Capital › Sherlock |
| PROD | публичный APY | `track_snapshot.json` → `site_numbers.json` | generate_track_snapshot / build_site_numbers | `/api/health-public` (однодневная, подменяет в браузере), `/api/ssot/facts`, `books_summary` | неделя | **да**: 4.9 vs 4.2; генератор сломан с 10-02 | Product › метрики |
| PROD | профиль продукта | `tier_bands.json` (TARGET) + `constitution.json` + `site_numbers.packages` | builders | `tier1_packages.json` (BACKTEST, помечен «замер») | по ADR / неделя | **да**: тип числа | Product › профили |
| STU | здоровье агента | `agent_health.json` | agent_health | system_health, self_heal, MC, reliability | 1ч | **да, 5 вердиктов** | Studio › агенты |
| STU | инцидент | НЕТ канона: `push_state.json` (edge) + `data/incidents.json` (читает только scoring) | разные | alert_history | — | нет единой записи | Studio › инциденты |
| STU | Problem | **ОТСУТСТВУЕТ** (`reliability.py` выводит PROBLEM_CANDIDATE, не хранит) | — | — | — | — | Studio › Problems |
| STU | задача | `nimbalyst-local/tracker` на **origin** | orchestrator_queue, intake | `_BOARD.md`, MC, Bridge `/needs` | минуты | **да**: прод-дерево 494/170/47 расхождений | Studio › задачи |
| STU | пункт роадмапа | `docs/ROADMAP.md` | сессии | 8 старых роадмапов без баннера, `KANBAN.json` (кормит brief) | дни | да | Studio › роадмап |
| STU | решение владельца | tracker `owner-decision-*`/`own-*` на origin | intake/агенты/владелец | бот (прод), MC, Director OS, Bridge | минуты | **да**: 11/12/6/4; 13 закрытий только в проде | Studio › решения |
| STU | релиз | частично: `build_loop` lineage (ADR-551) | — | — | — | **UNKNOWN** — единого понятия «релиз» нет | Studio/Product › релизы |
| STU | решение памяти | `architecture/memory_truth.json` + `docs/decisions` | сессии | `data/memory/index.db` (расходник, устарел) | — | индекс отстаёт на 14 ADR | Studio › память |
| STU | состояние Telegram | `telegram_bot_capabilities.json` (маячок) + `telegram/push_state.json` | бот / push_policy | MC | 30 с | `owner_decision_pending.json` **испорчен (2041)** | Studio › владелец |

## 6. Инциденты, открытые этим аудитом

| ID | Что | Серьёзность | Статус |
|---|---|---|---|
| INC-1 | **Прод-агент `com.spa.decision_loop`** (`findings_bridge --run`) запускает G97-зонд (ADR-562, pid 63060 с 10:04:20); зонд зовёт 99 производителей в одноразовом дереве **без `SPA_DATA_DIR`/`SPA_LIVE_ROOT`** → `live_data_dir()` уводит запись в прод; `owner_decision_pending.json` получил `generated_at 2041-11-23` в 10:04:22 (agent_health перезаписал в 10:37). В плане зонда есть append-only `investment_os/outcomes.jsonl` (замер: не тронут, mtime 09:19). Ещё 5 харнессов `*_doors/*_probe` с той же дырой. Сторож проверяет «дерево одноразовое», а не «куда легла запись». Показания owner-control 08:04–08:36Z испорчены | HIGH | путь доказан кодом И процессом; фикс C8 |
| INC-2 | Токен OpenClaw-бота в открытом виде и засвечен в транскрипте | HIGH (секрет) | ротация — владелец |
| INC-3 | Публикация сайта сломана с 10-02 (`ModuleNotFoundError`) | HIGH | REPAIR |
| INC-4 | `books_summary` инвертирует лестницу у владельца | HIGH PRODUCT_TRUTH | REPAIR |
| INC-5 | DR: «offsite» на том же диске (`is_real_remote:false`); ledger'ы Oracle / Research Factory / Capital Shadow и `trading_research/market.db` не входят ни в один бэкап; `weekly_backup` невидим сторожам и, вероятно, усекает архивы | HIGH (восстановление) | C10 + выбор внешнего DR — владелец |
| INC-6 | `:8767` раздаёт репо вкл. `.git/` на loopback | MEDIUM | retire |

## 6a. Пропуски карты, найденные ревью

- **Публичный API** без своей строки правды (`/api/live/books`, `/api/health-public`, `/api/ssot/facts`, `/api/tier1/packages`).
- **Адаптеры:** 8 штук ежедневно выдают литеральные fallback-APY (напр. 14% `pendle_yt`) — против правила adapters.md (fake-fallback запрещён).
- **Kill-switch runtime-состояние** (`kill_switch_status.json`, `kill_switch_active.json`) — без строки в матрице.
- **CMO-публикация:** 44 одобренных черновика, 0 опубликовано. **Family fund** кабинет — 404. **earn-defi** — свои падающие джобы (drill FAIL 5/6).
- `decision_loop` работает 3 ч+ с логом 3.8 GB — тот же агент, что и источник INC-1.
- Публичная главная показывает «Go-live progress 29/29» — та же путаница областей (предмет №2).
- GoLive-критерий C013 вечно PASS из замороженного `KANBAN.json`.

## 6b. Исправленные ярлыки регистра (ревью §3.3)

`KANBAN.json` и `PROJECT_CONTROL/` — НЕ SUPERSEDED (их всё ещё читают: брифинг, C013, шапка CLAUDE.md) → RECONNECT/MERGE ·
`OWNER_BACKLOG_2026-07-16` — DEFER до попунктной сверки переноса · `weekly_backup` — REPAIR (заменитель не покрывает его состав) ·
`research/btc_cycle` — KEEP как доказательство (единственная запись исходных индикаторных результатов владельца) ·
legacy strategy registries — KEEP (разрешают id `S7`) · нейминг тиров — **решён владельцем 2026-07-11** (не открытый вопрос);
«Core» имеет три живых значения; `tier_paper_rollup` — третье определение Balanced/Aggressive.

## 7. UNKNOWN_PURPOSE (не удалять)

LOGOS desk + :8777 · `mission_tick` (plist в `~/studio-os-scratch`) · OpenClaw gateway · `tier_paper_rollup` ·
shadow tournament · CPA evidence history · gold/anti-crisis research (fake 8% fallback) ·
`deploy-landing.yml` (CF Pages vs GitHub Pages) · сам `mission_tick` контур Studio OS.

## 8. Контракты

Заморожены в [ADR-580](../decisions/ADR-580-company-truth-contracts-rm-truth-01.md) (C1–C12, с поправками ревью). Срезы-доказательства: `A1…A6_*.md` в этом каталоге.
