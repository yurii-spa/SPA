"""Tests for the Q2-14 research-changelog generator (scripts/generate_research_changelog.py).

Verifies: the digest is a deterministic template of REAL numbers (track ledger + refusal count), it is
idempotent (unchanged data → no duplicate), a same-date re-run with newer data replaces the entry, and it
is fail-CLOSED when there is no live data (no fabricated digest). Uses injected paths — no live coupling.
"""
import importlib
import json

import pytest

rcg = importlib.import_module("scripts.generate_research_changelog")


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    ledger = tmp_path / "track_ledger.json"
    ledger.write_text(json.dumps({
        "n_evidenced_days": 19, "days_needed": 30, "cumulative_return_pct": 0.21,
        "max_drawdown_from_peak_pct": 0.0, "last_evidenced_date": "2026-07-10"}))
    decisions = tmp_path / "decision_log.jsonl"
    decisions.write_text("\n".join(json.dumps({"approved": i % 3 != 0}) for i in range(9)) + "\n")
    out = tmp_path / "changelog.json"
    monkeypatch.setattr(rcg, "_LEDGER", ledger)
    monkeypatch.setattr(rcg, "_DECISIONS", decisions)
    monkeypatch.setattr(rcg, "_OUT", out)
    return {"ledger": ledger, "decisions": decisions, "out": out}


def test_digest_has_real_numbers(wired):
    r = rcg.generate(date="2026-07-11")
    assert r["created"] is True
    e = json.loads(wired["out"].read_text())[0]
    assert "19/30 days" in e["summary"]
    assert "+0.21%" in e["summary"]
    # 3 of 9 have approved=False (i%3==0 → 0,3,6) → 3 refusals of 9
    assert "3 declined of 9" in e["summary"]
    assert e["auto"] is True and e["tag"] == "Changelog"


def test_idempotent_no_duplicate(wired):
    rcg.generate(date="2026-07-11")
    r2 = rcg.generate(date="2026-07-11")
    assert r2["created"] is False
    assert "unchanged" in r2["reason"]
    assert len(json.loads(wired["out"].read_text())) == 1


def test_same_date_newer_data_replaces(wired):
    rcg.generate(date="2026-07-11")
    # track advances a day → new signature → same-slug entry replaced, not duplicated
    wired["ledger"].write_text(json.dumps({
        "n_evidenced_days": 20, "days_needed": 30, "cumulative_return_pct": 0.25,
        "max_drawdown_from_peak_pct": 0.0, "last_evidenced_date": "2026-07-11"}))
    r = rcg.generate(date="2026-07-11")
    assert r["created"] is True
    entries = json.loads(wired["out"].read_text())
    assert len(entries) == 1                          # replaced, not duplicated
    assert "20/30 days" in entries[0]["summary"]


def test_fail_closed_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(rcg, "_LEDGER", tmp_path / "missing.json")
    monkeypatch.setattr(rcg, "_DECISIONS", tmp_path / "missing.jsonl")
    monkeypatch.setattr(rcg, "_OUT", tmp_path / "out.json")
    r = rcg.generate(date="2026-07-11")
    assert r["created"] is False
    assert "no live data" in r["reason"]
