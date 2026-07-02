# 12 — Protocol Card System (§19)

**Status:** research-layer documentation. No runtime code, RiskPolicy, dashboard, deploy, or
existing files are modified by this document. **Tone:** institutional, evidence-first. **TVL /
revenue / user-activity numbers in any card are placeholders marked "TBD — requires data
verification" until sourced with a last-verified date.**

Cross-references: `docs/11_strategy_card_system.md` (Strategy Cards reference these), `docs/13_stablecoin_card_system.md`
(sibling due-diligence for stablecoins), `docs/02_current_architecture_audit.md` (existing `adapters/`
+ `dfb/` overlay — protocols are *implicit* there; these cards formalize the due-diligence), `docs/14_risk_scoring_v2.md`
(advisory scorecard), `docs/06_spa_core_invariants.md` (hard invariants preserved), `data/protocol_cards/`
(schema + template + README).

---

## 1. Purpose

A **Protocol Card** is a single, comparable, auditable due-diligence record for one protocol SPA can
depend on (a lending market, a vault, an LP venue, an RWA issuer's on-chain surface). It exists so
that every protocol a Strategy Card touches is described in the *same* vocabulary: how big it is, who
holds the admin keys, what it depends on (oracles, bridges), what has already gone wrong, why its
yield is or is not sustainable, and how much of the book may safely sit on it.

Today this knowledge is **implicit** — spread across the 35 read-only adapters in
`spa_core/adapters/` (`ADAPTER_REGISTRY`), the `spa_core/dfb/` risk-first pool screener + NO-FORK
risk overlay, red-team notes, and the operator's head. The Protocol Card formalizes that into one
file per protocol so it is:

- **Comparable** — every protocol answers the same fields, so an Aave market and a Pendle market can
  be laid side by side.
- **Auditable** — a future reviewer (or external IC / due-diligence party) can reconstruct *why* a
  protocol was trusted, capped, or refused, from the card alone.
- **Promotion-gating** — a Strategy Card cannot advance to Enhanced / MaxYield until every protocol
  in its `protocols_used` has a reviewed Protocol Card (`docs/11 §5`).

A Protocol Card is a **research-layer artifact**. Cards live under `data/protocol_cards/` (research
data), never in runtime `data/*.json`. A card **describes** a protocol; it never **executes** against
one and is never read by the deterministic RiskPolicy or the execution path.

---

## 2. Relationship to what already exists (do not duplicate)

Per `docs/02_current_architecture_audit.md`, the protocol layer already exists in code. The card
system **formalizes and unifies** it — it does not rebuild it:

| Existing module | What the card reuses / references |
|---|---|
| `spa_core/adapters/` — 35 read-only adapters + DeFiLlama feed | `protocol_id` mapping, `chains`, live `tvl` / `apy` inputs (cited with a last-verified date, never hardcoded into the card) |
| `spa_core/dfb/` — risk-first pool screener + NO-FORK risk overlay | `risk_score`, `oracle_dependencies`, `admin_keys`, `yield_sustainability` inputs — the card **cites** the overlay verdict, never re-derives it |
| `spa_core/risk/policy.py` — deterministic caps (TVL ≥ $5M, per-protocol 40% T1 / 20% T2) | `max_allocation_recommendation` is **advisory** and never exceeds / overrides the RiskPolicy caps |
| `spa_core/redteam/` | `exploit_history`, `emergency_triggers`, `known_risks` red-team inputs |

**Rule:** the card is a *presentation and record* layer over these modules. Where a value can be
produced by an existing module (a TVL figure, a risk-overlay verdict, an adapter's chain list), the
card **cites** it with a source + last-verified date and does not invent a parallel number.

---

## 3. Full field list

Fields are grouped for readability; the authoritative machine schema is
`data/protocol_cards/schema.protocol_card.json` and the fill-in template is
`data/protocol_cards/template.protocol_card.md`. All numeric TVL / revenue / activity fields are
placeholders (`TBD — requires data verification`) until sourced with a last-verified date.

### 3.1 Identity

| Field | Type | Meaning |
|---|---|---|
| `protocol_id` | string | Stable unique id (e.g. `PC-0001`). Never reused. Maps to the adapter key where one exists. |
| `protocol_name` | string | Human-readable protocol name (e.g. `Aave V3`). |
| `category` | enum | Coarse family: `lending`, `dex`, `lp`, `rwa`, `derivatives`, `restaking`, `yield_aggregator`, `stablecoin_issuer`, `bridge`, `other`. |
| `chains` | array | Chains the protocol operates on (cross-ref adapter `chains`). |
| `website` | string | Official website URL. |
| `docs` | string | Official documentation URL. |
| `app_url` | string | Official app / dApp URL. |

### 3.2 Size & activity (never presented without a last-verified date)

| Field | Type | Meaning |
|---|---|---|
| `tvl` | number\|null | Total value locked (USD). **TBD — requires data verification.** Cite adapter / DeFiLlama + date. |
| `tvl_trend` | enum | `rising` \| `stable` \| `declining` \| `volatile` \| `unknown`. |
| `revenue` | number\|null | Protocol revenue (annualized USD, if known). TBD until sourced. |
| `fees` | number\|null | Protocol fees (annualized USD, if known). TBD until sourced. |
| `user_activity` | string | Qualitative user-activity note (active borrowers, depositors, unique users). TBD until sourced. |
| `protocol_age` | string | Time live (e.g. `~3y since 2021`), a proxy for battle-testing. |

### 3.3 Security & trust surface (the due-diligence core)

| Field | Type | Meaning |
|---|---|---|
| `audits` | array | Audits: firm, scope, date. Empty array = none found (state so explicitly). |
| `bug_bounty` | string | Bug-bounty program + size, or `none`. |
| `exploit_history` | array | Past exploits / incidents: what, when, impact, resolution. Empty = none known (state so). |
| `admin_keys` | string | Who controls admin/upgrade keys; multisig threshold; timelock. **The single most load-bearing trust field.** |
| `upgradeability` | enum | `immutable` \| `timelock` \| `multisig` \| `upgradeable_no_timelock` \| `unknown`. |
| `oracle_dependencies` | array | Oracles relied on (Chainlink, protocol-native, TWAP) and what breaks if they fail. |
| `bridge_dependencies` | array | Bridges / cross-chain messaging the protocol depends on. |
| `governance_model` | string | Governance structure (token vote, council, DAO, off-chain). |

### 3.4 Yield & incentives

| Field | Type | Meaning |
|---|---|---|
| `token_incentives` | string | Token/points incentives inflating APY, and their expected duration. |
| `yield_sustainability` | enum | `organic` \| `incentive_dependent` \| `mixed` \| `unsustainable` \| `unknown`. Whether the yield survives after incentives end. |

### 3.5 Risk assessment (advisory; feeds Strategy Cards)

| Field | Type | Meaning |
|---|---|---|
| `known_risks` | array | Enumerated protocol-specific risks (red-team + overlay inputs). |
| `risk_score` | 0–100 | Advisory overall protocol risk (higher = riskier per `docs/14`). **Advisory only** — cites `dfb` overlay, never a hard gate. |
| `max_allocation_recommendation` | number\|null | Advisory ceiling (% of book) for this protocol. **Never exceeds / overrides RiskPolicy caps** (`docs/06` A.1). TBD until sourced. |
| `monitoring_frequency` | enum | `continuous` \| `daily` \| `weekly` \| `monthly` \| `on_event`. How often the protocol must be re-checked. |
| `emergency_triggers` | array | Conditions that force de-risking / exit from this protocol (TVL collapse, admin-key change, exploit, oracle failure, governance capture). |

### 3.6 Provenance

| Field | Type | Meaning |
|---|---|---|
| `notes` | string | Free-text reviewer notes. |
| `created_at` | ISO-8601 | Creation timestamp (UTC). |
| `updated_at` | ISO-8601 | Last update timestamp (UTC). |

---

## 4. Where cards live

- Directory: `data/protocol_cards/` (research layer, **not** runtime `data/*.json`).
- Schema: `data/protocol_cards/schema.protocol_card.json` (JSON Schema draft 2020-12).
- Template: `data/protocol_cards/template.protocol_card.md`.
- README: `data/protocol_cards/README.md`.
- One card per protocol, as a JSON file conforming to the schema and/or a markdown card from the
  template. `protocol_id` is the stable key; map it to the adapter key where one exists.

---

## 5. Review discipline

- Every protocol in a Strategy Card's `protocols_used` **must** have a reviewed Protocol Card before
  that strategy can promote to Enhanced / MaxYield (`docs/11 §5`, promotion gate "Protocol review").
- `admin_keys`, `upgradeability`, `oracle_dependencies`, `exploit_history`, and `emergency_triggers`
  are the load-bearing trust fields — an empty/unknown value there is a finding, not a blank.
- `risk_score` and `max_allocation_recommendation` are **advisory** and cite the `dfb` overlay /
  RiskPolicy caps; they never replace the deterministic RiskPolicy or wire into execution.

---

## 6. Invariants this document preserves

- The deterministic RiskPolicy remains the sole hard execution gate; card scores and allocation
  recommendations are advisory records (`docs/06` A.1–A.4, invariants 14 & 17).
- No LLM is placed in the risk/execution/monitoring/kill path by the card system.
- No TVL / revenue / activity number is presented as verified without a last-verified date and
  source; unknowns are `TBD — requires data verification`.
- Cards reuse the existing adapter + `dfb` overlay + red-team modules rather than duplicating their
  math.
