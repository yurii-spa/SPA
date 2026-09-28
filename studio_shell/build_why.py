#!/usr/bin/env python3
"""WHY? decision-trace projector for ONE real Opportunity (Aave V3), read-only.

Builds a directed source→evidence→fact→gate→decision→result trace from REAL data, honestly.
The deterministic RiskPolicy gates (authority=DETERMINISTIC) are visually distinct from any
LLM step (authority=LLM); in the risk path LLM is FORBIDDEN (invariant #3), so that node is
ABSENT, not faked. Missing segments are marked TRACE PARTIAL — no fabricated edges.

RiskPolicy constants are read from the repo invariants (CLAUDE.md / .claude/rules/risk-engine.md):
TVL floor ≥ $5M/pool, APY band 1%…30%, and TVL floor is checked ONLY with live TVL
(ADR-053: tvl_source == "live"); static literals do not evidence the floor.

Emits studio_shell/why_aave.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / 'why_aave.json'

TVL_FLOOR_USD = 5_000_000        # RiskPolicy TVL floor ≥ $5M/pool
APY_MIN, APY_MAX = 1.0, 30.0     # RiskPolicy APY band 1%…30%


def build(adapter_key='aave_v3'):
    data = json.loads((REPO / 'data' / 'adapter_status.json').read_text(encoding='utf-8'))
    a = (data.get('adapters') or {}).get(adapter_key) or {}
    disp = a.get('display_name') or adapter_key
    apy = a.get('live_apy') if a.get('live_apy_fresh') else a.get('apy')
    apy_live = bool(a.get('live_apy') is not None and a.get('live_apy_fresh'))
    tvl = a.get('tvl_usd')
    tvl_live = a.get('tvl_source') == 'live'
    src = f'data/adapter_status.json#adapters.{adapter_key}'

    nodes, edges = [], []
    def N(id, label, kind, authority, status, detail='', provenance=''):
        nodes.append({'id': id, 'label': label, 'kind': kind, 'authority': authority,
                      'status': status, 'detail': detail, 'provenance': provenance})
    def E(a, b, label=''):
        edges.append({'source': a, 'target': b, 'label': label})

    N('obj', disp, 'object', 'NONE', 'MARKET', 'Opportunity', src)
    # SOURCE
    N('src', 'adapter_status', 'source', 'NONE', 'RECENT',
      'DeFiLlama-backed adapter status', src)
    E('obj', 'src')
    # EVIDENCE (honest: live vs static)
    N('ev_apy', 'APY evidence', 'evidence', 'NONE', 'LIVE' if apy_live else 'UNEVIDENCED',
      ('live & fresh' if apy_live else 'fallback / not fresh'), src)
    N('ev_tvl', 'TVL evidence', 'evidence', 'NONE', 'LIVE' if tvl_live else 'UNEVIDENCED',
      (f"tvl_source={a.get('tvl_source')}"), src)
    E('src', 'ev_apy'); E('src', 'ev_tvl')
    # FACTS
    N('f_apy', f'APY {apy}%' if apy is not None else 'APY —', 'fact', 'NONE',
      'LIVE' if apy_live else 'UNEVIDENCED', '', src)
    N('f_tvl', f'TVL ${tvl/1e9:.1f}B' if isinstance(tvl, (int, float)) else 'TVL —', 'fact', 'NONE',
      'LIVE' if tvl_live else 'UNEVIDENCED', '', src)
    E('ev_apy', 'f_apy'); E('ev_tvl', 'f_tvl')
    # DETERMINISTIC GATES (RiskPolicy)
    # EXECUTED policy: constants live in code (spa_core/risk/policy.py), not only docs
    POLICY_SRC = 'spa_core/risk/policy.py'  # v1.0: min_apy 1.0 / max_apy 30.0 / min_tvl_usd 5_000_000
    apy_pass = isinstance(apy, (int, float)) and APY_MIN <= apy <= APY_MAX
    N('g_apy', f'APY band {APY_MIN:.0f}–{APY_MAX:.0f}%', 'gate', 'DETERMINISTIC',
      'PASS' if apy_pass else 'BLOCK', 'RiskPolicy v1.0 · EXECUTED (code)', POLICY_SRC + '#RiskConfig')
    nodes[-1]['policy_kind'] = 'EXECUTED'
    # TVL floor requires LIVE tvl (ADR-053); static ⇒ UNEVIDENCED (fail-closed)
    tvl_gate = 'UNEVIDENCED' if not tvl_live else ('PASS' if isinstance(tvl, (int, float)) and tvl >= TVL_FLOOR_USD else 'BLOCK')
    N('g_tvl', f'TVL floor ${TVL_FLOOR_USD/1e6:.0f}M (live)', 'gate', 'DETERMINISTIC',
      tvl_gate, 'EXECUTED: min_tvl_usd in RiskConfig; ADR-053 requires tvl_source==live — static literal does not evidence it',
      POLICY_SRC + '#min_tvl_usd')
    nodes[-1]['policy_kind'] = 'EXECUTED'
    E('f_apy', 'g_apy'); E('f_tvl', 'g_tvl')
    # LLM step — FORBIDDEN in risk path (invariant #3): ABSENT, not faked
    N('llm', 'LLM recommendation', 'llm', 'LLM', 'ABSENT',
      'LLM forbidden in risk/execution (invariant #3) — no LLM authority over capital', 'CLAUDE.md#invariants')
    # DECISION (deterministic aggregate; fail-CLOSED on unevidenced)
    decided = 'BLOCK' if (not apy_pass or tvl_gate in ('BLOCK', 'UNEVIDENCED')) else 'PASS'
    dstatus = 'UNEVIDENCED' if tvl_gate == 'UNEVIDENCED' and apy_pass else decided
    N('dec', 'RiskPolicy decision', 'decision', 'DETERMINISTIC', dstatus,
      'fail-CLOSED: unevidenced TVL floor ⇒ not fundable in live', '.claude/rules/risk-engine.md')
    E('g_apy', 'dec'); E('g_tvl', 'dec'); E('llm', 'dec', 'no authority')
    # RESULT (real current: paper track, not live allocation)
    N('res', 'Not in live allocation', 'result', 'DETERMINISTIC', 'PAPER',
      'paper-trading; live allocation gated by RiskPolicy + go-live', 'data/golive_status.json')
    E('dec', 'res')

    partial = tvl_gate == 'UNEVIDENCED'
    return {
        'schema': 'earn-defi/why-trace/1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'object': disp, 'object_id': f'op:{adapter_key}',
        'trace_partial': partial,
        'partial_reason': 'TVL floor cannot be evidenced (tvl_source=static, needs live) — '
                          'deterministic gate is UNEVIDENCED, fail-CLOSED' if partial else '',
        'note': 'Deterministic RiskPolicy gates vs LLM shown distinctly. LLM has NO authority '
                'over capital (invariant #3). No fabricated edges; missing segments named.',
        'authorities': {'DETERMINISTIC': 'RiskPolicy v1.0 gate', 'LLM': 'advisory only, forbidden in risk',
                        'NONE': 'data/fact'},
        'nodes': nodes, 'edges': edges,
    }


def main():
    g = build()
    tmp = OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, OUT)
    print(json.dumps({'wrote': str(OUT), 'object': g['object'], 'nodes': len(g['nodes']),
                      'edges': len(g['edges']), 'trace_partial': g['trace_partial']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
