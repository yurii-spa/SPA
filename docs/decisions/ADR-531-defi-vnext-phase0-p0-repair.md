# ADR-531: DeFi Engine vNext — Phase 0: P0 safety & data-integrity repair

- **Status:** ACCEPTED · 2026-10-01 · owner: @yurii (owner directive «DEFI ENGINE vNEXT — PHASE 0 P0 SAFETY &
  DATA INTEGRITY REPAIR», autonomous execution authorised in it)
- **Scope:** the four P0 defects of the DeFi gap audit ([ADR-530](ADR-530-defi-architecture-gap-audit.md),
  `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` §J). P0-1, P0-2 and P0-3 are fixed in code. P0-4 (public wording)
  is prepared as an owner package and **not published**.
- **Not changed:** RiskPolicy v1.0 and every numeric limit (SOFT −5 % / HARD −10 %, red-flag threshold 5,
  caps, TVL floor), allocation policy, the Conservative track, live capital (0), the Trading Research Engine,
  `landing/**`. No new agent.

## P0-1 — Balanced / Aggressive paper economics

**Root cause.** Three properties of model v1 compounded:
1. `sleeve_book.rebalance_book` re-sized EVERY kept leg to `equity × weight` each day.
2. Accrued interest raised `equity` but not the legs' notionals, so the next day each leg "moved" by its
   share of the yield.
3. `book_move_cost` had no dust band, so every such few-dollar delta was a touched leg paying full Ethereum
   gas ($12).

Measured result: Balanced $48.03 cost vs $13.77 yield a day, Aggressive $24.01 vs $14.34. Both tracks lost
money by construction.

**Fix, model `sleeve-econ-v2`.**
- **In place:** interest (`accrue_book(compound_in_place=True)`) and observed instrument re-marks
  (`mark_to_market(revalue_notional=True)`) stay inside the position, as in a real lending position, with
  no transaction.
- **Dust band:** a kept leg within the dust band is neither moved nor charged. The band is the SAME rule as
  the Conservative book (`TriggerParams.min_leg_frac`, `sleeve_book.dust_band_usd`), with no second number.
- **Never over-deployed at rebalance:** if kept legs would sum above equity, every leg is re-sized,
  deterministically. On a real-move day, cost is debited after sizing, so the stored sum can exceed
  equity by at most that cost until the next day's re-size, which is free; the same holds in v1.
- **Real moves still pay:** an open, a close or a re-sizing beyond the band pays the cost model.
- **Measured on the decided book:** cost is computed on the decided pre-accrual book, the same input
  `sleeve_replay` uses.
- **Versioned:** every new history row and archive record carries `economics_model` and `cost_dust_usd`.
  `sleeve_replay` recomputes each day with the model that wrote it, so v1 days still re-derive exactly as
  they were written.

**Verification.** A sandbox on a copy of live inputs ran 5 simulated days: cost $0.00 and turnover $0 on
every drift-only day, net = yield. Replay passes across 22 v1 + 5 v2 archived days (max diff $0.005).

## Balanced / Aggressive track treatment (no silent rewrite)

- History is **not** rewritten. All 39 existing rows of each book stay as written and are classified
  **v1 — DISTORTED** (phantom gas from 2026-09-10; literal rates 08-24…09-09).
- Each book's state gets a one-time `economics_model_boundary`: v1 rows, last v1 date, first v2 date,
  defect discovery time 2026-10-01T07:50Z, activation time. It is written by the first v2 cycle.
- `generate_track_snapshot` publishes `post_fix` (v2-only days and APY) and the boundary next to the
  unchanged `apy_pct`. The two are never merged into one number.
- **Recommendation (owner subject №2, public numbers):**
  - Publish Balanced/Aggressive performance from the v2 boundary only, as a new track version.
  - Show the v1 period as «distorted by a cost-model defect, kept for audit».
  - Do NOT delete or restate v1 rows.
  - Until the owner decides, the published `apy_pct` stays as computed, and the boundary is available to
    every report.

## P0-2 — Kill switch fail-open

Every trigger now has one outcome:

| Outcome | Meaning |
|---|---|
| `TRIGGERED` | the trigger fired |
| `CLEAR` | measured, threshold not reached |
| `PARTIAL` | measured on live categories; the rest named |
| `NOT_APPLICABLE` | no evidenced series yet (track start), or a thin Sharpe sample |
| `UNMEASURED` | the input is not a current, live observation |

`summarize` returns «all triggers clear» **only** when every trigger is `CLEAR`.

Truth table for red flags (threshold and the CRITICAL-on-held rule are unchanged):

| Input | Outcome |
|---|---|
| live, no CRITICAL on held / only WARN / ≤ threshold | CLEAR |
| > threshold CRITICAL-on-held live flags (also inside a `fallback_used` document) | TRIGGERED |
| `fallback_used` or some flags not live, live categories measured | PARTIAL (non-live flags named) |
| file missing / not JSON / not an object / no flag list / no `generated_at` | UNMEASURED |
| older than 1800 s (`uptime_monitor` liveness window of `com.spa.red_flag_monitor`) | UNMEASURED |
| all sources bootstrap, or a provenance map with no live category | UNMEASURED |
| positions file present but unreadable | UNMEASURED |
| positions file absent (first cycle) | held = ∅ (measured) |

**Which flag is live.** `split_live_red_flags` is one rule, used by both the kill switch and
`threat_reactor`. A flag is live only if:
- its own `source` is not bootstrap, AND
- its category is `live` in the monitor's MEASURED `provenance.by_category`.

On 2026-10-01 a CRITICAL `token_unlock` flag carried `source: defillama` while its whole category was
bootstrap, so the field alone would have counted fixture data and risked a false kill.

**Action on UNMEASURED.** The cycle routes it into the existing LAW 1 FAIL-SAFE HOLD: hold positions, no new
trades, CRITICAL alert, exit code `EXIT_SAFETY_UNMEASURED`. It does not liquidate. Absence of evidence of
danger is not evidence of danger, and «clear» is never written. The cycle passes its own clock to
`run_kill_switch_check(now=)`.

**threat_reactor.**
- Its designed rule is kept: ONE CRITICAL live flag on a held protocol is a threat (MP-REACT; its
  tests pin it). It is now trustworthy instead of dead:
  - the document must be MEASURED (`evaluate_red_flags` not UNMEASURED, so fresh and stamped);
  - the flag must be live by source and category provenance;
  - the held match is exact, not a substring match (independent review, B2).
- New `unmeasured` list: missing, stale or UNKNOWN peg report; unmeasured red flags; missing emergency
  status.
- `clear` is true only with no threats AND nothing unmeasured.
- Kill-switch state UNMEASURED reads as `unknown`, so recovery is not announced.

On today's live data: red flags are PARTIAL (4 non-live flags named), kill state CLEAR_PARTIAL, no hold.

## P0-3 — Peg monitor false GREEN

- **No synthetic price:** `get_peg_price` returns `None` when no price field exists; there is no 1.0.
- **Price sources:** the adapter's own field, or the fresh RTMR multi-source quorum price of the base asset
  (`signals/latest.json`, `staleness_ok`, ≤ 1800 s). Both present and ≥ CAUTION apart ⇒ the worse price,
  with `conflict=true`.
- **Watched set:** held positions of all three books, plus book cash. An asset reached only by the old
  «USDC» name fallback is never priced.
- **Overall status:** RED > UNKNOWN > YELLOW > GREEN. GREEN only when every watched asset is measured and
  stable; empty set, any UNMEASURED, unreadable positions, or an error ⇒ UNKNOWN.
- **Downstream:**
  - The sleeve MTM accepts only instrument (`price_source` adapter) prices.
  - `integrated_risk_dashboard` no longer paints missing/UNKNOWN status green.
  - `threat_reactor` treats UNKNOWN as unmeasured.

On today's live data, 7 of 8 held assets are measured via the USDC quorum. Overall is UNKNOWN because the
Balanced book's sUSDe (USDe) has no quorum. That is a real monitoring-coverage gap (Phase 1), now visible
instead of green.

## P0-4 — public wording

`docs/owner_packages/2026-10-01-defi-p0-4-site-wording.md` covers the eight evidenced contradictions, with
page:line, old → proposed EN/RU, facts only and no new numbers. The owner card is
`nimbalyst-local/tracker/owner-decision-sait-ubrat-vosem-utverzhdenii-kotorye-ne.md`. It is published only
after approval, via `scripts/safe_site_push.py`.

## Tests

**New: `spa_core/tests/test_defi_p0_repair.py`.** 52 tests: the full P0-2 truth table, the P0-3
price-source cases, P0-1 economics and replay versioning, cycle E2E for LAW 1, reactor and dashboard
downstream. 32 named mutations (25 before review + 7 for the review fixes), each turning a test red, including a reintroduction of the over-strict
«all flags bootstrap ⇒ UNMEASURED» rule that would have held the live book daily.

**Existing tests changed** (each with an in-test note and a journal entry, inv. #16):
- **Fixtures given the inputs the real writers always emit:** `generated_at`, provenance, the held book, a
  measured red-flag document via `spa_core/tests/_measured_inputs.py`. The frozen 2026-06 literal
  timestamps were replaced with the current time, which shrinks the frozen-date population.
- **Tests that asserted a defect were inverted to the new contract:** 1.0 fallback, «missing adapter ⇒
  STABLE», «empty ⇒ GREEN», «fallback with live sources ⇒ ignored».
- **One golden field updated:** the characterization golden's `kill_switch_reason` on a first cycle.
- No assertion was removed or weakened. Every inverted one is stricter.

## Independent review (adversarial, separate agent) — findings and resolution

| # | Finding | Resolution |
|---|---|---|
| B1 | the pre-cutover readiness drill wrote an unstamped red-flags document ⇒ UNMEASURED ⇒ the drill failed (money-path readiness gate red) | the drill writes a fresh, provenanced document; `test_pre_cutover_gate` 31/31; a drill mutation turns it red |
| B2 | the reactor could liquidate on ONE stale, substring-matched live flag | it acts only on a MEASURED document (fresh), with live-by-category flags and an exact held match; its designed single-flag rule (MP-REACT, pinned by `tests/test_kill_switch_eval_path.py`) is kept, since raising it to the daily threshold would silently weaken a designed safety trigger; tests assert both directions |
| S2 | MTM could take the worse quorum price on `adapter+rtmr` rows | `instrument_price` is stored separately; MTM uses only it |
| S3 | legacy synthetic `mark_price` 1.0 on live legs would book a phantom jump at the first real mark | marks are dropped when the model boundary is first written (tested) |
| S5 | downstream readers saw only `triggered` | `golive_preflight` (warn), `paper_trading_kickoff` (not met), `rules_watchdog` (unchecked) honour `state`; the API live router stays display-only (P1) |
| S6 | a fallback document with no provenance and no live flags was PARTIAL | it is now UNMEASURED |
| S7 | an unreadable equity file read as «track not started» | present-but-unreadable ⇒ UNMEASURED |
| nit | future-dated documents passed as fresh | > 5 min in the future ⇒ UNMEASURED (kill switch and reactor) |

Recorded as P1 debt, not fixed in Phase 0:
- **S1:** no USDe quorum, so peg stays UNKNOWN while Balanced holds sUSDe. Effects: the reactor's
  `clear=false`, kill-switch alert recovery is held back, and the series anomaly detector lists the
  UNMEASURED row as a WARN anomaly.
- **S4:** one adapter price field serves both «peg» and «instrument price».
- The kill switch's held set reads the main book only.
- **Pre-existing:** `intraday_equity` uses the absolute deviation, so it never marks down on a depeg.
- The dust band depends on `SPA_CAPITAL_MODE` (replay is safe: the band is archived).
