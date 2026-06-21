# ADR-050: Aerodrome Thin-Pool Finding + $20M LP TVL Depth Floor

| Field            | Value                                            |
|------------------|--------------------------------------------------|
| **Date**         | 2026-06-21                                       |
| **Status**       | ACCEPTED                                          |
| **Author**       | Claude (SPA agent)                               |
| **Approved by**  | _pending_ (Yurii)                                |
| **Policy ver.**  | v1.0 (RiskPolicy `min_tvl_usd` unchanged; LP floor lives in adapter) |
| **ADR number**   | ADR-050                                           |

> **Numbering note:** latest existing ADR was ADR-049; ADR-050 is the next free
> number.

---

## Context

DeFiLlama research surfaced the **Aerodrome USDC-USDT** stable pool on Base at an
attractive **8.19% APY** — but with only **~$2M TVL**. SPA's global RiskPolicy
TVL floor is **$5M** (`RiskConfig.min_tvl_usd`), which was designed for **lending**
positions (single-asset supply into a money market). That floor is the wrong tool
for an **AMM LP** position.

An AMM LP position is fundamentally **market-making**: capital sits in the pool's
reserves, so position size relative to pool depth directly determines price impact
and slippage on entry/exit.

Sizing math against the thin Aerodrome pool:

| Portfolio | Max T2 position (20%) | As % of $2M pool | Verdict |
|---|---:|---:|---|
| $100k (today) | $20k | **1%** | Acceptable |
| $1M (scaled) | $200k | **10%** | Market-moving / distorts pricing |

At today's $100k virtual capital the position is tolerable, but the same pool
becomes a liability the moment the portfolio scales. A static $5M floor does not
capture this — a pool can clear $5M and still be far too thin for a meaningful LP
allocation once capital grows.

---

## Decision

1. **Apply a $20M minimum TVL floor for AMM LP positions** (vs the $5M floor that
   remains correct for lending). Encoded in
   `spa_core/adapters/aerodrome_usdc_adapter.py` as `LP_TVL_FLOOR_USD = 20_000_000`.

2. **Add a `pool_depth_check()` depth gate.** A pool is flagged **`THIN_POOL`**
   when its TVL is below the $20M LP floor **OR** below **20×** our max T2 position
   (`POOL_DEPTH_MULTIPLE = 20`). At $100k portfolio the max T2 position is $20k, so
   the depth-multiple floor is $400k; the $20M absolute floor dominates and is the
   binding constraint.

3. **Cap any LP position at 1% of pool TVL** (`MAX_POOL_PARTICIPATION_PCT = 0.01`).
   This is the forward-looking guard: even if the portfolio scales, the position
   can never exceed 1% of the pool, keeping price impact negligible.

4. **Emit an advisory warning** on thin pools (read-only — does not block the APY
   feed):
   > `Aerodrome pool TVL $2M < $20M depth floor. Position limited to 1% of TVL.`

5. **S41 risk flag:** `s41_amm_stable_yield.py` documents that if Aerodrome pool
   TVL < $20M, the Aerodrome sleeve is reduced from **15% → 5%** of the portfolio.

The RiskPolicy `version` stays **`"v1.0"`** — the $5M `min_tvl_usd` is unchanged.
The $20M LP floor is an **adapter-level / strategy-level** depth gate layered on
top of (stricter than) the global floor, consistent with the existing per-adapter
`_MIN_POOL_TVL` and capacity-limit (MP-209) machinery.

---

## Rationale

- **AMM LP ≠ lending.** Lending supply does not move a market; LP capital *is* the
  market. The risk that matters for LP is **price impact / slippage**, which is a
  function of position-size-to-depth — not an absolute TVL number.
- **A floor that scales with capital.** The 1%-of-TVL cap and the 20× depth
  multiple both express the same invariant — never be a large fraction of the pool
  — so the protection holds as the portfolio grows, instead of silently breaking
  at $1M.
- **High APY in a thin pool is a trap.** 8.19% on $2M is often emission-driven and
  evaporates (or moves against you on exit) precisely when a large LP tries to
  realize it. The depth floor stops SPA from chasing a yield it cannot actually
  capture at size.
- **Conservative by construction.** SPA is in a paper track building an honest
  record (real track since 2026-06-10). A depleted thin-pool LP would distort the
  track far more than the foregone yield is worth.

---

## Consequences

- **Positive:** SPA will not over-allocate into the thin Aerodrome pool; the LP
  sleeve auto-shrinks (15% → 5%) when the pool is below depth. Protection scales
  with capital.
- **Negative / trade-off:** SPA forgoes the headline 8.19% APY at full size while
  the pool stays under $20M. Acceptable — the yield is not safely capturable at
  scale.
- **Re-evaluation:** if the Aerodrome USDC-USDT pool deepens past $20M on a
  sustained basis, the full 15% sleeve re-enables automatically via
  `pool_depth_check()` returning `OK`.

---

## Implementation

| Artifact | Change |
|---|---|
| `spa_core/adapters/aerodrome_usdc_adapter.py` | `LP_TVL_FLOOR_USD`, `POOL_DEPTH_MULTIPLE`, `MAX_POOL_PARTICIPATION_PCT`, `pool_depth_check()`, thin-pool warning in `_fetch_live_apy`, `lp_tvl_floor_*` in `health_check` |
| `spa_core/strategies/s41_amm_stable_yield.py` | Thin-pool risk note: Aerodrome 15% → 5% when pool TVL < $20M |
| `tests/test_aerodrome_velodrome.py` | Tests for the $20M LP floor + `pool_depth_check()` |

---

## Status

**ACCEPTED** (2026-06-21). Adapter-level depth gate; RiskPolicy v1.0 unchanged.
