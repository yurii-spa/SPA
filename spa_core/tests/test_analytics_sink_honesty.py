"""The site-analytics sink must never report a success it did not measure.

Card `agent-checkup-waitlist-fail-open-ok-true`: the DeFi Checkup waitlist answered `ok:true`
for three weeks while no mail was sent, because the handler swallowed the failure and published
an optimistic flag. The twin of that bug lived here — `record_event` wrapped the append in a bare
`except: pass` and returned an unconditional `{"ok": True}` — on the very sink that carries the
Checkup funnel attribution (`utm_source=defi-checkup`), so a dead write reads as "no traffic".

POSITIVE CONTROL IN BOTH DIRECTIONS (each test fails on the unfixed code, and on a mutated fix):
  • a real write reports `ok:true` / `stored:"ok"` AND the row is on disk;
  • a failed write reports `ok:false` / `stored:"error"` and no row exists;
  • the three read outcomes stay distinguishable: measured counts · measured zero (absent sink)
    · NOT measured (unreadable sink → counts withheld, never a fabricated zero, never a 500).

No network, no real data/ — every sink is redirected into tmp_path.
"""
from __future__ import annotations

import json

import pytest

from spa_core.api.routers import analytics as A


# ── write side ────────────────────────────────────────────────────────────────────────────────

def test_successful_write_reports_ok_and_the_row_is_on_disk(monkeypatch, tmp_path):
    """The honest success half: ok:true is allowed ONLY together with a row on disk."""
    log = tmp_path / "site_analytics.jsonl"
    monkeypatch.setattr(A, "_LOG", log)
    out = A.record_event(A.Event(page="/packages", event="view",
                                 utm_source="defi-checkup", utm_campaign="depeg"))
    assert out["ok"] is True
    assert out["stored"] == "ok"
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["page"] == "/packages" and rows[0]["utm_source"] == "defi-checkup"


def test_failed_write_is_refused_not_reported_as_success(monkeypatch, tmp_path):
    """The measured fail-OPEN: sink path is a DIRECTORY ⇒ the append raises ⇒ nothing persists.

    Before the fix this returned {"ok": true} with zero rows written. The response must now carry
    the refusal — and the endpoint must still not raise (analytics may not 500 a public page)."""
    sink_dir = tmp_path / "sink_is_a_directory"
    sink_dir.mkdir()
    monkeypatch.setattr(A, "_LOG", sink_dir)
    out = A.record_event(A.Event(page="/", event="view"))
    assert out["ok"] is False, "a write that did not happen must never be reported as ok"
    assert out["stored"] == "error"
    assert not any(sink_dir.iterdir()), "nothing was persisted — that is the whole point"


def test_failed_write_never_raises_through_the_endpoint(monkeypatch, tmp_path):
    """Swallowing the exception stays correct — only the optimistic flag was wrong."""
    def _boom(*_a, **_kw):
        raise OSError("disk full")
    monkeypatch.setattr(A, "_LOG", tmp_path / "x.jsonl")
    monkeypatch.setattr("builtins.open", _boom)
    out = A.record_event(A.Event(page="/", event="view"))
    assert out == {"ok": False, "stored": "error"}


# ── read side: success · measured zero · not measured ─────────────────────────────────────────

def test_summary_reports_measured_counts_for_a_readable_sink(monkeypatch, tmp_path):
    log = tmp_path / "a.jsonl"
    monkeypatch.setattr(A, "_LOG", log)
    A.record_event(A.Event(page="/pilot", event="view",
                           utm_source="defi-checkup", utm_campaign="depeg"))
    s = A.summary()
    assert s["sink"] == "ok" and s["measured"] is True
    assert s["total_views"] == 1
    assert any(c["campaign"] == "defi-checkup:depeg" for c in s["top_campaigns"])
    assert "flag_reason" not in s


def test_absent_sink_is_a_measured_zero_not_an_unknown(monkeypatch, tmp_path):
    """No log yet genuinely means no events — that zero is honest and stays a zero."""
    monkeypatch.setattr(A, "_LOG", tmp_path / "never_written.jsonl")
    s = A.summary()
    assert s["sink"] == "absent" and s["measured"] is True
    assert s["total_views"] == 0 and s["views_today"] == 0


def test_unreadable_sink_withholds_counts_instead_of_publishing_a_zero(monkeypatch, tmp_path):
    """The third outcome: the log exists but cannot be read ⇒ NOT measured.

    A zero here would read as 'nobody visited' on the admin funnel page — the same lie class as
    ok:true for an unsent mail. Counts are withheld; the surface must not 500 either (only
    FileNotFoundError used to be caught, so an unreadable sink raised straight through)."""
    sink_dir = tmp_path / "sink_is_a_directory"
    sink_dir.mkdir()
    monkeypatch.setattr(A, "_LOG", sink_dir)
    s = A.summary()                       # must not raise
    assert s["sink"] == "unreadable" and s["measured"] is False
    assert s["total_views"] is None and s["views_today"] is None and s["views_7d"] is None
    assert s["top_pages"] == [] and s["top_campaigns"] == []
    assert "unreadable" in s["flag_reason"]


def test_the_three_read_outcomes_are_pairwise_distinguishable(monkeypatch, tmp_path):
    """Guards the fix from being 'simplified' back into two outcomes."""
    got = {}
    log = tmp_path / "b.jsonl"
    monkeypatch.setattr(A, "_LOG", tmp_path / "absent.jsonl")
    got["absent"] = (A.summary()["sink"], A.summary()["measured"])
    monkeypatch.setattr(A, "_LOG", log)
    A.record_event(A.Event(page="/", event="view"))
    got["ok"] = (A.summary()["sink"], A.summary()["measured"])
    bad = tmp_path / "dir_sink"
    bad.mkdir()
    monkeypatch.setattr(A, "_LOG", bad)
    got["unreadable"] = (A.summary()["sink"], A.summary()["measured"])
    assert len(set(got.values())) == 3, got


@pytest.mark.parametrize("keys", [("ok", "stored")])
def test_write_response_shape_is_pinned(monkeypatch, tmp_path, keys):
    monkeypatch.setattr(A, "_LOG", tmp_path / "c.jsonl")
    out = A.record_event(A.Event(page="/", event="view"))
    assert set(out) == set(keys)
