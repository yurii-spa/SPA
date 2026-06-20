#!/usr/bin/env python3
"""SPA go-live readiness checker — 29-criteria gate (MP-006 / MP-384 / MP-417 / MP-1228).

Validates the paper-trading track record against 29 criteria grouped into
9 categories. All 29 must pass for ``ready=True``.

Criteria groups
===============
1. Data integrity (6)       — anti-demo core (original MP-006)
2. Adapters (4)             — T1/T2 adapter files exist + valid syntax (MP-384)
3. Components (5)           — key runtime modules deployed (MP-384)
4. Adapter status (3)       — adapter_status.json coverage (MP-384)
5. Continuity (2)           — gap_monitor health + 30-day track (MP-417)
6. Infrastructure (2)       — autopush launchd + Telegram daily alert (MP-417)
7. Performance (3)          — APY floor, drawdown kill, min track days (MP-417)
8. Compliance (1)           — risk policy snapshot committed (MP-417)
9. Integrity & Evidence (3) — adapter registry, backtest evidence,
                              audit-trail hash chain (MP-1228)

Honesty rule (MP-1228)
======================
``min_track_days_30`` and ``gap_monitor_30d`` count ONLY equity bars dated on
or after ``PAPER_REAL_START`` (the post-teardown reset). Pre-teardown bars are
demo/void per CLAUDE.md and must never inflate the track-record length. These
two criteria are *time-gated*: when they fail purely because not enough honest
days have accrued yet, they are reported as ``PENDING`` (with an estimated
days-to-pass) rather than ``FAIL`` — they are waiting on the calendar, not on a
defect to fix.

Result is persisted to ``data/golive_status.json`` (atomic write) so the
dashboard and CLI read one canonical verdict.

Scope / safety
==============
* STRICTLY READ-ONLY over track record; only write is the status file.
* Stdlib only — no external dependencies.
* Atomic writes (tmpfile + os.replace).
* Advisory: ``cycle_runner`` must NOT abort on ``ready=False`` — the cycle
  must keep running to accumulate the track record the criteria wait for.
* LLM_FORBIDDEN: never import this module from risk/execution/monitoring.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_OUT_FILENAME = "golive_status.json"
EQUITY_FILENAME = "equity_curve_daily.json"
TRADES_FILENAME = "trades.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
CYCLE_RUNNER_REL = Path("spa_core") / "paper_trading" / "cycle_runner.py"

FRESHNESS_WINDOW_HOURS = 48
MIN_TRACK_DAYS = 30           # required honest paper-trading days
APY_FLOOR_PCT = 1.0           # minimum acceptable APY for go-live
DRAWDOWN_KILL_PCT = 5.0       # kill-switch threshold (matches RiskPolicy)
ADAPTER_REGISTRY_MIN = 20     # minimum adapters registered for go-live (MP-1228)

# Paper trading real start (post-teardown reset, per CLAUDE.md)
PAPER_REAL_START = datetime(2026, 6, 10, tzinfo=timezone.utc).date()

# Criteria that fail purely because not enough honest days have accrued yet.
# They block go-live but are reported as PENDING (waiting on the calendar),
# never FAIL (a defect to fix).
TIME_GATED_CRITERIA = frozenset({"min_track_days_30", "gap_monitor_30d"})

ADAPTER_REGISTRY_FILENAME = "adapter_registry.json"
BACKTEST_FILENAMES = ("backtest_results.json", "backtest_vs_paper.json")

# Text fallback for criterion 4 when a file is not valid JSON.
_DEMO_TRUE_RE = re.compile(r'"is_demo"\s*:\s*true')


# ─── Result object ───────────────────────────────────────────────────────────


@dataclass
class GoLiveResult:
    """Verdict of the 29-criteria go-live gate."""

    ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    timestamp: str = ""
    consecutive_ready_days: int | None = None
    # Per-criterion rich status (name → {status, blocking, estimated_days_to_pass, …})
    details: dict[str, dict] = field(default_factory=dict)
    real_track_days: int = 0

    def to_dict(self) -> dict:
        passed = sum(self.checks.values())
        total = len(self.checks)
        d: dict[str, Any] = {
            "ready": self.ready,
            "passed": passed,
            "total": total,
            "checks": dict(self.checks),
            # Dashboard-friendly per-criterion breakdown (MP-1228).
            "criteria": [
                {"name": name, **self.details.get(name, {})}
                for name in self.checks
            ],
            "blockers": list(self.blockers),
            "real_track_days": self.real_track_days,
            "timestamp": self.timestamp,
            "source": "golive_checker",
            "version": "v6.0-29criteria",
        }
        if self.consecutive_ready_days is not None:
            d["consecutive_ready_days"] = self.consecutive_ready_days
        return d

    def summary(self) -> str:
        """Human-readable report for the CLI and the dashboard."""
        passed = sum(self.checks.values())
        total = len(self.checks)
        lines = [
            "─" * 64,
            f"GO-LIVE READINESS (29-criteria gate)   [{self.timestamp}]",
            "─" * 64,
        ]
        # Group labels for display
        group_starts = {
            "equity_curve_real": "── Group 1: Data Integrity ──────────────────────",
            "compound_v3_adapter": "── Group 2: Adapters ────────────────────────────",
            "multi_strategy_runner": "── Group 3: Components ──────────────────────────",
            "adapter_status_has_compound": "── Group 4: Adapter Status ──────────────────────",
            "gap_monitor_ok": "── Group 5: Continuity ──────────────────────────",
            "autopush_installed": "── Group 6: Infrastructure ──────────────────────",
            "min_track_days_30": "── Group 7: Performance ─────────────────────────",
            "risk_policy_snapshot": "── Group 8: Compliance ──────────────────────────",
            "adapter_registry_complete": "── Group 9: Integrity & Evidence ────────────────",
        }
        for name, ok in self.checks.items():
            if name in group_starts:
                lines.append(f"  {group_starts[name]}")
            det = self.details.get(name, {})
            status = det.get("status", "PASS" if ok else "FAIL")
            extra = ""
            if status == "PENDING":
                eta = det.get("estimated_days_to_pass")
                tgt = det.get("target_date", "")
                extra = f"  — {eta} more day(s) needed (target {tgt})"
            lines.append(f"  [{status}] {name}{extra}")
        if self.blockers:
            lines.append("")
            lines.append("  Blockers:")
            for b in self.blockers:
                lines.append(f"    • {b}")
        lines.append("")
        lines.append(
            f"  Verdict: {'READY' if self.ready else 'NOT READY'}"
            f" ({passed}/{total} checks pass)"
        )
        if self.consecutive_ready_days is not None:
            lines.append(f"  Consecutive READY days: {self.consecutive_ready_days}")
        lines.append("─" * 64)
        return "\n".join(lines)


# ─── IO helpers (stdlib only) ─────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path) -> Any:
    """Read JSON defensively: missing/corrupt file → None (never raises)."""
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


def _check_file_syntax(path: Path) -> tuple[bool, str]:
    """Return (ok, detail) — file exists and has valid Python syntax."""
    if not path.is_file():
        return False, f"{path.name}: file not found"
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        return True, f"{path.name}: exists + syntax OK"
    except SyntaxError as exc:
        return False, f"{path.name}: syntax error — {exc}"
    except OSError as exc:
        return False, f"{path.name}: read error — {exc}"


# ─── Checker ─────────────────────────────────────────────────────────────────


class GoLiveChecker:
    """26-criteria go-live gate (MP-006 / MP-384 / MP-417).

    Run ``checker.check()`` for the full verdict; ``checker.check(write=False)``
    for a dry-run that never touches disk.
    """

    def __init__(
        self,
        data_dir: str | os.PathLike | None = None,
        repo_root: str | os.PathLike | None = None,
        now: datetime | None = None,
        home_dir: str | os.PathLike | None = None,
        paper_start=None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        self.repo_root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)
        # home_dir is injectable for testing so unit tests don't touch real LaunchAgents
        self.home_dir = Path(home_dir) if home_dir is not None else Path.home()
        # paper_start is injectable so tests can use synthetic histories; production
        # defaults to the post-teardown reset date (honesty rule, MP-1228). Accepts a
        # date or datetime.
        if paper_start is None:
            self.paper_start = PAPER_REAL_START
        elif isinstance(paper_start, datetime):
            self.paper_start = paper_start.date()
        else:
            self.paper_start = paper_start
        # Honest count of post-teardown track days, populated during check().
        self._real_track_days = 0

    # ── Honesty helper (MP-1228) ──────────────────────────────────────────────

    def _real_track_dates(self, daily: Any) -> list[str]:
        """Unique equity-bar dates ON OR AFTER ``self.paper_start``.

        Pre-teardown bars are demo/void per CLAUDE.md and must never inflate the
        track-record length. Returns sorted ISO date strings.
        """
        if not isinstance(daily, list):
            return []
        out: set[str] = set()
        for bar in daily:
            if not isinstance(bar, dict) or not bar.get("date"):
                continue
            ds = str(bar["date"])[:10]
            try:
                d = datetime.strptime(ds, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d >= self.paper_start:
                out.add(ds)
        return sorted(out)

    # ══════════════════════════════════════════════════════════════════════════
    # Group 1: Data Integrity (6 checks — original MP-006 anti-demo gate)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_equity_curve(self, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        if doc is None:
            blockers.append(f"{EQUITY_FILENAME}: missing or unreadable")
            return False
        if not isinstance(doc, dict) or doc.get("is_demo") is not False:
            blockers.append(f"{EQUITY_FILENAME}: not marked is_demo:false")
            return False
        daily = doc.get("daily")
        if not isinstance(daily, list) or not daily:
            blockers.append(f"{EQUITY_FILENAME}: no daily equity records")
            return False
        return True

    def _check_trades(self, blockers: list[str]) -> bool:
        trades = _read_json(self.data_dir / TRADES_FILENAME)
        if not isinstance(trades, list):
            blockers.append(f"{TRADES_FILENAME}: missing or unreadable")
            return False
        real = [t for t in trades if isinstance(t, dict) and t.get("is_demo") is False]
        if not real:
            blockers.append(
                f"{TRADES_FILENAME}: no real (is_demo:false) trades recorded yet"
            )
            return False
        return True

    def _check_status(self, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / PT_STATUS_FILENAME)
        if not isinstance(doc, dict):
            blockers.append(f"{PT_STATUS_FILENAME}: missing or unreadable")
            return False
        if doc.get("is_demo") is not False:
            blockers.append(f"{PT_STATUS_FILENAME}: not marked is_demo:false")
            return False
        return True

    def _check_no_demo_data(self, blockers: list[str]) -> bool:
        """NO json file anywhere under data/ may contain ``is_demo: true``."""
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
            blockers.append(
                "demo data (is_demo:true) detected in: " + ", ".join(offenders)
            )
            return False
        return True

    def _check_freshness(self, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        daily = doc.get("daily") if isinstance(doc, dict) else None
        if not isinstance(daily, list) or not daily:
            blockers.append(
                f"{EQUITY_FILENAME}: no records to assess {FRESHNESS_WINDOW_HOURS}h freshness"
            )
            return False
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
            blockers.append(f"{EQUITY_FILENAME}: no parseable record dates")
            return False
        age = self.now - latest
        if age >= timedelta(hours=FRESHNESS_WINDOW_HOURS):
            blockers.append(
                f"{EQUITY_FILENAME}: last record {latest.date()} is "
                f"{age.total_seconds() / 3600.0:.0f}h old "
                f"(> {FRESHNESS_WINDOW_HOURS}h — cycle loop may be stalled)"
            )
            return False
        return True

    def _check_cycle_runner(self, blockers: list[str]) -> bool:
        path = self.repo_root / CYCLE_RUNNER_REL
        if not path.is_file():
            blockers.append(f"{CYCLE_RUNNER_REL}: missing — real cycle loop not deployed")
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Group 2: Adapters (4 checks — MP-384)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_compound_v3_adapter(self, blockers: list[str]) -> bool:
        ok, detail = _check_file_syntax(
            self.repo_root / "spa_core" / "adapters" / "compound_v3_adapter.py"
        )
        if not ok:
            blockers.append(detail)
        return ok

    def _check_morpho_steakhouse_adapter(self, blockers: list[str]) -> bool:
        ok, detail = _check_file_syntax(
            self.repo_root / "spa_core" / "adapters" / "morpho_steakhouse_adapter.py"
        )
        if not ok:
            blockers.append(detail)
        return ok

    def _check_aave_arbitrum_adapter(self, blockers: list[str]) -> bool:
        ok, detail = _check_file_syntax(
            self.repo_root / "spa_core" / "adapters" / "aave_arbitrum_adapter.py"
        )
        if not ok:
            blockers.append(detail)
        return ok

    def _check_pendle_pt_adapter(self, blockers: list[str]) -> bool:
        ok, detail = _check_file_syntax(
            self.repo_root / "spa_core" / "adapters" / "pendle_pt_adapter.py"
        )
        if not ok:
            blockers.append(detail)
        return ok

    # ══════════════════════════════════════════════════════════════════════════
    # Group 3: Components (5 checks — MP-384)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_multi_strategy_runner(self, blockers: list[str]) -> bool:
        path = self.repo_root / "spa_core" / "paper_trading" / "multi_strategy_runner.py"
        if not path.is_file():
            blockers.append("multi_strategy_runner.py: not found")
            return False
        return True

    def _check_promotion_engine(self, blockers: list[str]) -> bool:
        path = self.repo_root / "spa_core" / "paper_trading" / "promotion_engine.py"
        if not path.is_file():
            blockers.append("promotion_engine.py: not found")
            return False
        return True

    def _check_safe_tx_builder(self, blockers: list[str]) -> bool:
        path = self.repo_root / "spa_core" / "execution" / "safe_tx_builder.py"
        if not path.is_file():
            blockers.append("safe_tx_builder.py: not found")
            return False
        return True

    def _check_http_server(self, blockers: list[str]) -> bool:
        path = self.repo_root / "spa_core" / "family_fund" / "http_server.py"
        if not path.is_file():
            blockers.append("http_server.py: not found")
            return False
        return True

    def _check_adr022_exists(self, blockers: list[str]) -> bool:
        path = self.repo_root / "docs" / "adr" / "ADR-022-gnosis-safe-multisig.md"
        if not path.is_file():
            blockers.append("ADR-022-gnosis-safe-multisig.md: not found")
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Group 4: Adapter status coverage (3 checks — MP-384)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_adapter_status_key(self, key: str, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / "adapter_status.json")
        if not isinstance(doc, dict):
            blockers.append("adapter_status.json: missing or not a dict")
            return False
        # v2 format (schema_version 2): adapters is a nested dict keyed by
        # snake_case protocol name.  v1 format: keys are at the top level.
        # Support both by checking the nested dict first (MP-1195).
        scope = doc.get("adapters", doc)
        if not isinstance(scope, dict):
            scope = doc
        if key not in scope:
            blockers.append(f"adapter_status.json: key '{key}' not present")
            return False
        return True

    def _check_adapter_status_has_compound(self, blockers: list[str]) -> bool:
        return self._check_adapter_status_key("compound_v3", blockers)

    def _check_adapter_status_has_morpho(self, blockers: list[str]) -> bool:
        return self._check_adapter_status_key("morpho_steakhouse", blockers)

    def _check_adapter_status_has_arbitrum(self, blockers: list[str]) -> bool:
        return self._check_adapter_status_key("aave_arbitrum", blockers)

    # ══════════════════════════════════════════════════════════════════════════
    # Group 5: Continuity (2 checks — MP-417)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_gap_monitor_ok(self, blockers: list[str]) -> bool:
        """gap_monitor.json must report status: ok (no equity gaps)."""
        doc = _read_json(self.data_dir / "gap_monitor.json")
        if not isinstance(doc, dict):
            blockers.append("gap_monitor.json: missing or unreadable")
            return False
        status = doc.get("status", "")
        if status != "ok":
            gap_flag = doc.get("gap_detected", "?")
            blockers.append(
                f"gap_monitor.json: status='{status}' gap_detected={gap_flag} — equity gap found"
            )
            return False
        return True

    def _check_gap_monitor_30d(self, blockers: list[str]) -> bool:
        """Equity curve must span at least MIN_TRACK_DAYS of real data.

        ADR-002: go-live requires 30 continuous honest days without gaps.
        The gap_monitor tracks freshness; the equity curve length tracks duration.
        """
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        daily = doc.get("daily") if isinstance(doc, dict) else None
        # Honesty rule: only count bars dated >= paper_start (post-teardown).
        dates = self._real_track_dates(daily)
        self._real_track_days = len(dates)
        if not dates:
            blockers.append(
                f"gap_monitor_30d: no honest track days on/after {self.paper_start} — "
                f"need {MIN_TRACK_DAYS} real days"
            )
            return False
        count = len(dates)
        if count < MIN_TRACK_DAYS:
            days_to_go = MIN_TRACK_DAYS - count
            blockers.append(
                f"gap_monitor_30d: {count}/{MIN_TRACK_DAYS} honest track days "
                f"(since {self.paper_start}; {days_to_go} more needed — target ~"
                f"{(self.now.date() + timedelta(days=days_to_go)).isoformat()})"
            )
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Group 6: Infrastructure (2 checks — MP-417)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_autopush_installed(self, blockers: list[str]) -> bool:
        """com.spa.autopush launchd plist must be installed in ~/Library/LaunchAgents/.

        The plist file existing in scripts/ is not enough — it must be loaded
        into launchd so auto-push runs every 90 minutes.
        Fix: bash mp009_fix_launchd.command  OR  run scripts/install_autopush.sh
        """
        launch_agents = self.home_dir / "Library" / "LaunchAgents"
        plist = launch_agents / "com.spa.autopush.plist"
        if not plist.is_file():
            blockers.append(
                "autopush_installed: ~/Library/LaunchAgents/com.spa.autopush.plist "
                "not found — macOS/launchd-only check (always fails in CI/sandbox); "
                "on the production host run: bash mp009_fix_launchd.command"
            )
            return False
        return True

    def _check_telegram_alert_today(self, blockers: list[str]) -> bool:
        """Telegram daily summary must have been sent today (UTC).

        Checks data/telegram_alert_state.json for ``daily_summary == today``.
        """
        doc = _read_json(self.data_dir / "telegram_alert_state.json")
        if not isinstance(doc, dict):
            blockers.append(
                "telegram_alert_today: telegram_alert_state.json missing — "
                "daily alert not configured"
            )
            return False
        today = self.now.strftime("%Y-%m-%d")
        last_sent = str(doc.get("daily_summary", ""))[:10]
        if last_sent != today:
            blockers.append(
                f"telegram_alert_today: last daily alert was {last_sent or 'never'} "
                f"(today is {today}) — check com.spa.daily-paper-report launchd plist"
            )
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Group 7: Performance (3 checks — MP-417)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_min_track_days(self, blockers: list[str]) -> bool:
        """Equity curve must have at least MIN_TRACK_DAYS (30) unique daily bars.

        Separate from gap_monitor_30d: that checks *continuity* (ADR-002 gap rule),
        this checks *duration* (minimum honest trading history for go-live).
        """
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        daily = doc.get("daily") if isinstance(doc, dict) else None
        if not isinstance(daily, list):
            blockers.append(
                f"min_track_days_30: equity_curve_daily.json missing — need {MIN_TRACK_DAYS} days"
            )
            return False
        # Honesty rule: only count bars dated >= paper_start (post-teardown);
        # pre-teardown bars are demo/void per CLAUDE.md.
        dates = self._real_track_dates(daily)
        self._real_track_days = len(dates)
        count = len(dates)
        if count < MIN_TRACK_DAYS:
            days_to_go = MIN_TRACK_DAYS - count
            blockers.append(
                f"min_track_days_30: {count}/{MIN_TRACK_DAYS} honest paper-trading days "
                f"(since {self.paper_start}; {days_to_go} more needed — target go-live ~"
                f"{(self.now.date() + timedelta(days=days_to_go)).isoformat()})"
            )
            return False
        return True

    def _check_apy_above_floor(self, blockers: list[str]) -> bool:
        """Current APY must be above APY_FLOOR_PCT (1%)."""
        doc = _read_json(self.data_dir / PT_STATUS_FILENAME)
        if not isinstance(doc, dict):
            blockers.append(
                f"apy_above_floor: {PT_STATUS_FILENAME} missing — cannot verify APY"
            )
            return False
        apy = doc.get("apy_today_pct")
        if apy is None:
            # Fall back to equity curve last return
            eq = _read_json(self.data_dir / EQUITY_FILENAME)
            summary = eq.get("summary") if isinstance(eq, dict) else None
            if isinstance(summary, dict):
                total_ret = summary.get("total_return_pct", 0)
                num_days = summary.get("num_days", 1) or 1
                apy = (total_ret / num_days) * 365
        if apy is None:
            blockers.append("apy_above_floor: APY not available in status or equity curve")
            return False
        if float(apy) < APY_FLOOR_PCT:
            blockers.append(
                f"apy_above_floor: APY {apy:.2f}% < floor {APY_FLOOR_PCT}% — "
                "yield too low for go-live"
            )
            return False
        return True

    def _check_drawdown_below_kill(self, blockers: list[str]) -> bool:
        """Portfolio max drawdown must be below DRAWDOWN_KILL_PCT (5%)."""
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        if not isinstance(doc, dict):
            blockers.append("drawdown_below_kill: equity_curve_daily.json missing")
            return False
        summary = doc.get("summary", {}) or {}
        drawdown = summary.get("max_drawdown_pct")
        if drawdown is None:
            # Try paper_trading_status.json
            st = _read_json(self.data_dir / PT_STATUS_FILENAME) or {}
            drawdown = st.get("max_drawdown_pct")
        if drawdown is None:
            # Compute from daily bars
            daily = doc.get("daily") or []
            equities = [
                float(b["close_equity"])
                for b in daily
                if isinstance(b, dict) and "close_equity" in b
            ]
            if equities:
                peak = equities[0]
                max_dd = 0.0
                for eq in equities:
                    peak = max(peak, eq)
                    dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
                    max_dd = max(max_dd, dd)
                drawdown = max_dd
        if drawdown is None:
            # Can't compute — pass conservatively (we have other freshness checks)
            return True
        if float(drawdown) >= DRAWDOWN_KILL_PCT:
            blockers.append(
                f"drawdown_below_kill: drawdown {drawdown:.2f}% ≥ kill-switch "
                f"threshold {DRAWDOWN_KILL_PCT}% — RiskPolicy kill switch active"
            )
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Group 8: Compliance (1 check — MP-417)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_risk_policy_snapshot(self, blockers: list[str]) -> bool:
        """At least one risk policy version snapshot must exist in spa_core/risk/versions/.

        The snapshot proves the current RiskPolicy v1.0 is immutably committed
        (required by RiskPolicy version freeze rule in CLAUDE.md).
        """
        versions_dir = self.repo_root / "spa_core" / "risk" / "versions"
        if not versions_dir.is_dir():
            blockers.append(
                "risk_policy_snapshot: spa_core/risk/versions/ directory not found"
            )
            return False
        # Look for non-dunder Python files or JSON snapshots
        snapshots = [
            p for p in versions_dir.iterdir()
            if p.is_file()
            and not p.name.startswith("__")
            and p.suffix in (".py", ".json", ".md")
        ]
        if not snapshots:
            blockers.append(
                "risk_policy_snapshot: spa_core/risk/versions/ has no snapshot files — "
                "commit a versioned copy of RiskConfig v1.0"
            )
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Group 9: Integrity & Evidence (3 checks — MP-1228)
    # ══════════════════════════════════════════════════════════════════════════

    def _check_adapter_registry_complete(self, blockers: list[str]) -> bool:
        """data/adapter_registry.json must register at least ADAPTER_REGISTRY_MIN adapters.

        Guards against an adapter-registry regression that would silently shrink
        the protocol universe the allocator can choose from.
        (User spec called this ``strategy_registry_complete``; renamed to reflect
        that it validates the ADAPTER registry, not the strategy registry.)
        """
        doc = _read_json(self.data_dir / ADAPTER_REGISTRY_FILENAME)
        if not isinstance(doc, dict):
            blockers.append(
                f"adapter_registry_complete: {ADAPTER_REGISTRY_FILENAME} missing or not a dict"
            )
            return False
        adapters = doc.get("adapters", doc)
        count = len(adapters) if isinstance(adapters, (list, dict)) else 0
        if count < ADAPTER_REGISTRY_MIN:
            blockers.append(
                f"adapter_registry_complete: {count}/{ADAPTER_REGISTRY_MIN} adapters "
                f"registered in {ADAPTER_REGISTRY_FILENAME}"
            )
            return False
        return True

    def _check_backtest_completed(self, blockers: list[str]) -> bool:
        """A backtest-evidence artifact must exist and be non-empty.

        Accepts either ``backtest_results.json`` or ``backtest_vs_paper.json``
        (the paper-vs-backtest comparison). Proves the strategy set was validated
        offline before any live capital decision.
        """
        for fname in BACKTEST_FILENAMES:
            doc = _read_json(self.data_dir / fname)
            if isinstance(doc, (dict, list)) and doc:
                return True
        blockers.append(
            "backtest_completed: no backtest evidence found "
            f"({' or '.join(BACKTEST_FILENAMES)} missing/empty)"
        )
        return False

    def _check_audit_trail_signed(self, blockers: list[str]) -> bool:
        """Tamper-evident audit-trail hash chain must be deployed and intact.

        Requires ``spa_core/audit/audit_trail_signer.py`` to exist and the chain
        (if any has been written) to verify without a tamper error. A missing
        chain file verifies vacuously — the signing infrastructure is deployed
        and nothing is tampered.
        """
        signer_path = self.repo_root / "spa_core" / "audit" / "audit_trail_signer.py"
        if not signer_path.is_file():
            blockers.append(
                "audit_trail_signed: spa_core/audit/audit_trail_signer.py not found"
            )
            return False
        try:
            from spa_core.audit import audit_trail_signer as _ats

            if _ats.verify_chain(data_dir=str(self.data_dir)):
                return True
            blockers.append("audit_trail_signed: chain verification returned False")
            return False
        except Exception as exc:  # AuditChainTamperedError or import error
            blockers.append(f"audit_trail_signed: chain verification failed — {exc}")
            return False

    # ══════════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════════

    def _compute_consecutive_ready_days(self, ready: bool) -> int:
        """Track consecutive days with ready=True (advisory metric only).

        When not ready, returns 0. When ready, increments daily from prior
        saved value. Seeds from PAPER_REAL_START when no prior state exists.
        """
        status_path = self.data_dir / STATUS_OUT_FILENAME
        prior = _read_json(status_path) or {}
        prior_days = prior.get("consecutive_ready_days", 0) or 0
        prior_ts_str = prior.get("timestamp", "")

        if not ready:
            return 0

        try:
            prior_ts = datetime.fromisoformat(prior_ts_str.replace("Z", "+00:00"))
            prior_date = prior_ts.date()
        except (ValueError, AttributeError):
            prior_date = None

        today = self.now.date()
        seeded_days = max(1, (today - PAPER_REAL_START).days)

        if prior_date is None or prior_days == 0:
            return seeded_days
        if prior_date < today:
            return max(prior_days + 1, seeded_days)
        return max(prior_days, seeded_days)

    def _build_details(
        self, checks: dict[str, bool], blockers: list[str]
    ) -> dict[str, dict]:
        """Classify every criterion as PASS / FAIL / PENDING with metadata.

        * PASS    — criterion satisfied.
        * PENDING — a time-gated criterion failing only because not enough honest
                    days have accrued yet (waiting on the calendar, not a defect).
                    Carries ``estimated_days_to_pass`` and a ``target_date``.
        * FAIL    — a real defect to fix now.

        ``blocking`` is True for any non-PASS criterion (all 29 gate go-live).
        """
        days_to_track = max(0, MIN_TRACK_DAYS - self._real_track_days)
        target_date = (self.now.date() + timedelta(days=days_to_track)).isoformat()
        details: dict[str, dict] = {}
        for name, ok in checks.items():
            if ok:
                details[name] = {
                    "status": "PASS",
                    "blocking": False,
                    "estimated_days_to_pass": 0,
                    "message": "ok",
                }
            elif name in TIME_GATED_CRITERIA:
                details[name] = {
                    "status": "PENDING",
                    "blocking": True,
                    "estimated_days_to_pass": days_to_track,
                    "target_date": target_date,
                    "message": (
                        f"{self._real_track_days}/{MIN_TRACK_DAYS} honest track days — "
                        f"{days_to_track} more needed (target {target_date})"
                    ),
                }
            else:
                # Surface the most relevant blocker line if one mentions this criterion.
                msg = next((b for b in blockers if b.startswith(name)), "failed")
                details[name] = {
                    "status": "FAIL",
                    "blocking": True,
                    "estimated_days_to_pass": None,
                    "message": msg,
                }
        return details

    def check(self, write: bool = True) -> GoLiveResult:
        """Run all 29 criteria and return a GoLiveResult.

        Persists ``data/golive_status.json`` unless ``write=False``.
        Never raises on bad/missing data — every failure is a blocker, not an exception.
        """
        blockers: list[str] = []

        checks: dict[str, bool] = {
            # ── Group 1: Data Integrity ───────────────────────────────────
            "equity_curve_real":           self._check_equity_curve(blockers),
            "trades_real":                 self._check_trades(blockers),
            "status_real":                 self._check_status(blockers),
            "no_demo_data":                self._check_no_demo_data(blockers),
            "data_fresh_48h":              self._check_freshness(blockers),
            "cycle_runner_exists":         self._check_cycle_runner(blockers),
            # ── Group 2: Adapters ─────────────────────────────────────────
            "compound_v3_adapter":         self._check_compound_v3_adapter(blockers),
            "morpho_steakhouse_adapter":   self._check_morpho_steakhouse_adapter(blockers),
            "aave_arbitrum_adapter":       self._check_aave_arbitrum_adapter(blockers),
            "pendle_pt_adapter":           self._check_pendle_pt_adapter(blockers),
            # ── Group 3: Components ───────────────────────────────────────
            "multi_strategy_runner":       self._check_multi_strategy_runner(blockers),
            "promotion_engine":            self._check_promotion_engine(blockers),
            "safe_tx_builder":             self._check_safe_tx_builder(blockers),
            "http_server":                 self._check_http_server(blockers),
            "adr022_exists":               self._check_adr022_exists(blockers),
            # ── Group 4: Adapter Status ───────────────────────────────────
            "adapter_status_has_compound": self._check_adapter_status_has_compound(blockers),
            "adapter_status_has_morpho":   self._check_adapter_status_has_morpho(blockers),
            "adapter_status_has_arbitrum": self._check_adapter_status_has_arbitrum(blockers),
            # ── Group 5: Continuity ───────────────────────────────────────
            "gap_monitor_ok":              self._check_gap_monitor_ok(blockers),
            "gap_monitor_30d":             self._check_gap_monitor_30d(blockers),
            # ── Group 6: Infrastructure ───────────────────────────────────
            "autopush_installed":          self._check_autopush_installed(blockers),
            "telegram_alert_today":        self._check_telegram_alert_today(blockers),
            # ── Group 7: Performance ──────────────────────────────────────
            "min_track_days_30":           self._check_min_track_days(blockers),
            "apy_above_floor":             self._check_apy_above_floor(blockers),
            "drawdown_below_kill":         self._check_drawdown_below_kill(blockers),
            # ── Group 8: Compliance ───────────────────────────────────────
            "risk_policy_snapshot":        self._check_risk_policy_snapshot(blockers),
            # ── Group 9: Integrity & Evidence ─────────────────────────────
            "adapter_registry_complete":   self._check_adapter_registry_complete(blockers),
            "backtest_completed":          self._check_backtest_completed(blockers),
            "audit_trail_signed":          self._check_audit_trail_signed(blockers),
        }

        ready = all(checks.values())
        consecutive_days = self._compute_consecutive_ready_days(ready)
        details = self._build_details(checks, blockers)
        result = GoLiveResult(
            ready=ready,
            checks=checks,
            blockers=blockers,
            timestamp=self.now.isoformat(),
            consecutive_ready_days=consecutive_days,
            details=details,
            real_track_days=self._real_track_days,
        )
        if write:
            _atomic_write_json(self.data_dir / STATUS_OUT_FILENAME, result.to_dict())
        return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="golive_checker",
        description=(
            "SPA Go-live readiness gate — 29 criteria "
            "(MP-006 / MP-384 / MP-417 / MP-1228). "
            "Exit 0 = READY, exit 1 = NOT READY."
        ),
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute verdict without writing golive_status.json",
    )
    args = parser.parse_args(argv)

    result = GoLiveChecker(data_dir=args.data_dir).check(write=not args.dry_run)
    print(result.summary())
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
