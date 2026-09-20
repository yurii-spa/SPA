#!/usr/bin/env python3
"""System Map: a derived graph over the Cartographer snapshot (Phase 0B).

Pure function of the snapshot — no probes of its own, so the map can be rebuilt from a
stored snapshot and compared across runs. Every edge carries WHY it exists:

  declaration       — a source declares it (manifest, plist, repo file content);
  observation       — we observed it on this machine (filesystem, launchd, ps);
  static_inference  — derived by safe reading, NOT by execution.

A ``static_inference`` edge is never presented as proof that something executed.
"""
from pathlib import Path

MAP_SCHEMA = 'cartographer.system_map/0.1'

NODE_TYPES = ('launchd_job', 'plist_installed', 'plist_declared', 'entrypoint',
              'checkout', 'artifact', 'document')
EDGE_TYPES = ('declared_in_repo', 'installed_from', 'declares_entrypoint', 'resides_in',
              'declares_target', 'produces', 'consumes', 'governed_by')
BASES = ('declaration', 'observation', 'static_inference')


def _nid(kind, value):
    """Stable node id: type prefix plus the identifying string, normalised."""
    return f'{kind}:{str(value).strip()}'


def build(s):
    nodes, edges = {}, []
    unresolved = []

    def node(kind, value, **attrs):
        nid = _nid(kind, value)
        if nid not in nodes:
            nodes[nid] = {'id': nid, 'type': kind, 'key': str(value), **attrs}
        else:
            nodes[nid].update({k: v for k, v in attrs.items() if v is not None})
        return nid

    def edge(src, dst, kind, basis, evidence):
        assert basis in BASES, basis
        assert kind in EDGE_TYPES, kind
        edges.append({'id': f'{kind}|{src}|{dst}', 'src': src, 'dst': dst,
                      'type': kind, 'basis': basis, 'evidence': evidence})


    for e in s['entities']:
        job = node('launchd_job', e['id'],
                   status=e['status'], stages=e['stages'], intent=e.get('intent'),
                   layer=e.get('layer'), role=e.get('role'), schedule=e.get('schedule'),
                   pid=e.get('pid'), last_exit=e.get('last_exit'),
                   last_exit_basis=e.get('last_exit_basis'),
                   domains=e.get('domains'))

        # job → plist declared in the repository (the SOURCE of an install, not an install)
        if e.get('declared_plist_in_repo'):
            p = node('plist_declared', e['declared_plist_in_repo'])
            edge(job, p, 'declared_in_repo', 'observation',
                 'plist file present in <repo>/launchd/')

        # job → installed plist → entrypoint → checkout
        for inst in e.get('installed_paths') or []:
            pl = node('plist_installed', inst['plist'], domain_dir=inst.get('plist_domain_dir'),
                      keep_alive=inst.get('keep_alive'),
                      start_interval=inst.get('start_interval'),
                      has_calendar_schedule=inst.get('has_calendar_schedule'),
                      environment_keys=inst.get('environment_keys'))
            edge(job, pl, 'installed_from', 'observation',
                 f"plist read from {inst.get('plist_domain_dir')}")
            ep = inst.get('entrypoint') or {}
            kind = ep.get('target_kind')
            if kind:
                key = ep['target'] if kind in ('script', 'executable') else f"module:{ep['target']}"
                epn = node('entrypoint', key, target_kind=kind,
                           executable=ep.get('executable'),
                           target_exists=ep.get('target_exists'),
                           argument_count=ep.get('argument_count'), arguments_omitted=True)
                edge(pl, epn, 'declares_entrypoint', 'observation',
                     f'installed plist launch form parsed as {kind}; argument content omitted')
                if kind == 'script' and ep.get('target_exists') is False:
                    unresolved.append({'entity': e['id'], 'what': 'entrypoint_script_missing',
                                       'reason': 'declared script absent on disk; no later '
                                                 'argument substituted for it'})
                co = inst.get('entrypoint_checkout')
                if co:
                    con = node('checkout', co)
                    edge(epn, con, 'resides_in', 'observation',
                         'nearest ancestor directory containing .git')
                else:
                    unresolved.append({'entity': e['id'], 'what': 'checkout',
                                       'reason': 'no ancestor .git found for the entrypoint'})
                declared_target = inst.get('entrypoint_declared_target')
                if declared_target:
                    edge(epn, node('entrypoint', f'module:{declared_target}',
                                   target_kind='module',
                                   note='module declared by the wrapper itself'),
                         'declares_target', 'static_inference',
                         'wrapper comment `# AGENT_MODULE:` read statically; wrapper NOT executed')
                elif kind == 'script' and ep.get('target_exists'):
                    unresolved.append({'entity': e['id'], 'what': 'wrapper_target',
                                       'reason': 'dynamic target, no static declaration; '
                                                 'wrapper deliberately not executed'})
            else:
                unresolved.append({'entity': e['id'], 'what': 'entrypoint',
                                   'reason': ep.get('unknown_reason') or 'not resolved'})

        # component → produces → artifact  (declaration; freshness is an observation ON the node)
        for out in e.get('declared_outputs') or []:
            rel = out.get('relpath') or out.get('path')
            an = node('artifact', rel, exists=out.get('exists'), fresh=out.get('fresh'),
                      slo_hours=out.get('slo_hours'), age_seconds=out.get('age_seconds'),
                      is_symlink=out.get('is_symlink'), producer_attribution='UNKNOWN')
            edge(job, an, 'produces', 'declaration',
                 'architecture/manifest.json produces[]; freshness observed, producer UNKNOWN')

        # component → consumes → artifact
        for rel in e.get('declared_consumes') or []:
            an = node('artifact', rel)
            edge(job, an, 'consumes', 'declaration', 'architecture/manifest.json consumes[]')

        # component → governed_by → document (only with an explicit declared reference).
        # Three outcomes are kept apart: resolved · absent from a COMPLETE index ·
        # unverifiable because the index itself is missing.
        for ref in e.get('document_references') or []:
            dn = node('document', ref['reference'], resolved_path=ref.get('path'),
                      reference_kind=ref.get('kind'), outcome=ref['outcome'],
                      resolved=ref['outcome'] == 'resolved')
            edge(job, dn, 'governed_by', 'declaration',
                 'architecture/manifest.json governed_by[]; resolution outcome: '
                 + ref['outcome'])
            if ref['outcome'] != 'resolved':
                unresolved.append({'entity': e['id'], 'what': f"governed_by_{ref['outcome']}",
                                   'reason': f"{ref['reference']}: {ref['outcome']}"})

    # checkouts observed independently of any entrypoint (repos and their worktrees)
    for r in s.get('repositories') or []:
        cn = node('checkout', r['path'], head=r.get('head'),
                  cached_origin_main=r.get('cached_origin_main'),
                  remote_origin_main=r.get('remote_origin_main'),
                  drift_measured=r.get('drift') is not None)
        for w in r.get('worktrees') or []:
            node('checkout', w['worktree'], head=w.get('HEAD'), exists=w.get('exists'),
                 detached=w.get('detached'), drift_measured=w.get('code_drift_vs_cached_ref') is not None)

    basis_counts = {b: sum(1 for x in edges if x['basis'] == b) for b in BASES}
    type_counts = {t: sum(1 for n in nodes.values() if n['type'] == t) for t in NODE_TYPES}
    edge_type_counts = {t: sum(1 for x in edges if x['type'] == t) for t in EDGE_TYPES}
    return {
        'schema_version': MAP_SCHEMA,
        'derived_from': {'snapshot_schema': s.get('schema_version'),
                         'snapshot_finished_at': s.get('finished_at')},
        'derived_state': True,
        'node_types': list(NODE_TYPES),
        'edge_types': list(EDGE_TYPES),
        'evidence_bases': list(BASES),
        'nodes': list(nodes.values()),
        'edges': edges,
        'node_type_counts': type_counts,
        'edge_type_counts': edge_type_counts,
        'edge_basis_counts': basis_counts,
        'unresolved': unresolved,
        'limits': [
            'static_inference edges are safe reads, never proof of execution',
            'produces/consumes are DECLARATIONS from the manifest; the map does not claim '
            'the component actually wrote or read the artifact',
            'artifact freshness is observed, producer attribution is UNKNOWN',
            'a wrapper whose target is dynamic stays UNRESOLVED by design — wrappers are '
            'never executed for analysis',
        ],
    }


def validate(m):
    """Referential integrity and contract. Raises on any dangling reference."""
    ids = {n['id'] for n in m['nodes']}
    if len(ids) != len(m['nodes']):
        raise ValueError('duplicate node ids')
    for e in m['edges']:
        if e['src'] not in ids or e['dst'] not in ids:
            raise ValueError(f"dangling edge {e['id']}")
        if e['basis'] not in m['evidence_bases']:
            raise ValueError(f"unknown basis {e['basis']}")
        if e['type'] not in m['edge_types']:
            raise ValueError(f"unknown edge type {e['type']}")
        if not e.get('evidence'):
            raise ValueError(f"edge without evidence {e['id']}")
    for n in m['nodes']:
        if n['type'] not in m['node_types']:
            raise ValueError(f"unknown node type {n['type']}")
    if len({e['id'] for e in m['edges']}) != len(m['edges']):
        raise ValueError('duplicate edge ids')
    return True


def mermaid(m, s, top_artifacts=8):
    """Readable overview: groups, not hundreds of nodes.

    Individual jobs are deliberately NOT drawn — 80+ nodes is an unreadable graph, and
    the machine-readable answer already lives in system_map.json.
    """
    jobs = [n for n in m['nodes'] if n['type'] == 'launchd_job']
    by_layer = {}
    for j in jobs:
        key = j.get('layer') or 'layer:UNDECLARED'
        st = by_layer.setdefault(key, {'total': 0, 'status': {}})
        st['total'] += 1
        st['status'][j['status']] = st['status'].get(j['status'], 0) + 1

    deg = {}
    for e in m['edges']:
        if e['type'] in ('produces', 'consumes'):
            deg[e['dst']] = deg.get(e['dst'], 0) + 1
    hot = sorted(deg.items(), key=lambda kv: -kv[1])[:top_artifacts]
    art_by_id = {n['id']: n for n in m['nodes'] if n['type'] == 'artifact'}
    checkouts = [n for n in m['nodes'] if n['type'] == 'checkout']
    ep_by_checkout = {}
    for e in m['edges']:
        if e['type'] == 'resides_in':
            ep_by_checkout[e['dst']] = ep_by_checkout.get(e['dst'], 0) + 1

    def sid(prefix, i):
        return f'{prefix}{i}'

    lines = ['# System Map — overview', '',
             f"Derived from snapshot `{m['derived_from']['snapshot_finished_at']}` · "
             f"schema `{m['schema_version']}`", '',
             f"Nodes {len(m['nodes'])} ({m['node_type_counts']})", '',
             f"Edges {len(m['edges'])} ({m['edge_type_counts']})", '',
             f"Evidence bases: {m['edge_basis_counts']}", '',
             '> Groups, not individual jobs: 80+ nodes would be unreadable. Per-component',
             '> detail lives in `system_map.json`; unresolved claims in `unresolved` there.', '',
             '```mermaid', 'graph LR']
    lines.append('  subgraph Layers["Declared layers → component status"]')
    layer_ids = {}
    for i, (layer, st) in enumerate(sorted(by_layer.items())):
        nid = sid('L', i)
        layer_ids[layer] = nid
        detail = ', '.join(f'{k} {v}' for k, v in sorted(st['status'].items()))
        lines.append(f'    {nid}["{layer}<br/>{st["total"]} jobs<br/>{detail}"]')
    lines.append('  end')

    lines.append('  subgraph Checkouts["Checkouts hosting entrypoints"]')
    co_ids = {}
    for i, c in enumerate(sorted(checkouts, key=lambda n: n['key'])):
        n_ep = ep_by_checkout.get(c['id'], 0)
        if n_ep == 0 and len(checkouts) > 6:
            continue  # keep the picture readable: only checkouts that actually host entrypoints
        nid = sid('C', i)
        co_ids[c['id']] = nid
        name = Path(c['key']).name or c['key']
        head = (c.get('head') or '')[:9]
        lines.append(f'    {nid}["{name}<br/>{n_ep} entrypoints<br/>HEAD {head}"]')
    lines.append('  end')

    lines.append('  subgraph Artifacts["Most-referenced declared artifacts"]')
    art_ids = {}
    for i, (aid, count) in enumerate(hot):
        a = art_by_id.get(aid, {})
        nid = sid('A', i)
        art_ids[aid] = nid
        fresh = a.get('fresh')
        mark = {True: 'fresh', False: 'STALE', None: 'freshness UNKNOWN'}[fresh]
        lines.append(f'    {nid}["{Path(a.get("key", aid)).name}<br/>{count} refs<br/>{mark}"]')
    lines.append('  end')

    # layer → checkout (where that layer's entrypoints live) and layer → artifact
    seen = set()
    job_layer = {j['id']: (j.get('layer') or 'layer:UNDECLARED') for j in jobs}
    ep_owner = {}
    for e in m['edges']:
        if e['type'] == 'installed_from':
            ep_owner[e['dst']] = e['src']
    pl_to_ep = {e['src']: e['dst'] for e in m['edges'] if e['type'] == 'declares_entrypoint'}
    ep_to_co = {e['src']: e['dst'] for e in m['edges'] if e['type'] == 'resides_in'}
    for pl, job in ep_owner.items():
        ep = pl_to_ep.get(pl)
        co = ep_to_co.get(ep) if ep else None
        if not co or co not in co_ids:
            continue
        pair = (layer_ids.get(job_layer.get(job)), co_ids[co])
        if all(pair) and pair not in seen:
            seen.add(pair)
            lines.append(f'  {pair[0]} -->|entrypoints observed| {pair[1]}')
    for e in m['edges']:
        if e['type'] not in ('produces', 'consumes') or e['dst'] not in art_ids:
            continue
        pair = (layer_ids.get(job_layer.get(e['src'])), art_ids[e['dst']], e['type'])
        if pair[0] and pair not in seen:
            seen.add(pair)
            arrow = 'declares produces' if e['type'] == 'produces' else 'declares consumes'
            lines.append(f'  {pair[0]} -.->|{arrow}| {pair[1]}')
    lines += ['```', '',
              '## What this picture does NOT claim', '']
    lines += [f'- {x}' for x in m['limits']]
    lines += ['', f"Unresolved claims: {len(m['unresolved'])} "
                  '(see `unresolved` in system_map.json — each with a reason).', '']
    return '\n'.join(lines)
