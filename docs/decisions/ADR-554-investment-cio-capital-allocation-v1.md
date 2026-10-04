# ADR-554 · Chief Investment Officer (Штирлиц) — cross-sleeve capital allocation v1 (ADVISORY / PAPER)

- **Status:** ACCEPTED — architecture freeze (owner macro-epic 2026-10-04 «CHIEF INVESTMENT OFFICER / CAPITAL ALLOCATION»)
- **Date:** 2026-10-04
- **Related:** ADR-525 + `docs/CAPITAL_ARCHITECTURE.md` (Capital Allocator «Not built»), ADR-055 (Head-of-Investment),
  ADR-060/324/328/336 (per-book CIO veto), ADR-103/104 (house-view directive), ADR-484 (optimum loses to KEEP),
  ADR-364/366/397/398/480/547 (Portfolio CIO §49 instruments), ADR-530…533/537 (three DeFi paper portfolios),
  ADR-552 (Mission Control), ADR-129 / invariant #17 (absence is its own value).
- **Boundary:** real capital $0. No execution, no RiskPolicy / stop / limit / leverage / tier / live-admission change,
  no strategy mechanics change, no public claim. The CIO writes a RECOMMENDATION artifact; nothing consumes it as an
  instruction.

## Phase 0 — what already exists (audit 2026-10-04, three independent read-only audits)

| Responsibility | Existing implementation | Class | Belongs to the Investment CIO? |
|---|---|---|---|
| A. Investment research | Trading Research Engine (`spa_core/trading_research`, 138 candidates, append-only hash-chained evidence, 5 FORWARD_PAPER with 2–17 observations); AI Investment OS analysts `com.spa.io_*` (7 feed the chief, 3 have no decision reader); aggressive_lab / strategy_lab_paper / rates_desk research ledgers | IMPLEMENTED (research) / PARTIAL | input only |
| B. Strategy evaluation | `package_status` (work · data · decision · history · live admission), `defi_engine` (books, APY definitions, findings, passports), tournament engine (shadow), `tier_curator` (advisory) | IMPLEMENTED | input only |
| C. Portfolio construction | per-book `allocator/allocator.py` (Conservative only, 1 of 3 books); Balanced/Aggressive mechanics in `hy_cycle`/`lp_cycle` | PARTIAL (`PER_BOOK_ONLY`) | **cross-book part — yes** |
| D. Capital allocation across sleeves | none; `swarm/blend_forward.json` (susde/rates/rwa blend, paper) and `swarm/eyc_allocator.json` (shadow, authority NONE) | **MISSING** | **yes** |
| E. Risk aggregation | RiskPolicy v1.0 (Conservative only, hard gate); own stops −8 % / −25 % for Balanced/Aggressive; kill switch; `defi_engine` findings (advisory); ~90 risk/stress modules with zero importers and 3-month-stale artifacts | PARTIAL / STALE | aggregation view — yes; limits — NO (owner) |
| F. Correlation / diversification | `tier1_correlation.json` (backtest strategy blend); `correlation_matrix.json` stale 06-21; `cross_asset_correlation_log.json` stale 09-03 and mislabelled «live» | STALE / PARTIAL | yes (honest version) |
| G. Regime awareness | four classifiers, none gates capital: `market_regime.json` (APY spread), `hy_regime_log` (**proxy inputs**: funding = target APY, depeg = 0), `swarm/funding_regime.json` (the only real funding signal), trading `regime.py` | DUPLICATE | reads `funding_regime` + chief posture only |
| H. Liquidity / capacity | `defi_engine.exit_model` (illiquid share, advisory, not enforced); capacity modules unread | PARTIAL | read-side — yes |
| I. Recommendation generation | `cio_arming` (ADR-324/328): per-book reshuffle VETO on the paper money path — HOLD in 952/952 decisions, never builds a target; `chief_investment` house-view posture | PARTIAL | the per-book veto stays as is; cross-sleeve recommendation — new |
| J. Decision explanation | `allocation_rationale*` (per book), `cio_brief.py` (prose) | IMPLEMENTED per book | cross-sleeve — new |
| K. Forward validation | `shadow_trigger_eval` (NOT_READY; ADR-299: biased); trading forward paper | PARTIAL | cross-sleeve track — new |
| L. Outcome feedback | `allocation_rationale_history*.jsonl` (no outcome field) + `investment_os/outcomes.jsonl` (posture pairs); no «recommended → realised vs KEEP» ledger | **MISSING** | **yes** |
| Cash / Treasury | 5 % RiskPolicy floor (`risk/policy.py:131`) + ADR-055 cash explanation; cash earns 0 % (no accrual anywhere); RWA backstop paper (advisory) | **no sleeve** — buffer only | the KEEP/cash alternative — yes |
| Market-neutral / basis | paper research ledgers (`aggressive_lab/susde_dn`, `strategy_lab_paper/variant_n`, `rates_desk` fixed carry), outside RiskPolicy, no mandate; basis feed stale since 08-29 | EXPERIMENTAL | observe-only |

**Conclusion.** A CIO already exists in four partial forms (per-book veto, posture brake, house view, §49 meters).
What is missing is the layer CAPITAL_ARCHITECTURE calls «Not built»: a cross-sleeve, KEEP-aware, evidence-weighted
recommendation with an immutable ledger and an outcome track. v1 builds exactly that and **reuses** the rest.
The per-book veto `cio_arming` is NOT replaced or touched (it is a paper money-path mechanic).

## Role identity (stable role IDs; nicknames are display only)

`architecture/roles.json` (new, canonical):
- `chief_investment_officer` — title «Chief Investment Officer», display_name «Штирлиц», domain capital / investments /
  portfolio construction / investment research. Components: `spa_core/investment_cio` (this ADR; cross-sleeve
  advisory), `paper_trading/cio_arming.py` (per-book veto, ADR-324/328, unchanged), `investment_os/agents/chief_investment.py`
  (house view), `investment_os/directive.py` (posture brake). Authority is declared PER COMPONENT: `investment_cio`
  NONE (advisory), `cio_arming` PAPER_VETO, `directive` PAPER_BRAKE, `chief_investment` ADVISORY_INPUT_TO_BRAKE.
  `domain_excludes` separates the roles (data freshness, fleet operations, delivery are not CIO work). May: read evidence,
  publish recommendations and outcomes. May NOT: move money, execute, change RiskPolicy, limits, stops, leverage, tiers,
  live admission, strategy mechanics, publish claims.
- `chief_operating_officer` — title «Chief Operating Officer», display_name «Шурик» — RESERVED, `implemented: false`.
Authority, memory, lineage and tests bind to `role_id`; a display name never appears in a permission check.

## WP-A01 — sleeve contract (`spa_core/investment_cio/contract.py`)

Sleeves are capital sleeves, not agents. v1 universe:

| sleeve_id | Allocatable | Source of truth (projected, never copied) |
|---|---|---|
| `defi_conservative` | yes | `defi_engine/status.json` books + `package_status.public_view` + `equity_curve_daily.json` |
| `defi_balanced` | yes | same + `hy_paper_trading.json` |
| `defi_aggressive` | yes | same + `lp_paper_trading.json` |
| `cash` | yes (KEEP / buffer) | definitional: 0 % yield is a MEASURED fact (no accrual exists), not an absence |
| `trading_research` | observe-only (no book, research stage) | `trading_research/status.json` |
| `market_neutral_basis` | observe-only (no mandate) | `strategy_lab_paper/variant_n_series.json`, `aggressive_lab/susde_dn`, `rates_desk` |

Every field from the epic list exists in the contract. Each value is `{value, unit, source, as_of}` or the explicit
`NOT_MEASURED` / `NOT_ENOUGH_HISTORY` / `UNDEFINED` with a reason. A missing measurement is never 0, never `[]`,
never HEALTHY. A stale source (older than its declared cadence) makes the value `STALE` with its age.

## WP-A02 — recommendation contract (`InvestmentCIORecommendation`, schema `investment-cio-rec/1`)

`recommendation_id` (content hash) · `generated_at` · `evidence_cutoff` (max `as_of` used) · `mode: ADVISORY_PAPER` ·
`stance ∈ {RECOMMEND, HOLD, INSUFFICIENT_EVIDENCE, NO_RECOMMENDATION}` · `recommended_weights` · `seed_split_weights`
(the experiments' seeding, reported) · `previous_recommendation_id` · `change_vs_current` · `portfolio_expected_return` (realised-evidence based, labelled) ·
`portfolio_risk_summary` (per risk axis) · `portfolio_drawdown_estimate` (worst-case-to-stops + realised) ·
`liquidity_summary` · `diversification_summary` · `regime` · `confidence ∈ {LOW, MEDIUM, HIGH}` + reasons ·
`binding_constraints` · `major_risks` (by factor) · `unknowns` · `abstentions` (per sleeve, with reason) · `rationale`
(rule trace + the §44 eight facts of `cio_explainability`, each SPOKEN or named UNKNOWN) · `alternatives_considered` (KEEP, equal-weight, policy) · `evidence_refs` (file + digest) ·
`policy_version` · `code_identity` (sha256 of the package source) · `lineage` (input snapshot digest → policy →
recommendation). «NO RECOMMENDATION / HOLD / INSUFFICIENT EVIDENCE» are first-class outcomes.

## WP-A03 — allocation philosophy (`cio-policy-v1`, deterministic, no LLM) — revised after the independent review

Objective: sustainable risk-adjusted return with controlled drawdown, liquidity and diversification — **not** APY.
1. **Cash is always feasible; the reference is the SEED_SPLIT** (the experiments' equal $100k seeding — nobody's
   decision, so it is reported, never used as «KEEP» for hysteresis).
2. **Evidence gates weight, not return.** Maturity of the CURRENT economics (`valid_periods`): `< 30` IMMATURE →
   weight 0, abstain naming the reason (e.g. «re-versioned 2026-10-02, 2/30»); `30–89` DEVELOPING → cap 20 %;
   `≥ 90` MATURE → cap 50 % (an uncalibrated v1 diversification parameter, labelled as such: 90 calm accrual days
   with zero stress events prove nothing about the tail — «no tail observed» is an UNKNOWN tail, not a safe one).
   Engine mechanic caps (e.g. leveraged loop 10 %) apply on top, regardless of maturity.
3. **Exclusion gates** (weight 0, named): data not HEALTHY or STALE · work not RUNNING · own stop / kill switch /
   soft de-risk active · worst-case loss UNKNOWN · on MATURE windows only: cost-amortised realised net return below
   the named hurdle (the risk-free proxy, the Sky savings rate from the engine's pool snapshot; hurdle unreadable ⇒
   the gate is SKIPPED and that is named). The return gate keeps a bad sleeve out; it never ranks.
4. **Worst-case loss per sleeve** `S = max(nearest enforced stop, modelled stress loss at the reference stress)` —
   the stress term exists because a stop is a limit, not a loss estimate (a 3.33× loop passes its −25 % stop on a
   10 % depeg, modelled −33.3 %). Missing ⇒ UNKNOWN ⇒ ineligible.
5. **Risk budgeting**: among eligible sleeves weight ∝ 1/S, then maturity and mechanic caps, remainder to cash; the
   look-through cash floor is 5 % (RiskPolicy `min_cash_pct`, reused) computed on a look-through basis (a book's own
   cash counts; a book with UNKNOWN cash makes look-through cash UNKNOWN — never assumed).
6. **Portfolio check** (reported, not scaled): Σ wᵢ·Sᵢ vs Σ wᵢ·loss_budgetᵢ (the engine's published per-book
   budgets, from `tier_bands`); a breach is a binding constraint and a major risk (e.g. Conservative's known
   «loss_budget_unbound»: budget 3 % vs nearest stop 5 %).
7. **Stance** (field `stance`, not «decision»): `RECOMMEND` needs ≥ 2 eligible sleeves; with 1 → `INSUFFICIENT_EVIDENCE`
   and the single-sleeve weights appear only as the alternative «evidence-only portfolio (not a recommendation)»;
   with 0 → `NO_RECOMMENDATION`; `HOLD` when every |Δ| vs the PREVIOUS recommendation < 5 pp.
8. **Confidence**: LOW or MEDIUM only in v1 (MEDIUM needs ≥ 2 eligible MATURE sleeves); HIGH is unreachable until
   mark-to-market coverage and a measured price-risk correlation exist.
9. **No false precision**: weights to 1 pp; every return carries its window and n bars; a rate on < 30 bars is never
   displayed as a rate.
10. **Regime is display-only in v1** (chief posture, `swarm/funding_regime` — UNKNOWN reads as not-GREEN); it has no
   effect on weights.

## WP-A04 — risk separation

Eight axes per sleeve, each `{level ∈ LOW|MEDIUM|HIGH|UNKNOWN, evidence, source}`: PROTOCOL (tier mix, max protocol
share), STRATEGY (mechanism class), MARKET (directional / depeg exposure), EXECUTION (paper slippage/cost model),
LIQUIDITY (exit model illiquid share), COUNTERPARTY (issuer/custody of collateral), LEVERAGE (LTV/HF), DATA_MODEL
(maturity, mark-to-market coverage, stale inputs). No opaque aggregate score. RiskPolicy is read, never changed.
COUNTERPARTY has no source today ⇒ UNKNOWN. `major_risks` are keyed by underlying FACTOR (e.g. USDe peg, Maple credit,
Fluid), not by axis, so one factor hitting four axes is one risk. Exit shares are compared only on a common basis
(NAV vs deployed notional is named, never mixed).

## WP-A05 — correlation and exposure

Pearson on daily returns only when both series have ≥ 30 overlapping days on the CURRENT economics and > 5 distinct
values; otherwise `NOT_ENOUGH_HISTORY` / `UNDEFINED` (constant accrual). Today all official pairs are
NOT_ENOUGH_HISTORY (Balanced/Aggressive: 2 valid periods). Any computed coefficient is labelled
`accrual_correlation` with n (sleeve mark-to-market coverage is 0 %: it measures co-movement of APY feeds, not tail
co-movement) and never raises confidence. Exposure overlap is the primary diversification fact: look-through
per-protocol share Σ wᵢ·shareᵢ,ₚ checked read-only against the RiskPolicy caps (T1 40 % / T2 20 %, tiers from the
tier authority, not book labels), common failure-mode groups (Maple credit, Ethena/USDe peg, Fluid), leverage
(`gross_exposure_over_nav` per sleeve and portfolio), maturity, directional exposure.

## WP-A06 — modes and the no-execution boundary

States RESEARCH · PAPER · SHADOW · LIVE_NOT_APPROVED; v1 runs ADVISORY/PAPER only. Guards in BOTH directions (tests):
the CIO package imports nothing from `spa_core/execution`, `paper_trading`, `allocator`, `risk`, `governance` or
`investment_os` writers, and calls no decider name of the §41 census (`optimize`, `allocate`, `rebalance_*`); no
module under `paper_trading/`, `risk/`, `governance/`, `allocator/`, `execution/` or `investment_os/directive.py`
imports `spa_core.investment_cio` or names a path containing `investment_cio` (pattern readers included). Its only
writes: `data/investment_cio/` — never `data/investment_os/` (a brake input). It is deliberately NOT a §41 target
producer (authority NONE). `swarm/blend_forward.json` (existing cross-desk paper blend) is an observe-only input
shown as an alternative, so there are not two cross-sleeve weight producers.

## WP-S03/S04 — ledger, lineage, forward validation

- `data/investment_cio/snapshots/<sha256>.json.gz` — content-addressed, immutable input snapshot (gzipped: kept out of
  `golive_checker`'s `*.json` scan; retention 400 days). Each input carries its own `as_of`; `evidence_cutoff` is the
  OLDEST input time, and every input's age is listed.
- `data/investment_cio/ledger.jsonl` — append-only, hash-chained (`prev_hash`), ONE recommendation per UTC day;
  `flock` serialises writers; chain verified before every append (broken chain ⇒ refuse, exit 2). The DeFi snapshot is
  read from ONE document (`defi_engine/status.json`, which embeds `packages`) for an atomic cross-book view.
- `data/investment_cio/outcomes.jsonl` — append-only, separate. At horizons 7 d / 30 d, using only bars strictly after
  the recommendation date: buy-and-hold portfolio return Σ wᵢ·Eᵢ(t+h)/Eᵢ(t) − 1 (books never rebalance between
  each other) for RECOMMENDED, SEED_SPLIT and the pre-registered equal-weight universe (the three DeFi books), plus
  risk outcomes (max drawdown in the horizon, stop proximity) and the switching cost of RECOMMENDED vs SEED_SPLIT from
  the existing move-cost evidence (NOT_MEASURED when absent). Book equity is CONTINUOUS across experiment versions
  (re-versioning is recorded as an event, so a re-versioned loser cannot escape the track). The digest of each
  equity series used is stored. Skill claims count distinct-weight episodes, not rows. Recommendations are never
  edited.
- `data/investment_cio/latest.json` — pointer (atomic), rebuilt from the ledger if corrupt.
Forward-only from 2026-10-04; historical replay may supplement, never replace.

## Data-quality fixes in scope (only what the CIO reads)

1. `package_status` `valid_periods: 0` on an absent book / read-model error → `None` (absence ≠ measured zero; the
   site already renders null as «not measured»).
2. `package_status` `live_capital_usd: 0` literal → 0 only when EVERY engine (`paper_trading_status`, `defi_engine`)
   declares a paper mode, else `None` with a reason; v1 can never compute a positive value.
3. `package_status` «paused» for BOTH sleeves now includes the experiment `stop_reference` drawdown the books stop on
   (Aggressive used the legacy drawdown; Balanced only `regime == EXIT`).
4. `/api/v1/golive` overwrote the checker's `timestamp` with request time → original kept, `served_at` added.
Recorded, not changed (money-path mechanics or other owners): allocator `DEFAULT_GRADE="B"` for unscored protocols;
sleeve mark-to-market 0 when unmarked (the CIO reads `mtm_coverage_pct` and marks NOT_MEASURED); `hy_regime_log`
proxy inputs (the CIO never reads it); `market_structure` «live» label on a stale file (not read by the CIO).

## Mission Control (ADR-552) integration

One new section `capital.investment_cio` read through the CIO package's read function (no second truth), rendered as
«Штирлиц — Chief Investment Officer» in the existing Capital tab with «paper recommendation — nothing executes it»:
stance, recommended vs seed-split weights with each sleeve's maturity beside its weight,
confidence, regime, binding constraints, major risks, unknowns, abstentions, evidence maturity, PAPER · real capital
$0. No buttons.

## Architecture freeze checklist

Existing-vs-new map (above) · role ownership (roles.json) · sleeve contract · recommendation contract · risk taxonomy ·
allocation philosophy · evidence/confidence rules · correlation methodology · UNKNOWN semantics (invariant #17) ·
action boundary (no execution, AST-enforced) · lineage (snapshot → policy → recommendation → outcome) · source of
truth (engines own state; the CIO projects) — frozen. Independent review precedes implementation.

## Independent architecture review of the freeze (2026-10-04)

Eighteen findings (1 CRITICAL, 10 HIGH); every one is folded into the sections above before implementation:
F1 stop ≠ loss estimate (worst-case loss = max(stop, modelled stress)) · F2 one mature sleeve is not an allocation
(`INSUFFICIENT_EVIDENCE`) · F3 KEEP was a seeding artefact (SEED_SPLIT; hysteresis vs previous recommendation; costs)
· F4 look-through cash and gross exposure · F5 exposure overlap by factor · F6 accrual correlation labelled, HIGH
unreachable · F7 MATURE cap 50 %, unknown tail · F8 return gate MATURE-only vs a named hurdle · F9 continuous book
equity across versions · F10 per-input `as_of`, buy-and-hold outcomes, risk outcomes, series digests · F11 daily
cadence, gzipped snapshots with retention · F12 authority per component · F13 two-way guards, no `investment_os`
writes · F14 one DeFi document, blend_forward named · F15 axes measured/UNKNOWN, factor-keyed risks · F16 data-quality
fixes 2/3 tightened · F17 `stance`, «nothing executes it», regime display-only · F18 n bars on every rate.

## WP-A07 — post-implementation independent review (2026-10-04) and remediation

Twenty-one findings (1 HIGH, 10 MEDIUM, 10 LOW); no CRITICAL, no money-path coupling, no real-capital path. All
fixed, each with a test that fails without the fix:
- **HIGH 1** — Conservative's worst-case bound used SOFT_DERISK (5 %, «halt new», it does not liquidate) → only
  LIQUIDATING stops bound a loss (HARD_KILL 10 %), with daily-bar gap and credit/peg events named as unmodelled.
- **MEDIUM**:
  - 2 — the stop gate passed on a stale or missing kill state → UNKNOWN; CLEAR_PARTIAL is a named warning.
  - 3 — an input without a readable time looked fresh → NOT_MEASURED «age unknown»; research strands get a 78 h cadence.
  - 4 — HOLD could keep weight in a now-ineligible sleeve → HOLD only with an unchanged eligible set.
  - 5 — a torn ledger line was a permanent outage → single `os.write` + fsync, `LedgerError` naming the line,
    `run --repair` moves the torn tail aside (never deletes).
  - 6 — `latest.json` was served unverified → the ledger tail is always served.
  - 7 — concurrent outcome scoring duplicated rows → one lock around the whole scoring, hash-chained outcome rows.
  - 8 — the protocol-cap check claimed MEASURED while partial → PARTIAL with named unchecked protocols.
  - 9 — leverage/exposure and risk evidence were measured from absence or literals → read from sources, or
    NOT_MEASURED / UNKNOWN.
  - 10 — duplicated constants → one copy, with a parity test against `RiskConfig` and `REPORTABLE_AFTER`.
  - 11 — the role inherited veto authority → the role owns only the advisory layer; veto and brake are
    `related_preexisting` with their own ADRs.
- **LOW**:
  - 12 — n-less rates are NOT_ENOUGH_HISTORY.
  - 13 — UNKNOWN dominates when levels are combined.
  - 14 — major risks name their basis (seed split vs recommendation) and «sleeve weight touching the factor».
  - 15 — back-dated appends are refused.
  - 16 — outcomes stay pending until a bar exists (7-day grace); the anchor comes from the immutable snapshot.
  - 17 — strict `<` on stops.
  - 18 — no default 0 equity.
  - 19 — `realised_trailing` label and `evidence_cutoff_complete`.
  - 20 — `i18n.js` diff reduced to additions.
  - 21 — `anchors.jsonl` external anchor; no orphan snapshots on an idempotent re-run.
The fixes were reviewed again before delivery (journal W40).
