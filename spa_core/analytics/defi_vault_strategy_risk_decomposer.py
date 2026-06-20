"""
MP-926 DeFiVaultStrategyRiskDecomposer
Decomposes sources of risk in DeFi vault strategies across four risk dimensions:
smart_contract, liquidity, oracle, and counterparty.

Pure stdlib, read-only/advisory, atomic ring-buffer log (cap 100).
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "vault_risk_decomposition_log.json"
)
RING_BUFFER_MAX = 100

# Risk label thresholds (composite_risk_score 0-100)
_RISK_LABEL_THRESHOLDS = [
    (71, "SPECULATIVE"),
    (56, "AGGRESSIVE"),
    (41, "BALANCED"),
    (21, "MODERATE"),
    (0,  "CONSERVATIVE"),
]

# Flag constants
FLAG_CONCENTRATION_RISK    = "CONCENTRATION_RISK"
FLAG_UNINSURED_HIGH_RISK   = "UNINSURED_HIGH_RISK"
FLAG_HIGH_ORACLE_EXPOSURE  = "HIGH_ORACLE_EXPOSURE"
FLAG_COMPLEX_STRATEGY      = "COMPLEX_STRATEGY"

# Defaults
_DEFAULT_CONCENTRATION_THRESHOLD  = 60.0   # single strategy allocation_pct >60%
_DEFAULT_UNINSURED_COMPOSITE_GATE = 70.0   # composite > 70
_DEFAULT_UNINSURED_INSURANCE_GATE = 10.0   # insurance < 10%
_DEFAULT_ORACLE_RISK_THRESHOLD    = 7.0    # weighted_oracle_risk > 7
_DEFAULT_COMPLEX_STRATEGY_COUNT   = 5      # > 5 strategies → complex

# Dominant risk type names
_RISK_COMPONENTS = [
    ("smart_contract",  "weighted_sc_risk"),
    ("liquidity",       "weighted_liquidity_risk"),
    ("oracle",          "weighted_oracle_risk"),
    ("counterparty",    "weighted_counterparty_risk"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_data_path(data_dir: str | None = None) -> str:
    if data_dir is not None:
        return os.path.join(data_dir, "vault_risk_decomposition_log.json")
    return DATA_FILE


def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(path: str, entries: list) -> None:
    """Atomic ring-buffer write capped at RING_BUFFER_MAX."""
    capped = entries[-RING_BUFFER_MAX:]
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    atomic_save(capped, str(path))
def _weighted_risk(strategies: list[dict], risk_key: str) -> float:
    """Compute allocation-weighted average of a risk dimension (0-10)."""
    total_alloc = sum(s.get("allocation_pct", 0.0) for s in strategies)
    if total_alloc <= 0.0:
        return 0.0
    total = sum(
        s.get(risk_key, 0.0) * s.get("allocation_pct", 0.0)
        for s in strategies
    )
    return total / total_alloc


def _composite_risk_score(
    weighted_sc: float,
    weighted_liq: float,
    weighted_oracle: float,
    weighted_cp: float,
) -> float:
    """Composite risk score 0-100 from four 0-10 risk components."""
    avg = (weighted_sc + weighted_liq + weighted_oracle + weighted_cp) / 4.0
    return round(min(100.0, max(0.0, avg * 10.0)), 4)


def _risk_label(composite: float) -> str:
    for threshold, label in _RISK_LABEL_THRESHOLDS:
        if composite >= threshold:
            return label
    return "CONSERVATIVE"


def _dominant_risk_type(
    weighted_sc: float,
    weighted_liq: float,
    weighted_oracle: float,
    weighted_cp: float,
) -> str:
    components = [
        ("smart_contract",  weighted_sc),
        ("liquidity",       weighted_liq),
        ("oracle",          weighted_oracle),
        ("counterparty",    weighted_cp),
    ]
    return max(components, key=lambda x: x[1])[0]


def _compute_flags(
    strategies: list[dict],
    composite: float,
    weighted_oracle: float,
    insurance_coverage_pct: float,
    config: dict,
) -> list[str]:
    flags: list[str] = []

    conc_thresh  = config.get("concentration_threshold",  _DEFAULT_CONCENTRATION_THRESHOLD)
    uninsc_comp  = config.get("uninsured_composite_gate", _DEFAULT_UNINSURED_COMPOSITE_GATE)
    uninsc_ins   = config.get("uninsured_insurance_gate", _DEFAULT_UNINSURED_INSURANCE_GATE)
    oracle_thresh = config.get("oracle_risk_threshold",   _DEFAULT_ORACLE_RISK_THRESHOLD)
    complex_count = config.get("complex_strategy_count",  _DEFAULT_COMPLEX_STRATEGY_COUNT)

    # CONCENTRATION_RISK: any single strategy allocation > threshold
    max_alloc = max((s.get("allocation_pct", 0.0) for s in strategies), default=0.0)
    if max_alloc > conc_thresh:
        flags.append(FLAG_CONCENTRATION_RISK)

    # UNINSURED_HIGH_RISK: composite > gate AND insurance < gate
    if composite > uninsc_comp and insurance_coverage_pct < uninsc_ins:
        flags.append(FLAG_UNINSURED_HIGH_RISK)

    # HIGH_ORACLE_EXPOSURE: weighted oracle risk > threshold
    if weighted_oracle > oracle_thresh:
        flags.append(FLAG_HIGH_ORACLE_EXPOSURE)

    # COMPLEX_STRATEGY: more than complex_count strategies
    if len(strategies) > complex_count:
        flags.append(FLAG_COMPLEX_STRATEGY)

    return flags


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiVaultStrategyRiskDecomposer:
    """
    Decomposes risk sources across vault strategies.

    Usage:
        decomposer = DeFiVaultStrategyRiskDecomposer()
        result = decomposer.decompose(vaults, config)
    """

    def decompose(
        self,
        vaults: list[dict],
        config: dict,
        *,
        data_dir: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Parameters
        ----------
        vaults : list of vault dicts, each with:
            - name              : str
            - protocol          : str
            - strategies        : list of {name, allocation_pct, smart_contract_risk,
                                           liquidity_risk, oracle_risk,
                                           counterparty_risk, apy_pct}
            - total_tvl_usd     : float
            - insurance_coverage_pct : float
        config : dict of optional overrides (thresholds)
        data_dir : optional override for log directory
        dry_run  : if True, skip log write

        Returns
        -------
        dict with keys:
            "vaults"     : per-vault decomposition
            "aggregates" : cross-vault aggregate stats
        """
        vault_results: dict[str, Any] = {}

        for vault in vaults:
            name                  = vault.get("name", "")
            strategies            = vault.get("strategies", [])
            insurance_coverage_pct = float(vault.get("insurance_coverage_pct", 0.0))

            # Weighted risk components
            w_sc      = _weighted_risk(strategies, "smart_contract_risk")
            w_liq     = _weighted_risk(strategies, "liquidity_risk")
            w_oracle  = _weighted_risk(strategies, "oracle_risk")
            w_cp      = _weighted_risk(strategies, "counterparty_risk")

            composite = _composite_risk_score(w_sc, w_liq, w_oracle, w_cp)
            insurance_adjusted = round(composite * (1.0 - insurance_coverage_pct / 100.0), 4)
            dominant  = _dominant_risk_type(w_sc, w_liq, w_oracle, w_cp)
            label     = _risk_label(composite)
            flags     = _compute_flags(
                strategies, composite, w_oracle, insurance_coverage_pct, config
            )

            vault_results[name] = {
                "weighted_sc_risk":            round(w_sc, 4),
                "weighted_liquidity_risk":     round(w_liq, 4),
                "weighted_oracle_risk":        round(w_oracle, 4),
                "weighted_counterparty_risk":  round(w_cp, 4),
                "composite_risk_score":        composite,
                "insurance_adjusted_risk":     insurance_adjusted,
                "dominant_risk_type":          dominant,
                "risk_label":                  label,
                "flags":                       flags,
            }

        # --------------- Aggregates ---------------
        scores = {n: r["composite_risk_score"] for n, r in vault_results.items()}

        safest_vault    = min(scores, key=scores.__getitem__) if scores else None
        riskiest_vault  = max(scores, key=scores.__getitem__) if scores else None
        avg_composite   = (
            round(sum(scores.values()) / len(scores), 4) if scores else 0.0
        )
        conservative_count = sum(
            1 for r in vault_results.values() if r["risk_label"] == "CONSERVATIVE"
        )
        speculative_count = sum(
            1 for r in vault_results.values() if r["risk_label"] == "SPECULATIVE"
        )

        aggregates = {
            "safest_vault":        safest_vault,
            "riskiest_vault":      riskiest_vault,
            "average_composite_risk": avg_composite,
            "conservative_count":  conservative_count,
            "speculative_count":   speculative_count,
            "vault_count":         len(vault_results),
        }

        result = {
            "vaults":     vault_results,
            "aggregates": aggregates,
        }

        # --------------- Ring-buffer log ---------------
        if not dry_run:
            log_path = _get_data_path(data_dir)
            entries  = _load_log(log_path)
            entries.append({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "vault_count": len(vaults),
                "average_composite_risk": avg_composite,
                "safest_vault": safest_vault,
                "riskiest_vault": riskiest_vault,
                "conservative_count": conservative_count,
                "speculative_count": speculative_count,
            })
            _save_log(log_path, entries)

        return result
