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
    # ИЗМЕНЕНО 14.09 (ADR-375, инв. #16): предмет утверждения тот же — «задача ВСЁ ЖЕ
    # создана», — сменилось только ожидаемое состояние. С правилом машинной приёмки
    # приём больше не берёт задачу в работу: он её ПРИНИМАЕТ, а мерку объявляет тот,
    # кто возьмёт. `new` и значит «ещё ничья».
    assert Q.load_card(path).status == "new"                  # task still created
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
    # ИЗМЕНЕНО 14.09 (ADR-375, инв. #16): см. причину выше — приём оставляет задачу
    # в `new`. Утверждение УСИЛЕНО: проверяется не только статус, но и что ни одна
    # карточка не ушла из приёма молча (пустой список прошёл бы прежнюю проверку).
    assert paths, "сцена без карточек — проверка была бы вакуумной"
    assert all(Q.load_card(p).status == "new" for p in paths)


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
    # ADR-551: the agent closes an owner decision only on the owner's recorded answer — the
    # fixture plays the owner and records it first.
    _t = owner_cards[0].read_text(encoding="utf-8")
    owner_cards[0].write_text(_t.replace("\nstatus:", "\nowner_answer_via: test-fixture\nstatus:", 1), encoding="utf-8")
    Q.set_status(owner_cards[0], "done", closed_by="test", evidence="контроль #446")
    hit = exact_prior_ask(text, tracker_dir=tmp_path / "tracker")
    assert hit is not None and hit["status"] == "done", (
        "повтор дословного текста обязан находиться по записи, сделанной интейком")


# ── ARB 16.10: an accepted task is not re-processed every run; no «same or new?» question to the owner ──
# Measured: two intake runs after the 2026-10-15 reboot re-processed the same 28 `new` cards and sent
# 44–45 notices each, re-appending «Проверь: это то же самое или новое?» to the ARB card.

def test_second_run_does_not_reprocess_an_accepted_task(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Починить сторожа", body="Починить сторожа", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task",
                  verdict="PARTIAL", resp_h=_PARTIAL_RESP)
    first = I.run_note_intake()
    body1 = path.read_text(encoding="utf-8")
    assert Q.load_card(path).status == "new" and "intake_seen:" in body1
    n1 = len(notes)
    # the next run sees the card again (still `new`) — exactly the live situation
    monkeypatch.setattr(Q, "list_cards", lambda **k: [Q.load_card(path)])
    second = I.run_note_intake()
    assert Q.load_card(path).id in first["processed"] and second["processed"] == []
    assert len(notes) == n1, "no repeated «Создал задачу» notice"
    assert path.read_text(encoding="utf-8") == body1, "nothing appended twice"


def test_task_accepted_before_the_fix_is_recognised_by_the_intake_stamp(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Старая задача",
                         body="Старая задача\n\n## Как понять, что готово\nЗадача выполнена и проверена (детали — обычный цикл).\n",
                         status="new", tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task")
    res = I.run_note_intake()
    assert res["processed"] == [] and notes == []


def test_partial_hint_is_information_not_a_question_to_the_owner(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Похожая задача", body="Похожая задача", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task",
                  verdict="PARTIAL", resp_h="Пересекается с пакетом ADR-763.")
    I.run_note_intake()
    body = path.read_text(encoding="utf-8")
    assert "Проверь: это то же самое или новое?" not in body
    assert "владельцу этот вопрос не задаётся" in body
    assert all("проверь:" not in n.lower() for n in notes)
    assert any("отвечать не нужно" in n for n in notes)


# ── 16.10 crash-recovery: the intake stamp means «intake finished», never «task done». A crash between
# the linked work, the stamp and the Telegram notice must lose neither the card nor the notice, and a
# re-run must not duplicate linked work. Notices go through a durable outbox (data/intake_outbox.json)
# BEFORE the stamp; delivery is AT-LEAST-ONCE (a crash between a successful send and the outbox drop
# repeats the message), re-processing the same card does not add a second notice (key = card name).
# Each test below is red on origin 8f913113 (notice lost / second idea note / second owner card). ──
import json as _json
from datetime import datetime as _dt, timezone as _tz

import pytest as _pytest

_D1 = _dt(2026, 10, 16, 6, 0, tzinfo=_tz.utc)  # FROZEN-DATE-OK: injected-clock — passed as now= to run_note_intake
_D2 = _dt(2026, 10, 17, 6, 0, tzinfo=_tz.utc)  # FROZEN-DATE-OK: injected-clock — passed as now= to run_note_intake


class _Crash(BaseException):
    """A process death: not an ``Exception``, so the intake's per-card ``except`` cannot absorb it."""


def _live_list(path):
    """list_cards that honours ``status=`` like the real one (the next run must not see a done card)."""
    def _lc(**k):
        c = Q.load_card(path)
        return [c] if k.get("status") in (None, c.status) else []
    return _lc


def _outbox(tmp_path):
    p = tmp_path / "data" / "intake_outbox.json"
    return _json.loads(p.read_text(encoding="utf-8"))["pending"] if p.exists() else []


def _crash_once(monkeypatch, obj, name, *, before=True):
    real = getattr(obj, name)
    state = {"armed": True}

    def wrapped(*a, **k):
        if state["armed"]:
            state["armed"] = False
            if before:
                raise _Crash(name)
            out = real(*a, **k)
            raise _Crash(name)
        return real(*a, **k)
    monkeypatch.setattr(obj, name, wrapped)


def test_crash_after_stamp_before_notify_does_not_lose_the_notice(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Починить отчёт", body="Починить отчёт", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    _crash_once(monkeypatch, I, "_stamp_seen", before=False)      # stamp written, then the process dies
    with _pytest.raises(_Crash):
        I.run_note_intake(now=_D1)
    body1 = path.read_text(encoding="utf-8")
    assert "intake_seen:" in body1 and notes == []
    assert [e["key"] for e in _outbox(tmp_path)] == [path.name], "notice was not durably handed off before the stamp"
    second = I.run_note_intake(now=_D2)
    assert second["processed"] == []                               # the stamped card is not re-processed …
    assert len(notes) == 1 and "Создал задачу" in notes[0]         # … but its notice is delivered, once
    assert _outbox(tmp_path) == []
    assert path.read_text(encoding="utf-8") == body1               # nothing appended twice
    I.run_note_intake(now=_D2)
    assert len(notes) == 1                                         # delivered exactly once on the happy path


def test_crash_after_linked_work_before_stamp_keeps_card_and_notice(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Проверить сторожа", body="Проверить сторожа", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    _crash_once(monkeypatch, I, "_stamp_seen", before=True)       # criterion appended, no stamp yet
    with _pytest.raises(_Crash):
        I.run_note_intake(now=_D1)
    body1 = path.read_text(encoding="utf-8")
    assert "intake_seen:" not in body1                             # no stamp before hand-off completed
    assert Q.load_card(path).status == "new"                       # the card is not lost
    I.run_note_intake(now=_D2)
    assert len(notes) == 1 and "Создал задачу" in notes[0]
    assert path.read_text(encoding="utf-8").count("## Как понять, что готово") == 1


def test_failed_hand_off_writes_no_stamp_and_no_linked_work(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Задача без передачи", body="Задача без передачи", status="new",
                         tracker_dir=tmp_path / "tracker")
    before = path.read_text(encoding="utf-8")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    def _disk_full(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(I, "_outbox_save", _disk_full)
    res = I.run_note_intake(now=_D1)
    assert res["processed"] == [] and notes == []
    assert path.read_text(encoding="utf-8") == before              # stays `new`, untouched → next run retries


def test_idea_crash_before_close_rerun_next_day_writes_no_second_note(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Идея про сводку", body="Идея про сводку", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="idea")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    _crash_once(monkeypatch, Q, "set_status", before=True)        # note written + notice handed off, carrier open
    with _pytest.raises(_Crash):
        I.run_note_intake(now=_D1)
    assert Q.load_card(path).status == "new" and notes == []
    I.run_note_intake(now=_D2)
    ideas = sorted((tmp_path / "docs" / "ideas").glob("*.md"))
    assert len(ideas) == 1, f"second idea note on re-run: {[p.name for p in ideas]}"
    assert Q.load_card(path).status == "done"
    assert len(notes) == 1 and "Записал как идею" in notes[0]


def test_idea_crash_during_notify_delivers_on_next_run(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Идея про ленту", body="Идея про ленту", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="idea")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    def _dies(text, *a, **k):
        raise _Crash("notify")
    monkeypatch.setattr(I, "_notify", _dies)
    with _pytest.raises(_Crash):
        I.run_note_intake(now=_D1)
    assert Q.load_card(path).status == "done"                      # intake finished for the card …
    assert len(_outbox(tmp_path)) == 1                             # … and its notice survived the crash
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: notes.append(text))
    I.run_note_intake(now=_D2)
    assert len(notes) == 1 and "Записал как идею" in notes[0]
    assert len(list((tmp_path / "docs" / "ideas").glob("*.md"))) == 1


def test_unclear_crash_before_close_rerun_makes_no_second_owner_card(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Непонятная строка", body="ы-ы", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="unclear")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    monkeypatch.setattr(ask_router, "classify_and_answer", lambda body: ("unclear", "Это задача?"))
    _crash_once(monkeypatch, Q, "set_status", before=True)
    with _pytest.raises(_Crash):
        I.run_note_intake(now=_D1)
    # the classifier words its question differently on the re-run — still the same owner question
    monkeypatch.setattr(ask_router, "classify_and_answer", lambda body: ("unclear", "Это вопрос или задача?"))
    I.run_note_intake(now=_D2)
    owner_cards = list((tmp_path / "tracker").glob("owner-decision-*.md"))
    assert len(owner_cards) == 1, [p.name for p in owner_cards]
    assert Q.load_card(path).status == "done"
    assert len(notes) == 1 and notes[0].startswith("❓")


def test_undelivered_notice_stays_in_outbox_until_telegram_accepts(tmp_path, monkeypatch):
    path = Q.create_card("inbox", "Задача при лежащем Telegram", body="Задача при лежащем Telegram",
                         status="new", tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: False)  # bot down / flood guard dropped it
    I.run_note_intake(now=_D1)
    assert "intake_seen:" in path.read_text(encoding="utf-8") and len(_outbox(tmp_path)) == 1
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: notes.append(text))
    I.run_note_intake(now=_D2)
    I.run_note_intake(now=_D2)
    assert len(notes) == 1 and _outbox(tmp_path) == []


def test_crash_between_send_and_drop_repeats_the_notice_at_least_once(tmp_path, monkeypatch):
    """The stated semantics: at-least-once. Sent, then the process died before the outbox drop ⇒
    the next run sends it again (never zero times)."""
    path = Q.create_card("inbox", "Задача с повтором", body="Задача с повтором", status="new",
                         tracker_dir=tmp_path / "tracker")
    notes = _wire(monkeypatch, tmp_path, card=Q.load_card(path), kind="task")
    monkeypatch.setattr(Q, "list_cards", _live_list(path))
    _crash_once(monkeypatch, I, "_outbox_drop", before=True)
    with _pytest.raises(_Crash):
        I.run_note_intake(now=_D1)
    I.run_note_intake(now=_D2)
    assert len(notes) == 2 and notes[0] == notes[1]
    assert _outbox(tmp_path) == []


def test_unreadable_outbox_is_moved_aside_not_treated_as_empty_and_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_REPO", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "intake_outbox.json").write_text("{broken", encoding="utf-8")
    assert I._outbox_load() == []
    aside = list((tmp_path / "data").glob("intake_outbox.json.unreadable-*"))
    assert len(aside) == 1 and aside[0].read_text(encoding="utf-8") == "{broken"
