"""Tests for Telegram→Inbox intake (ENV_SETUP_BRIEF_v3 · Этап 6).

The heavy offline whisper path is verified end-to-end manually (say→opus→turbo);
these unit tests cover the pure text/card logic without loading a model.
"""

from __future__ import annotations

from spa_core.telegram import inbox_intake
from spa_core.owner_queue.queue import load_card, list_cards


def test_title_from_text_first_nonempty_line():
    assert inbox_intake._title_from_text("\n\n купить зонт \nвторая строка") == "купить зонт"
    assert inbox_intake._title_from_text("") == "Задание из Telegram"
    long = "x" * 200
    assert inbox_intake._title_from_text(long).endswith("…")


def test_save_inbox_task_text(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_intake, "create_card", _card_into(tmp_path))
    path, title = inbox_intake.save_inbox_task("купить зонт в пятницу", source="telegram")
    assert title == "купить зонт в пятницу"
    c = load_card(path)
    assert c.tracker_type == "inbox"
    assert c.status == "new"
    assert c.fields.get("source") == "telegram"
    assert "купить зонт" in c.body
    assert "Расшифровка" not in c.body  # no transcript for a text task


def test_save_inbox_task_voice_includes_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_intake, "create_card", _card_into(tmp_path))
    path, _title = inbox_intake.save_inbox_task(
        "проверь дашборд", source="voice", transcript="проверь дашборд на телефоне")
    c = load_card(path)
    assert c.fields.get("source") == "voice"
    assert "Расшифровка голосового" in c.body
    assert "на телефоне" in c.body


def _card_into(tmp_path):
    """Wrap create_card to force the tracker_dir into tmp_path (isolates the test)."""
    from spa_core.owner_queue.queue import create_card as _real

    def _wrapped(*args, **kwargs):
        kwargs.setdefault("tracker_dir", tmp_path)
        return _real(*args, **kwargs)

    return _wrapped
