# 07 — Yield Lab Architecture

> The Yield Lab is the closed research layer where SPA **searches for, tests, rejects, validates, and
> graduates** strategies before any public or live exposure — the place the system looks for
> **≥10–15%** with **capital preservation first**. This doc **formalizes existing modules into one
> lifecycle vocabulary; it is not a rebuild.** Preserve `docs/06` invariants throughout.

## 1. Purpose

Research → test → reject → validate → graduate. A candidate yield mechanism enters as an idea and
either dies with a documented reason or graduates into a product line with evidence. Nothing reaches
Enhanced/Max/Experimental or live capital without yield-source verification, protocol + stablecoin
review, liquidity review, Risk Scoring v2 (advisory), Red Team review, a paper-test plan, and
**human approval**.

## 1a. Mandate — spread over the floor, every point risk-explained (ADR-YL-008)

The Lab's approve/reject logic has one source of truth (`docs/adr/ADR-YL-008`, resolves OQ-1):

> Systematically search for **fundable 10–15%** strategies, but **every point of spread over the live
> RWA floor** (≈3.4%, **dynamic from `data/rwa_feed.py`, never hardcoded**) **must be explained by a
> specific accepted, measurable risk**. **Unexplained spread ⇒ REJECT.** Rejection is a **positive
> result recorded in the refusal log.** The **RWA floor is the official baseline** — Enhanced/Max
> strategies are judged as **spread over the floor**, not as absolute APY.

Operationally: `spread = sustainable/observed APY − live floor`; the priced, accepted risks must sum
to explain the whole spread; any **residual (unexplained) spread is treated as unpriced tail risk**,
not alpha, and blocks advancement. This gate composes **under** RiskPolicy `v1.0` (only stricter). The
per-status table below inherits this rule — read every "exit → next" and "auto-fail" through it, and
see the added spread fields on the Strategy Card (`docs/11`), the advisory `spread_attribution_score`
(`docs/14`), and the mandatory red-team spread check (`prompts/agents/red_team_agent.md`).

## 2. What already exists (do not duplicate — see docs/02 §2)

| Existing module | Lifecycle role it already plays |
|---|---|
| `strategy_lab/aggressive_lab/` | Paper-tests the refused 10–15%+ strategies (roster, tail overlay, dated-drawdown contrast) → the **Max/Experimental** research sleeve. |
| `strategy_lab/rates_desk/` | Refusal-first fixed-rate carry, live-paper, **hash-chained decision log (entries + refusals)** → **Enhanced + Red Team + APY-evidence** machinery. |
| `strategy_lab/{rwa_backstop,liquidator,underwriting}/` | Thesis de-risk probes (measurement-GO / NO-GO verdicts). |
| `strategy_lab/promotion.py`, `tournament/tournament_engine.py` | Promotion ladder backtest → paper → live → the **status transitions** below. |
| `redteam/`, `riskwire/`, `dfb/`, `compliance/` | Red-team scenarios, measurement facade, pool screener, compliance surface. |

The lifecycle below is the **shared vocabulary** these map onto; it does not replace their code.

## 3. Status lifecycle

```
idea → research → rejected
                → paper_testing → paper_passed → small_capital_testing → small_capital_passed
                → approved_for_{preserve, core, enhanced, max_yield}
                → frozen → retired
```

Per-status contract (entry / exit / evidence / approval / reports / review / min duration / max
allocation / auto-fail):

| Status | Entry criteria | Exit → next | Required evidence | Human approval | Required reports | Risk + Red-Team | Min duration | Max allocation | Auto-fail conditions |
|---|---|---|---|---|---|---|---|---|---|
| **idea** | Candidate logged (from discovery / manual) | Analyst picks up → research | L0 (unverified) | none | Strategy Card stub | none | — | 0 | — |
| **research** | Yield-source hypothesis written | Yield source verified + data source found → paper_testing; else → rejected | L1→L2 (public/observed APY, source verified) | none | Strategy Card, Yield Thesis entry, Protocol/Stablecoin Card | Risk Scoring v2 (advisory) draft | — | 0 | Yield source cannot be explained; no verifiable data source; hard-reject risk flag |
| **rejected** | From research/any review with a failing reason | terminal (may reopen with new evidence) | reason documented | none | Rejection note (why we lose money / why yield disappears) | Red-Team summary if triggered | — | 0 | — |
| **paper_testing** | Paper-test plan approved | Meets pass thresholds → paper_passed; breaches → rejected/frozen | L3 (paper-tracked) | analyst sign-off to start | Paper-test plan + daily result log | **Red Team mandatory** for Enhanced/Max/Experimental/leverage/credit/counterparty/bridge/opaque/new-stablecoin/lockup/options/basis | **≥30 evidenced days** | 0 (paper) | Drawdown past tier limit; depeg/exploit/freeze event; yield-source assumption falsified; evidence gap |
| **paper_passed** | Thresholds met over min duration | IC decides → small_capital_testing | L3 verified | analyst + reviewer | Paper results report | Red Team closed | — | 0 | Regression on re-test |
| **small_capital_testing** | IC memo + human approval to fund a small sleeve | Meets thresholds → small_capital_passed; breach → frozen | L4 (small-capital tested) | **owner/IC approval (mandatory)** | Small-capital test report + live monitoring | Red Team re-review at scale | tier-defined (e.g. ≥14 live days) | **capped small sleeve** (per `docs/34` tier caps) | Execution slippage/queue worse than modeled; drawdown breach; counterparty event |
| **small_capital_passed** | Thresholds met | IC → approved_for_* | L4→L5 | owner/IC | Validation report | — | — | small | — |
| **approved_for_{preserve, core, enhanced, max_yield}** | IC approval + product-line fit | May be re-tiered / frozen / retired | L5+ (line-appropriate) | **owner/IC per line** | IC memo; ongoing monitoring + reporting | Periodic Red-Team re-review (Enhanced/Max) | — | per product-line + capital-tier caps | Sustained underperformance; risk-flag; invariant conflict |
| **frozen** | Risk flag, breach, or pause decision | Un-freeze (review) or → retired | reason + snapshot | reviewer | Freeze note | Red-Team if risk-driven | — | held only, no increase | — |
| **retired** | Superseded / capacity gone / thesis dead | terminal | lessons-learned | reviewer | Retirement + Lessons report | — | — | 0 | — |

**Notes.** Product lines & their ranges live in `docs/34` (Preserve 4–7 / Core 7–10 / Enhanced 10–13
/ Max 13–18 / Experimental 18–25+). Capital tiers change allowed strategies + max allocation. All new
research strategies default `IS_ADVISORY=True` and move **no** live capital.

## 4. What the Yield Lab supports

Candidates; Strategy Cards; Protocol Cards; Stablecoin Cards; paper testing; small-capital testing;
results reporting; Risk Scoring v2 (advisory) + Red-Team reviews; ranking (tournament/promotion);
product-line proposals; IC memos; lessons-learned; retirement records. Each artifact type gets its
own schema/template doc (`docs/11–16`, `docs/39`, `docs/41`) — this doc is the lifecycle spine that
binds them.

## 5. Guardrails

Advisory only (L0/L1 autonomy); RiskPolicy `v1.0` remains the sole hard gate and is never
approached; no APY presented without an evidence level; every graduation step requires the named
human approval; card/evidence data lives in **NEW** directories, never in runtime `data/*.json`.

**Cross-reference:** `docs/02` (audit), `docs/06` (invariants), `docs/10` (agents), `docs/11–14`
(cards + risk scoring), `docs/34` (tiers), `docs/37` (evidence), `docs/29` (backlog).
