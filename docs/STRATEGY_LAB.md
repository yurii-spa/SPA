# Strategy Lab — backtest + paper-trading of pluggable yield strategies

A lab where several yield strategies run through **one shared backtest harness** and **one live
paper-trading service** (no real capital), for an honest risk-adjusted comparison vs the RWA
risk-free floor. Lives in `spa_core/strategy_lab/`. Parallel model — wraps the existing engines,
does not disturb them. stdlib-only, deterministic, LLM-forbidden in risk/kill logic.

## One-command usage

```bash
# Backtest — runs ALL strategies over the same window/capital, prints the comparative table:
python3 scripts/strategy_lab_backtest.py --refresh            # --refresh re-fetches live data
python3 scripts/strategy_lab_backtest.py --md report.md       # also write a markdown report

# Paper-trading (live, no capital) — one tick (launchd invokes this hourly):
python3 scripts/strategy_lab_paper.py                         # single tick (restart-survival)
python3 scripts/strategy_lab_paper.py --loop --interval 3600  # daemon mode
python3 scripts/strategy_lab_paper.py --status                # status table
python3 scripts/strategy_lab_paper.py --weekly               # weekly comparative report
```

Runs as `com.spa.strategy_lab_paper` (launchd, hourly) — survives restart, accumulates a
time-series for weeks/months.

## Strategies

| id | mandate | what it is | kill conditions |
|---|---|---|---|
| `variant_n` | neutral (β≈0) | LRT (eETH) spot + short ETH-perp hedge. Income = restaking yield + points ± funding. ETH price hedged out; residual = LRT/ETH depeg. | funding < X for N hours; LRT depeg > Y% |
| `variant_d` | directional (β≈1) | Pure LRT, no hedge. Income = restaking + points + ETH price move. ISOLATED sleeve, outside the stablecoin mandate. | drawdown > Z% from peak |
| `eth_lst_neutral` | neutral (β≈0) | **NEW — the SAFE ETH-yield sleeve.** PLAIN-staking LSTs (stETH/rETH, **NOT LRTs**) spot + short ETH-perp, β≈0. Income = staking yield ± funding. LSTs hug their ETH peg far tighter than LRTs → much smaller depeg residual than variant_n. The recommended ETH approach. | tighter LST depeg > Y%; funding < X for N hours |
| `rwa_sleeve` | stable (T1) | **NEW — the realized RWA cash floor (allocatable, not a benchmark).** Holds tokenized US-Treasury funds (BUIDL/USYC/USDY/OUSG…) and accrues at the LIVE tokenized-T-bill yield (rwa_feed, TVL-weighted ~3.4%). Zero price vol, ~no drawdown — the lowest-risk T1 home for idle cash. Banks the floor, doesn't try to beat it. | — (zero-vol) |
| `engine_a/b/c` | stable | Baselines wrapping the real Engine A ($100k base) / B (HY) / C (LP) sleeves. | risk-policy drawdown stop |
| `rwa_floor` | benchmark | Risk-free floor — **live tokenized-T-bill yield (~3.4%, rwa_feed), no longer hardcoded**, zero vol. The bar every strategy must beat risk-adjusted. Reference row, not held. | — |

All thresholds (X/Y/Z/N) live in the SSOT config — never hardcoded.

## Adding a strategy (DoD #4)

One new class implementing the `Strategy` ABC (`base.py`: `init/positions/step/metrics/kill_check`)
+ one config block in `strategy_lab_config.json`. The harness never changes.

## Architecture

```
spa_core/strategy_lab/
  base.py            — Strategy ABC + MarketSnapshot + Position + StrategyMetrics + KillResult + InvalidDataError
  config.py          — SSOT loader (strategy_lab_config.json); risk LIMITS imported from spa_core.risk.policy (not duplicated)
  metrics.py         — net APY, maxDD, Sharpe/Sortino, β-to-ETH, funding drag, corr-to-stable, tail(ETH-20+flip), beats-RWA-floor
  data/              — funding_feed (median across Binance/Bybit/OKX/KuCoin/Hyperliquid) · price (ETH/LST/LRT via DeFiLlama coins)
                       · restaking/staking (DeFiLlama yields) · rwa_feed (LIVE tokenized-T-bill floor, TVL-weighted ~3.4%)
                       schema-validated, fail-CLOSED (raise on bad/empty; no silent defaults), ff-with-limit + gap flags
  strategies/        — variant_n.py · variant_d.py · eth_lst_neutral.py · rwa_sleeve.py · baselines.py (A/B/C/RWA wrappers)
  backtest.py        — shared harness: same capital + window + data, deterministic, costs, window-stress validation
  report.py          — comparative markdown table vs RWA floor
  paper.py           — live service: restart-survival, idempotent per day, fail-closed, kills→Telegram
```

## Data layer (decisions)

- **Sourcing:** live public keyless APIs. Funding = **median across 5 venues — Binance, Bybit,
  OKX, KuCoin, Hyperliquid** ETH-perp (Hyperliquid pays hourly → normalized to the 8h cadence of
  the CEX venues before blending). Prices (ETH + eETH/ezETH/weETH + stETH/rETH) = DeFiLlama coins.
  Restaking/staking APY = DeFiLlama yields.
- **RWA floor = LIVE:** `data/rwa_feed.py` pulls the tokenized US-Treasury market (BUIDL/USYC/USDY/
  OUSG/USTB/TBILL…, ~$15B) from DeFiLlama yields and returns the **TVL-weighted mean APY (~3.4%)** —
  no longer a hardcoded literal. Fail-closed (raises `InvalidDataError` if no pool clears the $5M
  TVL floor); callers (`config.rwa_floor_apy_pct`) decide whether to fall back to a committed literal.
  Both `rwa_floor` (benchmark) and `rwa_sleeve` (allocatable) read this same live rate.
- **Fail-closed:** a malformed/empty API response raises `InvalidDataError`; strategies go to a
  safe state — never a silent default.
- **One source of truth:** backtest (historical) and paper (live) consume the SAME `MarketData`
  / cached series, so they can't disagree.

## Historical depth (free pagination)

The feeds paginate the free keyless endpoints to reach **~2 years** of real history at $0:
- **Binance/Bybit funding** — paged via `startTime`/`endTime` (Binance 1000/page ascending, Bybit
  200/page descending), de-duped, daily MEDIAN across venues. Reaches back to perp inception.
- **ETH + LRT prices** — DeFiLlama `coins.llama.fi/chart` paged in ≤365-day daily chunks.
- **Restaking APY** — DeFiLlama `yields.llama.fi/chart/{pool}` per-date APY series.

Real achievable depth: prices/eETH-restaking from **2024-06-05**; ezETH restaking from 2024-12-13
(earlier dates honestly gapped, not fabricated). Default window: **2024-06-05 → 2026-06-24**.

## Latest real comparative (deep window 2024-06-05 → 2026-06-24, 750 days)

Window validation ✅ — contains **4 ETH drawdowns >10% + 74 funding flips to negative** (real stress).

| Strategy | Net APY % | MaxDD % | Sharpe | β(ETH) | Beats floor |
|---|---|---|---|---|---|
| variant_n | −0.84 | 10.79 | −0.04 | −0.02 | ❌ (killed 2024-08-09, LRT depeg 2.89%) |
| variant_d | −15.42 | 30.05 | −1.03 | 0.05* | ❌ (killed 2024-08-05, drawdown 30%) |
| engine_a / b / c | 4.60 / 8.33 / 8.87 | 0 | — | ~0 | ✅ |
| rwa_floor | 4.60 | 0 | — | 0 | benchmark |

*Variant D's full-window β reads ~0 because its drawdown kill latched in the Aug-2024 ETH crash and
it held flat thereafter. **Honest finding:** over a deep window with real ETH crashes, both restaking
candidates hit their kill switches and do NOT beat the stable engines / RWA floor — exactly what the
lab exists to surface. (On a calm short window, Variant N's neutral carry did beat the floor; it is
the tail/crash behaviour that disqualifies it here.)

## Forward-record analytics (live, risk-adjusted) — `forward_analytics.py`

`spa_core/strategy_lab/forward_analytics.py` computes a deterministic risk-adjusted scorecard **on
the LIVE accruing forward series themselves** — the per-day equity tracks the paper services grow
(`data/strategy_lab_paper/*_series.json` + the rates-desk `data/rates_desk/paper/*_series.json`).
The backtest table above is historical; this is the realized forward record. stdlib-only,
deterministic, fail-CLOSED, LLM-forbidden, advisory (reads the series + the live floor — never moves
capital, never touches `execution/`, never blocks a tick). Reuses `metrics.py` (no reinvented math)
and gates every series through `track_integrity` first.

**What it computes per track (T4 — risk-adjusted attribution):**
- ingest one `*_series.json`, VALIDATE via `track_integrity` (gap / dup / out-of-order / future /
  malformed → fail-CLOSED → verdict `UNKNOWN`, never a fabricated number);
- realized `ann_return_pct`, `max_dd_pct`, `rolling_vol_pct` (well-defined from ≥2 points);
- realized Sharpe / Sortino — **HONEST insufficient-history → UNKNOWN rule:** fewer than
  `MIN_POINTS_FOR_RATIO` (= 7 equity points → ≥ 6 daily returns) → the ratio is a degenerate
  artifact, so it is reported `"UNKNOWN"`, not a number. A locked-volatility book (fixed-rate
  accrual whose only variance is float noise → `metrics.sharpe()` returns `None`) is FLAGGED
  `locked_vol` and reported `UNKNOWN` — never a fabricated ~4.5e8 Sharpe (the documented
  degenerate-Sharpe hazard);
- **attribution vs the ~3.4% RWA floor:** `excess_vs_floor_pct = realized ann return − floor`,
  decomposed into the floor leg (return attributable to sitting in RWA cash) and the
  excess-carry leg (return attributable to the strategy's edge). Positive → beating the risk-free
  benchmark;
- per-track verdict: `UNKNOWN` (broken series), `THIN_TRACK` (honest return + attribution but not
  yet a trustworthy ratio — the current state at ~3–6 track-days), `BEATS_FLOOR`, or `BELOW_FLOOR`.
  Never a fabricated PASS on insufficient evidence.

**Stress overlay (T5 — drawdown on the realized record):** applies the canonical 2024–2026 PT
mark-down shocks (the SAME magnitudes the promotion gate replays via `levered_stress`, NO looser) to
the **currently-held** rates-desk carry book (read from `rates_desk_fixed_carry_state.json`) on top
of the realized forward equity. Per scenario: `stress_dd_pct` + `survives` (DD within the promotion
drawdown band, `MAX_DD_BAND_PCT = 15%`); a cash book with no held PT notional honestly reports 0%
stress DD rather than fabricating a loss.

**Output:** `data/forward_analytics.json` (atomic) — `{rwa_floor_apy_pct, min_points_for_ratio,
max_dd_band_pct, n_tracks, n_unknown, n_thin_track, n_beats_floor, tracks:[…per-track scorecard…],
carry_book_stress_overlay:{…}}`. Run: `python3 -m spa_core.strategy_lab.forward_analytics`.

**Feeds the fundability one-pager:** `scripts/generate_fundability_onepager.py` reads
`data/forward_analytics.json` for its *Live forward-record analytics* section (`docs/FUNDABILITY.md`),
surfacing each track's risk-adjusted scorecard + the stress overlay. It passes the `UNKNOWN` /
`THIN_TRACK` sentinels through **verbatim** — a thin track renders as `THIN (N/30 days, metrics
pending)`, never a coerced number. The honest thin-labeling is the credibility: trustworthy
risk-adjusted ratios only arrive near day 30 (target **2026-07-21**), and until then the forward
tracks (~3–6 days today) are honestly UNKNOWN by design.

### Promotion ladder (canonical criteria)

A sleeve only climbs `backtest → paper_Nd → live` if it clears the canonical promotion criteria —
the constants live in `spa_core/tournament/tournament_engine.py` (`PROMOTION_CRITERIA`), imported,
not re-hardcoded:

| criterion | constant | bar |
|---|---|---|
| Sharpe | `min_sharpe` | ≥ 1.5 |
| paper days | `min_days_paper` | ≥ 7 |
| APY | `min_apy_pct` | ≥ 3% |
| max drawdown | `max_drawdown` | ≥ −15% (band) |

The full rung-by-rung flow (GOOD promotes only on the 7th cleared day; a TOXIC / refused sleeve never
ages into a promotion; BLOCKED-NO-HEDGE is terminal off-ladder) is asserted end-to-end in
`spa_core/tests/test_promotion_ladder_e2e.py`, importing the REAL constants so a criteria change
breaks the test, not the ladder silently.
