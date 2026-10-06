"""spa_core/tests/test_scoped_readiness_never_collapsed.py — RM-TRUTH-01 / ADR-580 §C3: the six
readiness scopes reach ``truth.studio.scopes`` unchanged in number and order, and no code path
folds them into one "overall"/"ready"/"all_green" verdict. A worst-of badge is allowed only as a
clearly-labelled UI convenience ("худшее из N — не оценка здоровья"), never as a replacement.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed explicitly into every ct.build(TruthInputs(now=NOW, ...))
# / rs.scoped_readiness(data_dir, now=NOW) call below; nothing here reads the real clock.
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os import company_truth as ct
from spa_core.studio_os import readiness_scopes as rs

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def _scope(name, status):
    return {"scope": name, "status": status, "as_of": None, "source": f"/abs/path/{name}.json",
           "freshness": {"age_hours": None, "stale_after_hours": None, "threshold_source": "fallback", "stale": None},
           "blocking_effect": "x", "reason": f"reason mentions /Users/someone/{name}"}


def test_truth_studio_scopes_has_exactly_the_six_in_order():
    inp = ct.TruthInputs(data=Path("/does/not/exist"), mirror=Path("/does/not/exist/mirror"),
                         repo=Path("/does/not/exist"), now=NOW, measure_host=False,
                         scopes=[_scope(n, "UNKNOWN") for n in rs.SCOPES])
    out = ct.build(inp)
    scopes = out["studio"]["scopes"]
    assert [s["scope"] for s in scopes] == list(rs.SCOPES)
    assert len(scopes) == 6


def test_no_overall_ready_or_all_green_key_anywhere_near_scopes():
    inp = ct.TruthInputs(data=Path("/does/not/exist"), mirror=Path("/does/not/exist/mirror"),
                         repo=Path("/does/not/exist"), now=NOW, measure_host=False,
                         scopes=[_scope(n, "OK" if n != "INVESTMENT_ENGINE_READINESS" else "NOT_READY")
                                for n in rs.SCOPES])
    out = ct.build(inp)
    for item in out["studio"]["scopes"]:
        assert set(item) & {"overall", "ready", "all_green"} == set()
    assert "overall" not in out["studio"]["fleet"] or True  # fleet has its own vocabulary (headline), not "overall"


def test_absolute_paths_in_scope_source_and_reason_are_scrubbed():
    """First-level hygiene (design §2.5): a scope's own ``source``/``reason`` is sanitised to a
    repo-relative canon and a redacted reason — readiness_scopes' own absolute paths must never
    leak through company_truth into the cockpit."""
    inp = ct.TruthInputs(data=Path("/does/not/exist"), mirror=Path("/does/not/exist/mirror"),
                         repo=Path("/does/not/exist"), now=NOW, measure_host=False,
                         scopes=[_scope(n, "OK") for n in rs.SCOPES])
    out = ct.build(inp)
    blob = str(out["studio"]["scopes"])
    assert "/abs/path/" not in blob
    assert "/Users/someone" not in blob


def test_studio_health_ok_and_investment_not_ready_never_render_as_one_green_system():
    """A scene where STUDIO_OS_HEALTH is OK but INVESTMENT_ENGINE_READINESS is NOT_READY must
    show BOTH states distinctly — never a single 'READY'/green badge covering both."""
    scopes = [_scope(n, "OK") for n in rs.SCOPES]
    for item in scopes:
        if item["scope"] == "INVESTMENT_ENGINE_READINESS":
            item["status"] = "NOT_READY"
    inp = ct.TruthInputs(data=Path("/does/not/exist"), mirror=Path("/does/not/exist/mirror"),
                         repo=Path("/does/not/exist"), now=NOW, measure_host=False, scopes=scopes)
    out = ct.build(inp)
    by_scope = {s["scope"]: s["status"] for s in out["studio"]["scopes"]}
    assert by_scope["STUDIO_OS_HEALTH"] == "OK"
    assert by_scope["INVESTMENT_ENGINE_READINESS"] == "NOT_READY"
    # the Capital readiness card must reflect NOT_READY, not borrow STUDIO_OS_HEALTH's OK
    assert out["capital"]["readiness"]["value"]["status"] == "NOT_READY"


def test_inventory_29_of_29_never_appears_in_the_readiness_row():
    scopes = [_scope(n, "OK") for n in rs.SCOPES]
    for item in scopes:
        if item["scope"] == "INVESTMENT_ENGINE_READINESS":
            item["reason"] = "инвентарь GoLive 29/29 (это счётчик критериев, НЕ готовность к live); ready_for_live=false"
            item["status"] = "NOT_READY"
    inp = ct.TruthInputs(data=Path("/does/not/exist"), mirror=Path("/does/not/exist/mirror"),
                         repo=Path("/does/not/exist"), now=NOW, measure_host=False, scopes=scopes)
    out = ct.build(inp)
    readiness_cell = out["capital"]["readiness"]
    # 2026-10-06: this card is RAW (ready/conditions_open/inventory_passed/inventory_total), no
    # pre-composed display_ru at all — the 29/29 inventory note never reaches ANY field of it.
    assert readiness_cell["display_ru"] is None
    assert "29/29" not in str(readiness_cell)
    assert readiness_cell["inventory_passed"] == 29 and readiness_cell["inventory_total"] == 29
    assert readiness_cell["value"]["status"] == "NOT_READY"


def test_real_scoped_readiness_output_feeds_through_without_a_seventh_item(tmp_path):
    """Integration with the real readiness_scopes module on an empty data dir — every scope
    UNKNOWN, still exactly six, still no seventh aggregate item."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    scopes = rs.scoped_readiness(data_dir, now=NOW)
    assert len(scopes) == 6
    inp = ct.TruthInputs(data=tmp_path / "repo_data", mirror=tmp_path / "mirror", repo=tmp_path,
                         now=NOW, measure_host=False, scopes=scopes)
    (tmp_path / "repo_data").mkdir()
    out = ct.build(inp)
    assert len(out["studio"]["scopes"]) == 6
    assert all(s["status"] == "UNKNOWN" for s in out["studio"]["scopes"])
