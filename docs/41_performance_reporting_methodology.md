# 41 — Performance Reporting Methodology (§36)

**Status: STUB.** This document is a Priority-3 placeholder for the performance-reporting
methodology — how returns are measured, disclosed, and framed. It lists the methodology's components
only; formulae and templates are deferred.

**Scope discipline — honesty first.** Paper / backtest performance is **never** presented as live
(see `06_spa_core_invariants.md`, invariant C-8). The "evidenced" track counts only real
daily-cycle-log-backed days; backfill / reconstructed / warmup days are excluded and labelled. Every
performance figure carries its evidence level (L0–L6, `docs/37`), yield source, risk category, and
last-verified date. No invented numbers.

**Cross-references:** `docs/37_apy_realism_and_evidence_standard.md` (evidence levels + APY taxonomy),
`docs/26_dashboard_specification.md` (display surface), the evidenced-track honesty model
(`golive_checker.py`, `paper_evidence_history.json`).

## Planned contents (outline only)

- **Paper vs live distinction** — separate labelling, separate surfaces; paper never shown as live.
- **APY taxonomy** — gross vs net (fees/gas/slippage) vs risk-adjusted; advertised vs observed vs
  executable vs sustainable.
- **Drawdown** — peak-to-current and max drawdown definitions; alignment with the two-tier
  kill-switch drawdown model.
- **Time-weighted return (TWR)** — methodology for period return isolating cash-flow timing.
- **Money-weighted return (MWR / IRR)** — methodology capturing capital-flow timing.
- **Risk-adjusted metrics** — Sharpe / vs-RWA-floor attribution (advisory framing).
- **Disclosure rules** — mandatory evidence level, yield source, risk category, last-verified date on
  every reported figure; explicit uncertainty for unverified data.
- **Reporting cadence & templates** — daily / periodic report structure (deferred).

TODO: expand at MVP 2-3 stage.
