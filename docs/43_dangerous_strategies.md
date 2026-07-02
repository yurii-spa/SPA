# 43 — Dangerous Strategies (§42)

**Status: STUB.** This document is a Priority-3 placeholder listing strategy *patterns the desk
refuses or approaches with extreme caution*. Each entry is a one-line "why dangerous" only;
per-strategy red-team depth is deferred. Capital preservation is the governing principle
(charter): the desk refuses risk-compensation yield it cannot justify.

**Scope discipline.** Advisory research catalogue. Refusal culture is already load-bearing in
`spa_core/redteam/` and the refusal logs (`06_spa_core_invariants.md`, invariant C-9). This document
formalizes the pattern list; the deterministic RiskPolicy remains the hard gate.

**Cross-references:** `docs/14_risk_scoring_v2.md` (advisory scoring), `docs/07_yield_lab_lifecycle.md`
(red-team gate), `spa_core/redteam/`, existing refusal logs.

## Dangerous strategy patterns (one line each — expand later)

- **Unaudited high-APY vaults** — no audit means unknown exploit surface behind an attractive yield.
- **Unknown / algorithmic stablecoins** — reflexive peg mechanics can collapse to zero.
- **Weak-bridge assets** — bridge exploit or freeze can zero the wrapped asset.
- **Leverage loop without a liquidation model** — cannot bound loss if you cannot model liquidation.
- **Opaque CeFi yield** — undisclosed counterparty/rehypothecation; withdrawal-freeze risk.
- **Admin-key protocols** — upgradeable/admin-controlled contracts can drain or change terms.
- **Illiquid pools** — exit slower/worse than entry; slippage and stuck capital.
- **Points farming with unclear value** — reward has no verifiable cash value; speculative.
- **Emissions-only yield** — APY funded by token emissions, not real revenue; not sustainable.
- **Rehypothecated lending** — collateral reused elsewhere; hidden chain of counterparty risk.
- **Long-lockup with unclear exit** — capital trapped; no reliable redemption path.
- **Hidden short-vol structured products** — sells tail risk for steady premium; blows up in stress.
- **CEX-concentrated delta-neutral** — counterparty/custody concentration on a single exchange.
- **Undercollateralized lending** — default risk not covered by collateral; credit exposure.
- **Single-custodian BTC yield** — one custodian failure zeroes the position.
- **Opaque market-making** — undisclosed strategy/inventory risk; cannot underwrite the loss modes.
- **Options-as-income without tail analysis** — premium income masks unbounded/large tail loss.
- **APY paid in illiquid tokens** — headline yield cannot be realized at quoted value.
- **Recursive leverage on correlated collateral** — correlation breaks the model; cascading liquidation.
- **Brand-new protocol with high APY** — no track record; incentives + unproven code + exploit risk.

TODO: expand at MVP 2-3 stage. (Per-strategy red-team detail to be expanded per entry at MVP 2-3.)
