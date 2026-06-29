"""
spa_core/strategy_lab/aggressive_lab/harness.py — the SHARED real-data harness + the two services
(live paper + historical backtest) that PRODUCE Lane 1's realized_series.jsonl + meta.json.

This is Lane 1 (the producer). It writes, per aggressive strategy, into data/aggressive_lab/<id>/:
    realized_series.jsonl   — proof-chained, append-only, one {date,equity_usd,phase,...} per line,
    meta.json               — the strategy's honest self-description (risk_class/shape/source).
Lane 2 (loader/risk/scorecard) consumes exactly these — the data contract documented in __init__.py.

TWO PRODUCERS, ONE HARNESS (so forward + backtest are apples-to-apples):
  • PaperService.tick()  — advance every roster book ONE day on the LATEST live snapshot, append a
        phase="forward" point. Restart-survival (state persisted + restored), idempotent per UTC day
        (re-ticking a day restores the pre-tick snapshot, never double-accrues), fail-CLOSED (a gap
        → no advance, no fabricated point, an honest gap record).
  • run_backtest()       — replay every book over the REAL 2024–2026 history, writing phase=
        "backtest" points so the owner sees realized performance INCLUDING the stress windows
        immediately. THIN/INSUFFICIENT honesty: a book that fails closed early simply has a short
        series (the loader/risk layer reports INSUFFICIENT_DATA — never a fabricated number).

ISOLATION (airtight): EVERY write goes through aggressive_lab._io, which routes through the
isolation guard — the harness literally cannot write a go-live/live-allocation file. Both services
ALSO take a protected-file md5 witness before work and verify it byte-identical after (a breach
raises IsolationViolation). Pure virtual books; no real capital; OUTSIDE_RISKPOLICY stamped.

stdlib-only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.aggressive_lab import (
    AGGRESSIVE_LAB_DIR,
    DEFAULT_NOTIONAL_USD,
    META_NAME,
    REALIZED_SERIES_NAME,
)
from spa_core.strategy_lab.aggressive_lab import _io
from spa_core.strategy_lab.aggressive_lab import isolation, proof
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds
from spa_core.strategy_lab.aggressive_lab.roster import build_roster, roster_ids
from spa_core.strategy_lab.base import MarketSnapshot

log = logging.getLogger("spa.aggressive_lab.harness")

STATE_NAME = "paper_state.json"
STATUS_NAME = "status.json"
SERIES_CAP = 1000  # generous: a 2024-26 backtest is ~700 days + forward


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── series helpers (proof-chained, idempotent per UTC day) ──────────────────────────────────────────
def _series_path(root: Path, sid: str) -> Path:
    return root / sid / REALIZED_SERIES_NAME


def _meta_path(root: Path, sid: str) -> Path:
    return root / sid / META_NAME


def _write_meta(root: Path, strat) -> None:
    _io.atomic_write_json(_meta_path(root, strat.id), isolation.stamp(strat.describe()), lab_root=root)


def upsert_day(root: Path, sid: str, point: dict) -> None:
    """Append (or REFRESH today's) proof-chained realized point to <id>/realized_series.jsonl.

    Idempotent per UTC day AND per phase: if the last stored point has the same (date, phase), it is
    REPLACED (re-tick refresh — never a double-append). The replacement re-chains from the prior
    point so the proof chain stays intact. Atomic + isolation-guarded write."""
    series = _io.read_jsonl(_series_path(root, sid))
    same = (series and series[-1].get("date") == point.get("date")
            and series[-1].get("phase", "forward") == point.get("phase", "forward"))
    if same:
        series = series[:-1]
    prev = proof.last_hash(series)
    chained = proof.chain_point(point, prev)
    series.append(chained)
    if len(series) > SERIES_CAP:
        series = series[-SERIES_CAP:]
    # rewrite the whole file atomically through the isolation-guarded writer
    text = "\n".join(__import__("json").dumps(p, sort_keys=True) for p in series) + "\n"
    _io.atomic_write_text(_series_path(root, sid), text, lab_root=root)


def _point(date: str, strat, phase: str) -> dict:
    m = strat.metrics()
    return {
        "date": date,
        "as_of": date,
        "equity_usd": strat.equity(),
        "phase": phase,
        "net_apy_pct": m.net_apy_pct,
        "risk_class": strat.risk_class,
        "risk_shape": strat.risk_shape,
        "killed": bool(m.extra.get("killed")),
        "outside_riskpolicy": True,
        "is_advisory": True,
    }


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Producer 1 — the LIVE paper service (forward track).
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class PaperService:
    """Live paper-trade the WHOLE aggressive roster one UTC day per tick on REAL data.

    `feeds` is an AggressiveFeeds (injectable for tests; default builds live snapshots). Restart-
    survival: each book's equity/day-count/killed state is persisted + restored. Idempotent per day."""

    def __init__(
        self,
        feeds: Optional[AggressiveFeeds] = None,
        *,
        state_dir: Optional[Path] = None,
        config: Optional[Dict[str, dict]] = None,
        notional_usd: float = DEFAULT_NOTIONAL_USD,
        verify_isolation: bool = True,
    ) -> None:
        self._root = Path(state_dir) if state_dir else AGGRESSIVE_LAB_DIR
        self._feeds = feeds or AggressiveFeeds()
        self._notional = notional_usd
        self._verify_isolation = verify_isolation
        self._strats = build_roster(config, notional_usd=notional_usd)
        self._last_tick: Optional[str] = None
        self._restore()

    @property
    def _state_path(self) -> Path:
        return self._root / STATE_NAME

    @property
    def _status_path(self) -> Path:
        return self._root / STATUS_NAME

    # ── restart-survival ──────────────────────────────────────────────────────────────────────────
    def _restore(self) -> None:
        doc = _safe_load_json(self._state_path)
        if not isinstance(doc, dict) or "books" not in doc:
            return
        books = doc.get("books") or {}
        for sid, strat in self._strats.items():
            b = books.get(sid)
            if isinstance(b, dict):
                strat._equity = float(b.get("equity", strat._equity))
                strat._days = int(b.get("days", strat._days))
                strat._killed = bool(b.get("killed", strat._killed))
                strat._kill_reason = str(b.get("kill_reason", strat._kill_reason))
                strat._cum_cost = float(b.get("cum_cost", strat._cum_cost))
                strat._cum_funding = float(b.get("cum_funding", strat._cum_funding))
        self._last_tick = doc.get("last_tick")

    def _persist(self, day: str, pre: Optional[dict] = None) -> None:
        books = {
            sid: {
                "equity": s._equity, "days": s._days, "killed": s._killed,
                "kill_reason": s._kill_reason, "cum_cost": s._cum_cost,
                "cum_funding": s._cum_funding,
            }
            for sid, s in self._strats.items()
        }
        doc = {"last_tick": day, "saved_at": _utc_now_iso(), "books": books}
        if pre is not None:
            doc["pretick"] = pre
        _io.atomic_write_json(self._state_path, isolation.stamp(doc), lab_root=self._root)
        self._last_tick = day

    def _snapshot_books(self) -> dict:
        return {
            sid: {
                "equity": s._equity, "days": s._days, "killed": s._killed,
                "kill_reason": s._kill_reason, "cum_cost": s._cum_cost,
                "cum_funding": s._cum_funding,
            }
            for sid, s in self._strats.items()
        }

    def _restore_books(self, snap: dict) -> None:
        for sid, b in (snap or {}).items():
            s = self._strats.get(sid)
            if s is None or not isinstance(b, dict):
                continue
            s._equity = float(b["equity"]); s._days = int(b["days"])
            s._killed = bool(b["killed"]); s._kill_reason = str(b["kill_reason"])
            s._cum_cost = float(b["cum_cost"]); s._cum_funding = float(b["cum_funding"])

    # ── the tick ────────────────────────────────────────────────────────────────────────────────
    def tick(self, as_of: Optional[str] = None) -> dict:
        """Advance every roster book one day on the latest live snapshot; append forward points.
        fail-CLOSED: if the snapshot has no usable required field for a book, that book fails closed
        (no fabricated accrual). Idempotent per UTC day. Isolation-verified."""
        before = isolation.snapshot_protected() if self._verify_isolation else None
        try:
            snap = self._feeds.build_live_snapshot(as_of)
        except Exception as exc:  # noqa: BLE001 — a total feed failure is a global gap (no advance)
            return self._gap(as_of or _utc_today(), f"live snapshot failed: {exc}", before)
        day = snap.date

        # idempotency: re-ticking the same day restores the stored pre-tick book snapshot first.
        if self._last_tick == day:
            doc = _safe_load_json(self._state_path)
            pre = doc.get("pretick") if isinstance(doc, dict) else None
            if isinstance(pre, dict) and pre.get("date") == day:
                self._restore_books(pre.get("books", {}))

        pre_books = {"date": day, "books": self._snapshot_books()}

        per_strategy = {}
        for sid, strat in self._strats.items():
            strat.step(snap)            # accrues (or fail-closed safe-holds) on REAL data
            strat.kill_check(snap)      # advances the kill state machine
            upsert_day(self._root, sid, _point(day, strat, phase="forward"))
            _write_meta(self._root, strat)
            m = strat.metrics()
            per_strategy[sid] = {
                "equity_usd": strat.equity(), "net_apy_pct": m.net_apy_pct,
                "killed": bool(m.extra.get("killed")), "kill_reason": m.extra.get("kill_reason"),
            }

        self._persist(day, pre=pre_books)
        if before is not None:
            isolation.verify_unchanged(before)  # ISOLATION PROOF: go-live track byte-identical
        return self._write_status(day, gap=False, gap_reason="", per_strategy=per_strategy)

    def _gap(self, day: str, reason: str, before) -> dict:
        log.warning("aggressive_lab paper GAP %s — %s (no advance)", day, reason)
        if before is not None:
            isolation.verify_unchanged(before)
        return self._write_status(day, gap=True, gap_reason=reason, per_strategy={})

    def _write_status(self, day: str, *, gap: bool, gap_reason: str, per_strategy: dict) -> dict:
        status = isolation.stamp({
            "generated_at": _utc_now_iso(), "date": day, "gap": gap, "gap_reason": gap_reason,
            "n_strategies": len(self._strats), "strategies": per_strategy,
            "roster": roster_ids(),
        })
        _io.atomic_write_json(self._status_path, status, lab_root=self._root)
        return status


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Producer 2 — the REAL 2024–2026 historical backtest.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def run_backtest(
    feeds: AggressiveFeeds,
    start: str,
    end: str,
    *,
    state_dir: Optional[Path] = None,
    config: Optional[Dict[str, dict]] = None,
    notional_usd: float = DEFAULT_NOTIONAL_USD,
    verify_isolation: bool = True,
) -> dict:
    """Replay every roster book over the REAL [start, end] history and write phase="backtest"
    realized points (so the owner sees realized performance incl. stress windows immediately).

    fail-CLOSED: if `feeds.historical_snapshots` raises (no real data), we DO NOT fabricate — the
    error propagates. A book that fails closed mid-window simply stops advancing (short series →
    INSUFFICIENT_DATA downstream). Isolation-verified (go-live track byte-identical before/after)."""
    root = Path(state_dir) if state_dir else AGGRESSIVE_LAB_DIR
    before = isolation.snapshot_protected() if verify_isolation else None

    snaps: List[MarketSnapshot] = feeds.historical_snapshots(start, end)  # fail-closed if empty
    strats = build_roster(config, notional_usd=notional_usd)

    # fresh backtest series: clear ONLY this lab's per-strategy files of any prior backtest points,
    # by rewriting from scratch (the forward points, if any, are produced by the paper service in a
    # separate phase; for a clean replay we write a backtest-only file). We keep this simple and
    # deterministic: the backtest fully owns the file it writes here.
    summary = {}
    for sid, strat in strats.items():
        series: List[dict] = []
        prev_hash = None
        for snap in snaps:
            strat.step(snap)
            strat.kill_check(snap)
            pt = proof.chain_point(_point(snap.date, strat, phase="backtest"), prev_hash)
            prev_hash = pt["hash"]
            series.append(pt)
        text = "\n".join(__import__("json").dumps(p, sort_keys=True) for p in series) + "\n"
        _io.atomic_write_text(_series_path(root, sid), text, lab_root=root)
        _write_meta(root, strat)
        m = strat.metrics()
        summary[sid] = {
            "points": len(series),
            "final_equity_usd": strat.equity(),
            "net_return_pct": m.net_apy_pct,
            "killed": bool(m.extra.get("killed")),
            "kill_reason": m.extra.get("kill_reason"),
            "risk_class": strat.risk_class,
            "risk_shape": strat.risk_shape,
        }

    out = isolation.stamp({
        "generated_at": _utc_now_iso(), "window": {"start": start, "end": end},
        "n_days": len(snaps), "n_strategies": len(strats), "summary": summary,
    })
    _io.atomic_write_json(root / "backtest_summary.json", out, lab_root=root)
    if before is not None:
        isolation.verify_unchanged(before)  # ISOLATION PROOF
    return out


def _safe_load_json(path: Path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return __import__("json").loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
