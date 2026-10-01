> **Working evidence (EPISODIC), not canon.** Notes of a read-only auditor, 2026-10-01; the canonical findings are
> `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` (ADR-530), where every P0 and headline number was re-measured.

# Audit 3: strategy mechanics and yield economics

Code: `~/Documents/SPA_mirror` @ e6204fd23 (2026-10-01 09:15). Runtime: `~/Documents/SPA_Claude/data/` as of 2026-10-01 ~09:40 local. Read-only.

## Live books (ground truth, 2026-10-01)

| Book | File | Holdings | APY | Costs | Note |
|---|---|---|---|---|---|
| Conservative (Engine A, main) | `current_positions.json` gen 06:00:13Z | compound_v3 40k, maple 20k, fluid_fusdc 20k, morpho_blue_base 10k, aave_v3 5k, cash 5k | 5.39 (bar `apy_today`) | `costs_paid_usd` 50.15 total | last trade T034 2026-09-11 (`trades.json`, `cio_trial_grant: ADR-334`) |
| Balanced (Engine B) | `hy_paper_trading.json` last_cycle 06:55Z | maple, fluid_fusdc, susde, morpho_steakhouse, ~24.9k each | 5.05 | `costs_paid_usd` 1223.52; **cost_usd 48.03/day vs yield 13.77/day** | equity 99,555 (below 100k seed) |
| Aggressive (Engine C) | `lp_paper_trading.json` | maple 50.1k, fluid_fusdc 50.1k | 5.22 | `costs_paid_usd` 632.76; **cost_usd 24.01/day vs yield 14.34/day** | equity 100,261, net_pnl −9.67/day |

No book holds an LP, Pendle, leveraged, looped, perp or CLMM position. Every live position is single-asset stablecoin lending/savings. Pendle/Ethena/Aerodrome legs were in B/C from 08-24 to 09-10 at fallback literals (`apy_pct` 10.625/13.0) and were closed 09-10 when ADR-292 made observed provenance a requirement.

## (A) Capability table

| Capability | Status | Expected | Current impl. (path:line) | Runtime evidence | Risk if incomplete | Recommendation |
|---|---|---|---|---|---|---|
| Net APY after costs | **PARTIAL** (main IMPLEMENTED; sleeves broken) | net = accrual − real move cost | Main: `cycle_runner.py:2503-2522`, cost from `rebalance_economics._move_cost_usd` with `min_leg_frac` dust band. Sleeves: `sleeve_book.book_move_cost` `sleeve_book.py:390-456`, no dust band | Main bar 10-01 `cost_usd 0.0`, net 14.98. LP 10-01 `turnover_usd 10.8, cost_usd 24.0086` = 2 legs × $12 ETH gas + 10.8×8bp. HY `cost_usd 48.0279` = 4 × $12 | **Defect:** `rebalance_book` resizes notional to `equity*weight` every day (`sleeve_book.py:318-322`), so accrued yield counts as a "move" on every leg and is charged full Ethereum gas daily. That is ≈$8.8k/yr on C and ≈$17.5k/yr on B, more than they earn, so both sleeve tracks bleed by construction | Apply the main path's `min_leg_frac` band, or exclude same-protocol accrual drift from turnover, in `book_move_cost` |
| Source-of-yield split (base/incentive/fees) | **MISSING** in decision path | apyBase vs apyReward per pool | `defillama_feed.get_apy` returns total `apy` (`defillama_feed.py:161-178`). Only `aave_v3.get_supply_rate` reads apyBase (`aave_v3.py:178-196`) and it is not used by the allocator. `apy_ranking.json` rows have no base/reward fields | `apy_decomposition_log.json`: 100 rows, **all `protocol_name:"unknown"`, `total_advertised_apy_pct:0.0`**, last ts 2026-08-03T14:48Z (dead for 2 months). Read by `investment_os/agents/yield_quality.py:36,82`, which labels it "L2 live yield decomposition" | Emission-inflated APY is scored as organic. The feed's own docstring shows the Aave "Umbrella" pool with 1.66pp of its 5.25 from apyReward (`defillama_feed.py:211-216`) | Carry apyBase/apyReward through the ranking. Mark decomposition log as stale or unchecked |
| Exit plan / exit liquidity | **PARTIAL** (advisory only) | exit-latency/queue gate on book | Adapter consts: maple `EXIT_LATENCY_HOURS=336` (`adapters/maple.py:36`), susde 168 (`susde_adapter.py:86`). `exit_liquidity.py` (advisory ladder). `RiskPolicy.check_axis_compliance` takes `exit_latency_map` (`risk/policy.py:950-953`), but `check_axes` defaults to False (`policy.py:661`) and no production caller sets it True | `exit_liquidity_log.json` (writer `io_liquidity`) last entry analyses **spark_susds $25k**, a position no book holds | B and C hold 25–50% in a 14-day-queue asset (maple) and B holds 25% in a 7-day cooldown (susde). No gate looks at this | Wire `exit_latency_map` + `check_axes=True` (needs ADR). Point the liquidity agent at the actual books |
| Rebalance: ALLOC-001 violation trigger | **IMPLEMENTED** (main) | rebalance on policy violation | `cycle_runner.py:1253-1318` | `validation_summary` `policy_compliant:true`, so no trigger today | — | — |
| Rebalance: ADR-060 yield-improvement trigger | **IMPLEMENTED** (main, CIO-armed); **MISSING** in sleeves | move when gain > cost + band | Shadow calc `write_shadow_rationale` `cycle_runner.py:2121-2172`. Decision via `cio_arming.trade_allowed` `cycle_runner.py:2246-2276`. `ARMED_BOOKS` = conservative/balanced/aggressive (`cio_arming.py:69-82`) | `allocation_rationale.json` 06:00:13Z: `decision HOLD`, `gain_pp 0.081 < 0.5`, `payback_days 226.3`, turnover 20% > 15% | Sleeves: `rebalance_book` keeps any still-eligible holding and never re-ranks (`sleeve_book.py:301-316`). C's docstring says it holds the "top-2 by APY", but it holds maple 5.14 + fluid 5.78 while compound_v3 6.11 is ranked first (`apy_ranking.json` 06:00:34Z). The sleeves have effectively infinite hysteresis | Add a yield-improvement leg to `rebalance_book`, or fix the docstring claim |
| Anti-churn (hysteresis/min-hold/payback) | **IMPLEMENTED** (main) | — | `rebalance_economics.py:83-84,343-409` (payback 30d, min_hold 3d, reversal ×1.5). Churn damper `governance/churn_damper` `cycle_runner.py:2225`. Both layered with CIO | params in rationale: `min_gain_pp 0.5, max_payback_days 30, max_turnover_per_week 0.25`. Main costs 50.15 over 132 bars | — | — |
| Gas/execution cost model (`backtesting/tier1/cost_model.py`) | **IMPLEMENTED** (used live) | used by live cycle | Imported by `allocator/rebalance_economics.py:37` (main) and `sleeve_book.py:361` (sleeves). Flat constants: ETH $12/leg, L2 $0.05–0.25, `cost_model.py:20-26` | Exact reconciliation above (24.0086 = 2×12 + 10.8×0.0008) | Static gas, no gas-price feed. Applied to phantom moves (see Net APY) | Feed live gas. Fix sleeve turnover |
| Slippage model | **PARTIAL** | size/depth-aware | Flat `SLIPPAGE_BPS_STABLE=8.0` (`cost_model.py:25`). Depth tools exist only in research: `rates_desk/depth_at_size.py` (artifact `rates_desk/depth_at_size.json` 2026-06-29, stale) | — | Fine at $100k on blue chips. Wrong at size or for PT/LP | Keep flat for paper. Depth model needed before scale |
| Reward-token price risk | **MISSING** | haircut emission APY by token vol | References only in `risk/scoring_engine.py`, `risk/protocol_risk_map.py` (Risk Scoring v2, advisory by inv. #1) | none in books | Emission APY is treated as cash yield | See source-of-yield row |
| Incentive decay | **MISSING** (live); PARTIAL (lab) | — | `aggressive_lab/roster.py:610-615` PointsFarm models decay (advisory). No `incentive_decay` in money path | decomposition log `incentive_decay_risk_pct 0.0` ×100 (dead) | — | — |
| APY sustainability | **PARTIAL** | persistence/stability screen | Allocator uses point-in-time APY only: no history, rolling, or median in `allocator/allocator.py`. Provenance gate (live-only) `sleeve_book.py:58-80` | `apy_series_daily.json`: aave_v3 4.99 → **12.67** (08-06 → 10-01), moonwell 4.50 → 11.97. Neither gated as spikes | Spikes enter rankings at face value. Main is protected only by the payback band | Add persistence filter (e.g. 7d median) |
| Historical APY reliability | **PARTIAL** | ≥30–90d per pool | Own daily series written by cycle (`cycle_runner.py:3179`) | `apy_series_daily.json`: **56 days** (2026-08-06 → 10-01) for 23 pools; wusdm/stusd 18 days of 0.0. `apy_history.json` empty (`protocol_history:{}`, last_updated null). DeFiLlama `/chart` history not ingested for live pools. Deep Pendle history exists for research (`rates_desk/pendle_pt_history.json` 2026-07-06) | Short window, cannot judge regime or sustainability | Backfill DeFiLlama chart per pinned pool_id |
| LP / impermanent loss | **MISSING** (live) | IL model + price feed | `lp_cycle.py:262` says verbatim: "IL по-прежнему не моделируется (нужен прайс-фид) — il_drawdown 0". `il_drawdown_pct` is just the equity drawdown (`lp_cycle.py:106`). Lab: `EthStableLP` `roster.py:634` | aggressive_lab `lp_eth_stable` **killed 2026-07-15** "eth_price missing/invalid". Engine C holds zero LPs | "LP sleeve" name with no LP mechanics | Rename, or build IL on `peg_history`/price feed |
| CLMM / concentrated liquidity | **MISSING** (docs + dead analytics) | — | `docs/research/clmm_model.py`, `RS-volatile-clmm.md` are not imported anywhere. `analytics/concentrated_liquidity_analyzer.py` is in the Tier-B write-off list "result not coercible to score (NoneType)" (`_tier_b_writeoff.py:528`) | none | — | — |
| Range management | **MISSING** | — | none beyond above | none | — | — |
| Looping / recursive lending | **PARTIAL** (advisory lab) | — | `docs/LOOPING_STRATEGY.md` self-declares "L2 — визия… Кода нет". Executable: `aggressive_lab/roster.py:552` LeverageLoop (wstETH × lev − borrow, liq @0.825 LTV), `:690` LeveredRestaking 3× | `aggressive_lab/leverage_loop/realized_series.jsonl` 10-01: equity 100,183.18, `is_advisory:true`, `outside_riskpolicy:true`, `mtm_source:"realized_backtest_series"`. Also `leverage_looping_log.json` analytics (stale 09-03) | — | — |
| Liquidation / health factor | **PARTIAL** (lab proxy) | per-position HF | Proxy only: `levered_move <= -0.5/lev ⇒ _liquidated` (`roster.py:439-441,594-596,725-727`). No HF computation from oracle/LTV. `liquidator/` = market monitor + estimator | `paper_state.json` leverage_loop `liquidated:false`. `liquidation_cascade_log.json` stale 09-03 | Not relevant to live (no leverage) | — |
| Leveraged yield | **PARTIAL** (advisory) | — | `swarm/leverage_brain.py` (reco = base_cap × regime × guardian × depth). aggressive_lab PT-levered, YT | `swarm/leverage_brain.json` 06:56Z: books `REFUSED_NO_TELEMETRY` / `leverage_reco:null`. Agent `com.spa.swarm_brain` loaded | — | — |
| Pendle PT/YT | **PARTIAL** (advisory paper) | — | `rates_desk` fixed-carry (PT to maturity), `paper_rates.py`. strategy_lab_paper `pt_susde`/`pt_usde`. aggressive_lab `pendle_yt_susde`/`pendle_pt_levered`. Adapter `pendle_pt_susde_adapter.py` (exit 24h) | `rates_desk/paper/status.json` 07:09Z: equity 100,207.76, 4 open/46 closed, "0 entered… honest no-edge". aggressive_lab pendle_yt_susde equity 120,667 (cum +20.7% in 89d, advisory). **Not in any live book** (main held `pendle` at fallback 8.0% 09-08→09-11, closed) | — | — |
| Basis / carry | **PARTIAL** (advisory) | — | `strategies/s_basis.py` (only via `cycle_tournament.py:340`). `carry_truth_table.py` | `basis_trade_opportunities.json` stale 2026-08-29, `spot_yield_pct 5.0` literal, `perp_funding 10.95` identical for ETH/SOL. `carry_truth_table.json` 2026-06-29, 11/11 INSUFFICIENT_DATA | — | Retire or refresh stale artifacts |
| Delta-neutral | **PARTIAL** (advisory). Live label is cosmetic | — | aggressive_lab `SusdeDeltaNeutral` `roster.py:296`, strategy_lab `variant_n`. Live sleeves stamp `is_delta_neutral: True` on every leg (`sleeve_book.py:312`). `check_positions_delta_neutral` passes when the field is True (`lp_cycle.py:119-131`) | `variant_n` equity 102,660 (advisory). HY/LP `delta_neutral_ok:true` on a Maple credit book | Tautological check | Drop the label, or compute it |
| Funding-rate dependency (hy_cycle perp feed) | **PARTIAL** — still proxy in hy_cycle | hy uses real funding | `hy_cycle.py:129-142`: `funding_rate = hy_target_apy_pct()/100` "proxy… true perp funding feed not yet wired (v1)", non-gating (`hy_cycle.py:8-17`). A real 5-venue feed exists: `strategy_lab/data/funding_feed.py`, consumed by `swarm/funding_regime.py:124` | `swarm/funding_regime.json` 06:57Z: ETH `history_days 68`, carry 4.93% → `regime YELLOW`. `perp_funding_rates.json` (`feeds/perp_funding_feed.py`) **stale 2026-08-29**. Balanced holds 25% susde (funding-driven) with no funding input | Balanced carries funding-flip risk with no sensor feeding the book | Route `funding_regime` into hy_cycle (advisory first) |
| Active strategy supervision | **IMPLEMENTED** (main + sleeves) | — | Two-tier kill-switch (governance). Tier-A BLOCK zeroes target (`cycle_gates.py` Step 2c-pre). CIO arming on all 3 books (`cio_arming.py:69`). `intraday_actor.py` (ADR-114, DERISK B/C between cycles, agent `com.spa.intraday_equity` loaded). Sleeve kills: C −25% (`lp_cycle.py:235`), B −8% | Agents loaded, exit 0: daily_cycle, hy_cycle, lp_cycle (hourly), aggressive_lab. `allocation_rationale.json` written 06:00Z today | Sleeves are not under RiskPolicy v1.0 ("paper-рукав", `hy_cycle.py:17`). C runs maple at 50% vs the RiskPolicy T2 cap of 20%. Risk axes (credit ≤15%, peg ≤10%) never evaluated (`risk_axes.py:104,126`) | Run sleeve books through `check_portfolio_health(check_axes=True)` advisory |

## (B) Strategy depth: mechanic → support → where it runs → evidence

| Mechanic | Support | Where it runs | Evidence |
|---|---|---|---|
| Single-asset stable lending/savings | Executable | **LIVE: A, B, C** | all positions above |
| Concentration (2×60% cap) | Executable | **LIVE: C** | `sleeve_book.py:54-56`, `lp_cycle.py:276-279` |
| Cost-aware rebalance, payback, hysteresis | Executable | **LIVE: A** (CIO-armed); sleeves via CIO gate only | `rebalance_economics.py`, `allocation_rationale.json` HOLD |
| sUSDe carry (funding-backed, unhedged) | Executable | **LIVE: B** (25%) | `hy_paper_trading.json` susde 5.2453 |
| Delta-neutral sUSDe + short perp | Executable | advisory paper (aggressive_lab) | `susde_dn` equity 103,042.8 |
| Pendle PT fixed carry to maturity | Executable | advisory paper (rates_desk, strategy_lab_paper) | `rates_desk/paper/status.json` |
| Pendle YT (leveraged yield) | Executable | advisory paper (aggressive_lab) | pendle_yt_susde 120,667 |
| PT levered loop | Executable | advisory paper (aggressive_lab) | pendle_pt_levered 100,731.7, cum_cost 2,447 |
| wstETH leverage loop / levered restaking | Executable (liq proxy) | advisory paper (aggressive_lab) | leverage_loop 100,183; levered_restaking 99,895 |
| LRT neutral / directional | Executable | advisory paper (aggressive_lab, strategy_lab_paper variant_n/d) | lrt_neutral 97,195; variant_d 169,953 |
| ETH directional | Executable | advisory paper | eth_directional 100,596 |
| Points/emission farming (with decay) | Executable | advisory paper | points_farm 101,540 |
| ETH/stable LP with IL | Executable but dead | advisory paper, **killed 2026-07-15** | `status.json` kill_reason |
| Dynamic leverage recommendation | Executable | advisory (swarm L3) | `leverage_brain.json` all REFUSED/null |
| Funding-regime classifier | Executable | advisory (swarm L1), real 5-venue feed | `funding_regime.json` YELLOW |
| Basis trade scan | Executable | stale analytics | `basis_trade_opportunities.json` 08-29 |
| CLMM / range management | None executable | docs/research only; analytics module written off | `_tier_b_writeoff.py:528` |
| Recursive lending (Looping track) | Doc only | docs (L2 "визия") | `docs/LOOPING_STRATEGY.md:3` |
| IL accounting in Engine C | None | — | `lp_cycle.py:262` |
| Health-factor monitoring of positions | None (proxy in lab) | — | `roster.py:439` |

## (C) What makes "aggressive" aggressive

**Neither riskier protocols nor more complex mechanics. It is concentration plus a wider stop, on the same universe.**

- Code admits it: `lp_cycle.py:14-18`: "«агрессия» здесь = КОНЦЕНТРАЦИЯ + широкий бюджет просадки, а НЕ directional-риск".
- Universe is identical to Balanced. Both use `sleeve_book.book_candidates` (`sleeve_book.py:254`) with the same live-provenance + $5M TVL gate. Differences: `AGG_MAX_POSITIONS=2`, `AGG_PER_PROTOCOL_CAP_PCT=60` vs 4/40, and kill −25% vs −8%.
- Measured outcome on 10-01: Aggressive APY **5.22**, Balanced **5.05**, Conservative **5.39**. Aggressive's two holdings (maple, fluid_fusdc) are also in the Conservative book. Its concentration risk is real (50% Maple, a 14-day exit queue and credit risk, above the RiskPolicy T2 cap of 20%), but its yield premium is ≈0 and is negative after the phantom-gas defect.
- Every genuinely complex mechanic (YT, PT-levered, loops, restaking, DN basis, points, LP) runs only in `aggressive_lab` / `strategy_lab_paper` / `rates_desk`. All are `is_advisory:true`, `outside_riskpolicy:true`, and none feed `lp_paper_trading.json`. ADR-292 (09-09) removed the fallback-literal Pendle/Ethena/Aerodrome legs, which had been the only "aggressive" content.

## (D) Strengths (evidence-backed)

1. Provenance discipline. Sleeves only fund `apy_source=="live" && tvl_source=="live" && tvl≥$5M` (`sleeve_book.py:58-80`). Main zero-accrues fallback pools (ADR-298, `cycle_runner.py:2465-2500`). Main feed 16/16 live (`current_positions.feed_coverage`).
2. Main-book economics are rigorous. Payback/min-hold/turnover/reversal gates plus churn damper plus CIO run in layers. Live HOLD today, with numbers (`gain 0.081pp`, `payback 226d`). Total costs $50.15 over 132 bars.
3. One cost model, used live, so cost numbers reconcile exactly to `cost_model.py` constants.
4. Sleeves now charge costs and keep MTM coverage as a third outcome (`mtm_coverage_pct`, `mtm_unmarked`). "Not measured" is visible in the track.
5. The advisory lab is substantive and honestly labelled. Ten real-feed strategies with hash-chained forward series (`realized_series.jsonl` prev_hash/hash), a real 5-venue funding regime with 68 days of history, and Pendle PT history.
6. Supervision is automatic: kill ladder, Tier-A block, intraday DERISK actor, and a CIO armed on all three books.

## (E) UNKNOWNs

- Why main uses aave_v3 **5.4008** while `apy_ranking.json` shows aave_v3 **12.6687** with TVL $4.09M (below the floor). This could be a different pool behind the same key (cf. ADR-233 pool-identity issue at `defillama_feed.py:203-230`). Not resolved.
- `moonwell_base` 11.97%: `tvl_source:"static"`, so it is correctly excluded. Whether a live TVL path exists is unknown.
- Whether the sleeve phantom-gas defect is already tracked in a card. Not checked.
- `aggressive_lab` `net_apy_pct` looks like cumulative return, not annualised (pendle_yt 20.67% over 89 days). Field semantics not verified.
- strategy_lab_paper engine_b/engine_c equities (20,447 / 10,236, `is_advisory:false`, APY 8.16/8.60) do not match the hy/lp books. Their relation to the live sleeves was not traced.
- `com.spa.swarm_health` last exit code 1 (`launchctl list`). Cause not investigated.
