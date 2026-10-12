"""Храповик заказа G697 п. 2: объявленный путь, которого фикстура НЕ НЕСЁТ.

# LLM_FORBIDDEN

Форма, за которую платили ЧЕТЫРЕ цикла подряд (#832, #834, #837, #841): в
`_READ_SCHEMA` шага 0-офис объявляется новый раздел, фикстура соседа его не
получает, и ЧУЖАЯ сцена краснеет не о своём предмете. Каждый раз это находили
прогоном и чинили по одному; заказ потребовал мерить население.

Замер 2026-10-12 (прибор `_fixture_schema_gap.py`): площадок двери **121** —
фикстура разрешена у 81, имя не объявлено у 16, документ собран ВЫЗОВОМ у 14,
НЕ ИЗМЕРЕНО 10. Население класса — **47 площадок · 301 пара «площадка ×
путь» · 21 ключ «файл::артефакт»**.

Храповик держит ключи: число РАЗНЫХ не несомых путей у ключа не вправе
вырасти, нового ключа появиться не вправе. Объявил поле и не дал его фикстуре
— красный тест СРАЗУ, и красный О СВОЁМ предмете, а не о чужом.

База может **только уменьшаться**. Дописывать в неё, чтобы погасить падение,
ЗАПРЕЩЕНО (инв. #16, тот же порядок, что у `frozen_date_baseline.json`,
`design_status_baseline.json`, `site_numbers_baseline.json`). Честный выход из
класса два: дать фикстуре значение ЛИБО, если куцый документ и есть предмет
сцены, пометить площадку `# SCHEMA-GAP-OK: <причина>` — освобождение видно,
считается и печатается.

**Население СМЕШАННОЕ, и это сказано вслух.** Среди 21 ключа есть и латентный
вред (`test_list_day_axis.py::list_identity_census.json` — ровно пять
разделов, добавленных #832/#834/#837/#841 и предыдущим ходом), и намеренно
куцые документы, чей ПРЕДМЕТ — отдельная ветка отчёта (третий исход,
generic-ветка, возраст). Разделить их мерой нельзя: намерение автора в
исходнике не записано ничем, кроме пометки, которой пока ни у кого нет.
Поэтому прибор мерит ФОРМУ, а разбор 21 ключа по природе — заказ следующего
хода, а не догадка этого.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from spa_core.tests import _fixture_schema_gap as gap

_ROOT = Path(__file__).resolve().parents[2]
_BASELINE = Path(__file__).with_name("fixture_schema_gap_baseline.json")


def _office():
    """Шаг 0-офис — ПАКЕТНЫМ импортом, не загрузкой по пути (урок #820)."""
    return importlib.import_module("scripts.consume_office_reports")


def _census() -> gap.Census:
    office = _office()
    return gap.measure(schema=office._READ_SCHEMA, has_path=office._has_path,
                       root=str(_ROOT))


def _baseline() -> dict:
    return json.loads(_BASELINE.read_text(encoding="utf-8"))


def test_the_measurement_had_a_subject_at_all() -> None:
    """Ноль площадок — «НЕ ИЗМЕРЕНО», а не «населения нет» (инв. #17)."""
    census = _census()
    assert census.files_scanned > 0, (
        "НЕ ИЗМЕРЕНО: ни один тест-файл не зовёт дверь "
        f"`{gap.DOOR}` — предмета у замера нет, и нулём это не считается")
    assert census.sites, (
        "НЕ ИЗМЕРЕНО: ни одна площадка двери не разрешена до документа — "
        "«не несомых путей 0» на нуле сравнений есть подделка доказательства")


def test_every_scanned_file_was_actually_parsed() -> None:
    """Неразобранный файл обязан падать ГРОМКО, а не выпадать из населения."""
    broken = [row for row in _census().unmeasured
              if row[1].startswith(("file_unparsed", "file_unreadable"))]
    assert not broken, f"НЕ ИЗМЕРЕНО: файлы не прочитаны/не разобраны: {broken}"


def test_a_marker_without_a_reason_is_not_an_exemption() -> None:
    """Записка без причины освобождением не является (урок `FROZEN-DATE-OK`)."""
    bare = _census().marker_without_reason
    assert not bare, (
        "пометка `SCHEMA-GAP-OK` без причины: причина — часть объявления, "
        f"«и так понятно» причиной не является: {bare}")


def test_the_unmeasured_share_did_not_grow() -> None:
    """Потеря охвата прибором — тоже регресс, и молчать о ней нельзя."""
    census = _census()
    ceiling = _baseline()["unmeasured_max"]
    assert len(census.unmeasured) <= ceiling, (
        f"НЕ ИЗМЕРЕНО выросло: {len(census.unmeasured)} > {ceiling}. "
        "Новая площадка двери не разрешается прибором — её документ надо "
        "собрать так, чтобы разбор его видел, либо расширить прибор; "
        "поднимать потолок запрещено.\n"
        + "\n".join(f"  {where}: {why}" for where, why in census.unmeasured))


def test_no_key_carries_more_unfed_paths_than_the_baseline() -> None:
    """Главный храповик: ключ не вправе вырасти, новый ключ не вправе быть."""
    report = gap.compare(_census(), _baseline()["keys"])
    assert not report, (
        "объявленный путь `_READ_SCHEMA` не несёт фикстура того же "
        "производителя (заказ G697 п. 2, ADR-698). Лечится ЗНАЧЕНИЕМ в "
        "фикстуре либо пометкой `# SCHEMA-GAP-OK: <причина>`, если куцый "
        "документ и есть предмет сцены. ДОПИСЫВАТЬ В БАЗУ ЗАПРЕЩЕНО.\n"
        + "\n".join(report))
