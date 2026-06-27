#!/usr/bin/env python3
"""
MP-446 — Day 1 Pre-flight Validation
Запускать накануне первого launchd цикла (2026-06-13 08:00).
Все 6 проверок должны быть PASS перед go.

Usage:
    cd ~/Documents/SPA_Claude
    python3 scripts/preflight_day1.py
"""
import ast
import json
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from spa_core.utils import clock  # noqa: E402  (after sys.path setup for standalone run)
CYCLE_RUNNER = os.path.join(REPO_ROOT, "spa_core", "paper_trading", "cycle_runner.py")
PAPER_EVIDENCE = os.path.join(REPO_ROOT, "data", "paper_evidence.json")
ADAPTER_STATUS = os.path.join(REPO_ROOT, "data", "adapter_status.json")
GOLIVE_STATUS = os.path.join(REPO_ROOT, "data", "golive_status.json")
OUTPUT_FILE = os.path.join(REPO_ROOT, "data", "preflight_day1.json")

EXPECTED_START_DATE = "2026-06-12"
MIN_ADAPTERS = 10

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _result(name: str, passed: bool, detail: str = "") -> dict:
    status = "PASS" if passed else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return {"check": name, "status": status, "detail": detail}


def _atomic_write(path: str, data: dict) -> None:
    """Атомарная запись: tmp + os.replace."""
    dir_ = os.path.dirname(path)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp_path = fh.name
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_cycle_runner_syntax() -> dict:
    """1. cycle_runner.py существует и синтаксис корректен."""
    name = "cycle_runner.py exists & syntax OK"
    if not os.path.isfile(CYCLE_RUNNER):
        return _result(name, False, f"file not found: {CYCLE_RUNNER}")
    try:
        with open(CYCLE_RUNNER, encoding="utf-8") as fh:
            src = fh.read()
        ast.parse(src)
        return _result(name, True, f"{len(src):,} bytes parsed")
    except SyntaxError as exc:
        return _result(name, False, str(exc))


def check_adapter_registry() -> dict:
    """2. ADAPTER_REGISTRY загружается, count >= MIN_ADAPTERS."""
    name = f"ADAPTER_REGISTRY loads (>= {MIN_ADAPTERS} adapters)"
    try:
        sys.path.insert(0, REPO_ROOT)
        from spa_core.adapters import ADAPTER_REGISTRY  # noqa: PLC0415
        count = len(ADAPTER_REGISTRY)
        passed = count >= MIN_ADAPTERS
        return _result(name, passed, f"{count} adapters found")
    except Exception as exc:  # noqa: BLE001
        return _result(name, False, str(exc))


def check_paper_evidence_tracker() -> dict:
    """3. PaperEvidenceTracker инициализируется без исключений."""
    name = "PaperEvidenceTracker initializes"
    try:
        sys.path.insert(0, REPO_ROOT)
        from spa_core.paper_trading.paper_evidence_tracker import PaperEvidenceTracker  # noqa: PLC0415
        # Инит с временным файлом, чтобы не трогать реальные данные
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name
        try:
            _ = PaperEvidenceTracker(evidence_file=tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return _result(name, True)
    except Exception as exc:  # noqa: BLE001
        return _result(name, False, str(exc))


def check_paper_evidence_json() -> dict:
    """4. paper_evidence.json парсится, start_date == EXPECTED_START_DATE."""
    name = f"paper_evidence.json valid (start_date={EXPECTED_START_DATE})"
    if not os.path.isfile(PAPER_EVIDENCE):
        return _result(name, False, "file not found")
    try:
        with open(PAPER_EVIDENCE, encoding="utf-8") as fh:
            data = json.load(fh)
        start = data.get("start_date")
        passed = start == EXPECTED_START_DATE
        return _result(name, passed, f"start_date={start!r}")
    except Exception as exc:  # noqa: BLE001
        return _result(name, False, str(exc))


def check_adapter_status_json() -> dict:
    """5. adapter_status.json парсится, count >= MIN_ADAPTERS адаптеров."""
    name = f"adapter_status.json valid (>= {MIN_ADAPTERS} adapters)"
    if not os.path.isfile(ADAPTER_STATUS):
        return _result(name, False, "file not found")
    try:
        with open(ADAPTER_STATUS, encoding="utf-8") as fh:
            data = json.load(fh)
        adapters = data.get("adapters", [])
        count = len(adapters) if isinstance(adapters, list) else len(adapters)
        passed = count >= MIN_ADAPTERS
        return _result(name, passed, f"{count} adapters in adapter_status")
    except Exception as exc:  # noqa: BLE001
        return _result(name, False, str(exc))


def check_golive_status_json() -> dict:
    """6. golive_status.json парсится, ready=true."""
    name = "golive_status.json valid (ready=true)"
    if not os.path.isfile(GOLIVE_STATUS):
        return _result(name, False, "file not found")
    try:
        with open(GOLIVE_STATUS, encoding="utf-8") as fh:
            data = json.load(fh)
        ready = data.get("ready", False)
        blockers = data.get("blockers", [])
        detail = f"ready={ready}"
        if blockers:
            detail += f", blockers={blockers}"
        return _result(name, bool(ready), detail)
    except Exception as exc:  # noqa: BLE001
        return _result(name, False, str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 60)
    print("SPA MP-446 — Day 1 Pre-flight Validation")
    print(f"Timestamp : {clock.utcnow().isoformat()}Z")
    print(f"Repo root : {REPO_ROOT}")
    print("=" * 60)

    checks = [
        check_cycle_runner_syntax(),
        check_adapter_registry(),
        check_paper_evidence_tracker(),
        check_paper_evidence_json(),
        check_adapter_status_json(),
        check_golive_status_json(),
    ]

    passed_count = sum(1 for c in checks if c["status"] == "PASS")
    total = len(checks)

    print("-" * 60)
    print(f"Result: {passed_count}/{total} checks passed")
    print("-" * 60)

    all_pass = passed_count == total

    if all_pass:
        verdict = "PRE-FLIGHT: ALL SYSTEMS GO ✓"
        print(f"\n  ✅  {verdict}\n")
    else:
        verdict = "PRE-FLIGHT: BLOCKED — fix before cycle"
        failed = [c["check"] for c in checks if c["status"] == "FAIL"]
        print(f"\n  ❌  {verdict}")
        for f in failed:
            print(f"       • {f}")
        print()

    # Атомарная запись результата
    output = {
        "timestamp": clock.utcnow().isoformat() + "Z",
        "mp": "MP-446",
        "verdict": verdict,
        "all_pass": all_pass,
        "passed": passed_count,
        "total": total,
        "checks": checks,
    }
    _atomic_write(OUTPUT_FILE, output)
    print(f"  📄  Report saved: {OUTPUT_FILE}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
