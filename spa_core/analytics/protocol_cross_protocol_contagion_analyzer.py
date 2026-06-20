"""
MP-927 ProtocolCrossProtocolContagionAnalyzer
Analyzes chain-reaction (contagion) risk between mutually dependent protocols.
Builds a directed dependency graph and scores each protocol's exposure to
cascading failure.

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
    os.path.dirname(__file__), "..", "..", "data", "contagion_risk_log.json"
)
RING_BUFFER_MAX = 100

# Contagion label thresholds (contagion_risk_score 0-100)
_CONTAGION_LABEL_THRESHOLDS = [
    (71, "SYSTEMIC"),
    (51, "HIGH"),
    (31, "MODERATE"),
    (11, "LOW"),
    (0,  "ISOLATED"),
]

# Flag constants
FLAG_CIRCULAR_DEPENDENCY       = "CIRCULAR_DEPENDENCY"
FLAG_SINGLE_ORACLE_DEPENDENCY  = "SINGLE_ORACLE_DEPENDENCY"
FLAG_SYSTEMIC_EXPOSURE         = "SYSTEMIC_EXPOSURE"
FLAG_HIGH_EXPOSURE_RATIO       = "HIGH_EXPOSURE_RATIO"

# Scoring weights
_CRITICAL_DEP_WEIGHT     = 20
_NONCRITICAL_DEP_WEIGHT  = 10
_SYSTEMIC_FLAG_BONUS     = 50
_INDEGREE_WEIGHT         = 10

# Defaults
_DEFAULT_EXPOSURE_RATIO_THRESHOLD = 0.50   # exposure > 50% TVL


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_data_path(data_dir: str | None = None) -> str:
    if data_dir is not None:
        return os.path.join(data_dir, "contagion_risk_log.json")
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
def _contagion_label(score: float) -> str:
    for threshold, label in _CONTAGION_LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "ISOLATED"


def _detect_cycles(graph: dict[str, list[str]]) -> set[str]:
    """
    DFS cycle detection on directed graph.
    Returns set of node names that participate in at least one cycle.
    graph: {node_name: [dep_name, ...]}
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}
    in_cycle: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        """Returns True if a cycle was detected on this path."""
        color[node] = GRAY
        path.append(node)
        found = False
        for neighbour in graph.get(node, []):
            if neighbour not in color:
                # neighbour not in graph (external dependency)
                continue
            if color[neighbour] == GRAY:
                # Back-edge → cycle: mark everyone on path from neighbour to here
                idx = path.index(neighbour)
                for n in path[idx:]:
                    in_cycle.add(n)
                found = True
            elif color[neighbour] == WHITE:
                if dfs(neighbour):
                    found = True
        path.pop()
        color[node] = BLACK
        return found

    for node in list(graph):
        if color[node] == WHITE:
            dfs(node)

    return in_cycle


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolCrossProtocolContagionAnalyzer:
    """
    Analyzes cross-protocol contagion risk via dependency graph analysis.

    Usage:
        analyzer = ProtocolCrossProtocolContagionAnalyzer()
        result = analyzer.analyze(protocols, config)
    """

    def analyze(
        self,
        protocols: list[dict],
        config: dict,
        *,
        data_dir: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Parameters
        ----------
        protocols : list of protocol dicts, each with:
            - name          : str
            - tvl_usd       : float
            - dependencies  : list of {protocol_name, dependency_type,
                                       exposure_usd, critical}
            - protocol_type : str
            - chain         : str
            - is_systemic   : bool
        config : dict of optional overrides
        data_dir : optional override for log directory
        dry_run  : if True, skip log write

        Returns
        -------
        dict with keys:
            "protocols"  : per-protocol contagion analysis
            "aggregates" : cross-protocol aggregate stats
        """
        exposure_ratio_threshold = float(
            config.get("exposure_ratio_threshold", _DEFAULT_EXPOSURE_RATIO_THRESHOLD)
        )

        # Index protocols by name for quick lookup
        protocol_map: dict[str, dict] = {p["name"]: p for p in protocols}
        all_names = set(protocol_map)

        # --------------- Build dependency graph ---------------
        # graph[A] = [B, C, ...] means A depends on B and C
        graph: dict[str, list[str]] = {}
        # in_degree_map[B] = list of (from_protocol_name, critical)
        in_degree_map: dict[str, list[tuple[str, bool]]] = {n: [] for n in all_names}

        for p in protocols:
            name = p["name"]
            deps = p.get("dependencies", [])
            graph[name] = []
            for dep in deps:
                dep_name = dep.get("protocol_name", "")
                critical = bool(dep.get("critical", False))
                graph[name].append(dep_name)
                if dep_name in in_degree_map:
                    in_degree_map[dep_name].append((name, critical))
                else:
                    # External / unlisted dependency still tracked in-degree
                    in_degree_map[dep_name] = [(name, critical)]

        # --------------- Cycle detection ---------------
        cycled_nodes = _detect_cycles(graph)

        # --------------- Per-protocol analysis ---------------
        protocol_results: dict[str, Any] = {}

        for p in protocols:
            name         = p["name"]
            tvl_usd      = float(p.get("tvl_usd", 0.0))
            deps         = p.get("dependencies", [])
            is_systemic  = bool(p.get("is_systemic", False))

            # Degree metrics
            out_degree = len(deps)
            # in_degree = number of (listed) protocols that depend on this one
            in_dependents     = in_degree_map.get(name, [])
            in_degree         = len(in_dependents)
            in_degree_critical = sum(1 for _, crit in in_dependents if crit)
            in_degree_noncrit  = in_degree - in_degree_critical

            # Contagion risk score (0-100)
            contagion_raw = (
                in_degree_critical * _CRITICAL_DEP_WEIGHT
                + in_degree_noncrit * _NONCRITICAL_DEP_WEIGHT
            )
            contagion_risk_score = min(100.0, float(contagion_raw))

            # Systemic importance score (0-100)
            systemic_raw = (
                (1 if is_systemic else 0) * _SYSTEMIC_FLAG_BONUS
                + in_degree * _INDEGREE_WEIGHT
            )
            systemic_importance_score = min(100.0, float(systemic_raw))

            contagion_label = _contagion_label(contagion_risk_score)

            # --------------- Flags ---------------
            flags: list[str] = []

            # CIRCULAR_DEPENDENCY
            if name in cycled_nodes:
                flags.append(FLAG_CIRCULAR_DEPENDENCY)

            # SINGLE_ORACLE_DEPENDENCY: protocol has deps and ALL are type 'oracle'
            dep_types = [d.get("dependency_type", "") for d in deps]
            if dep_types and all(t == "oracle" for t in dep_types):
                flags.append(FLAG_SINGLE_ORACLE_DEPENDENCY)

            # SYSTEMIC_EXPOSURE: depends on a protocol with is_systemic=True
            for dep in deps:
                dep_name = dep.get("protocol_name", "")
                dep_proto = protocol_map.get(dep_name, {})
                if dep_proto.get("is_systemic", False):
                    flags.append(FLAG_SYSTEMIC_EXPOSURE)
                    break

            # HIGH_EXPOSURE_RATIO: any single dep exposure > threshold * TVL
            if tvl_usd > 0:
                for dep in deps:
                    exp = float(dep.get("exposure_usd", 0.0))
                    if exp / tvl_usd > exposure_ratio_threshold:
                        flags.append(FLAG_HIGH_EXPOSURE_RATIO)
                        break
            elif deps:
                # TVL = 0 but has exposure → always high ratio if exposure > 0
                for dep in deps:
                    if float(dep.get("exposure_usd", 0.0)) > 0:
                        flags.append(FLAG_HIGH_EXPOSURE_RATIO)
                        break

            protocol_results[name] = {
                "in_degree":                  in_degree,
                "out_degree":                 out_degree,
                "contagion_risk_score":       round(contagion_risk_score, 4),
                "systemic_importance_score":  round(systemic_importance_score, 4),
                "contagion_label":            contagion_label,
                "flags":                      flags,
            }

        # --------------- Aggregates ---------------
        contagion_scores   = {n: r["contagion_risk_score"]      for n, r in protocol_results.items()}
        systemic_scores    = {n: r["systemic_importance_score"]  for n, r in protocol_results.items()}

        most_systemic = (
            max(systemic_scores, key=systemic_scores.__getitem__)
            if systemic_scores else None
        )
        most_isolated = (
            min(contagion_scores, key=contagion_scores.__getitem__)
            if contagion_scores else None
        )
        highest_contagion_risk = (
            max(contagion_scores, key=contagion_scores.__getitem__)
            if contagion_scores else None
        )

        total_critical_deps = sum(
            sum(1 for d in p.get("dependencies", []) if d.get("critical", False))
            for p in protocols
        )
        systemic_count = sum(1 for p in protocols if p.get("is_systemic", False))

        aggregates = {
            "most_systemic":              most_systemic,
            "most_isolated":              most_isolated,
            "highest_contagion_risk":     highest_contagion_risk,
            "total_critical_dependencies": total_critical_deps,
            "systemic_count":             systemic_count,
            "protocol_count":             len(protocol_results),
        }

        result = {
            "protocols":  protocol_results,
            "aggregates": aggregates,
        }

        # --------------- Ring-buffer log ---------------
        if not dry_run:
            log_path = _get_data_path(data_dir)
            entries  = _load_log(log_path)
            entries.append({
                "timestamp":                  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "protocol_count":             len(protocols),
                "systemic_count":             systemic_count,
                "total_critical_dependencies": total_critical_deps,
                "most_systemic":              most_systemic,
                "highest_contagion_risk":     highest_contagion_risk,
            })
            _save_log(log_path, entries)

        return result
