"""Regression tests for the event-driven owner-queue intake (``run_note_intake``).

Focus: the intake used to carry its OWN copy of ``_slug`` WITHOUT the Cyrillic→Latin
transliteration that ``queue._slug`` gained in the readable-card-ids fix (cycle #3).
That divergent copy collapsed every Russian-titled *idea* into ``docs/ideas/<date>-note.md``.
The fix makes intake reuse the canonical ``queue._slug`` (DRY). These tests lock the
behaviour so the two slugs can never silently diverge again.

The classify / history-check / Telegram legs are Claude/network-backed, so they are
monkeypatched on their SOURCE modules (the intake imports them lazily, which binds to
the patched attributes at call time). No live ``claude`` or bot is exercised.
"""

from __future__ import annotations

from spa_core.owner_queue import intake as I
from spa_core.owner_queue import queue as Q
from spa_core.owner_queue import history_check as H
from spa_core.telegram import ask_router


def _wire(monkeypatch, tmp_path, *, card, kind, verdict="NEW", resp_h=""):
    """Redirect intake's dependencies at their source modules + isolate the repo root."""
    monkeypatch.setattr(I, "_REPO", tmp_path)                       # ideas/ + journal/ → tmp
    monkeypatch.setattr(I, "_notify", lambda *a, **k: None)          # no Telegram
    monkeypatch.setattr(Q, "ingest_notes", lambda *a, **k: None)    # no loose-note scan
    monkeypatch.setattr(Q, "list_cards", lambda **k: [card])        # feed our single card
    monkeypatch.setattr(H, "history_check", lambda body: {"verdict": verdict, "response": resp_h})
    monkeypatch.setattr(ask_router, "classify_and_answer", lambda body: (kind, ""))


def test_idea_filename_is_readable_translit_not_note(tmp_path, monkeypatch):
    """A Russian-titled idea must land under a transliterated, human-readable filename."""
    path = Q.create_card(
        "inbox", "Добавить кнопку наверх страницы",
        body="Добавить кнопку наверх страницы", status="new",
        tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    _wire(monkeypatch, tmp_path, card=card, kind="idea")

    res = I.run_note_intake()

    ideas = sorted((tmp_path / "docs" / "ideas").glob("*.md"))
    assert ideas, "idea note should have been written"
    name = ideas[0].name
    assert not name.endswith("-note.md"), f"idea filename collapsed to opaque -note.md: {name}"
    assert "dobavit" in name, f"expected transliterated slug, got: {name}"
    assert card.id in res["processed"]
    assert Q.load_card(path).status == "done"  # idea card closed (idea ≠ instruction)


def test_intake_reuses_canonical_queue_slug(tmp_path, monkeypatch):
    """The idea filename must match exactly what queue._slug produces (no divergent copy)."""
    title = "Проверить дашборд и графики"
    path = Q.create_card(
        "inbox", title, body=title, status="new", tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    _wire(monkeypatch, tmp_path, card=card, kind="idea")

    I.run_note_intake()

    ideas = sorted((tmp_path / "docs" / "ideas").glob("*.md"))
    assert ideas, "idea note should have been written"
    assert ideas[0].name.endswith(f"-{Q._slug(title)}.md")
