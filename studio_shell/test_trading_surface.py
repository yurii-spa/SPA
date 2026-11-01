#!/usr/bin/env python3
"""S3 E7.4: TRADING surface projector — two separate engine blocks, never summed, gaps are UNKNOWN.

Synthetic ledgers in tmp (no live data). Layout at 390/430 px is checked by check_trading_layout.py (Chrome)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import build_mobile as bm

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — build_*(now=NOW); every stamp derives from NOW
MS = int(NOW.timestamp() * 1000)


def _spa(tmp, *, age_s=60, days=31, verified=True):
    d = tmp / 'tr'
    d.mkdir()
    since = MS - days * 86_400_000
    fwd = [{'id': 'a@v1:BTC:1D:spot_long:1', 'forward_net': -0.04, 'forward_observations': 31},
           {'id': 'b@v1:BTC:4h:spot_long:2', 'forward_net': 0.03, 'forward_observations': 186}]
    (d / 'status.json').write_text(json.dumps({'generated_at_ms': MS - age_s * 1000, 'ok': True, 'live_capital_usd': 0,
                                               'forward_since_ms': since, 'last_bar_close_ms': {'1D': MS - 3_600_000},
                                               'observations': 10, 'evidence_verified': verified,
                                               'forward_candidates': fwd}))
    c = sqlite3.connect(d / 'evidence.db')
    c.execute('CREATE TABLE observations (candidate_id, bar_open_time, bar_close_time, action, position_held, signal_ts_ms)')
    for f in fwd:
        c.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)', (f['id'], MS - 2 * 86_400_000, MS - 86_400_000, 'HOLD', 0, MS))
    c.commit()
    return d


def _earn(tmp, *, mode='INCIDENT', age_h=3, days=59):
    root = tmp / 'earn'
    (root / 'data').mkdir(parents=True)
    c = sqlite3.connect(root / 'data' / 'earn_defi.db')
    c.executescript('CREATE TABLE decisions (id INTEGER PRIMARY KEY, ts_utc, payload);'
                    'CREATE TABLE nav_daily (id INTEGER PRIMARY KEY, date, payload, backfilled);'
                    'CREATE TABLE system_state (key, value);'
                    'CREATE TABLE incidents (id INTEGER PRIMARY KEY, payload, state);')
    ts = (NOW - timedelta(hours=age_h)).isoformat().replace('+00:00', 'Z')
    c.execute('INSERT INTO decisions (ts_utc, payload) VALUES (?, ?)', (ts, json.dumps(
        {'action': 'HOLD', 'date': '2026-10-31', 'config_version': '0.3', 'reasons': ['r1', 'deviation within threshold']})))
    for i in range(days):
        c.execute('INSERT INTO nav_daily (date, payload, backfilled) VALUES (?, ?, ?)',
                  (f'D{i:03d}', json.dumps({'date': f'D{i:03d}', 'nav_usdt': 100_000 + i, 'cum_return': 0.002,
                                            'max_drawdown': -0.07}), 'false'))
    c.execute("INSERT INTO system_state VALUES ('system_mode', ?)", (mode,))
    c.execute("INSERT INTO incidents (payload, state) VALUES (?, 'OPEN')", (json.dumps({'kc': 'KC-1', 'detail': 'price source'}),))
    c.commit()
    return root


def test_two_separate_blocks_and_nothing_is_summed(tmp_path, monkeypatch):
    monkeypatch.setenv('SPA_TRADING_DATA_DIR', str(_spa(tmp_path)))
    monkeypatch.setenv('EARN_DEFI_DIR', str(_earn(tmp_path)))
    t = bm.build_trading(now=NOW)
    assert [b['engine'] for b in t['blocks']] == ['spa_trading_research', 'earn_defi']
    spa, earn = t['blocks']
    assert spa['paper_result']['summed'] is False and len(spa['paper_result']['rows']) == 2
    assert earn['paper_result']['kind'] == 'nav' and earn['paper_result']['summed'] is False
    assert not any(k in json.dumps(t) for k in ('"total_return"', '"combined"', '"sum"'))


def test_spa_block_fields_and_hold_reason(tmp_path):
    b = bm.build_spa_trading(_spa(tmp_path), now=NOW)
    assert b['freshness'] == 'LIVE' and b['live_capital_usd'] == 0
    assert b['last_decision']['actions'] == {'HOLD': 2} and b['why_hold']
    assert b['history']['calendar_days'] >= 30 and b['why_no_result'] is None and b['active_block'] is None


def test_spa_immature_history_names_why_there_is_no_result(tmp_path):
    b = bm.build_spa_trading(_spa(tmp_path, days=10), now=NOW)
    assert b['why_no_result'] and '< 30' in b['why_no_result']


def test_spa_broken_chain_is_an_active_block_and_stale_is_stale(tmp_path):
    b = bm.build_spa_trading(_spa(tmp_path, verified=False, age_s=3 * 3600), now=NOW)
    assert 'цепочка' in b['active_block'] and b['freshness'] == 'STALE'


def test_missing_sources_are_unknown_with_reason_not_zero(tmp_path):
    spa = bm.build_spa_trading(tmp_path / 'nope', now=NOW)
    earn = bm.build_earn_defi(tmp_path / 'nope', now=NOW)
    for b in (spa, earn):
        assert b['present'] is False and b['freshness'] == 'UNKNOWN' and b['why_no_result']
        assert 'paper_result' not in b


def test_earn_defi_incident_is_the_active_block_and_daily_cadence_is_fresh(tmp_path):
    b = bm.build_earn_defi(_earn(tmp_path, age_h=20), now=NOW)
    assert b['freshness'] == 'LIVE'                   # дневной движок: 20 ч — внутри своего такта, не «устарело»
    assert bm.build_earn_defi(_earn(tmp_path / 'z', age_h=30), now=NOW)['freshness'] == 'RECENT'
    assert 'INCIDENT' in b['active_block'] and 'KC-1' in b['active_block']
    assert b['why_hold'] == 'deviation within threshold'
    assert b['history']['observed_days'] == 59 and b['history']['backfilled_days'] == 0
    assert bm.build_earn_defi(_earn(tmp_path / 'x', mode='NORMAL', age_h=60), now=NOW)['active_block'] is None
    assert bm.build_earn_defi(_earn(tmp_path / 'y', age_h=60), now=NOW)['freshness'] == 'STALE'
