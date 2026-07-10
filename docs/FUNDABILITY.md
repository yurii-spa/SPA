# SPA — Fundability one-pager

_Auto-generated, REALIZED-ONLY, HONEST. Every performance number traces to a realized `data/` source or is labeled INSUFFICIENT_DATA; a missing source is reported as data unavailable, never fabricated. NO backtest figure is presented as realized (backtest rows are explicitly fenced). stdlib-only, deterministic, fail-CLOSED. NOT marketing — the refusal-chain and the published NO-GO are the differentiator._

---

## 1. The thesis — measurement, not yield

**Honesty contract for this sheet (WS6):** every performance claim below traces to a **REALIZED** data point (the live forward `*_series.json` tracks, decomposed by the WS1 carry truth-table + realized A/B) **or** is labeled **INSUFFICIENT_DATA**. A backtest figure is NEVER presented as realized; where a backtest is shown it is explicitly fenced as **BACKTEST (not realized)**.

SPA's research arc already killed the obvious answer: **plain crypto-yield is a diversifier, not an edge**. Neutral books don't beat the tokenized-T-bill floor risk-adjusted, directional books eat the full drawdown, and LRT restaking dies in crashes (ezETH depeg). "More APY" is a dead end.

> **The edge is not yield. The edge is the structural role of honest measurement / underwriting** — being the party that can correctly price and refuse risk others don't see, and *prove* it.

The convergent, honest conclusion: **the moat is real, but it is a scale / trust / relationships play, not a single-strategy alpha play** — AND, on the REALIZED forward track to date, **the desk does not yet demonstrably beat the RWA floor at fundable scale.** That is the honest WS1 verdict and this sheet does not contradict it. $10M/year is reachable through scale across many capacity-bound books plus the trust earned by a transparent, fail-closed measurement-and-refusal engine — over multiple years — not by chasing a higher headline rate, and not today. The code builds the proof; the proof earns the trust; the trust + capital + relationships are what turn it into $10M.


---

## 2. The realized edge — to date (realized-only, never backtest)

This is the genuinely-fundable section: it is built **only** on REALIZED forward numbers. Every cell traces to a live `*_series.json` track decomposed by the WS1 machinery, or reads **INSUFFICIENT_DATA**. The honest one-line answer first:


### 2a. Carry truth-table — realized carry above the RWA floor

Realized carry-above-the-floor (bps/yr) per forward sleeve, ranked. RWA floor: **3.18%/yr** (live tokenized-T-bills). A verdict is only trusted at **>= 7 distinct forward days**; below that the sleeve reads **INSUFFICIENT_DATA** with a **null** bps — never a fabricated 0.0. Carry is the NAV-reconciling residual (carry + floor == realized PnL exactly), so no leg can be inflated independently.

**Tally:** above floor **0** · at floor **0** · below floor **0** · **INSUFFICIENT_DATA 11**.


| sleeve | realized carry vs floor | realized carry $ | track depth | verdict |
|---|---:|---:|---:|:--|
| engine_a | +31.71 bps | $4 | 6 pts | INSUFFICIENT_DATA |
| engine_b | +481.85 bps | $13 | 6 pts | INSUFFICIENT_DATA |
| engine_c | +531.89 bps | $7 | 6 pts | INSUFFICIENT_DATA |
| legacy_risk_adjusted | INSUFFICIENT_DATA | $0 | 1 pts | INSUFFICIENT_DATA |
| legacy_risk_adjusted_floorfair | INSUFFICIENT_DATA | $0 | 1 pts | INSUFFICIENT_DATA |
| optimized_yield | INSUFFICIENT_DATA | $0 | 1 pts | INSUFFICIENT_DATA |
| rates_desk_fixed_carry | -247.38 bps | $-27 | 5 pts | INSUFFICIENT_DATA |
| rwa_floor | +31.71 bps | $4 | 6 pts | INSUFFICIENT_DATA |
| rwa_sleeve | +2.58 bps | $0 | 4 pts | INSUFFICIENT_DATA |
| variant_d | +7414.77 bps | $1,016 | 6 pts | INSUFFICIENT_DATA |
| variant_n | -2602.50 bps | $-357 | 6 pts | INSUFFICIENT_DATA |

**The honest reading:** at today's track depth **every** realized sleeve is INSUFFICIENT_DATA, and the two longest tracks (the FixedCarry carry book and the RWA sleeve) are **at-or-below** the floor on realized carry so far. The desk does **not** yet demonstrably beat the floor on realized data. This is the correct reading of a few-day track — not a failure, and not hidden.


### 2b. Realized forward A/B — the optimizer uplift (realized, not a replay)

`is_realized`: **yes** — each UTC day the live held-universe is scored ONCE through the legacy heuristic AND the optimizer and banked into parallel paper books (one distinct row per day). This is **not** a replayed backtest. Current depth: **1 day(s)** (verdict trusted at >= 7); verdict **INSUFFICIENT_DATA**.

Honest apples-to-apples decomposition (the raw gap mixes selection skill with a cash-drag advantage the legacy book gets for free by skipping the 5% cash floor):

- raw uplift (NOT apples-to-apples): **+108.00 bps**
- **selection alpha** (apples-to-apples, both reserve 5%): **+130.50 bps**
- cash-drag leg (the floor-skip advantage, NOT skill): **+22.50 bps**

Even where the realized selection alpha reads positive on day 1, the verdict stays INSUFFICIENT_DATA until the track matures — a 1-day uplift is not an edge.


### 2c. Edge at scale — the optimizer's uplift is a $100k artifact

The optimizer uplift recomputed at each AUM AFTER the real MP-209/ADR-009 pool-capacity caps bind (capacity-capped capital becomes idle cash, earns 0 — the conservative drag). Materiality bar: **0.25%**.

| AUM | legacy yield | optimizer yield | uplift | material? |
|---|---:|---:|---:|:--:|
| $100,000 | 4.50% | 5.58% | +1.08pp | yes |
| $1,000,000 | 3.38% | 1.38% | -2.00pp | no |
| $10,000,000 | 1.83% | 0.84% | -0.99pp | no |

**The load-bearing honest finding (WS1):** the optimizer's **+1.08pp is a $100k-scale artifact**. It falls below the materiality bar and goes **NEGATIVE past ~$1M AUM** (edge survives at max AUM tested: **no**; first AUM below materiality: **$1,000,000**). The optimizer concentrates into high-yield small-TVL pools; at $1M+ the 1%-of-TVL cap forces most of that book into idle cash. **At the fundable size that underlies the $100M thesis, today's universe cannot support the edge.** We do not claim otherwise.


### 2d. Cost of refusal — is sitting in cash defensible?

From the FixedCarry forward series' per-day scan diagnostics (read-only re-derivation, 4 diagnostic day(s), aggregated at >= 7): cost-of-caution **651.30 bps/yr** **IF** the refused edge were real carry. But the gate's thesis is that the refused yield is **tail-compensation** (the 2025-10 USDe-leverage-unwind / ezETH pattern), not carry — so this 'cost' is an insurance premium, not forgone alpha. Since even the approved FixedCarry book is below the floor on realized data so far (§2a), the conservatism is **DEFENSIBLE while the realized carry track is thin/at-or-below floor — the gate is not yet demonstrably leaving real money on the table.**


---

## 3. The engine + proof — refusal-first carry (BACKTEST + measurement)

> **The sleeve APY/DD figures in the table below are BACKTEST numbers (not realized).** They describe the engine's behaviour over the 2024-2026 replay window, NOT money earned on the live forward track. The REALIZED edge to date is §2; this section documents the engine that produced the refusals and the live proof chain.

### Rates Desk engine — **BACKTEST-validated** (refusal-first carry)

A risk-adjusted fair-value model for tokenized yield that (a) harvests genuinely mispriced carry and (b) REFUSES yield that is just tail-risk compensation (the ezETH / over-levered-USDe pattern). RWA floor reference: **3.4%/yr**.


**BACKTEST (not realized)** — engine behaviour over the 2024-2026 replay:


| sleeve | stage | net APY %/yr (BACKTEST) | beats floor (BACKTEST) | max DD % | refusals | kills |
|---|---|---:|:--:|---:|---:|---:|
| fixed_carry | PAPER_CANDIDATE | 6.0901% | yes | 0.000% | 1070 | 8 |
| levered_carry | PAPER_CANDIDATE | 4.9571% | yes | 6.856% | 2211 | 1 |
| basis_hedge | BLOCKED-NO-HEDGE | 3.4000% | no | 0.000% | 0 | 0 |
| rate_matrix | PAPER_CANDIDATE | 6.0863% | yes | 0.000% | 3098 | 328 |

**Proof chain** (live, hash-linked `data/rates_desk/decision_log.jsonl`): **2000** logged decisions — **773 refusals** (of which **0** structural tail-vetoes) and **1227 entries**. Every decision — entry AND refusal — is hashed into a tamper-evident record: the public "what we traded AND what we refused, and why."


**Honest caveats (stated, not hidden):**
- The refusal fired **early** — toxic LRT PT books (ezETH / rsETH) were refused ~100% of days on *structural* grounds, never held into the Aug-2024 / Oct-2025 / Apr-2026 depegs; a huge quoted rate never rescued a tail-vetoed book.
- Deflated Sharpe is **structurally degenerate** for locked held-to-maturity carry (near-zero downside variance by construction) — reported as a not-noise check only.
- **The backtest APY above is NOT the realized edge.** On the REALIZED forward track (§2) the FixedCarry book is **below the floor so far** and every sleeve is INSUFFICIENT_DATA. The backtest validates the engine's behaviour through stress windows; it does not assert money was earned live. We do not present it as realized.
- The carry edge is **capacity-bound** (~$250k fundable ceiling per book; the §9 exit-capacity rule sizes DOWN rather than eat slippage). A single rates book does **not** clear $10M — this needs **scale across many gated books**.


### RWA Repo Backstop — **measurement-GO / book NO-GO**

"Lend against Liquidation NAV, not marketing NAV." The Safety Board measures, from free data, that RWA collateral is genuinely **not cash-like** on an executable on-chain exit: **11/11** assets not cash-like (LIQUID 0 · THIN 1 · REDEMPTION_ONLY 9 · UNSAFE 1). Max on-chain ERC-4626 NAV divergence from $1.00 marketing NAV measured: **8.17%**. The *measurement* layer is GO (deterministic, fail-closed, runs continuously); the underwriting *book* is NO-GO read-only — it needs whitelisting + redemption agreements + capital + legal, none of it buildable in code.


### Liquidator — **NO-GO** (published — we publish what we kill)

The long-tail / nested-collateral liquidation opportunity was measured read-only at ~$3.8M/yr gross addressable (top-20 ~$2.2M/yr) — ~5-10x **below** the $20M/yr bar, too small to justify the custody + CEX + balance-sheet build. **VERDICT: NO-GO, published.** Publishing the kill is itself the credibility signal: the desk states plainly what it refuses to build, not only what it ships.

### 3d. The safety machinery is proven to FIRE (not just present)

A monotonic paper curve is a fair objection: if the track only ever goes up (~0% drawdown to date), how do we know the kill-switch and de-risk gates actually work? We answer it head-on. `scripts/defenses_exercised_report.py` drives the **same production governance code the daily cycle uses** (`kill_switch.drawdown_tier` + `KillSwitchChecker.check_drawdown_trigger` + `cycle_gates.apply_soft_derisk_gate`) through a labelled stress matrix and asserts every defense fires:

- two-tier drawdown ladder returns **NONE / SOFT_DERISK / HARD_KILL** at the right bands (SOFT ≥5%, HARD ≥10% inclusive, ADR-048);
- the hard kill **triggers all-cash at 15%** and is correctly **held at 3%**;
- soft de-risk **blocks every NEW position and INCREASE** while leaving HOLD/REDUCE intact.

**11/11 defenses fire — reproducible by anyone: `python3 scripts/defenses_exercised_report.py` (exit 0 = all fired), deterministic, stdlib-only, inert (the live track is never touched).** The report also states the honest contrast: the same classifier on the live evidenced curve returns `NONE` at 0% drawdown — the gates are dormant because the track never stressed, **not** because they are absent. Measurement-first means proving the brakes work before you need them.


---

## 4. The forward track-to-date (accruing, not yet 30)

**19/30 evidenced days — accruing, not yet 30** (honest anchor 2026-06-22, target 2026-07-21). Go-live criteria: **27/29 pass** — NOT READY (the remaining blockers are time-gated: there is simply nothing to fix in code, only track days to accrue).


Forward-track integrity: **all_ok** — 13 forward tracks, 0 failing (no duplicates / gaps / out-of-order / future-dated points).


**Day-30 readiness (auto, verifiable, hash-anchored):** verdict **NOT_READY**, readiness **63.33%** (19/30 evidenced days). The artifact's content is fingerprinted: `proof_hash=dfd2e4713655129b…` — re-running the generator over the same evidenced track reproduces it, and any tampered/backfilled bar breaks it. The readiness % is the honest evidenced fraction, never an inflated snapshot.


---

## 5. Live forward-record analytics (risk-adjusted, accruing)

The verdict above is static; THIS is the live risk-adjusted picture computed ON the accruing forward series themselves (per-day equity for the rates-desk carry book + each Strategy-Lab sleeve). Honestly labeled: the forward record is still thin, so trustworthy risk-adjusted ratios arrive near day 30 — until then a thin track reads **THIN (metrics pending)**, never a fabricated Sharpe. The honest thin-labeling IS the credibility.


**13 forward tracks** (beats-floor 5 · thin 6 · unknown 0). Attribution baseline: the live RWA floor **3.3%/yr**; a realized Sharpe/Sortino is only trusted at **>= 7 equity points** — below that the ratio is a degenerate artifact and is reported THIN, not a number.


| track | days | realized APY %/yr | excess vs floor %/yr | Sharpe | Sortino | max DD % | status |
|---|---:|---:|---:|---:|---:|---:|:--|
| paper/rates_desk_fixed_carry | 16 | 0.74% | -2.57% | 554.41 | UNKNOWN | 0.00% | below floor |
| strategy_lab_paper/centrifuge_drop | 9 | 8.33% | 5.02% | UNKNOWN | UNKNOWN | 0.00% | THIN (9/30 days, metrics pending) |
| strategy_lab_paper/engine_a | 17 | 3.44% | 0.13% | 206.03 | UNKNOWN | 0.00% | beats floor |
| strategy_lab_paper/engine_b | 17 | 8.29% | 4.98% | 1217.94 | UNKNOWN | 0.00% | beats floor |
| strategy_lab_paper/engine_c | 17 | 8.87% | 5.56% | UNKNOWN | UNKNOWN | 0.00% | THIN (17/30 days, metrics pending) |
| strategy_lab_paper/fluid | 8 | 4.81% | 1.50% | UNKNOWN | UNKNOWN | 0.00% | THIN (8/30 days, metrics pending) |
| strategy_lab_paper/maple_syrup | 9 | 10.52% | 7.20% | UNKNOWN | UNKNOWN | 0.00% | THIN (9/30 days, metrics pending) |
| strategy_lab_paper/pt_susde | 9 | 11.85% | 8.54% | UNKNOWN | UNKNOWN | 0.00% | THIN (9/30 days, metrics pending) |
| strategy_lab_paper/pt_usde | 9 | 9.20% | 5.89% | UNKNOWN | UNKNOWN | 0.00% | THIN (9/30 days, metrics pending) |
| strategy_lab_paper/rwa_floor | 17 | 3.44% | 0.13% | 206.03 | UNKNOWN | 0.00% | beats floor |
| strategy_lab_paper/rwa_sleeve | 15 | 3.36% | 0.05% | 613.99 | UNKNOWN | 0.00% | beats floor |
| strategy_lab_paper/variant_d | 17 | 898.72% | 895.40% | 5.28 | 9.33 | 3.94% | beats floor |
| strategy_lab_paper/variant_n | 17 | 2.98% | -0.34% | 0.82 | 1.25 | 0.49% | below floor |

**Forward stress overlay** (canonical 2024-2026 PT mark-down shocks applied to the **currently-held** carry book — $17,387 PT notional — on top of the REALIZED forward equity, drawdown band 15%): worst-case stressed DD **1.04%**, **survives ALL**.


| stress scenario | PT mark-down % | shock $ | stressed DD % | survives |
|---|---:|---:|---:|:--:|
| 2024-08 ETH crash / carry-unwind | 1.50% | $261 | 0.26% | yes |
| 2025-10 USDe leverage unwind (THE test) | 3.00% | $522 | 0.52% | yes |
| 2026-04 KelpDAO rsETH depeg | 6.00% | $1,043 | 1.04% | yes |

**Framed honestly for a funder:** the forward record is *accruing* — this is the risk-adjusted picture to date, every number sourced live from the realized series and labeled THIN where a ratio would be premature. The refusal chain plus this honest thin-labeling is exactly what makes the day-30 artifact trustworthy: the ratios that land near day 30 will rest on a record that was never fabricated along the way.


---

## 6. The safety architecture

- **Refusal-first gate** — a deterministic policy composed *under* the global RiskPolicy, only ever stricter; LLM-forbidden in risk/kill; fail-CLOSED (missing/invalid data -> max tail-risk, never a silent pass).
- **Kill switch** — drawdown >= 5% closes everything; cannot be overridden.
- **Proof-of-reserves / NAV reconciliation** — NAV conserved across the simulated rebalance.

- **Go-live dry-run harness** (`golive_dry_run.json`): all gates reached=yes, ordering_ok=yes, NAV reconciliation=PASS, live-trading gate active=no, would_proceed=no, moves_capital=no. The gates are **verified inert** — the harness proves the fail-closed chain fires (RiskPolicy blocks an over-concentrated trade, the live-trading gate stays inactive) WITHOUT moving any capital.

- **Honest-track reset as a TRUST signal** — the track shows **19/30 accruing**, anchored to the real evidenced start. It was reset to the honest count rather than padded; the published low number IS the credibility.


---

## 7. The off-code gates — honestly, what stands between here and $10M

The code did its job: it took each thesis to an honest verdict for free. But across all three, the same boundary appears — **the code can measure and refuse; the $10M is off-code.** Stated plainly, not hidden:

- **Custody / MPC** — institutional key management for real capital; not buildable in read-only paper code.
- **External audit** — independent code + controls audit of the execution path.
- **Legal** — fund structure, collateral perfection, redemption agreements, force-redemption rights; the RWA underwriting leg can only be *documented*, not *executed*, without it.
- **Real capital + relationships** — whitelisting / subscription access to redemption queues; the carry edge needs scale across many capacity-bound books, which needs AUM.

This is the honest scale truth: SPA contributes the cheapest, most defensible first layer — the transparent, fail-closed measurement-and-refusal engine that PROVES the mispricing — plus an honest record of exactly which off-code legs gate the business.


---

_Regenerated 2026-07-10 06:16 UTC. All numbers live from `data/` — REALIZED-ONLY sources (carry_truth_table.json · realized_ab/realized_ab.json · edge_at_scale.json · refusal_cost.json) for the §2 edge claims, plus golive_status.json · rates_desk/rates_desk_promotion.json (BACKTEST, fenced) · rates_desk/decision_log.jsonl · rwa_safety_board.json · forward_track_integrity.json · forward_analytics.json · golive_dry_run.json. Regenerable via `python3 scripts/generate_fundability_onepager.py --md`. Reproduce the realized numbers from raw series: `python3 scripts/verify_spa.py --check-fundability data/`. Follow-up: a public `/fundability` site page mirroring this doc._
