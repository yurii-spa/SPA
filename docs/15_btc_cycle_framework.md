# 15 — BTC Cycle Framework (§14)

> **DECISION-SUPPORT ONLY — NOT AUTO-TRADING.** This is the **analytical companion** to
> [`36_btc_capital_cycle_machine.md`](36_btc_capital_cycle_machine.md). It defines *how* the desk
> **detects** a BTC cycle phase, *how* it scores confidence, and *how* it reasons about BTC allocation
> and BTC yield — as **research and recommendation** for a human, never as an execution engine. It
> holds no keys, signs nothing, moves no funds, and never overrides the deterministic RiskPolicy or the
> two-tier kill-switch ([`06_spa_core_invariants.md`](06_spa_core_invariants.md), ADR-YL-007).
> Default autonomy = L0/L1.
>
> **No invented numbers.** Every metric level, band, APY, TVL, and price below is a *category or
> method* marked `requires verification` / `source TBD`. The desk never presents an unverified number
> as fact ([`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)).

**Purpose.** Where [`36`](36_btc_capital_cycle_machine.md) is the *playbook* (8 phases, what to do),
this file is the *analysis*: the detection method, the metric families and how they are combined, the
confidence-scoring method, BTC allocation bands, BTC risk controls, and an honest treatment of every
BTC yield option and its risks — including **when pure cold storage beats yield**.

**Not a duplicate of `bull_cycle_detector`.** SPA's deterministic
[`bull_cycle_detector`](../spa_core/strategies/bull_cycle_detector.py) (ADR-018) classifies the
**DeFi-yield APY regime** to set tier caps. This framework classifies the **BTC price/capital cycle**.
They answer different questions and can be read together (a yield-BULL regime often — not always —
overlaps early/mid BTC-bull phases). Any future BTC-cycle detector must inherit `bull_cycle_detector`'s
determinism, fail-safe-NEUTRAL default, and atomic-write discipline, and must stay **advisory**.

---

## 1. Cycle-phase detection (method, not thresholds)

Phase detection is a **confluence classifier over metric families**, not a single-metric trigger. The
method:

1. **Pull** each metric from a verified, freshness-checked feed (`requires verification / source TBD`).
2. **Normalize** each into a position-within-history band (e.g. percentile / z-score vs its own
   cycle history) — never an absolute hardcoded level.
3. **Group** by family (valuation, derivatives, on-chain behavior, macro, sentiment).
4. **Classify** the phase (one of the 8 in [`36`](36_btc_capital_cycle_machine.md)) by the *agreement*
   across families — a phase is asserted only when multiple families concur.
5. **Fail safe.** On stale/missing/contradictory data, default to the **least-action** classification
   and **lower confidence** — never assert a high-conviction phase from thin data.

The 8 phases (accumulation → recovery → early bull → mid bull → euphoria → distribution → early bear →
capitulation) and their behavioral playbook live in [`36`](36_btc_capital_cycle_machine.md); this file
does not restate them.

---

## 2. Metric families (all `requires verification` / `source TBD`)

### 2.1 Valuation / on-chain
- **MVRV** — aggregate unrealized P/L; extreme-high band = distribution/euphoria risk, low band =
  accumulation zone.
- **NUPL** — net unrealized P/L; historically banded into fear→euphoria zones.
- **Realized price** — aggregate cost basis; price *below* it = capitulation zone.
- **LTH behavior** — long-term-holder supply/spending; rising = accumulation, falling = distribution.
- **Exchange reserves** — BTC on exchanges; falling = withdrawal to cold (bullish supply), rising =
  sell-pressure.

### 2.2 Derivatives
- **Funding rate** — leverage/positioning bias; sustained extreme-positive = froth.
- **Open interest (OI)** — leverage build-up; OI rising while price stalls = fragility.
- **Options skew** — downside vs upside protection demand; put-skew = fear, call-skew = greed.

### 2.3 Flows & liquidity
- **ETF flows** — institutional demand pulse (net creations/redemptions).
- **Stablecoin supply** — aggregate sidelined dry powder.
- **Macro liquidity** — net-liquidity proxy; risk-asset tailwind/headwind.

### 2.4 Macro
- **DXY** — dollar strength, inverse risk-appetite proxy.
- **Rates** — front-end / real yields; also sets the **RWA-floor** competition for idle stables.

### 2.5 Sentiment
- **Sentiment index** (fear/greed) and **search trends** — crowd-positioning extremes; contrarian at
  the tails.

> **Availability caveat.** Each metric's feed, cadence, and history depth is `requires verification`.
> A metric with stale or shallow history is **down-weighted**, not trusted at face value.

---

## 3. Confidence scoring (method)

The framework attaches a **confidence score** to every phase classification. It is a documented
*method*, not a live number:

- **Metric agreement** — how many families concur on the same phase (more agreement → higher
  confidence).
- **Data freshness** — stale feeds cut confidence.
- **History depth** — thin history (few cycles / short series) caps confidence.
- **Metric dispersion** — contradictory readings across families lower confidence.

**Consequences of confidence** (this is the safety coupling):
- **Low confidence** → smaller, slower recommended moves; more human review; bias to HOLD.
- **High confidence** → still staged, ladder-based moves; **never** an all-at-once action.
- Confidence **never** unlocks leverage, naked short-vol, or bypass of RiskPolicy/kill-switch.

> The confidence score is itself `requires verification` in its live weighting; it is advisory input to
> a human, not an automated trigger.

---

## 4. BTC allocation bands

Allocation is expressed as **directional bands per phase**, not fixed percentages, and always
subordinate to the deterministic RiskPolicy and cash-buffer minimum:

| Phase group | BTC bias | Stable bias | Notes |
|---|---|---|---|
| Accumulation / Recovery / Capitulation | **Building** (laddered up) | Drawing down (funds ladder) | Preferred zones to add; small tranches |
| Early / Mid Bull | **Hold core** (adds only on dips) | Restore/hold buffer | Mid-bull begins first profit rungs |
| Euphoria / Distribution | **Reducing** (profit ladder) | Rising to cycle-high | Primary distribution zones |
| Early Bear | **Hold core only** | High (RWA floor) | No adds; rebuild dry powder |

- A **long-term core** is distinguished from **discretionary size**; ladders act on discretionary size,
  the core is held through the cycle unless a structural break invalidates the thesis.
- Every band is a *recommendation*; a human approves the actual sizing (§6, and
  [`36`](36_btc_capital_cycle_machine.md) §4). Concrete band edges are `requires verification`.

---

## 5. BTC risk controls

- **No leverage** on the cycle position (any leverage request is denied).
- **Ladder discipline** — build and distribute in fixed-fraction tranches; never all-at-once; keep
  reserve for lower/higher rungs (cycles overshoot).
- **Cash-buffer minimum** always preserved (never deploy the buffer itself into a ladder).
- **Structural-break override** — a verified custody/exchange/protocol/oracle failure preserves capital
  and escalates, overriding phase logic (but never the RiskPolicy/kill-switch, which are already
  authoritative).
- **Wrapped-BTC risk overlay** — every wrapped-BTC yield mechanism carries bridge/custodian/governance
  risk *on top of* the yield ([`33_yield_thesis_map.md`](33_yield_thesis_map.md) B4). **WBTC excluded**
  (governance overhang, `requires verification`); **LBTC-restaking REFUSED** (points/airdrop-leverage).
- **Fail-safe default** — HOLD / do-nothing on ambiguous or stale data.

---

## 6. BTC yield options and their risks

Honest treatment, consistent with [`33_yield_thesis_map.md`](33_yield_thesis_map.md) Domain B — "yield
on BTC" is mostly small or tail-compensation:

| Option | Yield source | Category | Key risks | Posture |
|---|---|---|---|---|
| **Lending** (tbtc/cbbtc) | Borrow demand for BTC | Preserve (**~0%**, `requires verification`) | Low utilization → ~0 APY; contract/custody risk | Advisory read-only adapters exist; honest ~0% |
| **Wrapped-BTC / BTCFi** | Various (lending/LP/restaking on wrapped BTC) | n/a — **risk multiplier** | Bridge exploit; custodian insolvency; governance capture; de-peg | Only via **vetted custody**; WBTC excluded, LBTC-restaking REFUSED |
| **Options / covered calls** | Option premium (short upside) | Enhanced (premium-dep.) | **Caps upside in a rally**; short-vol tail; assignment; venue/counterparty | **REFUSE naked**; overlay-only on held BTC, decision-support, human-approved |
| **Basis / cash-and-carry** | Spot–future basis, delta-neutral | Core → Enhanced | Basis compression; funding flip; **CEX-leg custody/legal gated, off-code** | Decision-support only; isolated; red-team required |
| **Custody (cold storage)** | **None** (no yield) | n/a | Self-custody operational risk | Often the correct answer — see §7 |

Every yield option is subordinate to the deterministic RiskPolicy and the two-tier kill-switch and may
**never** be auto-executed by this framework.

---

## 7. When pure cold storage beats yield — and when not to chase BTC yield

**Cold storage (zero yield) is the right choice when:**
- The incremental yield is **~0** or is **tail-compensation** you cannot underwrite (most on-chain BTC
  lending, `requires verification`).
- The yield requires **wrapping** BTC into a bridge/custodian/governance-risk asset for a few basis
  points — the risk dwarfs the reward.
- The desk is in **Euphoria / Distribution / Early Bear** and wants BTC **risk-off**, not
  rehypothecated.
- Counterparty, venue, or custody risk is unquantified or the feed is `requires verification` with no
  reproducible source.

**Do not chase BTC yield when:**
- The excess APY over cold storage is **compensation for depeg/liquidation/funding-reversal/counterparty
  risk** rather than real economic return (the core honesty test in
  [`33_yield_thesis_map.md`](33_yield_thesis_map.md) §0).
- Doing so requires **leverage** or **naked short-vol** (both forbidden here).
- It would put the **long-term cycle core** at principal risk to earn a small carry.

**Yield may be considered (decision-support, human-approved) when:** it is real borrow-demand or real
economic yield through **vetted custody**, isolated, red-team-cleared, RiskPolicy-capped, and it does
not impair the cycle thesis. Even then, it is a *recommendation*, not an automated action.

---

## 8. Cross-references

- Phase playbook (identification, allocation behavior, ladders, forbidden actions per phase):
  [`36_btc_capital_cycle_machine.md`](36_btc_capital_cycle_machine.md).
- Yield-source honesty for BTC mechanisms: [`33_yield_thesis_map.md`](33_yield_thesis_map.md) Domain B.
- Deterministic yield-regime detector (complementary): ADR-018 /
  [`bull_cycle_detector`](../spa_core/strategies/bull_cycle_detector.py).
- Evidence discipline: [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md).
- Invariants: [`06_spa_core_invariants.md`](06_spa_core_invariants.md).

---

*Decision-support / analytical framework, advisory only. Not auto-trading (ADR-YL-007). No private
keys, no signing, no fund movement, no override of RiskPolicy or kill-switch. All metric/APY/price/TVL
values are categories or method descriptions marked `requires verification` — none is a live figure.*
