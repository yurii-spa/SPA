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


# ── ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ: авария 11.08.2026 (упавший классификатор) ─────────
#
# Каждый тест ниже — воспроизведение НАСТОЯЩЕЙ аварии, а не гипотезы. 11.08 headless
# `claude` был недоступен; `classify_and_answer` вернул на вид обычный вердикт
# ("unclear", "Не смог обработать сообщение…"), интейк честно его исполнил и за день
# выпустил 44 карточки-вопроса владельцу (настоящих вопросов — 0), закрыв 44 исходных
# задания как `done` (28 из них на origin по сей день `new`).
#
# ВАЖНО — здесь ломается ПРОВОДКА, а не деталь: подменяется `subprocess.run` (то, что
# реально упало), а `classify_and_answer` работает НАСТОЯЩИЙ. Тест, подменяющий сам
# классификатор, зеленел бы и на дефекте — ровно так дефект и прожил два месяца.

def _wire_live_router(monkeypatch, tmp_path, cards, *, subprocess_run):
    """Как _wire, но БЕЗ подмены классификатора: падает нижний слой (subprocess)."""
    import subprocess as _sp

    notes: list[str] = []
    monkeypatch.setattr(I, "_REPO", tmp_path)
    monkeypatch.setattr(Q, "TRACKER_DIR", tmp_path / "tracker")
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: notes.append(text))
    monkeypatch.setattr(Q, "ingest_notes", lambda *a, **k: None)
    monkeypatch.setattr(Q, "list_cards", lambda **k: list(cards))
    monkeypatch.setattr(H, "history_check", lambda body: {"verdict": "NEW", "response": ""})
    monkeypatch.setattr(_sp, "run", subprocess_run)
    return notes


def _boom(*a, **k):
    raise OSError("no claude (авария 11.08)")


def _exit_nonzero(*a, **k):
    import types
    return types.SimpleNamespace(returncode=1, stdout="", stderr="rate limited")


def test_classifier_outage_creates_no_owner_question(tmp_path, monkeypatch):
    """Классификатор упал ⇒ вопрос владельцу НЕ рождается, исходник НЕ закрывается."""
    path = Q.create_card(
        "inbox", "ADR-070.2: канон трека коммитится циклом",
        body="ADR-070.2: канон трека коммитится циклом", status="new",
        tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    notes = _wire_live_router(monkeypatch, tmp_path, [card], subprocess_run=_boom)

    res = I.run_note_intake()

    owner_cards = list((tmp_path / "tracker").glob("owner-decision-*.md"))
    assert owner_cards == [], f"упавший классификатор породил вопрос владельцу: {owner_cards}"
    assert Q.load_card(path).status == "new", "исходное задание закрыто/сдвинуто при недоступном классификаторе"
    assert card.id in res["unavailable"]
    assert card.id not in res["processed"], "карточка не обработана — её нельзя считать обработанной"
    assert not any("Уточнение по заметке" in n for n in notes)


def test_classifier_nonzero_exit_creates_no_owner_question(tmp_path, monkeypatch):
    """Ненулевой код выхода `claude` (rate-limit) — тот же класс, тот же запрет."""
    path = Q.create_card(
        "inbox", "Tier-C: пять настоящих отказов агрегатора",
        body="Tier-C: пять настоящих отказов агрегатора", status="new",
        tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    _wire_live_router(monkeypatch, tmp_path, [card], subprocess_run=_exit_nonzero)

    res = I.run_note_intake()

    assert list((tmp_path / "tracker").glob("owner-decision-*.md")) == []
    assert Q.load_card(path).status == "new"
    assert res["unavailable"] == [card.id]


def test_classifier_outage_does_not_mass_produce_owner_questions(tmp_path, monkeypatch):
    """Массовый прогон 11.08 в миниатюре: N входящих ⇒ 0 вопросов, 0 закрытий, 1 сообщение."""
    paths = [
        Q.create_card("inbox", f"Задание {i}", body=f"Задание {i}", status="new",
                      tracker_dir=tmp_path / "tracker")
        for i in range(5)
    ]
    cards = [Q.load_card(p) for p in paths]
    notes = _wire_live_router(monkeypatch, tmp_path, cards, subprocess_run=_boom)

    res = I.run_note_intake()

    assert list((tmp_path / "tracker").glob("owner-decision-*.md")) == [], \
        "повторилась авария 11.08: недоступность классификатора превратилась в вопросы владельцу"
    assert [Q.load_card(p).status for p in paths] == ["new"] * 5
    assert len(res["unavailable"]) == 5
    # ровно ОДНО уведомление на прогон, а не по штуке на карточку (иначе это флуд)
    assert len(notes) == 1, f"ожидалось одно сводное сообщение, получено {len(notes)}: {notes}"
    assert "недоступен" in notes[0].lower()


def test_live_router_unclear_still_reaches_owner(tmp_path, monkeypatch):
    """Обратный контроль: ЖИВОЙ классификатор, сказавший UNCLEAR, по-прежнему спрашивает владельца.

    Без этого теста починку можно было бы «сдать», просто перестав создавать карточки
    вообще — то есть заглушив законный путь переспроса.
    """
    import types

    def _unclear(*a, **k):
        return types.SimpleNamespace(
            returncode=0, stdout="UNCLEAR\nЭто про сайт или про агентов?", stderr="")

    path = Q.create_card(
        "inbox", "Непонятное сообщение", body="ы", status="new",
        tracker_dir=tmp_path / "tracker",
    )
    card = Q.load_card(path)
    notes = _wire_live_router(monkeypatch, tmp_path, [card], subprocess_run=_unclear)

    res = I.run_note_intake()

    owner_cards = list((tmp_path / "tracker").glob("owner-decision-*.md"))
    assert len(owner_cards) == 1, "настоящее «непонятно» обязано дойти до владельца"
    assert "Это про сайт или про агентов?" in owner_cards[0].read_text(encoding="utf-8")
    assert Q.load_card(path).status == "done"
    assert res["unavailable"] == []
    assert any("вопрос" in n.lower() for n in notes)


# ── Флуд-предохранитель: большая очередь = ОДНА сводка, а не лента ────────────
#
# Побочный эффект починки аварии 11.08: в очередь честно вернулись 46 заданий, ранее
# закрытых упавшим классификатором. Прежний код отправил бы владельцу 46 сообщений
# подряд. Это не «много информации» — это потеря сигнала: среди 46 «создал задачу»
# тревогу о стоп-кране никто не прочитает. Штатные 1–2 входящих приходят как прежде.

def test_small_batch_still_sends_individual_replies(tmp_path, monkeypatch):
    """Регресс-страховка: обычный прогон (1 карточка) — прежний отдельный ответ."""
    path = Q.create_card("inbox", "Одна задача", body="Одна задача", status="new",
                         tracker_dir=tmp_path / "tracker")
    card = Q.load_card(path)
    notes = _wire(monkeypatch, tmp_path, card=card, kind="task")

    I.run_note_intake()

    assert len(notes) == 1
    assert "Одна задача" in notes[0]
    assert "сводкой" not in notes[0]


def test_large_batch_collapses_into_one_summary(tmp_path, monkeypatch):
    """Разбор накопившейся очереди уходит владельцу ОДНИМ сообщением."""
    paths = [Q.create_card("inbox", f"Задача {i}", body=f"Задача {i}", status="new",
                           tracker_dir=tmp_path / "tracker") for i in range(12)]
    cards = [Q.load_card(p) for p in paths]
    notes: list[str] = []
    monkeypatch.setattr(I, "_REPO", tmp_path)
    monkeypatch.setattr(Q, "TRACKER_DIR", tmp_path / "tracker")
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: notes.append(text))
    monkeypatch.setattr(Q, "ingest_notes", lambda *a, **k: None)
    monkeypatch.setattr(Q, "list_cards", lambda **k: list(cards))
    monkeypatch.setattr(H, "history_check", lambda body: {"verdict": "NEW", "response": ""})
    monkeypatch.setattr(ask_router, "classify_and_answer", lambda body: ("task", ""))

    res = I.run_note_intake()

    assert len(notes) == 1, f"владелец получил {len(notes)} сообщений вместо одной сводки"
    assert "12" in notes[0], "сводка обязана назвать ЧИСЛО разобранных, иначе она бесполезна"
    assert "Задача 0" in notes[0], "в сводке должны быть видны первые заголовки"
    assert "Задача 11" not in notes[0], "сводка не должна выродиться в ту же ленту"
    assert len(res["processed"]) == 12, "сводка не должна отменять саму обработку"
    assert all(Q.load_card(p).status == "in-progress" for p in paths)


def test_unclear_card_records_the_source_text_readably(tmp_path, monkeypatch):
    """Круг замкнут: то, что интейк ЗАПИСАЛ, следующий заход обязан ПРОЧИТАТЬ.

    Положительный контроль к циклу #446. Детерминированная сверка «этот текст уже
    становился вопросом» стоит на дословной записи исходного текста в теле карточки.
    Обе половины — писатель (интейк) и читатель (`recorded_source_text`) — верны
    поодиночке и бесполезны порознь: смени интейк форму записи, и сверка молча
    перестанет находить что-либо ВООБЩЕ, не покраснев ни одним тестом.
    """
    from spa_core.owner_queue.history_check import exact_prior_ask, recorded_source_text

    text = ("## Задание (из Telegram)\n\n"
            "По двум чистым снимкам подряд (решение владельца 2026-08-07, ADR-070 п.13)")
    path = Q.create_card("inbox", "ADR-070.13", body=text, status="new",
                         tracker_dir=tmp_path / "tracker")
    card = Q.load_card(path)
    _wire(monkeypatch, tmp_path, card=card, kind="unclear")

    I.run_note_intake()

    owner_cards = [p for p in (tmp_path / "tracker").glob("owner-decision-*.md")]
    assert owner_cards, "unclear обязан завести карточку владельцу"
    body = Q.load_card(owner_cards[0]).body
    assert recorded_source_text(body) == text, (
        "читатель обязан достать РОВНО тот текст, который записал интейк")

    # …и тот же текст, придя снова после закрытия карточки, обязан быть узнан повтором.
    # `_wire` подменяет `list_cards` одной карточкой — снимаем подмену, иначе сверка
    # смотрела бы в харнесс, а не в трекер (сторож судил бы не тот предмет).
    monkeypatch.undo()
    Q.set_status(owner_cards[0], "done", closed_by="test", evidence="контроль #446")
    hit = exact_prior_ask(text, tracker_dir=tmp_path / "tracker")
    assert hit is not None and hit["status"] == "done", (
        "повтор дословного текста обязан находиться по записи, сделанной интейком")
