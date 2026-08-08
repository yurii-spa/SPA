"""Запасной ключ владельца к защите сайта: обход `Owner-Approved: own-NN`.

Решение владельца 2026-08-08, вариант А карточки
`owner-decision-zapasnoi-klyuch-k-zaschite-saita-ne-rabo`.

**Что было сломано — две половины, и чинить их можно только вместе.**

1. Вызов `list_cards(card_type=...)` при параметре `tracker_type` падал `TypeError`,
   а `TypeError` молча проглатывался соседним `except Exception`. Обход **не работал
   никогда, с первого дня**: какую бы карточку владелец ни указал, ответ был «разрешения нет».
   Опасного не произошло — замок всё это время был ЗАКРЫТ, мимо него ничего не уехало.
   Плохо было другое: `docs/OWNER_GATE.md` обещал владельцу механизм, которого нет.
2. `approves:` читался как одна сплошная строка вместо перечня файлов.

Починить только первую половину значило бы поменять «молча не работает» на «молча работает
НЕ ТАК» — обход открылся бы не на те файлы. Второе хуже первого, поэтому обе или ни одной.

Тесты идут в ОБЕ стороны: обход открывается ровно для карточек в `owner-done` и ровно для
перечисленных в них файлов, и НЕ открывается ни для чего другого.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_owner_gate_under_test", _REPO / "scripts" / "check_owner_gate.py")
gate = importlib.util.module_from_spec(_SPEC)
sys.modules["check_owner_gate_under_test"] = gate
_SPEC.loader.exec_module(gate)


class _Card:
    def __init__(self, cid, status, approves=None):
        self.id = cid
        self.name = cid
        self.status = status
        self.frontmatter = {} if approves is None else {"approves": approves}


def _fake_queue(monkeypatch, cards, *, signature_ok=True):
    """Подменяет очередь карточек. `signature_ok=False` воспроизводит опечатку.

    Настоящий `list_cards` принимает `tracker_type`. Заглушка с таким же именем
    параметра ловит вызов с `card_type=` ровно так же, как это делал прод:
    TypeError.
    """
    import spa_core.owner_queue.queue as q

    if signature_ok:
        def list_cards(tracker_type=None, status=None, tracker_dir=None):
            return list(cards)
    else:
        def list_cards(card_type=None, status=None, tracker_dir=None):
            return list(cards)

    monkeypatch.setattr(q, "list_cards", list_cards, raising=False)
    monkeypatch.setattr(q, "load_card", lambda path: None, raising=False)


# ── половина 1: опечатка в имени параметра ──────────────────────────────────

def test_bypass_works_for_owner_done_card(monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: до правки здесь всегда было None."""
    _fake_queue(monkeypatch, [_Card("own-42", "owner-done", ["landing/src/pages/a.astro"])])
    got = gate._approved_scope("правка\n\nOwner-Approved: own-42", _REPO)
    assert got is not None, "обход не открылся для карточки в owner-done"
    assert got["card"] == "own-42"
    assert got["approves"] == ["landing/src/pages/a.astro"]


def test_typo_signature_is_reported_not_swallowed(monkeypatch, caplog):
    """Сбой поиска обязан быть СЛЫШЕН — немота и дала дефекту прожить год.

    Стенд с «неправильной» сигнатурой воспроизводит ровно ту поломку.
    """
    _fake_queue(monkeypatch, [_Card("own-42", "owner-done", ["landing/a.astro"])],
                signature_ok=False)
    with caplog.at_level("WARNING"):
        got = gate._approved_scope("Owner-Approved: own-42", _REPO)
    assert got is None, "сломанный поиск не смеет выдавать разрешение"
    assert any("own-42" in r.getMessage() for r in caplog.records), \
        "сбой проглочен молча — это и была причина, по которой дефект не заметили"


# ── половина 2: approves читается как ПЕРЕЧЕНЬ ──────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (["landing/a.astro", "landing/b.astro"], ["landing/a.astro", "landing/b.astro"]),
    ("landing/a.astro, landing/b.astro", ["landing/a.astro", "landing/b.astro"]),
    ("landing/a.astro\nlanding/b.astro", ["landing/a.astro", "landing/b.astro"]),
    ("landing/a.astro", ["landing/a.astro"]),
    ("B", ["B"]),
    (None, []),
    ("", []),
    ("   ", []),
    (",,", []),
])
def test_approves_is_parsed_as_a_list(raw, expected):
    assert gate._parse_approves(raw) == expected


def test_comma_string_is_not_one_giant_path(monkeypatch):
    """Вторая половина поломки: строка целиком не должна быть «одним файлом».

    Иначе обход не совпал бы НИ С ЧЕМ (или, хуже, совпал бы не с тем).
    """
    _fake_queue(monkeypatch,
                [_Card("own-7", "owner-done", "landing/a.astro, landing/b.astro")])
    got = gate._approved_scope("Owner-Approved: own-7", _REPO)
    assert got["approves"] == ["landing/a.astro", "landing/b.astro"]
    assert "landing/a.astro, landing/b.astro" not in got["approves"]


# ── контроли в обратную сторону: замок остаётся замком ──────────────────────

def test_card_not_owner_done_gives_no_bypass(monkeypatch):
    """Только владелец переводит в owner-done (инв. №14) — иначе обхода нет."""
    for status in ("needs-owner", "ingested", "backlog", ""):
        _fake_queue(monkeypatch, [_Card("own-42", status, ["landing/a.astro"])])
        assert gate._approved_scope("Owner-Approved: own-42", _REPO) is None, status


def test_unknown_card_gives_no_bypass(monkeypatch):
    _fake_queue(monkeypatch, [_Card("own-42", "owner-done", ["landing/a.astro"])])
    assert gate._approved_scope("Owner-Approved: own-999", _REPO) is None


def test_no_trailer_gives_no_bypass(monkeypatch):
    _fake_queue(monkeypatch, [_Card("own-42", "owner-done", ["landing/a.astro"])])
    assert gate._approved_scope("обычная правка без трейлера", _REPO) is None
    assert gate._approved_scope(None, _REPO) is None


def test_card_without_approves_scope_bypasses_nothing(monkeypatch):
    """Карточка без перечня файлов не открывает сайт целиком."""
    _fake_queue(monkeypatch, [_Card("own-42", "owner-done", None)])
    got = gate._approved_scope("Owner-Approved: own-42", _REPO)
    assert got is not None and got["approves"] == []


def test_empty_scope_never_matches_a_file():
    """Пустая строка в approves не смеет стать разрешением на пустой путь."""
    assert gate._parse_approves("") == []
    assert "" not in gate._parse_approves("landing/a.astro,,")
