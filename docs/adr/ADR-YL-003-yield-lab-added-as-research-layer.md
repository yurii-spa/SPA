# ADR-YL-003: Yield Lab is added as a closed research layer

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab)                                  |
| **References**  | `prompts/claude_code/yield_lab_master.md`, `docs/07_yield_lab_architecture.md`, `docs/11_strategy_card_system.md`, `docs/06_spa_core_invariants.md` (E.16, E.19) |

---

## Context

The founder vision targets 10% minimum / 12–15% target / 15–20% opportunistic annualized return
(stablecoins, BTC, ETH; capital preservation first). SPA Core is deliberately conservative and must
not be diluted into a plain 5–8% optimizer. Higher-yield mechanisms must be discovered, analyzed,
tested, and validated — but never exposed publicly or run live without evidence. A dedicated,
*closed* research layer is needed so higher-risk work happens off the public/live surface.

## Decision

The **Yield Lab** is added as a closed research layer between SPA Core and any public/live exposure:

- It sits in the layered architecture as: SPA Core → **Yield Lab** → AI Investment OS → Builder OS →
  Execution Support (`docs/07`). Default autonomy is **Level 0 (research) / Level 1 (recommendation)**
  only — no execution automation (invariant E.19).
- Every candidate strategy flows through the Yield Lab **lifecycle**
  (`idea → research → rejected / paper_testing → paper_passed → small_capital_testing →
  small_capital_passed → approved_for_{preserve,core,enhanced,max_yield} / frozen / retired`) and is
  recorded as a **Strategy Card** (`docs/11`, `data/strategy_cards/`).
- No candidate becomes an approved Strategy Card without yield-source verification, protocol review,
  stablecoin review (if applicable), liquidity review, advisory Risk Scoring v2, Red Team review, a
  paper-test plan, and **human approval** (invariant E.16, `docs/11` §5).
- The Yield Lab reuses existing research modules (`spa_core/strategy_lab/*`, `spa_core/tournament/*`)
  rather than duplicating their math; it **records and presents**, it does not re-derive risk verdicts.

## Consequences

- **Positive:** higher-yield exploration is possible without endangering the conservative core or
  making unvalidated public claims; promotion becomes a documented checklist, not a judgment call.
- **Negative / cost:** a real evidence bar (paper track + reviews + human sign-off) sits between an
  idea and any live use — intentionally slow.
- **Neutral:** the research layer can hold many candidates in `research`/`paper_testing` indefinitely.

## Alternatives considered

- **Expose higher-yield strategies directly from SPA Core once backtested** — rejected: backtest is
  not evidence of live executability; violates the APY evidence standard (ADR-YL-006) and E.16.
- **No formal layer; ad-hoc research in notebooks** — rejected: loses the durable, comparable,
  auditable Strategy Card record and the honest lifecycle ledger.
