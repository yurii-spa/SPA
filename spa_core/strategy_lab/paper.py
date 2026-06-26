"""
spa_core/strategy_lab/paper.py — the LIVE paper-trading service for the Strategy Lab.

ONE service paper-trades ALL strategies (variant_n, variant_d, engine_a/b/c, rwa_floor,
rwa_sleeve) on LIVE market data, persists a growing per-strategy time-series, and SURVIVES
RESTART. rwa_sleeve is the REAL allocatable T1 cash floor — it accrues a forward record at the
SAME live tokenized-T-bill rate the RWAFloor benchmark + the rwa_floor_curve use. The prior
launchd/background-script reset bug (state zeroed on every relaunch) is the thing this file
exists to NOT repeat: on init we RELOAD each strategy's persisted state from disk and restore
it into a freshly-built strategy object, rather than re-initialising to fresh capital.

DESIGN (mirrors spa_core/paper_trading/cycle_runner.py):
  - Restart-survival: every strategy's full internal book state is snapshotted to disk after
    each tick (data/strategy_lab_paper/<id>_state.json) and restored on the next start.
  - Idempotent per UTC day: re-ticking the same calendar day does NOT double-accrue — we
    restore the *pre-tick* snapshot of that day and replay the single tick, exactly like
    cycle_runner._upsert_equity_point drops a same-date bar and recomputes it.
  - Fail-CLOSED: if MarketData.latest() raises or the datapoint is invalid, we do NOT advance
    with fabricated data — we hold safe, record a gap, optionally Telegram-alert, and leave
    every strategy's prior state untouched.
  - Atomic writes everywhere (spa_core.utils.atomic).

stdlib only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab import config as lab_config
from spa_core.strategy_lab.base import InvalidDataError, Strategy
from spa_core.strategy_lab.data.market_data import MarketData
from spa_core.strategy_lab.strategies.baselines import build_baselines
from spa_core.strategy_lab.strategies.rwa_sleeve import RwaSleeve
from spa_core.strategy_lab.strategies.variant_d import VariantD
from spa_core.strategy_lab.strategies.variant_n import VariantN
from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.strategy_lab.paper")

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
STATE_DIR = _REPO_ROOT / "data" / "strategy_lab_paper"

SERIES_CAP = 400          # ring-buffer length per strategy time-series
KILLS_CAP = 500           # kills.jsonl is trimmed to this many lines on write
STATUS_NAME = "status.json"
KILLS_NAME = "kills.jsonl"

# Global-block keys that variant_n needs merged into its per-strategy config (cost + cadence).
_GLOBAL_PASSTHROUGH = (
    "funding_settles_per_day",
    "gas_usd_per_rebalance",
    "slippage_bps",
    "rebalance_bps",
)


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _jsonify(value):
    """Make a strategy instance attribute JSON-serializable (sets → sorted lists)."""
    if isinstance(value, set):
        return {"__set__": sorted(value)}
    return value


def _unjsonify(value):
    if isinstance(value, dict) and set(value.keys()) == {"__set__"}:
        return set(value["__set__"])
    return value


def _dump_strategy_state(strat: Strategy) -> dict:
    """Snapshot a strategy's full internal book state.

    All strategy instance attributes are JSON-friendly primitives (float/int/str/bool/None/
    dict/list) plus the occasional set, which we wrap. We snapshot the entire ``__dict__`` so
    we never silently miss a field a strategy adds — restart-survival stays complete by
    construction rather than by an enumerated allow-list that can drift out of date.
    """
    return {k: _jsonify(v) for k, v in strat.__dict__.items()}


def _restore_strategy_state(strat: Strategy, snap: dict) -> None:
    """Restore a previously-dumped snapshot into a freshly-built strategy object IN PLACE."""
    for k, v in snap.items():
        strat.__dict__[k] = _unjsonify(v)


class PaperService:
    """Live paper-trading service over the full Strategy-Lab strategy set.

    Restart-survival: on construction we build the strategies fresh, then OVERWRITE their
    internal state from the persisted ``<id>_state.json`` files (if present). A relaunch
    therefore continues the book rather than zeroing it.
    """

    def __init__(
        self,
        market_data: Optional[MarketData] = None,
        state_dir: Optional[Path] = None,
        config: Optional[dict] = None,
        telegram_send: Optional[Callable[[str], bool]] = None,
        alert_on_kill: bool = True,
        alert_on_gap: bool = True,
    ) -> None:
        self._state_dir = Path(state_dir) if state_dir else STATE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._cfg = config if config is not None else lab_config.load_config()
        self._md = market_data if market_data is not None else MarketData()
        self._alert_on_kill = alert_on_kill
        self._alert_on_gap = alert_on_gap

        # Telegram is injectable for tests; default to the canonical flood-guarded client.
        if telegram_send is not None:
            self._telegram_send = telegram_send
        else:
            self._telegram_send = self._default_telegram_send

        # Tracks the last UTC day we refreshed live market data on, so a single tick refreshes at
        # most once per calendar day (hourly launchd ticks must NOT re-fetch the network 24×/day).
        self._last_md_refresh_day: Optional[str] = None

        # Build the strategy set, then RESTORE persisted state (restart-survival).
        self._strategies: Dict[str, Strategy] = self._build_strategies()
        self._restore_all()

    # ── construction ────────────────────────────────────────────────────────────────────
    def _build_strategies(self) -> Dict[str, Strategy]:
        """Build all strategies at their configured capital (fresh, pre-restore)."""
        strategies_cfg = self._cfg.get("strategies", {})
        global_cfg = self._cfg.get("global", {})
        out: Dict[str, Strategy] = {}

        # variant_n: per-strategy block + the global cost/cadence params it reads in init().
        vn_block = dict(strategies_cfg["variant_n"])
        for k in _GLOBAL_PASSTHROUGH:
            vn_block[k] = global_cfg[k]
        vn = VariantN()
        vn.init(float(global_cfg["initial_capital"]), vn_block)
        out[vn.id] = vn

        # variant_d: its own block at the global initial capital (directional sleeve).
        vd = VariantD()
        vd.init(float(global_cfg["initial_capital"]), dict(strategies_cfg["variant_d"]))
        out[vd.id] = vd

        # engine_a/b/c + rwa_floor at their configured per-sleeve capital.
        for sid, strat in build_baselines(self._cfg).items():
            out[sid] = strat

        # rwa_sleeve: the REAL allocatable T1 cash floor (holds tokenized T-bills, accrues at the
        # SAME live rwa_feed rate the RWAFloor benchmark + the floor curve use). Building it here
        # gives the realized floor a forward paper record like every other sleeve (advisory,
        # disconnect (c) fix). Its capital comes from its own config block.
        rwa_block = strategies_cfg["rwa_sleeve"]
        rs = RwaSleeve()
        rs.init(float(rwa_block["capital_usd"]), dict(rwa_block))
        out[rs.id] = rs
        return out

    # ── persistence paths ─────────────────────────────────────────────────────────────────
    def _state_path(self, sid: str) -> Path:
        return self._state_dir / f"{sid}_state.json"

    def _series_path(self, sid: str) -> Path:
        return self._state_dir / f"{sid}_series.json"

    @property
    def _status_path(self) -> Path:
        return self._state_dir / STATUS_NAME

    @property
    def _kills_path(self) -> Path:
        return self._state_dir / KILLS_NAME

    # ── restart-survival ──────────────────────────────────────────────────────────────────
    def _restore_all(self) -> None:
        """Restore every strategy's persisted internal state into its built object.

        Missing/corrupt state file → the strategy keeps its fresh init (first run). The
        persisted ``__state_meta__`` carries last_tick_date for idempotency.
        """
        self._last_tick: Dict[str, Optional[str]] = {}
        for sid, strat in self._strategies.items():
            doc = atomic_load(str(self._state_path(sid)), default=None)
            if not isinstance(doc, dict) or "state" not in doc:
                self._last_tick[sid] = None
                continue
            try:
                _restore_strategy_state(strat, doc["state"])
                self._last_tick[sid] = doc.get("meta", {}).get("last_tick_date")
            except Exception as exc:  # noqa: BLE001 — a corrupt snapshot must not zero the book
                log.warning("restore failed for %s (keeping fresh init): %s", sid, exc)
                self._last_tick[sid] = None

    def _persist_state(self, sid: str, strat: Strategy, last_tick_date: str) -> None:
        # Preserve any existing `pretick` snapshot for this day: _persist_pretick() writes it
        # BEFORE we advance, and the same-day idempotent re-tick replays from it. Rebuilding the
        # doc from scratch here (the prior bug) silently dropped `pretick`, leaving the documented
        # replay path dead — re-ticks fell through to the bare skip branch instead of replaying.
        doc = atomic_load(str(self._state_path(sid)), default={})
        if not isinstance(doc, dict):
            doc = {}
        doc["meta"] = {
            "id": sid,
            "last_tick_date": last_tick_date,
            "saved_at": _utc_now_iso(),
        }
        doc["state"] = _dump_strategy_state(strat)
        atomic_save(doc, str(self._state_path(sid)))
        self._last_tick[sid] = last_tick_date

    def _persist_pretick(self, sid: str, snap: dict, date: str) -> None:
        """Stash the PRE-tick snapshot for the day so a same-day re-tick replays once (idempotent)."""
        doc = atomic_load(str(self._state_path(sid)), default={})
        if not isinstance(doc, dict):
            doc = {}
        doc.setdefault("pretick", {})
        doc["pretick"] = {"date": date, "state": snap}
        atomic_save(doc, str(self._state_path(sid)))

    # ── time-series ───────────────────────────────────────────────────────────────────────
    def _append_series_point(self, sid: str, point: dict) -> None:
        """Append a dated point to the strategy's time-series, refreshing a same-date trailing
        point (idempotent per UTC day, like cycle_runner's equity-bar upsert)."""
        doc = atomic_load(str(self._series_path(sid)), default={"id": sid, "series": []})
        if not isinstance(doc, dict):
            doc = {"id": sid, "series": []}
        series: List[dict] = doc.get("series") or []
        if series and series[-1].get("date") == point["date"]:
            series = series[:-1]  # refresh today's point rather than duplicate it
        series.append(point)
        if len(series) > SERIES_CAP:
            series = series[-SERIES_CAP:]
        doc["id"] = sid
        doc["series"] = series
        doc["generated_at"] = _utc_now_iso()
        atomic_save(doc, str(self._series_path(sid)))

    def _record_kill(self, sid: str, reason: str, date: str) -> None:
        """Append a kill event to kills.jsonl (trimmed ring) + fire a flood-guarded alert."""
        event = {
            "ts": _utc_now_iso(),
            "date": date,
            "strategy": sid,
            "reason": reason,
        }
        # Append + trim to KILLS_CAP lines (jsonl, atomic via read-all/rewrite).
        lines: List[str] = []
        if self._kills_path.exists():
            try:
                lines = self._kills_path.read_text().splitlines()
            except Exception:  # noqa: BLE001
                lines = []
        lines.append(json.dumps(event, sort_keys=True))
        if len(lines) > KILLS_CAP:
            lines = lines[-KILLS_CAP:]
        # atomic_save writes JSON; we want raw jsonl, so write via a tmp+replace by hand.
        tmp = self._kills_path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(str(tmp), str(self._kills_path))

        if self._alert_on_kill:
            self._telegram_send(
                f"🛑 Strategy Lab KILL — {sid}\n{reason}\n(paper, {date})"
            )

    # ── telegram (canonical flood-guarded client) ─────────────────────────────────────────
    @staticmethod
    def _default_telegram_send(text: str) -> bool:
        # RETIRED as a Telegram push (Phase-1 Telegram rebuild). Strategy-lab
        # paper updates are informational → digest queue, never pushed. Returns
        # False. Never raises.
        try:
            from spa_core.telegram import push_policy
            push_policy.enqueue_digest(
                "strategy_lab", "Strategy Lab paper", text,
                reason="strategy_lab_paper_retired_push",
            )
        except Exception as exc:  # noqa: BLE001 — alerts must never crash the service
            log.warning("strategy_lab paper: digest route failed: %s", exc)
        return False

    # ── live market-data refresh (once per UTC day) ───────────────────────────────────────
    def _refresh_market_data_if_due(self, utc_day: str) -> None:
        """Refresh the live market-data cache at most once per UTC day.

        The cached series' newest date only advances when the feeds are re-fetched. The hourly
        launchd tick must therefore trigger a refresh so ``latest()`` returns the current day's
        snapshot — but only the FIRST tick of each UTC day (subsequent same-day ticks reuse the
        cache, so we do not hammer the network 24×/day).

        Duck-typed: a market-data object WITHOUT a ``refresh`` method (e.g. the test FakeMarketData,
        whose date is driven directly via the injected snapshot) is left untouched. Fail-CLOSED:
        a refresh that raises propagates to the caller, which records a gap and does not advance —
        so a network failure never fabricates a date. On success we mark the day done; we only
        re-fetch the same day if a prior refresh FAILED (left the marker un-advanced)."""
        if self._last_md_refresh_day == utc_day:
            return
        refresh = getattr(self._md, "refresh", None)
        if not callable(refresh):
            # No refresh surface (injected fake): the snapshot's date is supplied directly.
            self._last_md_refresh_day = utc_day
            return
        refresh()  # may raise → fail-closed in tick() (gap, no advance, marker stays un-advanced)
        self._last_md_refresh_day = utc_day

    # ── the tick ──────────────────────────────────────────────────────────────────────────
    def tick(self) -> dict:
        """Advance ALL strategies one tick on the LATEST live market snapshot.

        FAIL-CLOSED: if the live fetch raises / yields no usable date, NO strategy is advanced
        and NO fabricated point is written — a gap is recorded and (optionally) alerted. Each
        per-strategy advance is itself idempotent per UTC day.

        Returns the freshly-written status dict.
        """
        date = _utc_today()
        try:
            # ROOT-CAUSE FIX: refresh live market data once per UTC day BEFORE reading latest().
            # Without this the cached series' max() date is frozen at first-load, so latest().date
            # never advances → every hourly tick is "same day" → the series stays n=1. Refreshing
            # here advances the latest available data date so the forward track actually grows.
            self._refresh_market_data_if_due(date)
            snapshot = self._md.latest()
            if snapshot is None or not getattr(snapshot, "date", None):
                raise InvalidDataError("latest() returned no usable snapshot")
        except Exception as exc:  # noqa: BLE001 — any fetch failure is fail-closed
            return self._handle_gap(date, f"live data fetch failed: {exc}")

        market_date = snapshot.date  # the real data date (may differ from wall-clock UTC day)

        for sid, strat in self._strategies.items():
            self._tick_one(sid, strat, snapshot, market_date)

        return self._write_status(market_date, gap=False, gap_reason="")

    def _tick_one(self, sid: str, strat: Strategy, snapshot, market_date: str) -> None:
        """Advance one strategy idempotently for `market_date`.

        Idempotency: if this strategy already ticked for `market_date`, restore the stored
        PRE-tick snapshot first so re-running the same day replays exactly one accrual rather
        than compounding a second.
        """
        if self._last_tick.get(sid) == market_date:
            doc = atomic_load(str(self._state_path(sid)), default={})
            pretick = doc.get("pretick") if isinstance(doc, dict) else None
            if isinstance(pretick, dict) and pretick.get("date") == market_date:
                _restore_strategy_state(strat, pretick["state"])
            # else: no pretick available (shouldn't happen) → skip to avoid double-accrue.
            else:
                return

        # Snapshot the pre-tick state so a future same-day re-tick can replay idempotently.
        pre = _dump_strategy_state(strat)
        self._persist_pretick(sid, pre, market_date)

        # Advance: step() then kill_check() (same order the harness uses).
        try:
            strat.step(snapshot)
            kill = strat.kill_check(snapshot)
        except Exception as exc:  # noqa: BLE001 — a strategy bug must not crash the service;
            # treat as a kill (safe state) and restore the pre-tick book (no fabricated advance).
            _restore_strategy_state(strat, pre)
            self._record_kill(sid, f"step/kill_check raised (fail-closed): {exc}", market_date)
            self._persist_state(sid, strat, market_date)
            self._append_series_point(sid, self._series_point(sid, strat, market_date, killed=True,
                                                              kill_reason=f"error: {exc}"))
            return

        killed_now = bool(getattr(kill, "triggered", False))
        kill_reason = getattr(kill, "reason", "") if killed_now else ""

        # Persist the advanced state + append the dated time-series point.
        self._persist_state(sid, strat, market_date)
        self._append_series_point(
            sid,
            self._series_point(sid, strat, market_date, killed=killed_now, kill_reason=kill_reason),
        )

        # Fire a kill event the first time a strategy transitions to killed on this date.
        if killed_now and not self._already_recorded_kill(sid, market_date):
            self._record_kill(sid, kill_reason or "kill triggered", market_date)

    def _already_recorded_kill(self, sid: str, date: str) -> bool:
        if not self._kills_path.exists():
            return False
        try:
            for line in self._kills_path.read_text().splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("strategy") == sid and ev.get("date") == date:
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _series_point(
        self, sid: str, strat: Strategy, date: str, killed: bool, kill_reason: str
    ) -> dict:
        m = strat.metrics()
        return {
            "date": date,
            "ts": _utc_now_iso(),
            "equity_usd": strat.equity(),
            "net_apy_pct": m.net_apy_pct,
            "max_drawdown_pct": m.max_drawdown_pct,
            "beta_to_eth": m.beta_to_eth,
            "killed": killed,
            "kill_reason": kill_reason,
        }

    # ── fail-closed gap handling ───────────────────────────────────────────────────────────
    def _handle_gap(self, date: str, reason: str) -> dict:
        """Record a data gap WITHOUT advancing any strategy or writing a fabricated point."""
        log.warning("Strategy Lab paper: GAP on %s — %s (safe-hold, no advance)", date, reason)
        if self._alert_on_gap:
            self._telegram_send(f"⚠️ Strategy Lab paper GAP — {date}\n{reason}\n(safe-hold, no advance)")
        return self._write_status(date, gap=True, gap_reason=reason)

    # ── status ─────────────────────────────────────────────────────────────────────────────
    def _write_status(self, date: str, gap: bool, gap_reason: str) -> dict:
        strategies: Dict[str, dict] = {}
        for sid, strat in self._strategies.items():
            m = strat.metrics()
            killed = bool(m.extra.get("killed", False)) if m.extra else False
            strategies[sid] = {
                "id": sid,
                "name": getattr(strat, "name", sid),
                "mandate": getattr(strat, "mandate", ""),
                "is_advisory": getattr(strat, "is_advisory", True),
                "equity_usd": strat.equity(),
                "net_apy_pct": m.net_apy_pct,
                "killed": killed,
                "last_tick": self._last_tick.get(sid),
            }
        status = {
            "generated_at": _utc_now_iso(),
            "date": date,
            "gap": gap,
            "gap_reason": gap_reason,
            "n_strategies": len(strategies),
            "strategies": strategies,
        }
        atomic_save(status, str(self._status_path))
        return status

    def status(self) -> dict:
        """Return the latest status (recomputed live from current strategy state)."""
        date = self._latest_known_date()
        return self._write_status(date, gap=False, gap_reason="")

    def _latest_known_date(self) -> str:
        dates = [d for d in self._last_tick.values() if d]
        return max(dates) if dates else _utc_today()

    # ── weekly report hook ─────────────────────────────────────────────────────────────────
    def weekly_report(self, send_telegram: bool = False) -> Optional[str]:
        """Produce a markdown comparison from the accumulated paper series.

        The report module is built in parallel; we import it INSIDE the function and guard with
        try/except so it is NOT a hard dependency — absent it, this is a graceful no-op.
        """
        try:
            from spa_core.strategy_lab import report as lab_report  # type: ignore
        except Exception as exc:  # noqa: BLE001 — report module optional
            log.info("weekly_report: report module unavailable (%s)", exc)
            return None
        try:
            series = {
                sid: atomic_load(str(self._series_path(sid)), default={"series": []})
                for sid in self._strategies
            }
            # The report module owns the formatting; we pass it the accumulated series + status.
            md = lab_report.build_weekly_markdown(series, self._write_status(
                self._latest_known_date(), gap=False, gap_reason=""))
        except Exception as exc:  # noqa: BLE001 — a report bug must not break the service
            log.warning("weekly_report failed: %s", exc)
            return None
        if md and send_telegram:
            self._telegram_send(md)
        return md
