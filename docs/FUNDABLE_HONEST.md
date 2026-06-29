# SPA — what we are, and what we aren't (honest one-pager)

_Auto-generated, REALIZED-ONLY, HONEST. The honesty IS the moat: a funder trusts the desk that names its own gaps. Every performance number below traces to a REALIZED `data/` source or is labeled INSUFFICIENT_DATA; NO backtest figure is presented as realized; NO claim exceeds the evidence. stdlib-only, deterministic, fail-CLOSED._

> **One line:** the **machinery** (measurement, refusal, proof, a public verifier) is world-class and reproducible today. The **realized edge** is still maturing and is INSUFFICIENT_DATA at this track depth — and it compresses at scale. The **business** ($10M/yr) is owner-gated off-code (capital / custody / audit / legal). We do not claim the edge is proven, and we do not claim $10M is reachable today.


---

## 1. What is genuinely world-class (machinery, not returns)

These are claims about the **engine and its proofs** — independently checkable, not performance assertions:

- **Measurement** — a deterministic, fail-CLOSED, LLM-forbidden fair-value engine that prices tokenized yield by subtracting structural haircuts (peg / liquidity / protocol / oracle / funding) and measures on-chain liquidation-NAV vs marketing-NAV from free data.
- **Refusal** — a refusal-first gate composed *under* the global RiskPolicy (only ever stricter). It REFUSES yield that is tail-risk compensation (the ezETH / over-levered-USDe pattern), and it publishes what it refused and why: a hash-linked, tamper-evident decision log of **718** decisions (**296 refusals**, of which **162** structural tail-vetoes, and **422 entries**).
- **Proof** — every decision (entry AND refusal), the exit-NAV-by-size schedules, the evidenced equity track, the tournament rankings and the RWA-NAV points are hashed into tamper-evident chains. "What we refused" is a public surface no competitor publishes.
- **A public, zero-dependency verifier** — `scripts/verify_spa.py` lets a skeptical third party re-derive every published hash AND every realized fundability number from the raw series on a clean machine with none of our code: **"don't trust us, check us."**


---

## 2. What is still maturing (the realized edge — honest, sourced)

- **Track depth:** **8/30 evidenced days** — accruing, not yet 30 (anchor 2026-06-22, target 2026-07-21). Go-live: **27/29 pass** — NOT READY; the remaining blockers are time-gated (track days to accrue), nothing to fix in code.

- **Realized edge vs the RWA floor (3.18%/yr):** of **11** forward sleeves, **0** beat the floor and **11** are **INSUFFICIENT_DATA** at this depth. The flagship FixedCarry carry book's realized carry-above-floor is **-247.38 bps** — i.e. **at-or-below the floor so far**. **We do NOT claim the desk beats the floor on realized data yet.** A thin track yields INSUFFICIENT_DATA with a null bps, never a fabricated 0.0.

- **Optimizer A/B (realized, `is_realized:yes`):** depth **1 day(s)**, verdict **INSUFFICIENT_DATA**. Apples-to-apples selection alpha to date: **+130.50 bps** — but a 1-day uplift is not an edge; the verdict stays INSUFFICIENT_DATA until the track matures.

- **The edge compresses at scale:** the optimizer's uplift is **+1.08pp at $100k** but goes to **-0.99pp** at the largest AUM tested (survives at max AUM: **no**; below the materiality bar by **$1,000,000**). The +1pp is a small-scale artifact that pool-capacity caps dissolve at fundable size. **At the size that underlies the $100M thesis, today's universe cannot support the edge.**


---

## 3. What is owner-gated / off-code (the path to $10M)

The code took each thesis to an honest verdict for free. But the same boundary appears everywhere — **the code can measure and refuse; the business is off-code.** Stated plainly, none of it buildable in read-only paper code:

- **Capital + relationships** — the carry edge is capacity-bound; $10M needs scale across many gated books, deeper pools, and AUM. Whitelisting / subscription access to redemption queues is a relationship, not a feature.
- **Custody / MPC** — institutional key management for real capital.
- **External audit** — independent code + controls audit of the execution path.
- **Legal** — fund structure, collateral perfection, redemption agreements, force-redemption rights; the RWA underwriting leg can only be *documented*, not *executed*, without it.


**On the cost of caution:** DEFENSIBLE while the realized carry track is thin/at-or-below floor — the gate is not yet demonstrably leaving real money on the table. — the gate's refusals are insurance against the tail (the ezETH / USDe-unwind pattern), defensible precisely because the realized carry does not yet beat the floor.


---

## 4. The honest bottom line

- **Genuinely world-class, today:** the measurement + refusal + proof engine and its public, zero-dependency verifier. Reproduce every number yourself: `python3 scripts/verify_spa.py --check-fundability data/`.
- **Still maturing:** the realized edge is INSUFFICIENT_DATA at this track depth and is at-or-below the floor so far; it compresses at scale. We name this gap rather than hide it.
- **Owner-gated:** capital, custody, audit, legal — the $10M is off-code. $0 real capital today.

_The product is not a return we promise; it is a measurement-and-refusal engine whose every claim a hostile reviewer can reproduce, and whose gaps we name first._


---

_Regenerated 2026-06-29 18:06 UTC. REALIZED-ONLY sources: `data/`carry_truth_table.json · realized_ab/realized_ab.json · edge_at_scale.json · refusal_cost.json · golive_status.json · rates_desk/decision_log.jsonl. Regenerable via `python3 scripts/generate_fundable_honest.py --md`. Companion sheet: `docs/FUNDABILITY.md`; reproduce the realized numbers: `python3 scripts/verify_spa.py --check-fundability data/`._
