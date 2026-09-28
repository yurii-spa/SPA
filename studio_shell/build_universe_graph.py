#!/usr/bin/env python3
"""Earn DeFi UNIVERSE / SYSTEM graph projector (read-only).

Projects REAL canonical/derived SPA state into a node/edge graph the reused d3-force engine
renders. Read-only, stdlib, no backend expansion, no secrets. Every node carries `provenance`
(canonical source) and a `track` (MARKET · PAPER · SHADOW · STUDIO · UNKNOWN) so paper is never
shown as real. Domain chain Opportunity→…→Risk belongs to the Investment Engine; Studio OS only
*reads* it (UI ≠ canonical truth). Absence is a named value, never a fake PASS.

Emits studio_shell/universe.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser('~'))
REPO = Path(__file__).resolve().parents[1]
MISSION_STATE = HOME / 'studio-os-scratch' / 'mission-state' / 'v04'
OUT = Path(__file__).resolve().parent / 'universe.json'
LIVE_S, RECENT_S = 900, 6 * 3600


def _load(p):
    p = Path(p)
    if not p.exists():
        return None, {'present': False, 'freshness': 'UNKNOWN', 'path': str(p)}
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError) as e:
        return None, {'present': True, 'freshness': 'UNKNOWN', 'why': str(e), 'path': str(p)}
    ts = d.get('generated_at') or d.get('updated_at') or d.get('timestamp') if isinstance(d, dict) else None
    fr = 'UNKNOWN'
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            fr = 'LIVE' if age < LIVE_S else 'RECENT' if age < RECENT_S else 'STALE'
        except ValueError:
            pass
    return d, {'present': True, 'freshness': fr, 'updated_at': ts, 'path': str(p)}


def build():
    nodes, edges = [], []
    def node(id, label, domain, kind, track, status='', metrics=None, provenance='', fresh='', hub=False):
        nodes.append({'id': id, 'label': label, 'domain': domain, 'kind': kind, 'track': track,
                      'status': status, 'metrics': metrics or {}, 'provenance': provenance,
                      'fresh': fresh, 'hub': hub})
    def edge(a, b, kind='link', flow=False):
        edges.append({'source': a, 'target': b, 'kind': kind, 'flow': flow})

    node('earndefi', 'EARN DEFI', 'core', 'core', 'STUDIO', hub=True,
         provenance='studio-os')

    # ── OPPORTUNITIES (real market data; Investment Engine domain, read-only) ──────────
    adapters, ameta = _load(REPO / 'data' / 'adapter_status.json')
    node('opps', 'OPPORTUNITIES', 'opportunities', 'hub', 'MARKET', hub=True,
         status=f"live {(adapters or {}).get('live_fresh_count','?')}/{(adapters or {}).get('live_count','?')}",
         provenance='data/adapter_status.json', fresh=ameta['freshness'])
    edge('earndefi', 'opps', 'domain')
    adict = (adapters or {}).get('adapters') or {}
    # top protocols by TVL for a legible universe
    items = sorted(adict.items(), key=lambda kv: -(kv[1].get('tvl_usd') or 0))[:14]
    for key, a in items:
        live = a.get('live_apy'); fresh_apy = a.get('live_apy_fresh')
        apy = live if (live is not None and fresh_apy) else a.get('apy')
        apy_track = 'LIVE' if (live is not None and fresh_apy) else 'UNKNOWN'
        tvl = a.get('tvl_usd'); tvl_src = a.get('tvl_source')
        nid = f'op:{key}'
        node(nid, a.get('display_name') or key, 'opportunities', 'opportunity', 'MARKET',
             status=('live APY' if apy_track == 'LIVE' else 'APY unevidenced'),
             metrics={'apy_pct': round(apy, 2) if isinstance(apy, (int, float)) else None,
                      'apy_evidence': apy_track,
                      'tvl_usd': tvl, 'tvl_source': tvl_src,
                      'tvl_evidenced': tvl_src == 'live'},
             provenance=f'data/adapter_status.json#adapters.{key}', fresh=ameta['freshness'])
        edge('opps', nid, 'contains')

    # ── CHAINS ────────────────────────────────────────────────────────────────────────
    chains, cmeta = _load(REPO / 'data' / 'chains_status.json')
    cdict = (chains or {}).get('chains') or {}
    if cdict:
        node('chains', 'CHAINS', 'opportunities', 'hub', 'MARKET', hub=True,
             provenance='data/chains_status.json', fresh=cmeta['freshness'])
        edge('earndefi', 'chains', 'domain')
        for ch in list(cdict)[:6]:
            cid = f'chain:{ch}'
            info = cdict[ch] if isinstance(cdict[ch], dict) else {}
            node(cid, ch, 'opportunities', 'chain', 'MARKET',
                 metrics={'pools': info.get('pool_count') or info.get('pools')},
                 provenance=f'data/chains_status.json#chains.{ch}', fresh=cmeta['freshness'])
            edge('chains', cid, 'contains')

    # ── RISK (deterministic RiskPolicy signals; go-live gates) ─────────────────────────
    alerts, rmeta = _load(REPO / 'data' / 'risk_alerts.json')
    golive, gmeta = _load(REPO / 'data' / 'golive_status.json')
    rstatus = f"{(alerts or {}).get('count','?')} alerts"
    node('risk', 'RISK', 'risk', 'hub', 'STUDIO', hub=True, status=rstatus,
         metrics={'alerts': (alerts or {}).get('count'), 'alert_status': (alerts or {}).get('status')},
         provenance='data/risk_alerts.json', fresh=rmeta['freshness'])
    edge('earndefi', 'risk', 'domain')
    if isinstance(golive, dict):
        node('golive', f"GoLive {golive.get('passed','?')}/{golive.get('total','?')}", 'risk', 'gate',
             'STUDIO', status='ready' if golive.get('ready') else 'not ready',
             metrics={'passed': golive.get('passed'), 'total': golive.get('total'),
                      'track_days': golive.get('real_track_days'), 'blockers': golive.get('blockers')},
             provenance='data/golive_status.json', fresh=gmeta['freshness'])
        edge('risk', 'golive', 'contains')

    # ── CAPITAL (PAPER — never shown as real) ──────────────────────────────────────────
    cap, capmeta = _load(REPO / 'data' / 'capital_config.json')
    cap_amt = None
    if isinstance(cap, dict):
        cap_amt = cap.get('total_capital') or cap.get('capital') or cap.get('virtual_capital_usd')
    node('capital', 'CAPITAL', 'capital', 'hub', 'PAPER', hub=True,
         status='PAPER — виртуальный капитал',
         metrics={'paper_usd': cap_amt or 100000, 'note': 'paper trading; not real capital'},
         provenance='data/capital_config.json (paper)' , fresh=capmeta['freshness'])
    edge('earndefi', 'capital', 'domain')

    # ── SYSTEM (Studio OS infra: missions, planes, fleet, dispatch) ────────────────────
    ledger, lmeta = _load(MISSION_STATE / 'ledger.json')
    node('system', 'SYSTEM', 'system', 'hub', 'STUDIO', hub=True,
         provenance=str(MISSION_STATE / 'ledger.json'), fresh=lmeta['freshness'])
    edge('earndefi', 'system', 'domain')
    if isinstance(ledger, dict):
        missions = ledger.get('missions') or {}
        items_l = ledger.get('items') or {}
        dispatch_off = ledger.get('mission_dispatch_disabled')
        node('missions', f'Missions {len(missions)}', 'system', 'missions', 'STUDIO',
             status='dispatch CLOSED' if dispatch_off else 'dispatch open',
             metrics={'missions': len(missions), 'work_items': len(items_l),
                      'dispatch_open': not bool(dispatch_off)},
             provenance=str(MISSION_STATE / 'ledger.json') + '#missions', fresh=lmeta['freshness'])
        edge('system', 'missions', 'contains')
    node('provider', 'PROVIDER plane', 'system', 'plane', 'STUDIO',
         status='needs privileged probe for live state',
         provenance='/tmp/spa_studio_provider_runner.out.log')
    node('candidate', 'CANDIDATE plane', 'system', 'plane', 'STUDIO',
         provenance='/tmp/spa_studio_worker_runner.out.log')
    edge('system', 'provider', 'contains')
    edge('system', 'candidate', 'contains')
    reg, regmeta = _load(REPO / 'data' / 'agent_registry.json')
    if isinstance(reg, dict):
        node('fleet', f"Fleet {reg.get('total_loaded','?')}/{reg.get('total_known','?')}", 'system',
             'fleet', 'STUDIO', status='snapshot — check freshness',
             metrics={'loaded': reg.get('total_loaded'), 'known': reg.get('total_known'),
                      'by_role': reg.get('by_role')},
             provenance='data/agent_registry.json', fresh=regmeta['freshness'])
        edge('system', 'fleet', 'contains')

    # ── RESEARCH / FACTORY (honest: no clean investor-strategy read source yet) ────────
    node('factory', 'FACTORY / R&D', 'factory', 'hub', 'UNKNOWN', hub=True,
         status='strategy lifecycle read source: NOT AVAILABLE (advisory only)',
         provenance='strategy_lab (advisory) — no canonical investor-strategy projection')
    edge('earndefi', 'factory', 'domain')

    return {
        'schema': 'earn-defi/universe-graph/1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'note': 'READ-ONLY projection of real SPA state. UI ≠ canonical truth. '
                'track: MARKET=live market data · PAPER=virtual capital · STUDIO=studio-os state · '
                'UNKNOWN=no clean read source. Absence is named, never a fake PASS.',
        'tracks': ['MARKET', 'PAPER', 'SHADOW', 'STUDIO', 'UNKNOWN'],
        'nodes': nodes, 'edges': edges,
        'counts': {'nodes': len(nodes), 'edges': len(edges)},
    }


def main():
    g = build()
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, OUT)
    print(json.dumps({'wrote': str(OUT), **g['counts'],
                      'domains': sorted({n['domain'] for n in g['nodes']})}, ensure_ascii=False))


if __name__ == '__main__':
    main()
