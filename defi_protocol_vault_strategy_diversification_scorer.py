"""
MP-1038 DeFiProtocolVaultStrategyDiversificationScorer
Advisory-only analytics module.

Scores how well a vault/strategy diversifies across protocols, chains, and yield
sources using Herfindahl-Hirschman Index (HHI) across three dimensions.

Inputs:
  allocations          — list of dicts:
                         { protocol, chain, yield_type, weight_pct, apy_pct }
  max_single_protocol_pct   — threshold for protocol concentration warning (default 40.0)
  max_single_chain_pct      — threshold for chain concentration warning    (default 60.0)
  max_single_yield_type_pct — threshold for yield type warning             (default 70.0)

Outputs:
  diversification_score (0-100), herfindahl_index, concentration_warnings (list),
  weighted_apy_pct,
  label: WELL_DIVERSIFIED / GOOD_MIX / MODERATE_CONCENTRATION /
         CONCENTRATED / SINGLE_POINT_EXPOSURE

Data log: data/vault_strategy_diversification_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
import tempfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_RING_SIZE = 100
_DEFAULT_MAX_PROTOCOL_PCT = 40.0
_DEFAULT_MAX_CHAIN_PCT = 60.0
_DEFAULT_MAX_YIELD_TYPE_PCT = 70.0

# Score thresholds (inclusive lower bound of each band)
_THRESHOLD_WELL_DIVERSIFIED = 80.0
_THRESHOLD_GOOD_MIX = 60.0
_THRESHOLD_MODERATE = 40.0
_THRESHOLD_CONCENTRATED = 20.0

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _aggregate_weights(allocations: list, key: str) -> dict:
    """
    Aggregate weight_pct by a given key across allocations.
    Returns {key_value: total_weight_pct}.
    """
    result: dict = {}
    for a in allocations:
        k = str(a.get(key, "unknown"))
        result[k] = result.get(k, 0.0) + float(a.get("weight_pct", 0.0))
    return result


def _hhi(weights_pct: dict) -> float:
    """
    Compute Herfindahl-Hirschman Index from {name: weight_pct}.
    Normalises weights to fractions before squaring, so result ∈ [0, 1].
    Empty or zero-total input → 0.0.
    """
    total = sum(weights_pct.values())
    if total <= 0.0:
        return 0.0
    return sum((w / total) ** 2 for w in weights_pct.values())


def _protocol_weights(allocations: list) -> dict:
    return _aggregate_weights(allocations, "protocol")


def _chain_weights(allocations: list) -> dict:
    return _aggregate_weights(allocations, "chain")


def _yield_type_weights(allocations: list) -> dict:
    return _aggregate_weights(allocations, "yield_type")


def _protocol_hhi(allocations: list) -> float:
    return _hhi(_protocol_weights(allocations))


def _chain_hhi(allocations: list) -> float:
    return _hhi(_chain_weights(allocations))


def _yield_type_hhi(allocations: list) -> float:
    return _hhi(_yield_type_weights(allocations))


def _combined_hhi(allocations: list) -> float:
    """Average HHI across protocol, chain, and yield_type dimensions."""
    return (_protocol_hhi(allocations) + _chain_hhi(allocations) + _yield_type_hhi(allocations)) / 3.0


def _diversification_score(combined_hhi_value: float) -> float:
    """
    Convert combined HHI to a diversification score in [0, 100].
    Lower HHI ⟹ better diversification ⟹ higher score.
    """
    return round(max(0.0, min(100.0, 100.0 * (1.0 - combined_hhi_value))), 4)


def _concentration_warnings(
    protocol_w: dict,
    chain_w: dict,
    yield_type_w: dict,
    max_protocol: float,
    max_chain: float,
    max_yield_type: float,
) -> list:
    """
    Return a list of human-readable warning strings when any single
    entity exceeds its configured threshold.
    """
    warnings: list = []
    for name, w in sorted(protocol_w.items()):
        if w > max_protocol:
            warnings.append(
                f"Protocol '{name}' is {w:.1f}% > {max_protocol:.1f}% limit"
            )
    for name, w in sorted(chain_w.items()):
        if w > max_chain:
            warnings.append(
                f"Chain '{name}' is {w:.1f}% > {max_chain:.1f}% limit"
            )
    for name, w in sorted(yield_type_w.items()):
        if w > max_yield_type:
            warnings.append(
                f"Yield type '{name}' is {w:.1f}% > {max_yield_type:.1f}% limit"
            )
    return warnings


def _weighted_apy(allocations: list) -> float:
    """
    Compute weight-averaged APY.
    weighted_apy = Σ(weight_pct_i * apy_pct_i) / Σ(weight_pct_i)
    """
    total_weight = sum(float(a.get("weight_pct", 0.0)) for a in allocations)
    if total_weight <= 0.0:
        return 0.0
    total = sum(
        float(a.get("weight_pct", 0.0)) * float(a.get("apy_pct", 0.0))
        for a in allocations
    )
    return round(total / total_weight, 6)


def _label(score: float) -> str:
    """Map diversification score to qualitative label."""
    if score >= _THRESHOLD_WELL_DIVERSIFIED:
        return "WELL_DIVERSIFIED"
    if score >= _THRESHOLD_GOOD_MIX:
        return "GOOD_MIX"
    if score >= _THRESHOLD_MODERATE:
        return "MODERATE_CONCENTRATION"
    if score >= _THRESHOLD_CONCENTRATED:
        return "CONCENTRATED"
    return "SINGLE_POINT_EXPOSURE"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    allocations: list,
    max_single_protocol_pct: float = _DEFAULT_MAX_PROTOCOL_PCT,
    max_single_chain_pct: float = _DEFAULT_MAX_CHAIN_PCT,
    max_single_yield_type_pct: float = _DEFAULT_MAX_YIELD_TYPE_PCT,
) -> dict:
    """
    Score diversification of a vault/strategy across protocols, chains, and yield sources.

    Parameters
    ----------
    allocations : list of dicts
        Each dict must have keys: protocol, chain, yield_type, weight_pct, apy_pct.
    max_single_protocol_pct : float
        Warn when a single protocol exceeds this weight percentage.
    max_single_chain_pct : float
        Warn when a single chain exceeds this weight percentage.
    max_single_yield_type_pct : float
        Warn when a single yield type exceeds this weight percentage.

    Returns
    -------
    dict with keys:
      n_allocations, protocol_weights, chain_weights, yield_type_weights,
      protocol_hhi, chain_hhi, yield_type_hhi, herfindahl_index,
      diversification_score, concentration_warnings, weighted_apy_pct, label, timestamp.
    """
    if not allocations:
        return {
            "allocations": [],
            "max_single_protocol_pct": max_single_protocol_pct,
            "max_single_chain_pct": max_single_chain_pct,
            "max_single_yield_type_pct": max_single_yield_type_pct,
            "n_allocations": 0,
            "protocol_weights": {},
            "chain_weights": {},
            "yield_type_weights": {},
            "protocol_hhi": 0.0,
            "chain_hhi": 0.0,
            "yield_type_hhi": 0.0,
            "herfindahl_index": 0.0,
            "diversification_score": 0.0,
            "concentration_warnings": [],
            "weighted_apy_pct": 0.0,
            "label": "SINGLE_POINT_EXPOSURE",
            "timestamp": time.time(),
        }

    pw = _protocol_weights(allocations)
    cw = _chain_weights(allocations)
    yw = _yield_type_weights(allocations)

    phhi = _hhi(pw)
    chhi = _hhi(cw)
    yhhi = _hhi(yw)
    combined = (phhi + chhi + yhhi) / 3.0

    score = _diversification_score(combined)
    warnings = _concentration_warnings(
        pw, cw, yw,
        max_single_protocol_pct,
        max_single_chain_pct,
        max_single_yield_type_pct,
    )
    w_apy = _weighted_apy(allocations)
    lbl = _label(score)

    return {
        "allocations": list(allocations),
        "max_single_protocol_pct": max_single_protocol_pct,
        "max_single_chain_pct": max_single_chain_pct,
        "max_single_yield_type_pct": max_single_yield_type_pct,
        "n_allocations": len(allocations),
        "protocol_weights": pw,
        "chain_weights": cw,
        "yield_type_weights": yw,
        "protocol_hhi": round(phhi, 8),
        "chain_hhi": round(chhi, 8),
        "yield_type_hhi": round(yhhi, 8),
        "herfindahl_index": round(combined, 8),
        "diversification_score": score,
        "concentration_warnings": warnings,
        "weighted_apy_pct": w_apy,
        "label": lbl,
        "timestamp": time.time(),
    }


class DeFiProtocolVaultStrategyDiversificationScorer:
    """
    Class wrapper for MP-1038 vault/strategy diversification scoring.

    Parameters
    ----------
    max_single_protocol_pct : float  (default 40.0)
    max_single_chain_pct    : float  (default 60.0)
    max_single_yield_type_pct : float (default 70.0)
    """

    def __init__(
        self,
        max_single_protocol_pct: float = _DEFAULT_MAX_PROTOCOL_PCT,
        max_single_chain_pct: float = _DEFAULT_MAX_CHAIN_PCT,
        max_single_yield_type_pct: float = _DEFAULT_MAX_YIELD_TYPE_PCT,
    ):
        self.max_single_protocol_pct = max_single_protocol_pct
        self.max_single_chain_pct = max_single_chain_pct
        self.max_single_yield_type_pct = max_single_yield_type_pct

    def score(self, allocations: list) -> dict:
        """Score diversification of the given allocations."""
        return analyze(
            allocations,
            max_single_protocol_pct=self.max_single_protocol_pct,
            max_single_chain_pct=self.max_single_chain_pct,
            max_single_yield_type_pct=self.max_single_yield_type_pct,
        )


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append a compact snapshot to the ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "vault_strategy_diversification_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    snapshot = {
        "timestamp": result["timestamp"],
        "n_allocations": result["n_allocations"],
        "herfindahl_index": result["herfindahl_index"],
        "protocol_hhi": result["protocol_hhi"],
        "chain_hhi": result["chain_hhi"],
        "yield_type_hhi": result["yield_type_hhi"],
        "diversification_score": result["diversification_score"],
        "weighted_apy_pct": result["weighted_apy_pct"],
        "label": result["label"],
        "n_warnings": len(result["concentration_warnings"]),
    }
    log.append(snapshot)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    os.makedirs(data_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=data_dir, prefix=".vault_diversification_log_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_ALLOCATIONS = [
    {"protocol": "Aave V3",   "chain": "Ethereum", "yield_type": "lending", "weight_pct": 30.0, "apy_pct": 3.5},
    {"protocol": "Compound",  "chain": "Ethereum", "yield_type": "lending", "weight_pct": 20.0, "apy_pct": 4.8},
    {"protocol": "Morpho",    "chain": "Ethereum", "yield_type": "lending", "weight_pct": 20.0, "apy_pct": 6.5},
    {"protocol": "Yearn V3",  "chain": "Ethereum", "yield_type": "vault",   "weight_pct": 15.0, "apy_pct": 5.2},
    {"protocol": "Euler V2",  "chain": "Arbitrum", "yield_type": "lending", "weight_pct": 10.0, "apy_pct": 5.8},
    {"protocol": "Pendle",    "chain": "Arbitrum", "yield_type": "pt_yield","weight_pct":  5.0, "apy_pct": 12.0},
]

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-1038 DeFiProtocolVaultStrategyDiversificationScorer")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run",   action="store_true", help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(_SAMPLE_ALLOCATIONS)

    print(f"Allocations       : {result['n_allocations']}")
    print(f"Protocol HHI      : {result['protocol_hhi']:.6f}")
    print(f"Chain HHI         : {result['chain_hhi']:.6f}")
    print(f"Yield Type HHI    : {result['yield_type_hhi']:.6f}")
    print(f"Combined HHI      : {result['herfindahl_index']:.6f}")
    print(f"Diversif. Score   : {result['diversification_score']:.2f}")
    print(f"Weighted APY      : {result['weighted_apy_pct']:.4f}%")
    print(f"Label             : {result['label']}")
    print(f"Protocol weights  : {result['protocol_weights']}")
    print(f"Chain weights     : {result['chain_weights']}")
    print(f"Yield type weights: {result['yield_type_weights']}")
    if result["concentration_warnings"]:
        print("Warnings:")
        for w in result["concentration_warnings"]:
            print(f"  ⚠ {w}")
    else:
        print("No concentration warnings.")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to    : {args.data_dir}/vault_strategy_diversification_log.json")
