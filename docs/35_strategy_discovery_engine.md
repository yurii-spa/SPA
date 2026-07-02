# 35 — Strategy Discovery Engine

**Purpose.** Define the desk's **continuous discovery** process: how new yield opportunities are found,
recorded as candidates, triaged, and — only after full due diligence and human approval — promoted into
the Yield Lab lifecycle as a Strategy Card. Discovery is deliberately *decoupled* from approval: finding
something is cheap and automatable; approving it is expensive, human-gated, and evidence-bound.

**No invented numbers.** Any concrete APY/TVL/utilization/funding figure a candidate carries is
`requires verification`; apparent yield is a *category* or a raw feed value labelled unverified. See
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md).

**Do not duplicate.** Discovery machinery already exists — this doc *formalizes and unifies* it:
- Risk-first pool screening + no-fork overlay → `spa_core/dfb/` (public `/board`).
- Live protocol APY/TVL discovery → `spa_core/adapters/defillama_feed.py` + `spa_core/adapters/`.
- Backtest→paper→live promotion ladder → `spa_core/tournament/tournament_engine.py`.
See [`02_current_architecture_audit.md`](02_current_architecture_audit.md) §2.

---

## 1. What to track (discovery signal surface)

The engine continuously scans these surfaces. Each surface feeds candidates; a signal is **never** an
approval — it is an input to the Candidate Record (§2).

| Signal | Where / source | What a change signals |
|---|---|---|
| **DeFiLlama yields** | `defillama_feed.py` (TTL-cached) | New/rising pool APYs across chains |
| **Protocol APY changes** | adapters + feed deltas | Rate moves, utilization shifts, new markets |
| **Morpho vaults** | vault registry / curator config | New curated vaults; curator/allocation changes |
| **Pendle markets** | Pendle market data (incl. expired history) | New PT/YT maturities, implied-rate dislocations |
| **Ethena rates** | sUSDe rate + collateral feed | Basis/funding regime for the synthetic-stable class |
| **Lending utilization** | on-chain reserve utilization | Borrow-demand strength; withdrawal-freeze risk |
| **Funding rates** | 5-venue funding feed (Binance/Bybit/OKX/KuCoin/Hyperliquid) | Basis/carry opportunity + regime |
| **Futures basis** | CEX/DEX basis feeds | Cash-and-carry entry conditions |
| **Borrow/supply imbalances** | per-market supply vs borrow | Spread/looping conditions; rate-inversion warning |
| **RWA yields** | `data/rwa_feed.py` (tokenized T-bills) | The moving floor every candidate must beat |
| **Tokenized credit** | issuer disclosures (opaque) | Private-credit opportunities (legal-gated) |
| **New launches** | protocol/token/market launches | Fresh mechanisms — highest scrutiny, lowest trust |
| **Incentive campaigns** | emissions/points programs | Subsidy (flag as incentive, not yield) |
| **Governance** | on-chain proposals / forum | Rate changes, cap changes, risk-parameter shifts |
| **Revenue / TVL trends** | `spa_core/dfb/` trends + feed history | Sustainability of a pool's fee/borrow base |
| **Exploit / news** | security feeds, incident reports | Kill/avoid signals for held or candidate protocols |
| **On-chain flows** | large deposits/withdrawals | Liquidity migration, whale concentration |
| **Regime changes** | rate/vol/funding regime detectors | Whether funding/basis strategies are even viable |
| **CEX funding** | CEX funding history | Off-chain leg conditions for basis/carry |
| **OTC** | counterparty desks (off-code) | Bilateral opportunities (relationship-gated) |

**Discipline.** A high `apparent_yield` from any surface is a *reason to investigate*, never a reason to
allocate. New launches and opaque/off-code surfaces (credit, OTC) start at maximum suspicion.

---

## 2. Strategy Candidate Record

Every discovered opportunity is written as a Candidate Record. It is a *research artifact*, explicitly
**not** a Strategy Card and **not** an approval. Concrete numbers `requires verification`.

| Field | Content |
|---|---|
| `candidate_id` | Stable unique id. |
| `source` | Which discovery surface (§1) surfaced it. |
| `discovered_at` | Timestamp of first observation. |
| `strategy_type` | Category from doc 33 / doc 38 (e.g. curated-vault, fixed-carry, basis, LP). |
| `assets` | Stablecoin(s)/BTC/ETH involved. |
| `protocols` | Protocol(s) touched (each needs a Protocol Card before promotion). |
| `chains` | Chain(s) of execution. |
| `apparent_yield` | Raw observed feed value — labelled unverified; category only for public reference. |
| `suspected_yield_source` | Which of the five buckets (doc 33 §0): borrow / tail-comp / basis-funding / incentive / real-economic. |
| `required_due_diligence` | The specific reviews still owed (protocol, stablecoin, curator, liquidity, red-team). |
| `first_risk_flags` | Immediate concerns (leverage, opacity, depeg history, incentive-dependence, thin depth). |
| `capacity_guess` | Rough deployable size + the binding constraint (method, not invented number). |
| `liquidity_guess` | Rough exit liquidity + expected slippage at tier (method). |
| `initial_product_line_fit` | Preserve / Core / Enhanced / Max / Experimental (tentative). |
| `initial_capital_tier_fit` | Smallest tier where it plausibly works ([`34`](34_capital_tiers_strategy.md)). |
| `required_data_sources` | Feeds needed to verify the yield (must be reproducible by our code). |
| `next_action` | One concrete next step (verify feed / write protocol card / red-team / reject / paper-test plan). |

---

## 3. The promotion rule (hard gate)

**No candidate becomes an approved Strategy Card without, in order:**

1. **Yield-source verification** — the suspected bucket (doc 33 §0) is *confirmed* by a reproducible,
   schema-checked, freshness-checked data source (evidence level ≥ L2, [`37`](37_apy_realism_and_evidence_standard.md)).
2. **Protocol review** — a Protocol Card (exploit history, oracle design, governance, upgradeability).
3. **Stablecoin review** — a Stablecoin Card ([`38`](38_stablecoin_yield_engine.md) §2) for every stable involved.
4. **Liquidity review** — depth + exit path + slippage at the intended capital tier.
5. **Risk review** — Risk Scoring v2 (advisory) sub-scores; hard-reject / human-review triggers.
6. **Red-team review** — mandatory for Enhanced/Max/Experimental/leverage/credit/counterparty/basis/
   opaque/new-stablecoin/lockup/options; must answer the doc-33 red-team questions.
7. **Paper-test plan** — a concrete plan to run it (or a documented reason it cannot be paper-tested).
8. **Human approval** — the owner/IC signs off. No LLM and no automated score approves a strategy.

A candidate failing any step is either **rejected** (recorded — refusals are first-class evidence) or
**held** at candidate status with `next_action` updated. Promotion is one Yield-Lab lifecycle step at a
time (idea → research → paper_testing → …, [`06`](06_spa_core_invariants.md) §E-16) — never a jump
straight to a fundable claim.

---

## 4. How this connects to the existing desk

- **`spa_core/dfb/`** already screens the pool universe risk-first and publishes a `/board`; it is the
  primary automated feeder of raw candidates. Discovery should *emit Candidate Records from* dfb output,
  not re-implement pool screening.
- **`spa_core/adapters/defillama_feed.py`** + adapters are the reproducible feeds that satisfy step-1
  yield-source verification (L2). A candidate whose yield cannot be pulled by our own code cannot pass.
- **`spa_core/tournament/tournament_engine.py`** is the backtest→paper→live promotion ladder; an approved
  Strategy Card enters *its* pipeline for L3+ evidence. Discovery ends where the tournament begins.
- **`spa_core/redteam/`** supplies the step-6 red-team machinery.

The engine's job is only the front of the funnel — surface, record, triage, and refuse — so that by the
time anything reaches the tournament or the paper track, it already carries verified yield-source,
protocol/stablecoin/liquidity/risk/red-team review, a paper-test plan, and a human signature.
