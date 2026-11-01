#!/usr/bin/env python3
"""Owner-Remote read models: CAPITAL + STRATEGIES (read-only, real data).

Projects real SPA state for the mobile Owner Remote. No invented financial state; REAL/PAPER/
SHADOW never confused (current mode is PAPER — stated explicitly); missing → UNKNOWN. Each value
carries provenance. No second capital/strategy database or lifecycle — reads the canonical files.

Emits studio_shell/capital.json + studio_shell/strategies.json + studio_shell/trading.json.

TRADING (S3 E7.4): TWO SEPARATE blocks — SPA Trading Research and earn-defi. Each engine keeps its own
ledgers; nothing here joins them, and their returns are never summed (different universes, sizing and
cost models). Both read-only (sqlite ``mode=ro``); a missing source is UNKNOWN with the reason.
"""
from __future__ import annotations

import json
import os
import sqlite3
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


MATURITY_DAYS = 30                      # тот же порог зрелости, что у публикуемых ставок (REPORTABLE_AFTER)


def _fresh(age_s, cadence_s=900):
    """Freshness against the engine's OWN cadence: SPA ticks every 15 min, earn-defi decides once a day."""
    if age_s is None:
        return 'UNKNOWN'
    return 'LIVE' if age_s < cadence_s else 'RECENT' if age_s < 2 * cadence_s + 3600 else 'STALE'


def _ro(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def build_spa_trading(data_dir=None, now=None):
    """SPA Trading Research block — status.json (derived) + evidence.db (the ledger) for the last decision."""
    now = now or datetime.now(timezone.utc)
    d = Path(data_dir or os.environ.get('SPA_TRADING_DATA_DIR') or REPO / 'data' / 'trading_research')
    out = {'engine': 'spa_trading_research', 'title': 'SPA Trading Research', 'track': 'PAPER',
           'universe': 'BTCUSDT · 138 кандидатов · spot/perp-модели', 'live_capital_usd': None,
           'provenance': 'data/trading_research/{status.json,evidence.db}'}
    st, _ = _load(d / 'status.json')
    if not isinstance(st, dict) or 'generated_at_ms' not in st:
        return {**out, 'present': False, 'freshness': 'UNKNOWN', 'why_no_result': 'status.json недоступен — данных нет'}
    nowms = now.timestamp() * 1000
    out.update(present=True, live_capital_usd=st.get('live_capital_usd'),
               freshness=_fresh((nowms - st['generated_at_ms']) / 1000),
               as_of=datetime.fromtimestamp(st['generated_at_ms'] / 1000, timezone.utc).isoformat())
    since = st.get('forward_since_ms')
    lbc = st.get('last_bar_close_ms')
    last_close = max(lbc.values()) if isinstance(lbc, dict) and lbc else lbc if isinstance(lbc, (int, float)) else None
    out['history'] = {'since': datetime.fromtimestamp(since / 1000, timezone.utc).date().isoformat() if since else None,
                      'calendar_days': round((last_close - since) / 86_400_000, 1)
                      if since and last_close else None, 'observations': st.get('observations'),
                      'evidence_verified': st.get('evidence_verified')}
    fwd = [c for c in st.get('forward_candidates') or [] if isinstance(c, dict)]
    last = []
    try:
        con = _ro(d / 'evidence.db')
        try:
            for c in fwd:
                r = con.execute('SELECT bar_close_time, action, position_held, signal_ts_ms FROM observations '
                                'WHERE candidate_id=? ORDER BY bar_open_time DESC LIMIT 1', (c['id'],)).fetchone()
                if r:
                    last.append({'id': c['id'], 'bar_close': datetime.fromtimestamp(r[0] / 1000, timezone.utc).isoformat(),
                                 'action': r[1], 'position': r[2]})
        finally:
            con.close()
    except sqlite3.Error as e:
        out['ledger_error'] = f'evidence.db: {e}'
    acts = {}
    for x in last:
        acts[x['action']] = acts.get(x['action'], 0) + 1
    out['last_decision'] = {'at': max((x['bar_close'] for x in last), default=None), 'actions': acts,
                            'per_candidate': last} if last else None
    # paper result PER candidate — five different strategies are never added into one number
    out['paper_result'] = {'kind': 'per_candidate_forward_net', 'summed': False,
                           'rows': [{'id': c['id'], 'forward_net': c.get('forward_net'),
                                     'observations': c.get('forward_observations')} for c in fwd]}
    days = out['history']['calendar_days']
    blocks = []
    if st.get('evidence_verified') is False:
        blocks.append('цепочка доказательств нарушена')
    if st.get('ok') is False:
        blocks.append('последний такт завершился ошибкой' + (f": {st.get('error')}" if st.get('error') else ''))
    out['active_block'] = '; '.join(blocks) or None
    out['why_no_result'] = (None if days is not None and days >= MATURITY_DAYS and fwd else
                            'кандидатов в forward нет' if not fwd else
                            f'forward {days} дн. < {MATURITY_DAYS} — результат ещё не зрелый')
    out['why_hold'] = ('позиции открываются только сигналом своего кандидата; HOLD = сигнал не изменился'
                       if acts.get('HOLD') else None)
    return out


def build_earn_defi(earn_dir=None, now=None):
    """earn-defi block — its OWN ledger earn_defi.db (decisions, nav_daily, incidents, system_state)."""
    now = now or datetime.now(timezone.utc)
    root = Path(earn_dir or os.environ.get('EARN_DEFI_DIR') or Path.home() / 'Documents' / 'earn-defi')
    db = root / 'data' / 'earn_defi.db'
    out = {'engine': 'earn_defi', 'title': 'earn-defi', 'track': 'PAPER', 'universe': 'BTC + стабильная нога',
           'provenance': 'earn-defi data/earn_defi.db'}
    if not db.exists():
        return {**out, 'present': False, 'freshness': 'UNKNOWN', 'why_no_result': f'ledger earn-defi не найден ({db})'}
    try:
        con = _ro(db)
        try:
            dec = con.execute('SELECT ts_utc, payload FROM decisions ORDER BY id DESC LIMIT 1').fetchone()
            nav = con.execute('SELECT payload FROM nav_daily ORDER BY id DESC LIMIT 1').fetchone()
            ndays, first = con.execute('SELECT COUNT(DISTINCT date), MIN(date) FROM nav_daily').fetchone()
            nback = con.execute("SELECT COUNT(*) FROM nav_daily WHERE backfilled NOT IN ('0','false','False','')").fetchone()[0]
            state = dict(con.execute('SELECT key, value FROM system_state').fetchall())
            inc = con.execute("SELECT payload FROM incidents WHERE state='OPEN' ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        return {**out, 'present': False, 'freshness': 'UNKNOWN', 'why_no_result': f'ledger не читается: {e}'}
    out['present'] = True
    if dec:
        p = json.loads(dec[1])
        ts = datetime.fromisoformat(dec[0].replace('Z', '+00:00'))
        out.update(freshness=_fresh((now - ts).total_seconds(), cadence_s=24 * 3600), as_of=dec[0],
                   last_decision={'at': dec[0], 'date': p.get('date'), 'action': p.get('action'),
                                  'config_version': p.get('config_version'),
                                  'target_weight': p.get('target_weight'), 'current_weight': p.get('current_weight'),
                                  'reasons': p.get('reasons') or []})
    else:
        out.update(freshness='UNKNOWN', last_decision=None)
    if nav:
        n = json.loads(nav[0])
        out['paper_result'] = {'kind': 'nav', 'summed': False, 'date': n.get('date'), 'nav_usdt': n.get('nav_usdt'),
                               'cum_return': n.get('cum_return'), 'max_drawdown': n.get('max_drawdown'),
                               'cost_total_usdt': n.get('cost_total_usdt'), 'n_trades': n.get('n_trades')}
    else:
        out['paper_result'] = None
    out['history'] = {'since': state.get('paper_start_date') or first, 'observed_days': ndays, 'backfilled_days': nback}
    mode = state.get('system_mode')
    out['active_block'] = None if mode in (None, 'NORMAL') else (
        f'режим {mode}' + (f" — {json.loads(inc[0]).get('kc')}: {json.loads(inc[0]).get('detail')}" if inc else '')
        + ' (снимает владелец)')
    out['why_no_result'] = (None if out['paper_result'] and ndays >= MATURITY_DAYS else
                            'NAV нет' if not out['paper_result'] else f'наблюдённых дней {ndays} < {MATURITY_DAYS}')
    act = (out.get('last_decision') or {}).get('action')
    out['why_hold'] = ((out['last_decision']['reasons'] or ['причина не записана'])[-1] if act == 'HOLD' else None)
    return out


def build_trading(now=None):
    return {'schema': 'earn-defi/trading/1', 'generated_at': (now or datetime.now(timezone.utc)).isoformat(),
            'blocks': [build_spa_trading(now=now), build_earn_defi(now=now)],
            'note': 'Два отдельных движка, свои ledgers. Доходности НЕ суммируются: разные universe, размер позиции и '
                    'издержки. Всё — бумажная торговля, реальный капитал $0.'}


def main():
    cap = build_capital(); strat = build_strategies()
    (HERE / 'trading.json').write_text(json.dumps(build_trading(), ensure_ascii=False, indent=1), encoding='utf-8')
    (HERE / 'capital.json').write_text(json.dumps(cap, ensure_ascii=False, indent=1), encoding='utf-8')
    (HERE / 'strategies.json').write_text(json.dumps(strat, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'capital_track': cap.get('track'), 'capital_total': cap.get('total_usd'),
                      'allocations': len(cap.get('allocations', [])), 'strategies': strat.get('total')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
