"""
Bull Cycle Detector + Dynamic Tier Allocation — FEAT-STRAT-001 (Sprint v3.19).

Detects when DeFi yield markets are in a "bull cycle" (elevated APYs across
the whitelist) and dynamically expands the allocation caps for T2/T3 strategies
to capture higher yields while maintaining safety constraints.

Bull Cycle definition
----------------------
Market-wide median APY across all whitelisted protocols exceeds the bull
threshold (default 8%) for at least ``MIN_BULL_DAYS`` (default 7) consecutive
calendar days, computed from ``data/historical_apy.json``.

Allocation caps
---------------

| Cycle | T1 (lending) | T2 (stable LP) | T3 (yield loop) | Cash buffer |
|-------|-------------|----------------|-----------------|-------------|
| BEAR  | 80%         | 15%            | 5%              | 5% min      |
| NEUTRAL | 60%       | 30%            | 10%             | 5% min      |
| BULL  | 40%         | 40%            | 20%             | 5% min      |

These caps represent the *maximum* fraction of total capital that may be
deployed to each tier.  The actual allocation from Kelly/Markowitz may be lower.

Design constraints
-------------------
* **Stdlib only** — json, statistics, datetime, math, os, logging.
* **LLM forbidden** — deterministic signal processing.
* **Never raises** — all public methods catch exceptions.
* Threshold and caps are env-overridable.

Output schema (``data/market_cycle.json``)
------------------------------------------

::

    {
      "generated_at": "<ISO-8601>",
      "detector_version": "1.0",
      "cycle": "BULL",                  // "BEAR" | "NEUTRAL" | "BULL"
      "consecutive_bull_days": 9,
      "current_median_apy": 9.42,
      "bull_threshold": 8.0,
      "min_bull_days": 7,
      "allocation_caps": {
        "t1_max_pct": 40.0,
        "t2_max_pct": 40.0,
        "t3_max_pct": 20.0,
        "cash_buffer_min_pct": 5.0
      },
      "protocol_apys": {
        "aave-v3-usdc-ethereum": {"latest_apy": 9.1, "7d_median": 9.0},
        ...
      },
      "history_days_used": 90
    }

CLI
---
::

    python -m spa_core.strategies.bull_cycle_detector             # detect + print
    python -m spa_core.strategies.bull_cycle_detector --json      # JSON output
    python -m spa_core.strategies.bull_cycle_detector --write     # write to file
"""

from __future__ import annotations

import json
import logging
import math
import os
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable constants (env-overridable)
# ---------------------------------------------------------------------------

BULL_APY_THRESHOLD: float = float(os.environ.get("SPA_BULL_APY_THRESHOLD", "8.0"))
MIN_BULL_DAYS: int = int(os.environ.get("SPA_MIN_BULL_DAYS", "7"))
LOOKBACK_DAYS: int = int(os.environ.get("SPA_BULL_LOOKBACK_DAYS", "30"))

# Allocation cap presets by cycle
_CAPS: dict[str, dict[str, float]] = {
    "BEAR": {
        "t1_max_pct": 80.0,
        "t2_max_pct": 15.0,
        "t3_max_pct": 5.0,
        "cash_buffer_min_pct": 5.0,
    },
    "NEUTRAL": {
        "t1_max_pct": 60.0,
        "t2_max_pct": 30.0,
        "t3_max_pct": 10.0,
        "cash_buffer_min_pct": 5.0,
    },
    "BULL": {
        "t1_max_pct": 40.0,
        "t2_max_pct": 40.0,
        "t3_max_pct": 20.0,
        "cash_buffer_min_pct": 5.0,
    },
}

DEFAULT_HISTORICAL_APY_PATH = Path(__file__).resolve().parents[2] / "data" / "historical_apy.json"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "market_cycle.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AllocationCaps:
    """
    Maximum allocation fractions per strategy tier.

    All values are percentages of total capital (0–100).
    T1 + T2 + T3 may sum to more than 100% — these are *caps*, not targets.
    The cash buffer is a *minimum* always held in reserve.
    """
    t1_max_pct: float       # T1 lending
    t2_max_pct: float       # T2 stable LP
    t3_max_pct: float       # T3 yield loop
    cash_buffer_min_pct: float  # cash buffer floor

    def to_dict(self) -> dict:
        return asdict(self)

    def __post_init__(self) -> None:
        for attr in ("t1_max_pct", "t2_max_pct", "t3_max_pct", "cash_buffer_min_pct"):
            val = getattr(self, attr)
            if not (0.0 <= val <= 100.0):
                raise ValueError(f"AllocationCaps.{attr}={val} must be in [0, 100]")


@dataclass
class CycleState:
    """
    Current market cycle state and associated allocation caps.
    """
    cycle: str                    # "BEAR" | "NEUTRAL" | "BULL"
    consecutive_bull_days: int
    current_median_apy: float
    bull_threshold: float
    min_bull_days: int
    allocation_caps: AllocationCaps
    protocol_apys: dict           # protocol_key → {latest_apy, 7d_median}
    history_days_used: int
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    detector_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "detector_version": self.detector_version,
            "cycle": self.cycle,
            "consecutive_bull_days": self.consecutive_bull_days,
            "current_median_apy": round(self.current_median_apy, 4),
            "bull_threshold": self.bull_threshold,
            "min_bull_days": self.min_bull_days,
            "allocation_caps": self.allocation_caps.to_dict(),
            "protocol_apys": self.protocol_apys,
            "history_days_used": self.history_days_used,
        }


# ---------------------------------------------------------------------------
# APY history loader
# ---------------------------------------------------------------------------

def _load_apy_history(path: str | Path) -> dict[str, list[dict]]:
    """
    Load ``data/historical_apy.json`` and return a dict of
    ``{protocol_key: [{date, apy, tvl_usd}, ...]}`` sorted by date ascending.

    Returns empty dict on any failure.
    """
    try:
        p = Path(path)
        if not p.exists():
            log.warning("historical_apy.json not found at %s", p)
            return {}
        with p.open() as fh:
            raw = json.load(fh)
        protocols = raw.get("protocols", {})
        if not isinstance(protocols, dict):
            return {}
        result: dict[str, list[dict]] = {}
        for proto_key, entries in protocols.items():
            if not isinstance(entries, list):
                continue
            # Sort by date ascending
            valid = [e for e in entries if isinstance(e, dict) and "date" in e and "apy" in e]
            valid.sort(key=lambda e: e["date"])
            result[proto_key] = valid
        return result
    except Exception as exc:
        log.warning("_load_apy_history failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Median APY computation helpers
# ---------------------------------------------------------------------------

def _compute_daily_market_medians(
    apy_history: dict[str, list[dict]],
    lookback_days: int = LOOKBACK_DAYS,
) -> list[tuple[str, float]]:
    """
    Compute a daily market-wide median APY for the past ``lookback_days`` days.

    For each calendar date in the lookback window, the median is taken across
    all protocols that have an APY entry for that date.

    Returns a list of ``(date_str, median_apy)`` sorted ascending by date.
    Empty list if data is insufficient.
    """
    if not apy_history:
        return []

    # Collect all available dates from all protocols
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=lookback_days)

    # Build per-date APY collection
    daily_apys: dict[str, list[float]] = {}
    for proto_key, entries in apy_history.items():
        for entry in entries:
            try:
                d = entry["date"]  # "YYYY-MM-DD"
                if d < str(start_date):
                    continue
                apy = float(entry["apy"])
                if math.isnan(apy) or math.isinf(apy) or apy < 0:
                    continue
                daily_apys.setdefault(d, []).append(apy)
            except (KeyError, ValueError, TypeError):
                continue

    if not daily_apys:
        return []

    result = []
    for date_str in sorted(daily_apys.keys()):
        apys = daily_apys[date_str]
        if len(apys) >= 2:
            result.append((date_str, statistics.median(apys)))
        elif len(apys) == 1:
            result.append((date_str, apys[0]))

    return result


def _count_consecutive_bull_days(
    daily_medians: list[tuple[str, float]],
    threshold: float = BULL_APY_THRESHOLD,
) -> int:
    """
    Count how many trailing consecutive calendar days the market-wide
    median APY has been above *threshold*.

    Returns 0 if no data or threshold not met.
    """
    if not daily_medians:
        return 0
    count = 0
    for _, median_apy in reversed(daily_medians):
        if median_apy >= threshold:
            count += 1
        else:
            break
    return count


def _determine_cycle(
    consecutive_bull_days: int,
    current_median_apy: float,
    threshold: float = BULL_APY_THRESHOLD,
    min_bull_days: int = MIN_BULL_DAYS,
) -> str:
    """
    Determine the market cycle label.

    Rules:
    * ``BULL``    — consecutive_bull_days ≥ min_bull_days
    * ``BEAR``    — current_median_apy < threshold × 0.75 (well below threshold)
    * ``NEUTRAL`` — everything else
    """
    if consecutive_bull_days >= min_bull_days:
        return "BULL"
    bear_threshold = threshold * 0.75
    if current_median_apy < bear_threshold:
        return "BEAR"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Per-protocol APY summary
# ---------------------------------------------------------------------------

def _protocol_apy_summary(
    apy_history: dict[str, list[dict]],
    window_days: int = 7,
) -> dict[str, dict]:
    """
    For each protocol, compute latest APY and 7-day median.
    Returns a dict of protocol_key → {latest_apy, 7d_median}.
    """
    result: dict[str, dict] = {}
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=window_days)).isoformat()
    for proto_key, entries in apy_history.items():
        if not entries:
            continue
        try:
            latest_apy = float(entries[-1]["apy"])
            recent = [
                float(e["apy"]) for e in entries
                if e.get("date", "") >= cutoff
                and not math.isnan(float(e["apy"]))
            ]
            median_7d = statistics.median(recent) if recent else latest_apy
            result[proto_key] = {
                "latest_apy": round(latest_apy, 4),
                "7d_median": round(median_7d, 4),
            }
        except Exception:
            continue
    return result


# ---------------------------------------------------------------------------
# BullCycleDetector — main class
# ---------------------------------------------------------------------------

class BullCycleDetector:
    """
    Detects market bull/neutral/bear cycles from historical APY data and
    provides dynamic allocation caps for each cycle.

    Usage::

        detector = BullCycleDetector()
        state = detector.detect()
        caps = state.allocation_caps
        print(caps.t3_max_pct)  # → 20.0 in BULL, 10.0 in NEUTRAL
    """

    def __init__(
        self,
        apy_history_path: str | Path = DEFAULT_HISTORICAL_APY_PATH,
        output_path: str | Path = DEFAULT_OUTPUT_PATH,
        bull_threshold: float = BULL_APY_THRESHOLD,
        min_bull_days: int = MIN_BULL_DAYS,
        lookback_days: int = LOOKBACK_DAYS,
    ) -> None:
        self._apy_path = Path(apy_history_path)
        self._output_path = Path(output_path)
        self._bull_threshold = bull_threshold
        self._min_bull_days = min_bull_days
        self._lookback_days = lookback_days

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(self) -> CycleState:
        """
        Load APY history, compute market cycle, return ``CycleState``.
        NEVER raises — returns a NEUTRAL fallback on any error.
        """
        try:
            apy_history = _load_apy_history(self._apy_path)
            daily_medians = _compute_daily_market_medians(
                apy_history, lookback_days=self._lookback_days
            )

            if not daily_medians:
                # No data available — return safe NEUTRAL (don't assume BEAR from 0% median)
                log.info("No APY history data available — defaulting to NEUTRAL cycle")
                return self._fallback_state()

            current_median = daily_medians[-1][1]

            consecutive_bull = _count_consecutive_bull_days(
                daily_medians, threshold=self._bull_threshold
            )
            cycle = _determine_cycle(
                consecutive_bull, current_median,
                threshold=self._bull_threshold,
                min_bull_days=self._min_bull_days,
            )
            caps_dict = _CAPS[cycle]
            caps = AllocationCaps(**caps_dict)
            proto_summary = _protocol_apy_summary(apy_history)

            return CycleState(
                cycle=cycle,
                consecutive_bull_days=consecutive_bull,
                current_median_apy=current_median,
                bull_threshold=self._bull_threshold,
                min_bull_days=self._min_bull_days,
                allocation_caps=caps,
                protocol_apys=proto_summary,
                history_days_used=len(daily_medians),
            )
        except Exception as exc:
            log.error("BullCycleDetector.detect failed: %s", exc)
            return self._fallback_state()

    def get_allocation_caps(self) -> AllocationCaps:
        """
        Return allocation caps for the current market cycle.
        NEVER raises.
        """
        try:
            return self.detect().allocation_caps
        except Exception as exc:
            log.error("get_allocation_caps failed: %s", exc)
            return AllocationCaps(**_CAPS["NEUTRAL"])

    def get_cycle(self) -> str:
        """
        Return the current cycle string: "BEAR" | "NEUTRAL" | "BULL".
        NEVER raises.
        """
        try:
            return self.detect().cycle
        except Exception:
            return "NEUTRAL"

    def export(self, *, dry_run: bool = True) -> dict:
        """
        Detect cycle and write result to ``data/market_cycle.json``.
        Returns the result dict regardless of ``dry_run``.
        NEVER raises.
        """
        try:
            state = self.detect()
            result = state.to_dict()
            if not dry_run:
                self._output_path.parent.mkdir(parents=True, exist_ok=True)
                with self._output_path.open("w") as fh:
                    json.dump(result, fh, indent=2)
                log.info("Market cycle written to %s", self._output_path)
            return result
        except Exception as exc:
            log.error("BullCycleDetector.export failed: %s", exc)
            return {"error": str(exc)}

    def is_bull(self) -> bool:
        """Return True if the current cycle is BULL. NEVER raises."""
        try:
            return self.get_cycle() == "BULL"
        except Exception:
            return False

    def is_bear(self) -> bool:
        """Return True if the current cycle is BEAR. NEVER raises."""
        try:
            return self.get_cycle() == "BEAR"
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _fallback_state(self) -> CycleState:
        """Return a safe NEUTRAL CycleState for error fallback."""
        return CycleState(
            cycle="NEUTRAL",
            consecutive_bull_days=0,
            current_median_apy=0.0,
            bull_threshold=self._bull_threshold,
            min_bull_days=self._min_bull_days,
            allocation_caps=AllocationCaps(**_CAPS["NEUTRAL"]),
            protocol_apys={},
            history_days_used=0,
        )


# ---------------------------------------------------------------------------
# DynamicTierAllocator — applies caps to a capital amount
# ---------------------------------------------------------------------------

class DynamicTierAllocator:
    """
    Applies bull-cycle-aware allocation caps to a given total capital amount.

    Given total capital and per-tier target allocations (from Kelly/Markowitz),
    clamps each tier to its maximum cap and ensures the cash buffer is preserved.

    Usage::

        allocator = DynamicTierAllocator()
        adjusted = allocator.apply_caps(
            total_capital=100_000,
            target_allocations={"t1": 70_000, "t2": 25_000, "t3": 5_000}
        )
        # → {"t1": ..., "t2": ..., "t3": ..., "cash": ..., "cycle": "NEUTRAL"}
    """

    def __init__(
        self,
        detector: BullCycleDetector | None = None,
        apy_history_path: str | Path = DEFAULT_HISTORICAL_APY_PATH,
    ) -> None:
        self._detector = detector or BullCycleDetector(apy_history_path=apy_history_path)

    def apply_caps(
        self,
        total_capital: float,
        target_allocations: dict[str, float],
    ) -> dict[str, float | str]:
        """
        Clamp target allocations to current cycle caps.

        Parameters
        ----------
        total_capital:
            Total portfolio capital in USD.
        target_allocations:
            Dict with keys ``"t1"``, ``"t2"``, ``"t3"`` (dollar amounts).
            Unknown keys are passed through unchanged.

        Returns
        -------
        Dict with keys ``"t1"``, ``"t2"``, ``"t3"``, ``"cash"``, ``"cycle"``.
        NEVER raises.
        """
        try:
            if total_capital <= 0:
                return {"t1": 0.0, "t2": 0.0, "t3": 0.0, "cash": 0.0, "cycle": "NEUTRAL"}

            caps = self._detector.get_allocation_caps()
            cycle = self._detector.get_cycle()

            t1_max = total_capital * caps.t1_max_pct / 100.0
            t2_max = total_capital * caps.t2_max_pct / 100.0
            t3_max = total_capital * caps.t3_max_pct / 100.0
            cash_min = total_capital * caps.cash_buffer_min_pct / 100.0

            t1 = min(float(target_allocations.get("t1", 0.0)), t1_max)
            t2 = min(float(target_allocations.get("t2", 0.0)), t2_max)
            t3 = min(float(target_allocations.get("t3", 0.0)), t3_max)

            deployed = t1 + t2 + t3
            max_deployable = total_capital - cash_min

            # Scale down proportionally if total exceeds deployable
            if deployed > max_deployable and deployed > 0:
                scale = max_deployable / deployed
                t1 *= scale
                t2 *= scale
                t3 *= scale
                deployed = t1 + t2 + t3

            cash = total_capital - deployed

            return {
                "t1": round(t1, 2),
                "t2": round(t2, 2),
                "t3": round(t3, 2),
                "cash": round(cash, 2),
                "cycle": cycle,
            }
        except Exception as exc:
            log.error("DynamicTierAllocator.apply_caps failed: %s", exc)
            return {
                "t1": float(target_allocations.get("t1", 0.0)),
                "t2": float(target_allocations.get("t2", 0.0)),
                "t3": float(target_allocations.get("t3", 0.0)),
                "cash": 0.0,
                "cycle": "NEUTRAL",
            }

    def describe(self, total_capital: float = 100_000) -> str:
        """Return a human-readable string showing current caps and cycle."""
        try:
            state = self._detector.detect()
            caps = state.allocation_caps
            return (
                f"Market Cycle: {state.cycle}  "
                f"(median APY {state.current_median_apy:.2f}% over "
                f"{state.history_days_used}d, {state.consecutive_bull_days} bull days)\n"
                f"Allocation caps: T1≤{caps.t1_max_pct:.0f}%  "
                f"T2≤{caps.t2_max_pct:.0f}%  "
                f"T3≤{caps.t3_max_pct:.0f}%  "
                f"Cash≥{caps.cash_buffer_min_pct:.0f}%\n"
                f"On ${total_capital:,.0f} capital: "
                f"T1≤${total_capital * caps.t1_max_pct / 100:,.0f}  "
                f"T2≤${total_capital * caps.t2_max_pct / 100:,.0f}  "
                f"T3≤${total_capital * caps.t3_max_pct / 100:,.0f}"
            )
        except Exception as exc:
            return f"DynamicTierAllocator.describe error: {exc}"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_detector: Optional[BullCycleDetector] = None


def get_detector() -> BullCycleDetector:
    """Return (and lazily create) the module-level singleton BullCycleDetector."""
    global _default_detector
    if _default_detector is None:
        _default_detector = BullCycleDetector()
    return _default_detector


def get_allocation_caps() -> AllocationCaps:
    """Module-level shortcut — return current cycle allocation caps."""
    return get_detector().get_allocation_caps()


def get_cycle() -> str:
    """Module-level shortcut — return current cycle label."""
    return get_detector().get_cycle()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="SPA Bull Cycle Detector")
    parser.add_argument("--json",  action="store_true", help="Print JSON output")
    parser.add_argument("--write", action="store_true", help="Write market_cycle.json")
    parser.add_argument("--capital", type=float, default=100_000, help="Total capital for demo")
    args = parser.parse_args()

    detector = BullCycleDetector()
    if args.json:
        result = detector.export(dry_run=not args.write)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    allocator = DynamicTierAllocator(detector=detector)
    print(allocator.describe(total_capital=args.capital))
    print()

    # Demo: apply caps to a typical allocation
    demo_targets = {
        "t1": args.capital * 0.55,
        "t2": args.capital * 0.35,
        "t3": args.capital * 0.10,
    }
    adjusted = allocator.apply_caps(total_capital=args.capital, target_allocations=demo_targets)
    print("Demo allocation (target vs capped):")
    for tier in ("t1", "t2", "t3", "cash"):
        target = demo_targets.get(tier, 0)
        actual = adjusted[tier]
        print(f"  {tier}: target=${target:,.0f}  capped=${actual:,.0f}")
    print(f"  cycle={adjusted['cycle']}")

    if args.write:
        detector.export(dry_run=False)
        print("\nWrote data/market_cycle.json")
