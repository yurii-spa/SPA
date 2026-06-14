"""
MP-959: Protocol Smart Contract Complexity Scorer
Scores smart-contract complexity as a proxy for audit risk.
Pure stdlib, no external dependencies.
"""
import json
import os
import datetime
from typing import Optional

# Normalization maxima for raw complexity components
_LOC_MAX = 10_000
_FUNC_MAX = 200
_EXT_CALL_MAX = 50
_INHERIT_MAX = 10
_ASSEMBLY_MAX = 20

# Component weights (must sum to 1.0)
_COMPLEXITY_WEIGHTS = {
    'loc': 0.20,
    'funcs': 0.30,
    'ext_calls': 0.20,
    'inherit': 0.15,
    'assembly': 0.15,
}

# Proxy-pattern base upgrade risk (0–100)
_PROXY_RISK = {
    'none': 0,
    'transparent': 30,
    'uups': 40,
    'beacon': 50,
    'diamond': 80,
}

# Upgrade-mechanism base risk (0–100)
_UPGRADE_MECHANISM_RISK = {
    'none': 0,
    'timelock': 20,
    'dao': 30,
    'multisig': 40,
}

# Risk label boundaries (net_risk_score ranges)
_RISK_LABEL_THRESHOLDS = [
    ('SIMPLE', 0.0, 20.0),
    ('MODERATE', 20.0, 40.0),
    ('COMPLEX', 40.0, 60.0),
    ('VERY_COMPLEX', 60.0, 80.0),
    ('CRITICAL_COMPLEXITY', 80.0, float('inf')),
]

DEFAULT_CONFIG = {
    'loc_max': _LOC_MAX,
    'func_max': _FUNC_MAX,
    'ext_call_max': _EXT_CALL_MAX,
    'inherit_max': _INHERIT_MAX,
    'assembly_max': _ASSEMBLY_MAX,
    'assembly_heavy_threshold': 10,
    'oracle_dependent_threshold': 2,
    'battle_tested_days': 365,
    'under_audited_complexity_threshold': 60,
    'under_audited_audit_count': 2,
    'log_path': 'data/contract_complexity_log.json',
    'log_cap': 100,
}

VALID_RISK_LABELS = {
    'SIMPLE', 'MODERATE', 'COMPLEX', 'VERY_COMPLEX', 'CRITICAL_COMPLEXITY'
}

VALID_FLAGS = {
    'PROXY_RISK', 'ASSEMBLY_HEAVY', 'ORACLE_DEPENDENT',
    'BATTLE_TESTED', 'UNDER_AUDITED', 'BUG_BOUNTY_ACTIVE'
}


class ProtocolSmartContractComplexityScorer:
    """
    Scores DeFi smart-contract complexity and audit risk.

    complexity_score (0–100):
        weighted sum of normalised:
          LOC×0.20 + function_count×0.30 + external_calls×0.20
          + inheritance_depth×0.15 + assembly_blocks×0.15

    upgrade_risk_score (0–100):
        proxy_base×0.60 + upgrade_mechanism_base×0.40
        (+20 penalty when proxy exists but no protective upgrade mechanism)

    audit_coverage_score (0–100, inverse risk):
        audit_count×25 (capped 100) + bug_bounty bonus (up to 20)

    net_risk_score (0–100):
        complexity_score + upgrade_risk_score – audit_coverage_score, clamped to [0, 100]
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_risk_label(self, net_risk_score: float) -> str:
        """Return SIMPLE / MODERATE / COMPLEX / VERY_COMPLEX / CRITICAL_COMPLEXITY."""
        for label, lo, hi in _RISK_LABEL_THRESHOLDS:
            if lo <= net_risk_score < hi:
                return label
        return 'CRITICAL_COMPLEXITY'

    def _score_contract(self, contract: dict) -> dict:
        cfg = self.config

        name = contract.get('name', 'UNKNOWN')
        protocol = contract.get('protocol', 'UNKNOWN')
        loc = float(contract.get('lines_of_code', 0) or 0)
        func_count = float(contract.get('function_count', 0) or 0)
        ext_call_count = float(contract.get('external_call_count', 0) or 0)
        inheritance_depth = float(contract.get('inheritance_depth', 0) or 0)
        proxy_pattern = str(contract.get('proxy_pattern', 'none') or 'none').lower()
        upgrade_mechanism = str(contract.get('upgrade_mechanism', 'none') or 'none').lower()
        oracle_dependencies = int(contract.get('oracle_dependencies', 0) or 0)
        cross_contract_calls = int(contract.get('cross_contract_calls', 0) or 0)
        assembly_blocks_count = float(contract.get('assembly_blocks_count', 0) or 0)
        audit_count = int(contract.get('audit_count', 0) or 0)
        bug_bounty_usd = float(contract.get('bug_bounty_usd', 0) or 0)
        days_live = int(contract.get('days_live', 0) or 0)
        critical_bugs_found = int(contract.get('critical_bugs_found', 0) or 0)

        # --- complexity_score (0-100) ---
        loc_max = float(cfg.get('loc_max', _LOC_MAX))
        func_max = float(cfg.get('func_max', _FUNC_MAX))
        ext_max = float(cfg.get('ext_call_max', _EXT_CALL_MAX))
        inherit_max = float(cfg.get('inherit_max', _INHERIT_MAX))
        assembly_max = float(cfg.get('assembly_max', _ASSEMBLY_MAX))

        norm_loc = min(1.0, loc / loc_max) if loc_max > 0 else 0.0
        norm_funcs = min(1.0, func_count / func_max) if func_max > 0 else 0.0
        norm_ext = min(1.0, ext_call_count / ext_max) if ext_max > 0 else 0.0
        norm_inherit = min(1.0, inheritance_depth / inherit_max) if inherit_max > 0 else 0.0
        norm_assembly = min(1.0, assembly_blocks_count / assembly_max) if assembly_max > 0 else 0.0

        complexity_score = (
            norm_loc * _COMPLEXITY_WEIGHTS['loc']
            + norm_funcs * _COMPLEXITY_WEIGHTS['funcs']
            + norm_ext * _COMPLEXITY_WEIGHTS['ext_calls']
            + norm_inherit * _COMPLEXITY_WEIGHTS['inherit']
            + norm_assembly * _COMPLEXITY_WEIGHTS['assembly']
        ) * 100.0
        complexity_score = round(min(100.0, max(0.0, complexity_score)), 4)

        # --- upgrade_risk_score (0-100) ---
        proxy_base = float(_PROXY_RISK.get(proxy_pattern, 20))
        upgrade_base = float(_UPGRADE_MECHANISM_RISK.get(upgrade_mechanism, 30))
        upgrade_risk_score = proxy_base * 0.60 + upgrade_base * 0.40

        # Extra penalty: proxy exists but no protective mechanism (none)
        if proxy_pattern != 'none' and upgrade_mechanism == 'none':
            upgrade_risk_score = min(100.0, upgrade_risk_score + 20.0)

        upgrade_risk_score = round(min(100.0, max(0.0, upgrade_risk_score)), 4)

        # --- audit_coverage_score (0-100, higher = safer) ---
        audit_base = min(100.0, audit_count * 25.0)
        bounty_bonus = min(20.0, (bug_bounty_usd / 100_000.0) * 10.0)
        audit_coverage_score = round(min(100.0, max(0.0, audit_base + bounty_bonus)), 4)

        # --- net_risk_score (0-100) ---
        net_risk_score = complexity_score + upgrade_risk_score - audit_coverage_score
        net_risk_score = round(min(100.0, max(0.0, net_risk_score)), 4)

        # --- risk label ---
        risk_label = self._get_risk_label(net_risk_score)

        # --- flags ---
        flags = []

        # PROXY_RISK: proxy exists and upgrade mechanism is not timelock/dao
        if proxy_pattern != 'none' and upgrade_mechanism not in ('timelock', 'dao'):
            flags.append('PROXY_RISK')

        # ASSEMBLY_HEAVY
        if assembly_blocks_count > cfg['assembly_heavy_threshold']:
            flags.append('ASSEMBLY_HEAVY')

        # ORACLE_DEPENDENT
        if oracle_dependencies > cfg['oracle_dependent_threshold']:
            flags.append('ORACLE_DEPENDENT')

        # BATTLE_TESTED: days_live >= threshold AND zero critical bugs
        if days_live >= cfg['battle_tested_days'] and critical_bugs_found == 0:
            flags.append('BATTLE_TESTED')

        # UNDER_AUDITED: audit_count < threshold AND complexity_score > threshold
        if (audit_count < cfg['under_audited_audit_count']
                and complexity_score > cfg['under_audited_complexity_threshold']):
            flags.append('UNDER_AUDITED')

        # BUG_BOUNTY_ACTIVE
        if bug_bounty_usd > 0:
            flags.append('BUG_BOUNTY_ACTIVE')

        return {
            'name': name,
            'protocol': protocol,
            'lines_of_code': int(loc),
            'function_count': int(func_count),
            'external_call_count': int(ext_call_count),
            'inheritance_depth': int(inheritance_depth),
            'proxy_pattern': proxy_pattern,
            'upgrade_mechanism': upgrade_mechanism,
            'oracle_dependencies': oracle_dependencies,
            'cross_contract_calls': cross_contract_calls,
            'assembly_blocks_count': int(assembly_blocks_count),
            'audit_count': audit_count,
            'bug_bounty_usd': bug_bounty_usd,
            'days_live': days_live,
            'critical_bugs_found': critical_bugs_found,
            'complexity_score': complexity_score,
            'upgrade_risk_score': upgrade_risk_score,
            'audit_coverage_score': audit_coverage_score,
            'net_risk_score': net_risk_score,
            'risk_label': risk_label,
            'flags': flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, contracts: list, config: Optional[dict] = None) -> dict:
        """
        Score complexity and audit risk for a list of contract dicts.

        Args:
            contracts: list of contract dicts (see module docstring for fields).
            config: optional config overrides (merged with instance config).

        Returns:
            dict with 'contracts' (per-contract scores), 'aggregates', 'timestamp', 'status'.
        """
        if config:
            self.config = {**self.config, **config}

        timestamp = datetime.datetime.utcnow().isoformat()

        if not contracts:
            result = {
                'contracts': [],
                'aggregates': {
                    'most_complex': None,
                    'most_complex_score': 0.0,
                    'safest': None,
                    'safest_score': 0.0,
                    'average_complexity_score': 0.0,
                    'critical_complexity_count': 0,
                    'under_audited_count': 0,
                    'total_contracts': 0,
                },
                'timestamp': timestamp,
                'status': 'ok',
            }
            self._write_log(result)
            return result

        scored = [self._score_contract(c) for c in contracts]

        avg_complexity = sum(s['complexity_score'] for s in scored) / len(scored)
        most_complex = max(scored, key=lambda x: x['net_risk_score'])
        safest = min(scored, key=lambda x: x['net_risk_score'])
        critical_count = sum(1 for s in scored if s['risk_label'] == 'CRITICAL_COMPLEXITY')
        under_audited_count = sum(1 for s in scored if 'UNDER_AUDITED' in s['flags'])

        result = {
            'contracts': scored,
            'aggregates': {
                'most_complex': most_complex['name'],
                'most_complex_score': most_complex['net_risk_score'],
                'safest': safest['name'],
                'safest_score': safest['net_risk_score'],
                'average_complexity_score': round(avg_complexity, 4),
                'critical_complexity_count': critical_count,
                'under_audited_count': under_audited_count,
                'total_contracts': len(scored),
            },
            'timestamp': timestamp,
            'status': 'ok',
        }

        self._write_log(result)
        return result

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _write_log(self, result: dict):
        """Append a summary entry to the ring-buffer log (atomic write, cap 100)."""
        log_path = self.config.get('log_path', DEFAULT_CONFIG['log_path'])
        cap = int(self.config.get('log_cap', DEFAULT_CONFIG['log_cap']))

        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as fh:
                    entries = json.load(fh)
                if not isinstance(entries, list):
                    entries = []
            except (json.JSONDecodeError, IOError, OSError):
                entries = []

        agg = result.get('aggregates', {})
        log_entry = {
            'timestamp': result.get('timestamp', datetime.datetime.utcnow().isoformat()),
            'total_contracts': agg.get('total_contracts', 0),
            'average_complexity_score': agg.get('average_complexity_score', 0.0),
            'critical_complexity_count': agg.get('critical_complexity_count', 0),
            'under_audited_count': agg.get('under_audited_count', 0),
            'most_complex': agg.get('most_complex'),
            'safest': agg.get('safest'),
        }
        entries.append(log_entry)

        if len(entries) > cap:
            entries = entries[-cap:]

        tmp_path = log_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, log_path)
