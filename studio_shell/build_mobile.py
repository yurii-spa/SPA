#!/usr/bin/env python3
"""Owner-Remote read models: CAPITAL + STRATEGIES (read-only, real data).

Projects real SPA state for the mobile Owner Remote. No invented financial state; REAL/PAPER/
SHADOW never confused (current mode is PAPER — stated explicitly); missing → UNKNOWN. Each value
carries provenance. No second capital/strategy database or lifecycle — reads the canonical files.

Emits studio_shell/capital.json + studio_shell/strategies.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def _load(p):
    p = Path(p)
    if not p.exists():
        return None, {'present': False}
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError) as e:
        return None, {'present': True, 'why': str(e)}
    ts = d.get('generated_at') or d.get('updated_at') or d.get('updated') or d.get('as_of') if isinstance(d, dict) else None
    fr = 'UNKNOWN'
    if ts:
        try:
            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            fr = 'LIVE' if age < 900 else 'RECENT' if age < 6 * 3600 else 'STALE'
        except ValueError:
            pass
    return d, {'present': True, 'freshness': fr, 'updated_at': ts}


def build_capital():
    pos, meta = _load(REPO / 'data' / 'current_positions.json')
    cfg, _ = _load(REPO / 'data' / 'capital_config.json')
    if not isinstance(pos, dict):
        return {'present': False, 'note': 'current_positions.json unavailable'}
    mode = (pos.get('execution_mode') or (cfg or {}).get('capital', {}).get('mode') or 'paper').lower()
    # LIVE is the ONLY real-money track. paper / read_only_simulation are virtual → PAPER; shadow → SHADOW.
    if mode == 'live':
        track = 'REAL'
    elif mode == 'shadow':
        track = 'SHADOW'
    else:  # paper, read_only_simulation, demo, anything else virtual
        track = 'PAPER'
    exec_mode = pos.get('execution_mode')
    allocations = []
    for name, d in (pos.get('positions_detail') or {}).items():
        if not isinstance(d, dict):
            continue
        allocations.append({
            'protocol': name, 'usd': d.get('usd'),
            'apy_pct': round(d.get('apy_pct'), 2) if isinstance(d.get('apy_pct'), (int, float)) else None,
            'apy_source': d.get('apy_source'), 'apy_evidenced': d.get('apy_source') == 'live',
            'as_of': d.get('as_of'), 'track': track,
            'provenance': f'data/current_positions.json#positions_detail.{name}',
        })
    allocations.sort(key=lambda a: -(a.get('usd') or 0))
    total = pos.get('capital_usd') or pos.get('current_equity_usd')
    return {
        'schema': 'earn-defi/capital/1', 'present': True,
        'track': track,                # everything here is PAPER today — stated, never shown as REAL
        'execution_mode': exec_mode,   # e.g. read_only_simulation — the honest sub-mode under PAPER
        'is_demo': pos.get('is_demo'),
        'total_usd': total, 'equity_usd': pos.get('current_equity_usd'),
        'deployed_usd': pos.get('deployed_usd'), 'cash_usd': pos.get('cash_usd'),
        'accrued_yield_usd': pos.get('accrued_yield_usd'),
        'policy_version': pos.get('policy_version'), 'policy_compliant': pos.get('policy_compliant'),
        # total sits under exactly ONE track (the active one); the other two stay None (NOT AVAILABLE).
        'tracks': {k: (total if k == track else None) for k in ('REAL', 'PAPER', 'SHADOW')},
        'allocations': allocations, 'freshness': meta.get('freshness', 'UNKNOWN'),
        'provenance': 'data/current_positions.json',
        'note': 'PAPER (virtual) capital — not real. REAL/SHADOW = NOT AVAILABLE.',
    }


def build_strategies():
    s, meta = _load(REPO / 'data' / 'strategy_summary.json')
    if not isinstance(s, dict):
        return {'present': False, 'note': 'strategy_summary.json unavailable'}
    out = []
    for st in (s.get('strategies') or []):
        if not isinstance(st, dict):
            continue
        out.append({
            'id': st.get('id'), 'name': st.get('name') or st.get('id'),
            'label': st.get('tournament_label'), 'type': st.get('type'),
            'tier': st.get('risk_tier'), 'status': (st.get('status') or 'UNKNOWN'),
            'apy_mid': st.get('target_apy_mid'), 'apy_min': st.get('target_apy_min'), 'apy_max': st.get('target_apy_max'),
            'max_drawdown_pct': st.get('max_drawdown_pct'), 'tags': st.get('tags'),
            'provenance': f"data/strategy_summary.json#strategies[{st.get('id')}]",
        })
    return {
        'schema': 'earn-defi/strategies/1', 'present': True, 'total': len(out),
        'strategies': out, 'freshness': meta.get('freshness', 'UNKNOWN'),
        'provenance': 'data/strategy_summary.json',
        'note': 'Advisory strategy catalogue (canonical). Lifecycle = each strategy’s own status; not a new DB.',
    }


def main():
    cap = build_capital(); strat = build_strategies()
    (HERE / 'capital.json').write_text(json.dumps(cap, ensure_ascii=False, indent=1), encoding='utf-8')
    (HERE / 'strategies.json').write_text(json.dumps(strat, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'capital_track': cap.get('track'), 'capital_total': cap.get('total_usd'),
                      'allocations': len(cap.get('allocations', [])), 'strategies': strat.get('total')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
