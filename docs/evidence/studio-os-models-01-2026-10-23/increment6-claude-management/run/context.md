# Role context pack — architect (role-pack/1)

> DERIVED — files and git are canonical; this pack is a projection. Generated 2026-10-25T15:24:00+00:00. context preparation only — no model call, no provider routing, no permission.

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
- head: a1a5f13611cb30fe164d3c98f84a04499e0759e4
- server_branch_head: 95ea39f1795ef4f48f86a9642f65937b4314b584
- head_equals_server: False
- verified_code_sha: 5a0d497f0ce7c9f7fe8740cf8e982ff1eb66ec0e
- verified_is_ancestor_of_head: True
- head_code_is_verified: True
- code_changed_since_verified: []
- changed_since_verified: ['docs/ROADMAP.md', 'docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md', 'docs/evidence/studio-os-models-01-2026-10-23/increment5-plan/ARB_REVIEW_2026-10-25_a2bdf7c09.md', 'docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/fragments/01_owner_decision_ADR-OWN-2026-10-23.md', 'docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/fragments/02_director_os_backlog.md', 'docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/fragments/03_state_studio_os.md', 'docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/model_roles.tmp.json', 'docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/task.txt', 'docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md', 'docs/evidence/studio-os-next-01-2026-10-16/ci_control_2026-10-25_5a0d497f0_run40190831822.md', 'docs/journal/2026-W43.md']
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
| **проверенный код** | **`30ca5abc46a42a3fcf8910113f62d4edde967629`** — MODELS-01 инкремент 3 (`memory.answer.ask` через контракт, cwd CLI, 125 ⇒ ownership_unresolved) и B-11; полный CI 40097091074: RED 12/12, 2 failed (такт §49 ×2), новых против базы 0. **Принят ARB 24.10** (маршрутизация не включена, NO_REGRESSION не объявлен) |
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

1. **B-12 исправлен и принят ARB** (`b736e6d1d`, проверенный код `393faa72d`, CI 40131303808).
2. Решение о подключении производителя §49 (пакет `arb_packages_2026-10-23/s49_connection_package.md`) — за ARB/владельцем.
3. MODELS-01: инкременты 2 и 3 приняты ARB (`86d9c662a`, `30ca5abc4`); инкремент 4 — `python -m spa_core.studio_os.memory
   arch-review` (код `3a1b55370`, CI 40103531673: 2 failed — такт §49, новых 0), демонстрация — разбор B-12
   (`docs/evidence/studio-os-models-01-2026-10-23/increment4/`); ждёт решения ARB.
4. Backlog B-1…B-8 — `stage8_2026-10-23/BACKLOG_census_findings.md`.

**Подготовка локальной пробы ПРИНЯТА ARB** на `5a0d497f0ce7c9f7fe8740cf8e982ff1eb66ec0e` (код `a490f2979`, CI 40190831822:
2 failed — такт §49, новых 0; не зелёный CI и не NO_REGRESSION) — `increment5-plan/ARB_REVIEW_2026-10-25_a2bdf7c09.md`,
раздел «Follow-up acceptance». R1/R2 закрыты. **Сама проба ОТЛОЖЕНА** решением владельца 25.10: «Claude сейчас, локальные
модели — после нового Mac mini» (ADR-OWN-2026-10-23, раздел «Owner sequencing directive»; ROADMAP). Покупка оборудования
и автоматический запуск этим не разрешены.

**Следующий шаг:** ОДИН управленческий прогон через `memory arch-review` и `claude_subscription_cli` на текущем входе
(`docs/evidence/studio-os-models-01-2026-10-23/increment6-claude-management/`). Назначения моделей остаются null;
предложенное моделью задание автоматически не исполняется. Подключение именно Claude Pro и защита от платного продолжения
НЕ проверены.

## Task · constraints

Разрешено: обычный push и CI только в `integ/studio-os-next-01-stab`; чтение уже идущих прогонов. Запрещено: merge,
`main`, force-push, публикация сайта, установки, расписания, перезапуски служб, рабочий трекер и `--apply`, удаления,
`git stash`, отмена чужих прогонов, RiskPolicy/ставки/лимиты, новые провайдеры моделей, платные API, локальные модели;
объявлять NO_REGRESSION или приёмку ARB; объединять результаты разных SHA.

## UNKNOWN

- none

Credential-like lines dropped: 0

## Inputs (sha256)

- `docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md` 8f70b4d9bf499644a1518e1b9401c49f46670a22332e1a151c3354439749e3dd
- `docs/continuity/ARCHITECT_CONTEXT.md` 61a52614a233b8226b3133e0b7e47afb1b53dbc508e88fb842881566c2fa33c6
- `docs/ROADMAP.md` 262dd4d92ac73b5205eadc10e673724539983c63e034939ad64be6a2b0a625e0
- `docs/continuity/state.json` 1f2d7113b1260c04833aca9420df939bbcf812006003d9d6b5f7609457adeed3

## Task fragments (explicit, sanitized)

### Fragment: 01_owner_decision_ADR-OWN-2026-10-23.md

# Excerpt: docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md lines 1–85 (at aaec91755, unchanged)

# ADR-OWN-2026-10-23 · Model-independent Studio OS and bounded verification

- Date: 2026-10-23 (Europe/Madrid).
- Decision owner: Yurii Kulieshov.
- Recorded by: Architecture Review Board.
- Status: owner directive accepted for priority and design; implementation and production activation are not claimed.
- Source: owner's instruction of 2026-10-23: avoid repeated 6–12 hour whole-system audits; make interchangeable models at multiple levels, including the architect, an important roadmap priority.
- Related: ADR-423 (deferred local LLM/router work), ADR-527 (memory), ADR-610 (architect continuity), ADR-763 / ROADMAP item 17.

## Decision and priority

**STUDIO-OS-MODELS-01 is P1 and the next bounded Studio OS macro after the current stage-8 checkpoint.**
It is not conditional on closing every item of technical debt. Mandatory release gates and the explicit remaining risks still apply to the actions they protect. Product work may proceed within existing safe boundaries.

The Architecture Review Board/architect and the implementation worker are roles, not vendor names. ChatGPT and Claude Code are the current participants. A compatible cloud or local model can fulfil an approved role after that role's capability and quality checks; the model never becomes the owner or acquires new permissions by being selected.

This directive reopens the design/roadmap deferral in ADR-423 points 1–3. It does not activate a new production provider or resume resource-heavy local-model experiments. ADR-423's prohibition on automatic paid API fallback, the hardware-purchase deferral and resource safeguards remain. No provider, service, subscription or hardware purchase is authorized by this priority change.

## Starting evidence and scope limit

- docs/MEMORY_ARCHITECTURE.md already treats AI sessions (Claude, Codex, local models) as replaceable workers and files/Git as memory.
- docs/continuity/ARCHITECT_CONTEXT.md and BOOTSTRAP.md already provide a continuity path; reuse it.
- ADR-423 deferred a production router and kept Claude Subscription as the only production AI provider as of 2026-09-19. Its measurements are historical, not a current host inventory.
- Selected current source call sites remain provider-specific: spa_core/studio_os/memory/answer.py calls the Claude CLI; spa_core/dev_agents/architect.py uses an Anthropic client. These observations do not establish which callers are active in production.
- No complete model router, working local adapter, or provider-independent architect execution is accepted on this evidence.

Inspect only the existing model-call seams, role declarations and continuity interfaces needed for the first slice. Do not repeat a system-wide audit or replace existing components without inspecting them.

## Architecture and first increments

1. **Portable architect and reviewer context.** Reuse the existing memory/continuity assembler for a versioned role package: task, owner intent, relevant decisions, allowed actions, exact code revision, evidence references and open risks. A fresh architect can recover the state without chat history. Unknown/stale inputs remain explicit.
2. **One provider contract and role configuration.** Keep stable role identifiers separate from provider/model identifiers. Declare required capabilities, allowed tools, input/output format, context limit, deadline, retry limit and resource budget. Unsupported combinations refuse; no silent escalation or fallback.
3. **Small interchangeable execution slice.** Wrap the existing approved Claude subscription path; prepare an independently selectable second adapter using fixtures before any production activation. Local-provider qualification is a separately bounded canary on a safe task after resources and limits are specified. Do not benchmark every model.
4. **Observed resource use.** Attribute model calls, elapsed time, retries and failures to task/role/provider. Record tokens or quota only when actually exposed; missing accounting is UNKNOWN. Do not infer subscription charges from token counts.

The first reviewable result is one safe task recovered by a fresh architect and processed through the same role/provider contract without a provider-specific workflow rewrite. New provider activation remains a separate delivery step. Subsequent slices are selected from actual gaps, not a speculative framework backlog.

## Owner clarification — 2026-10-25: Claude Pro for management

- Decision owner: Yurii Kulieshov; recorded by ARB from the owner's request to connect his Claude Pro subscription for management.
- Status: requirement accepted for design; the actual account, plan, billing safeguards and production connection are not verified by this record.
- Reuse the official Claude Code CLI and the existing `claude_subscription_cli` seam for architecture review, planning and preparation of implementation tasks. Support the owner's Pro subscription and compatible Max access; do not require another subscription or an API account. The same provider may serve different roles without changing their permissions. Company memory remains the existing files and Git.
- Authentication stays in the official client. Do not extract or copy OAuth tokens into SDKs, adapters, context packs or reports. Reuse the intended signed-in profile; an explicitly selected `CLAUDE_CONFIG_DIR` may separate accounts when needed. Do not log out, replace credentials or change the active implementer's account automatically. Account/plan facts must be reported from safe status metadata or marked UNKNOWN.
- Stay within included subscription usage. Do not silently use API credentials, cloud billing, paid usage credits or another provider. Detect and refuse a billing mode outside the intended subscription; unknown paid-overage settings must remain UNKNOWN rather than a promise of no charges. Changes to payment settings are the owner's decision.
- Management and implementation share the subscription's limits. A quota refusal preserves the task and reports a pause; do not repeatedly poll with model calls or infer subscription charges from CLI cost estimates.
- Acceptance: an explicitly selected subscription profile can perform a safe management task through the existing contract; unavailable login, quota and unsupported billing mode have clear outcomes; owner authority and all existing safety gates remain unchanged. This does not authorize local inference, a new production provider, paid fallback or service changes.

Rationale: reuse the owner's paid access for management and development while preserving model-independent roles and bounded costs. Alternatives rejected: a separate API dependency for management, exported subscription credentials, and implicit paid continuation. Consequence: management consumes the same quota as development and can pause when that quota is exhausted.

Provider references checked 2026-10-25: [Pro/Max access and shared limits](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan), [official authentication and profiles](https://code.claude.com/docs/en/authentication), [paid usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).

## Owner sequencing directive — 2026-10-25: Claude now, local models after the new Mac mini

- Decision owner: Yurii Kulieshov; recorded by ARB from: «я бы клод тестировал пока мак мини не купил новый».
- Status: accepted for the next bounded management test, within the existing subscription and permissions.
- Next step: use the existing official Claude Code subscription seam and `memory arch-review` for one useful
  management/architecture task. Supply fresh canonical context and check factual accuracy, unknowns,
  priorities, owner authority and the usefulness of its proposed implementation task. Preserve output as a
  proposal for ARB review; do not execute the generated task automatically.
- Reuse the intended authenticated subscription profile; do not switch accounts or represent an observed
  Max profile as a verified Pro connection. Included-usage and no-paid-fallback restrictions above remain.
- Defer real Ollama inference and real weight-copy preparation until the owner's new Mac mini is available.
  Availability of the new hardware is not automatic permission to start: a bounded launch still needs its
  own owner authorization. No hardware purchase or model download is authorized by this directive.
- Keep the accepted local-probe preparation (`5a0d497f0`) and its evidence. Do not delete it, repeat its audit,
  or make local-provider qualification a prerequisite for useful work with Claude.

Rationale: deliver useful management behaviour using the owner's current access while postponing local
compute experiments until the planned hardware change. Alternatives: run Qwen on the current Mac (deferred
by the owner); block all management work until a second provider is qualified (rejected). Consequences:
model-independent architecture remains P1, Claude management is the immediate test, and actual Pro-profile
qualification, billing safeguards and second-provider qualification remain separate evidence questions.

## Acceptance

- Owner intent, decisions and task state survive replacement of an AI session; existing memory is reused.
- Architect/ARB role, implementation role and owner authority remain distinct.
- Provider choice changes through explicit configuration at the existing execution seam; permissions do not change.
- A fixture-backed second adapter exercises the same input/output/refusal contract; an unavailable or unqualified provider cannot silently receive the role.
- A real second-provider canary, when authorized and available, reports quality, time and resource use for the stated task. Fixture success is not production readiness.
- Timeouts, cancellation, malformed output and quota exhaustion preserve task state; retries are bounded.
- Credentials are not copied into context packs or reports.
- No LLM is introduced into risk, execution, monitoring or kill components; Investment Engine and Product Studio stay separate.
- No autonomous real-capital movement, risk-limit/rate change, paid API fallback or owner approval is enabled.

### Fragment: 02_director_os_backlog.md

# Excerpt: docs/ROADMAP.md lines 270–307 — Director OS backlog (at aaec91755, unchanged)

## Director OS backlog — the 34 items of 2026-10-15, reconciled 2026-10-16 (ADR-763)

Source: `ROADMAP_ITEMS_FOR_ARCHITECT_2026-10-15.md` (15.10 handover attachment, outside the repo). This section is
part of THIS roadmap, not a second one; it adds no cards. Owner = who decides; «agent» = Claude Code executor;
acceptance is a machine check where one exists. Priority В/С/Н as in the source. Note: the source's item 1 and 4
cite «п. 31 (история трека)» — it means item 32; item 31 is VoiceOver.

**Done (no new work):** 10 = duplicate of 29 (one methodology, `track_period_view`, released `0dc759eb2`) · 28 Wave 2
published `0dc759eb2` (remaining residue moved to item 15 debt) · 29 one methodology done (Oracle's own method stays
separate and labelled; aligning it is an optional owner decision, Н).

**Duplicates (tracked under their twin):** 22 → 2 · 14 → 30 · 10 → 29.

| # | Item | Status | Depends on | Owner | Acceptance | Next step |
|---|---|---|---|---|---|---|
| 23 | Voice intake, first real iPhone send | published, not owner-verified | — | owner (test) / agent | one card per send, visible status in the cockpit | STUDIO-OS-NEXT-01 package 4: phone script |
| 24 | Who processes `cockpit-voice` cards, feedback | not built | 23 | agent | card leaves `new` with a reason; owner sees the outcome | package 4 |
| 25 | Long/English voice, retry when Mac busy | not built | 24 | agent | retry keeps the text; no duplicate card | package 4 (re-send/failure only) |
| 30 / 14 | ADR-762 version-bound answer; answer from cockpit | proposed | owner decision | owner (mechanism) / agent (candidate) | candidate: CAS under one lock, replay-safe, journal + recovery, kill-switch for writes | package 5 candidate, not wired live |
| 16 | «Проверить ещё раз» (read-only) then «Исправить» | not decided | ADR-760 pattern | owner per action | one ADR per action; read-only first | package 5 after ADR-762 candidate |
| 32 | Package value history by day | no data in canon | — | agent | `capital.package_values` series with measured_at, read-only from `data/defi_engine/` | package 5 |
| 1 | Week balance tile | no data | 32 | agent | tile = value − value 7 d ago with both dates | after 32 |
| 4 | Combined annual figure | too early (owner: wait until all packages have 30 days) | 32, ~2026-11-01 | owner | rule in `owner_view` | after 32 + 30 days |
| 11 | Package costs measured, not modelled | no data | — | agent | journal of simulated actual costs | package 5 «financial evidence» |
| 17 | Health tile beyond 5 groups; plain warning reasons | not built | — | agent | every warning has a plain reason + source | package 5 «plain reasons» |
| 5 | Infrastructure plan (Mac resources, costs) | partial | package 2 | agent | RAM / swap / disk / top consumers with times | package 2 feeds it |
| 27 | Restart long-lived agents after delivery | partial (named, not restarted) | — | owner (restarts) | procedure with owner confirmation | later |
| 15 | Off-subject owner questions in the queue | queue defect (ADR-285) | — | agent | `needs-owner` holds only the three subjects | later |
| 20 | Agents section (read-only) | not built, data exists | — | agent | section over `agent_health` | later |
| 19 | Throughput («Мощность») | no data | — | agent | cycles/cards/closures per day from the journal | later |
| 12 / 13 | Strategy readiness stages; Trading screen | not built | ADR for criteria | owner (criteria) / agent | readiness criterion ADR; screen | later |
| 6 | Live «what is happening now» lines | no data | — | agent | last action per agent with time | later |
| 3 | Claude load tile | no data, «100 %» undefined | — | owner (definition) | source + definition | later |
| 2 | Product progress tile | no data | machine status per roadmap item | agent | each item has a probe | later |
| 9 | Real money | owner subject №1 | GoLive, legal | owner | — | not in scope |
| 26 | Cockpit without the Mac | not decided | — | owner | — | later |
| 7, 8, 18, 21, 31, 33, 34 | Search · notifications in cockpit · incident history · repositories · VoiceOver · policies · company memory section | low priority (Н) | — | owner (8, 31, 33) / agent | — | later |

### Fragment: 03_state_studio_os.md

# Excerpt: docs/STATE.md line 18 — confirmed Studio OS state (at aaec91755, unchanged)

- **Новый пульт владельца ВЫПУЩЕН 15.10** (`2df987cec`; макет «SPA Director OS», тёмная тема; ADR-762 — представление над Company Truth; голос ADR-760). **STUDIO-OS-NEXT-01 (ADR-763, ROADMAP п. 17) передан ARB 18.10:** кандидат `b47b637a1`; полный вердикт CI восстановлен (ADR-768, шарды, исход каждого теста) — прогон №14: 134 982 теста, **58 красных, 0 ошибок, 0 новых, 0 собственных регрессий**; ремонт набора НЕ завершён, каждый остаток с задачей (`docs/evidence/studio-os-next-01-2026-10-16/residual_run14.md`); вход новой сессии — `…/START_HERE.md`, передача — `…/HANDOVER_FOR_ARB_FINAL.md`. Пульт 1175 с → 14 с; бэкап и восстановление проверены; автономность доказана на ОДНОЙ задаче только-чтения; API-чтение портфеля не пишет боевую БД (проверено 18.10). Открыто у владельца: iPhone-голос не подтверждён · ADR-762 выключен · `weekly_backup` включён · идея двух уровней проверок не promoted · перезапуск долгожителей (mission/director/bot) · капитал $0. **23.10:** кандидат стабилизации `integ/studio-os-next-01-stab` не принят ARB; этап 8 (`3c40ed137`, CI 39935715615) и после разбора ARB: B-9 причина доказана и исправлена (CI 40026699075 на `3da13e7bf`: B-9 закрыт, 2 новых — мой `exit.json` в evidence и порядок набора B-10, оба исправлены: конечный `d12af8deb`, CI 40031634618 — 2 failed, новых против базы 0); P1 STUDIO-OS-MODELS-01 (ADR-OWN-2026-10-23): пакет роли `role-pack` (очистка всех источников) + контракт провайдера и роли `model_roles` (`86d9c662a`, CI 40069391393: 2 failed — такт §49, новых 0; адаптер Claude и тестовый; назначения null — роутинга нет; инкремент 3 `ef5ed5f27`: `memory.answer.ask` через контракт, срок — `claude_run_with_timeout`; по замечаниям ARB — cwd CLI во временном каталоге, 125 ⇒ ownership_unresolved без повтора, B-11 исправлен; **инкремент 3 и B-11 приняты ARB на `30ca5abc4`** — маршрутизация не включена, NO_REGRESSION не объявлен; инкремент 4 `memory arch-review` и B-12 приняты ARB на `393faa72d` (production не заявлена, второго провайдера нет, CI RED по такту §49, NO_REGRESSION не объявлен); проба `qwen3.5:4b` подготовлена в коде (`e5a45db30`; по замечаниям ARB 25.10 — единый вердикт, точный грейдер, частное хранилище, отказ на занятом/чужом порту; ARB R1/R2 на `a2bdf7c09` исправлены — результат привязан к запуску, неполный замер памяти = стоп), inference не запускался — ждёт решения владельца); остаток — такт производителя §49 ×2 — журнал W43, передача `…/HANDOVER_2026-10-23_POST_ARB8.md`; `--apply` заблокирован; §49 не установлен.
