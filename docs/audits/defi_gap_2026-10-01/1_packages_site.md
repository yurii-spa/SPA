> **Working evidence (EPISODIC), not canon.** Notes of a read-only auditor, 2026-10-01; the canonical findings are
> `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` (ADR-530), where every P0 and headline number was re-measured.

# Audit 1 — Three DeFi packages, APY math, product/site surface

Audited 2026-10-01 (read-only). Code: `~/Documents/SPA_mirror` @ `e6204fd23` (2026-10-01 09:15 +02). The files that matter (`hy_cycle.py`, `lp_cycle.py`, `sleeve_book.py`, `sleeve_yield.py`, `generate_track_snapshot.py`) are byte-identical in the running tree `~/Documents/SPA_Claude` (checked with `cmp`), so the code cited here is the code that runs. Live state: `~/Documents/SPA_Claude/data/`. Site: `curl -sL https://earn-defi.com/...` fetched 2026-10-01. Static HTML only; client JS was not run and api.earn-defi.com was not fetched.

---

## (A) Package table

Names come from `landing/src/lib/tier_bands.json`:
- Conservative / Консервативный, alt "Preserve"
- Balanced / Сбалансированный, alt "Core"
- Aggressive / Агрессивный, alt "Max Yield"

The alias pages redirect `/strategies/preserve|core|max-yield/` to `/strategies/conservative|balanced|aggressive/` (`landing/src/pages/strategies/core.astro` meta-refresh). Name conflict: `scripts/tier_paper_rollup.py:7` calls the *Conservative* track "Core". Its output `data/tier_paper_rollup.json` has no consumer in the repo.

| Field | Conservative | Balanced | Aggressive |
|---|---|---|---|
| Engine / book (verified) | `spa_core/paper_trading/cycle_runner.py` → `data/equity_curve_daily.json`, `data/current_positions.json` (`"source":"cycle_runner"`, `"execution_mode":"read_only_simulation"`) | `spa_core/paper_trading/hy_cycle.py` → `data/hy_paper_trading.json` (`"sleeve":"B"`, `"engine":"HY/Carry"`). Mapping is in `scripts/generate_track_snapshot.py:293` | `spa_core/paper_trading/lp_cycle.py` → `data/lp_paper_trading.json` (`"sleeve":"C"`, `"engine":"LP/Liquidity"`). Mapping is in `generate_track_snapshot.py:294` |
| Audience (site copy only) | "Allocators prioritising stability and capital preservation" (/strategies/conservative/) | "Family offices and individual allocators seeking systematic, transparent DeFi yield" (/strategies/balanced/) | "Experienced allocators accepting higher volatility and drawdown" (/strategies/aggressive/) |
| Risk profile in code | RiskPolicy v1.0 (`policy_version":"v1.0"`, `policy_compliant:true`). Kill switch SOFT −5% / HARD −10% | **Outside RiskPolicy.** Only gates: kill at −8% (`hy_cycle.py:48`) and CIO `allow_new` / `cio_arming.gate_sleeve_book` (`hy_cycle.py:275-297`). Neither is a RiskPolicy call | **Outside RiskPolicy.** Kill at −25% (`lp_cycle.py:51` `IL_KILL_THRESHOLD = -0.25`). Concentration: top-2 names, 60% cap each (`sleeve_book.py:55-56`, `lp_cycle.py:278-279`) |
| Live positions | `current_positions.json` @ 2026-10-01T06:00:13Z: compound_v3 $40,000 @ 6.113% · maple $20,000 @ 5.1418% · fluid_fusdc $20,000 @ 5.78% · morpho_blue_base $10,000 @ 5.6917% · aave_v3 $5,000 @ 5.4008% · cash $5,000. `validation_summary`: **t1_pct 45.0, t2_pct 50.0**, cash 5.0 | `hy_paper_trading.json` @ `last_cycle_at` 2026-10-01T06:55:42Z: maple, fluid_fusdc, susde, morpho_steakhouse at **$24,897.33 each**; APY 5.1418 / 5.3 / 5.2453 / 4.5027; all opened 2026-09-10 | `lp_paper_trading.json` @ 2026-10-01T06:55:42Z: maple $50,135.21 @ 5.1418%, fluid_fusdc $50,135.21 @ 5.3%; opened 2026-09-10 |
| Chains / assets | All Ethereum except morpho_blue_base (Base), per `adapter_registry.json` `chain`. Assets are USDC lending markets. Asset per row is not in the ranking (`asset` = None) | All Ethereum. susde is staked USDe (registry `tier: 3`), the rest are T2 (maple, fluid_fusdc, morpho_steakhouse = `tier: 2`) | Ethereum. Both legs `tier: 2` |
| Tier composition (registry) | T1: compound_v3, aave_v3. T2: maple, fluid_fusdc, morpho_blue_base | 3× T2 + 1× T3 (susde). **No T1** | 2× T2. No T1 |
| What the strategy does | Plain supply into lending, chosen by tuner `optimized_yield`, `tuner_expected_apy` 5.7566 | Plain supply / staked-USDe hold. Candidates are all observed names sorted by APY, with no APY floor (`sleeve_book.book_candidates`, `:254-275`). 4 equal-weight legs, 40% cap. Every leg is stamped with the literal `is_delta_neutral: True` (`:312`) | Same plain supply, top-2. ADR-125 says so: "«агрессия» здесь = концентрация + широкий бюджет просадки, а НЕ directional-риск" |
| Leverage / LP / looping in code | None | None. `sleeve_book.py` has no leverage path | None. Despite the engine name "LP/Liquidity", `lp_candidates` is no longer called (`sleeve_book.py:229-239`) |
| APY code path | `daily_yield = position_usd * apy_pct/100/365` (`cycle_runner.py:26`). Cost per ADR-298 (`cycle_runner.py:2500-2535`, `rebalance_economics._move_cost_usd` with dust band `min_leg_frac`). Headline = compound NAV from the anchor (`generate_track_snapshot.py:232-239`) | `accrue_book`: notional × observed APY/365, capped at 30% (`sleeve_book.py:326-347`), minus `book_move_cost` (`hy_cycle.py:314-316`), plus mark-to-market (`:322-323`). Site APY = compound over "honest" bars (`generate_track_snapshot.py:_sleeve_paper_track` :146-185) | Same as Balanced (`lp_cycle.py:273-305`) |
| Gross or net | Net of *modelled* gas and slippage only **since 2026-09-10**: the first bar with a `cost_usd` key is 2026-09-10, and the only cost was 2026-09-11 $50.15. `costs_paid_usd` 50.15. The first 80 evidenced days carry no cost model | Net of modelled cost. `costs_paid_usd` **1,223.52**. Daily cost $48.03 against yield $13.77 (2026-10-01 row) | Net of modelled cost. `costs_paid_usd` **632.76**. Daily cost $24.01 against yield $14.34 |
| Liquidity / exit assumptions in code | RiskPolicy TVL floor $5M (`risk/policy.py:121,477`). Capacity cap `effective_max_pct` (`risk/capacity_limits.py:294`, 1% of pool, 3% for T1 with TVL > $1B). `exit_liquidity.py` is used only by analytics, investment_os and riskwire modules, not by `cycle_runner` or `cycle_gates` (grep). No exit-time model | Only the TVL floor of $5M plus `apy_source == "live"` and `tvl_source == "live"` (`sleeve_book.py:77-79,136-172`). No pool-share cap, no exit-time model | Same as Balanced |
| Rebalance trigger | ADR-060 `TriggerParams`: min_gain 0.50pp, payback ≤30 d, min_hold 3 d, cooldown 3 d (`allocator/rebalance_economics.py:82-85`) | **Every daily row** (once per UTC day, first hourly run about 00:55Z, per `sleeve_inputs_balanced.jsonl` ts 2026-10-01T00:55:41Z). `rebalance_book` re-sizes every leg to equity/n (`sleeve_book.py:317-322`), then the CIO gate runs | Same: daily re-size of both legs |
| Automation | `com.spa.daily_cycle`, StartCalendarInterval 08:00 local. Loaded (`launchctl list`: `- 0 com.spa.daily_cycle`) | `com.spa.hy_cycle`, `StartInterval 3600`, `RunAtLoad false`, wrapper `scripts/agent_hy_cycle.sh` → `hy_cycle --run`. Loaded, last exit 0. `cycles_completed` 2155 | `com.spa.lp_cycle`, `StartInterval 3600`. Loaded, last exit 0. `cycles_completed` 2166 |
| Paper or live | Paper (`execution_mode: read_only_simulation`) | Paper / advisory | Paper / advisory |
| Evidenced days | `equity_curve_daily.json` summary: `evidenced_days` **100** (2026-06-22 → 2026-10-01). Of 132 bars, 20 are warmup, 11 backfill, 1 reconstructed | `daily_history` has 39 rows since 2026-08-24. Only **22 rows** (2026-09-10 onward) use `accrual_basis: per_position_observed_apy`. The 17 rows from 08-24 to 09-09 were `per_position_live_apy` on fallback literals (flat apy 10.625) | 39 rows, of which 22 are observed. 08-24 to 09-09 ran at a flat 13.0 on literals |
| Track result | NAV $101,477.05. `paper_apy_pct` 4.9195. `max_drawdown_pct` −0.0393 | NAV $99,555.06. Snapshot `apy_pct` **−4.35**. dd −0.94%. Observed window 09-09 → 10-01 annualised: **−14.45%** (computed from the history rows) | NAV $100,260.76. Snapshot `apy_pct` **2.13**. dd −0.34%. Observed window annualised: **−5.56%** |

**Finding A1 (most material): the cost model makes both advisory books lose money by construction.**
- Each daily row re-sizes every leg by a few dollars as equity drifts. Turnover is about $35/day, which roughly equals the prior day's P&L.
- `book_move_cost` (`sleeve_book.py:390-444`) then charges full Ethereum gas of $12 per touched leg, from `GAS_USD_PER_POSITION_CHANGE` (`backtesting/tier1/cost_model.py:20-24`). There is no dust band; the main book does have one (`min_leg_frac`, `cycle_runner.py:2514`).
- Result: $48.03 a day for 4 legs (Balanced) and $24.01 for 2 legs (Aggressive). Annualised drag is about **17.5%** and **8.8%** of $100k, against gross yields of about 4.7–5.2%.
- Every day since 2026-09-10 has a negative `net_pnl_usd`: Balanced about −$35/day, Aggressive about −$11/day.

**Finding A2:** Balanced and Aggressive hold nearly the same thing as Conservative. Both hold maple and fluid_fusdc, which Conservative also holds; Balanced adds susde and morpho_steakhouse. Gross yield is about 5% in all three books. ADR-292 predicted this in `sleeve_book.py:271-273`: "обе книги дадут примерно столько же, сколько консервативная, потому что 12 % и 20 % в наблюдаемой вселенной нет".

**Finding A3:** Balanced does not hold the highest-APY candidate. The 2026-10-01 candidate list puts compound_v3 at 6.388% on top, but the book kept morpho_steakhouse at 4.5027% (`sleeve_inputs_balanced.jsonl` last record). This is probably the CIO gate's HOLD, not a yield ranking.

---

## (B) APY computation chain

1. **Rates.** `data/apy_ranking.json` is written by `apy_aggregator` (generated 2026-10-01T06:00:34Z). Each row has `apy_source` and `tvl_source`. Rows marked `fallback` or `static` are excluded from the sleeve books (`sleeve_book.observable_rows`). These are supplier-side protocol APYs as read from feeds, with no fee or gas adjustment.
2. **Conservative accrual.** `cycle_runner` accrues `position_usd*apy/100/365` per pool. Since ADR-298 it subtracts `_move_cost_usd` on rebalance legs above the dust band (`cycle_runner.py:2500-2535`). Equity bar → `equity_curve_daily.json`.
3. **Sleeve accrual.** `accrue_book` (`sleeve_book.py:326`) → minus `book_move_cost` (`:390`) → plus `mark_to_market` (`:486`).
   - Mark-to-market coverage is tiny: `mtm_coverage_pct` is 25.0 for Balanced (only morpho_steakhouse has a price, `mark_price 1.0`) and 0.0 for Aggressive.
   - So the price risk of susde and maple is **not measured**, and the field says so honestly.
4. **Public headline.** `paper_apy_pct = ((NAV_last/NAV_anchor)^(365/evidenced_days) − 1)·100` (`generate_track_snapshot.py:232-239`).
   - For 80 of the 100 days this is effectively **gross of costs**: costs were only modelled from 2026-09-10, and only $50.15 has been charged.
   - The sleeve books use the same compound formula over all 39 rows with positions, so 17 literal-rate days are mixed in (`_sleeve_paper_track`).
5. **Telegram uses a different formula.** `spa_core/reporting/books_summary.py:35-39` annualises simply (`return_pct*365/days`). Site and owner report therefore annualise differently.
6. **Aggressive Lab mislabels a return as APY.** `spa_core/strategy_lab/aggressive_lab/roster.py:229-233` sets `net_apy_pct = (equity − capital)/capital·100`. That is a **cumulative return since start, not annualised**. Example: `data/aggressive_lab/status.json` 2026-10-01, `pendle_yt_susde` `net_apy_pct: 20.6672` after about 89 days.
7. **Home-page tier cards show a third, backtest number.** `snap.packages` comes from `data/tier1_packages.json` `blended_net_apy_pct` (`generate_track_snapshot.py:77-92`), which is a backtest of strategies s61/s27/s62/s77, not the live book. Conservative = **3.709**; Balanced and Aggressive = null with `status: "no_validated_strategies_yet"` (file generated 2026-10-01T04:30:24Z). `index.astro:671-677` writes this value into the cards client-side.

**Gross vs net, in one line:** every live number is net only of a *modelled* cost (gas table + 8 bps slippage + 5 bps bridge). None is net of real execution or protocol fees, none is shown as gross anywhere, and the word "gross" does not appear on any audited page.

---

## (C) Site explanation matrix (live static HTML, 2026-10-01)

| Item | Verdict | Evidence |
|---|---|---|
| What each strategy does | **MISLEADING** | /packages/ Balanced: "sUSDe carry, Pendle YT-sUSDe. Risk-class C". /strategies/balanced/: "Aave V3 … Compound V3 … Morpho Steakhouse … Yearn V3 … Euler V2 … gated by RiskPolicy v1.0". /methodology/: "Balanced — Paper tracked since June 22, 2026 … Conservative / Aggressive — Target profile defined. Paper tracking not yet started." /strategies/aggressive/: "Levered PT carry loops · Points / incentive farming · Unhedged directional restaking". Actual books: plain supply in maple/fluid/susde/morpho_steakhouse and maple/fluid, outside RiskPolicy |
| Conservative composition | **MISLEADING** | /strategies/conservative/: "Tier 1 protocols only … No Tier 2 or Tier 3 protocols … Aave V3 ~3.5% · Compound V3 ~4.8% · Spark sUSDS ~5%". Home: "Tier 1 pools only", "Tier mix T1". Live book: **T2 = 50%** (maple, fluid, morpho_blue_base), no Spark position, aave_v3 at 5.40% and compound at 6.11% |
| Where yield comes from | **PARTIAL / MISLEADING** | Conservative and Balanced: "All yield comes from lending market interest rates … no leverage". Balanced holds sUSDe (registry T3; its yield is not a lending rate). Aggressive: "Yield amplified through leverage" while the book has none |
| Gross vs net APY | **MISLEADING** | Bands say "up to 6% / 12% / 20% net APY" (tier_bands.json). Home: "4.9% realized … (accrual, no costs charged)", but costs have been charged since 09-10. /risk-disclosure/: "Paper trading performance does not account for: Live transaction slippage and gas costs", yet the sleeve books' negative APY comes *entirely* from modelled gas. No gross/net split anywhere |
| Major risks | **PARTIAL** | Per-page "Strategy-Specific Risks" (smart contract, depeg, oracle, insolvency, APY compression, liquidity) and /risk/ matrix. The Balanced matrix row "Stablecoin depeg: Low · Liquidation None" ignores the sUSDe leg |
| Liquidity | **PARTIAL** | "withdrawals from lending pools may be temporarily delayed if utilisation rates approach 100%". /exit-nav/ covers the rates-desk book ("Our live book (honestly thin)"), not the three packages |
| Exit time | **MISLEADING** | All three strategy pages: "No lock-up. Standard processing T+1. Large or complex withdrawals may take up to 5 business days. No withdrawal fee." /faq/ says the opposite: "No product terms — including lock-up — are set yet". /emergency-withdrawal/: "there is no withdrawal process of any kind". No exit-time model exists in code. The first quote also matches the solicitation phrases forbidden by `.claude/rules/site-copy.md` |
| Leverage | **MISLEADING** for Aggressive | Conservative/Balanced "No leverage" is true in code. Aggressive claims leverage; the Aggressive book (lp_cycle) has none. Leverage exists only in the separate Aggressive Lab books (`leverage_loop`, `pendle_pt_levered`) |
| Liquidation possibility | **PARTIAL** | /risk/ matrix "Liquidation None / None / High". Aggressive FAQ: "real liquidation-cascade risk (levered loops)", which does not apply to the book reported as "Paper test running · 2 positions" |
| Protocol vs strategy risk shown separately | **ABSENT** | Pages list protocol-level risks under "Strategy-Specific Risks". There is no separate strategy-mechanics risk line |
| Historical vs current yield | **MISLEADING** | Hardcoded per-protocol APYs ("~3.5%", "~4.8%", "~5%", "Morpho Steakhouse ~6.5%") presented as current. Home calculator "At our realized rate ~$1,650/yr" on $50,000 = **3.3%**, hardcoded at `landing/src/pages/index.astro:188,206` (`a*0.033`), sitting beside "4.9% realized". /packages/: "The tail in numbers: 15% vs the real ~3.3%". /risk-disclosure/: "target go-live date is approximately July 21, 2026" |
| Paper vs real | **MISLEADING (partly)** | Paper is disclosed widely ("results are simulated"). But /packages/ Conservative says "LIVE · evidenced · fundable" and "L6 · live evidenced" (from tier_bands.json), and the rollup status says "LIVE · evidenced · fundable". /faq/: "A Gnosis Safe (multisig) is used — no transaction goes through without confirmation", in present tense, for a paper system |
| Confidence / evidence level (L0–L6) | **PARTIAL / MISLEADING** | /methodology/ explains the scale correctly: "Paper is L3 … Must say 'paper', never 'live'", and "our evidenced paper track is honest L3". /packages/ tags Conservative **L6** (defined in `docs/37` as "Multi-cycle validated … at live capital") and tags the running Balanced/Aggressive paper tracks "L2 · paper / backtest" (paper = L3 per docs/37). /packages/ does show "17 of 35 days accrued on rates nobody observed (before 2026-09-10)" (good) |
| Tail shown next to yield | **EXPLAINED (labels) / MISLEADING (values)** | "Worst drawdown: ~4.5% (backtest, hedged sUSDe book)" (Balanced) and "up to ~50% (backtest, unhedged directional book)" (Aggressive). These tails belong to aggressive_lab backtests, not to the books whose paper day count is shown on the same card |
| Drawdown | **MISLEADING** | /packages/ and home cards: "0.0%" (literal `dd_short_en "0.0% (live)"` in tier_bands.json). Same home page, Transparency block: "Max drawdown -0.04%". Snapshot: −0.0393 |

---

## (D) Contradictions

1. **Four different definitions of Balanced/Aggressive.**
   - (a) hy_cycle / lp_cycle books (ADR-125; snapshot `paper_tracks`; /packages day counter).
   - (b) aggressive_lab blends (`scripts/tier_paper_rollup.py`, which reads `aggressive_lab/scorecard.json`, mtime 2026-07-10).
   - (c) tier1 backtest packages (`data/tier1_packages.json`: "no_validated_strategies_yet").
   - (d) site prose (sUSDe/Pendle YT; Morpho/Yearn/Euler lending; levered PT loops).
   - The /packages footer even says "realized numbers live on /status (Conservative) and in the Aggressive Lab (the rest)", while the same page renders hy/lp numbers.
2. **Conservative "T1 only"** (site, `docs/THREE_TIER_YIELD_PRODUCT.md` "RWA-пол") vs live **50% T2** (`current_positions.json` `t2_pct: 50.0`; SYSTEM_BRIEFING "T1: 45% · T2: 50%").
3. **Kill switch for Balanced/Aggressive.** Site says SOFT 5% / HARD 10% ("The same non-overridable two-tier kill switch applies"). Code: −8% (`hy_cycle.py:48`) and −25% (`lp_cycle.py:51`). The Aggressive page also contradicts itself: "Aggressive is advisory research OUTSIDE RiskPolicy v1.0" vs its FAQ "Yes. RiskPolicy v1.0 applies to all strategies."
4. **Three Conservative APYs on the home page:** card 3.7% (tier1 backtest, client JS), hero 4.9% (site_numbers, measured 2026-09-27), calculator 3.3% (literal). Inside `track_snapshot.json`, `packages.conservative.apy_pct` 3.7 / `dd_pct` 0.0 vs `paper_tracks.conservative.apy_pct` 4.92 / `dd_pct` −0.0393.
5. **Stale numbers on the site.** The site is weekly (`site_numbers.json` `measured_at` 2026-09-27): it shows "day 35", "96/30", Balanced −3.4%, Aggressive 2.8%. The daily snapshot (2026-10-01) has 39 days, 100/30, −4.35%, 2.13%. Disclosed as weekly cadence, but the date is not printed beside the package figures in the static text.
6. **Evidence tags.** /packages "L6" vs /methodology "L3" for the same Conservative track.
7. **Costs.** Home "(accrual, no costs charged)" vs `costs_paid_usd` 50.15 (main book) and 1,223.52 / 632.76 (sleeve books). /risk-disclosure says paper excludes gas and slippage.
8. **aave_v3 TVL in two artifacts, same morning.** `apy_ranking.json` says `tvl_usd 4,085,659` (`live`, below the $5M floor, APY 12.67). `current_positions.json` says `tvl_usd 57,672,290` (APY 5.40), and the main book holds $5,000 in it.
9. **susde.** Blocked as `"advisory"` in Conservative (`current_positions.json` `feed_coverage.blocked.susde`) but held at $24,897 in Balanced. Expected by design (advisory sleeve), but the Balanced page lists no sUSDe.
10. **Docs vs code.**
    - `docs/PACKAGES.md` and `docs/THREE_TIER_YIELD_PRODUCT.md` describe Balanced as "sUSDe delta-neutral, Pendle PT-carry, LST-hedged" and Aggressive as "Levered Pendle PT/YT carry, LRT-restaking, points"; ADR-125 explicitly says the live Aggressive book is not directional or leveraged.
    - The Balanced per-protocol cap is 40%, but the site table shows "Per-protocol cap (T2) 20%" while the book holds four T2/T3 legs at 25%.
    - The Aggressive legs are 50% T2 each against a site table showing "40% T1 / 20% T2".
11. **CLAUDE.md snapshot is stale.** It says GoLive 27/29 and 13/30 evidenced; live is 29/29 and 100/30 (`track_snapshot.json`, SYSTEM_BRIEFING 07:28 UTC).
12. **Owner surfaces under-report.**
    - `docs/SYSTEM_BRIEFING.md` (2026-10-01 07:28 UTC) has no Balanced/Aggressive section at all; Portfolio covers only Conservative.
    - The Telegram daily report (`spa_core/telegram/reports/daily.py:755-764`) gives only "Советующие пакеты (paper, капитал не двигают): Σ <equity>". There is no per-package APY, no cost, and no note that both books lose money daily.

---

## (E) UNKNOWNs

- **What the client-side JS renders.** api.earn-defi.com was not fetched (outside the allowed HTTP scope). The home tier-card values come from code reading only (`index.astro:666-680`), and /aggressive-lab/ figures are JS-only (the static page has no numbers).
- **Whether the CIO gate (`cio_arming.gate_sleeve_book`) is "armed" for balanced/aggressive.** Not checked (`is_armed` state). That decides whether the daily re-size is accepted or held. The rows show turnover every day, which suggests it is accepted.
- **Real exit time and slippage at size for maple, fluid, susde.** No code models it for these books; `exit_liquidity.py` is not on the money path.
- **The sUSDe / maple price path.** Not measured (`mtm_unmarked` lists them), so the sleeve drawdowns exclude price moves.
- **Why the ranking's aave_v3 TVL (4.08M) differs from the cycle feed (57.7M).** Two sources, root cause not traced.
- **Whether "4.9% realized" is shown with its measurement date on every page.** `realizedPhrase` appends "(measured …)", but the static home hero text lacks it.
- **RU copy.** Checked only through tier_bands.json names; no full RU pass (text extraction takes element text, not `data-ru`).
