# SPA — Institutional Audit Report

_Generated: 2026-06-20T23:51:06.365651+00:00_  ·  _Version: v1.0_

## 1. Identity

> Personal research project. No external capital managed. Paper trading only.

- External capital managed: **$0**
- Trading mode: **paper**

## 2. Governance

- ADR count: **37**
- Last decision: **2026-06-20** (ADR_INDEX.md)
- Rule changes this month: **37**
- Risk policy version: **v1.0**

## 3. Risk Controls

**7/7 controls PASS**

| Control | Status | Detail |
|---|---|---|
| Portfolio drawdown kill switch (≥5% closes all) | **PASS** | observed max drawdown 0.20% vs 5% threshold |
| T1 per-protocol cap (≤40%) | **PASS** | max T1 position spark_susds at 7.53% |
| T2 per-protocol cap (≤20%) | **PASS** | max T2 position morpho_steakhouse at 8.90% |
| T2 aggregate cap (≤50%) | **PASS** | T2 aggregate 47.14% of portfolio |
| Minimum cash buffer (≥5%) | **PASS** | cash buffer 5.00% of capital |
| Per-pool TVL floor (≥$5,000,000) | **PASS** | enforced by RiskPolicy gate on every rebalance |
| New-position APY bounds (1%–30%) | **PASS** | enforced by RiskPolicy gate on every candidate entry |

## 4. Paper Track

- Track start: **2026-06-10**  ·  Days elapsed: **10**
- NAV: **$100,000.00** → **$100,121.33**
- Total return: **0.1213%**  ·  Annualized: **1.43%**
- Max drawdown: **-0.2047%**  ·  Daily vol: **0.0020%**
- Consistency (positive days): **100.0%** (29+ / 0-)

## 5. Positions

- Capital: **$100,000.00**  ·  Deployed: **$94,999.88**  ·  Cash: **$5,000.12**
- Open positions: **24**

| Protocol | Size (USD) | Weight | Tier | APY |
|---|---:|---:|:---:|---:|
| morpho_steakhouse | 8,897.68 | 8.90% | T2 | — |
| spark_susds | 7,528.81 | 7.53% | T1 | — |
| compound_v3 | 7,118.15 | 7.12% | T1 | — |
| aave_v3_polygon | 6,981.26 | 6.98% | T1 | — |
| aave_v3_optimism | 6,570.60 | 6.57% | T1 | — |
| aave_arbitrum | 5,612.39 | 5.61% | T1 | — |
| susde | 5,555.55 | 5.56% | T3 | — |
| aave_v3 | 4,791.06 | 4.79% | T1 | — |
| pendle | 3,703.70 | 3.70% | T2 | — |
| extra_finance_base | 3,703.70 | 3.70% | T3 | — |
| frax | 3,472.22 | 3.47% | T2 | — |
| scrvusd | 3,240.74 | 3.24% | T2 | — |
| fluid_fusdc | 3,009.25 | 3.01% | T2 | — |
| morpho_blue_base | 2,870.36 | 2.87% | T2 | — |
| sfrax | 2,777.78 | 2.78% | T2 | — |
| stusd | 2,777.78 | 2.78% | T2 | — |
| sdai | 2,546.29 | 2.55% | T2 | — |
| moonwell_base | 2,546.29 | 2.55% | T2 | — |
| wusdm | 2,314.81 | 2.31% | T2 | — |
| maple | 2,231.48 | 2.23% | T2 | — |
| aave_v3_base | 2,083.33 | 2.08% | T2 | — |
| morpho_blue | 1,898.14 | 1.90% | T2 | — |
| yearn_v3 | 1,495.36 | 1.50% | T2 | — |
| euler_v2 | 1,273.15 | 1.27% | T2 | — |

## 6. Events Log

_Source: audit_trail_jsonl  ·  30 of 672 records_

| Timestamp | Event | Chain hash |
|---|---|---|
| 2026-06-20T15:42:30.123551+00:00 | risk_verdict | — |
| 2026-06-20T15:42:30.136484+00:00 | trade_executed | — |
| 2026-06-20T15:43:12.290255+00:00 | cycle_start | — |
| 2026-06-20T15:43:17.500670+00:00 | allocation_proposal | — |
| 2026-06-20T15:43:17.580284+00:00 | risk_verdict | — |
| 2026-06-20T15:43:17.592086+00:00 | trade_executed | — |
| 2026-06-20T15:50:47.814169+00:00 | cycle_start | — |
| 2026-06-20T15:50:53.042524+00:00 | allocation_proposal | — |
| 2026-06-20T15:50:53.120932+00:00 | risk_verdict | — |
| 2026-06-20T15:50:53.133012+00:00 | trade_executed | — |
| 2026-06-20T15:51:34.812234+00:00 | cycle_start | — |
| 2026-06-20T15:51:40.039031+00:00 | allocation_proposal | — |
| 2026-06-20T15:51:40.119046+00:00 | risk_verdict | — |
| 2026-06-20T16:53:40.784685+00:00 | cycle_start | — |
| 2026-06-20T16:53:42.992739+00:00 | allocation_proposal | — |
| 2026-06-20T16:53:43.074916+00:00 | risk_verdict | — |
| 2026-06-20T16:59:25.443189+00:00 | cycle_start | — |
| 2026-06-20T16:59:27.638201+00:00 | allocation_proposal | — |
| 2026-06-20T16:59:27.724071+00:00 | risk_verdict | — |
| 2026-06-20T17:03:50.332993+00:00 | cycle_start | — |
| 2026-06-20T17:03:57.469246+00:00 | allocation_proposal | — |
| 2026-06-20T17:03:57.566468+00:00 | risk_verdict | — |
| 2026-06-20T17:22:39.141166+00:00 | cycle_start | — |
| 2026-06-20T17:22:41.732858+00:00 | allocation_proposal | — |
| 2026-06-20T17:22:41.786918+00:00 | risk_verdict | — |
| 2026-06-20T17:22:41.980549+00:00 | trade_executed | — |
| 2026-06-20T21:23:06.108134+00:00 | cycle_start | — |
| 2026-06-20T21:23:09.194187+00:00 | allocation_proposal | — |
| 2026-06-20T21:23:09.263343+00:00 | risk_verdict | — |
| 2026-06-20T21:23:09.465517+00:00 | trade_executed | — |

## 7. Integrity Check

- Hash chain: **INTACT**  ·  Verified: **True**
- Records: **0**  ·  File exists: **False**

## 8. System Health

- GoLive: **27/29**  ·  Ready: **False**
- Last cycle run: **2026-06-20T21:23:06.104513+00:00**
- Errors (last 7d): **189**
- Blockers:
  - gap_monitor_30d: 11/30 honest track days (since 2026-06-10; 19 more needed — target ~2026-07-09)
  - min_track_days_30: 11/30 honest paper-trading days (since 2026-06-10; 19 more needed — target go-live ~2026-07-09)
