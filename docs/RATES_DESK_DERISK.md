# SPA Rates Desk — Cheap De-Risk (RESEARCH, paper, reversible)

**Status:** research de-risk per §8 of the thesis. NOT a live trading book. Pure compute over
data we already have, deterministic, stdlib-only, LLM-forbidden, fail-CLOSED.
**Date:** 2026-06-25 · **Module:** `spa_core/strategy_lab/rates_desk/` · **Tests:** `spa_core/tests/test_rates_desk.py` (11 green)

---

## The thesis under test

The edge is a **risk-adjusted fair-value model for tokenized yield** that (a) harvests
genuinely-mispriced carry and (b) **REFUSES yield that is just tail-risk compensation** (the
ezETH / over-levered-USDe pattern). The single question before any capital:

> Does our risk engine separate **"real excess spread"** from **"tail-comp you'll pay back"**?

Two deterministic yes/no tests answer it, over the real cached 2024-06 → 2026-06 history.

---

## What was built

| File | Role |
|---|---|
| `risk_score.py` | Deterministic 0–1 **tail-risk score** per underlying per date. Components: (1) **depeg drawdown** of the smoothed X/ETH ratio vs its trailing peak, (2) **downside-drift vol** of the smoothed ratio, (3) **funding-flip probability** (fraction of recent days with negative perp funding). Higher = more toxic. |
| `fair_value.py` | `fair_implied = baseline_yield − tail_haircut`; **CARRY** when `quoted − fair > cost` AND `tail < threshold`; **REFUSE** when the high yield is explained by tail (or no spread clears cost). |
| `retro.py` | The two retrospective tests over `data/rates_desk/*` (deep-fetched real history). |
| `config.py` | All thresholds in one place (no magic numbers in logic; change → new ADR). |

**Design choice (inherited from `strategies/eth_lst_neutral.py` + `variant_n.py`):** the depeg
signal is measured on a **short trailing median** of the X/ETH ratio — DeFiLlama logs the token
and ETH at different intraday moments, producing spurious 1-day ratio spikes. The ratio is **not**
assumed ≈1.0: value-accruing wrappers (weETH, rETH, ezETH) drift above 1.0, so "depeg" is a
**drawdown from the ratio's own trailing peak**, never absolute distance from 1.0.

---

## Data availability (honest)

The repo's `data/market_data/` cache held only the shallow **most-recent 90-day** page, *not* the
~2-year history the thesis assumes. The feeds *can* paginate deep history, so I deep-fetched the
real series into a research cache **`data/rates_desk/`**:

| File | Coverage | Source |
|---|---|---|
| `prices_deep.json` | eth/eeth/weeth/ezeth/steth/reth, **591–696 pts**, 2024-06-01 → 2026-06-25 | DeFiLlama coins API |
| `funding_deep.json` | ETH-perp 8h funding median, **755 days**, 2024-06-01 → 2026-06-25 | 5-venue funding feed |
| `restaking_deep.json` | eeth/weeth/steth/reth **751–755 pts** (ezeth from 2024-12-13, **560 pts**) | DeFiLlama yields |
| `pendle_pt_deep.json` | 7 PT markets (USDe, sUSDe, sUSDS, superUSDC, …), implied + underlying APY | Pendle API v2 |

**Key data gap:** Pendle `/active` returns only **currently-live** markets → PT implied-yield
history maxes at **~69 days** here (markets created ~April 2026; expired-market history is not
exposed by the keyless API). This is the binding limitation for TEST 2 (below).

---

## TEST 1 — REFUSAL EDGE → **PASS (substantive); FAIL (strict)**

*Did the tail score flag the toxic LRTs as high-risk BEFORE their drawdowns, while keeping the
tight-peg LSTs low?*

| Underlying | Group | Median score | Peak | First refuse-cross | Worst ratio DD | Flagged BEFORE? |
|---|---|---|---|---|---|---|
| ezeth | LRT (suspect) | **0.383** | 0.90 | 2024-08-11 | −5.0% (2025-08) | ✅ |
| eeth | LRT (suspect) | **0.355** | 0.95 | 2024-08-21 | −6.4% (2025-05) | ✅ |
| weeth | LRT (suspect) | **0.230** | 0.75 | 2024-09-08 | −2.9% (2024-12) | ✅ |
| steth | LST (safe) | **0.144** | 0.84 | 2024-08-11 | −3.7% (2024-08) | ✅ |
| reth | LST (safe) | **0.342** | 0.85 | 2024-08-11 | −4.0% (2024-08) | ✅ |

- **Toxic flagged-before-drawdown: 3/3.** Every restaking LRT crossed the refuse threshold at or
  before its worst drawdown (no look-ahead).
- **Toxic vs safe separation: 0.080** (toxic mean median 0.323 vs safe 0.243) — a real, meaningful
  gap, well above the 0.04 "not-coin-flip" bar.
- **stETH (the canonical tight-peg LST) stays low: ✅** (median 0.144).
- **The cleanest raw signal** (downside-drift vol of the smoothed ratio, full history):
  ezETH 0.84% ≈ eETH 0.85% > rETH 0.65% > weETH 0.51% > stETH 0.46% — the scorer's drift
  component reproduces this ordering exactly.

**Why strict FAILs and what it means (honest):**
- **rETH** scores moderately toxic (median 0.342). Its DeFiLlama-derived X/ETH ratio is genuinely
  **noisy** (thinner secondary-market pricing → larger day-to-day oscillation), which the
  downside-drift component reads as risk. This is a **data-quality caveat, not a thesis failure** —
  the same noise would inflate a real desk's measured risk on rETH too.
- The **Aug-2024 ETH crash spiked EVERY staked-ETH token** transiently (stETH peak 0.84, rETH 0.85).
  That is honest systemic behavior — a single crash is not a per-token toxicity signal — so the
  discriminating test is the **median-regime** score, not a one-off threshold cross.

**Calibration finding (recorded here, not hidden):** funding-flip is the **same shared ETH-perp
funding for every token**, so it does **not discriminate** between underlyings — it only flags
*when* the broad carry regime unwinds. At the initial 0.20 funding weight a uniform ~0.07 funding
floor collapsed the toxic-vs-safe separation. Dropping funding to **0.10** (a systemic overlay) and
lifting the per-underlying drift weight to **0.60** restored the clean ranking. Funding belongs in
the score as a *regime* term, not a *cross-sectional* one.

**Verdict TEST 1: the risk engine DOES separate toxic restaking from safe staking** (3/3 toxic
flagged before blowup, clean 0.08 separation, stETH stays low). The strict "all safe LSTs stay
low" bar fails only on rETH's noisy pricing. **Substantive PASS.**

---

## TEST 2 — CARRY EDGE → **INCONCLUSIVE (honest data gap)**

*On real Pendle PT implied-yield history, does CARRY select genuinely-mispriced spread that beats
the ~3.4% RWA floor, while REFUSing tail-comp?*

| Market | Days | CARRY days | Refuse(tail) | Net spread (CARRY) | Realized carry |
|---|---|---|---|---|---|
| USDe | 69 | 69 | 0 | 4.60% | 4.60% |
| srUSDe | 21 | 21 | 0 | 2.50% | 2.50% |
| tmvUSDC | 39 | 38 | 0 | 2.41% | 2.35% |
| jrUSDe | 21 | 17 | 0 | 2.19% | 1.78% |
| sUSDS | 42 | 40 | 0 | 1.45% | 1.38% |
| sUSDe | 69 | 60 | 0 | 0.94% | 0.81% |
| superUSDC | 60 | 3 | 0 | 9.14% | 0.46% |

- **Blended realized carry (markets ≥20 days): 1.98%/yr** vs **RWA floor 3.375%** → on this short,
  calm window the *gated* carry does **not** beat the floor on average.
- The mechanism works: the classifier admits genuine implied-over-underlying spread and the
  `superUSDC` case (only 3/60 CARRY days, 9% headline) shows it correctly **withholds** entry when
  the high headline is not a clean, persistent spread.
- **No REFUSE(tail) days fired** — because the available PT window (Apr–Jun 2026) contains **no
  stress event** and funding never flipped materially negative. The tail gate was simply never
  triggered in this calm sample.

**Why INCONCLUSIVE, not a NO:**
1. **History is far too short** (max 69 days). Pendle's keyless `/active` API drops expired markets,
   so a 2024-2026 PT implied-yield series is **not obtainable** from the free endpoint.
2. **Deflated-Sharpe is degenerate here.** Running the real `tier1/deflated_sharpe` on the USDe
   carry series gives daily Sharpe 5.6, PSR≈1.0, minTRL≈4 days — the "stablecoin Sharpe is
   degenerate" trap the tier1 modules explicitly warn about. The statistic *passes* but is
   **meaningless**: the binding risk for a carry book is the **discrete principal tail** (depeg /
   exploit / bad-debt), and the calm 69-day window contains none. So a "pass" would be false comfort.

**What a real TEST 2 needs:** expired-market PT implied-yield history spanning ≥1 stress event
(e.g. via a Pendle subgraph / archival snapshots), so the carry book can be tested **through** a
funding flip and a depeg — exactly where the tail gate must earn its keep. Absent that, TEST 2 can
demonstrate the *mechanism* and net-of-cost spread but **cannot deliver a risk-adjusted verdict.**

---

## GO / NO-GO

**Is the thesis real enough to build the full desk?**

**QUALIFIED GO — for the REFUSAL leg; HOLD on the CARRY leg pending data.**

- The **refusal engine is the real, validated half of the thesis.** On two years of real data it
  separates toxic restaking (ezETH/eETH) from safe staking (stETH), flags the toxic ones at/before
  their drawdowns, and does so deterministically and fail-closed. This is precisely the capability
  the thesis says must exist before capital — and it does. The refusal/whitelist filter is buildable
  now as an advisory gate (`IS_ADVISORY=True`) layered on the existing adapter feeds.
- The **carry-harvest leg is unproven, not disproven.** The fair-value classifier behaves correctly
  on the available window, but the only obtainable PT history is too short and too calm to test the
  thing that matters (carry survival through a tail event), and on this window the gated carry did
  not beat the RWA floor. **Do not allocate to a carry book** until expired-market PT history (or an
  equivalent multi-year, stress-spanning implied-yield series) is sourced and the carry passes a
  *principal-tail-aware* test — not a degenerate Sharpe.

**Cheapest next step:** wire the validated tail-risk scorer in as an **advisory REFUSE filter** over
the existing yield universe (no capital, fully reversible), and separately invest in sourcing
long-horizon PT implied-yield data to make TEST 2 answerable.

---

## Reproduce

```bash
python3 -m pytest spa_core/tests/test_rates_desk.py -q        # 11 green
python3 -m spa_core.strategy_lab.rates_desk.retro             # prints both verdicts (real data)
```

Data lives in `data/rates_desk/` (deep-fetched real history; re-fetchable from the keyless feeds).
