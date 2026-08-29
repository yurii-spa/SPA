"""Tests for the files-first owner-queue (ENV_SETUP_BRIEF_v3 · Этап 3)."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from datetime import datetime, timezone

from spa_core.owner_queue.queue import (
    OwnerDoneForbidden,
    create_card,
    ingest_notes,
    scan_promotion_mentions,
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
    # Readable filename from a transliterated Cyrillic title — no opaque timestamp, no 'note'
    # fallback (owner feedback inbox-task-readable-card-ids).
    assert p.name == "inbox-prover-dashbord-na-telefone.md"
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


def test_create_card_readable_slug_no_timestamp(tmp_path):
    # Russian title → readable transliterated slug; no 14-digit timestamp in the name.
    p = create_card("inbox", "Добавить кнопку наверх", tracker_dir=tmp_path)
    assert p.name == "inbox-dobavit-knopku-naverh.md"
    assert not re.search(r"\d{8}-\d{6}", p.name)


def test_create_card_collision_gets_readable_suffix(tmp_path):
    # Same title, РАЗНОЕ содержание → base name, then '-2', '-3' (readable, not a timestamp).
    #
    # ИЗМЕНЕНО НАМЕРЕННО 2026-08-09 (инв. #16): раньше три карточки создавались с ПУСТЫМ
    # телом, то есть были неотличимы. Теперь `create_card` идемпотентен по паре
    # (заголовок, тело) для ОТКРЫТЫХ карточек — это защита от потока одинаковых
    # уведомлений владельцу (замер 08–09.08: авторы плодили `-2`, `-3`… и каждая слала
    # своё сообщение). Смысл теста сохранён и УСИЛЕН: он по-прежнему пиннит читаемый
    # суффикс вместо таймстампа, но теперь на РЕАЛЬНОМ случае — разные карточки с
    # совпавшим заголовком, а не на трёх копиях одного вопроса.
    p1 = create_card("inbox", "Починить график", "первая находка", tracker_dir=tmp_path)
    p2 = create_card("inbox", "Починить график", "вторая находка", tracker_dir=tmp_path)
    p3 = create_card("inbox", "Починить график", "третья находка", tracker_dir=tmp_path)
    assert p1.name == "inbox-pochinit-grafik.md"
    assert p2.name == "inbox-pochinit-grafik-2.md"
    assert p3.name == "inbox-pochinit-grafik-3.md"


def test_slug_fallback_when_nothing_survives(tmp_path):
    # A title with no transliterable/ASCII content still yields a valid, unique name.
    p = create_card("inbox", "★☆✦", tracker_dir=tmp_path)
    assert p.name == "inbox-note.md"


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


# --------------------------------------------------- шаг 1б: метка или разговор О метке
#
# Положительный контроль аварии 2026-08-29: шапка-предупреждение, которую просят ставить
# в КАЖДУЮ идею, содержит `#promote` — и сканер назвал непромоутенную идею кандидатом.
# Строка, ЗАПРЕЩАЮЩАЯ действовать, стала поводом действовать; удар пришёлся ровно в
# инвариант протокола №3 и в сторону разрешения. Шапка ниже — дословно из
# docs/ideas/2026-08-29-cio-oversight-layer.md.

WARNING_HEADER = (
    "# Слой надзора CIO\n"
    "\n"
    "> **Идея, не инструкция.** Агенты по этому файлу не действуют без промоушена "
    "(владелец, `#promote`, CLAUDE.md §7.3)\n"
    "\n"
    "Хорошо бы свести ёмкость и решения в один слой.\n"
)


def test_promotions_reject_the_warning_header(tmp_path):
    """Шапка «не действовать без #promote» — НЕ промоушен (авария 2026-08-29).

    Честно про охват: эта строка защищена ДВУМЯ условиями сразу (цитата `>` И обратные
    кавычки), поэтому снятие любого ОДНОГО оставляет тест зелёным — условия заслоняют
    друг друга. Пооосевой контроль — `test_promotions_reject_quoted_fenced_and_indented_tags`,
    где каждый файл включает ровно одну ось. Здесь проверяется ИСХОД на настоящем тексте.
    """
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "cio.md").write_text(WARNING_HEADER, encoding="utf-8")

    assert scan_promotions(dirs=[ideas]) == []


def test_rejected_mention_is_named_not_swallowed(tmp_path):
    """Отказ обязан быть слышен: fail-CLOSED «нет» ≠ «ничего не нашли»."""
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "cio.md").write_text(WARNING_HEADER, encoding="utf-8")

    mentions = scan_promotion_mentions(dirs=[ideas])
    assert [m.path.name for m in mentions] == ["cio.md"]
    assert "#promote" in mentions[0].snippet


def test_promotions_reject_quoted_fenced_and_indented_tags(tmp_path):
    """Цитата, блок кода и отступ — разговор О метке во всех трёх формах."""
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "quoted.md").write_text("# Идея\n> ставьте #promote в заметку\n", encoding="utf-8")
    (ideas / "fenced.md").write_text("# Идея\n```\n#promote\n```\n", encoding="utf-8")
    (ideas / "indented.md").write_text("# Идея\n\n    grep -rl '#promote' docs/ideas\n", encoding="utf-8")
    (ideas / "inline.md").write_text("# Идея\nметка называется `#promote` и ставится владельцем\n",
                                     encoding="utf-8")

    assert scan_promotions(dirs=[ideas]) == []
    assert sorted(m.path.name for m in scan_promotion_mentions(dirs=[ideas])) == [
        "fenced.md", "indented.md", "inline.md", "quoted.md",
    ]


def test_promotions_accept_frontmatter_promote_true(tmp_path):
    """Оговорённое место: метку ОБЪЯВЛЯЮТ во frontmatter, а не выводят из текста."""
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "d.md").write_text(
        "---\ntitle: Идея\npromote: true\n---\n\n> тут даже цитата про `#promote` не мешает\n",
        encoding="utf-8",
    )

    proms = scan_promotions(dirs=[ideas])
    assert [p.path.name for p in proms] == ["d.md"]
    assert scan_promotion_mentions(dirs=[ideas]) == []


def test_promotions_accept_a_bare_tag_in_prose(tmp_path):
    """Обратный контроль: настоящая метка владельца распознаётся по-прежнему."""
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "e.md").write_text("# Идея\nдавай сделаем это #promote\n", encoding="utf-8")
    (ideas / "f.md").write_text("---\ntitle: Идея\n---\n\n#promote\n", encoding="utf-8")

    assert sorted(p.path.name for p in scan_promotions(dirs=[ideas])) == ["e.md", "f.md"]
