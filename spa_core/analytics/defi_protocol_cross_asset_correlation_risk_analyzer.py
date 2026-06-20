"""
MP-1012: DeFiProtocolCrossAssetCorrelationRiskAnalyzer
=======================================================
Advisory-only analytics module.
Analyzes cross-asset correlation risk in DeFi portfolios:
concentrated exposure to correlated assets (ETH-correlated, same-chain, same-protocol).

Computes: portfolio_volatility_pct, effective_diversification_ratio,
herfindahl_concentration, chain_concentration_score, protocol_concentration_score,
correlation_risk_score.

Risk labels: WELL_DIVERSIFIED / ADEQUATELY_DIVERSIFIED / MODERATELY_CONCENTRATED /
HIGHLY_CONCENTRATED / DANGEROUS_CONCENTRATION

Flags: ETH_CORRELATED_DOMINANCE, SINGLE_CHAIN_RISK, PROTOCOL_CONCENTRATION,
STABLECOIN_BUFFER, EFFECTIVE_DIVERSIFICATION, EXTREME_CONCENTRATION

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/cross_asset_correlation_log.json
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
import math
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "cross_asset_correlation_log.json",
)
LOG_MAX_ENTRIES = 100

# Risk label thresholds
WELL_DIVERSIFIED_DIV_RATIO = 1.8
ADEQUATELY_DIVERSIFIED_DIV_RATIO = 1.4
MODERATELY_CONCENTRATED_DIV_RATIO = 1.1

HIGHLY_CONCENTRATED_HHI = 3000
HIGHLY_CONCENTRATED_CHAIN = 5000
DANGEROUS_SINGLE_POSITION = 50.0
DANGEROUS_CORR_RISK = 80.0

# Flag thresholds
ETH_CORRELATED_THRESHOLD = 70.0
SINGLE_CHAIN_THRESHOLD = 70.0
PROTOCOL_CONCENTRATION_THRESHOLD = 40.0
STABLECOIN_BUFFER_THRESHOLD = 20.0
EFFECTIVE_DIVERSIFICATION_THRESHOLD = 1.5
EXTREME_CONCENTRATION_THRESHOLD = 40.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_portfolio(portfolio: dict, idx: int) -> None:
    """Validate required fields in a portfolio dict."""
    required = {
        "name",
        "positions",
        "protocol_exposure",
        "chain_exposure",
        "stablecoin_pct",
        "eth_correlated_pct",
    }
    missing = required - set(portfolio.keys())
    if missing:
        raise ValueError(
            f"Portfolio {idx} ('{portfolio.get('name', '?')}') missing fields: {missing}"
        )
    if not isinstance(portfolio["positions"], list) or len(portfolio["positions"]) == 0:
        raise ValueError(f"Portfolio {idx}: 'positions' must be a non-empty list")
    for j, pos in enumerate(portfolio["positions"]):
        _validate_position(pos, idx, j)


def _validate_position(pos: dict, p_idx: int, pos_idx: int) -> None:
    """Validate a single position dict."""
    required = {"asset", "weight_pct", "volatility_30d_pct", "correlation_matrix_row"}
    missing = required - set(pos.keys())
    if missing:
        raise ValueError(
            f"Portfolio {p_idx}, position {pos_idx} missing fields: {missing}"
        )
    if not isinstance(pos["correlation_matrix_row"], dict):
        raise ValueError(
            f"Portfolio {p_idx}, position {pos_idx}: correlation_matrix_row must be a dict"
        )


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _compute_portfolio_volatility(positions: list) -> float:
    """
    Compute portfolio volatility (pct) using weighted sum with correlations.
    σ_p = sqrt(Σ_i Σ_j w_i * w_j * σ_i * σ_j * ρ_ij)
    """
    n = len(positions)
    variance = 0.0
    for i in range(n):
        w_i = positions[i]["weight_pct"] / 100.0
        vol_i = positions[i]["volatility_30d_pct"] / 100.0
        asset_i = positions[i]["asset"]
        corr_row = positions[i]["correlation_matrix_row"]
        for j in range(n):
            w_j = positions[j]["weight_pct"] / 100.0
            vol_j = positions[j]["volatility_30d_pct"] / 100.0
            asset_j = positions[j]["asset"]
            if i == j:
                rho = 1.0
            else:
                # Try to get correlation from matrix; default to 0 if missing
                rho = float(corr_row.get(asset_j, 0.0))
            variance += w_i * w_j * vol_i * vol_j * rho
    return math.sqrt(max(variance, 0.0)) * 100.0


def _compute_weighted_vol_sum(positions: list) -> float:
    """Sum of w_i * vol_i (weighted individual volatilities)."""
    total = 0.0
    for pos in positions:
        total += (pos["weight_pct"] / 100.0) * pos["volatility_30d_pct"]
    return total


def _compute_effective_diversification_ratio(positions: list) -> float:
    """
    Effective diversification ratio = weighted_vol_sum / portfolio_vol.
    Values > 1.5 indicate good diversification.
    """
    port_vol = _compute_portfolio_volatility(positions)
    if port_vol <= 0:
        return 1.0
    weighted_sum = _compute_weighted_vol_sum(positions)
    return round(weighted_sum / port_vol, 4)


def _compute_herfindahl_concentration(positions: list) -> float:
    """
    Herfindahl-Hirschman Index for position concentration.
    HHI = Σ (weight_pct²) / 100
    Range: 100 (equal weights N positions) to 10000 (single position).
    """
    return round(sum(p["weight_pct"] ** 2 for p in positions) / 100.0, 2)


def _compute_exposure_hhi(exposure: dict) -> float:
    """HHI for any exposure dict (protocol or chain)."""
    if not exposure:
        return 0.0
    total = sum(exposure.values())
    if total <= 0:
        return 0.0
    return round(sum((v / total * 100) ** 2 / 100.0 for v in exposure.values()), 2)


def _compute_correlation_risk_score(eth_correlated_pct: float,
                                     div_ratio: float) -> float:
    """
    Correlation risk score 0-100.
    High ETH correlated exposure + low diversification ratio → higher score.
    """
    # ETH correlation component (0-70)
    eth_component = min(70.0, eth_correlated_pct * 0.7)
    # Low diversification component (0-30): div_ratio 1.0 → 30 pts, 2.5+ → 0 pts
    div_component = max(0.0, 30.0 - (div_ratio - 1.0) * 20.0)
    return round(min(100.0, eth_component + div_component), 2)


# ---------------------------------------------------------------------------
# Risk label
# ---------------------------------------------------------------------------

def _risk_label(positions: list, hhi: float, chain_conc: float,
                div_ratio: float, corr_risk: float) -> str:
    """Classify portfolio risk label."""
    # Check DANGEROUS_CONCENTRATION first
    max_weight = max(p["weight_pct"] for p in positions)
    if max_weight > DANGEROUS_SINGLE_POSITION or corr_risk > DANGEROUS_CORR_RISK:
        return "DANGEROUS_CONCENTRATION"
    # Check HIGHLY_CONCENTRATED
    if hhi > HIGHLY_CONCENTRATED_HHI or chain_conc > HIGHLY_CONCENTRATED_CHAIN:
        return "HIGHLY_CONCENTRATED"
    # Check diversification ratio
    if div_ratio > WELL_DIVERSIFIED_DIV_RATIO and corr_risk < 30:
        return "WELL_DIVERSIFIED"
    if div_ratio > ADEQUATELY_DIVERSIFIED_DIV_RATIO:
        return "ADEQUATELY_DIVERSIFIED"
    if div_ratio > MODERATELY_CONCENTRATED_DIV_RATIO:
        return "MODERATELY_CONCENTRATED"
    return "HIGHLY_CONCENTRATED"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def _compute_flags(positions: list, div_ratio: float,
                   eth_correlated_pct: float,
                   chain_exposure: dict,
                   protocol_exposure: dict,
                   stablecoin_pct: float) -> list:
    """Compute advisory flags for a portfolio."""
    flags = []
    if eth_correlated_pct > ETH_CORRELATED_THRESHOLD:
        flags.append("ETH_CORRELATED_DOMINANCE")
    if chain_exposure:
        max_chain = max(chain_exposure.values()) if chain_exposure else 0
        if max_chain > SINGLE_CHAIN_THRESHOLD:
            flags.append("SINGLE_CHAIN_RISK")
    if protocol_exposure:
        max_protocol = max(protocol_exposure.values()) if protocol_exposure else 0
        if max_protocol > PROTOCOL_CONCENTRATION_THRESHOLD:
            flags.append("PROTOCOL_CONCENTRATION")
    if stablecoin_pct > STABLECOIN_BUFFER_THRESHOLD:
        flags.append("STABLECOIN_BUFFER")
    if div_ratio > EFFECTIVE_DIVERSIFICATION_THRESHOLD:
        flags.append("EFFECTIVE_DIVERSIFICATION")
    max_weight = max(p["weight_pct"] for p in positions) if positions else 0
    if max_weight > EXTREME_CONCENTRATION_THRESHOLD:
        flags.append("EXTREME_CONCENTRATION")
    return flags


# ---------------------------------------------------------------------------
# Per-portfolio analysis
# ---------------------------------------------------------------------------

def _analyze_one(portfolio: dict) -> dict:
    """Analyze a single portfolio and return its metrics."""
    positions = portfolio["positions"]
    protocol_exposure = portfolio["protocol_exposure"]
    chain_exposure = portfolio["chain_exposure"]
    stablecoin_pct = float(portfolio.get("stablecoin_pct", 0.0))
    eth_correlated_pct = float(portfolio.get("eth_correlated_pct", 0.0))

    port_vol = round(_compute_portfolio_volatility(positions), 4)
    div_ratio = _compute_effective_diversification_ratio(positions)
    hhi = _compute_herfindahl_concentration(positions)
    chain_conc = _compute_exposure_hhi(chain_exposure)
    protocol_conc = _compute_exposure_hhi(protocol_exposure)
    corr_risk = _compute_correlation_risk_score(eth_correlated_pct, div_ratio)
    label = _risk_label(positions, hhi, chain_conc, div_ratio, corr_risk)
    flags = _compute_flags(
        positions, div_ratio, eth_correlated_pct,
        chain_exposure, protocol_exposure, stablecoin_pct
    )

    return {
        "name": portfolio["name"],
        "portfolio_volatility_pct": port_vol,
        "effective_diversification_ratio": div_ratio,
        "herfindahl_concentration": hhi,
        "chain_concentration_score": round(chain_conc, 2),
        "protocol_concentration_score": round(protocol_conc, 2),
        "correlation_risk_score": corr_risk,
        "risk_label": label,
        "flags": flags,
        "position_count": len(positions),
        "stablecoin_pct": stablecoin_pct,
        "eth_correlated_pct": eth_correlated_pct,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolCrossAssetCorrelationRiskAnalyzer:
    """
    Analyzes cross-asset correlation risk across DeFi portfolios.
    Advisory/read-only. No execution side-effects.
    """

    def analyze(self, portfolios: list, config: Optional[dict] = None) -> dict:
        """
        Analyze correlation risk for a list of DeFi portfolios.

        Parameters
        ----------
        portfolios : list[dict]
            Each dict must contain:
                name                  str
                positions             list[dict]  (asset, weight_pct, volatility_30d_pct,
                                                  correlation_matrix_row)
                protocol_exposure     dict[str, float]
                chain_exposure        dict[str, float]
                stablecoin_pct        float
                eth_correlated_pct    float
        config : dict, optional
            Optional overrides (future use).

        Returns
        -------
        dict with keys:
            portfolios            list[dict]  per-portfolio results
            most_diversified      str | None  name of best-diversified portfolio
            most_concentrated     str | None  name of most concentrated portfolio
            avg_correlation_risk  float
            dangerous_count       int
            well_diversified_count int
            analyzed_at           str  ISO timestamp
        """
        if config is None:
            config = {}
        if not isinstance(portfolios, list) or len(portfolios) == 0:
            raise ValueError("portfolios must be a non-empty list")

        for idx, p in enumerate(portfolios):
            _validate_portfolio(p, idx)

        results = []
        for p in portfolios:
            results.append(_analyze_one(p))

        # Aggregates
        avg_corr_risk = round(
            sum(r["correlation_risk_score"] for r in results) / len(results), 2
        )
        dangerous_count = sum(
            1 for r in results if r["risk_label"] == "DANGEROUS_CONCENTRATION"
        )
        well_div_count = sum(
            1 for r in results if r["risk_label"] == "WELL_DIVERSIFIED"
        )

        # Most diversified: highest div_ratio AND lowest corr_risk
        sorted_by_div = sorted(
            results,
            key=lambda r: (-r["effective_diversification_ratio"],
                           r["correlation_risk_score"])
        )
        most_diversified = sorted_by_div[0]["name"] if sorted_by_div else None

        # Most concentrated: highest herfindahl + corr_risk
        sorted_by_conc = sorted(
            results,
            key=lambda r: -(r["herfindahl_concentration"] + r["correlation_risk_score"])
        )
        most_concentrated = sorted_by_conc[0]["name"] if sorted_by_conc else None

        output = {
            "portfolios": results,
            "most_diversified": most_diversified,
            "most_concentrated": most_concentrated,
            "avg_correlation_risk": avg_corr_risk,
            "dangerous_count": dangerous_count,
            "well_diversified_count": well_div_count,
            "analyzed_at": _iso_now(),
        }

        # Append to ring-buffer log
        _append_log(output)
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    """Load existing log or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append result snapshot to ring-buffer log (capped at LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    snapshot = {
        "ts": result.get("analyzed_at", _iso_now()),
        "portfolio_count": len(result.get("portfolios", [])),
        "avg_correlation_risk": result.get("avg_correlation_risk"),
        "dangerous_count": result.get("dangerous_count"),
        "well_diversified_count": result.get("well_diversified_count"),
        "most_concentrated": result.get("most_concentrated"),
        "most_diversified": result.get("most_diversified"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(portfolios: list, config: Optional[dict] = None) -> dict:
    """Module-level shorthand — delegates to DeFiProtocolCrossAssetCorrelationRiskAnalyzer."""
    return DeFiProtocolCrossAssetCorrelationRiskAnalyzer().analyze(portfolios, config)
