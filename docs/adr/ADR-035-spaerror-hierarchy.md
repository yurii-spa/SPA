# ADR-035: SPAError Exception Hierarchy

**Date:** 2026-06-20  
**Status:** Accepted  
**Sprint:** v10.71 (MP-1456)  
**Deciders:** SPA Engineering

---

## Context

The SPA codebase used bare `Exception`, `ValueError`, `RuntimeError`, and `IOError`
throws without a unified error taxonomy. This makes error handling inconsistent:
callers cannot distinguish between a risk policy violation and a network timeout.

In v10.x sprints, a systematic audit found **78 bare `raise Exception(...)` calls**
and **34 modules** with mixed exception types for similar error conditions.

## Decision

Implement a **SPAError hierarchy** in `spa_core/exceptions.py`:

```python
class SPAError(Exception):
    """Base exception for all SPA system errors."""
    code: str = "SPA_UNKNOWN"

class AdapterError(SPAError):
    """Data adapter fetch/parse failures."""
    code = "SPA_ADAPTER"

class RiskPolicyError(SPAError):
    """Risk policy gate rejection."""
    code = "SPA_RISK"

class DataIntegrityError(SPAError):
    """JSON schema violations, missing required fields."""
    code = "SPA_DATA"

class ExecutionError(SPAError):
    """Live trading execution failures (execution domain only)."""
    code = "SPA_EXEC"

class LiveTradingForbiddenError(SPAError):
    """Raised when live trading is attempted before gate unlocks."""
    code = "SPA_GATE"

class ConfigError(SPAError):
    """Configuration or environment variable errors."""
    code = "SPA_CONFIG"

class AtomicWriteError(SPAError):
    """File write failures during atomic save."""
    code = "SPA_WRITE"
```

### Error Catalog

Each error code maps to a runbook entry in `docs/ERROR_CATALOG.md`:

| Code | Severity | Auto-recover? | Alert? |
|------|----------|---------------|--------|
| SPA_ADAPTER | WARN | Yes (retry×3) | No |
| SPA_RISK | INFO | N/A (by design) | No |
| SPA_DATA | ERROR | No | Yes |
| SPA_EXEC | CRITICAL | No | Yes |
| SPA_GATE | CRITICAL | No | Yes (block) |
| SPA_CONFIG | FATAL | No | Yes |
| SPA_WRITE | ERROR | No | Yes |

### Migration

Batch migration across 13 files (v10.51–v10.62):
- `spa_core/adapters/*.py`: `AdapterError`
- `spa_core/risk/policy.py`: `RiskPolicyError`
- `spa_core/golive/activate.py`: `LiveTradingForbiddenError`
- All data readers: `DataIntegrityError`

## Consequences

**Positive:**
- Callers can `except RiskPolicyError` vs `except AdapterError` distinctly
- Monitoring can alert on SPA_EXEC/SPA_GATE while suppressing SPA_ADAPTER
- Error codes enable structured logging and dashboards

**Negative:**
- Migration requires touching many files (done in phases)
- Existing `except Exception` catches must be narrowed (linting task)

## Implementation Status

- `spa_core/exceptions.py`: ✓ created (MP-1360)
- Batch 1–5 migration: ✓ completed in v10.x sprints (78 files total)
- `docs/ERROR_CATALOG.md`: ✓ created (MP-1362)

## Related ADRs

- ADR-034: Atomic write centralization (companion)
- ADR-036: BaseAnalytics migration
