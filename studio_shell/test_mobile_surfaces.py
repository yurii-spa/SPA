#!/usr/bin/env python3
"""Guards for the Owner-Remote surfaces (CAPITAL/STRATEGIES projectors) + VOICE safety classifier.

Positive-control style: every test asserts a property that a real defect would break. The classifier
test reproduces the Cyrillic `\\b` bug (money commands leaking into GREEN) and fails loudly if a RED
phrase is ever misclassified. Node absence is a THIRD outcome (explicit failure), never a silent skip.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
import build_mobile  # noqa: E402


# ── projector invariants ────────────────────────────────────────────────────────────────
def test_capital_paper_mode_is_never_real():
    cap = build_mobile.build_capital()
    assert cap['present'], cap
    # current mode is read_only_simulation → PAPER track, and REAL must be NOT AVAILABLE (None)
    assert cap['track'] == 'PAPER', cap['track']
    assert cap['tracks']['REAL'] is None, 'REAL must never carry a value under a paper mode'
    assert cap['tracks']['PAPER'] == cap['total_usd']
    assert cap['tracks']['SHADOW'] is None


def test_capital_live_mode_maps_to_real():
    # only LIVE is real money — proven by driving the mapping directly
    import types
    fake = {'execution_mode': 'live', 'capital_usd': 1.0, 'positions_detail': {}}
    orig = build_mobile._load
    build_mobile._load = lambda p: (fake, {'freshness': 'LIVE'}) if 'current_positions' in str(p) else ({}, {})
    try:
        cap = build_mobile.build_capital()
    finally:
        build_mobile._load = orig
    assert cap['track'] == 'REAL' and cap['tracks']['REAL'] == 1.0
    _ = types  # keep import meaningful


def test_every_allocation_has_provenance_and_track():
    cap = build_mobile.build_capital()
    for a in cap['allocations']:
        assert a['provenance'].startswith('data/current_positions.json#'), a
        assert a['track'] == cap['track']
        # apy_evidenced is a real boolean derived from apy_source == 'live', never invented
        assert a['apy_evidenced'] == (a['apy_source'] == 'live')


def test_strategies_carry_status_and_provenance():
    s = build_mobile.build_strategies()
    assert s['present'] and s['total'] == len(s['strategies'])
    for st in s['strategies']:
        assert st['status'], 'lifecycle status must be present (real value or explicit UNKNOWN)'
        assert st['provenance'].startswith('data/strategy_summary.json#')


# ── VOICE safety classifier (the security-critical path) ─────────────────────────────────
_NODE_HARNESS = r"""
import { classifyIntent } from './surfaces.js';
const CASES = %s;
let bad = [];
for (const [p, exp] of CASES) {
  const z = classifyIntent(p).zone;
  if (z !== exp) bad.push(p + ' => ' + z + ' (expected ' + exp + ')');
}
process.stdout.write(JSON.stringify(bad));
"""

_CASES = [
    # RED — money / signing / execution / risk changes must NEVER be GREEN (RU + EN)
    ["переведи деньги", "RED"],
    ["переведи 20000 долларов в aave", "RED"],
    ["купи BTC", "RED"],
    ["купи биткоин на весь кэш", "RED"],
    ["продай позицию pendle", "RED"],
    ["выведи весь кэш", "RED"],
    ["подпиши транзакцию", "RED"],
    ["включи реальное исполнение", "RED"],
    ["включи live execution", "RED"],
    ["перейти на live", "RED"],
    ["измени risk limit", "RED"],
    ["измени лимит концентрации", "RED"],
    ["отключи стоп-кран", "RED"],
    ["transfer money to compound", "RED"],
    ["buy BTC", "RED"],
    ["sell the pendle position", "RED"],
    ["sign the transaction", "RED"],
    ["enable live execution", "RED"],
    ["change the risk limit", "RED"],
    ["disable kill switch", "RED"],
    # ambiguous — RED must WIN over any task/nav match (conservative)
    ["создай задачу перевести деньги в aave", "RED"],
    ["покажи и переведи капитал", "RED"],
    # YELLOW — canonical task / decision needs confirm
    ["создай задачу проверить свежесть APY", "YELLOW"],
    ["создай задачу проверить Morpho", "YELLOW"],
    ["запиши решение поднять буфер кэша", "YELLOW"],
    ["запиши решение пока не запускать live", "YELLOW"],
    ["create a task to review adapters", "YELLOW"],
    # GREEN — navigation / query / draft capture execute immediately
    ["покажи капитал", "GREEN"],
    ["какие стратегии в paper", "GREEN"],
    ["что требует моего внимания", "GREEN"],
    ["почему Aave заблокирован", "GREEN"],
    ["открой систему", "GREEN"],
    ["сколько у нас стратегий", "GREEN"],
    ["запиши идею про новый источник дохода", "GREEN"],
]


def test_voice_classifier_safety():
    node = shutil.which('node')
    if node is None:
        # absence of the tool is a THIRD outcome, not a pass — fail loudly (inv #17 culture)
        pytest.fail('node not found: cannot verify voice safety classifier (not measured ≠ safe)')
    harness = _NODE_HARNESS % json.dumps(_CASES, ensure_ascii=False)
    out = subprocess.run([node, '--input-type=module', '-e', harness],
                         cwd=HERE, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    bad = json.loads(out.stdout.strip() or '[]')
    assert bad == [], 'voice classifier misclassified (RED leaking is a safety defect): ' + '; '.join(bad)


def test_voice_server_csrf_and_rebinding_guards():
    """Positive control for the CSRF / DNS-rebinding fix: a write-capable loopback server must reject
    non-loopback Host (rebinding), cross-origin Origin (CSRF), missing token, and non-JSON (form CSRF).
    Only rejection paths are exercised — none of them reach a canonical write, so nothing is created."""
    import http.client
    import importlib.util
    import threading
    from http.server import ThreadingHTTPServer
    spec = importlib.util.spec_from_file_location('voice_server', HERE / 'voice_server.py')
    vs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vs)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), vs.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        def req(method, path, headers=None, body=None):
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in (headers or {}).items():
                c.putheader(k, v)
            if body is not None:
                c.putheader('Content-Length', str(len(body)))
            c.endheaders()
            if body is not None:
                c.send(body.encode())
            r = c.getresponse(); r.read(); c.close(); return r.status

        LOOP = 'application/json'
        # DNS rebinding: attacker hostname in Host
        assert req('GET', '/voice/health', {'Host': 'evil.attacker.com'}) == 403
        # cross-origin CSRF on a write
        assert req('POST', '/voice/task', {'Host': '127.0.0.1', 'Origin': 'http://evil.com', 'Content-Type': LOOP}, '{"confirmed":true}') == 403
        # missing token
        assert req('POST', '/voice/task', {'Host': '127.0.0.1', 'Content-Type': LOOP}, '{"confirmed":true}') == 403
        # form CSRF: non-JSON content type
        assert req('POST', '/voice/task', {'Host': '127.0.0.1', 'Content-Type': 'text/plain'}, '{"confirmed":true}') == 415
        # legit loopback health works
        assert req('GET', '/voice/health', {'Host': '127.0.0.1'}) == 200
    finally:
        srv.shutdown()


_PARITY_CORPUS = [
    "переведи деньги", "переведи 10000 в aave", "купи BTC", "продай позицию pendle",
    "выведи весь кэш", "подпиши транзакцию", "включи live execution", "перейти на live",
    "измени risk limit", "отключи стоп-кран", "transfer money", "sell the position",
    "sign the transaction", "enable live execution", "disable kill switch",
    "создай задачу перевести деньги в aave", "поставь задачу продать pendle",
    "создай задачу проверить APY Morpho", "запиши решение пока не запускать X",
    "create a task to review adapters", "покажи капитал", "какие стратегии в paper",
    "что требует моего внимания", "почему Aave заблокирован", "открой систему",
    "статус Aave", "сколько у нас стратегий", "запиши идею про Base", "почему aave",
]


def test_js_python_classifier_parity():
    """The JS mirror (surfaces.js) and the Python authority (spa_core.owner_remote.intent) MUST agree on
    the zone for every phrase — otherwise the web UI and Telegram would apply different safety rules."""
    node = shutil.which('node')
    if node is None:
        pytest.fail('node not found: cannot verify JS↔Python classifier parity (not measured ≠ safe)')
    import json as _json
    harness = (
        "import { classifyIntent } from './surfaces.js';\n"
        "const C = " + _json.dumps(_PARITY_CORPUS, ensure_ascii=False) + ";\n"
        "process.stdout.write(JSON.stringify(C.map(t => classifyIntent(t).zone)));\n")
    out = subprocess.run([node, '--input-type=module', '-e', harness],
                         cwd=HERE, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    js_zones = _json.loads(out.stdout.strip())

    import sys as _sys
    _sys.path.insert(0, str(HERE.parent))
    from spa_core.owner_remote.intent import classify
    disagree = []
    for phrase, jz in zip(_PARITY_CORPUS, js_zones):
        pz = classify(phrase)["zone"]
        if pz != jz:
            disagree.append(f"{phrase!r}: JS={jz} Python={pz}")
    assert disagree == [], "classifier drift (web vs Telegram safety rules diverge): " + "; ".join(disagree)


def test_server_red_defence_in_depth():
    """The loopback server independently refuses action-like text (client block is not the only gate)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('voice_server', HERE / 'voice_server.py')
    vs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vs)
    reds = [
        'переведи деньги', 'перевести деньги в aave', 'купи BTC', 'продай позицию',
        'подпиши транзакцию', 'включи live execution', 'измени risk limit', 'disable kill switch',
        'transfer money', 'sign the transaction', 'enable live execution',
    ]
    for r in reds:
        assert vs.RED_RE.search(r), f'server RED defence missed: {r}'
    # a plain task must NOT trip the server RED filter
    assert not vs.RED_RE.search('проверить свежесть Morpho')
    # decision write is explicitly not available
    assert vs._stt_engine() in ('LOCAL_WHISPER', 'NONE')


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-q']))
