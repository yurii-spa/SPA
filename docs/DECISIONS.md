# DECISIONS — Журнал решений сессий

Агент добавляет запись в КОНЦЕ каждой сессии. Читай последние 3-5 записей в начале сессии.

---

## 2026-06-28 (ADR-049 — EXECUTION kill-switch CONVERGED onto the ONE governance source of truth)

**Decision (Money-Path Trust sprint, WS-B1/B2): the EXECUTION pre-trade
kill-switch (`spa_core/execution/safety_checks.py` →
`PreExecutionSafety.check_not_in_kill_switch`) now consults the SAME canonical
governance two-tier ladder + the SAME persisted state as the rest of the system.
The threshold VALUES are UNCHANGED (owner-set 5% / 10%); only the SOURCE converges.**

**The divergence the architect found (now FIXED).** The execution gate had its own
*private* kill logic, divergent from governance on BOTH axes:
- it hard-blocked at a flat hardcoded `max_drawdown_stop = 0.05` — i.e. a single 5%
  rung that ALL-CASH-blocked every trade, ignoring the owner-approved two-tier
  ladder (SOFT de-risk `[5%,10%)` blocks only NEW/increasing exposure; HARD `≥10%`
  blocks ALL). It also pre-dated ADR-048 and referenced governance as "15%".
- it gated on a process-local module boolean `_kill_switch_active` that did NOT
  survive a process restart — **a crash silently reset the manual kill.**

**B1 — converge the drawdown gate onto governance.** Extracted the pure boundary
classifier `governance.kill_switch.classify_drawdown_pct(dd_pct)` — now the SINGLE
place the tier constants (`SOFT_DERISK_THRESHOLD_PCT=5.0`,
`DRAWDOWN_THRESHOLD_PCT=10.0`) and half-open band semantics are applied. Both
`governance.drawdown_tier()` (equity-curve path) AND the execution gate classify
through it, so they CANNOT diverge. The execution gate now:
SOFT → blocks only NEW/increasing exposure (`supply`), ALLOWS reduce/`withdraw`;
HARD → blocks ALL (incl. withdraw, i.e. all-cash). `max_drawdown_stop` retained in
the signature for call-site compatibility but **ignored for the verdict** (governance
owns the threshold — verified by a test that a 50% arg does not change a SOFT verdict).

**B2 — persist the manual kill.** `_kill_switch_active` is demoted to a deprecated
advisory shim (no longer authoritative). `activate/deactivate/is_kill_switch_active`
and `check_not_in_kill_switch` now read/write the canonical atomic
`data/kill_switch_active.json` via the governance `KillSwitchChecker` lifecycle
(file ABSENT = OFF; `active=False` = explicitly OFF). The kill SURVIVES a process
restart; unreadable state fails CLOSED (treated as ACTIVE). A `set_data_dir_override`
test/sandbox hook points the persisted state at a throwaway dir so live `data/` is
NEVER touched (the golive_dry_run manual-kill injection was migrated onto it — it no
longer writes/clears the LIVE kill file).

**Verdict parity (proven, sandbox-only — live `data/` untouched).** Across
{0, 4.99, 5.0, 7.5, 9.99, 10.0, 15}% the execution verdict == governance
`drawdown_tier()` on the SAME equity; both boundaries inclusive (exactly 5.0% →
SOFT, exactly 10.0% → HARD). Red-team: a 7% drawdown does NOT all-cash a `withdraw`
(proves no divergent flat-5% hard-block remains); the kill survives a simulated
restart (write → new process reads it active); absence = OFF.

**Files changed (deterministic, stdlib-only, LLM-FORBIDDEN, fail-CLOSED, atomic):**
- `spa_core/governance/kill_switch.py` — extracted `classify_drawdown_pct` (shared
  boundary classifier / single source of the tier constants); `drawdown_tier` now
  composes it. No value change.
- `spa_core/execution/safety_checks.py` — `check_not_in_kill_switch` converged onto
  `classify_drawdown_pct` + persisted `kill_switch_active.json` (two-tier, action-aware);
  `activate/deactivate/is_kill_switch_active` persist via governance lifecycle;
  `set_data_dir_override` test hook; `run_all` threads `action` into the kill check.
- `spa_core/execution/golive_dry_run.py` — stale 5%-vs-15% divergence comment
  rewritten; manual-kill injection routed through a throwaway data dir (no live write).
- Tests: `spa_core/tests/test_pre_execution_safety.py` — fixture redirects persisted
  state to tmp + new `TestKillSwitchGovernanceConvergence` (tier-parity parametrize,
  SOFT-allows-reduce red-team, HARD-blocks-all, ignored-`max_drawdown_stop`,
  persist-across-restart, absence=OFF, active=False=OFF).

**GUARDRAIL honoured:** execution stays INERT (`is_live` OFF) — this builds cutover
READINESS, it does NOT flip live. WS-A (optimizer) and WS-C (sleeve_capture) untouched.

**RiskPolicy version:** stays **v1.0** — kill/two-tier logic lives in the governance
layer, not in `RiskConfig`.

**Verified:** `pytest spa_core/tests/ tests/ -k "safety_check or kill_switch or
execution or pre_cutover or drawdown"` → **1568 passed, 15 skipped, 0 failed**;
`python3 -m spa_core.paper_trading.pre_cutover_gate` → all defenses fired, exit 0,
inert. NOT pushed.

---

## 2026-06-27 (ADR-048 — HARD kill 15→10 + DL-02 reconciliation + boundary fix, owner-approved)

**Decision (owner-approved 2026-06-27): lower the HARD kill-switch drawdown
threshold 15% → 10%, make the boundary INCLUSIVE (`>=`), and reconcile the
DailyLimits DL-02 10%-peak HALT so it no longer SHADOWS the hard kill.** This
closes the two OWNER-DECISIONs flagged in the ADR-034 addendum below (now RESOLVED).

This supersedes the 15% rung of the ADR-034 ladder. The owner-approved ladder is now:

| Rung | Axis | Threshold | Effect |
|---|---|---|---|
| **DL-01** | single-day loss | **> 2%/day** | `DailyLimitsChecker` **HALT** (HOLD, no new trades). UNCHANGED. Distinct daily-loss axis — NEVER deferred. |
| **SOFT de-risk** | peak→current drawdown | **[5%, 10%)** | de-risk: halt new / no INCREASE (hold + reduce only), edge-triggered WARNING. Does NOT liquidate. UNCHANGED. |
| **HARD kill** | peak→current drawdown | **≥ 10%** | full kill → **ALL-CASH** `{"cash":1.0, …:0.0}`. LOWERED 15→10; now OWNS the 10% peak-drawdown rung. |

**The shadow bug (found by the architect, now FIXED).** Inside `run_cycle` the money-path order is:
Step 1b kill-switch *check* (arms `_ks_triggered`) → Step 1c soft de-risk check →
Step 2 allocator → **Step 2a DailyLimits HALT (DL-01/DL-02) — EARLY-RETURNS** →
Step 2b emergency breakers → **Step 2c `apply_kill_switch_override` (the ALL-CASH action)**.
Because DL-02 (peak drawdown > 10%) early-returned `blocked_by_daily_limits` (a HOLD,
positions unchanged) at Step 2a — *before* the all-cash override at Step 2c — a ≥10%
drawdown HALTed instead of going all-cash. The hard kill was computed but its effect
was preempted. With the hard kill now at 10%, the same rung is owned by the kill, so
the shadow had to be reconciled.

**Reconciliation chosen — option (a), DL-02 DEFERS to the armed hard kill (minimal-risk).**
In `cycle_runner.run_cycle`, when the DL gate returns HALT and the hard kill is ARMED
(`_ks_triggered`, computed in Step 1b), a **DL-02-only** HALT is DEFERRED: its halt
reason is dropped (gate → PASS) so the cycle flows through to Step 2c where the
all-cash override fires. **DL-01 (daily loss) is NEVER deferred** — if DL-01 is among
the halt reasons the cycle still HALTs as before. Chosen over option (b) (retiring
DL-02's rung) because it is the **least invasive**: the money-path order is untouched,
the `DailyLimitsChecker` primitive is unchanged (still a reusable HALT for other
callers / a recovered book whose historical peak-drawdown exceeded 10% but current
drawdown is < 10% → kill NOT armed → DL-02 still HALTs correctly), and DL-01 is fully
preserved. End state: **at ≥10% evidenced peak drawdown the cycle goes ALL-CASH.**

**Boundary fix.** `check_drawdown_trigger` now fires on `drawdown >= DRAWDOWN_THRESHOLD_PCT`
(was strict `>`), so it AGREES with `drawdown_tier` (`>=`) at exactly 10.0% — the old
0-width 15.0% gap (classifier `>=` vs trigger `>`) is closed. Exactly 10.0% DOES kill.

**Files changed (deterministic, stdlib-only, LLM-FORBIDDEN, fail-CLOSED, atomic):**
- `spa_core/governance/kill_switch.py` — `DRAWDOWN_THRESHOLD_PCT 15.0 → 10.0`;
  `check_drawdown_trigger` boundary `>` → `>=`; tier-band + docstrings updated.
- `spa_core/paper_trading/cycle_runner.py` — Step 2a DL-02→hard-kill deferral
  (DL-01 intact); soft-band docstrings 15→10.
- `spa_core/paper_trading/pre_cutover_gate.py` — `DL02_PEAK_DRAWDOWN` drill
  replaced by `DL02_DEFERS_TO_KILL` (asserts ≥10% → all-cash kill owns the rung);
  HARD drawdown drill + ladder print updated.
- `spa_core/paper_trading/cycle_gates.py` — soft-band docstrings 15→10.
- Tests: `tests/test_kill_switch_two_tier.py`, `spa_core/tests/test_cycle_derisk_e2e.py`
  (new E2E `test_d1t2_hard_kill_drawdown_fires_in_run_cycle` @ 10/12/15% → all-cash;
  `test_d1t2_dl01_daily_loss_still_halts_not_killed`), `spa_core/tests/test_pre_cutover_gate.py`,
  `spa_core/tests/test_kill_switch.py`, `spa_core/tests/test_kill_switch_sharpe.py`,
  `tests/test_kill_switch_eval_path.py`.
- Docs: this ADR, `docs/PRE_CUTOVER_GATE.md`, `CLAUDE.md` RiskPolicy ladder.

**Validated (sandbox-only, live `data/` NEVER touched):** `python3 -m spa_core.paper_trading.pre_cutover_gate`
→ all defenses fire, exit 0; the new E2E test proves 10/12/15% evidenced drawdown →
ALL-CASH end-to-end in `run_cycle` (the previously-shadowed path now works).

**RiskPolicy version:** stays **v1.0** — the two-tier/kill logic lives in the
governance layer (`kill_switch.py` / `cycle_gates.py` / `cycle_runner.py`), not in
`RiskConfig`. Per the P3-10 / ADR-034 process this owner-gated threshold change is
recorded as an ADR with its pinning tests updated in the same change.

---

## 2026-06-27 (ADR-034 — TWO-TIER drawdown kill-switch, owner-approved)

**Decision (owner-approved 2026-06-27): the drawdown response becomes an explicit
TWO-TIER ladder, resolving the long-standing 5%-vs-15% contradiction documented in
the P3-10 note below.**

The earlier P3-10 note recorded that SPA had *two* drawdown switches at 5% and 15%
that were "intentionally distinct" but **uncoordinated** — a recurring source of
"which threshold is the kill-switch?" confusion (CLAUDE.md / `RiskPolicy` said the
"5% drawdown kill switch", while `kill_switch.py` killed at 15%). The owner has now
chosen a single coherent semantics: the 5% threshold is a **soft de-risk**, the 15%
threshold is the **hard kill**. They are no longer two unrelated switches but two
rungs of one ladder over the **same** evidenced peak-to-current drawdown.

| Tier | Threshold | Effect | Rationale |
|---|---|---|---|
| **SOFT_DERISK** | drawdown ∈ **[5%, 15%)** | DE-RISK: **halt new allocations / no INCREASE** of any position (hold + reduce allowed); emit an **edge-triggered WARNING**. Does **NOT** liquidate. | A 5% drawdown on a stablecoin book is most often a recoverable depeg / funding wobble. Panic-liquidating it crystallises a loss that would otherwise mean-revert. So we stop *adding* risk and let the book recover — we do not sell into the dip. |
| **HARD_KILL** | drawdown ≥ **15%** | Full kill → all-cash `{"cash": 1.0, …protocols: 0.0}` (unchanged `check_drawdown_trigger` behaviour). | A 15% drawdown on a stablecoin book is not noise — it signals a real protocol collapse. Full liquidation to cash is the correct emergency stop. |

**Implementation (deterministic, stdlib-only, LLM-FORBIDDEN, fail-CLOSED, atomic):**
- `spa_core/governance/kill_switch.py`:
  - `SOFT_DERISK_THRESHOLD_PCT = 5.0` added; `DRAWDOWN_THRESHOLD_PCT = 15.0` kept.
  - `evidenced_drawdown_pct()` — the single shared evidenced + non-finite-safe
    drawdown used by BOTH tiers (so they can never disagree). Preserves the
    T6/P5-4 evidenced-bars-only segregation and the P5-1 non-finite guard verbatim.
  - `drawdown_tier()` → `NONE` / `SOFT_DERISK` / `HARD_KILL` (monotone, half-open
    bands; fail-closed to `NONE` when the drawdown is not computable).
  - `check_derisk_trigger()` + `is_derisk_active()` — the SOFT-tier `(bool, reason)`
    signal, parallel to and strictly weaker than `check_drawdown_trigger()` /
    `is_kill_switch_active()` (HARD tier — `(bool, reason)` contract UNCHANGED).
  - `run_derisk_check()` — entry point writing `data/derisk_status.json`; the
    WARNING is **edge-triggered** (only on the inactive→active transition) so a
    multi-day de-risk window does not flood the alert channel.
- `spa_core/paper_trading/cycle_gates.py::apply_soft_derisk_gate()` — caps every
  protocol's `target_usd` to its **currently-held** USD (new protocol → 0; held →
  `min(target, held)`), so the cycle can only hold or reduce, never open/increase,
  under soft de-risk. Freed capital stays in cash. Does NOT liquidate.
- `spa_core/paper_trading/cycle_runner.py` — Step 1c runs `run_derisk_check` (advisory,
  never HALTs the cycle); Step 2c-soft applies the gate AFTER the hard kill override
  (mutually exclusive — `_derisk_active` is False whenever the hard kill fires).

**RiskPolicy version:** stays **v1.0**. Per the `policy.py` GOVERNANCE process the
owner-gated thresholds in `RiskConfig` are **untouched** by this ADR — the two-tier
logic lives entirely in the governance kill-switch layer (`kill_switch.py` /
`cycle_gates.py`), not in `RiskConfig`. `RiskConfig.max_drawdown_stop = 0.05`
continues to gate `check_new_position` exactly as before (it is itself a "do not add
risk at 5%" brake, consistent with — and subsumed by — the new SOFT tier's intent).
No `RiskConfig` field changed → no version bump required; this ADR records that
decision. A future change to the 5% or 15% *values* still requires the full
owner-gated process (value + pinning test together, per the P3-10 note).

### ADDENDUM (2026-06-27, Day-2 sprint — E2E-validated, closing the two-tier behaviour)

The TWO-TIER ladder above is now **end-to-end validated** by the PRE-CUTOVER
READINESS GATE (`spa_core/paper_trading/pre_cutover_gate.py`). The gate DRIVES a
cycle through each tier against a sandbox and ASSERTS the response:

- **SOFT tier** (`SOFT_DERISK` drill): an 8% evidenced drawdown → `drawdown_tier`
  returns `SOFT_DERISK`, `check_derisk_trigger` fires, and `apply_soft_derisk_gate`
  blocks a brand-new protocol, caps an INCREASE of a held protocol to its held
  size, leaves a REDUCTION intact, and does **NOT** liquidate (held position
  stays > 0). This is the Day-1-validated, post-ALLOC-002 behaviour, now pinned.
- **HARD tier** (`HARD_KILL_DRAWDOWN` drill): a 20% evidenced drawdown →
  `check_drawdown_trigger` fires → `apply_kill_switch_override` forces ALL-CASH.

**Day-1 findings recorded as OWNER-DECISIONS to reconcile (flagged, not changed):**
**→ BOTH RESOLVED by ADR-048 (owner-approved 2026-06-27) at the top of this file:
finding #1 reconciled (hard kill lowered to 10% and DL-02 now DEFERS to it);
finding #2 fixed (boundary made inclusive `>=` so classifier and trigger agree).**

1. **DL-02 @ 10% peak preempts HARD @ 15%.** The `DailyLimitsChecker` DL-02 peak
   drawdown HALT fires at **10%** — *below* the kill-switch HARD threshold of
   **15%**. In a falling book the cycle therefore HALTs (no new trades) at 10%
   *before* the 15% all-cash kill is ever reached. This is arguably correct
   (HALT-then-kill is a safe ordering), but the two thresholds were set
   independently and their interaction is implicit. **OWNER-DECISION:** confirm
   the DL-02 10% HALT / HARD-kill 15% ordering is intentional, or reconcile the
   numbers into one explicit ladder (DL-01 2% daily · DL-02 10% peak · SOFT 5% ·
   HARD 15% — note SOFT 5% < DL-02 10% < HARD 15%, so the order of *effects* down
   a drawdown is: SOFT de-risk → DL-02 HALT → HARD all-cash).
2. **The 15.0% boundary gap.** `check_drawdown_trigger` HARD-kills on
   `drawdown > 15.0%` (strictly greater), while `drawdown_tier` classifies
   `drawdown >= 15.0%` as `TIER_HARD_KILL`. At **exactly 15.0%** the classifier
   says HARD but the trigger does **not** fire (it needs > 15.0%). The boundary is
   left strictly-greater **intentionally** to preserve the existing eval-path
   tests, but the classifier/trigger disagree on the single point 15.0%.
   **OWNER-DECISION:** make the boundary consistent (both `>=` or both `>`), or
   accept the documented 0.0%-wide gap as immaterial.

Both findings are documented here and in `docs/PRE_CUTOVER_GATE.md`; neither is a
code defect (the gate proves the defenses fire on either side of the boundary) —
they are owner-gated *threshold-reconciliation* decisions deferred to the owner.

---

## 2026-06-27 (Investigation: dual engines / track.db / data git-policy — design clarity)

**Dual promotion engines — BOTH LIVE, distinct subsystems (NOT duplicates):**
- `spa_core/paper_trading/promotion_engine.py` (PromotionEngine, Sharpe>0.8 / 14d) —
  CANONICAL для **daily-cycle** shadow-панели; вызывается из `cycle_reporting.py`
  (run_post_cycle_advisory) поверх `TournamentEvaluator`. Своих data-файлов:
  `promotion_report.json`.
- `spa_core/tournament/tournament_engine.py` (TournamentEngine, Sharpe≥1.5 / 7d / 3% / -15%) —
  CANONICAL для **standalone Tournament** сабсистема; отдельный агент
  `com.spa.tournament_engine` (09:00 UTC), свой `data/strategy_tournament.json`.
- Вердикт: РАЗНЫЕ подсистемы (разные расписания, data-файлы, пороги) — НЕ dead, НЕ
  дубликаты. Docstrings обоих помечены canonical-for-X. Кода не удалял.

**Allocators — single live money-path:**
- `spa_core/allocator/allocator.py::StrategyAllocator` — CANONICAL live money-path
  (cycle_runner `_build_real_allocator`). Помечен в docstring.
- `dynamic_allocator.DynamicAllocator` — SECONDARY/experimental, only `__main__`+tests.
- `analytics/{chain,regime_adjusted,risk_weighted_capital}_allocator*` — Tier-C
  background catalog (`_module_registry`), не в money-path. Помечены / закода не удалял.

**track.db = 0 bytes — ANOMALY (benign for SSOT, defeats mirror purpose):**
- track.db = SQLite mirror (`spa_core/persistence/track_store.py`), пишется в каждом
  цикле через `_default_track_persister` (cycle_runner). JSON = SSOT; track.db — лишь
  crash-recovery зеркало + то, что `backup.py`/`dr_backup.py` пакуют в архив.
- Прогон `TrackStore.sync_from_json` против sandbox-копии живого JSON → 94 KB DB
  (17 trades, 38 equity points). `_publish` использует `os.replace` полностью
  собранной scratch-DB → 0 байт НЕ может быть результатом успешного sync.
- Вывод: live track.db рассинхронизирован/clobbered (mtime сегодня 12:02 ≠ cycle 06:00),
  `_persist_track` глотает ВСЕ исключения (cycle логирует `ok`). Site/SSOT не страдает
  (читает JSON), но backup-архивы сейчас несут ПУСТУЮ track.db. Рекомендация: проверить
  `/tmp/spa_daily_cycle*.log` на `track_persist_failed` + проверить доступность
  `$SPA_BACKUP_DIR`/iCloud (run_backup в том же персистере). НЕ удалял.

**data/ git-policy (equity_curve_daily / golive_status / paper_evidence_history):**
- Вердикт: **KEEP-TRACKED** (НЕ untrack). GitHub Pages dashboard (`index.html`,
  deploy-pages.yml `path:'.'`, yurii-spa.github.io/SPA/) читает committed копии как
  static/offline fallback: `STATIC_DATA_BASE='/SPA/data'` И remote
  `RAW_DATA_BASE='https://raw.githubusercontent.com/yurii-spa/SPA/main/data'`
  (`golive_status.json`). Untrack → сломает fallback когда live API down.
- (Astro-landing использует ОТДЕЛЬНЫЙ `landing/src/data/track_snapshot.json`, не
  committed data/*.json — но github.io dashboard зависит от committed копий.)

> **UPDATE 2026-06-28 — обоснование SUPERSEDED:** legacy github.io dashboard
> (`index.html`, `deploy-pages.yml`, `spa_frontend/`) **удалён**. Это был ЕДИНСТВЕННЫЙ
> потребитель committed `STATIC_DATA_BASE`/`RAW_DATA_BASE`-fallback. Теперь ничего не
> читает закоммиченные `data/*.json` (canonical дашборд `earn-defi.com/dashboard` —
> Astro, берёт всё вживую из `api.earn-defi.com`). → Untrack этих трёх снимков теперь
> **технически безопасен** (fallback нечего ломать). Сам untrack остаётся **owner-gated**;
> здесь фиксируется лишь, что блокер «сломает fallback» больше не действует.

---

## 2026-06-26 (P3-10 — Dual-drawdown design note + governance invariant test)

**ADR-style note: the two drawdown switches are INTENTIONALLY DISTINCT (do NOT conflate).**

SPA has **two separate drawdown circuit-breakers** that live in different layers,
fire on different measurements, and have NO cross-reconciliation today. This is
deliberate. The 5% and 15% thresholds are **owner-gated** — this note documents
the design, it does NOT change any value.

| | RiskPolicy 5% stop | Kill-switch 15% stop |
|---|---|---|
| File | `spa_core/risk/policy.py` (`RiskConfig.max_drawdown_stop = 0.05`) | `spa_core/governance/kill_switch.py` (`DRAWDOWN_THRESHOLD_PCT = 15.0`) |
| Measurement | **intra-cycle** unrealized P&L vs deployed capital (`PortfolioState.total_drawdown_pct`, computed fresh each cycle from current positions) | **peak-to-current** over the last 30 **evidenced** equity bars (`check_drawdown_trigger`, warmup/backfill excluded — N1 fix) |
| Trigger window | the *current* cycle's snapshot | rolling 30-day real track |
| Effect | **blocks NEW positions** (`check_new_position` → `approved=False`); held book is NOT force-liquidated by this rule | **liquidates ALL** → forces `{"cash": 1.0, …protocols: 0.0}` all-cash allocation |
| Severity | per-trade gate | account-level emergency stop |

**Why distinct (not a bug):**
- The 5% policy stop is a *tight intra-cycle brake on adding risk* — if the book
  is already 5% underwater on a single snapshot, do not pile on new exposure.
- The 15% kill-switch is a *wider, slower, account-level liquidation* measured
  over the honest 30-day track, with explicit safety carve-outs (only evidenced
  real bars count, so a warmup/demo peak can't fabricate a 15% drawdown that
  closes the live book).
- They answer different questions ("should I add this position right now?" vs
  "is the whole account in an emergency?"), so a single threshold would be wrong
  for at least one of them.

**No cross-check exists today.** Neither switch reads the other's threshold or
state. A 6% intra-cycle drawdown blocks new trades but does NOT trip the
kill-switch (which needs 15% peak-to-current over the real series); conversely the
kill-switch can fire on a slow 30-day bleed that never showed a 5% single-cycle
snapshot.

**IF the owner ever decides to RECONCILE them** (e.g. tier the policy stop off the
kill-switch peak, or unify the measurement basis), then **BOTH the values AND their
pinning tests MUST change together** — never one alone:
- `spa_core/risk/policy.py` (`max_drawdown_stop`) + `spa_core/tests/test_risk_policy*.py`
  (incl. `test_drawdown_kill_switch_threshold_blocks_directly` in
  `test_risk_policy_gate.py`).
- `spa_core/governance/kill_switch.py` (`DRAWDOWN_THRESHOLD_PCT`) +
  `spa_core/tests/test_kill_switch.py`.
- Owner sign-off + a new ADR (per `policy.py` GOVERNANCE change process), because
  both are owner-gated risk parameters.

This note exists to prevent a future agent from silently conflating the two
(e.g. "drawdown is 5% in one file and 15% in another — let me 'fix' the
inconsistency"). They are **not** inconsistent; they are two switches.

**Also shipped (P3-10, Part A): governance non-override invariant test.**
CLAUDE.md / `policy.py` rule "approved=False from RiskPolicy CANNOT be overridden
by any agent" was enforced only by convention. Added direct tests on the N12 gate
(`spa_core/paper_trading/risk_gate.py::_apply_risk_policy_gate`) in
`spa_core/tests/test_risk_policy_gate.py` asserting: for EVERY rejection reason
(T1/T2 concentration, T2-total cap, TVL floor, APY bounds, drawdown) the gate
verdict is always `approved=False`; no caller input / kwarg / adapter flag / tier
relabelling flips it back to True; a gate exception **fails closed**; the only
benign escape (min-cash trim) approves a strictly *more conservative* book. Test
fails the instant any path lets a rejection through as approved.

---

## 2026-06-21 (APY Expectation Recalibration)

**APY Expectation Recalibration (2026-06-21):** Real blended T1/T2 APY ~4.1% (confirmed by
11-day paper track). Historical DeFiLlama mean 3.5–5%. Previous estimates of 5–7% were optimistic.

DeFiLlama live scan (2026-06) per protocol (USDC pools, mean / current):
- Aave V3: 3.64% mean, ~3.1% current (range 1.57–12.60%)
- Compound V3: 3.78% mean, ~3.27% current (range 2.34–11.70%)
- Morpho Blue: 6.87% mean, ~4.65% current curated vaults (range 3.55–9.57%)
- Yearn V3: 4.93% mean (range 1.37–16.05%)
- Sky sUSDS: 4.20% mean, ~3.60% current (range 3.60–4.75%)
- Fluid USDC: 6.22% current (new T2, added to adapter table)

**Корректировки:** CLAUDE.md adapter-таблица обновлена (Compound ~4.8%→~3.3%, Morpho
Steakhouse ~6.5%→~4.6% curated, Aave ~3.5%→~3.1% current); добавлена строка «T1 blended
realistic yield: 3.5–5% (не 5–6.5%)». RULES.md: `apy_below_benchmark` benchmark
зафиксирован на ~4% (T1-only не вытягивает 5% надёжно; жёсткого 5%-GoLive-гейта нет).

---

## 2026-06-21 (Session decisions — ADR-042…047)

Шесть решений сессии задокументированы как ADR. Исходно черновики были
пронумерованы 030–035, но эти номера заняты (ADR-030…041 уже существуют), поэтому
перенумерованы в **ADR-042…047** для непрерывной последовательности.

| ADR | Тема | Status | Ключевое |
|-----|------|--------|----------|
| [ADR-042](adr/ADR-042-backtest-harness-design.md) | Backtest Harness Design | Accepted | 35+ backtest-файлов наконец прогнаны; adapter-harness в `scripts/run_backtest.py` нормализует 3 несовместимых интерфейса в дневные equity curves. S7=11.08%, S2=8.98%, S0=5.72% (90д synthetic). **S7 bear = −14.28%** — risk-сигнал. |
| [ADR-043](adr/ADR-043-new-protocol-adapters-ethena-fluid-usual.md) | New Protocol Adapters (Ethena/Fluid/Usual) | Accepted | 3 новых T2-адаптера, layered fallback (direct API → DeFiLlama → cache). Live APY: Ethena 3.50%, Fluid 6.22%, Usual 2.27%. Registry → 22 активных tuple. |
| [ADR-044](adr/ADR-044-bear-market-hedge-strategy.md) | Bear-Market Hedge S31 + Market-Neutral S32 | **Proposed** | Мотивирован S7 −14.28%. Regime detection: Aave utilization + T2 APY trend. Target max DD <0.5% в bear. S31/S32 ещё не реализованы. |
| [ADR-045](adr/ADR-045-kelly-criterion-allocation.md) | Kelly Criterion Allocation | Accepted | Half-Kelly (50% blend), tier-based hack prob: T1 0.5%/y, T2 2.0%, T3 5.0%. Реализован `spa_core/allocator/kelly_sizer.py`. Supersedes ADR_012 sizing rationale. |
| [ADR-046](adr/ADR-046-multi-chain-expansion-strategy.md) | Multi-Chain Expansion | Accepted | Read-only адаптеры Arbitrum (Aave/Radiant/GMX) + Optimism (Aave/Velodrome). Bridge risk + gas monitoring. T2-until-proven per-chain. |
| [ADR-047](adr/ADR-047-site-privacy-hardening.md) | Site Privacy Hardening (earn-defi.com) | Accepted | Reframe → «personal research project, paper validation». `noindex` все страницы, удалён mechanism of entry, переработан emergency-withdrawal. `scripts/cf_install_token.command` НЕ пушится (secrets policy). |

**Что сделано:**
- Прочитан формат существующих ADR (ADR-041, ADR_TEMPLATE) и `docs/DECISIONS.md`
- Верифицированы артефакты сессии в репо: `scripts/run_backtest.py` ✓, адаптеры
  ethena/fluid/usual ✓ (T2, MP-1227), `kelly_sizer.py` ✓ (half-Kelly, T1/T2/T3 = 0.5/2.0/5.0%),
  arb/op адаптеры ✓. S31/S32 — **отсутствуют** → ADR-044 в статусе Proposed.
- Написаны 6 ADR (042–047), обновлён `docs/adr/ADR_INDEX.md`

**Заметки:**
- Перенумерация 030–035 → 042–047 (коллизия номеров)
- ADR-045 ссылается и supersede'ит sizing-обоснование `docs/ADR_012_dynamic_kelly_sizing.md`
- SECURITY: `scripts/cf_install_token.command` исключён из всех пушей

---

## 2026-06-12 (v4.64 Phase2 Roadmap)

**Что сделано:**
- Прочитан полный контекст: CURRENT_STATE, KANBAN, RULES, ADR-002, golive_status, equity_curve, gap_monitor
- Оценка готовности к Phase 2: **42/100** (главный блокер — 3/30 дней трека)
- GoLiveChecker: технически READY (все 6 критериев), но ADR-002 требует READY 7+ дней подряд — ETA 2026-06-17
- Создан `docs/PHASE2_ROADMAP.md` — критический путь, sprint plan v4.64–v4.70, риски
- KANBAN обновлён: sprint_current → v4.64; добавлены MP-350 (Telegram activation), MP-351 (preflight script), MP-352 (chain concentration)

**Ключевые выводы:**
- Autopush работал раньше как автономный агент v4.64 — KANBAN уже на v4.64 при нашей работе
- Минимальный путь к live-пилоту: MP-402 ✅ → 30d track → ADR-002 review → activate.py (ERC-4626 не нужен для личного пилота)
- Все Phase 2 features (MP-403-507) в правильном dependency order, разблокированы последовательно

**Топ-5 блокеров (не изменились):**
1. Трек record: 3/30 дней (27 дней ждать)
2. MP-313: bash mp009_fix_launchd.command (USER ACTION P0)
3. UA-004: GitHub Pages (USER ACTION P1)
4. MP-017: RPC keys для Pendle (USER ACTION P1)
5. ADR-011 manual review (Owner action к 2026-07-15)

**Следующий автономный sprint (v4.64):**
- MP-350: Активировать Telegram daily report (снять dry_run) — код готов, token в Keychain
- MP-351: ADR-011 pre-flight скрипт — автоматизировать всё что можно из 39-point checklist
- MP-352: ethereum chain concentration → разобраться и понизить до INFO если структурно

---

## 2026-06-12 (SYS-sprint)

**Что сделано:**
- Аудит истории проекта (SPA_audit_report.md, 561 строка)
- Выявлено 7 категорий системных ошибок
- Создано 13 SYS-задач в KANBAN backlog (SYS-001..010, MP-312..314)
- MP-310 Decision Audit Trail (72 теста)
- MP-146 Ulcer Index (81 тест)
- MP-147 Bias Ratio (58 тестов)
- CURRENT_STATE.md создан (SYS-001)
- CLAUDE.md согласован с реальностью (SYS-002)
- DECISIONS.md создан (SYS-006)

**Что НЕ сделано и почему:**
- Autopush не работает (USER ACTION: `bash mp009_fix_launchd.command` — пользователь не запустил)
- Telegram daily report не активирован (ждёт Telegram token от пользователя, задача MP-314)
- GitHub Pages не включены (USER ACTION: Settings → Pages → main/root)
- Sprint log v4.31-v4.47 пропущен (9 записей, задача SYS-009 в backlog)

**Блокеры для следующей сессии:**
- USER ACTION: `bash mp009_fix_launchd.command` (P0, ~2 мин)
- USER ACTION: Telegram token → daily report (MP-314)

**Следующий приоритет (автономно):**
- SYS-003/004/005/007/008: Обновить RULES.md (sprint DoD, infra-first, anti-HALT, startup, delivery_status)
- SYS-009: Восстановить sprint log v4.31-v4.47
- MP-312: Kill-switch drill

---

## 2026-06-12 (MP-412 ADR-023 Strategy Promotion Policy)

| ADR | Date | Topic | Status | Notes |
|-----|------|-------|--------|-------|
| ADR-023 | 2026-06-12 | Strategy Promotion Policy Paper→Live | Accepted | T3 requires 30d, T1/T2 14d |

**Что сделано:**
- Создан `docs/ADR-023-strategy-promotion-policy.md` — детерминированные критерии продвижения стратегий
- Promotion Gate: MIN_DAYS_PAPER ≥14d, SHARPE ≥0.80, MAX_DD ≥-5%, APY ≥7.0%, CALMAR ≥1.0
- T3/T3-SPEC (S7, S8, S10): MIN_DAYS ≥30d, SHARPE ≥1.0, MAX_ALLOC 30%, требует USER_APPROVAL
- S7 (Pendle YT+PT, 10.115% APY) — первая стратегия выше 10% барьера, Est. promotion 2026-07-12
- KANBAN: MP-412 → done
