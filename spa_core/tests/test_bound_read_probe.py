"""Проба приёмки «чтение привязано к МОДУЛЮ объявления» — контроль в ОБЕ стороны.

# LLM_FORBIDDEN

Сторож пробы `card_acceptance.PROBES["collection_read_is_bound_to_the_declaring_module"]`
(ADR-942, заказ G931 п. 2). Правило `.claude/rules/acceptance.md` п. 3: проба
регистрируется ТОЛЬКО с тестом, где она зелёная на целом контуре и красная на
КАЖДОМ порванном звене — с названным звеном.

**Положительный контроль — настоящая авария, а не придуманная.** Звено
«слияние по голому имени» рвётся не выдуманной заглушкой, а ВОСПРОИЗВЕДЕНИЕМ
прежней редакции прибора: берутся его же `declarations()` и `reads()`, и чтения
сводятся по ОДНОМУ имени — дословно то, что ADR-941 нашёл на двух `_TS_KEYS`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import declared_collection_census as dcc

PROBE_NAME = "collection_read_is_bound_to_the_declaring_module"


def _probe(**kwargs) -> tuple:
    return ca.PROBES[PROBE_NAME](None, **kwargs)


# ───────── звено 0: проба в реестре и зелена на НАСТОЯЩЕМ приборе ─────────

def test_the_probe_is_registered_and_green_on_the_real_instrument():
    assert PROBE_NAME in ca.PROBES, "проба не в реестре — очередь её не примет"
    verdict, message = _probe()
    assert verdict == ca.SATISFIED, message
    # Строка вердикта обязана НАЗЫВАТЬ измеренное, а не быть постоянной.
    for must in ("spa_core/one.py", "spa_core/two.py", "привязка", "предмет"):
        assert must in message, f"вердикт не называет «{must}»: {message}"


# ───────── звено 1: ВОЗВРАТ СЛИЯНИЯ ПО ИМЕНИ (авария ADR-941) ─────────

def _census_merging_by_bare_name(
        root: Path,
        declaration_roots: Sequence[str] = dcc.DECLARATION_ROOTS,
        reader_roots: Sequence[str] = dcc.READER_ROOTS,
) -> Dict[str, Any]:
    """ПРЕЖНЯЯ редакция прибора: чтения сведены по ОДНОМУ имени, без модуля.

    Это не заглушка — это дефект ADR-941 целиком, собранный из НАСТОЯЩИХ
    `declarations()` и `reads()` сегодняшнего прибора.
    """
    decls, broken_decl = dcc.declarations(root, declaration_roots)
    bound, unbound, broken_read, resolution = dcc.reads(root, reader_roots)
    by_name: Dict[str, Dict[str, list]] = {}
    for (_module, name), buckets in bound.items():
        acc = by_name.setdefault(name, {k: [] for k in dcc.READ_KINDS})
        for kind in dcc.READ_KINDS:
            acc[kind] = acc[kind] + buckets[kind]
    rows = []
    for decl in decls:
        places = by_name.get(decl["name"], {k: [] for k in dcc.READ_KINDS})
        own = f"{decl['module']}:{decl['lineno']}"
        places = {k: [p for p in v if p != own] for k, v in places.items()}
        total = sum(len(v) for v in places.values())
        axes = {
            "reader": "has_reader" if total else "no_reader",
            "iter": "iterated" if places["loop"] else "never_iterated",
            "empty": "asked" if places["emptiness"] else "not_asked",
            "other": "other_reads" if places["other"] else "only_loop",
        }
        rows.append({
            **decl, "axes": axes, "reads": places, "read_count": total,
            "unresolved_reads": {k: [] for k in dcc.READ_KINDS},
            "unresolved_read_count": 0,
            "subject": all(axes[a] == w for a, w in dcc.SUBJECT_AXES.items()),
            "not_excluded": False,
        })
    return {
        "root": str(root), "surface": len(rows),
        "subject": sum(1 for r in rows if r["subject"]),
        "not_excluded": 0, "empty_today": 0, "subject_and_empty_today": 0,
        "resolution": resolution, "colliding_names": 1,
        "declarations_in_collision": 2,
        "unparsable_declaration_files": broken_decl,
        "unparsable_reader_files": broken_read,
        "unmeasured": bool(broken_decl or broken_read),
        "rows": rows,
    }


def test_the_probe_refuses_when_reads_merge_by_bare_name():
    """ЗВЕНО: чужое противоядие зачтено одноимённому перечню ⇒ ОТКАЗ.

    Без этой проверки проба не отличала бы починку ADR-942 от дефекта
    ADR-941 — то есть была бы украшением.
    """
    verdict, message = _probe(census=_census_merging_by_bare_name)
    assert verdict == ca.NOT_SATISFIED, (verdict, message)
    assert "ГОЛОМУ ИМЕНИ" in message, message


# ───────── звено 2: противоядие НЕ ПРОЧИТАНО ─────────

def test_the_probe_refuses_when_the_antidote_is_not_read():
    def blind_to_emptiness(root, **kwargs):
        result = dcc.census(root, **kwargs)
        for row in result["rows"]:
            row["axes"]["empty"] = "not_asked"
            row["subject"] = True
        result["subject"] = len(result["rows"])
        return result

    verdict, message = _probe(census=blind_to_emptiness)
    assert verdict == ca.NOT_SATISFIED, (verdict, message)
    assert "НЕ ПРОЧИТАНО" in message, message


# ───────── звено 3: привязка МЕРТВА, а вердикты совпали ─────────

def test_the_probe_refuses_when_resolution_is_dead():
    """Вердикты те же, привязка не работает ни на одном чтении.

    Этот мутант и есть причина, по которой проба спрашивает `resolution`
    отдельно: совпадение вердиктов могло быть случайным.
    """
    def no_resolution(root, **kwargs):
        result = dcc.census(root, **kwargs)
        result["resolution"] = {k: 0 for k in dcc.RESOLUTION_KINDS}
        return result

    verdict, message = _probe(census=no_resolution)
    assert verdict == ca.NOT_SATISFIED, (verdict, message)
    assert "привязка мертва" in message, message


# ───────── звено 4: ТРЕТИЙ ИСХОД. «Не измерено» вердиктом не является ─────────

def test_an_instrument_that_raises_is_unmeasured_not_a_verdict():
    def exploding(root, **kwargs):
        raise RuntimeError("дверь к дереву закрыта")

    verdict, message = _probe(census=exploding)
    assert verdict == ca.UNMEASURED, (verdict, message)
    assert "RuntimeError" in message, message


def test_an_unparsable_scene_is_unmeasured_not_a_verdict():
    def unparsable(root, **kwargs):
        result = dcc.census(root, **kwargs)
        result["unmeasured"] = True
        result["unparsable_reader_files"] = [
            {"path": "spa_core/reader_two.py", "reason": "не разбирается"}]
        return result

    verdict, message = _probe(census=unparsable)
    assert verdict == ca.UNMEASURED, (verdict, message)
    assert "НЕ РАЗОБРАЛАСЬ" in message, message


def test_a_scene_without_two_namesakes_is_unmeasured():
    """Сцена, потерявшая ОДИН из двух одноимённых перечней, мерой не является."""
    def one_row_only(root, **kwargs):
        result = dcc.census(root, **kwargs)
        result["rows"] = [r for r in result["rows"]
                          if r["module"] != "spa_core/two.py"]
        return result

    verdict, message = _probe(census=one_row_only)
    assert verdict == ca.UNMEASURED, (verdict, message)
    assert "ДВУХ объявлений" in message, message


def test_a_non_measurement_answer_is_unmeasured():
    verdict, message = _probe(census=lambda root, **kwargs: "зелено")
    assert verdict == ca.UNMEASURED, (verdict, message)


# ───────── звено 5: СЦЕНА ОБЪЯВЛЕНА, а не спрятана в теле пробы ─────────

def test_the_scene_is_declared_and_carries_both_namesakes():
    """Урок ADR-932: мерка, живущая только в теле условия, расходится молча.

    Сцена объявлена константой, и контроль выше судит ТУ ЖЕ сцену, которую
    строит проба. Проверяется её несущее свойство: два ОДНОИМЁННЫХ объявления
    в РАЗНЫХ модулях и противоядие РОВНО у одного.
    """
    scene = ca.MODULE_BOUND_READ_SCENE
    assert scene, "сцена ПУСТА — проба мерила бы пустоту"
    decls = [rel for rel, text in scene.items() if text.startswith("COLL = ")]
    assert len(decls) == 2, f"одноимённых объявлений не два: {decls}"
    antidotes = [rel for rel, text in scene.items() if "assert COLL" in text]
    assert len(antidotes) == 1, f"противоядие обязано быть РОВНО у одного: {antidotes}"
    assert sum(1 for t in scene.values() if "for x in COLL" in t) == 2, (
        "итерацию обязаны читать ОБА — иначе ось `iter` сняла бы предмет "
        "у одного из них по другой причине, и проба отвечала бы не о слиянии")


@pytest.mark.parametrize("name", [PROBE_NAME])
def test_the_probe_name_is_what_the_queue_will_accept(name):
    """Очередь принимает имя из реестра; расхождение имени и ключа — отказ."""
    assert name in ca.PROBES
    assert ca.PROBES[name].__name__ == f"_probe_{name}"
