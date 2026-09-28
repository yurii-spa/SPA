# EARN_DEFI_NEXT_PRODUCT_PASS_REPORT

Phase A (Telegram Owner Gateway) + Phase B (first investment vertical slice — Aave V3). Reuse-first: no
second bot, no new visual framework, no desktop redesign, no money path, no RiskPolicy change. Telegram is
transport, never canonical state.

## A. TELEGRAM CURRENT STATE (delta audit — code + runtime, not prior descriptions)
Existing production bot `spa_core/telegram/bot.py` (1791 lines) + ~20 modules + launchd `com.spa.telegram_bot`.
Already had: **voice→local-whisper→route** (`inbox_intake.transcribe_voice_message`, `large-v3-turbo`,
offline), getUpdates **offset file** (`data/tg_bot_v2_offset.json`), **fail-closed owner allow-list**
(`Router.is_owner`, `str(chat_id)==owner`), inline-button owner-decision cards via canonical
`owner_queue.create_card`, and `ask_router` free-form Q&A via a **local `claude -p`** (LLM; allowed — not
risk/exec/monitoring). Gap: `_classify_route` created tasks **immediately** and had **no GREEN/YELLOW/RED**
safety model. Reused the bot; did NOT create a second.

## B. TELEGRAM GATEWAY
New `spa_core/owner_remote/` package: `intent.py` (the ONE shared classifier), `gateway.py` (plan +
idempotent confirm + idea capture), `answers.py` (deterministic GREEN), `slice.py` (Phase B). `bot.py`
`_classify_route` rewritten to route through the gateway; owner allow-list already enforced on the intake
path (`is_owner` before `_classify_route`), and re-checked on the confirm-callback write path.

## C. VOICE / WHISPER
Unchanged, reused: Telegram voice → `transcribe_voice_message` → local `whisper` CLI (offline, no paid API).
Transcript flows into the **same** classifier + gateway as text. `VOICE_STT_ENGINE=LOCAL_WHISPER`.

## D. GREEN / YELLOW / RED (one shared classifier)
`spa_core.owner_remote.intent.classify` is the authority for **both** Telegram and the web server-side
(`voice_server.py` now imports `is_red` from it). The web UI's JS `classifyIntent` is a client hint locked
by a **JS↔Python parity test** (`test_mobile_surfaces.py::test_js_python_classifier_parity`, 29 phrases).
RED is checked first → wins over YELLOW/GREEN ("создай задачу перевести деньги" → RED).

## E. CANONICAL TASK / IDEA
- **Task (YELLOW):** message → draft with inline **[✅ Подтвердить] [✖ Отмена]**; on confirm →
  `orchestrator_queue`/`save_inbox_task` (`--type inbox`, `source=telegram_text|telegram_voice`,
  `status=new`). Returns the canonical card path. **No auto-dispatch.** **Idempotent** by
  `token=source:message_id` — a Telegram retry / double-tap creates exactly ONE card (proven by test).
- **Idea (GREEN):** → `docs/ideas/<date-slug>.md` (accepted owner home; agents don't act until `#promote`).
- Provenance preserved: transcript, normalized request, timestamp, source, confirmation state, canonical ID,
  outcome (pending ledger `data/tg_owner_pending.json` — not canonical truth).

## F. SECURITY / IDEMPOTENCY
Fail-closed owner allow-list; RED blocked client- AND server-side; no secrets/signing/financial path in the
gateway; canonical writes only via existing intake; idempotency key = `source:message_id`; no second memory
authority (only the canonical intake + docs/ideas + a non-canonical pending ledger). **Not** live-tested end
-to-end on Telegram: starting a second poller against the production token would 409-conflict with the live
bot (documented anti-pattern). Proven instead by deterministic unit tests of the gateway + bot routing.

## G. GIT INTEGRATION
Continued on branch `feature/mobile-owner-remote` (the accepted Owner-Remote line). Integration to `main`
is **blocked** by (a) extensive **unrelated** dirty/untracked work across the tree (data/*, other
scripts/shadow/*, other ADRs) and (b) a repo-wide pre-commit gate that fails on **pre-existing** `spa_core/`
debt this change does not touch. Per the task's rule, unrelated work was **not** destroyed; Phase A/B was
committed onto the safe feature branch. Not pushed. COMMIT_SHA in the delivery message.

## H. INVESTMENT SLICE (Aave V3) — read-only projection
`spa_core/owner_remote/slice.py::build_investment_slice` threads ONE object through
OPPORTUNITY→STRATEGY→POSITION→CAPITAL→RISK→RESULT→WHY. Not persisted; references canonical sources only;
every field tagged AVAILABLE/DERIVABLE/PARTIAL/MISSING/NOT_APPLICABLE; blanks never invented.

## I. OPPORTUNITY
Aave V3: APY **3.5% UNEVIDENCED** (live_apy=null, static fallback), TVL **$12B static** (unevidenced),
freshness UNKNOWN, chain ethereum, asset USDC (derived). Provenance `data/adapter_status.json#adapters.aave_v3`.

## J. STRATEGY
7 candidate strategies reference Aave (S3 Aave Arbitrum L2+Morpho T1, S9 E-Mode Looping T3, S21 Recursive
Loop T2, …) → `candidate_strategies: AVAILABLE`. But **no** canonical opportunity→strategy→position binding
exists (no allocation) → `active_binding: MISSING`, with the required-later mapping named. Not auto-associated.

## K. POSITION (passport read model)
No Aave paper position → `position_id: MISSING`, `held=false`, capital-specific fields MISSING/NA (never
filled from general knowledge). Derivable fields (mechanism=lending, yield_source=variable supply APY) marked
DERIVABLE. `timelock_status: NOT_APPLICABLE` (GSM gate is Sky/sUSDS, not Aave supply).

## L. CAPITAL
PAPER (virtual), `allocated_to_this=$0` (0% of book); book total/deployed/cash from
`data/current_positions.json`. REAL money implication: NONE. REAL/PAPER/SHADOW never confused.

## M. RISK (EXECUTED policy)
Thresholds read from **`spa_core/risk/policy.py#RiskConfig`** (EXECUTED, not docs), RiskPolicy v1.0. Gates:
✅ APY ∈ [1,30]% (3.5) · ⛔ APY must be evidenced (UNEVIDENCED) · ⛔ live TVL ≥ $5M (ADR-053: static $12B
does NOT count). Distinguishes DOCUMENTED vs EXECUTED (falls back to DOCUMENTED only if the import fails).

## N. RESULT
**NOT FUNDABLE · UNEVIDENCED** — "blocked by: APY must be evidenced (live); live TVL ≥ $5,000,000 (static
does NOT count)". No live allocation. No success result invented.

## O. WHY
The slice's RISK gates ARE the WHY (source→evidence→fact→rule→gate→status→result). Missing edges named
honestly: "strategy→position binding", "position (no capital allocated)".

## P. TELEGRAM QUERY REUSE
Telegram GREEN answers read the SAME projection: "Статус Aave" → `answer_slice` (NOT FUNDABLE · UNEVIDENCED),
"Почему Aave не live?" → `answer_why` (the same gates), "Каких данных не хватает по Aave?" →
`answer_slice_missing` (MISSING/PARTIAL fields). "Покажи капитал" / "Какие стратегии" / "Что требует моего
внимания" read the same read models as Desktop/Mobile. No separate Telegram business logic.

## Q. TESTS
- `spa_core/tests/test_owner_remote.py` (33): classifier RED/YELLOW/GREEN incl. ambiguous→RED, slice honesty
  (position MISSING, EXECUTED gates fail, result NOT FUNDABLE, every field a valid status enum), gateway
  plans, allow-list, **idempotent confirm** (double-confirm → 1 card), cancel blocks creation.
- `spa_core/tests/test_bot_classify_route.py` (rewritten, inv #16 + journal note): RED block, task→confirm
  (no silent create), LLM-task→confirm, structured query→deterministic, outage→save, unclear→ask-back.
- `studio_shell/test_mobile_surfaces.py` (8): + JS↔Python classifier parity.
- Full `spa_core/tests/` green except one **pre-existing** unrelated failure
  (`test_heir_all_rows_price_survivors`, other in-flight census work — fails in isolation, touches none of my
  files).

## R. SCREENSHOTS
`/tmp/sos_shots/slice_desktop.png` (Aave slice in the FounderOS shell). Slice mobile overflow = 0 at 390/430.

## S. EXACT COMMITS
Branch `feature/mobile-owner-remote`; Phase A/B COMMIT_SHA in the delivery message.

## T. REMAINING GAPS
- **CANONICAL_DECISION_WRITE = NOT_AVAILABLE** (unchanged) — Telegram "запиши решение" → DRAFT + offer to
  save as idea; no owner→ADR intake fabricated.
- **Telegram not live-tested end-to-end** (second poller would 409 with the production bot). Deploying +
  restarting the bot is the owner's action; logic is unit-proven.
- Aave data is unevidenced/static today → slice honestly says NOT FUNDABLE; a position/binding appears only
  when live APY/TVL evidence + an allocation exist.
- Not pushed; integration to `main` deferred (unrelated dirty tree + pre-existing gate debt).

Final statuses:
TELEGRAM_OWNER_GATEWAY_READY = **YES** (logic wired, owner-gated, RED-safe, idempotent, unit-proven; live
enablement = deploy+restart the existing bot, owner action).
INVESTMENT_VERTICAL_SLICE_READY = **YES** (one real object end-to-end, honest MISSING edges, EXECUTED risk
provenance, desktop + Telegram read one projection).
