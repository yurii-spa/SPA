"""
System Config Validator (MP-636).
===================================

Validates that all key system configuration files and modules are present
and well-formed.  Catches missing files, invalid JSON, and Python syntax
errors before they cause runtime failures.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies any project file.
* Graceful: all check methods catch exceptions and return ValidationResult.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Checks performed
----------------
  REQUIRED_FILES      — presence of essential project files (CRITICAL on miss)
  REQUIRED_ANALYTICS  — presence + valid Python syntax for analytics modules
  JSON validity       — JSON parse check for files with .json extension

Severity
--------
  CRITICAL — missing required file or analytics module
  WARNING  — malformed JSON or syntax error in existing file
  INFO     — informational pass result

CLI
---
  python3 -m spa_core.analytics.system_config_validator --check
  python3 -m spa_core.analytics.system_config_validator --run   (alias for --check)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path("/Users/yuriikulieshov/Documents/SPA_Claude")

# Severity literals
SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """The outcome of a single configuration check."""
    check_name: str          # short identifier for this check
    passed: bool             # True if the check passed
    severity: str            # "CRITICAL" | "WARNING" | "INFO"
    message: str             # human-readable explanation
    file_path: Optional[str] # absolute path of the file checked, or None


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class SystemConfigValidator:
    """
    Validates that essential SPA project files and analytics modules
    are present and well-formed.

    All public methods return ValidationResult or list[ValidationResult]
    and never raise exceptions — errors are captured in the result.
    """

    PROJECT_ROOT: Path = _PROJECT_ROOT

    REQUIRED_FILES: List[str] = [
        "KANBAN.json",
        "CURRENT_STATE.md",
        "spa_core/__init__.py",
        "spa_core/paper_trading/cycle_runner.py",
        "spa_core/analytics/__init__.py",
        "data/adapter_status.json",
        "push_to_github.py",
    ]

    REQUIRED_ANALYTICS: List[str] = [
        "benchmark_tracker",
        "portfolio_snapshot_diff",
        "weekly_summary_report",
        "alert_threshold_manager",
        "gas_cost_tracker",
        "protocol_risk_scorer",
        "strategy_tournament",
        "slippage_simulator",
        "liquidity_exit_simulator",
        "cycle_health_monitor",
        "apy_anomaly_detector",
    ]

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._root = project_root if project_root is not None else self.PROJECT_ROOT

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _abs_path(self, relative: str) -> Path:
        return self._root / relative

    # ------------------------------------------------------------------
    # Individual check methods
    # ------------------------------------------------------------------

    def check_file_exists(
        self,
        filepath: str,
        severity: str = SEV_CRITICAL,
    ) -> ValidationResult:
        """
        Check that a file (relative to PROJECT_ROOT) exists on disk.

        Returns a passed=True INFO result if found, or a failed result
        with the specified severity if missing.
        """
        abs_path = self._abs_path(filepath)
        str_path = str(abs_path)

        if abs_path.exists() and abs_path.is_file():
            return ValidationResult(
                check_name=f"file_exists:{filepath}",
                passed=True,
                severity=SEV_INFO,
                message=f"Required file exists: {filepath}",
                file_path=str_path,
            )
        else:
            return ValidationResult(
                check_name=f"file_exists:{filepath}",
                passed=False,
                severity=severity,
                message=f"Required file missing: {filepath}",
                file_path=str_path,
            )

    def check_json_valid(self, filepath: str) -> ValidationResult:
        """
        Check that a file contains valid JSON.

        Returns passed=True if parsing succeeds, passed=False (WARNING)
        if the file is missing or cannot be parsed.
        """
        abs_path = self._abs_path(filepath)
        str_path = str(abs_path)

        if not abs_path.exists():
            return ValidationResult(
                check_name=f"json_valid:{filepath}",
                passed=False,
                severity=SEV_WARNING,
                message=f"File not found for JSON check: {filepath}",
                file_path=str_path,
            )
        try:
            with open(abs_path, "r", encoding="utf-8") as fh:
                json.load(fh)
            return ValidationResult(
                check_name=f"json_valid:{filepath}",
                passed=True,
                severity=SEV_INFO,
                message=f"Valid JSON: {filepath}",
                file_path=str_path,
            )
        except json.JSONDecodeError as exc:
            return ValidationResult(
                check_name=f"json_valid:{filepath}",
                passed=False,
                severity=SEV_WARNING,
                message=f"Invalid JSON in {filepath}: {exc}",
                file_path=str_path,
            )
        except OSError as exc:
            return ValidationResult(
                check_name=f"json_valid:{filepath}",
                passed=False,
                severity=SEV_WARNING,
                message=f"Cannot read {filepath}: {exc}",
                file_path=str_path,
            )

    def check_python_syntax(self, filepath: str) -> ValidationResult:
        """
        Check that a Python file compiles without syntax errors.

        Uses compile() (no execution). Returns passed=False (WARNING)
        if the file is missing, unreadable, or has a syntax error.
        """
        abs_path = self._abs_path(filepath)
        str_path = str(abs_path)

        if not abs_path.exists():
            return ValidationResult(
                check_name=f"python_syntax:{filepath}",
                passed=False,
                severity=SEV_WARNING,
                message=f"File not found for syntax check: {filepath}",
                file_path=str_path,
            )
        try:
            source = abs_path.read_text(encoding="utf-8")
        except OSError as exc:
            return ValidationResult(
                check_name=f"python_syntax:{filepath}",
                passed=False,
                severity=SEV_WARNING,
                message=f"Cannot read {filepath}: {exc}",
                file_path=str_path,
            )
        try:
            compile(source, str_path, "exec")
            return ValidationResult(
                check_name=f"python_syntax:{filepath}",
                passed=True,
                severity=SEV_INFO,
                message=f"Valid Python syntax: {filepath}",
                file_path=str_path,
            )
        except SyntaxError as exc:
            return ValidationResult(
                check_name=f"python_syntax:{filepath}",
                passed=False,
                severity=SEV_WARNING,
                message=f"Syntax error in {filepath}: {exc}",
                file_path=str_path,
            )

    def check_analytics_module(self, module_name: str) -> ValidationResult:
        """
        Check that spa_core/analytics/{module_name}.py exists and has
        valid Python syntax.

        Returns the first failing ValidationResult encountered, or a
        passed=True INFO result if both checks pass.
        """
        relative = f"spa_core/analytics/{module_name}.py"
        abs_path = self._abs_path(relative)
        str_path = str(abs_path)

        # Step 1: existence
        if not abs_path.exists() or not abs_path.is_file():
            return ValidationResult(
                check_name=f"analytics_module:{module_name}",
                passed=False,
                severity=SEV_CRITICAL,
                message=f"Analytics module missing: {relative}",
                file_path=str_path,
            )

        # Step 2: syntax
        syntax_result = self.check_python_syntax(relative)
        if not syntax_result.passed:
            return ValidationResult(
                check_name=f"analytics_module:{module_name}",
                passed=False,
                severity=SEV_WARNING,
                message=f"Analytics module has syntax error: {relative} — {syntax_result.message}",
                file_path=str_path,
            )

        return ValidationResult(
            check_name=f"analytics_module:{module_name}",
            passed=True,
            severity=SEV_INFO,
            message=f"Analytics module OK: {relative}",
            file_path=str_path,
        )

    # ------------------------------------------------------------------
    # Orchestrated run
    # ------------------------------------------------------------------

    def run_all_checks(self) -> List[ValidationResult]:
        """
        Run all checks: required files + JSON validity where applicable +
        all required analytics modules (existence + syntax).

        Returns a flat list of all ValidationResult objects.
        """
        results: List[ValidationResult] = []

        # Required files — existence check
        for filepath in self.REQUIRED_FILES:
            results.append(self.check_file_exists(filepath, severity=SEV_CRITICAL))

        # JSON validity for .json files among required files
        for filepath in self.REQUIRED_FILES:
            if filepath.endswith(".json"):
                results.append(self.check_json_valid(filepath))

        # Required analytics modules
        for module_name in self.REQUIRED_ANALYTICS:
            results.append(self.check_analytics_module(module_name))

        return results

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(self) -> dict:
        """
        Run all checks and produce a structured summary.

        Returns a dict with:
          results          — list of result dicts (serialisable)
          total_checks     — total number of checks run
          passed           — number of passed checks
          failed_critical  — number of failed CRITICAL checks
          failed_warning   — number of failed WARNING checks
          health_pct       — passed / total * 100
          is_healthy       — True if failed_critical == 0
          advisory         — human-readable summary
          generated_at     — ISO-8601 timestamp
        """
        results = self.run_all_checks()

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        failed_critical = sum(
            1 for r in results if not r.passed and r.severity == SEV_CRITICAL
        )
        failed_warning = sum(
            1 for r in results if not r.passed and r.severity == SEV_WARNING
        )
        health_pct = (passed_count / total * 100.0) if total > 0 else 0.0
        is_healthy = failed_critical == 0

        if is_healthy and failed_warning == 0:
            advisory = (
                f"HEALTHY: All {total} checks passed. "
                f"System configuration is valid."
            )
        elif is_healthy:
            advisory = (
                f"DEGRADED: {passed_count}/{total} checks passed. "
                f"{failed_warning} warning(s) — no critical failures."
            )
        else:
            advisory = (
                f"UNHEALTHY: {failed_critical} critical failure(s), "
                f"{failed_warning} warning(s). "
                f"{passed_count}/{total} checks passed ({health_pct:.1f}%)."
            )

        return {
            "generated_at": self._now_iso(),
            "results": [
                {
                    "check_name": r.check_name,
                    "passed": r.passed,
                    "severity": r.severity,
                    "message": r.message,
                    "file_path": r.file_path,
                }
                for r in results
            ],
            "total_checks": total,
            "passed": passed_count,
            "failed_critical": failed_critical,
            "failed_warning": failed_warning,
            "health_pct": round(health_pct, 2),
            "is_healthy": is_healthy,
            "advisory": advisory,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="System Config Validator (MP-636)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run all checks and print report (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Alias for --check.",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Override project root path.",
    )
    args = parser.parse_args(argv)

    root = Path(args.project_root) if args.project_root else None
    validator = SystemConfigValidator(project_root=root)
    report = validator.generate_report()

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if report["failed_critical"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
