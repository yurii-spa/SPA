# 41 — Performance Reporting Methodology (§36)

**Purpose.** Define how returns are measured, disclosed, and framed: the paper-vs-live separation, the
APY taxonomy applied to reporting, the return methodologies (TWR, MWR/IRR), drawdown definitions,
risk-adjusted metrics, the mandatory disclosures on every figure, and reporting cadence/templates. This
is the methodology behind every number the dashboard ([`26`](26_dashboard_specification.md)) and reports
render.

**Scope discipline — honesty first.** Paper / backtest performance is **never** presented as live
([`06_spa_core_invariants.md`](06_spa_core_invariants.md), invariant C-8). The "evidenced" track counts
only real daily-cycle-log-backed days; backfill / reconstructed / warmup / demo days are excluded and
labelled. Every performance figure carries its evidence level (L0–L6,
[`37`](37_apy_realism_and_evidence_standard.md)), yield source, risk category, and last-verified date.
**No invented numbers.** No LLM in the reporting/measurement path (deterministic).

**Cross-references:** [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)
(evidence levels + APY taxonomy), [`26_dashboard_specification.md`](26_dashboard_specification.md)
(display surface + invariants), [`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md)
(capital-compression disclosure), the evidenced-track honesty model (`golive_checker.py`,
`paper_evidence_history.json`, gap monitor).

---

## 1. Paper vs live distinction

- **Separate labelling, separate surfaces.** Paper (L3) is always labelled "paper" and never shown on a
  live surface; a backtest is evidence toward L1/L2 at most and is never called "live-tested"
  ([`37`](37_apy_realism_and_evidence_standard.md) rule 2).
- **Evidenced track = real cycle-log days only.** The reference honesty model is the existing evidenced
  paper track: only continuous, real daily-cycle-backed days count; backfilled/warmup/demo bars are
  excluded and explicitly labelled, and continuity is enforced by `golive_checker.py` (29 criteria) +
  the gap monitor.

---

## 2. APY taxonomy in reporting

Every reported yield states **which** of the six taxonomy numbers it is
([`37`](37_apy_realism_and_evidence_standard.md) §2): **advertised → observed → executable → net →
sustainable → risk-adjusted**. Reports lead with the honest end (net / sustainable / risk-adjusted) and
never present advertised as observed or gross as net. Net = executable minus fees, gas, slippage, hedge
cost, roll cost. Sustainable = net after stripping non-recurring incentives/points and after
capital-compression at our size ([`34`](34_capital_tiers_strategy.md)).

---

## 3. Return methodologies

| Metric | Definition | Use |
|---|---|---|
| **Time-weighted return (TWR)** | Compounds period sub-returns, neutralizing the timing/size of external cash flows | Compare strategy/manager performance independent of deposit timing |
| **Money-weighted return (MWR / IRR)** | The rate that sets the NPV of all cash flows to zero; sensitive to cash-flow timing | Report the actual capital-experienced return |
| **Cumulative / annualized** | Total-period and annualized-equivalent return | Headline period figures (labelled paper/live + evidence level) |

TWR and MWR are reported **together** where cash flows occurred, since they answer different questions;
reporting only the more flattering one is forbidden.

---

## 4. Drawdown

- **Peak-to-current drawdown** — current equity vs the running evidenced peak; this is the measure the
  **two-tier kill-switch** acts on (SOFT −5% de-risk / HARD −10% all-cash, inclusive,
  [`06`](06_spa_core_invariants.md)). Reporting uses the same `evidenced_drawdown_pct` definition so the
  reported drawdown and the kill-switch agree.
- **Max drawdown** — the largest peak-to-trough decline over the reporting window.
- Both are computed on the **evidenced** equity series (real cycle-log days), not on any backfilled
  series.

---

## 5. Risk-adjusted metrics

- **Sharpe** — reported net-of-cost; degenerate Sharpe on mock/short data is flagged, not published as
  meaningful (a known SPA hazard: tournament Sharpe on mock data is untrustworthy).
- **Spread over the RWA floor** — the primary risk-adjusted frame: performance is reported as spread
  over the live floor (≈3.4% `requires verification`, from `data/rwa_feed.py`), and for Enhanced/Max the
  spread must be **risk-explained** ([`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
  Attribution vs the floor is advisory framing, not a gate.

---

## 6. Disclosure rules

Every reported figure carries, without exception: **evidence level (L0–L6) · yield source · risk
category · last-verified date**, plus paper/live labelling and, where size affects the rate, the
**capital-compression disclosure** ([`34`](34_capital_tiers_strategy.md), [`37`](37_apy_realism_and_evidence_standard.md)
rule 6). Unverified data is shown with explicit uncertainty (`requires verification`), never as a clean
number.

---

## 7. Reporting cadence & templates

- **Cadence.** Daily internal snapshot (evidenced track + drawdown + kill-switch state); periodic
  (monthly/quarterly) attribution report; per-strategy card update on any evidence-level change.
- **Templates.** A report template already exists (REPORT-001, evidence level per number); reports
  follow it — each number annotated with its evidence level and taxonomy type. Detailed formulae and the
  full template library are finalized at MVP 2-3, reusing the existing reporting modules
  (`spa_core/reporting/`, `spa_core/compliance/monthly_statement.py`).
