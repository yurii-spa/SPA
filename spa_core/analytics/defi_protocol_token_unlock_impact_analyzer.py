"""
MP-1020: DeFi Protocol Token Unlock Impact Analyzer
Analyzes the price and liquidity impact of upcoming token unlock events.
Pure stdlib, no external dependencies.
"""
import json
import os
from typing import Optional
from spa_core.utils import clock

DEFAULT_CONFIG = {
    'log_path': 'data/token_unlock_impact_log.json',
    'log_cap': 100,
    # beneficiary sell-pressure factors (higher = more selling expected)
    'beneficiary_factors': {
        'team': 1.0,
        'investors': 0.9,
        'ecosystem': 0.5,
        'community': 0.2,
    },
    # thresholds for labels
    'negligible_supply_pct': 1.0,      # < 1% circulating supply
    'low_impact_supply_pct': 3.0,
    'moderate_supply_pct': 5.0,
    'high_pressure_supply_pct': 5.0,   # team/investor cliff ≥ 5%
    'critical_supply_pct': 20.0,       # ≥ 20% supply → CRITICAL
    'critical_net_impact': 70.0,       # net_impact_score > 70 → CRITICAL
    # near-term threshold
    'near_term_days': 30,
    # absorption ratio (volume / unlock > this → sufficient)
    'absorption_ratio': 2.0,
    # historical dump threshold (negative pct < -10)
    'historical_dump_pct': -10.0,
    # absorption normalization: volume/unlock capped at this for scoring
    'absorption_norm_cap': 10.0,
    # cliff unlock size threshold for flag
    'cliff_flag_pct': 3.0,
}

VALID_IMPACT_LABELS = {
    'NEGLIGIBLE_IMPACT',
    'LOW_IMPACT',
    'MODERATE_PRESSURE',
    'HIGH_PRESSURE',
    'CRITICAL_OVERHANG',
}

VALID_FLAGS = {
    'TEAM_INVESTOR_UNLOCK',
    'CLIFF_UNLOCK',
    'NEAR_TERM_UNLOCK',
    'COMMUNITY_FRIENDLY',
    'ABSORPTION_SUFFICIENT',
    'HISTORICAL_DUMP',
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class DeFiProtocolTokenUnlockImpactAnalyzer:
    """
    Analyzes the impact of upcoming DeFi protocol token unlocks on price
    and liquidity.

    Key formulas
    ------------
    unlock_to_volume_ratio  = (next_unlock_amount_usd / daily_volume_usd) × 100
    supply_inflation_pct    = (next_unlock_amount_usd / circulating_supply_usd) × 100
    beneficiary_factor      = config['beneficiary_factors'][beneficiary] (0..1)
    cliff_factor            = 1.0 if cliff else 0.0
    vol_ratio_norm          = min(unlock_to_volume_ratio / 100, 1.0)   (0..1)
    hist_impact_norm        = min(abs(historical_unlock_price_impact_pct) / 20, 1.0)
    sell_pressure_score     = (beneficiary_factor×0.3 + cliff_factor×0.2
                               + vol_ratio_norm×0.3 + hist_impact_norm×0.2) × 100
    absorption_ratio_raw    = daily_volume_usd / max(next_unlock_amount_usd, 1)
    absorption_norm         = min(absorption_ratio_raw / absorption_norm_cap, 1.0) × 100
    net_impact_score        = sell_pressure_score - absorption_capacity_score

    Impact label assignment (in priority order)
    -------------------------------------------
    CRITICAL_OVERHANG  → supply_inflation ≥ 20% OR net_impact > 70
    HIGH_PRESSURE      → beneficiary in {team, investors} AND cliff AND supply_inflation ≥ 5%
    MODERATE_PRESSURE  → supply_inflation ≥ 3%
    LOW_IMPACT         → supply_inflation ≥ 1%
    NEGLIGIBLE_IMPACT  → community AND supply_inflation < 1% (catch-all)
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = {**DEFAULT_CONFIG}
        if config:
            cfg.update(config)
        self.config = cfg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _beneficiary_factor(self, beneficiary: str) -> float:
        factors = self.config.get('beneficiary_factors', DEFAULT_CONFIG['beneficiary_factors'])
        return factors.get(beneficiary, 0.5)

    def _compute_schedule_metrics(self, s: dict) -> dict:
        """Return enriched metric dict for a single schedule."""
        daily_volume = max(float(s.get('daily_volume_usd', 1)), 1.0)
        unlock_amount = float(s.get('next_unlock_amount_usd', 0))
        circulating = max(float(s.get('circulating_supply_usd', 1)), 1.0)
        beneficiary = s.get('next_unlock_beneficiary', 'community')
        cliff = bool(s.get('unlock_cliff', False))
        hist_pct = float(s.get('historical_unlock_price_impact_pct', 0.0))
        days_until = float(s.get('next_unlock_date_days', 0))

        # Core ratios
        unlock_to_volume_ratio = (unlock_amount / daily_volume) * 100.0
        supply_inflation_pct = (unlock_amount / circulating) * 100.0

        # Sell pressure score components (each normalised 0..1)
        b_factor = self._beneficiary_factor(beneficiary)
        cliff_factor = 1.0 if cliff else 0.0
        vol_ratio_norm = _clamp(unlock_to_volume_ratio / 100.0, 0.0, 1.0)
        hist_impact_norm = _clamp(abs(hist_pct) / 20.0, 0.0, 1.0)

        sell_pressure_score = _clamp(
            (b_factor * 0.3 + cliff_factor * 0.2 + vol_ratio_norm * 0.3 + hist_impact_norm * 0.2) * 100.0
        )

        # Absorption capacity
        abs_norm_cap = self.config.get('absorption_norm_cap', DEFAULT_CONFIG['absorption_norm_cap'])
        absorption_ratio_raw = daily_volume / max(unlock_amount, 1.0)
        absorption_capacity_score = _clamp(min(absorption_ratio_raw / abs_norm_cap, 1.0) * 100.0)

        # Net impact
        net_impact_score = sell_pressure_score - absorption_capacity_score

        return {
            'unlock_to_volume_ratio': round(unlock_to_volume_ratio, 4),
            'supply_inflation_pct': round(supply_inflation_pct, 4),
            'sell_pressure_score': round(sell_pressure_score, 4),
            'absorption_capacity_score': round(absorption_capacity_score, 4),
            'net_impact_score': round(net_impact_score, 4),
            '_beneficiary': beneficiary,
            '_cliff': cliff,
            '_hist_pct': hist_pct,
            '_days_until': days_until,
            '_unlock_amount': unlock_amount,
            '_daily_volume': daily_volume,
        }

    def _assign_label(self, metrics: dict, supply_inflation_pct: float) -> str:
        """Assign impact label based on computed metrics."""
        critical_supply = self.config.get('critical_supply_pct', DEFAULT_CONFIG['critical_supply_pct'])
        critical_net = self.config.get('critical_net_impact', DEFAULT_CONFIG['critical_net_impact'])
        high_pct = self.config.get('high_pressure_supply_pct', DEFAULT_CONFIG['high_pressure_supply_pct'])
        moderate_pct = self.config.get('moderate_supply_pct', DEFAULT_CONFIG['moderate_supply_pct'])
        low_pct = self.config.get('low_impact_supply_pct', DEFAULT_CONFIG['low_impact_supply_pct'])
        negligible_pct = self.config.get('negligible_supply_pct', DEFAULT_CONFIG['negligible_supply_pct'])

        net_impact = metrics['net_impact_score']
        beneficiary = metrics['_beneficiary']
        cliff = metrics['_cliff']

        if supply_inflation_pct >= critical_supply or net_impact > critical_net:
            return 'CRITICAL_OVERHANG'
        if beneficiary in ('team', 'investors') and cliff and supply_inflation_pct >= high_pct:
            return 'HIGH_PRESSURE'
        if supply_inflation_pct >= moderate_pct:
            return 'MODERATE_PRESSURE'
        if supply_inflation_pct >= low_pct:
            return 'LOW_IMPACT'
        return 'NEGLIGIBLE_IMPACT'

    def _assign_flags(self, s: dict, metrics: dict) -> list:
        """Assign flags list for a schedule."""
        flags = []
        beneficiary = metrics['_beneficiary']
        cliff = metrics['_cliff']
        days_until = metrics['_days_until']
        unlock_amount = metrics['_unlock_amount']
        daily_volume = metrics['_daily_volume']
        hist_pct = metrics['_hist_pct']
        supply_inflation_pct = metrics['supply_inflation_pct']

        near_term = self.config.get('near_term_days', DEFAULT_CONFIG['near_term_days'])
        abs_ratio = self.config.get('absorption_ratio', DEFAULT_CONFIG['absorption_ratio'])
        hist_dump = self.config.get('historical_dump_pct', DEFAULT_CONFIG['historical_dump_pct'])
        cliff_flag_pct = self.config.get('cliff_flag_pct', DEFAULT_CONFIG['cliff_flag_pct'])

        if beneficiary in ('team', 'investors'):
            flags.append('TEAM_INVESTOR_UNLOCK')
        if cliff and supply_inflation_pct >= cliff_flag_pct:
            flags.append('CLIFF_UNLOCK')
        if days_until <= near_term:
            flags.append('NEAR_TERM_UNLOCK')
        if beneficiary == 'community':
            flags.append('COMMUNITY_FRIENDLY')
        if daily_volume > unlock_amount * abs_ratio:
            flags.append('ABSORPTION_SUFFICIENT')
        if hist_pct < hist_dump:
            flags.append('HISTORICAL_DUMP')

        return flags

    def _build_result(self, s: dict) -> dict:
        """Enrich a single schedule with computed fields."""
        metrics = self._compute_schedule_metrics(s)
        supply_inflation_pct = metrics['supply_inflation_pct']
        label = self._assign_label(metrics, supply_inflation_pct)
        flags = self._assign_flags(s, metrics)

        return {
            'name': s.get('name', ''),
            'protocol': s.get('protocol', ''),
            'next_unlock_beneficiary': metrics['_beneficiary'],
            'unlock_cliff': metrics['_cliff'],
            'next_unlock_date_days': metrics['_days_until'],
            'next_unlock_amount_usd': metrics['_unlock_amount'],
            'unlock_to_volume_ratio': metrics['unlock_to_volume_ratio'],
            'supply_inflation_pct': supply_inflation_pct,
            'sell_pressure_score': metrics['sell_pressure_score'],
            'absorption_capacity_score': metrics['absorption_capacity_score'],
            'net_impact_score': metrics['net_impact_score'],
            'impact_label': label,
            'flags': flags,
        }

    def _write_log(self, result: dict) -> None:
        """Atomically append result summary to ring-buffer log."""
        log_path = self.config.get('log_path', DEFAULT_CONFIG['log_path'])
        cap = int(self.config.get('log_cap', DEFAULT_CONFIG['log_cap']))

        # Load existing log
        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        entries = data
            except (json.JSONDecodeError, OSError):
                entries = []

        entry = {
            'ts': clock.utcnow().isoformat() + 'Z',
            'total_analyzed': result.get('total_analyzed', 0),
            'critical_overhang_count': result.get('critical_overhang_count', 0),
            'negligible_count': result.get('negligible_count', 0),
            'highest_pressure_name': (result.get('highest_pressure') or {}).get('name', ''),
            'total_upcoming_unlock_usd': result.get('total_upcoming_unlock_usd', 0),
        }
        entries.append(entry)
        entries = entries[-cap:]  # ring-buffer trim

        # Atomic write
        dir_path = os.path.dirname(log_path) or '.'
        os.makedirs(dir_path, exist_ok=True)
        tmp_path = log_path + '.tmp'
        with open(tmp_path, 'w') as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, schedules: list, config: Optional[dict] = None) -> dict:
        """
        Analyze token unlock schedules and return impact assessment.

        Parameters
        ----------
        schedules : list[dict]
            Each item contains unlock schedule fields (see module docstring).
        config : dict, optional
            Override instance config for this call.

        Returns
        -------
        dict with keys:
            analyzed          : list of enriched schedule dicts
            highest_pressure  : schedule with highest sell_pressure_score
            lowest_pressure   : schedule with lowest sell_pressure_score
            total_upcoming_unlock_usd : sum of upcoming_unlocks_12mo_usd
            critical_overhang_count   : count of CRITICAL_OVERHANG labels
            negligible_count          : count of NEGLIGIBLE_IMPACT labels
            total_analyzed            : int
        """
        if config:
            saved = self.config
            merged = {**self.config, **config}
            self.config = merged

        analyzed = [self._build_result(s) for s in (schedules or [])]

        # Restore config if overridden
        if config:
            self.config = saved  # noqa: F821

        total_upcoming = sum(
            float(s.get('upcoming_unlocks_12mo_usd', 0)) for s in (schedules or [])
        )
        critical_count = sum(1 for r in analyzed if r['impact_label'] == 'CRITICAL_OVERHANG')
        negligible_count = sum(1 for r in analyzed if r['impact_label'] == 'NEGLIGIBLE_IMPACT')

        highest = max(analyzed, key=lambda r: r['sell_pressure_score'], default=None)
        lowest = min(analyzed, key=lambda r: r['sell_pressure_score'], default=None)

        result = {
            'analyzed': analyzed,
            'highest_pressure': highest,
            'lowest_pressure': lowest,
            'total_upcoming_unlock_usd': round(total_upcoming, 2),
            'critical_overhang_count': critical_count,
            'negligible_count': negligible_count,
            'total_analyzed': len(analyzed),
        }

        self._write_log(result)
        return result
