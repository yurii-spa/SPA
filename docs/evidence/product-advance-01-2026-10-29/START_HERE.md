# START HERE — PRODUCT-ADVANCE-01 (29.10.2026), граница поставки 1 → поставки 2 и 3

Задание (каноническое, перенесено из проекта ARB дословно): [`docs/tasks/product-advance-01-2026-10-29.md`](../../tasks/product-advance-01-2026-10-29.md).
Владелец: Юрий. Приёмка: ARB. Исполнитель: Claude Code. Один эпик, 20 приёмочных подзадач, три поставки.
Этот файл — состояние на границе поставки 1. Чат не единственный источник: всё, что нужно новому окну, ниже.

## 0. Где лежат кандидаты (проверено 29.10)

| Репозиторий | Ветка / дерево | SHA | Что внутри |
|---|---|---|---|
| SPA | `tgux01/candidate` (origin), worktree `/private/tmp/spa_wt_tgux_20261028T203906Z` | код = `9303926d445d950ca3965ebba53a990cdda09d21`; этот документ — следующим коммитом ветки | TELEGRAM-OWNER-UX-01 + ARB R3; ADR-852 (Proposed) |
| SPA | дерево доставки `/private/tmp/spa_wt_tgux_deliver` (detached на `origin/main` `a78c38f56`, правки не закоммичены) | код побайтно = `9303926d4` | 19 файлов, пушер `--dry-run`: 1 коммит |
| earn-defi | `tgux01/candidate`, worktree `/private/tmp/earn_wt_tgux_20261028` (удалённого репо нет) | `eaef0c741bb26137b145baa72357c1e2cc6e48c7` | D-62 + D-63 (ARB R1/R2) |

`/private/tmp` переживает не всё (перезагрузка). Ветка SPA на origin — надёжная копия; earn-defi ветка живёт только
в локальном `.git` `~/Documents/earn-defi` (worktree можно пересоздать: `git -C ~/Documents/earn-defi worktree add <dir> tgux01/candidate`).

## 1. Поставка 1 — A (Telegram): статус по разделению «реализовано / проверено / доставлено / активировано / заблокировано»

| | Реализовано | Проверено | Доставлено | Активировано | Заблокировано |
|---|---|---|---|---|---|
| A1 R1/R2 (earn-defi) | да, `eaef0c7` (D-63) | 245 passed; новые тесты на `0ec8668` красные 6 из 7 | нет | нет | применение — решение владельца (рабочее дерево монитора) |
| A1 R3 (SPA) | да, `9303926d4` | целевые 216 + связанные 483 passed; новые 4 теста на `5e9dc665a` красные все | нет | нет | см. A2 |
| A2 доставка SPA | дерево доставки готово, резерв прод-копий `~/studio-os-serve/backups/tgux01_20261028T230921Z` | dry-run OK | **нет** | — | **автоматический контроль отклонил push в main как «Production Deploy» (28.10 23:1x).** Не обходилось. Нужен допуск владельца по действующему порядку |
| A3 что исполняется | сверка ниже | только чтение | — | **ничего из пакета не активно** — код не на main | бот (KeepAlive) потребует точечного перезапуска — решение владельца |
| A4 результат владельца | таблица 9 случаев (ниже), «было → стало» в ADR-852 / отчётах | фикстуры + фиктивный отправитель | — | — | случаи 6/7 — отдельные задачи |

CI SPA (ci-control, 12/12): база `e1493273c` прогон 40774145860 = 65 падений; финальный `9303926d4` прогон 40789300018 = 67:
65 общих с тождественными причинами + 2 дополнительных (`test_card_acceptance::…returns_a_known_verdict`,
`test_tracker_board_matches_cards::…live_cards`), оба красные и в прогоне 40781658817 на `main` с ТЕМ ЖЕ sha `e1493273c`.
Общий CI красный; отсутствие регрессий по всей системе не доказано. Подробно — ADR-852 «CI».

### A3 — кто исполнит код пакета (замер 29.10, только чтение, без перезапусков)

| Код | Процесс | Как подхватит | Сейчас |
|---|---|---|---|
| `dashboard_watcher` | `com.spa.dashboard_watcher`, StartInterval 300 | новый процесс каждый запуск — после синхронизации кода | старый код (main не содержит пакета) |
| `reports/daily.py` (сводка, R3) | `com.spa.digest_daily` 08:10 | так же | старый |
| `morning_work_digest` | `com.spa.work_digest` 09:00 | так же | старый |
| `resource_guard` | `com.spa.resource_guard`, 300 с | так же | старый (последний выход 2 — по его договору CRITICAL/не измерено) |
| `owner_decisions` (карточка-поручение) | `owner_queue/notify.py` (цикл оркестратора) и **`com.spa.telegram_bot` (KeepAlive, pid 8859, старт 28.10 04:56)** — бот импортирует модуль лениво и держит в памяти | бот — только перезапуском | старый; **перезапуск бота = отдельное решение владельца** (имя службы, проверка маячком `data/telegram_bot_capabilities.json`, откат — повторный перезапуск на прежнем коде) |
| `push_policy` / `telegram_client` (след доставки) | все отправители, включая бот | расписанные — сразу; бот — перезапуском | старый |
| earn-defi `monitoring` / `commit_reveal` | `com.earn-defi.monitor` 12:40/22:40, `com.earn-defi.daily` 12:10/22:10, из `~/Documents/earn-defi` (`main` = `21c125e`) | fast-forward `main` → `tgux01/candidate` в рабочем дереве | старый; применение — решение владельца |

### A4 — девять случаев PDF

| № | Итог |
|---|---|
| 1 COMMIT/REVEAL | исправлено (earn-defi); COMMIT не раскрывает содержимого; хеш перепроверяется |
| 2 INCIDENT + сверка | исправлено (earn-defi): новое/хуже/изменилось сразу, напоминание одним сообщением, «снято» только по результату той же проверки |
| 3 resource_guard ×12 | исправлено (SPA) |
| 4 ресурсы Mac | исправлено (SPA) |
| 5 CRITICAL агентов | строки переведены; повтор того же инцидента молчит (поведение push_policy, тест) |
| 6 сайт-сторож | текст уже русский (ADR-478); частота повторов — **отдельная задача** (маршрут CI-прогона/окно дедупа) |
| 7 цепочка сбоев | строки переведены; свёртка разных отправителей — **отдельная задача** (корреляция) |
| 8 поручение | исправлено (SPA); в боте — после перезапуска |
| 9 красный CI | исправлено (SPA) |

## 2. Сверка B–E с origin/main `a78c38f56` (только чтение, 29.10)

**B.** SPA: `spa_core/trading_research/` (CLI `python -m spa_core.trading_research tick|backtest|verify|status`),
`com.spa.trading_research` StartInterval 900, хранилище `data/trading_research/{evidence,market}.db` + `status.json`;
кандидаты из `strategies.registry()` (документ называет 138 — сверить). earn-defi: `data/earn_defi.db`, launchd из `deploy/`.
Пульт: `spa_core/studio_os/owner_view.py::trading_tile()` ← `trading_research/read_model.trading_lab_view(data_dir, earn_defi_track=…)`
— блок «торговля» УЖЕ есть, но без свежести тиков, непрерывности и разрывов; два контура в нём не разделены как
требует B4. API earn-defi: `spa_core/api/routers/btc_engine.py` (ADR-260).
**C.** SPA: наблюдения с хеш-цепочкой, издержки `trading_research/execution.step()` (spot 10+5 бп; perp 5+5 + funding);
earn-defi: `replay`, `commit_reveal`, `execution/base.py`. Нет: экспорта одного цикла (TRP-01), разложения результата
(TRP-04). TRP-03: ближайшее — `capital_shadow/contract.py` (`INTENT_ID_FIELDS`, TTL), тесты `test_capital_shadow_*`;
версии политики в идентичности нет. TRP-02 (совокупность допустимых по отдельности заявок): теста нет ни в SPA,
ни в earn-defi → это отдельная задача, не PASS.
**D.** Очередь: `scripts/orchestrator_queue.py` (`set-status` — безопасная запись), `spa_core/owner_queue/*`,
`owner_decision_pending.py`; реестр ответов `docs/decisions/owner-answers-2026-10-27-session.json` — 18 записей.
На origin/main `status: needs-owner` в frontmatter — **0** из 1495 карточек; пульт показывает «Ждут вашего ответа: N»
из `owner_view.owner_questions()`. **Прод-копии трекера расходятся с origin** (усечены — память
`prod-tree-tracker-copies-are-truncated`): D1 обязан снять список с ОБЕИХ копий и назвать расхождение.
**E.** `spa_core/studio_os/memory/{assembler,role_pack,arch_review,continuity}.py`, CLI `python -m spa_core.studio_os.memory`;
`architecture/model_roles.json`: роли architect/worker, assignments null, `claude_subscription_cli` и `fixture_test_adapter`
квалифицированы, `ollama_local` — нет. На пульте ролей/провайдеров нет (импортирует только `arch_review`).

## 3. План поставок 2 и 3 (оценка — активная работа, без ожидания CI ~1–1,5 ч на прогон)

| Блок | Осталось | Файлы | Приёмка | Оценка |
|---|---|---|---|---|
| B1+B2 | read-only карточка контура ×2 + замер непрерывности 7 суток по правилам контура (HOLD ≠ нет записи ≠ не измерено) | `trading_research/read_model.py` (+ читатель earn-defi через уже опубликованный `track.json`/`status`), новый тест | фикстуры: пропуск источника, нет вычисления, устаревший экран, HOLD, late/backfill — 5 различимых исходов | 3–4 ч |
| B3 | только если B2 найдёт подтверждённый разрыв | по находке | воспроизведение на копии | 0–3 ч |
| B4 | два блока на пульте | `owner_view.py`, `mission_ui/app.js`, `styles.css` | 390/430 px без горизонтальной прокрутки (эмуляция; ручной iPhone — отдельно владельцем) | 2–3 ч |
| C1+C2 | экспорт и офлайн-повтор одного цикла каждого контура (SQLite — штатный снимок с учётом WAL) | `trading_research/evidence.py`/новый `cycle_export.py`; earn-defi `replay.py` | совпадение в допуске; подменённый вход — отказ; повтор не пишет | 4–5 ч |
| C3 | разложение результата из существующей модели | `trading_research/read_model.py` | сумма = ledger в допуске; нет компонента — UNKNOWN | 2 ч |
| C4 | TRP-03 на существующем контракте; TRP-02 — отдельная задача | `capital_shadow` тест | отказ на симуляции | 1–2 ч |
| D1–D4 | снимок очереди владельца (origin + прод), сверка с 18 ответами, классификация, пульт | `owner_view.owner_questions`, отчёт в `docs/evidence/` | сумма категорий = исходный список; запись в трекер — только `orchestrator_queue.py set-status`, без массового `--apply` | 3–4 ч |
| E1–E4 | пакет контекста из assembler/role_pack; секция ролей на пульте; START_HERE-проверка на фикстурах | `mission_control.py`, `owner_view.py`, `mission_ui/app.js` | assignments null ⇒ «не назначен»; нет проверки ⇒ UNKNOWN; потерянный источник/устаревший SHA ⇒ явный отказ | 3–4 ч |

Зависимости: B, D, E независимы; C опирается на B (TRP-01/04), TRP-03/07 — сразу. B4, D4, E2 правят одни и те же
`owner_view.py` / `mission_ui/app.js` / `styles.css` — делать последовательно в ОДНОМ дереве.
Диск: свободно ~11–12 ГБ < 20 ⇒ предохранитель ADR-551 отказывает тяжёлым прогонам (> 2000 тестов) — гонять
целевые наборы частями; обход не переносится. CI — по одному на кандидата поставки.

## 4. Что делать новому окну (по порядку)

1. Прочитать этот файл и задание. Повторный аудит не делать.
2. Поставка 1: ждёт допуска владельца на push SPA (`push_to_github_batch.py` из `/private/tmp/spa_wt_tgux_deliver`) и
   решения о применении earn-defi и перезапуске бота. Сам не пушить в обход отказа.
3. Поставка 2 (B+C) в НОВОМ worktree от `origin/main` (не в дереве Telegram): B1/B2 → B4 → C1/C2 → C3 → C4.
4. Поставка 3 (D+E) — после B4 (общие файлы пульта).
5. На границе каждой поставки — обновить этот файл (или следующий START_HERE) и ROADMAP.

Запрещено в эпике: stash/pop, force-push, удаления, массовые перезапуски, очистка диска, денежный пакет,
переписывание трекера мимо `orchestrator_queue.py`, новый бот/движок/память, платные API, Ollama.
