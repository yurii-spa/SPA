"""
MP-896 ProtocolPartnershipNetworkAnalyzer
Advisory analytics — maps protocol integration partnerships, computes network centrality,
dependency risk, composability benefits, and TVL influence. Pure stdlib, read-only/advisory.
"""
import json
import os
import time

_LOG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'partnership_network_log.json')
_RING_BUFFER_SIZE = 100


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


def _centrality_label(total_degree: int) -> str:
    if total_degree >= 10:
        return 'HUB'
    elif total_degree >= 5:
        return 'CONNECTOR'
    elif total_degree >= 2:
        return 'PARTICIPANT'
    else:
        return 'ISOLATED'


def _dependency_risk(inbound: int) -> str:
    if inbound >= 8:
        return 'CRITICAL'
    elif inbound >= 5:
        return 'HIGH'
    elif inbound >= 3:
        return 'MODERATE'
    else:
        return 'LOW'


def _network_resilience(outbound: int) -> str:
    if outbound >= 3:
        return 'REDUNDANT'
    elif outbound >= 2:
        return 'SOME_REDUNDANCY'
    elif outbound == 1:
        return 'SINGLE_PATH'
    else:
        return 'NONE'


def analyze(network: dict, config: dict = None) -> dict:
    """
    Analyze protocol integration partnerships and network metrics.

    network: dict with 'protocols' list, each item having
             'name', 'tvl_usd', 'integrations' (list of protocol names).
    config: currently unused, reserved for future use.

    Returns dict with per-protocol metrics and network-level summaries.
    """
    protocols_raw = (network or {}).get('protocols', [])

    # Build name→tvl lookup
    name_to_tvl = {p['name']: float(p.get('tvl_usd', 0.0)) for p in protocols_raw}

    # Initialize inbound and TVL-influence maps
    inbound_map = {p['name']: 0 for p in protocols_raw}
    tvl_influence_map = {p['name']: 0.0 for p in protocols_raw}

    # Walk every outbound edge A→target
    for p in protocols_raw:
        src_tvl = name_to_tvl[p['name']]
        for target in p.get('integrations', []):
            if target in inbound_map:
                inbound_map[target] += 1
                tvl_influence_map[target] += src_tvl
            # If target is not in the registry, the edge is skipped for
            # inbound/TVL-influence but still counts toward src's outbound.

    analyzed = []
    for p in protocols_raw:
        name = p['name']
        outbound = len(p.get('integrations', []))
        inbound = inbound_map.get(name, 0)
        total_degree = outbound + inbound
        composability_score = min(100, total_degree * 10)
        centrality = _centrality_label(total_degree)
        dep_risk = _dependency_risk(inbound)
        tvl_influence = tvl_influence_map.get(name, 0.0)
        resilience = _network_resilience(outbound)

        analyzed.append({
            'name': name,
            'outbound_integrations': outbound,
            'inbound_integrations': inbound,
            'total_degree': total_degree,
            'composability_score': composability_score,
            'centrality_label': centrality,
            'dependency_risk': dep_risk,
            'tvl_influence_score': tvl_influence,
            'network_resilience': resilience,
        })

    most_connected = None
    highest_tvl_influence = None
    if analyzed:
        most_connected = max(analyzed, key=lambda x: x['total_degree'])['name']
        highest_tvl_influence = max(analyzed, key=lambda x: x['tvl_influence_score'])['name']

    n = len(protocols_raw)
    if n <= 1:
        density = 0.0
    else:
        total_edges = sum(len(p.get('integrations', [])) for p in protocols_raw)
        density = total_edges / (n * (n - 1))

    avg_composability = 0.0
    if analyzed:
        avg_composability = sum(p['composability_score'] for p in analyzed) / len(analyzed)

    isolated_count = sum(1 for p in analyzed if p['centrality_label'] == 'ISOLATED')

    return {
        'protocols': analyzed,
        'most_connected': most_connected,
        'highest_tvl_influence': highest_tvl_influence,
        'network_density': round(density, 6),
        'average_composability_score': round(avg_composability, 6),
        'isolated_count': isolated_count,
        'timestamp': time.time(),
    }


def run(network: dict, config: dict = None, data_dir: str = None) -> dict:
    """Analyze and persist result to ring-buffer log (atomic write)."""
    result = analyze(network, config)
    log_path = (_LOG_PATH if data_dir is None
                else os.path.join(data_dir, 'partnership_network_log.json'))
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
    sample_network = {
        'protocols': [
            {'name': 'Aave', 'tvl_usd': 5_000_000_000, 'integrations': ['Compound', 'Yearn']},
            {'name': 'Compound', 'tvl_usd': 2_000_000_000, 'integrations': ['Aave']},
            {'name': 'Yearn', 'tvl_usd': 500_000_000, 'integrations': ['Aave', 'Compound']},
            {'name': 'Isolated', 'tvl_usd': 10_000_000, 'integrations': []},
        ]
    }
    if mode == '--run':
        result = run(sample_network, data_dir=data_dir)
    else:
        result = analyze(sample_network)
    print(json.dumps(result, indent=2))
