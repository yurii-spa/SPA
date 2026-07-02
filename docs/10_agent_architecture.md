# 10 — Agent Architecture (AI Investment OS + Builder OS)

> **No autonomous agents run in production.** This is **prompts + schemas + architecture only**,
> default autonomy **L0 (research) / L1 (recommendation)**. Every agent is decision-support: it
> produces documents/scores/memos for humans, never execution. Build on existing
> `spa_core/{agents,dev_agents,agent_runtime,redteam}`. Universal FORBIDDEN (all agents): hold
> keys/seeds, sign, move funds, bypass/weaken RiskPolicy, override hard gates, change allocation
> without human approval, run autonomous execution, alter strategy logic silently, present unverified
> APY as verified, write secrets to files. Universal error mode: on missing/stale/unverified input →
> emit UNKNOWN / abstain, never fabricate. All outputs are advisory; storage in NEW research dirs
> (never runtime `data/*.json`).

## AI Investment OS — 16 agents

| # | Agent | Role / goal | Inputs | Outputs | Downstream | Allowed | Agent-specific FORBIDDEN | Validation / error | Human approval | Frequency | Storage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Chief Investment** | Synthesize a house view + allocation *recommendation* | All agent outputs, Risk Scoring, IC memos | House-view memo, allocation proposal | IC / owner | Recommend | Decide/execute allocation | Conflicting inputs → flag, no auto-resolve | **Required** for any proposal | Weekly | research memos dir |
| 2 | **Stablecoin Yield** | Find/analyze stablecoin yield mechanisms (≥10%) | DeFiLlama feed, protocol data, Stablecoin Cards | Candidate list, yield-source notes | Yield Lab, Chief Investment | Research | Claim APY without evidence | Unverifiable APY → L0/UNKNOWN | Start of paper test | Daily | candidates dir |
| 3 | **BTC Cycle** | BTC capital-cycle *decision-support* (accumulate/rotate) | Price/on-chain/macro feeds | Cycle-state read, ladder suggestion | Chief Investment | Research | Auto-trade / signal execution | Feed gap → UNKNOWN | Recommendation only | Daily | btc research dir |
| 4 | **ETH Yield** | ETH staking/restaking/yield DD | LST/LRT feeds, protocol data | ETH yield map, risk notes | Yield Lab | Research | Present restaking points as realized yield | Depeg/slashing modeled explicitly | Start of paper test | Daily | eth research dir |
| 5 | **Market Regime** | Classify regime (risk-on/off, funding, vol) | Funding/vol/rate feeds | Regime label + confidence | All | Research | Drive execution directly | Insufficient history → UNKNOWN | Advisory | Daily | regime dir |
| 6 | **DeFi Protocol** | Protocol due diligence → Protocol Cards | Docs, audits, TVL, governance | Protocol Card | Yield Lab, Risk | Research | Approve protocol for live use | Missing audit → hard-flag | Card review before paper | On demand | protocol cards dir |
| 7 | **Smart Contract Risk** | Contract/exploit/upgrade risk | Audits, upgradeability, incident history | Contract-risk score (advisory) | Risk Scoring, Red Team | Research | Be a hard gate | Unknown upgradeability → red | Advisory | On demand | risk scoring dir |
| 8 | **Stablecoin Risk** | Peg/backing/redemption/depeg risk | Reserves, peg history, redemption terms | Stablecoin Card + depeg scenarios | Yield Lab, Red Team | Research | Certify a peg as safe | Opaque backing → hard-flag | Card review | On demand | stablecoin cards dir |
| 9 | **Liquidity** | Exit-liquidity / capacity / slippage by size | Pool depth, exit-NAV models | Liquidity/capacity report | Capital Allocation, Tiers | Research | Ignore capacity at scale | Thin depth → cap recommendation | Advisory | On demand | liquidity dir |
| 10 | **On-chain** | On-chain signals (flows, utilization, whales) | RPC/indexer/DeFiLlama | On-chain signal notes | Regime, Discovery | Research | Fabricate on-chain facts | Missing data → UNKNOWN | Advisory | Daily | onchain dir |
| 11 | **News & Narrative** | Narrative/catalyst/incident scan | News, governance forums | Narrative digest (sourced) | Chief Investment, Red Team | Research | Present rumor as fact | Uncited claim → dropped | Advisory | Daily | news dir |
| 12 | **Quant & Backtesting** | Backtest candidates on real history | Historical feeds, backtest harness | Backtest report (net, risk-adj) | Yield Lab, IC | Research | Present backtest as live (L3+) | Mock data → flag degenerate metrics | Before paper | On demand | backtest dir |
| 13 | **Red Team** | Adversarial teardown (how we lose money) | Candidate + all cards | Red-Team memo answering the mandatory questions | Yield Lab, IC | Research | Approve anything | Any unanswered failure mode → block | **Mandatory** for Enhanced/Max/etc. | Per candidate | redteam dir |
| 14 | **Capital Allocation** | Size *recommendations* within caps | Tiers, caps, Risk Scoring | Sizing proposal | IC / owner | Recommend | Set allocation live | Cap breach → reject own proposal | **Required** | Weekly | allocation dir |
| 15 | **Portfolio Monitoring** | Watch approved sleeves for drift/breach | Live paper track, red-flag monitor | Alerts, drift report | Reporting, owner | Research/alert | Trigger kill / de-risk itself | Kill path stays deterministic | Alert only | Continuous (paper) | monitoring dir |
| 16 | **Reporting** | IC memos, performance/attribution reports | Track, attribution, cards | Reports/memos with evidence levels | Owner / IC / investors | Research | Publish unverified numbers | Missing evidence → mark UNKNOWN | Review before publish | Scheduled | reports dir |

## Builder OS — 9 agents

| # | Agent | Role / goal | Inputs | Outputs | Downstream | Allowed | FORBIDDEN | Validation / error | Human approval | Frequency | Storage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Documentation** | Keep docs current with behavior | Code, docs, ADRs | Doc updates | All sessions | Edit docs | Change runtime code | Drift → flag | Review | On change | docs/ |
| 2 | **Architecture** | Review designs vs invariants | Proposals, `docs/06` | Architecture review | Owner | Review/recommend | Approve invariant changes | Invariant conflict → block | Required | On proposal | docs/adr |
| 3 | **Code Planning** | Turn backlog into stepwise plans | `docs/29`, code | Task plan + CC prompt | Sessions | Plan | Implement runtime/exec | Missing deps → flag | — | Per task | plans dir |
| 4 | **Backlog** | Maintain/prioritize `docs/29` | Docs, findings | Backlog updates | Sessions | Edit backlog | Reprioritize owner-gated silently | Dep cycle → flag | Review | Weekly | docs/29 |
| 5 | **QA** | Tests + suite green | Code, tests | Test additions, results | Release | Add tests | Mutate live track | Live `data/` write → block | — | Per change | tests/ |
| 6 | **Security Review** | Scan for secrets/keys/exec bypass | Diffs, config | Security review | Owner | Review | Ship on unresolved finding | Secret in file → hard-block | Required | Per change | security dir |
| 7 | **Data Quality** | Gate research inputs | Feeds, `data_trust/` | DQ report | Investment agents | Research | Trust stale/invalid data | Stale → UNKNOWN | Advisory | Continuous | dq dir |
| 8 | **Release Manager** | Coordinate safe changes | Diffs, CI | Release checklist | Owner | Plan | Deploy dashboard/prod | Deploy scope → STOP-ask | **Required** | Per release | release dir |
| 9 | **Technical Debt** | Track/prioritize debt | Code, audits | Debt register | Backlog | Research | Big-bang refactor | Rewrite temptation → split | — | Weekly | debt dir |

## Existing code to build on

`spa_core/agents/` (chief/strategy/risk_sentinel/protocol_research/reporting/tester/… classes),
`spa_core/dev_agents/` (architect, tester), `spa_core/agent_runtime/` (runtime, budget, **mandate**),
`spa_core/redteam/` (scenarios, registry, runner). New per-agent prompt templates go in
`docs/agent_prompts/`. Autonomy stays L0/L1; nothing here is wired to execution.

**Cross-reference:** `docs/06`, `docs/07`, `docs/14` (Risk Scoring v2), `docs/29`, `docs/39` (IC).
