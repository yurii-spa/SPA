# 37 — APY Realism & Evidence Standard

> **Canonical (ADR-YL-009).** This is the **CANONICAL** definition of evidence levels **L0–L6**. Other docs use the tags; none re-defines them.

**Purpose.** This document defines the discipline that prevents the desk from ever presenting a yield
number it has not earned the right to claim. It codifies (1) **evidence levels L0–L6**, (2) the **APY
taxonomy** (advertised vs observed vs executable vs net vs sustainable vs risk-adjusted), (3) the
**per-strategy evidence record** every strategy must carry, and (4) the **hard claim rules**.

This is the operationalization of the charter's rule: *never claim APY without an evidence level;
distinguish advertised / observed / executable / net / sustainable / risk-adjusted; never present
paper or backtest as live; never show APY without risk category, source, last-verified date, and a
yield-source explanation.* See [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md)
§§ APY-evidence and [`06_spa_core_invariants.md`](06_spa_core_invariants.md) §C.

**No invented numbers.** This document defines *how* numbers must be qualified. It contains no live
APY/TVL values; any example is written `requires verification`.

---

## 1. Evidence levels L0–L6

Each level has **entry criteria** (what must be true to claim it) and a **claim permission** (what you
are allowed to say once at it). A strategy may never be described at a level above the evidence it holds.

| Level | Name | Entry criteria | Permits claiming |
|---|---|---|---|
| **L0** | Idea / unverified | A hypothesis exists. No data checked. | "Candidate idea." **No APY may be quoted**, even a range. |
| **L1** | Historical public APY observed | A public historical APY series has been *observed* (screenshotted / logged) from a named source. | "Historically, source X showed a range Y (`requires verification`)." Must label as *historical, unverified as executable*. |
| **L2** | Data-source verified | The data source is reproducibly pulled by our own code, schema-checked, freshness-checked, cross-checked where possible. | "Observed APY from a verified feed, last-verified DATE." Still not tradable-verified. |
| **L3** | Paper-tracked | The strategy runs in the paper harness against live data for a real, continuous, cycle-log-backed period. Only real daily-cycle days count (no backfill/warmup). | "Paper-tracked over N evidenced days." **Must say "paper", never "live".** |
| **L4** | Small-capital tested | Executed with real but small capital; execution frictions (slippage, gas, fills) observed. | "Small-capital tested; executable net APY observed at size S (`requires verification`)." |
| **L5** | Live-capital tested | Executed at meaningful (product-tier) capital through at least one full entry/exit. | "Live at capital tier T; net executable APY observed." |
| **L6** | Multi-cycle validated | Survived multiple market regimes / cycles at live capital, including at least one stress episode. | "Multi-cycle validated." The only level that supports a durable claim. |

**Promotion is one level at a time.** No strategy jumps L2 → L5. Each promotion requires the evidence
record (§3) updated and, for Enhanced/Max/Experimental, a Red Team pass
([`33_yield_thesis_map.md`](33_yield_thesis_map.md) red-team columns).

**L3 exemplar — SPA's evidenced track.** The paper trade track already embodies L3 done honestly:
only real daily-cycle-log-backed days count as *evidenced*; backfilled, reconstructed, warmup, or demo
bars are excluded and explicitly labelled. `golive_checker.py` (29 criteria) and the gap monitor
enforce continuity. This is the reference implementation of "paper-tracked" — a strategy is at L3 only
if its track has the same honesty property (real cycle-log days, no reconstruction).

---

## 2. APY taxonomy — six distinct numbers

The single word "APY" hides six different quantities. Every quoted number must state *which one* it is.
They descend from most flattering to most honest; the desk markets on the honest end.

| Term | Definition | Typical relation | Trap it prevents |
|---|---|---|---|
| **Advertised APY** | The headline number a protocol/UI shows. | Highest | Marketing a UI number as real return. |
| **Observed APY** | What our verified feed actually measured over a window. | ≤ advertised | Assuming the headline held. |
| **Executable APY** | What we could actually enter at, given depth/queue/entry price. | ≤ observed | Ignoring capacity/entry slippage. |
| **Net APY** | Executable minus fees, slippage, gas, hedge cost, roll cost. | ≤ executable | Quoting gross as take-home. |
| **Sustainable APY** | Net, after stripping non-recurring incentives/points and after capital-compression at our size. | ≤ net | Treating a subsidy or thin-depth spike as durable. |
| **Risk-adjusted APY** | Sustainable APY judged against the risk taken and the **RWA floor** benchmark (≈3.4% `requires verification`). | Context-dependent | Rewarding yield that is merely tail-comp. |

**Rule of the funnel:** a strategy is only interesting if its *risk-adjusted sustainable net executable*
APY beats the floor by a margin that survives stress. The desk's audited honesty is that most
candidates do **not** clear this funnel at fundable scale — say so.

---

## 3. Per-strategy evidence record (mandatory fields)

Every strategy card must carry this record. Missing a field = the strategy cannot be promoted past its
current level, and its APY may not be shown publicly.

| Field | Requirement |
|---|---|
| Current observed APY | The verified observed number (or "none — not yet L2"). Category, plus value only if L2+ and `requires verification` where concrete. |
| Historical range | Observed historical band with window + source (L1+). |
| Source | Named data source(s) for every number. |
| Sustainability estimate | Explicit judgment of how durable the yield is (which bucket from doc 33 §0). |
| Confidence | Low / Medium / High, justified. |
| Data source freshness | Feed cadence + staleness handling. |
| Last-verified date | Date the numbers were last confirmed. **Required on every public APY.** |
| Base-vs-incentive split | How much is real yield vs emissions/points subsidy. |
| Capital-compression flag | Does APY fall as we add size? By how much (method, not invented number)? |
| Leverage-dependency flag | Does the APY require leverage? What is the liquidation surface? |
| Counterparty-dependency flag | CEX / custodian / issuer / bridge dependencies. |
| Regime-dependency flag | Does it rely on bull-regime funding / positive basis / high rates? |
| Evidence level | Current L0–L6, with the date of last promotion. |
| Yield source | The plain-language "who pays and why" from doc 33. |
| Risk category | Preserve / Core / Enhanced / Max / Experimental. |

A public surface may render an APY **only** if the record has: risk category **and** last-verified date
**and** yield-source explanation **and** an evidence level of **L2 or higher**.

---

## 4. Hard rules (non-negotiable)

These are enforcement rules, not guidelines. They align with
[`06_spa_core_invariants.md`](06_spa_core_invariants.md) §C.

1. **Never market an unverified APY.** Below L2, no APY number reaches any public or investor surface —
   not even a range.
2. **Never call paper "validated" or "live-tested."** Paper is L3 and must be labelled "paper." A
   backtest is *not* live-tested; a backtest is evidence toward L1/L2 at most, never L4+.
3. **Never show APY without all three:** (a) risk category, (b) last-verified date, (c) yield-source
   explanation. A number without these is forbidden on every surface.
4. **Never present advertised as observed, observed as executable, or gross as net.** Always name which
   of the six taxonomy numbers is being shown.
5. **Never hide the base-vs-incentive split.** Subsidy-driven APY must be labelled as subsidy and its
   sustainable (ex-incentive) figure shown alongside.
6. **Never quote an APY that ignores capital-compression at our tier.** If size moves the rate, the
   compression must be disclosed (method per [`34_capital_tiers.md`](00_index.md) when written).
7. **The risk-adjusted benchmark is the RWA floor.** Any Enhanced/Max claim must be stated *relative to*
   the floor and *after* stress, or it is not stated at all.
8. **Downgrade on staleness.** If a strategy's last-verified date ages past its freshness window, its
   effective claimable level drops until re-verified (fail-closed).
9. **Red Team gates promotion for Enhanced/Max/Experimental/leverage/credit/counterparty/basis.** No
   promotion to a fundable claim without the red-team questions in doc 33 answered.
10. **No LLM in the evidence or risk path.** Evidence-level assignment and APY qualification are
    deterministic bookkeeping, consistent with the invariant that no LLM sits in the risk path.

---

## 5. How this connects to the rest of the desk

- **Yield source** for every number is defined in [`33_yield_thesis_map.md`](33_yield_thesis_map.md).
- **Risk category** comes from the product lines (Preserve/Core/Enhanced/Max/Experimental).
- **L3 honesty** is exemplified by the existing evidenced paper track (`paper_trading/cycle_runner.py`,
  `golive_checker.py`, gap monitor) — real cycle-log days only.
- **Refusal-first discipline** (the desk documents *refusals* as first-class evidence, hash-chained)
  lives in `spa_core/strategy_lab/rates_desk/` and `spa_core/redteam/`; a REFUSE is itself a validated
  finding, recorded, not hidden.

The standard is deliberately strict so that when the desk *does* make an APY claim, the claim is
boring, verifiable, and true.
