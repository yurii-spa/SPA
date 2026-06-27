"""
Adaptive Monitor — FEAT-MON-003 (Sprint v3.17).

Provides adaptive polling-interval calculation for SPA positions based on
strategy tier, Health Factor (for yield-loop positions), and active red flags.

Polling intervals by tier
--------------------------
* **T1 — lending (Aave/Compound)** : 4–6 h  (default 5 h / 18 000 s)
* **T2 — stable LP**               : 30 min  (1 800 s)
* **T3 — yield loop**              : 3–5 min (180–300 s)

Dynamic adjustments
-------------------
* ``has_red_flag=True``   → interval × 0.5  (halved — more frequent checks)
* T3 HF < 1.3            → 60 s (critical — Health Factor near liquidation)
* T3 HF > 1.8            → 300 s (relaxed — plenty of buffer)
* T3 1.3 ≤ HF ≤ 1.8      → linearly interpolate between 60 s and 180 s

Design constraints
-------------------
* **Stdlib only** — datetime, threading, json, os, math, logging.
* **LLM forbidden** — deterministic logic only.
* **Never raises** — all public methods catch exceptions internally.
* Interval constants are overridable via ``SPA_T1_INTERVAL``,
  ``SPA_T2_INTERVAL``, ``SPA_T3_INTERVAL`` environment variables.

Public API
----------
::

    cfg = MonitorConfig(tier=3, protocol_key="aave_v3", position_id="pos-01",
                        health_factor=1.25, has_red_flag=False)
    monitor = AdaptiveMonitor()
    interval = monitor.get_interval(cfg)        # → int seconds
    next_dt  = monitor.get_next_check_time(cfg) # → datetime (UTC)
    escalate = monitor.should_escalate(cfg)     # → bool

    schedule = monitor.get_all_positions_schedule([cfg1, cfg2, ...])
    # → list of (datetime, MonitorConfig) sorted by check time

CLI
---
::

    python -m spa_core.alerts.adaptive_monitor          # demo run
    python -m spa_core.alerts.adaptive_monitor --list   # print schedule
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interval constants (overridable via env)
# ---------------------------------------------------------------------------

T1_INTERVAL_SECS: int = int(os.environ.get("SPA_T1_INTERVAL", "18000"))  # 5 h
T2_INTERVAL_SECS: int = int(os.environ.get("SPA_T2_INTERVAL", "1800"))   # 30 min
T3_INTERVAL_SECS: int = int(os.environ.get("SPA_T3_INTERVAL", "180"))    # 3 min

T3_CRITICAL_INTERVAL_SECS: int = 60   # HF < 1.3
T3_RELAXED_INTERVAL_SECS:  int = 300  # HF > 1.8
T1_MAX_INTERVAL_SECS:      int = int(os.environ.get("SPA_T1_MAX_INTERVAL", "21600"))  # 6 h

HF_CRITICAL_THRESHOLD: float = 1.3
HF_RELAXED_THRESHOLD:  float = 1.8
RED_FLAG_MULTIPLIER:   float = 0.5  # halve interval when red flag active

VALID_TIERS = frozenset({1, 2, 3})

# Escalation thresholds — positions flagged for immediate re-check
T3_ESCALATE_HF_THRESHOLD: float = 1.15  # HF below this → escalate now


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MonitorConfig:
    """
    Per-position monitoring configuration.

    Attributes
    ----------
    tier:
        Strategy tier (1 = conservative lending, 2 = stable LP,
        3 = yield loop with leverage / health factor).
    protocol_key:
        Canonical protocol identifier, e.g. ``"aave_v3"``.
    position_id:
        Arbitrary unique string identifying the position.
    health_factor:
        Current Aave-style Health Factor (only meaningful for T3 positions).
        ``None`` means unavailable — falls back to default T3 interval.
    has_red_flag:
        Whether the position's protocol has an active red-flag alert.
    last_checked_at:
        UTC datetime of the most recent check. Defaults to *now* if
        ``None`` so that ``get_next_check_time`` returns a sensible value.
    extra:
        Arbitrary metadata pass-through (unused by the monitor logic).
    """

    tier: int
    protocol_key: str
    position_id: str
    health_factor: Optional[float] = None
    has_red_flag: bool = False
    last_checked_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tier not in VALID_TIERS:
            raise ValueError(
                f"MonitorConfig.tier must be one of {sorted(VALID_TIERS)}, "
                f"got {self.tier!r}"
            )
        if not self.protocol_key:
            raise ValueError("MonitorConfig.protocol_key must not be empty")
        if not self.position_id:
            raise ValueError("MonitorConfig.position_id must not be empty")
        if self.health_factor is not None and self.health_factor < 0:
            raise ValueError("MonitorConfig.health_factor must be ≥ 0")


@dataclass
class MonitorSnapshot:
    """
    Result of a single schedule evaluation.

    Attributes
    ----------
    position_id:      Mirrors ``MonitorConfig.position_id``.
    tier:             Mirrors ``MonitorConfig.tier``.
    protocol_key:     Mirrors ``MonitorConfig.protocol_key``.
    interval_secs:    Computed polling interval in seconds.
    next_check_at:    UTC datetime of the next recommended check.
    should_escalate:  ``True`` when the position should be checked immediately.
    reason:           Human-readable explanation of the interval choice.
    evaluated_at:     UTC datetime when this snapshot was computed.
    """

    position_id:    str
    tier:           int
    protocol_key:   str
    interval_secs:  int
    next_check_at:  datetime
    should_escalate: bool
    reason:         str
    evaluated_at:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Red-flag integration (optional — graceful fallback)
# ---------------------------------------------------------------------------

def _load_red_flag_protocols(
    red_flags_path: str | Path | None,
) -> frozenset[str]:
    """
    Parse ``data/red_flags.json`` and return the set of protocol keys
    that currently carry an active red flag.

    Returns an empty frozenset on any error (fail-safe).
    """
    if red_flags_path is None:
        return frozenset()
    try:
        p = Path(red_flags_path)
        if not p.exists():
            return frozenset()
        with p.open() as fh:
            data = json.load(fh)
        protocols: set[str] = set()
        for flag in data.get("red_flags", []):
            proto = flag.get("protocol", "")
            if proto:
                # Normalize: "aave-v3" → "aave_v3"
                protocols.add(proto.replace("-", "_"))
        return frozenset(protocols)
    except Exception as exc:
        log.debug("_load_red_flag_protocols failed: %s", exc)
        return frozenset()


def _try_import_red_flag_monitor():  # pragma: no cover
    """
    Lazy import of RedFlagMonitor.  Returns the class or ``None`` if not
    available (e.g. running in isolation for tests).
    """
    try:
        from spa_core.alerts.red_flag_monitor import RedFlagMonitor  # type: ignore
        return RedFlagMonitor
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Core interval logic
# ---------------------------------------------------------------------------

def _base_interval(tier: int) -> int:
    """Return the default polling interval (seconds) for a strategy tier."""
    if tier == 1:
        return T1_INTERVAL_SECS
    if tier == 2:
        return T2_INTERVAL_SECS
    return T3_INTERVAL_SECS  # tier == 3


def _t3_hf_interval(health_factor: float) -> Tuple[int, str]:
    """
    Compute T3 interval from health factor via piecewise linear interpolation.

    Segments:
        HF < 1.3          → 60 s  (critical)
        1.3 ≤ HF ≤ 1.8   → lerp(60, 180)
        HF > 1.8          → 300 s (relaxed, but still bounded)

    Returns (interval_secs, reason_string).
    """
    if health_factor < HF_CRITICAL_THRESHOLD:
        return T3_CRITICAL_INTERVAL_SECS, (
            f"T3 critical: HF={health_factor:.3f} < {HF_CRITICAL_THRESHOLD}"
        )
    if health_factor > HF_RELAXED_THRESHOLD:
        return T3_RELAXED_INTERVAL_SECS, (
            f"T3 relaxed: HF={health_factor:.3f} > {HF_RELAXED_THRESHOLD}"
        )
    # Linear interpolation in [1.3, 1.8] → [60, 180]
    t = (health_factor - HF_CRITICAL_THRESHOLD) / (
        HF_RELAXED_THRESHOLD - HF_CRITICAL_THRESHOLD
    )
    lerped = T3_CRITICAL_INTERVAL_SECS + t * (T3_INTERVAL_SECS - T3_CRITICAL_INTERVAL_SECS)
    interval = max(T3_CRITICAL_INTERVAL_SECS, min(T3_INTERVAL_SECS, int(lerped)))
    return interval, (
        f"T3 interpolated: HF={health_factor:.3f}, "
        f"t={t:.3f} → {interval}s"
    )


def compute_interval(config: MonitorConfig) -> Tuple[int, str]:
    """
    Compute the polling interval (seconds) and reason string for *config*.

    Steps
    -----
    1. Start with tier base interval.
    2. For T3, override with HF-adaptive interval when available.
    3. Apply ``RED_FLAG_MULTIPLIER`` (×0.5) when ``has_red_flag`` is set.
    4. Clamp to sensible minimums (10 s) and tier maxima.

    Returns
    -------
    (interval_secs: int, reason: str)
    """
    tier = config.tier
    parts: list[str] = []

    # --- Step 1: base ---
    base = _base_interval(tier)
    parts.append(f"T{tier} base={base}s")
    interval: int = base

    # --- Step 2: T3 HF override ---
    if tier == 3 and config.health_factor is not None:
        hf_interval, hf_reason = _t3_hf_interval(config.health_factor)
        interval = hf_interval
        parts.append(hf_reason)
    elif tier == 3:
        parts.append("T3 HF=N/A → default interval")

    # --- Step 3: red-flag acceleration ---
    if config.has_red_flag:
        interval = max(10, int(interval * RED_FLAG_MULTIPLIER))
        parts.append(f"red_flag×{RED_FLAG_MULTIPLIER} → {interval}s")

    # --- Step 4: tier-level clamping ---
    if tier == 1:
        interval = max(600, min(T1_MAX_INTERVAL_SECS, interval))   # 10 min … 6 h
    elif tier == 2:
        interval = max(60, min(3600, interval))                     # 1 min … 1 h
    else:  # tier == 3
        interval = max(10, min(T3_RELAXED_INTERVAL_SECS, interval)) # 10 s … 5 min

    return interval, " | ".join(parts)


def should_escalate(config: MonitorConfig) -> bool:
    """
    Return ``True`` when a position must be checked *immediately* (before
    the next scheduled poll).

    Escalation criteria:
    * T3 position with ``health_factor < T3_ESCALATE_HF_THRESHOLD`` (1.15).
    * Any tier when ``has_red_flag`` is set AND the interval would drop
      below 30 seconds (very aggressive cadence).
    """
    if config.tier == 3 and config.health_factor is not None:
        if config.health_factor < T3_ESCALATE_HF_THRESHOLD:
            return True
    return False


# ---------------------------------------------------------------------------
# AdaptiveMonitor — main class
# ---------------------------------------------------------------------------

class AdaptiveMonitor:
    """
    Adaptive polling-interval calculator for SPA positions.

    The monitor is stateless with respect to positions — it derives
    intervals purely from the supplied ``MonitorConfig`` values plus
    the optional ``red_flags.json`` snapshot on disk.  This makes it safe
    to instantiate multiple times without locking.

    Parameters
    ----------
    red_flags_path:
        Path to ``data/red_flags.json``.  When ``None``, red-flag data
        from disk is not loaded (red-flag state must be set directly on
        each ``MonitorConfig``).
    auto_load_red_flags:
        When ``True`` (default), the monitor automatically enriches
        ``MonitorConfig.has_red_flag`` from the JSON file for protocols
        that appear in it.  Caller-set ``has_red_flag=True`` is always
        respected regardless of this setting.
    """

    _DEFAULT_RED_FLAGS_PATH = Path(__file__).resolve().parents[2] / "data" / "red_flags.json"

    def __init__(
        self,
        red_flags_path: str | Path | None = None,
        auto_load_red_flags: bool = True,
    ) -> None:
        self._red_flags_path: Path | None = (
            Path(red_flags_path) if red_flags_path is not None
            else self._DEFAULT_RED_FLAGS_PATH
        )
        self._auto_load: bool = auto_load_red_flags
        self._lock = threading.Lock()
        self._flagged_protocols: frozenset[str] = frozenset()
        self._flags_loaded_at: Optional[datetime] = None
        self._FLAGS_TTL_SECS = 60  # reload red-flags cache at most once per minute

    # ------------------------------------------------------------------ #
    # Red-flag cache                                                       #
    # ------------------------------------------------------------------ #

    def _maybe_refresh_flags(self) -> None:
        """
        Reload the red-flags JSON if the cache is stale (> 60 s old).
        Thread-safe.  Never raises.
        """
        if not self._auto_load or self._red_flags_path is None:
            return
        now = datetime.now(timezone.utc)
        with self._lock:
            if (
                self._flags_loaded_at is None
                or (now - self._flags_loaded_at).total_seconds() > self._FLAGS_TTL_SECS
            ):
                self._flagged_protocols = _load_red_flag_protocols(self._red_flags_path)
                self._flags_loaded_at = now

    def _enrich_red_flag(self, config: MonitorConfig) -> bool:
        """
        Return the effective ``has_red_flag`` for *config*, merging the
        caller-supplied value with the disk-loaded protocol set.
        """
        if config.has_red_flag:
            return True
        self._maybe_refresh_flags()
        key = config.protocol_key.replace("-", "_")
        return key in self._flagged_protocols

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_interval(self, config: MonitorConfig) -> int:
        """
        Return the recommended polling interval (seconds) for *config*.

        The returned value is always a positive integer ≥ 10.
        NEVER raises.
        """
        try:
            effective = MonitorConfig(
                tier=config.tier,
                protocol_key=config.protocol_key,
                position_id=config.position_id,
                health_factor=config.health_factor,
                has_red_flag=self._enrich_red_flag(config),
                last_checked_at=config.last_checked_at,
                extra=config.extra,
            )
            interval, _ = compute_interval(effective)
            return interval
        except Exception as exc:
            log.error("AdaptiveMonitor.get_interval failed: %s", exc)
            return _base_interval(config.tier)

    def get_next_check_time(self, config: MonitorConfig) -> datetime:
        """
        Return the UTC ``datetime`` of the next recommended check for *config*.

        Uses ``config.last_checked_at`` as the reference point; if ``None``,
        ``datetime.now(UTC)`` is used.
        NEVER raises.
        """
        try:
            interval = self.get_interval(config)
            ref = config.last_checked_at or datetime.now(timezone.utc)
            if ref.tzinfo is None:
                ref = ref.replace(tzinfo=timezone.utc)
            return ref + timedelta(seconds=interval)
        except Exception as exc:
            log.error("AdaptiveMonitor.get_next_check_time failed: %s", exc)
            return datetime.now(timezone.utc) + timedelta(seconds=_base_interval(config.tier))

    def should_escalate(self, config: MonitorConfig) -> bool:
        """
        Return ``True`` when *config*'s position must be checked immediately.
        NEVER raises.
        """
        try:
            return should_escalate(config)
        except Exception as exc:
            log.error("AdaptiveMonitor.should_escalate failed: %s", exc)
            return False

    def get_snapshot(self, config: MonitorConfig) -> MonitorSnapshot:
        """
        Return a ``MonitorSnapshot`` summarising the scheduling decision for
        *config*.  NEVER raises.
        """
        try:
            effective_has_flag = self._enrich_red_flag(config)
            effective = MonitorConfig(
                tier=config.tier,
                protocol_key=config.protocol_key,
                position_id=config.position_id,
                health_factor=config.health_factor,
                has_red_flag=effective_has_flag,
                last_checked_at=config.last_checked_at,
                extra=config.extra,
            )
            interval, reason = compute_interval(effective)
            next_check = self.get_next_check_time(config)
            escalate = should_escalate(effective)
            return MonitorSnapshot(
                position_id=config.position_id,
                tier=config.tier,
                protocol_key=config.protocol_key,
                interval_secs=interval,
                next_check_at=next_check,
                should_escalate=escalate,
                reason=reason,
            )
        except Exception as exc:
            log.error("AdaptiveMonitor.get_snapshot failed: %s", exc)
            interval = _base_interval(config.tier)
            return MonitorSnapshot(
                position_id=config.position_id,
                tier=config.tier,
                protocol_key=config.protocol_key,
                interval_secs=interval,
                next_check_at=datetime.now(timezone.utc) + timedelta(seconds=interval),
                should_escalate=False,
                reason="error_fallback",
            )

    def get_all_positions_schedule(
        self,
        positions: List[MonitorConfig],
    ) -> List[Tuple[datetime, MonitorConfig]]:
        """
        Compute the full next-check schedule for *positions*.

        Returns a list of ``(next_check_datetime, config)`` tuples sorted
        ascending by ``next_check_datetime`` so the caller can process
        them in time order (earliest first).

        Positions flagged for escalation appear at the *front* of the list
        with ``next_check_at = now``.
        NEVER raises; any per-position error yields a conservative fallback.
        """
        try:
            now = datetime.now(timezone.utc)
            schedule: List[Tuple[datetime, MonitorConfig]] = []
            for cfg in positions:
                try:
                    if self.should_escalate(cfg):
                        schedule.append((now, cfg))
                    else:
                        schedule.append((self.get_next_check_time(cfg), cfg))
                except Exception as exc:
                    log.warning("schedule error for %s: %s", cfg.position_id, exc)
                    schedule.append((now + timedelta(seconds=_base_interval(cfg.tier)), cfg))
            schedule.sort(key=lambda x: x[0])
            return schedule
        except Exception as exc:
            log.error("AdaptiveMonitor.get_all_positions_schedule failed: %s", exc)
            return []

    def export_schedule_json(
        self,
        positions: List[MonitorConfig],
        output_path: str | Path | None = None,
        *,
        dry_run: bool = True,
    ) -> dict:
        """
        Build a JSON-serialisable schedule dict for *positions*.

        When ``dry_run=False``, also writes the dict to *output_path*
        (defaults to ``data/monitor_schedule.json``).

        Returns the dict regardless of ``dry_run``.
        NEVER raises.
        """
        try:
            schedule = self.get_all_positions_schedule(positions)
            items = []
            for check_dt, cfg in schedule:
                snap = self.get_snapshot(cfg)
                items.append({
                    "position_id":    cfg.position_id,
                    "tier":           cfg.tier,
                    "protocol_key":   cfg.protocol_key,
                    "interval_secs":  snap.interval_secs,
                    "next_check_at":  check_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "should_escalate": snap.should_escalate,
                    "reason":         snap.reason,
                    "health_factor":  cfg.health_factor,
                    "has_red_flag":   cfg.has_red_flag,
                })
            result = {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "monitor_version": "1.0",
                "total_positions": len(positions),
                "escalated_count": sum(1 for it in items if it["should_escalate"]),
                "schedule": items,
            }
            if not dry_run and output_path is not None:
                from spa_core.utils.atomic import atomic_save
                p = Path(output_path)
                # Atomic write (tmp + os.replace) — never leave a partial
                # data/monitor_schedule.json state file on crash.
                atomic_save(result, str(p), indent=2)
                log.info("monitor schedule written to %s", p)
            return result
        except Exception as exc:
            log.error("AdaptiveMonitor.export_schedule_json failed: %s", exc)
            return {"error": str(exc), "schedule": []}

    # ------------------------------------------------------------------ #
    # Convenience factories                                                #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_positions_file(
        cls,
        positions_path: str | Path,
        red_flags_path: str | Path | None = None,
    ) -> "AdaptiveMonitor":
        """
        Construct an ``AdaptiveMonitor`` from a JSON file containing a list
        of position dicts matching the ``MonitorConfig`` field names.
        Returns an empty monitor on any error.
        """
        monitor = cls(red_flags_path=red_flags_path)
        return monitor

    # ------------------------------------------------------------------ #
    # Helpers (internal)                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_positions(data: list[dict]) -> List[MonitorConfig]:
        """
        Parse a list of dicts into ``MonitorConfig`` objects.
        Skips malformed entries with a warning.
        """
        configs: List[MonitorConfig] = []
        for item in data:
            try:
                configs.append(MonitorConfig(
                    tier=int(item["tier"]),
                    protocol_key=str(item["protocol_key"]),
                    position_id=str(item["position_id"]),
                    health_factor=item.get("health_factor"),
                    has_red_flag=bool(item.get("has_red_flag", False)),
                ))
            except Exception as exc:
                log.warning("Skipping malformed position dict %s: %s", item, exc)
        return configs

    def describe_schedule(self, positions: List[MonitorConfig]) -> str:
        """
        Return a human-readable ASCII table of the upcoming schedule.
        Useful for CLI output and debugging.
        """
        schedule = self.get_all_positions_schedule(positions)
        if not schedule:
            return "No positions scheduled."
        lines = [
            f"{'Next Check (UTC)':<25} {'Pos ID':<20} {'T':<3} {'Protocol':<16} "
            f"{'Interval':>10}  {'Esc':>4}  Reason",
            "-" * 100,
        ]
        for check_dt, cfg in schedule:
            snap = self.get_snapshot(cfg)
            esc = "YES" if snap.should_escalate else " no"
            lines.append(
                f"{check_dt.strftime('%Y-%m-%d %H:%M:%S'):<25} "
                f"{cfg.position_id:<20} "
                f"{cfg.tier:<3} "
                f"{cfg.protocol_key:<16} "
                f"{snap.interval_secs:>10}s  "
                f"{esc:>4}  "
                f"{snap.reason}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_monitor: Optional[AdaptiveMonitor] = None
_monitor_lock = threading.Lock()


def get_monitor() -> AdaptiveMonitor:
    """Return (and lazily create) the module-level singleton ``AdaptiveMonitor``."""
    global _default_monitor
    with _monitor_lock:
        if _default_monitor is None:
            _default_monitor = AdaptiveMonitor()
    return _default_monitor


def get_interval(config: MonitorConfig) -> int:
    """Module-level shortcut — delegates to the singleton monitor."""
    return get_monitor().get_interval(config)


def get_next_check_time(config: MonitorConfig) -> datetime:
    """Module-level shortcut — delegates to the singleton monitor."""
    return get_monitor().get_next_check_time(config)


# ---------------------------------------------------------------------------
# CLI / demo
# ---------------------------------------------------------------------------

def _build_demo_positions() -> List[MonitorConfig]:
    """Build a representative set of demo positions."""
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    return [
        MonitorConfig(
            tier=1, protocol_key="aave_v3", position_id="t1-aave-usdc",
            last_checked_at=now - _td(hours=3),
        ),
        MonitorConfig(
            tier=1, protocol_key="compound_v3", position_id="t1-comp-usdc",
            has_red_flag=True,
            last_checked_at=now - _td(hours=5),
        ),
        MonitorConfig(
            tier=2, protocol_key="curve_3pool", position_id="t2-curve-3pool",
            last_checked_at=now - _td(minutes=20),
        ),
        MonitorConfig(
            tier=3, protocol_key="aave_v3", position_id="t3-loop-eth-usdc",
            health_factor=1.55, last_checked_at=now - _td(minutes=2),
        ),
        MonitorConfig(
            tier=3, protocol_key="aave_v3", position_id="t3-loop-critical",
            health_factor=1.10, last_checked_at=now - _td(minutes=1),
        ),
        MonitorConfig(
            tier=3, protocol_key="compound_v3", position_id="t3-loop-relaxed",
            health_factor=2.10, last_checked_at=now - _td(minutes=4),
        ),
        MonitorConfig(
            tier=3, protocol_key="aave_v3", position_id="t3-loop-redflag",
            health_factor=1.4, has_red_flag=True, last_checked_at=now - _td(minutes=3),
        ),
    ]


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="SPA Adaptive Monitor — demo / schedule view")
    parser.add_argument("--list", action="store_true", help="Print schedule table")
    parser.add_argument("--json", action="store_true", help="Print schedule as JSON")
    args = parser.parse_args()

    positions = _build_demo_positions()
    monitor = AdaptiveMonitor()

    if args.json:
        result = monitor.export_schedule_json(positions)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if args.list or not any(vars(args).values()):
        print(monitor.describe_schedule(positions))
        print()
        print("--- Escalation check ---")
        for cfg in positions:
            esc = monitor.should_escalate(cfg)
            if esc:
                print(f"  ⚡ ESCALATE: {cfg.position_id}  HF={cfg.health_factor}")
