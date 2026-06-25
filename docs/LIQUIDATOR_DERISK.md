# Cross-Domain / Balance-Sheet Liquidator — cheap read-only de-risk (thesis #3)

**Status:** research de-risk per §8 (first-cheap-test) + Alt-1 of the thesis. NOT a live trading
book, NO capital, NO custody, NO CEX execution. Pure read-only compute over the keyless DeFiLlama
`/pools` surface. stdlib-only, deterministic, fail-CLOSED, LLM-forbidden.

**Module:** `spa_core/strategy_lab/liquidator/` (`market_monitor.py`, `opportunity_estimator.py`).
**Tests:** `spa_core/tests/test_liquidator.py` (16, green).

---

## The thesis (restated)

Be the **delta-neutral, balance-sheet liquidator** for long-tail / nested collateral on isolated
lending (Morpho Blue / Euler V2). When atomic single-block MEV bots **fail** — illiquid collateral
in a crash that can't be routed through a DEX in one tick — clear the bad debt with a balance
sheet, hedge the price risk via perps, and unwind the nested collateral over hours/days. Capture
the liquidation penalty + OEV the MEV bots can't.

The cheap test measures the **opportunity SIZE** read-only. The CEX-execution + custody +
balance-sheet legs are **OUT OF SCOPE / deferred** (exactly as the rates-desk brief defers its CEX
hedge leg).

---

## What we built (read-only, our stack)

1. **`market_monitor.py`** — indexes every Morpho Blue + Euler V2 market on DeFiLlama `/pools`
   (784 rows live), recording `{protocol, chain, symbol, tvl, supply_apy, exposure,
   underlyingTokens}` and **classifying the collateral kind** (vanilla stable / vanilla ETH /
   vanilla BTC / **LRT** / **PT** / **LP** / **exotic** / unknown) deterministically off the symbol
   + DeFiLlama's `exposure` and `stablecoin` flags. Long-tail = LRT, PT, LP, exotic, unknown — the
   kinds where atomic-MEV liquidation breaks. Fail-CLOSED: an unclassifiable symbol → UNKNOWN →
   treated long-tail/illiquid.

2. **`opportunity_estimator.py`** — per market, estimates the **annual addressable penalty $** and
   gates it on the **EXIT GAP**, reusing `rwa_backstop/liquidation_nav.py`'s constant-product
   slippage + DEX-discovery primitives (one source of truth):
   - `borrowed_usd ≈ tvl × BORROW_SHARE[kind]` (documented; RPC-gated real value)
   - `annual_liquidated = borrowed × ANNUAL_LIQ_TURNOVER[kind]` (documented per-kind)
   - `gross_penalty = annual_liquidated × penalty_bps/1e4` (documented LIF per kind — Morpho's real
     LIF is a function of LLTV we don't have at the pool level)
   - **EXIT GAP:** `atomic_fill_frac(\$1M clip)` = realised DEX fill via the liquidation_nav
     slippage model against the collateral's aggregate public DEX depth. If `fill ≥ 0.985` →
     atomic-MEV handles it → **not our edge** (illiquid_share=0). Below → MEV bots stand down → the
     penalty is addressable to a balance-sheet liquidator (illiquid_share → 1, fully so when there
     is no qualifying DEX pool).
   - `addressable_penalty = gross_penalty × illiquid_share`.

---

## (a) How much addressable long-tail opportunity exists? — the numbers

Live DeFiLlama `/pools`, Morpho Blue + Euler V2, 784 markets, $9.9B aggregate TVL:

| metric | value |
|---|---|
| markets indexed | **784** |
| long-tail markets (LRT/PT/LP/exotic/unknown) | 275 |
| long-tail TVL | ~$1.66B (16.8% of TVL) |
| **GROSS** annual penalty pool (all markets) | **~$6.7M/yr** |
| **TOTAL ADDRESSABLE** (illiquid-gated) penalty | **~$3.8M/yr** |
| long-tail addressable | ~$3.6M/yr |
| **TOP-20 addressable** (the Alt-1 read) | **~$2.2M/yr** |

addressable by collateral kind: exotic ~$1.6M, unknown ~$1.2M, LP ~$0.85M, LRT ~$0.02M.

> **Alt-1 kill bar: the top-20 unsupported/illiquid markets must show ≥ $20M/yr gross
> penalty/recapture potential.** Observed top-20 ≈ **$2.2M/yr**; total addressable ≈ **$3.8M/yr**.
> Both are **~5–10× BELOW the bar.** **The edge is WEAK.**

### The single biggest honesty correction

A naive symbol-classification gave a **$18M** top-line — but that was an artifact. DeFiLlama
`/pools` for Morpho/Euler is **dominated by MetaMorpho curator SUPPLY VAULTS** (STEAKUSDC =
Steakhouse, GTUSDCP = Gauntlet, SENPYUSD, SYRUPUSDC, ETHENAUSDC…), which are **stable-denominated
deposit wrappers, not volatile collateral that gets liquidated.** They are flagged
`stablecoin=True`; using that flag to keep them out of the long-tail collapses the estimate from
$18M → **$3.8M**. Even the residual top markets (STEAKETH, AA-FALCONXUSDC, KPK-USDC-PRIME, PRIME)
are partly non-stable-flagged curator vaults, so **$3.8M is an UPPER bound** on the real
collateral-liquidation tail.

---

## (b) Honest data gaps — measurable now vs RPC-gated

**Measurable now from DeFiLlama `/pools` aggregates (what this module uses):**
- the market universe per protocol/chain, per-market **TVL**, supply APY, exposure (single/multi),
  underlyingTokens, and DeFiLlama's stablecoin flag;
- the **collateral kind** (legible from the symbol) → the long-tail vs vanilla split;
- the **on-chain DEX depth** for each collateral token (DEX-project pools on the same feed) → the
  **exit gap / atomic-fillability** — the genuinely informative, live-measurable signal here.

**NOT measurable from `/pools` — needs per-market / per-position RPC or subgraph indexing:**
- the **LLTV / liquidation incentive (LIF)** per market — null at the pool level for Morpho/Euler
  (we substitute documented per-kind penalties; real LIF = `min(1.15, 1/(0.3·LLTV+0.7))`);
- the **borrowed amount** per collateral market (`apyBaseBorrow`, totalBorrow null on `/pools`) — we
  proxy it as a documented share of TVL;
- the **at-risk (near-liquidation) positions** — the actual opportunity is positions whose health
  factor is approaching 1.0; that is a **per-borrower** read (subgraph/RPC of each market's
  borrowers + a live oracle price), **entirely absent** from any aggregate feed. Annual liquidation
  turnover is a documented assumption here, not a measurement.
- the **vault-vs-market disambiguation** — separating true isolated collateral markets from
  MetaMorpho curator vaults cleanly also needs the Morpho subgraph (the stablecoin flag is a proxy).

So: the **monitor + exit-gap are honestly live**; the **dollar opportunity is a documented-constant
estimate** whose precision is RPC-gated. The estimate is good enough to *bound* the opportunity and
the bound is well under the bar.

---

## (c) Go / No-Go

- **The read-only monitor/exit-gap (cheap):** ✅ **worth keeping** — it's built, green, costs one
  keyless call, and it already answered the question (and exposed the vault-classification trap).
  It can run as a periodic research probe; the exit-gap is the real, live-measurable signal.
- **Building per-position RPC/subgraph at-risk indexing (medium cost):** **NOT yet justified.** The
  aggregate bound is ~5–10× below the kill bar; per-position precision would refine a number that is
  already far on the wrong side of go/no-go. Defer unless the addressable pool grows materially
  (e.g. a large LRT/PT market expansion on Morpho/Euler).
- **The actual liquidator BUSINESS (expensive, deferred):** **NO-GO on the cheap test.** Even if
  built, it is gated on the expensive deferred legs — **custody + CEX/perp execution +
  balance-sheet capital + bad-debt underwriting** — and the addressable long-tail penalty
  (~$3.8M/yr GROSS across ALL of Morpho+Euler, contested by incumbent professional liquidators) does
  not clear the $20M Alt-1 bar that would justify standing up that infrastructure.

**VERDICT: NO-GO.** The cheap monitor is a keeper as a research probe; the long-tail liquidation
opportunity on Morpho Blue + Euler V2 is **too small (≈$2–4M/yr gross, well under the $20M bar)** to
justify the custody + CEX-execution + balance-sheet build. Honest bound, fail-CLOSED throughout.

*The $20M figure is the Alt-1 kill bar from the thesis; all dollar figures above are documented-
constant estimates gated by the live exit-gap, not realised PnL.*
