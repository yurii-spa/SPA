"""
MP-951 ProtocolLiquidityProviderProfitabilityTracker
Advisory/read-only analytics module.
Tracks LP position profitability factoring in fees, rewards, IL, gas costs,
and compares against a simple hold (hodl) benchmark.

Pure stdlib. Atomic writes via tmp + os.replace.
Ring-buffer log → data/lp_profitability_log.json (cap 100).

Labels:  EXCELLENT / GOOD / BREAK_EVEN / UNDERPERFORMING / LOSS
Flags:   BEATS_HODL / HIGH_IL_RATIO / GAS_HEAVY / REWARD_DEPENDENT / LONG_TERM_HOLD

CLI:
  python3 -m spa_core.analytics.protocol_liquidity_provider_profitability_tracker --check
  python3 -m spa_core.analytics.protocol_liquidity_provider_profitability_tracker --run
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "lp_profitability_log.json"
_RING_CAP = 100

LABEL_EXCELLENT = "EXCELLENT"
LABEL_GOOD = "GOOD"
LABEL_BREAK_EVEN = "BREAK_EVEN"
LABEL_UNDERPERFORMING = "UNDERPERFORMING"
LABEL_LOSS = "LOSS"

FLAG_BEATS_HODL = "BEATS_HODL"
FLAG_HIGH_IL_RATIO = "HIGH_IL_RATIO"
FLAG_GAS_HEAVY = "GAS_HEAVY"
FLAG_REWARD_DEPENDENT = "REWARD_DEPENDENT"
FLAG_LONG_TERM_HOLD = "LONG_TERM_HOLD"

# Thresholds
_EXCELLENT_APY = 20.0
_GOOD_APY = 8.0
_BREAK_EVEN_APY = 0.0
_UNDERPERFORMING_APY = -5.0
_HIGH_IL_RATIO_THRESHOLD = 0.50        # IL > 50% of fees
_GAS_HEAVY_THRESHOLD = 0.05            # gas > 5% of gross pnl
_LONG_TERM_DAYS = 180
_DAYS_PER_YEAR = 365.0


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class ProtocolLiquidityProviderProfitabilityTracker:
    """Tracks LP position profitability across a list of positions."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, positions: list[dict], config: dict | None = None) -> dict:
        """Compute profitability metrics for each LP position.

        Parameters
        ----------
        positions:
            List of position dicts.  Each must contain:
            ``protocol``, ``pair``, ``entry_value_usd``, ``current_value_usd``,
            ``fees_earned_usd``, ``rewards_earned_usd``, ``il_loss_usd``,
            ``gas_costs_usd``, ``days_held``.
            Optional: ``entry_price_ratio``, ``current_price_ratio``,
            ``benchmark_hodl_value_usd``.
        config:
            Override thresholds: ``excellent_apy``, ``good_apy``,
            ``il_ratio_threshold``, ``gas_heavy_threshold``, ``long_term_days``.

        Returns
        -------
        dict with keys ``positions``, ``aggregates``, ``tracked_at``.
        """
        cfg = self._merge_config(config or {})
        results = []
        for pos in positions:
            results.append(self._compute_position(pos, cfg))

        aggregates = self._compute_aggregates(results)
        output = {
            "positions": results,
            "aggregates": aggregates,
            "tracked_at": datetime.now(timezone.utc).isoformat(),
        }
        return output

    # ------------------------------------------------------------------
    # Per-position computation
    # ------------------------------------------------------------------

    def _compute_position(self, pos: dict, cfg: dict) -> dict:
        protocol = str(pos.get("protocol", "unknown"))
        pair = str(pos.get("pair", "unknown"))
        entry_value_usd = float(pos.get("entry_value_usd", 0.0))
        current_value_usd = float(pos.get("current_value_usd", 0.0))
        fees_earned_usd = float(pos.get("fees_earned_usd", 0.0))
        rewards_earned_usd = float(pos.get("rewards_earned_usd", 0.0))
        il_loss_usd = float(pos.get("il_loss_usd", 0.0))
        gas_costs_usd = float(pos.get("gas_costs_usd", 0.0))
        days_held = float(pos.get("days_held", 1.0))

        # Optional fields
        entry_price_ratio = float(pos.get("entry_price_ratio", 1.0))
        current_price_ratio = float(pos.get("current_price_ratio", 1.0))
        benchmark_hodl_value_usd = float(
            pos.get("benchmark_hodl_value_usd", entry_value_usd)
        )

        # Derived P&L
        # Gross PnL = capital appreciation + fees + rewards − IL
        capital_change = current_value_usd - entry_value_usd
        gross_pnl_usd = capital_change + fees_earned_usd + rewards_earned_usd - il_loss_usd
        net_pnl_usd = gross_pnl_usd - gas_costs_usd

        # Percentage returns (vs entry)
        if entry_value_usd > 0:
            net_pnl_pct = (net_pnl_usd / entry_value_usd) * 100.0
        else:
            net_pnl_pct = 0.0

        # vs hodl (outperformance): how much better/worse than simply holding
        hodl_pnl_usd = benchmark_hodl_value_usd - entry_value_usd
        vs_hodl_usd = net_pnl_usd - hodl_pnl_usd
        if entry_value_usd > 0:
            vs_hodl_pct = (vs_hodl_usd / entry_value_usd) * 100.0
        else:
            vs_hodl_pct = 0.0

        # Annualized APY (simple, not compounding) based on fees only
        if days_held > 0 and entry_value_usd > 0:
            fee_apy_pct = (fees_earned_usd / entry_value_usd) * (
                _DAYS_PER_YEAR / days_held
            ) * 100.0
            total_apy_pct = (net_pnl_usd / entry_value_usd) * (
                _DAYS_PER_YEAR / days_held
            ) * 100.0
        else:
            fee_apy_pct = 0.0
            total_apy_pct = 0.0

        # IL as pct of fees earned
        if fees_earned_usd > 0:
            il_as_pct_fees = (il_loss_usd / fees_earned_usd) * 100.0
        else:
            il_as_pct_fees = 100.0 if il_loss_usd > 0 else 0.0

        # Label
        label = self._assign_label(total_apy_pct=total_apy_pct, vs_hodl_pct=vs_hodl_pct, cfg=cfg)

        # Flags
        flags = self._compute_flags(
            vs_hodl_pct=vs_hodl_pct,
            il_loss_usd=il_loss_usd,
            fees_earned_usd=fees_earned_usd,
            gas_costs_usd=gas_costs_usd,
            gross_pnl_usd=gross_pnl_usd,
            rewards_earned_usd=rewards_earned_usd,
            days_held=days_held,
            cfg=cfg,
        )

        return {
            "protocol": protocol,
            "pair": pair,
            "entry_value_usd": entry_value_usd,
            "current_value_usd": current_value_usd,
            "fees_earned_usd": fees_earned_usd,
            "rewards_earned_usd": rewards_earned_usd,
            "il_loss_usd": il_loss_usd,
            "gas_costs_usd": gas_costs_usd,
            "days_held": days_held,
            "entry_price_ratio": entry_price_ratio,
            "current_price_ratio": current_price_ratio,
            "benchmark_hodl_value_usd": benchmark_hodl_value_usd,
            "gross_pnl_usd": round(gross_pnl_usd, 4),
            "net_pnl_usd": round(net_pnl_usd, 4),
            "net_pnl_pct": round(net_pnl_pct, 4),
            "vs_hodl_pct": round(vs_hodl_pct, 4),
            "fee_apy_pct": round(fee_apy_pct, 4),
            "total_apy_pct": round(total_apy_pct, 4),
            "il_as_pct_fees": round(il_as_pct_fees, 4),
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Label assignment
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_label(total_apy_pct: float, vs_hodl_pct: float, cfg: dict) -> str:
        excellent_apy = cfg["excellent_apy"]
        good_apy = cfg["good_apy"]

        if total_apy_pct >= excellent_apy and vs_hodl_pct >= 0:
            return LABEL_EXCELLENT
        if total_apy_pct >= good_apy:
            return LABEL_GOOD
        if total_apy_pct >= _BREAK_EVEN_APY:
            return LABEL_BREAK_EVEN
        if total_apy_pct >= _UNDERPERFORMING_APY:
            return LABEL_UNDERPERFORMING
        return LABEL_LOSS

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_flags(
        vs_hodl_pct: float,
        il_loss_usd: float,
        fees_earned_usd: float,
        gas_costs_usd: float,
        gross_pnl_usd: float,
        rewards_earned_usd: float,
        days_held: float,
        cfg: dict,
    ) -> list[str]:
        flags: list[str] = []

        if vs_hodl_pct > 0:
            flags.append(FLAG_BEATS_HODL)

        # HIGH_IL_RATIO: IL > threshold * fees_earned
        if fees_earned_usd > 0:
            il_ratio = il_loss_usd / fees_earned_usd
        else:
            il_ratio = 1.0 if il_loss_usd > 0 else 0.0
        if il_ratio > cfg["il_ratio_threshold"]:
            flags.append(FLAG_HIGH_IL_RATIO)

        # GAS_HEAVY: gas > gas_heavy_threshold * |gross_pnl|
        if abs(gross_pnl_usd) > 0:
            gas_ratio = gas_costs_usd / abs(gross_pnl_usd)
        else:
            gas_ratio = 1.0 if gas_costs_usd > 0 else 0.0
        if gas_ratio > cfg["gas_heavy_threshold"]:
            flags.append(FLAG_GAS_HEAVY)

        # REWARD_DEPENDENT: rewards > fees
        if rewards_earned_usd > fees_earned_usd:
            flags.append(FLAG_REWARD_DEPENDENT)

        # LONG_TERM_HOLD
        if days_held >= cfg["long_term_days"]:
            flags.append(FLAG_LONG_TERM_HOLD)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_aggregates(results: list[dict]) -> dict:
        if not results:
            return {
                "most_profitable": None,
                "least_profitable": None,
                "total_net_pnl_usd": 0.0,
                "average_total_apy": 0.0,
                "excellent_count": 0,
                "total_positions": 0,
            }

        sorted_by_apy = sorted(results, key=lambda r: r["total_apy_pct"], reverse=True)
        most_profitable = f"{sorted_by_apy[0]['protocol']}:{sorted_by_apy[0]['pair']}"
        least_profitable = f"{sorted_by_apy[-1]['protocol']}:{sorted_by_apy[-1]['pair']}"
        total_net_pnl_usd = sum(r["net_pnl_usd"] for r in results)
        average_total_apy = sum(r["total_apy_pct"] for r in results) / len(results)
        excellent_count = sum(1 for r in results if r["label"] == LABEL_EXCELLENT)

        return {
            "most_profitable": most_profitable,
            "least_profitable": least_profitable,
            "total_net_pnl_usd": round(total_net_pnl_usd, 4),
            "average_total_apy": round(average_total_apy, 4),
            "excellent_count": excellent_count,
            "total_positions": len(results),
        }

    # ------------------------------------------------------------------
    # Config merge
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_config(config: dict) -> dict:
        return {
            "excellent_apy": float(config.get("excellent_apy", _EXCELLENT_APY)),
            "good_apy": float(config.get("good_apy", _GOOD_APY)),
            "il_ratio_threshold": float(config.get("il_ratio_threshold", _HIGH_IL_RATIO_THRESHOLD)),
            "gas_heavy_threshold": float(config.get("gas_heavy_threshold", _GAS_HEAVY_THRESHOLD)),
            "long_term_days": float(config.get("long_term_days", _LONG_TERM_DAYS)),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def write_log(self, output: dict) -> Path:
        """Append ``output`` to ring-buffer log, capped at _RING_CAP entries."""
        log_path = self._data_dir / _LOG_FILENAME
        try:
            with open(log_path) as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append(output)
        if len(log) > _RING_CAP:
            log = log[-_RING_CAP:]

        self._atomic_write(log_path, log)
        return log_path

    @staticmethod
    def _atomic_write(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_positions() -> list[dict]:
    return [
        {
            "protocol": "Uniswap V3",
            "pair": "ETH/USDC",
            "entry_value_usd": 10_000,
            "current_value_usd": 9_800,
            "fees_earned_usd": 800,
            "rewards_earned_usd": 200,
            "il_loss_usd": 300,
            "gas_costs_usd": 50,
            "days_held": 90,
            "entry_price_ratio": 1.0,
            "current_price_ratio": 1.05,
            "benchmark_hodl_value_usd": 10_500,
        },
        {
            "protocol": "Curve",
            "pair": "USDC/USDT/DAI",
            "entry_value_usd": 50_000,
            "current_value_usd": 50_200,
            "fees_earned_usd": 3_000,
            "rewards_earned_usd": 500,
            "il_loss_usd": 100,
            "gas_costs_usd": 80,
            "days_held": 200,
            "entry_price_ratio": 1.0,
            "current_price_ratio": 1.0,
            "benchmark_hodl_value_usd": 50_200,
        },
    ]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run_mode = "--run" in args

    data_dir: Path | None = None
    if "--data-dir" in args:
        idx = args.index("--data-dir")
        if idx + 1 < len(args):
            data_dir = Path(args[idx + 1])

    tracker = ProtocolLiquidityProviderProfitabilityTracker(data_dir=data_dir)
    result = tracker.track(_sample_positions())
    print(json.dumps(result, indent=2))

    if run_mode:
        path = tracker.write_log(result)
        print(f"\n[MP-951] Log written → {path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
