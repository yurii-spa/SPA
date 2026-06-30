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
from spa_core.paper_trading.track_evidence import (
    evidenced_dates as _evidenced_dates,
    first_evidenced_date as _first_evidenced_date,
    real_max_drawdown_pct as _real_max_drawdown_pct,
    real_total_return_pct as _real_total_return_pct,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_OUT_FILENAME = "golive_status.json"
EQUITY_FILENAME = "equity_curve_daily.json"
TRADES_FILENAME = "trades.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
CYCLE_RUNNER_REL = Path("spa_core") / "paper_trading" / "cycle_runner.py"

FRESHNESS_WINDOW_HOURS = 48
# The daily digest (com.spa.digest_daily) fires ~08:10 UTC. Before that hour the
# telegram_alert_today criterion grants a grace pass IF yesterday's digest sent
# (the most recent DUE digest went out, today's just hasn't fired yet) — stops a
# recurring pre-08:10 false-dip without ever fabricating a send (WS-2.4).
DIGEST_GRACE_UNTIL_HOUR = 9   # UTC hour; grace applies while now.hour < this
MIN_TRACK_DAYS = 30           # required honest paper-trading days
APY_FLOOR_PCT = 1.0           # minimum acceptable APY for go-live
# Go-live drawdown GATE = the SOFT-derisk tier (5%), NOT the kill switch.
# Per ADR-048/049 the two-tier ladder is SOFT-derisk at 5% (halt new/increase, no
# liquidation) and HARD kill (all-cash) at 10%. Go-live deliberately gates on the
# stricter SOFT tier: the track must stay under 5% drawdown to be go-live-ready.
# The 5.0 value + the FAIL behaviour are OWNER-GATED (do not change without an ADR).
GOLIVE_MAX_DRAWDOWN_PCT = 5.0  # SOFT-derisk tier; HARD kill is 10% (kill_switch.py)
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
    # Honest go-live anchor + target, derived from the first EVIDENCED track day.
    # ``evidenced_anchor`` = first day a real daily_cycle ran (2026-06-22 on the
    # live track); ``target_date`` = anchor + (MIN_TRACK_DAYS - 1) (2026-07-21).
    # Both None until at least one evidenced day exists (fail-closed).
    evidenced_anchor: str | None = None
    target_date: str | None = None

    def to_dict(self) -> dict:
        passed = sum(self.checks.values())
        total = len(self.checks)
        # FAIL-CLOSED INVARIANT (WS-2.4, architect-flagged): the serialized
        # ``ready`` can NEVER be True unless EVERY criterion passes. We re-derive
        # it here from ``checks`` rather than trusting the stored ``self.ready``
        # field, so a corrupted/partial result object or an out-of-band mutation
        # that flipped ``ready`` true while a check is still False can never leak
        # a fabricated "ready_for_live" to any consumer. ``ready`` is the AND of
        # all checks AND requires the full criteria set to be present.
        ready = bool(self.ready) and total > 0 and all(self.checks.values())
        d: dict[str, Any] = {
            "ready": ready,
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
            # Honest derived anchor + target — every consumer reads the ONE
            # canonical value here instead of re-deriving or hardcoding it.
            "evidenced_anchor": self.evidenced_anchor,
            "target_date": self.target_date,
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
        """Unique EVIDENCED equity-bar dates ON OR AFTER ``self.paper_start``.

        HONEST TRACK RESET (operator-approved, 2026-06-26)
        ==================================================
        The go-live track counts ONLY days backed by real evidence that a live
        ``daily_cycle`` actually ran. Three classes of bar are NOT evidenced and
        are excluded from the count (history is preserved on disk, just flagged):

        * ``reconstructed: true`` — interpolated placeholder (no live cycle ran).
        * flat-rate **backfill** (``evidenced: false`` / ``source: "backfill"``)
          — constant apy/yield/positions, zero down days, no cycle log.
        * warmup / pre-teardown bars (dated < ``paper_start``).

        Counting is delegated to
        :func:`spa_core.paper_trading.track_evidence.is_evidenced_bar`, which is
        the single source of truth for the evidenced-day definition. Bars are
        labelled honestly (``evidenced`` / ``source``) by ``track_evidence``;
        this gate simply trusts those labels. Legacy/synthetic bars with no
        explicit honesty label are still counted (backward-compat), so only the
        flat-rate backfill and reconstructed days are dropped from the real
        track.

        MONOTONE day-count (WS-2.4): counting is via ``sorted(set(...))`` so
        duplicate / out-of-order dates can never over-count, and ``today`` is
        pinned to the checker's UTC ``now`` so a FUTURE-dated bar (which cannot
        evidence a cycle that has not run yet) is excluded.
        """
        return _evidenced_dates(
            daily, paper_start=self.paper_start, today=self.now.date()
        )

    def _evidenced_anchor(self, daily: Any):
        """First evidenced track date (the honest anchor), or None.

        The go-live target is ``anchor + MIN_TRACK_DAYS``: 30 evidenced days
        from the first real cycle day. Returns a ``date`` or None when no
        evidenced day exists yet.
        """
        iso = _first_evidenced_date(daily, paper_start=self.paper_start)
        if not iso:
            return None
        try:
            return datetime.strptime(iso, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _target_date_from_anchor(self, daily: Any) -> str | None:
        """Honest go-live target = first_evidenced + (MIN_TRACK_DAYS - 1) days, or None.

        Anchored STRICTLY to the first EVIDENCED day so the target is a fixed
        calendar date that does not drift day to day. Fail-CLOSED: when no
        evidenced day exists yet there is no honest anchor → returns None (the
        criteria stay PENDING with no fabricated target). The 11 unevidenced
        backfill days (2026-06-10..21) never anchor the target — only real
        cycle-evidenced days do, so the live anchor is 2026-06-22 → 2026-07-21.
        """
        anchor = self._evidenced_anchor(daily)
        if anchor is None:
            return None
        return (anchor + timedelta(days=MIN_TRACK_DAYS - 1)).isoformat()

    def _golive_target_date(self, daily: Any) -> str:
        """Display-string form of the honest target for blocker/criterion text.

        Returns the evidenced-anchored target when available, else the literal
        ``"pending"`` (no evidenced day yet → no honest calendar target).
        """
        target = self._target_date_from_anchor(daily)
        return target if target is not None else "pending"

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
            anchor = dates[0] if dates else self.paper_start.isoformat()
            blockers.append(
                f"gap_monitor_30d: {count}/{MIN_TRACK_DAYS} evidenced track days "
                f"(anchor {anchor}; {days_to_go} more needed — target ~"
                f"{self._golive_target_date(daily)})"
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
        """Telegram daily summary sent today (UTC), with a pre-digest grace.

        Gate: data/telegram_alert_state.json must carry ``daily_summary`` written
        ONLY on a SUCCESSFUL send by the SOLE daily-alert owner com.spa.digest_daily
        (~08:10 UTC → spa_core.telegram.reports.daily). A same-UTC-day value means
        the digest genuinely went out today — never force-passed.

        WS-2.4 PRE-DIGEST GRACE (stop the daily false-dip): the digest only fires
        ~08:10 UTC, so before that the criterion would FAIL every single morning
        even though nothing is wrong — a recurring transient dip the owner kept
        seeing. We now also PASS when YESTERDAY's digest sent AND we are still
        inside the pre-fire window (UTC hour < DIGEST_GRACE_UNTIL_HOUR): the
        most-recent expected digest (yesterday's) DID go out and today's simply
        has not fired yet. This is honest — it requires a real successful send on
        the most recent due day; it never fabricates a send. It does NOT mask a
        genuine miss: once past the grace hour, or if yesterday ALSO did not
        send, the criterion fails (visibly) until today's digest fires.
        """
        doc = _read_json(self.data_dir / "telegram_alert_state.json")
        if not isinstance(doc, dict):
            blockers.append(
                "telegram_alert_today: data/telegram_alert_state.json missing — "
                "the daily digest (com.spa.digest_daily @08:10 UTC) has not "
                "written its send-state yet; it is created on the first "
                "successful daily digest send"
            )
            return False
        today = self.now.strftime("%Y-%m-%d")
        last_sent = str(doc.get("daily_summary", ""))[:10]
        if last_sent == today:
            return True

        # Pre-digest grace: yesterday's digest sent + still before today's fire.
        yesterday = (self.now.date() - timedelta(days=1)).isoformat()
        if last_sent == yesterday and self.now.hour < DIGEST_GRACE_UNTIL_HOUR:
            return True

        blockers.append(
            f"telegram_alert_today: daily digest has not run yet today "
            f"(last sent {last_sent or 'never'}, today is {today}) — "
            f"com.spa.digest_daily fires ~08:10 UTC; this clears once today's "
            f"digest sends (not a Telegram outage)"
        )
        return False

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
            anchor = dates[0] if dates else self.paper_start.isoformat()
            blockers.append(
                f"min_track_days_30: {count}/{MIN_TRACK_DAYS} evidenced paper-trading days "
                f"(anchor {anchor}; {days_to_go} more needed — target go-live ~"
                f"{self._golive_target_date(daily)})"
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
            # Fall back to the EVIDENCED equity series only (T10): annualize the
            # real total return over the real track length. The summary roll-up
            # (total_return_pct / num_days) spans warmup/backfill bars and would
            # mis-state the real APY, so it is never used here.
            eq = _read_json(self.data_dir / EQUITY_FILENAME)
            eq_daily = eq.get("daily") if isinstance(eq, dict) else None
            real_dates = self._real_track_dates(eq_daily)
            real_days = max(1, len(real_dates))
            total_ret = _real_total_return_pct(eq_daily, paper_start=self.paper_start)
            apy = (total_ret / real_days) * 365
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
        """Portfolio max drawdown must be below GOLIVE_MAX_DRAWDOWN_PCT (5%).

        This is the go-live DRAWDOWN GATE = the SOFT-derisk tier (5%), NOT the
        kill switch (the HARD all-cash kill is 10%, ADR-048). Go-live gates on the
        stricter soft tier on purpose.

        HONEST TRACK RESET (T10, 2026-06-26): drawdown is a REAL go-live metric,
        so it is computed STRICTLY over the EVIDENCED series — never over the
        ``summary.max_drawdown_pct`` roll-up, which spans warmup/backfill/
        reconstructed bars and can fabricate a drawdown that the real track never
        experienced (e.g. the warmup→06-10 backfill discontinuity reads as a fake
        -0.20% drawdown while the real 06-22..26 series is monotonic, dd 0.00%).
        Segregated via :func:`track_evidence.real_max_drawdown_pct`.
        """
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        if not isinstance(doc, dict):
            blockers.append("drawdown_below_kill: equity_curve_daily.json missing")
            return False
        daily = doc.get("daily")
        # real_max_drawdown_pct returns a non-positive % (≤ 0.0); the kill
        # threshold is a magnitude, so compare against its absolute value.
        real_dd = _real_max_drawdown_pct(daily, paper_start=self.paper_start)
        drawdown = abs(real_dd)
        if float(drawdown) >= GOLIVE_MAX_DRAWDOWN_PCT:
            blockers.append(
                f"drawdown_below_kill: drawdown {drawdown:.2f}% ≥ go-live drawdown "
                f"gate {GOLIVE_MAX_DRAWDOWN_PCT}% (SOFT-derisk tier; HARD kill is "
                f"10%, ADR-048)"
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
        # Honest go-live target anchored to the first EVIDENCED day (fixed
        # calendar date, does not drift). Fail-CLOSED: None when no evidenced
        # day exists yet (criteria stay PENDING with no fabricated target).
        eq_doc = _read_json(self.data_dir / EQUITY_FILENAME)
        eq_daily = eq_doc.get("daily") if isinstance(eq_doc, dict) else None
        target_date = self._target_date_from_anchor(eq_daily)
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
                target_txt = target_date if target_date is not None else "pending"
                details[name] = {
                    "status": "PENDING",
                    "blocking": True,
                    "estimated_days_to_pass": days_to_track,
                    "target_date": target_date,
                    "message": (
                        f"{self._real_track_days}/{MIN_TRACK_DAYS} honest track days — "
                        f"{days_to_track} more needed (target {target_txt})"
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
        # Honest derived anchor + target (fail-closed: None until first evidenced
        # day). Surfaced as top-level fields so every consumer reads ONE value.
        eq_doc = _read_json(self.data_dir / EQUITY_FILENAME)
        eq_daily = eq_doc.get("daily") if isinstance(eq_doc, dict) else None
        anchor = self._evidenced_anchor(eq_daily)
        result = GoLiveResult(
            ready=ready,
            checks=checks,
            blockers=blockers,
            timestamp=self.now.isoformat(),
            consecutive_ready_days=consecutive_days,
            details=details,
            real_track_days=self._real_track_days,
            evidenced_anchor=anchor.isoformat() if anchor is not None else None,
            target_date=self._target_date_from_anchor(eq_daily),
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
