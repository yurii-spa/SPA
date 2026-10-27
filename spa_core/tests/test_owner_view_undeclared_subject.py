# LLM_FORBIDDEN
"""ARB 27.10: «тема не объявлена» — НЕИЗВЕСТНО, а не «вопрос не к владельцу» (UNKNOWN ≠ NONE).

Пульт говорил о группе undeclared «не относятся к деньгам… ваш ответ не нужен», а среди 15 таких карточек были
риск, публикация и лицензия. Здесь закреплено: пояснение не обещает, что решение не нужно; итог называет их число.
"""
from __future__ import annotations

import re
from pathlib import Path

from spa_core.studio_os import owner_view as ov

_UI = Path(__file__).resolve().parents[2] / "spa_core" / "studio_os" / "mission_ui" / "i18n.js"


def _model(n_owner=1, n_undeclared=2):
    owner = [{"id": f"own-{i}", "title_ru": f"вопрос {i}", "subject_key": "MONEY"} for i in range(n_owner)]
    und = [{"id": f"und-{i}", "title_ru": f"без темы {i}"} for i in range(n_undeclared)]
    return {"truth": {"decisions": {"groups": {"owner": owner, "undeclared": und, "answered": [],
                                               "accepted": [], "prod_only": []}}}}


def test_the_undeclared_group_never_promises_that_no_answer_is_needed():
    title, explain = ov.GROUP_EXPLAIN["undeclared"]
    text = (title + " " + explain).lower()
    assert "не нужен" not in text.replace("не значит, что ваш ответ не нужен", "")
    assert "не определ" in text and "разобрать" in text


def test_the_summary_counts_undeclared_questions_as_open():
    sec = ov.decisions(_model(1, 2), None)
    assert "Ждут вашего ответа: 1" in sec["summary"]["text"] and "ещё 2 без объявленной темы" in sec["summary"]["text"]
    group = next(g for g in sec["groups"] if g["key"] == "undeclared")
    assert group["count"] == 2 and "Тема не определена" in group["title"]
    assert "ещё" not in ov.decisions(_model(1, 0), None)["summary"]["text"]


def test_the_ui_header_over_the_groups_does_not_claim_no_answer_is_needed():
    js = _UI.read_text(encoding="utf-8")
    for line in re.findall(r'"ux\.dec\.other_groups":\s*"([^"]*)"', js):
        assert "не нужен" not in line and "no answer needed" not in line.lower()
