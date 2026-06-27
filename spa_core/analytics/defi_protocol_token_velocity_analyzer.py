"""
MP-958: DeFi Protocol Token Velocity Analyzer
Analyzes token velocity as an indicator of real usage vs. speculation.
Pure stdlib, no external dependencies.
"""
import json
import os
from typing import Optional
from spa_core.utils import clock

# Velocity label thresholds (annualized)
_VELOCITY_THRESHOLDS = [
    ('STORE_OF_VALUE', 0.0, 0.5),
    ('LOW_VELOCITY', 0.5, 2.0),
    ('MODERATE', 2.0, 10.0),
    ('HIGH_VELOCITY', 10.0, 50.0),
    ('HYPERACTIVE', 50.0, float('inf')),
]

DEFAULT_CONFIG = {
    'annualize_days': 30,
    'speculation_velocity_threshold': 10.0,
    'speculation_utility_threshold': 40,
    'utility_driven_utility_threshold': 60,
    'utility_driven_velocity_threshold': 5.0,
    'high_staking_threshold': 50.0,
    'vesting_overhang_threshold': 30.0,
    'broad_adoption_wallets': 10000,
    'log_path': 'data/token_velocity_log.json',
    'log_cap': 100,
}

VALID_VELOCITY_LABELS = {
    'STORE_OF_VALUE', 'LOW_VELOCITY', 'MODERATE', 'HIGH_VELOCITY', 'HYPERACTIVE'
}

VALID_FLAGS = {
    'PURE_SPECULATION', 'UTILITY_DRIVEN', 'HIGH_STAKING_LOCK',
    'VESTING_OVERHANG', 'BROAD_ADOPTION'
}


class DeFiProtocolTokenVelocityAnalyzer:
    """
    Analyzes DeFi token velocity metrics for a list of tokens.

    Velocity ratio = 30d trading volume / market_cap (raw 30-day ratio).
    Annualized velocity = velocity_ratio × (365 / annualize_days).
    effective_circulating = circulating_supply × (1 - staked_pct/100 - vesting_locked_pct/100).
    effective_market_cap = market_cap_usd × (1 - locked_fraction).
    adjusted_velocity = (volume_30d / effective_market_cap) × annualize_factor.
    utility_score = min(100, len(utility_uses) × 20).
    speculation_index = velocity_component × 0.6 + utility_inverse × 0.4 (0–100).
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_velocity_label(self, annualized_velocity: float) -> str:
        """Return STORE_OF_VALUE / LOW_VELOCITY / MODERATE / HIGH_VELOCITY / HYPERACTIVE."""
        for label, lo, hi in _VELOCITY_THRESHOLDS:
            if lo <= annualized_velocity < hi:
                return label
        return 'HYPERACTIVE'  # fallback for >=50

    def _analyze_token(self, token: dict) -> dict:
        name = token.get('name', 'UNKNOWN')
        protocol = token.get('protocol', 'UNKNOWN')
        circulating_supply = float(token.get('circulating_supply', 0) or 0)
        trading_volume_30d_usd = float(token.get('trading_volume_30d_usd', 0) or 0)
        market_cap_usd = float(token.get('market_cap_usd', 0) or 0)
        unique_wallets_30d = int(token.get('unique_wallets_30d', 0) or 0)
        on_chain_tx_count_30d = int(token.get('on_chain_tx_count_30d', 0) or 0)
        staked_pct = float(token.get('staked_pct', 0) or 0)
        vesting_locked_pct = float(token.get('vesting_locked_pct', 0) or 0)
        avg_hold_duration_days = float(token.get('avg_hold_duration_days', 0) or 0)
        utility_uses = list(token.get('utility_uses', []) or [])

        annualize_days = float(self.config.get('annualize_days', 30))
        annualize_factor = 365.0 / annualize_days if annualize_days > 0 else 12.0

        # velocity_ratio (30-day, raw)
        if market_cap_usd > 0:
            velocity_ratio = trading_volume_30d_usd / market_cap_usd
            annualized_velocity = velocity_ratio * annualize_factor
        else:
            velocity_ratio = 0.0
            annualized_velocity = 0.0

        # effective_circulating
        locked_fraction = (staked_pct + vesting_locked_pct) / 100.0
        locked_fraction = min(1.0, max(0.0, locked_fraction))
        effective_circulating = circulating_supply * (1.0 - locked_fraction)

        # effective_market_cap
        effective_market_cap = market_cap_usd * (1.0 - locked_fraction)

        # adjusted_velocity (annualized)
        if effective_market_cap > 0:
            adjusted_velocity = (trading_volume_30d_usd / effective_market_cap) * annualize_factor
        else:
            adjusted_velocity = annualized_velocity  # fallback

        # utility_score 0-100
        utility_score = min(100, len(utility_uses) * 20)

        # speculation_index 0-100
        velocity_component = min(100.0, (annualized_velocity / 50.0) * 100.0)
        utility_inverse = 100.0 - utility_score
        speculation_index = velocity_component * 0.6 + utility_inverse * 0.4
        speculation_index = round(min(100.0, max(0.0, speculation_index)), 4)

        # velocity label
        velocity_label = self._get_velocity_label(annualized_velocity)

        # flags
        cfg = self.config
        flags = []
        if (annualized_velocity > cfg['speculation_velocity_threshold']
                and utility_score < cfg['speculation_utility_threshold']):
            flags.append('PURE_SPECULATION')
        if (utility_score > cfg['utility_driven_utility_threshold']
                and annualized_velocity < cfg['utility_driven_velocity_threshold']):
            flags.append('UTILITY_DRIVEN')
        if staked_pct > cfg['high_staking_threshold']:
            flags.append('HIGH_STAKING_LOCK')
        if vesting_locked_pct > cfg['vesting_overhang_threshold']:
            flags.append('VESTING_OVERHANG')
        if unique_wallets_30d > cfg['broad_adoption_wallets']:
            flags.append('BROAD_ADOPTION')

        return {
            'name': name,
            'protocol': protocol,
            'circulating_supply': circulating_supply,
            'trading_volume_30d_usd': trading_volume_30d_usd,
            'market_cap_usd': market_cap_usd,
            'unique_wallets_30d': unique_wallets_30d,
            'on_chain_tx_count_30d': on_chain_tx_count_30d,
            'staked_pct': staked_pct,
            'vesting_locked_pct': vesting_locked_pct,
            'avg_hold_duration_days': avg_hold_duration_days,
            'utility_uses': utility_uses,
            'velocity_ratio': round(velocity_ratio, 8),
            'annualized_velocity': round(annualized_velocity, 6),
            'effective_circulating': round(effective_circulating, 4),
            'effective_market_cap': round(effective_market_cap, 4),
            'adjusted_velocity': round(adjusted_velocity, 6),
            'utility_score': utility_score,
            'speculation_index': speculation_index,
            'velocity_label': velocity_label,
            'flags': flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, tokens: list, config: Optional[dict] = None) -> dict:
        """
        Analyze velocity metrics for a list of token dicts.

        Args:
            tokens: list of token dicts (see module docstring for fields).
            config: optional config overrides (merged with instance config).

        Returns:
            dict with 'tokens' (per-token analysis), 'aggregates', 'timestamp', 'status'.
        """
        if config:
            self.config = {**self.config, **config}

        timestamp = clock.utcnow().isoformat()

        if not tokens:
            result = {
                'tokens': [],
                'aggregates': {
                    'highest_velocity': None,
                    'highest_velocity_value': 0.0,
                    'lowest_velocity': None,
                    'lowest_velocity_value': 0.0,
                    'most_speculative': None,
                    'most_speculative_index': 0.0,
                    'most_utility_driven': None,
                    'most_utility_score': 0,
                    'average_velocity': 0.0,
                    'speculation_count': 0,
                    'total_tokens': 0,
                },
                'timestamp': timestamp,
                'status': 'ok',
            }
            self._write_log(result)
            return result

        analyzed = [self._analyze_token(t) for t in tokens]

        velocities = [a['annualized_velocity'] for a in analyzed]
        avg_velocity = sum(velocities) / len(velocities)

        highest = max(analyzed, key=lambda x: x['annualized_velocity'])
        lowest = min(analyzed, key=lambda x: x['annualized_velocity'])
        most_speculative = max(analyzed, key=lambda x: x['speculation_index'])
        most_utility = max(analyzed, key=lambda x: x['utility_score'])
        speculation_count = sum(1 for a in analyzed if 'PURE_SPECULATION' in a['flags'])

        result = {
            'tokens': analyzed,
            'aggregates': {
                'highest_velocity': highest['name'],
                'highest_velocity_value': highest['annualized_velocity'],
                'lowest_velocity': lowest['name'],
                'lowest_velocity_value': lowest['annualized_velocity'],
                'most_speculative': most_speculative['name'],
                'most_speculative_index': most_speculative['speculation_index'],
                'most_utility_driven': most_utility['name'],
                'most_utility_score': most_utility['utility_score'],
                'average_velocity': round(avg_velocity, 6),
                'speculation_count': speculation_count,
                'total_tokens': len(analyzed),
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
            'timestamp': result.get('timestamp', clock.utcnow().isoformat()),
            'total_tokens': agg.get('total_tokens', 0),
            'average_velocity': agg.get('average_velocity', 0.0),
            'speculation_count': agg.get('speculation_count', 0),
            'highest_velocity': agg.get('highest_velocity'),
            'most_speculative': agg.get('most_speculative'),
        }
        entries.append(log_entry)

        if len(entries) > cap:
            entries = entries[-cap:]

        tmp_path = log_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, log_path)
