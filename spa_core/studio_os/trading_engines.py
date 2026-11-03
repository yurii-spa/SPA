"""Два раздельных paper-движка — SPA Trading Research и earn-defi — одним проектором (S3 E7.4 → S4 K3).

Перенесено из ``studio_shell/build_mobile.py`` ОДНОЙ копией: им пользуются и локальный ``studio_shell``
(вкладка S3), и пульт владельца Director OS (``mission_control.build`` → ``capital.trading_engines``).
Каждый движок читает СВОИ ledgers (sqlite ``mode=ro``); доходности не суммируются — разные universe,
размер позиции и издержки. Отсутствующий источник — UNKNOWN с причиной. Ничего не пишет.

Совокупный допуск ``capital_shadow/aggregate.py`` (S3 E6.3) здесь НЕ показывается как действующая
защита: он доказан только в shadow-модуле и к рабочему циклу не подключён.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


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



MATURITY_DAYS = 30                      # тот же порог зрелости, что у публикуемых ставок (REPORTABLE_AFTER)


def _fresh(age_s, cadence_s=900):
    """Freshness against the engine's OWN cadence: SPA ticks every 15 min, earn-defi decides once a day."""
    if age_s is None:
        return 'UNKNOWN'
    return 'LIVE' if age_s < cadence_s else 'RECENT' if age_s < 2 * cadence_s + 3600 else 'STALE'


def _ro(path):
    from spa_core.trading_research.read_model import open_ro   # одна дверь read-only (migrate_callsites)
    return open_ro(path)


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


def build_trading(now=None, data_dir=None, earn_dir=None):
    return {'schema': 'earn-defi/trading/1', 'generated_at': (now or datetime.now(timezone.utc)).isoformat(),
            'blocks': [build_spa_trading(data_dir=data_dir, now=now), build_earn_defi(earn_dir=earn_dir, now=now)],
            'note': 'Два отдельных движка, свои ledgers. Доходности НЕ суммируются: разные universe, размер позиции и '
                    'издержки. Всё — бумажная торговля, реальный капитал $0.'}


