# ADR-036: BaseAnalytics Abstract Base Class — 43-Class Migration

**Date:** 2026-06-20  
**Status:** Accepted  
**Sprint:** v10.71 (MP-1456)  
**Deciders:** SPA Engineering

---

## Context

The `spa_core/analytics/` directory contained 43 independent analytics classes,
each implementing its own:
- CLI `main()` with identical `--check` / `--run` / `--base-dir` argument parsing
- `_read_json()` / `_atomic_write_json()` helper methods (254 copies — see ADR-034)
- `OUTPUT_PATH` class variable (no standard location)
- Error handling with bare exceptions

This duplication caused:
- Bugs in one module not being fixed in others
- Inconsistent `--base-dir` handling between modules
- No shared interface for the cycle_runner to call analytics uniformly

## Decision

Introduce **`BaseAnalytics`** in `spa_core/base.py`:

```python
class BaseAnalytics:
    """Abstract base for all SPA analytics modules.
    
    Subclasses must define:
      OUTPUT_PATH: str   # relative to base_dir / "data/"
    
    And implement:
      to_dict() -> dict   # the computed result
    """

    OUTPUT_PATH: str = ""   # override in subclass

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"

    def to_dict(self) -> dict:
        raise NotImplementedError

    def generate_report(self) -> dict:
        """Alias for to_dict() — used by cycle_runner orchestration."""
        return self.to_dict()

    def save(self) -> str:
        """Compute and atomically write to OUTPUT_PATH. Returns file path."""
        from spa_core.utils.atomic import atomic_save
        out = self.data_dir / self.OUTPUT_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        atomic_save(data, out)
        return str(out)

    # ── Shared helpers ──────────────────────────────────────────────────────
    def _read_json(self, path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        from spa_core.utils.atomic import atomic_save
        atomic_save(data, path)

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        from spa_core.utils.atomic import atomic_save_text
        atomic_save_text(text, path)
```

### Migration Phases (v10.x sprints)

**Phase 1** (v10.41): Create `BaseAnalytics`, migrate 5 core modules.  
**Phase 2** (v10.50): Migrate `spa_core/analytics/` (15 modules).  
**Phase 3** (v10.57): Migrate `spa_core/paper_trading/` analytics (13 modules).  
**Phase 4** (v10.62): Migrate remaining 10 modules; enforce via class hierarchy check.

Total: **43 classes** migrated to inherit `BaseAnalytics`.

### Cycle Runner Integration

After migration, `cycle_runner.py` can call any analytics uniformly:

```python
ANALYTICS_MODULES = [
    DrawdownAnalytics,
    ConcentrationAnalytics,
    YieldAttribution,
    RiskContribution,
    CorrelationAnalyzer,
]
for cls in ANALYTICS_MODULES:
    cls(base_dir=self.base_dir).save()
```

## Consequences

**Positive:**
- 43 modules share a single `save()` implementation
- CLI argument parsing standardized via `BaseAnalytics.main()` mixin (future)
- `generate_report()` alias enables uniform orchestration
- Single fix point for `_read_json` error handling

**Negative:**
- 43-module migration required careful testing
- Legacy `main()` CLIs must remain compatible during transition

## Implementation Status

- `spa_core/base.py`: ✓ `BaseAnalytics` created (MP-1340)
- Phase 1–4 migration: ✓ all 43 classes migrated (v10.41–v10.62)
- `GoLiveReadinessReport` inherits `BaseAnalytics`: ✓
- Cycle runner orchestration: integration pending post-go-live

## Related ADRs

- ADR-034: Atomic write centralization (dep)
- ADR-035: SPAError hierarchy (companion)
- ADR-032: Live trading gate (uses BaseAnalytics pattern)
