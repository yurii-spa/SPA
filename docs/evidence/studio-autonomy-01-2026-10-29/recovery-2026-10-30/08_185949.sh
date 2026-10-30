cd /private/tmp/spa_wt_autonomy_s1; python3 - <<'EOF'
from pathlib import Path
p=Path("spa_core/tests/test_goal_graph_s1_e2e3.py"); s=p.read_text()
s=s.replace('''    from spa_core.owner_queue import cockpit_loop as cl
    import time
    real = cl.atomic_save_text if hasattr(cl, "atomic_save_text") else None
    try:''','''    import time
    try:''',1)
s=s.replace('''        out.put(f"err {exc}")
    del real
''','''        out.put(f"err {exc}")
''',1)
p.write_text(s)
EOF
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_goal_graph_s1_e2e3.py -q -p no:randomly 2>&1 | tail -1