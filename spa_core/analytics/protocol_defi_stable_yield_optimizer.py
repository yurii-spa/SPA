"""
MP-1021: Protocol DeFi Stable Yield Optimizer
Optimizes allocation across stablecoin yield opportunities with risk adjustment.
Pure stdlib, no external dependencies.
"""
import json
import os
from typing import Optional
from spa_core.utils import clock

DEFAULT_CONFIG = {
    'log_path': 'data/stable_yield_optimizer_log.json',
    'log_cap': 100,
    # Label thresholds
    'top_allocation_risk_adj_apy': 8.0,    # risk_adj_apy > this
    'top_allocation_stability': 80.0,      # stability_score > this
    'top_allocation_peg': 95.0,            # peg_score > this
    'high_priority_risk_adj_apy': 5.0,
    'high_priority_stability': 60.0,
    'low_priority_sc_risk': 60.0,
    'low_priority_peg': 90.0,
    'avoid_sc_risk': 80.0,
    'avoid_peg': 80.0,
    # Flag thresholds
    'high_risk_sc_threshold': 70.0,
    'depeg_risk_peg': 90.0,
    'gas_inefficient_threshold': 50.0,     # gas_entry+exit > $50
    'gas_inefficient_capital': 10_000.0,   # for <$10K max_allocation
    'established_age_days': 730,
    'established_tvl': 100_000_000,
    # Stability score weights
    'stability_weight_age': 0.2,
    'stability_weight_tvl': 0.2,
    'stability_weight_apy_vol': 0.3,
    'stability_weight_peg': 0.3,
    # Optimal allocation weights
    'alloc_weight_stability': 0.4,
    'alloc_weight_yield_per_risk': 0.3,
    'alloc_weight_tvl': 0.3,
    # Normalization caps
    'age_norm_cap_days': 1825,             # 5 years
    'tvl_norm_cap': 1_000_000_000,        # $1B
    'apy_vol_norm_cap': 20.0,             # 20% std → worst volatility
    'yield_per_risk_norm_cap': 1.0,       # yield_per_risk cap for normalization
    # Gas cost annualization: assume capital held for 1 year
    'annualize_capital_for_gas': 10_000.0,
}

VALID_LABELS = {
    'TOP_ALLOCATION',
    'HIGH_PRIORITY',
    'STANDARD',
    'LOW_PRIORITY',
    'AVOID',
}

VALID_FLAGS = {
    'HIGH_RISK_PROTOCOL',
    'DEPEG_RISK',
    'GAS_INEFFICIENT',
    'ESTABLISHED_PROTOCOL',
    'REAL_YIELD_STABLE',
    'INSTANT_EXIT',
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class ProtocolDeFiStableYieldOptimizer:
    """
    Optimizes stablecoin yield opportunity allocation.

    Key formulas
    ------------
    risk_adjusted_apy = current_apy_pct × (100 - smart_contract_risk_score) / 100
                        × stablecoin_peg_score / 100

    annualized_gas_cost_pct = (gas_cost_to_enter_usd + gas_cost_to_exit_usd)
                              / annualize_capital_for_gas × 100

    net_apy_after_gas = risk_adjusted_apy - annualized_gas_cost_pct

    stability_score (0–100):
        age_norm   = min(protocol_age_days / age_norm_cap_days, 1.0)
        tvl_norm   = min(tvl_usd / tvl_norm_cap, 1.0)
        apy_vol_norm = 1.0 - min(apy_volatility_pct / apy_vol_norm_cap, 1.0)  ← lower is better
        peg_norm   = stablecoin_peg_score / 100
        stability_score = (age_norm×0.2 + tvl_norm×0.2 + apy_vol_norm×0.3 + peg_norm×0.3) × 100

    yield_per_risk_unit = net_apy_after_gas / (smart_contract_risk_score + 1)

    optimal_allocation_pct (raw, before normalisation):
        yield_per_risk_norm = min(yield_per_risk_unit / yield_per_risk_norm_cap, 1.0)
        tvl_weight_norm     = min(tvl_usd / tvl_norm_cap, 1.0)
        raw = stability_score/100 × 0.4
            + yield_per_risk_norm × 0.3
            + tvl_weight_norm × 0.3
    After computing raw for all opportunities, normalise so they sum to 100 % (if sum > 0).

    Label assignment (priority order)
    ----------------------------------
    AVOID        → smart_contract_risk > 80 OR peg < 80
    LOW_PRIORITY → smart_contract_risk > 60 OR peg < 90   (and not AVOID)
    TOP_ALLOCATION → risk_adj_apy > 8% AND stability > 80 AND peg > 95
    HIGH_PRIORITY  → risk_adj_apy > 5% AND stability > 60
    STANDARD       → catch-all
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = {**DEFAULT_CONFIG}
        if config:
            cfg.update(config)
        self.config = cfg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_risk_adjusted_apy(self, opp: dict) -> float:
        apy = float(opp.get('current_apy_pct', 0.0))
        sc_risk = float(opp.get('smart_contract_risk_score', 0.0))
        peg = float(opp.get('stablecoin_peg_score', 100.0))
        return apy * (100.0 - sc_risk) / 100.0 * peg / 100.0

    def _compute_annualized_gas_pct(self, opp: dict) -> float:
        gas_in = float(opp.get('gas_cost_to_enter_usd', 0.0))
        gas_out = float(opp.get('gas_cost_to_exit_usd', 0.0))
        capital = self.config.get('annualize_capital_for_gas', DEFAULT_CONFIG['annualize_capital_for_gas'])
        if capital <= 0:
            return 0.0
        return (gas_in + gas_out) / capital * 100.0

    def _compute_stability_score(self, opp: dict) -> float:
        age = float(opp.get('protocol_age_days', 0.0))
        tvl = float(opp.get('tvl_usd', 0.0))
        apy_vol = float(opp.get('apy_volatility_pct', 0.0))
        peg = float(opp.get('stablecoin_peg_score', 100.0))

        age_cap = self.config.get('age_norm_cap_days', DEFAULT_CONFIG['age_norm_cap_days'])
        tvl_cap = self.config.get('tvl_norm_cap', DEFAULT_CONFIG['tvl_norm_cap'])
        apy_vol_cap = self.config.get('apy_vol_norm_cap', DEFAULT_CONFIG['apy_vol_norm_cap'])

        w_age = self.config.get('stability_weight_age', DEFAULT_CONFIG['stability_weight_age'])
        w_tvl = self.config.get('stability_weight_tvl', DEFAULT_CONFIG['stability_weight_tvl'])
        w_vol = self.config.get('stability_weight_apy_vol', DEFAULT_CONFIG['stability_weight_apy_vol'])
        w_peg = self.config.get('stability_weight_peg', DEFAULT_CONFIG['stability_weight_peg'])

        age_norm = _clamp(age / max(age_cap, 1), 0.0, 1.0)
        tvl_norm = _clamp(tvl / max(tvl_cap, 1), 0.0, 1.0)
        apy_vol_norm = _clamp(1.0 - min(apy_vol / max(apy_vol_cap, 1e-9), 1.0), 0.0, 1.0)
        peg_norm = _clamp(peg / 100.0, 0.0, 1.0)

        raw = w_age * age_norm + w_tvl * tvl_norm + w_vol * apy_vol_norm + w_peg * peg_norm
        return _clamp(raw * 100.0)

    def _compute_yield_per_risk(self, net_apy: float, opp: dict) -> float:
        sc_risk = float(opp.get('smart_contract_risk_score', 0.0))
        return net_apy / (sc_risk + 1.0)

    def _assign_label(self, opp: dict, risk_adj_apy: float, stability: float) -> str:
        sc_risk = float(opp.get('smart_contract_risk_score', 0.0))
        peg = float(opp.get('stablecoin_peg_score', 100.0))

        avoid_sc = self.config.get('avoid_sc_risk', DEFAULT_CONFIG['avoid_sc_risk'])
        avoid_peg = self.config.get('avoid_peg', DEFAULT_CONFIG['avoid_peg'])
        low_sc = self.config.get('low_priority_sc_risk', DEFAULT_CONFIG['low_priority_sc_risk'])
        low_peg = self.config.get('low_priority_peg', DEFAULT_CONFIG['low_priority_peg'])
        top_apy = self.config.get('top_allocation_risk_adj_apy', DEFAULT_CONFIG['top_allocation_risk_adj_apy'])
        top_stab = self.config.get('top_allocation_stability', DEFAULT_CONFIG['top_allocation_stability'])
        top_peg = self.config.get('top_allocation_peg', DEFAULT_CONFIG['top_allocation_peg'])
        hi_apy = self.config.get('high_priority_risk_adj_apy', DEFAULT_CONFIG['high_priority_risk_adj_apy'])
        hi_stab = self.config.get('high_priority_stability', DEFAULT_CONFIG['high_priority_stability'])

        if sc_risk > avoid_sc or peg < avoid_peg:
            return 'AVOID'
        if sc_risk > low_sc or peg < low_peg:
            return 'LOW_PRIORITY'
        if risk_adj_apy > top_apy and stability > top_stab and peg > top_peg:
            return 'TOP_ALLOCATION'
        if risk_adj_apy > hi_apy and stability > hi_stab:
            return 'HIGH_PRIORITY'
        return 'STANDARD'

    def _assign_flags(self, opp: dict, risk_adj_apy: float) -> list:
        flags = []
        sc_risk = float(opp.get('smart_contract_risk_score', 0.0))
        peg = float(opp.get('stablecoin_peg_score', 100.0))
        gas_in = float(opp.get('gas_cost_to_enter_usd', 0.0))
        gas_out = float(opp.get('gas_cost_to_exit_usd', 0.0))
        max_alloc = float(opp.get('max_single_allocation_usd', 0.0))
        age = float(opp.get('protocol_age_days', 0.0))
        tvl = float(opp.get('tvl_usd', 0.0))
        yield_type = opp.get('yield_type', '')
        lockup = float(opp.get('lockup_days', 0.0))

        hi_risk = self.config.get('high_risk_sc_threshold', DEFAULT_CONFIG['high_risk_sc_threshold'])
        depeg_peg = self.config.get('depeg_risk_peg', DEFAULT_CONFIG['depeg_risk_peg'])
        gas_thresh = self.config.get('gas_inefficient_threshold', DEFAULT_CONFIG['gas_inefficient_threshold'])
        gas_capital = self.config.get('gas_inefficient_capital', DEFAULT_CONFIG['gas_inefficient_capital'])
        est_age = self.config.get('established_age_days', DEFAULT_CONFIG['established_age_days'])
        est_tvl = self.config.get('established_tvl', DEFAULT_CONFIG['established_tvl'])

        if sc_risk > hi_risk:
            flags.append('HIGH_RISK_PROTOCOL')
        if peg < depeg_peg:
            flags.append('DEPEG_RISK')
        if (gas_in + gas_out) > gas_thresh and max_alloc < gas_capital:
            flags.append('GAS_INEFFICIENT')
        if age >= est_age and tvl >= est_tvl:
            flags.append('ESTABLISHED_PROTOCOL')
        if yield_type == 'real_yield':
            flags.append('REAL_YIELD_STABLE')
        if lockup == 0:
            flags.append('INSTANT_EXIT')

        return flags

    def _compute_raw_allocation_weight(self, stability: float, yield_per_risk: float, tvl: float) -> float:
        """Return raw (unnormalised) allocation weight 0..1."""
        tvl_cap = self.config.get('tvl_norm_cap', DEFAULT_CONFIG['tvl_norm_cap'])
        ypr_cap = self.config.get('yield_per_risk_norm_cap', DEFAULT_CONFIG['yield_per_risk_norm_cap'])
        w_stab = self.config.get('alloc_weight_stability', DEFAULT_CONFIG['alloc_weight_stability'])
        w_ypr = self.config.get('alloc_weight_yield_per_risk', DEFAULT_CONFIG['alloc_weight_yield_per_risk'])
        w_tvl = self.config.get('alloc_weight_tvl', DEFAULT_CONFIG['alloc_weight_tvl'])

        stability_norm = _clamp(stability / 100.0, 0.0, 1.0)
        ypr_norm = _clamp(yield_per_risk / max(ypr_cap, 1e-9), 0.0, 1.0)
        tvl_norm = _clamp(tvl / max(tvl_cap, 1.0), 0.0, 1.0)

        return w_stab * stability_norm + w_ypr * ypr_norm + w_tvl * tvl_norm

    def _build_result(self, opp: dict) -> dict:
        """Enrich a single opportunity (no normalisation yet)."""
        risk_adj_apy = self._compute_risk_adjusted_apy(opp)
        gas_pct = self._compute_annualized_gas_pct(opp)
        net_apy = risk_adj_apy - gas_pct
        stability = self._compute_stability_score(opp)
        yield_per_risk = self._compute_yield_per_risk(net_apy, opp)
        label = self._assign_label(opp, risk_adj_apy, stability)
        flags = self._assign_flags(opp, risk_adj_apy)
        raw_weight = self._compute_raw_allocation_weight(
            stability, yield_per_risk, float(opp.get('tvl_usd', 0.0))
        )

        return {
            'name': opp.get('name', ''),
            'protocol': opp.get('protocol', ''),
            'stablecoin': opp.get('stablecoin', ''),
            'yield_type': opp.get('yield_type', ''),
            'current_apy_pct': float(opp.get('current_apy_pct', 0.0)),
            'risk_adjusted_apy': round(risk_adj_apy, 6),
            'net_apy_after_gas': round(net_apy, 6),
            'stability_score': round(stability, 4),
            'yield_per_risk_unit': round(yield_per_risk, 6),
            'optimal_allocation_pct': 0.0,   # set after normalisation
            '_raw_weight': raw_weight,
            'label': label,
            'flags': flags,
        }

    def _write_log(self, result: dict) -> None:
        """Atomically append summary to ring-buffer log."""
        log_path = self.config.get('log_path', DEFAULT_CONFIG['log_path'])
        cap = int(self.config.get('log_cap', DEFAULT_CONFIG['log_cap']))

        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        entries = data
            except (json.JSONDecodeError, OSError):
                entries = []

        top = result.get('top_opportunity')
        entry = {
            'ts': clock.utcnow().isoformat() + 'Z',
            'total_analyzed': result.get('total_analyzed', 0),
            'top_allocation_count': result.get('top_allocation_count', 0),
            'avoid_count': result.get('avoid_count', 0),
            'total_yield_weighted_apy': result.get('total_yield_weighted_apy', 0.0),
            'top_opportunity_name': (top or {}).get('name', ''),
        }
        entries.append(entry)
        entries = entries[-cap:]

        dir_path = os.path.dirname(log_path) or '.'
        os.makedirs(dir_path, exist_ok=True)
        tmp_path = log_path + '.tmp'
        with open(tmp_path, 'w') as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, stable_opportunities: list, config: Optional[dict] = None) -> dict:
        """
        Optimize allocation across stablecoin yield opportunities.

        Parameters
        ----------
        stable_opportunities : list[dict]
        config : dict, optional — per-call config override

        Returns
        -------
        dict with keys:
            opportunities              : list of enriched + normalised dicts
            top_opportunity            : highest optimal_allocation_pct entry
            avoid_list                 : entries labelled AVOID
            total_yield_weighted_apy   : sum(optimal_allocation_pct/100 × risk_adj_apy)
            top_allocation_count       : count of TOP_ALLOCATION labels
            avoid_count                : count of AVOID labels
            recommended_portfolio      : sorted by optimal_allocation_pct desc
            total_analyzed             : int
        """
        if config:
            saved = self.config
            self.config = {**self.config, **config}

        opps = list(stable_opportunities or [])
        enriched = [self._build_result(o) for o in opps]

        # Normalise optimal_allocation_pct
        total_raw = sum(r['_raw_weight'] for r in enriched)
        for r in enriched:
            if total_raw > 0:
                r['optimal_allocation_pct'] = round(r['_raw_weight'] / total_raw * 100.0, 4)
            else:
                r['optimal_allocation_pct'] = 0.0
            del r['_raw_weight']

        if config:
            self.config = saved  # noqa: F821

        # Aggregates
        avoid_list = [r for r in enriched if r['label'] == 'AVOID']
        top_alloc_count = sum(1 for r in enriched if r['label'] == 'TOP_ALLOCATION')
        avoid_count = len(avoid_list)

        total_weighted_apy = sum(
            r['optimal_allocation_pct'] / 100.0 * r['risk_adjusted_apy']
            for r in enriched
        )

        recommended = sorted(enriched, key=lambda r: r['optimal_allocation_pct'], reverse=True)
        top = recommended[0] if recommended else None

        result = {
            'opportunities': enriched,
            'top_opportunity': top,
            'avoid_list': avoid_list,
            'total_yield_weighted_apy': round(total_weighted_apy, 6),
            'top_allocation_count': top_alloc_count,
            'avoid_count': avoid_count,
            'recommended_portfolio': recommended,
            'total_analyzed': len(enriched),
        }

        self._write_log(result)
        return result
