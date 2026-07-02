# 07 — Sleeve Status (YL-005): lifecycle × product-line × spread verdict

> Companion to `docs/07_yield_lab_architecture.md` (the lifecycle spine) and
> `docs/adr/ADR-YL-008-unified-yield-lab-mandate.md` (the mandate). This maps **every**
> `spa_core/strategy_lab/` and `spa_core/strategy_lab/aggressive_lab/` sleeve to its (1) lifecycle
> status (docs/07 §3), (2) targeted product line (docs/34), and (3) **spread verdict under
> ADR-YL-008** — is every point of spread over the live RWA floor (~3.4%, live from `data/rwa_feed.py`,
> **never hardcoded**) explained by a specific accepted measurable risk, or is it **refused**?
>
> **Honesty rules of this table (never violated):**
> - The mandate judges **spread over the floor**, NOT absolute APY.
> - **Rejection is a positive result** (logged in the refusal log) — a REJECTED row is the Lab working.
> - Numbers are **sourced** (`data/aggressive_lab/scorecard.json`, `data/strategy_lab_backtest.json`)
>   or `requires verification` — never invented.
> - Live floor baseline: `rwa_sleeve` realized **~3.4328%** in `data/strategy_lab_backtest.json` (the
>   baseline confirmed by data, not a literal).

## Legend

- **Lifecycle status** (docs/07 §3): `idea → research → rejected` / `paper_testing → paper_passed →
  small_capital_testing → small_capital_passed → approved_for_{preserve,core,enhanced,max_yield} →
  frozen → retired`. `baseline` = the floor itself (not a spread candidate).
- **Product line** (docs/34): Preserve 4–7% / Core 7–10% / Enhanced 10–13% / MaxYield 13–18% /
  Experimental 18–25%+. This is the **TARGET** bucket; approval is separate.
- **Spread verdict (ADR-YL-008):** `explained` (spread fully attributed → eligible) / `INSUFFICIENT_DATA`
  (no realized spread yet) / `risk-comp` (positive but tail not fully priced → advisory, not promotable)
  / `REFUSED` (unexplained spread = unpriced tail → rejected, refusal-logged) / `baseline` (IS the floor,
  spread ≈ 0 by construction).

## Strategy-Lab sleeves (`spa_core/strategy_lab/`)

| Sleeve | Lifecycle status | Product line (target) | Realized (sourced) | Spread verdict | One-line honest verdict (ADR-YL-008) |
|---|---|---|---|---|---|
| `rwa_sleeve` | **baseline** | Preserve | net **3.4328%** = floor (`strategy_lab_backtest.json`; `beats_rwa_floor` true, at floor) | **baseline** | IS the floor — banks ~3.4%, does not beat it; spread ≈ 0 by construction, trivially "explained." Every other row is measured against this. (card: `SC-RWA-001`) |
| `rates_desk_fixed_carry` | **paper_testing** | Enhanced | backtest net **6.0901%** (walk-forward 100%); live-paper realized-at-size **INSUFFICIENT_DATA** (realized_days 0) | **INSUFFICIENT_DATA** | Backtest-GO carry (beats floor ~269 bps in backtest), refusal-validated (1,070 refusals), but realized-at-size spread = 0 and not yet decomposed point-by-point → held, not promoted. (card: `SC-RDFC-001`) |
| `eth_lst_neutral` | **paper_testing** | Enhanced | backtest **0.0%** (FAIL-CLOSED tick 1: "eth_price missing/invalid" 2024-06-05, equity flat $100k); forward series absent → **INSUFFICIENT_DATA** (`strategy_lab_backtest.json`) | **INSUFFICIENT_DATA** | The SAFE hedged-ETH design (plain LST + short perp, β≈0), but no realized spread yet (backtest never traded; forward absent). "Safer design" earns nothing under the mandate without a realized, risk-explained spread → held. (card: `SC-ETHLSTN-001`) |
| `variant_n` | **paper_testing** | Enhanced | strategy_lab backtest **0.0%** / **killed** (fail-closed, offline feed; `net_apy_pct` 0.0, `beats_rwa_floor` false) → **INSUFFICIENT_DATA** | **INSUFFICIENT_DATA** | Neutral restaking (LRT eETH spot + short ETH-perp, β≈0). In the strategy_lab window it fail-closed/killed with no traded track → no realized spread to explain. Prior runs show the LRT depeg kill firing (Aug-2024) — the tail this design carries. |
| `variant_d` (strategy_lab) | **paper_testing** | MaxYield | strategy_lab backtest **0.0%** / **killed** (fail-closed; `beats_rwa_floor` false) → **INSUFFICIENT_DATA** | **INSUFFICIENT_DATA** | Pure directional LRT (NO hedge, β≈1) — an isolated directional sleeve. In the strategy_lab window it produced no traded track. **The aggressive-lab `variant_d` run (below) is the trustworthy directional evidence: realized −15.48% → REJECTED.** Same design, distinct run. |

## Aggressive-Lab sleeves (`spa_core/strategy_lab/aggressive_lab/`)

> Source: `data/aggressive_lab/scorecard.json` (generated 2026-06-29; `is_advisory` true,
> `outside_riskpolicy` true, `separate_from_golive_track` true). These are the 10–15% strategies the
> desk normally **refuses**, paper-tested so the owner can choose with eyes open. Headline yield is
> **risk-compensation**; the realized number + tail is what it actually pays for. Ratios come from the
> **backtest** (700 pts, 2024-07-01→2026-05-31) where trustworthy; the 12-pt "forward" is LOCKED_VOL →
> read as INSUFFICIENT_DATA, never a Sharpe.

| Sleeve | Risk class | Lifecycle status | Product line (target) | Headline → realized (sourced) | Spread verdict | One-line honest verdict (ADR-YL-008) |
|---|---|---|---|---|---|---|
| `leverage_loop` | C (risk-comp) | **rejected** | MaxYield | headline **15.0%** → backtest realized **−8.95%** (max_dd 27.94%; worst stress dd 35.22%) | **REFUSED** | Levered PT carry loop. The entire ~1160 bps nominal spread is unpriced liquidation tail — and it MATERIALIZED (realized negative). Refused; a positive result in the refusal log. (card: `SC-LEVLOOP-001`) |
| `lrt_carry` | C (risk-comp) | **rejected** | Enhanced | headline **13.0%** → backtest realized **−3.60%** (max_dd 20.14%; worst stress dd 26.00%, NOT_RECOVERED) | **REFUSED** | LRT carry (eETH/rsETH PT). The fat headline is compensation for the depeg tail that hit Aug-2024 and the 2026-04 rsETH depeg; realized spread NEGATIVE → the tail is unpriced. Refused. |
| `points_farm` | D (incentive) | **research / advisory** | MaxYield | headline **14.0%** → backtest realized **12.35%** (low vol; but risk_class D = decays) | **risk-comp (incentive)** | Points/airdrop farm. Realized is high with a small backtest drawdown, BUT it is **incentive class (D) — it DECAYS**, not a durable edge; the "spread" is emissions that end, not risk-explained carry. Advisory only; NOT a fundable structural spread. |
| `susde_dn` | C (risk-comp) | **research / risk-comp** | MaxYield | headline **11.0%** → backtest realized **4.2175%** (Sharpe 1.06; worst stress dd 10.55%, NOT_RECOVERED) | **risk-comp** | sUSDe delta-neutral funding carry. Realized POSITIVE and beats the floor by ~82 bps — but as class C the spread must be fully attributed or refused; the thin spread pays a severe funding-flip/Ethena-unwind tail that is not decomposed → advisory, not promoted. (card: `SC-SUSDEDN-001`) |
| `thin_new` | C (risk-comp) | **paper_testing (thin)** | MaxYield | headline **12.0%** → forward realized **12.747%** on only 6 pts; backtest **empty** → **INSUFFICIENT_DATA** | **INSUFFICIENT_DATA** | A brand-new sleeve with only ~6 forward days and no backtest. Must read INSUFFICIENT_DATA, never a fabricated Sharpe. No verdict possible until it has a trustworthy track; no spread can be attributed yet. |
| `variant_d` (aggressive_lab) | B (beta) | **rejected** | Enhanced | headline **9.0%** → backtest realized **−15.48%** (max_dd 28.95%; worst stress dd 34.54%, NOT_RECOVERED) | **REFUSED** | Pure directional ETH restaking (NO hedge) — secretly ETH beta, flagged B. Realized deeply NEGATIVE: the "yield" was directional market exposure, not a risk-explained spread. Refused. |

## Roll-up (honest scoreboard)

- **Baseline:** `rwa_sleeve` — the ~3.4% floor everything is measured against (not a spread play).
- **Held / INSUFFICIENT_DATA (no realized spread yet, cannot be promoted):** `rates_desk_fixed_carry`,
  `eth_lst_neutral`, `variant_n`, `variant_d` (strategy_lab), `thin_new`. Correctly NOT promoted —
  the mandate requires a **realized, risk-explained** spread, and none has one.
- **Risk-comp / advisory (positive but tail not fully priced — beating the floor is necessary, not
  sufficient):** `susde_dn` (realized +4.22%, class-C funding tail), `points_farm` (realized +12.35%,
  class-D decaying incentives).
- **REJECTED (unexplained spread = unpriced tail that materialized — the refusal log = the product):**
  `leverage_loop` (−8.95%), `lrt_carry` (−3.60%), `variant_d`/aggressive_lab (−15.48%).
- **Fully-explained, floor-beating, fundable spread:** **NONE yet.** No sleeve currently has a realized
  spread over the floor that is fully attributed to accepted measurable risk. This is the honest state
  the ADR-YL-008 mandate is designed to surface: the refusals and the "held" rows ARE the Lab's output,
  and absolute APY is deliberately not the yardstick.

---

*Sources: `data/aggressive_lab/scorecard.json` (2026-06-29), `data/strategy_lab_backtest.json`,
`spa_core/strategy_lab/strategies/eth_lst_neutral.py`, `docs/07_yield_lab_architecture.md`,
`docs/adr/ADR-YL-008-unified-yield-lab-mandate.md`. Strategy Cards:
`data/strategy_cards/examples/{rwa_sleeve, rates_desk_fixed_carry, eth_lst_neutral, leverage_loop,
susde_dn}.strategy.md`. Realized numbers are sourced or `requires verification`; none invented.*
