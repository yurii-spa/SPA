# DEPRECATED — orphaned module, use spa_core.paper_trading.golive_checker instead
# This file is kept for historical reference only. No imports point here.
# TODO: remove in next cleanup cycle
raise ImportError("DEPRECATED: use spa_core.paper_trading.golive_checker")

#!/usr/bin/env python3
"""SPA GoLive readiness checker — extended edition (MP-384).

Runs all 18 checks (6 original anti-demo criteria + 12 new component/adapter/data
checks added in v4.69) and returns a structured result via ``run_all()``.

Design constraints (same as the original checker):
* Stdlib only — no external packages.
* Strictly read-only over the repo and data directory.
* The only write is the status file (atomic tmp + os.replace).
* Never raises on missing/corrupt data — every failure is a ``passed=False``.
* LLM_FORBIDDEN: this module must never be called from risk/execution/monitoring.
"""
# from __future__ import annotations  # MP-1233: neutralized — unreachable below DEPRECATED raise, broke py_compile

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

# ─── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_OUT_FILENAME = "golive_status.json"

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path) -> Any:
    """Read JSON defensively; missing/corrupt → None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _contains_demo_true(obj: Any) -> bool:
    """Recursively detect ``"is_demo": true`` anywhere in a parsed JSON doc."""
    if isinstance(obj, dict):
        if obj.get("is_demo") is True:
            return True
        return any(_contains_demo_true(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_demo_true(v) for v in obj)
    return False


_DEMO_TRUE_RE = re.compile(r'"is_demo"\s*:\s*true')

FRESHNESS_WINDOW_HOURS = 48


# ─── Extended GoLiveChecker ────────────────────────────────────────────────────


class GoLiveChecker:
    """Extended GoLive readiness gate: 18 checks total (6 original + 12 new).

    MP-384 added:
      Adapters (4): compound_v3, morpho_steakhouse, aave_arbitrum, pendle_pt
      Components (5): multi_strategy_runner, promotion_engine, safe_tx_builder,
                       http_server, adr022
      Data (3): adapter_status compound / morpho / arbitrum presence
    """

    def __init__(
        self,
        data_dir: str | os.PathLike | None = None,
        repo_root: str | os.PathLike | None = None,
        now: datetime | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        self.repo_root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)

    # ── Group 1: Original 6 anti-demo checks ─────────────────────────────────

    def _check_equity_curve_real(self) -> tuple[bool, str]:
        doc = _read_json(self.data_dir / "equity_curve_daily.json")
        if doc is None:
            return False, "equity_curve_daily.json: missing or unreadable"
        if not isinstance(doc, dict) or doc.get("is_demo") is not False:
            return False, "equity_curve_daily.json: not marked is_demo:false"
        daily = doc.get("daily")
        if not isinstance(daily, list) or not daily:
            return False, "equity_curve_daily.json: no daily equity records"
        return True, f"{len(daily)} daily records, is_demo:false"

    def _check_trades_real(self) -> tuple[bool, str]:
        trades = _read_json(self.data_dir / "trades.json")
        if not isinstance(trades, list):
            return False, "trades.json: missing or unreadable"
        real = [t for t in trades if isinstance(t, dict) and t.get("is_demo") is False]
        if not real:
            return False, "trades.json: no real (is_demo:false) trades recorded yet"
        return True, f"{len(real)} real trades found"

    def _check_status_real(self) -> tuple[bool, str]:
        doc = _read_json(self.data_dir / "paper_trading_status.json")
        if not isinstance(doc, dict):
            return False, "paper_trading_status.json: missing or unreadable"
        if doc.get("is_demo") is not False:
            return False, "paper_trading_status.json: not marked is_demo:false"
        return True, "paper_trading_status.json is_demo:false OK"

    def _check_no_demo_data(self) -> tuple[bool, str]:
        offenders: list[str] = []
        if self.data_dir.is_dir():
            for path in sorted(self.data_dir.rglob("*.json")):
                if path.name == STATUS_OUT_FILENAME or path.name.startswith("."):
                    continue
                doc = _read_json(path)
                if doc is not None:
                    demo = _contains_demo_true(doc)
                else:
                    try:
                        demo = bool(_DEMO_TRUE_RE.search(path.read_text(encoding="utf-8")))
                    except OSError:
                        demo = False
                if demo:
                    offenders.append(path.name)
        if offenders:
            return False, "demo data (is_demo:true) detected in: " + ", ".join(offenders)
        return True, "no is_demo:true found in data/"

    def _check_data_fresh_48h(self) -> tuple[bool, str]:
        doc = _read_json(self.data_dir / "equity_curve_daily.json")
        daily = doc.get("daily") if isinstance(doc, dict) else None
        if not isinstance(daily, list) or not daily:
            return False, "equity_curve_daily.json: no records to assess freshness"
        latest: datetime | None = None
        for bar in daily:
            if not isinstance(bar, dict):
                continue
            try:
                dt = datetime.strptime(str(bar.get("date")), "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            if latest is None or dt > latest:
                latest = dt
        if latest is None:
            return False, "equity_curve_daily.json: no parseable record dates"
        age = self.now - latest
        if age >= timedelta(hours=FRESHNESS_WINDOW_HOURS):
            hours = age.total_seconds() / 3600.0
            return (
                False,
                f"last record {latest.date()} is {hours:.0f}h old (> {FRESHNESS_WINDOW_HOURS}h)",
            )
        return True, f"last record {latest.date()}, age {age.total_seconds()/3600:.1f}h"

    def _check_cycle_runner_exists(self) -> tuple[bool, str]:
        path = self.repo_root / "spa_core" / "paper_trading" / "cycle_runner.py"
        if not path.is_file():
            return False, "spa_core/paper_trading/cycle_runner.py: not found"
        return True, "cycle_runner.py exists"

    # ── Group 2: Adapter checks (MP-384) ─────────────────────────────────────

    def _check_file_syntax(self, rel_path: str) -> tuple[bool, str]:
        """Check file exists and has valid Python syntax (importable)."""
        path = self.repo_root / rel_path
        if not path.is_file():
            return False, f"{rel_path}: file not found"
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            return True, f"{rel_path}: exists + syntax OK"
        except SyntaxError as exc:
            return False, f"{rel_path}: syntax error — {exc}"
        except OSError as exc:
            return False, f"{rel_path}: read error — {exc}"

    def _check_compound_v3_adapter(self) -> tuple[bool, str]:
        return self._check_file_syntax("spa_core/adapters/compound_v3_adapter.py")

    def _check_morpho_steakhouse_adapter(self) -> tuple[bool, str]:
        return self._check_file_syntax("spa_core/adapters/morpho_steakhouse_adapter.py")

    def _check_aave_arbitrum_adapter(self) -> tuple[bool, str]:
        return self._check_file_syntax("spa_core/adapters/aave_arbitrum_adapter.py")

    def _check_pendle_pt_adapter(self) -> tuple[bool, str]:
        return self._check_file_syntax("spa_core/adapters/pendle_pt_adapter.py")

    # ── Group 3: Component checks (MP-384) ────────────────────────────────────

    def _check_multi_strategy_runner(self) -> tuple[bool, str]:
        path = self.repo_root / "spa_core" / "paper_trading" / "multi_strategy_runner.py"
        if not path.is_file():
            return False, "spa_core/paper_trading/multi_strategy_runner.py: not found"
        return True, "multi_strategy_runner.py exists"

    def _check_promotion_engine(self) -> tuple[bool, str]:
        path = self.repo_root / "spa_core" / "paper_trading" / "promotion_engine.py"
        if not path.is_file():
            return False, "spa_core/paper_trading/promotion_engine.py: not found"
        return True, "promotion_engine.py exists"

    def _check_safe_tx_builder(self) -> tuple[bool, str]:
        path = self.repo_root / "spa_core" / "execution" / "safe_tx_builder.py"
        if not path.is_file():
            return False, "spa_core/execution/safe_tx_builder.py: not found"
        return True, "safe_tx_builder.py exists"

    def _check_http_server(self) -> tuple[bool, str]:
        path = self.repo_root / "spa_core" / "family_fund" / "http_server.py"
        if not path.is_file():
            return False, "spa_core/family_fund/http_server.py: not found"
        return True, "http_server.py exists"

    def _check_adr022_exists(self) -> tuple[bool, str]:
        path = self.repo_root / "docs" / "adr" / "ADR-022-gnosis-safe-multisig.md"
        if not path.is_file():
            return False, "docs/adr/ADR-022-gnosis-safe-multisig.md: not found"
        return True, "ADR-022-gnosis-safe-multisig.md exists"

    # ── Group 4: adapter_status.json data checks (MP-384) ────────────────────

    def _check_adapter_status_key(self, key: str) -> tuple[bool, str]:
        doc = _read_json(self.data_dir / "adapter_status.json")
        if not isinstance(doc, dict):
            return False, "data/adapter_status.json: missing or not a dict"
        # v2 format (schema_version 2): adapters is a nested dict keyed by
        # snake_case protocol name.  v1 format: keys are at the top level.
        # Support both by checking the nested dict first (MP-1195).
        scope = doc.get("adapters", doc)
        if not isinstance(scope, dict):
            scope = doc
        if key not in scope:
            return False, f"data/adapter_status.json: key '{key}' not present"
        return True, f"adapter_status.json['adapters']['{key}'] present"

    def _check_adapter_status_has_compound(self) -> tuple[bool, str]:
        return self._check_adapter_status_key("compound_v3")

    def _check_adapter_status_has_morpho(self) -> tuple[bool, str]:
        return self._check_adapter_status_key("morpho_steakhouse")

    def _check_adapter_status_has_arbitrum(self) -> tuple[bool, str]:
        return self._check_adapter_status_key("aave_arbitrum")

    # ── Public API ────────────────────────────────────────────────────────────

    # Ordered registry of all 18 checks: (name, method)
    _CHECKS: list[tuple[str, str]] = [
        # Group 1 — original anti-demo gate (6)
        ("equity_curve_real",            "_check_equity_curve_real"),
        ("trades_real",                  "_check_trades_real"),
        ("status_real",                  "_check_status_real"),
        ("no_demo_data",                 "_check_no_demo_data"),
        ("data_fresh_48h",               "_check_data_fresh_48h"),
        ("cycle_runner_exists",          "_check_cycle_runner_exists"),
        # Group 2 — new adapters (4)
        ("compound_v3_adapter",          "_check_compound_v3_adapter"),
        ("morpho_steakhouse_adapter",    "_check_morpho_steakhouse_adapter"),
        ("aave_arbitrum_adapter",        "_check_aave_arbitrum_adapter"),
        ("pendle_pt_adapter",            "_check_pendle_pt_adapter"),
        # Group 3 — new components (5)
        ("multi_strategy_runner",        "_check_multi_strategy_runner"),
        ("promotion_engine",             "_check_promotion_engine"),
        ("safe_tx_builder",              "_check_safe_tx_builder"),
        ("http_server",                  "_check_http_server"),
        ("adr022_exists",                "_check_adr022_exists"),
        # Group 4 — adapter_status data (3)
        ("adapter_status_has_compound",  "_check_adapter_status_has_compound"),
        ("adapter_status_has_morpho",    "_check_adapter_status_has_morpho"),
        ("adapter_status_has_arbitrum",  "_check_adapter_status_has_arbitrum"),
    ]

    def run_all(self, write: bool = True) -> dict:
        """Run all 18 checks and return a structured result dict.

        Returns:
            {
                "passed": int,
                "total":  int,
                "ready":  bool,
                "timestamp": str,
                "results": [{"name": str, "passed": bool, "detail": str}, ...]
            }
        """
        results: list[dict] = []
        for name, method_name in self._CHECKS:
            method = getattr(self, method_name)
            try:
                ok, detail = method()
            except Exception as exc:  # defensive: checker must never crash
                ok, detail = False, f"unexpected error: {exc}"
            results.append({"name": name, "passed": ok, "detail": detail})

        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        output = {
            "passed": passed,
            "total": total,
            "ready": passed == total,
            "timestamp": self.now.isoformat(),
            "source": "checklist.golive_checker",
            "version": "v4.69",
            "results": results,
            "blockers": [r["detail"] for r in results if not r["passed"]],
        }
        if write:
            _atomic_write_json(self.data_dir / STATUS_OUT_FILENAME, output)
        return output

    # Legacy compat: expose check() as an alias backed by run_all()
    def check(self, write: bool = True):  # type: ignore[override]
        raw = self.run_all(write=write)
        # Return a lightweight object with .ready, .checks, .blockers, .summary()
        return _LegacyResult(raw)


class _LegacyResult:
    """Thin wrapper for backward-compat with callers using .check()."""

    def __init__(self, raw: dict) -> None:
        self.ready: bool = raw["ready"]
        self.checks: dict[str, bool] = {r["name"]: r["passed"] for r in raw["results"]}
        self.blockers: list[str] = raw["blockers"]
        self.timestamp: str = raw["timestamp"]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "checks": self.checks,
            "blockers": self.blockers,
            "timestamp": self.timestamp,
            "source": "checklist.golive_checker",
        }

    def summary(self) -> str:
        lines = [
            "─" * 60,
            f"GO-LIVE READINESS (extended v4.69)   [{self.timestamp}]",
            "─" * 60,
        ]
        for name, ok in self.checks.items():
            lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if self.blockers:
            lines.append("  blockers:")
            lines.extend(f"    • {b}" for b in self.blockers)
        passed = sum(self.checks.values())
        total = len(self.checks)
        lines.append(
            f"  verdict: {'READY' if self.ready else 'NOT READY'}"
            f" ({passed}/{total} checks pass)"
        )
        lines.append("─" * 60)
        return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="spa_core.checklist.golive_checker",
        description="Extended GoLive readiness checker v4.69 (MP-384).",
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument(
        "--dry-run", action="store_true", help="do not write golive_status.json"
    )
    args = parser.parse_args(argv)

    checker = GoLiveChecker(data_dir=args.data_dir)
    result = checker.run_all(write=not args.dry_run)

    print(f"Score: {result['passed']}/{result['total']}")
    for item in result["results"]:
        icon = "✅" if item["passed"] else "❌"
        print(f"{icon} {item['name']}: {item['detail']}")
    verdict = "READY" if result["ready"] else "NOT READY"
    print(f"\nVerdict: {verdict} ({result['passed']}/{result['total']} pass)")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
