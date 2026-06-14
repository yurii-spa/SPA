"""
MP-1043  ProtocolDeFiYieldSourceDependencyGraphAnalyzer
--------------------------------------------------------
Maps and scores the dependency chain of a DeFi yield source.

Example: Pendle PT-sUSDS → Sky → MakerDAO governance.
Each dependency in the chain is a single point of failure; the chain fails
if ANY dependency fails (series reliability model).

The module returns:
- total_failure_probability_pct  – probability at least one dep fails
- weakest_link                   – the highest-risk individual dependency
- chain_centralization_score     – fraction of chain TVL that is centralised
- effective_yield_risk_multiplier – how much yield must compensate for chain risk
- label                          – advisory verdict

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "yield_source_dependency_graph_log.json",
)
_LOG_CAP = 100

LABEL_ATOMIC_YIELD = "ATOMIC_YIELD"
LABEL_SIMPLE_DEPENDENCY = "SIMPLE_DEPENDENCY"
LABEL_MODERATE_CHAIN = "MODERATE_CHAIN"
LABEL_COMPLEX_DEPENDENCY = "COMPLEX_DEPENDENCY"
LABEL_DEPENDENCY_NIGHTMARE = "DEPENDENCY_NIGHTMARE"

ALL_LABELS = (
    LABEL_ATOMIC_YIELD,
    LABEL_SIMPLE_DEPENDENCY,
    LABEL_MODERATE_CHAIN,
    LABEL_COMPLEX_DEPENDENCY,
    LABEL_DEPENDENCY_NIGHTMARE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, abs_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _clamp_prob(p: float) -> float:
    """Clamp a probability in pct to [0, 100]."""
    return max(0.0, min(100.0, p))


# ---------------------------------------------------------------------------
# Depth limiter
# ---------------------------------------------------------------------------

def _apply_depth_limit(dependency_chain: list, max_chain_depth: int) -> list:
    """
    Return only the first *max_chain_depth* entries of the chain.
    If max_chain_depth <= 0 the full chain is returned unchanged.
    """
    if max_chain_depth > 0:
        return dependency_chain[:max_chain_depth]
    return dependency_chain


# ---------------------------------------------------------------------------
# Sub-calculators
# ---------------------------------------------------------------------------

def _total_failure_probability_pct(dependency_chain: list) -> float:
    """
    Series reliability: the chain fails if ANY single dependency fails.

    P(chain survives) = ∏ (1 - p_i / 100)
    P(chain fails)    = 1 - P(chain survives)          [returned as pct]

    An empty chain means no external dependencies → 0 % failure probability.
    """
    if not dependency_chain:
        return 0.0
    p_survive = 1.0
    for dep in dependency_chain:
        p_fail_i = _clamp_prob(float(dep.get("failure_probability_pct", 0.0))) / 100.0
        p_survive *= (1.0 - p_fail_i)
    return (1.0 - p_survive) * 100.0


def _weakest_link(dependency_chain: list) -> dict:
    """
    Return the dependency dict with the highest ``failure_probability_pct``.
    Returns an empty dict when the chain is empty.
    """
    if not dependency_chain:
        return {}
    return max(
        dependency_chain,
        key=lambda d: float(d.get("failure_probability_pct", 0.0)),
    )


def _chain_centralization_score(dependency_chain: list) -> float:
    """
    0-100: share of chain TVL controlled by centralised dependencies.

    When TVL figures are available they are used as weights; otherwise a
    simple count-based fraction is returned.
    """
    if not dependency_chain:
        return 0.0

    total_tvl = sum(float(d.get("tvl_usd", 0.0)) for d in dependency_chain)

    if total_tvl > 0:
        centralized_tvl = sum(
            float(d.get("tvl_usd", 0.0))
            for d in dependency_chain
            if d.get("is_centralized", False)
        )
        return min(100.0, centralized_tvl / total_tvl * 100.0)
    else:
        centralized_count = sum(
            1 for d in dependency_chain if d.get("is_centralized", False)
        )
        return min(100.0, centralized_count / len(dependency_chain) * 100.0)


def _effective_yield_risk_multiplier(total_failure_probability_pct: float) -> float:
    """
    How much the required yield must be multiplied to compensate for the
    probability of total chain failure.

    multiplier = 1 / P(chain survives) = 1 / (1 - P_fail / 100)

    Clamped to 1 000 when P_fail ≥ 99.9 % to avoid division-by-zero.
    """
    p_fail = _clamp_prob(total_failure_probability_pct) / 100.0
    p_survive = 1.0 - p_fail
    if p_survive < 0.001:
        return 1_000.0
    return 1.0 / p_survive


def _dependency_label(
    dependency_chain: list,
    total_failure_pct: float,
    chain_centralization_score: float,
) -> str:
    """
    Assign advisory label based on chain depth, failure probability, and
    centralisation.

    Priority order (highest to lowest):
    1. DEPENDENCY_NIGHTMARE   – failure_pct > 60 % OR centralisation > 80 %
    2. COMPLEX_DEPENDENCY     – chain length ≥ 4 OR failure_pct ≥ 30 %
    3. MODERATE_CHAIN         – chain length ≥ 2 OR failure_pct ≥ 10 %
    4. SIMPLE_DEPENDENCY      – exactly 1 dependency AND failure_pct < 10 %
    5. ATOMIC_YIELD           – no dependencies (empty chain)
    """
    n = len(dependency_chain)

    if n == 0:
        return LABEL_ATOMIC_YIELD

    if total_failure_pct > 60.0 or chain_centralization_score > 80.0:
        return LABEL_DEPENDENCY_NIGHTMARE

    if n >= 4 or total_failure_pct >= 30.0:
        return LABEL_COMPLEX_DEPENDENCY

    if n >= 2 or total_failure_pct >= 10.0:
        return LABEL_MODERATE_CHAIN

    # n == 1 and total_failure_pct < 10
    return LABEL_SIMPLE_DEPENDENCY


def _recommendations(
    label: str,
    dependency_chain: list,
    total_failure_pct: float,
    chain_centralization_score: float,
    weakest: dict,
    risk_multiplier: float,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []
    n = len(dependency_chain)

    if label == LABEL_ATOMIC_YIELD:
        recs.append(
            "Yield source has no external dependencies. "
            "Structural risk is minimal — only smart-contract risk applies."
        )
        return recs

    if label == LABEL_DEPENDENCY_NIGHTMARE:
        recs.append(
            f"CRITICAL: chain failure probability {total_failure_pct:.1f}% "
            f"across {n} dependencies. Avoid or size extremely small."
        )
        if chain_centralization_score > 80.0:
            recs.append(
                f"Centralization score {chain_centralization_score:.0f}/100. "
                "A single actor can cause total loss."
            )
    elif label == LABEL_COMPLEX_DEPENDENCY:
        recs.append(
            f"Complex chain ({n} hops, {total_failure_pct:.1f}% failure prob). "
            "Each additional layer compounds risk multiplicatively."
        )
    elif label == LABEL_MODERATE_CHAIN:
        recs.append(
            f"Moderate dependency chain ({n} hops, {total_failure_pct:.1f}% failure prob). "
            "Monitor all upstream protocols for governance or liquidity changes."
        )
    else:  # SIMPLE_DEPENDENCY
        recs.append(
            f"Single dependency, low failure probability ({total_failure_pct:.1f}%). "
            "Well within acceptable risk tolerance for most strategies."
        )

    if weakest:
        wname = weakest.get("name", "?")
        wprob = float(weakest.get("failure_probability_pct", 0.0))
        recs.append(
            f"Weakest link: '{wname}' with {wprob:.1f}% individual failure probability. "
            "Prioritise monitoring this dependency."
        )

    if risk_multiplier > 2.0:
        recs.append(
            f"Required yield risk multiplier {risk_multiplier:.2f}x: the stated APY "
            "must significantly exceed risk-free rate to justify this dependency chain."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(source: dict, config: dict | None = None) -> dict:
    """
    Analyse the dependency graph of a DeFi yield source.

    Parameters
    ----------
    source : dict
        Required keys:
        - yield_source_name : str
        - dependency_chain  : list[dict], each dict has:
              name                    : str
              type                    : str  (e.g. "protocol", "oracle", "bridge")
              failure_probability_pct : float  (0-100, estimated annual failure prob)
              tvl_usd                 : float  (TVL controlled by this dependency)
              is_centralized          : bool
        - max_chain_depth   : int  (0 = no limit; positive = cap analysis depth)
    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    name = str(source.get("yield_source_name", "UNKNOWN"))
    raw_chain: list = source.get("dependency_chain", [])
    if not isinstance(raw_chain, list):
        raw_chain = []
    max_depth = int(source.get("max_chain_depth", 0))

    # Normalise each dependency entry
    chain: list[dict] = []
    for dep in raw_chain:
        chain.append(
            {
                "name": str(dep.get("name", "?")),
                "type": str(dep.get("type", "unknown")),
                "failure_probability_pct": _clamp_prob(
                    float(dep.get("failure_probability_pct", 0.0))
                ),
                "tvl_usd": max(0.0, float(dep.get("tvl_usd", 0.0))),
                "is_centralized": bool(dep.get("is_centralized", False)),
            }
        )

    # Apply depth limit
    effective_chain = _apply_depth_limit(chain, max_depth)
    effective_depth = len(effective_chain)

    total_fail_pct = _total_failure_probability_pct(effective_chain)
    weakest = _weakest_link(effective_chain)
    centralization = _chain_centralization_score(effective_chain)
    multiplier = _effective_yield_risk_multiplier(total_fail_pct)
    label = _dependency_label(effective_chain, total_fail_pct, centralization)
    recs = _recommendations(
        label, effective_chain, total_fail_pct, centralization, weakest, multiplier
    )

    result: dict[str, Any] = {
        "yield_source_name": name,
        "dependency_chain": effective_chain,
        "max_chain_depth": max_depth,
        "effective_depth": effective_depth,
        "total_failure_probability_pct": total_fail_pct,
        "weakest_link": weakest,
        "chain_centralization_score": centralization,
        "effective_yield_risk_multiplier": multiplier,
        "label": label,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldSourceDependencyGraphAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` function.

    >>> a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer()
    >>> r = a.analyze({"yield_source_name": "Pendle PT-sUSDS", ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, source: dict) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(source, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "yield_source_name": "Pendle PT-sUSDS",
        "dependency_chain": [
            {
                "name": "Sky (sUSDS)",
                "type": "protocol",
                "failure_probability_pct": 5.0,
                "tvl_usd": 4_000_000_000.0,
                "is_centralized": False,
            },
            {
                "name": "MakerDAO governance",
                "type": "governance",
                "failure_probability_pct": 3.0,
                "tvl_usd": 8_000_000_000.0,
                "is_centralized": False,
            },
            {
                "name": "Pendle AMM",
                "type": "protocol",
                "failure_probability_pct": 4.0,
                "tvl_usd": 500_000_000.0,
                "is_centralized": False,
            },
        ],
        "max_chain_depth": 10,
    }

    import json as _json
    print(_json.dumps(analyze(_demo), indent=2, default=str))
    sys.exit(0)
