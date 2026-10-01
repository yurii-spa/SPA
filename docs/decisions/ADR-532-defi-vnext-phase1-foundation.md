# ADR-532: DeFi Engine vNext — Phase 1 foundation (derived, advisory)

- **Status:** ACCEPTED · 2026-10-01 · owner: @yurii (owner directive «DEFI ENGINE vNEXT — PHASE 1
  FOUNDATION», autonomous execution authorised in it)
- **Builds on:** [ADR-530](ADR-530-defi-architecture-gap-audit.md) (gap audit, §J P1 / §K),
  [ADR-531](ADR-531-defi-vnext-phase0-p0-repair.md) (Phase 0).
- **Not changed:** RiskPolicy v1.0 and every numeric limit, the two-tier kill switch, every protocol
  tier label, allocation, the Conservative track, live capital (0), the Trading Research Engine,
  `landing/**`. No new agent and no new canonical store.

## Decision

Phase 1 is a **derived layer**, `spa_core/defi_engine/`. It reads the three books and the existing
canonical sources, and publishes every hour (from the `hy_cycle` / `lp_cycle` CLI, after each cycle's
own write) two artifacts:

- `data/defi_engine/status.json` — the DeFi engine status contract;
- `data/defi_engine/passports.json` — one Position Passport per held position.

Both are rebuilt from scratch on every run and never read back as an input. Nothing on the money
path imports the package; a test enforces this.

| Audit item | Component | What it does |
|---|---|---|
| P1-1 protocol × strategy risk | `mechanics.py` | Second axis: 14 mechanics, each with an advisory risk score, an advisory cap, who pays and data needs. Every registry key is mapped (test). `price_delta_neutral` is computed; an unknown key gives `None`, never `True`. Position risk = max(protocol, mechanic), with the binding axis named. |
| P1-5 canonical APY contract | `apy_contract.py` | Eight named definitions, all in percent, gross and net. `track_realized_apy_net` is the site's headline method; parity is tested. Unmeasured values carry a reason and are never 0.0. A bar with no cost field is never a zero-cost bar, and a sleeve's missing cash is never a residual (both found by the independent review). |
| P1-6 single tier authority | `tiers.py` | The authority is `adapters.tier_map.tier_of`. Census of 8 tier copies, each disagreement with direction (looser/stricter) and money-path flag. Ratchet: no new looser money-path copy. |
| Position Passport | `passport.py` | Derived per-position record: book, mechanic, underlying, who pays, yield + source, tier + composite risk, exit, loss budget, gate, monitoring, evidence level (L3). |
| P1-3 exit / liquidity | `exit_model.py` | Exit latency comes from the adapter class `EXIT_LATENCY_HOURS`; the drifted mirror in `exit_liquidity.py` (missing `fluid_fusdc`) is no longer read. Exit depth = position / LIVE pool TVL only. The ≤25 % illiquid policy is reused from `exit_latency_policy`. |
| P1-7 loss budgets | `loss_budget.py` | Published budgets 3/10/25 % are held parity-tested against `tier_bands.json`. Reports consumed share, status, and whether an enforced stop binds the budget. |
| P1-3 / P1-13 monitoring coverage | `coverage.py` | Per held position, five RTMR dimensions: declared (the sensors' own tables) vs observed (fresh, non-stale signal). Plus an advisory daily `rate_watch` against the pool's own median. |
| P1-15 status contract | `engine.py` | `defi-engine-status/1`: `money_path_effect: none`, `live_capital_usd: 0`, findings list, code version. |
| Wiring / migrations | `hy_cycle` / `lp_cycle` CLI, `architecture/manifest.json` | Publish runs after `--run` only, and a failure is printed by name. The new artifacts are declared with a 26 h SLO. No book record is rewritten. Sleeve rows and positions keep their schema. The Passport carries the mechanic, so no migration of history is needed. |

### Measured on the live tree 2026-10-01 (first build)

- **Conservative:** track net **4.9165 %**, equal to the site headline; track gross **5.1059 %**. Only
  charged costs are added back ($50.15). 77 of 100 bars carry no cost field: no cost was charged before
  ADR-298. Spot APY: gross 5.45 %, on NAV 5.11 %, net 4.25 %. The cost drag of 0.86 %/yr is computed
  only over the trailing run of bars with an observed cost. 19.7 % of the book is slower than 72 h
  (maple), inside the 25 % policy. The loss budget of 3 % is **unbound**: the nearest enforced stop is
  SOFT at 5 %.
- **Balanced:** 50.0 % illiquid (share of deployed notional — a sleeve state has no cash field) (maple 336 h + sUSDe 168 h), against the 25 % policy. It is at the
  advisory caps for RWA credit and staked synthetic. Its figures are unmeasured until the first
  `sleeve-econ-v2` row (first v2 day: 2026-10-02, because a sleeve writes one row per day).
- **Aggressive:** 50.0 % illiquid (maple). RWA credit is 50 % of NAV, against an advisory cap of
  25 %. Figures are unmeasured until its first v2 row.
- **Tier census:** 8 disagreements.
  - Looser on the money path: `policy_enforcer` T1 for `aave_v3_base` and `morpho_steakhouse`
    (authority T2).
  - Stricter on the money path: `policy_enforcer` T3 for `moonwell_base`, `stusd` and `usual_usd0pp`;
    data registry T3 for `ethena_susde`.
  - Off the money path: two in `ADAPTER_METADATA`.
- **Coverage:** 11 positions, none fully covered. No position of any book has a rate sensor
  (11 of 11), and 8 of 11 have no liquidity sensor. The RTMR liquidity sensor is sized on
  Conservative only and misses `maple` and `morpho_blue_base`.

## Owner gate — what this ADR does not do

Four changes would turn these findings into money-path behaviour:

- **A** — tier labels, one value per protocol, no copy loosened;
- **B** — bind the Conservative 3 % budget to a SOFT-equivalent hold;
- **C** — RTMR liquidity scopes plus a rate sensor with a FREEZE-only reaction;
- **D** — the Aggressive delta-neutral check computed from the mechanic.

The session's permission system refused the first two attempts, editing protocol tier labels and
risk scores ("modify shared resources"). The edits were reverted, not worked around. All four
changes are packaged for the owner in
[`docs/owner_packages/2026-10-01-defi-p1-money-path-bindings.md`](../owner_packages/2026-10-01-defi-p1-money-path-bindings.md).

## Consequences

The owner, the CIO and the publication pipeline get one hourly answer to:
- what each position is and who pays for it;
- how fast it can be exited;
- what loss it may cost against the published budget;
- how well it is watched;
- which of the four APY numbers is which.

A finding now has a fixed home (`status.findings`) instead of a sentence in an audit.

## Independent review (separate agent, 2026-10-01)

- **Money path:** no defect found.
- **Five invariant #17 findings, all fixed:**
  1. a missing `cost_usd` was read as 0.0;
  2. an unknown stop was reported as "unbound";
  3. a stale signals file was reported as "uncovered" instead of "unmeasured";
  4. sleeve cash was a negative residual, which made income on NAV larger than gross;
  5. unknown cash was read as 0.
- **Medium findings, fixed:**
  - one bar was enough for an "ok" budget; ≥ 2 bars are now required;
  - status and passports could mix runs; both now carry a shared `run_id`, and passports are written first;
  - day conventions are now named in `DEFINITIONS`;
  - docstrings named tests that do not exist; they now name the real tests.
- **Weak tests:** strengthened. A mutation run puts back each defect the review named; 9 of 9 mutations
  are killed.
