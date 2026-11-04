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


def _ru_bars(n):
    from spa_core.utils.presentation import ru_plural
    return ru_plural(n, "бар", "бара", "баров")


def _ro(path):
    from spa_core.trading_research.read_model import open_ro   # одна дверь read-only (migrate_callsites)
    return open_ro(path)


def _vs_hold(v):
    if not isinstance(v, dict):
        return {'state': 'UNKNOWN', 'text': 'сравнение с HOLD не посчитано (статус старой версии)'}
    if v.get('state') != 'MEASURED':
        return {'state': v.get('state') or 'UNKNOWN', 'text': v.get('why') or 'сравнение с HOLD не измерено'}
    ex = v['excess_vs_hold']
    return {'state': 'MEASURED', 'forward_net': v['forward_net'], 'hold_net': v['hold_net'], 'excess': ex,
            'text': f"{'лучше' if ex > 0 else 'хуже' if ex < 0 else 'наравне с'} HOLD на {abs(ex) * 100:.1f} п.п. "
                    f"за то же окно ({v['bars']} {_ru_bars(v['bars'])}), после издержек"}


def _research_card(st, fwd, days=None):
    """Что исследуется, против чего, насколько верить — словами, без суммы доходностей разных стратегий."""
    rq = st.get('research_quality') if isinstance(st.get('research_quality'), dict) else {}
    md = rq.get('market_data') if isinstance(rq.get('market_data'), dict) else {}
    sel = (rq.get('selection') or {}) if isinstance(rq.get('selection'), dict) else {}
    a, e = sel.get('all_trials') or {}, sel.get('effective_trials') or {}
    dsr = {}
    for k, blk in (('all', a), ('eff', e)):
        for cid, v in (blk.get('candidates') or {}).items():
            if isinstance(v, dict) and v.get('state') == 'MEASURED':
                dsr.setdefault(cid, {})[k] = v.get('dsr')
    luck = [c for c, v in dsr.items() if (v.get('eff') if v.get('eff') is not None else v.get('all', 0)) >= 0.95]
    if not dsr:
        trust = 'поправка на отбор не посчитана — достоверность отбора НЕ ИЗМЕРЕНА'
    elif luck:
        trust = f'с поправкой на отбор отличимы от удачи: {len(luck)} из {len(dsr)}'
    else:
        trust = (f"с поправкой на отбор ({a.get('trials_tested')} испытаний; эффективно ≈{e.get('trials_used')}) ни один "
                 f"из {len(dsr)} не отличим от удачи (DSR < 0.95)")
    return {
        'hypothesis': 'правила тренда/импульса/возврата на BTC (10 семейств, 1h/4h/1D) лучше, чем держать BTC, после издержек',
        'control': 'HOLD BTC за то же окно, с издержками входа',
        'selection': {'trials_tested': a.get('trials_tested'), 'trials_effective': e.get('trials_used'),
                      'dsr': dsr, 'text': trust},
        'data': {'state': md.get('state') or 'UNKNOWN',
                 'text': (f"рыночные данные свежие ({md.get('age_minutes')} мин)" if md.get('state') == 'FRESH' else
                          f"рыночные данные УСТАРЕЛИ ({md.get('age_minutes')} мин)" if md.get('state') == 'STALE' else
                          md.get('why') or 'свежесть рыночных данных не измерена')},
        'next_check': (f'forward {days} дн. < {MATURITY_DAYS}: ждать зрелости; затем — повторный отбор только с '
                       f'предрегистрацией и бюджетом попыток' if days is None or days < MATURITY_DAYS else
                       f'forward зрелый ({days} дн. ≥ {MATURITY_DAYS}): решение о кандидатах — по сравнению с HOLD и '
                       f'поправке на отбор выше; новый отбор — только с предрегистрацией и бюджетом попыток'),
    }


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
            # находка F12/T06: лента BUY/SELL — пары «сигнал → виртуальное исполнение» из ledger, только чтение
            from spa_core.trading_research.read_model import signal_events
            out['signal_events'] = signal_events(con, [c['id'] for c in fwd], now_ms=int(nowms))
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
                                     'observations': c.get('forward_observations'),
                                     # мандат 01.11 §2.6: тот же forward против HOLD BTC за ТО ЖЕ окно, после издержек
                                     'vs_hold': _vs_hold(c.get('vs_hold'))} for c in fwd]}
    out['research'] = _research_card(st, fwd, (out.get('history') or {}).get('calendar_days'))
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


def investment_engine_modes(earn_dir=None, now=None):
    """Режим каждого инвестиционного движка — ОТДЕЛЬНАЯ ось от здоровья процессов (находки F2/T01/T02).

    Только чтение собственного ledger движка. Блокировка движка (INCIDENT) — это факт о финансовом контуре,
    а не о том, живы ли службы: службы могут честно быть OK, пока движку запрещены новые позиции.
    Инцидент earn-defi ЗАЩЁЛКНУТ: снимается только вручную (`earn_defi.risk.kill_conditions.clear_incident`,
    CLI `incident-clear`). Само условие дневной цикл перепроверяет каждый день и при новом срабатывании открыл бы
    новую запись — поэтому видны «последний оценённый день» и «срабатываний после открытия».
    Возвращает ``{"observed_at", "engines": [...]}``; нечитаемый ledger — ``mode=None`` с причиной (инв. #17)."""
    now = now or datetime.now(timezone.utc)
    root = Path(earn_dir or os.environ.get('EARN_DEFI_DIR') or Path.home() / 'Documents' / 'earn-defi')
    db = root / 'data' / 'earn_defi.db'
    eng = {'engine': 'earn_defi', 'title': 'earn-defi (BTC + стабильная нога, paper)', 'source': f'{db}#system_state,incidents',
           'mode': None, 'incident': None, 'reason': None}
    if not db.exists():
        eng['reason'] = f'ledger earn-defi не найден ({db})'
        return {'observed_at': now.isoformat(), 'engines': [eng]}
    try:
        con = _ro(db)
        try:
            state = dict(con.execute('SELECT key, value FROM system_state').fetchall())
            ts = dict(con.execute('SELECT key, updated_at_utc FROM system_state').fetchall()) if _has_col(con, 'system_state', 'updated_at_utc') else {}
            # Таблица incidents только дописывается: каждое срабатывание — новая строка OPEN, снятие — строка CLEARED.
            # Текущий инцидент = ПЕРВЫЙ OPEN после последнего CLEARED; «срабатываний после открытия» — остальные OPEN
            # (ревью 04.11: прежний «последний OPEN» делал это число нулём по построению, а не по замеру).
            rows = con.execute("SELECT id, ts_utc, payload, state FROM incidents ORDER BY id").fetchall() \
                if _has_col(con, 'incidents', 'ts_utc') and _has_col(con, 'incidents', 'state') else []
            last_clear = max((r[0] for r in rows if r[3] == 'CLEARED'), default=0)
            opens = [r for r in rows if r[3] == 'OPEN' and r[0] > last_clear]
            inc = opens[0] if opens else None
            later = len(opens) - 1 if opens else None
            # дневной цикл оценивает KC-1 на каждый день NAV: последний день данных и момент записи — из ledger
            last_day, last_ts = (con.execute('SELECT MAX(date), MAX(ts_utc) FROM nav_daily').fetchone()
                                 if _has_col(con, 'nav_daily', 'date') and _has_col(con, 'nav_daily', 'ts_utc') else (None, None))
        finally:
            con.close()
    except sqlite3.Error as e:
        eng['reason'] = f'ledger не читается: {e}'
        return {'observed_at': now.isoformat(), 'engines': [eng]}
    eng['mode'] = state.get('system_mode')
    eng['mode_since'] = ts.get('system_mode')
    eng['ledger_last_write'] = last_ts
    if inc:
        try:
            p = json.loads(inc[2]) if inc[2] else {}
        except (TypeError, ValueError):   # битая запись не прячет известный режим (ревью 04.11)
            p = {'detail': 'запись инцидента не разбирается'}
        p = p if isinstance(p, dict) else {}
        eng['incident'] = {'id': inc[0], 'opened_at': inc[1], 'kc': p.get('kc'), 'data_date': p.get('date'),
                           'detail': p.get('detail'), 'latched': True,
                           # день данных, на котором дневной цикл последний раз оценивал условие (None — не измерено)
                           'last_condition_check': last_day, 'later_triggers': later,
                           'clear_by': 'владелец (earn-defi CLI incident-clear --reason …)',
                           'effect': 'новые позиции запрещены, уменьшение разрешено'}
    # момент наблюдения — последняя запись дневного цикла в ledger, а не время чтения (ревью 04.11, F14)
    return {'observed_at': last_ts or None, 'engines': [eng]}


def _has_col(con, table, col):
    try:
        return any(r[1] == col for r in con.execute(f'PRAGMA table_info({table})').fetchall())
    except sqlite3.Error:
        return False


def build_trading(now=None, data_dir=None, earn_dir=None):
    return {'schema': 'earn-defi/trading/1', 'generated_at': (now or datetime.now(timezone.utc)).isoformat(),
            'blocks': [build_spa_trading(data_dir=data_dir, now=now), build_earn_defi(earn_dir=earn_dir, now=now)],
            'note': 'Два отдельных движка, свои ledgers. Доходности НЕ суммируются: разные universe, размер позиции и '
                    'издержки. Всё — бумажная торговля, реальный капитал $0.'}


