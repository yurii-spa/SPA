"""
MP-970: DeFiProtocolComposabilityRiskAnalyzer
Analyzes composability (money-lego) risks between DeFi protocols.
Stdlib only, read-only analytics, atomic ring-buffer log (cap 100).
"""

import json
import os
import tempfile
import time
from typing import Dict, List, Optional, Any

_LOG_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'composability_risk_log.json'
)
_LOG_CAP = 100

# Risk label constants
RISK_LABEL_SAFE = 'SAFE_COMPOSITION'
RISK_LABEL_LOW = 'LOW_RISK'
RISK_LABEL_MODERATE = 'MODERATE'
RISK_LABEL_HIGH = 'HIGH_RISK'
RISK_LABEL_SYSTEMIC = 'SYSTEMIC'

# Flag constants
FLAG_DEEP_DEPENDENCY = 'DEEP_DEPENDENCY'
FLAG_NO_CIRCUIT_BREAKER = 'NO_CIRCUIT_BREAKER'
FLAG_SLOW_UNWIND = 'SLOW_UNWIND'
FLAG_PRIOR_ISSUES = 'PRIOR_ISSUES'
FLAG_LARGE_TVL_AT_RISK = 'LARGE_TVL_AT_RISK'

ALL_RISK_LABELS = [
    RISK_LABEL_SAFE,
    RISK_LABEL_LOW,
    RISK_LABEL_MODERATE,
    RISK_LABEL_HIGH,
    RISK_LABEL_SYSTEMIC,
]

VALID_INTEGRATION_TYPES = {
    'collateral', 'oracle', 'liquidity', 'yield_source', 'governance'
}


class DeFiProtocolComposabilityRiskAnalyzer:
    """
    Analyzes composability risks between DeFi protocols (money-lego risk).

    Each integration represents a dependency link between two protocols.
    The analyzer computes contagion_multiplier, fragility_score,
    recovery_score, and net_composability_risk (0-100), then assigns a
    risk_label and flags.

    Read-only analytics — never modifies allocator, risk, or execution domains.
    Ring-buffer log written atomically to data/composability_risk_log.json.
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        'depth_penalty_factor': 15.0,      # pts added per extra depth level
        'issue_penalty_per_issue': 10.0,   # pts added per historical issue
        'issue_penalty_cap': 30.0,         # max issue penalty pts
        'circuit_breaker_pts': 40.0,       # recovery pts for having circuit breaker
        'auto_unwind_pts': 30.0,           # recovery pts for auto unwind
        'fast_unwind_pts': 30.0,           # recovery pts for fast unwind
        'fragility_weight': 0.6,           # weight of fragility in net risk
        'recovery_weight': 0.3,            # weight of (100-recovery) in net risk
        'issue_weight': 0.1,               # weight of issue penalty in net risk
        'large_tvl_threshold_usd': 10_000_000,     # flag threshold
        'slow_unwind_threshold_hours': 72,          # flag threshold
        'deep_dependency_threshold': 3,             # flag threshold (depth > 3)
        'systemic_depth_threshold': 4,              # SYSTEMIC if depth > 4
        'systemic_risk_threshold': 80.0,            # SYSTEMIC if risk > 80
        'high_risk_threshold': 60.0,
        'moderate_threshold': 40.0,
        'low_risk_threshold': 20.0,
    }

    def __init__(self, log_file: Optional[str] = None) -> None:
        self._log_file = log_file or _LOG_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self, integrations: List[Dict], config: Optional[Dict] = None
    ) -> Dict:
        """
        Analyze composability risks across a list of protocol integrations.

        Args:
            integrations: list of integration dicts (see module docstring).
            config: optional config overrides.

        Returns:
            dict with keys: timestamp, integrations_analyzed, results, aggregates.
        """
        cfg = {**self.DEFAULT_CONFIG, **(config or {})}
        log_override = cfg.pop('log_file', None)
        if log_override:
            self._log_file = log_override

        results = [self._analyze_integration(integ, cfg) for integ in integrations]
        aggregates = self._aggregate(results)

        output = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'integrations_analyzed': len(results),
            'results': results,
            'aggregates': aggregates,
        }
        self._append_log(output)
        return output

    # ------------------------------------------------------------------
    # Per-integration analysis
    # ------------------------------------------------------------------

    def _analyze_integration(self, integ: Dict, cfg: Dict) -> Dict:
        name = str(integ.get('name', 'unknown'))
        base_protocol = str(integ.get('base_protocol', ''))
        dependent_protocol = str(integ.get('dependent_protocol', ''))
        integration_type = str(integ.get('integration_type', 'unknown'))
        tvl_at_risk_usd = float(integ.get('tvl_at_risk_usd', 0.0))
        dependency_depth = int(integ.get('dependency_depth', 1))
        audit_score = max(0.0, min(100.0, float(integ.get('base_protocol_audit_score', 50))))
        circuit_breaker = bool(integ.get('circuit_breaker_exists', False))
        auto_unwind = bool(integ.get('auto_unwind_available', False))
        time_to_unwind = float(integ.get('time_to_unwind_hours', 24.0))
        historical_issues = max(0, int(integ.get('historical_issues_count', 0)))

        # --- Derived metrics ---

        # contagion_multiplier: raw $ exposure × depth layers
        contagion_multiplier = tvl_at_risk_usd * dependency_depth

        # fragility_score 0-100: inverse audit weighted by depth penalty
        depth_penalty = (dependency_depth - 1) * cfg['depth_penalty_factor']
        fragility_raw = (100.0 - audit_score) + depth_penalty
        fragility_score = max(0.0, min(100.0, fragility_raw))

        # recovery_score 0-100: cb + auto_unwind + fast_unwind
        cb_pts = cfg['circuit_breaker_pts'] if circuit_breaker else 0.0
        au_pts = cfg['auto_unwind_pts'] if auto_unwind else 0.0
        fast_unwind_ok = time_to_unwind <= cfg['slow_unwind_threshold_hours']
        fu_pts = cfg['fast_unwind_pts'] if fast_unwind_ok else 0.0
        recovery_score = min(100.0, cb_pts + au_pts + fu_pts)

        # issue_penalty: capped additive penalty
        issue_penalty = min(
            float(cfg['issue_penalty_cap']),
            historical_issues * float(cfg['issue_penalty_per_issue'])
        )

        # net_composability_risk 0-100
        net_risk_raw = (
            fragility_score * cfg['fragility_weight']
            + (100.0 - recovery_score) * cfg['recovery_weight']
            + issue_penalty * cfg['issue_weight']
        )
        net_composability_risk = max(0.0, min(100.0, net_risk_raw))

        # --- Risk label ---
        if (
            dependency_depth > cfg['systemic_depth_threshold']
            or net_composability_risk > cfg['systemic_risk_threshold']
        ):
            risk_label = RISK_LABEL_SYSTEMIC
        elif net_composability_risk > cfg['high_risk_threshold']:
            risk_label = RISK_LABEL_HIGH
        elif net_composability_risk > cfg['moderate_threshold']:
            risk_label = RISK_LABEL_MODERATE
        elif net_composability_risk > cfg['low_risk_threshold']:
            risk_label = RISK_LABEL_LOW
        else:
            risk_label = RISK_LABEL_SAFE

        # --- Flags ---
        flags: List[str] = []
        if dependency_depth > cfg['deep_dependency_threshold']:
            flags.append(FLAG_DEEP_DEPENDENCY)
        if not circuit_breaker:
            flags.append(FLAG_NO_CIRCUIT_BREAKER)
        if time_to_unwind > cfg['slow_unwind_threshold_hours']:
            flags.append(FLAG_SLOW_UNWIND)
        if historical_issues > 0:
            flags.append(FLAG_PRIOR_ISSUES)
        if tvl_at_risk_usd > cfg['large_tvl_threshold_usd']:
            flags.append(FLAG_LARGE_TVL_AT_RISK)

        return {
            'name': name,
            'base_protocol': base_protocol,
            'dependent_protocol': dependent_protocol,
            'integration_type': integration_type,
            'tvl_at_risk_usd': tvl_at_risk_usd,
            'dependency_depth': dependency_depth,
            'contagion_multiplier': contagion_multiplier,
            'fragility_score': round(fragility_score, 4),
            'recovery_score': round(recovery_score, 4),
            'net_composability_risk': round(net_composability_risk, 4),
            'risk_label': risk_label,
            'flags': flags,
        }

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, results: List[Dict]) -> Dict:
        if not results:
            return {
                'highest_risk_integration': None,
                'safest_integration': None,
                'total_tvl_at_risk_usd': 0.0,
                'systemic_count': 0,
                'average_risk_score': 0.0,
            }

        by_risk = sorted(results, key=lambda r: r['net_composability_risk'], reverse=True)
        return {
            'highest_risk_integration': by_risk[0]['name'],
            'safest_integration': by_risk[-1]['name'],
            'total_tvl_at_risk_usd': sum(r['tvl_at_risk_usd'] for r in results),
            'systemic_count': sum(1 for r in results if r['risk_label'] == RISK_LABEL_SYSTEMIC),
            'average_risk_score': round(
                sum(r['net_composability_risk'] for r in results) / len(results), 4
            ),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, record: Dict) -> None:
        log_path = os.path.normpath(self._log_file)
        try:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as fh:
                    entries = json.load(fh)
                if not isinstance(entries, list):
                    entries = []
            else:
                entries = []
        except (json.JSONDecodeError, OSError):
            entries = []

        entries.append(record)
        if len(entries) > _LOG_CAP:
            entries = entries[-_LOG_CAP:]

        dir_path = os.path.dirname(log_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path or '.', prefix='.comp_risk_log_tmp_'
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(entries, fh, indent=2)
            os.replace(tmp_path, log_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
