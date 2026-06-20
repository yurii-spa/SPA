"""
MP-972 DeFiYieldTokenizationAnalyzer
=====================================
Advisory-only, read-only analytics module.
Analyzes positions in yield tokenization protocols (Pendle, Spectra, Element).

Position fields:
    protocol, asset, maturity_date_days, principal_token_price_pct,
    yield_token_price_usd, implied_fixed_apy_pct, current_variable_apy_pct,
    pt_amount, yt_amount, notional_usd, days_to_maturity,
    secondary_market_liquidity_usd

Computed per position:
    pt_discount_pct             = 100 - principal_token_price_pct
    fixed_vs_variable_spread_pct = implied_fixed_apy_pct - current_variable_apy_pct
    yt_implied_leverage         = notional_usd / (yt_price * yt_amount)
    break_even_variable_apy     = implied_fixed_apy_pct (variable APY at which YT = 0)
    time_value_per_day_usd      = (discount_pct/100 * notional) / days

Labels: FIXED_RATE_ADVANTAGE | AT_PAR | VARIABLE_ADVANTAGE | DEEP_DISCOUNT | MATURED
Flags:  HIGH_YT_LEVERAGE | APPROACHING_MATURITY | ILLIQUID_SECONDARY |
        FIXED_LOCKS_IN_PREMIUM | UNDERWATER_YT

Output file: data/yield_tokenization_log.json (ring-buffer cap 100)
Pure Python stdlib only. Atomic writes via tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ── Labels ──────────────────────────────────────────────────────────────────
LABEL_FIXED_RATE_ADVANTAGE = "FIXED_RATE_ADVANTAGE"   # implied_fixed > variable + 2%
LABEL_AT_PAR               = "AT_PAR"                 # spread within ±2%
LABEL_VARIABLE_ADVANTAGE   = "VARIABLE_ADVANTAGE"     # variable > implied_fixed + 2%
LABEL_DEEP_DISCOUNT        = "DEEP_DISCOUNT"          # pt_discount >= 20%
LABEL_MATURED              = "MATURED"                # days_to_maturity <= 0

# ── Flags ────────────────────────────────────────────────────────────────────
FLAG_HIGH_YT_LEVERAGE        = "HIGH_YT_LEVERAGE"        # leverage > 10x
FLAG_APPROACHING_MATURITY    = "APPROACHING_MATURITY"    # 0 < days < 30
FLAG_ILLIQUID_SECONDARY      = "ILLIQUID_SECONDARY"      # liquidity < $100 K
FLAG_FIXED_LOCKS_IN_PREMIUM  = "FIXED_LOCKS_IN_PREMIUM"  # spread > 3%
FLAG_UNDERWATER_YT           = "UNDERWATER_YT"           # break_even > variable * 1.5

_RING_CAP = 100
_DEFAULT_LOG = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "yield_tokenization_log.json"
    )
)


# ──────────────────────────────────────────────────────────────────────────────
# Pure computation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _pt_discount_pct(principal_token_price_pct: float) -> float:
    """100 − PT price (as % of par). Positive means trading below par."""
    return 100.0 - principal_token_price_pct


def _fixed_vs_variable_spread(
    implied_fixed_apy_pct: float, current_variable_apy_pct: float
) -> float:
    """implied_fixed_apy_pct − current_variable_apy_pct."""
    return implied_fixed_apy_pct - current_variable_apy_pct


def _yt_implied_leverage(
    notional_usd: float, yt_price_usd: float, yt_amount: float
) -> float:
    """
    notional_usd / (yt_price_usd × yt_amount).
    Returns 0.0 when denominator ≤ 0.
    """
    denom = yt_price_usd * yt_amount
    if denom <= 0.0:
        return 0.0
    return notional_usd / denom


def _break_even_variable_apy(
    implied_fixed_apy_pct: float, days_to_maturity: int
) -> float:
    """
    Variable APY at which YT = 0 (break-even for YT holder).
    Equals implied_fixed_apy_pct — the rate the variable must sustain for
    the YT position to break even. Returns 0.0 for matured positions.
    """
    if days_to_maturity <= 0:
        return 0.0
    return implied_fixed_apy_pct


def _time_value_per_day(
    pt_discount_pct: float, notional_usd: float, days_to_maturity: int
) -> float:
    """
    (pt_discount_pct / 100 × notional_usd) / days_to_maturity.
    Returns 0.0 when days_to_maturity ≤ 0.
    """
    if days_to_maturity <= 0:
        return 0.0
    discount_usd = (pt_discount_pct / 100.0) * notional_usd
    return discount_usd / days_to_maturity


def _classify_label(
    implied_fixed_apy_pct: float,
    current_variable_apy_pct: float,
    pt_disc: float,
    days_to_maturity: int,
) -> str:
    """Assign a position label based on market conditions."""
    if days_to_maturity <= 0:
        return LABEL_MATURED
    if pt_disc >= 20.0:
        return LABEL_DEEP_DISCOUNT
    spread = implied_fixed_apy_pct - current_variable_apy_pct
    if spread > 2.0:
        return LABEL_FIXED_RATE_ADVANTAGE
    if spread < -2.0:
        return LABEL_VARIABLE_ADVANTAGE
    return LABEL_AT_PAR


def _build_flags(
    yt_leverage: float,
    days_to_maturity: int,
    secondary_liquidity: float,
    spread: float,
    break_even: float,
    current_variable: float,
) -> list:
    """Return list of flag strings for a position."""
    flags = []
    if yt_leverage > 10.0:
        flags.append(FLAG_HIGH_YT_LEVERAGE)
    if 0 < days_to_maturity < 30:
        flags.append(FLAG_APPROACHING_MATURITY)
    if secondary_liquidity < 100_000.0:
        flags.append(FLAG_ILLIQUID_SECONDARY)
    if spread > 3.0:
        flags.append(FLAG_FIXED_LOCKS_IN_PREMIUM)
    if current_variable > 0.0 and break_even > current_variable * 1.5:
        flags.append(FLAG_UNDERWATER_YT)
    return flags


# ──────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_yt_log_path(data_dir: Optional[str] = None) -> str:
    if data_dir:
        return os.path.join(data_dir, "yield_tokenization_log.json")
    return _DEFAULT_LOG


def _atomic_write_yt(path: str, obj) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    atomic_save(obj, str(path))
def _load_yt_log(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


# ──────────────────────────────────────────────────────────────────────────────
# Main class
# ──────────────────────────────────────────────────────────────────────────────

class DeFiYieldTokenizationAnalyzer:
    """
    Analyzes positions in yield tokenization protocols (Pendle, Spectra, Element).
    Advisory-only — never mutates allocator / risk / execution state.
    """

    def analyze(self, positions: list, config: dict = None) -> dict:
        """
        Analyze a list of yield tokenization positions.

        Parameters
        ----------
        positions : list of dict
            Required keys per position:
                protocol, asset, maturity_date_days, principal_token_price_pct,
                yield_token_price_usd, implied_fixed_apy_pct,
                current_variable_apy_pct, pt_amount, yt_amount, notional_usd,
                days_to_maturity, secondary_market_liquidity_usd
        config : dict, optional
            Reserved for future configuration overrides.

        Returns
        -------
        dict
            Keys: positions, best_fixed_rate, highest_yt_leverage,
                  total_notional_usd, fixed_rate_advantage_count,
                  approaching_maturity_count, timestamp
        """
        if config is None:
            config = {}

        analyzed = []
        for pos in positions:
            protocol  = str(pos.get("protocol", "unknown"))
            asset     = str(pos.get("asset", "unknown"))
            pt_price  = float(pos.get("principal_token_price_pct", 100.0))
            yt_price  = float(pos.get("yield_token_price_usd", 0.0))
            implied_f = float(pos.get("implied_fixed_apy_pct", 0.0))
            variable  = float(pos.get("current_variable_apy_pct", 0.0))
            pt_amount = float(pos.get("pt_amount", 0.0))
            yt_amount = float(pos.get("yt_amount", 0.0))
            notional  = float(pos.get("notional_usd", 0.0))
            days      = int(pos.get("days_to_maturity", 0))
            liquidity = float(pos.get("secondary_market_liquidity_usd", 0.0))

            disc     = _pt_discount_pct(pt_price)
            spread   = _fixed_vs_variable_spread(implied_f, variable)
            lev      = _yt_implied_leverage(notional, yt_price, yt_amount)
            bk_even  = _break_even_variable_apy(implied_f, days)
            tv_day   = _time_value_per_day(disc, notional, days)
            label    = _classify_label(implied_f, variable, disc, days)
            flags    = _build_flags(lev, days, liquidity, spread, bk_even, variable)

            analyzed.append({
                "protocol":                      protocol,
                "asset":                         asset,
                "days_to_maturity":              days,
                "pt_discount_pct":               disc,
                "fixed_vs_variable_spread_pct":  spread,
                "yt_implied_leverage":           lev,
                "break_even_variable_apy":       bk_even,
                "time_value_per_day_usd":        tv_day,
                "label":                         label,
                "flags":                         flags,
                "notional_usd":                  notional,
                "implied_fixed_apy_pct":         implied_f,
                "current_variable_apy_pct":      variable,
            })

        # ── Aggregates ────────────────────────────────────────────────────────
        if analyzed:
            best_fixed  = max(p["implied_fixed_apy_pct"] for p in analyzed)
            high_lev    = max(p["yt_implied_leverage"] for p in analyzed)
            total_not   = sum(p["notional_usd"] for p in analyzed)
            fixed_cnt   = sum(
                1 for p in analyzed if p["label"] == LABEL_FIXED_RATE_ADVANTAGE
            )
            appr_cnt    = sum(
                1 for p in analyzed if FLAG_APPROACHING_MATURITY in p["flags"]
            )
        else:
            best_fixed  = 0.0
            high_lev    = 0.0
            total_not   = 0.0
            fixed_cnt   = 0
            appr_cnt    = 0

        return {
            "positions":                  analyzed,
            "best_fixed_rate":            best_fixed,
            "highest_yt_leverage":        high_lev,
            "total_notional_usd":         total_not,
            "fixed_rate_advantage_count": fixed_cnt,
            "approaching_maturity_count": appr_cnt,
            "timestamp":                  time.time(),
        }

    def run(
        self,
        positions: list,
        config: dict = None,
        data_dir: Optional[str] = None,
    ) -> dict:
        """Analyze and persist result to ring-buffer log (cap 100)."""
        result = self.analyze(positions, config)
        path = _resolve_yt_log_path(data_dir)
        log = _load_yt_log(path)
        log.append(result)
        if len(log) > _RING_CAP:
            log = log[-_RING_CAP:]
        _atomic_write_yt(path, log)
        return result


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience wrappers
# ──────────────────────────────────────────────────────────────────────────────

_default_analyzer = DeFiYieldTokenizationAnalyzer()


def analyze(positions: list, config: dict = None) -> dict:
    """Module-level shortcut for DeFiYieldTokenizationAnalyzer().analyze()."""
    return _default_analyzer.analyze(positions, config)


def run(positions: list, config: dict = None, data_dir: Optional[str] = None) -> dict:
    """Module-level shortcut for DeFiYieldTokenizationAnalyzer().run()."""
    return _default_analyzer.run(positions, config, data_dir)


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="DeFiYieldTokenizationAnalyzer (MP-972)"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Run analysis, print JSON, no write (default)"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Run analysis + persist to ring-buffer log"
    )
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    demo_positions = [
        {
            "protocol": "Pendle",
            "asset": "stETH",
            "maturity_date_days": 180,
            "principal_token_price_pct": 95.0,
            "yield_token_price_usd": 0.08,
            "implied_fixed_apy_pct": 10.6,
            "current_variable_apy_pct": 4.5,
            "pt_amount": 100_000,
            "yt_amount": 100_000,
            "notional_usd": 95_000,
            "days_to_maturity": 180,
            "secondary_market_liquidity_usd": 5_000_000,
        },
        {
            "protocol": "Spectra",
            "asset": "USDC",
            "maturity_date_days": 25,
            "principal_token_price_pct": 99.0,
            "yield_token_price_usd": 0.005,
            "implied_fixed_apy_pct": 7.3,
            "current_variable_apy_pct": 5.0,
            "pt_amount": 50_000,
            "yt_amount": 50_000,
            "notional_usd": 49_500,
            "days_to_maturity": 25,
            "secondary_market_liquidity_usd": 80_000,
        },
    ]

    if args.run:
        result = run(demo_positions, data_dir=args.data_dir)
        print(json.dumps(result, indent=2, default=str))
    else:
        result = analyze(demo_positions)
        print(json.dumps(result, indent=2, default=str))
