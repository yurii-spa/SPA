#!/usr/bin/env python3
"""Контроль пробы `closed_cards_fate_named` В ОБЕ СТОРОНЫ (ADR-1051, правило
`.claude/rules/acceptance.md` п. 3).

Проба механизирует критерий, названный циклом #1187 в теле карточки
`inbox-desyat-kartochek-zakryty-dveryu-kotoraya` ДО работы: храповик приёмки зелен
БЕЗ правок базы и без новых `acceptance_probe:` у десяти закрытых карточек, а у каждой
из десяти названа ПРИЧИНА выбранной дороги.

Проверка «зелена на целом контуре» без обратной стороны ничего не стоит: строка
`carried_to:` или поле `fate_reason:` стали бы опт-аутом с нулевой ценой. Поэтому здесь
сцена ОДНА, а порванных звеньев восемь, и каждое названо в вердикте поимённо:

* носитель оставлен `done` без освобождения;
* `carried_to` обещает путь, которого нет;
* причина не названа вовсе;
* причина названа ФЛАГОМ (слишком коротка, чтобы быть причиной);
* у закрытой карточки объявлена проба — критерий задним числом;
* имя дописано в базу освобождений (инв. #16);
* НОВЫЙ нарушитель рядом с десятью — вердикт берётся у СТОРОЖА, а не пересказывается;
* проводка разошлась: сторож читает не ту функцию освобождения, что исполнитель.

Плюс два третьих исхода (инв. #17): ни одной из десяти нет в дереве · база не читается.
Оба обязаны быть `unmeasured`, а не «чисто».

Вердикты сравниваются как ЗНАЧЕНИЯ, а не подстрокой (ADR-333).

Только stdlib, оффлайн; живой трекер не трогается — всё в одноразовом каталоге.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import spa_core.tests.test_inbox_acceptance_ratchet as ratchet
from spa_core.monitoring.card_acceptance import (
    NOT_SATISFIED,
    PROBES,
    SATISFIED,
    UNMEASURED,
    _TEN_CLOSED_WITHOUT_CRITERION,
)

PROBE = "closed_cards_fate_named"

#: Дороги сцены: семь карточек возвращены в приём, три освобождены носителями —
#: ровно то разделение, которым разобраны настоящие десять (цикл #1189).
_CARRIED = _TEN_CLOSED_WITHOUT_CRITERION[3:6]
_RETURNED = tuple(n for n in _TEN_CLOSED_WITHOUT_CRITERION if n not in _CARRIED)

_REASON = "возврат в приём: предмет измерен, закрытие пробой не заработано"
_TARGET = "nimbalyst-local/tracker/cel-nositelya.md"


def _probe():
    return PROBES[PROBE](None)


def _scene(tmp_path: Path, monkeypatch, *, baseline: list[str] | None = None,
           baseline_text: str | None = None) -> Path:
    """Одноразовое дерево с десятью РАЗОБРАННЫМИ карточками. Возвращает каталог трекера."""
    tracker = tmp_path / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    (tracker / "cel-nositelya.md").write_text("предмет носителя уехал сюда", encoding="utf-8")
    for name in _RETURNED:
        (tracker / name).write_text(
            "---\ntrackerStatus:\n  type: inbox\nstatus: new\n"
            f'fate_reason: "{_REASON}"\n---\n\nтело\n', encoding="utf-8")
    for name in _CARRIED:
        (tracker / name).write_text(
            "---\ntrackerStatus:\n  type: inbox\nstatus: done\n"
            f"carried_to: {_TARGET}\n"
            f'fate_reason: "заработанное освобождение: предмет уехал в {_TARGET}"\n---\n\nтело\n',
            encoding="utf-8")
    base_path = tmp_path / "scripts" / "inbox_acceptance_baseline.json"
    base_path.parent.mkdir(parents=True)
    if baseline_text is not None:
        base_path.write_text(baseline_text, encoding="utf-8")
    else:
        base_path.write_text(json.dumps({"files": baseline or ["inbox-staraya-kartochka.md"]}),
                             encoding="utf-8")
    monkeypatch.setattr(ratchet, "_TRACKER", tracker)
    monkeypatch.setattr(ratchet, "_REPO", tmp_path)
    monkeypatch.setattr(ratchet, "_BASELINE", base_path)
    return tracker


def test_the_whole_contour_is_satisfied(tmp_path, monkeypatch) -> None:
    """Положительная сторона: судьба названа у всех десяти ⇒ `satisfied`."""
    _scene(tmp_path, monkeypatch)
    verdict, why = _probe()
    assert verdict == SATISFIED, why
    # Разбивка по дорогам — часть ответа: «зелено» без неё не говорит, ЧТО измерено.
    assert "возврат в приём 7" in why and "заработанное освобождение 3" in why, why


def test_a_carrier_left_closed_without_a_release_is_named(tmp_path, monkeypatch) -> None:
    """Звено 1: карточка осталась `done` без освобождения ⇒ отказ с её ИМЕНЕМ."""
    tracker = _scene(tmp_path, monkeypatch)
    victim = _RETURNED[0]
    (tracker / victim).write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: done\n"
        f'fate_reason: "{_REASON}"\n---\n\nтело\n', encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why and "судьба НЕ названа" in why, why


def test_a_promised_path_does_not_free_the_carrier(tmp_path, monkeypatch) -> None:
    """Звено 2: `carried_to` на несуществующий путь ⇒ отказ (это опт-аут, не освобождение)."""
    tracker = _scene(tmp_path, monkeypatch)
    victim = _CARRIED[0]
    (tracker / victim).write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: done\n"
        "carried_to: nimbalyst-local/tracker/net-takoi-tseli.md\n"
        f'fate_reason: "{_REASON}"\n---\n\nтело\n', encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why, why


def test_a_road_without_a_reason_is_refused(tmp_path, monkeypatch) -> None:
    """Звено 3: дорога выбрана, причина НЕ названа ⇒ отказ."""
    tracker = _scene(tmp_path, monkeypatch)
    victim = _RETURNED[1]
    (tracker / victim).write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: new\n---\n\nтело\n", encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why and "причина НЕ названа" in why, why


def test_a_reason_that_is_a_flag_is_refused(tmp_path, monkeypatch) -> None:
    """Звено 4: причина-флаг (`ок`) отказывается — иначе поле стало бы опт-аутом."""
    tracker = _scene(tmp_path, monkeypatch)
    victim = _RETURNED[2]
    (tracker / victim).write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: new\nfate_reason: \"ок\"\n---\n\nтело\n",
        encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why and "короче" in why, why


def test_a_reason_in_prose_does_not_pass_as_a_field(tmp_path, monkeypatch) -> None:
    """Подстрокой проба НЕ проходит (ADR-333): причина в ТЕЛЕ полем не является."""
    tracker = _scene(tmp_path, monkeypatch)
    victim = _RETURNED[3]
    (tracker / victim).write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: new\n---\n\n"
        f'fate_reason: "{_REASON}"\n', encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why, why


def test_a_retroactive_probe_on_a_closed_card_is_refused(tmp_path, monkeypatch) -> None:
    """Звено 5: `acceptance_probe` у ЗАКРЫТОЙ карточки — самосертификация ⇒ отказ."""
    tracker = _scene(tmp_path, monkeypatch)
    victim = _RETURNED[4]
    (tracker / victim).write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: new\n"
        "acceptance_probe: problem_absent\n"
        f'fate_reason: "{_REASON}"\n---\n\nтело\n', encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why and "задним числом" in why, why


def test_a_name_written_into_the_baseline_is_refused(tmp_path, monkeypatch) -> None:
    """Звено 6: имя дописано в базу освобождений ⇒ отказ (инв. #16, база только убывает)."""
    victim = _RETURNED[5]
    _scene(tmp_path, monkeypatch, baseline=[victim])
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert victim in why and "базу" in why, why


def test_a_fresh_offender_beside_the_ten_reddens_the_probe(tmp_path, monkeypatch) -> None:
    """Звено 7: вердикт берётся У СТОРОЖА — новый нарушитель РЯДОМ с десятью тоже красит.

    Без этой стороны проба судила бы только о названных десяти, и одиннадцатая карточка,
    взятая в работу без критерия в том же дереве, прошла бы молча.
    """
    tracker = _scene(tmp_path, monkeypatch)
    (tracker / "inbox-odinnadtsataya.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\nstatus: in-progress\n---\n\nтело\n", encoding="utf-8")
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert "храповик приёмки КРАСЕН" in why and "inbox-odinnadtsataya.md" in why, why


def test_a_second_copy_of_the_release_condition_is_named(tmp_path, monkeypatch) -> None:
    """Звено 8: проводка. Сторож читает НЕ ту функцию освобождения ⇒ отказ, а не зелень."""
    _scene(tmp_path, monkeypatch)
    monkeypatch.setattr(ratchet, "carried_release", lambda *a, **k: (Path("/"), ""))
    verdict, why = _probe()
    assert verdict == NOT_SATISFIED, why
    assert "НЕ ту функцию освобождения" in why, why


def test_an_empty_tracker_is_unmeasured_not_clean(tmp_path, monkeypatch) -> None:
    """Третий исход: ни одной из десяти в дереве нет ⇒ `unmeasured`, НЕ «все разобраны»."""
    _scene(tmp_path, monkeypatch)
    for name in _TEN_CLOSED_WITHOUT_CRITERION:
        (tmp_path / "nimbalyst-local" / "tracker" / name).unlink()
    verdict, why = _probe()
    assert verdict == UNMEASURED, why
    assert "ни одной из десяти" in why, why


def test_an_unreadable_baseline_is_unmeasured(tmp_path, monkeypatch) -> None:
    """Третий исход: база не читается ⇒ `unmeasured` (ADR-1049), а не пропуск."""
    _scene(tmp_path, monkeypatch, baseline_text="{ это не JSON")
    verdict, why = _probe()
    assert verdict == UNMEASURED, why
    assert "НЕ ПРОЧИТАНА" in why, why


def test_the_probe_is_registered_once(tmp_path, monkeypatch) -> None:
    """Проба обязана быть в реестре: необъявленную не примет ни очередь, ни шаг 0-офис."""
    assert PROBE in PROBES
    assert len(_TEN_CLOSED_WITHOUT_CRITERION) == 10
    assert len(set(_TEN_CLOSED_WITHOUT_CRITERION)) == 10


@pytest.mark.parametrize("verdict", [SATISFIED, NOT_SATISFIED, UNMEASURED])
def test_three_outcomes_are_distinct_values(verdict: str) -> None:
    """Три исхода — РАЗНЫЕ значения; слипнись два, вердикт перестал бы отвечать (инв. #17)."""
    assert len({SATISFIED, NOT_SATISFIED, UNMEASURED}) == 3
    assert isinstance(verdict, str) and verdict
