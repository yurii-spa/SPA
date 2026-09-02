"""CIO oversight phase C — the WHERE/HOW MUCH/WHY/WHY NOW brief.

Computes nothing new: every field comes straight from phase E/F's already-recorded
ledger. The tests that matter most are the honest-degradation ones — no fabricated
gate verdict on a pre-phase-F record, no invented "unchanged" on a single-record
history, an explicit "not wired" state for Balanced/Aggressive rather than a
coincidentally-empty one.
"""
from __future__ import annotations

from spa_core.paper_trading.allocation_rationale import write_shadow_rationale
from spa_core.paper_trading.cio_brief import (
    brief_from_history,
    build_books_brief,
    no_record_brief,
)


def _rec(cycle_date, **kw):
    r = {
        "schema": "shadow-hist-v2", "decision_id": f"adr060-shadow-{cycle_date}",
        "cycle_date": cycle_date, "policy_version": "v1.0", "mode": "paper",
        "verdict": "HOLD", "reasons": [], "legs": [], "gates": {},
        "current_positions": {}, "turnover_usd": 0.0, "turnover_frac": 0.0,
        "cost_usd": 0.0,
    }
    r.update(kw)
    return r


# ─── fail-closed shapes ────────────────────────────────────────────────────


def test_empty_history_is_fail_closed_not_a_blank_brief():
    brief = brief_from_history([])
    assert brief == {"available": False, "reason": "no_decision_record_for_book"}


def test_no_record_brief_is_explicit_not_wired_not_coincidentally_empty():
    """A fixed function, not brief_from_history([]) — the reader must be able to
    tell 'this book has no producer' from 'this book's history is just empty'."""
    brief = no_record_brief("Balanced")
    assert brief["available"] is False
    assert brief["reason"] == "no_decision_record_for_book"
    assert brief["label"] == "Balanced"


def test_build_books_brief_gives_balanced_and_aggressive_the_no_record_state(tmp_path):
    result = build_books_brief(tmp_path)  # no history file at all
    assert result["conservative"]["available"] is False
    assert result["balanced"] == no_record_brief("Balanced")
    assert result["aggressive"] == no_record_brief("Aggressive")


# ─── WHERE / HOW MUCH ───────────────────────────────────────────────────────


def test_where_and_how_much_derive_from_the_latest_records_legs():
    rec = _rec("2026-08-30", verdict="ACT",
               current_positions={"maple": 40000.0, "pendle": 20000.0},
               legs=[{"protocol": "maple", "delta_usd": 5000.0, "direction": "increase"}],
               turnover_usd=5000.0, turnover_frac=0.05, cost_usd=12.5)
    brief = brief_from_history([rec])
    assert "maple" in brief["where"]
    assert "+maple" in brief["where"]
    assert "$5,000" in brief["how_much"]
    assert "$12.50" in brief["how_much"]


def test_how_much_says_no_move_sized_when_legs_are_empty():
    rec = _rec("2026-08-30", verdict="HOLD", legs=[])
    brief = brief_from_history([rec])
    assert "не размерялся" in brief["how_much"]


# ─── WHY: gate honesty ──────────────────────────────────────────────────────


def test_why_reads_gates_when_present_v2_record():
    rec = _rec("2026-08-30", verdict="HOLD", reasons=["gain_below_band:0.1pp<0.5pp"],
               gates={"gain_above_band": False, "payback_within_horizon": True})
    brief = brief_from_history([rec])
    assert brief["gates_evidenced"] is True
    assert "выгода выше порога" in brief["why"]  # the FAILED gate is named
    assert "не пройдено" in brief["why"]


def test_why_degrades_to_reasons_only_on_a_pre_phase_f_v1_record():
    """A shadow-hist-v1 line has no gates at all — must NOT fabricate a verdict."""
    rec = {"cycle_date": "2026-08-01", "verdict": "HOLD", "reasons": ["cooldown_active"],
           "current_positions": {}}
    brief = brief_from_history([rec])
    assert brief["gates_evidenced"] is False
    assert "cooldown_active" in brief["why"]


def test_why_all_gates_passed_reads_as_passed_not_empty():
    rec = _rec("2026-08-30", verdict="ACT",
               gates={"gain_above_band": True, "payback_within_horizon": True})
    brief = brief_from_history([rec])
    assert "все критерии пройдены" in brief["why"]


# ─── WHY NOW ────────────────────────────────────────────────────────────────


def test_why_now_single_record_is_first_cycle_not_fabricated_unchanged():
    brief = brief_from_history([_rec("2026-08-30")])
    assert "первый записанный цикл" in brief["why_now"]


def test_why_now_names_a_verdict_flip():
    records = [_rec("2026-08-29", verdict="HOLD"), _rec("2026-08-30", verdict="ACT")]
    brief = brief_from_history(records)
    assert "HOLD" in brief["why_now"] and "ACT" in brief["why_now"]


def test_why_now_names_a_specific_gate_flip():
    records = [
        _rec("2026-08-29", verdict="HOLD",
             gates={"gain_above_band": False, "cooldown_ok": True}),
        _rec("2026-08-30", verdict="HOLD",
             gates={"gain_above_band": True, "cooldown_ok": True}),
    ]
    brief = brief_from_history(records)
    assert "выгода выше порога" in brief["why_now"]


def test_why_now_streak_counts_identical_consecutive_verdicts():
    records = [_rec(f"2026-08-{d:02d}", verdict="HOLD", reasons=["quiet"])
               for d in range(25, 30)]  # 5 identical days
    brief = brief_from_history(records)
    assert "5-й день" in brief["why_now"]


def test_why_now_mixed_schema_pair_skips_gate_diff_falls_back_to_verdict():
    """One v1 record (no gates) followed by a v2 record — must not crash comparing
    gates, and must not silently read the missing gates as 'no change'."""
    records = [
        {"cycle_date": "2026-08-29", "verdict": "HOLD", "reasons": ["x"]},  # v1, no gates
        _rec("2026-08-30", verdict="HOLD", reasons=["x"], gates={"cooldown_ok": True}),
    ]
    brief = brief_from_history(records)  # must not raise
    assert brief["available"] is True


# ─── mutation-style regression pins (see journal for the applied-then-reverted pass) ──


def test_why_now_uses_not_equal_for_verdict_change_detection():
    """Pins the exact comparison direction — a flipped operator would silently
    stop reporting verdict changes as changes."""
    records = [_rec("2026-08-29", verdict="HOLD"), _rec("2026-08-30", verdict="HOLD")]
    brief = brief_from_history(records)
    assert "изменился" not in brief["why_now"]


# ─── book scoping: Balanced/Aggressive brief from THEIR OWN ledger ─────────
#
# hy_cycle.py/lp_cycle.py now call write_shadow_rationale (book_id="balanced"/
# "aggressive") into their OWN files. build_books_brief must read each book's
# OWN latest record — not Conservative's, and not another book's.


def _seed_book(tmp_path, book_id, cycle_date, **kw):
    kw.setdefault("current_positions", {})
    kw.setdefault("target_positions", {})
    kw.setdefault("apy_pct", {})
    kw.setdefault("apy_sources", {})
    kw.setdefault("capital_usd", 100_000.0)
    write_shadow_rationale(
        data_dir=tmp_path, cycle_date=cycle_date,
        run_ts=f"{cycle_date}T12:00:00+00:00", book_id=book_id, **kw)


def test_each_book_is_briefed_from_its_own_latest_record_not_conservatives(tmp_path):
    _seed_book(tmp_path, None, "2026-08-30",
               current_positions={"maple": 40_000.0})
    _seed_book(tmp_path, "balanced", "2026-08-30",
               current_positions={"pendle": 55_000.0})
    _seed_book(tmp_path, "aggressive", "2026-08-30",
               current_positions={"aerodrome": 60_000.0})

    result = build_books_brief(tmp_path)
    assert "maple" in result["conservative"]["where"]
    assert "pendle" in result["balanced"]["where"]
    assert "aerodrome" in result["aggressive"]["where"]
    # никакая из трёх не подмешала чужие имена
    assert "pendle" not in result["conservative"]["where"]
    assert "aerodrome" not in result["balanced"]["where"]
    assert "maple" not in result["aggressive"]["where"]


def test_a_book_with_a_genuinely_empty_ledger_still_gets_no_record_brief(tmp_path):
    """Only Conservative has a ledger — Balanced/Aggressive have none at all
    (their cycle never ran during this stretch). Same shape as before wiring."""
    _seed_book(tmp_path, None, "2026-08-30", current_positions={"maple": 40_000.0})
    result = build_books_brief(tmp_path)
    assert result["conservative"]["available"] is True
    assert result["balanced"] == no_record_brief("Balanced")
    assert result["aggressive"] == no_record_brief("Aggressive")


def test_a_book_with_an_unparseable_ledger_also_falls_back_to_no_record(tmp_path):
    """File EXISTS but has zero parseable lines — load_history reports that as
    an empty history (bad=1, records=[]), and the brief must degrade the same
    way as a missing file, not raise or fabricate availability."""
    (tmp_path / "allocation_rationale_history_balanced.jsonl").write_text(
        "not json at all\n", encoding="utf-8")
    result = build_books_brief(tmp_path)
    assert result["balanced"] == no_record_brief("Balanced")


def test_second_cycle_updates_only_the_book_that_ran(tmp_path):
    """A second cycle for Balanced must not touch Conservative's or
    Aggressive's brief — three independent books, three independent files."""
    _seed_book(tmp_path, None, "2026-08-30", current_positions={"maple": 1.0})
    _seed_book(tmp_path, "balanced", "2026-08-30", current_positions={"pendle": 1.0})
    _seed_book(tmp_path, "aggressive", "2026-08-30", current_positions={"aerodrome": 1.0})
    before = build_books_brief(tmp_path)

    _seed_book(tmp_path, "balanced", "2026-08-31", current_positions={"susde": 2.0})
    after = build_books_brief(tmp_path)

    assert after["conservative"] == before["conservative"]
    assert after["aggressive"] == before["aggressive"]
    assert after["balanced"] != before["balanced"]
    assert "susde" in after["balanced"]["where"]
