# 02 — Current Architecture Audit

**Status:** read-only audit, no runtime files modified. **Date basis:** repository state on the
`yield-lab-scaffolding` branch (forked from `main` @ `b71dde9e2`). **Method:** static inspection of
`spa_core/`, `landing/`, `data/`, `docs/`, `.github/`, plus registry counts verified by import.

This document maps what the Yield Lab master prompt *assumes must be built* against what *already
exists* in the repository. The headline finding: **a substantial research / risk / refusal layer
already exists.** The master prompt reads as greenfield in places; reality is not. Where the master
prompt calls something "missing," this audit says honestly whether it is missing, partial, or present
under a different name. No files were invented; unverified values are marked *requires verification*.

---

## 1. Repository map (verified)

**Python core — `spa_core/` (~55 packages).** The load-bearing ones:

| Package | Role | Master-prompt relevance |
|---|---|---|
| `risk/policy.py` | Deterministic RiskPolicy, `version: v1.0` (hard execution gate) | §2, §6 invariant |
| `paper_trading/` | `cycle_runner.py`, `golive_checker.py`, `cycle_gates.py` (SOFT-derisk), gap monitor | SPA Core |
| `governance/kill_switch.py` | Two-tier kill (SOFT −5% / HARD −10%, ADR-034/048) | §2 invariant |
| `adapters/` | 35 read-only protocol adapters + DeFiLlama feed | Protocol layer |
| `strategy_lab/` | **Existing research layer** — see §2 below | **Yield Lab (partial)** |
| `tournament/` | `tournament_engine.py` backtest→paper→live promotion ladder | Strategy discovery/validation (partial) |
| `redteam/` | **Existing red-team module** | §24 Red Team (partial) |
| `riskwire/` | Measurement-as-a-product facade (50 subjects) | AI Investment OS (partial) |
| `dfb/` | "DeFi Board" risk-first pool screener + overlay | Strategy Discovery / Protocol cards (partial) |
| `compliance/` | **Existing compliance module** | §22 (partial) |
| `governance/`, `safety/`, `stress/` | Kill-switch ladder, safety board, stress tests | Risk layer |
| `monitoring/`, `alerts/`, `dr/` | Health, red-flag monitor, resilience/offsite/drills | §26 monitoring (partial) |
| `api/server.py` | FastAPI read-API (`api.earn-defi.com`) | §34 API (partial, live) |
| `execution/` | Execution-domain (do NOT import from read-only code) | §27 Execution Support |
| `family_fund/`, `reporting/`, `analytics/` | Cabinet API, reports, attribution | §36 reporting (partial) |
| `optimization/`, `allocator/`, `portfolio/` | Allocation engines | §11 portfolio (partial) |

- **35 adapters** in `ADAPTER_REGISTRY` (verified by import). Read-only domain.
- **1,489 test files** across `spa_core/tests/` + `tests/`. Suite green as of this session (0 failed).
- **~400 `data/*.json`** runtime state files + many `data/*/` subdirs (aggressive_lab, rates_desk,
  rwa_backstop, riskwire, dfb, historical_apy, backups, …). **Not touched by this scaffolding.**
- **Frontend:** `landing/` (Astro → Cloudflare-proxied GitHub Pages, `earn-defi.com`). Public
  dashboard + Desk Cockpit + DFB board + Academy. **Not touched by this scaffolding.**
- **CI:** `.github/workflows/` — ci.yml, ci-lite.yml, test.yml, deploy-landing.yml, proof-gate.yml,
  spa-lint.yml (LLM-forbidden lint), spa-run.yml, spa_alerts.yml.
- **Build:** `requirements.txt` (Python, stdlib-first runtime); `landing/package.json` (Astro).
- **Docs:** large existing `docs/` (many ADRs `ADR_0xx` / `ADR-0xx`, AUDIT_*, ARCHITECTURE_TIER1,
  BACKTEST_METHODOLOGY, RATES_DESK, STRATEGY_LAB, PROOF_CHAIN_SPEC, SYSTEM_BRIEFING, …). `docs/adr/`
  already holds ADR-002…025. Numbered `NN_lowercase.md` names are free (no collision).

## 2. The research layer that ALREADY EXISTS (key correction to the master prompt)

The master prompt asks to "add a Yield Lab research layer." Much of it is already present:

- **`spa_core/strategy_lab/`** — a pluggable `Strategy` ABC + one backtest harness + one live paper
  service, with sub-packages:
  - `aggressive_lab/` — **already paper-tests the 10–15%+ strategies the desk REFUSES** (roster,
    harness, tail overlay, scorecard, annual-contrast with real dated drawdowns e.g. leverage_loop
    liquidation). This is the master prompt's "Max/Experimental research sleeve," already built.
  - `rates_desk/` — refusal-first fixed/implied-rate carry sleeve (RateSurface → FairValueEngine →
    refusal gate → 4 trade shapes), the validated thesis #1. Emits a hash-chained decision log
    (entries AND refusals). This is the master prompt's "Enhanced Yield + Red Team + APY evidence"
    machinery, already built and live-paper.
  - `rwa_backstop/`, `liquidator/`, `underwriting/` — thesis #2/#3 de-risk probes.
  - `forward_analytics.py` — risk-adjusted scorecard vs the RWA floor (attribution + stress).
- **`spa_core/redteam/`** — a red-team module already exists (master prompt §24).
- **`spa_core/riskwire/`** — measurement-as-a-product (the master prompt's "AI Investment OS"
  measurement thesis), already scaffolded.
- **`spa_core/dfb/`** — risk-first pool screener + no-fork risk overlay (the master prompt's
  "Strategy Discovery / Protocol Card" surface), already built with a public `/board` UI.
- **Two-tier kill, GoLiveChecker (29 criteria), evidenced-track honesty, APY-evidence discipline
  ("evidenced" vs backfill), refusal logs, proof chains** — the master prompt's "APY Evidence
  Standard," "Red Team," and "capital preservation first" principles are already operational culture,
  not aspirational.

**Implication:** this scaffolding run should *formalize and unify* the existing pieces into the
master prompt's vocabulary (Strategy/Protocol/Stablecoin Cards, Yield Lab lifecycle, Capital Tiers,
Discovery Engine, BTC/ETH cycle frameworks, Risk Scoring v2), **not build them from scratch** — and
must explicitly cross-reference the existing modules so future sessions do not duplicate them.

## 3. What is genuinely missing (drives the doc backlog)

| Capability | State | MVP? | Connects to | Risk if ignored |
|---|---|---|---|---|
| Unified **Strategy Card** schema/template | Missing (data lives ad-hoc in strategy_lab) | MVP | strategy_lab, tournament | Strategy knowledge stays implicit/uncomparable |
| **Protocol Card** / **Stablecoin Card** systems | Missing (implicit in adapters + dfb overlay) | MVP | adapters, dfb, defillama_feed | Due-diligence not captured/auditable |
| **Yield Thesis Map** (where yield comes from) | Missing as a doc (knowledge is in code/heads) | MVP | all | No shared map of yield sources/risks |
| **APY Evidence Standard** doc (L0–L6) | Partial (culture exists; not codified) | MVP | golive, evidence calc | Evidence levels inconsistent across surfaces |
| **Risk Scoring v2** (advisory) framework doc | Partial (`analytics`, `risk_scoring_engine`, dfb overlay score) | MVP | dfb overlay, RiskPolicy (advisory only) | New-strategy scoring stays ad-hoc |
| **Capital Tiers Strategy** ($100k→$100M+) | Partial (capital_sweep.py exists) | MVP | optimization, allocator | Scale failure modes undocumented |
| **Strategy Discovery Engine** doc | Partial (dfb, defillama_feed, tournament) | Later | dfb, feeds | Discovery stays manual |
| **BTC Capital Cycle Machine / BTC & ETH frameworks** | Missing (bull_cycle_detector ADR exists) | Later | analysis, feeds | BTC/ETH rotation undocumented |
| **Agent architecture + prompts** (Investment/Builder OS) | Partial (`agents/`, `dev_agents/`, `agent_runtime/`) | MVP prompts | agents | Agent roles/guardrails not standardized |
| **IC workflow / reporting templates** | Partial (`reporting/`) | Later | reporting, family_fund | Decisions not memo-tracked |
| **Data quality / data architecture** docs | Partial (`data_trust/`, `data_pipeline/`) | Later | data_trust | Data-quality gating undocumented |
| **DB schema / API spec / dashboard-expansion** docs | Missing (future) | Much later | api, database | Future build unplanned |
| **External-capital readiness / dangerous-strategies / compliance** docs | Partial (`compliance/`) | Later | compliance | Legal/risk gaps un-catalogued |

## 4. What must be preserved (see `docs/06`)

Deterministic RiskPolicy `v1.0` as the sole hard gate; no LLM in risk/execution/monitoring/kill;
stdlib-first runtime; atomic writes; two-tier kill values (owner/ADR-gated); GoLiveChecker; the
public dashboard/cockpit/board; the runtime `data/*.json` formats; the read-only vs execution domain
split; the evidenced-track honesty; the `spa_core/execution/` no-import rule from read-only code.

## 5. What is unclear / risky (see `docs/31`)

Divergence between the master prompt's greenfield framing and the existing research layer; ADR
numbering collision (existing `docs/adr/ADR-002+` → new ADRs namespaced **ADR-YL-###**); the
relationship between the master prompt's "Yield Lab" and the existing `strategy_lab/`; whether
Risk Scoring v2 should reuse the existing dfb overlay / risk_scoring_engine or be a new advisory
layer; APY-target framing (10–15%) vs the desk's honest edge-at-scale finding (does not beat the
~3.4% RWA floor via yield at fundable scale) — a strategic tension the docs must hold honestly.

## 6. Acceptance

This audit is complete when a future session can, from it alone: (a) locate every load-bearing
module, (b) know which master-prompt capabilities already exist and where, (c) know what is genuinely
missing and in what priority, and (d) avoid duplicating the existing research layer. Cross-reference:
`docs/06_spa_core_invariants.md`, `docs/31_open_questions.md`, `prompts/claude_code/yield_lab_master.md`.
