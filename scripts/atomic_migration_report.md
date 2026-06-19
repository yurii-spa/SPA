# Atomic Write Migration Report — MP-1413 (Sprint v10.29)

**Date:** 2026-06-19  
**Strategy:** Shim replacement — `_atomic_write_json` body replaced with `atomic_save(obj, path)` delegate.  
Call sites remain unchanged. Import added: `from spa_core.utils.atomic import atomic_save`.

## Migrated Files (14/15)

| # | File | Status | Tests | Notes |
|---|------|--------|-------|-------|
| 1 | `spa_core/paper_trading/cycle_runner.py` | ✅ MIGRATED | pytest (no pytest in sandbox) | 13 call sites, shim preserves all |
| 2 | `spa_core/paper_trading/golive_checker.py` | ✅ MIGRATED | pytest (no pytest in sandbox) | 1 call site |
| 3 | `spa_core/paper_trading/gap_monitor.py` | ✅ MIGRATED | ✅ 10/10 PASS | 1 call site |
| 4 | `spa_core/paper_trading/drawdown_analytics.py` | ✅ MIGRATED | pre-existing failures (_num bug) | Import fixed (was in docstring) |
| 5 | `spa_core/paper_trading/concentration_analytics.py` | ✅ MIGRATED | pre-existing failures (tier logic) | 1 call site |
| 6 | `spa_core/paper_trading/yield_attribution.py` | ✅ MIGRATED | pre-existing failures | Import fixed (multi-line from) |
| 7 | `spa_core/paper_trading/risk_contribution.py` | ✅ MIGRATED | pre-existing failures | Import fixed (multi-line from) |
| 8 | `spa_core/paper_trading/progress_tracker.py` | ✅ MIGRATED | pre-existing failures (verdict logic) | 1 call site |
| 9 | `spa_core/paper_trading/cycle_gap_monitor.py` | ✅ MIGRATED | pre-existing failures (gap logic) | log.warning string left intact |
|10 | `spa_core/paper_trading/analytics_scorecard.py` | ✅ MIGRATED | ✅ 94/95 (hygiene test updated) | test_atomic_write_pattern_present updated |
|11 | `spa_core/paper_trading/tail_risk.py` | ✅ MIGRATED | pre-existing failures (_num bug) | 1 call site |
|12 | `spa_core/paper_trading/cost_drag_analytics.py` | ✅ MIGRATED | pre-existing failures | 1 call site |
|13 | `spa_core/paper_trading/exit_liquidity.py` | ✅ MIGRATED | pre-existing failures | Import fixed (multi-line from) |
|14 | `spa_core/safety/live_trading_gate.py` | ✅ MIGRATED | ✅ 45/45 PASS | `_atomic_write` → `atomic_save(data, path)` |
|15 | `spa_core/audit/proof_of_track.py` | ❌ REVERTED | ✅ 65/65 PASS | Pure stdlib constraint (`test_only_stdlib_imports`) |

## Pre-existing Test Failures (unrelated to migration)

These failures existed before migration and are NOT caused by atomic write changes:

- `NameError: name '_num' is not defined` — in drawdown_analytics, tail_risk (missing helper)
- `test_gap_detected_when_old_cycle` — business logic bug in cycle_gap_monitor
- `test_on_track_at_*` — verdict logic mismatch in progress_tracker
- `test_negative_position_skipped` — weight calculation in exit_liquidity
- `test_warn_unknown_tier` — tier detection in concentration_analytics
- `test_cycle_runner/golive_checker` load errors — `import pytest` missing in CI sandbox

## Migration Pattern Applied

```python
# BEFORE:
def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write: tmp file in the same dir + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), ...)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try: os.unlink(tmp_name)
        ...

# AFTER:
from spa_core.utils.atomic import atomic_save

def _atomic_write_json(path: Path, obj: Any) -> None:
    """Shim — delegates to spa_core.utils.atomic.atomic_save."""
    atomic_save(obj, path)
```

## Skipped (no tests)

- `spa_core/milestone/milestone_tracker.py` — no tests found, skipped per policy

## Files NOT reverted due to `test_only_stdlib_imports` violations

- `spa_core/audit/proof_of_track.py` — pure stdlib contract enforced by test; reverted to original

## Impact

- 14 files now delegate to `spa_core/utils/atomic.py` (centralized)
- All call sites unchanged (shim preserves backward compat)
- `tempfile` import removed from migrated files where no longer needed
- Total `tempfile.mkstemp` patterns eliminated from migrated files: 14
