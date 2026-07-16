#!/usr/bin/env python3
"""
SPA Smart Audit Script
Запуск: python3 scripts/audit_spa.py
Читает data/AUDIT_BASELINE.json и подавляет known non-issues.
Выдаёт только реальные новые проблемы.
"""
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).parent.parent
DATA = REPO / "data"
BASELINE_FILE = DATA / "AUDIT_BASELINE.json"


def load_baseline():
    if not BASELINE_FILE.exists():
        return {}
    return json.loads(BASELINE_FILE.read_text())


def check_golive():
    """Запускает GoLiveChecker — только если мы на Mac (HOME содержит /Users/)"""
    home = os.environ.get("HOME", "")
    if "/Users/" not in home:
        return None, "⚠ Skipped: Linux sandbox (mac-only check)"
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'.');"
             "from spa_core.paper_trading.golive_checker import GoLiveChecker;"
             "r=GoLiveChecker().check();"
             "fails={k:str(v) for k,v in r.checks.items() if v is not True};"
             "print(f\"{sum(v is True for v in r.checks.values())}/{len(r.checks)}\");"
             "import json; print(json.dumps(fails))"
             ],
            capture_output=True, text=True, cwd=str(REPO), timeout=30
        )
        lines = result.stdout.strip().splitlines()
        score = lines[0] if lines else "?"
        fails = json.loads(lines[1]) if len(lines) > 1 else {}
        return score, fails
    except Exception as e:
        return None, str(e)


def check_pending_pushes():
    state_file = DATA / "autopush_state.json"
    if not state_file.exists():
        return []
    state = json.loads(state_file.read_text())
    last = state.get("last_version", 0)
    scripts = list((REPO / "scripts").glob("push_v*.sh"))
    import re
    pending = []
    for s in scripts:
        m = re.search(r"push_v(\d+)\.sh", s.name)
        if m and int(m.group(1)) > last:
            pending.append(int(m.group(1)))
    return sorted(pending)


def check_strategy_imports():
    import importlib
    import glob as glib
    ok, fail = [], []
    for f in glib.glob(str(REPO / "spa_core/strategies/s*.py")):
        mod = "spa_core.strategies." + Path(f).stem
        try:
            importlib.import_module(mod)
            ok.append(mod)
        except Exception as e:
            fail.append((mod, str(e)[:100]))
    return ok, fail


def check_data_files():
    issues = []
    key_files = [
        "autopush_state.json",
        "current_positions.json",
        "paper_trading_status.json",
        "equity_curve_daily.json",
        "tournament_results.json",
    ]
    for f in key_files:
        p = DATA / f
        if not p.exists():
            issues.append(f"MISSING: data/{f}")
        else:
            try:
                json.loads(p.read_text())
            except Exception:
                issues.append(f"INVALID JSON: data/{f}")
    return issues


def main():
    baseline = load_baseline()
    missing_ok = set(baseline.get("missing_files", {}).keys())
    is_mac = "/Users/" in os.environ.get("HOME", "")

    print(f"╔══ SPA Smart Audit — {datetime.now().strftime('%Y-%m-%d %H:%M')} ══╗")
    print(f"║ Platform: {'macOS host' if is_mac else 'Linux sandbox (some checks skipped)'}")
    print()

    issues = []
    warnings = []

    # GoLive
    if is_mac:
        score, fails = check_golive()
        if score:
            # Ready when passed == total (e.g. "29/29"), regardless of the
            # criteria count — the gate grows over time (MP-1228).
            parts = score.split("/")
            all_pass = len(parts) == 2 and parts[0] == parts[1]
            if all_pass:
                print(f"✅ GoLive: {score}")
            else:
                print(f"⚠  GoLive: {score}")
                for k, v in (fails or {}).items():
                    issues.append(f"GoLive FAIL: {k} → {v}")
        else:
            warnings.append(f"GoLive check error: {fails}")
    else:
        print("⏭  GoLive: skipped (mac-only)")

    # Pending pushes
    pending = check_pending_pushes()
    if pending:
        print(f"📤 Pending push scripts: {pending}")
        if len(pending) > 5:
            issues.append(f"Push queue backed up: {len(pending)} scripts pending")
    else:
        print("✅ Push queue: empty")

    # Strategy imports
    ok_strats, fail_strats = check_strategy_imports()
    if fail_strats:
        for mod, err in fail_strats:
            issues.append(f"Strategy import FAIL: {mod} — {err}")
        print(f"❌ Strategy imports: {len(ok_strats)} ok, {len(fail_strats)} FAIL")
    else:
        print(f"✅ Strategy imports: {len(ok_strats)} ok")

    # Data files
    data_issues = check_data_files()
    real_data_issues = [i for i in data_issues
                        if not any(known in i for known in missing_ok)]
    if real_data_issues:
        for i in real_data_issues:
            issues.append(i)
        print(f"❌ Data files: {len(real_data_issues)} issues")
    else:
        suppressed = len(data_issues) - len(real_data_issues)
        print(f"✅ Data files: ok" + (f" ({suppressed} suppressed by baseline)" if suppressed else ""))

    print()
    if issues:
        print(f"╔══ REAL ISSUES ({len(issues)}) ══╗")
        for i in issues:
            print(f"  ❌ {i}")
    else:
        print("╔══ NO NEW ISSUES ══╗")
        print("  All checks passed or suppressed by AUDIT_BASELINE.json")

    if warnings:
        print(f"\n⚠ Warnings:")
        for w in warnings:
            print(f"  {w}")

    baseline_note = baseline.get("_description", "")
    print(f"\n📋 Baseline: {BASELINE_FILE.name} ({baseline.get('_updated','?')})")
    print("╚══════════════════════════════════════════╝")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    sys.exit(main())
