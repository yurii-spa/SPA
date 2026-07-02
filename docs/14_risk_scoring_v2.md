# 14 — Risk Scoring v2 (Advisory) (§21)

> **ADVISORY ONLY.** Risk Scoring v2 is a decision-support scorecard. It **never** replaces the
> deterministic RiskPolicy (`spa_core/risk/policy.py`, `version: v1.0`), which remains the sole hard
> execution gate. It is **never** wired to execution, allocation, or the kill path (ADR-YL-004,
> `docs/06` invariant 17). No LLM sits in the scoring path. It **composes UNDER** the RiskPolicy —
> only ever stricter, never looser.

**Status:** research-layer documentation. No runtime code, RiskPolicy, dashboard, deploy, or existing
files are modified by this document. **Numbers here are weights/thresholds for a scoring MVP — not
APY/TVL claims.** APY/TVL used as inputs must be real and evidence-levelled (`docs/37`); unknown
inputs are `TBD — requires verification`.

Cross-references: `docs/11_strategy_card_system.md` (cards carry these scores), `docs/06_spa_core_invariants.md`
(invariants A.1–A.4, 17), `docs/37_apy_evidence_standard.md` (evidence levels), `docs/34` (capital tiers).

---

## 1. What this is, and what it is not

Risk Scoring v2 turns a Strategy Card into a set of **0–100 advisory sub-scores** plus one advisory
overall risk score and one advisory allocation score. Its outputs:

- **inform** human reviewers and Strategy Cards (which fields to fill, where to focus red-team);
- **trigger** advisory actions — human review, red-team, or an advisory emergency-exit flag;
- **compose under** the RiskPolicy — a strategy the advisory layer likes but the RiskPolicy rejects
  is **rejected** (the hard gate wins); a strategy the advisory layer flags but the RiskPolicy would
  allow is still **held back** by the advisory human-review trigger. The advisory layer can only
  make the desk *more* cautious, never less.

It is **not** an allocator, **not** a kill-switch, **not** a hard gate, and **not** a replacement for
the deterministic RiskPolicy or the two-tier kill (`docs/06` A.3). It writes advisory research output;
it never mutates runtime allocation or execution state.

### Score direction convention

Per this document, **higher = riskier** for every `*_risk_score` and for `overall_risk_score`
(so `red` = high number = worse). `yield_score`, `confidence_score`, and `allocation_score` follow
their own stated direction (see each). This is the opposite direction from the existing
`spa_core/risk/scoring_engine.py` convention (there higher = *safer*); Risk Scoring v2 **reuses** that
engine's sub-score computations and **inverts/rescales** them to the 0–100 risk-up convention for
presentation. See §4.

---

## 2. Reuse, don't reinvent (this is a formalization, not a new engine)

Per `docs/02`, the risk-scoring machinery already exists. Risk Scoring v2 is a **thin advisory
scorecard over existing modules**, not a new risk model:

| Existing module | Reused for |
|---|---|
| `spa_core/risk/scoring_engine.py` (ADR-014: 15 deterministic sub-scores in [0,1], A/B/C/D, weight vector summing to 1.0, offline-tolerant, LLM-forbidden) | the protocol/smart-contract/oracle/bridge/liquidity/regulatory/concentration sub-scores. Risk Scoring v2 maps its `[0,1]` "higher = safer" outputs onto the `[0,100]` "higher = riskier" advisory scale; it does not re-derive them. |
| `spa_core/dfb/risk_overlay.py` (NO-FORK per-pool verdict: refusal + structural haircut + exit-liquidity-by-size + risk_class A/B/C/D + engine_proof_hash) | `liquidity_risk_score` (from exit-liquidity-by-size), and the hard-rejection / red-team veto signals (the engine's structural veto). The overlay defines NO risk math of its own; neither does Risk Scoring v2. |
| `spa_core/strategy_lab/rates_desk/` (refusal-first fair-value gate, decision + refusal log) | `yield_sustainability_score`, and the refusal signal that maps to hard-rejection / red-team triggers. |
| `spa_core/strategy_lab/forward_analytics.py` (risk-adjusted scorecard vs the RWA floor + stress) | `market_regime_risk_score`, `black_swan_risk_score`, `correlation_risk_score` inputs. |

**Rule (NO-FORK, mirrors dfb):** Risk Scoring v2 **presents** existing engine outputs on a common
advisory scale. Any sub-score that an existing module already computes is **cited**, not recomputed
with new math. Where no existing module produces a value, the sub-score is filled from the Strategy
Card's qualitative fields by a documented deterministic mapping, and marked lower `confidence_score`.

---

## 3. The sub-scores

All sub-scores are `0–100`. For every `*_risk_score`, **higher = riskier**. Each row gives: meaning,
required inputs, a suggested **MVP weight** (relative; the MVP overall-risk aggregation normalizes
weights to sum to 1.0), green/yellow/red bands, and the trigger thresholds. **Weights are an MVP
starting point and may evolve** with evidence; changes are documented, not silent.

Trigger legend (all advisory):
- **hard-reject** = advisory recommendation to reject the card at this stage (still subordinate to the
  RiskPolicy hard gate — this never *permits* anything, only *forbids* advisory promotion).
- **human-review** = card cannot advance without a named human reviewer signing off.
- **red-team** = mandatory red-team review (`spa_core/redteam/`) before advancing.
- **emergency-exit** = advisory flag recommending emergency exit of a live/paper position.

Bands below use the higher = riskier convention: **green ≤ 33**, **yellow 34–66**, **red ≥ 67**
(unless a row states otherwise).

| # | Sub-score | Meaning (higher = riskier unless noted) | Required inputs | MVP weight | green / yellow / red | hard-reject | human-review | red-team | emergency-exit |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `yield_score` | **higher = MORE yield** (not risk). Attractiveness of the yield vs product-line target. | expected/observed APY (evidence-levelled) | 0 (informational) | n/a | n/a | n/a | n/a | n/a |
| 2 | `yield_sustainability_score` | risk that the yield is not durable (emissions/points/tail-comp vs real cashflow) | yield_source/mechanism; rates_desk refusal signal | 1.5 | ≤33 / 34–66 / ≥67 | ≥90 | ≥67 | ≥67 | — |
| 3 | `protocol_risk_score` | protocol-level risk (age, TVL trend, deps, governance) | scoring_engine sub-scores (TVL, age, deps, timelock, multisig) | 1.5 | ≤33 / 34–66 / ≥67 | scoring_engine grade `D` | ≥67 | grade `D` 2 runs | — |
| 4 | `smart_contract_risk_score` | contract/exploit exposure (audits, findings, hack history) | scoring_engine (audit_count, findings_severity, hack_history) | 1.5 | ≤33 / 34–66 / ≥67 | open critical finding | ≥67 | ≥67 | active exploit |
| 5 | `stablecoin_risk_score` | depeg/redemption/reserve risk (if a stablecoin is involved; else n/a) | Stablecoin Card (docs/13); peg history | 1.5 | ≤33 / 34–66 / ≥67 | ≥90 | ≥50 | new/opaque stablecoin | observed depeg |
| 6 | `liquidity_risk_score` | risk of not exiting at size | dfb exit-liquidity-by-size @ $1M/$5M/$10M | 1.5 | ≤33 / 34–66 / ≥67 | flagged exit-liquidity hole | ≥67 | — | liquidity vanishes |
| 7 | `counterparty_risk_score` | reliance on a specific counterparty (CEX, issuer, MM) | Strategy Card counterparty fields | 1.0 | ≤33 / 34–66 / ≥67 | ≥90 | ≥50 | ≥67 | counterparty fail |
| 8 | `bridge_risk_score` | bridged-asset / cross-chain messaging exposure | scoring_engine (bridge_dependency) | 1.0 | ≤33 / 34–66 / ≥67 | — | ≥67 | any bridge dep | bridge halt |
| 9 | `oracle_risk_score` | oracle manipulation/staleness exposure | scoring_engine (oracle_risk) | 1.5 | ≤33 / 34–66 / ≥67 | custom/unaudited oracle | ≥50 | ≥67 | oracle fail |
| 10 | `liquidation_risk_score` | forced-liquidation exposure (leverage/collateral) | leverage, collateral, LTV | 1.5 | ≤33 / 34–66 / ≥67 | ≥90 | ≥50 | any leverage | near liq threshold |
| 11 | `operational_risk_score` | ops/keys/monitoring/human-process risk | monitoring_requirements; ops model | 1.0 | ≤33 / 34–66 / ≥67 | — | ≥67 | — | monitoring gap |
| 12 | `regulatory_risk_score` | legal/sanctions/securities surface | scoring_engine (regulatory_surface) | 1.0 | ≤33 / 34–66 / ≥67 | sanctioned exposure | ≥50 | ≥67 | new enforcement |
| 13 | `concentration_risk_score` | single-protocol/single-asset concentration | book context; RiskPolicy caps | 1.0 | ≤33 / 34–66 / ≥67 | breaches RiskPolicy cap | ≥67 | — | — |
| 14 | `correlation_risk_score` | correlation to BTC/ETH/rates/other book positions | forward_analytics; beta | 1.0 | ≤33 / 34–66 / ≥67 | — | ≥67 | ≥67 | regime break |
| 15 | `market_regime_risk_score` | sensitivity to regime (bull/bear/high-vol/low-funding) | forward_analytics stress overlay | 1.0 | ≤33 / 34–66 / ≥67 | — | ≥67 | ≥67 | regime flip |
| 16 | `black_swan_risk_score` | tail / stress-scenario fragility (BTC/ETH −50%, funding reverse, basis collapse) | forward_analytics stress; red-team scenarios | 1.5 | ≤33 / 34–66 / ≥67 | ≥90 | ≥50 | ≥50 | stress trigger |
| 17 | `confidence_score` | **higher = MORE confidence** in the inputs/data (not risk). Low confidence widens caution. | data completeness; evidence level; fallback flags | (gating, not summed) | ≥67 / 34–66 / ≤33 | — | ≤33 | — | — |
| 18 | `overall_risk_score` | weighted aggregate of the `*_risk_score` rows (higher = riskier) | rows 2–16 + weights | derived | ≤33 / 34–66 / ≥67 | ≥80 | ≥50 | ≥67 | — |
| 19 | `allocation_score` | **advisory** suggested-allocation signal (higher = more allocatable). Never an allocator. | overall_risk_score, confidence_score, capacity | derived | ≥67 / 34–66 / ≤33 | — | — | — | — |
| 20 | `spread_attribution_score` | **higher = MORE of the spread-over-floor is explained** by priced accepted risks (ADR-YL-008). 100 = spread fully explained; low = large unexplained residual = unpriced tail risk. | `spread_over_floor_bps` + `spread_risk_explanation` (docs/11 §3.4a) vs the **live** RWA floor | (gating, not summed) | ≥67 / 34–66 / ≤33 | — | ≤66 | ≤66 | — |

Notes:
- `yield_score`, `confidence_score`, `allocation_score`, `spread_attribution_score` are **not** risk-up
  (higher = better). `yield_score` is informational (weight 0 in the risk aggregate — attractiveness
  must never lower measured risk).
- `spread_attribution_score` is **advisory**: it flags how much of the spread is unexplained, but the
  actual **REJECT** on unexplained spread is the **deterministic** `spread_fully_explained` gate on the
  Strategy Card (docs/11 §3.4a / Promotion gates), per ADR-YL-008 — never the score itself. A low score
  is a mandatory human-review + red-team trigger.
- `overall_risk_score` = weighted mean of rows 2–16 using the MVP weights (normalized to sum 1.0),
  then **down-adjusted for confidence**: low `confidence_score` shifts `overall_risk_score` upward
  (unknown = treated as riskier — fail-closed), never downward.
- `allocation_score` is an **advisory** presentation only. The real cap is always the RiskPolicy
  (per-protocol 40% T1 / 20% T2, T2 total ≤ 50%, TVL floor ≥ $5M, min cash ≥ 5%) — `allocation_score`
  can only recommend **less** than the RiskPolicy allows, never more.

---

## 4. How it composes under the RiskPolicy (only stricter, never looser)

The decision order for any candidate is:

1. **RiskPolicy (hard, deterministic).** If `approved=False`, the strategy is rejected. Nothing in
   Risk Scoring v2 can override this (`docs/06` A.1, A.4). Risk Scoring v2 does not import
   `spa_core/execution/` and does not read/write execution-owned state.
2. **Risk Scoring v2 (advisory).** Applied only within what the RiskPolicy already permits. Its role
   is to **withhold advisory promotion** and to **raise triggers** (human-review / red-team /
   emergency-exit). Any hard-reject sub-score → advisory reject at the current lifecycle stage. Any
   human-review trigger → the Strategy Card cannot advance without a named human sign-off. Any
   red-team trigger → mandatory red-team before advancing.
3. **Net effect:** the composed system is the intersection of "RiskPolicy allows" and "advisory layer
   does not flag." It is always ⊆ what the RiskPolicy allows — **stricter or equal, never looser.**

Fail-closed: missing/unknown inputs raise the relevant `*_risk_score` toward red and lower
`confidence_score`; they never default a strategy to "safe."

---

## 5. Reuse mapping detail

- `spa_core/risk/scoring_engine.py` produces 15 `[0,1]` "higher = safer" sub-scores + A/B/C/D grade.
  Risk Scoring v2 maps each to a `[0,100]` "higher = riskier" advisory sub-score by
  `risk = round(100 * (1 - safer))`, and adopts the engine's grade thresholds as the source of the
  `protocol_risk_score` / `smart_contract_risk_score` hard-reject signals (grade `D`).
- `spa_core/dfb/risk_overlay.py` supplies `liquidity_risk_score` (from exit-liquidity-by-size) and the
  structural-veto → red-team/hard-reject signal (NO-FORK: cited, never recomputed).
- `spa_core/strategy_lab/rates_desk/` refusal log supplies the `yield_sustainability_score`
  refusal signal.
- `spa_core/strategy_lab/forward_analytics.py` supplies stress/correlation/regime inputs.

Any value with no existing producer is derived from Strategy Card qualitative fields by a documented
deterministic mapping and carries a reduced `confidence_score`.

---

## 6. Invariants this document preserves

- Deterministic RiskPolicy `v1.0` remains the sole hard execution gate; Risk Scoring v2 is advisory
  and composes only stricter (`docs/06` A.1–A.4, 17; ADR-YL-004).
- No LLM in the scoring / risk / execution / monitoring / kill path.
- No import of `spa_core/execution/`; no write to runtime allocation/execution state.
- Reuses existing engines (scoring_engine, dfb overlay, rates_desk, forward_analytics) rather than
  reinventing risk math (NO-FORK).
- No APY/TVL presented as verified without an evidence level; unknowns → `TBD — requires verification`
  and treated as riskier (fail-closed).
- Weights and thresholds are an MVP starting point and may evolve; changes are documented.
