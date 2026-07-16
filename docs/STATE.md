# SPA — STATE (текущее состояние проекта)

> Живой файл состояния. Оркестратор читает в начале цикла и обновляет в конце.
> Живые оперативные цифры — `docs/SYSTEM_BRIEFING.md` (auto, 30 мин). Здесь — фокус,
> задачи, решения, вопросы. **Максимум ~150 строк.**

_Обновлено: 2026-07-16 (автономный цикл #13: очередь пуста → hardening — регресс-покрытие непокрытых **fail-safe веток** `spa_core/telegram/ask_router.py::classify_and_answer` (ЖИВОЙ классификатор каждого Telegram-сообщения владельца вопрос/задача/непонятно; общий для бота и intake). Контракт «любая ошибка → unclear» покрыт был лишь наполовину: +8 тестов — rc≠0 / пустой+whitespace stdout / `TimeoutExpired` / UNCLEAR без 2-й строки / QUESTION с пустым телом / регистро-устойчивость маркера. Модуль НЕ менял (только тесты, инвариант #16). 13/13 + 37 смежных зелёные. Предыдущий #12: регресс-тесты `scripts/orchestrator_queue.py` CLI)_
---

## 🎯 Текущий фокус

- **ENV_SETUP_BRIEF_v3 — ЗАВЕРШЁН + запушен в origin** (все 8 этапов + smoke-test). Files-first
  контур владельца живой: Owner Decisions + Inbox трекеры, протокол оркестратора, наблюдение :4455,
  Obsidian-база знаний, Telegram `/task`+`/status`+голос.
- **Автономный цикл `com.spa.orchestrator` ВКЛЮЧЁН** (governed autonomy, **каждый час** — owner 2026-07-16
  «чаще → больше работы»; было 3ч. Live: plist `StartInterval=3600`, агент `run interval=3600s`).
- **Agent cleanup сделан:** roadmap-loop остановлен, novel-edge переподчинён, 3 retired выгружены (fleet 54).
- **Go-live трек** — идёт фоном: ~24/30 evidenced дней (anchor 2026-06-22, target ~2026-07-21).
  Осталось просто дождать честных трек-дней. Кодом чинить нечего.

## 📊 Оперативный снимок (дрейфует — истина в SYSTEM_BRIEFING)

| Поле | Значение |
|---|---|
| GoLive | ⛔ **27/29 pass** — NOT READY (2 time-gated блокера) |
| Трек | **25/30** evidenced (anchor 2026-06-22, target ~2026-07-21) |
| Portfolio | ~$100,456 (+0.46%/24d), deployed 80% / cash 20%, ✅ policy-compliant |
| Аллокация | T1 45% · T2 35% · cash 20% · expected APY ~8.35% |
| Агенты | 54 загружено (`launchctl`, после чистки), agent_health nominal |
| KANBAN | v12.80 · done 1358 · 65 стратегий · 33 адаптера |

**GoLive блокеры (только ожидание, не баги):** `gap_monitor_30d`, `min_track_days_30` — оба
= 24/30 evidenced трек-дней, ждать ещё 6.

## 📋 Активные задачи

- [in progress] ENV_SETUP_BRIEF_v3 — Этапы 1–4, 6, 7 выполнены (память / Owner Decisions / протокол
  оркестратора / наблюдение :4455 / Inbox 3-входа / Obsidian-база знаний + промоушен `#promote`);
  остался **Этап 8 (smoke-test)** — по подтверждению владельца.
- [waiting] Go-live — накопление трек-дней до 30 (пассивно).

**⚠️ Амендмент к Этапу 6.3 (owner, 2026-07-15) — реализовать при Этапе 6:** разбор inbox
классифицирует сообщение на ЗАДАЧА → карточка с критериями / ИДЕЯ → `docs/ideas/` с датой (без
задачи) / НЕПОНЯТНО → `Needs Owner`. Telegram-бот отвечает: «создал задачу…» / «записал как идею» /
«есть вопрос — смотри карточку». Детали — journal `2026-W29.md`.

## 🗂️ Последние решения (одной строкой → ADR)

- **Hardening (автономный цикл, 2026-07-16, #13):** очередь пуста (inbox/owner-done/promotions/loose-notes=0)
  → диверсифицировал от owner_queue/адаптеров/CLI/router → покрыл непокрытые **fail-safe ветки**
  `spa_core/telegram/ask_router.py::classify_and_answer` — ЖИВОЙ классификатор каждого Telegram-сообщения
  владельца (вопрос/задача/непонятно), общий для бота (`_classify_route`) и event-driven intake.
  Документированный контракт «любая ошибка → `unclear`» был покрыт лишь наполовину (5 тестов). Регрессия в
  этих ветках = спурьозные карточки или сфабрикованный ответ на живом owner-пути. +8 регресс-тестов (5→13):
  **rc≠0** (claude non-zero exit — stale-stdout НЕ утекает в ответ), **пустой/whitespace stdout**,
  **`subprocess.TimeoutExpired`** (самый вероятный реальный сбой), **UNCLEAR без 2-й строки**→дефолт-переспрос,
  **QUESTION с пустым телом**→плейсхолдер, **регистро-/пробел-устойчивость маркера** (`task`/`Task`/` TASK `→task;
  lowercase `question`→сохраняет тело). Модуль НЕ менял (только тесты, инвариант #16). Замечено (НЕ чинил молча —
  риск ложных карточек): `TASK: <текст>` одной строкой → `question` (head≠`TASK`); если владелец подтвердит баг —
  карточка. 13/13 + 37 смежных зелёные. Пуш кодом+STATE+journal на origin. НЕ трогал risk/kill/трек/site/агентов;
  owner-done не ставил. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #12):** очередь пуста (inbox/owner-done/promotions=0; `ingest-notes`
  без свободных заметок) → диверсифицировал от внутренностей `owner_queue`/адаптеров на уровень **точки входа**:
  `scripts/orchestrator_queue.py` — детерминированный CLI, через который LaunchAgent-оркестратор
  (`com.spa.orchestrator`) КАЖДЫЙ цикл дёргает весь протокол (`list`/`set-status`/`create`/`ingest-notes`/
  `promotions`/`notify`); на origin **0 выделенных тестов**. +17 сквозных `main(argv=…)`-тестов
  (`spa_core/tests/test_orchestrator_queue_cli.py`, новый): exit-коды, JSON-контракт `_card_dict`, фильтры;
  **инвариант #14 `owner-done`→REFUSED exit 2** в `set-status` И `create` (карточка не тронута/не создана);
  `create` (файл+путь+дефолт-статус+`--field`+`--body-file`), `ingest-notes` (пусто / русская заметка→карточка),
  `promotions` (JSON+human через мок), `notify` (**`--check` НЕ идёт в send-путь** / обычный send «OK» с верным
  path+dry_run — реальный бот/Keychain НЕ тронут, замокан). Герметично: `queue.TRACKER_DIR`/`INBOX_NOTES_DIR`→tmp,
  модуль по файловому пути (`importlib`, `scripts/`≠пакет). CLI НЕ менял — только тесты (инвариант #16). 17/17 +
  75 смежных зелёные. Пуш кодом+STATE+journal на origin. НЕ трогал risk/kill/трек/site/агентов; owner-done не
  ставил. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #11):** очередь пуста (inbox/owner-done/promotions=0) →
  диверсифицировал от owner_queue-slug/intake/адаптеров/`safe_site_push` → соседний НЕпокрытый файл того же
  human-in-the-loop контура: `spa_core/owner_queue/notify.py` (owner-Telegram уведомление, инвариант #8).
  На origin покрыт лишь ОДНИМ happy-path тестом на `build_message`. +9 регресс-тестов
  (`spa_core/tests/test_owner_notify.py`, файл новый): `build_message` repo-relative путь + basename-fallback
  out-of-repo (`ValueError` на `relative_to` → голое имя, без краха) + HTML-escape + amended §2.4 заголовок;
  и КЛЮЧЕВОЙ инвариант **«уведомление НИКОГДА не роняет оркестратор»** — `notify_needs_owner` проглатывает
  бросок бота на `send_message` / в `__init__` (нет creds) / falsy-возврат; `dry_run` не трогает бота;
  happy-path шлёт с `parse_mode="HTML"`. Герметично: фейковый бот через `sys.modules` (реальный Keychain-бот
  не импортируется). 9/9 + 64 смежных зелёные. Модуль НЕ менял — только тесты (инвариант #16). Пуш кодом,
  STATE/journal из worktree на origin/main (локаль 969 позади). НЕ трогал risk/kill/трек/site/агентов;
  owner-done не ставил. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #10):** очередь пуста (inbox/owner-done/promotions=0) →
  диверсифицировал от `owner_queue`/адаптеров → `scripts/safe_site_push.py` (единственный санкционированный
  путь авто-шипа сайта, ADR-OWN-2026-07-autoship; на origin было **0 тестов**). Починен **реальный
  латентный баг** в `_route_to_owner_card`: вызов `create_card(card_type="owner-decision", …)` при сигнатуре
  `create_card(tracker_type=…)` → `TypeError` на КАЖДОМ gated site-push (воспроизведено эмпирически) →
  owner-карточка **не создавалась** и owner **не уведомлялся** — human-in-the-loop (инвариант #8) молча
  разорван (push оставался fail-closed, но владелец слеп к застрявшей owner-gated правке). Заодно чинён
  basename-баг notify (использовал `Path.name` вместо полного пути → `load_card` бы падал `FileNotFoundError`).
  Фикс: `tracker_type` + полный `Path` из `create_card`; **CLEAN/GATED/ERROR ветки решения гейта не тронуты**.
  +4 регресс-теста (`spa_core/tests/test_safe_site_push.py`, класс имел 0): gated→карточка+notify полным
  путём (падает на баге до фикса — проверено), guard-error→fail-closed, clean→batch с маркером
  `SPA_SITE_PUSH_VERIFIED=1`, no-site-files→guard пропущен. 4/4 + 49 смежных owner_queue зелёные. Пуш кодом,
  verified на origin (basename-collapse готча сработала на `/tmp`-worktree путях → 2 root-дубля удалены
  через API, файлы перепушены на верные пути `scripts/`+`spa_core/tests/`, root чист 404/404). НЕ трогал
  risk/kill/трек/site-copy/агентов; тесты только добавил; owner-done не ставил. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #9):** очередь пуста (inbox/owner-done/promotions=0) →
  диверсифицировал от `owner_queue` (циклы #2–#8) в домен адаптеров. Починен **fail-CLOSED-баг**
  в `spa_core/adapters/ethena_susde_adapter.py::_norm_apy`: out-of-band нормализованный APY молча
  **клампился** до правдоподобных 50% (`_clamp`, строка 238) → обвал доходности <1% у percent-источника
  мис-масштабировался в ~90%→50%, показывался «живым здоровым» и глушил advisory-anomaly (`<3%`) — нарушение
  инварианта #2 / `apy_contract`. Теперь вне `[0, 0.50]` → `None` (fail-close на next-source/cached-stale),
  вместо фабрикации; `bool`/`inf` тоже fail closed. **Ноль изменений в полосе 0–50%.** Held-позиция `susde`
  обслуживается ДРУГИМ адаптером (`SusdeAdapter` T3) — не затронута. +17 регресс-тестов (класс имел 0):
  17/17 + 242 смежных + 116 classifier зелёные. Пуш кодом, verified на origin (fail-closed-строка +
  `@classmethod`, root чист). НЕ трогал risk/kill/трек/site/агентов; тесты только добавил; owner-done не
  ставил. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #8):** очередь пуста (inbox/owner-done/promotions=0) →
  диверсифицировал от owner_queue → починил **реальный баг корректности** в живом event-driven intake
  (`spa_core/owner_queue/intake.py`): `partial_note` (вердикт `PARTIAL` из `history_check`, §6.6/§1a)
  СТАВИЛСЯ, но НИГДЕ не читался (dead variable) → пометка «похоже на …, проверь» молча терялась во всех
  3 ветках (task/idea/unclear). Протокол §1a требует её и в теле карточки, и в Telegram-ответе. Ввёл
  `partial_body`+`partial_tg`, вплёл во все ветки; NEW/DONE/… без изменений. +4 регресс-теста
  (`test_owner_intake.py`, `_wire` теперь captures notify + изолирует `Q.TRACKER_DIR`). 45/45 смежных
  зелёные. Пуш кодом (basename-collapse готча сработала→починена: root-дубли удалены, верные пути
  верифицированы на origin). НЕ трогал risk/kill/трек/site/агентов; тесты только добавил. Детали — journal `2026-W29.md`.
- **Автономный цикл (2026-07-16, #7, inbox-cadence):** разобрана inbox-задача владельца «оркестратор
  раз в 1 час, а не раз в 3 часа». `history_check` + верификация → **§6.6 DONE**: уже исполнено ранее
  (origin-коммит `6f5a26504` cadence 3h→1h; `plist StartInterval=3600`; загруженный агент подтверждён
  `run interval = 3600 seconds`). Дубль не создавал — bookkeeping: inbox-карточка закрыта `done` (§6.4),
  STATE поправлен (кадэнс 3ч→1ч), `own-23` аннотирована (владелец фактически ответил «ежечасно»,
  owner-done за ним — инвариант #14), Telegram-ответ владельцу по-человечески отправлен. Кода/сайта/тестов
  не трогал; risk/kill/трек/агентов не трогал. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #6):** очередь пуста (inbox/owner-done/promotions=0) →
  **сознательно диверсифицировал** от `owner_queue` (циклы #2–#5 подряд его правили) → покрыл соседний
  критичный НЕпокрытый модуль `scripts/build_agent_registry.py` (детерминированный SSOT флота 58 агентов,
  кормит память И дашборд `/admin/agents`) — на origin было **0 выделенных тестов**.
  `spa_core/tests/test_build_agent_registry.py` (+17 герметичных тестов, `_launchctl`/`_retired` замоканы,
  `_LAUNCH_DIR`→tmp): `_schedule` (8 форм), три класса флагов проблем (retired-загружен / не-reboot-safe /
  drift), допуск `last_exit` (−15/0 чисто vs ненулевой флагается), role-rollup исключает retired.
  Модуль НЕ менял — только тесты (инвариант #16). 17/17 + 21/21 смежный `test_api_agents`. Пуш кодом,
  verified на origin (верный путь, root чист). НЕ трогал risk/kill/трек/site/агентов. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #5):** очередь пуста (inbox/owner-done/promotions=0) →
  DRY-фикс реального дубль-бага: `spa_core/owner_queue/intake.py` держал СОБСТВЕННУЮ копию `_slug` без
  Cyrillic→Latin транслита (цикл #3 чинил только `queue._slug`) → русские заголовки ИДЕЙ схлопывались
  в `docs/ideas/<дата>-note.md`. Удалил дубль (+осиротевший `import re`), intake переиспользует
  каноническую `queue._slug`. +2 регресс-теста (`spa_core/tests/test_owner_intake.py`: русский заголовок →
  читаемое имя, не `-note.md`; имя == `queue._slug`). 2/2 + 53 смежных зелёных. Пуш кодом, verified на
  origin (верные пути, без basename-collapse). НЕ трогал: risk/kill/трек/site/агентов; тесты только
  добавил. Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #4):** очередь пуста (inbox/owner-done/promotions=0) →
  добавлено регресс-покрытие критического дедуп-пути `spa_core/owner_queue/history_check.py` (§6.6 —
  обязательная проверка истории перед созданием карточки), у которого на origin было **0 тестов**.
  `spa_core/tests/test_history_check.py` (+21 тест): `is_duplicate` (только DONE/IN_PROGRESS/REJECTED
  подавляют карточку), парсинг вердикта (first-token upper-case, тело-ответ), и главное — **fail-safe→NEW**
  на любой сбой (non-zero exit / исключение / пустой вывод / мусор-вердикт), т.к. молчаливая поломка этого
  парсинга снова начнёт плодить дубли. Subprocess замокан (без реального `claude`, офлайн-CI). 21/21 +
  51 смежных owner_queue зелёных. Пуш кодом, verified на origin (верный путь, без basename-collapse).
  НЕ трогал: risk/kill/трек/site/агентов; тесты только добавил. Детали — journal `2026-W29.md`.
- **Автономный цикл (2026-07-16, #3, inbox-task-readable-card-ids):** исполнена owner-задача — **читаемые
  имена карточек**. `_slug` (`spa_core/owner_queue/queue.py`) получил Cyrillic→Latin транслит (русские
  заголовки схлопывались в `note`); имя файла = читаемый slug (`inbox-dobavit-knopku-naverh.md`), таймстамп
  из имени убран (дата осталась в `created:`), коллизия → суффикс `-2`/`-3`. Идея-файлы `docs/ideas/` тоже
  стали читаемыми. Это внутренние имена файлов, НЕ site-copy (транслит там запрещён). `/status`/`notify.py`
  и так показывают title, не ID — правки бота не требовалось. Старые карточки не переименовывал (форвард-изменение).
  +3 теста (18 owner_queue / 29 смежных зелёных). Пуш кодом, verified на origin. Карточка закрыта `done` (§6.4).
  Детали — journal `2026-W29.md`.
- **Hardening (автономный цикл, 2026-07-16, #2):** закрыт **dead-letter баг owner-queue** — `create_card`
  писал `status:` только `if status` → карточка без статуса невидима во всех фильтрах; теперь статус
  обязателен + `set_status` вставляет строку; починена карточка `212059-apy`. +3 теста. (Детали — journal.)
- **Hardening (автономный цикл, 2026-07-16):** закрыт **fail-open в owner-gate**
  (`scripts/check_owner_gate.py`, Class B) — line-level dynamic-suppressor пропускал запечённое число
  доходности, если на строке был динамический токен (`{snap.x}`); теперь подавление per-span
  (`_DYNAMIC_WINDOW=6`, строго fail-CLOSED). +2 регресс-теста, 17 зелёных. Пуш кодом (не ADR — правит баг,
  не меняет решение/пороги). Детали — journal `2026-W29.md`.
- **Автономный цикл (2026-07-15, inbox-569xl):** исполнена owner-задача из Telegram — написана
  [`docs/CHECKUP_NOTIFICATIONS_SPEC.md`](CHECKUP_NOTIFICATIONS_SPEC.md) (уведомления DeFi Checkup:
  e-mail+Telegram, deeplink по $-материальности, weekly digest, honesty-gated). Дизайн-документ, НЕ код;
  сборка — только после `#approved` владельцем (owner-gates в §8 спеки: RESEND/own-07, пороги/own-16,
  отдельный TG-бот, кадэнс). Карточка закрыта `done`. Детали — journal `2026-W29.md`.
- **ADR backfill (автономный цикл, 2026-07-15):** выписаны 3 ADR-файла, бывшие «backfill TODO» в
  INDEX — [ADR-050](decisions/ADR-050-riskpolicy-governance-layer.md) (RiskPolicy→governance / API auth /
  exec-bypass), [ADR-053](decisions/ADR-053-rtmr-sense-loop.md) (RTMR sense-loop), [ADR-YL-012](decisions/ADR-YL-012-spa-swarm.md)
  (SPA Swarm advisory). Запись уже принятых решений, без изменения risk-логики. Детали — journal `2026-W29.md`.
- **Правило (owner, 2026-07-15):** ничего «в воздухе» — любое решение/договорённость/пожелание из
  любой сессии фиксировать до её конца (решение→ADR+STATE, задача→Inbox, идея→docs/ideas/). Внесено в CLAUDE.md §Протокол-сессии п.4.
- **STOP автономного ROADMAP-loop (owner, 2026-07-15):** сессия `1345fef8` (PID 2853, запущена 02.07,
  «full autonomy») ОСТАНОВЛЕНА, полномочия отозваны. Состояние заморожено в `MIGRATION_FREEZE.md`
  (8 ships, остаток owner-gated, in-flight работы не было). Пережила Этап-0 т.к. это не LaunchAgent.
- **Автономный цикл ВКЛЮЧЁН (owner, 2026-07-15):** `com.spa.orchestrator` armed, governed autonomy,
  каждые 3ч (headless claude под протоколом; очередь+hardening+мелкие фичи; owner-gated→карточки; тесты не
  трогать молча). Выключить: `launchctl bootout gui/$(id -u)/com.spa.orchestrator`. **Пересмотр кадэнса ~17.07** (own-23).
- **Единственная активная сессия SPA (owner, 2026-07-15):** первое окно закрыто, roadmap-loop
  полностью завершён; env-setup сессия (PID 94256) — теперь главная и единственная сессия SPA.
  Конкурентного клоббера больше нет. Работа — под новым протоколом (owner-gated карточками, announce,
  тесты не трогать молча). _(LOGOS `scanner.run` — отдельный проект, не SPA.)_
- **Ветка `yield-lab-scaffolding` на ревью (артефакт остановленной сессии):** локальная (не на origin),
  ~116 коммитов / 173 файла, docs-first Yield Lab research-слой, последний коммит 03.07. НЕ смержена.
  Мержить/нет — карточка `own-22` (риски: docs-overlap с origin, CLAUDE.md-конфликт, API-push-only).
  Точка восстановления — `PROGRESS.md` на ветке. Детали — `MIGRATION_FREEZE.md`.

## ⏸️ Отложено до MVP 2–3 (не потерять)

- **P3-стабы Yield Lab** (`docs/23,24,26,39–43`) на ветке `yield-lab-scaffolding` — оставлены как
  заглушки «TODO: expand at MVP 2-3» (часть 23/24/25/26/39–44 уже расширена в remediation-sprint;
  остаток — по мере строительства Yield Lab). Разворачивать при MVP 2–3, не раньше.
- **Остаток ROADMAP v2 (незавершённое остановленной сессии)** — durably в `docs/ROADMAP_2MONTH_EISENHOWER_v2.md`
  (не потеряется). Сессия аннотировала: `🔎 VERIFIED` = сделано (Q1-12,Q2-5b,8,9,15,17,18), `⚠️ NOTE` = отложено.
  Реально открытые код-задачи: Q2-7 (public /pilot+DD), Q2-11/12 (Uniswap-LP detection, отложены),
  Q2-13 (defenses→RTMR), Q2-14 (research-changelog → карточка own-20), Q2-16 (per-refusal SEO), Q2-19
  (non-custodial advisory pilot), Q3-7 (page-sprawl dedupe). Owner-gated Q1-5/6, Q2-3/4/5 → карточки own-*.
  **НЕ подхватываю автоматически** — приоритеты выбирает владелец (карточками, по одной, под новым протоколом).
- ENV_SETUP_BRIEF_v3 smoke-test пройден (owner-done→ingested, голосовой inbox, декомпозиция) → [ADR-TEST](decisions/ADR-TEST-smoke-2026-07-15.md).
- Two-tier kill-switch SOFT −5% / HARD −10% inclusive → [ADR-048](decisions/ADR-048-two-tier-kill-switch.md) (+ADR-034).
- RiskPolicy → governance-слой, API auth, exec-bypass закрыт → ADR-050.
- RTMR real-time monitoring sense-loop → ADR-053.
- Site Custodian (защита earn-defi.com от stale-чисел) → [ADR-YL-011](decisions/ADR-YL-011-site-custodian.md).
- SPA Swarm (5-слойный рой, advisory) → ADR-YL-012.
- Tier naming Conservative/Balanced/Aggressive; APY «up to {max}%»; /pilot = терминал воронки
  (форма, не mailbox); FAQ переписан под paper-стадию; /admin за Cloudflare Access;
  per-sleeve BELOW_FLOOR вердикты скрыты до улучшения → см. закрытые Q-OWN (ADR-OWN-2026-07).

## ❓ Открытые вопросы владельцу (трекер `nimbalyst-local/tracker/own-*.md`, статус `needs-owner`)

- **own-07** — включить письма-подтверждения подписки: `RESEND_API_KEY` + `WALLET_REF_SALT` на прод Railway.
- **own-08** — единая расшифровка «SPA» на сайте (3 варианта, дрейф). Рекомендация: «Smart Passive Aggregator» везде.
- **own-11** — /pilot «живой человек» (имя/фото/календарь) + рабочая почта (напр. `invest@earn-defi.com`).
- **own-13** — подтвердить формулировку early-access waitlist (M7). Рекомендация: ДА, честно.
- **`212059-apy`** (site-custodian APY-алерт) — работа исполнена (owner ответил в чате, pid67426, commit
  e01e042f); карточка была невидима (баг статуса, починен) → теперь `needs-owner`, нужен лишь финальный
  клик owner-done владельца. Действий по коду не требуется.
- ~~own-06~~ — **РЕШЕНО/ingested:** проверил вживую — approvals на проде `status=scanned`, ключ работает.
  Возврат задачи был петлёй ежечасного `defi-checkup-build-cycle`; в его SKILL.md добавлен LOOP GUARD
  (проверять вживую перед докладом). Действий владельца не требуется.

> Мигрировано в files-first трекер (Этап 2). `docs/OWNER_DECISIONS_NEEDED.md` — теперь указатель.
> Отвечать: перевести карточку `needs-owner → owner-done` (в Nimbalyst или правкой `status:`).

## 👁️ Наблюдение (Этап 4)

- **Резервный монитор сессий/задач:** `claude-code-kanban` → **http://localhost:4455**
  (агент `com.spa.cc-kanban`, KeepAlive, read-only над `~/.claude`). Наблюдает headless-сессии
  оркестратора, которые Nimbalyst НЕ показывает.
- **Nimbalyst vs headless (проверено 4.2):** Nimbalyst трекает только сессии, которые запускает
  сам (`ai_sessions` = 1 строка на запущенную им сессию; 165 внешних SPA-транскриптов в `~/.claude`
  он не видит). Вывод: **headless — через claude-code-kanban:4455**; Nimbalyst — для интерактива,
  очереди, задач и мобильных аппрувов.

## 🔗 Ориентиры

- Инварианты: `CLAUDE.md` + `.claude/rules/`. Реестр решений: `docs/decisions/INDEX.md`.
- Живой статус: `docs/SYSTEM_BRIEFING.md`. Журнал: `docs/journal/`.
- Идеи (не действовать): `docs/ideas/`. Черновики правил: `docs/rules-draft/`.
- Протокол оркестратора: `docs/ORCHESTRATOR_PROTOCOL.md`. Очередь: `nimbalyst-local/tracker/`.
