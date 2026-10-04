# FROZEN-DATE-OK: injected-clock — the date is passed into prune_snapshots(now=...) and run.main(--now)
"""Tests for the ADR-554 WP-A06 no-execution boundary — guards in BOTH directions.

1. FORWARD: spa_core/investment_cio/*.py imports nothing from the money-path packages and calls no
   decider name.
2. REVERSE: no module under the money-path packages (nor investment_os/directive.py) imports
   spa_core.investment_cio or names a path containing "investment_cio".
3. The package writes only under <data_dir>/investment_cio/.
4. No "recommended_weights" key ever lands in a file cycles read (outside investment_cio/).
5. executes is always False; real_capital_usd is never a synthesised positive number.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.investment_cio import contract, ledger, outcomes, policy

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "spa_core" / "investment_cio"

FORBIDDEN_MODULES = ("spa_core.execution", "spa_core.paper_trading", "spa_core.allocator",
                    "spa_core.risk", "spa_core.governance", "spa_core.investment_os")
DECIDER_NAMES = ("optimize", "allocate", "rebalance_book", "rebalance_portfolio")

REVERSE_SCAN_DIRS = ("spa_core/paper_trading", "spa_core/risk", "spa_core/governance",
                    "spa_core/allocator", "spa_core/execution")
REVERSE_SCAN_SINGLE_FILES = ("spa_core/investment_os/directive.py",)


def _py_files(d: Path):
    for p in d.rglob("*.py"):
        if "__pycache__" not in p.parts:
            yield p


# ── 1. forward guard ────────────────────────────────────────────────────────────────────────────

def test_forward_guard_no_forbidden_imports():
    violations = []
    for path in _py_files(PACKAGE_DIR):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == m or alias.name.startswith(m + ".") for m in FORBIDDEN_MODULES):
                        violations.append((str(path), alias.name))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                full = mod if node.level == 0 else "." * node.level + mod
                if any(full == m or full.startswith(m + ".") for m in FORBIDDEN_MODULES):
                    violations.append((str(path), full))
    assert violations == [], f"investment_cio imports a forbidden money-path module: {violations}"


def test_forward_guard_calls_no_decider_name():
    violations = []
    for path in _py_files(PACKAGE_DIR):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in DECIDER_NAMES:
                    violations.append((str(path), name))
    assert violations == [], f"investment_cio calls a decider name from the Sec.41 census: {violations}"


# ── 2. reverse guard ─────────────────────────────────────────────────────────────────────────────

def _reverse_scan_targets():
    for d in REVERSE_SCAN_DIRS:
        p = ROOT / d
        if p.exists():
            yield from _py_files(p)
    for f in REVERSE_SCAN_SINGLE_FILES:
        p = ROOT / f
        if p.exists():
            yield p


def test_reverse_guard_money_path_never_imports_investment_cio():
    import_violations = []
    string_violations = []
    for path in _reverse_scan_targets():
        text = path.read_text()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "spa_core.investment_cio" or alias.name.startswith(
                            "spa_core.investment_cio."):
                        import_violations.append((str(path), alias.name))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "spa_core.investment_cio" or mod.startswith("spa_core.investment_cio."):
                    import_violations.append((str(path), mod))
        if "investment_cio" in text:
            string_violations.append(str(path))
    assert import_violations == [], f"money-path module imports spa_core.investment_cio: {import_violations}"
    assert string_violations == [], f"money-path module names 'investment_cio' (pattern reader?): {string_violations}"


# ── 3. writes confined to <data_dir>/investment_cio/ (and its declared anchors sibling) ────────

def _snapshot_tree(data_dir: Path) -> set:
    if not data_dir.exists():
        return set()
    return {str(p.relative_to(data_dir)) for p in data_dir.rglob("*") if p.is_file()}


def _under_declared_dirs(rel: str) -> bool:
    """N3: the external ledger anchor deliberately lives in ``ledger.ANCHORS_DIRNAME`` — a
    SIBLING of ``investment_cio/``, not nested inside it, precisely so one directory being wiped
    or restored does not silently also wipe or restore the other (the whole point of an external
    anchor). This is the ONE other directory the CIO package is allowed to write under."""
    return (rel.startswith(f"{contract.DATA_SUBDIR}/") or rel.startswith(f"{contract.DATA_SUBDIR}\\")
           or rel.startswith(f"{ledger.ANCHORS_DIRNAME}/") or rel.startswith(f"{ledger.ANCHORS_DIRNAME}\\"))


def test_ledger_and_outcomes_write_only_under_investment_cio(tmp_path):
    before = _snapshot_tree(tmp_path)
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    ledger.append(tmp_path, {
        "schema": contract.SCHEMA_REC, "recommendation_id": "a" * 64, "generated_at": "2026-09-01T09:30:00Z",
        "date": "2026-09-01", "recommended_weights": {"cash": 1.0}, "seed_split_weights": {"cash": 1.0},
        "stance": contract.STANCE_NONE, "lineage": {}, "executes": False, "real_capital_usd": None,
    }, snapshot_digest_=snap, code_identity_=ledger.code_identity())
    outcomes.score_due(tmp_path, datetime(2026, 10, 1, tzinfo=timezone.utc))
    ledger.prune_snapshots(tmp_path, retention_days=400, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    after = _snapshot_tree(tmp_path)
    new_files = after - before
    assert new_files, "the test should have produced at least one new file"
    for rel in new_files:
        assert _under_declared_dirs(rel), \
            f"investment_cio wrote outside its own directory (or its declared anchors sibling): {rel}"


def test_run_writes_only_under_investment_cio_if_sleeves_exists(tmp_path):
    try:
        from spa_core.investment_cio import sleeves  # noqa: F401
    except ImportError:
        pytest.skip("spa_core.investment_cio.sleeves not available yet (concurrent work-package) — "
                   "writes-confinement is covered directly via ledger/outcomes above")
    from spa_core.investment_cio import run
    before = _snapshot_tree(tmp_path)
    rc = run.main(["--data-dir", str(tmp_path), "--now", "2026-10-04T09:30:00Z"])
    assert rc in (0, 2, 75)
    after = _snapshot_tree(tmp_path)
    for rel in after - before:
        assert _under_declared_dirs(rel), \
            f"run.py wrote outside investment_cio/ (or its declared anchors sibling): {rel}"


def test_idempotent_rerun_leaves_no_orphan_snapshot(tmp_path):
    """Finding #21: an unconditional save_snapshot BEFORE checking same-date idempotency used to
    leave a fresh, never-referenced *.json.gz on every same-date retry (the sleeves document
    embeds timestamps that depend on --now, so even identical underlying files produce a new
    digest on a later --now). The fix checks the date first and skips the whole build+snapshot
    step on a same-date re-run."""
    try:
        from spa_core.investment_cio import sleeves  # noqa: F401
    except ImportError:
        pytest.skip("spa_core.investment_cio.sleeves not available yet (concurrent work-package)")
    from spa_core.investment_cio import ledger, run

    rc1 = run.main(["--data-dir", str(tmp_path), "--now", "2026-10-04T09:30:00Z"])
    assert rc1 == 0
    snap_dir = tmp_path / contract.DATA_SUBDIR / contract.SNAPSHOT_DIR
    count_after_first = len(list(snap_dir.glob("*.json.gz"))) if snap_dir.exists() else 0
    assert count_after_first >= 1

    rc2 = run.main(["--data-dir", str(tmp_path), "--now", "2026-10-04T15:00:00Z"])  # same UTC date, later time
    assert rc2 == 0
    count_after_second = len(list(snap_dir.glob("*.json.gz")))
    assert count_after_second == count_after_first, (
        "a same-date re-run must not leave a new orphan snapshot (finding #21)")
    assert len(ledger.read_all(tmp_path)) == 1


# ── 4. no 'recommended_weights' key in anything a cycle reads ──────────────────────────────────

CYCLE_READ_FILES = {
    "hy_paper_trading.json": {"sleeve": "balanced", "daily_history": []},
    "lp_paper_trading.json": {"sleeve": "aggressive", "daily_history": []},
    "equity_curve_daily.json": {"daily": []},
    "package_status.json": {"packages": {}},
}


def test_recommended_weights_never_leaks_into_a_cycle_read_file(tmp_path):
    for name, content in CYCLE_READ_FILES.items():
        (tmp_path / name).write_text(json.dumps(content))
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    ledger.append(tmp_path, {
        "schema": contract.SCHEMA_REC, "recommendation_id": "b" * 64, "generated_at": "2026-09-01T09:30:00Z",
        "date": "2026-09-01", "recommended_weights": {"defi_conservative": 0.5, "cash": 0.5},
        "seed_split_weights": {"defi_conservative": 0.5, "cash": 0.5}, "stance": contract.STANCE_RECOMMEND,
        "lineage": {},
    }, snapshot_digest_=snap, code_identity_=ledger.code_identity())

    leaks = []
    for p in tmp_path.rglob("*"):
        if not p.is_file():
            continue
        if f"/{contract.DATA_SUBDIR}/" in str(p).replace("\\", "/") + "/":
            continue
        try:
            if "recommended_weights" in p.read_text():
                leaks.append(str(p))
        except (UnicodeDecodeError, OSError):
            continue
    assert leaks == [], f"'recommended_weights' leaked into a cycle-read file: {leaks}"


def test_live_data_dir_has_no_recommended_weights_outside_investment_cio():
    live_data = ROOT / "data"
    if not live_data.exists():
        pytest.skip("no data/ in this worktree")
    leaks = []
    for p in live_data.rglob("*.json"):
        if f"/{contract.DATA_SUBDIR}/" in str(p).replace("\\", "/") + "/":
            continue
        try:
            if "recommended_weights" in p.read_text():
                leaks.append(str(p))
        except (UnicodeDecodeError, OSError):
            continue
    assert leaks == [], f"'recommended_weights' found outside data/{contract.DATA_SUBDIR}/: {leaks}"


# ── 5. executes is always False; real_capital_usd never a synthesised positive number ──────────

def test_executes_always_false_and_real_capital_never_synthesised_positive():
    now = datetime(2026, 10, 4, 9, 30, tzinfo=timezone.utc)
    scenes = [
        {"schema": contract.SCHEMA_SLEEVES, "generated_at": "x", "sleeves": {}, "inputs": [],
         "exposure": {}, "correlation": {}, "seed_split_weights": {}},
        {"schema": contract.SCHEMA_SLEEVES, "generated_at": "x", "sleeves": {
            "cash": {"sleeve_id": "cash", "name": "Cash", "mechanism": "cash", "mechanism_class": "cash",
                    "mode": contract.MODE, "allocatable": True, "live_admission": True, "experiment_id": "x",
                    "experiment_start": "2026-01-01", "versions_closed": [],
                    **{f: contract.absent(contract.NOT_MEASURED, reason="n/a") for f in contract.SLEEVE_FIELDS
                      if f not in ("sleeve_id", "name", "mechanism", "mechanism_class", "mode", "allocatable",
                                  "live_admission", "experiment_id", "experiment_start", "versions_closed",
                                  "risk", "composition", "factors", "correlation_features", "gates",
                                  "warnings", "unknowns")},
                    "risk": {}, "composition": {}, "factors": {}, "correlation_features": {},
                    "gates": [], "warnings": [], "unknowns": []},
        }, "inputs": [], "exposure": {}, "correlation": {}, "seed_split_weights": {}},
    ]
    for doc in scenes:
        rec = policy.recommend(doc, None, now)
        assert rec["executes"] is False
        assert rec["real_capital_usd"] is None  # realistic input (sleeves.py never sets it in paper mode)
        assert not (isinstance(rec["real_capital_usd"], (int, float)) and rec["real_capital_usd"] > 0)


# ── finding N8: a back-dated run must not leave an orphan snapshot ──────────────────────────────

def test_backdated_run_leaves_no_orphan_snapshot_and_exits_nonzero(tmp_path):
    """The snapshot used to be saved to disk BEFORE append() ever got a chance to refuse a
    back-dated date (finding #15) — the refusal happened, but the orphan *.json.gz stayed."""
    try:
        from spa_core.investment_cio import sleeves  # noqa: F401
    except ImportError:
        pytest.skip("spa_core.investment_cio.sleeves not available yet (concurrent work-package)")
    from spa_core.investment_cio import ledger, run

    rc1 = run.main(["--data-dir", str(tmp_path), "--now", "2026-10-04T09:30:00Z"])
    assert rc1 == 0
    snap_dir = tmp_path / contract.DATA_SUBDIR / contract.SNAPSHOT_DIR
    count_after_first = len(list(snap_dir.glob("*.json.gz"))) if snap_dir.exists() else 0
    assert count_after_first >= 1

    rc2 = run.main(["--data-dir", str(tmp_path), "--now", "2026-10-01T09:30:00Z"])  # earlier date
    assert rc2 == 2
    count_after_backdated = len(list(snap_dir.glob("*.json.gz")))
    assert count_after_backdated == count_after_first, \
        "a back-dated run must not leave a new orphan snapshot (finding N8)"
    assert len(ledger.read_all(tmp_path)) == 1
