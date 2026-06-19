# Atomic Migration Batch 2 Report
**Sprint v10.39 — MP-1423**  
Date: 2026-06-19

---

## Overview

Batch 2 migrated **15 files** from `spa_core/analytics/` to use the centralized
`atomic_save()` from `spa_core.utils.atomic`. This eliminates copy-pasted
`tempfile.mkstemp + os.replace` boilerplate across the analytics layer.

**Batch 1 recap (already done):** 14 files in `spa_core/paper_trading/` and `spa_core/safety/`.

---

## Migrated Files (15)

| # | File | Pattern | `import tempfile` removed |
|---|------|---------|--------------------------|
| 1 | `spa_core/analytics/rs001_stress_engine.py` | inline mkstemp | ✅ |
| 2 | `spa_core/analytics/apy_milestone_tracker.py` | inline mkstemp | ✅ |
| 3 | `spa_core/analytics/evidence_auto_calculator.py` | inline mkstemp | ✅ |
| 4 | `spa_core/analytics/research_risk_attribution.py` | inline mkstemp | ✅ |
| 5 | `spa_core/analytics/cycle_health_monitor.py` | `def _atomic_write_json` shim | ✅ |
| 6 | `spa_core/analytics/apy_forecaster.py` | inline mkstemp | ✅ |
| 7 | `spa_core/analytics/weekly_paper_report_v2.py` | inline mkstemp | ✅ |
| 8 | `spa_core/analytics/rebalance_cost.py` | inline mkstemp | ✅ |
| 9 | `spa_core/analytics/regime_adjusted_allocator.py` | inline mkstemp | ✅ |
| 10 | `spa_core/analytics/golive_readiness_report.py` | `def _atomic_write_json` shim (text writer retained) | ⚠️ partial |
| 11 | `spa_core/analytics/signal_aggregator.py` | `def _write_atomic` shim | ✅ |
| 12 | `spa_core/analytics/paper_backtest_drift_v2.py` | inline mkstemp | ✅ |
| 13 | `spa_core/analytics/rs001_live_apy_engine.py` | inline mkstemp | ✅ |
| 14 | `spa_core/analytics/paper_evidence_tracker_v2.py` | inline mkstemp | ✅ |
| 15 | `spa_core/analytics/source_acquisition_tracker.py` | inline mkstemp | ✅ |

**Note on `golive_readiness_report.py`:** `_atomic_write_json` was migrated to
`atomic_save`. `_atomic_write_text` (writes Markdown, not JSON) was intentionally
left with its own `tempfile.mkstemp` — `atomic_save` is JSON-only.

---

## Migration Pattern Applied

### Case A — Existing `_atomic_write` method (shim)
```python
# Before:
def _atomic_write_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

# After:
def _atomic_write_json(path, data):
    from spa_core.utils.atomic import atomic_save
    atomic_save(data, str(path))
```

### Case B — Inline mkstemp block
```python
# Before:
fd, tmp_path = tempfile.mkstemp(dir=str(out_dir), prefix=".tmp_")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp_path, str(out_path))
except Exception:
    try: os.unlink(tmp_path)
    except OSError: pass
    raise

# After:
from spa_core.utils.atomic import atomic_save
atomic_save(payload, str(out_path))
```

**Lazy import** (inside function/method) used throughout to avoid circular imports.

---

## Test Results

| Test suite | Tests run | Status |
|-----------|-----------|--------|
| 13 unittest files | 787 | ✅ OK |
| `apy_milestone_tracker` (pytest) | 62 | ✅ OK (agent env) |
| `signal_aggregator` (pytest) | — | ✅ OK (agent env) |

---

## Candidate Pool

Total files scanned with atomic write patterns: **364** (analytics/ + backtesting/).  
Files with corresponding tests in `tests/`: **37**.  
Files migrated in batch 2: **15** (first 15 with tests, analytics-first).

---

## Excluded Files

- `spa_core/audit/proof_of_track.py` — stdlib contract (has `test_only_stdlib_imports`),
  protected by `scripts/stdlib_contract_guard.py` (MP-1424).
- All files without corresponding test files (322 remaining candidates).

---

## Next Steps (Batch 3+)

- Remaining 22 files with tests in the candidate pool.
- 322+ files without tests — can be migrated after adding tests.
- See `scripts/stdlib_contract_guard.py` for safe exclusion of stdlib contract files.
