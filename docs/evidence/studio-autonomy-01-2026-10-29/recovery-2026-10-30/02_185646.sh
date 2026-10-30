cd /private/tmp/spa_wt_autonomy_s1; python3 - <<'EOF'
from pathlib import Path
p=Path("spa_core/telegram/owner_decisions.py"); s=p.read_text()
def rep(old,new):
    global s
    assert s.count(old)==1,(old[:70]); s=s.replace(old,new,1)
rep('''            if options is not None:
                rec["options"] = [{"num": o.num, "label": o.label,
                                   "recommended": o.recommended} for o in options]''','''            if options is not None:
                rec["options"] = [{"num": o.num, "label": o.label,
                                   "recommended": o.recommended} for o in options]
                # Досылка показывает владельцу ТЕКУЩИЙ вопрос — его версия и есть отправленная.
                if rec.get("card"):
                    rec["question_sha256"] = _question_version_of(rec["card"])''')
rep('''        "question_sha256": _question_version_of(live_card),''','''        "question_sha256": _question_version_of(p),''')
p.write_text(s)
EOF
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest $(grep -rl "owner_decisions" spa_core/tests --include="test_*.py" | tr '\n' ' ') -q -p no:randomly 2>&1 | grep -E "^FAILED|passed|failed|refused" | sed 's/ - .*//' | tail -8