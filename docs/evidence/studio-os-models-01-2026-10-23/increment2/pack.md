# Role context pack — architect (role-pack/1)

> DERIVED — files and git are canonical; this pack is a projection. Generated 2026-10-24T05:00:59+00:00. context preparation only — no model call, no provider routing, no permission.

## Role

- role_id: `architect` · current participant: ChatGPT (the role is stable; the participant (vendor/model) is replaceable and gains no permission by being selected)
- authority: | **ChatGPT — Architecture Review Board (ARB)** | architecture, conflict/supersession review, acceptance, precise assignments for Claude | decides architecture only after a FRESH bootstrap; never implements, never approves owner subjects | ARB-CONTINUITY-01 directive (2026-10-07), ADR-610 |

## Owner intent

- Last confirmed by the owner: **2026-10-01** (directive «THREE DEFI PAPER PORTFOLIOS — STRATEGY MECHANICS, OPERATIONS AND WEBSITE»).
- Latest owner directive: **2026-10-23** — model-independent workers and architect, P1; bounded verification ([owner decision](decisions/ADR-OWN-2026-10-23-model-independent-studio.md)).
- Continuing owner directive: **2026-10-16** «STUDIO-OS-NEXT-01 — next stage of Earn DeFi Studio OS under the ARB plan» (ADR-763, item 17).

Roadmap item 17: **STUDIO-OS-NEXT-01 · next stage of Studio OS under the ARB plan** — implemented; candidate handed to ARB 2026-10-18, NOT ARB-accepted (owner directive 2026-10-16, ADR-763). Packages in order: (1) this roadmap + the 34-item reconciliation below; (2) Mac resources and cockpit build speed (`findings_bridge` ~5 GB RSS and swap 92.9 % before the 2026-10-15 reboot, `mission_build` 17–22 min, stale `director_*` names in `architecture/resource_policy.json`, RAM/swap/disk told apart in alerts); (3) backup coverage table, gaps closed in a candidate with a restore drill, then a PREPARED (not executed) decision to retire `com.spa.weekly_backup` with rollback; (4) voice path to exactly one card and a plain status for the owner, re-send and connection failure; (5) ADR-762 version-bound confirmation in a separate candidate (not wired into the live confirmation mechanism), then package value history, plain reasons for warnings, read-only check buttons, financial evidence. Real capital $0; no limit or tolerance changes; no new markets; nothing deleted. Status 2026-10-16 (each claim with its level): (2) resources — implemented + live-verified: cockpit build 1175 s → 14 s in production, CORRUPT cells 0, findings_bridge census peak 7.25 GB → 224 MB, frozen-data equivalence 0 differing fields (`cc98a1ba`); (3) backups — implemented, restore-drilled in scratch and into a clean clone (`2e173313`, `5bc89182`), first nightly run with the new sets not yet observed; iCloud upload to Apple NOT MEASURED

## Revision (measured from git)

- branch: integ/studio-os-next-01-stab
- head: c60ad6d6a5f2ebbfce38f1aae04d22d3ba049e95
- server_branch_head: 1ff07227b35d34274a09b1f64c8bcf42908d72ab
- head_equals_server: False
- verified_code_sha: d12af8debbca09b4e40a6419a76a4a512ec77e63
- verified_is_ancestor_of_head: True
- head_code_is_verified: False
- code_changed_since_verified: ['architecture/model_roles.json', 'spa_core/studio_os/memory/role_pack.py', 'spa_core/studio_os/model_roles/__init__.py', 'spa_core/studio_os/model_roles/__main__.py', 'spa_core/studio_os/model_roles/adapters.py', 'spa_core/studio_os/model_roles/contract.py', 'spa_core/tests/test_model_roles_contract.py', 'spa_core/tests/test_role_pack.py']
- changed_since_verified: ['architecture/model_roles.json', 'docs/STATE.md', 'docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md', 'docs/evidence/studio-os-next-01-2026-10-16/ci_control_2026-10-23_d12af8deb_run40031634618.md', 'docs/journal/2026-W43.md', 'spa_core/studio_os/memory/role_pack.py', 'spa_core/studio_os/model_roles/__init__.py', 'spa_core/studio_os/model_roles/__main__.py', 'spa_core/studio_os/model_roles/adapters.py', 'spa_core/studio_os/model_roles/contract.py', 'spa_core/tests/test_model_roles_contract.py', 'spa_core/tests/test_role_pack.py']
- dirty: ['M docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md']

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
| **проверенный код** (конечный) | **`d12af8debbca09b4e40a6419a76a4a512ec77e63`** — правка B-10 и копии `*.excerpt.json`; полный CI 40031634618: RED 12/12, **2 failed** (такт производителя §49 ×2), новых против базы 0, исправлено 67 |
| последующий HEAD | docs-only коммит с результатом CI — своим прогоном не проверен |
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

- Последний ПОЛНЫЙ результат — о `3c40ed137` (39935715615): 135 651 · 134 929 passed · 3 failed (такт производителя
  §49 ×2; `test_investor_report` — B-9).
- Кандидат 1 `3da13e7bf`: ci-control 40026699075 — RED 12/12, 135 663 · 134 940 passed · 4 failed: такт производителя §49 ×2,
  `test_prior_run_operand_census` (мои копии `exit.json`/`run.json` в evidence — неоднозначные имена; переименованы),
  `test_live_paths` (B-10, порядок набора; исправлено). B-9 в CI закрыт. Census 40026699805 — о `3da13e7bf`.
- Конечный код `d12af8deb`: ci-control 40031634618 — RED 12/12, 135 663 · 134 942 passed · 2 failed (такт производителя §49 ×2),
  новых против базы 0. Census 40031633042 о `d12af8deb` на момент записи не завершён — прочитать по артефакту.

## Task · open_problems_and_next_step

1. Прочитать census 40031633042 (о `d12af8deb`) по артефакту; новых находок не ожидается, но это не утверждение.
2. Решение о подключении производителя §49 (пакет `arb_packages_2026-10-23/s49_connection_package.md`) — за ARB/владельцем.
3. MODELS-01 инкремент 2: один контракт провайдера и конфигурация ролей; второй адаптер — на фикстурах. Не начат.
4. Backlog B-1…B-8 — `stage8_2026-10-23/BACKLOG_census_findings.md`.

**Следующий шаг:** прочитать census 40031633042 и внести в evidence; затем ждать решения ARB (подключение §49; MODELS-01 инкремент 2).

## Task · constraints

Разрешено: обычный push и CI только в `integ/studio-os-next-01-stab`; чтение уже идущих прогонов. Запрещено: merge,
`main`, force-push, публикация сайта, установки, расписания, перезапуски служб, рабочий трекер и `--apply`, удаления,
`git stash`, отмена чужих прогонов, RiskPolicy/ставки/лимиты, новые провайдеры моделей, платные API, локальные модели;
объявлять NO_REGRESSION или приёмку ARB; объединять результаты разных SHA.

## UNKNOWN

- none

Credential-like lines dropped: 0

## Inputs (sha256)

- `docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md` 7fbfaa2d30a73cd921b9e26766cf9d116a7aa9661ec2252f21eed8393c243a47
- `docs/continuity/ARCHITECT_CONTEXT.md` 61a52614a233b8226b3133e0b7e47afb1b53dbc508e88fb842881566c2fa33c6
- `docs/ROADMAP.md` 9a9f727cff89d6ee43db496fd4093d5a04f8130b14cad4de4fd56ed048d18d56
- `docs/continuity/state.json` 1f2d7113b1260c04833aca9420df939bbcf812006003d9d6b5f7609457adeed3
