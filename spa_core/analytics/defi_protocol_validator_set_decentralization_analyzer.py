"""
MP-1006 DeFiProtocolValidatorSetDecentralizationAnalyzer
Evaluates decentralization of validator/sequencer sets in DeFi infrastructure
(L1/L2/bridges). Advisory/read-only. Pure stdlib. Atomic writes only.
"""

import json
import os
import time
import tempfile
from typing import Optional

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "validator_decentralization_log.json"
)
_LOG_CAP = 100

# ---------------------------------------------------------------------------
# HHI computation (approximation from percentile data)
# ---------------------------------------------------------------------------

def _compute_hhi(top1: float, top5: float, top10: float, validator_count: int) -> float:
    """Approximate Herfindahl-Hirschman Index from percentile stake data."""
    top1 = max(0.0, min(100.0, top1))
    top5 = max(top1, min(100.0, top5))
    top10 = max(top5, min(100.0, top10))
    vc = max(1, validator_count)

    hhi = top1 ** 2

    n2_5 = 4
    stake2_5 = top5 - top1
    each2_5 = stake2_5 / n2_5 if n2_5 > 0 else 0.0
    hhi += n2_5 * each2_5 ** 2

    n6_10 = 5
    stake6_10 = top10 - top5
    each6_10 = stake6_10 / n6_10 if n6_10 > 0 else 0.0
    hhi += n6_10 * each6_10 ** 2

    remaining_count = max(0, vc - 10)
    remaining_pct = max(0.0, 100.0 - top10)
    if remaining_count > 0:
        each_remaining = remaining_pct / remaining_count
        hhi += remaining_count * each_remaining ** 2

    return round(max(0.0, hhi), 2)


# ---------------------------------------------------------------------------
# Per-network scoring
# ---------------------------------------------------------------------------

def _stake_concentration_score(hhi: float) -> int:
    """Normalize HHI to 0-100 concentration score."""
    return max(0, min(100, int(hhi / 100)))


def _validator_diversity_score(stake_conc: int, geo: float, client: float,
                                centralized: bool) -> int:
    """Composite validator diversity score 0-100."""
    centralized_penalty = 20 if centralized else 0
    score = 100 - stake_conc * 0.5 + geo * 0.3 + client * 0.2 - centralized_penalty
    return max(0, min(100, int(score)))


def _nakamoto_ratio(nakamoto: int, validator_count: int) -> float:
    """Nakamoto coefficient as % of total validators."""
    if validator_count <= 0:
        return 0.0
    return round(nakamoto / validator_count * 100, 2)


def _liveness_risk_score(nakamoto: int, centralized: bool,
                          slashing_incidents: int) -> int:
    """Liveness risk 0-100 based on low nakamoto + centralized + slashing."""
    nakamoto_risk = max(0.0, (1.0 - nakamoto / 33.0)) * 40.0
    sequencer_risk = 30.0 if centralized else 0.0
    slashing_risk = min(30.0, slashing_incidents * 5.0)
    return max(0, min(100, int(nakamoto_risk + sequencer_risk + slashing_risk)))


def _decentralization_label(nakamoto: int, hhi: float, top5: float,
                              centralized: bool) -> str:
    """Assign decentralization label based on key metrics."""
    if centralized or nakamoto < 3:
        return "SINGLE_POINT_OF_FAILURE"
    if nakamoto > 50 and hhi < 500 and not centralized:
        return "HIGHLY_DECENTRALIZED"
    if nakamoto < 10 or top5 > 50.0:
        return "CENTRALIZED"
    if nakamoto < 20 or top5 > 35.0 or hhi > 1500.0:
        return "MODERATELY_CENTRALIZED"
    return "DECENTRALIZED"


def _compute_flags(top5: float, geo: float, client: float,
                   slashing: int, nakamoto: int, centralized: bool) -> list:
    """Return list of flag strings for a network."""
    flags = []
    if centralized:
        flags.append("CENTRALIZED_SEQUENCER")
    if top5 > 60.0:
        flags.append("HIGH_STAKE_CONCENTRATION")
    if geo < 40.0:
        flags.append("GEOGRAPHIC_RISK")
    if client < 30.0:
        flags.append("CLIENT_MONOCULTURE")
    if slashing > 2:
        flags.append("SLASHING_HISTORY")
    if nakamoto > 50:
        flags.append("STRONG_NAKAMOTO")
    return flags


def _parse_multisig(threshold_str: Optional[str]) -> dict:
    """Parse upgrade_multisig_threshold like '5/9' into numerator/denominator."""
    if not threshold_str:
        return {"numerator": None, "denominator": None}
    parts = str(threshold_str).strip().split("/")
    if len(parts) == 2:
        try:
            return {"numerator": int(parts[0]), "denominator": int(parts[1])}
        except ValueError:
            pass
    return {"numerator": None, "denominator": None}


# ---------------------------------------------------------------------------
# Ring-buffer log writer
# ---------------------------------------------------------------------------

def _append_log(record: dict, log_path: str = _LOG_PATH,
                 cap: int = _LOG_CAP) -> None:
    """Atomically append record to ring-buffer log JSON file."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(record)
    if len(entries) > cap:
        entries = entries[-cap:]

    dir_name = os.path.dirname(log_path)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_name, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        json.dump(entries, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(networks: list, config: Optional[dict] = None) -> dict:
    """
    Analyze validator/sequencer set decentralization across DeFi networks.

    Parameters
    ----------
    networks : list[dict]
        Each item must include:
            name                        str
            network_type                str  l1_pos/l2_optimistic/l2_zk/bridge_multisig/app_chain
            validator_count             int
            top_validator_stake_pct     float  % stake held by top-1 validator
            top5_validator_stake_pct    float  % stake by top-5
            top10_validator_stake_pct   float  % stake by top-10
            geographic_distribution_score  float  0-100
            client_diversity_score      float  0-100
            nakamoto_coefficient        int    min validators to capture 33%
            time_to_finality_seconds    float
            slashing_incidents_count    int
            sequencer_centralized       bool
            upgrade_multisig_threshold  str    e.g. "5/9" (optional)

    config : dict (optional)
        Override thresholds, log_path, log_cap.

    Returns
    -------
    dict with per-network analyses and aggregate summary.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)
    log_cap = int(cfg.get("log_cap", _LOG_CAP))
    write_log = cfg.get("write_log", True)

    if not isinstance(networks, list) or len(networks) == 0:
        return {
            "error": "networks must be a non-empty list",
            "network_analyses": [],
            "summary": {},
        }

    results = []
    for net in networks:
        name = net.get("name", "unknown")
        network_type = net.get("network_type", "unknown")
        vc = int(net.get("validator_count", 1))
        top1 = float(net.get("top_validator_stake_pct", 0.0))
        top5 = float(net.get("top5_validator_stake_pct", 0.0))
        top10 = float(net.get("top10_validator_stake_pct", 0.0))
        geo = float(net.get("geographic_distribution_score", 50.0))
        client = float(net.get("client_diversity_score", 50.0))
        nakamoto = int(net.get("nakamoto_coefficient", 1))
        ttf = float(net.get("time_to_finality_seconds", 0.0))
        slashing = int(net.get("slashing_incidents_count", 0))
        centralized = bool(net.get("sequencer_centralized", False))
        multisig_str = net.get("upgrade_multisig_threshold", None)

        hhi = _compute_hhi(top1, top5, top10, vc)
        stake_conc = _stake_concentration_score(hhi)
        diversity_score = _validator_diversity_score(stake_conc, geo, client, centralized)
        nak_ratio = _nakamoto_ratio(nakamoto, vc)
        liveness_risk = _liveness_risk_score(nakamoto, centralized, slashing)
        label = _decentralization_label(nakamoto, hhi, top5, centralized)
        flags = _compute_flags(top5, geo, client, slashing, nakamoto, centralized)
        multisig = _parse_multisig(multisig_str)

        results.append({
            "name": name,
            "network_type": network_type,
            "validator_count": vc,
            "nakamoto_coefficient": nakamoto,
            "herfindahl_index": hhi,
            "stake_concentration_score": stake_conc,
            "validator_diversity_score": diversity_score,
            "nakamoto_ratio": nak_ratio,
            "liveness_risk_score": liveness_risk,
            "decentralization_label": label,
            "flags": flags,
            "time_to_finality_seconds": ttf,
            "slashing_incidents_count": slashing,
            "sequencer_centralized": centralized,
            "upgrade_multisig": multisig,
        })

    # Aggregate
    if results:
        by_diversity = sorted(results, key=lambda r: r["validator_diversity_score"], reverse=True)
        most_decentralized = by_diversity[0]["name"]
        most_centralized = by_diversity[-1]["name"]
        avg_nakamoto = round(
            sum(r["nakamoto_coefficient"] for r in results) / len(results), 2
        )
        spof_count = sum(1 for r in results if r["decentralization_label"] == "SINGLE_POINT_OF_FAILURE")
        highly_dec_count = sum(1 for r in results if r["decentralization_label"] == "HIGHLY_DECENTRALIZED")
    else:
        most_decentralized = None
        most_centralized = None
        avg_nakamoto = 0.0
        spof_count = 0
        highly_dec_count = 0

    summary = {
        "network_count": len(results),
        "most_decentralized": most_decentralized,
        "most_centralized": most_centralized,
        "avg_nakamoto_coefficient": avg_nakamoto,
        "spof_count": spof_count,
        "highly_decentralized_count": highly_dec_count,
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    output = {
        "network_analyses": results,
        "summary": summary,
    }

    if write_log:
        log_record = {
            "timestamp": summary["analyzed_at"],
            "network_count": len(results),
            "spof_count": spof_count,
            "highly_decentralized_count": highly_dec_count,
            "avg_nakamoto_coefficient": avg_nakamoto,
        }
        _append_log(log_record, log_path=log_path, cap=log_cap)

    return output
