"""
MP-840 ProtocolMultiChainRiskAssessor
Assesses additional risks from cross-chain deployments — bridge vulnerabilities,
chain-specific smart contract risks, liquidity fragmentation, and operational complexity.

Advisory / read-only. Pure stdlib. Atomic writes via tmp + os.replace.
"""

import json
import os
import time
import tempfile

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "multi_chain_risk_log.json")
LOG_MAX = 100

_DEFAULT_CONFIG = {
    "max_bridge_risk": 60,
}


def _merge_config(user_config: dict | None) -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if user_config:
        cfg.update(user_config)
    return cfg


# ---------------------------------------------------------------------------
# Per-chain helpers
# ---------------------------------------------------------------------------

def _bridge_risk_score(bridge_type: str, bridge_audit_score: int, active_incidents: int) -> int:
    """Compute 0-100 bridge risk for a single chain."""
    if bridge_type == "NONE":
        base = 0.0
    elif bridge_type == "NATIVE":
        # range 5-10
        base = 10.0 - (bridge_audit_score / 100.0 * 5.0)
    elif bridge_type == "CANONICAL":
        # range 10-25
        base = 25.0 - (bridge_audit_score / 100.0 * 15.0)
    elif bridge_type == "THIRD_PARTY":
        # range 30-70
        base = 70.0 - (bridge_audit_score / 100.0 * 40.0)
    else:
        base = 0.0

    incident_penalty = min(20, active_incidents * 10)
    raw = base + incident_penalty
    return int(min(100, max(0, raw)))


def _maturity_component(avg_maturity_years: float) -> float:
    """0-10 points: inverse maturity."""
    if avg_maturity_years >= 4:
        return 0.0
    elif avg_maturity_years >= 2:
        return 3.0
    elif avg_maturity_years >= 1:
        return 6.0
    else:
        return 10.0


def _fragmentation_component(chain_count: int) -> float:
    """0-30 points based on number of chains."""
    if chain_count >= 5:
        return 30.0
    elif chain_count >= 3:
        return 20.0
    elif chain_count >= 2:
        return 10.0
    else:
        return 0.0


def _concentration_component(tvl_concentration: float) -> float:
    """0-20 points: concentrated = less fragmentation risk."""
    if tvl_concentration >= 90:
        return 5.0
    elif tvl_concentration >= 70:
        return 8.0
    elif tvl_concentration >= 50:
        return 12.0
    else:
        return 20.0


def _risk_label(score: int) -> str:
    if score >= 76:
        return "CRITICAL"
    elif score >= 51:
        return "HIGH"
    elif score >= 26:
        return "MODERATE"
    else:
        return "LOW"


def _fragmentation_risk_label(chain_count: int) -> str:
    if chain_count == 1:
        return "LOW"
    elif chain_count <= 3:
        return "MODERATE"
    else:
        return "HIGH"


# ---------------------------------------------------------------------------
# Per-protocol analysis
# ---------------------------------------------------------------------------

def _analyze_protocol(deployment: dict, cfg: dict) -> dict:
    protocol = deployment["protocol"]
    chains = deployment["chains"]
    max_bridge_risk = cfg["max_bridge_risk"]

    chain_count = len(chains)

    # Total TVL
    total_tvl = sum(float(c["tvl_usd"]) for c in chains)

    # TVL concentration (% in largest chain)
    if total_tvl > 0 and chains:
        max_chain_tvl = max(float(c["tvl_usd"]) for c in chains)
        tvl_concentration = max_chain_tvl / total_tvl * 100.0
    else:
        tvl_concentration = 0.0

    # Per-chain details
    chain_details = []
    bridge_risks_all = []
    for c in chains:
        chain_name = c["chain_name"]
        chain_tvl = float(c["tvl_usd"])
        bridge_type = c["bridge_type"]
        bridge_audit = int(c.get("bridge_audit_score", 0))
        maturity = float(c["chain_maturity_years"])
        is_evm = bool(c["is_evm_compatible"])
        incidents = int(c["active_incidents"])

        tvl_pct = (chain_tvl / total_tvl * 100.0) if total_tvl > 0 else 0.0
        br = _bridge_risk_score(bridge_type, bridge_audit, incidents)
        bridge_risks_all.append(br)

        flags = []
        if br > max_bridge_risk:
            flags.append(f"Bridge risk {br} exceeds threshold {max_bridge_risk}")
        if incidents > 0:
            flags.append(f"{incidents} active security incident(s)")
        if not is_evm:
            flags.append("Non-EVM chain — additional compatibility risk")

        chain_details.append({
            "chain_name": chain_name,
            "tvl_pct": round(tvl_pct, 4),
            "bridge_risk": br,
            "flags": flags,
        })

    # Bridge risk score: avg of all chains (non-NONE might still be 0 if type==NONE)
    # Spec: "avg bridge_risk across all chains"
    if bridge_risks_all:
        avg_bridge_risk = sum(bridge_risks_all) / len(bridge_risks_all)
        bridge_risk_score = int(round(avg_bridge_risk))
    else:
        avg_bridge_risk = 0.0
        bridge_risk_score = 0

    # Avg chain maturity
    if chains:
        avg_maturity = sum(float(c["chain_maturity_years"]) for c in chains) / len(chains)
    else:
        avg_maturity = 0.0

    # Components
    bridge_comp = avg_bridge_risk * 0.4
    frag_comp = _fragmentation_component(chain_count)
    conc_comp = _concentration_component(tvl_concentration)
    mat_comp = _maturity_component(avg_maturity)

    raw_score = bridge_comp + frag_comp + conc_comp + mat_comp
    multi_chain_risk_score = int(min(100, raw_score))

    risk_label = _risk_label(multi_chain_risk_score)
    fragmentation_risk = _fragmentation_risk_label(chain_count)

    # Recommendations
    recommendations = []
    if multi_chain_risk_score > 70:
        recommendations.append(
            "High cross-chain risk — consider consolidating to primary chain"
        )
    if bridge_risk_score > max_bridge_risk:
        recommendations.append(
            "Bridge risk elevated — prefer native/canonical bridges where possible"
        )
    if chain_count >= 5:
        recommendations.append(
            "High operational complexity from many chain deployments"
        )

    return {
        "protocol": protocol,
        "chain_count": chain_count,
        "total_tvl_usd": round(total_tvl, 4),
        "tvl_concentration": round(tvl_concentration, 4),
        "multi_chain_risk_score": multi_chain_risk_score,
        "risk_label": risk_label,
        "bridge_risk_score": bridge_risk_score,
        "fragmentation_risk": fragmentation_risk,
        "chain_details": chain_details,
        "recommendations": recommendations,
    }


def analyze(protocol_deployments: list, config: dict = None) -> dict:
    """
    Assess cross-chain deployment risks for a list of protocols.

    Parameters
    ----------
    protocol_deployments : list of dict
        Each dict contains 'protocol' (str) and 'chains' (list of chain dicts).
    config : dict, optional
        max_bridge_risk (default 60).

    Returns
    -------
    dict with per-protocol results and aggregate metrics.
    """
    cfg = _merge_config(config)

    if not protocol_deployments:
        return {
            "protocols": [],
            "riskiest_protocol": None,
            "safest_protocol": None,
            "average_risk_score": 0.0,
            "timestamp": time.time(),
        }

    results = [_analyze_protocol(d, cfg) for d in protocol_deployments]

    scores = [(r["multi_chain_risk_score"], r["protocol"]) for r in results]
    riskiest_protocol = max(scores, key=lambda x: x[0])[1]
    safest_protocol = min(scores, key=lambda x: x[0])[1]
    average_risk_score = sum(s for s, _ in scores) / len(scores)

    return {
        "protocols": results,
        "riskiest_protocol": riskiest_protocol,
        "safest_protocol": safest_protocol,
        "average_risk_score": round(average_risk_score, 4),
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistent log
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=os.path.dirname(path), delete=False, suffix=".tmp"
    ) as fh:
        json.dump(data, fh, indent=2)
        tmp_path = fh.name
    os.replace(tmp_path, path)


def _load_log(path: str) -> list:
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def run_and_log(protocol_deployments: list, config: dict = None, data_file: str = None) -> dict:
    """Run analysis and append result to ring-buffer log (capped at LOG_MAX)."""
    result = analyze(protocol_deployments, config)
    path = data_file or DATA_FILE
    log = _load_log(path)
    log.append(result)
    if len(log) > LOG_MAX:
        log = log[-LOG_MAX:]
    _atomic_write(path, log)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-840 ProtocolMultiChainRiskAssessor")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute and write to data file")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    demo = [
        {
            "protocol": "Aave V3",
            "chains": [
                {
                    "chain_name": "Ethereum",
                    "tvl_usd": 8_000_000,
                    "bridge_type": "NONE",
                    "bridge_audit_score": 0,
                    "chain_maturity_years": 8.0,
                    "is_evm_compatible": True,
                    "active_incidents": 0,
                },
                {
                    "chain_name": "Arbitrum",
                    "tvl_usd": 2_000_000,
                    "bridge_type": "CANONICAL",
                    "bridge_audit_score": 85,
                    "chain_maturity_years": 3.0,
                    "is_evm_compatible": True,
                    "active_incidents": 0,
                },
            ],
        },
    ]

    if args.run:
        data_file = None
        if args.data_dir:
            data_file = os.path.join(args.data_dir, "multi_chain_risk_log.json")
        result = run_and_log(demo, data_file=data_file)
        print(json.dumps(result, indent=2))
    else:
        result = analyze(demo)
        print(json.dumps(result, indent=2))
