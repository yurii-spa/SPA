# Покрытие `data/` ежедневным FULL-архивом — классификация 2026-10-16

> Замер: прод-дерево `~/Documents/SPA_Claude/data`, 2026-10-16 ~04:30 (только чтение).
> Производитель FULL — `scripts/daily_backup.py`; проверка полноты — `spa_core/dr/full_archive_verify.py`
> (классы ADR-611: FULL — ежедневный полный, CRITICAL — DR-набор `spa_dr_backup/*`).
> Сторож этого документа и нового покрытия — `spa_core/tests/test_backup_data_coverage.py`
> (каждый каталог из `_EVIDENCE_SUBTREES` обязан иметь строку здесь).

## Итог

| Класс | Каталогов | Что сделано |
|---|---|---|
| **НУЖНО** (невосстановимо) | 15 | добавлено в FULL; два якоря объявлены в `architecture/provenance.json` ⇒ обязательны при проверке |
| **НУЖНО-НЕ-ПРОВЕРЕНО** (писатель не найден / назначение не доказано) | 5 | добавлено в FULL (дёшево; «неизвестно» ≠ «воспроизводимо») |
| **ВОСПРОИЗВОДИМО** (генератор назван / копия в git) | 24 | не добавлено |
| **ВРЕМЕННОЕ** | 3 | не добавлено, `backups/` и `memory/` запрещены в коде (`_NEVER_SUBTREES`) |

Всего вне FULL было **47** подкаталогов (из 55; `trading_research/` покрыт частично — только два `.db`)
и **111** файлов верхнего уровня не-json. Архив на реальных данных: **17 166 780 → 20 291 404 байт**
(+3,1 МБ, +18 %), членов **857 → 1311**.

Как понимать столбец «писатель»: найден по ссылке на путь в коде, затем проверен по модулю,
который пишет (ловушка CLAUDE.md: «никто не читает файл по имени» — не доказательство).

## НУЖНО — добавлено в FULL

| каталог | класс | обоснование | писатель | размер | покрыто чем |
|---|---|---|---|---|---|
| `capital_shadow_anchors` | НУЖНО | внешний якорь-свидетель леджера `capital_shadow/ledger.jsonl` (уже в FULL); пишется на каждый append; леджер без якоря не доказывает, что его не переписали — та же роль, что у `investment_cio_anchors` | `spa_core/capital_shadow/ledger.py` (`contract.ANCHORS_SUBDIR`) | 68 КБ, 10-15 | FULL `_PROOF_SUBTREES` + обязателен (provenance) |
| `research_factory_anchors` | НУЖНО | то же для `research_factory/ledger.jsonl` (ADR-560) | `spa_core/research_factory/_common.py` (`HashLedger`) | 1,8 МБ, 10-15 | FULL `_PROOF_SUBTREES` + обязателен (provenance) |
| `aggressive_lab` | НУЖНО | `*/realized_series.jsonl` — proof-chained форвард-серии бумажных книг; только paper-путь дописывает, прошедший день не наблюдается повторно | `spa_core/strategy_lab/aggressive_lab/harness.py` (PaperService.tick) | 4,2 МБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `swarm` | НУЖНО | `*_proof.jsonl` — ежедневные proof-цепочки роя (append, по одной строке в день) | `spa_core/strategy_lab/swarm/common.py::append_daily_proof` | 376 КБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `strategy_lab_paper` | НУЖНО | живые форвард-серии бумажных стратегий («persists a growing per-strategy time-series») | `spa_core/strategy_lab/paper.py` | 416 КБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `sleeve_aggressive` | НУЖНО | append-only леджер рукава, идемпотентен по дате | `spa_core/strategy_lab/sleeve/composer.py::append_ledger` | 28 КБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `investment_os` | НУЖНО | `*_verdicts.jsonl`/`*_proof.jsonl` — hash-chained архив вердиктов аналитиков (ADR-066) | `spa_core/investment_os/verdict_archive.py` | 968 КБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `dfb` | НУЖНО | proof-chained история по пулам; агент остановлен 2026-08-30 — заново не собрать | `spa_core/dfb/paper_dfb.py` | 1,7 МБ, 08-30 | FULL `_EVIDENCE_SUBTREES` |
| `monitoring` | НУЖНО | `risk_posture.json` — живое de-risk состояние (FREEZE), `reaction_log.json` — журнал de-risk действий (кольцо 2000); `signal_log.json` — кольцо ~26 ч наблюдений (370 КБ в gzip, взят целиком, чтобы не плодить исключения) | `spa_core/monitoring/actions.py`, `sense_loop.py` | 9,7 МБ, 10-16 | FULL `_EVIDENCE_SUBTREES` (`monitoring_config.json` ещё и в git) |
| `telegram` | НУЖНО | `user_prefs.json` — настройки уведомлений владельца; `push_state.json` — дедуп отправок (без него повтор пушей). Чат-id — не секрет, токен в Keychain | `spa_core/telegram/*` | 100 КБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `cmo_drafts` | НУЖНО | черновики с полем `status`/`approved_at` — записи одобрения | `spa_core/cmo/draft_store.py` | 372 КБ, 10-15 | FULL `_EVIDENCE_SUBTREES` |
| `daily_summaries` | НУЖНО | дневные сводки на момент дня (go-live, лучшая стратегия, риски); агент пишет только СЕГОДНЯ — прошлое не перегенерировать | `spa_core/agents/daily_summary_agent.py` | 472 КБ, 10-16 | FULL `_EVIDENCE_SUBTREES` |
| `statements` | НУЖНО | выпущенные месячные выписки; прод-копия `2026-06.json` РАСХОДИТСЯ с git (переписана 10-01) | `spa_core/compliance/monthly_statement.py` | 12 КБ, 10-01 | FULL `_EVIDENCE_SUBTREES` (+ старая версия в git) |
| `publication_inputs` | НУЖНО | ADR-630: content-addressed точные входы каждой собранной полки сайта; одобрение через дни сверяется с ЭТИМИ байтами | `scripts/build_site_numbers.py` (`INPUTS_STORE`) | 256 КБ, 10-14 | FULL `_EVIDENCE_SUBTREES` |
| `bee` | НУЖНО | `hash_chain.json`, `pinned/`, `hashes/` — закреплённые 06-22 хэши; `defillama_apy_history.json` числится в DR `CRITICAL_FILES` (воспроизводим, но взят целиком) | `spa_core/backtesting/tier1/*` | 1,0 МБ, 10-15 | FULL `_EVIDENCE_SUBTREES` (8 из 16 файлов ещё и в git) |

## НУЖНО-НЕ-ПРОВЕРЕНО — добавлено в FULL

| каталог | класс | обоснование | писатель | размер | покрыто чем |
|---|---|---|---|---|---|
| `dd_snapshot` | НУЖНО-НЕ-ПРОВЕРЕНО | замороженный DD-снимок 07-11 с закреплённой головой цепочки; источник (rates_desk) кольцевой — снимок уже не префикс текущих данных; мог уйти внешнему ревьюеру | `scripts/build_dd_snapshot.py` | 1,9 МБ, 07-11 | FULL `_EVIDENCE_SUBTREES` |
| `reports` | НУЖНО-НЕ-ПРОВЕРЕНО | `golive_readiness_2026-07-29.*` — отчёт на момент; месячные txt | `spa_core/reporting/*`, monthly-агент | 36 КБ, 10-01 | FULL `_EVIDENCE_SUBTREES` (pdf ещё и в git) |
| `dataroom` | НУЖНО-НЕ-ПРОВЕРЕНО | zip-бандлы data-room 07-11/12; генератор строит НОВЫЙ, не прежний; выдавались ли наружу — неизвестно | `scripts/build_dataroom.py` | 708 КБ, 07-12 | FULL `_EVIDENCE_SUBTREES` |
| `_corrupt_snapshot_20260625` | НУЖНО-НЕ-ПРОВЕРЕНО | криминалистика инцидента 06-25, писателя в коде нет | — | 36 КБ, 06-25 | FULL `_EVIDENCE_SUBTREES` |
| `sandbox_sweep` | НУЖНО-НЕ-ПРОВЕРЕНО | писатель в коде не найден (`capital_sweep` — 0 ссылок) | — | 4 КБ, 06-30 | FULL `_EVIDENCE_SUBTREES` |

## ВОСПРОИЗВОДИМО — не добавлено

| каталог | класс | обоснование | писатель / команда | размер | покрыто чем |
|---|---|---|---|---|---|
| `trading_research` (кроме `.db`) | ВОСПРОИЗВОДИМО (условно) | `backtest.json` переписывается ежедневно; `backtest_history/` — неизменяемые копии (ADR-590 «переживают перезапись», не потерю хоста). Квалификационные метрики канонически лежат в append-only событии `BACKTEST_QUALIFIED` в `evidence.db` (FULL); копия воспроизводима из `market.db` (FULL) + `code_version` (sha исходников пакета) + `data_to_ms`. Цена включения ≈ 1,3 МБ gzip в день накопительно на каждый архив | `python3 -m spa_core.trading_research` (forward.py → `backtest.save_versioned`) | 87 МБ (56 МБ история), 10-16 | `evidence.db`+`market.db` в FULL; `status.json` — производное; `tick.lock` — временное |
| `continuity` | ВОСПРОИЗВОДИМО | генерируется из канонических источников (ADR-610) | `python -m spa_core.studio_os.memory continuity build` | 72 КБ | генератор + git |
| `defi_engine` | ВОСПРОИЗВОДИМО | `status.json`/`passports.json` пересчитываются ежечасно | `python3 -m spa_core.defi_engine --run` | 72 КБ | генератор |
| `riskwire` | ВОСПРОИЗВОДИМО | снимок измерений пересобирается каждым циклом (цепочка внутри артефакта, не между запусками) | `spa_core/riskwire/facade.py` из `cycle_runner` | 304 КБ | генератор |
| `market_data` | ВОСПРОИЗВОДИМО | кэш фидов (цены, funding, ratios) | `spa_core/strategy_lab/data/market_data.py` (перезапрос) | 100 КБ | внешние фиды |
| `realized_ab` | ВОСПРОИЗВОДИМО | разовый A/B-расчёт 06-29 над входами из FULL | `python3 -m spa_core.strategy_lab.realized_ab` | 16 КБ | генератор |
| `underwriting` | ВОСПРОИЗВОДИМО | отчёт андеррайтинга 06-29 | `python3 -m spa_core.strategy_lab.underwriting.report` | 32 КБ | генератор |
| `strategy_lab` | ВОСПРОИЗВОДИМО | `portfolio_book`/`capacity` 06-28/29 | `python3 -m spa_core.strategy_lab.portfolio_book` | 12 КБ | генератор |
| `retired_plists_backup` | ВОСПРОИЗВОДИМО | все 4 plist байт-в-байт равны `scripts/com.spa.*.plist` в git | — | 20 КБ | git |
| `task_links` | ВОСПРОИЗВОДИМО | в git (байт-в-байт) и в ночном `scripts/memory_backup.py` | `spa_core/studio_os/links.py` | 4 КБ | git + memory_backup |
| `backtest`, `historical_apy`, `strategies` | ВОСПРОИЗВОДИМО | все файлы в git, байт-в-байт с прод-копией | backtesting / export_data | 136 КБ | git (GitHub) |
| `ic_memos`, `milestones`, `monthly_reports`, `red_team_reviews`, `research_reports`, `risk_reviews`, `weekly_evidence` | ВОСПРОИЗВОДИМО | шаблоны/отчёты июня, все в git, байт-в-байт | — | 40 КБ | git (GitHub) |
| `protocol_cards`, `stablecoin_cards`, `strategy_cards`, `strategy_candidates` | ВОСПРОИЗВОДИМО | карточки, все в git (исключения в `.gitignore`), байт-в-байт | ручные / `build_maturity_register.py` читает | 444 КБ | git (GitHub) |

## ВРЕМЕННОЕ — не добавлено

| каталог | класс | обоснование | писатель | размер | покрыто чем |
|---|---|---|---|---|---|
| `backups` | ВРЕМЕННОЕ (сами архивы) | FULL/CRITICAL-архивы и снимки `spa_*.db`; архив в себе — рекурсия. Запрещён кодом | `daily_backup.py`, `dr_backup.py`, `persistence/backup.py` | 626 МБ | оффсайт-копия (`spa_core/dr/offsite_copy.py`) |
| `memory` | ВРЕМЕННОЕ | `index.db` — расходник ADR-527, `build` ≈ 5 с. Запрещён кодом | `python -m spa_core.studio_os.memory build` | 174 МБ | генератор |
| `orchestrator_cycle.lock` | ВРЕМЕННОЕ | каталог-замок цикла | `scripts/orchestrator_cycle_lock.py` | 4 КБ | — |

## Файлы верхнего уровня (не `*.json`/`*.jsonl`) — 111

| файлы | класс | обоснование | покрыто чем |
|---|---|---|---|
| `track.db`, `spa.db`, `academy.db` | НУЖНО | уже в FULL через sqlite online-backup (`_SQLITE_FILES`) | FULL |
| `*.db-shm`, `*.db-wal` (2) | ВРЕМЕННОЕ | состояние WAL; online-backup даёт согласованную копию без них | — |
| `tmp*.tmp` (87, 2,3 МБ) | ВРЕМЕННОЕ | обломки `atomic_save` | — |
| `*.lock` (3), `.DS_Store`, `.gitkeep` | ВРЕМЕННОЕ | замки/служебное | — |
| `.last_daily_digest`, `.last_weekly_digest`, `.last_daily_report_sent` | ВОСПРОИЗВОДИМО | маркеры дедупа; потеря ⇒ максимум один повторный дайджест | — |
| `*.md` (3), `*.pdf` (4) | ВОСПРОИЗВОДИМО | все 7 в git | git (GitHub) |
| `*.pre_heal_bak` (3), `*.pre_advisory_bak` (1) | НУЖНО-НЕ-ПРОВЕРЕНО | копии трек-файлов ДО «лечения» 07-01 — след правки трека; писателя в коде нет; 41 КБ | FULL `_EXTRA_GLOBS` |
| `rates_desk/anchors.jsonl.orphaned-*` (2, внутри покрытого каталога, но мимо его маски) | НУЖНО-НЕ-ПРОВЕРЕНО | осиротевшие кольца якорей ре-базы 07-10/11; 906 байт | FULL `_EXTRA_GLOBS` |

## Проверка на реальных данных (2026-10-16, в scratch, прод не тронут)

* origin-код: 857 членов, 17 166 780 байт; `full_archive_verify` с новым объявлением — **не ок**:
  `required:missing:capital_shadow_anchors/anchors.jsonl`, `…research_factory_anchors/ledger.anchors.jsonl`.
* новый код: 1311 членов, 20 291 404 байт, `verify()` 0 расхождений, `full_archive_verify` — **ок**
  (14 обязательных, 5 sqlite, 12 CIO-снимков для replay).
* восстановление в отдельную папку: sha256 всех 1311 членов = манифест, лишних файлов 0,
  `PRAGMA integrity_check` = ok для `track.db`, `spa.db`, `academy.db`, `trading_research/evidence.db`, `…/market.db`;
  ни одного члена из `backups/` или `memory/`.

## Остающиеся ограничения

* Восстановление КОДА зависит от GitHub (origin); FULL несёт только `data/`.
* Загрузка FULL в iCloud (`dr_offsite_copy`) этим изменением **НЕ ИЗМЕРЕНА**.
* `trading_research/backtest_history/` не в FULL сознательно (см. выше); единственная полная копия вне
  хоста — недельный архив всего дерева, который остаётся (`docs/backup/WEEKLY_BACKUP_RETIREMENT.md`).
* Новые каталоги `data/` в FULL сами не попадут: классификацию надо повторять (сторож держит только
  перечисленные).
