# Role context pack — architect (role-pack/1)

> DERIVED — files and git are canonical; this pack is a projection. Generated 2026-10-25T17:30:57+00:00. context preparation only — no model call, no provider routing, no permission.

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
- head: b1b1cbaff4518046b2facb7f8d3571d5bab3d2b0
- server_branch_head: cf3a33b0cff0b3131427ddb6a748cdd0adf11b73
- head_equals_server: False
- verified_code_sha: 33b3219ac8b59ca56d49fa6b1e35fdcc04febf4c
- verified_is_ancestor_of_head: True
- head_code_is_verified: False
- code_changed_since_verified: ['spa_core/studio_os/memory/arch_review.py', 'spa_core/tests/test_task_prep.py']
- changed_since_verified: ['docs/ROADMAP.md', 'docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md', 'docs/evidence/studio-os-next-01-2026-10-16/ci_control_2026-10-25_33b3219ac_run40209078724.md', 'docs/evidence/studio-os-next-01-2026-10-16/voice_owner_check_2026-10-25/ARB_REVIEW.md', 'docs/evidence/studio-os-next-01-2026-10-16/voice_owner_check_2026-10-25/OWNER_SCRIPT.md', 'docs/evidence/studio-os-next-01-2026-10-16/voice_owner_check_2026-10-25/STATUS.md', 'docs/journal/2026-W43.md', 'spa_core/studio_os/memory/arch_review.py', 'spa_core/tests/test_task_prep.py']
- dirty: ['?? docs/evidence/studio-os-next-01-2026-10-16/task_prep_2026-10-25/fixture_answers_NOT_A_MODEL.json', '?? docs/evidence/studio-os-next-01-2026-10-16/task_prep_2026-10-25/request_backup.txt', '?? docs/evidence/studio-os-next-01-2026-10-16/task_prep_2026-10-25/request_vague.txt']

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
| **актуальный проверенный кандидат** | **`33b3219ac8b59ca56d49fa6b1e35fdcc04febf4c`**, CI **40209078724**: 135827 всего, 135106 passed, 2 failed (§49), 719 skipped, 0 ошибок/не получено/ошибок сбора, 12/12. Артефакт и digest сверены ARB; новых failed node IDs против `5a0d497f0` нет. Правка уведомлений `391d2c75d` принята в кандидате. Не зелёный CI, не NO_REGRESSION, не production-доставка |
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

- Актуальный полный результат — **40209078724** на **33b3219ac**, числа и ограничения в §2. Наблюдавшийся
  HEAD `cf3a33b0c` добавляет только запись CI и журнал; своего отдельного полного прогона у него нет.
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
сам владелец её ещё не проходил. Следующий пакет — полезный план обычного поручения до исполнения через существующий
вход архитектора; предложение превратить выбор внутренней пробы в обязанность владельца не выбрано. Работать с
временными входами и тестовым провайдером, без нового реального управленческого вызова, автоматического исполнения
или записи карточки. Сначала переиспользовать имеющееся; код добавлять только для доказанного разрыва.
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

- `docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md` a80b69b33e4b798e82aed65de23868c94fadee963c3f0bc271173d6199e8efc0
- `docs/continuity/ARCHITECT_CONTEXT.md` 61a52614a233b8226b3133e0b7e47afb1b53dbc508e88fb842881566c2fa33c6
- `docs/ROADMAP.md` 4eaa497fa5ddad2d0b09b1281a618c830168a902489b21c0c0337b70af516374
- `docs/continuity/state.json` 1f2d7113b1260c04833aca9420df939bbcf812006003d9d6b5f7609457adeed3
