"""
MP-895 DeFiStakingRewardTracker
Advisory analytics — reads positions list, computes effective APY after slashing drag,
exit drag, and opportunity cost comparison. Pure stdlib, read-only/advisory.
"""
import json
import os
import time

_LOG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'staking_reward_log.json')
_RING_BUFFER_SIZE = 100

_COMPOUNDING_BONUS_MAP = {
    'DAILY': 30,
    'WEEKLY': 15,
    'MONTHLY': 5,
    'MANUAL': 0,
}


def _load_log(path: str) -> list:
    try:
        with open(path) as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_log(path: str, entries: list, result: dict) -> None:
    entries = list(entries)
    entries.append(result)
    if len(entries) > _RING_BUFFER_SIZE:
        entries = entries[-_RING_BUFFER_SIZE:]
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, path)


def _lockup_label(lockup_days: int) -> str:
    if lockup_days == 0:
        return 'LIQUID'
    elif lockup_days <= 30:
        return 'SHORT'
    elif lockup_days <= 90:
        return 'MEDIUM'
    elif lockup_days <= 365:
        return 'LONG'
    else:
        return 'VERY_LONG'


def _staking_grade(adjusted_apy: float) -> str:
    if adjusted_apy >= 15:
        return 'A+'
    elif adjusted_apy >= 10:
        return 'A'
    elif adjusted_apy >= 7:
        return 'B'
    elif adjusted_apy >= 4:
        return 'C'
    elif adjusted_apy >= 1:
        return 'D'
    else:
        return 'F'


def _build_recommendation(grade: str, adjusted_apy: float, effective_apy: float,
                           net_premium: float, flags: list) -> str:
    if grade in ('A+', 'A'):
        return (f"Excellent staking. {adjusted_apy:.1f}% adj APY, "
                f"{net_premium:.1f}% premium vs opportunity cost.")
    elif grade == 'B':
        flag_str = ', '.join(flags) if flags else 'clean'
        return f"Good yield. {adjusted_apy:.1f}% adj APY. Watch: {flag_str}."
    elif grade == 'C':
        return f"Marginal. {net_premium:.1f}% net premium. Consider alternatives."
    else:
        return f"Poor risk-return. Effective APY: {effective_apy:.1f}%. Not recommended."


def analyze(positions: list, config: dict = None) -> dict:
    """
    Analyze staking positions for effective APY after slashing drag and exit costs.

    positions: list of dicts with staking position details
    config: optional dict with 'opportunity_cost_apy_pct' (default 5.0)

    Returns dict with per-position analysis and summary metrics.
    """
    if config is None:
        config = {}
    opportunity_cost_apy = float(config.get('opportunity_cost_apy_pct', 5.0))

    analyzed = []
    for pos in positions:
        protocol = str(pos.get('protocol', ''))
        staked_asset = str(pos.get('staked_asset', ''))
        gross_apy = float(pos.get('gross_apy_pct', 0.0))
        lockup_days = int(pos.get('lockup_days', 0))
        slashing_risk = float(pos.get('slashing_risk_pct', 0.0))
        slashing_penalty = float(pos.get('slashing_penalty_pct', 0.0))
        exit_cost = float(pos.get('exit_cost_pct', 0.0))
        compounding = str(pos.get('reward_compounding', 'MANUAL')).upper()
        capital_usd = float(pos.get('capital_usd', 0.0))

        # slashing_drag_pct = (slashing_risk_pct / 100) * slashing_penalty_pct
        slashing_drag = (slashing_risk / 100.0) * slashing_penalty

        # exit_drag_annualized_pct:
        # if lockup_days > 0: exit_cost_pct / lockup_days * 365
        # if lockup_days == 0 (LIQUID): 0.0
        if lockup_days > 0:
            exit_drag_annualized = exit_cost / lockup_days * 365.0
        else:
            exit_drag_annualized = 0.0

        effective_apy = gross_apy - slashing_drag - exit_drag_annualized
        net_premium = effective_apy - opportunity_cost_apy

        label = _lockup_label(lockup_days)
        bonus_bps = _COMPOUNDING_BONUS_MAP.get(compounding, 0)
        adjusted_apy = effective_apy + bonus_bps / 100.0

        grade = _staking_grade(adjusted_apy)

        flags = []
        if net_premium < 0:
            flags.append('NEGATIVE_PREMIUM')
        if slashing_risk > 5:
            flags.append('HIGH_SLASHING_RISK')
        if lockup_days > 90:
            flags.append('LONG_LOCKUP')
        if compounding == 'MANUAL':
            flags.append('MANUAL_COMPOUNDING')

        recommendation = _build_recommendation(grade, adjusted_apy, effective_apy,
                                               net_premium, flags)

        analyzed.append({
            'protocol': protocol,
            'staked_asset': staked_asset,
            'gross_apy_pct': gross_apy,
            'slashing_drag_pct': round(slashing_drag, 6),
            'exit_drag_annualized_pct': round(exit_drag_annualized, 6),
            'effective_apy_pct': round(effective_apy, 6),
            'opportunity_cost_pct': opportunity_cost_apy,
            'net_premium_pct': round(net_premium, 6),
            'lockup_label': label,
            'compounding_bonus_bps': bonus_bps,
            'adjusted_apy_pct': round(adjusted_apy, 6),
            'staking_grade': grade,
            'flags': flags,
            'recommendation': recommendation,
        })

    best = None
    if analyzed:
        best_pos = max(analyzed, key=lambda x: x['adjusted_apy_pct'])
        best = f"{best_pos['protocol']}:{best_pos['staked_asset']}"

    avg_effective = 0.0
    if analyzed:
        avg_effective = sum(p['effective_apy_pct'] for p in analyzed) / len(analyzed)

    total_capital = sum(float(pos.get('capital_usd', 0.0)) for pos in positions)

    return {
        'positions': analyzed,
        'best_staking_opportunity': best,
        'average_effective_apy_pct': round(avg_effective, 6),
        'total_capital_usd': total_capital,
        'timestamp': time.time(),
    }


def run(positions: list, config: dict = None, data_dir: str = None) -> dict:
    """Analyze and persist result to ring-buffer log (atomic write)."""
    result = analyze(positions, config)
    log_path = (_LOG_PATH if data_dir is None
                else os.path.join(data_dir, 'staking_reward_log.json'))
    entries = _load_log(log_path)
    _save_log(log_path, entries, result)
    return result


if __name__ == '__main__':
    import sys
    mode = '--run' if '--run' in sys.argv else '--check'
    data_dir = None
    if '--data-dir' in sys.argv:
        idx = sys.argv.index('--data-dir')
        data_dir = sys.argv[idx + 1]
    sample = [
        {
            'protocol': 'Ethereum', 'staked_asset': 'ETH', 'gross_apy_pct': 4.5,
            'lockup_days': 0, 'slashing_risk_pct': 1.0, 'slashing_penalty_pct': 5.0,
            'exit_cost_pct': 0.0, 'reward_compounding': 'DAILY', 'validator_count': 10,
            'capital_usd': 50000,
        },
        {
            'protocol': 'Cosmos', 'staked_asset': 'ATOM', 'gross_apy_pct': 14.0,
            'lockup_days': 21, 'slashing_risk_pct': 2.0, 'slashing_penalty_pct': 5.0,
            'exit_cost_pct': 0.5, 'reward_compounding': 'DAILY', 'validator_count': 5,
            'capital_usd': 20000,
        },
    ]
    if mode == '--run':
        result = run(sample, data_dir=data_dir)
    else:
        result = analyze(sample)
    print(json.dumps(result, indent=2))
