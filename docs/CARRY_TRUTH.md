# CARRY TRUTH — does the desk actually beat the RWA floor, risk-adjusted, on REALIZED data?

> ROUND-2 "Prove the Edge", Workstream 1. The honest answer, replacing narrative with numbers.
> Source artifacts (deterministic, fail-CLOSED, LLM-FORBIDDEN, advisory — the go-live track is
> byte-untouched):
> `data/realized_ab/realized_ab.json` · `data/edge_at_scale.json` ·
> `data/carry_truth_table.json` · `data/refusal_cost.json`.
> Regenerate: `python3 -m spa_core.strategy_lab.{realized_ab,edge_at_scale,carry_truth_table,refusal_cost}`.

---

## The one-line answer

**INSUFFICIENT_DATA — yet.** On the REALIZED forward track (anchor 2026-06-22, ~4–6 days deep),
**no sleeve has enough day-distinct history to claim it beats the RWA floor risk-adjusted**, and
the two sleeves with the longest tracks are **at-or-BELOW** the floor on realized carry so far:

| Sleeve | Realized carry-above-floor | Track depth | Verdict |
|---|---|---|---|
| `rates_desk_fixed_carry` (FixedCarry) | **−$27.11** (raw accrual ~$7.78 < what the floor would have earned) | 5 pts | INSUFFICIENT_DATA (and **below floor** so far) |
| `rwa_sleeve` (the realized floor itself) | +$0.21 (≈ at floor, by construction) | 4 pts | INSUFFICIENT_DATA |
| every other forward sleeve | thin (< 7 pts) | 4–6 pts | INSUFFICIENT_DATA |

The honest, valuable finding: **the desk does not yet demonstrably beat the floor on realized data**,
and the headline ~$7.78/week FixedCarry accrual is, on a like-for-like floor comparison, *below* the
~3.18%/yr the same capital would have earned just holding tokenized T-bills. This is not a failure —
it is the correct reading of a 4–6 day track. The machinery is now in place to flip this to a real
verdict as the track matures, without ever fabricating one early.

---

## WS-1.1 — Realized forward A/B (`is_realized:true`, not a replayed backtest)

`data/optimizer_ab.json` was a BACKTEST: it replayed the same window every run, so it was
`is_realized:false` with 7 byte-identical rows (every day +1.3737pp — one number printed 7×).

`spa_core/strategy_lab/realized_ab.py` replaces it with a REALIZED forward A/B: each UTC day it
scores the live held-universe ONCE through the legacy `risk_adjusted` heuristic AND the WS-1.2
`optimized_yield` optimizer, and banks realized daily accrual into TWO parallel paper books
(`data/realized_ab/*_series.json`), one **distinct** row per UTC day. `is_realized:true`. It starts
THIN (1 day → `status:"thin"`, `verdict:"INSUFFICIENT_DATA"`) — correct, by design.

## WS-1.2 — Cash-floor-fair decomposition (selection alpha vs cash drag)

The legacy heuristic deploys ~100% (it skips the 5% cash floor); the optimizer reserves it. A raw
APY gap therefore conflates **selection skill** with a **cash-drag advantage**. The realized A/B
decomposes the uplift and banks a third, like-for-like book (`legacy_risk_adjusted_floorfair`, same
5% floor):

- `raw_uplift_bps` — optimized − legacy (**NOT** apples-to-apples; the headline backtest claimed this)
- `selection_alpha_bps` — optimized − legacy-floor-fair (**apples-to-apples** selection edge)
- `cash_drag_bps` — legacy − legacy-floor-fair (the floor-skip advantage, **not** selection skill)

On the first realized day the decomposition reads: raw ≈ +108 bps, **selection ≈ +130 bps**, cash-drag
≈ +22 bps **in the legacy book's favor** — i.e. the naive raw gap *under*states the optimizer's true
selection edge because the legacy book was getting ~22 bps for free by skipping the cash floor.
Honest apples-to-apples, the opposite spin from the backtest headline.

## WS-1.3 — Scale-honest edge curve (the edge that matters survives at fundable size)

`spa_core/strategy_lab/edge_at_scale.py` recomputes the optimizer uplift at **$100k / $1M / $10M**
AFTER the **real** MP-209/ADR-009 pool-capacity caps (1% of pool TVL, 3% for T1 > $1B) bind, using
each pool's **live** TVL (read-only from `adapter_orchestrator_status.json`). Capacity-capped capital
becomes idle cash (earns 0 — the conservative, fundable-honest drag).

| AUM | legacy yield | optimizer yield | uplift | optimizer capital capped-out |
|---|---|---|---|---|
| $100k | 4.50% | 5.58% | **+1.08pp** | $0 |
| $1M | 3.38% | 1.38% | **−2.00pp** | $700k |
| $10M | 1.83% | 0.84% | **−0.99pp** | $7.9M |

**The edge does NOT survive at scale. It falls below the 0.25pp materiality bar at ≈ $1M AUM and goes
NEGATIVE.** Why: the optimizer concentrates into high-yield, **small-TVL** pools (euler_v2 ~$14M,
pendle ~$7M, …). At $1M+ a 20%-weight slug exceeds the 1%-of-TVL cap, so most of the optimizer's
concentrated book is capped out into cash, while the legacy heuristic's broader spread survives the
caps better. **The optimizer's +1.08pp is a $100k-scale artifact; at the fundable size that underlies
the $100M thesis, today's universe cannot support it.** That is the valuable finding.

## WS-1.4 — Carry truth-table (this document's table)

`spa_core/strategy_lab/carry_truth_table.py` ranks every realized forward sleeve by carry-above-floor
(bps), reusing the NAV-reconciling floor-leg/carry-leg split (`forward_analytics.captured_book_attribution`
— carry is the residual, so no leg can be inflated independently). INSUFFICIENT_DATA is a first-class
verdict (thin/broken track → **null bps, never a fabricated 0.0**).

## WS-1.5 — "Why in cash" refusal-cost (`data/refusal_cost.json`)

`spa_core/strategy_lab/refusal_cost.py` quantifies what the refusal-first gate forgoes by sitting in
cash, from the FixedCarry forward series' per-day `scan_diag` (read-only re-derivation). On 2 of 4
diagnostic days the gate refused a `tail_veto` candidate quoting ~1300 bps → **cost-of-caution ≈ 651
bps/yr IF that refused edge were real carry**. But the gate's thesis is that the refused ~1300 bps is
*tail-compensation* (the 2025-10 USDe-leverage-unwind / ezETH pattern), not carry — so the "cost" is an
**insurance premium**, not lost alpha. The realized carry track adjudicates: since even the *approved*
FixedCarry book is **below** the floor so far (WS-1.4), the conservatism is **defensible** — the gate
is not yet demonstrably leaving fundable money on the table. A `size_floor` refusal forgoes nothing
fundable and is **excluded** from cost-of-caution (counting it would inflate the apparent cost).

---

## Red-team (each masking path is caught — see `tests/test_round2_ws1_prove_edge.py`)

- **replay-day injection** (re-counting one day) → the realized books append ONE row per UTC day; a
  duplicate date REFRESHES from the prior equity (never double-compounds); a multi-row book with
  byte-identical accrual every row is flagged `replay_suspect`.
- **cash-drag laundering** (hiding the floor advantage) → the decomposition is the headline; the raw
  gap is labeled `raw_uplift_apples_to_apples:false`; `cash_drag_bps` is reported explicitly.
- **INSUFFICIENT_DATA masked as 0.0** → a thin/broken track yields `INSUFFICIENT_DATA` with **null**
  bps, never a fabricated 0.0 presented as a real verdict.
- **a backtest presented as realized** → the realized A/B writes a SEPARATE `is_realized:true`
  artifact and never reads/echoes `data/optimizer_ab.json` (the backtest); the truth-table ingests
  only on-disk forward `*_series.json` tracks.
- **scale-cap evasion** (a fabricated huge TVL so caps never bind) → `edge_at_scale` uses the real
  live per-pool TVL; a missing TVL defaults to the $5M floor (conservative — caps bind *sooner*).

---

## Honest bottom line

- **Does the desk beat the floor risk-adjusted on realized data?** → **INSUFFICIENT_DATA yet** (track
  is 4–6 days; the two longest tracks are at-or-below floor so far).
- **At what AUM does the optimizer edge survive?** → **It does not survive past ≈ $1M** on today's
  universe; the +1.08pp is a $100k-scale artifact that capacity-caps dissolve at fundable size.
- **Is the refusal gate's conservatism defensible?** → **Yes, so far** — the realized carry doesn't
  yet beat the floor, so refusing ~1300 bps tail-comp candidates is insurance, not forgone alpha.

The value of this workstream is the machinery that will keep these answers truthful as the track
deepens — and the honest admission that, today, the edge is **not yet proven** at fundable scale.
