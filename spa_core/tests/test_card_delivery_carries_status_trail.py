"""Перенос правки карточки на свежий origin обязан везти И след перехода.

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД (``trail_line(now=…)``), а
# литеральные отметки внутри байтов карточки воспроизводят конкретную аварию
# 2026-08-27 дословно; обе стороны закреплены, календарь на вердикт не влияет.

**Авария, которую повторяет каждый тест ниже (замер 27.08, цикл #394).**
``card_delivery.rebase_card`` держался на посылке «правка моста над существующей
карточкой — это РОВНО одна строка ``status:``». Посылка перестала быть верной в
день, когда след перехода поехал ВМЕСТЕ с карточкой (решение владельца, вариант 1):
``owner_queue.queue.set_status`` пишет ``status:`` и блок ``status_trail:`` одной
записью. С тех пор ЛЮБОЕ закрытие карточки, сделанное штатным писателем, переносу
не поддавалось: карточка ``inbox-nahodka-petli-vozmozhnost-fluid-fusdc-5-2``
получила отказ «расхождение … не сводится к одной строке status:» шесть прогонов
подряд, а шаг 0-офис каждый цикл печатал «ДОЛГ ДОСТАВКИ: 1 карточк(и) НЕ на origin».

Отказ был честен по своему контракту и отвечал не на тот вопрос — тот самый класс,
ради которого сторожей и разделяют. Поэтому здесь проверяется не «функция что-то
вернула», а ОБЕ стороны: правка штатного писателя переносится, а всякое ДРУГОЕ
расхождение с origin по-прежнему получает отказ.
"""

import datetime as dt

import pytest

from spa_core.monitoring import card_delivery as cd
from spa_core.owner_queue import status_audit


FIXED_NOW = dt.datetime(2026, 8, 27, 1, 14, 16, 421559, tzinfo=dt.timezone.utc)

# Байты карточки с origin ДО правки — дословно ``6145ccca6^`` пути
# nimbalyst-local/tracker/inbox-nahodka-petli-vozmozhnost-fluid-fusdc-5-2.md.
REAL_REMOTE = b"""---
trackerStatus:
  type: inbox
title: "\xd0\x9d\xd0\xb0\xd1\x85\xd0\xbe\xd0\xb4\xd0\xba\xd0\xb0 \xd0\xbf\xd0\xb5\xd1\x82\xd0\xbb\xd0\xb8"
status: new
source: nimbalyst
created: 2026-08-26
finding_key: "gap:opportunity_unnamed:fluid_fusdc"
---

\xd0\xa2\xd0\xb5\xd0\xbb\xd0\xbe \xd0\xba\xd0\xb0\xd1\x80\xd1\x82\xd0\xbe\xd1\x87\xd0\xba\xd0\xb8.

_finding_key: `gap:opportunity_unnamed:fluid_fusdc` \xc2\xb7 ADR-066_
"""

# Та же карточка после ``queue.set_status(..., "done")`` — ровно то, что лежало в
# прод-дереве и шесть раз получало отказ переноса.
REAL_LOCAL = REAL_REMOTE.replace(b"status: new\n", b"status: done\n").replace(
    b'finding_key: "gap:opportunity_unnamed:fluid_fusdc"\n',
    b'finding_key: "gap:opportunity_unnamed:fluid_fusdc"\n'
    b"status_trail:\n"
    b'  - "2026-08-27T01:14:16.421559+00:00 new -> done \xc2\xb7 queue.set_status"\n',
)


def _card(status: str) -> str:
    return (
        "---\n"
        "trackerStatus:\n"
        "  type: inbox\n"
        'title: "Находка"\n'
        f"status: {status}\n"
        "source: nimbalyst\n"
        "---\n"
        "\n"
        "Тело.\n"
    )


def _closed_by_the_real_writer(status_from: str, status_to: str,
                               now: dt.datetime = FIXED_NOW) -> bytes:
    """Карточка, закрытая ТЕМ ЖЕ кодом, что в проде (``status_audit.stamp_trail``)."""
    text = _card(status_to)
    return status_audit.stamp_trail(text, old=status_from, new=status_to,
                                    source="queue.set_status", now=now,
                                    session=None).encode("utf-8")


# ── положительные контроли: авария 27.08 ────────────────────────────────────

def test_real_stuck_card_of_2026_08_27_now_carries():
    """Дословные байты застрявшей карточки переносятся, и результат — НАШ файл."""
    carried, why = cd.rebase_card(REAL_LOCAL, REAL_REMOTE)
    assert carried is not None, f"перенос отказал: {why}"
    assert why == ""
    assert carried == REAL_LOCAL


def test_real_stuck_card_keeps_the_trail_entry():
    """След не теряется по дороге — иначе сторож переходов назовёт его чужим."""
    carried, _why = cd.rebase_card(REAL_LOCAL, REAL_REMOTE)
    trail = status_audit.read_trail(carried.decode("utf-8"))
    assert [(t["old"], t["new"], t["source"]) for t in trail] == [
        ("new", "done", "queue.set_status")]


def test_edit_of_the_real_writer_carries():
    """Тот же контроль, но карточку закрывает НАСТОЯЩИЙ писатель, а не байты из истории."""
    remote = _card("new").encode("utf-8")
    local = _closed_by_the_real_writer("new", "done")
    assert local != remote
    carried, why = cd.rebase_card(local, remote)
    assert carried is not None, f"перенос отказал: {why}"
    assert carried == local


def test_second_transition_carries_over_a_trail_origin_already_has():
    """origin уже видел первый переход; мы дописали второй — переносится дописанное."""
    remote = _closed_by_the_real_writer("new", "in-progress")
    local_text = status_audit.stamp_trail(
        remote.decode("utf-8").replace("status: in-progress", "status: done"),
        old="in-progress", new="done", source="queue.set_status",
        now=FIXED_NOW + dt.timedelta(hours=1), session=None)
    local = local_text.encode("utf-8")
    carried, why = cd.rebase_card(local, remote)
    assert carried is not None, f"перенос отказал: {why}"
    assert carried == local
    assert len(status_audit.read_trail(carried.decode("utf-8"))) == 2


# ── обратные контроли: отказ обязан остаться отказом ────────────────────────

def test_refuses_when_origin_holds_a_trail_entry_we_never_saw():
    """origin ушёл вперёд по следу ⇒ наш след стёр бы чужой переход. Отказ."""
    ours = _closed_by_the_real_writer("new", "done")
    theirs_text = status_audit.stamp_trail(
        _card("in-progress"), old="new", new="in-progress",
        source="queue.set_status", now=FIXED_NOW - dt.timedelta(hours=2), session=None)
    theirs = status_audit.stamp_trail(
        theirs_text.replace("status: in-progress", "status: blocked"),
        old="in-progress", new="blocked", source="queue.set_status",
        now=FIXED_NOW - dt.timedelta(hours=1), session=None).encode("utf-8")
    carried, why = cd.rebase_card(ours, theirs)
    assert carried is None
    assert "status_trail" in why and "стёр" in why


def test_refuses_when_origin_gained_a_field_we_never_saw():
    """Прежний отказ цел: на origin поле, которого мы не видели."""
    remote = _card("new").replace("source: nimbalyst\n",
                                  "source: nimbalyst\npriority: high\n").encode("utf-8")
    local = _closed_by_the_real_writer("new", "done")
    carried, why = cd.rebase_card(local, remote)
    assert carried is None
    assert "status_trail" in why


def test_refuses_when_origin_shows_the_card_was_already_seen():
    """Захват/ответ владельца на origin — закрытие отменяется, как и раньше."""
    remote = _card("new").replace("source: nimbalyst\n",
                                  "source: nimbalyst\nclaimed_by: pid999\n").encode("utf-8")
    local = _closed_by_the_real_writer("new", "done")
    carried, why = cd.rebase_card(local, remote)
    assert carried is None
    assert "claimed_by" in why


def test_card_without_a_trail_still_carries_the_old_way():
    """Карточка без следа обязана переноситься ровно как до починки."""
    remote = _card("new").encode("utf-8")
    local = _card("done").encode("utf-8")
    carried, why = cd.rebase_card(local, remote)
    assert carried is not None, f"перенос отказал: {why}"
    assert carried == local


def test_body_divergence_still_refuses():
    """Тело разошлось — переносить нельзя ни при каком следе."""
    remote = _card("new").replace("Тело.", "Другое тело.").encode("utf-8")
    local = _closed_by_the_real_writer("new", "done")
    carried, why = cd.rebase_card(local, remote)
    assert carried is None


# ── страж самой починки ─────────────────────────────────────────────────────

def test_trail_key_matches_the_writer():
    """Байтовая копия ключа не смеет разойтись с писателем следа."""
    assert cd._TRAIL_KEY.decode("utf-8") == status_audit.TRAIL_KEY


@pytest.mark.parametrize("indent", [b"  ", b"\t"])
def test_split_trail_block_takes_the_key_and_its_items(indent):
    fm = (b"status: done\n" + cd._TRAIL_KEY + b":\n" + indent + b'- "a"\n'
          + indent + b'- "b"\n' + b"source: nimbalyst\n")
    rest, block = cd.split_trail_block(fm)
    assert rest == b"status: done\nsource: nimbalyst\n"
    assert block == cd._TRAIL_KEY + b":\n" + indent + b'- "a"\n' + indent + b'- "b"\n'


def test_split_trail_block_is_a_no_op_without_a_trail():
    fm = b"status: done\nsource: nimbalyst\n"
    assert cd.split_trail_block(fm) == (fm, b"")
