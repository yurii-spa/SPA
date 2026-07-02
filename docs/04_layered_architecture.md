# 04 — Layered Architecture (DOCS-005)

The five layers of the target architecture, each with its responsibility, what it **MAY** and
**MUST-NOT** do, and the boundaries between them. The single hard rule: **the deterministic RiskPolicy
is the sole hard gate, and it lives in SPA Core.** Every layer above it is advisory (autonomy L0/L1).
Real modules per layer are cross-referenced to [`02`](02_current_architecture_audit.md); invariants to
[`06`](06_spa_core_invariants.md).

---

## Layer 1 — SPA Core (trust foundation)

The existing deterministic, paper-tracked stablecoin yield optimizer. The layer that touches (paper)
capital.

- **Responsibility:** run the daily cycle, enforce risk, hold the evidenced track. Modules:
  `risk/policy.py` (RiskPolicy `v1.0`), `paper_trading/` (cycle_runner, golive_checker, cycle_gates),
  `governance/kill_switch.py` (two-tier), `adapters/` (35 read-only), `api/server.py`.
- **MAY:** enforce hard caps; run/allocate the paper book; write runtime `data/*.json`; own execution
  domain (`execution/`).
- **MUST-NOT:** contain any LLM in the risk/execution/monitoring/kill path; be weakened, overridden, or
  bypassed by any layer above; change RiskPolicy `version` without a new ADR.
- **Boundary:** the **only** layer with a hard gate. `execution/` is import-forbidden from all layers
  above ([`06`](06_spa_core_invariants.md) §B-6). Everything above SPA Core is advisory input to a
  human, never a control signal.

## Layer 2 — Yield Lab (closed research layer)

Where strategies are searched for, tested, rejected, validated, and graduated **before** any public or
live exposure.

- **Responsibility:** the lifecycle spine (idea → … → approved/frozen/retired) and the spread-over-floor
  mandate. Modules: `strategy_lab/{aggressive_lab,rates_desk,rwa_backstop,liquidator,underwriting}`,
  `strategy_lab/{forward_analytics,promotion}.py`, `tournament/`.
- **MAY:** paper-test candidates; emit hash-chained decision/refusal logs; produce Strategy/Protocol/
  Stablecoin Cards; write research-layer state to **NEW** directories.
- **MUST-NOT:** move live capital (sleeves default `IS_ADVISORY=True`); present paper/backtest as live;
  approach or approximate the RiskPolicy gate; graduate anything to Enhanced/Max with
  `spread_fully_explained=false` ([`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
- **Boundary:** composes **under** RiskPolicy (only stricter, never looser). Graduation requires named
  human approval at each step. → [`07`](07_yield_lab_architecture.md).

## Layer 3 — AI Investment OS (research / decision-support agents)

Research and decision-support agents: discovery, protocol/stablecoin analysis, risk memos, red-team,
BTC/ETH cycle, portfolio recommendations, reporting.

- **Responsibility:** turn signals into candidates, due diligence, and recommendations. Modules:
  `redteam/` (red-team battery), `riskwire/` (measurement-as-a-product), `dfb/` (risk-first pool
  screener + `/board`), `compliance/`, discovery per [`35`](35_strategy_discovery_engine.md).
- **MAY:** research, score (Risk Scoring v2 advisory), red-team, write IC/risk memos, recommend
  allocations (L1), produce reports.
- **MUST-NOT:** approve a strategy (no LLM/score approves); make an APY claim without an evidence level;
  bypass the deterministic RiskPolicy; introduce execution automation.
- **Boundary:** output is **advisory to a human** (autonomy L0/L1). Feeds candidates *into* Layer 2;
  never allocates. Discovery ends where the tournament begins ([`35`](35_strategy_discovery_engine.md) §4).

## Layer 4 — Builder OS (dev-support agents)

Development-support agents: docs, backlog, prompts, architecture review.

- **Responsibility:** keep the research layer documented, planned, and coherent. Artifacts: this docs
  set, backlog, agent prompts, ADRs, schemas/templates.
- **MAY:** write/maintain docs, schemas, templates, prompts, backlog; propose architecture.
- **MUST-NOT:** touch runtime execution, RiskPolicy, the public dashboard, security-sensitive behavior,
  or deployment without owner approval; introduce runtime code or dependencies.
- **Boundary:** produces documentation and scaffolding only. No runtime authority; changes to Layers 1–3
  behavior require the owner and an ADR.

## Layer 5 — Execution Support (non-custodial, human-in-the-loop)

Prepares checklists and approvals for a human to act on. **Never signs, never controls funds.**

- **Responsibility:** turn an approved decision into a human-executable checklist / unsigned artifact.
- **MAY:** prepare checklists, pre-flight validations, and (future) unsigned tx + multisig proposals for
  human review.
- **MUST-NOT:** hold private keys or seeds, sign transactions, move/withdraw funds, or run autonomous
  execution (ADR-YL-005, [`06`](06_spa_core_invariants.md) §B).
- **Boundary:** strictly non-custodial and human-gated. Default autonomy now is L0/L1; L3+ (unsigned tx
  + multisig) is future and owner-gated.

---

## Cross-cutting boundary rules

1. **One hard gate.** RiskPolicy in SPA Core is authoritative; Layers 2–5 are advisory and compose only
   *stricter* under it. No advisory score, agent, or recommendation is ever a control signal.
2. **No LLM below the advisory line.** Layers 3–5 may use LLMs for research/planning; the risk,
   execution, monitoring, and kill paths (Layer 1) never do.
3. **Evidence discipline crosses every layer.** No claim without an evidence level; refusals are
   first-class outputs ([`06`](06_spa_core_invariants.md) §C, [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
4. **New state in new directories.** Research layers never break runtime `data/*.json` formats.

Cross-refs: [`02`](02_current_architecture_audit.md) §1–2 (real modules per layer), [`06`](06_spa_core_invariants.md)
(invariants), [`07`](07_yield_lab_architecture.md) (lifecycle), [`05`](05_research_topology_map.md)
(module → layer map).
