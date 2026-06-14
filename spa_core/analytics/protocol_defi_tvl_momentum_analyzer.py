"""
MP-1135: ProtocolDeFiTvlMomentumAnalyzer

Analyses TVL momentum as a leading indicator of protocol health and yield
sustainability.  Rapidly growing TVL dilutes yield; rapidly falling TVL signals
protocol problems.

Pure stdlib, read-only/advisory, atomic ring-buffer log (cap 100).
Python 3.9 compatible.

CLI:
    python3 -m spa_core.analytics.protocol_defi_tvl_momentum_analyzer --check
    python3 -m spa_core.analytics.protocol_defi_tvl_momentum_analyzer --run
    python3 -m spa_core.analytics.protocol_defi_tvl_momentum_analyzer --run --data-dir <dir>

Momentum Score Formula  (int, 0-100, 50 = neutral)
    raw = 50 + (change_7d_pct * 50 + change_30d_pct * 30 + change_90d_pct * 20) / 100
    momentum_score = int(clamp(raw, 0, 100))
    Weights: 7d→50, 30d→30, 90d→20 (sum = 100)

TVL change formulas:
    tvl_change_7d_pct  = (tvl_now - tvl_7d_ago)  / |tvl_7d_ago|  * 100
    tvl_change_30d_pct = (tvl_now - tvl_30d_ago) / |tvl_30d_ago| * 100
    tvl_change_90d_pct = (tvl_now - tvl_90d_ago) / |tvl_90d_ago| * 100
    (returns 0.0 when the denominator is 0)

Yield dilution risk  (based on tvl_change_30d_pct — TVL growth dilutes yield)
    < 10%   → LOW
    10–50%  → MEDIUM
    50–200% → HIGH
    > 200%  → CRITICAL

TVL label  (based on tvl_change_30d_pct)
    > 50%            → RAPID_GROWTH
    10% – 50%        → HEALTHY_GROWTH
    -10% – 10%       → STABLE
    -30% – -10%      → DECLINING
    < -30%           → RAPID_DECLINE

Log file: data/tvl_momentum_log.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ── constants ────────────────────────────────────────────────────────────────

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
LOG_FILENAME = "tvl_momentum_log.json"
LOG_CAP = 100

# Momentum score weights (must sum to 100)
_W_7D: float = 50.0
_W_30D: float = 30.0
_W_90D: float = 20.0

# Yield dilution risk thresholds (based on 30d growth %)
_DILUTION_CRITICAL: float = 200.0
_DILUTION_HIGH: float = 50.0
_DILUTION_MEDIUM: float = 10.0

# TVL label thresholds (based on 30d change %)
_LABEL_RAPID_GROWTH: float = 50.0
_LABEL_HEALTHY_GROWTH: float = 10.0
_LABEL_STABLE_LOW: float = -10.0
_LABEL_DECLINING_LOW: float = -30.0

VALID_YIELD_TYPES = frozenset({"fees", "emissions", "lending", "staking"})

# Demo input for CLI
_DEMO_INPUT: Dict[str, Any] = {
    "protocol_name": "demo-protocol",
    "tvl_now_usd":    500_000_000.0,
    "tvl_7d_ago_usd": 480_000_000.0,
    "tvl_30d_ago_usd": 420_000_000.0,
    "tvl_90d_ago_usd": 350_000_000.0,
    "yield_type": "lending",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _pct_change(old: float, new: float) -> float:
    """(new - old) / |old| * 100; returns 0.0 when old == 0."""
    if old == 0.0:
        return 0.0
    return (new - old) / abs(old) * 100.0


def _momentum_score(change_7d: float, change_30d: float, change_90d: float) -> int:
    """Weighted momentum score, int clamped to [0, 100], neutral = 50."""
    raw = 50.0 + (change_7d * _W_7D + change_30d * _W_30D + change_90d * _W_90D) / 100.0
    return int(max(0.0, min(100.0, raw)))


def _yield_dilution_risk(change_30d: float) -> str:
    """Classify yield dilution risk from 30-day TVL growth."""
    if change_30d >= _DILUTION_CRITICAL:
        return "CRITICAL"
    if change_30d >= _DILUTION_HIGH:
        return "HIGH"
    if change_30d >= _DILUTION_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _tvl_label(change_30d: float) -> str:
    """Classify TVL trend from 30-day change."""
    if change_30d > _LABEL_RAPID_GROWTH:
        return "RAPID_GROWTH"
    if change_30d > _LABEL_HEALTHY_GROWTH:
        return "HEALTHY_GROWTH"
    if change_30d >= _LABEL_STABLE_LOW:
        return "STABLE"
    if change_30d >= _LABEL_DECLINING_LOW:
        return "DECLINING"
    return "RAPID_DECLINE"


def _write_log(entry: Dict[str, Any], log_path: str, cap: int) -> None:
    """Append *entry* to the ring-buffer log at *log_path* (atomic write)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log: List[Any] = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                raw = json.load(fh)
            if isinstance(raw, list):
                log = raw
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp, log_path)


# ── main class ───────────────────────────────────────────────────────────────

class ProtocolDeFiTvlMomentumAnalyzer:
    """
    TVL momentum analyser for a single DeFi protocol.

    Public API
    ----------
    result = analyzer.analyze(
        tvl_now_usd    = 500_000_000.0,
        tvl_7d_ago_usd = 480_000_000.0,
        tvl_30d_ago_usd = 420_000_000.0,
        tvl_90d_ago_usd = 350_000_000.0,
        protocol_name  = "Aave-USDC",
        yield_type     = "lending",
        config         = {"write_log": True},   # optional
    )

    Returned keys
    -------------
    protocol_name        str
    yield_type           str
    tvl_now_usd          float
    tvl_7d_ago_usd       float
    tvl_30d_ago_usd      float
    tvl_90d_ago_usd      float
    tvl_change_7d_pct    float
    tvl_change_30d_pct   float
    tvl_change_90d_pct   float
    momentum_score       int   0-100, 50=neutral
    yield_dilution_risk  str   LOW/MEDIUM/HIGH/CRITICAL
    tvl_label            str   RAPID_GROWTH/HEALTHY_GROWTH/STABLE/DECLINING/RAPID_DECLINE
    timestamp            str

    Config keys (all optional)
    --------------------------
    write_log   bool   write ring-buffer log (default False)
    log_path    str    override log file path
    log_cap     int    ring-buffer cap (default 100)
    """

    LOG_CAP: int = LOG_CAP

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        tvl_now_usd: float,
        tvl_7d_ago_usd: float,
        tvl_30d_ago_usd: float,
        tvl_90d_ago_usd: float,
        protocol_name: str = "",
        yield_type: str = "lending",
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if config is None:
            config = {}

        log_path = config.get("log_path", os.path.join(_DATA_DIR, LOG_FILENAME))
        cap = int(config.get("log_cap", self.LOG_CAP))
        write_log = bool(config.get("write_log", False))

        tvl_now = float(tvl_now_usd)
        tvl_7d  = float(tvl_7d_ago_usd)
        tvl_30d = float(tvl_30d_ago_usd)
        tvl_90d = float(tvl_90d_ago_usd)

        # ── TVL changes ───────────────────────────────────────────────────
        change_7d  = _pct_change(tvl_7d,  tvl_now)
        change_30d = _pct_change(tvl_30d, tvl_now)
        change_90d = _pct_change(tvl_90d, tvl_now)

        # ── derived metrics ───────────────────────────────────────────────
        score  = _momentum_score(change_7d, change_30d, change_90d)
        risk   = _yield_dilution_risk(change_30d)
        label  = _tvl_label(change_30d)

        # ── output ────────────────────────────────────────────────────────
        output: Dict[str, Any] = {
            "protocol_name":       protocol_name,
            "yield_type":          yield_type,
            "tvl_now_usd":         round(tvl_now, 2),
            "tvl_7d_ago_usd":      round(tvl_7d, 2),
            "tvl_30d_ago_usd":     round(tvl_30d, 2),
            "tvl_90d_ago_usd":     round(tvl_90d, 2),
            "tvl_change_7d_pct":   round(change_7d, 6),
            "tvl_change_30d_pct":  round(change_30d, 6),
            "tvl_change_90d_pct":  round(change_90d, 6),
            "momentum_score":      score,
            "yield_dilution_risk": risk,
            "tvl_label":           label,
            "timestamp":           time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if write_log:
            _write_log(
                {
                    "ts":                  time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "protocol_name":       protocol_name,
                    "yield_type":          yield_type,
                    "tvl_now_usd":         round(tvl_now, 2),
                    "tvl_change_7d_pct":   round(change_7d, 6),
                    "tvl_change_30d_pct":  round(change_30d, 6),
                    "tvl_change_90d_pct":  round(change_90d, 6),
                    "momentum_score":      score,
                    "yield_dilution_risk": risk,
                    "tvl_label":           label,
                },
                log_path,
                cap,
            )

        return output


# ── CLI ──────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.analytics.protocol_defi_tvl_momentum_analyzer",
        description=(
            "MP-1135 ProtocolDeFiTvlMomentumAnalyzer: TVL momentum analysis as a "
            "leading indicator of protocol health and yield sustainability. "
            "Read-only/advisory."
        ),
        add_help=True,
    )
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--check", action="store_true",
        help="compute and print JSON analysis WITHOUT writing (default)",
    )
    grp.add_argument(
        "--run", action="store_true",
        help="compute and atomically write to data/tvl_momentum_log.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        cfg: Dict[str, Any] = {}
        if args.run:
            data_dir = args.data_dir if args.data_dir else _DATA_DIR
            cfg["log_path"] = os.path.join(data_dir, LOG_FILENAME)
            cfg["write_log"] = True

        az = ProtocolDeFiTvlMomentumAnalyzer()
        result = az.analyze(
            tvl_now_usd=_DEMO_INPUT["tvl_now_usd"],
            tvl_7d_ago_usd=_DEMO_INPUT["tvl_7d_ago_usd"],
            tvl_30d_ago_usd=_DEMO_INPUT["tvl_30d_ago_usd"],
            tvl_90d_ago_usd=_DEMO_INPUT["tvl_90d_ago_usd"],
            protocol_name=_DEMO_INPUT["protocol_name"],
            yield_type=_DEMO_INPUT["yield_type"],
            config=cfg,
        )

        if args.run:
            print(
                f"tvl_momentum_analyzer: protocol={result['protocol_name']} "
                f"label={result['tvl_label']} "
                f"score={result['momentum_score']} "
                f"dilution_risk={result['yield_dilution_risk']} — "
                f"written {cfg['log_path']}"
            )
        else:
            print(json.dumps(result, indent=2))
    except Exception as exc:  # advisory: no tracebacks, always exit 0
        print(
            f"tvl_momentum_analyzer: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
