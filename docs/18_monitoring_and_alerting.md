# 18 — Monitoring & Alerting (research-layer alert taxonomy)

> Research-layer document. This is the **alert taxonomy and cadence** the research/decision-support
> layer reasons over — an **advisory** view. It does **not** modify or duplicate the runtime
> monitoring that already exists; it names the triggers, severities, and human-approval boundaries so
> research memos, red-team reviews, and IC discussion share one vocabulary.
> Related: [`06_spa_core_invariants.md`](06_spa_core_invariants.md), [`14_risk_scoring_v2.md`](14_risk_scoring_v2.md)
> (advisory scoring), [`43_dangerous_strategies.md`](43_dangerous_strategies.md),
> [`39_investment_committee_workflow.md`](39_investment_committee_workflow.md).

---

## 0. Scope and boundary

Runtime monitoring **already exists** and is authoritative — do not re-implement it here:

- `spa_core/monitoring/` — `system_health_monitor.py`, `agent_health_monitor.py`,
  `cycle_health_monitor.py`, `peg_monitor.py`, `anomaly_detector.py`,
  `portfolio_health.py`, `threat_reactor.py`, `data_freshness_monitor.py`, gas monitors,
  `resilience_status.py`, `self_heal.py`.
- `spa_core/alerts/` — `red_flag_monitor.py`, `apy_spike_monitor.py`, `apy_drift_alert.py`,
  `risk_monitor.py`, `governance_watcher.py`, `alert_manager.py` / `alert_dispatcher.py` /
  `severity.py`, `telegram_*`.

**Hard boundary (invariants A.2 / A.3):** no LLM in the risk, execution, monitoring, or kill path.
The two-tier kill-switch (`spa_core/governance/kill_switch.py`: SOFT_DERISK at drawdown ∈ [5%,10%);
HARD_KILL at ≥10% inclusive) is deterministic and owner/ADR-gated — nothing in this taxonomy overrides
it. This document is the **research-layer map** onto those existing signals; any alert here that would
gate execution is advisory only and defers to the deterministic runtime.

## 1. Monitoring cadence

| Cadence | Focus | Purpose |
|---|---|---|
| **Real-time / event-driven** | depeg · exploit · withdrawal freeze · bridge failure · oracle failure · liquidation · counterparty failure | Catch fast, capital-threatening events; drive immediate human review and (deterministically) the kill-switch. |
| **Hourly** | APY · TVL · liquidity depth · funding/basis · peg deviation · flows (in/out) | Detect drift and early stress before it becomes an event. |
| **Daily** | portfolio risk · protocol health · strategy performance vs floor | Steady-state risk and attribution review. |
| **Weekly** | Investment-committee (IC) review | Aggregate findings, approvals, refusals, spread-attribution ([`39`](39_investment_committee_workflow.md)). |
| **Monthly** | full report | Performance/attribution + risk posture + evidence-level roll-up ([`41`](41_performance_reporting_methodology.md)). |

## 2. Alert taxonomy

Each alert names: **trigger**, **severity**, **action**, **human-approval** requirement, and
**escalation** path. Severity uses the existing `spa_core/alerts/severity.py` convention
(INFO / WARNING / CRITICAL). "Action" here is the **research/decision-support** response; any capital
effect is deterministic and human-gated, never taken by this layer.

### 2.1 Real-time / event-driven

| Alert | Trigger | Severity | Action (advisory) | Human approval | Escalation |
|---|---|---|---|---|---|
| **Stablecoin depeg** | peg deviation beyond band on a held/candidate asset | CRITICAL | flag position; draft de-risk/exit checklist | Required to act | IC + owner immediately |
| **Protocol exploit** | credible exploit/incident signal on a held/candidate protocol | CRITICAL | freeze candidate; propose exit; open red-team note | Required to act | IC + owner immediately |
| **Withdrawal freeze / queue halt** | redemptions/withdrawals suspended | CRITICAL | mark illiquid; recompute exit horizon | Required to act | IC + owner |
| **Bridge failure** | bridge halt / anomalous state on a cross-chain leg | CRITICAL | flag exposure; propose halt of new cross-chain entries | Required to act | IC + owner |
| **Oracle failure** | stale / diverging oracle vs reference | CRITICAL | distrust affected valuations; flag liquidation risk | Required to act | IC + owner |
| **Liquidation event** | collateral position near/at liquidation | CRITICAL | draft unwind/top-up checklist (human-executed) | Required to act | IC + owner |
| **Counterparty failure** | credit/venue/custodian counterparty distress | CRITICAL | flag counterparty exposure; propose freeze | Required to act | IC + owner |

### 2.2 Hourly

| Alert | Trigger | Severity | Action (advisory) | Human approval | Escalation |
|---|---|---|---|---|---|
| **APY spike/collapse** | APY moves beyond drift band (cf. `apy_spike_monitor` / `apy_drift_alert`) | WARNING→CRITICAL | investigate yield-source change; re-verify evidence level | Not for research note; required for any allocation change | Daily review, IC if persistent |
| **TVL drop** | material TVL decline on held/candidate pool | WARNING | reassess capacity/floor (TVL ≥ $5M invariant) | Required for allocation change | Daily review |
| **Liquidity thinning** | exit depth / slippage worsening | WARNING | recompute exit horizon and size caps | Required for allocation change | Daily review |
| **Funding/basis reversal** | funding or basis flips against a carry sleeve | WARNING→CRITICAL | reassess carry thesis; flag potential refusal | Required to act | IC if thesis breaks |
| **Peg drift (sub-depeg)** | small but persistent peg deviation | WARNING | watch-list; tighten monitoring | — | Escalate to real-time band on breach |
| **Flow anomaly** | abnormal inflow/outflow on protocol | INFO→WARNING | contextualize; watch for exploit/exit precursor | — | Daily review |

### 2.3 Daily

| Alert | Trigger | Severity | Action (advisory) | Human approval | Escalation |
|---|---|---|---|---|---|
| **Portfolio risk breach (advisory)** | advisory risk score / concentration crosses threshold | WARNING | risk memo; propose rebalance for human review | Required to act | IC |
| **Protocol health degradation** | governance / audit / incident signal deterioration | WARNING | update protocol card; reassess tier | Required for tier change | IC |
| **Strategy underperformance vs floor** | sleeve spread over live RWA floor turns negative/unexplained | WARNING | flag for spread-attribution review (ADR-YL-008) | Required to keep/cut | IC |

### 2.4 Weekly / monthly

| Alert | Trigger | Severity | Action | Human approval | Escalation |
|---|---|---|---|---|---|
| **IC review packet** | scheduled weekly | INFO | compile alerts, approvals, refusals, spread-attribution | IC decisions | Owner for out-of-policy items |
| **Monthly report** | scheduled monthly | INFO | full performance/attribution + risk posture + evidence roll-up | Owner sign-off | — |

## 3. Human-approval and escalation principle

- **The research/alert layer never moves capital.** It flags, drafts, and recommends. Every capital
  effect is deterministic (RiskPolicy / kill-switch) and/or human-approved (see
  [`19_execution_support.md`](19_execution_support.md) and [`20_human_in_the_loop_governance.md`](20_human_in_the_loop_governance.md)).
- **CRITICAL** real-time alerts escalate to IC + owner immediately; the deterministic kill-switch acts
  on drawdown independently and is not gated by this taxonomy.
- Advisory scores that trigger red-team or human review derive from [`14_risk_scoring_v2.md`](14_risk_scoring_v2.md)
  and remain advisory (ADR-YL-004) — never a hard gate.

> Never invent thresholds not backed by data; where a concrete band is not yet defined, it is marked
> as **requiring verification** and calibrated against the existing runtime monitors, not guessed.
</content>
