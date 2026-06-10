import json, os, tempfile

path = 'KANBAN.json'
with open(path) as f:
    k = json.load(f)

assert 'SPA-V407' not in json.dumps(k, ensure_ascii=False), 'V407 already present!'

item = {
    'id': 'SPA-V407',
    'title': 'Shadow->allocator feedback loop — StrategySelector picks best shadow strategy by Sortino, confidence-gated, caps preserved',
    'priority': 'HIGH',
    'type': 'code',
    'status': 'done',
    'sprint': 'v4.05',
    'tags': ['strategy', 'allocator', 'integration', 'feedback-loop'],
    'added': '2026-06-10',
    'completed': '2026-06-10',
    'completed_at': '2026-06-10',
    'done': True,
    'files': [
        'spa_core/strategies/strategy_selector.py',
        'spa_core/allocator/allocator.py',
        'spa_core/tests/test_strategy_selector.py',
    ],
    'data': ['data/strategy_shadow_comparison.json', 'data/target_allocation.json'],
    'description': (
        'Zamknul petlyu shadow-strategii -> realnyy allokator. Novyy StrategySelector '
        '(read-only, stdlib) chitaet data/strategy_shadow_comparison.json, vybiraet '
        'luchshuyu shadow-strategiyu po Sortino (primary) / Sharpe (tiebreak) s '
        'confidence-geytom (>=30d high, >=15d medium selectable, 7-14d low NE '
        'selectable, <7d ne kandidat) i normalizuet ee live-vesa iz '
        'data/strategies/{name}.json. StrategyAllocator poluchil '
        'strategy_loop_enabled=True: pri nalichii strategii confidence>=medium ee vesa '
        'ispolzuyutsya kak baza, POVERKH primenyayutsya tier-caps (T1<=40%, T2<=20%) i '
        'risk-grade D isklyucheniya — strategiya ne mozhet oboyti limity. V output '
        'dobavleny strategy_loop_active / selected_strategy_id / strategy_confidence. '
        'Fallback na risk_adjusted kogda strategii net / nizkaya confidence. Ne '
        'importiruet execution/feed_health/risk-agentov. 22 testa (15+ trebuemyh).'
    ),
}

done = k['columns']['done']
done.insert(0, item)
k['sprint_completed'] = 'v4.05'
k['sprint_current'] = 'v4.05'
k['last_updated'] = '2026-06-10'
k['updated_by'] = 'SPA-V407 (claude)'
k['_v407_dispatch_note'] = (
    'Shadow->allocator feedback loop: StrategySelector wired into StrategyAllocator '
    '(confidence-gated, caps+risk-D preserved). Pushed.'
)

d = os.path.dirname(os.path.abspath(path)) or '.'
fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(k, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    os.replace(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

print('KANBAN updated: sprint_completed=%s, done=%d' % (k['sprint_completed'], len(done)))
