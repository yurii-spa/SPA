"""DIRECTOR-OS-UX-04 — the owner's mockup as the spec, filled ONLY from the canon.

Fixed fixture + fixed clock (no prod reads). Every mockup block either carries live data or is
listed «в разработке» with a reason; the new tiles/rows reuse the SAME numbers the sections show.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os import owner_view as ov

FIX = json.loads((Path(__file__).parent / "fixtures" / "owner_view" / "mission_fixture.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 9, 7, 15, tzinfo=timezone.utc)


def _view(model=None):
    return ov.build(copy.deepcopy(model if model is not None else FIX), NOW)


def test_in_development_registry_is_complete_and_honest():
    keys = set()
    for r in ov.IN_DEVELOPMENT:
        for f in ("key", "title", "where", "reason_kind", "reason", "needs", "priority", "nav"):
            assert r.get(f) not in (None, ""), (r.get("key"), f)
        assert r["reason_kind"] in (ov.REASON_NO_DATA, ov.REASON_NOT_DECIDED, ov.REASON_NOT_BUILT)
        assert r["priority"] in ("высокий", "средний", "низкий")
        if r["nav"]:
            assert r.get("nav_title") and r.get("nav_group")
        assert r["key"] not in keys
        keys.add(r["key"])
    v = _view()
    for d in v["sections"]["overview"]["in_development"] + v["sections"]["protection"]["in_development"]:
        assert d["key"] in keys and d["badge"] == "в разработке" and d["line"]
    assert {d["key"] for d in v["in_development"]} == keys


def test_health_tile_reuses_the_protection_checks():
    v = _view()
    tile = v["sections"]["overview"]["kpis"]["health"]
    prot = v["sections"]["protection"]
    good = next(g["count"] for g in prot["check_groups"] if g["key"] == "verified")
    total = len(prot["checks"])
    assert tile["big"] == f"{good}/{total}"
    assert tile["bar"]["value"] == good and tile["bar"]["max"] == total
    assert tile["state_pill"]["text"] in ("под угрозой", "есть замечания", "в порядке")
    if good < total:
        assert tile["state_pill"]["text"] != "в порядке"


def test_attention_lists_owner_questions_first_then_serious_problems():
    v = _view()
    at = v["sections"]["overview"]["attention"]
    q = v["sections"]["overview"]["questions"]["items"]
    rows = at["rows"]
    assert [r["title"] for r in rows[:len(q)]] == [x["title"] for x in q][:len(rows)]
    for r, x in zip(rows, q):
        assert r["badge"] == str(x["age_days"])
        assert r["link_area"] == "decisions"
    for r in rows[len(q):]:
        assert r["link_area"] == "protection" and r["pill"]["text"] in ("критично", "важно")
    for r in rows:
        assert r["sub"] is None or len(r["sub"]) <= 140


def test_happening_rows_come_from_the_canon_only():
    v = _view()
    rows = v["sections"]["overview"]["happening"]["rows"]
    titles = [r["title"] for r in rows]
    assert any(t.startswith("Пакет «") for t in titles)
    assert "Трейдинг: исследование стратегий" in titles
    m = copy.deepcopy(FIX)
    m["truth"]["studio"].pop("claude_work", None)
    rows2 = _view(m)["sections"]["overview"]["happening"]["rows"]
    assert not any(r["abbr"] == "АС" for r in rows2), "no assistant row without the canon"


def test_nav_counts_match_the_sections():
    v = _view()
    n = v["nav_counts"]
    assert n["decisions"] == v["sections"]["overview"]["questions"]["count"]
    cnt = v["sections"]["protection"]["problems"]["counts"]
    assert n["protection"] == cnt.get("critical", 0) + cnt.get("important", 0)


def test_unknown_is_never_zero_in_the_new_blocks():
    m = copy.deepcopy(FIX)
    m["truth"]["studio"].pop("problems", None)
    m["truth"].pop("decisions", None)
    v = _view(m)
    assert v["nav_counts"]["decisions"] is None
    assert v["nav_counts"]["protection"] is None
    at = v["sections"]["overview"]["attention"]
    assert at["rows"] == [] and at["questions_count"] is None


def test_new_blocks_have_no_jargon_on_main_text():
    v = _view()
    o = v["sections"]["overview"]
    hits = [(p, t) for p, t in ov.main_texts({"h": o["happening"], "a": o["attention"], "d": o["in_development"],
                                               "k": o["kpis"]["health"]}) if ov.jargon_hits(t)]
    assert hits == []
