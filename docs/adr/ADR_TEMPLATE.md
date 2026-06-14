# ADR-XXX: [Short Decision Title]

| Field            | Value                          |
|------------------|--------------------------------|
| **Date**         | YYYY-MM-DD                     |
| **Status**       | Proposed / Approved / Rejected / Superseded by ADR-XXX |
| **Author**       | [Name]                         |
| **Approved by**  | [Owner name] on YYYY-MM-DD     |
| **Policy ver.**  | vX.Y (if risk policy change)   |
| **ADR number**   | ADR-XXX                        |

---

## Context

_What problem or situation prompted this decision? What constraints existed?
Describe the current state and why a decision was needed._

---

## Decision

_What was decided? Be specific and unambiguous. Include the exact parameter values
or code changes if this is a risk policy ADR._

### Changes to RiskConfig (if applicable)

| Parameter | Old value | New value | Rationale |
|-----------|-----------|-----------|-----------|
| `param_name` | `old` | `new` | Why |

---

## Rationale

_Why was this decision made over alternatives? What tradeoffs were considered?_

### Alternatives Considered

- **Option A** — [description]: rejected because [reason]
- **Option B** — [description]: rejected because [reason]

---

## Consequences

### Positive
- [Expected benefit]

### Negative / Risks
- [Known downside or risk]

### Neutral
- [Side effect that is neither good nor bad]

---

## Paper Test Plan (for risk policy changes)

| Item               | Value                        |
|--------------------|------------------------------|
| Start date         | YYYY-MM-DD                   |
| Minimum duration   | 2 weeks                      |
| Go-live target     | YYYY-MM-DD                   |
| Success criteria   | [e.g. Sharpe > 0.5, max DD < 3%] |
| Monitoring         | [what to watch daily]        |

**Paper Test Status:** Not started / In progress / Passed / Failed

---

## Paper Test Results

_Fill in after paper testing completes._

| Metric            | Result | Pass? |
|-------------------|--------|-------|
| Sharpe ratio      |        |       |
| Max drawdown      |        |       |
| Total return      |        |       |
| Policy violations |        |       |

---

## Rollback Plan

If this change needs to be reverted:

1. Load the previous `RiskConfig` values from `spa_core/risk/versions/<previous_version>.py`
2. Update the defaults in `spa_core/risk/policy.py`
3. Bump `version` and `version_date` fields in `RiskConfig`
4. Create a new ADR documenting the rollback (reference this ADR)
5. Owner sign-off → merge

Previous version snapshot: `spa_core/risk/versions/<previous_version>.py`

---

## References

- Previous ADR: [ADR-XXX](./ADR_XXX_title.md)
- Policy file: [`spa_core/risk/policy.py`](../../spa_core/risk/policy.py)
- Snapshot: [`spa_core/risk/versions/vX_Y_name.py`](../../spa_core/risk/versions/)
- Strategy passport: `SPA/01_Docs/Strategy_Passport_*.md`
