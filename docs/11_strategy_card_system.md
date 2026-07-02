# 11 — Strategy Card System (§18)

**Status:** research-layer documentation. No runtime code, RiskPolicy, dashboard, deploy, or
existing files are modified by this document. **Tone:** institutional, evidence-first. **APY/TVL
numbers in any card are placeholders marked "TBD — requires verification" until sourced.**

Cross-references: `docs/07_yield_lab_lifecycle.md` (lifecycle statuses), `docs/37_apy_evidence_standard.md`
(L0–L6 evidence levels), `docs/14_risk_scoring_v2.md` (advisory scorecard), `docs/06_spa_core_invariants.md`
(hard invariants preserved), `data/strategy_cards/` (schema + template + examples), the existing
research layer `spa_core/strategy_lab/*` and `spa_core/tournament/*`.

---

## 1. Purpose

A **Strategy Card** is a single, comparable, auditable record for one yield strategy. It exists so
that every candidate strategy — before it can touch any product line — is described in the *same*
vocabulary: where the yield comes from, who pays it, why it can disappear, what can go wrong, what
evidence supports the APY, how it scores on the advisory Risk Scoring v2, and what it is approved for.

The card is the durable memory of a strategy. Today much of this knowledge is implicit — spread across
`spa_core/strategy_lab/` code, tournament results, red-team notes, and the operator's head. The card
formalizes that knowledge into one file per strategy so it is:

- **Comparable** — every strategy answers the same fields, so `Preserve` and `Experimental`
  candidates can be laid side by side.
- **Auditable** — a future reviewer (or external IC / due-diligence party) can reconstruct *why* a
  strategy was approved, rejected, or frozen, from the card alone.
- **Promotable** — the card records exactly which gates a strategy has passed on the Yield Lab
  lifecycle, so promotion is a checklist, not a judgment call.

A Strategy Card is a **research-layer artifact**. Cards live under `data/strategy_cards/` (research
data), never in runtime `data/*.json`. A card **describes** a strategy; it never **executes** one and
is never read by the deterministic RiskPolicy or the execution path.

---

## 2. Relationship to what already exists (do not duplicate)

Per `docs/02_current_architecture_audit.md`, a substantial research layer already exists. The card
system **formalizes and unifies** it — it does not rebuild it:

| Existing module | What the card reuses / references |
|---|---|
| `spa_core/strategy_lab/` (pluggable `Strategy` ABC, harness, live paper) | `paper_test_status`, `observed_apy_range`, forward analytics vs the RWA floor |
| `spa_core/strategy_lab/aggressive_lab/` | source for `Enhanced/MaxYield/Experimental` candidate cards (already paper-tests refused 10–15%+ strategies) |
| `spa_core/strategy_lab/rates_desk/` | `yield_source`, `yield_mechanism`, refusal-first decision log → `red_team_status`, hash-chained proof |
| `spa_core/tournament/` (backtest → paper → live ladder) | `validation_status`, promotion evidence — the tournament ladder is the *runtime* promotion machinery the card records |
| `spa_core/dfb/risk_overlay.py` (NO-FORK risk verdict) | `risk_score`, `liquidity_score` inputs — the card cites the engine verdict, never re-derives it |
| `spa_core/risk/scoring_engine.py` (ADR-014, 15 subscores A/B/C/D) | the advisory `risk_score` sub-scores (see `docs/14`) |

**Rule:** the card is a *presentation and record* layer over these modules. Where a value can be
produced by an existing module (a risk verdict, an exit-liquidity-by-size row, a proof hash, a
paper-track datapoint), the card **cites** it and does not invent a parallel number.

---

## 3. Full field list

Fields are grouped for readability; the authoritative machine schema is
`data/strategy_cards/schema.strategy_card.json` and the fill-in template is
`data/strategy_cards/template.strategy_card.md`. All numeric yield/capacity fields are
placeholders (`TBD — requires verification`) until sourced with an evidence level.

### 3.1 Identity

| Field | Type | Meaning |
|---|---|---|
| `strategy_id` | string | Stable unique id (e.g. `SC-0001`). Never reused. |
| `name` | string | Human-readable name. |
| `version` | string | Card version (semver-ish, e.g. `1.0`); bumps on material edits. |
| `category` | string | Coarse family (e.g. `lending`, `rwa`, `basis`, `carry`, `lp`, `restaking`, `leverage`, `options`). |
| `product_line` | enum | `Preserve` \| `Core` \| `Enhanced` \| `MaxYield` \| `Experimental`. The line the card is **targeted at** (approval is separate — see `approved_for_product_line`). |
| `asset_type` | string | Primary underlying asset class (`stablecoin`, `BTC`, `ETH`, `mixed`). |

### 3.2 What the strategy touches

| Field | Type | Meaning |
|---|---|---|
| `assets_used` | array | Concrete assets held (e.g. `["USDC","sUSDe"]`). |
| `protocols_used` | array | Protocols the strategy depends on (cross-reference Protocol Cards). |
| `chains_used` | array | Chains the strategy operates on. |

### 3.3 Yield source (the honesty core)

| Field | Type | Meaning |
|---|---|---|
| `yield_source` | string | One-line: where the yield comes from. |
| `yield_mechanism` | string | Mechanism detail (lending spread, funding basis, RWA coupon, emissions, points, etc.). |
| `who_pays_the_yield` | string | The counterparty actually paying (borrowers, protocol treasury, short-side of a basis, T-bill issuer, incentive program). |
| `why_yield_exists` | string | The economic reason this yield is available at all. |
| `why_yield_can_disappear` | string | The failure/compression modes that end the yield (rate compression, incentive end, funding flip, depeg, capacity). |

### 3.4 APY (never presented without an evidence level)

| Field | Type | Meaning |
|---|---|---|
| `expected_apy_range` | object `{low,high}` | Expected forward APY. **TBD — requires verification** by default. |
| `observed_apy_range` | object `{low,high}` | Observed (paper/backtest/live) APY. Must carry an evidence level. |
| `base_apy` | number\|null | Base (non-incentive) APY. |
| `incentive_apy` | number\|null | Incentive/emissions portion of APY. |
| `sustainable_apy_estimate` | number\|null | Estimate of APY expected to persist after incentives/compression. |
| `apy_evidence_level` | enum `L0..L6` | Evidence level per `docs/37`. L0 idea → L6 multi-cycle validated. **No APY value is treated as verified below the level stated here.** |

### 3.4a Spread over the floor (the mandate — ADR-YL-008)

The RWA floor is the **official baseline**: an Enhanced/Max card is judged as **spread over the live
floor**, not absolute APY, and **every point of spread must be explained by a named accepted risk**.

| Field | Type | Meaning |
|---|---|---|
| `floor_baseline_pct` | object `{value, source, as_of}` | The **live** RWA floor used for this evaluation (source `data/rwa_feed.py`; fail-closed committed-literal fallback flagged). **Never hardcoded.** |
| `spread_over_floor_bps` | number\|null | `(sustainable/observed APY − floor)` in bps. The quantity under scrutiny. |
| `spread_risk_explanation` | array of `{risk, bps, evidence}` | Itemized mapping of spread → **specific, accepted, measurable** risks. The bps should sum to the spread. |
| `unexplained_spread_bps` | number\|null | Residual = `spread_over_floor_bps − Σ spread_risk_explanation.bps`. Treated as **unpriced tail risk**, not alpha. |
| `spread_fully_explained` | bool | True only if `unexplained_spread_bps ≤ tolerance`. **A card cannot advance to Enhanced/Max while this is false** (→ REJECT, logged in the refusal log). |

### 3.5 Advisory scores (0–100; see `docs/14`)

| Field | Type | Meaning |
|---|---|---|
| `confidence_score` | 0–100 | Confidence in the card's own inputs/data (advisory). |
| `risk_score` | 0–100 | Advisory overall risk (higher = riskier per `docs/14` convention). |
| `liquidity_score` | 0–100 | Advisory liquidity/exitability. |
| `complexity_score` | 0–100 | Operational/technical complexity. |

> These scores are **advisory only** (Risk Scoring v2, ADR-YL-004). They never replace the
> deterministic RiskPolicy and are never wired to execution. See `docs/14`.

### 3.6 Capacity & capital

| Field | Type | Meaning |
|---|---|---|
| `capacity_estimate` | number\|null | Approx. capital the strategy can absorb before APY compresses / slippage bites. **TBD — requires verification.** |
| `min_capital` | number\|null | Minimum sensible allocation. |
| `max_capital` | number\|null | Maximum sensible allocation. |
| `suitable_capital_tiers` | array | Capital tiers this fits (`$100k`, `$1M`, `$10M`, `$100M+`); cross-ref `docs/34`. |
| `lockup_period` | string\|null | Lockup (e.g. `none`, `7d`, `variable`). |
| `withdrawal_time` | string\|null | Expected time to exit to cash. |

### 3.7 Risk dimensions (qualitative descriptors; feed the advisory scores)

| Field | Meaning |
|---|---|
| `smart_contract_risk` | Contract/exploit exposure. |
| `stablecoin_risk` | Depeg / redemption / reserve risk (if stablecoin involved). |
| `counterparty_risk` | Reliance on a specific counterparty (CEX, issuer, market maker). |
| `bridge_risk` | Bridged-asset / cross-chain messaging exposure. |
| `oracle_risk` | Oracle manipulation / staleness exposure. |
| `liquidation_risk` | Forced-liquidation exposure (leverage, collateral). |
| `regulatory_risk` | Legal / sanctions / securities surface. |
| `operational_risk` | Ops/keys/monitoring/human-process risk. |
| `concentration_risk` | Single-protocol / single-asset concentration. |
| `correlation_risk` | Correlation to BTC/ETH/rates/other book positions. |
| `market_regime_risk` | Sensitivity to regime (bull/bear/high-vol/low-funding). |

### 3.8 Dependencies, assumptions, conditions

| Field | Type | Meaning |
|---|---|---|
| `key_dependencies` | array | External things that must hold (a peg, a CEX leg, an oracle, an incentive program). |
| `assumptions` | array | Stated assumptions the thesis rests on. |
| `entry_conditions` | array | Conditions required to enter. |
| `exit_conditions` | array | Normal exit conditions. |
| `emergency_exit_conditions` | array | Conditions that force an emergency exit. |
| `monitoring_requirements` | array | What must be monitored while the position is open. |
| `data_sources_required` | array | Feeds/data the strategy depends on (must be real, cited). |

### 3.9 Validation & approval (the promotion ledger)

| Field | Type | Meaning |
|---|---|---|
| `validation_status` | string | Where the strategy is in validation (free text mirroring lifecycle). |
| `paper_test_status` | string | Paper-testing state / result (cross-ref `strategy_lab` / `tournament`). |
| `small_capital_test_status` | string | Small-capital test state / result. |
| `red_team_status` | string | Red-team review state / verdict (cross-ref `spa_core/redteam/`). |
| `approved_for_product_line` | enum\|null | Product line the card is **approved** for (may lag `product_line` target). |
| `final_recommendation` | string | The reviewer's recommendation (approve / reject / defer / research-only). |
| `max_allocation` | number\|null | Advisory maximum allocation if approved (never overrides RiskPolicy caps). |
| `review_frequency` | string | How often the card must be re-reviewed (e.g. `weekly`, `monthly`). |

### 3.10 Provenance

| Field | Type | Meaning |
|---|---|---|
| `owner` | string | Human owner accountable for the card. |
| `created_at` | ISO-8601 | Creation timestamp. |
| `updated_at` | ISO-8601 | Last update timestamp. |
| `status` | enum | Lifecycle status (see §4). |

---

## 4. Lifecycle statuses (`status` enum)

Mirrors `docs/07_yield_lab_lifecycle.md` and the master prompt:

```
idea → research → rejected
              ↘ paper_testing → paper_passed → small_capital_testing → small_capital_passed
                    → approved_for_preserve | approved_for_core | approved_for_enhanced | approved_for_max_yield
                    → frozen | retired
```

`status` values (enum, exact): `idea`, `research`, `rejected`, `paper_testing`, `paper_passed`,
`small_capital_testing`, `small_capital_passed`, `approved_for_preserve`, `approved_for_core`,
`approved_for_enhanced`, `approved_for_max_yield`, `frozen`, `retired`.

`status` (where the card *is*) and `approved_for_product_line` (what it is *cleared for*) are
distinct on purpose: a card can be `paper_passed` while `approved_for_product_line = null`.

---

## 5. Promotion gates

A card cannot advance to **Enhanced** or **MaxYield** (or **Experimental** public exposure) without
**all** of the following recorded on the card as satisfied. These gates are additive to — never a
substitute for — the deterministic RiskPolicy hard gate (`docs/06`, invariant A.1).

| Gate | Card evidence required |
|---|---|
| **Spread fully explained (ADR-YL-008)** | `spread_fully_explained = true`: `spread_over_floor_bps` computed against the **live** `floor_baseline_pct`, `spread_risk_explanation` accounts for the whole spread, `unexplained_spread_bps ≤ tolerance`. **Unexplained spread ⇒ REJECT, recorded in the refusal log.** |
| **Clear yield source** | `yield_source`, `yield_mechanism`, `who_pays_the_yield`, `why_yield_exists`, `why_yield_can_disappear` all filled with substantive answers (no `TBD`). |
| **APY evidence level** | `apy_evidence_level` ≥ **L3 (paper-tracked)** for Enhanced; ≥ **L4 (small-capital tested)** for MaxYield. Never a lower level presented as higher. |
| **Protocol review** | Every entry in `protocols_used` has a reviewed Protocol Card (`docs/12`). |
| **Stablecoin review (if applicable)** | If any stablecoin is involved, a reviewed Stablecoin Card (`docs/13`); `stablecoin_risk` substantively filled. |
| **Risk review** | Advisory Risk Scoring v2 completed (`docs/14`); `risk_score`, `liquidity_score`, `complexity_score` present; no hard-rejection sub-score triggered. |
| **Red-team review** | `red_team_status` = passed, produced by `spa_core/redteam/` (mandatory for Enhanced/Max/Experimental/leverage/credit/counterparty/bridge/opaque/new-stablecoin/lockup/options/basis). |
| **Capacity estimate** | `capacity_estimate` + `suitable_capital_tiers` present and sourced (not `TBD`) — the strategy must have a defensible size. |
| **Liquidity review** | `liquidity_score` present and exit-liquidity-by-size cited from `dfb/risk_overlay.py` (not synthesized). |
| **Paper testing** | `paper_test_status` = passed with a real paper track (`strategy_lab`/`tournament`), not backtest-only. |
| **Human approval** | `approved_for_product_line` set by a named human `owner` with a `final_recommendation`. **No card self-promotes.** |

For **Preserve / Core**: the same gates apply in principle, at the desk's already-conservative bar;
the lifecycle in `docs/07` governs the exact evidence bar per line.

---

## 6. Where cards live

- Directory: `data/strategy_cards/` (research layer, **not** runtime `data/*.json`).
- Schema: `data/strategy_cards/schema.strategy_card.json` (JSON Schema draft 2020-12).
- Template: `data/strategy_cards/template.strategy_card.md`.
- Examples: `data/strategy_cards/examples/` (populated in Priority 2; empty at scaffolding time).
- One card per strategy, ideally as a JSON file conforming to the schema plus/or a markdown card
  from the template. `strategy_id` is the stable key.

---

## 7. Invariants this document preserves

- The deterministic RiskPolicy remains the sole hard execution gate; cards and their scores are
  advisory records (`docs/06` A.1–A.4, invariant 17).
- No LLM is placed in the risk/execution/monitoring/kill path by the card system.
- No APY/TVL number is presented as verified without an evidence level and source; unknowns are
  `TBD — requires verification`.
- Cards reuse the existing research/risk modules rather than duplicating their math.
