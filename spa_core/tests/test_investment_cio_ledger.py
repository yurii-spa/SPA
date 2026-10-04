# FROZEN-DATE-OK: injected-clock — every date is passed in: outcomes.score_due(now=...), ledger.append of dated recommendations
"""Tests for spa_core.investment_cio.ledger + outcomes (ADR-554 WP-S03/S04)."""
from __future__ import annotations

import hashlib
import json
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.investment_cio import contract, ledger, outcomes, read as cio_read


def _minimal_rec(date: str, weights: dict, *, seed_split: dict | None = None, rec_id: str | None = None) -> dict:
    """A bare recommendation dict — enough for ledger/outcomes mechanics tests (policy.py's own
    tests cover REC_FIELDS completeness)."""
    return {
        "schema": contract.SCHEMA_REC,
        "recommendation_id": rec_id or hashlib.sha256(f"{date}-{weights}".encode()).hexdigest(),
        "generated_at": f"{date}T09:30:00Z",
        "date": date,
        "recommended_weights": weights,
        "seed_split_weights": seed_split if seed_split is not None else dict(weights),
        "stance": contract.STANCE_RECOMMEND if weights else contract.STANCE_NONE,
        "lineage": {},
    }


def _write_equity_files(data_dir) -> None:
    (data_dir / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-09-01", "equity": 100000.0, "evidenced": True},
        {"date": "2026-09-08", "equity": 100700.0, "evidenced": True},
        {"date": "2026-10-01", "equity": 103000.0, "evidenced": True},
    ]}))
    (data_dir / "hy_paper_trading.json").write_text(json.dumps({
        "daily_history": [
            {"date": "2026-09-01", "equity": 50000.0},
            {"date": "2026-09-08", "equity": 50500.0},
            {"date": "2026-10-01", "equity": 51500.0},
        ],
        "economics_model_boundary": {"first_v2_date": "2026-08-15", "activated_at": "2026-08-15T00:00:00Z"},
    }))
    (data_dir / "lp_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-01", "equity": 20000.0},
        {"date": "2026-09-08", "equity": 20100.0},
        {"date": "2026-10-01", "equity": 20600.0},
    ]}))


# ── append-only + chain verify ───────────────────────────────────────────────────────────────────

def test_append_only_chain_verify(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    line1 = ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}),
                          snapshot_digest_=snap, code_identity_=code_id)
    line2 = ledger.append(tmp_path, _minimal_rec("2026-09-02", {"defi_conservative": 0.5, "cash": 0.5}),
                          snapshot_digest_=snap, code_identity_=code_id)
    assert line1["seq"] == 1 and line2["seq"] == 2
    assert line2["prev_hash"] == line1["entry_hash"]
    verdict = ledger.verify_chain(tmp_path)
    assert verdict == {"ok": True, "break_at": None, "entries": 2}


def test_tampering_breaks_chain_and_refuses_append(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)

    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    row = json.loads(path.read_text().strip())
    row["recommendation"]["recommended_weights"] = {"cash": 0.5, "defi_conservative": 0.5}  # edit, no rehash
    path.write_text(json.dumps(row) + "\n")

    verdict = ledger.verify_chain(tmp_path)
    assert verdict["ok"] is False
    assert verdict["break_at"] == 1

    with pytest.raises(ledger.LedgerError):
        ledger.append(tmp_path, _minimal_rec("2026-09-02", {"cash": 1.0}), snapshot_digest_=snap,
                      code_identity_=code_id)


def test_backdated_append_refuses_and_leaves_ledger_untouched(tmp_path):
    """Finding #15: one-entry-per-date used to check only the LAST entry, so a back-dated run
    (an older date appended after a newer one) silently inserted itself into history."""
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-05", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    with pytest.raises(ledger.LedgerError):
        ledger.append(tmp_path, _minimal_rec("2026-09-01", {"defi_conservative": 1.0}),
                      snapshot_digest_=snap, code_identity_=code_id)
    entries = ledger.read_all(tmp_path)
    assert len(entries) == 1
    assert entries[0]["recommendation"]["date"] == "2026-09-05"


def test_torn_last_line_raises_a_named_ledger_error_not_a_bare_json_error(tmp_path):
    """Finding #5: a torn last ledger line (partial write) used to raise a bare
    ``json.JSONDecodeError`` out of every reader. Now every reader gets a named
    :class:`ledger.LedgerError` pointing at the exact line."""
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    ledger.append(tmp_path, _minimal_rec("2026-09-02", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    with open(path, "a") as f:
        f.write('{"seq": 3, "prev_hash": "deadbeef", "entry_hash":')  # torn mid-write, no closing

    with pytest.raises(ledger.LedgerError, match="line 3"):
        ledger.read_all(tmp_path)
    with pytest.raises(ledger.LedgerError, match="line 3"):
        ledger.verify_chain(tmp_path)
    with pytest.raises(ledger.LedgerError, match="line 3"):
        ledger.append(tmp_path, _minimal_rec("2026-09-03", {"cash": 1.0}), snapshot_digest_=snap,
                      code_identity_=code_id)


def test_repair_moves_torn_tail_and_restores_an_intact_chain(tmp_path):
    """Finding #5: ``ledger.repair()`` verifies the chain up to the last good line and moves the
    torn tail aside — never deletes it — leaving the ledger intact afterwards."""
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    ledger.append(tmp_path, _minimal_rec("2026-09-02", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    with open(path, "a") as f:
        f.write('{"seq": 3, "prev_hash": "deadbeef", "entry_hash":')  # torn mid-write

    with pytest.raises(ledger.LedgerError):
        ledger.verify_chain(tmp_path)

    result = ledger.repair(tmp_path)
    assert result["repaired"] is True
    assert result["good_lines"] == 2
    assert result["moved_lines"] >= 1
    torn_path = Path(result["torn_file"])
    assert torn_path.exists()
    assert "deadbeef" in torn_path.read_text()

    assert ledger.verify_chain(tmp_path) == {"ok": True, "break_at": None, "entries": 2}
    assert len(ledger.read_all(tmp_path)) == 2

    # a second repair on an already-intact ledger is a safe no-op
    result2 = ledger.repair(tmp_path)
    assert result2["repaired"] is False


def test_fully_rewritten_ledger_disagrees_with_the_external_anchors(tmp_path):
    """Finding #21: a ledger fully rewritten with internally-consistent, recomputed hashes (but
    different content) can no longer be caught by the hash chain alone — the external, never-
    rewritten ``anchors.jsonl`` is what catches it."""
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    ledger.append(tmp_path, _minimal_rec("2026-09-02", {"defi_conservative": 0.5, "cash": 0.5}),
                  snapshot_digest_=snap, code_identity_=code_id)
    assert ledger.verify_chain(tmp_path)["ok"] is True
    anchors_before = ledger.read_anchors(tmp_path)
    assert len(anchors_before) == 2

    # rewrite the WHOLE ledger with different content, recomputing a self-consistent hash chain
    rec1 = _minimal_rec("2026-09-01", {"cash": 1.0})
    rec2 = _minimal_rec("2026-09-02", {"cash": 0.3, "defi_conservative": 0.7})  # different history
    h1 = ledger._entry_hash(ledger.GENESIS, 1, rec1, snap, code_id)
    line1 = {"seq": 1, "prev_hash": ledger.GENESIS, "entry_hash": h1, "recommendation": rec1,
            "snapshot_digest": snap, "code_identity": code_id}
    h2 = ledger._entry_hash(h1, 2, rec2, snap, code_id)
    line2 = {"seq": 2, "prev_hash": h1, "entry_hash": h2, "recommendation": rec2,
            "snapshot_digest": snap, "code_identity": code_id}
    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    path.write_text(json.dumps(line1) + "\n" + json.dumps(line2) + "\n")

    # the rewrite is internally self-consistent (a plain hash-chain check alone would pass it)
    entries = ledger.read_all(tmp_path)
    prev, self_consistent = ledger.GENESIS, True
    for e in entries:
        want = ledger._entry_hash(prev, e["seq"], e["recommendation"], e["snapshot_digest"], e["code_identity"])
        self_consistent = self_consistent and want == e["entry_hash"]
        prev = e["entry_hash"]
    assert self_consistent, "the rewrite must be internally self-consistent to test the ANCHOR, not the hash check"

    verdict = ledger.verify_chain(tmp_path)
    assert verdict["ok"] is False
    assert verdict.get("reason") == "anchor_mismatch"


def test_anchors_are_written_on_every_real_append_and_never_on_an_idempotent_one(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    assert len(ledger.read_anchors(tmp_path)) == 1
    # the same date again (idempotent) must not append a second anchor row
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"defi_conservative": 1.0}), snapshot_digest_=snap,
                  code_identity_=code_id)
    assert len(ledger.read_anchors(tmp_path)) == 1


def test_one_per_date_idempotence(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    line1 = ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}),
                          snapshot_digest_=snap, code_identity_=code_id)
    different_but_same_date = _minimal_rec("2026-09-01", {"cash": 0.9, "defi_conservative": 0.1})
    line2 = ledger.append(tmp_path, different_but_same_date, snapshot_digest_=snap, code_identity_=code_id)
    assert line1["entry_hash"] == line2["entry_hash"]
    assert len(ledger.read_all(tmp_path)) == 1


def test_corrupt_latest_json_rebuilds(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    written = ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}),
                            snapshot_digest_=snap, code_identity_=code_id)
    latest_path = tmp_path / contract.DATA_SUBDIR / contract.LATEST
    latest_path.write_text("{not valid json")
    assert ledger.read_latest_pointer(tmp_path) is None

    rebuilt = ledger.rebuild_latest(tmp_path)
    assert rebuilt is not None
    assert rebuilt["entry_hash"] == written["entry_hash"]
    assert ledger.read_latest_pointer(tmp_path)["entry_hash"] == written["entry_hash"]


def test_missing_latest_json_rebuilds(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    written = ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}),
                            snapshot_digest_=snap, code_identity_=code_id)
    (tmp_path / contract.DATA_SUBDIR / contract.LATEST).unlink()
    assert ledger.read_latest_pointer(tmp_path) is None
    rebuilt = ledger.rebuild_latest(tmp_path)
    assert rebuilt["entry_hash"] == written["entry_hash"]


def _worker_append(data_dir_str, rec, snap_digest, code_id, q):
    from spa_core.investment_cio import ledger as _ledger  # re-import in the child process
    try:
        line = _ledger.append(data_dir_str, rec, snapshot_digest_=snap_digest, code_identity_=code_id,
                             lock_timeout_s=10.0)
        q.put(("ok", line["seq"], line["entry_hash"]))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        q.put(("err", str(exc), None))


def test_concurrent_runs_two_processes_one_entry(tmp_path):
    rec = _minimal_rec("2026-09-05", {"cash": 1.0})
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker_append, args=(str(tmp_path), rec, snap, code_id, q)) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=20)
    results = [q.get(timeout=5) for _ in procs]
    assert all(r[0] == "ok" for r in results), results
    entries = ledger.read_all(tmp_path)
    assert len(entries) == 1
    assert ledger.verify_chain(tmp_path)["ok"] is True


def test_snapshot_immutability(tmp_path):
    doc = {"a": 1, "b": [1, 2, 3]}
    d1 = ledger.save_snapshot(tmp_path, doc)
    path = tmp_path / contract.DATA_SUBDIR / contract.SNAPSHOT_DIR / f"{d1}.json.gz"
    content1 = path.read_bytes()
    d2 = ledger.save_snapshot(tmp_path, doc)
    assert d1 == d2
    assert path.read_bytes() == content1
    assert ledger.load_snapshot(tmp_path, d1) == doc


def test_prune_never_deletes_a_referenced_snapshot(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap,
                  code_identity_=ledger.code_identity())
    path = tmp_path / contract.DATA_SUBDIR / contract.SNAPSHOT_DIR / f"{snap}.json.gz"
    # pretend it's ancient
    old = 0
    import os
    os.utime(path, (old, old))
    removed = ledger.prune_snapshots(tmp_path, retention_days=1, now=datetime.now(timezone.utc))
    assert snap not in removed
    assert path.exists()


def test_prune_deletes_unreferenced_old_snapshot(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"unreferenced": True})
    path = tmp_path / contract.DATA_SUBDIR / contract.SNAPSHOT_DIR / f"{snap}.json.gz"
    import os
    os.utime(path, (0, 0))
    removed = ledger.prune_snapshots(tmp_path, retention_days=1, now=datetime.now(timezone.utc))
    assert snap in removed
    assert not path.exists()


# ── outcomes: lookahead, buy-and-hold math, re-versioned continuity ────────────────────────────────

def test_outcome_lookahead_horizon_not_elapsed_means_no_outcome(tmp_path):
    _write_equity_files(tmp_path)
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"defi_conservative": 1.0}),
                 snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}), code_identity_=ledger.code_identity())
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)  # 4 days later: neither 7d nor 30d elapsed
    assert outcomes.find_due(tmp_path, now) == []
    summary = outcomes.score_due(tmp_path, now)
    assert summary["scored"] == 0
    assert not (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).exists()


def test_bars_at_or_before_rec_date_are_never_the_target_leg():
    from spa_core.investment_cio.outcomes import _anchor_and_target
    series = [
        {"date": "2026-08-20", "equity": 999999.0},
        {"date": "2026-09-01", "equity": 100000.0},  # == rec_date -> must become the ANCHOR, never target
        {"date": "2026-09-08", "equity": 100700.0},
    ]
    anchor, target = _anchor_and_target(series, "2026-09-01", "2026-09-08")
    assert anchor == {"date": "2026-09-01", "equity": 100000.0}
    assert target == {"date": "2026-09-08", "equity": 100700.0}
    assert target["date"] > "2026-09-01"


# ── finding N2: target must be the FIRST bar at/after target_date, never the nearest EARLIER one ─

def test_target_is_the_first_bar_at_or_after_target_date_never_an_earlier_one():
    from spa_core.investment_cio.outcomes import _anchor_and_target
    series = [
        {"date": "2026-09-01", "equity": 100000.0},  # == rec_date -> anchor
        {"date": "2026-09-05", "equity": 100300.0},  # a short 4-day bar — must NEVER be the target
    ]
    anchor, target = _anchor_and_target(series, "2026-09-01", "2026-09-08")  # 7-day horizon
    assert anchor == {"date": "2026-09-01", "equity": 100000.0}
    assert target is None, "no bar has reached the 7-day target_date yet — must stay pending"

    # once a bar lands AT or AFTER target_date, it (and only it) becomes the target
    series.append({"date": "2026-09-09", "equity": 100900.0})
    _, target2 = _anchor_and_target(series, "2026-09-01", "2026-09-08")
    assert target2 == {"date": "2026-09-09", "equity": 100900.0}


def test_short_horizon_bar_is_never_written_as_the_full_horizon_return(tmp_path):
    """Probe exactly as specified: rec 09-05, series ends 09-08, run 09-12. A 7-day horizon (due
    09-12) must NOT be written as a measured 3-day return labelled 7-day — it must stay PENDING."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-05", "equity": 50000.0}, {"date": "2026-09-08", "equity": 50300.0},
    ]}))
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-05", "equity": 20000.0}, {"date": "2026-09-08", "equity": 20100.0},
    ]}))
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-09-05", "equity": 100000.0, "evidenced": True},
        {"date": "2026-09-08", "equity": 100300.0, "evidenced": True},  # series ENDS here, 09-12 never arrives
    ]}))
    rec = _minimal_rec("2026-09-05", {"defi_conservative": 1.0})
    ledger.append(tmp_path, rec, snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}),
                 code_identity_=ledger.code_identity())
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)  # exactly the 7-day due date; no 09-12 bar exists
    summary = outcomes.score_due(tmp_path, now)
    assert summary["scored"] == 0, "a 3-day bar must never be written as the 7-day outcome"
    assert not (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).exists()


def test_anchor_date_says_snapshot_when_equity_came_from_the_snapshot(tmp_path):
    from spa_core.investment_cio.outcomes import _bah_leg
    series = [{"date": "2026-09-01", "equity": 999999.0}, {"date": "2026-09-08", "equity": 101000.0}]
    leg_live = _bah_leg(series, "2026-09-01", "2026-09-08")
    assert leg_live["anchor_date"] == "2026-09-01"
    leg_snapshot = _bah_leg(series, "2026-09-01", "2026-09-08", anchor_equity=100000.0)
    assert leg_snapshot["anchor_date"] == "snapshot"
    assert leg_snapshot["anchor_source"] == "snapshot_current_equity"
    # the VALUE used must be the snapshot's, not the live bar's 999999.0
    assert pytest.approx(leg_snapshot["return_pct"], abs=1e-9) == 101000.0 / 100000.0 - 1.0


def test_max_drawdown_uses_the_same_snapshot_anchor_as_the_return_leg():
    from spa_core.investment_cio.outcomes import _max_drawdown_in_horizon
    series_by_sleeve = {
        "defi_conservative": {"state": contract.MEASURED, "series": [
            {"date": "2026-09-01", "equity": 100000.0},
            {"date": "2026-09-04", "equity": 90000.0},   # a real ~10% dip vs the TRUE (snapshot) anchor
            {"date": "2026-09-08", "equity": 101000.0},
        ]},
    }
    weights = {"defi_conservative": 1.0}
    result = _max_drawdown_in_horizon(weights, series_by_sleeve, "2026-09-01", "2026-09-08",
                                      anchors_by_sleeve={"defi_conservative": 100000.0})
    assert result["state"] == contract.MEASURED
    assert pytest.approx(result["max_drawdown_pct"], abs=1e-6) == 0.10


def test_max_drawdown_window_extends_to_the_same_target_bar_as_the_return_leg():
    from spa_core.investment_cio.outcomes import _max_drawdown_in_horizon
    series_by_sleeve = {
        "defi_conservative": {"state": contract.MEASURED, "series": [
            {"date": "2026-09-01", "equity": 100000.0},
            {"date": "2026-09-09", "equity": 90000.0},  # lands AFTER the calendar target_date (09-08)
        ]},
    }
    weights = {"defi_conservative": 1.0}
    without_target_bar_date = _max_drawdown_in_horizon(weights, series_by_sleeve, "2026-09-01", "2026-09-08")
    # the calendar-bound window excludes the 09-09 bar entirely -> no drawdown is visible at all
    assert without_target_bar_date["max_drawdown_pct"] == 0.0

    with_target_bar_date = _max_drawdown_in_horizon(weights, series_by_sleeve, "2026-09-01", "2026-09-08",
                                                     target_bar_date="2026-09-09")
    assert pytest.approx(with_target_bar_date["max_drawdown_pct"], abs=1e-6) == 0.10


def test_buy_and_hold_math_on_known_scene(tmp_path):
    _write_equity_files(tmp_path)
    rec = _minimal_rec("2026-09-01", {"defi_conservative": 0.6, "defi_balanced": 0.3, "cash": 0.1},
                       seed_split={"defi_conservative": 1 / 3, "defi_balanced": 1 / 3, "defi_aggressive": 1 / 3})
    ledger.append(tmp_path, rec, snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}),
                 code_identity_=ledger.code_identity())
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)  # 9 days later: 7d elapsed, 30d not
    summary = outcomes.score_due(tmp_path, now)
    assert summary["scored"] == 1

    lines = (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["horizon_days"] == 7

    rec_leg = row["returns"]["RECOMMENDED"]
    assert rec_leg["state"] == contract.MEASURED
    assert pytest.approx(rec_leg["return_pct"], abs=1e-9) == 0.6 * 0.007 + 0.3 * 0.01 + 0.1 * 0.0

    seed_leg = row["returns"]["SEED_SPLIT"]
    assert pytest.approx(seed_leg["return_pct"], abs=1e-6) == (0.007 + 0.01 + 0.005) / 3

    equal_leg = row["returns"]["EQUAL_WEIGHT"]
    assert pytest.approx(equal_leg["return_pct"], abs=1e-6) == (0.007 + 0.01 + 0.005) / 3

    # a second call the same day must not duplicate the outcome row
    outcomes.score_due(tmp_path, now)
    lines2 = (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).read_text().splitlines()
    assert len(lines2) == 1


def test_reversioned_book_equity_is_continuous(tmp_path):
    _write_equity_files(tmp_path)
    result = outcomes.load_equity_series(tmp_path, "defi_balanced")
    assert result["state"] == contract.MEASURED
    assert len(result["series"]) == 3  # all bars kept across the boundary, never truncated
    assert result["events"] and result["events"][0]["type"] == "re_versioning"


def test_switching_cost_not_measured_when_evidence_file_absent(tmp_path):
    from spa_core.investment_cio.outcomes import _switching_cost
    result = _switching_cost(tmp_path)
    assert result["state"] == contract.NOT_MEASURED
    assert "rebalance_cost_evidence.json" in result["reason"]


def test_distinct_weight_episodes_counts_episodes_not_rows(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"defi_conservative": 1.0}),
                 snapshot_digest_=snap, code_identity_=code_id)
    ledger.append(tmp_path, _minimal_rec("2026-09-02", {"defi_conservative": 1.0}),  # same weights -> HOLD, not a new episode
                 snapshot_digest_=snap, code_identity_=code_id)
    ledger.append(tmp_path, _minimal_rec("2026-09-03", {"defi_conservative": 0.5, "cash": 0.5}),  # new episode
                  snapshot_digest_=snap, code_identity_=code_id)
    assert outcomes.distinct_weight_episodes(tmp_path) == 2


# ── finding #16: outcomes stay pending (never a permanent NOT_MEASURED) until a bar lands ───────

def test_outcome_stays_pending_until_a_bar_lands_then_scores_on_retry(tmp_path):
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-01", "equity": 50000.0}, {"date": "2026-09-08", "equity": 50500.0},
    ]}))
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-01", "equity": 20000.0}, {"date": "2026-09-08", "equity": 20100.0},
    ]}))
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-09-01", "equity": 100000.0, "evidenced": True},
    ]}))  # no 09-08 bar YET for conservative
    rec = _minimal_rec("2026-09-01", {"defi_conservative": 1.0})
    ledger.append(tmp_path, rec, snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}),
                 code_identity_=ledger.code_identity())
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)  # 10 days later: 7d horizon elapsed, no bar yet

    summary1 = outcomes.score_due(tmp_path, now)
    assert summary1["scored"] == 0
    assert not (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).exists()

    # the book finally publishes the bar the 7d horizon needed
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-09-01", "equity": 100000.0, "evidenced": True},
        {"date": "2026-09-08", "equity": 101000.0, "evidenced": True},
    ]}))
    summary2 = outcomes.score_due(tmp_path, now)
    assert summary2["scored"] == 1
    lines = (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["returns"]["RECOMMENDED"]["state"] == contract.MEASURED
    assert "note" not in row


def test_outcome_written_not_measured_only_after_the_pending_grace_expires(tmp_path):
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-01", "equity": 50000.0}, {"date": "2026-09-08", "equity": 50500.0},
    ]}))
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps({"daily_history": [
        {"date": "2026-09-01", "equity": 20000.0}, {"date": "2026-09-08", "equity": 20100.0},
    ]}))
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-09-01", "equity": 100000.0, "evidenced": True},
    ]}))  # conservative NEVER publishes its 09-08 bar
    rec = _minimal_rec("2026-09-01", {"defi_conservative": 1.0})
    ledger.append(tmp_path, rec, snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}),
                 code_identity_=ledger.code_identity())

    still_pending_at = datetime(2026, 9, 11, tzinfo=timezone.utc)  # past the 7d horizon, within grace
    assert outcomes.score_due(tmp_path, still_pending_at)["scored"] == 0

    well_past_grace = datetime(2026, 9, 20, tzinfo=timezone.utc)  # > target_date(09-08) + 7d grace
    summary = outcomes.score_due(tmp_path, well_past_grace)
    assert summary["scored"] == 1
    row = json.loads((tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).read_text().splitlines()[0])
    assert row["returns"]["RECOMMENDED"]["state"] == contract.NOT_MEASURED
    assert "note" in row and "terminal" in row["note"]


def test_anchor_equity_prefers_the_recommendations_own_snapshot(tmp_path):
    """Finding #16: the anchor for a horizon return is the sleeve's current_equity AS RECORDED in
    the recommendation's own immutable snapshot, not a live re-read of a (possibly later-edited)
    equity file."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({"daily_history": []}))
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps({"daily_history": []}))
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-09-01", "equity": 999999.0, "evidenced": True},  # a LATER, different anchor value
        {"date": "2026-09-08", "equity": 101000.0, "evidenced": True},
    ]}))
    sleeves_doc = {"sleeves": {"defi_conservative": {
        "current_equity": contract.measured(100000.0, unit="usd", source="test", as_of="2026-09-01"),
    }}}
    snap = ledger.save_snapshot(tmp_path, sleeves_doc)
    anchor = outcomes.anchor_equity_from_snapshot(tmp_path, snap, "defi_conservative")
    assert anchor == 100000.0  # the SNAPSHOT's own figure, not the 999999.0 the live file carries

    # a sleeve absent from the snapshot (or a synthetic test snapshot) falls back gracefully
    assert outcomes.anchor_equity_from_snapshot(tmp_path, snap, "defi_balanced") is None
    legacy_snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    assert outcomes.anchor_equity_from_snapshot(tmp_path, legacy_snap, "defi_conservative") is None


# ── finding #7: score_due must hold the outcomes lock around the WHOLE find+append cycle ───────

def test_concurrent_score_due_never_duplicates_an_outcome(tmp_path, monkeypatch):
    """Widening the window between "decided due" and "appended" (via a slowed find_due) used to
    let two concurrent score_due() calls both decide an item was due and both append it — because
    the old code only locked the final per-item write, not the decision. Threads (not processes)
    so the monkeypatched, slowed find_due is shared."""
    import threading
    import time as _time

    _write_equity_files(tmp_path)
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"defi_conservative": 1.0}),
                 snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}), code_identity_=ledger.code_identity())
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)

    real_find_due = outcomes.find_due

    def slow_find_due(data_dir, now_):
        result = real_find_due(data_dir, now_)
        _time.sleep(0.3)  # widens the race window finding #7 closed by moving the lock earlier
        return result

    monkeypatch.setattr(outcomes, "find_due", slow_find_due)

    threads = [threading.Thread(target=outcomes.score_due, args=(tmp_path, now), kwargs={"lock_timeout_s": 20.0})
              for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=25)

    lines = (tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES).read_text().splitlines()
    assert len(lines) == 1, f"race duplicated an outcome row: {len(lines)} lines"
    assert outcomes.distinct_scored_keys(tmp_path) == 1
    assert outcomes.verify_outcomes_chain(tmp_path)["ok"] is True


# ── finding #5 / #6: read.latest never raises, always serves the verified ledger tail ───────────

def test_read_latest_on_a_torn_ledger_returns_not_measured_never_raises(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    with open(path, "a") as f:
        f.write('{"seq": 2, "prev_hash": "deadbeef"')  # torn mid-write

    doc = cio_read.latest(tmp_path)  # must not raise
    assert doc["state"] == contract.NOT_MEASURED
    assert "line" in doc["reason"] or "repair" in doc["reason"]


def test_read_latest_always_serves_the_ledger_tail_never_an_edited_pointer(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    written = ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap,
                            code_identity_=code_id)

    doc = cio_read.latest(tmp_path)
    assert doc["state"] == contract.MEASURED
    assert doc["recommendation"] == written["recommendation"]
    assert doc["pointer_mismatch"] is False

    # edit latest.json's RECOMMENDATION content without recomputing its entry_hash field
    latest_path = tmp_path / contract.DATA_SUBDIR / contract.LATEST
    pointer = json.loads(latest_path.read_text())
    pointer["recommendation"] = dict(pointer["recommendation"], recommended_weights={"defi_conservative": 1.0})
    latest_path.write_text(json.dumps(pointer))  # entry_hash field left stale — still "matches" the tail

    doc2 = cio_read.latest(tmp_path)
    assert doc2["state"] == contract.MEASURED
    assert doc2["recommendation"] == written["recommendation"]  # served from the LEDGER TAIL, not the edited pointer
    assert doc2["pointer_mismatch"] is True


# ── finding N3: a chain that is NOT OK must withhold the recommendation entirely ────────────────

def test_read_latest_on_a_hash_tampered_chain_is_not_measured_and_withholds_the_recommendation(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)

    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    row = json.loads(path.read_text().strip())
    row["recommendation"]["recommended_weights"] = {"cash": 0.5, "defi_conservative": 0.5}  # edit, no rehash
    path.write_text(json.dumps(row) + "\n")
    assert ledger.verify_chain(tmp_path)["ok"] is False  # the tamper IS a hash break

    doc = cio_read.latest(tmp_path)
    assert doc["state"] == contract.NOT_MEASURED
    assert "recommendation" not in doc
    assert "break_at" in doc["reason"]


def test_a_missing_anchor_is_itself_a_break(tmp_path):
    """N3: an anchor that CAN be silently absent is not a witness. Deleting anchors.jsonl must
    make verify_chain report anchor_missing, not quietly fall back to 'nothing to cross-check'."""
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    assert ledger.verify_chain(tmp_path)["ok"] is True

    anchors_path = tmp_path / ledger.ANCHORS_DIRNAME / "anchors.jsonl"
    assert anchors_path.exists()
    anchors_path.unlink()

    verdict = ledger.verify_chain(tmp_path)
    assert verdict["ok"] is False
    assert verdict["reason"] == "anchor_missing"


def test_anchors_live_in_a_directory_sibling_to_investment_cio(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    anchors_path = tmp_path / ledger.ANCHORS_DIRNAME / "anchors.jsonl"
    assert anchors_path.exists()
    assert anchors_path.parent.parent == tmp_path  # a SIBLING of investment_cio/, not nested inside it
    assert not (tmp_path / contract.DATA_SUBDIR / "anchors.jsonl").exists()


def test_repair_refuses_on_tampering_it_cannot_fix(tmp_path):
    """N3: when the ledger FILE is internally self-consistent (parses, hash-chains cleanly) but
    disagrees with the never-rewritten external anchors, repair() must refuse outright — there is
    no torn tail to move aside, because every line looks well-formed. It must never claim 'chain
    already intact'."""
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"cash": 1.0}), snapshot_digest_=snap, code_identity_=code_id)
    ledger.append(tmp_path, _minimal_rec("2026-09-02", {"defi_conservative": 0.5, "cash": 0.5}),
                  snapshot_digest_=snap, code_identity_=code_id)

    rec1 = _minimal_rec("2026-09-01", {"cash": 1.0})
    rec2 = _minimal_rec("2026-09-02", {"cash": 0.3, "defi_conservative": 0.7})  # different history
    h1 = ledger._entry_hash(ledger.GENESIS, 1, rec1, snap, code_id)
    line1 = {"seq": 1, "prev_hash": ledger.GENESIS, "entry_hash": h1, "recommendation": rec1,
            "snapshot_digest": snap, "code_identity": code_id}
    h2 = ledger._entry_hash(h1, 2, rec2, snap, code_id)
    line2 = {"seq": 2, "prev_hash": h1, "entry_hash": h2, "recommendation": rec2,
            "snapshot_digest": snap, "code_identity": code_id}
    path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    path.write_text(json.dumps(line1) + "\n" + json.dumps(line2) + "\n")
    assert ledger.verify_chain(tmp_path)["ok"] is False  # self-consistent rewrite, anchors disagree

    result = ledger.repair(tmp_path)
    assert result["repaired"] is False
    assert result["fixable"] is False
    assert result["reason"] in ("anchor_mismatch", "anchor_missing")
    assert result["reason"] != "chain already intact"

    from spa_core.investment_cio import run as cio_run
    rc = cio_run.main(["--data-dir", str(tmp_path), "--repair"])
    assert rc == 2


# ── finding N6: executes/real_capital_usd are the LAST gate before anything is written ──────────

def test_append_refuses_a_recommendation_with_live_executes_or_nonzero_real_capital(tmp_path):
    snap = ledger.save_snapshot(tmp_path, {"doc": 1})
    code_id = ledger.code_identity()

    rec_bad_executes = _minimal_rec("2026-09-01", {"cash": 1.0})
    rec_bad_executes["executes"] = True
    with pytest.raises(ledger.LedgerError):
        ledger.append(tmp_path, rec_bad_executes, snapshot_digest_=snap, code_identity_=code_id)

    rec_bad_capital = _minimal_rec("2026-09-01", {"cash": 1.0})
    rec_bad_capital["real_capital_usd"] = 5000
    with pytest.raises(ledger.LedgerError):
        ledger.append(tmp_path, rec_bad_capital, snapshot_digest_=snap, code_identity_=code_id)

    assert ledger.read_all(tmp_path) == []  # neither refused attempt wrote anything

    rec_ok = _minimal_rec("2026-09-01", {"cash": 1.0})
    rec_ok["executes"] = False
    rec_ok["real_capital_usd"] = 0
    line = ledger.append(tmp_path, rec_ok, snapshot_digest_=snap, code_identity_=code_id)
    assert line["seq"] == 1


# ── final independent check (ADR-554): truncation, crash between writes, late target bars ─────────
def _two_entries(tmp_path):
    for d in ("2026-09-01", "2026-09-02"):
        ledger.append(tmp_path, _minimal_rec(d, {"defi_conservative": 1.0}),
                      snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": d}), code_identity_=ledger.code_identity())


def test_cutting_the_tail_entry_off_the_ledger_is_detected(tmp_path):
    """Deleting the last ledger line left a self-consistent chain; the anchors still remember it."""
    _two_entries(tmp_path)
    led = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    led.write_text(led.read_text().splitlines()[0] + "\n")
    v = ledger.verify_chain(tmp_path)
    assert v["ok"] is False and v["reason"] == "ledger_truncated"
    assert cio_read.latest(tmp_path)["integrity"] == "BROKEN"
    with pytest.raises(ledger.LedgerError):
        ledger.append(tmp_path, _minimal_rec("2026-09-03", {"defi_conservative": 1.0}),
                      snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 3}), code_identity_=ledger.code_identity())


def test_a_crash_before_the_tail_anchor_is_repairable_not_tampering(tmp_path):
    """The ledger line was written, the anchor was not (crash, or a torn last anchor line). The tail
    entry's own hash chain checks out ⇒ repair restores that single anchor; the ledger is usable again."""
    _two_entries(tmp_path)
    anc = ledger._anchors_path(tmp_path)
    lines = anc.read_text().splitlines()
    anc.write_text(lines[0] + "\n" + lines[1][:20])                 # torn last anchor line, no newline
    assert ledger.verify_chain(tmp_path)["reason"] == "anchor_missing"
    r = ledger.repair(tmp_path)
    assert r["fixable"] is True and r["repaired"] is True
    assert ledger.verify_chain(tmp_path)["ok"] is True
    ledger.append(tmp_path, _minimal_rec("2026-09-03", {"defi_conservative": 1.0}),
                  snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 3}), code_identity_=ledger.code_identity())
    assert ledger.verify_chain(tmp_path)["ok"] is True


def test_a_far_later_bar_is_not_scored_as_the_horizon_return(tmp_path):
    """Bars on days 0–3 then day 20: the 7-day horizon must not carry a ~20-day return."""
    def series(e0):
        return [{"date": "2026-09-01", "equity": e0}, {"date": "2026-09-04", "equity": e0 * 1.001},
                {"date": "2026-09-21", "equity": e0 * 1.012}]
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({"daily_history": series(50000.0)}))
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps({"daily_history": series(20000.0)}))
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        dict(r, evidenced=True) for r in series(100000.0)]}))
    ledger.append(tmp_path, _minimal_rec("2026-09-01", {"defi_conservative": 1.0}),
                  snapshot_digest_=ledger.save_snapshot(tmp_path, {"doc": 1}), code_identity_=ledger.code_identity())
    outcomes.score_due(tmp_path, datetime(2026, 9, 22, tzinfo=timezone.utc))
    path = tmp_path / contract.DATA_SUBDIR / contract.OUTCOMES
    rows = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    seven = [r for r in rows if r.get("horizon_days") == 7]
    for row in seven:                                   # pending (no row) is fine; a row must not end on day 20
        ends = [leg.get("end_date") for port in (row.get("returns") or {}).values()
                for leg in ((port or {}).get("legs") or {}).values()]
        assert "2026-09-21" not in ends, ends
