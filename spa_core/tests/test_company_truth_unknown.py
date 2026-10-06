"""spa_core/tests/test_company_truth_unknown.py — RM-TRUTH-01 / ADR-580 inv. #17: for EVERY
canon a Company Truth cell reads, its absence is its OWN value (NOT_MEASURED/STALE), never 0,
"", or healthy by default — and the cell's ``display_ru`` equals its ``unknown_ru``, taken from
the copy deck, never a guessed number. One test pair per canon in the design's own list:
equity curve · books (Balanced/Aggressive) · agent_health · site_freshness_report ·
session_changes · tracker · problems.json · dr_offsite_status · backups dir · resilience_status ·
trading_research (Trading Lab) · cio ledger · shadow ledger · research_factory · memory index ·
manifest · roles.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed explicitly into every function under test
# below; nothing here reads the real clock.
from __future__ import annotations

import json
import sqlite3
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from spa_core.studio_os import company_truth as ct

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
NEVER_GREEN_STATES = {ct.NOT_MEASURED, ct.STALE, ct.NOT_ENOUGH_HISTORY, ct.CORRUPT}


def _assert_absent(cell: dict, *, canon_substr: str | None = None):
    assert cell["state"] in NEVER_GREEN_STATES, cell
    assert cell["value"] is None or isinstance(cell["value"], dict) and not any(
        v for v in cell["value"].values() if v), cell
    assert cell["display_ru"] == cell["unknown_ru"]
    assert cell["unknown_ru"]
    if canon_substr:
        assert canon_substr in cell["canon"], cell["canon"]


# ── equity curve (home.tile.yield / capital.defi.conservative) ─────────────────────────────────
def test_equity_curve_absent_is_not_measured():
    _assert_absent(ct.tile_yield(None, NOW), canon_substr="equity_curve_daily.json")


def test_equity_curve_present_with_two_evidenced_bars_is_measured():
    doc = {"bars": [{"evidenced": True, "equity": 100000, "date": "2026-10-03"},
                    {"evidenced": True, "equity": 100500, "date": "2026-10-04"}]}
    out = ct.tile_yield(doc, NOW)
    assert out["state"] == ct.MEASURED
    assert out["value"]["apy_pct"] is not None


def test_equity_curve_with_fewer_than_two_bars_is_not_enough_history_never_a_number():
    doc = {"bars": [{"evidenced": True, "equity": 100000, "date": "2026-10-04"}]}
    out = ct.tile_yield(doc, NOW)
    assert out["state"] == ct.NOT_ENOUGH_HISTORY
    assert out["value"] is None


# ── books (Balanced=hy / Aggressive=lp) ─────────────────────────────────────────────────────────
def test_books_absent_is_not_measured(tmp_path):
    out = ct.capital_defi({"items": {}}, None, None, tmp_path, ct.tile_yield(None, NOW))
    _assert_absent(out["books"]["balanced"], canon_substr="hy_paper_trading.json")
    _assert_absent(out["books"]["aggressive"], canon_substr="lp_paper_trading.json")


def test_books_present_but_immature_is_not_enough_history(tmp_path):
    hy = {"daily_history": [{"economics_model": "v2", "equity": 100, "positions_count": 1,
                             "date": "2026-10-04"}], "experiments": []}
    out = ct.capital_defi({"items": {}}, hy, None, tmp_path, ct.tile_yield(None, NOW))
    assert out["books"]["balanced"]["state"] == ct.NOT_ENOUGH_HISTORY


def test_conservative_book_reuses_the_home_tile_yield_cell_no_second_formula():
    """2026-10-06 integration fix: the real producer used to read a non-existent ``rate_ru``
    field off ``packages_section`` (which carries work/data status words, not a rate) — the
    Capital DeFi Conservative card showed null rate/dd even while Главная's "yield" tile, built
    from the SAME equity curve, showed a real 4.9 %. Both must now agree because both read the
    SAME `tile_yield()` cell."""
    equity_doc = {"bars": [{"evidenced": True, "equity": 100000, "date": "2026-10-03"},
                          {"evidenced": True, "equity": 100500, "date": "2026-10-04"}]}
    yc = ct.tile_yield(equity_doc, NOW)
    out = ct.capital_defi({"items": {"conservative": {"work": "RUNNING", "data": "HEALTHY"}}},
                          None, None, Path("/does/not/exist"), yc)
    cons = out["books"]["conservative"]
    assert cons["state"] == yc["state"] == ct.MEASURED
    assert cons["rate_ru"] is not None and "%" in cons["rate_ru"]
    assert cons["evidenced_days"] == yc["value"]["evidenced_days"]


# ── agent_health.json (home.tile.system / studio.fleet) ────────────────────────────────────────
def test_agent_health_absent_is_not_measured():
    f = ct.typed_fleet({"agents": []}, {}, None, {"roles": []}, announced=0, unannounced=0)
    _assert_absent(f["headline"], canon_substr="agent_health.json")


def test_agent_health_present_is_measured():
    manifest = {"agents": [{"label": "com.spa.a", "intent": "active", "schedule": "daemon"}]}
    f = ct.typed_fleet(manifest, {"com.spa.a": {}}, {"agents": [{"label": "com.spa.a", "status": "OK"}]},
                       {"roles": []}, announced=0, unannounced=0)
    assert f["headline"]["state"] == ct.MEASURED


# ── site_freshness_report.json (home.tile.product / capital/product website_health) ────────────
def test_site_freshness_absent_scope_is_not_measured():
    _assert_absent(ct.tile_product(None), canon_substr="site_freshness_report.json")
    _assert_absent(ct.tile_product({"status": "UNKNOWN"}), canon_substr="site_freshness_report.json")


def test_site_freshness_present_scope_is_measured():
    out = ct.tile_product({"status": "OK", "reason": "всё свежо", "as_of": NOW.isoformat()})
    assert out["state"] == ct.MEASURED


# ── session_changes.jsonl (studio.claude_work) ──────────────────────────────────────────────────
def test_session_changes_absent_is_not_measured():
    out = ct.claude_work(None, {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=0)
    _assert_absent(out, canon_substr="session_changes.jsonl")


def test_session_changes_present_with_no_active_work_is_measured_zero():
    out = ct.claude_work([], {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=0,
                         measure_host=True)
    assert out["state"] == ct.MEASURED_ZERO
    assert out["value"] == {"active": 0, "undeclared": 0}


# ── tracker (decisions triage / Решения) ────────────────────────────────────────────────────────
def test_tracker_absent_is_not_measured():
    out = ct.decisions_triage(None, None, NOW)
    assert out["state"] == ct.NOT_MEASURED
    tile = ct.tile_needs(out)
    _assert_absent(tile, canon_substr="tracker")


def test_tracker_present_is_measured():
    cards = {"own-a.md": {"fm": {"title": "A", "status": "needs-owner", "type": "owner-decision",
                                "subject": "money"}, "body": "", "trail": [], "path": None}}
    out = ct.decisions_triage(cards, None, NOW)
    tile = ct.tile_needs(out)
    assert tile["state"] in (ct.MEASURED, ct.MEASURED_ZERO)


# ── data/problems.json (studio.problems / product.truth_incidents) ────────────────────────────
def test_problems_file_absent_is_not_measured_says_not_run_yet(tmp_path):
    out = ct.studio_problems(tmp_path, NOW)
    _assert_absent(out, canon_substr="problems.json")
    assert "не запущен" in out["unknown_ru"]


def test_problems_file_present_is_measured(tmp_path):
    (tmp_path / "problems.json").write_text(json.dumps({"problems": {}, "generated_at": NOW.isoformat()}),
                                            encoding="utf-8")
    out = ct.studio_problems(tmp_path, NOW)
    assert out["state"] == ct.MEASURED_ZERO


# ── backups: dr_offsite_status.json / backups dir / resilience_status.json ─────────────────────
def test_dr_offsite_status_absent_is_not_measured(tmp_path):
    tmp_path.joinpath("backups").mkdir()
    out = ct.studio_backups(tmp_path, NOW)
    _assert_absent(out["off_host_backup"], canon_substr="dr_offsite_status.json")


def test_backups_dir_absent_is_not_measured(tmp_path):
    out = ct.studio_backups(tmp_path, NOW)
    _assert_absent(out["local_backup"], canon_substr="spa_state")


def test_resilience_status_absent_is_not_measured(tmp_path):
    out = ct.studio_backups(tmp_path, NOW)
    _assert_absent(out["recovery_tested"], canon_substr="resilience_status.json")


# ── Trading Lab (guarded import of another WP's branch; here, genuinely absent) ─────────────────
def test_trading_lab_module_absent_is_not_measured(tmp_path):
    out = ct.capital_trading_lab(tmp_path, NOW)
    assert out["state"] == ct.NOT_MEASURED
    assert out["value"] is None
    assert out["unknown_ru"]


def test_trading_lab_module_present_is_measured(tmp_path):
    fake_pkg = types.ModuleType("spa_core.trading_research")
    fake_mod = types.ModuleType("spa_core.trading_research.read_model")
    now_ms = int(NOW.timestamp() * 1000)
    fake_mod.STALE_AFTER_H = 2.0
    fake_mod.trading_lab_view = lambda d: {
        "engine_health": {"value": "HEALTHY", "as_of": now_ms},
        "strategies_researched": {"value": 138, "state": "MEASURED", "as_of": now_ms},
        "forward_paper_active": {"value": 5, "state": "MEASURED", "as_of": now_ms},
        "champions": {"value": 0, "state": "MEASURED", "as_of": now_ms},
        "evidence_integrity": {"value": "VERIFIED", "as_of": now_ms},
    }
    with mock.patch.dict(sys.modules, {"spa_core.trading_research": fake_pkg,
                                       "spa_core.trading_research.read_model": fake_mod}):
        out = ct.capital_trading_lab(tmp_path, NOW)
    assert out["state"] == ct.MEASURED
    assert out["candidates"] == 138
    assert out["forward"] == 5
    assert out["chain_ok"] is True


# ── cio ledger / shadow ledger / research_factory (via capital.* re-projection) ─────────────────
def test_cio_ledger_absent_is_not_measured():
    _assert_absent(ct.capital_oracle(None), canon_substr="investment_cio")


def test_cio_ledger_present_is_measured():
    cio = {"_meta": {"state": "HEALTHY", "observed_at": NOW.isoformat(), "age_min": 1, "stale_after_min": 1800},
          "stance": "HOLD", "confidence": "MEDIUM", "date": "2026-10-05"}
    out = ct.capital_oracle(cio)
    assert out["state"] == ct.MEASURED


def test_shadow_ledger_absent_is_not_measured():
    _assert_absent(ct.capital_readiness(None, {"status": "UNKNOWN"}), canon_substr="capital_shadow")


def test_shadow_ledger_present_is_measured():
    scope = {"status": "NOT_READY", "reason": "x", "as_of": NOW.isoformat()}
    out = ct.capital_readiness({"owner_decisions_pending": 4}, scope)
    assert out["state"] == ct.MEASURED
    assert out["value"]["go_live_conditions_open"] == 4


def test_research_factory_absent_is_not_measured_for_basis_treasury_and_sherlock():
    _assert_absent(ct.capital_basis(None), canon_substr="research_factory")
    _assert_absent(ct.capital_treasury(None, None), canon_substr="research_factory")
    _assert_absent(ct.capital_sherlock(None), canon_substr="research_factory")


def test_research_factory_present_is_measured():
    ru = {"_meta": {"state": "HEALTHY", "observed_at": NOW.isoformat(), "age_min": 1, "stale_after_min": 1560},
         "by_mechanism": {"FUNDING_CAPTURE": [{"candidate_id": "c1"}]},
         "top_candidates": [{"candidate_id": "c1", "domain": "TREASURY"}],
         "sherlock": {"reviewed_today": 5, "evidence_ready": 3}}
    assert ct.capital_basis(ru)["state"] == ct.MEASURED
    assert ct.capital_treasury(ru, {"cash_usd": 100000})["state"] == ct.MEASURED
    assert ct.capital_sherlock(ru)["state"] == ct.MEASURED
    # The factory's `reviewed_today` is a FLAG (research_factory/read.py: `any(...)`), never a
    # count — the earlier fixture value 5 encoded the very defect the real-tree seam test found
    # (a bool printed as «всего»). The count of facts is not in this source ⇒ None (inv #17).
    assert ct.capital_sherlock(ru)["usable"] == 3 and ct.capital_sherlock(ru)["total"] is None
    ru_flag = {**ru, "sherlock": {"reviewed_today": True, "evidence_ready": 3}}
    assert ct.capital_sherlock(ru_flag)["total"] is None and ct.capital_sherlock(ru_flag)["usable"] == 3


# ── memory index (data/memory/index.db + architecture/memory_truth.json) ───────────────────────
def test_memory_index_absent_is_not_measured(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data" / "memory").mkdir(parents=True)
    (repo / "architecture").mkdir(parents=True)
    mirror = tmp_path / "mirror"
    (mirror / "docs" / "decisions").mkdir(parents=True)
    out = ct.studio_memory(repo, mirror)
    _assert_absent(out, canon_substr="memory/index.db")


def test_memory_index_present_is_measured(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data" / "memory").mkdir(parents=True)
    (repo / "architecture").mkdir(parents=True)
    db = repo / "data" / "memory" / "index.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE chunks (path TEXT, body TEXT)")
    con.execute("INSERT INTO chunks VALUES (?, ?)", ("docs/decisions/ADR-500-x.md", "text"))
    con.commit()
    con.close()
    mirror = tmp_path / "mirror"
    (mirror / "docs" / "decisions").mkdir(parents=True)
    (mirror / "docs" / "decisions" / "ADR-500-x.md").write_text("x", encoding="utf-8")
    out = ct.studio_memory(repo, mirror)
    assert out["state"] in (ct.MEASURED, ct.MEASURED_ZERO)
    assert out["value"]["newest_indexed"] == 500


# ── manifest.json / roles.json (studio.fleet) ───────────────────────────────────────────────────
def test_manifest_absent_is_not_measured():
    f = ct.typed_fleet(None, {}, {"agents": []}, {"roles": []}, announced=0, unannounced=0)
    _assert_absent(f["headline"], canon_substr="manifest.json")


def test_roles_absent_gives_none_count_not_zero():
    f = ct.typed_fleet({"agents": []}, {}, {"agents": []}, None, announced=0, unannounced=0)
    assert f["configured_roles"]["n"] is None  # absence is None, never a counted zero


def test_roles_present_measures_implemented_only():
    f = ct.typed_fleet({"agents": []}, {}, {"agents": []}, {"roles": [{"implemented": True}, {"implemented": False}]},
                       announced=0, unannounced=0)
    assert f["configured_roles"]["n"] == 1


def test_trading_lab_present_but_ledger_missing_is_not_measured_with_the_views_reason(tmp_path):
    """Модуль на месте, леджера нет: карточка НЕ MEASURED, причина берётся из ячейки ядра
    (слияние Wave 2 RM-TRUTH-01: раньше любой словарь объявлялся измеренным)."""
    out = ct.capital_trading_lab(tmp_path, NOW)
    assert out["state"] == ct.NOT_MEASURED
    assert "evidence.db" in (out["unknown_ru"] or "")
