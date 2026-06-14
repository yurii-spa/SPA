"""
MP-971: ProtocolLiquidityDepthStressTester
Tests liquidity depth under various stress scenarios.
Stdlib only, read-only analytics, atomic ring-buffer log (cap 100).
"""

import json
import os
import tempfile
import time
from typing import Dict, List, Optional, Any

_LOG_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'liquidity_depth_log.json'
)
_LOG_CAP = 100

# Stress label constants
STRESS_DEEP = 'DEEP_LIQUIDITY'
STRESS_ADEQUATE = 'ADEQUATE'
STRESS_THIN = 'THIN'
STRESS_VERY_THIN = 'VERY_THIN'
STRESS_ILLIQUID = 'ILLIQUID'

# Flag constants
FLAG_LP_CONCENTRATED = 'LP_CONCENTRATED'
FLAG_ACTIVE_RANGE_NARROW = 'ACTIVE_RANGE_NARROW'
FLAG_HIGH_VOLUME_RATIO = 'HIGH_VOLUME_RATIO'
FLAG_INSTITUTIONAL_GRADE = 'INSTITUTIONAL_GRADE'
FLAG_RETAIL_ONLY = 'RETAIL_ONLY'

ALL_STRESS_LABELS = [
    STRESS_DEEP,
    STRESS_ADEQUATE,
    STRESS_THIN,
    STRESS_VERY_THIN,
    STRESS_ILLIQUID,
]


class ProtocolLiquidityDepthStressTester:
    """
    Tests protocol liquidity depth under various stress scenarios.

    Computes price_impact_100k_pct, price_impact_1m_pct, price_impact_10m_pct
    using a linear constant-product approximation against the pool's
    liquidity distribution. Assigns a stress_label and flags per pool.

    Read-only analytics — never modifies allocator, risk, or execution domains.
    Ring-buffer log written atomically to data/liquidity_depth_log.json.
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        # Stress label thresholds (on $10M price impact)
        'illiquid_slippage_threshold_pct': 5.0,
        # Adequate vs thin boundary (on $1M price impact)
        'very_thin_impact_threshold_pct': 2.0,
        'thin_impact_threshold_pct': 0.5,
        'deep_liquidity_impact_threshold_pct': 0.1,
        # Flags
        'lp_concentration_threshold_pct': 60.0,   # top3 > threshold → LP_CONCENTRATED
        'cl_utilization_narrow_pct': 50.0,         # CL util < threshold → ACTIVE_RANGE_NARROW
        'high_volume_ratio_threshold': 0.5,        # vol/liq > threshold → HIGH_VOLUME_RATIO
        'institutional_impact_threshold_pct': 0.1, # $1M impact < → INSTITUTIONAL_GRADE
        'retail_impact_threshold_pct': 1.0,        # $100K impact > → RETAIL_ONLY
        # Default distribution fallback when pcts are 0
        'fallback_dist_1pct': 0.10,
        'fallback_dist_5pct': 0.30,
        'fallback_dist_10pct': 0.50,
    }

    def __init__(self, log_file: Optional[str] = None) -> None:
        self._log_file = log_file or _LOG_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def test(self, pools: List[Dict], config: Optional[Dict] = None) -> Dict:
        """
        Stress-test liquidity depth across a list of pools.

        Args:
            pools: list of pool dicts (see module docstring).
            config: optional config overrides.

        Returns:
            dict with keys: timestamp, pools_analyzed, results, aggregates.
        """
        cfg = {**self.DEFAULT_CONFIG, **(config or {})}
        log_override = cfg.pop('log_file', None)
        if log_override:
            self._log_file = log_override

        results = [self._analyze_pool(pool, cfg) for pool in pools]
        aggregates = self._aggregate(results)

        output = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'pools_analyzed': len(results),
            'results': results,
            'aggregates': aggregates,
        }
        self._append_log(output)
        return output

    # ------------------------------------------------------------------
    # Per-pool analysis
    # ------------------------------------------------------------------

    def _analyze_pool(self, pool: Dict, cfg: Dict) -> Dict:
        protocol = str(pool.get('protocol', 'unknown'))
        pair = str(pool.get('pair', 'unknown'))
        total_liq = max(0.0, float(pool.get('total_liquidity_usd', 0.0)))
        dist = pool.get('liquidity_distribution', {}) or {}
        pct_1 = float(dist.get('pct_within_1pct', 0.0))
        pct_5 = float(dist.get('pct_within_5pct', 0.0))
        pct_10 = float(dist.get('pct_within_10pct', 0.0))
        daily_vol = max(0.0, float(pool.get('daily_volume_usd', 0.0)))
        top3_conc = max(0.0, min(100.0, float(pool.get('top_3_lp_concentration_pct', 0.0))))
        is_cl = bool(pool.get('is_concentrated_liquidity', False))
        active_range = max(0.0, min(100.0, float(pool.get('active_range_utilization_pct', 100.0))))
        fee_tier = float(pool.get('fee_tier_bps', 30.0))
        avg_slippage_1m = float(pool.get('avg_slippage_1m_usd', 0.0))

        # Effective liquidity per price range using distribution pcts
        eff_liq_1pct = total_liq * (pct_1 / 100.0) if pct_1 > 0.0 else total_liq * cfg['fallback_dist_1pct']
        eff_liq_5pct = total_liq * (pct_5 / 100.0) if pct_5 > 0.0 else total_liq * cfg['fallback_dist_5pct']
        eff_liq_10pct = total_liq * (pct_10 / 100.0) if pct_10 > 0.0 else total_liq * cfg['fallback_dist_10pct']

        # Price impact (linear CPAMM approximation): impact% = trade_size / eff_liq * 100
        price_impact_100k_pct = self._price_impact(100_000.0, eff_liq_1pct)
        price_impact_1m_pct = self._price_impact(1_000_000.0, eff_liq_5pct)
        price_impact_10m_pct = self._price_impact(10_000_000.0, eff_liq_10pct)

        # market_depth_score 0-100: derived from $1M impact (lower impact = deeper)
        if price_impact_1m_pct >= 10.0:
            market_depth_score = 0.0
        else:
            market_depth_score = max(0.0, min(100.0, 100.0 - price_impact_1m_pct * 10.0))

        # concentration_risk_score: top3 LP concentration as HHI proxy (0-100)
        concentration_risk_score = top3_conc

        # volume_to_liquidity_ratio
        vol_liq_ratio = daily_vol / total_liq if total_liq > 0.0 else 0.0

        # --- Stress label ---
        if price_impact_10m_pct > cfg['illiquid_slippage_threshold_pct']:
            stress_label = STRESS_ILLIQUID
        elif price_impact_1m_pct > cfg['very_thin_impact_threshold_pct']:
            stress_label = STRESS_VERY_THIN
        elif price_impact_1m_pct > cfg['thin_impact_threshold_pct']:
            stress_label = STRESS_THIN
        elif price_impact_1m_pct > cfg['deep_liquidity_impact_threshold_pct']:
            stress_label = STRESS_ADEQUATE
        else:
            stress_label = STRESS_DEEP

        # --- Flags ---
        flags: List[str] = []
        if top3_conc > cfg['lp_concentration_threshold_pct']:
            flags.append(FLAG_LP_CONCENTRATED)
        if is_cl and active_range < cfg['cl_utilization_narrow_pct']:
            flags.append(FLAG_ACTIVE_RANGE_NARROW)
        if vol_liq_ratio > cfg['high_volume_ratio_threshold']:
            flags.append(FLAG_HIGH_VOLUME_RATIO)
        if price_impact_1m_pct < cfg['institutional_impact_threshold_pct']:
            flags.append(FLAG_INSTITUTIONAL_GRADE)
        if price_impact_100k_pct > cfg['retail_impact_threshold_pct']:
            flags.append(FLAG_RETAIL_ONLY)

        return {
            'protocol': protocol,
            'pair': pair,
            'total_liquidity_usd': total_liq,
            'daily_volume_usd': daily_vol,
            'top_3_lp_concentration_pct': top3_conc,
            'is_concentrated_liquidity': is_cl,
            'active_range_utilization_pct': active_range,
            'fee_tier_bps': fee_tier,
            'price_impact_100k_pct': price_impact_100k_pct,
            'price_impact_1m_pct': price_impact_1m_pct,
            'price_impact_10m_pct': price_impact_10m_pct,
            'market_depth_score': round(market_depth_score, 4),
            'concentration_risk_score': round(concentration_risk_score, 4),
            'volume_to_liquidity_ratio': round(vol_liq_ratio, 6),
            'stress_label': stress_label,
            'flags': flags,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _price_impact(trade_usd: float, eff_liq: float) -> float:
        """Linear CPAMM price impact approximation (% of trade)."""
        if eff_liq <= 0.0:
            return 100.0
        return round(min(100.0, (trade_usd / eff_liq) * 100.0), 6)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, results: List[Dict]) -> Dict:
        if not results:
            return {
                'deepest_pool': None,
                'shallowest_pool': None,
                'total_ecosystem_liquidity_usd': 0.0,
                'illiquid_count': 0,
                'institutional_grade_count': 0,
            }

        by_depth = sorted(results, key=lambda r: r['market_depth_score'], reverse=True)
        deepest = by_depth[0]
        shallowest = by_depth[-1]

        return {
            'deepest_pool': f"{deepest['protocol']}/{deepest['pair']}",
            'shallowest_pool': f"{shallowest['protocol']}/{shallowest['pair']}",
            'total_ecosystem_liquidity_usd': sum(r['total_liquidity_usd'] for r in results),
            'illiquid_count': sum(1 for r in results if r['stress_label'] == STRESS_ILLIQUID),
            'institutional_grade_count': sum(
                1 for r in results if FLAG_INSTITUTIONAL_GRADE in r['flags']
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
            dir=dir_path or '.', prefix='.liq_depth_log_tmp_'
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
