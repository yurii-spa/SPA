#!/usr/bin/env python3
"""DeFi Protocol Lending Utilization Cliff Detector (SPA-V760 / MP-1044) — read-only / advisory.

Detects when a lending protocol is approaching the "utilization cliff" — the kink
point in the interest rate model where borrowing rates jump sharply (slope2 >> slope1)
and supplier liquidity becomes locked because borrowers won't repay into a high-rate
environment.

Uses the standard kinked (two-slope) interest rate model:
    utilization < optimal  →  borrow_rate = base + (util / opt) * slope1
    utilization >= optimal →  borrow_rate = base + slope1 + ((util-opt)/(100-opt)) * slope2

Outputs a cliff_proximity_score (0–100), estimated days to cliff, borrow rate at the
kink, available exit liquidity, and a severity label.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/lending_utilization_cliff_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Labels
------
  SAFE_ZONE        proximity_ratio < 0.70
  APPROACHING_CLIFF 0.70 <= proximity_ratio < 0.90
  CLIFF_WARNING    0.90 <= proximity_ratio < 1.00
  ON_THE_CLIFF     1.00 <= proximity_ratio <= 1.05
  CLIFF_BREACHED   proximity_ratio > 1.05

  proximity_ratio = current_utilization_pct / optimal_utilization_pct

CLI
---
  python3 -m spa_core.analytics.defi_protocol_lending_utilization_cliff_detector --check
  python3 -m spa_core.analytics.defi_protocol_lending_utilization_cliff_detector --run
  python3 -m spa_core.analytics.defi_protocol_lending_utilization_cliff_detector --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "lending_utilization_cliff_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "defi_protocol_lending_utilization_cliff_detector"
MP_TAG = "MP-1044"

# Label proximity thresholds (fraction of optimal utilization)
THRESHOLD_SAFE = 0.70
THRESHOLD_APPROACHING = 0.90
THRESHOLD_ON_CLIFF_HI = 1.05  # upper bound for ON_THE_CLIFF

log = logging.getLogger("spa.analytics.defi_protocol_lending_utilization_cliff_detector")


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _compute_borrow_rate(
    utilization_pct: float,
    optimal_utilization_pct: float,
    base_rate_pct: float,
    slope1_pct: float,
    slope2_pct: float,
) -> float:
    """Compute borrow rate using kinked two-slope model.

    Both ``utilization_pct`` and ``optimal_utilization_pct`` are expressed as
    percentages (0–100). The returned rate is also in percent.

    Edge cases
    ----------
    * utilization <= 0: returns base_rate_pct.
    * optimal == 0 and util > 0: entire slope1 applied instantly, then slope2.
    * optimal == 100: slope2 is never reached.
    """
    u = float(utilization_pct)
    opt = float(optimal_utilization_pct)
    base = float(base_rate_pct)
    s1 = float(slope1_pct)
    s2 = float(slope2_pct)

    if u <= 0.0:
        return base

    if u <= opt:
        if opt <= 0.0:
            return base + s1
        return base + (u / opt) * s1
    else:
        remaining = 100.0 - opt
        if remaining <= 0.0:
            return base + s1
        excess = u - opt
        return base + s1 + (excess / remaining) * s2


def _compute_cliff_proximity_score(
    current_utilization_pct: float,
    optimal_utilization_pct: float,
) -> float:
    """Return a 0–100 score representing proximity to the kink.

    0 = no borrows; 100 = at or past the kink.
    """
    if optimal_utilization_pct <= 0.0:
        return 100.0
    ratio = current_utilization_pct / optimal_utilization_pct
    return min(100.0, round(ratio * 100.0, 4))


def _compute_days_to_cliff(
    current_utilization_pct: float,
    optimal_utilization_pct: float,
    daily_borrow_growth_pct: float,
) -> Optional[float]:
    """Estimate days until utilization reaches the kink.

    Model: borrows grow at ``daily_borrow_growth_pct`` % per day →
    daily utilization delta ≈ current_utilization_pct * daily_borrow_growth_pct / 100.

    Returns None when:
    * Already at or past cliff.
    * daily_borrow_growth_pct <= 0 (borrows not growing).
    * current_utilization_pct <= 0 (no borrows to grow from).
    """
    gap = optimal_utilization_pct - current_utilization_pct
    if gap <= 0.0:
        return 0.0  # already at/past cliff

    if daily_borrow_growth_pct <= 0.0 or current_utilization_pct <= 0.0:
        return None  # never reaching cliff under current conditions

    daily_delta = current_utilization_pct * (daily_borrow_growth_pct / 100.0)
    if daily_delta <= 0.0:
        return None

    days = gap / daily_delta
    return round(days, 2)


def _compute_exit_liquidity_pct(
    current_utilization_pct: float,
    total_supplied_usd: float,
    total_borrowed_usd: float,
) -> float:
    """Return the % of pool available for immediate withdrawal.

    Prefers the supplied/borrowed figures for accuracy; falls back to
    100 - utilization_pct when totals are invalid.
    """
    if total_supplied_usd > 0.0 and total_borrowed_usd >= 0.0:
        liquid = total_supplied_usd - total_borrowed_usd
        pct = max(0.0, liquid / total_supplied_usd * 100.0)
        return round(pct, 4)
    return max(0.0, round(100.0 - current_utilization_pct, 4))


def _proximity_ratio(
    current_utilization_pct: float,
    optimal_utilization_pct: float,
) -> float:
    """Return current / optimal utilization ratio (no cap)."""
    if optimal_utilization_pct <= 0.0:
        return float("inf") if current_utilization_pct > 0 else 0.0
    return current_utilization_pct / optimal_utilization_pct


def _label(ratio: float) -> str:
    """Classify cliff proximity."""
    if not math.isfinite(ratio):
        return "CLIFF_BREACHED"
    if ratio < THRESHOLD_SAFE:
        return "SAFE_ZONE"
    if ratio < THRESHOLD_APPROACHING:
        return "APPROACHING_CLIFF"
    if ratio < 1.00:
        return "CLIFF_WARNING"
    if ratio <= THRESHOLD_ON_CLIFF_HI:
        return "ON_THE_CLIFF"
    return "CLIFF_BREACHED"


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


def _analyze_single(
    protocol_name: str,
    current_utilization_pct: float,
    optimal_utilization_pct: float,
    kink_multiplier: float,
    base_rate_pct: float,
    slope1_pct: float,
    slope2_pct: float,
    total_supplied_usd: float,
    total_borrowed_usd: float,
    daily_borrow_growth_pct: float,
) -> Dict[str, Any]:
    """Run full cliff analysis for one protocol snapshot. Never raises."""
    warnings: List[str] = []

    # Clamp input to sane ranges
    cur = max(0.0, min(100.0, float(current_utilization_pct)))
    opt = max(0.0, min(100.0, float(optimal_utilization_pct)))
    base = float(base_rate_pct)
    s1 = max(0.0, float(slope1_pct))
    s2 = max(0.0, float(slope2_pct))
    km = float(kink_multiplier)
    supplied = max(0.0, float(total_supplied_usd))
    borrowed = max(0.0, float(total_borrowed_usd))
    growth = float(daily_borrow_growth_pct)

    if opt <= 0.0:
        warnings.append("optimal_utilization_pct <= 0 — cliff detection degenerate")
    if supplied <= 0.0:
        warnings.append("total_supplied_usd <= 0 — exit_liquidity_pct estimated from utilization")
    if borrowed > supplied and supplied > 0.0:
        warnings.append("total_borrowed_usd > total_supplied_usd — data inconsistency")

    ratio = _proximity_ratio(cur, opt)
    cliff_score = _compute_cliff_proximity_score(cur, opt)
    days_to_cliff = _compute_days_to_cliff(cur, opt, growth)
    borrow_rate_now = _compute_borrow_rate(cur, opt, base, s1, s2)
    borrow_rate_at_cliff = _compute_borrow_rate(opt, opt, base, s1, s2)
    borrow_rate_if_breached = _compute_borrow_rate(min(cur, 99.9), opt, base, s1, s2) \
        if cur > opt else None
    exit_liq = _compute_exit_liquidity_pct(cur, supplied, borrowed)
    severity_label = _label(ratio)

    rate_jump = borrow_rate_at_cliff - _compute_borrow_rate(
        max(0.0, opt - 1.0), opt, base, s1, s2
    )

    return {
        "protocol_name": str(protocol_name),
        "current_utilization_pct": round(cur, 4),
        "optimal_utilization_pct": round(opt, 4),
        "kink_multiplier": round(km, 4),
        "base_rate_pct": round(base, 4),
        "slope1_pct": round(s1, 4),
        "slope2_pct": round(s2, 4),
        "total_supplied_usd": round(supplied, 2),
        "total_borrowed_usd": round(borrowed, 2),
        "daily_borrow_growth_pct": round(growth, 4),
        "proximity_ratio": round(ratio, 6) if math.isfinite(ratio) else None,
        "cliff_proximity_score": round(cliff_score, 4),
        "days_to_cliff_estimate": days_to_cliff,
        "borrow_rate_current_pct": round(borrow_rate_now, 6),
        "borrow_rate_at_cliff_pct": round(borrow_rate_at_cliff, 6),
        "rate_jump_at_cliff_pct": round(rate_jump, 6),
        "exit_liquidity_pct": round(exit_liq, 4),
        "label": severity_label,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class DeFiProtocolLendingUtilizationCliffDetector(BaseAnalytics):
    """Detect lending protocol utilization cliff proximity.

    Usage
    -----
    ::

        detector = DeFiProtocolLendingUtilizationCliffDetector()
        result = detector.analyze(
            protocol_name="aave_v3",
            current_utilization_pct=76.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=76_000_000,
            daily_borrow_growth_pct=0.5,
        )
        print(result["label"])  # → APPROACHING_CLIFF
    """

    OUTPUT_PATH = "data/lending_utilization_cliff_log.json"

    def __init__(
        self,
        data_dir: Optional[Path | str] = None,
        ring_cap: int = RING_BUFFER_CAP,
    ) -> None:
        super().__init__()
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._ring_cap = ring_cap
        self._last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Returns last cliff analysis result as JSON-serializable dict."""
        return dict(self._last_result) if self._last_result else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        protocol_name: str,
        current_utilization_pct: float,
        optimal_utilization_pct: float,
        kink_multiplier: float,
        base_rate_pct: float,
        slope1_pct: float,
        slope2_pct: float,
        total_supplied_usd: float,
        total_borrowed_usd: float,
        daily_borrow_growth_pct: float,
    ) -> Dict[str, Any]:
        """Run cliff detection for a single protocol snapshot.

        Returns
        -------
        Dict with cliff_proximity_score, days_to_cliff_estimate,
        borrow_rate_at_cliff_pct, exit_liquidity_pct, label, and metadata.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            detail = _analyze_single(
                protocol_name=protocol_name,
                current_utilization_pct=current_utilization_pct,
                optimal_utilization_pct=optimal_utilization_pct,
                kink_multiplier=kink_multiplier,
                base_rate_pct=base_rate_pct,
                slope1_pct=slope1_pct,
                slope2_pct=slope2_pct,
                total_supplied_usd=total_supplied_usd,
                total_borrowed_usd=total_borrowed_usd,
                daily_borrow_growth_pct=daily_borrow_growth_pct,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("analyze() failed for %r: %s", protocol_name, exc)
            detail = {
                "protocol_name": str(protocol_name),
                "error": str(exc),
                "label": "SAFE_ZONE",
                "cliff_proximity_score": 0.0,
                "days_to_cliff_estimate": None,
                "borrow_rate_at_cliff_pct": 0.0,
                "exit_liquidity_pct": 100.0,
                "warnings": [f"analysis_error: {exc}"],
            }

        result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp": timestamp,
            **detail,
        }
        self._last_result = result
        return result

    def analyze_batch(
        self,
        protocols: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze multiple protocol snapshots at once.

        Each element of ``protocols`` must be a dict matching the keyword
        arguments of :meth:`analyze`.

        Returns
        -------
        Batch result with per_protocol list and summary counts by label.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        per_protocol: List[Dict[str, Any]] = []

        for p in protocols:
            try:
                r = self.analyze(**p)
                per_protocol.append(r)
            except Exception as exc:  # noqa: BLE001
                log.warning("Batch analyze failed for %r: %s", p.get("protocol_name"), exc)
                per_protocol.append({
                    "protocol_name": p.get("protocol_name", "unknown"),
                    "error": str(exc),
                    "label": "SAFE_ZONE",
                    "cliff_proximity_score": 0.0,
                })

        label_counts: Dict[str, int] = {}
        for r in per_protocol:
            lbl = r.get("label", "SAFE_ZONE")
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        at_risk = [
            r for r in per_protocol
            if r.get("label") in ("CLIFF_WARNING", "ON_THE_CLIFF", "CLIFF_BREACHED")
        ]

        batch_result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp": timestamp,
            "protocol_count": len(per_protocol),
            "at_risk_count": len(at_risk),
            "label_counts": label_counts,
            "per_protocol": per_protocol,
            "at_risk": at_risk,
        }
        self._last_result = batch_result
        return batch_result

    def get_label(self) -> Optional[str]:
        """Return the label from the last :meth:`analyze` call, or None."""
        if self._last_result is None:
            return None
        return self._last_result.get("label")

    def is_at_risk(self) -> bool:
        """Return True if last result is CLIFF_WARNING / ON_THE_CLIFF / CLIFF_BREACHED."""
        label = self.get_label()
        return label in ("CLIFF_WARNING", "ON_THE_CLIFF", "CLIFF_BREACHED")

    def save(self) -> bool:
        """Atomically append last result to the ring-buffer log file.

        Returns True on success, False on any error (never raises).
        """
        if self._last_result is None:
            log.warning("save() called before analyze() — nothing to write")
            return False
        try:
            log_path = self._data_dir / LOG_FILENAME
            existing: List[Any] = _load_json_list(log_path)
            existing.append(self._last_result)
            if len(existing) > self._ring_cap:
                existing = existing[-self._ring_cap:]
            _atomic_write(log_path, existing)
            log.info("lending_utilization_cliff_log written (%d entries)", len(existing))
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("save() failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Module-level functional API
# ---------------------------------------------------------------------------


def analyze_cliff(
    protocol_name: str,
    current_utilization_pct: float,
    optimal_utilization_pct: float,
    kink_multiplier: float,
    base_rate_pct: float,
    slope1_pct: float,
    slope2_pct: float,
    total_supplied_usd: float,
    total_borrowed_usd: float,
    daily_borrow_growth_pct: float,
    data_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Functional entry-point: analyze and return result dict."""
    detector = DeFiProtocolLendingUtilizationCliffDetector(data_dir=data_dir)
    return detector.analyze(
        protocol_name=protocol_name,
        current_utilization_pct=current_utilization_pct,
        optimal_utilization_pct=optimal_utilization_pct,
        kink_multiplier=kink_multiplier,
        base_rate_pct=base_rate_pct,
        slope1_pct=slope1_pct,
        slope2_pct=slope2_pct,
        total_supplied_usd=total_supplied_usd,
        total_borrowed_usd=total_borrowed_usd,
        daily_borrow_growth_pct=daily_borrow_growth_pct,
    )


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------


_DEMO_PROTOCOLS: List[Dict[str, Any]] = [
    {
        "protocol_name": "aave_v3_usdc",
        "current_utilization_pct": 55.0,
        "optimal_utilization_pct": 80.0,
        "kink_multiplier": 60.0,
        "base_rate_pct": 0.0,
        "slope1_pct": 4.0,
        "slope2_pct": 75.0,
        "total_supplied_usd": 500_000_000,
        "total_borrowed_usd": 275_000_000,
        "daily_borrow_growth_pct": 0.3,
    },
    {
        "protocol_name": "compound_v3_usdc",
        "current_utilization_pct": 78.5,
        "optimal_utilization_pct": 80.0,
        "kink_multiplier": 50.0,
        "base_rate_pct": 0.5,
        "slope1_pct": 5.0,
        "slope2_pct": 60.0,
        "total_supplied_usd": 300_000_000,
        "total_borrowed_usd": 235_500_000,
        "daily_borrow_growth_pct": 0.8,
    },
    {
        "protocol_name": "morpho_steakhouse",
        "current_utilization_pct": 93.5,
        "optimal_utilization_pct": 92.0,
        "kink_multiplier": 80.0,
        "base_rate_pct": 0.0,
        "slope1_pct": 6.5,
        "slope2_pct": 150.0,
        "total_supplied_usd": 120_000_000,
        "total_borrowed_usd": 112_200_000,
        "daily_borrow_growth_pct": 0.2,
    },
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="defi_protocol_lending_utilization_cliff_detector",
        description="MP-1044 Lending Utilization Cliff Detector — kinked rate model analysis",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print; do NOT write to disk (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute, print, and atomically write to data/lending_utilization_cliff_log.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override default data/ directory path",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry-point — exit 0 always (pure advisory)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    write_mode: bool = args.run

    detector = DeFiProtocolLendingUtilizationCliffDetector(data_dir=data_dir)
    result = detector.analyze_batch(_DEMO_PROTOCOLS)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if write_mode:
        ok = detector.save()
        if not ok:
            print(
                "[defi_protocol_lending_utilization_cliff_detector] WARNING: save() failed",
                file=sys.stderr,
            )
        else:
            print(
                f"[defi_protocol_lending_utilization_cliff_detector] Written to "
                f"{data_dir / LOG_FILENAME}",
                file=sys.stderr,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
