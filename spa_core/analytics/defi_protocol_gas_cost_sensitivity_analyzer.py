"""
MP-1116 DeFiProtocolGasCostSensitivityAnalyzer
Advisory/read-only analytics module.

Analyzes how sensitive a DeFi position's net returns are to gas price
fluctuations. High-frequency strategies on L1 are extremely sensitive;
L2/passive positions are not.

Inputs:
  strategy_type          (str)  active_lp / passive_vault / lending / farming / staking
  transactions_per_month (int)  number of on-chain interactions per month
  avg_gas_per_tx_gwei    (float) gas units × gas_price_gwei, e.g. 200_000 * 30 gwei
  eth_price_usd          (float) current ETH price in USD
  position_size_usd      (float) position size in USD
  gross_monthly_yield_pct(float) gross monthly yield % before gas drag
  chain                  (str)  ethereum / arbitrum / base / optimism / polygon

Outputs:
  monthly_gas_cost_usd   (float) txs * gas_per_tx * eth_price / 1e9
  annual_gas_cost_usd    (float) monthly_gas_cost_usd * 12
  gas_drag_pct           (float) annual_gas / position * 100
  net_annual_yield_pct   (float) gross_annual - gas_drag
  gas_sensitivity_score  (int)   0-100, 100=extremely sensitive
  gas_label              (str)   GAS_NEGLIGIBLE / LOW_GAS_DRAG / MODERATE_GAS_DRAG
                                 / HIGH_GAS_DRAG / GAS_KILLS_YIELD

Data log: data/gas_cost_sensitivity_log.json (ring-buffer, max 100 entries)
Pure stdlib. No external dependencies.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_CAP = 100

VALID_STRATEGY_TYPES = frozenset({
    "active_lp", "passive_vault", "lending", "farming", "staking"
})
VALID_CHAINS = frozenset({
    "ethereum", "arbitrum", "base", "optimism", "polygon"
})

# Gas drag label thresholds (exclusive upper bound)
# gas_drag_pct < 0.1  → GAS_NEGLIGIBLE
# gas_drag_pct < 0.5  → LOW_GAS_DRAG
# gas_drag_pct < 2.0  → MODERATE_GAS_DRAG
# gas_drag_pct <= 5.0 → HIGH_GAS_DRAG
# gas_drag_pct > 5.0  → GAS_KILLS_YIELD
_DRAG_THRESHOLDS = [
    (0.1,  "GAS_NEGLIGIBLE"),
    (0.5,  "LOW_GAS_DRAG"),
    (2.0,  "MODERATE_GAS_DRAG"),
]
_HIGH_GAS_DRAG_CEILING = 5.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _gas_label(gas_drag_pct: float) -> str:
    """Return gas label for the given gas drag percentage."""
    for threshold, label in _DRAG_THRESHOLDS:
        if gas_drag_pct < threshold:
            return label
    if gas_drag_pct <= _HIGH_GAS_DRAG_CEILING:
        return "HIGH_GAS_DRAG"
    return "GAS_KILLS_YIELD"


def _gas_sensitivity_score(gas_drag_pct: float) -> int:
    """
    Return gas sensitivity score 0-100.
    Linearly scaled: 0% drag → 0, 5% drag → 100. Capped at 100.
    """
    raw = gas_drag_pct / _HIGH_GAS_DRAG_CEILING * 100.0
    return min(100, max(0, int(raw)))


def _atomic_write(path: str, data) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    dir_part = os.path.dirname(path)
    if dir_part:
        os.makedirs(dir_part, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    strategy_type: str,
    transactions_per_month: int,
    avg_gas_per_tx_gwei: float,
    eth_price_usd: float,
    position_size_usd: float,
    gross_monthly_yield_pct: float,
    chain: str = "ethereum",
) -> dict:
    """
    Analyze gas cost sensitivity for a DeFi position.

    Parameters
    ----------
    strategy_type : str
        One of active_lp / passive_vault / lending / farming / staking.
    transactions_per_month : int
        Number of on-chain interactions per month.
    avg_gas_per_tx_gwei : float
        Gas cost per transaction in gwei (gas_units * gas_price_gwei).
        E.g. 200_000 gas units * 30 gwei/unit = 6_000_000 gwei.
    eth_price_usd : float
        Current ETH price in USD.
    position_size_usd : float
        Position size in USD.
    gross_monthly_yield_pct : float
        Gross monthly yield as a percentage (before gas drag).
    chain : str, optional
        Chain name: ethereum / arbitrum / base / optimism / polygon.
        Defaults to "ethereum".

    Returns
    -------
    dict with keys:
        strategy_type, chain, transactions_per_month, avg_gas_per_tx_gwei,
        eth_price_usd, position_size_usd, gross_monthly_yield_pct,
        gross_annual_yield_pct, monthly_gas_cost_usd, annual_gas_cost_usd,
        gas_drag_pct, net_annual_yield_pct, gas_sensitivity_score,
        gas_label, timestamp.
    """
    n_txs = int(transactions_per_month)
    gas_per_tx = float(avg_gas_per_tx_gwei)
    eth_price = float(eth_price_usd)
    pos_size = float(position_size_usd)
    gross_monthly = float(gross_monthly_yield_pct)

    # Core calculations
    monthly_gas_cost_usd = n_txs * gas_per_tx * eth_price / 1_000_000_000.0
    annual_gas_cost_usd = monthly_gas_cost_usd * 12.0
    gross_annual_yield_pct = gross_monthly * 12.0

    if pos_size > 0.0:
        gas_drag_pct = annual_gas_cost_usd / pos_size * 100.0
    else:
        gas_drag_pct = 0.0

    net_annual_yield_pct = gross_annual_yield_pct - gas_drag_pct

    label = _gas_label(gas_drag_pct)
    score = _gas_sensitivity_score(gas_drag_pct)

    return {
        "strategy_type": str(strategy_type),
        "chain": str(chain),
        "transactions_per_month": n_txs,
        "avg_gas_per_tx_gwei": gas_per_tx,
        "eth_price_usd": eth_price,
        "position_size_usd": pos_size,
        "gross_monthly_yield_pct": gross_monthly,
        "gross_annual_yield_pct": gross_annual_yield_pct,
        "monthly_gas_cost_usd": monthly_gas_cost_usd,
        "annual_gas_cost_usd": annual_gas_cost_usd,
        "gas_drag_pct": gas_drag_pct,
        "net_annual_yield_pct": net_annual_yield_pct,
        "gas_sensitivity_score": score,
        "gas_label": label,
        "timestamp": time.time(),
    }


def log_result(
    result: dict,
    log_path: str = "data/gas_cost_sensitivity_log.json",
) -> None:
    """
    Append a summary entry to the ring-buffer log.
    Ring-buffer capped at _LOG_CAP (100) entries.
    Atomic write: tmp + os.replace.
    """
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entry = {
        "timestamp": result.get("timestamp", time.time()),
        "strategy_type": result.get("strategy_type"),
        "chain": result.get("chain"),
        "transactions_per_month": result.get("transactions_per_month"),
        "position_size_usd": result.get("position_size_usd"),
        "gross_annual_yield_pct": result.get("gross_annual_yield_pct"),
        "annual_gas_cost_usd": result.get("annual_gas_cost_usd"),
        "gas_drag_pct": result.get("gas_drag_pct"),
        "net_annual_yield_pct": result.get("net_annual_yield_pct"),
        "gas_sensitivity_score": result.get("gas_sensitivity_score"),
        "gas_label": result.get("gas_label"),
    }

    entries.append(entry)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1116 DeFiProtocolGasCostSensitivityAnalyzer"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Compute and print result; do NOT write to log (default behaviour)"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Compute result AND write to log"
    )
    parser.add_argument(
        "--data-dir", default="data",
        help="Directory for JSON state files (default: data)"
    )
    args = parser.parse_args()

    # Demo: active LP on Ethereum — high gas sensitivity example
    demo = analyze(
        strategy_type="active_lp",
        transactions_per_month=60,
        avg_gas_per_tx_gwei=6_000_000.0,   # 200_000 gas * 30 gwei
        eth_price_usd=3_500.0,
        position_size_usd=50_000.0,
        gross_monthly_yield_pct=2.0,
        chain="ethereum",
    )

    import json as _json
    print(_json.dumps(
        {k: v for k, v in demo.items() if k != "timestamp"},
        indent=2,
    ))

    if args.run:
        log_path = os.path.join(args.data_dir, "gas_cost_sensitivity_log.json")
        log_result(demo, log_path)
        print(f"[MP-1116] Result logged → {log_path}")


if __name__ == "__main__":
    _cli()
