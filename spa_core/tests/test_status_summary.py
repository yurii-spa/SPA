"""Tests for the /status summary (ENV_SETUP cleanup — /status Telegram command)."""

from __future__ import annotations

from spa_core.telegram import status_summary


def test_build_status_summary_returns_html_with_all_blocks():
    msg = status_summary.build_status_summary()
    assert msg.startswith("📊 <b>Статус SPA</b>")
    # all four labelled blocks present
    assert "Агенты:" in msg
    assert "claude-сессии" in msg
    assert "Owner Decisions:" in msg or "Карточки:" in msg
    assert "STATE.md:" in msg
    assert "<b>" in msg  # HTML formatting


def test_cards_block_counts_real_tracker(tmp_path, monkeypatch):
    # point the queue at a temp tracker with known cards
    from spa_core.owner_queue import queue as q

    (tmp_path / "own-1.md").write_text(
        "---\ntrackerStatus:\n  type: owner-decision\ntitle: A\nstatus: needs-owner\n---\nx", encoding="utf-8")
    (tmp_path / "inbox-1.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: B\nstatus: new\n---\nx", encoding="utf-8")
    monkeypatch.setattr(q, "TRACKER_DIR", tmp_path)
    block = status_summary._cards_block()
    assert "needs-owner:1" in block
    assert "new:1" in block


def test_freshness_block_never_raises():
    # even if files are missing the block must return a string
    assert isinstance(status_summary._freshness_block(), str)
