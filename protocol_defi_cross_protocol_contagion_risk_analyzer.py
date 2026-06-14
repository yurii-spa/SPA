"""
MP-1069: Protocol DeFi Cross-Protocol Contagion Risk Analyzer
Analyzes contagion risk arising from cross-protocol dependencies in DeFi.
Pure stdlib, no external dependencies. Read-only / advisory.
"""
import json
import os
import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------

LOG_PATH_DEFAULT = "data/cross_protocol_contagion_risk_log.json"
LOG_CAP_DEFAULT = 100

# Contagion labels (ascending risk)
VALID_LABELS = frozenset([
    "ISOLATED_PROTOCOL",
    "LOW_CONTAGION",
    "MODERATE_INTERCONNECT",
    "HIGH_CONTAGION_RISK",
    "SYSTEMIC_RISK_NODE",
])

# dependency_type → weight for concentration scoring
DEPENDENCY_TYPE_WEIGHT = {
    "liquidity": 1.0,
    "collateral": 1.2,
    "oracle": 1.5,
    "bridge": 1.3,
    "governance": 0.8,
    "yield": 0.7,
    "insurance": 0.9,
    "default": 1.0,
}

# Thresholds for contagion_risk_score → label
_LABEL_THRESHOLDS = [
    (15.0,  "ISOLATED_PROTOCOL"),
    (35.0,  "LOW_CONTAGION"),
    (60.0,  "MODERATE_INTERCONNECT"),
    (80.0,  "HIGH_CONTAGION_RISK"),
]
_LABEL_EXTREME = "SYSTEMIC_RISK_NODE"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiCrossProtocolContagionRiskAnalyzer:
    """
    Analyzes DeFi cross-protocol contagion risk for a given protocol.

    Input fields (all in the *payload* dict passed to ``analyze``):
        protocol_name           str   – name of the protocol under analysis
        tvl_usd                 float – total value locked in the protocol (USD)
        protocols_exposed_to    list  – list of dicts:
                                        {"name": str,
                                         "shared_tvl_usd": float,
                                         "dependency_type": str}
        shared_collateral_assets list – list of str (e.g. ["USDC", "ETH"])
        oracle_providers        list  – list of str (e.g. ["Chainlink", "Pyth"])
        bridge_dependencies     list  – list of str (e.g. ["LayerZero"])
        insurance_coverage_usd  float – insurance coverage available (USD), 0 if none
        circuit_breaker_exists  bool  – whether a circuit breaker / pause mechanism exists

    Output keys:
        protocol_name                str
        contagion_surface_usd        float – total shared TVL across exposed protocols
        dependency_concentration_score float – 0–100 (higher = more concentrated risk)
        contagion_risk_score         float – 0–100 composite risk score
        insured_ratio                float – insurance_coverage_usd / tvl_usd (capped 0–1)
        contagion_label              str   – one of VALID_LABELS
    """

    def __init__(self, log_path: Optional[str] = None, log_cap: int = LOG_CAP_DEFAULT):
        self._log_path = log_path or LOG_PATH_DEFAULT
        self._log_cap = max(1, int(log_cap))

    # ------------------------------------------------------------------
    # Core computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_contagion_surface_usd(protocols_exposed_to: list) -> float:
        """Sum of shared_tvl_usd across all exposed protocols."""
        total = 0.0
        for p in (protocols_exposed_to or []):
            total += _safe_float(p.get("shared_tvl_usd", 0.0))
        return max(0.0, total)

    @staticmethod
    def _compute_dependency_concentration_score(protocols_exposed_to: list) -> float:
        """
        HHI-inspired concentration score over weighted dependency shares.

        For each exposed protocol:
            weight = DEPENDENCY_TYPE_WEIGHT.get(dependency_type, 1.0)
            weighted_share = (shared_tvl_usd × weight) / total_weighted_tvl

        HHI_raw  = Σ weighted_share²
        Score    = HHI_raw × 100    (bounded 0–100)

        Returns 0 when there are no exposed protocols.
        """
        if not protocols_exposed_to:
            return 0.0

        weighted_values = []
        for p in protocols_exposed_to:
            dep_type = (p.get("dependency_type") or "default").strip().lower()
            weight = DEPENDENCY_TYPE_WEIGHT.get(dep_type, DEPENDENCY_TYPE_WEIGHT["default"])
            shared_tvl = _safe_float(p.get("shared_tvl_usd", 0.0))
            weighted_values.append(shared_tvl * weight)

        total_w = sum(weighted_values)
        if total_w <= 0:
            return 0.0

        hhi = sum((v / total_w) ** 2 for v in weighted_values)
        return _clamp(hhi * 100.0)

    @staticmethod
    def _compute_insured_ratio(insurance_coverage_usd: float, tvl_usd: float) -> float:
        """insured_ratio = coverage / tvl, clamped 0–1."""
        if tvl_usd <= 0:
            return 0.0
        return _clamp(insurance_coverage_usd / tvl_usd, 0.0, 1.0)

    def _compute_contagion_risk_score(
        self,
        tvl_usd: float,
        contagion_surface_usd: float,
        dependency_concentration_score: float,
        shared_collateral_assets: list,
        oracle_providers: list,
        bridge_dependencies: list,
        insured_ratio: float,
        circuit_breaker_exists: bool,
    ) -> float:
        """
        Composite contagion risk score (0–100).

        Components and weights:
        1. Exposure ratio (30 pts):
           exposure_ratio = contagion_surface_usd / max(tvl_usd, 1)
           capped at 1.0 → score = exposure_ratio × 30

        2. Dependency concentration (25 pts):
           score = (dependency_concentration_score / 100) × 25

        3. Shared-infrastructure breadth (25 pts):
           n_shared_collateral  (capped at 5) × 2.5  ← up to 12.5
           n_oracle_providers   (capped at 3) × 2.5  ← up to 7.5
           n_bridge_deps        (capped at 5) × 1.0  ← up to 5

        4. Mitigants (−20 pts max):
           circuit_breaker: −10
           insurance (insured_ratio): −10 × insured_ratio

        Final score is clamped to [0, 100].
        """
        # 1. Exposure ratio component
        exposure_ratio = _safe_float(contagion_surface_usd) / max(_safe_float(tvl_usd), 1.0)
        exposure_score = _clamp(exposure_ratio, 0.0, 1.0) * 30.0

        # 2. Concentration component
        concentration_score = (dependency_concentration_score / 100.0) * 25.0

        # 3. Shared infrastructure breadth
        n_collateral = min(len(shared_collateral_assets or []), 5)
        n_oracles = min(len(oracle_providers or []), 3)
        n_bridges = min(len(bridge_dependencies or []), 5)

        breadth_score = n_collateral * 2.5 + n_oracles * 2.5 + n_bridges * 1.0

        # 4. Mitigants (reduce risk)
        cb_credit = 10.0 if circuit_breaker_exists else 0.0
        insurance_credit = 10.0 * _clamp(insured_ratio, 0.0, 1.0)
        mitigation = cb_credit + insurance_credit

        raw = exposure_score + concentration_score + breadth_score - mitigation
        return round(_clamp(raw, 0.0, 100.0), 4)

    @staticmethod
    def _assign_label(contagion_risk_score: float) -> str:
        for threshold, label in _LABEL_THRESHOLDS:
            if contagion_risk_score < threshold:
                return label
        return _LABEL_EXTREME

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        """Atomically append entry to ring-buffer log (capped at log_cap)."""
        entries: list = []
        log_path = self._log_path
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        entries = data
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(entry)
        entries = entries[-self._log_cap:]

        dir_path = os.path.dirname(log_path) or "."
        os.makedirs(dir_path, exist_ok=True)
        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, payload: dict) -> dict:
        """
        Analyze cross-protocol contagion risk for a single protocol.

        Parameters
        ----------
        payload : dict
            Must include the input fields documented in the class docstring.

        Returns
        -------
        dict with keys: protocol_name, contagion_surface_usd,
            dependency_concentration_score, contagion_risk_score,
            insured_ratio, contagion_label.
        """
        protocol_name = payload.get("protocol_name", "")
        tvl_usd = _safe_float(payload.get("tvl_usd", 0.0))
        protocols_exposed_to = payload.get("protocols_exposed_to") or []
        shared_collateral_assets = payload.get("shared_collateral_assets") or []
        oracle_providers = payload.get("oracle_providers") or []
        bridge_dependencies = payload.get("bridge_dependencies") or []
        insurance_coverage_usd = _safe_float(payload.get("insurance_coverage_usd", 0.0))
        circuit_breaker_exists = bool(payload.get("circuit_breaker_exists", False))

        contagion_surface_usd = self._compute_contagion_surface_usd(protocols_exposed_to)
        dep_conc_score = self._compute_dependency_concentration_score(protocols_exposed_to)
        insured_ratio = self._compute_insured_ratio(insurance_coverage_usd, tvl_usd)

        contagion_risk_score = self._compute_contagion_risk_score(
            tvl_usd=tvl_usd,
            contagion_surface_usd=contagion_surface_usd,
            dependency_concentration_score=dep_conc_score,
            shared_collateral_assets=shared_collateral_assets,
            oracle_providers=oracle_providers,
            bridge_dependencies=bridge_dependencies,
            insured_ratio=insured_ratio,
            circuit_breaker_exists=circuit_breaker_exists,
        )
        label = self._assign_label(contagion_risk_score)

        result = {
            "protocol_name": protocol_name,
            "contagion_surface_usd": round(contagion_surface_usd, 4),
            "dependency_concentration_score": round(dep_conc_score, 4),
            "contagion_risk_score": contagion_risk_score,
            "insured_ratio": round(insured_ratio, 6),
            "contagion_label": label,
        }

        log_entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "protocol_name": protocol_name,
            "contagion_surface_usd": result["contagion_surface_usd"],
            "contagion_risk_score": result["contagion_risk_score"],
            "contagion_label": result["contagion_label"],
        }
        self._append_log(log_entry)
        return result

    def analyze_batch(self, payloads: list) -> list:
        """Analyze cross-protocol contagion risk for a list of protocol payloads."""
        return [self.analyze(p) for p in (payloads or [])]
