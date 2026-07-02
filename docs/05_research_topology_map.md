# 05 — Research Topology Map (AUDIT-002)

Maps every **existing** research module to its charter layer/role and to the Yield-Lab doc that
**formalizes** it. Purpose: future sessions *formalize and unify* — they never duplicate code that
already exists ([`02`](02_current_architecture_audit.md) §2, [`06`](06_spa_core_invariants.md) §F-20).
All modules below are verified present in the repo. Layers per [`04`](04_layered_architecture.md).

---

## Module → charter role → formalizing doc

| Module | Charter layer / role | Formalized by |
|---|---|---|
| `spa_core/strategy_lab/` (harness: `base.py`, `backtest.py`, `paper.py`, `promotion.py`) | **L2 Yield Lab** — pluggable `Strategy` ABC + one backtest harness + one live-paper service; the lifecycle spine's code home | [`07`](07_yield_lab_architecture.md) (lifecycle), [`04`](04_layered_architecture.md) L2 |
| `strategy_lab/aggressive_lab/` | **L2** — paper-tests the refused 10–15%+ strategies (roster, tail overlay, dated-drawdown contrast) → the **Max/Experimental** research sleeve | [`33`](33_yield_thesis_map.md) A2/A6/C2 (REFUSE rows), [`07`](07_yield_lab_architecture.md) §2 |
| `strategy_lab/rates_desk/` | **L2** — refusal-first fixed/implied-rate carry (RateSurface → FairValueEngine → refusal gate → trade shapes); hash-chained decision log (entries + refusals); validated thesis #1 | [`33`](33_yield_thesis_map.md) A4 (FixedCarry), [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md) (refusal log), [`35`](35_screening_rubric.md) (spread pre-screen) |
| `strategy_lab/rwa_backstop/` | **L2** — thesis #2 de-risk probe (measurement-GO / book NO-GO) | [`33`](33_yield_thesis_map.md) A11, [`07`](07_yield_lab_architecture.md) §2 |
| `strategy_lab/liquidator/` | **L2** — thesis #3 de-risk probe (NO-GO) | [`33`](33_yield_thesis_map.md) A11, [`07`](07_yield_lab_architecture.md) §2 |
| `strategy_lab/underwriting/` | **L2** — measurement side of tokenized-credit underwriting (relationship/legal-gated off-code) | [`33`](33_yield_thesis_map.md) A11, [`34`](34_capital_tiers_strategy.md) (legal-gated tiers) |
| `strategy_lab/forward_analytics.py` | **L2/L3** — risk-adjusted scorecard on live forward series vs the RWA floor (attribution + stress overlay) | [`34`](34_capital_tiers_strategy.md) §1 (scale finding), [`07`](07_yield_lab_architecture.md) paper thresholds |
| `spa_core/tournament/` (`tournament_engine.py`) | **L2** — backtest → paper → live promotion ladder = the status transitions | [`07`](07_yield_lab_architecture.md) §3, [`35`](35_screening_rubric.md), [`35`(discovery)](35_strategy_discovery_engine.md) §4 |
| `spa_core/redteam/` | **L3 AI Investment OS** — red-team scenario battery (how we lose money, depeg, exploit, funding reverse, spread-attribution) | [`35`](35_screening_rubric.md) (red-team triggers), [`33`](33_yield_thesis_map.md) red-team Qs, `prompts/agents/red_team_agent.md` |
| `spa_core/riskwire/` | **L3** — measurement-as-a-product facade (the "AI Investment OS" measurement thesis) | [`04`](04_layered_architecture.md) L3 |
| `spa_core/dfb/` ("DeFi Board") | **L3** — risk-first pool screener + no-fork risk overlay + public `/board`; the primary automated candidate feeder | [`35`(discovery)](35_strategy_discovery_engine.md) §1/§4, [`35`](35_screening_rubric.md) |
| `spa_core/compliance/` | **L3** — compliance surface | [`04`](04_layered_architecture.md) L3 (future `45_compliance_map`) |
| `spa_core/adapters/` + `adapters/defillama_feed.py` | **L1 SPA Core / feed** — 35 read-only protocol adapters + live APY/TVL feed; satisfy L2 yield-source verification | [`33`](33_yield_thesis_map.md) (per-mechanism "SPA today"), [`35`(discovery)](35_strategy_discovery_engine.md) §1 |
| `spa_core/risk/policy.py` | **L1** — deterministic RiskPolicy `v1.0`, the sole hard gate | [`06`](06_spa_core_invariants.md) §A-1 |
| `spa_core/governance/kill_switch.py` | **L1** — two-tier kill (SOFT/HARD) | [`06`](06_spa_core_invariants.md) §A-3 |
| `data/rwa_feed.py` | **feed** — live tokenized-T-bill floor (the baseline every candidate is measured against) | [`33`](33_yield_thesis_map.md) A10, [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md) |

---

## Duplication guard (read before building anything)

- **Do NOT** re-implement pool screening → use `dfb/` output; emit Candidate Records *from* it
  ([`35`(discovery)](35_strategy_discovery_engine.md) §4).
- **Do NOT** re-implement a refusal log → reuse the `rates_desk/` hash-chained decision log + `/refusals`
  surface ([`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
- **Do NOT** re-implement backtest/paper/promotion → use the `strategy_lab/` harness + `tournament/`.
- **Do NOT** re-implement the red-team battery → use `redteam/`.
- **Do NOT** re-implement the RWA floor → read `data/rwa_feed.py` (dynamic, never hardcode).

The docs in the right-hand column are the charter vocabulary these modules map onto — they bind the
existing code, they do not replace it.
