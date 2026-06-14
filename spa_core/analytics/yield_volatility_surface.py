"""
MP-690: YieldVolatilitySurface
Build a volatility surface for DeFi yields — mapping volatility across
different protocols and time horizons. Detect anomalous yield spikes.

Pure stdlib, read-only advisory module.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json
import time
import os
import math
from pathlib import Path

DATA_FILE = Path("data/volatility_surface_log.json")
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class YieldObservation:
    protocol: str
    timestamp: float   # unix timestamp
    apy_pct: float


@dataclass
class VolatilityNode:
    protocol: str
    window_days: int          # 7, 14, 30, 90
    mean_apy: float
    std_apy: float
    min_apy: float
    max_apy: float
    apy_range: float          # max - min
    coefficient_of_variation: float   # std / mean (0 if mean == 0)
    is_anomalous: bool        # True if latest obs > mean + 2*std
    volatility_label: str     # LOW / MODERATE / HIGH / EXTREME


@dataclass
class VolatilitySurfaceReport:
    surface_id: str
    protocols: List[str]
    nodes: List[VolatilityNode]
    most_volatile_protocol: str
    least_volatile_protocol: str
    avg_surface_volatility: float     # mean of all nodes' std_apy
    spike_alerts: List[str]           # protocols with is_anomalous=True
    surface_stability: str            # STABLE / UNSTABLE / VOLATILE / CHAOTIC


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _population_std(values: List[float]) -> float:
    """Population standard deviation (not sample)."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


def _volatility_label(cv: float) -> str:
    if cv < 0.05:
        return "LOW"
    if cv < 0.15:
        return "MODERATE"
    if cv < 0.30:
        return "HIGH"
    return "EXTREME"


def _surface_stability(avg_vol: float) -> str:
    if avg_vol < 0.5:
        return "STABLE"
    if avg_vol < 2.0:
        return "UNSTABLE"
    if avg_vol < 5.0:
        return "VOLATILE"
    return "CHAOTIC"


# ---------------------------------------------------------------------------
# Core: build_surface
# ---------------------------------------------------------------------------

WINDOWS = [7, 14, 30, 90]


def build_surface(
    surface_id: str,
    observations: List[YieldObservation],
) -> VolatilitySurfaceReport:
    """
    Build a VolatilitySurfaceReport from a list of YieldObservations.
    """
    if not observations:
        return VolatilitySurfaceReport(
            surface_id=surface_id,
            protocols=[],
            nodes=[],
            most_volatile_protocol="",
            least_volatile_protocol="",
            avg_surface_volatility=0.0,
            spike_alerts=[],
            surface_stability="STABLE",
        )

    # Group by protocol
    by_protocol: Dict[str, List[YieldObservation]] = {}
    for obs in observations:
        by_protocol.setdefault(obs.protocol, []).append(obs)

    protocols = sorted(by_protocol.keys())
    all_nodes: List[VolatilityNode] = []

    for protocol, obs_list in by_protocol.items():
        # Sort by timestamp ascending; latest = last
        sorted_obs = sorted(obs_list, key=lambda o: o.timestamp)
        latest_ts = sorted_obs[-1].timestamp
        latest_apy = sorted_obs[-1].apy_pct

        for window_days in WINDOWS:
            cutoff = latest_ts - window_days * 86400
            window_obs = [o for o in sorted_obs if o.timestamp >= cutoff]

            if len(window_obs) < 2:
                continue  # skip — not enough data

            apys = [o.apy_pct for o in window_obs]
            mean_apy = sum(apys) / len(apys)
            std_apy = _population_std(apys)
            min_apy = min(apys)
            max_apy = max(apys)
            apy_range = max_apy - min_apy
            cv = std_apy / mean_apy if mean_apy > 0 else 0.0
            is_anomalous = latest_apy > (mean_apy + 2 * std_apy)
            label = _volatility_label(cv)

            all_nodes.append(VolatilityNode(
                protocol=protocol,
                window_days=window_days,
                mean_apy=mean_apy,
                std_apy=std_apy,
                min_apy=min_apy,
                max_apy=max_apy,
                apy_range=apy_range,
                coefficient_of_variation=cv,
                is_anomalous=is_anomalous,
                volatility_label=label,
            ))

    # most / least volatile: protocol with highest / lowest max std_apy across windows
    proto_max_std: Dict[str, float] = {}
    for node in all_nodes:
        proto_max_std[node.protocol] = max(
            proto_max_std.get(node.protocol, 0.0), node.std_apy
        )

    if proto_max_std:
        most_volatile = max(proto_max_std, key=lambda p: proto_max_std[p])
        least_volatile = min(proto_max_std, key=lambda p: proto_max_std[p])
    else:
        most_volatile = ""
        least_volatile = ""

    # avg_surface_volatility: mean of all nodes' std_apy
    if all_nodes:
        avg_vol = sum(n.std_apy for n in all_nodes) / len(all_nodes)
    else:
        avg_vol = 0.0

    # spike_alerts
    spike_alerts = [
        f"{n.protocol} spike detected at {n.window_days}d window"
        for n in all_nodes
        if n.is_anomalous
    ]

    stability = _surface_stability(avg_vol)

    return VolatilitySurfaceReport(
        surface_id=surface_id,
        protocols=protocols,
        nodes=all_nodes,
        most_volatile_protocol=most_volatile,
        least_volatile_protocol=least_volatile,
        avg_surface_volatility=avg_vol,
        spike_alerts=spike_alerts,
        surface_stability=stability,
    )


# ---------------------------------------------------------------------------
# Persistence: ring-buffer JSON
# ---------------------------------------------------------------------------

def _report_to_dict(report: VolatilitySurfaceReport) -> dict:
    return {
        "surface_id": report.surface_id,
        "protocols": report.protocols,
        "nodes": [
            {
                "protocol": n.protocol,
                "window_days": n.window_days,
                "mean_apy": n.mean_apy,
                "std_apy": n.std_apy,
                "min_apy": n.min_apy,
                "max_apy": n.max_apy,
                "apy_range": n.apy_range,
                "coefficient_of_variation": n.coefficient_of_variation,
                "is_anomalous": n.is_anomalous,
                "volatility_label": n.volatility_label,
            }
            for n in report.nodes
        ],
        "most_volatile_protocol": report.most_volatile_protocol,
        "least_volatile_protocol": report.least_volatile_protocol,
        "avg_surface_volatility": report.avg_surface_volatility,
        "spike_alerts": report.spike_alerts,
        "surface_stability": report.surface_stability,
        "saved_at": time.time(),
    }


def save_results(report: VolatilitySurfaceReport, data_file: Path = DATA_FILE) -> None:
    """Append report to ring-buffer JSON file (atomic write)."""
    history = load_history(data_file)
    history.append(_report_to_dict(report))
    # keep last MAX_ENTRIES
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]

    data_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load history from JSON file; return [] if missing or corrupt."""
    if not data_file.exists():
        return []
    try:
        return json.loads(data_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-690 YieldVolatilitySurface")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Compute and write to data file")
    parser.add_argument("--data-dir", default="data", help="Override data directory")
    args = parser.parse_args()

    df = Path(args.data_dir) / "volatility_surface_log.json"

    # Build a sample report from empty observations (demo mode)
    report = build_surface("cli-demo", [])
    print(json.dumps(_report_to_dict(report), indent=2))

    if args.run:
        save_results(report, data_file=df)
        print(f"Saved to {df}")
