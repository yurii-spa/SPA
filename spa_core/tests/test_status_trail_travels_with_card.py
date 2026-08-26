"""След перехода едет ВМЕСТЕ с карточкой — воспроизведение замера 17.08 в обе стороны.

Решение владельца 2026-08-23, вариант 1 (карточка
`owner-decision-zakrytie-voprosa-vladeltsa-iz-rabochego`, ADR-129).

Авария, которую эти тесты воспроизводят дословно (замер 17.08, карточка):
дерево A закрывает вопрос владельца через наш же API (`orchestrator_queue.set_status`),
git довозит в дерево B ТОЛЬКО карточку — журнал аудита в `data/` в git не попадает
(`.gitignore`: `data/**/*.jsonl`), — и сторож в дереве B печатает
`CRITICAL: неатрибутированный уход из needs-owner`, то есть «вопрос владельца закрыли
без владельца». Протокол §3.4 требует работать именно из отдельного дерева, поэтому
тревога звучала бы КАЖДЫЙ раз.

Обе стороны обязательны, иначе починка была бы просто ослаблением сторожа:

* `test_delivered_card_is_attributed_by_its_trail` — законная доставка ТИХАЯ;
* `test_silent_hand_edit_is_still_critical` — молчаливая правка `status:` руками
  по-прежнему **CRITICAL** (в ней следа нет).

А `test_forged_trail_is_named_in_the_docstring` держит честность границы: подделку
следа файловый сторож не различает, и это сказано вслух, а не забыто.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import tracker_status_sentinel as sentinel
from spa_core.owner_queue import queue as q
from spa_core.owner_queue import status_audit as sa

CARD = "owner-decision-probe-c360.md"

CARD_TEXT = """---
trackerStatus:
  type: owner-decision
title: "Пробная карточка цикла #360"
status: needs-owner
source: nimbalyst
created: 2026-08-23
---

## Что случилось и почему это важно

Тело карточки для воспроизведения замера 17.08.
"""


def _tree(root: Path) -> Path:
    """Рабочее дерево-заглушка: `.git` (корень опознаётся) + трекер + `data/`."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / sentinel.TRACKER_REL).mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    return root


def _card(root: Path) -> Path:
    return root / sentinel.TRACKER_REL / CARD


def _first_run(root: Path, when: dt.datetime) -> dict:
    """Первый прогон сторожа: он и создаёт снимок, с которым сверяется второй."""
    return sentinel.run(root=root, now=when, write=True)


@pytest.fixture()
def trees(tmp_path):
    """Дерево A (работает) и дерево B (прод, куда git довозит только карточку)."""
    a = _tree(tmp_path / "tree_a")
    b = _tree(tmp_path / "tree_b")
    _card(a).write_text(CARD_TEXT, encoding="utf-8")
    _card(b).write_text(CARD_TEXT, encoding="utf-8")
    return a, b


def _deliver(a: Path, b: Path) -> None:
    """То, что делает git: везёт КАРТОЧКУ и не везёт журнал из `data/`."""
    _card(b).write_text(_card(a).read_text(encoding="utf-8"), encoding="utf-8")


# ---------------------------------------------------------------- предпосылка

def test_audit_journal_does_not_travel(trees, monkeypatch):
    """Премиса аварии: журнал остаётся в дереве A. Умрёт она — умрут и оба теста ниже."""
    a, b = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    q.set_status(_card(a), "ingested")
    _deliver(a, b)
    assert (a / sa.AUDIT_REL).is_file(), "в дереве A запись обязана быть"
    assert not (b / sa.AUDIT_REL).exists(), "в дерево B журнал не едет — это и есть беда"


# ------------------------------------------------- сторона 1: законная доставка

def test_delivered_card_is_attributed_by_its_trail(trees, monkeypatch):
    """Законное закрытие из дерева A приезжает в прод ОБЪЯСНЁННЫМ, а не CRITICAL."""
    a, b = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    t0 = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.timezone.utc)
    _first_run(b, t0)                                  # прод снял базовый снимок

    q.set_status(_card(a), "ingested")
    _deliver(a, b)

    report = sentinel.run(root=b, now=t0 + dt.timedelta(hours=1), write=False)
    assert report["critical"] == 0, report["unattributed"]
    assert report["verdict"] == sentinel.VERDICT_OK, report
    assert sentinel.exit_code(report) == 0
    (attributed,) = report["attributed"]
    assert attributed["reason"] == "card_trail"
    assert attributed["from"] == "needs-owner" and attributed["to"] == "ingested"
    assert "queue.set_status" in attributed["writer"]
    assert "cycle-probe" in attributed["writer"], "ярлык сессии обязан быть виден"


def test_trail_survives_a_late_delivery(trees, monkeypatch):
    """Карточка может приехать через СУТКИ — след обязан работать и тогда.

    Именно поэтому у следа НЕТ временного окна (у журнала оно есть). Требовать окна
    значило бы вернуть ложную тревогу для всякой неспешной доставки.
    """
    a, b = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    q.set_status(_card(a), "ingested")                 # переход СЕГОДНЯ
    t0 = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)   # снимок прода — позже
    _first_run(b, t0)
    _deliver(a, b)
    report = sentinel.run(root=b, now=t0 + dt.timedelta(hours=1), write=False)
    assert report["critical"] == 0, report["unattributed"]
    assert report["attributed"][0]["reason"] == "card_trail"
    assert report["attributed"][0]["trail_ts"], "возраст следа обязан быть НАЗВАН"


# --------------------------------------- сторона 2: немой писатель по-прежнему CRITICAL

def test_silent_hand_edit_is_still_critical(trees):
    """Правка `status:` руками мимо нашего кода — следа нет, тревога остаётся."""
    a, b = trees
    t0 = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.timezone.utc)
    _first_run(b, t0)
    _card(b).write_text(CARD_TEXT.replace("status: needs-owner", "status: ingested"),
                        encoding="utf-8")
    report = sentinel.run(root=b, now=t0 + dt.timedelta(hours=1), write=False)
    assert report["critical"] == 1, report
    (finding,) = report["unattributed"]
    assert finding["severity"] == "CRITICAL"
    assert finding["reason"] == "no_record"
    assert sentinel.exit_code(report) == 2


def test_trail_about_another_transition_does_not_excuse_this_one(trees, monkeypatch):
    """Чужой переход в следе — не индульгенция: цепочка обязана СОЙТИСЬ.

    Обратный контроль сужения: без него «след есть» означало бы «всё объяснено»,
    и сторож стал бы зелёным от любой записи в карточке.
    """
    a, b = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    t0 = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.timezone.utc)
    _first_run(b, t0)
    # В следе — законный переход needs-owner -> in-progress …
    q.set_status(_card(a), "in-progress")
    delivered = _card(a).read_text(encoding="utf-8")
    # … а в самой карточке кто-то дописал руками совсем другой статус.
    _card(b).write_text(delivered.replace("status: in-progress", "status: ingested"),
                        encoding="utf-8")
    report = sentinel.run(root=b, now=t0 + dt.timedelta(hours=1), write=False)
    assert report["critical"] == 1, report
    assert report["unattributed"][0]["reason"] == "no_record"


# ---------------------------------------------------------------- форма следа

def test_trail_carries_no_host_identity(trees, monkeypatch):
    """Владелец отказался от варианта 2 ИЗ-ЗА pid/путей/команд в репозитории.

    Значит их не должно быть и здесь, иначе выбран был бы вариант 2 задним числом.
    """
    a, _ = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    q.set_status(_card(a), "ingested")
    (entry,) = sa.read_trail(_card(a).read_text(encoding="utf-8"))
    raw = entry["raw"]
    assert str(a) not in raw and "/" not in raw.split(" · ")[-1]
    assert "pid" not in raw.lower()
    assert "python" not in raw.lower()


def test_trail_is_capped_and_keeps_the_latest(trees, monkeypatch):
    """Карточка живёт месяцами: неограниченный след превратил бы её в журнал."""
    a, _ = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    for i in range(sa.TRAIL_CAP + 4):
        q.set_status(_card(a), "in-progress" if i % 2 == 0 else "new")
    trail = sa.read_trail(_card(a).read_text(encoding="utf-8"))
    assert len(trail) == sa.TRAIL_CAP
    assert trail[-1]["new"] == "new"


def test_body_is_preserved_byte_for_byte(trees, monkeypatch):
    """Тело карточки — текст ВЛАДЕЛЬЦУ. След не имеет права его тронуть."""
    a, _ = trees
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-probe")
    body_before = CARD_TEXT.split("---", 2)[2]
    q.set_status(_card(a), "ingested")
    assert _card(a).read_text(encoding="utf-8").split("---", 2)[2] == body_before


def test_owner_only_status_is_still_refused(trees):
    """След не приоткрыл инвариант #14: агент по-прежнему не ставит owner-done."""
    a, _ = trees
    with pytest.raises(q.OwnerDoneForbidden):
        q.set_status(_card(a), "owner-done")
    assert sa.read_trail(_card(a).read_text(encoding="utf-8")) == [], (
        "отказ не имеет права оставить след — иначе он врал бы о переходе"
    )


def test_card_without_frontmatter_does_not_lose_the_status_write():
    """Некуда писать след — работа важнее следа (переход останется необъяснённым)."""
    text = "просто текст без frontmatter\n"
    assert sa.stamp_trail(text, old=None, new="ingested",
                          source="queue.set_status") == text


def test_forged_trail_is_named_in_the_docstring():
    """Граница механизма записана там, где её прочитают, — иначе она забудется."""
    doc = sentinel.__doc__ or ""
    assert "подделки" in doc or "подделк" in doc, doc[:200]
