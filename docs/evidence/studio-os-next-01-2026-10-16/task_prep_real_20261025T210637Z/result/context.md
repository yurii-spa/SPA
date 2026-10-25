# Role context pack — architect (role-pack/1)

> DERIVED — files and git are canonical; this pack is a projection. Generated 2026-10-25T21:09:52+00:00. context preparation only — no model call, no provider routing, no permission.

## Role

- role_id: `architect` · current participant: ChatGPT (the role is stable; the participant (vendor/model) is replaceable and gains no permission by being selected)
- authority: | **ChatGPT — Architecture Review Board (ARB)** | architecture, conflict/supersession review, acceptance, precise assignments for Claude | decides architecture only after a FRESH bootstrap; never implements, never approves owner subjects | ARB-CONTINUITY-01 directive (2026-10-07), ADR-610 |

## Owner intent

- Last confirmed by the owner: **2026-10-01** (directive «THREE DEFI PAPER PORTFOLIOS — STRATEGY MECHANICS, OPERATIONS AND WEBSITE»).
- Latest owner clarification: **2026-10-25** — support the owner's Claude Pro subscription for Studio OS management through the official Claude Code CLI; included usage only, no automatic paid continuation (same owner decision below).
- Latest sequencing directive: **2026-10-25** — test management with the existing Claude subscription now; defer real local-model probes until the owner has a new Mac mini. No hardware purchase is authorized here. Owner priority directive: **2026-10-23** — model-independent workers and architect, P1; bounded verification ([owner decision](decisions/ADR-OWN-2026-10-23-model-independent-studio.md)).
- Continuing owner directive: **2026-10-16** «STUDIO-OS-NEXT-01 — next stage of Earn DeFi Studio OS under the ARB plan» (ADR-763, item 17).

Roadmap item 17: **STUDIO-OS-NEXT-01 · next stage of Studio OS under the ARB plan** — implemented; candidate handed to ARB 2026-10-18, NOT ARB-accepted (owner directive 2026-10-16, ADR-763). Packages in order: (1) this roadmap + the 34-item reconciliation below; (2) Mac resources and cockpit build speed (`findings_bridge` ~5 GB RSS and swap 92.9 % before the 2026-10-15 reboot, `mission_build` 17–22 min, stale `director_*` names in `architecture/resource_policy.json`, RAM/swap/disk told apart in alerts); (3) backup coverage table, gaps closed in a candidate with a restore drill, then a PREPARED (not executed) decision to retire `com.spa.weekly_backup` with rollback; (4) voice path to exactly one card and a plain status for the owner, re-send and connection failure; (5) ADR-762 version-bound confirmation in a separate candidate (not wired into the live confirmation mechanism), then package value history, plain reasons for warnings, read-only check buttons, financial evidence. Real capital $0; no limit or tolerance changes; no new markets; nothing deleted. Status 2026-10-16 (each claim with its level): (2) resources — implemented + live-verified: cockpit build 1175 s → 14 s in production, CORRUPT cells 0, findings_bridge census peak 7.25 GB → 224 MB, frozen-data equivalence 0 differing fields (`cc98a1ba`); (3) backups — implemented, restore-drilled in scratch and into a clean clone (`2e173313`, `5bc89182`), first nightly run with the new sets not yet observed; iCloud upload to Apple NOT MEASURED

## Revision (measured from git)

- branch: integ/studio-os-next-01-stab
- head: 20b0652e2da26069ba69ef6a69c6a8c0d7175b7a
- server_branch_head: 04f41fbca74eeeed49bbf040616e8fc3accff4d7
- head_equals_server: False
- verified_code_sha: 5499ceca482db091027364cac2b5263ea95cf342
- verified_is_ancestor_of_head: True
- head_code_is_verified: False
- code_changed_since_verified: ['spa_core/studio_os/memory/arch_review.py', 'spa_core/tests/test_task_prep.py']
- changed_since_verified: ['docs/ROADMAP.md', 'docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md', 'docs/evidence/studio-os-next-01-2026-10-16/ci_control_2026-10-25_5499ceca4_run40216933079.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_2026-10-25/ARB_REVIEW.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_2026-10-25/README.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/fragments/01_intake_mission_intake.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/fragments/02_dispatcher_cockpit_dispatch.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/fragments/03_loop_cockpit_loop.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/fragments/04_task_prep_arch_review.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/fragments/05_state_voice_path_STATUS.md', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/launch_conditions.json', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/model_roles.tmp.json', 'docs/evidence/studio-os-next-01-2026-10-16/task_prep_real_20261025T210637Z/request.txt', 'docs/journal/2026-W43.md', 'spa_core/studio_os/memory/arch_review.py', 'spa_core/tests/test_task_prep.py']
- dirty: []

## Decisions cited

- ADR-762: ADR-762 · Пульт владельца: детерминированное представление над Company Truth и граница защиты подтверждения — `docs/decisions/ADR-762-director-os-owner-view-model-and-version-bound-confirmation.md`
- ADR-763: ADR-763 · STUDIO-OS-NEXT-01: следующий этап Earn DeFi Studio OS по плану ARB (директива владельца 16.10) — `docs/decisions/ADR-763-studio-os-next-stage-owner-directive-2026-10-16.md`
- ADR-768: ADR-768 · Контрольный прогон CI по частям — единственный источник ПОЛНОГО вердикта набора — `docs/decisions/ADR-768-ci-control-sharded-verdict.md`
- ADR-OWN-2026-10-23-model-independent-studio: ADR-OWN-2026-10-23 · Model-independent Studio OS and bounded verification — `docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md`

## Task · goal

- Пункт ROADMAP **17 STUDIO-OS-NEXT-01** (ADR-763): стабилизация набора тестов и измеримость критерия §49 «No
  regression» под управлением ARB. Стабилизация и NO_REGRESSION ARB НЕ приняты.
- Приоритет владельца **P1 STUDIO-OS-MODELS-01** (ADR-OWN-2026-10-23-model-independent-studio): модель-независимые
  роли архитектора и исполнителя; первый срез — переносимый пакет контекста роли (сделан, см. §3). Роутер моделей —
  отдельный следующий шаг, НЕ сделан.
- Реальный капитал — $0; живого исполнения нет.

## Task · revision

| что | значение |
|---|---|
| ветка / дерево | `integ/studio-os-next-01-stab` · `/tmp/spa_wt_integ` |
| код этапа 8 | `3c40ed1377bc535ea88f2ec17b0a2f41485a99c6` — полный CI 39935715615: RED 12/12, 3 failed, новых против базы 1 (B-9) |
| кандидат 1 | `3da13e7bf0e5b48961ef1d6a6110bc9552bfa32c` — правка B-9 и пакет роли; полный CI 40026699075: RED 12/12, 4 failed (B-9 закрыт; 2 новых разобраны и исправлены в кандидате 2) |
| код после ARB этапа 8 | `d12af8debbca09b4e40a6419a76a4a512ec77e63` — правка B-10 и копии `*.excerpt.json`; полный CI 40031634618: RED 12/12, **2 failed** (такт производителя §49 ×2), новых против базы 0, исправлено 67 |
| код MODELS-01 инкремента 2 (принят ARB как контракт) | `86d9c662a0df31fc78dcf67cf6a919ff482e9264` — контракт провайдера, конфигурация ролей, очистка role-pack, `__all__`; полный CI 40069391393: RED 12/12, 2 failed (такт §49 ×2), новых против базы 0 |
| код MODELS-01 инкремента 3 (история) | `30ca5abc46a42a3fcf8910113f62d4edde967629` — `memory.answer.ask` через контракт, cwd CLI, 125 ⇒ ownership_unresolved и B-11; CI 40097091074: RED 12/12, 2 failed (такт §49 ×2). Принят ARB 24.10 |
| проверенный код до голосового пакета | `5a0d497f0ce7c9f7fe8740cf8e982ff1eb66ec0e` — включает принятый инкремент 4/B-12 (`393faa72d`) и подготовку локальной пробы с закрытыми R1/R2. CI 40190831822: 135826 всего, 135105 passed, 2 failed (§49), 719 skipped, 12/12. Принят ARB 25.10 в указанном объёме |
| кандидат голосового пакета | `33b3219ac8b59ca56d49fa6b1e35fdcc04febf4c`, CI 40209078724: 135827 всего, 135106 passed, 2 failed (§49), 719 skipped, 12/12. Правка уведомлений `391d2c75d` принята в кандидате; не доставлена |
| **актуальный проверенный кандидат** | **`5499ceca482db091027364cac2b5263ea95cf342`**, CI **40216933079**: 135848 всего, 135127 passed, 2 failed (§49), 719 skipped, 0 ошибок/не получено/ошибок сбора, 12/12. Артефакт и digest сверены ARB; новых failed node IDs против `33b3219ac` нет. Task-prep пока требует R1/R2. Не зелёный CI, не NO_REGRESSION, не production-доставка |
| база ветки | `62fe88b48` (run 39832458873) |
| последующий HEAD | docs-only поверх кандидата (этот файл и evidence) — своим прогоном не проверен |

## Task · decisions

- **Документы владельца** `docs/ROADMAP.md` и `docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md`
  зафиксированы без правок (коммит `47e9ce053`); строка реестра `docs/decisions/INDEX.md` добавлена, иначе
  `test_memory_in_git` краснел «решение вне реестра».
- **B-9 исправлен (причина доказана).** `test_decision_logger.py` импортировал `spa_core.agents.decision_logger` под
  подделкой `database` и оставлял в модуле `get_connection` = MagicMock; `test_investor_report::test_audit_trail_from_temp_db`
  позже в том же процессе получал пустой ответ без исключения (в CI нет захваченного `log.error` — исключения не было).
  На Mac не виден: нет `web3`/`aiohttp`, `conftest` импорт-пробует `spa_core` и грузит настоящий слой БД раньше.
  Воспроизведено на временной копии с conftest как в CI: 1 failed → после правки 45 passed. Правка — в виновнике
  (`cce8366ee`), утверждения не тронуты; положительный контроль — чистый подпроцесс (без правки красен).
- **MODELS-01, инкремент 1:** `python -m spa_core.studio_os.memory role-pack` (`spa_core/studio_os/memory/role_pack.py`) —
  пакет из существующих файлов (роль из ARCHITECT_CONTEXT §3, намерение из ROADMAP, задача из хендовера, ADR по
  ссылкам, ревизия измерена git'ом); нового хранилища нет, модели не зовёт.

## Task · verification

- Актуальный полный результат — **40216933079** на **5499ceca4**, числа и ограничения в §2. Наблюдавшийся
  HEAD `04f41fbca` добавляет только запись CI и журнал; своего отдельного полного прогона у него нет.
- Исторический результат этапа 8 — о `3c40ed137` (39935715615): 135 651 · 134 929 passed · 3 failed (такт производителя
  §49 ×2; `test_investor_report` — B-9).
- Кандидат 1 `3da13e7bf`: ci-control 40026699075 — RED 12/12, 135 663 · 134 940 passed · 4 failed: такт производителя §49 ×2,
  `test_prior_run_operand_census` (мои копии `exit.json`/`run.json` в evidence — неоднозначные имена; переименованы),
  `test_live_paths` (B-10, порядок набора; исправлено). B-9 в CI закрыт. Census 40026699805 — о `3da13e7bf`.
- Конечный код `d12af8deb`: ci-control 40031634618 — RED 12/12, 135 663 · 134 942 passed · 2 failed (такт производителя §49 ×2),
  новых против базы 0. Историческая запись о census 40031633042: на момент её составления прогон не завершился.
  Это НЕ текущий статус и НЕ поручение повторить прогон; актуальный результат брать из датированного evidence.

## Task · open_problems_and_next_step

1. **B-12 исправлен и принят ARB** (`b736e6d1d`, проверенный код `393faa72d`, CI 40131303808).
2. Решение о подключении производителя §49 (пакет `arb_packages_2026-10-23/s49_connection_package.md`) — за ARB/владельцем.
3. MODELS-01: инкременты 2 и 3 приняты ARB (`86d9c662a`, `30ca5abc4`); инкремент 4 `memory arch-review` и B-12
   приняты ARB на `393faa72d` (CI 40131303808, 2 прежних падения §49). Повторной приёмки старого пакета не требуется.
4. Backlog B-1…B-8 — `stage8_2026-10-23/BACKLOG_census_findings.md`.

**Подготовка локальной пробы ПРИНЯТА ARB** на `5a0d497f0ce7c9f7fe8740cf8e982ff1eb66ec0e` (код `a490f2979`, CI 40190831822:
2 failed — такт §49, новых 0; не зелёный CI и не NO_REGRESSION) — `increment5-plan/ARB_REVIEW_2026-10-25_a2bdf7c09.md`,
раздел «Follow-up acceptance». R1/R2 закрыты. **Сама проба ОТЛОЖЕНА** решением владельца 25.10: «Claude сейчас, локальные
модели — после нового Mac mini» (ADR-OWN-2026-10-23, раздел «Owner sequencing directive»; ROADMAP). Покупка оборудования
и автоматический запуск этим не разрешены.

**Управленческий прогон уже выполнен:** `increment6-claude-management/`, Max, 1 попытка, 115,951 с.
**Голосовой пакет проверен ARB:** `voice_owner_check_2026-10-25/ARB_REVIEW.md`. Подготовка проверки с iPhone завершена;
сам владелец её ещё не проходил. Task-prep уже добавлен в существующий вход архитектора, демонстрация — на фикстуре.
Следующий объединённый пакет — R1/R2 и явная подпись о заявленных моделью полномочиях, затем один реальный ответ
Claude при подтверждении условий включённой подписки того же профиля; если условия неизвестны — не запускать вызов,
назвать недостающий факт. Срок/попытки и критерии — `task_prep_2026-10-25/ARB_REVIEW.md`. Без автоматического
исполнения, записи карточки или доставки. Не переделывать существующие входы и не повторять общий аудит.
Назначения моделей остаются null.
Подключение именно Pro и программная защита от платного продолжения не приняты; текущая проверка web-настройки
кредитов ARB и её пределы записаны в `increment6-claude-management/ARB_REVIEW.md`.

## Task · constraints

Разрешено: обычный push и CI только в `integ/studio-os-next-01-stab`; чтение уже идущих прогонов. Запрещено: merge,
`main`, force-push, публикация сайта, установки, расписания, перезапуски служб, рабочий трекер и `--apply`, удаления,
`git stash`, отмена чужих прогонов, RiskPolicy/ставки/лимиты, новые провайдеры моделей, платные API, локальные модели;
объявлять NO_REGRESSION или приёмку ARB; объединять результаты разных SHA.

## UNKNOWN

- none

Credential-like lines dropped: 0

## Inputs (sha256)

- `docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md` c0361440449c0061635658b47dac2b275a5d6cb00dfb2adb0e232a96469a1923
- `docs/continuity/ARCHITECT_CONTEXT.md` 61a52614a233b8226b3133e0b7e47afb1b53dbc508e88fb842881566c2fa33c6
- `docs/ROADMAP.md` e8ef80d34f95f783a2728ae4fe7c01e44b05c7d4b36ad910cd20fdac8382a41d
- `docs/continuity/state.json` 1f2d7113b1260c04833aca9420df939bbcf812006003d9d6b5f7609457adeed3

## Task fragments (explicit, sanitized)

### Fragment: 01_intake_mission_intake.md

# Excerpt: spa_core/studio_os/mission_intake.py lines 1-39 (at 9a07f8998, unchanged)

"""spa_core/studio_os/mission_intake.py — the ONE write action of the owner cockpit (ADR-760).

Owner 15.10: «голосовой ввод с телефона — огромный плюс». The cockpit stays read-only for
everything else; this module is the only place a cockpit request may write, and it may write
exactly one thing: a NEW inbox card through the SAME intake path the Telegram ``/task`` and voice
messages use (``spa_core.telegram.inbox_intake.save_inbox_task`` → ``owner_queue.create_card``,
status ``new``). It never executes, approves, answers, moves money or touches any other file.

Two operations, each guarded by :class:`IntakeGate` (the server calls ``gate.check`` first):

* ``transcribe(audio_bytes, content_type)`` — the SAME local offline whisper the Telegram bot uses
  (``inbox_intake.transcribe_voice``); audio ≤ ``MAX_AUDIO_BYTES`` and ≤ ``MAX_AUDIO_SECONDS``
  (measured by ``ffprobe`` when present; absent ⇒ the duration is «не измерена» and only the size
  limit applies — said in the answer, never silently). Whisper absent ⇒ a NAMED refusal
  ``WHISPER_UNAVAILABLE``, never an empty transcript.
* ``submit(text, kind, transcript; provenance)`` — one inbox card; ``kind`` ∈ idea/task/note.
  ``submission_id`` (made by the page when the composer opens, kept across retries) makes the
  write IDEMPOTENT: a card already carrying that id (any status) is returned with
  ``duplicate: true`` instead of a second card. The check-and-write runs under one lock
  (an in-process lock + ``flock`` on the tracker directory itself — no marker file is written).
  With an id, idempotency is by that id ONLY: a NEW composer session (new id) with identical text is
  a deliberate second note and becomes a second card (the open-twin merge of ``create_card`` is
  bypassed); without an id (an old page) the open-twin guard stays.
  Every cockpit card records its PROVENANCE as three separate things (ARB 16.10, :class:`Provenance`):
  the channel of arrival, the ESTABLISHED author (only from a server-side verified identity — never a
  client-supplied field) and the fixed authority-boundary line :data:`AUTHORITY_NOTE` (ADR-285), which
  never names the author: a record is never a permission, whoever wrote it.

Whisper outcomes are NOT collapsed (inv. #17): timeout ⇒ 504 ``WHISPER_TIMEOUT``, the process failed
⇒ 503 ``WHISPER_FAILED``, nothing heard ⇒ 422 ``EMPTY_TRANSCRIPT``, a transcription already running
⇒ 429 ``WHISPER_BUSY`` (one whisper at a time — ``_WHISPER_SLOT``).

Guards (fail-CLOSED; any doubt ⇒ refusal, nothing written):
  * a per-process CSRF token (``csrf_token()``; the page fetches it with a same-origin GET — a
    cross-site page cannot read it) must be echoed in ``X-Intake-Token``;
  * ``Origin`` must equal the listener's own origin (loopback for the local listener, the
    Access-protected public host for the public one); missing ⇒ refused;
  * the body type must match the operation; size limits; a small rate limit per operation.
"""

### Fragment: 02_dispatcher_cockpit_dispatch.md

# Excerpt: spa_core/owner_queue/cockpit_dispatch.py lines 1-33 (at 9a07f8998, unchanged)

"""spa_core/owner_queue/cockpit_dispatch.py — запись из пульта получает исполнителя БЕЗ человека.

Дефект, который это закрывает (ARB 16.10, живое демо). Сквозной путь пульта (ADR-763) довозил
запись до карточки ``new`` + ``intake_seen`` — и там она стояла: исполнителя назначил вручную тот
же агент, что отправил запись. Замер прод-трекера 16.10: из 48 переходов ``new → in-progress`` у
inbox-карточек за всё время циклом оркестратора сделано 7, ни одного — для карточки пульта; каждый
цикл с 15.10 начинал промпт с «ГОЛОДАЮЩИЙ ПРИКАЗ … взять ПЕРВОЙ» (``agent_orchestrator.sh``,
``STARVE_PREFIX``), и шаг 1 протокола (разбор ``new``) до записей пульта не доходил. Выбора
исполнителя для записи пульта не было нигде — ни в обёртке, ни в протоколе, ни в коде.

Новой системы здесь нет. Этот модуль — детерминированный шаг ВНУТРИ существующего часового цикла
(``com.spa.orchestrator`` → ``scripts/agent_orchestrator.sh``), вызываемый ДО сессии Claude:

* :func:`dispatch` — самая старая ПРИНЯТАЯ запись пульта (``status: new`` + ``intake_seen``, без
  захвата) берётся через ``cockpit_loop.take_card`` (захват шага 0b → проба → ``in-progress``),
  исполнитель — сессия цикла (``SPA_SESSION_ID``). Проба берётся ТОЛЬКО из объявления: поле
  ``acceptance_probe`` карточки или строка ``проба: <имя[:аргумент]>`` в тексте записи,
  проверенная реестром ``card_acceptance.validate_spec``. Угадывать пробу по смыслу текста
  запрещено (инв. #3 — приёмка без LLM; правило приёмки п. 2 — мерку не выбирает исполнитель).
  Пробы нет ⇒ карточка НЕ берётся и НЕ закрывается: «не принято» с причиной и следующим шагом
  (``cockpit_loop.record_no_probe``), одно уведомление; повторный прогон её не трогает, пока
  кто-нибудь не объявит пробу (тогда она снова кандидат).
* :func:`settle` — ПОСЛЕ сессии: перемерить собственную пробу карточки, взятой этим циклом
  (``close_verified``). «Сделано» ставит только ``satisfied``; иначе ``blocked`` с причиной —
  второго исполнения не бывает ни при каком исходе.
* :func:`rewake` — страховка потерянной побудки приёма: запись пульта без ``intake_seen`` старше
  порога ⇒ ещё раз тронуть ``inbox/.cockpit-wake`` (``mission_intake.wake_intake``). Приём сам
  здесь НЕ запускается — только штатная дверь launchd; повтор безопасен (``intake_seen``).

# LLM_FORBIDDEN — детерминированный выбор и учёт; LLM — только исполнитель в сессии цикла.
"""
from __future__ import annotations

### Fragment: 03_loop_cockpit_loop.md

# Excerpt: spa_core/owner_queue/cockpit_loop.py lines 1-42 (at 9a07f8998, unchanged)

"""spa_core/owner_queue/cockpit_loop.py — сквозной путь записи из пульта (STUDIO-OS-NEXT-01, ADR-763).

«запись из пульта → карточка → исполнитель → проверенный результат → понятное уведомление» —
из УЖЕ существующих частей. Этот модуль новой системы не заводит: он связывает звенья 3–5, у
которых до сих пор не было общей двери.

  1. Пульт — ``studio_os.mission_intake.submit`` (идемпотентность по ``submission_id``, автор,
     строка о границе полномочий ADR-285). Здесь не трогается.
  2. Приём — ``owner_queue.intake.run_note_intake``: метка ``intake_seen`` и «📥 Создал задачу»
     через долговечные исходящие ``data/intake_outbox.json``. Карточка остаётся ``new``: приём
     НЕ есть исполнение.
  3. Исполнитель — :func:`take_card`: тот же порядок, что предписан циклу (шаг 0b
     ``scripts/check_card_claim.py claim`` → ``orchestrator_queue.py probe`` → ``set-status
     in-progress``), одним вызовом. Повторная доставка (тот же исполнитель) — no-op; другой
     исполнитель получает ОТКАЗ — второго исполнения одной карточки не бывает
     (:class:`TakeRefused`). Карточка в работе без захвата тоже отказывает: кто её исполняет,
     не измерено, а «не измерено» ≠ «свободна» (инв. #2).
  4. Проверка результата — :func:`close_verified`: гоняет СОБСТВЕННУЮ пробу карточки
     (``card_acceptance.run_probe``) и закрывает ТОЛЬКО на ``satisfied``, записав
     ``verified_by_probe``. ``not_satisfied`` / ``unmeasured`` / нет пробы ⇒ карточка остаётся в
     работе, во frontmatter — причина и следующий шаг простыми словами.
  5. Уведомление — то же долговечное ``intake_outbox`` (ключ «карточка#событие») и блок «Мои
     записи» (``mission_control.cockpit_records`` → ``owner_view.my_records``).

Порядок записей — ради падения на ЛЮБОЙ границе:
  * закрытие: отметка ``verified_by_probe`` → ``set_status done`` → исходящие → отметка
    ``owner_notice``. Упали после ``done``, до исходящих ⇒ :func:`sweep_notices` (его зовёт
    каждый прогон приёма) дочистит уведомление. Упали до ``done`` ⇒ карточка в работе, повторный
    :func:`close_verified` перемерит пробу.
  * «не принято»: поля причины → исходящие → ``owner_notice``. Уведомление — одно на СМЕНУ
    состояния (``owner_notice`` хранит последнее отправленное состояние), не на каждый перемер.

Семантика доставки в Telegram — **НЕ МЕНЕЕ ОДНОГО РАЗА**, не «ровно один раз». Падение между
отправкой и вычёркиванием из исходящих, или отправка, ответ на которую потерялся, ПОВТОРИТ
сообщение. Дубль невозможен только в исходящих (ключ заменяет запись) и в решении «слать ли»
(``owner_notice``), но не в чате владельца.

Этот модуль НИКОГДА не ставит ``owner-done``/``owner-accepted`` (инв. #14) и не отвечает за
владельца: он закрывает inbox-карточку агента по её собственной пробе.

# LLM_FORBIDDEN — детерминированный учёт и сверка, никакого суждения модели (инв. #3).
"""

### Fragment: 04_task_prep_arch_review.md

# Excerpt: spa_core/studio_os/memory/arch_review.py lines 1-24 and 66-103 — task-prep (at 9a07f8998, committed, unchanged)

"""One command: a SAFE architecture review of one task by the chosen provider (STUDIO-OS-MODELS-01, inc. 4).

Lives in ``memory`` (next to ``role_pack``), not in ``model_roles``: the dependency runs memory → model_roles
only — the transport layer never imports its callers (held by ``test_memory_answer_via_contract``).

# LLM_FORBIDDEN

    python -m spa_core.studio_os.memory arch-review --handover <repo-rel handover> --task-id ID \
        --task "<one task>" --verified-sha <40-hex> --provider <id> --out DIR \
        [--roadmap-item 17] [--extra-context FILE ...] [--fixture F.json]

What it does — and nothing else:

1. builds the context with the existing :mod:`spa_core.studio_os.memory.role_pack` (role ``architect``,
   the given verified revision), plus small EXPLICIT extra fragments (implementation snippets, links),
   each sanitized by the same credential sanitizer and fingerprinted;
2. calls role ``architect`` through the existing contract (:func:`contract.execute`) with the provider
   named explicitly (repository assignments stay null — no routing);
3. writes ``DIR/context.md`` (exactly what the model saw), ``DIR/review.json`` (task id, revisions, context
   hash, provider, status, time, reported usage, completeness, parsed sections) and
   ``DIR/recommendation.md`` (facts → unknowns → decision with reason → acceptance criteria → one
   copyable task block for the implementer).

It never edits the roadmap, cards, ADRs or permissions and never records an owner approval: the output
...
#: ``--kind task-prep`` (ARB 25.10): the SAME seam turns ONE ordinary owner request into a reviewable
#: preparation — intended outcome, plan, an acceptance PROPOSAL, unknowns/question, required authority.
#: It prepares, it never executes: no card, no ``acceptance_probe``, no claim, no worker, nothing «done».
KIND_ARCH, KIND_PREP = "arch", "task-prep"
PREP_VERSION = "task-prep/1"
PREP_SECTIONS = ("OUTCOME", "PLAN", "ACCEPTANCE PROPOSAL", "UNKNOWNS AND QUESTION", "PERMISSIONS")
NEW_CHECK_MARK = "NEW CHECK NEEDED"
NO_PLAN_MARK = "NO PLAN"
SUBJECT_NONE = "NONE"
#: Forms a task-prep run may report as success (exit 0): a plan FOR REVIEW or a valid clarifying question.
#: Neither is permission to execute.
ACCEPTABLE_FORMS = ("plan", "clarification")
#: ARB 25.10: the subject is the MODEL's proposal; only its membership in the vocabulary is checked.
SUBJECT_NOTE = ("предмет полномочий предложен моделью; проверено только, что это значение словаря ADR-285. "
                "Это не независимая проверка прав и не разрешение исполнять — даже NONE")
PREP_DISCLAIMER = ("ПРЕДЛОЖЕНИЕ ДЛЯ РАЗБОРА — не задание к исполнению: карточка не меняется, проверка результата не "
                   "назначается, исполнитель не запускается, ничего не объявлено сделанным. Зарегистрированное имя "
                   "проверки не доказывает, что она меряет это поручение. Тестовый ответ не оценивает реальную модель.")
PREP_INSTRUCTION = """Prepare ONE ordinary request of the owner for later work. Use ONLY the context below. Do NOT do the work.
The owner's request, verbatim (do not rewrite it):
<<<REQUEST
{task}
REQUEST>>>

Reply in plain Russian for the owner, in EXACTLY these five sections, with these headings, in this order:
## OUTCOME — what will exist when the request is fulfilled, in one or two sentences the owner can check.
## PLAN — 3–7 numbered steps of the work, each with its scope (what is touched, what is NOT touched).
If the request is too ambiguous to plan, write exactly "{no_plan}" here and ask in the next section.
## ACCEPTANCE PROPOSAL — how the RESULT will be checked by a machine, before the work starts. Either name an
existing check in backticks AND say why it measures THIS outcome, or write "{new_check}: <what the check must
measure, a positive and a negative control>". Never pick a check only because it exists.
## UNKNOWNS AND QUESTION — what the context does not establish (say UNKNOWN); if anything blocks planning,
ONE plain question to the owner ending with "?".
## PERMISSIONS — first line exactly "subject: <one of NONE, MONEY, PUBLIC_NUMBERS_NAMING_LEGAL, IRREVERSIBLE,
PHYSICAL_ACTION>" (the owner's three subjects of ADR-285, or an action only the owner can physically do);
then why. This is a proposal: do not claim approval, acceptance or completion."""

_IDENT = re.compile(r"`([A-Za-z][A-Za-z0-9_]{2,}(?::[A-Za-z0-9_.+\-]+)?)`")

### Fragment: 05_state_voice_path_STATUS.md

# Excerpt: docs/evidence/studio-os-next-01-2026-10-16/voice_owner_check_2026-10-25/STATUS.md lines 6-18 and 40-58 — current state of the voice path (at 9a07f8998, unchanged)

## Звенья: ветка · доставка · живое поведение
«Совпадает» = git-blob файла одинаков в ветке, на `origin/main` и в прод-дереве `~/Documents/SPA_Claude`.

| звено | код в ветке | на origin/main и в прод-дереве | загружено работающей службой | живое поведение |
|---|---|---|---|---|
| `mission_server` + `mission_intake.submit/transcribe` | ✅ | совпадает (файлы не менялись с 16.10 20:52) | `mission_server` (KeepAlive, pid 74640) стартовал 17.10 01:14 — ПОСЛЕ последней правки этих файлов; байты зависимостей при старте не сверялись | запись владельца с iPhone через полный путь — **не наблюдалась** (в «Мои записи» 3 записи: 2 агентские 16.10, 1 голосовая 15.10 до замыкания контура, автор не записан) |
| интерфейс `mission_ui` (кнопка «🎙 Продиктовать», «Мои записи») | ✅ | раздаётся тот же `app.js`/`index.html` (blob совпадает, сборка `b-20261025T154457Z`) | раздаётся сейчас | ✅ снимок «Мои записи» MEASURED 15:44:57Z |
| приём `owner_queue/intake` (`com.spa.inbox_watch`, WatchPaths) | ✅ | совпадает | новый процесс на каждый запуск — исполняет файл дерева | на записи владельца не наблюдался |
| `cockpit_dispatch` (rewake/dispatch/settle в `agent_orchestrator.sh`) | ✅ | совпадает | новый процесс в каждом цикле | ✅ шаг идёт: лог `/tmp/spa_orchestrator.log`, 8 циклов 24–25.10 ≈ раз в 2 ч, последний 16:17 CET — «взятой записи пульта нет» |
| `cockpit_loop` (захват, проверка, уведомления) | ✅ + правка этого пакета | старая версия (без правки) | новый процесс на каждый запуск | уведомление владельцу о записи пульта — не наблюдалось |
| `mission_control.cockpit_records` → `owner_view.my_records` | ✅ (`mission_control.py` в ветке новее main, но `cockpit_records` не изменён) | — | `com.spa.mission_control` каждые 300 с | ✅ показывает 3 записи |
| транскрибация whisper | ✅ | — | `/opt/homebrew/bin/whisper`, модель `turbo`, `ffprobe` есть | в этом пакете не запускалась |

...
## Точный оставшийся разрыв
1. **Обычная запись владельца не исполняется автоматически.** Без строки «проба: <имя>» диспетчер честно отказывает
   (правило приёмки: мерку не угадывают). Владелец имён проб не знает; в уведомлении следующий шаг упоминает
   `card_acceptance.PROBES` — служебное имя. Это не дефект замка, а отсутствующий механизм: **кто объявляет проверку
   для обычной записи.** Минимальное предложение (не реализовано, требует решения ARB/владельца): в пульте у записи
   «не взято в работу» — короткий выбор из нескольких проверок простыми словами, выбор пишет `acceptance_probe` через
   существующий `queue.set_acceptance_probe`; без выбора — как сейчас.
2. Живой путь с iPhone ни разу не пройден владельцем; полный UX повтора/ошибки связи, длинный/английский голос — не
   проверены (п. 25).
3. Правка уведомления — только в ветке; доставка на `main` и в прод-дерево — отдельное действие.

## Решение ARB 25.10 после проверки отчёта

Правка уведомлений принята для кандидата `33b3219ac`; полный CI и пределы приёмки — в `ARB_REVIEW.md` рядом.
Предложение сделать выбор внутренних проб обязанностью владельца не выбрано. Правило
`.claude/rules/acceptance.md` уже допускает объявление критерия сессией ДО работы; требуется связать подготовку
обычного поручения с этим порядком, сохранив детерминированную приёмку. Сценарий телефона исправлен ARB:
нужен выбор «Задача»; повтор после ошибки и новая запись после успеха — разные действия; доставка уведомлений
допускает повтор после неопределённого исхода отправки. Ни live-проверка владельца, ни доставка правки не объявлены.
