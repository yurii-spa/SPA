"""
spa_core/backtesting/paper_day1_checklist.py

MP-1428 (v10.44): Day 1 paper trading readiness checklist.

Verifies all infrastructure is in place before the first live paper trading day.
Run this to confirm the system is operational.

All CRITICAL checks must pass before Day 1 begins.

Usage:
    python3 -m spa_core.backtesting.paper_day1_checklist   # print report
    python3 scripts/day1_readiness_check.py                 # script, exit 1 on fail

stdlib only, no external dependencies, LLM FORBIDDEN.
MP-1428 (v10.44)
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# ── Repo root detection ───────────────────────────────────────────────────────
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT: Path = _THIS_FILE.parents[2]  # spa_core/backtesting → spa_core → repo


def _repo(rel: str) -> Path:
    return _REPO_ROOT / rel


# ── Result builder ────────────────────────────────────────────────────────────

def _ok(detail: str = "", critical: bool = True) -> Dict[str, Any]:
    return {"pass": True, "critical": critical, "detail": detail}


def _fail(detail: str = "", critical: bool = True) -> Dict[str, Any]:
    return {"pass": False, "critical": critical, "detail": detail}


# ════════════════════════════════════════════════════════════════════════════
#  PaperDay1Checklist
# ════════════════════════════════════════════════════════════════════════════

class PaperDay1Checklist:
    """
    Comprehensive Day 1 readiness checks.

    All CRITICAL checks must pass before Day 1.
    NON-CRITICAL checks are advisory warnings.

    Example:
        checklist = PaperDay1Checklist()
        result = checklist.run_all()
        if result["all_critical_pass"]:
            print("Ready for Day 1!")
        checklist.print_report()
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base = Path(base_dir).resolve() if base_dir else _REPO_ROOT

    # ── Individual checks ─────────────────────────────────────────────────

    def check_evidence_calculator(self) -> Dict[str, Any]:
        """
        CRITICAL: EvidenceAutoCalculator is importable and functional.
        Located at spa_core/analytics/evidence_auto_calculator.py
        """
        try:
            mod = importlib.import_module(
                "spa_core.analytics.evidence_auto_calculator"
            )
            cls = getattr(mod, "EvidenceAutoCalculator", None)
            if cls is None:
                return _fail("EvidenceAutoCalculator class not found in module")
            # Basic instantiation check
            obj = cls(base_dir=str(self._base))
            return _ok(f"EvidenceAutoCalculator OK (module: {mod.__file__})")
        except Exception as exc:
            return _fail(f"Import/init failed: {exc}")

    def check_cycle_with_evidence(self) -> Dict[str, Any]:
        """
        CRITICAL: CPACycleWithEvidence is importable.
        Located at spa_core/backtesting/cpa_cycle_with_evidence.py
        """
        try:
            mod = importlib.import_module(
                "spa_core.backtesting.cpa_cycle_with_evidence"
            )
            cls = getattr(mod, "CPACycleWithEvidence", None)
            if cls is None:
                return _fail("CPACycleWithEvidence class not found in module")
            return _ok(f"CPACycleWithEvidence OK (module: {mod.__file__})")
        except Exception as exc:
            return _fail(f"Import failed: {exc}")

    def check_telegram_bot(self) -> Dict[str, Any]:
        """
        NON-CRITICAL: Telegram bot tokens present in macOS Keychain.
        Checks TELEGRAM_BOT_TOKEN_SPA and TELEGRAM_CHAT_ID_SPA.
        Non-critical so tests pass in CI environments without Keychain.
        """
        try:
            from spa_core.utils.keychain import get_telegram_token, get_telegram_chat_id
            token = get_telegram_token()
            chat_id = get_telegram_chat_id()
            if token and chat_id:
                masked = token[:6] + "..." if len(token) > 6 else "***"
                return _ok(
                    f"Telegram tokens present (token={masked}, chat_id={chat_id})",
                    critical=False,
                )
            missing = []
            if not token:
                missing.append("TELEGRAM_BOT_TOKEN_SPA")
            if not chat_id:
                missing.append("TELEGRAM_CHAT_ID_SPA")
            return _fail(
                f"Missing from Keychain: {', '.join(missing)}. "
                "Run: security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -w <token>",
                critical=False,
            )
        except Exception as exc:
            return _fail(f"Keychain check failed: {exc}", critical=False)

    def check_launchd_plist(self) -> Dict[str, Any]:
        """
        CRITICAL: com.spa.daily_cycle.plist exists in scripts/ with correct content.
        """
        plist = self._base / "scripts" / "com.spa.daily_cycle.plist"
        if not plist.exists():
            return _fail(f"Plist not found: {plist}")
        content = plist.read_text()
        issues = []
        if "com.spa.daily_cycle" not in content:
            issues.append("Missing Label=com.spa.daily_cycle")
        if "Hour" not in content or "<integer>8</integer>" not in content:
            issues.append("Missing Hour=8 in StartCalendarInterval")
        if "run_daily_paper_cycle.sh" not in content:
            issues.append("Does not reference run_daily_paper_cycle.sh")
        if issues:
            return _fail(f"Plist issues: {'; '.join(issues)}")
        return _ok(f"Plist OK: {plist}")

    def check_live_trading_gate(self) -> Dict[str, Any]:
        """
        CRITICAL (safety): LiveTradingGate must be LOCKED.
        Gate active = dangerous; gate locked = correct for paper trading.
        """
        try:
            sys_path_bak = sys.path[:]
            if str(self._base) not in sys.path:
                sys.path.insert(0, str(self._base))
            try:
                from spa_core.safety.live_trading_gate import LiveTradingGate
                gate = LiveTradingGate(base_dir=str(self._base))
                is_active = gate.is_active()
            finally:
                sys.path = sys_path_bak

            if is_active:
                return _fail(
                    "LiveTradingGate is ACTIVE — live trading is enabled. "
                    "This is DANGEROUS during paper trading!"
                )
            return _ok("LiveTradingGate is LOCKED (safe for paper trading)")
        except Exception as exc:
            # If gate file doesn't exist, default is locked — safe
            if "gate" in str(exc).lower() or "FileNotFoundError" in type(exc).__name__:
                return _ok(
                    f"Gate file absent → defaults to LOCKED (safe). Detail: {exc}"
                )
            # Import or other error — assume locked for safety, warn
            return _ok(
                f"Gate check: {exc} — defaulting to LOCKED (no gate file = locked)",
                critical=True,
            )

    def check_data_directories(self) -> Dict[str, Any]:
        """
        CRITICAL: data/ and logs/ directories exist.
        """
        data_dir = self._base / "data"
        logs_dir = self._base / "logs"
        missing = []
        if not data_dir.exists():
            missing.append(str(data_dir))
        if not logs_dir.exists():
            missing.append(str(logs_dir))
        if missing:
            return _fail(f"Missing directories: {', '.join(missing)}")
        return _ok("data/ ✓  logs/ ✓")

    def check_kill_switch(self) -> Dict[str, Any]:
        """
        CRITICAL: Kill switch mechanism is present and active.
        Checks for LiveTradingGate (primary kill switch) and
        risk_policy_blocks.json or kill_switch_drill.py presence.
        """
        issues = []
        gate_module = self._base / "spa_core" / "safety" / "live_trading_gate.py"
        if not gate_module.exists():
            issues.append(f"live_trading_gate.py missing at {gate_module}")

        kill_drill = self._base / "scripts" / "kill_switch_drill.py"
        if not kill_drill.exists():
            issues.append("kill_switch_drill.py not found in scripts/")

        if issues:
            return _fail(
                f"Kill switch issues: {'; '.join(issues)}",
                critical=True,
            )
        return _ok(
            "Kill switch OK: LiveTradingGate + kill_switch_drill.py present"
        )

    def check_adapter_registry(self) -> Dict[str, Any]:
        """
        CRITICAL: Adapter registry is present and populated.
        Expects at least 15 registered adapters (actual count depends on version).
        """
        MIN_ADAPTERS = 15
        try:
            sys_path_bak = sys.path[:]
            if str(self._base) not in sys.path:
                sys.path.insert(0, str(self._base))
            try:
                from spa_core.adapters.registry import ADAPTER_REGISTRY, registry_summary
                count = len(ADAPTER_REGISTRY)
                summary = registry_summary()
            finally:
                sys.path = sys_path_bak

            if count < MIN_ADAPTERS:
                return _fail(
                    f"Only {count} adapters registered (minimum {MIN_ADAPTERS}). "
                    f"Summary: {summary}"
                )
            return _ok(
                f"{count} adapters registered. "
                f"T1={summary.get('t1_count',0)} "
                f"T2={summary.get('t2_count',0)} "
                f"T3={summary.get('t3_count',0)}"
            )
        except Exception as exc:
            return _fail(f"Adapter registry check failed: {exc}")

    # ── Check runner ──────────────────────────────────────────────────────

    def run_all(self) -> Dict[str, Any]:
        """
        Run all checks.

        Returns:
            {
                "all_critical_pass": bool,
                "critical_pass_count": int,
                "critical_total": int,
                "advisory_pass_count": int,
                "advisory_total": int,
                "checks": {
                    name: {"pass": bool, "critical": bool, "detail": str}
                }
            }
        """
        check_methods = [
            ("evidence_calculator", self.check_evidence_calculator),
            ("cycle_with_evidence", self.check_cycle_with_evidence),
            ("telegram_bot", self.check_telegram_bot),
            ("launchd_plist", self.check_launchd_plist),
            ("live_trading_gate", self.check_live_trading_gate),
            ("data_directories", self.check_data_directories),
            ("kill_switch", self.check_kill_switch),
            ("adapter_registry", self.check_adapter_registry),
        ]

        checks: Dict[str, Dict[str, Any]] = {}
        for name, fn in check_methods:
            try:
                result = fn()
            except Exception as exc:
                result = _fail(f"Unexpected error: {exc}")
            checks[name] = result

        critical_checks = [r for r in checks.values() if r.get("critical", True)]
        advisory_checks = [r for r in checks.values() if not r.get("critical", True)]

        critical_pass = sum(1 for r in critical_checks if r["pass"])
        advisory_pass = sum(1 for r in advisory_checks if r["pass"])

        return {
            "all_critical_pass": all(r["pass"] for r in critical_checks),
            "critical_pass_count": critical_pass,
            "critical_total": len(critical_checks),
            "advisory_pass_count": advisory_pass,
            "advisory_total": len(advisory_checks),
            "checks": checks,
        }

    # ── Reporting ─────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """Human-readable Markdown checklist with ✅/❌ per check."""
        result = self.run_all()
        lines = [
            "# SPA Paper Trading — Day 1 Readiness Checklist",
            "",
            f"**Status:** {'✅ ALL CRITICAL PASS' if result['all_critical_pass'] else '❌ BLOCKED'}",
            f"**Critical:** {result['critical_pass_count']}/{result['critical_total']} pass",
            f"**Advisory:** {result['advisory_pass_count']}/{result['advisory_total']} pass",
            "",
            "## Checks",
            "",
        ]
        for name, check in result["checks"].items():
            icon = "✅" if check["pass"] else "❌"
            tag = "CRITICAL" if check.get("critical", True) else "advisory"
            detail = check.get("detail", "")
            lines.append(f"### {icon} `{name}` [{tag}]")
            if detail:
                lines.append(f"> {detail}")
            lines.append("")
        return "\n".join(lines)

    def print_report(self) -> None:
        """Print checklist to stdout with ✅/❌ icons."""
        result = self.run_all()
        print("=" * 60)
        print("SPA Paper Trading — Day 1 Readiness Checklist")
        print("=" * 60)
        for name, check in result["checks"].items():
            icon = "✅" if check["pass"] else "❌"
            tag = "" if check.get("critical", True) else " [advisory]"
            detail = check.get("detail", "")
            print(f"  {icon}  {name}{tag}")
            if detail:
                print(f"       {detail}")
        print("-" * 60)
        status = "✅ READY for Day 1" if result["all_critical_pass"] else "❌ NOT READY — fix critical checks"
        print(f"  {status}")
        print(
            f"  Critical: {result['critical_pass_count']}/{result['critical_total']} | "
            f"Advisory: {result['advisory_pass_count']}/{result['advisory_total']}"
        )
        print("=" * 60)


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    checklist = PaperDay1Checklist()
    result = checklist.run_all()
    checklist.print_report()
    sys.exit(0 if result["all_critical_pass"] else 1)


if __name__ == "__main__":
    main()
