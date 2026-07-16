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
    """Redirect intake's dependencies at their source modules + isolate the repo root.

    Returns the list that captures every Telegram ``_notify`` payload, so tests can
    assert on what the owner actually sees."""
    notes: list[str] = []
    monkeypatch.setattr(I, "_REPO", tmp_path)                       # ideas/ + journal/ → tmp
    monkeypatch.setattr(Q, "TRACKER_DIR", tmp_path / "tracker")     # unclear→owner card stays in tmp
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: notes.append(text))  # capture Telegram
    monkeypatch.setattr(Q, "ingest_notes", lambda *a, **k: None)    # no loose-note scan
    monkeypatch.setattr(Q, "list_cards", lambda **k: [card])        # feed our single card
    monkeypatch.setattr(H, "history_check", lambda body: {"verdict": verdict, "response": resp_h})
    monkeypatch.setattr(ask_router, "classify_and_answer", lambda body: (kind, ""))
    return notes


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


# ── PARTIAL verdict (§1a): the "похоже на …, проверь" hint must reach BOTH the
# persisted card/note body AND the Telegram reply. It used to be dropped: intake set
# ``partial_note`` from the history-check but never read it in any routing branch.

_PARTIAL_RESP = "Похоже на карточку own-08 (расшифровка SPA), проверь — то же или другое?"


def test_partial_task_hint_in_card_body_and_telegram(tmp_path, monkeypatch):
    """A PARTIAL task keeps the card (in-progress) but stamps the match hint in body + TG."""
    path = Q.create_card(
        "inbox", "Уточнить расшифровку SPA", body="Уточнить расшифровку SPA",
        status="new", tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    notes = _wire(monkeypatch, tmp_path, card=card, kind="task",
                  verdict="PARTIAL", resp_h=_PARTIAL_RESP)

    I.run_note_intake()

    body = path.read_text(encoding="utf-8")
    assert _PARTIAL_RESP in body, "PARTIAL hint must be persisted in the card body for the full cycle"
    assert "похоже на уже существующее" in body.lower()
    assert Q.load_card(path).status == "in-progress"          # task still created
    assert any(_PARTIAL_RESP in n for n in notes), "owner's Telegram reply must carry the hint"


def test_partial_idea_hint_in_note_and_telegram(tmp_path, monkeypatch):
    """A PARTIAL idea is still saved, but the note file + TG reply carry the match hint."""
    path = Q.create_card(
        "inbox", "Идея про changelog", body="Идея про changelog",
        status="new", tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    notes = _wire(monkeypatch, tmp_path, card=card, kind="idea",
                  verdict="PARTIAL", resp_h=_PARTIAL_RESP)

    I.run_note_intake()

    ideas = sorted((tmp_path / "docs" / "ideas").glob("*.md"))
    assert ideas, "idea note should have been written"
    assert _PARTIAL_RESP in ideas[0].read_text(encoding="utf-8"), "PARTIAL hint must be in the idea note"
    assert any(_PARTIAL_RESP in n for n in notes), "owner's Telegram reply must carry the hint"


def test_partial_unclear_hint_in_owner_card_and_telegram(tmp_path, monkeypatch):
    """A PARTIAL unclear routes to an owner card whose body + TG reply carry the hint."""
    path = Q.create_card(
        "inbox", "Непонятное сообщение", body="ы", status="new",
        tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    # unclear branch writes to the DEFAULT owner-decision tracker; _wire isolates it to tmp.
    notes = _wire(monkeypatch, tmp_path, card=card, kind="unclear",
                  verdict="PARTIAL", resp_h=_PARTIAL_RESP)

    I.run_note_intake()

    owner_cards = list((tmp_path / "tracker").glob("owner-decision-*.md"))
    assert owner_cards, "unclear should create an owner-decision card"
    joined = "\n".join(c.read_text(encoding="utf-8") for c in owner_cards)
    assert _PARTIAL_RESP in joined, "PARTIAL hint must be in the owner-decision card body"
    assert any(_PARTIAL_RESP in n for n in notes), "owner's Telegram reply must carry the hint"


def test_new_verdict_adds_no_partial_hint(tmp_path, monkeypatch):
    """Guard: a NEW verdict must NOT stamp any spurious 'похоже на' hint."""
    path = Q.create_card(
        "inbox", "Совсем новая задача", body="Совсем новая задача",
        status="new", tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    notes = _wire(monkeypatch, tmp_path, card=card, kind="task", verdict="NEW")

    I.run_note_intake()

    assert "похоже на" not in path.read_text(encoding="utf-8").lower()
    assert not any("похоже на" in n.lower() for n in notes)
