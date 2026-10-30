cd /private/tmp/spa_wt_autonomy_s1; python3 - <<'EOF'
from pathlib import Path
p=Path("spa_core/telegram/owner_decisions.py"); s=p.read_text()
def rep(old,new):
    global s
    assert s.count(old)==1,(old[:70]); s=s.replace(old,new,1)
rep('''        "buttons": prep.keyboard is not None,
        "choice": None,
    })
    _save(doc, path_obj)
    return prep''','''        "buttons": prep.keyboard is not None,
        # STUDIO-AUTONOMY-01 E3.4 (ADR-857): версия ВОПРОСА, который владелец увидел. Нажатие
        # сверяет её с карточкой в момент записи: вопрос изменился ⇒ старый ответ не пишется.
        "question_sha256": _question_version_of(live_card),
        "choice": None,
    })
    _save(doc, path_obj)
    return prep


def _question_version_of(card) -> Optional[str]:
    """Версия вопроса карточки (тот же расчёт, что у реестра ответов); не прочли — None."""
    try:
        from spa_core.owner_queue.owner_answer import question_version
        return question_version(Path(card).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — «не измерено», а не выдуманная версия
        return None''')
rep('''    card_path = Path(rec["card"])
    if not card_path.exists():
        return {"ok": False, "reason": "card_gone", "card": str(card_path)}
''','''    card_path = Path(rec["card"])
    if not card_path.exists():
        return {"ok": False, "reason": "card_gone", "card": str(card_path)}
    # E3.4: ответ относится к той версии вопроса, что была отправлена. Записи до правки версию не
    # несут — для них сверка не проводится (названный предел), а не выдумывается.
    sent_version = rec.get("question_sha256")
    if sent_version and kind == KIND_OPTION and _question_version_of(card_path) != sent_version:
        return {"ok": False, "reason": "question_changed", "card": str(card_path)}
''')
rep('''    "write_failed": "Не смог записать решение. В карточке ничего не изменилось.",
}''','''    "write_failed": "Не смог записать решение. В карточке ничего не изменилось.",
    "question_changed": ("Вопрос в карточке изменился после того, как я его отправил — старый ответ "
                         "не записал. Пришлю актуальную версию; ответь на неё."),
}''')
rep('''    "unknown_option", "unknown_card", "card_gone", "card_withdrawn", "write_failed",
})''','''    "unknown_option", "unknown_card", "card_gone", "card_withdrawn", "write_failed",
    "question_changed",
})''')
p.write_text(s)
EOF
grep -n "^from typing\|^import\|Optional" spa_core/telegram/owner_decisions.py | head -5; SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest $(grep -rl "owner_decisions" spa_core/tests --include="test_*.py" | head -40 | tr '\n' ' ') -q -p no:randomly 2>&1 | grep -E "^FAILED|passed|failed" | sed 's/ - .*//' | tail -8