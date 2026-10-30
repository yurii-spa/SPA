cd /private/tmp/spa_wt_autonomy_s1; cat >> spa_core/tests/test_goal_graph_s1_e2e3.py <<'EOF'


# ── E3.4 ответ кнопкой относится к той версии вопроса, что была отправлена ─────────────────────
_Q = ("---\ntitle: Вопрос\nstatus: needs-owner\ntrackerStatus:\n  type: owner-decision\n---\n"
      "## Что случилось и почему это важно\nX.\n## Что от тебя нужно\n1. Да\n2. Нет\n")


def _push_journal(tmp_path, card, version):
    j = tmp_path / "pushes.json"
    j.write_text(json.dumps({"pushes": [{"pid": "p1", "card": str(card), "card_id": card.stem,
                                         "options": [{"num": "1", "label": "Да"}], "choice": None,
                                         "question_sha256": version}]}))
    return j


def test_button_answer_to_a_changed_question_is_not_written(tmp_path):
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, question_version(_Q))
    card.write_text(_Q.replace("X.", "X изменён после отправки."))         # вопрос поменяли
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)
    assert res == {"ok": False, "reason": "question_changed", "card": str(card)}
    assert "status: needs-owner" in card.read_text() and "owner_choice" not in card.read_text()
    assert "question_changed" in od.PRESERVE_ON_REFUSAL                   # слова владельца сохраняются


def test_button_answer_to_the_sent_version_is_written_and_identity_still_checked(tmp_path):
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, question_version(_Q))
    assert od.record_choice("p1", "1", "99", owner_chat_id="42", state_path=journal)["reason"] == "not_owner"
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)
    assert res["ok"] is True and "owner_choice" in card.read_text()
EOF
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_goal_graph_s1_e2e3.py -q -p no:randomly --tb=short 2>&1 | grep -E "^E |FAILED|passed|failed" | head