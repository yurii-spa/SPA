# Paper Trading Week 2 Analysis (Jun 18–21)

> Generated 2026-06-21. Source of truth: `data/equity_curve_daily.json` (real track,
> `is_warmup:false`, `is_demo:false`). Real track started **2026-06-10**; all bars
> before that date are pre-teardown warmup and excluded.
>
> **Data cutoff:** the latest completed cycle is **2026-06-20 close** ($100,121.33).
> The 2026-06-21 cycle runs at 08:00 via `com.spa.daily_cycle` and is not yet in the
> dataset. To keep the 11 real bars balanced, weeks are split **Jun 10–16 (7d)** and
> **Jun 17–20 (4d)**.

## Performance Summary

| Metric | Week 1 (Jun 10–16) | Week 2 (Jun 17–20) | Overall (Jun 10–20) |
|--------|--------------------|--------------------|---------------------|
| Start equity | $100,000.00 | $100,075.67 | $100,000.00 |
| End equity | $100,075.67 | $100,121.33 | $100,121.33 |
| Return | +0.0757% | +0.0456% | **+0.1213%** |
| Annualized APY | ~3.94% | ~4.33% | **4.11%** |
| Positive days | 7/7 | 4/4 | **11/11** |
| Best day | Jun 16 +0.0108% | **Jun 20 +0.0132%** | Jun 20 +0.0132% |
| Worst day | Jun 16 +0.0108% | Jun 17 +0.0108% | +0.0108% (no losing day) |
| Max drawdown | 0.00% | 0.00% | **0.00%** (real track) |

*Daily returns Jun 11–19 were flat at ≈ +0.0108%/day ($10.81/day yield at 3.94% APY).
"Worst day" reflects the lowest positive day — there were **no negative days**. The
`-0.20%` figure in the equity-curve summary is a bookkeeping artifact of the Jun 10
equity reset to $100k, not a realized loss.*

## GoLive Progress

- **Days complete:** 11/30 honest track days
- **Days remaining:** 19
- **Projected completion:** **2026-07-09**
- **GoLiveChecker:** 27/29 PASS (`ready:false`, v6.0-29criteria)
- **Remaining blockers (both time-based):**
  - `min_track_days_30` — 11/30 days (PENDING, → 2026-07-09)
  - `gap_monitor_30d` — 11/30 continuous days, no gaps so far (PENDING, → 2026-07-09)
- **All risk controls: PASS** — `drawdown_below_kill`, `apy_above_floor`,
  `risk_policy_snapshot`, `adapter_registry_complete`, `audit_trail_signed`
- Go-live decision gate per ADR-002: READY 7+ consecutive days + 30-day gap_monitor +
  manual Owner review. Target go-live **~2026-08-01**.

## Key Observations

1. **Major diversification event on Jun 20.** The portfolio rebalanced from 5
   concentrated positions (~$95k across aave_v3/compound_v3/yearn/euler/maple) to
   **24 positions** spanning Ethereum, Arbitrum, Optimism, Polygon and Base, plus new
   sleeves (spark_susds, morpho_steakhouse, pendle, susde, sdai, frax family). This
   lifted blended APY 3.94% → **4.82%** and daily yield $10.81 → **$13.23**.

2. **Steady, monotonic accrual.** 11/11 positive days, zero realized drawdown, daily
   volatility ~0.002%. Behavior is consistent with a diversified stablecoin yield book
   — low variance is expected, not alpha.

3. **Annualized 4.11% is honest and within policy bounds.** Above the APY floor and
   below the speculative band; no single position breaches T1 40% / T2 20% caps after
   the Jun 20 rebalance (largest position morpho_steakhouse ~$8.9k ≈ 8.9%).

4. **Cash buffer maintained.** $5,000.12 cash (5.0%) held against $94,999.88 deployed —
   satisfies the ≥5% min-cash-buffer rule exactly.

5. **GoLive is purely time-gated.** Every structural, infra, adapter, and risk
   criterion passes. The only two open items are the 30-day track-length requirements,
   both on track for **2026-07-09** assuming the daily cycle stays gap-free.
