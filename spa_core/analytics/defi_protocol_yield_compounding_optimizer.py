"""
MP-1134: DeFiProtocolYieldCompoundingOptimizer

Finds the optimal compounding frequency that maximises net yield after gas costs.
More frequent compounding increases effective APY but also total gas expenditure.
Computes the break-even compounding interval and surface the best frequency from a
caller-supplied list.

Pure stdlib, read-only/advisory, atomic ring-buffer log (cap 100).
Python 3.9 compatible.

CLI:
    python3 -m spa_core.analytics.defi_protocol_yield_compounding_optimizer --check
    python3 -m spa_core.analytics.defi_protocol_yield_compounding_optimizer --run
    python3 -m spa_core.analytics.defi_protocol_yield_compounding_optimizer --run --data-dir <dir>

Formula:
    effective_apy  = ((1 + base_apy_pct/100/freq)^freq - 1) * 100
    annual_gas_usd = freq * gas_cost_per_compound_usd
    gas_drag_pct   = annual_gas_usd / position_size_usd * 100
    net_apy_pct    = effective_apy - gas_drag_pct
    net_annual_yield_usd = net_apy_pct / 100 * position_size_usd
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
LOG_FILENAME = "yield_compounding_optimizer_log.json"
LOG_CAP = 100

# Label thresholds: optimal_frequency >= threshold → label
# Evaluated in order (first match wins).
_LABEL_THRESHOLDS: List[tuple] = [
    (365, "DAILY"),
    (52,  "WEEKLY"),
    (26,  "BIWEEKLY"),
    (12,  "MONTHLY"),
    (4,   "QUARTERLY"),
    (1,   "ANNUALLY"),
]

# Demo input used by the CLI --check / --run mode
_DEMO_INPUT: Dict[str, Any] = {
    "protocol_name": "demo-protocol",
    "base_apy_pct": 8.0,
    "position_size_usd": 50_000.0,
    "gas_cost_per_compound_usd": 5.0,
    "compounding_frequencies": [1, 4, 12, 26, 52, 365],
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _effective_apy(base_apy_pct: float, freq: int) -> float:
    """Compound APY: ((1 + base/100/n)^n - 1) * 100.  freq=0 → base_apy."""
    if freq <= 0:
        return base_apy_pct
    return ((1.0 + base_apy_pct / 100.0 / freq) ** freq - 1.0) * 100.0


def _optimal_label(freq: int) -> str:
    """Map a compounding frequency (times/year) to a human label."""
    for threshold, label in _LABEL_THRESHOLDS:
        if freq >= threshold:
            return label
    return "ANNUALLY"


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

class DeFiProtocolYieldCompoundingOptimizer:
    """
    Optimal compounding frequency analyser for a single DeFi yield position.

    Public API
    ----------
    result = optimizer.analyze(
        base_apy_pct              = 8.0,
        position_size_usd         = 50_000.0,
        gas_cost_per_compound_usd = 5.0,
        compounding_frequencies   = [1, 4, 12, 26, 52, 365],
        protocol_name             = "Aave-USDC",
        config                    = {"write_log": True},   # optional
    )

    Returned keys
    -------------
    protocol_name             str
    base_apy_pct              float
    position_size_usd         float
    gas_cost_per_compound_usd float
    results                   list[dict]  — one entry per frequency:
        frequency             int
        effective_apy_pct     float
        annual_gas_cost_usd   float
        net_apy_pct           float
        net_annual_yield_usd  float
    optimal_frequency         int
    optimal_net_apy_pct       float
    optimal_label             str   DAILY/WEEKLY/BIWEEKLY/MONTHLY/QUARTERLY/ANNUALLY
    gas_drag_at_optimal_pct   float
    timestamp                 str

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
        base_apy_pct: float,
        position_size_usd: float,
        gas_cost_per_compound_usd: float,
        compounding_frequencies: List[int],
        protocol_name: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if config is None:
            config = {}

        log_path = config.get("log_path", os.path.join(_DATA_DIR, LOG_FILENAME))
        cap = int(config.get("log_cap", self.LOG_CAP))
        write_log = bool(config.get("write_log", False))

        base_apy = float(base_apy_pct)
        position = float(position_size_usd)
        gas_per = float(gas_cost_per_compound_usd)

        # ── per-frequency analysis ────────────────────────────────────────
        results: List[Dict[str, Any]] = []
        for freq_raw in compounding_frequencies:
            freq = int(freq_raw)
            eff_apy = _effective_apy(base_apy, freq)
            annual_gas = gas_per * freq
            gas_drag = (annual_gas / position * 100.0) if position > 0 else 0.0
            net_apy = eff_apy - gas_drag
            # Round net_apy first; derive net_yield from rounded value so
            # net_annual_yield_usd == net_apy_pct / 100 * position exactly.
            net_apy_r = round(net_apy, 6)
            net_yield = round((net_apy_r / 100.0) * position, 6)

            results.append({
                "frequency":            freq,
                "effective_apy_pct":    round(eff_apy, 6),
                "annual_gas_cost_usd":  round(annual_gas, 6),
                "net_apy_pct":          net_apy_r,
                "net_annual_yield_usd": net_yield,
            })

        # ── optimal selection ─────────────────────────────────────────────
        if results:
            best = max(results, key=lambda r: r["net_apy_pct"])
            optimal_frequency = best["frequency"]
            optimal_net_apy = best["net_apy_pct"]
            opt_gas = best["annual_gas_cost_usd"]
            gas_drag_at_optimal = (opt_gas / position * 100.0) if position > 0 else 0.0
        else:
            optimal_frequency = 0
            optimal_net_apy = 0.0
            gas_drag_at_optimal = 0.0

        label = _optimal_label(optimal_frequency) if optimal_frequency >= 1 else "ANNUALLY"

        # ── output ────────────────────────────────────────────────────────
        output: Dict[str, Any] = {
            "protocol_name":             protocol_name,
            "base_apy_pct":              round(base_apy, 6),
            "position_size_usd":         round(position, 2),
            "gas_cost_per_compound_usd": round(gas_per, 6),
            "results":                   results,
            "optimal_frequency":         optimal_frequency,
            "optimal_net_apy_pct":       round(optimal_net_apy, 6),
            "optimal_label":             label,
            "gas_drag_at_optimal_pct":   round(gas_drag_at_optimal, 6),
            "timestamp":                 time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if write_log:
            _write_log(
                {
                    "ts":                    time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "protocol_name":         protocol_name,
                    "base_apy_pct":          round(base_apy, 6),
                    "position_size_usd":     round(position, 2),
                    "optimal_frequency":     optimal_frequency,
                    "optimal_net_apy_pct":   round(optimal_net_apy, 6),
                    "optimal_label":         label,
                    "gas_drag_at_optimal_pct": round(gas_drag_at_optimal, 6),
                },
                log_path,
                cap,
            )

        return output

    # ------------------------------------------------------------------ #
    # Convenience helpers (used by CLI / tests)
    # ------------------------------------------------------------------ #

    def result_for_freq(self, output: Dict[str, Any], freq: int) -> Optional[Dict[str, Any]]:
        """Return the per-frequency dict from *output['results']* matching *freq*."""
        for r in output.get("results", []):
            if r["frequency"] == freq:
                return r
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.analytics.defi_protocol_yield_compounding_optimizer",
        description=(
            "MP-1134 DeFiProtocolYieldCompoundingOptimizer: finds the compounding "
            "frequency that maximises net yield after gas costs. Read-only/advisory."
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
        help="compute and atomically write to data/yield_compounding_optimizer_log.json",
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

        opt = DeFiProtocolYieldCompoundingOptimizer()
        result = opt.analyze(
            base_apy_pct=_DEMO_INPUT["base_apy_pct"],
            position_size_usd=_DEMO_INPUT["position_size_usd"],
            gas_cost_per_compound_usd=_DEMO_INPUT["gas_cost_per_compound_usd"],
            compounding_frequencies=_DEMO_INPUT["compounding_frequencies"],
            protocol_name=_DEMO_INPUT["protocol_name"],
            config=cfg,
        )

        if args.run:
            print(
                f"yield_compounding_optimizer: protocol={result['protocol_name']} "
                f"optimal_freq={result['optimal_frequency']} "
                f"label={result['optimal_label']} "
                f"net_apy={result['optimal_net_apy_pct']:.4f}% — "
                f"written {cfg['log_path']}"
            )
        else:
            print(json.dumps(result, indent=2))
    except Exception as exc:  # advisory: no tracebacks, always exit 0
        print(
            f"yield_compounding_optimizer: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
