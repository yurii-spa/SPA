"""Tests for the files-first owner-queue (ENV_SETUP_BRIEF_v3 · Этап 3)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from datetime import datetime, timezone

from spa_core.owner_queue.queue import (
    OwnerDoneForbidden,
    create_card,
    ingest_notes,
    scan_promotions,
    first_instruction_line,
    list_cards,
    load_card,
    set_status,
)
from spa_core.owner_queue.notify import build_message


CARD = textwrap.dedent(
    """\
    ---
    trackerStatus:
      type: owner-decision
    title: Test card title
    status: needs-owner
    priority: high
    owner: someone@example.com
    legacy_id: Q-OWN-99
    ---

    ## Контекст
    Some context here.

    ## Инструкция владельцу
    1. Do the first concrete thing.
    2. Then the second.

    ## Критерий «сделано»
    It is done when X.
    """
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_card_parses_frontmatter(tmp_path):
    p = _write(tmp_path, "own-99.md", CARD)
    c = load_card(p)
    assert c.tracker_type == "owner-decision"
    assert c.title == "Test card title"
    assert c.status == "needs-owner"
    assert c.priority == "high"
    assert c.owner == "someone@example.com"
    assert c.legacy_id == "Q-OWN-99"
    assert c.id == "own-99"
    assert "## Контекст" in c.body


def test_list_cards_filters_by_type_and_status(tmp_path):
    _write(tmp_path, "own-1.md", CARD)
    _write(tmp_path, "own-2.md", CARD.replace("status: needs-owner", "status: owner-done"))
    _write(
        tmp_path,
        "inbox-1.md",
        CARD.replace("type: owner-decision", "type: inbox").replace("status: needs-owner", "status: to-do"),
    )
    assert len(list_cards(tracker_dir=tmp_path)) == 3
    assert len(list_cards(tracker_type="owner-decision", tracker_dir=tmp_path)) == 2
    assert len(list_cards(tracker_type="inbox", tracker_dir=tmp_path)) == 1
    done = list_cards(tracker_type="owner-decision", status="owner-done", tracker_dir=tmp_path)
    assert len(done) == 1 and done[0].id == "own-2"


def test_first_instruction_line_prefers_instruction_section(tmp_path):
    c = load_card(_write(tmp_path, "own-99.md", CARD))
    assert first_instruction_line(c) == "Do the first concrete thing."


def test_set_status_updates_only_status_line(tmp_path):
    p = _write(tmp_path, "own-99.md", CARD)
    set_status(p, "ingested")
    c = load_card(p)
    assert c.status == "ingested"
    # everything else preserved
    assert c.title == "Test card title"
    assert c.priority == "high"
    assert "Do the first concrete thing." in c.body
    # only one status line, and it is the new value
    assert p.read_text(encoding="utf-8").count("status: ingested") == 1
    assert "status: needs-owner" not in p.read_text(encoding="utf-8")


def test_set_status_refuses_owner_done(tmp_path):
    p = _write(tmp_path, "own-99.md", CARD)
    with pytest.raises(OwnerDoneForbidden):
        set_status(p, "owner-done")
    # file unchanged
    assert load_card(p).status == "needs-owner"


def test_build_message_is_html_safe_and_has_path(tmp_path):
    # underscores in a path must survive (HTML mode, not Markdown)
    p = _write(tmp_path, "own_weird_99.md", CARD)
    msg = build_message(load_card(p))
    assert "Test card title" in msg
    assert "Do the first concrete thing." in msg
    assert "own_weird_99.md" in msg
    assert "<b>" in msg  # HTML formatting present


def test_missing_dir_returns_empty(tmp_path):
    assert list_cards(tracker_dir=tmp_path / "does-not-exist") == []


def test_create_card_roundtrips(tmp_path):
    dt = datetime(2026, 7, 15, 13, 45, 0, tzinfo=timezone.utc)
    p = create_card(
        "inbox", "Проверь дашборд на телефоне", "Тело задания\nвторая строка",
        status="new", source="voice", extra_fields={"transcript": "raw text"},
        tracker_dir=tmp_path, now=dt,
    )
    assert p.exists()
    assert p.name.startswith("inbox-20260715-134500-")  # cyrillic title → slug 'note'
    c = load_card(p)
    assert c.tracker_type == "inbox"
    assert c.title == "Проверь дашборд на телефоне"
    assert c.status == "new"
    assert c.fields.get("source") == "voice"
    assert c.fields.get("created") == "2026-07-15"
    assert "Тело задания" in c.body
    # picked up by a type-filtered scan
    got = list_cards(tracker_type="inbox", status="new", tracker_dir=tmp_path)
    assert len(got) == 1 and got[0].id == p.stem


def test_create_card_refuses_owner_done(tmp_path):
    with pytest.raises(OwnerDoneForbidden):
        create_card("owner-decision", "x", status="owner-done", tracker_dir=tmp_path)


def test_create_card_title_with_yaml_chars_is_quoted(tmp_path):
    p = create_card("inbox", "fix: the API: broken #now", "body", tracker_dir=tmp_path)
    c = load_card(p)
    assert c.title == "fix: the API: broken #now"


def test_create_card_without_status_defaults_by_type(tmp_path):
    # No explicit status → must still be visible in a status-filtered scan (not dead-letter).
    p_own = create_card("owner-decision", "решение владельца", "тело", tracker_dir=tmp_path)
    assert load_card(p_own).status == "needs-owner"
    got = list_cards(tracker_type="owner-decision", status="needs-owner", tracker_dir=tmp_path)
    assert [c.id for c in got] == [p_own.stem]

    p_in = create_card("inbox", "задача", "тело", tracker_dir=tmp_path)
    assert load_card(p_in).status == "new"

    # Unknown tracker type falls back to "new", never blank.
    p_unk = create_card("mystery", "x", tracker_dir=tmp_path)
    assert load_card(p_unk).status == "new"


def test_create_card_always_emits_top_level_status_line(tmp_path):
    p = create_card("owner-decision", "нет статуса", "тело", tracker_dir=tmp_path)
    fm = p.read_text(encoding="utf-8").split("---")[1]
    assert any(ln.strip().startswith("status:") for ln in fm.splitlines())


def test_set_status_repairs_status_less_card(tmp_path):
    # Reproduce a legacy dead-letter card: valid frontmatter but NO status: line.
    card = tmp_path / "owner-decision-broken.md"
    card.write_text(
        textwrap.dedent(
            """\
            ---
            trackerStatus:
              type: owner-decision
            title: "сломанная карточка"
            source: telegram
            created: 2026-07-15
            ---

            body
            """
        ),
        encoding="utf-8",
    )
    # Invisible until repaired.
    assert load_card(card).status == ""
    assert list_cards(tracker_type="owner-decision", status="needs-owner", tracker_dir=tmp_path) == []

    set_status(card, "needs-owner")

    assert load_card(card).status == "needs-owner"
    got = list_cards(tracker_type="owner-decision", status="needs-owner", tracker_dir=tmp_path)
    assert [c.id for c in got] == ["owner-decision-broken"]
    # Repair must never smuggle in the owner-only status.
    with pytest.raises(OwnerDoneForbidden):
        set_status(card, "owner-done")


def test_ingest_notes(tmp_path):
    notes = tmp_path / "notes"
    track = tmp_path / "track"
    notes.mkdir()
    (notes / "README.md").write_text("readme", encoding="utf-8")
    (notes / "fix.md").write_text("Почини график\nвылезает за экран", encoding="utf-8")
    (notes / "empty.md").write_text("   \n", encoding="utf-8")  # ignored
    created = ingest_notes(notes_dir=notes, tracker_dir=track)
    assert len(created) == 1
    cards = list_cards(tracker_type="inbox", tracker_dir=track)
    assert len(cards) == 1 and cards[0].fields.get("source") == "obsidian"
    assert (notes / ".ingested" / "fix.md").exists()      # original archived
    assert (notes / "README.md").exists()                  # README untouched
    # idempotent: re-running finds nothing new
    assert ingest_notes(notes_dir=notes, tracker_dir=track) == []


def test_scan_promotions(tmp_path):
    ideas = tmp_path / "ideas"
    drafts = tmp_path / "rules-draft"
    ideas.mkdir()
    drafts.mkdir()
    (ideas / "README.md").write_text("readme #promote", encoding="utf-8")   # README skipped
    (ideas / "a.md").write_text("# Тёмная тема\nдобавить #promote пожалуйста", encoding="utf-8")
    (ideas / "b.md").write_text("просто идея без тега", encoding="utf-8")     # no tag
    (drafts / "c.md").write_text("правило про кэш\n#promoted-2026-07-01 уже сделано", encoding="utf-8")  # already promoted
    proms = scan_promotions(dirs=[ideas, drafts])
    assert len(proms) == 1
    assert proms[0].path.name == "a.md"
    assert proms[0].title == "Тёмная тема"
    assert "#promote" in proms[0].snippet
