cd /private/tmp/spa_wt_autonomy_s1; python3 - <<'EOF'
from pathlib import Path
p=Path("spa_core/telegram/owner_decisions.py"); s=p.read_text()
def rep(old,new):
    global s
    assert s.count(old)==1,(old[:70]); s=s.replace(old,new,1)
rep('''    if sent_version and kind == KIND_OPTION and _question_version_of(card_path) != sent_version:''','''    if sent_version and _question_version_of(card_path) != sent_version:''')
rep('''            if options is not None:
                rec["options"] = [{"num": o.num, "label": o.label,
                                   "recommended": o.recommended} for o in options]
                # Досылка показывает владельцу ТЕКУЩИЙ вопрос — его версия и есть отправленная.
                if rec.get("card"):
                    rec["question_sha256"] = _question_version_of(rec["card"])''','''            if options is not None:
                rec["options"] = [{"num": o.num, "label": o.label,
                                   "recommended": o.recommended} for o in options]
            if (options is not None or ack is not None) and rec.get("card"):
                # Досылка показывает владельцу ТЕКУЩИЙ вопрос — его версия и есть отправленная.
                rec["question_sha256"] = _question_version_of(rec["card"])''')
p.write_text(s)
EOF
grep -n "def record_answer_from_callback\|def handle_choice\|def apply_choice" spa_core/telegram/owner_decisions.py | head -3; sed -n 2585,2600p spa_core/telegram/owner_decisions.py | head -16