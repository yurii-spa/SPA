"""Origin закрыл карточку РАНЬШЕ нас — и это вечный ложный долг доставки.

# FROZEN-DATE-OK: injected-clock — часы в тестах ВХОД (`deliver(now=…)`,
# `trail_line(now=…)`), а литеральные отметки внутри байтов карточки
# воспроизводят конкретную аварию 2026-08-28 дословно: обе стороны закреплены,
# календарь на вердикт не влияет.

**Авария, которую повторяет каждый положительный контроль ниже (замер 28.08,
цикл #406, `data/findings_bridge_report.json` 23:30:19Z).**

    attempted: 5   delivered: []   rebase_refused: 5
    status: REFUSED · ДОЛГ ДОСТАВКИ: 5 карточк(и) НЕ на origin (старшему 4.25ч)

Все пять — `inbox-nahodka-petli-*`, и у всех пяти один и тот же текст отказа:
«на origin есть записи следа `status_trail`, которых нет в нашей копии — наш
след не дописан к чужому, а разошёлся с ним; перенос стёр бы чужой переход».

Отказ ВЕРЕН и здесь не ослаблен ни на йоту (обратные контроли ниже держат его в
обе стороны). Неверен был ВЫВОД, который из отказа делался: путь уходил в долг
доставки, а непустой долг по ADR-081 запрещает `IDLE` ⇒ обязательный шаг
0-офис печатал красную строку КАЖДЫЙ цикл. Между тем везти было нечего:

* на origin карточка уже несёт `status: done`;
* переход тот же — `new -> done`, записанный РАНЬШЕ (10:41Z) и другой сессией
  (`cycle-14899`), а наша запись (19:15Z, без ярлыка сессии) — повторное
  закрытие уже закрытой карточки;
* вне следа версия origin содержит всё наше и сверх того (`claimed_by` шага 0b
  и дописанный в тело разбор).

Доставка нашего следа добавила бы ВТОРУЮ запись об ОДНОМ переходе.

Сойтись копии не могут по построению: прод-дерево не синкает `nimbalyst-local/`
(CLAUDE.md §1), значит долг был вечным. Вечный ложный долг топит настоящий —
ровно та слепота, ради защиты от которой ADR-081 и заведён.

Пушер здесь ВСЕГДА инъектируется, и главное утверждение положительных контролей
двойное: исход стал `IDLE` **и** пушер не позван. По отдельности второе зелено и
на неисправленном модуле (там путь молчит по отказу) — тест, проверяющий только
его, был бы украшением.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

import pytest

from spa_core.monitoring import card_delivery as cd
from spa_core.owner_queue import status_audit


NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock
FIXED_NOW = dt.datetime(2026, 8, 27, 19, 15, 37, 183168, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock

CARD_NAME = "inbox-nahodka-petli-vozmozhnost-spark-susds-3-2.md"

_HEAD = """---
trackerStatus:
  type: inbox
title: "Находка петли: возможность spark_susds 3.8367% (evidence L4) доступна книге, не держи"
status: done
source: nimbalyst
created: 2026-08-27
finding_key: "gap:opportunity_unnamed:spark_susds"
"""

_BODY = """
Находка петли ADR-066 (house_view_gap, WARN, подтверждена 2 прогонами подряд):

возможность spark_susds 3.8367% (evidence L4) доступна книге, не держится и отказ НЕ назван.

_finding_key: `gap:opportunity_unnamed:spark_susds` · ADR-066_
"""

#: Прод-дерево: карточку закрыл мост в 19:15Z, ярлыка сессии в следе нет.
REAL_LOCAL = (
    _HEAD
    + "status_trail:\n"
      '  - "2026-08-27T19:15:37.183168+00:00 new -> done · queue.set_status"\n'
      "---\n"
    + _BODY
).encode("utf-8")

#: origin/main 88879f9c1: та же карточка, закрытая на 8.5 часов РАНЬШЕ другой
#: сессией, с захватом шага 0b и дописанным в тело разбором.
REAL_REMOTE = (
    _HEAD
    + "claimed_by: pid14899\n"
      "claimed_at: 2026-08-27T10:42:11Z\n"
      "status_trail:\n"
      '  - "2026-08-27T10:42:11.813292+00:00 new -> done · queue.set_status · cycle-14899"\n'
      "---\n"
    + _BODY
    + "\n---\n\n**Разобрано циклом #394 (2026-08-27). Находка оказалась ЛОЖНОЙ.**\n"
).encode("utf-8")


class _Pusher:
    """Инъектируемый пушер, который считает вызовы и НЕ ходит в сеть."""

    def __init__(self):
        self.calls = []

    def __call__(self, root, paths, message, allow_overwrite=False):
        self.calls.append({"paths": list(paths), "allow_overwrite": allow_overwrite})
        return 0, "ok"


def _remote(table):
    def reader(root, repo_path):
        value = table.get(os.path.basename(repo_path))
        if value is None:
            return cd.REMOTE_ABSENT, None, "на origin файла нет"
        return cd.REMOTE_PRESENT, value, ""
    return reader


def _run(tmp, local: bytes, remote: bytes, name: str = CARD_NAME):
    """Один прогон доставки в песочнице. Возвращает ``(квитанция, пушер, путь)``.

    Долг сеется НЕПУСТЫМ, ровно как в проде на момент аварии: иначе тест
    измерял бы «долг не появился», а не «вечный долг погашен».
    """
    root = os.path.realpath(tmp)
    tracker = os.path.join(root, cd.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    path = os.path.join(tracker, name)
    with open(path, "wb") as f:
        f.write(local)
    rel = os.path.join(cd.TRACKER_REL, name).replace(os.sep, "/")
    with open(os.path.join(root, cd.DEBT_REL), "w", encoding="utf-8") as f:
        json.dump({"generated_at": "2026-08-27T19:15:00+00:00", "adr": "ADR-081",
                   "debt": {rel: {"since": "2026-08-27T19:15:00+00:00", "attempts": 2,
                                  "last_status": cd.REFUSED,
                                  "last_reason": "след разошёлся"}}}, f)
    pusher = _Pusher()
    receipt = cd.deliver([], root=root, now=NOW, pusher=pusher,
                         reader=_remote({name: remote}), env={cd.ENV_FLAG: "1"})
    return receipt, pusher, path


def _closed_by_the_real_writer(status_to: str, *, status_from: str,
                               now: dt.datetime, session):
    """Карточка, закрытая ТЕМ ЖЕ кодом, что в проде (`status_audit.stamp_trail`)."""
    text = (_HEAD.replace("status: done", f"status: {status_to}") + "---\n" + _BODY)
    return status_audit.stamp_trail(text, old=status_from, new=status_to,
                                    source="queue.set_status", now=now,
                                    session=session).encode("utf-8")


# ── положительные контроли: авария 28.08 ─────────────────────────────────────

def test_real_stuck_card_of_2026_08_28_stops_owing():
    """ГЛАВНЫЙ контроль: раньше здесь был REFUSED и вечный долг 1."""
    with tempfile.TemporaryDirectory() as td:
        receipt, pusher, _path = _run(td, REAL_LOCAL, REAL_REMOTE)
    assert receipt["status"] == cd.IDLE, receipt["reason"]
    assert receipt["debt"]["count"] == 0
    # ДВА факта разом: исход стал IDLE И пушер молчал. Порознь второй зелен и
    # на неисправленном модуле — там путь молчит по отказу, а не по покрытию.
    assert pusher.calls == []


def test_the_card_lands_in_its_own_bucket_not_in_coverage():
    """Судьба общая, утверждения РАЗНЫЕ: там origin содержит наш след, здесь — нет."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher, _path = _run(td, REAL_LOCAL, REAL_REMOTE)
    assert [c["path"] for c in receipt["same_outcome_on_origin"]] == [
        f"{cd.TRACKER_REL.replace(os.sep, '/')}/{CARD_NAME}"]
    assert receipt["covered_by_origin"] == []
    assert receipt["already_on_origin"] == []
    assert receipt["rebase_refused"] == []


def test_the_reason_names_the_transition_and_who_recorded_it_first():
    """Отчёт обязан объяснять, а не просто молчать: иначе покрытие неотличимо от потери."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher, _path = _run(td, REAL_LOCAL, REAL_REMOTE)
    said = receipt["same_outcome_on_origin"][0]["reason"]
    assert "new -> done" in said
    assert "раньше" in said.lower()
    assert "нечего" in said


def test_office_step_reads_the_idle_reason_and_names_the_count():
    """Шаг 0-офис НАЗЫВАЕТ покрытие, а не проглатывает его в общее «везти нечего»."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher, _path = _run(td, REAL_LOCAL, REAL_REMOTE)
    assert "origin пришёл к тому же исходу раньше нас" in receipt["reason"]
    assert ": 1" in receipt["reason"]


def test_the_branch_leaves_our_copy_untouched():
    """Ветка ничего не пишет: ни на origin (пушер молчит), ни на диск."""
    with tempfile.TemporaryDirectory() as td:
        receipt, pusher, path = _run(td, REAL_LOCAL, REAL_REMOTE)
        with open(path, "rb") as f:
            after = f.read()
    assert receipt["status"] == cd.IDLE
    assert pusher.calls == []
    assert after == REAL_LOCAL


def test_the_real_writer_closing_twice_is_covered():
    """Тот же случай, но обе стороны закрывает НАСТОЯЩИЙ писатель, а не байты истории."""
    theirs = _closed_by_the_real_writer(
        "done", status_from="new", now=FIXED_NOW - dt.timedelta(hours=8),
        session="cycle-14899")
    ours = _closed_by_the_real_writer(
        "done", status_from="new", now=FIXED_NOW, session=None)
    assert ours != theirs
    covered, why = cd.origin_reached_same_outcome(ours, theirs)
    assert covered, why
    assert "new -> done" in why


def test_arrived_paths_counts_the_new_bucket():
    """«Доехало» — ОДНО определение на модуль: две копии списка разошлись бы молча."""
    receipt = {"attempted": ["a.md", "b.md"], "delivered": ["a.md"],
               "same_outcome_on_origin": [{"path": "b.md", "reason": "…"}]}
    assert cd.arrived_paths(receipt) == {"a.md", "b.md"}
    assert cd.owed_from_receipt(receipt) == []


# ── обратные контроли: отказ обязан остаться отказом ─────────────────────────
#
# Все они зелены и на неисправленном модуле, кроме тех, что зовут новую функцию
# по имени. Это объявлено, а не выдано за покрытие: их дело — доказать, что
# новая ветка НЕ стала дырой.

def test_rebase_still_refuses_the_very_same_pair():
    """ОБРАТНЫЙ КОНТРОЛЬ: сам перенос не ослаблен — он по-прежнему отказывает."""
    carried, why = cd.rebase_card(REAL_LOCAL, REAL_REMOTE)
    assert carried is None
    assert "status_trail" in why


def test_refuses_when_our_transition_is_not_recorded_on_origin():
    """Наш `in-progress -> done` при чужом `new -> done` — РАЗНЫЕ переходы, не отметки времени.

    Статус у обеих сторон ОДИН (`done`), тело и остальной frontmatter совпадают:
    иначе отказ дала бы проверка покрытия, и правило про стрелку осталось бы
    непроверенным — мутация «стрелка не сверяется» первую редакцию этого теста
    НЕ красила.
    """
    theirs = _closed_by_the_real_writer(
        "done", status_from="new", now=FIXED_NOW - dt.timedelta(hours=8),
        session="cycle-14899")
    ours = _closed_by_the_real_writer(
        "done", status_from="in-progress", now=FIXED_NOW, session=None)
    assert b"status: done" in ours and b"status: done" in theirs
    covered, _why = cd.origin_reached_same_outcome(ours, theirs)
    assert not covered


def test_refuses_when_origin_only_appended_to_our_trail():
    """ОБРАТНЫЙ КОНТРОЛЬ: наш след целиком у origin — это вопрос `covered_by_origin`.

    Своей записи, о которой можно было бы что-то утверждать, у нас тут нет.
    """
    ours = _closed_by_the_real_writer(
        "done", status_from="new", now=FIXED_NOW, session=None)
    theirs = status_audit.stamp_trail(
        ours.decode("utf-8"), old="done", new="ingested", source="queue.set_status",
        now=FIXED_NOW + dt.timedelta(hours=1), session="cycle-14899",
    ).replace("status: done", "status: ingested").encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(ours, theirs)
    assert not covered


def test_refuses_when_origin_holds_a_different_status():
    """origin вернул карточку владельцу — наш `status: done` в его копии не найдётся."""
    theirs = (_HEAD.replace("status: done", "status: needs-owner")
              + "owner_choice: \"вариант 2\"\n"
                "status_trail:\n"
                '  - "2026-08-27T10:42:11.813292+00:00 new -> done · queue.set_status · cycle-14899"\n'
                "---\n" + _BODY).encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(REAL_LOCAL, theirs)
    assert not covered


def test_refuses_when_our_body_carries_something_origin_lacks():
    """Наш неотправленный абзац — это груз; покрытием он не становится."""
    ours = REAL_LOCAL + "\n## Исполнено — цикл #406\n\nнаш отчёт\n".encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(ours, REAL_REMOTE)
    assert not covered


def test_refuses_when_origin_has_no_trail_at_all():
    """Пустой след origin ⇒ запись о переходе есть только у нас. Её и надо везти."""
    theirs = (_HEAD + "---\n" + _BODY).encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(REAL_LOCAL, theirs)
    assert not covered


def test_refuses_when_we_have_no_trail_at_all():
    """Карточка без следа переносится старым путём — сюда она попадать не должна."""
    ours = (_HEAD + "---\n" + _BODY).encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(ours, REAL_REMOTE)
    assert not covered


@pytest.mark.parametrize("broken", [
    '  - "мусор без стрелки"\n',
    '  - "2026-08-27T19:15:37.183168+00:00 new done"\n',
])
def test_unreadable_trail_line_refuses_instead_of_guessing(broken):
    """Неразобранная строка следа — отказ, а не пропуск: выдуманный переход тут дорог."""
    ours = (_HEAD + "status_trail:\n" + broken + "---\n" + _BODY).encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(ours, REAL_REMOTE)
    assert not covered
    theirs = (_HEAD + "claimed_by: pid14899\nstatus_trail:\n" + broken
              + "---\n" + _BODY).encode("utf-8")
    covered, _why = cd.origin_reached_same_outcome(REAL_LOCAL, theirs)
    assert not covered


def test_identical_trails_are_not_this_case():
    """Следы совпали — на этот вопрос отвечают ведра выше, не это."""
    covered, _why = cd.origin_reached_same_outcome(REAL_LOCAL, REAL_LOCAL)
    assert not covered


def test_not_a_card_refuses():
    """Без frontmatter судить не о чем — и догадка здесь стоила бы чужой правки."""
    junk = "просто текст".encode("utf-8")
    assert cd.origin_reached_same_outcome(junk, REAL_REMOTE)[0] is False
    assert cd.origin_reached_same_outcome(REAL_LOCAL, junk)[0] is False


# ── байтовые копии констант писателя пинятся к САМОМУ писателю ───────────────

def test_trail_separator_matches_the_writer():
    """`_TRAIL_SEP` — копия `status_audit.TRAIL_SEP`; расхождение молча слепит разбор."""
    assert cd._TRAIL_SEP == status_audit.TRAIL_SEP.encode("utf-8")


@pytest.mark.parametrize("session", [None, "cycle-14899"])
def test_trail_arrow_reads_what_the_real_writer_wrote(session):
    """Стрелка берётся из строки НАСТОЯЩЕГО писателя, а не из литерала по памяти."""
    line = status_audit.trail_line(old="new", new="done", source="queue.set_status",
                                   now=FIXED_NOW, session=session)
    assert cd.trail_arrow(f'  - "{line}"\n'.encode("utf-8")) == (b"new", b"done")


def test_trail_arrow_reads_a_missing_previous_status():
    """`(нет)` — законное значение `old` у писателя; разбор обязан его пережить."""
    line = status_audit.trail_line(old=None, new="new", source="queue.create",
                                   now=FIXED_NOW, session=None)
    old, new = cd.trail_arrow(f'  - "{line}"\n'.encode("utf-8"))
    assert old.decode("utf-8") == status_audit.MISSING_STATUS
    assert new == b"new"
