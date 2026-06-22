"""
MP-1080: DeFiProtocolTreasuryDiversificationAnalyzer
Analyzes treasury composition and runway for DeFi protocols.
Read-only/advisory — no modifications to allocator/risk/execution.
Atomic writes to data/treasury_diversification_log.json (ring-buffer 100).
"""

import json
import os
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save

# ── constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "treasury_diversification_log.json"
)
LOG_CAP = 100

VALID_ASSET_TYPES = {
    "native_token", "stablecoin", "eth", "btc", "rwa", "other_crypto"
}

# HHI thresholds (0–10000 raw, rescaled to 0–100 here via /100)
HHI_WELL_DIVERSIFIED = 15.0      # raw HHI < 1500
HHI_ADEQUATE = 25.0              # raw HHI < 2500
HHI_CONCENTRATED = 50.0         # raw HHI < 5000
# above 50 → NATIVE_TOKEN_HEAVY or CONCENTRATED

RUNWAY_CRITICAL_MONTHS = 12.0
STABLECOIN_GOOD_PCT = 30.0       # ≥30% stablecoins considered healthy


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _compute_total_treasury(holdings: list) -> float:
    """Sum all holding values."""
    return sum(float(h.get("value_usd", 0.0)) for h in holdings)


def _compute_runway_months(total_usd: float, monthly_burn_usd: float) -> float:
    """Months of runway given current treasury and monthly burn."""
    if monthly_burn_usd <= 0:
        return float("inf")
    return round(total_usd / monthly_burn_usd, 2)


def _compute_stablecoin_ratio(holdings: list, total_usd: float) -> float:
    """Percentage of treasury in stablecoins."""
    if total_usd <= 0:
        return 0.0
    stables = sum(
        float(h.get("value_usd", 0.0))
        for h in holdings
        if str(h.get("asset_type", "")).lower() == "stablecoin"
    )
    return round(100.0 * stables / total_usd, 4)


def _compute_native_token_ratio(holdings: list, total_usd: float) -> float:
    """Percentage of treasury in native protocol tokens."""
    if total_usd <= 0:
        return 0.0
    native = sum(
        float(h.get("value_usd", 0.0))
        for h in holdings
        if str(h.get("asset_type", "")).lower() == "native_token"
    )
    return round(100.0 * native / total_usd, 4)


def _compute_hhi(holdings: list, total_usd: float) -> float:
    """
    Herfindahl-Hirschman Index by asset_type, rescaled to 0–100.
    Raw HHI = sum(share_i^2 * 10000); we return raw/100 so range is 0–100.
    A single asset = 100; perfect equal spread across N types → 10000/N / 100.
    """
    if total_usd <= 0 or not holdings:
        return 100.0  # fully concentrated (no assets = worst case)

    # Aggregate by asset_type
    by_type: dict[str, float] = {}
    for h in holdings:
        atype = str(h.get("asset_type", "other_crypto")).lower()
        by_type[atype] = by_type.get(atype, 0.0) + float(h.get("value_usd", 0.0))

    raw_hhi = sum((v / total_usd) ** 2 for v in by_type.values()) * 10000.0
    return round(_clamp(raw_hhi / 100.0), 4)


def _compute_diversification_label(
    hhi_score: float,
    native_ratio: float,
    runway_months: float,
    stablecoin_ratio: float,
) -> str:
    """
    Priority rules:
      1. RUNWAY_CRITICAL — runway < 12 months
      2. NATIVE_TOKEN_HEAVY — native > 60%
      3. CONCENTRATED — HHI score > 50
      4. ADEQUATE — HHI 25–50
      5. WELL_DIVERSIFIED — HHI ≤ 25
    """
    if runway_months < RUNWAY_CRITICAL_MONTHS:
        return "RUNWAY_CRITICAL"
    if native_ratio > 60.0:
        return "NATIVE_TOKEN_HEAVY"
    if hhi_score > HHI_CONCENTRATED:
        return "CONCENTRATED"
    if hhi_score > HHI_ADEQUATE:
        return "ADEQUATE"
    return "WELL_DIVERSIFIED"


def _compute_vesting_pressure(
    vesting_unlocks_6m_usd: float,
    total_usd: float,
) -> float:
    """Fraction of treasury represented by upcoming 6-month vesting unlocks."""
    if total_usd <= 0:
        return 0.0
    return round(min(1.0, vesting_unlocks_6m_usd / total_usd), 4)


def _compute_revenue_coverage(
    revenue_usd_per_month: float,
    monthly_burn_usd: float,
) -> float:
    """Revenue / burn ratio; capped at 10 for display."""
    if monthly_burn_usd <= 0:
        return 10.0  # infinite coverage → cap at 10
    return round(min(10.0, revenue_usd_per_month / monthly_burn_usd), 4)


def _validate_holdings(holdings: list) -> list:
    """Return only holdings with recognised asset_type and non-negative value."""
    clean = []
    for h in holdings:
        atype = str(h.get("asset_type", "")).lower()
        if atype not in VALID_ASSET_TYPES:
            atype = "other_crypto"
        val = float(h.get("value_usd", 0.0))
        if val < 0:
            val = 0.0
        clean.append({
            "asset": h.get("asset", "UNKNOWN"),
            "value_usd": val,
            "asset_type": atype,
        })
    return clean


def _analyze_single(data: dict) -> dict:
    """Core analysis logic for one protocol treasury snapshot."""
    protocol_name = str(data.get("protocol_name", "UNKNOWN"))
    raw_holdings = data.get("treasury_holdings", [])
    if not isinstance(raw_holdings, list):
        raw_holdings = []
    holdings = _validate_holdings(raw_holdings)

    monthly_burn = float(data.get("monthly_burn_usd", 0.0))
    revenue_pm = float(data.get("revenue_usd_per_month", 0.0))
    vesting_6m = float(data.get("vesting_unlocks_6m_usd", 0.0))

    total = _compute_total_treasury(holdings)
    runway = _compute_runway_months(total, monthly_burn)
    stablecoin_ratio = _compute_stablecoin_ratio(holdings, total)
    native_ratio = _compute_native_token_ratio(holdings, total)
    hhi = _compute_hhi(holdings, total)
    label = _compute_diversification_label(hhi, native_ratio, runway, stablecoin_ratio)
    vesting_pressure = _compute_vesting_pressure(vesting_6m, total)
    revenue_coverage = _compute_revenue_coverage(revenue_pm, monthly_burn)

    runway_display = runway if runway != float("inf") else None

    return {
        "protocol_name": protocol_name,
        "total_treasury_usd": round(total, 2),
        "runway_months": runway_display,
        "stablecoin_ratio_pct": stablecoin_ratio,
        "native_token_ratio_pct": native_ratio,
        "hhi_concentration_score": hhi,
        "diversification_label": label,
        "vesting_pressure_ratio": vesting_pressure,
        "revenue_coverage_ratio": revenue_coverage,
        "holding_count": len(holdings),
    }


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    atomic_save(data, str(path))
def _append_log(result: dict, log_path: str) -> None:
    """Append a log entry (ring-buffer, cap LOG_CAP)."""
    existing: list = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "protocol_name": result.get("protocol_name", ""),
        "total_treasury_usd": result.get("total_treasury_usd", 0.0),
        "runway_months": result.get("runway_months"),
        "hhi_concentration_score": result.get("hhi_concentration_score", 0.0),
        "diversification_label": result.get("diversification_label", ""),
    }
    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]
    _atomic_write(log_path, existing)


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolTreasuryDiversificationAnalyzer:
    """
    Analyzes DeFi protocol treasury diversification, runway, and concentration risk.

    Input dict keys:
        protocol_name           str
        treasury_holdings       list of {"asset": str, "value_usd": float,
                                          "asset_type": str}
                                valid asset_types: native_token / stablecoin /
                                eth / btc / rwa / other_crypto
        monthly_burn_usd        float
        revenue_usd_per_month   float
        vesting_unlocks_6m_usd  float

    Output dict keys:
        total_treasury_usd        float
        runway_months             float | None  (None = infinite)
        stablecoin_ratio_pct      float  0–100
        native_token_ratio_pct    float  0–100
        hhi_concentration_score   float  0–100
        diversification_label     str    one of:
                                  WELL_DIVERSIFIED / ADEQUATE / CONCENTRATED /
                                  NATIVE_TOKEN_HEAVY / RUNWAY_CRITICAL
        vesting_pressure_ratio    float  0–1
        revenue_coverage_ratio    float  0–10
        holding_count             int
    """

    def analyze(self, data: dict, config: dict | None = None) -> dict:
        cfg = config or {}
        log_path = cfg.get("log_path", LOG_FILE)
        write_log = cfg.get("write_log", True)

        if not isinstance(data, dict):
            raise TypeError("data must be a dict")

        result = _analyze_single(data)

        if write_log:
            try:
                _append_log(result, log_path)
            except Exception:
                pass  # advisory — never raise on log failure

        return result
