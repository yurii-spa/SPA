"""
ProtocolTokenBuybackTracker (MP-842)
======================================
Tracks protocol token buyback programs, assessing their sustainability,
impact on token price, and what they signal about protocol revenue health.

Advisory / read-only module — never moves capital, never modifies risk/,
execution/, monitoring/, or allocator/. Pure stdlib, atomic writes.

analyze(protocols, config) -> dict

Output ring-buffer (100 entries): data/token_buyback_log.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — read-only, never touches execution domain.
* Atomic writes: tmp + os.replace.
* Never raises on the happy path; malformed input degrades gracefully.

CLI
---
``python3 -m spa_core.analytics.protocol_token_buyback_tracker --check``
``python3 -m spa_core.analytics.protocol_token_buyback_tracker --run``
``python3 -m spa_core.analytics.protocol_token_buyback_tracker --data-dir PATH``

MP-842.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RING_BUFFER_MAX: int = 100
_DEFAULT_DATA_FILE: str = "token_buyback_log.json"
_DEFAULT_MIN_REVENUE_COVERAGE: float = 0.1

# Sustainability thresholds (revenue_allocation_pct)
_AGGRESSIVE_THRESHOLD: float = 50.0
_MODERATE_THRESHOLD: float = 20.0

# Viability thresholds
_BUYBACK_YIELD_EXCELLENT_THRESHOLD: float = 2.0
_BULLISH_SCORE_THRESHOLD: int = 60

# Sentinel for revenue=0 and buyback>0
_SENTINEL_REVENUE_ALLOC: float = 999.0

# Frequency bonus lookup
_FREQUENCY_BONUS: Dict[str, int] = {
    "CONTINUOUS": 20,
    "WEEKLY": 15,
    "MONTHLY": 10,
    "IRREGULAR": 5,
    "NONE": 0,
}

# Sustainability multiplier lookup
_SUSTAINABILITY_MULTIPLIER: Dict[str, float] = {
    "STRONG": 1.0,
    "MODERATE": 0.8,
    "AGGRESSIVE": 0.6,
    "UNSUSTAINABLE": 0.3,
    "NONE": 0.0,
}

# ---------------------------------------------------------------------------
# Core logic helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce a value to float, returning default on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_bool(val: Any, default: bool = False) -> bool:
    """Coerce a value to bool."""
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    return default


def _compute_buyback_yield(buyback_usd_30d: float, market_cap_usd: float) -> float:
    """Annualised buyback yield as %."""
    if market_cap_usd <= 0:
        return 0.0
    return (buyback_usd_30d * 12.0 / market_cap_usd) * 100.0


def _compute_revenue_allocation(buyback_usd_30d: float,
                                revenue_usd_30d: float) -> float:
    """Buyback as fraction of revenue, expressed as %."""
    if revenue_usd_30d > 0:
        return (buyback_usd_30d / revenue_usd_30d) * 100.0
    if buyback_usd_30d > 0:
        return _SENTINEL_REVENUE_ALLOC  # spending with no revenue
    return 0.0


def _compute_sustainability(buyback_usd_30d: float,
                            buyback_frequency: str,
                            revenue_allocation_pct: float,
                            revenue_usd_30d: float) -> str:
    """Determine buyback sustainability tier."""
    if buyback_usd_30d == 0 or buyback_frequency == "NONE":
        return "NONE"
    # sentinel value or raw excess spending
    if revenue_allocation_pct >= _SENTINEL_REVENUE_ALLOC or \
            revenue_allocation_pct > 100.0:
        return "UNSUSTAINABLE"
    if revenue_allocation_pct > _AGGRESSIVE_THRESHOLD:
        return "AGGRESSIVE"
    if revenue_allocation_pct > _MODERATE_THRESHOLD:
        return "MODERATE"
    # <= 20% AND revenue > 0
    if revenue_usd_30d > 0:
        return "STRONG"
    return "UNSUSTAINABLE"


def _compute_price_support_score(buyback_yield_pct: float,
                                 buyback_frequency: str,
                                 tokens_burned: bool,
                                 sustainability: str) -> int:
    """Compute price support score 0-100."""
    base = min(40, int(buyback_yield_pct * 4))
    freq_bonus = _FREQUENCY_BONUS.get(buyback_frequency.upper(), 0)
    burn_bonus = 20 if tokens_burned else 0
    multiplier = _SUSTAINABILITY_MULTIPLIER.get(sustainability, 0.0)
    raw = int((base + freq_bonus + burn_bonus) * multiplier)
    return max(0, min(100, raw))


def _compute_signal(price_support_score: int,
                    sustainability: str,
                    buyback_yield_pct: float,
                    buyback_frequency: str) -> str:
    """Determine signal: BULLISH / NEUTRAL / BEARISH."""
    if sustainability == "UNSUSTAINABLE":
        return "BEARISH"
    if buyback_yield_pct < 1.0 and buyback_frequency == "NONE":
        return "BEARISH"
    if (price_support_score >= _BULLISH_SCORE_THRESHOLD and
            sustainability in ("STRONG", "MODERATE")):
        return "BULLISH"
    return "NEUTRAL"


def _compute_flags(buyback_usd_30d: float,
                   buyback_frequency: str,
                   revenue_allocation_pct: float,
                   tokens_burned: bool,
                   buyback_yield_pct: float) -> List[str]:
    """Build list of advisory flag strings."""
    flags: List[str] = []
    # Revenue coverage exceeded
    if revenue_allocation_pct >= _SENTINEL_REVENUE_ALLOC or \
            revenue_allocation_pct > 100.0:
        flags.append("Buyback spending exceeds revenue")
    # No buyback
    if buyback_frequency == "NONE" or buyback_usd_30d == 0:
        flags.append("No buyback program")
    # Tokens not burned
    if not tokens_burned and buyback_usd_30d > 0:
        flags.append("Tokens not burned — limited supply reduction")
    # Irregular
    if buyback_frequency == "IRREGULAR":
        flags.append("Irregular buybacks — unpredictable support")
    # High yield
    if buyback_yield_pct > 20.0:
        flags.append(
            f"High buyback yield {buyback_yield_pct:.1f}% — check sustainability"
        )
    return flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(protocols: List[Dict], config: Optional[Dict] = None) -> Dict:
    """
    Analyze protocol token buyback programs.

    protocols: list of {
        "name": str,
        "token_symbol": str,
        "buyback_usd_30d": float,
        "revenue_usd_30d": float,
        "token_price_usd": float,
        "market_cap_usd": float,
        "circulating_supply": float,
        "buyback_frequency": str,
        "tokens_burned": bool
    }
    config: {
        "min_revenue_coverage": float  # default 0.1
    }

    Returns analysis dict with per-protocol assessments and summary.
    """
    cfg = config or {}
    _min_rev_cov = _safe_float(
        cfg.get("min_revenue_coverage"), _DEFAULT_MIN_REVENUE_COVERAGE
    )

    protocol_results: List[Dict] = []
    total_yield_sum: float = 0.0
    total_annual_buyback: float = 0.0

    highest_yield_name: Optional[str] = None
    highest_yield_val: float = -1.0

    strong_protocols: List[Dict] = []  # for most_sustainable

    for proto in (protocols or []):
        name = str(proto.get("name", ""))
        token_symbol = str(proto.get("token_symbol", ""))
        buyback_30d = _safe_float(proto.get("buyback_usd_30d"), 0.0)
        revenue_30d = _safe_float(proto.get("revenue_usd_30d"), 0.0)
        _token_price = _safe_float(proto.get("token_price_usd"), 0.0)
        market_cap = _safe_float(proto.get("market_cap_usd"), 0.0)
        _circ_supply = _safe_float(proto.get("circulating_supply"), 0.0)
        freq = str(proto.get("buyback_frequency", "NONE")).upper()
        tokens_burned = _safe_bool(proto.get("tokens_burned"), False)

        # Derived metrics
        buyback_yield = _compute_buyback_yield(buyback_30d, market_cap)
        rev_alloc = _compute_revenue_allocation(buyback_30d, revenue_30d)
        sustainability = _compute_sustainability(
            buyback_30d, freq, rev_alloc, revenue_30d
        )
        implied_annual = buyback_30d * 12.0
        score = _compute_price_support_score(
            buyback_yield, freq, tokens_burned, sustainability
        )
        signal = _compute_signal(score, sustainability, buyback_yield, freq)
        flags = _compute_flags(
            buyback_30d, freq, rev_alloc, tokens_burned, buyback_yield
        )

        # Accumulate summary fields
        total_yield_sum += buyback_yield
        total_annual_buyback += implied_annual

        if buyback_yield > highest_yield_val:
            highest_yield_val = buyback_yield
            highest_yield_name = name

        if sustainability == "STRONG":
            strong_protocols.append({"name": name, "revenue": revenue_30d})

        protocol_results.append({
            "name": name,
            "token_symbol": token_symbol,
            "buyback_yield_annualized_pct": buyback_yield,
            "revenue_allocation_pct": rev_alloc,
            "buyback_sustainability": sustainability,
            "implied_annual_buyback_usd": implied_annual,
            "price_support_score": score,
            "signal": signal,
            "flags": flags,
        })

    # Summary
    count = len(protocol_results)
    average_yield = total_yield_sum / count if count > 0 else 0.0

    # most_sustainable: STRONG with highest revenue
    most_sustainable: Optional[str] = None
    if strong_protocols:
        best_strong = max(strong_protocols, key=lambda x: x["revenue"])
        most_sustainable = best_strong["name"]

    # highest_yield: only set if there were protocols
    if count == 0:
        highest_yield_name = None

    return {
        "protocols": protocol_results,
        "highest_yield_buyback": highest_yield_name,
        "most_sustainable": most_sustainable,
        "average_buyback_yield": average_yield,
        "total_implied_annual_buybacks_usd": total_annual_buyback,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _default_data_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "data"


def _load_log(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_log(path: Path, log: List[Dict]) -> None:
    """Atomic write with ring-buffer cap."""
    if len(log) > _RING_BUFFER_MAX:
        log = log[-_RING_BUFFER_MAX:]
    atomic_save(log, str(path))
def run(protocols: List[Dict], config: Optional[Dict] = None,
        data_dir: Optional[str] = None) -> Dict:
    """analyze() + append result to ring-buffer log file."""
    result = analyze(protocols, config)
    dd = Path(data_dir) if data_dir else _default_data_dir()
    dd.mkdir(parents=True, exist_ok=True)
    log_path = dd / _DEFAULT_DATA_FILE
    log = _load_log(log_path)
    log.append(result)
    _save_log(log_path, log)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_protocols() -> List[Dict]:
    """Return a small demo protocol set for --check / --run CLI."""
    return [
        {
            "name": "Aave",
            "token_symbol": "AAVE",
            "buyback_usd_30d": 500_000,
            "revenue_usd_30d": 3_000_000,
            "token_price_usd": 90.0,
            "market_cap_usd": 1_300_000_000,
            "circulating_supply": 14_400_000,
            "buyback_frequency": "WEEKLY",
            "tokens_burned": False,
        },
        {
            "name": "Compound",
            "token_symbol": "COMP",
            "buyback_usd_30d": 200_000,
            "revenue_usd_30d": 800_000,
            "token_price_usd": 55.0,
            "market_cap_usd": 450_000_000,
            "circulating_supply": 8_000_000,
            "buyback_frequency": "MONTHLY",
            "tokens_burned": True,
        },
        {
            "name": "ProtocolX",
            "token_symbol": "PX",
            "buyback_usd_30d": 5_000_000,
            "revenue_usd_30d": 100_000,
            "token_price_usd": 2.0,
            "market_cap_usd": 50_000_000,
            "circulating_supply": 25_000_000,
            "buyback_frequency": "CONTINUOUS",
            "tokens_burned": True,
        },
    ]


def _cli_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="MP-842 ProtocolTokenBuybackTracker"
    )
    parser.add_argument("--check", action="store_true",
                        help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and persist to data/")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory")
    args = parser.parse_args()

    protos = _demo_protocols()
    if args.run:
        result = run(protos, data_dir=args.data_dir)
        print("[MP-842] Result written to data/token_buyback_log.json")
    else:
        result = analyze(protos)
        print("[MP-842] --check mode (no write)")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli_main()
