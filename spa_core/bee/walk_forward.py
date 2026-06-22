"""
BEE S9.8 — Walk-Forward Backtest
=================================
EPIC-9 / ADR-043

LLM_FORBIDDEN: этот модуль не вызывает и не использует никаких LLM-вызовов.
Implements walk-forward validation: train 2022–2024, test 2025.

Дизайн:
  - Train: fit normal distribution (mean, std) on 2022-2024 APY data
  - Test: compute % of 2025 APY values within 80%/95% CI of trained dist
  - KS-test: compare 2025 APY vs theoretical normal(mean, std)
  - scipy используется если установлен; иначе stdlib KS approximation
  - Offline fallback: DeFiLlama hardcoded fallback data
  - Атомарная запись в data/bee/walk_forward_result.json

stdlib + optional scipy. No external dependencies.
"""
# LLM_FORBIDDEN
import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_BEE_DEFAULT = _PROJECT_ROOT / "data" / "bee"
_OUTPUT_FILENAME = "walk_forward_result.json"

TRAIN_START = "2022-01-01"
TRAIN_END = "2024-12-31"
TEST_START = "2025-01-01"
TEST_END = "2025-12-31"

# Optional scipy
try:
    from scipy import stats as _scipy_stats  # type: ignore
    _HAS_SCIPY = True
except ImportError:
    _scipy_stats = None
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
#  Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardResult:
    """
    Result of walk-forward backtest validation.
    LLM_FORBIDDEN.
    """
    train_period: Tuple[str, str]    # ("2022-01-01", "2024-12-31")
    test_period: Tuple[str, str]     # ("2025-01-01", "2025-12-31")
    train_n: int                      # number of training data points
    test_n: int                       # number of test data points
    pct_in_ci_80: float              # fraction of test points in 80% CI
    pct_in_ci_95: float              # fraction of test points in 95% CI
    ks_statistic: Optional[float]    # KS statistic (vs normal fit)
    ks_pvalue: Optional[float]       # KS p-value
    verdict: str                     # "validated" | "partially_validated" | "not_validated" | "insufficient_data"
    data_source: str                 # "defillama_real" | "fallback" | "modeled_fallback"
    train_mean: float = 0.0          # fitted mean APY
    train_std: float = 0.0           # fitted std APY
    notes: str = ""                  # optional notes


# ---------------------------------------------------------------------------
#  KS helpers (stdlib)
# ---------------------------------------------------------------------------

def _normal_cdf(x: float, mu: float, sigma: float) -> float:
    """Normal CDF via math.erf. LLM_FORBIDDEN."""
    if sigma <= 0:
        return 0.0 if x < mu else 1.0
    z = (x - mu) / (sigma * math.sqrt(2))
    return 0.5 * (1.0 + math.erf(z))


def _ks_stat_vs_normal(data: List[float], mu: float, sigma: float) -> float:
    """KS statistic D = max|F_emp - F_norm|. Stdlib only. LLM_FORBIDDEN."""
    if not data or sigma <= 0:
        return 0.0
    n = len(data)
    sdata = sorted(data)
    ks = 0.0
    for i, x in enumerate(sdata):
        f_theor = _normal_cdf(x, mu, sigma)
        ks = max(ks, abs((i + 1) / n - f_theor), abs(i / n - f_theor))
    return ks


def _ks_pvalue_approx(ks_stat: float, n: int) -> float:
    """Kolmogorov distribution p-value approximation. LLM_FORBIDDEN."""
    if ks_stat <= 0 or n <= 0:
        return 1.0
    x = ks_stat * (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n))
    pval = 0.0
    for k in range(1, 50):
        sign = (-1) ** (k - 1)
        term = sign * math.exp(-2.0 * k * k * x * x)
        pval += term
        if abs(term) < 1e-10:
            break
    return max(0.0, min(1.0, 2.0 * pval))


def _run_ks_test(
    data: List[float],
    mu: float,
    sigma: float,
) -> Tuple[Optional[float], Optional[float]]:
    """Run KS test, return (ks_statistic, ks_pvalue). LLM_FORBIDDEN."""
    if len(data) < 2 or sigma <= 0:
        return None, None

    if _HAS_SCIPY and _scipy_stats is not None:
        try:
            stat, pval = _scipy_stats.kstest(data, "norm", args=(mu, sigma))
            return round(float(stat), 6), round(float(pval), 6)
        except Exception:
            pass

    # stdlib fallback
    stat = _ks_stat_vs_normal(data, mu, sigma)
    pval = _ks_pvalue_approx(stat, len(data))
    return round(stat, 6), round(pval, 6)


# ---------------------------------------------------------------------------
#  Data helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD string. Returns None on error."""
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _split_train_test(
    apy_series: List[Dict],
    train_start: str = TRAIN_START,
    train_end: str = TRAIN_END,
    test_start: str = TEST_START,
    test_end: str = TEST_END,
) -> Tuple[List[float], List[float]]:
    """
    Split APY series into train and test lists.
    Returns (train_apys, test_apys) as decimal float lists.
    LLM_FORBIDDEN.
    """
    train_start_dt = _parse_date(train_start)
    train_end_dt = _parse_date(train_end)
    test_start_dt = _parse_date(test_start)
    test_end_dt = _parse_date(test_end)

    train: List[float] = []
    test: List[float] = []

    for entry in apy_series:
        date_str = entry.get("date", "")
        apy_raw = entry.get("apy")
        if not date_str or apy_raw is None:
            continue
        dt = _parse_date(date_str)
        if dt is None:
            continue
        apy = float(apy_raw)
        if apy > 1.0:
            apy /= 100.0  # normalise % → decimal

        if train_start_dt and train_end_dt and train_start_dt <= dt <= train_end_dt:
            train.append(apy)
        elif test_start_dt and test_end_dt and test_start_dt <= dt <= test_end_dt:
            test.append(apy)

    return train, test


def _fit_normal(data: List[float]) -> Tuple[float, float]:
    """Fit normal distribution (mean, std) to data. LLM_FORBIDDEN."""
    if not data:
        return 0.0, 0.0
    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n
    std = max(math.sqrt(variance), 1e-8)
    return mean, std


def _pct_in_ci(test_data: List[float], mean: float, std: float, z: float) -> float:
    """Fraction of test_data values within [mean - z*std, mean + z*std]."""
    if not test_data:
        return 0.0
    lo = mean - z * std
    hi = mean + z * std
    inside = sum(1 for x in test_data if lo <= x <= hi)
    return inside / len(test_data)


def _aggregate_series(pool_data_dict: Dict) -> List[Dict]:
    """Aggregate APY series across all pools (deduplicated by date, averaged)."""
    by_date: Dict[str, List[float]] = {}
    for pool_data in pool_data_dict.values():
        if not isinstance(pool_data, dict):
            continue
        for entry in pool_data.get("apy_series", []):
            d = entry.get("date", "")
            a = entry.get("apy")
            if d and a is not None:
                by_date.setdefault(d, []).append(float(a))
    # Average across pools per date
    return [{"date": d, "apy": sum(v) / len(v)} for d, v in sorted(by_date.items())]


def _determine_data_source(pool_data_dict: Dict) -> str:
    """Determine overall data_source from pool results."""
    sources = {
        v.get("data_source", "fallback")
        for v in pool_data_dict.values()
        if isinstance(v, dict)
    }
    if "defillama_real" in sources:
        return "defillama_real"
    if "cached" in sources:
        return "defillama_real"  # cached real data
    return "fallback"


def _determine_verdict(
    test_n: int,
    train_n: int,
    pct_in_ci_80: float,
    data_source: str,
) -> str:
    """
    Verdict logic:
      - insufficient_data: test_n < 3 or train_n < 5
      - validated: pct_in_ci_80 >= 0.70
      - partially_validated: pct_in_ci_80 >= 0.40
      - not_validated: pct_in_ci_80 < 0.40
    LLM_FORBIDDEN.
    """
    if test_n < 3 or train_n < 5:
        return "insufficient_data"
    if data_source in ("modeled_fallback",):
        # Extra note — lower confidence but still classifiable
        pass
    if pct_in_ci_80 >= 0.70:
        return "validated"
    elif pct_in_ci_80 >= 0.40:
        return "partially_validated"
    else:
        return "not_validated"


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def run_walk_forward(
    data_dir: str = "data",
    output_filename: str = _OUTPUT_FILENAME,
) -> "WalkForwardResult":
    """
    Run walk-forward backtest: train 2022–2024, test 2025.

    LLM_FORBIDDEN.
    Атомарная запись в data/bee/walk_forward_result.json.

    Args:
        data_dir: project data directory (default "data"; absolute or relative to cwd)
        output_filename: name of output JSON file

    Returns:
        WalkForwardResult dataclass
    """
    # LLM_FORBIDDEN
    data_path = Path(data_dir)
    bee_dir = data_path / "bee"
    bee_dir.mkdir(parents=True, exist_ok=True)
    output_path = bee_dir / output_filename

    # --- Load APY data ---
    pool_data: Dict = {}
    data_source_label = "modeled_fallback"

    try:
        from spa_core.bee.defillama_feed import fetch_apy_history, FALLBACK_APY_DATA, _compute_stats
        pool_data = fetch_apy_history(data_dir=bee_dir)
        # Determine actual data source
        data_source_label = _determine_data_source(pool_data)
    except Exception:
        pass

    if not pool_data:
        # Load from defillama_feed FALLBACK_APY_DATA directly
        try:
            from spa_core.bee.defillama_feed import FALLBACK_APY_DATA, _compute_stats
            for pid, raw in FALLBACK_APY_DATA.items():
                stats = _compute_stats(raw["apy_series"])
                pool_data[pid] = {
                    "apy_series": raw["apy_series"],
                    "data_source": "fallback",
                    **stats,
                }
            data_source_label = "modeled_fallback"
        except Exception:
            # Absolute last resort: empty → insufficient_data
            pool_data = {}

    # Aggregate and split
    if pool_data:
        apy_series = _aggregate_series(pool_data)
    else:
        apy_series = []

    train_apys, test_apys = _split_train_test(apy_series)

    # --- Fit & validate ---
    if len(train_apys) < 5 or len(test_apys) < 3:
        result = WalkForwardResult(
            train_period=(TRAIN_START, TRAIN_END),
            test_period=(TEST_START, TEST_END),
            train_n=len(train_apys),
            test_n=len(test_apys),
            pct_in_ci_80=0.0,
            pct_in_ci_95=0.0,
            ks_statistic=None,
            ks_pvalue=None,
            verdict="insufficient_data",
            data_source=data_source_label,
            notes="Insufficient data for walk-forward validation",
        )
    else:
        mean, std = _fit_normal(train_apys)
        pct_80 = _pct_in_ci(test_apys, mean, std, 1.282)   # 80% CI
        pct_95 = _pct_in_ci(test_apys, mean, std, 1.960)   # 95% CI

        ks_stat, ks_pval = _run_ks_test(test_apys, mean, std)
        verdict = _determine_verdict(len(test_apys), len(train_apys), pct_80, data_source_label)

        result = WalkForwardResult(
            train_period=(TRAIN_START, TRAIN_END),
            test_period=(TEST_START, TEST_END),
            train_n=len(train_apys),
            test_n=len(test_apys),
            pct_in_ci_80=round(pct_80, 4),
            pct_in_ci_95=round(pct_95, 4),
            ks_statistic=ks_stat,
            ks_pvalue=ks_pval,
            verdict=verdict,
            data_source=data_source_label,
            train_mean=round(mean, 6),
            train_std=round(std, 6),
            notes=(
                f"Walk-forward: train=[{TRAIN_START}..{TRAIN_END}] n={len(train_apys)}, "
                f"test=[{TEST_START}..{TEST_END}] n={len(test_apys)}, "
                f"data_source={data_source_label}"
            ),
        )

    # --- Atomic write ---
    output_dict = {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "LLM_FORBIDDEN": True,
        **asdict(result),
    }
    payload = json.dumps(output_dict, indent=2)
    tmp_path = str(output_path) + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(payload)
    os.replace(tmp_path, str(output_path))

    return result
