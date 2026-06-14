"""
MP-913  ProtocolDAOTreasuryAnalyzer
=====================================
Advisory-only module. Analyzes the financial health, diversification, and
runway of DAO protocol treasuries.

Pure Python stdlib only — no external dependencies.
Atomic writes: tmp-file + os.replace().
Advisory read-only: never modifies allocator / risk / execution.
"""

import json
import math
import os
import tempfile
import time
from typing import Any, Optional

# ── Data file ────────────────────────────────────────────────────────────────

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DATA_FILE = os.path.normpath(
    os.path.join(_MODULE_DIR, "..", "..", "data", "dao_treasury_log.json")
)
_LOG_CAP = 100

# ── I/O helpers ──────────────────────────────────────────────────────────────


def _atomic_write(path: str, obj: Any) -> None:
    """Write *obj* as JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_dao_treasury_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, record: dict) -> None:
    log = _load_log(path)
    log.append(record)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ── Core metric helpers ───────────────────────────────────────────────────────


def _compute_runway(
    stablecoins_usd: float,
    eth_btc_usd: float,
    monthly_burn_usd: float,
) -> Optional[float]:
    """
    Runway in months = (stablecoins + ETH/BTC) / monthly_burn.
    Returns ``None`` when burn rate is 0 (infinite runway).
    """
    liquid = stablecoins_usd + eth_btc_usd
    if monthly_burn_usd <= 0:
        return None  # infinite runway
    return liquid / monthly_burn_usd


def _compute_diversification_score(
    native_token_pct: float,
    stablecoins_usd: float,
    eth_btc_usd: float,
) -> float:
    """
    Diversification score [0, 100].

    Scoring rules
    -------------
    - Base: 100
    - Penalty for native concentration above 70 %:
        -(native_token_pct - 70) * 2  points per percentage-point over 70 %
    - Penalty for zero stablecoins: -10 points
    - Penalty for zero ETH/BTC:      -10 points
    - Clamp to [0, 100]
    """
    native_pct = max(0.0, min(100.0, native_token_pct))
    score = 100.0

    # Native concentration penalty
    if native_pct > 70.0:
        score -= (native_pct - 70.0) * 2.0

    # Diversification-asset penalties
    if stablecoins_usd <= 0:
        score -= 10.0
    if eth_btc_usd <= 0:
        score -= 10.0

    return max(0.0, min(100.0, score))


def _compute_concentration_risk(native_token_pct: float) -> float:
    """
    Concentration risk [0, 100].
    Linearly maps native token % → risk (100 % native = risk 100).
    """
    return max(0.0, min(100.0, float(native_token_pct)))


def _treasury_label(
    diversification_score: float,
    runway_months: Optional[float],
) -> str:
    """
    Classify treasury health.

    Labels (checked in priority order)
    ------------------------------------
    VERY_HEALTHY : score ≥ 80  AND  runway ≥ 36 months (or infinite)
    HEALTHY      : score ≥ 60  AND  runway ≥ 24 months (or infinite)
    ADEQUATE     : runway ≥ 12 months (or infinite)
    WATCH        : runway ≥  6 months
    CRITICAL     : runway  <  6 months
    """
    # infinite runway: treat as very long
    eff_runway = runway_months if runway_months is not None else math.inf

    if diversification_score >= 80.0 and eff_runway >= 36.0:
        return "VERY_HEALTHY"
    if diversification_score >= 60.0 and eff_runway >= 24.0:
        return "HEALTHY"
    if eff_runway >= 12.0:
        return "ADEQUATE"
    if eff_runway >= 6.0:
        return "WATCH"
    return "CRITICAL"


# ── Per-treasury computation ──────────────────────────────────────────────────

_LARGE_TREASURY_THRESHOLD = 100_000_000.0   # $100 M
_NATIVE_HEAVY_THRESHOLD = 70.0              # %
_SHORT_RUNWAY_THRESHOLD = 12.0             # months
_NEVER_DIVERSIFIED_DAYS = 365              # days
_INACTIVE_GOVERNANCE_THRESHOLD = 1        # proposals / 30 d


def _compute_treasury(treasury: dict) -> dict:
    """Compute health metrics for a single DAO treasury descriptor."""
    protocol = treasury.get("protocol", "unknown")
    total_usd = float(treasury.get("total_usd", 0.0))
    native_token_pct = float(treasury.get("native_token_pct", 0.0))
    stablecoins_usd = float(treasury.get("stablecoins_usd", 0.0))
    eth_btc_usd = float(treasury.get("eth_btc_usd", 0.0))
    other_assets_usd = float(treasury.get("other_assets_usd", 0.0))
    monthly_burn_usd = float(treasury.get("monthly_runway_burn_usd", 0.0))
    governance_proposals_30d = int(treasury.get("governance_proposals_30d", 0))
    last_div_days_ago = int(treasury.get("last_diversification_date_days_ago", 0))

    # Core metrics
    runway_months = _compute_runway(stablecoins_usd, eth_btc_usd, monthly_burn_usd)
    diversification_score = _compute_diversification_score(
        native_token_pct, stablecoins_usd, eth_btc_usd
    )
    concentration_risk = _compute_concentration_risk(native_token_pct)
    label = _treasury_label(diversification_score, runway_months)

    # Flags
    flags = []
    if native_token_pct > _NATIVE_HEAVY_THRESHOLD:
        flags.append("NATIVE_HEAVY")
    eff_runway = runway_months if runway_months is not None else math.inf
    if eff_runway < _SHORT_RUNWAY_THRESHOLD:
        flags.append("SHORT_RUNWAY")
    if last_div_days_ago > _NEVER_DIVERSIFIED_DAYS:
        flags.append("NEVER_DIVERSIFIED")
    if governance_proposals_30d < _INACTIVE_GOVERNANCE_THRESHOLD:
        flags.append("INACTIVE_GOVERNANCE")
    if total_usd > _LARGE_TREASURY_THRESHOLD:
        flags.append("LARGE_TREASURY")

    return {
        "protocol": protocol,
        "total_usd": total_usd,
        "native_token_pct": native_token_pct,
        "stablecoins_usd": stablecoins_usd,
        "eth_btc_usd": eth_btc_usd,
        "other_assets_usd": other_assets_usd,
        "monthly_runway_burn_usd": monthly_burn_usd,
        "governance_proposals_30d": governance_proposals_30d,
        "last_diversification_date_days_ago": last_div_days_ago,
        "runway_months": round(runway_months, 4) if runway_months is not None else None,
        "diversification_score": round(diversification_score, 4),
        "concentration_risk": round(concentration_risk, 4),
        "label": label,
        "flags": flags,
    }


# ── Main class ────────────────────────────────────────────────────────────────


class ProtocolDAOTreasuryAnalyzer:
    """
    Advisory-only analyzer for DAO / protocol treasury health.

    Each treasury descriptor (dict) should contain:
    - ``protocol``                        — protocol name
    - ``total_usd``                       — total treasury value in USD
    - ``native_token_pct``                — percentage held in own governance token
    - ``stablecoins_usd``                 — stablecoin holdings (USD)
    - ``eth_btc_usd``                     — ETH/BTC holdings (USD)
    - ``other_assets_usd``                — other assets (USD)
    - ``monthly_runway_burn_usd``         — monthly operational burn (USD)
    - ``governance_proposals_30d``        — proposals submitted in last 30 days
    - ``last_diversification_date_days_ago`` — days since last portfolio diversification

    The ``config`` dict accepts:
    - ``"write_log"`` (bool, default ``True``) — append to ring-buffer log.

    Usage
    -----
    ::
        analyzer = ProtocolDAOTreasuryAnalyzer()
        result = analyzer.analyze(treasuries=[...], config={})
    """

    def __init__(self, data_file: str = _DEFAULT_DATA_FILE) -> None:
        self.data_file = data_file

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(self, treasuries: list, config: dict) -> dict:
        """
        Analyze all treasury descriptors and return a consolidated report.

        Returns
        -------
        dict
            Keys: ``timestamp``, ``treasuries`` (list of results), ``errors``,
            ``aggregates``.
        """
        if not isinstance(treasuries, list):
            raise TypeError(
                f"treasuries must be a list, got {type(treasuries).__name__}"
            )
        if not isinstance(config, dict):
            raise TypeError(f"config must be a dict, got {type(config).__name__}")

        write_log = config.get("write_log", True)
        results = []
        errors = []

        for t in treasuries:
            if not isinstance(t, dict):
                errors.append({"treasury": str(t), "error": "not a dict"})
                continue
            try:
                results.append(_compute_treasury(t))
            except Exception as exc:
                errors.append(
                    {"treasury": t.get("protocol", "unknown"), "error": str(exc)}
                )

        # Aggregates
        total_ecosystem_usd = sum(r["total_usd"] for r in results)

        # Runway: treat None (infinite) as very large for averaging
        runways = []
        for r in results:
            if r["runway_months"] is not None:
                runways.append(r["runway_months"])
            # else: infinite — excluded from finite average (already a good sign)
        avg_runway = sum(runways) / len(runways) if runways else None

        critical_count = sum(1 for r in results if r["label"] == "CRITICAL")

        healthiest = None
        most_critical = None
        if results:
            healthiest = max(results, key=lambda r: r["diversification_score"])["protocol"]
            # Most critical = lowest effective runway
            def _eff_runway(r: dict) -> float:
                return r["runway_months"] if r["runway_months"] is not None else math.inf

            most_critical = min(results, key=_eff_runway)["protocol"]

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        output = {
            "timestamp": timestamp,
            "treasuries": results,
            "errors": errors,
            "aggregates": {
                "healthiest_treasury": healthiest,
                "most_critical": most_critical,
                "total_ecosystem_usd": round(total_ecosystem_usd, 4),
                "average_runway_months": round(avg_runway, 4) if avg_runway is not None else None,
                "critical_count": critical_count,
                "treasury_count": len(results),
                "error_count": len(errors),
            },
        }

        if write_log:
            _append_log(
                self.data_file,
                {
                    "timestamp": timestamp,
                    "treasury_count": len(results),
                    "total_ecosystem_usd": output["aggregates"]["total_ecosystem_usd"],
                    "critical_count": critical_count,
                    "error_count": len(errors),
                },
            )

        return output
