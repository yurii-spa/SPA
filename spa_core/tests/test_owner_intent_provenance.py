"""S4 K1 · регрессия инцидента P0 (01.11): карточка с ``source: telegram|voice`` — НЕ намерение владельца.

Инцидент: фикстура ``test_inbox_intake`` попала в прод-трекер; перепись повторов назвала её «владелец
повторил просьбу», ложное основание доехало до приказа (G887 п. 7), а закрытие едва не отправило
владельцу «вот ответ на твою просьбу». Причина — правило «это задание владельца» судило по ОДНОМУ
полю ``source``, которое пишет любой вызывающий ``save_inbox_task``.

Правило теперь (E3.4): намерение владельца = канал владельца И автор, установленный проверяющим
входом (бот — ``router.is_owner`` по чату из Keychain; пульт — проверенный JWT). Ни поле, ни текст,
ни повтор намерения не доказывают — исход «происхождение не установлено».

Каждая сцена — через НАСТОЯЩИЕ двери: путь бота ``_handle_inbox_intake`` (``/task``), ``set_status``,
``sweep_notices``, шаг 0a ``check_owner_order_starvation.main``. Рабочий трекер недоступен:
``queue.TRACKER_DIR`` подменён на каталог теста, и это проверяется.
"""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import owner_repeat_census as census
from spa_core.owner_queue import answer_channel as ac
from spa_core.owner_queue import cockpit_loop as cl
from spa_core.owner_queue import queue as q
from spa_core.telegram import bot as B
from spa_core.telegram import inbox_intake as ii

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — repeated_requests(now=NOW), sweep_notices(now=NOW)
OWNER, STRANGER = "111", "999"
PHRASE = "купить зонт в пятницу"
_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    t = tmp_path / "nimbalyst-local" / "tracker"
    t.mkdir(parents=True)
    monkeypatch.setattr(q, "TRACKER_DIR", t)
    return t


def _bot(monkeypatch, sent):
    bot = B.TelegramBot.__new__(B.TelegramBot)
    monkeypatch.setattr(bot, "send_message", lambda text, chat_id=None, **kw: sent.append(text), raising=False)
    monkeypatch.setattr(bot, "_get_router",
                        lambda: type("R", (), {"is_owner": staticmethod(lambda c: str(c) == OWNER)})(),
                        raising=False)
    monkeypatch.setattr(bot, "_handle_long_document", lambda *a, **kw: False, raising=False)
    return bot


def _fm(path: Path) -> dict:
    return ac.split_frontmatter(path.read_text(encoding="utf-8"))[0]


def test_the_workspace_tracker_is_not_reachable(tracker):
    assert Path(q.TRACKER_DIR) == tracker
    assert ii.inbox_tracker_dir() == tracker
    assert "SPA_Claude" not in str(tracker)


def test_owner_chat_task_is_an_owner_intent(monkeypatch, tracker):
    sent: list = []
    msg = {"message_id": 1, "text": f"/task {PHRASE}", "chat": {"id": int(OWNER)}}
    assert _bot(monkeypatch, sent)._handle_inbox_intake(msg, msg["text"], OWNER) is True
    (card,) = list(tracker.glob("inbox-*.md"))
    fm = _fm(card)
    assert fm.get("author") == "owner" and fm.get("channel") == "telegram"
    assert ac.owner_intent(fm)[0] == ac.INTENT_OWNER


def test_a_stranger_creates_nothing(monkeypatch, tracker):
    sent: list = []
    msg = {"message_id": 2, "text": f"/task {PHRASE}", "chat": {"id": int(STRANGER)}}
    assert _bot(monkeypatch, sent)._handle_inbox_intake(msg, msg["text"], STRANGER) is False
    assert not list(tracker.glob("inbox-*.md"))


def test_fixture_with_owner_source_is_provenance_unknown(tracker):
    path, _ = ii.save_inbox_task(PHRASE, source="telegram")
    intent, why = ac.owner_intent(_fm(Path(path)))
    assert intent == ac.INTENT_UNKNOWN and "НЕ УСТАНОВЛЕНО" in why
    voice, _ = ii.save_inbox_task("проверь дашборд", source="voice", transcript="проверь дашборд на телефоне")
    assert ac.owner_intent(_fm(Path(voice)))[0] == ac.INTENT_UNKNOWN


def _close(path: Path, anchor: Path):
    q.set_status(path, "done", closed_by="test", evidence="test",
                 carried_to=str(anchor.relative_to(anchor.parents[2])), repo_root=anchor.parents[2])


def test_closing_a_fixture_queues_no_owner_notice_but_an_owner_task_does(monkeypatch, tracker, tmp_path):
    anchor = tracker / "inbox-anchor.md"
    anchor.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: якорь\nstatus: new\n---\n\nт\n", encoding="utf-8")
    fixture, _ = ii.save_inbox_task(PHRASE, source="telegram")
    sent: list = []
    msg = {"message_id": 3, "text": "/task проверь дашборд", "chat": {"id": int(OWNER)}}
    _bot(monkeypatch, sent)._handle_inbox_intake(msg, msg["text"], OWNER)
    owner_card = next(p for p in tracker.glob("inbox-*.md") if _fm(p).get("author") == "owner")
    for p in (Path(fixture), owner_card):
        _close(p, anchor)
    assert not str(_fm(Path(fixture)).get("owner_notice") or "")
    assert _fm(owner_card).get("owner_notice") == ac.ANSWER_PENDING
    out = tmp_path / "outbox.json"
    queued = cl.sweep_notices(tracker_dir=tracker, outbox_path=out, now=NOW)
    assert queued == [owner_card.name], "владельцу — только о его задании"


def _starvation():
    spec = importlib.util.spec_from_file_location("_starv", _REPO / "scripts" / "check_owner_order_starvation.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _step0a(t: Path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _starvation().main(["--tracker-dir", str(t), "--ref", "", "--no-write", "--json"])
    return rc, json.loads(buf.getvalue())


def test_repeated_fixtures_are_not_an_owner_repeat_in_the_real_step(tracker):
    for _ in range(2):
        ii.save_inbox_task(PHRASE, source="telegram", merge_open_twin=False)
    rc, doc = _step0a(tracker)
    assert doc["repeated_groups"] == 0 and rc == 0, "фикстура не есть «владелец повторил просьбу»"
    cards = q.list_cards(tracker_dir=tracker)
    assert len(census.unconfirmed_repeats(cards, now=NOW)) == 1, "неопределённость названа, а не потеряна"


def test_the_same_repeat_from_the_owner_chat_is_a_repeat(monkeypatch, tracker):
    sent: list = []
    bot = _bot(monkeypatch, sent)
    for i in range(2):
        monkeypatch.setattr(ii, "create_card", _no_twin(ii.create_card), raising=False)
        msg = {"message_id": 10 + i, "text": f"/task {PHRASE}", "chat": {"id": int(OWNER)}}
        bot._handle_inbox_intake(msg, msg["text"], OWNER)
    assert len(list(tracker.glob("inbox-*.md"))) == 2
    rc, doc = _step0a(tracker)
    assert doc["repeated_groups"] == 1 and rc == 3


def _no_twin(real):
    def _wrapped(*a, **kw):
        kw["merge_open_twin"] = False
        return real(*a, **kw)
    return _wrapped


def test_control_the_old_source_only_rule_would_call_fixtures_an_owner_repeat(monkeypatch, tracker):
    """Контроль в обратную сторону: вернуть правило «по полю source» — и шаг 0a снова назовёт
    фикстуры повтором владельца. Без этой сцены зелёный тест выше не отличал бы «правило работает»
    от «мера вообще ничего не находит»."""
    for _ in range(2):
        ii.save_inbox_task(PHRASE, source="telegram", merge_open_twin=False)
    monkeypatch.setattr(ac, "owner_intent",
                        lambda fm: (ac.INTENT_OWNER, "старое правило") if ac.is_owner_task(fm)
                        else (ac.INTENT_NONE, ""))
    rc, doc = _step0a(tracker)
    assert doc["repeated_groups"] == 1 and rc == 3
