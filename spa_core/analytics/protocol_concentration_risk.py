"""Protocol Concentration Risk Analyzer (MP-603).

Обнаруживает чрезмерную концентрацию на уровне протоколов (smart contract risk).
Группирует адаптеры по протоколу (aave, morpho, compound, sky/maker и т.п.)
и вычисляет exposure к каждому.

Проблема: если портфель содержит aave_v3_ethereum, aave_v3_arbitrum,
aave_v3_base, aave_v3_optimism, aave_v3_polygon — это 5 разных адаптеров,
но все они используют смарт-контракты Aave. Уязвимость/баг в Aave затронет
все эти позиции одновременно.

Design constraints
------------------
* Pure stdlib — no external deps (no requests / numpy / pandas / web3 / LLM SDK).
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.protocol_concentration_risk --check
    python3 -m spa_core.analytics.protocol_concentration_risk --run
    python3 -m spa_core.analytics.protocol_concentration_risk --run --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "concentration_risk.json"
RING_BUFFER_MAX = 30

# Top-level keys in adapter_status.json that are NOT adapter entries
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode", "live_apy_enabled",
    "mev_protection", "adapters", "morpho_steakhouse", "base_gas_monitor",
})

# ---------------------------------------------------------------------------
# Protocol map: adapter prefix → canonical protocol name
# ---------------------------------------------------------------------------

# Маппинг prefix → canonical protocol name.
# Порядок важен для prefix-matching (более длинные/специфичные — первыми).
PROTOCOL_MAP: Dict[str, str] = {
    # Aave family
    "aave": "aave",
    # Morpho family
    "morpho": "morpho",
    # Compound family
    "compound": "compound",
    # MakerDAO / Sky / Spark family
    "spark": "makerdao",
    "sky": "makerdao",
    "sdai": "makerdao",
    "susds": "makerdao",
    # Frax family
    "sfrax": "frax",
    "frax": "frax",
    # Mountain Protocol
    "wusdm": "mountain",
    # Angle Protocol
    "stusd": "angle",
    # Curve
    "scrvusd": "curve",
    # Radiant Capital
    "radiant": "radiant",
    # Pendle Finance
    "pendle": "pendle",
    # Euler Finance
    "euler": "euler",
    # Yearn Finance
    "yearn": "yearn",
    # Maple Finance
    "maple": "maple",
    # Moonwell Finance
    "moonwell": "moonwell",
    # Fluid Protocol
    "fluid": "fluid",
    # Ethena
    "susde": "ethena",
    # Extra Finance
    "extra": "extra_finance",
}

# Sorted by key length descending so longer prefixes match first
_SORTED_PROTOCOL_KEYS = sorted(PROTOCOL_MAP.keys(), key=len, reverse=True)

# ---------------------------------------------------------------------------
# Safe helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float:
    """Coerce to finite float; return 0.0 on failure."""
    if isinstance(val, bool):
        return 0.0
    try:
        f = float(val)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _extract_apy(data: Dict[str, Any]) -> float:
    """Extract APY % from an adapter data dict."""
    for key in ("apy_pct", "apy"):
        val = data.get(key)
        if not isinstance(val, bool) and isinstance(val, (int, float)):
            f = float(val)
            if math.isfinite(f) and f > 0:
                return f
    mock = data.get("mock_apy")
    if isinstance(mock, dict):
        for chain_data in mock.values():
            if isinstance(chain_data, dict):
                for apy_val in chain_data.values():
                    if not isinstance(apy_val, bool) and isinstance(apy_val, (int, float)):
                        f = float(apy_val)
                        if math.isfinite(f) and f > 0:
                            return f
    return 0.0


def _extract_tvl(data: Dict[str, Any]) -> float:
    """Extract TVL in USD from an adapter data dict."""
    for key in ("tvl_usd", "tvl"):
        val = data.get(key)
        if not isinstance(val, bool) and isinstance(val, (int, float)):
            f = float(val)
            if math.isfinite(f) and f >= 0:
                return f
    return 0.0


def _extract_chains(data: Dict[str, Any]) -> List[str]:
    """Extract chains list from an adapter data dict."""
    chains = data.get("chains")
    if isinstance(chains, list) and chains:
        return [str(c) for c in chains if c]
    chain = data.get("chain") or data.get("network")
    if isinstance(chain, str) and chain:
        return [chain]
    return []


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProtocolExposure:
    """Exposure to a single underlying protocol (smart contract risk).

    Attributes
    ----------
    protocol           : Canonical protocol name (e.g. "aave", "morpho").
    adapter_ids        : List of adapter IDs that share this protocol.
    adapter_count      : Number of adapters sharing this protocol.
    total_tvl_usd      : Aggregate TVL across all adapters of this protocol.
    avg_apy_pct        : Average APY across all adapters of this protocol.
    chains             : Unique chains where this protocol is present.
    portfolio_weight_pct: % of total portfolio TVL concentrated in this protocol.
    risk_level         : "LOW" / "MEDIUM" / "HIGH" / "CRITICAL".
    risk_note          : Human-readable explanation of the risk.
    """

    protocol: str
    adapter_ids: List[str]
    adapter_count: int
    total_tvl_usd: float
    avg_apy_pct: float
    chains: List[str]
    portfolio_weight_pct: float
    risk_level: str
    risk_note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConcentrationReport:
    """Full protocol concentration risk snapshot.

    Attributes
    ----------
    generated_at             : ISO-8601 UTC timestamp.
    total_protocols          : Number of distinct protocols identified.
    total_adapters           : Total number of adapters analysed.
    total_tvl_usd            : Total TVL across all adapters.
    exposures                : ProtocolExposure list, sorted desc by portfolio_weight_pct.
    concentration_score      : HHI = Σ(weight_i/100)², 0=diverse, 1=single protocol.
    top_protocol             : Protocol with highest portfolio_weight_pct.
    top_protocol_weight_pct  : Weight of the top protocol.
    warnings                 : Auto-generated warning strings for HIGH/CRITICAL exposures.
    overall_risk             : "LOW" / "MEDIUM" / "HIGH".
    """

    generated_at: str
    total_protocols: int
    total_adapters: int
    total_tvl_usd: float
    exposures: List[ProtocolExposure] = field(default_factory=list)
    concentration_score: float = 0.0
    top_protocol: str = ""
    top_protocol_weight_pct: float = 0.0
    warnings: List[str] = field(default_factory=list)
    overall_risk: str = "LOW"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# ProtocolConcentrationRisk
# ---------------------------------------------------------------------------


class ProtocolConcentrationRisk:
    """Protocol-level concentration risk analyzer.

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing ``adapter_status.json`` and where
        ``concentration_risk.json`` will be written.
        Defaults to the repo ``data/`` directory.
    """

    # Concentration thresholds for a single protocol (% of total portfolio)
    MEDIUM_THRESHOLD_PCT: float = 25.0   # >25% → MEDIUM
    HIGH_THRESHOLD_PCT: float = 40.0     # >40% → HIGH
    CRITICAL_THRESHOLD_PCT: float = 60.0  # >60% → CRITICAL

    # Minimum number of adapters on different chains for cross-chain warning
    CROSS_CHAIN_MIN: int = 3

    # Safe allocation caps by risk level (max weight %)
    _RISK_CAPS: Dict[str, float] = {
        "LOW": 40.0,
        "MEDIUM": 30.0,
        "HIGH": 20.0,
        "CRITICAL": 10.0,
    }

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_adapter_data(self) -> Dict[str, Dict[str, Any]]:
        """Load adapter data from ``adapter_status.json``.

        Returns ``{adapter_id: data_dict}`` for every adapter entry.
        Non-adapter metadata keys are skipped via ``_SKIP_KEYS``.
        The ``"adapters"`` array is also processed — each entry keyed by its
        ``protocol_key`` (hyphens normalised to underscores).

        Returns ``{}`` when the file is missing or unreadable.
        """
        path = self.data_dir / "adapter_status.json"
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}

        result: Dict[str, Dict[str, Any]] = {}

        # Top-level protocol entries (must have a "tier" field)
        for key, val in raw.items():
            if key in _SKIP_KEYS:
                continue
            if not isinstance(val, dict):
                continue
            if "tier" not in val:
                continue
            result[key] = val

        # "adapters" array entries
        adapters_list = raw.get("adapters")
        if isinstance(adapters_list, list):
            for item in adapters_list:
                if not isinstance(item, dict):
                    continue
                protocol_key = item.get("protocol_key") or item.get("adapter_id")
                if not protocol_key or not isinstance(protocol_key, str):
                    continue
                normalized = protocol_key.replace("-", "_")
                for k in (protocol_key, normalized):
                    if k not in result:
                        result[k] = item

        return result

    # -----------------------------------------------------------------------
    # Protocol inference
    # -----------------------------------------------------------------------

    def infer_protocol(self, adapter_id: str) -> str:
        """Infer canonical protocol name from adapter_id using PROTOCOL_MAP.

        Matching strategy:
        1. Longest prefix match from PROTOCOL_MAP (sorted desc by length).
        2. Fallback: first word before ``_`` or ``-``.

        Returns ``"unknown"`` for empty or unrecognised inputs.

        Examples
        --------
        >>> r = ProtocolConcentrationRisk()
        >>> r.infer_protocol("aave_v3_arbitrum")
        'aave'
        >>> r.infer_protocol("morpho_blue_base")
        'morpho'
        >>> r.infer_protocol("compound_v3")
        'compound'
        >>> r.infer_protocol("spark_susds")
        'makerdao'
        >>> r.infer_protocol("unknown_protocol_xyz")
        'unknown_protocol'
        """
        if not adapter_id or not isinstance(adapter_id, str):
            return "unknown"

        # Normalise: lowercase, replace hyphens with underscores
        aid_lower = adapter_id.lower().replace("-", "_")

        # Prefix match (longest first)
        for prefix in _SORTED_PROTOCOL_KEYS:
            if aid_lower == prefix or aid_lower.startswith(prefix + "_"):
                return PROTOCOL_MAP[prefix]

        # Fallback: first segment before any _ or -
        for sep in ("_", "-"):
            idx = aid_lower.find(sep)
            if idx > 0:
                return aid_lower[:idx]

        # No separator found → return the whole normalised id
        return aid_lower if aid_lower else "unknown"

    # -----------------------------------------------------------------------
    # Grouping
    # -----------------------------------------------------------------------

    def group_by_protocol(
        self, adapter_data: Dict[str, Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """Group adapter IDs by their inferred protocol.

        Parameters
        ----------
        adapter_data : dict
            ``{adapter_id: data_dict}`` as returned by :meth:`load_adapter_data`.

        Returns
        -------
        dict
            ``{protocol: [adapter_id, ...]}`` — unrecognised adapters land in
            ``"unknown"``.
        """
        groups: Dict[str, List[str]] = {}
        for adapter_id in adapter_data:
            protocol = self.infer_protocol(adapter_id)
            groups.setdefault(protocol, []).append(adapter_id)
        return groups

    # -----------------------------------------------------------------------
    # Exposure computation
    # -----------------------------------------------------------------------

    def compute_exposure(
        self,
        protocol: str,
        adapter_ids: List[str],
        adapter_data: Dict[str, Dict[str, Any]],
        total_tvl: float,
    ) -> ProtocolExposure:
        """Compute ProtocolExposure for one protocol group.

        Parameters
        ----------
        protocol     : Canonical protocol name.
        adapter_ids  : Adapter IDs belonging to this protocol.
        adapter_data : Full adapter data dict.
        total_tvl    : Total TVL across all adapters (for weight calculation).

        Returns
        -------
        ProtocolExposure
        """
        tvl_sum = 0.0
        apy_values: List[float] = []
        chains_seen: List[str] = []

        for aid in adapter_ids:
            data = adapter_data.get(aid) or {}
            tvl_sum += _extract_tvl(data)
            apy = _extract_apy(data)
            if apy > 0:
                apy_values.append(apy)
            for ch in _extract_chains(data):
                if ch not in chains_seen:
                    chains_seen.append(ch)

        avg_apy = sum(apy_values) / len(apy_values) if apy_values else 0.0
        n_adapters = len(adapter_ids)
        n_chains = len(chains_seen)

        # Portfolio weight
        weight = (tvl_sum / total_tvl * 100.0) if total_tvl > 0 else 0.0
        weight = round(weight, 4)

        # Risk level
        if weight >= self.CRITICAL_THRESHOLD_PCT:
            risk_level = "CRITICAL"
        elif weight >= self.HIGH_THRESHOLD_PCT:
            risk_level = "HIGH"
        elif weight >= self.MEDIUM_THRESHOLD_PCT:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # Risk note
        if n_adapters == 1:
            note = f"1 adapter uses {protocol} smart contracts"
        elif n_chains >= self.CROSS_CHAIN_MIN:
            note = (
                f"{n_adapters} adapters on {n_chains} chains share "
                f"{protocol} smart contracts — cross-chain smart contract risk"
            )
        else:
            note = (
                f"{n_adapters} adapters share {protocol} smart contracts"
            )

        return ProtocolExposure(
            protocol=protocol,
            adapter_ids=sorted(adapter_ids),
            adapter_count=n_adapters,
            total_tvl_usd=round(tvl_sum, 2),
            avg_apy_pct=round(avg_apy, 4),
            chains=chains_seen,
            portfolio_weight_pct=weight,
            risk_level=risk_level,
            risk_note=note,
        )

    # -----------------------------------------------------------------------
    # HHI
    # -----------------------------------------------------------------------

    def compute_hhi(self, exposures: List[ProtocolExposure]) -> float:
        """Compute Herfindahl-Hirschman Index for protocol concentration.

        Formula::

            HHI = Σ (portfolio_weight_pct_i / 100) ²

        Returns 0.0 for empty input; 1.0 when a single protocol = 100%.
        """
        if not exposures:
            return 0.0
        hhi = sum((e.portfolio_weight_pct / 100.0) ** 2 for e in exposures)
        return round(min(1.0, max(0.0, hhi)), 6)

    # -----------------------------------------------------------------------
    # Report generation
    # -----------------------------------------------------------------------

    def generate_report(
        self,
        adapter_data: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> ConcentrationReport:
        """Generate a full ConcentrationReport.

        Parameters
        ----------
        adapter_data : dict, optional
            Pre-loaded adapter data.  When ``None``, calls
            :meth:`load_adapter_data`.

        Returns
        -------
        ConcentrationReport
        """
        now = datetime.now(timezone.utc).isoformat()

        if adapter_data is None:
            adapter_data = self.load_adapter_data()

        if not adapter_data:
            return ConcentrationReport(
                generated_at=now,
                total_protocols=0,
                total_adapters=0,
                total_tvl_usd=0.0,
            )

        # Aggregate total TVL across all adapters
        total_tvl = sum(_extract_tvl(d) for d in adapter_data.values())

        # Group adapters by protocol
        groups = self.group_by_protocol(adapter_data)

        # Compute per-protocol exposure
        exposures: List[ProtocolExposure] = []
        for protocol, ids in groups.items():
            exp = self.compute_exposure(protocol, ids, adapter_data, total_tvl)
            exposures.append(exp)

        # Sort descending by portfolio_weight_pct
        exposures.sort(key=lambda e: e.portfolio_weight_pct, reverse=True)

        # HHI concentration score
        hhi = self.compute_hhi(exposures)

        # Top protocol
        top_protocol = exposures[0].protocol if exposures else ""
        top_weight = exposures[0].portfolio_weight_pct if exposures else 0.0

        # Warnings
        warnings: List[str] = []
        for exp in exposures:
            if exp.risk_level == "CRITICAL":
                warnings.append(
                    f"{exp.protocol.title()} exposure {exp.portfolio_weight_pct:.1f}% "
                    f"CRITICAL (>={self.CRITICAL_THRESHOLD_PCT:.0f}% threshold) — "
                    f"{exp.adapter_count} adapters on {len(exp.chains)} chain(s)"
                )
            elif exp.risk_level == "HIGH":
                warnings.append(
                    f"{exp.protocol.title()} exposure {exp.portfolio_weight_pct:.1f}% "
                    f"exceeds {self.HIGH_THRESHOLD_PCT:.0f}% threshold — "
                    f"{exp.adapter_count} adapters on {len(exp.chains)} chain(s)"
                )
            # Cross-chain warning (≥CROSS_CHAIN_MIN chains, even at MEDIUM)
            if (
                len(exp.chains) >= self.CROSS_CHAIN_MIN
                and exp.risk_level in ("MEDIUM", "HIGH", "CRITICAL")
            ):
                warnings.append(
                    f"{exp.protocol.title()} spans {len(exp.chains)} chains "
                    f"({', '.join(sorted(exp.chains))}) — "
                    f"single bug affects all positions"
                )

        # Deduplicate warnings preserving order
        seen: set = set()
        deduped: List[str] = []
        for w in warnings:
            if w not in seen:
                seen.add(w)
                deduped.append(w)
        warnings = deduped

        # Overall risk: highest risk_level across all exposures
        risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        if exposures:
            overall = max(exposures, key=lambda e: risk_order.get(e.risk_level, 0))
            overall_risk = overall.risk_level
            # CRITICAL maps to HIGH in the top-level field (CRITICAL already flagged in warnings)
            if overall_risk == "CRITICAL":
                overall_risk = "HIGH"
        else:
            overall_risk = "LOW"

        return ConcentrationReport(
            generated_at=now,
            total_protocols=len(exposures),
            total_adapters=len(adapter_data),
            total_tvl_usd=round(total_tvl, 2),
            exposures=exposures,
            concentration_score=hhi,
            top_protocol=top_protocol,
            top_protocol_weight_pct=round(top_weight, 4),
            warnings=warnings,
            overall_risk=overall_risk,
        )

    # -----------------------------------------------------------------------
    # Safe allocation caps
    # -----------------------------------------------------------------------

    def get_safe_allocation_caps(
        self,
        adapter_data: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """Return recommended maximum weight (%) for each identified protocol.

        Caps by risk level:
        - LOW      → 40%
        - MEDIUM   → 30%
        - HIGH     → 20%
        - CRITICAL → 10%

        Parameters
        ----------
        adapter_data : dict, optional
            Pre-loaded adapter data.  When ``None``, calls
            :meth:`load_adapter_data`.

        Returns
        -------
        dict
            ``{protocol: max_weight_pct}``
        """
        report = self.generate_report(adapter_data)
        return {
            exp.protocol: self._RISK_CAPS.get(exp.risk_level, 30.0)
            for exp in report.exposures
        }

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Generate and atomically save the concentration report.

        Maintains a ring-buffer of the last :data:`RING_BUFFER_MAX` (30)
        snapshots inside the output file.

        Parameters
        ----------
        output_path : str, optional
            Full file path for the JSON output.  Defaults to
            ``{data_dir}/concentration_risk.json``.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if output_path is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.data_dir / OUTPUT_FILENAME
        else:
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing snapshots for ring-buffer
        snapshots: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    old = existing.get("snapshots", [])
                    if isinstance(old, list):
                        snapshots = [s for s in old if isinstance(s, dict)]
            except (ValueError, OSError):
                pass

        report_dict = self.to_dict()
        snapshots.append(report_dict)
        snapshots = snapshots[-RING_BUFFER_MAX:]

        out: Dict[str, Any] = {
            "schema_version": "1.0",
            "source": "protocol_concentration_risk",
            "last_updated": report_dict.get("generated_at", ""),
            "latest": report_dict,
            "snapshots": snapshots,
        }

        # Atomic write: tmp → os.replace
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(out_path.parent),
            prefix=f".{OUTPUT_FILENAME}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, str(out_path))
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(self) -> str:
        """Format a Telegram-ready summary message (≤1500 chars).

        Includes: overall risk, concentration score (HHI), top-3 exposed
        protocols, and any active warnings.
        """
        report = self.generate_report()
        lines: List[str] = [
            "🔬 Protocol Concentration Risk Report",
            (
                f"⚠️ Overall Risk: {report.overall_risk} | "
                f"HHI: {report.concentration_score:.4f}"
            ),
            f"📊 Protocols: {report.total_protocols} | Adapters: {report.total_adapters}",
            f"💰 Total TVL: ${report.total_tvl_usd:,.0f}",
            "",
            "🏆 Top Protocol Exposures:",
        ]
        for exp in report.exposures[:3]:
            lines.append(
                f"  {exp.protocol}: {exp.portfolio_weight_pct:.1f}% "
                f"[{exp.risk_level}] — {exp.adapter_count} adapters, "
                f"{len(exp.chains)} chain(s)"
            )
        if report.warnings:
            lines.append("")
            lines.append("🚨 Warnings:")
            for w in report.warnings[:5]:
                lines.append(f"  • {w}")
        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the current concentration report."""
        report = self.generate_report()
        return {
            "generated_at": report.generated_at,
            "total_protocols": report.total_protocols,
            "total_adapters": report.total_adapters,
            "total_tvl_usd": report.total_tvl_usd,
            "concentration_score": report.concentration_score,
            "top_protocol": report.top_protocol,
            "top_protocol_weight_pct": report.top_protocol_weight_pct,
            "overall_risk": report.overall_risk,
            "warnings": report.warnings,
            "exposures": [
                {
                    "protocol": e.protocol,
                    "adapter_ids": e.adapter_ids,
                    "adapter_count": e.adapter_count,
                    "total_tvl_usd": e.total_tvl_usd,
                    "avg_apy_pct": e.avg_apy_pct,
                    "chains": e.chains,
                    "portfolio_weight_pct": e.portfolio_weight_pct,
                    "risk_level": e.risk_level,
                    "risk_note": e.risk_note,
                }
                for e in report.exposures
            ],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPA Protocol Concentration Risk Analyzer (MP-603) — "
            "smart contract exposure HHI, MEDIUM/HIGH/CRITICAL thresholds."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print report without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/concentration_risk.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    analyzer = ProtocolConcentrationRisk(data_path=args.data_dir)
    report = analyzer.generate_report()

    print(f"Generated:          {report.generated_at}")
    print(f"Total protocols:    {report.total_protocols}")
    print(f"Total adapters:     {report.total_adapters}")
    print(f"Total TVL:          ${report.total_tvl_usd:,.2f}")
    print(f"Concentration HHI:  {report.concentration_score:.6f}")
    print(f"Top protocol:       {report.top_protocol} ({report.top_protocol_weight_pct:.2f}%)")
    print(f"Overall risk:       {report.overall_risk}")
    print("")

    if report.exposures:
        print("Protocol Exposures (all):")
        for exp in report.exposures:
            chains_str = ", ".join(exp.chains) if exp.chains else "—"
            print(
                f"  {exp.protocol:<20s}  "
                f"weight={exp.portfolio_weight_pct:>6.2f}%  "
                f"[{exp.risk_level:<8s}]  "
                f"adapters={exp.adapter_count}  "
                f"chains={chains_str}"
            )
    print("")

    if report.warnings:
        print("Warnings:")
        for w in report.warnings:
            print(f"  ⚠  {w}")
    else:
        print("No warnings.")

    caps = analyzer.get_safe_allocation_caps()
    if caps:
        print("")
        print("Safe Allocation Caps:")
        for protocol, cap in sorted(caps.items(), key=lambda x: -x[1]):
            print(f"  {protocol:<20s}  max={cap:.0f}%")

    if args.run:
        path = analyzer.save_report()
        print(f"\nSaved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
