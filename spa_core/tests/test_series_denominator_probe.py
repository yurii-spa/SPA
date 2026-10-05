"""Контроль пробы приёмки `series_denominator_measured` (ADR-568, заказ G99 п. 1).

Проба регистрируется только с тестом, где она ЗЕЛЕНА на целом контуре и КРАСНА
на каждом порванном звене — с НАЗВАННЫМ звеном, и где она не проходит
подстрокой (ADR-333). Иначе критерий приёмки — проза той же сессии, что работу
и делала.

Контур у пробы ДВУХПОЛОВИННЫЙ, и половины рвутся отдельно: живой прогон по
дереву, которое стои́т сейчас, и доезд числа до ЧИТАТЕЛЯ (артефакт шага
0-офис). Зелёная первая половина при мёртвой второй — ровно форма ADR-208:
число посчитано, и не читает его никто.

Литералов даты и литералов pid здесь нет вовсе: предмет пробы не зависит ни от
календаря, ни от того, какой номер процесса сегодня занят.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import card_acceptance as CA
from spa_core.monitoring import rule_second_copy_census as C

PROBE = "series_denominator_measured"

SEQUENCE_SCENE = '''
def alpha(rows):
    extra = [0.0] * 3
    for row in rows:
        extra[row["slot"]] += 1
    return extra
'''


def _tree(tmp_path: Path, *, source: str = SEQUENCE_SCENE) -> Path:
    """Одноразовое дерево: каталоги, которые обходит шаг, и один счётчик."""
    base = tmp_path / C.OPEN_COUNTER_DIRS[0]
    base.mkdir(parents=True, exist_ok=True)
    (base / "scene.py").write_text(source, encoding="utf-8")
    for extra in C.OPEN_COUNTER_DIRS[1:]:
        (tmp_path / extra).mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _live(root: Path) -> dict:
    neighbour = C.open_class_counter_census(root)
    return C.sequence_members_of_the_whole_population(root, neighbour)


def _shelf(root: Path, step: dict | None, *, key: str | None = None) -> Path:
    """Артефакт, который читает шаг 0-офис, — с подставленным шагом."""
    path = root / "data" / C.ARTIFACT
    doc: dict = {"status": "CLEAN", "generated_by": C.PRODUCER}
    if step is not None:
        doc[key or "sequence_members_of_the_whole_population"] = step
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _run(root: Path, artifact: Path | None = None) -> tuple[str, str]:
    """Проба на стенде: обе двери к живому дереву закрыты аргументами."""
    got = CA.measure_series_denominator(
        root=root, artifact=artifact or (root / "data" / C.ARTIFACT))
    if not got.get("measured"):
        return CA.UNMEASURED, got.get("reason", "")
    # Вердикт выносит САМА проба — второй копии правила вердикта здесь нет.
    saved = CA.measure_series_denominator
    try:
        CA.measure_series_denominator = lambda: got        # noqa: E731
        return CA.PROBES[PROBE](None)
    finally:
        CA.measure_series_denominator = saved


# ------------------------------------------------------- РЕГИСТРАЦИЯ

def test_the_probe_is_registered():
    """Проба, потерявшая регистрацию, не измеряет ничего (обход идёт реестром)."""
    assert PROBE in CA.PROBES


# -------------------------------------------------- ЗЕЛЁНЫЙ КОНТУР ЦЕЛИКОМ

def test_the_whole_contour_is_satisfied(tmp_path):
    """Живой прогон измерен И число доехало до читателя."""
    root = _tree(tmp_path)
    _shelf(root, _live(root))
    verdict, detail = _run(root)
    assert verdict == CA.SATISFIED, detail
    assert "знаменатель" in detail
    assert "число доехало до читателя" in detail


# ----------------------------------- ПОРВАННОЕ ЗВЕНО: ЧИСЛО НЕ ДОЕХАЛО

def test_a_missing_artifact_is_not_satisfied(tmp_path):
    """Артефакта нет ⇒ число посчитано, и читателя у него нет."""
    root = _tree(tmp_path)
    verdict, detail = _run(root)
    assert verdict == CA.NOT_SATISFIED
    assert "до читателя не доехало" in detail


def test_an_artifact_without_the_step_is_not_satisfied(tmp_path):
    """Артефакт есть, шага в нём нет — ровно форма ADR-208."""
    root = _tree(tmp_path)
    _shelf(root, None)
    verdict, detail = _run(root)
    assert verdict == CA.NOT_SATISFIED
    assert "нет вовсе" in detail


def test_a_key_that_merely_contains_the_name_does_not_pass(tmp_path):
    """Проба не проходит ПОДСТРОКОЙ (ADR-333): ключ сверяется целиком."""
    root = _tree(tmp_path)
    _shelf(root, _live(root),
           key="sequence_members_of_the_whole_population_draft")
    verdict, detail = _run(root)
    assert verdict == CA.NOT_SATISFIED
    assert "нет вовсе" in detail


def test_a_stale_artifact_is_not_satisfied(tmp_path):
    """Читатель держит вчерашнее население ⇒ критерий НЕ выполнен."""
    root = _tree(tmp_path)
    live = dict(_live(root))
    live["population"] = live["population"] + 7
    _shelf(root, live)
    verdict, detail = _run(root)
    assert verdict == CA.NOT_SATISFIED
    assert "артефакт старее кода" in detail


def test_an_artifact_carrying_a_refusal_is_not_satisfied(tmp_path):
    """В артефакте стои́т ОТКАЗ шага: читатель видит не поправку."""
    root = _tree(tmp_path)
    _shelf(root, {"status": "UNMEASURED",
                  "unmeasured_class": C.UNMEASURED_MEMBER_CONTROL})
    verdict, detail = _run(root)
    assert verdict == CA.NOT_SATISFIED
    assert C.UNMEASURED_MEMBER_CONTROL in detail


def test_an_unparsable_artifact_is_unmeasured(tmp_path):
    """Артефакт не разобран ⇒ «не измерено» с причиной, а не «не выполнено»."""
    root = _tree(tmp_path)
    (root / "data" / C.ARTIFACT).write_text("{не json", encoding="utf-8")
    verdict, detail = _run(root)
    assert verdict == CA.UNMEASURED
    assert "не разобран" in detail


# --------------------------------- ПОРВАННОЕ ЗВЕНО: ЖИВОЙ ЗАМЕР ОТКАЗАЛ

def test_a_tree_without_the_measured_directories_is_unmeasured(tmp_path):
    """Каталогов нет ⇒ отказ живого прогона, а не «поправка равна нулю»."""
    (tmp_path / "data").mkdir()
    verdict, detail = _run(tmp_path)
    assert verdict == CA.UNMEASURED
    assert "живой замер отказал" in detail


def test_the_probe_refuses_an_argument():
    """Пофайловой формы у критерия нет: аргумент отвергается ВСЛУХ."""
    verdict, detail = CA.PROBES[PROBE]("spa_core/monitoring/x.py")
    assert verdict == CA.UNMEASURED
    assert "не принимает аргумента" in detail


# ------------------- ПОРВАННОЕ ЗВЕНО: ПРИБОР В ГОЛОВНОЙ КЛЕТКЕ СВОЕГО ЗАМЕРА

def test_the_instrument_in_its_own_head_cell_is_not_satisfied(tmp_path):
    """Счётчик самого производителя в головной клетке ⇒ критерий НЕ выполнен.

    Стенд кладёт по пути производителя файл с накопителем-последовательностью:
    головное число ряда начинает зависеть от того, доставлен прибор или нет, и
    ни один сторож не сказал бы почему (замер ADR-566).
    """
    root = _tree(tmp_path)
    producer = root / C.PRODUCER
    producer.parent.mkdir(parents=True, exist_ok=True)
    producer.write_text(SEQUENCE_SCENE, encoding="utf-8")
    live = _live(root)
    assert live["own_sites"]["in_the_false_cell"] == 1, live["own_sites"]
    _shelf(root, live)
    verdict, detail = _run(root)
    assert verdict == CA.NOT_SATISFIED
    assert "ГОЛОВНОЙ клетке" in detail


# ------------------------ ПОРВАННОЕ ЗВЕНО: ФОРМА ОТВЕТА ЖИВОГО ПРОГОНА

@pytest.mark.parametrize("broken,needle", [
    ({"coordinates_agree_with_the_neighbour": False}, "координаты населения"),
    ({"correction_at_least": 9, "correction_at_most": 2}, "промежутком"),
    ({"correction_at_most": None}, "промежутком"),
])
def test_a_malformed_live_answer_is_not_satisfied(tmp_path, broken, needle):
    """Промежуток, который ничего не ограничивает, пробой не признаётся."""
    root = _tree(tmp_path)
    live = {**_live(root), **broken}
    got = {"measured": True, "reason": "", "live": live,
           "shelf": dict(live), "artifact": str(root / "data" / C.ARTIFACT)}
    saved = CA.measure_series_denominator
    try:
        CA.measure_series_denominator = lambda: got        # noqa: E731
        verdict, detail = CA.PROBES[PROBE](None)
    finally:
        CA.measure_series_denominator = saved
    assert verdict == CA.NOT_SATISFIED
    assert needle in detail
