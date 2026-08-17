# Триаж бэклога — 2026-08-16

> **Что это.** Владелец потребовал разобрать весь открытый бэклог за 48 часов. Это не план
> «как всё успеть», а **замер**: что действительно можно закрыть автономно, что упирается в Мак,
> что в деньги, что в решение владельца. Числа ниже — по факту чтения каждой карточки и, где это
> было возможно, по прогону кода на этом дереве.
>
> **Ничего не чинилось, ни один статус карточки не двигался.** Единственный записанный файл — этот.

## Как считалось

Открытыми считаны карточки `nimbalyst-local/tracker/*.md` со статусом
`new` · `backlog` · `in-progress` · `blocked`. Их **124** (в задании было «123» — расхождение
на одну `blocked`-карточку, `agent-fleet-parity-guard-never-scheduled`). Остальные 352 —
`done` (236) и `ingested` (103) плюс 8 `needs-owner` (они по определению у владельца и в этот
разбор не входят).

Читались frontmatter + первые разделы тела. Для 14 карточек посылка **проверена прогоном** на
этом дереве (тесты, наличие файлов, содержимое реестров) — см. раздел «Уже закрыты по факту».

## Итог в одну таблицу

| Корзина | Карточек | Доля |
|---|---:|---:|
| **E — уже закрыты по факту / посылка устарела** (проверено кодом) | **14** | 11 % |
| **A — можно закрыть автономно** (код/тесты/сторожа/документы) | **62** | 50 % |
| **B — money-path** (веса, пороги, RiskPolicy, kill-switch, живой трек) | **22** | 18 % |
| **C — требует Мака** (launchctl, прод-дерево, живые фиды, сеть за прокси) | **18** | 15 % |
| **D — требует решения владельца** | **8** | 6 % |
| **Всего** | **124** | |

---

## E · Уже закрыты по факту работой последних дней (14)

Каждая строка проверена **на этом дереве**, а не по журналу. Это самый дешёвый способ убрать
из бэклога 14 карточек: работы там ноль, нужен только перевод статуса.

| Карточка | Чем проверено | Вердикт |
|---|---|---|
| `agent-morpho-steakhouse-bez-risk-score` | `spa_core/risk/protocol_risk_map.py:97` содержит `morpho_steakhouse`; `pytest tests/test_risk_scoring_completeness.py` → **10 passed** | Три «краснеющих на main» теста зелёные |
| `inbox-adr-070-6-morpho-steakhouse-otsenka-morp` | то же | **Дубль** предыдущей, закрыт тем же коммитом |
| `agent-golive-gap-criterion` | `spa_core/paper_trading/golive_checker.py:595-627` — ветка `active_gaps` + fail-CLOSED на отсутствие поля | Реализовано (ADR-087) |
| `inbox-adr-070-16-go-live-blokiruyut-tolko-akti` | то же | **Дубль** предыдущей |
| `agent-manifest-drift-morning-digest` | `architecture/manifest.json:982` содержит `com.spa.morning_digest`; `pytest spa_core/tests/test_architecture_manifest.py` → **24 passed, 1 skipped** | Сторож больше не краснеет |
| `inbox-nahodka-petli-manifest-fakty-manifest-ch` | то же | Находка петли того же дрейфа; источник зелёный |
| `inbox-nomer-adr-067-zanyat-dvumya-raznymi-resh` | `docs/decisions/INDEX.md:27/29/49` — коллизия разведена: гейт перенумерован в **ADR-087**, на 067 оставлена строка-указатель `Superseded` | Ровно то, что просила карточка |
| `agent-enforcer-coverage-gaps` | `docs/decisions/ADR-062-enforcer-coverage-caps.md` существует; `spa_core/risk/policy_enforcer.py:45/98/105` — chain-cap 90 %, per-protocol 40 %, T1 40 % берутся из `RiskConfig` | «Ждёт go на пуш» — пуш состоялся |
| `inbox-test-gsm-sky-prikolochen-k-do-adr-065-so` | `pytest spa_core/tests/test_allocator_evidence_gate.py` → **16 passed** (в т.ч. `test_sky_susds_gsm_gate_is_consulted`) | Тест уже обновлён под ADR-065 |
| `agent-rank-demotion-paper-module` | `spa_core/strategy_lab/swarm/rank_demotion_forward.py` существует, реализует ДВЕ руки (drift #39/#40 и vol #45); `ADR-074-rank-based-tier-demotion.md` больше не `DRAFT` | Вариант C владельца построен |
| `inbox-demoushen-knig-aggressive-po-otnositelno` | то же | **Дубль** предыдущей (одно решение владельца 08.08) |
| `inbox-adr-070-22-paper-modul-dwell-zaschelki` | `spa_core/strategy_lab/swarm/dwell_hysteresis_forward.py` существует | Модуль построен |
| `agent-cycle-reconciliation-2026-08-04` | Карточка предупреждала о большом ребалансе **04.08**; сегодня 16.08 | Событие прошло 12 дней назад, предупреждать некого |
| `agent-qa-backlog` | Тело: «собрал ответы владельца на 12 вопросов, инжест сделан, борд создан» | Описывает СВОЮ работу в прошедшем времени |

**Условно сюда же (проверить перед работой, не закрывать вслепую):**
`inbox-adr-070-21-paper-modul-cdr-39-demoushen` — просит «paper-модуль CDR #39,
демоушен + отложенный возврат». `rank_demotion_forward.py` реализует ровно это правило
(«возврат: вне bottom-k M дней ПОДРЯД») рукой `drift (#39/#40)`. С высокой вероятностью
дубль, но названия не совпадают буквально — 15 минут сверки, а не полдня работы.

---

## Дубли — самый дешёвый способ уменьшить число

15 кластеров. Схлопывание даёт **−23 карточки** без единой строчки кода
(14 из них уже посчитаны в E — здесь показана вся картина связности).

| # | Кластер | Карточки | Что оставить |
|---|---|---|---|
| **К1** | morpho_steakhouse без риск-скора | `agent-morpho-steakhouse-bez-risk-score` · `inbox-adr-070-6-…` | обе в E |
| **К2** | go-live блокируют только активные дыры | `agent-golive-gap-criterion` · `inbox-adr-070-16-…` | обе в E |
| **К3** | ранговый демоушен Aggressive | `agent-rank-demotion-paper-module` · `inbox-demoushen-knig-aggressive-…` | обе в E |
| **К4** | манифест ↔ факты | `agent-manifest-drift-morning-digest` · `inbox-nahodka-petli-manifest-…` | обе в E |
| **К5** | **прод-дерево ≠ origin** | `agent-prod-clean-checkout-variant2` (корень) · `agent-origin-runtime-sync-gap` · `inbox-zamok-tsikla-orkestratora-dostavlen-no-v` · `inbox-prod-storozh-arhitektury-chitaet-fail-ko` | оставить корневую, три остальных — симптомы одной причины |
| **К6** | **долгожители крутят старый код** | `agent-dolgozhivuschie-agenty-krutyat-staryi-kod` · `inbox-dolgozhivuschie-agenty-ne-podhvatyvayut` | одна |
| **К7** | **живые фиды вне Ethereum** | `inbox-ozhivit-fidy-vne-ethereum-…` (корень) · `agent-blocked-protocols-need-live-feeds` · `inbox-krupneishaya-pozitsiya-knigi-stoit-na-ko` · `agent-find-feeds-for-seven-protocols` | одна работа, четыре описания |
| **К8** | morpho: два ключа — один пул/куратор | `agent-morpho-curator-concentration` · `inbox-morpho-blue-i-morpho-steakhouse-razresha` | одна |
| **К9** | безымянный простой капитала | `inbox-adr-076-3-atributsiya-kesha-…` (корень) · `inbox-nahodka-petli-vozmozhnost-fluid-fusdc-5` · `inbox-nahodka-petli-vozmozhnost-moonwell-base` | две находки петли гаснут сами, когда починена атрибуция |
| **К10** | owner-gate краснеет на своей автоматике | `inbox-owner-gate-krasneet-na-svoei-ezhednevnoi` · `inbox-adr-070-3-owner-gate-klass-…` | одна |
| **К11** | порядок отбора ALLOC-002 | `inbox-alloc-002-otbor-top-8-…` · `inbox-orkestrator-vedom-kanonicheskim-reestrom` | одна |
| **К12** | перезаполнение срезанного бюджета | `inbox-adr-072-ne-srabotal-trim-…` · `inbox-svesti-dve-realizatsii-perezapolneniya-b` | одна |
| **К13** | Balanced-трек пуст | `inbox-sbalansirovannyi-trek-nol-profinansirova` · `inbox-3-treka-parallelno-…` (+ `owner-decision-sbalansirovannyi-tir-…` в needs-owner) | одна |
| **К14** | portfolio-уровень аллокации | `agent-head-of-investment-layer` · `inbox-task-portfolio-cio-dynamic-capital-alloc` | одна (второе — спецификация владельца к первой) |
| **К15** | тесты ходят в живую сеть | `agent-tests-do-live-network-io` · `agent-tests-reach-live-feed-222` | одна (общий сторож `network_guard.py`) |

### Отдельно: мусорные карточки от интейка

Карточка `inbox-dlinnyi-dokument-vladeltsa-priehal-semyu` сама измеряет проблему: длинный
документ владельца приехал **семью** карточками за 21 секунду, из которых **шесть — куски
предложений, а не задачи** (`inbox-why-it-exists`, `inbox-actual-costs`,
`inbox-apy-persistence-confidence`, `inbox-100-zapuskov-na-odnom-snapshot`,
`inbox-dlya-kazhdogo-etapa…` и др.). В моём срезе `new/backlog/in-progress` из этой семёрки
осталась одна настоящая (`inbox-task-portfolio-cio-…`) — остальные уже вне открытого набора,
но **чинить надо интейк** (`spa_core/telegram/inbox_intake.py`), иначе следующий длинный
документ владельца снова раздуется в семь карточек.

---

## Карточки с устаревшей посылки (описанного дефекта больше нет)

Помимо E-списка, отдельно отмечены три класса, где посылка мертва не потому, что кто-то
починил, а потому, что изменился мир:

| Карточка | Почему посылка мертва |
|---|---|
| `agent-cycle-reconciliation-2026-08-04` | Это было предупреждение на конкретную дату. Дата прошла |
| `inbox-nahodka-petli-*` (4 шт.) | Механизм ADR-066 закрывает их САМ: «находка исчезает из отчёта источника ⇒ мост закроет карточку». Из четырёх две уже относятся к зелёным источникам |
| `agent-advisory-signals-track-c` | Владелец 23.07 прямо сказал «откладываем, держать в бэклоге». Это не задача, а закладка. Держать её в счётчике открытых — самообман |

---

## Полная таблица триажа (124)

Легенда размера: **S** ≤ полдня · **M** день–два · **L** больше двух дней.
«Парал.» — можно ли запускать одновременно с соседями по волне (конфликт считается по файлам).

### A · Автономно (62)

| Карточка | Трогает файлы | Разм. | Парал. |
|---|---|:--:|:--:|
| `agent-card-file-in-ownership-locks-a-card-it-doesnt-claim` | `scripts/check_card_claim.py` | M | да |
| `agent-changelog-generator-never-called` | `scripts/generate_research_changelog.py`, `scripts/run_daily_paper_cycle.sh` | S | да · хвост в C (агент/расписание) |
| `agent-checkpoint-7day-gate-conflict` | `scripts/checkpoint_7day.py`, `scripts/check_agent_before_deploy.sh` | M | да |
| `agent-checkup-waitlist-fail-open-ok-true` | API waitlist-хендлер, `tests/test_fund_api.py` | M | да · хвост в C (Railway) |
| `agent-cleanup` | `archive/`, `attic/`, широкий срез скриптов | M | **нет** (широкий blast radius) |
| `agent-drift-number-is-mostly-noise` | `spa_core/monitoring/deployment_drift_monitor.py` | S | да |
| `agent-dva-artefakta-odnogo-tsikla-raskhodyatsya-vtroe` | `spa_core/monitoring/capital_efficiency.py` | M | да |
| `agent-fake-fallback-v-15-adapterah` | `spa_core/adapters/*` (15 файлов), `spa_core/tests/adapter_fake_fallback_baseline.json` | L | **нет** (весь каталог адаптеров) |
| `agent-funded-protocol-not-in-registry` | новый сторож + `data/adapter_registry.json` (чтение) | S | да |
| `agent-guard-no-silent-mock-in-tournament` | `spa_core/tests/` (новый guard), `spa_core/strategies/` | M | да |
| `agent-idea17-needs-a-panel-with-daily-marks` | `spa_core/strategy_lab/aggressive_lab/harness.py`, `data/aggressive_lab/*` | L | да |
| `agent-insurance-scorer-otbrasyvaet-izvestnoe-pokrytie` | `spa_core/analytics/protocol_insurance_scorer.py` | S | да |
| `agent-orphaned-work-recurred-after-its-card-was-closed` | `docs/ORCHESTRATOR_PROTOCOL.md`, `scripts/reap_stale_worktrees.py` | M | да |
| `agent-porucheniya-bez-vybora-nechem-otvetit` | `spa_core/telegram/alert_actions.py`, `spa_core/owner_queue/` | M | да · хвост в C (рестарт бота) |
| `agent-predgateovaya-tsel-ne-sohranyaetsya` | `spa_core/paper_trading/cycle_runner.py` (запись артефакта) | S | **нет** (cycle_runner) |
| `agent-pusher-relative-path-silently-reads-the-host-tree` | `push_to_github.py`, `push_to_github_batch.py` | S | да |
| `agent-relocate-forecasters-to-timeseries-lane` | `spa_core/analytics/` (18 модулей), `data/historical_apy*` | L | да |
| `agent-relocate-optimizers-to-allocator-advisory` | `spa_core/analytics/` (13 модулей), `data/allocation_rationale.json` | M | да |
| `agent-relocate-trackers-to-reporting` | `spa_core/analytics/` (9 модулей), analytics_runner | M | да |
| `agent-rnd51-stale-branch-for-demotion-arm` | `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`, `spa_core/strategy_lab/swarm/rank_demotion_forward.py` | M | да |
| `agent-s76-apy-unit-guess` | `spa_core/strategies/s76_concentrated_lp.py`, `spa_core/adapters/apy_contract.py` | S | да |
| `agent-spark-susds-identity-split` | `spa_core/adapters/spark_susds.py`, реестр пинов | M | конфликт с fake-fallback |
| `agent-task-odno-chislo-dva-verdikta-portfolio-healt` | `spa_core/monitoring/system_health_monitor.py`, `agent_health_monitor.py` | S | да |
| `agent-task-prava-na-origin-nechem-pochinit-pusher-p` | `push_to_github.py` (передача mode) | S | конфликт с пушер-карточкой |
| `agent-test-run-dirties-tracked-fixtures` | `tests/fixtures/*`, `spa_core/data/*_log.json`, conftest | M | конфликт с сетевыми тестами |
| `agent-tests-do-live-network-io` | `spa_core/tests/network_guard.py`, `conftest.py` | M | **нет** (conftest) |
| `agent-tests-reach-live-feed-222` | то же — **делать одной работой с предыдущей** | L | **нет** |
| `agent-track-data-git-durability-guard` | `spa_core/monitoring/artifact_freshness.py` | M | да |
| `agent-tier-b-20-unsourced-modules-need-sources` | `spa_core/analytics/_protocol_key_coverage.py` | M | конфликт с Tier-C |
| `agent-tournament-trustworthy-real-apy` | `data/strategy_tournament.json`, турнирный движок | L | да · хвост в C (истор. ряды) |
| `agent-unwired-baseline-triage` | `spa_core/tests/unwired_scripts_baseline.json`, `spa_core/tests/_unwired.py` | M | конфликт с храповиком |
| `agent-wake-storm-fail-open-monitors` | `data/watchdog_status.json`/`self_heal_status.json` продюсеры | M | да · хвост в C (проверка на Маке) |
| `agent-audit-2026-08-02-fix-tracks` | координационная, кода нет | S | да |
| `agent-roadmap-continue-here` | индексная карточка-возобновление | S | да |
| `inbox-25-modulei-poluchili-vechnyi-verdikt-pok` | `scripts/audit_tier_c_wiring_feasibility.py` | M | конфликт с Tier-C |
| `inbox-7-day-checkpoint-gap-check-schitat-ot-ev` | `scripts/checkpoint_7day.py` | S | конфликт с гейтом checkpoint |
| `inbox-adr-070-12-bts-chestnyi-porog-zatem-vkly` | BTS-алерты | M | да · хвост в C (`SPA_BTS_ALERTS_ARMED`) |
| `inbox-adr-070-13-trevogu-core-agent-down-gasit` | `spa_core/monitoring/agent_health_monitor.py` | S | конфликт с «одно число — два вердикта» |
| `inbox-adr-070-14-governance-watchlist-nash-vai` | `spa_core/alerts/governance_watcher.py` | S | да |
| `inbox-adr-070-21-paper-modul-cdr-39-demoushen` | **сначала сверить с `rank_demotion_forward.py`** | S | да |
| `inbox-adr-070-3-owner-gate-klass-ezhednevnyi-s` | `scripts/check_owner_gate.py` | S | конфликт с owner-gate-карточкой |
| `inbox-adr-070-5-perenesti-3-garantii-dublya-v` | мост находок ADR-066 | M | да |
| `inbox-adr-076-3-atributsiya-kesha-obyazana-naz` | `spa_core/monitoring/capital_efficiency.py` | S | конфликт с «два артефакта» |
| `inbox-dlinnyi-dokument-vladeltsa-priehal-semyu` | `spa_core/telegram/inbox_intake.py`, `spa_core/owner_queue/intake.py` | S | да |
| `inbox-dva-predpisannyh-progona-ryadom-drug-druga-morya` | `docs/ORCHESTRATOR_PROTOCOL.md`, конфиг прогонов | S | конфликт с осиротевшей работой |
| `inbox-dva-raznyh-reestra-adapterov-nosyat-odno` | `spa_core/adapters/__init__.py`, `registry.py` + 6 потребителей | L | **нет** (реестр адаптеров) |
| `inbox-hrapovik-schitaet-upominanie-v-dokstring` | `spa_core/tests/_unwired.py` | M | **нет** (занята `pid66130`) |
| `inbox-mayachok-obyavlyaet-odnu-sposobnost-gejtit-dve` | `spa_core/telegram/alert_actions.py` | S | конфликт с «поручения без выбора» |
| `inbox-modul-39-tretei-rukoi-obyazana-byt-prich` | `spa_core/strategy_lab/swarm/`, `docs/DYNAMIC_LEVERAGE_GUARDIAN.md` | M | конфликт с rnd51 |
| `inbox-modul-bot-commands-zamenen-no-zhiv-svoi` | `spa_core/alerts/bot_commands.py` (списание) | S | да |
| `inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii` | `scripts/run_daily_paper_cycle.sh`, `spa_core/monitoring/cycle_lock_watch.py` | S | да |
| `inbox-owner-gate-krasneet-na-svoei-ezhednevnoi` | `scripts/check_owner_gate.py`, `landing/src/data/track_snapshot.json` | S | конфликт с ADR-070.3 |
| `inbox-paper-moduli-39-cdr-i-36-dwell-obyazany` | `spa_core/strategy_lab/swarm/*_forward.py` | S | конфликт с rnd51/#39 |
| `inbox-prod-storozh-arhitektury-chitaet-fail-ko` | `scripts/code_sync_from_origin.sh` | S | конфликт с прод-чекаутом |
| `inbox-storozh-perehodov-statusov-zhdet-pervogo` | `data/tracker_status_audit.jsonl` продюсер, `scripts/orchestrator_queue.py` | S | да |
| `inbox-stroka-risk-gate-dnevnogo-limita-ubytka` | `spa_core/reporting/daily_telegram_report.py` | S | да |
| `inbox-tier-c-171-iz-180-modulei-ne-otvechayut` | `scripts/audit_protocol_blindness.py`, `spa_core/analytics/` | L | **нет** (Tier-C семейство) |
| `inbox-tier-c-pyat-nastoyaschih-otkazov-agregat` | `spa_core/analytics/_protocol_key_coverage.py` | M | **нет** (то же) |
| `inbox-zamer-obmena-dohodnost-kontsentratsiya-n` | `docs/DYNAMIC_LEVERAGE_GUARDIAN.md` (замер) | M | конфликт с rnd51 |
| `inbox-nahodka-petli-analitik-red-team-critical` | находка петли ADR-066 — гаснет сама | S | да |
| `inbox-nahodka-petli-vozmozhnost-fluid-fusdc-5` | схлопнуть в ADR-076.3 | S | да |
| `inbox-nahodka-petli-vozmozhnost-moonwell-base` | схлопнуть в ADR-076.3 | S | да |

### B · Money-path (22) — автономно закрывать НЕЛЬЗЯ

Все идут через `spa_core/paper_trading/pre_cutover_gate.py`, sandbox-замер до/после и отдельное
решение. RiskPolicy остаётся `v1.0`; изменение порогов ⇒ новый ADR (`.claude/rules/risk-engine.md`).

| Карточка | Трогает файлы | Разм. |
|---|---|:--:|
| `agent-allocator-slep-k-limitu-seti` | `spa_core/allocator/`, chain_limits | M |
| `agent-allocator-yield-frozen-rootcause` | `data/allocation_rationale.json`, ADR-060 ARM — owner-gate | L |
| `agent-apy-evidence-provenance` | `data/adapter_status.json` схема + 12 адаптеров | L |
| `agent-book-violations-advisory-and-sky` | registry-merge путь аллокатора (инв. 9 и 10) | M |
| `agent-golive-intraday-drawdown-monitor` | `spa_core/governance/kill_switch.py` смежное | L |
| `agent-head-of-investment-layer` | новый слой над аллокатором | L |
| `agent-morpho-curator-concentration` | per-protocol cap, семантика куратора | M |
| `agent-safe-fallback-bypasses-adapter-gates` | `spa_core/tuner/portfolio_rebalancer.py:81` (`spark_susds` 13 %) — **инвариант 10 нарушается прямо сейчас** | M |
| `agent-tuner-constraints-drift-and-feed-divergence` | `portfolio_rebalancer._DEFAULT_CONSTRAINTS` | M |
| `inbox-3-treka-parallelno-conservative-balanced` | `spa_core/paper_trading/hy_cycle.py`, книги трёх треков | L |
| `inbox-adr-070-17-18-frax-udalit-notional-v3-vy` | реестр адаптеров = вселенная выбора | S |
| `inbox-adr-072-ne-srabotal-trim-proishodit-v-al` | `spa_core/paper_trading/risk_gate.py`, аллокатор | M |
| `inbox-adr-087-p-2-primenit-pravilo-adr-055-niz` | расчёт весов (сначала shadow) | M |
| `inbox-adr-087-p-3-svesti-dva-puti-apy-k-odnomu` | два пути APY — карточка сама помечена «Money-path» | M |
| `inbox-alloc-002-otbor-top-8-po-vesu-bednit-kni` | порядок отбора в аллокаторе | M |
| `inbox-dve-zapisi-o-dengah-rashodyatsya-kazhdyi` | `data/equity_curve_daily.json` ↔ `data/paper_evidence.json` | M |
| `inbox-morpho-blue-i-morpho-steakhouse-razresha` | пины пулов, скрытая концентрация | M |
| `inbox-orkestrator-vedom-kanonicheskim-reestrom` | канонический реестр + ALLOC-002 | M |
| `inbox-sbalansirovannyi-trek-nol-profinansirova` | `spa_core/paper_trading/hy_cycle.py` — 0 профинансированных дней из 40 | L |
| `inbox-snyataya-ostanovka-zhivet-v-git-vosstano` | `data/kill_switch_active.json` — **проверено: файл ЕСТЬ в git на HEAD** | S |
| `inbox-svesti-dve-realizatsii-perezapolneniya-b` | две реализации перезаполнения бюджета | M |
| `inbox-task-portfolio-cio-dynamic-capital-alloc` | `spa_core/allocator/allocator.py`, `docs/PORTFOLIO_CIO_PLAN.md` | L |

### C · Требует Мака (18)

`launchctl` / прод-дерево `~/Documents/SPA_Claude` / живые фиды и on-chain / сеть за прокси.
Из облака закрыть нельзя ни одну — можно только подготовить код и ждать.

| Карточка | Что именно недоступно | Разм. |
|---|---|:--:|
| `agent-prod-clean-checkout-variant2` | прод-дерево, п.6 правила деплоя (только владелец) | L |
| `agent-origin-runtime-sync-gap` | то же (симптом К5) | M |
| `inbox-zamok-tsikla-orkestratora-dostavlen-no-v` | то же (симптом К5) | S |
| `inbox-prod-storozh-arhitektury-chitaet-fail-ko` | код правится здесь, проверка — там (симптом К5) | S |
| `agent-dolgozhivuschie-agenty-krutyat-staryi-kod` | перезапуск `KeepAlive`-долгожителей | S |
| `inbox-dolgozhivuschie-agenty-ne-podhvatyvayut` | дубль К6 | S |
| `agent-fleet-inventory-73` | `launchctl list` | M |
| `agent-fleet-parity-guard-never-scheduled` | нужен plist + `launchctl bootstrap`; **занята мёртвой сессией `cycle-28258` с 05.08** | S |
| `inbox-tri-rabochih-dereva-derzhat-nedostavlenn` | `/private/tmp/spa_wt_*` на Маке | S |
| `inbox-okno-do-6-chasov-otvet-vladeltsa-mezhdu` | расписание `com.spa.decision_loop` | S |
| `inbox-adr-070-2-kanon-treka-kommititsya-tsiklo` | ночной цикл на Маке | M |
| `inbox-a-zadacha-pochinit-vse-taki-esche-raz-so` | Telegram-бот + GH Actions; **занята `pid43119` с 14.08** | M |
| `inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu` | живой DeFiLlama (корень К7) | L |
| `agent-blocked-protocols-need-live-feeds` | дубль К7 | L |
| `inbox-krupneishaya-pozitsiya-knigi-stoit-na-ko` | дубль К7 (aave_v3 TVL — литерал) | M |
| `agent-find-feeds-for-seven-protocols` | дубль К7 (поиск источников) | M |
| `agent-gsm-hours-producer` | on-chain чтение GSM Pause Delay | M |
| `agent-fluid-timelock-source` | on-chain таймлок Fluid | M |
| `inbox-ves-poddomen-checkup-earn-defi-com-otdae` | DNS/Cloudflare для `checkup.earn-defi.com` | M |

*(19 строк — `inbox-ves-poddomen…` учтён и в D: там есть развилка «поднять поддомен или снять ссылки».)*

### D · Требует решения владельца (8)

| Карточка | Что именно решает владелец |
|---|---|
| `agent-aaa-product-layer` | «Разбор — отдельно с владельцем» записано в теле карточки |
| `agent-advisory-signals-track-c` | сам отложил 23.07; открывать заново — его решение |
| `agent-plan-yield-stability-90pct` | зонтичная директива 05.08, приоритет волн за ним |
| `agent-site-numbers-and-gate` | числа доходности на сайте — **owner-gated** по `.claude/rules/site-copy.md` |
| `inbox-tablichka-chestnosti-dat-ei-dorogu-na-sa` | публичная копия + новый разрешённый класс owner-gate |
| `inbox-podgotovit-adr-peresmotr-limita-odnoi-ts` | подготовить ADR можно, **применять — только с явным «да»** (порог ADR-062) |
| `inbox-adr-070-20-clmm-research-hedzh-forma-adr` | допуск нового класса риска (CLMM + хедж) |
| `inbox-u-own-34-ostalsya-zhivoi-vopros-vladelts` | живой вопрос по §2.4, надо отправить и ждать |

---

## Волны — что запускать одновременно

Волны считаны по **непересечению файлов**. Внутри волны агенты не конфликтуют; между волнами —
барьер на прогон тестов (см. следующий раздел, там же причина, почему барьер дорогой).

**Волна 0 — «схлопнуть» (0 строк кода, любой момент, параллельно со всем).**
14 карточек из E + 6 мусорных карточек интейка + 9 дублей-симптомов из К5/К6/К7/К8.
Файлы: только `nimbalyst-local/tracker/*.md`. Это **−23…−29 открытых карточек за час работы**
и это самая выгодная волна во всём документе.

**Волна 1 — сторожа и мониторы** (7, все `spa_core/monitoring/*`, разные файлы)
`agent-task-odno-chislo-dva-verdikta` · `agent-track-data-git-durability-guard` ·
`agent-drift-number-is-mostly-noise` · `agent-dva-artefakta-odnogo-tsikla-raskhodyatsya-vtroe` ·
`agent-funded-protocol-not-in-registry` · `inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii` ·
`inbox-storozh-perehodov-statusov-zhdet-pervogo`
⚠️ `inbox-adr-070-13` и `inbox-adr-076-3` НЕ сюда — они делят файлы с 1-й и 4-й строками.

**Волна 2 — очередь, карточки, доставка** (6, `scripts/` + `push_to_github*`)
`agent-card-file-in-ownership-locks-a-card-it-doesnt-claim` ·
`agent-pusher-relative-path-silently-reads-the-host-tree` (+ `agent-task-prava-na-origin…` тем же агентом) ·
`inbox-dlinnyi-dokument-vladeltsa-priehal-semyu` ·
`agent-orphaned-work-recurred-after-its-card-was-closed` ·
`inbox-dva-predpisannyh-progona-ryadom-drug-druga-morya` ·
`inbox-modul-bot-commands-zamenen-no-zhiv-svoi`

**Волна 3 — Telegram, отчёты, owner-gate** (6)
`agent-porucheniya-bez-vybora-nechem-otvetit` (+ `inbox-mayachok-…` тем же агентом) ·
`inbox-stroka-risk-gate-dnevnogo-limita-ubytka` ·
`inbox-owner-gate-krasneet-na-svoei-ezhednevnoi` (+ `inbox-adr-070-3` тем же агентом) ·
`inbox-adr-070-14-governance-watchlist-nash-vai` ·
`inbox-adr-070-12-bts-chestnyi-porog` ·
`agent-changelog-generator-never-called`

**Волна 4 — advisory / R&D-модули** (6, `spa_core/strategy_lab/`, `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`)
⚠️ Внутри волны 4 три карточки делят `DYNAMIC_LEVERAGE_GUARDIAN.md` — их берёт ОДИН агент:
`agent-rnd51-stale-branch-for-demotion-arm` + `inbox-modul-39-tretei-rukoi` + `inbox-zamer-obmena-dohodnost-kontsentratsiya`.
Параллельно: `inbox-paper-moduli-39-cdr-i-36-dwell-obyazany` ·
`agent-idea17-needs-a-panel-with-daily-marks` · `inbox-adr-070-21` (сначала сверка) ·
`agent-s76-apy-unit-guess`

**Волна 5 — аналитика Tier-B/C и переселение own-27** (6)
Три «переселения» (`forecasters` / `optimizers` / `trackers`) идут параллельно — у них разные
списки модулей в одном плане. Семейство Tier-C (`inbox-tier-c-171-iz-180` ·
`inbox-tier-c-pyat-nastoyaschih` · `inbox-25-modulei-…` · `agent-tier-b-20-unsourced`) делит
`_protocol_key_coverage.py` — это **ОДИН агент, не четыре**. Плюс
`agent-insurance-scorer-otbrasyvaet-izvestnoe-pokrytie` (отдельный файл).

**Волна 6 — гигиена тестового набора** (3, и это ПОТОЛОК — все трогают conftest/фикстуры)
`agent-tests-do-live-network-io` + `agent-tests-reach-live-feed-222` (**одна работа**) ·
`agent-test-run-dirties-tracked-fixtures` ·
`agent-unwired-baseline-triage` + `inbox-hrapovik-schitaet-upominanie-v-dokstring` (**одна работа**, вторая занята `pid66130`)

**Волна 7 — адаптеры** (2, и параллелить их нельзя)
`agent-fake-fallback-v-15-adapterah` (15 файлов адаптеров) ·
`inbox-dva-raznyh-reestra-adapterov-nosyat-odno` (`__init__.py` + `registry.py` + 6 потребителей).
`agent-spark-susds-identity-split` — только ПОСЛЕ них.

**Волна 8 — прочее без соседей**
`agent-checkpoint-7day-gate-conflict` + `inbox-7-day-checkpoint-gap-check` (**одна работа**) ·
`agent-checkup-waitlist-fail-open-ok-true` · `agent-guard-no-silent-mock-in-tournament` ·
`agent-tournament-trustworthy-real-apy` · `agent-cleanup` (в одиночку, широкий радиус) ·
`inbox-adr-070-5-perenesti-3-garantii-dublya-v` · `agent-wake-storm-fail-open-monitors`

---

## Честная оценка по 48 часам

### Что мешает, кроме объёма

1. **Приёмка дороже работы.** Правило деплоя и `CLAUDE.md` требуют полного прогона
   `spa_core/tests/ tests/ scripts/tests/ spa_core/analytics/gross_of/ research/cards/`, а
   протокол — ещё и контрольного прогона на чистом `origin/main`. Замер на этом дереве 16.08:
   **`pytest --collect-only` по гейтящему срезу не выдал ни строки за 300 секунд и был снят по
   таймауту (код 143)** — то есть даже СБОР тестов, без единого прогона, дороже пяти минут.
   Карточка
   `inbox-dva-predpisannyh-progona-ryadom-drug-druga-morya` уже измерила худшее: два прогона
   рядом дают **~2 байта лога за 15 минут** против 18 КБ/мин у одиночного. То есть приёмка
   **не параллелится**, и она — настоящий потолок пропускной способности, а не число агентов.
2. **Набор зелёный по неверной причине.** 222 теста дают 9 268 отказов живого фида за прогон
   (`agent-tests-reach-live-feed-222`), и прогон пачкает git-tracked фикстуры
   (`agent-test-run-dirties-tracked-fixtures`). Значит «зелено» сейчас — слабый сигнал, и до
   волны 6 каждая приёмка стоит ручной сверки.
3. **Пять карточек заняты сессиями, две из них — мёртвыми.** `agent-fleet-parity-guard` держит
   `cycle-28258` с **5 августа** (11 дней), `inbox-tier-c-pyat-…` — `cycle-87477` с 6 августа.
   Пока захваты не сняты, брать их нельзя по протоколу.
4. **Инвариант 16.** Ни один красный тест нельзя погасить молча. Это правильно и это медленно.

### Реалистичный расчёт

При 6–8 параллельных агентов и барьере приёмки между волнами:

| | Карточек | Комментарий |
|---|---:|---|
| **Закроется за 48 ч** | **~35–42** | Волна 0 целиком (23–29 схлопыванием) + волны 1–3 (S-размер, ~12–15 штук) |
| **Начнётся, но не закроется** | ~12 | Волны 4–6: M/L-работы с приёмкой, реально это 3–5 дней |
| **Не начнётся вовсе** | ~48 | 22 B (нужен pre_cutover_gate + отдельные решения) · 18 C (нужен Мак) · 8 D (нужен владелец) |

**Разбор «~40 за 48 часов» по-честному: из них 23–29 — это не работа, а бухгалтерия**
(дубли и уже сделанное). Настоящих новых починок за двое суток — **12–15**, все размера S,
все из волн 1–3. Остальные 47 карточек класса A физически не помещаются: их суммарный размер
~20 M-работ и ~8 L-работ, а барьер приёмки один и не параллелится.

### Что сказать владельцу прямо

- **«Весь бэклог за 48 часов» — невыполнимо, и не из-за нехватки агентов.** 48 карточек из
  124 (39 %) закрыть автономно **нельзя в принципе**: 22 упираются в money-path (правила репо
  требуют `pre_cutover_gate` + отдельное решение), 18 — в физический Mac Mini, 8 — в его
  собственный ответ. Ни один агент этого не обойдёт, не нарушив инвариант.
- **Зато 23–29 карточек можно снять СЕГОДНЯ, за час, не написав ни строки кода** — они либо
  уже сделаны (14, проверено прогоном тестов), либо дубли (9 симптомов пяти кластеров), либо
  мусор от интейка (6). Это уменьшит открытый бэклог со 124 до ~95–101.
- **Самое дорогое из невидимого — приёмка.** Пока полный прогон не приведён в порядок
  (волна 6), каждая закрытая карточка стоит не «работа + 10 минут тестов», а «работа + час
  прогона + час контрольного прогона, которые нельзя запустить одновременно». Если владелец
  хочет ускорить бэклог — самая выгодная инвестиция не «больше агентов», а волна 6.
- **Два захвата надо снять руками** (`cycle-28258` от 05.08, `cycle-87477` от 06.08) —
  сессии мертвы, карточки заперты 10–11 дней.
- **Одна карточка B требует внимания вне очереди:**
  `agent-safe-fallback-bypasses-adapter-gates` — аварийный портфель
  (`spa_core/tuner/portfolio_rebalancer.py:81`) финансирует `spark_susds` на 13 %, что
  прямо нарушает инвариант 10. Дефект проверен, он в дереве сейчас.
