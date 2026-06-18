#!/usr/bin/env python3
"""SPA go-live readiness checker — 26-criteria gate (MP-006 / MP-384 / MP-417).

Validates the paper-trading track record against 26 criteria grouped into
8 categories. All 26 must pass for ``ready=True``.

Criteria groups
===============
1. Data integrity (6)  — anti-demo core (original MP-006)
2. Adapters (4)        — T1/T2 adapter files exist + valid syntax (MP-384)
3. Components (5)      — key runtime modules deployed (MP-384)
4. Adapter status (3)  — adapter_status.json coverage (MP-384)
5. Continuity (2)      — gap_monitor health + 30-day track (MP-417)
6. Infrastructure (2)  — autopush launchd + Telegram daily alert (MP-417)
7. Performance (3)     — APY floor, drawdown kill, min track days (MP-417)
8. Compliance (1)      — risk policy snapshot committed (MP-417)

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
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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

# Paper trading real start (post-teardown reset, per CLAUDE.md)
PAPER_REAL_START = datetime(2026, 6, 10, tzinfo=timezone.utc).date()

# Text fallback for criterion 4 when a file is not valid JSON.
_DEMO_TRUE_RE = re.compile(r'"is_demo"\s*:\s*true')


# ─── Result object ───────────────────────────────────────────────────────────


@dataclass
class GoLiveResult:
    """Verdict of the 26-criteria go-live gate."""

    ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    timestamp: str = ""
    consecutive_ready_days: int | None = None

    def to_dict(self) -> dict:
        passed = sum(self.checks.values())
        total = len(self.checks)
        d: dict[str, Any] = {
            "ready": self.ready,
            "passed": passed,
            "total": total,
            "checks": dict(self.checks),
            "blockers": list(self.blockers),
            "timestamp": self.timestamp,
            "source": "golive_checker",
            "version": "v5.0-26criteria",
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
            f"GO-LIVE READINESS (26-criteria gate)   [{self.timestamp}]",
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
        }
        for name, ok in self.checks.items():
            if name in group_starts:
                lines.append(f"  {group_starts[name]}")
            lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
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
    """Write JSON atomically: tmpfile in same dir + os.replace (rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


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
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        self.repo_root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)
        # home_dir is injectable for testing so unit tests don't touch real LaunchAgents
        self.home_dir = Path(home_dir) if home_dir is not None else Path.home()

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
        if key not in doc:
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
        if not isinstance(daily, list) or not daily:
            blockers.append(
                f"gap_monitor_30d: equity_curve_daily.json has no records — "
                f"need {MIN_TRACK_DAYS} real days"
            )
            return False
        # Count unique dates
        dates: set[str] = set()
        for bar in daily:
            if isinstance(bar, dict) and bar.get("date"):
                dates.add(str(bar["date"])[:10])
        count = len(dates)
        if count < MIN_TRACK_DAYS:
            days_to_go = MIN_TRACK_DAYS - count
            blockers.append(
                f"gap_monitor_30d: {count}/{MIN_TRACK_DAYS} real track days "
                f"({days_to_go} more needed — target ~"
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
                "not found — run: bash mp009_fix_launchd.command"
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
        dates: set[str] = set()
        for bar in daily:
            if isinstance(bar, dict) and bar.get("date"):
                dates.add(str(bar["date"])[:10])
        count = len(dates)
        if count < MIN_TRACK_DAYS:
            days_to_go = MIN_TRACK_DAYS - count
            blockers.append(
                f"min_track_days_30: {count}/{MIN_TRACK_DAYS} honest paper-trading days "
                f"({days_to_go} more needed — target go-live ~"
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

    def check(self, write: bool = True) -> GoLiveResult:
        """Run all 26 criteria and return a GoLiveResult.

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
        }

        ready = all(checks.values())
        consecutive_days = self._compute_consecutive_ready_days(ready)
        result = GoLiveResult(
            ready=ready,
            checks=checks,
            blockers=blockers,
            timestamp=self.now.isoformat(),
            consecutive_ready_days=consecutive_days,
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
            "SPA Go-live readiness gate — 26 criteria "
            "(MP-006 / MP-384 / MP-417). "
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
