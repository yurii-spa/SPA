# FROZEN-DATE-OK: даты — синтетические фикстуры истории, обе стороны сравнения запинены; логика модуля часы не читает (generated_at — только метаданные-штамп).
"""Y3 (ADR-055/ADR-060 tooling): accumulator + shadow-vs-fact evaluator.

Two properties carry the arming decision and therefore get the hard tests:
(1) the verdict history can never lie by duplication, silent loss, or a
    corrupt-line wipe — it is the ONLY durable record of the shadow's word;
(2) the evaluator's counterfactual is hand-checkable arithmetic, and every
    data hole surfaces as UNCHECKED, never as a made-up number.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading import allocation_rationale as ar
from spa_core.paper_trading import shadow_trigger_eval as ste
from spa_core.paper_trading.allocation_rationale import (
    HISTORY_FILENAME,
    append_rationale_history,
    build_history_record,
    write_shadow_rationale,
)
from spa_core.paper_trading.shadow_trigger_eval import (
    EVAL_FILENAME,
    evaluate_window,
    format_summary,
    load_history,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BOOK = {"morpho_steakhouse": 40_000.0, "maple": 20_000.0, "pendle": 20_000.0,
        "compound_v3": 5_000.0}
APY = {"morpho_steakhouse": 3.4657, "maple": 5.1097, "pendle": 13.9419,
       "compound_v3": 3.2984}
SRC = {k: "live" for k in APY}
CAPITAL = 100_000.0


def _rec(date: str, **kw) -> dict:
    r = {"schema": "shadow-hist-v1", "cycle_date": date, "verdict": "HOLD",
         "reasons": [], "capital_usd": CAPITAL, "current_positions": {},
         "target_positions": {}, "apy_evidenced_pct": {}, "cost_usd": 0.0}
    r.update(kw)
    return r


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ═══════════════════════ accumulator ═══════════════════════


def test_append_is_idempotent_by_date(tmp_path: Path) -> None:
    """A manual re-run of the same day must never double-count a verdict."""
    p = tmp_path / HISTORY_FILENAME
    append_rationale_history(_rec("2026-08-01", verdict="HOLD"), tmp_path)
    append_rationale_history(_rec("2026-08-01", verdict="ACT"), tmp_path)
    lines = _lines(p)
    assert len(lines) == 1
    assert json.loads(lines[0])["verdict"] == "ACT"  # latest run of the day wins
    append_rationale_history(_rec("2026-08-02"), tmp_path)
    assert len(_lines(p)) == 2
    dates = [json.loads(ln)["cycle_date"] for ln in _lines(p)]
    assert dates == ["2026-08-01", "2026-08-02"]  # order preserved


def test_append_preserves_corrupt_and_foreign_lines(tmp_path: Path) -> None:
    """The accumulator may drop nothing it did not write this call."""
    p = tmp_path / HISTORY_FILENAME
    corrupt = '{"cycle_date": "2026-07-30", broken json'
    p.write_text(corrupt + "\n" + json.dumps(_rec("2026-07-31")) + "\n",
                 encoding="utf-8")
    append_rationale_history(_rec("2026-08-01"), tmp_path)
    lines = _lines(p)
    assert lines[0] == corrupt          # unreadable ≠ deletable, byte-for-byte
    assert json.loads(lines[1])["cycle_date"] == "2026-07-31"
    assert json.loads(lines[2])["cycle_date"] == "2026-08-01"


def test_append_caps_at_max_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ar, "HISTORY_MAX_LINES", 5)
    for i in range(1, 8):
        append_rationale_history(_rec(f"2026-07-{i:02d}"), tmp_path)
    lines = _lines(tmp_path / HISTORY_FILENAME)
    assert len(lines) == 5
    assert json.loads(lines[0])["cycle_date"] == "2026-07-03"  # oldest dropped


def test_writer_appends_one_history_line_per_cycle(tmp_path: Path) -> None:
    """Integration: write_shadow_rationale feeds the accumulator, idempotently."""
    kw = dict(data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
              apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
              cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW)
    write_shadow_rationale(**kw)
    write_shadow_rationale(**kw)  # same-date re-run
    lines = _lines(tmp_path / HISTORY_FILENAME)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["cycle_date"] == "2026-08-02"
    assert row["verdict"] in ("ACT", "HOLD")
    assert row["apy_evidenced_pct"] == APY          # all sources are "live"
    assert row["current_positions"] == BOOK
    assert row["capital_usd"] == CAPITAL


def test_writer_write_false_leaves_no_history(tmp_path: Path) -> None:
    write_shadow_rationale(
        data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
        apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
        cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW, write=False)
    assert not (tmp_path / HISTORY_FILENAME).exists()


def test_history_record_prices_only_evidenced_protocols() -> None:
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {"decision": "HOLD", "reasons": ["r"]}}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources={**SRC, "maple": "fallback_stale"},
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert "maple" not in rec["apy_evidenced_pct"]
    assert rec["apy_unevidenced"] == ["maple"]


# ═══════════════════════ evaluator: hand-checked arithmetic ═══════════════════
#
# Timeline d01..d10, capital $100k, APYs constant: A = 2 %, B = 8 %, C never
# priced. Moving $50k A→B earns 50 000·0.06/365 = $8.2192/day; over a 7-day
# horizon $57.5342.


def _seed_timeline(tmp_path: Path) -> None:
    apy = {"A": 2.0, "B": 8.0}
    rows = [
        # d01: ACT that PAID — benefit 57.53, cost 10 ⇒ net +47.53 ⇒ hit
        _rec("2026-07-01", verdict="ACT", cost_usd=10.0,
             current_positions={"A": 100_000.0},
             target_positions={"A": 50_000.0, "B": 50_000.0},
             apy_evidenced_pct=apy),
        # d02: ACT that did NOT pay — $10k leg: 10 000·0.06/365·7 = 11.51,
        # cost 50 ⇒ net −38.49 ⇒ miss
        _rec("2026-07-02", verdict="ACT", cost_usd=50.0,
             current_positions={"A": 100_000.0},
             target_positions={"A": 90_000.0, "B": 10_000.0},
             apy_evidenced_pct=apy),
        # d03: HOLD that MISSED the same $50k move (net +47.53) ⇒ miss
        _rec("2026-07-03", verdict="HOLD", cost_usd=10.0,
             reasons=["cooldown"],
             current_positions={"A": 100_000.0},
             target_positions={"A": 50_000.0, "B": 50_000.0},
             apy_evidenced_pct=apy),
        # d04: trivial HOLD (no proposal) ⇒ hit, excluded from hit-rate
        _rec("2026-07-04", verdict="HOLD",
             current_positions={"A": 100_000.0},
             target_positions={"A": 100_000.0},
             apy_evidenced_pct=apy),
        # d05: HOLD proposing a move into NEVER-PRICED C ⇒ UNCHECKED, not a guess
        _rec("2026-07-05", verdict="HOLD",
             current_positions={"A": 100_000.0},
             target_positions={"A": 80_000.0, "C": 20_000.0},
             apy_evidenced_pct=apy),
    ]
    # ADR-067: владелец поднял порог наблюдения до 30 дней — тихие дни растянуты
    # d06..d31 (26 шт), counterfactual-утверждения не изменены (инв. 16, журнал W32)
    for i in range(6, 31):  # d06..d30: quiet days supplying forward APYs
        rows.append(_rec(f"2026-07-{i:02d}", verdict="HOLD",
                         current_positions={"A": 100_000.0},
                         target_positions={"A": 100_000.0},
                         apy_evidenced_pct=apy))
    # d31: material ACT on the LAST day, no recorded cost ⇒ assumption cost,
    # no forward data ⇒ UNCHECKED (был d10; сдвинут в хвост при растяжке окна
    # до порога ADR-067 — смысл «последний день без форвардов» сохранён)
    rows.append(_rec("2026-07-31", verdict="ACT", cost_usd=None,
                     current_positions={"A": 100_000.0},
                     target_positions={"A": 90_000.0, "B": 10_000.0},
                     apy_evidenced_pct=apy))
    for r in rows:
        append_rationale_history(r, tmp_path)


def test_evaluator_matches_hand_computed_counterfactuals(tmp_path: Path) -> None:
    _seed_timeline(tmp_path)
    doc = evaluate_window(tmp_path, write=True)
    by_date = {r["cycle_date"]: r for r in doc["per_verdict"]}

    act_hit = by_date["2026-07-01"]
    assert act_hit["outcome"] == "hit"
    assert act_hit["forward_days_checked"] == 7
    assert act_hit["benefit_usd_over_checked_days"] == pytest.approx(57.53, abs=0.01)
    assert act_hit["net_usd"] == pytest.approx(47.53, abs=0.01)
    assert act_hit["cost_source"] == "recorded"

    act_miss = by_date["2026-07-02"]
    assert act_miss["outcome"] == "miss"
    assert act_miss["net_usd"] == pytest.approx(-38.49, abs=0.01)

    hold_missed = by_date["2026-07-03"]
    assert hold_missed["outcome"] == "miss"
    assert hold_missed["missed_usd"] == pytest.approx(47.53, abs=0.01)

    trivial = by_date["2026-07-04"]
    assert trivial["outcome"] == "hit" and trivial["trivial"] is True

    unpriced = by_date["2026-07-05"]
    assert unpriced["outcome"] == "UNCHECKED"
    assert unpriced["unchecked_reason"] == "no_evidenced_apy_for_moved_legs"
    assert unpriced["unpriced_protocols"] == ["C"]

    last = by_date["2026-07-31"]
    assert last["outcome"] == "UNCHECKED"
    assert last["unchecked_reason"] == "no_forward_data"
    # turnover $10k ⇒ 15 bps assumption = $15, labelled as such
    assert last["cost_usd_used"] == pytest.approx(15.0, abs=0.01)
    assert last["cost_source"].startswith("assumption:")

    # Aggregates: scored = {d01 hit, d02 miss, d03 miss} ⇒ hit-rate 1/3;
    # following the ACTs nets 47.53 − 38.49 = $9.04 = 0.9 bps of $100k.
    # hold: d03+d04+d05 + 25 тихих (d06..d30) = 28; trivial: d04 + 25 = 26
    # (растяжка окна до порога ADR-067; scored/unchecked не изменились)
    assert doc["counts"] == {"act": 3, "hold": 28, "trivial_hold": 26,
                             "scored": 3, "unchecked": 2,
                             "corrupt_history_lines": 0}
    assert doc["hit_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert doc["net_usd_if_followed"] == pytest.approx(9.04, abs=0.01)
    assert doc["net_bps_if_followed"] == pytest.approx(0.9, abs=0.01)
    assert doc["hold_missed_usd_total"] == pytest.approx(47.53, abs=0.01)

    # 31 день наблюдения (ADR-067: порог 30), но лишь 3 scored ⇒ hit-rate
    # criterion UNCHECKED ⇒ fail-closed NOT_READY.
    assert doc["status"] == "NOT_READY" and doc["ready_to_arm"] is False
    st = {c["criterion"]: c["status"] for c in doc["criteria"]}
    assert st["observation_days"] == "PASS"
    assert st["hit_rate"] == "UNCHECKED"
    assert st["net_bps_if_followed"] == "PASS"

    assert (tmp_path / EVAL_FILENAME).exists()
    on_disk = json.loads((tmp_path / EVAL_FILENAME).read_text(encoding="utf-8"))
    assert on_disk["status"] == "NOT_READY"


def test_all_criteria_pass_makes_ready(tmp_path: Path) -> None:
    """5 scored ACT hits over 31 days ⇒ READY (positive control, пороги ADR-067)."""
    apy = {"A": 2.0, "B": 8.0}
    for i in range(1, 6):  # d01..d05: five paying ACTs
        append_rationale_history(
            _rec(f"2026-07-{i:02d}", verdict="ACT", cost_usd=10.0,
                 current_positions={"A": 100_000.0},
                 target_positions={"A": 50_000.0, "B": 50_000.0},
                 apy_evidenced_pct=apy), tmp_path)
    # ADR-067: порог наблюдения 30 дней — тихий хвост растянут до d31 (инв. 16)
    for i in range(6, 32):  # d06..d31: quiet forward days
        append_rationale_history(
            _rec(f"2026-07-{i:02d}", verdict="HOLD",
                 current_positions={"A": 100_000.0},
                 target_positions={"A": 100_000.0},
                 apy_evidenced_pct=apy), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    assert doc["hit_rate"] == 1.0
    assert doc["net_bps_if_followed"] > 0
    assert all(c["status"] == "PASS" for c in doc["criteria"])
    assert doc["status"] == "READY" and doc["ready_to_arm"] is True


def test_undersized_window_is_not_ready(tmp_path: Path) -> None:
    for i in range(1, 4):  # only 3 observed days
        append_rationale_history(_rec(f"2026-08-{i:02d}"), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    assert doc["observation_days"] == 3
    days = next(c for c in doc["criteria"] if c["criterion"] == "observation_days")
    assert days["status"] == "FAIL"
    assert doc["status"] == "NOT_READY"


def test_no_scored_act_keeps_payoff_unchecked(tmp_path: Path) -> None:
    """An all-HOLD week must NOT read as proof the trigger pays (fail-closed)."""
    for i in range(1, 9):
        append_rationale_history(
            _rec(f"2026-08-{i:02d}", verdict="HOLD",
                 current_positions={"A": 100_000.0},
                 target_positions={"A": 100_000.0},
                 apy_evidenced_pct={"A": 2.0}), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    net = next(c for c in doc["criteria"] if c["criterion"] == "net_bps_if_followed")
    assert net["status"] == "UNCHECKED"
    assert doc["status"] == "NOT_READY"


def test_missing_target_is_a_data_hole_not_a_liquidation(tmp_path: Path) -> None:
    """A log-reconstructed line without the proposed book must go UNCHECKED —
    pricing it as 'sell everything' would fabricate a counterfactual."""
    append_rationale_history(
        _rec("2026-08-01", verdict="HOLD",
             current_positions={"A": 100_000.0}, target_positions={},
             apy_evidenced_pct={"A": 2.0}), tmp_path)
    append_rationale_history(
        _rec("2026-08-02", apy_evidenced_pct={"A": 2.0},
             current_positions={"A": 100_000.0},
             target_positions={"A": 100_000.0}), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    row = doc["per_verdict"][0]
    assert row["outcome"] == "UNCHECKED"
    assert row["unchecked_reason"] == "no_target_recorded"


def test_equity_curve_cross_check_is_attached(tmp_path: Path) -> None:
    append_rationale_history(
        _rec("2026-08-01", apy_evidenced_pct={"A": 2.0},
             current_positions={"A": 100_000.0},
             target_positions={"A": 100_000.0}), tmp_path)
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps(
        {"daily": [{"date": "2026-08-01", "apy_today": 6.01}]}), encoding="utf-8")
    doc = evaluate_window(tmp_path, write=False)
    assert doc["per_verdict"][0]["book_apy_equity_pct"] == 6.01


# ═══════════════════════ robustness: nothing here may break the cycle ═════════


def test_evaluator_survives_empty_dir_and_writes_not_ready(tmp_path: Path) -> None:
    doc = evaluate_window(tmp_path, write=True)
    assert doc["status"] == "NOT_READY"
    assert doc["observation_days"] == 0
    assert (tmp_path / EVAL_FILENAME).exists()


def test_evaluator_counts_corrupt_lines_instead_of_dying(tmp_path: Path) -> None:
    (tmp_path / HISTORY_FILENAME).write_text(
        "garbage\n" + json.dumps(_rec("2026-08-01")) + "\n[1,2]\n", encoding="utf-8")
    records, bad = load_history(tmp_path)
    assert len(records) == 1 and bad == 2
    doc = evaluate_window(tmp_path, write=False)
    assert doc["counts"]["corrupt_history_lines"] == 2


def test_cycle_hook_is_guarded_and_after_rationale() -> None:
    """The Step-2g hook exists, sits AFTER the shadow write, and is fail-open."""
    src = Path(ste.__file__).parents[1].joinpath("paper_trading", "cycle_runner.py") \
        .read_text(encoding="utf-8")
    imp = src.index(
        "from spa_core.paper_trading.shadow_trigger_eval import evaluate_window")
    assert src.index("write_shadow_rationale(") < imp  # history first, eval second
    assert "Y3 shadow-eval skipped" in src             # except-branch: fail-open
    # the import is inside the guarded block, not module-level
    assert src.rfind("try:", 0, imp) > src.index("write_shadow_rationale(")


def test_format_summary_is_printable(tmp_path: Path) -> None:
    _seed_timeline(tmp_path)
    text = format_summary(evaluate_window(tmp_path, write=False))
    assert "NOT_READY" in text and "Критерии включения" in text
