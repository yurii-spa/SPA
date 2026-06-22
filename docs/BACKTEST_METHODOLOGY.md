# SPA Backtest Methodology

**Document:** BACKTEST_METHODOLOGY.md  
**Version:** 1.0.0  
**Date:** 2026-06-22  
**Status:** Active  

---

## Overview

The SPA (Systematic Portfolio Allocator) backtest measures the historical risk-adjusted performance of automated DeFi stablecoin yield strategies over the period **2022–2025**. The backtest is designed to support investor due diligence and to establish a verifiable track record prior to accepting external capital. It answers one core question: *how would SPA's allocation engine have performed if it had been running on real DeFi lending markets over the past four years?*

The simulation operates in "paper trading" mode — no on-chain transactions are executed. All positions are virtual. $100,000 USDC of initial capital is allocated across a whitelist of Tier-1 and Tier-2 lending protocols, and yield is accrued at the historically observed APY for each protocol on each day.

---

## Data Sources

All APY and TVL data is sourced from the **DeFiLlama Yields API** (`yields.llama.fi/pools`), the industry-standard public aggregator for on-chain yield data. Data is fetched daily with a 300-second cache TTL and stored in `data/historical_apy/`.

| Protocol | Chain | Tier | Source Pool |
|---|---|---|---|
| Aave V3 USDC | Ethereum | T1 | DeFiLlama pool UUID |
| Compound V3 (Comet) USDC | Ethereum | T1 | DeFiLlama pool UUID |
| Morpho Steakhouse USDC | Ethereum | T1 | DeFiLlama pool UUID |
| Morpho Blue USDC | Ethereum | T2 | DeFiLlama pool UUID |
| Yearn V3 USDC | Ethereum | T2 | DeFiLlama pool UUID |
| Sky/sUSDS | Ethereum | Watch | DeFiLlama pool UUID |

**Date range:** 2022-01-01 to 2025-12-31 (historical); live track from 2026-06-10.  
**Refresh cadence:** Daily at 08:00 local time via `launchd com.spa.daily_cycle`.  
**Field used:** `apy` (annualised, as percentage, from DeFiLlama), not `apyBase` or `apyReward` separately, to capture the blended yield actually received by liquidity providers.

---

## Simulation Design

**Time step:** Daily. Each day, the yield accrual for each protocol position is computed as:

```
daily_yield_usd = position_usd × (apy_pct / 100) / 365
```

**Initial capital:** $100,000 USDC (virtual).  
**Rebalancing:** Monthly, on the first trading day of each month, or when a position deviates more than 10 percentage points from its target weight.  
**Transaction costs:** 5 basis points (0.05%) on each rebalanced notional amount, applied as a direct deduction to the portfolio NAV. This models gas costs and AMM slippage.  
**Yield compounding:** Daily. Accrued yield is added to the position balance; subsequent yield is calculated on the updated balance.  
**Cash buffer:** A minimum 5% cash reserve (uninvested USDC) is maintained at all times per `RiskPolicy v1.0`.

---

## Strategy Universe

Four strategies are evaluated across the backtest period:

**S0 — Conservative (T1-only):** Allocates exclusively to Tier-1 protocols (Aave V3, Compound V3, Morpho Steakhouse). Maximum per-protocol weight 40%. Targets capital preservation with 3.5–4.5% p.a. yield.

**S1 — Balanced:** Blends T1 (60–70%) and T2 (30–40%) protocols. Targets 4.5–5.5% p.a. yield with moderate diversification. Governed by `RiskPolicy` T2 cap of 50%.

**S2 — Yield-Maximising:** Overweights T2 protocols up to the 50% cap. Targets 5.5–6.5% p.a. yield. Higher concentration risk; subject to tighter TVL floor enforcement ($5M minimum per pool).

**S_live — Current Portfolio:** Reflects the actual allocation weights live as of the generation date, as reported by `data/current_positions.json`. Used to provide an "as-deployed" benchmark alongside the theoretical strategy variants.

---

## Performance Metrics

All metrics are computed from the daily return series $r_1, r_2, \ldots, r_n$ where $r_t = (NAV_t - NAV_{t-1}) / NAV_{t-1}$.

**Annualised Return (CAGR):** $(NAV_n / NAV_0)^{365/n} - 1$. Expressed as a percentage.

**Sharpe Ratio:** $(R_{ann} - R_f) / (\sigma_{daily} \times \sqrt{365})$, where $R_f = 4\%$ p.a. (USDC savings rate / T-bill proxy). Note: for stablecoin yield strategies with near-zero price variance, Sharpe is structurally elevated. This is a property of the asset class, not data contamination.

**Sortino Ratio:** $(R_{ann} - R_f) / (\sigma_{downside} \times \sqrt{365})$, where $\sigma_{downside}$ measures only negative daily returns. Returns `null` when there is no downside volatility.

**Calmar Ratio:** $R_{ann} / |MaxDrawdown|$. Returns `null` when max drawdown is zero.

**Maximum Drawdown:** Peak-to-trough decline as a percentage of the peak NAV.

**VaR 95%:** The 5th percentile of daily returns over the backtest period (historical simulation method, no parametric assumption).

**CVaR 95% (Expected Shortfall):** Mean of all daily returns below the VaR 95% threshold.

**Omega Ratio:** $\int_0^{\infty}[1-F(r)]dr / \int_{-\infty}^0 F(r)dr$ evaluated at $r = 0$, where $F$ is the empirical CDF of daily returns.

---

## Benchmarks

**Primary benchmark:** USDC savings rate of **4.0% p.a.** This is the annualised return an investor would earn by holding USDC in a simple savings product (Coinbase USDC yield, Circle Reserve, or equivalent). It serves as the risk-free rate for Sharpe computation and the "do-nothing" comparison.

**Secondary benchmark:** T-bill proxy at **4.0% p.a.** (regime-adjusted), representing the annualised US 3-month T-bill rate for the 2022–2025 period. Rates varied from ~0.1% (early 2022) to ~5.4% (late 2023) and back to ~4.3% (2025); the 4.0% figure is the period-weighted average.

**Tertiary benchmark (within DeFi):** Lazy Aave — 100% allocation to Aave V3 USDC with no rebalancing. Measures alpha generated by the active allocation strategy versus a passive single-protocol position.

---

## Walk-Forward Validation

To test for overfitting and regime-consistency, a walk-forward validation is applied:

**Train:** 2022–2024 (3 years of daily APY data, 1,095 observations).  
**Test:** 2025 (1 year hold-out, 365 observations).  

**Procedure:** Strategy weights are optimised on the training set (maximise Sharpe subject to RiskPolicy constraints). The resulting weight vector is then applied without modification to the 2025 test set. Performance metrics are computed independently on both sets.

**Statistical test:** A two-sample Kolmogorov-Smirnov (KS) test compares the distribution of daily returns between the train and test periods. A p-value above 0.05 indicates the distributions are statistically consistent, supporting the "VALIDATED" verdict. The `pct_in_ci_80` metric reports the fraction of out-of-sample returns that fall within the 80% confidence interval of the in-sample distribution.

---

## Stress Testing

Three historical crisis events and one synthetic scenario are applied to the current allocation:

**LUNA/UST Collapse (May 2022):** UST depegged to near zero; LUNA lost 99.9% of value. SPA's whitelist contains no UST, LUNA, Anchor Protocol, or any Terra-native assets. Modelled portfolio impact: **~0%**.

**FTX Bankruptcy (November 2022):** FTX halted withdrawals; contagion spread to Solana ecosystem and several CeFi lenders. SPA holds no FTX-custodied assets and no Solana-native positions. Modelled impact: **~0%**.

**SVB/USDC Depeg (March 2023):** Circle's USDC temporarily traded at $0.87 due to SVB bank exposure. All USDC-denominated lending positions were marked down by 13% for a 72-hour window. Recovery occurred within 4 days. Methodology: apply 13% markdown to all Tier-1 USDC lending positions; compute portfolio NAV impact. Modelled impact: **~4.3% ($4,310)**.

**DeFi Contagion (Synthetic):** A single Tier-2 protocol suffers a 50% TVL collapse and the fund's largest T2 position is written to zero. Represents a plausible smart-contract exploit or governance failure. Modelled impact: **~8.9% ($8,898)** — worst-case scenario within current allocation.

---

## Limitations and Caveats

**No execution risk modelled.** The backtest assumes instant, frictionless execution at the observed APY. In practice, protocol deposits can experience queue delays, rate drift, and front-running.

**No liquidity risk.** Withdrawal queue lengths are not modelled. During stress periods (e.g., Aave V3 borrow-supply imbalance), withdrawal delays of hours to days can occur.

**No smart contract risk.** Protocol exploits, governance attacks, and oracle manipulation are not reflected in daily APY data. The DeFi Contagion stress test provides a partial proxy.

**APY is historical, not guaranteed.** DeFiLlama data reflects past lending rates. Future APYs depend on market demand for borrowing, which is highly variable. The 3.5–5% T1 blended yield observed in 2025–2026 may not persist.

**Survivorship bias.** Only protocols that survived the 2022–2025 period are in the backtest. Protocols that failed (e.g., Euler V1 exploit March 2023) are excluded from the whitelist.

**T-bill benchmark simplification.** The 4.0% p.a. flat benchmark smooths over a 400-basis-point range of actual short-term rates during the period. During 2022 (rates near zero), the benchmark understates the DeFi edge; during 2023 peak rates, it understates the T-bill alternative.

---

*Data source: DeFiLlama. Backtest is not a guarantee of future performance.*  
*Advisory / Paper Trading Only — no real capital deployed.*
