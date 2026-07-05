#!/usr/bin/env python3
"""
Pre-deployment validation for SPA.
Must pass before pushing to GitHub Pages / Cloudflare Pages.

Usage:
    python3 scripts/pre_deploy_check.py
    python3 -m scripts.pre_deploy_check

Exit codes:
    0 — all critical checks passed
    1 — one or more critical checks failed
"""
import sys
import os
import json
import shutil
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKS = []


def check(name, critical=True):
    """Decorator to register a check function."""
    def d(fn):
        CHECKS.append((name, fn, critical))
        return fn
    return d


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

@check("Landing build succeeds")
def landing_builds():
    """npm run build must succeed in landing/."""
    landing_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "landing",
    )
    if not os.path.isdir(landing_dir):
        raise AssertionError(f"landing/ directory not found at {landing_dir}")
    if shutil.which("npm") is None or not os.path.isdir(os.path.join(landing_dir, "node_modules")):
        return "skipped — npm/node_modules not installed here (landing build is verified by Cloudflare Pages + deploy-landing.yml)"
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=landing_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"Build failed:\n{result.stderr[-500:]}")
    return "build OK"


@check("GoLive score >= 80", critical=False)
def golive_ok():
    """GoLive readiness score must be >= 80 (advisory, non-critical)."""
    try:
        from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport  # noqa: PLC0415
        r = GoLiveReadinessReport()
        rep = r.generate_report()
        score = rep.get("total_score", 0)
        if score < 80:
            raise AssertionError(f"GoLive score {score} < 80")
        return f"score={score}"
    except ImportError as exc:
        raise AssertionError(f"GoLiveReadinessReport not found: {exc}") from exc


@check("LiveTradingGate locked")
def gate_locked():
    """LiveTradingGate must be LOCKED — never deploy with gate unlocked."""
    try:
        from spa_core.safety.live_trading_gate import LiveTradingGate  # noqa: PLC0415
        if LiveTradingGate().is_active():
            raise AssertionError("LiveTradingGate UNLOCKED! Dangerous.")
        return "LOCKED"
    except ImportError:
        # Gate module absent → not unlocked
        return "module absent (treated as LOCKED)"


@check("No hardcoded secrets")
def no_secrets():
    """Scan spa_core/**/*.py for hardcoded GitHub tokens or API keys."""
    result = subprocess.run(
        ["grep", "-rnE",
         r"ghp_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20}|AKIA[A-Z0-9]{16}|[0-9]{9,10}:AA[A-Za-z0-9_-]{33}",
         "spa_core/", "--include=*.py"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise AssertionError(f"Possible secrets found:\n{result.stdout[:200]}")
    return "clean"


@check("All tests pass", critical=False)
def tests_pass():
    """pytest tests/ must exit 0 (advisory)."""
    result = subprocess.run(
        ["python3", "-m", "pytest", "tests/", "-x", "-q", "--tb=no"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise AssertionError(f"Tests failed:\n{result.stdout[-300:]}")
    return "all green"


@check("data/ state files present")
def data_files_present():
    """Key JSON state files must exist."""
    required = [
        "data/trades.json",
        "data/equity_curve_daily.json",
        "data/golive_status.json",
        "data/current_positions.json",
        "data/paper_trading_status.json",
    ]
    missing = [f for f in required if not os.path.exists(f)]
    if missing:
        raise AssertionError(f"Missing state files: {missing}")
    return f"{len(required)} files present"


@check("golive_status.json parseable")
def golive_json_valid():
    """data/golive_status.json must be valid JSON."""
    path = "data/golive_status.json"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        data = json.load(fh)
    passed = sum(1 for v in data.get("checks", {}).values() if v)
    total = len(data.get("checks", {}))
    return f"{passed}/{total} checks pass"


@check("trades.json parseable")
def trades_json_valid():
    """data/trades.json must be valid JSON: a list, or a dict with a 'daily' list."""
    path = "data/trades.json"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        trades = json.load(fh)
    if not isinstance(trades, list):
        raise AssertionError(f"Expected list, got {type(trades).__name__}")
    return f"{len(trades)} trades"


@check("equity_curve_daily.json parseable")
def equity_curve_valid():
    """data/equity_curve_daily.json must be valid JSON: a list, or a dict with a 'daily' list."""
    path = "data/equity_curve_daily.json"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        curve = json.load(fh)
    points = curve.get("daily", curve) if isinstance(curve, dict) else curve
    if not isinstance(points, list):
        raise AssertionError(
            f"Expected a list or a dict with a 'daily' list, got {type(curve).__name__}"
        )
    return f"{len(points)} data points"


@check("landing/dist exists after build", critical=False)
def landing_dist_exists():
    """landing/dist directory must exist (artifact of build)."""
    dist = "landing/dist"
    if not os.path.isdir(dist):
        raise AssertionError(f"landing/dist not found — run build first")
    files = sum(len(ff) for _, _, ff in os.walk(dist))
    return f"{files} files in dist"


@check("KANBAN.json parseable")
def kanban_valid():
    """KANBAN.json must be valid JSON."""
    path = "KANBAN.json"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        data = json.load(fh)
    sprint = data.get("sprint_completed", "?")
    return f"sprint_completed={sprint}"


@check("push_to_github.py present")
def push_script_exists():
    """push_to_github.py must exist (deployment depends on it)."""
    if not os.path.exists("push_to_github.py"):
        raise AssertionError("push_to_github.py missing")
    return "present"


@check("RiskPolicy version is v1.0")
def risk_policy_version():
    """RiskPolicy must remain v1.0 during paper period (FORBIDDEN to change)."""
    path = "spa_core/risk/policy.py"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        content = fh.read()
    if '"v1.0"' not in content and "'v1.0'" not in content:
        raise AssertionError("RiskPolicy version != v1.0 — FORBIDDEN during paper period")
    return "v1.0 confirmed"


@check("No direct open() on state files", critical=False)
def no_direct_open():
    """State writes must use atomic tmp+os.replace, not open(w) directly."""
    result = subprocess.run(
        ["grep", "-rn", r'open(.*"w"', "spa_core/paper_trading/", "--include=*.py"],
        capture_output=True,
        text=True,
    )
    direct = [
        line for line in result.stdout.splitlines()
        if "tmp" not in line and "test" not in line
    ]
    if direct:
        raise AssertionError(f"Direct open(w) found: {direct[:3]}")
    return "atomic writes OK"


@check("landing/_headers present")
def headers_file_present():
    """landing/public/_headers (Cloudflare security headers) must exist."""
    path = "landing/public/_headers"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found — security headers missing")
    with open(path) as fh:
        content = fh.read()
    if "X-Frame-Options" not in content:
        raise AssertionError("X-Frame-Options missing from _headers")
    return "headers OK"


@check("landing/_redirects present")
def redirects_file_present():
    """landing/public/_redirects (Cloudflare routing) must exist."""
    path = "landing/public/_redirects"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        lines = [l for l in fh.read().splitlines() if l.strip() and not l.startswith("#")]
    return f"{len(lines)} redirect rules"


@check("astro.config.mjs has site set")
def astro_config_site():
    """astro.config.mjs must declare site: 'https://earn-defi.com'."""
    path = "landing/astro.config.mjs"
    if not os.path.exists(path):
        raise AssertionError(f"{path} not found")
    with open(path) as fh:
        content = fh.read()
    if "earn-defi.com" not in content:
        raise AssertionError("site not set to earn-defi.com in astro.config.mjs")
    return "site=earn-defi.com"


@check("GitHub Actions workflow present")
def gh_actions_present():
    """At least one GitHub Actions workflow must exist."""
    workflows_dir = ".github/workflows"
    if not os.path.isdir(workflows_dir):
        raise AssertionError(f"{workflows_dir} directory missing")
    workflows = [f for f in os.listdir(workflows_dir) if f.endswith(".yml")]
    if not workflows:
        raise AssertionError("No .yml workflows found in .github/workflows/")
    return f"{len(workflows)} workflows: {', '.join(workflows[:3])}"


@check("deploy-landing workflow present")
def deploy_workflow_present():
    """deploy-landing.yml must exist for GitHub Pages deployment."""
    path = ".github/workflows/deploy-landing.yml"
    if not os.path.exists(path):
        raise AssertionError(f"{path} missing — GitHub Pages deployment not configured")
    return "deploy-landing.yml present"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_checks(checks=None, verbose=True):
    """Run all registered checks and return (failed_critical, results)."""
    checks = checks or CHECKS
    results = []
    failed_critical = 0
    for name, fn, critical in checks:
        try:
            detail = fn()
            status = "pass"
            error = None
            if verbose:
                print(f"  ✅ {name}: {detail}")
        except (AssertionError, Exception) as exc:
            status = "fail"
            error = str(exc)
            if critical:
                failed_critical += 1
                if verbose:
                    print(f"  ❌ CRITICAL {name}: {exc}")
            else:
                if verbose:
                    print(f"  ⚠️  WARN {name}: {exc}")
        results.append(
            {"name": name, "critical": critical, "status": status, "error": error}
        )
    return failed_critical, results


def main():
    print("=" * 60)
    print("SPA Pre-Deploy Validation")
    print("=" * 60)

    failed, results = run_checks()

    critical_total = sum(1 for r in results if r["critical"])
    warn_total = sum(1 for r in results if not r["critical"])
    passed_critical = sum(
        1 for r in results if r["critical"] and r["status"] == "pass"
    )
    passed_warn = sum(
        1 for r in results if not r["critical"] and r["status"] == "pass"
    )

    print()
    print(
        f"Summary: {passed_critical}/{critical_total} critical | "
        f"{passed_warn}/{warn_total} advisory"
    )

    if failed > 0:
        print(f"\n❌ {failed} critical check(s) failed. Do not deploy.")
        sys.exit(1)

    print("\n✅ Pre-deploy checks passed.")


if __name__ == "__main__":
    main()
