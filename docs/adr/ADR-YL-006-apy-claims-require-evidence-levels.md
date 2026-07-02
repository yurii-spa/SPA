# ADR-YL-006: APY claims require an evidence level (L0–L6)

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab)                                  |
| **References**  | `docs/37_apy_realism_and_evidence_standard.md`, `docs/06_spa_core_invariants.md` (C.8), `docs/11_strategy_card_system.md` (§3.4), `prompts/claude_code/yield_lab_master.md` (APY evidence levels) |

---

## Context

The desk's credibility depends on never presenting an unverified or backtest APY as if it were live,
observed, or executable. The master prompt and invariant C.8 require that every APY/performance claim
carries an evidence level and a yield-source explanation. Marketing pressure and optimistic backtests
make this easy to violate accidentally.

## Decision

**No APY may be stated, displayed, or recorded without an explicit evidence level (L0–L6) and a
yield-source explanation.**

- Evidence ladder (`docs/37`): **L0** idea/unverified · **L1** historical public APY observed · **L2**
  data-source verified · **L3** paper-tracked · **L4** small-capital tested · **L5** live-capital
  tested · **L6** multi-cycle validated.
- Every APY figure must distinguish **advertised vs observed vs executable vs net vs sustainable vs
  risk-adjusted**, and must show **risk category, source, last-verified date, and yield-source
  explanation**. Paper/backtest is never presented as live.
- On a Strategy Card, `apy_evidence_level` gates how any APY value may be used: no value is treated as
  verified above the level stated. Promotion bars bind to evidence level — e.g. Enhanced requires
  ≥ **L3 (paper-tracked)**, MaxYield requires ≥ **L4 (small-capital tested)** (`docs/11` §5).
- Unknown numbers are written literally as **"TBD — requires verification"**; illustrative examples
  are labelled **"illustrative — requires verification"**. Never invent an APY/TVL number.

## Consequences

- **Positive:** every public and internal APY is honest and self-labelling; a reviewer can trust the
  number only as far as its stated level; the desk cannot accidentally over-claim.
- **Negative / cost:** attractive-looking backtest APYs cannot be surfaced as headline numbers until
  they earn a higher evidence level — slower, honest go-to-market.
- **Neutral:** the "evidenced" go-live track already counts only real daily-cycle-log-backed days
  (C.8); this ADR generalizes that discipline to all APY claims.

## Alternatives considered

- **Show backtest APY with a footnote** — rejected: footnotes are routinely stripped in reuse; the
  evidence level must travel *with* the number as a structured field, not as prose.
- **Only show live APY, hide research figures** — rejected: research needs L0–L2 figures internally;
  the fix is honest labelling, not hiding — presenting them *as* live is what is forbidden.
