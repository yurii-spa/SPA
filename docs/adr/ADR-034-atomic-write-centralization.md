# ADR-034: Centralized Atomic Write via `spa_core/utils/atomic.py`

**Date:** 2026-06-20  
**Status:** Accepted  
**Sprint:** v10.71 (MP-1456)  
**Deciders:** SPA Engineering

---

## Context

An audit in v10.x sprint series revealed **254 copies** of identical atomic write
patterns scattered across `spa_core/`:

```python
# Pattern found 254 times:
fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
try:
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
except Exception:
    os.unlink(tmp)
    raise
```

This duplication creates maintenance risk: a bug fix in one copy doesn't propagate
to others. A race condition or exception handling error in any copy can corrupt
`data/*.json` state files.

## Decision

Centralize all atomic write operations in **`spa_core/utils/atomic.py`**:

```python
# spa_core/utils/atomic.py
def atomic_save(data: dict | list, path: str | Path, indent: int = 2) -> None:
    """Write JSON atomically: tmp file → os.replace. Never corrupts on crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def atomic_save_text(text: str, path: str | Path) -> None:
    """Write text file atomically."""
    ...
```

### Migration Phases

**Phase 1** (v10.41–v10.50): Create `atomic.py`, import in new modules only.  
**Phase 2** (v10.51–v10.60): Migrate `spa_core/paper_trading/` modules.  
**Phase 3** (v10.61–v10.70): Migrate `spa_core/analytics/` modules.  
**Phase 4** (v10.71+): Migrate remaining modules; enforce via linting.

### Stdlib Contracts

`atomic_save` uses only Python stdlib (`json`, `os`, `tempfile`, `pathlib`).
No external dependencies are introduced. This is a hard constraint per CLAUDE.md.

## Consequences

**Positive:**
- Single fix point for atomic write bugs
- Consistent error handling and encoding (UTF-8, ensure_ascii=False)
- Automatic parent directory creation
- Lintable: can grep for `open(..., "w")` on state files as a policy violation

**Negative:**
- 254-file migration is high-volume (low-risk, mechanical)
- All migrated files must be re-pushed to GitHub

## Implementation Status

- `spa_core/utils/atomic.py`: ✓ created (MP-1341)
- Phase 1–4 migration: ✓ completed in v10.x sprints
- Linting rule documented in `REBUILD_PLAN_v1.md`

## Related ADRs

- ADR-035: SPAError hierarchy (companion structural improvement)
- ADR-036: BaseAnalytics migration
