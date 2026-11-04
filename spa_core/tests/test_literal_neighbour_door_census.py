"""Контроли прибора класса «литерал соседа в тесте ЖИВОГО замера» (G907 п. 2).

Каждый тест здесь — положительный или отрицательный контроль на СВОЙСТВЕ, на
котором стои́т ответ прибора ``spa_core/tests/_literal_neighbour_door.py``:

* он обязан НАЙТИ форму уже случившейся аварии #1029 (ADR-916) — литерал
  соседа, поданный шагу вместе с ЖИВЫМ корнем дерева;
* он обязан ПРОМАХНУТЬСЯ по литералу, который объявляет население СВОЕЙ
  сцены (``tmp_path``): там число задаёт сама сцена, и оно не дрейфует;
* он обязан промахнуться по соседу, собранному у ПРОИЗВОДИТЕЛЯ, — иначе
  лечение ADR-916 числилось бы болезнью;
* сцена роста обязана быть сценой РОСТА: её признаёт счётчиком та самая
  производственная форма (``_open_counter_sites``), по которой шаг и считает
  население. Сцена, которой перепись не видит, сделала бы канарейку
  вакуумной, а весь дифференциальный замер — ответом о приборе;
* канарейка обязана ЗАПИРАТЬ ответ: не сдвинулось население — о классе не
  говорим (урок ADR-898);
* ``skipped`` и исчезновение имени обязаны считаться сменой вердикта
  (урок #465: такой тест не краснеет и не проходит — он ИСЧЕЗАЕТ).

Ни один тест здесь не ходит в сеть, не зовёт pytest и не трогает живое
дерево: прогон прибора инъектируется (``runner=``), сцены — строки.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import rule_second_copy_census as census
from spa_core.tests import _literal_neighbour_door as door
from spa_core.tests import test_literal_neighbour_class_ratchet as ratchet

#: Целое объявление для контролей пробы. Член НАСТОЯЩИЙ — он обязан быть
#: найден в дереве, иначе положительная половина была бы вакуумной.
_GOOD_DECL = {
    "order": "G907.2",
    "sha": "deadbeefcafe",
    "measured_at": "2026-11-04T00:00:00Z",
    "scene": door.GROWN_REL,
    "canary": {"base_sites": 290, "grown_sites": 291, "delta": 1},
    "positive_control": {"status": "MEASURED", "declared": 104,
                         "flipped": ["b.py::bomb"], "steps_covered": []},
    "surface_files": ["spa_core/tests/_literal_neighbour_door.py"],
    "surface_count": 1,
    "members": [{
        "nodeid": ("spa_core/tests/test_literal_neighbour_door_census.py"
                   "::test_parse_outcomes_keeps_skipped_apart"),
        "file": "spa_core/tests/test_literal_neighbour_door_census.py",
        "base": "PASSED", "grown": "FAILED",
        "measured_in": "deadbeefcafe · сцена " + door.GROWN_REL,
    }],
    "member_files": ["spa_core/tests/test_literal_neighbour_door_census.py"],
    "member_count": 1,
    "upper_bound": 1,
    # Такт и охват бомбы — РАБОТА карточки. В целом объявлении они есть;
    # в живом объявлении 04.11 их НЕТ, и проба об этом честно отказывает.
    "tact": {"reader": "шаг 0-офис", "max_age_h": 192},
}


def _row_steps() -> list:
    """Перечень шагов ряда — У ПРОИЗВОДИТЕЛЯ, не литералом (ADR-913)."""
    return sorted(n for n in dir(census)
                  if n.startswith("UNMEASURED_") and n.endswith("_POPULATION"))


def _whole_declaration() -> dict:
    doc = json.loads(json.dumps(_GOOD_DECL))
    doc["positive_control"]["steps_covered"] = _row_steps()
    return doc

# --------------------------------------------------------------------------- #
# Материал: сцены исходника
# --------------------------------------------------------------------------- #

#: Форма аварии #1029 ДОСЛОВНО: помощник-сосед с числами-параметрами, живой
#: корень модульной константой, и шаг, позванный обоими сразу.
BOMB = '''
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _neighbour(never_read: int = 1, unbound: int = 0) -> dict:
    return {"status": "MEASURED",
            "unresolved_reasons": {"never_read": never_read,
                                   "unbound": unbound}}


def test_live():
    out = document_field_reader_in_file(REPO_ROOT, _neighbour(16, 10))
    assert out["status"] == "MEASURED"
'''

#: Тот же литерал — но на СВОЕЙ сцене. Это НЕ предмет класса.
SCENE_ONLY = '''
from pathlib import Path


def _neighbour(n: int = 1) -> dict:
    return {"status": "MEASURED", "unresolved_reasons": {"escapes": n}}


def _tree(tmp_path):
    root = tmp_path / "tree"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    return root


def test_scene(tmp_path):
    out = bound_name_read_in_this_scope(_tree(tmp_path), _neighbour(3))
    assert out["status"] == "MEASURED"
'''

#: Сосед, собранный у ПРОИЗВОДИТЕЛЯ, — лечение ADR-916.
PRODUCER = '''
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _live_neighbour(root):
    return census.container_counter_field_step(root, census.open_class_counter_census(root))


def test_live():
    out = document_field_reader_in_file(REPO_ROOT, _live_neighbour(REPO_ROOT))
    assert out["status"] == "MEASURED"
'''

#: Сосед БЕЗ числа: проверка отказа шага, литерала населения нет.
NO_NUMBER = '''
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_refusal():
    out = container_counter_field_step(ROOT, {"status": "MEASURED",
                                              "unresolved_reasons": {}})
    assert out["status"] == "UNMEASURED"
'''

#: Сосед, сперва ЛЁГШИЙ В ПЕРЕМЕННУЮ. Без разбора присваиваний прибор видел
#: бы здесь ноль — то есть «не спрашивали» читалось бы как «признака нет».
BOUND_NAME = '''
from pathlib import Path


def _root():
    return Path(__file__).resolve().parents[2]


def test_live():
    neighbour = {"status": "MEASURED", "open_to_an_unnamed_class": 158}
    out = writer_harm_form(_root(), neighbour)
    assert out["status"] == "MEASURED"
'''


def _surface(src: str) -> door.FileSurface:
    return door.file_surface("t.py", src)


# --------------------------------------------------------------------------- #
# 1. СЦЕНА РОСТА — её обязана видеть ПРОИЗВОДСТВЕННАЯ форма
# --------------------------------------------------------------------------- #

def test_the_grown_scene_is_exactly_one_counter_by_the_production_rule():
    """Сцена, которой перепись не видит, делает канарейку вакуумной.

    Спрашивается ровно тот искатель, которым шаг набирает своё население
    (``_open_counter_sites``), а не похожая проверка прибора: сверять сцену
    со своим представлением о ней значило бы сравнивать своё с собой
    (дословный урок ADR-913).
    """
    rows = census._open_counter_sites("<scene>", ast.parse(door.SCENE_SOURCE))
    assert len(rows) == 1, rows
    assert rows[0]["form"] == "form_get", rows[0]


def test_the_grown_scene_is_valid_python():
    """Сцена уезжает в дерево файлом: не разберись она, прогон упал бы ДО
    вопроса о населении, и прибор доложил бы о себе."""
    ast.parse(door.SCENE_SOURCE)


def test_the_scene_lands_in_a_directory_the_census_walks():
    """Сцена вне обходимых каталогов не сдвинула бы ничего."""
    assert any(door.GROWN_REL.startswith(sub + "/")
               for sub in census.OPEN_COUNTER_DIRS), census.OPEN_COUNTER_DIRS


# --------------------------------------------------------------------------- #
# 2. ПОВЕРХНОСТЬ — обе половины контроля
# --------------------------------------------------------------------------- #

def test_positive_control_finds_the_incident_form():
    """Не найдя формы аварии #1029, правило не вправе говорить о классе."""
    surf = _surface(BOMB)
    assert door.DOOR_LITERAL_LIVE in surf.doors, surf.as_dict()
    live = [s for s in surf.sites if s["door"] == door.DOOR_LITERAL_LIVE]
    assert len(live) == 1, live
    assert sorted(live[0]["declared"]) == [10, 16], live[0]


def test_negative_control_misses_a_literal_on_its_own_scene():
    """Литерал, объявляющий население СВОЕЙ сцены, бомбой не является."""
    surf = _surface(SCENE_ONLY)
    assert door.DOOR_LITERAL_LIVE not in surf.doors, surf.as_dict()
    assert door.DOOR_LITERAL_SCENE in surf.doors, surf.as_dict()


def test_negative_control_misses_a_neighbour_from_the_producer():
    """Лечение ADR-916 не имеет права числиться болезнью."""
    surf = _surface(PRODUCER)
    assert door.DOOR_PRODUCER in surf.doors, surf.as_dict()
    assert door.DOOR_LITERAL_LIVE not in surf.doors, surf.as_dict()


def test_a_neighbour_without_a_number_is_not_a_site():
    """Сосед без числа — проверка ОТКАЗА шага; населения он не объявляет."""
    surf = _surface(NO_NUMBER)
    assert door.DOOR_LITERAL_LIVE not in surf.doors, surf.as_dict()


def test_a_neighbour_bound_to_a_name_is_still_found():
    """«Не спрашивали» не имеет права совпасть с «признака нет» (инв. #17)."""
    surf = _surface(BOUND_NAME)
    assert door.DOOR_LITERAL_LIVE in surf.doors, surf.as_dict()
    live = [s for s in surf.sites if s["door"] == door.DOOR_LITERAL_LIVE]
    assert live and live[0]["declared"] == [158], live


#: Форма ЛОЖНОЙ площадки, измеренная 04.11: имя ``root`` связано с живым
#: корнем в ОДНОЙ функции и с ``tmp_path``-сценой в другой.
SCOPE_LEAK = '''
from pathlib import Path


def test_live():
    root = Path(C.__file__).resolve().parents[2]
    return root


def test_scene(tmp_path):
    root = _scene(tmp_path)
    out = sequence_members_of_the_whole_population(
        root, {"status": "MEASURED", "open_to_an_unnamed_class": 1})
    assert out["status"] == "MEASURED"
'''


def test_a_live_root_name_does_not_leak_across_scopes():
    """Признак, спрошенный не у того, о ком отвечают, — тот самый класс.

    До поправки 04.11 прибор насчитывал здесь площадку на ``tmp_path``, потому
    что имя ``root`` было связано с живым корнем в ЧУЖОЙ функции.
    """
    surf = _surface(SCOPE_LEAK)
    assert door.DOOR_LITERAL_LIVE not in surf.doors, surf.as_dict()
    assert door.DOOR_LITERAL_SCENE in surf.doors, surf.as_dict()


def test_a_root_taken_from_a_helper_is_still_live():
    """Обратная половина того же контроля: сузив правило до ``__file__`` в
    правой части, прибор потерял бы площадку, добытую ПОМОЩНИКОМ."""
    src = '''
from pathlib import Path


def _repo_root():
    return Path(__file__).resolve().parents[2]


def test_live():
    root = _repo_root()
    out = document_field_reader_in_file(root, {"status": "MEASURED",
                                               "unresolved_reasons": {"a": 7}})
    assert out["status"] == "MEASURED"
'''
    surf = _surface(src)
    assert door.DOOR_LITERAL_LIVE in surf.doors, surf.as_dict()


def test_an_unparsed_file_is_unmeasured_not_clean():
    """Третий исход: не разобрался ⇒ НЕ ИЗМЕРЕН, а не «признака нет»."""
    surf = _surface("def broken(:\n    pass\n")
    assert surf.unmeasured and "не разобран" in surf.unmeasured
    assert surf.doors == [] and surf.sites == []
    assert "doors" not in surf.as_dict()


def test_surface_without_the_test_dir_is_unmeasured(tmp_path):
    """Каталога нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не пустая поверхность."""
    out = door.measure_surface(tmp_path)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == "test_dir_absent"
    assert "surface_files" not in out


def test_live_root_is_read_from_a_zero_arg_maker_too():
    """Корень, добытый помощником, — тот же живой корень."""
    names, makers = door.live_root_names(ast.parse(BOUND_NAME))
    assert makers == {"_root"} and names == set()


# --------------------------------------------------------------------------- #
# 3. СЦЕНА: поставить и СНЯТЬ
# --------------------------------------------------------------------------- #

def test_apply_and_drop_the_scene(tmp_path):
    assert door.apply_scene(tmp_path, "base") is None
    target = door.apply_scene(tmp_path, "grown")
    assert target is not None and target.exists()
    assert target.read_text(encoding="utf-8") == door.SCENE_SOURCE
    assert door.drop_scene(tmp_path) is True
    assert door.drop_scene(tmp_path) is False


def test_a_second_scene_in_the_same_tree_refuses(tmp_path):
    """Второй прогон затёр бы слепок первого — и снять сцену было бы нечем
    (дословный порядок мутационного прибора, ADR-772 п. 5)."""
    door.apply_scene(tmp_path, "grown")
    with pytest.raises(RuntimeError, match="сцена уже стоит"):
        door.apply_scene(tmp_path, "grown")
    door.drop_scene(tmp_path)


def test_an_unknown_scene_refuses(tmp_path):
    with pytest.raises(ValueError, match="неизвестная сцена"):
        door.apply_scene(tmp_path, "shrunk")


# --------------------------------------------------------------------------- #
# 4. РАЗБОР ВЕРДИКТОВ
# --------------------------------------------------------------------------- #

def test_parse_outcomes_keeps_skipped_apart():
    out = door.parse_outcomes(
        "t.py::a PASSED [ 50%]\n"
        "t.py::b SKIPPED [ 75%]\n"
        "t.py::c FAILED [100%]\n"
        "это не строка вердикта\n")
    assert out == {"t.py::a": "PASSED", "t.py::b": "SKIPPED",
                   "t.py::c": "FAILED"}


# --------------------------------------------------------------------------- #
# 5. ДИФФЕРЕНЦИАЛЬНЫЙ ЗАМЕР — на инъектированном прогоне
# --------------------------------------------------------------------------- #

def _runner(base: dict, grown: dict):
    def run(tree_root, files, *, timeout_s, label):
        return (base if label == "base" else grown), f"tail {label}", 0
    return run


_OK_CANARY = {"status": "MEASURED", "base_sites": 290, "grown_sites": 291,
              "delta": 1}


def test_a_name_that_changes_verdict_is_a_member(tmp_path):
    out = door.differential(
        tmp_path, ["t.py"], timeout_s=1,
        runner=_runner({"t.py::bomb": "PASSED", "t.py::calm": "PASSED"},
                       {"t.py::bomb": "FAILED", "t.py::calm": "PASSED"}),
        canary_fn=lambda *a, **k: dict(_OK_CANARY))
    assert out["status"] == "MEASURED"
    assert out["member_files"] == ["t.py"]
    assert out["counts"]["changed"] == 1
    assert out["changed"][0]["nodeid"] == "t.py::bomb"


def test_a_tree_that_changes_nothing_has_no_members(tmp_path):
    out = door.differential(
        tmp_path, ["t.py"], timeout_s=1,
        runner=_runner({"t.py::calm": "PASSED"}, {"t.py::calm": "PASSED"}),
        canary_fn=lambda *a, **k: dict(_OK_CANARY))
    assert out["status"] == "MEASURED"
    assert out["member_files"] == [] and out["counts"]["changed"] == 0


def test_going_to_skipped_counts_as_a_change(tmp_path):
    """Урок #465: такой тест не краснеет и не проходит — он ИСЧЕЗАЕТ."""
    out = door.differential(
        tmp_path, ["t.py"], timeout_s=1,
        runner=_runner({"t.py::a": "PASSED"}, {"t.py::a": "SKIPPED"}),
        canary_fn=lambda *a, **k: dict(_OK_CANARY))
    assert out["counts"]["to_skipped"] == 1
    assert out["member_files"] == ["t.py"]


def test_a_vanished_name_counts_as_a_change(tmp_path):
    out = door.differential(
        tmp_path, ["t.py"], timeout_s=1,
        runner=_runner({"t.py::a": "PASSED"}, {}),
        canary_fn=lambda *a, **k: dict(_OK_CANARY))
    assert out["counts"]["vanished"] == 1
    assert out["changed"][0]["grown"] == "ABSENT"


def test_a_broken_canary_locks_the_answer(tmp_path):
    """Сцена не сдвинула население ⇒ ответа о классе НЕ ВЫДАЁТСЯ."""
    out = door.differential(
        tmp_path, ["t.py"], timeout_s=1,
        runner=_runner({"t.py::a": "PASSED"}, {"t.py::a": "FAILED"}),
        canary_fn=lambda *a, **k: {"status": "UNMEASURED", "delta": 0,
                                   "reason": "сцена НЕ сдвинула население"})
    assert out["status"] == "UNMEASURED"
    assert "member_files" not in out and "changed" not in out
    assert "канарейка" in out["reason"]


def test_an_empty_surface_is_unmeasured_not_an_empty_class(tmp_path):
    out = door.differential(tmp_path, [], timeout_s=1,
                            runner=_runner({}, {}),
                            canary_fn=lambda *a, **k: dict(_OK_CANARY))
    assert out["status"] == "UNMEASURED"
    assert "member_files" not in out


def test_the_scene_is_dropped_even_when_the_grown_run_raises(tmp_path):
    """Сцена, оставшаяся в дереве, есть байты, которых никто не писал
    (`.claude/rules/deployment.md`, § окна мутационного прибора)."""
    def boom(tree_root, files, *, timeout_s, label):
        if label == "grown":
            raise RuntimeError("прогон умер")
        return {"t.py::a": "PASSED"}, "", 0

    with pytest.raises(RuntimeError, match="прогон умер"):
        door.differential(tmp_path, ["t.py"], timeout_s=1, runner=boom,
                          canary_fn=lambda *a, **k: dict(_OK_CANARY))
    assert not (tmp_path / door.GROWN_REL).exists()


# --------------------------------------------------------------------------- #
# 5б. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ ПАЙПЛАЙНА — «членов 0» обязано быть проверяемым
# --------------------------------------------------------------------------- #

def test_the_bomb_is_valid_python_and_carries_the_literal():
    """Бомба уезжает в дерево файлом: не разберись она, прогон упал бы ДО
    вопроса о населении, и контроль доложил бы о себе."""
    src = door.BOMB_SOURCE.format(declared=4242)
    ast.parse(src)
    assert "4242" in src


def test_the_positive_control_accepts_a_bomb_that_reddens(tmp_path,
                                                          monkeypatch):
    monkeypatch.setattr(door, "live_declared_population",
                        lambda root, **kw: {"status": "MEASURED",
                                            "declared": 7})
    monkeypatch.setattr(door, "differential",
                        lambda *a, **kw: {"status": "MEASURED",
                                          "canary": dict(_OK_CANARY),
                                          "changed": [{"nodeid": "b::x",
                                                       "base": "PASSED",
                                                       "grown": "FAILED"}]})
    out = door.positive_control(tmp_path, timeout_s=1)
    assert out["status"] == "MEASURED" and out["declared"] == 7
    assert not (tmp_path / door.BOMB_REL).exists()


def test_the_positive_control_refuses_a_bomb_that_stays_green(tmp_path,
                                                              monkeypatch):
    """Не покраснела ⇒ рост до шага НЕ ДОХОДИТ, и «членов 0» есть свойство
    прибора, а не набора."""
    monkeypatch.setattr(door, "live_declared_population",
                        lambda root, **kw: {"status": "MEASURED",
                                            "declared": 7})
    monkeypatch.setattr(door, "differential",
                        lambda *a, **kw: {"status": "MEASURED",
                                          "canary": dict(_OK_CANARY),
                                          "changed": []})
    out = door.positive_control(tmp_path, timeout_s=1)
    assert out["status"] == "NOT_SATISFIED"
    assert "НЕ покраснела" in out["reason"]


def test_the_positive_control_is_unmeasured_when_the_chain_refuses(tmp_path,
                                                                   monkeypatch):
    """Третий исход: население не снято ⇒ бомбу собирать не из чего."""
    monkeypatch.setattr(door, "live_declared_population",
                        lambda root, **kw: {"unmeasured": "цепочка молчит"})
    out = door.positive_control(tmp_path, timeout_s=1)
    assert out["status"] == "UNMEASURED" and "цепочка молчит" in out["reason"]
    assert not (tmp_path / door.BOMB_REL).exists()


def test_the_bomb_is_removed_even_when_the_run_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(door, "live_declared_population",
                        lambda root, **kw: {"status": "MEASURED",
                                            "declared": 1})

    def boom(*a, **kw):
        raise RuntimeError("прогон умер")

    monkeypatch.setattr(door, "differential", boom)
    with pytest.raises(RuntimeError, match="прогон умер"):
        door.positive_control(tmp_path, timeout_s=1)
    assert not (tmp_path / door.BOMB_REL).exists()


# --------------------------------------------------------------------------- #
# 6. ОБЪЯВЛЕНИЕ — поверхность и члены суть РАЗНЫЕ числа
# --------------------------------------------------------------------------- #

def test_the_declaration_keeps_surface_and_members_apart():
    doc = door.declaration_from_measurement(
        {"surface_files": ["a.py", "b.py"], "counts": {"on_live_root": 2}},
        {"member_files": ["a.py"], "canary": dict(_OK_CANARY),
         "changed": [{"nodeid": "a.py::x", "base": "PASSED",
                      "grown": "FAILED"}]},
        sha="deadbeef", measured_at="2026-11-04T00:00:00Z")
    assert doc["surface_count"] == 2 and doc["member_count"] == 1
    assert doc["surface_files"] != doc["member_files"]
    assert doc["canary"]["delta"] == 1
    assert [m["nodeid"] for m in doc["members"]] == ["a.py::x"]
    # Потолок — ТОЛЬКО в объявлении, и равен длине перечня (ADR-912).
    assert doc["upper_bound"] == len(doc["members"])
    # Каждый член назвал замер, которым добыт: иначе имя дописано рукой.
    assert all(m["measured_in"] for m in doc["members"])
    json.dumps(doc, ensure_ascii=False)


def test_the_probe_agrees_on_a_whole_declaration():
    """Положительная половина: целое объявление ⇒ `satisfied`.

    «Целое» включает РАБОТУ карточки — такт и охват бомбы по всему ряду.
    Без этой половины проба зеленела бы на уже существующем объявлении, то
    есть мерила бы факт своего существования, а не исход работы.
    """
    got, why = ca._probe_literal_neighbour_class_declaration_holds(
        declaration=_whole_declaration(), module=ratchet)
    assert got == ca.SATISFIED, why
    assert "канарейка сдвинула население на 1" in why
    assert f"бомба накрывает {len(_row_steps())} шаг(ов)" in why


def test_the_probe_refuses_todays_declaration_on_purpose():
    """Отрицательная половина на ЖИВОМ объявлении: работа карточки НЕ сделана.

    Критерий объявлен ДО работы и мерит её ИСХОД. Зелёный ответ здесь был бы
    самосертификацией (`.claude/rules/acceptance.md` п. 1–2).
    """
    got, why = ca._probe_literal_neighbour_class_declaration_holds(
        declaration=ratchet.load_declaration(), module=ratchet)
    assert got == ca.NOT_SATISFIED, why
    assert "не называет ТАКТ" in why
    assert "не у всех шагов ряда" in why


def test_the_row_of_steps_is_read_from_the_producer():
    """Перечень шагов ряда — у производителя; литерал был бы своей меркой."""
    row = _row_steps()
    assert len(row) >= 10, row
    assert "UNMEASURED_DOC_POPULATION" in row


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d.update(canary={"delta": 0}), "НЕ сдвинула население"),
    (lambda d: d["members"][0].pop("measured_in"), "measured_in"),
    (lambda d: d["members"][0].update(nodeid="spa_core/tests/t_nope.py::x",
                                      file="spa_core/tests/t_nope.py"),
     "файла нет в дереве"),
    (lambda d: d.update(upper_bound=99), "граница 99"),
    (lambda d: d.update(surface_count=99), "поверхность 99"),
    (lambda d: d.pop("tact"), "не называет ТАКТ"),
    (lambda d: d.update(tact={"reader": "шаг 0-офис"}), "не называет ТАКТ"),
    (lambda d: d["positive_control"].update(steps_covered=[]),
     "не у всех шагов ряда"),
])
def test_the_probe_refuses_each_broken_link(mutate, expect):
    """Отрицательные половины: каждое порванное звено НАЗВАНО поимённо.

    Проба, зелёная на порванном звене, есть украшение
    (`.claude/rules/acceptance.md` п. 3).
    """
    doc = _whole_declaration()
    mutate(doc)
    got, why = ca._probe_literal_neighbour_class_declaration_holds(
        declaration=doc, module=ratchet)
    assert got == ca.NOT_SATISFIED, (got, why)
    assert expect in why, why


@pytest.mark.parametrize("doc,expect", [
    ({"canary": {"delta": 1}, "surface_files": []}, "`members` списком"),
    ({"members": [], "canary": {"delta": 1}}, "`surface_files` списком"),
    ({"members": [], "surface_files": [], "canary": {"delta": "много"}},
     "не назвала сдвиг числом"),
])
def test_the_probe_answers_unmeasured_not_a_verdict(doc, expect):
    """Третий исход (инв. #17): НЕ ИЗМЕРЕНО с причиной, а не отказ и не
    согласие. Слить его с `not_satisfied` значило бы выдать непрочитанное
    объявление за измеренную поломку."""
    got, why = ca._probe_literal_neighbour_class_declaration_holds(
        declaration=doc, module=ratchet)
    assert got == ca.UNMEASURED, (got, why)
    assert expect in why, why


def test_the_probe_is_unmeasured_when_the_guard_is_gone():
    """Сторожа нет ⇒ НЕ ИЗМЕРЕНО, а не «объявление в порядке»."""
    class Broken:
        @staticmethod
        def load_declaration():
            raise FileNotFoundError("объявления нет")

    got, why = ca._probe_literal_neighbour_class_declaration_holds(
        module=Broken)
    assert got == ca.UNMEASURED and "FileNotFoundError" in why


def test_an_empty_class_is_a_legal_answer_of_the_probe():
    """«Класс пуст» — законный ответ ПРИБОРА, и проба не вправе звать его
    поломкой: доказывает его канарейка со сдвинутым населением."""
    doc = _whole_declaration()
    doc.update(members=[], member_count=0, upper_bound=0, member_files=[])
    got, why = ca._probe_literal_neighbour_class_declaration_holds(
        declaration=doc, module=ratchet)
    assert got == ca.SATISFIED, why


def test_the_probe_is_registered_under_its_name():
    assert (ca.PROBES["literal_neighbour_class_declaration_holds"]
            is ca._probe_literal_neighbour_class_declaration_holds)


def test_the_live_declaration_matches_the_instrument(tmp_path):
    """Объявление на диске обязано говорить о ТЕХ ЖЕ полях, что прибор.

    Контракт объявления живёт в ОДНОМ месте — у производителя; своя копия
    перечня полей была бы меркой, которой сторож мерит сам себя (ADR-916 C).
    """
    baseline = (Path(__file__).resolve().parent
                / "literal_neighbour_class_baseline.json")
    assert baseline.is_file(), baseline
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    sample = door.declaration_from_measurement(
        {"surface_files": [], "counts": {"on_live_root": 0}},
        {"member_files": [], "canary": dict(_OK_CANARY), "changed": []},
        sha="x", measured_at="x")
    assert sorted(doc) == sorted(sample), (sorted(doc), sorted(sample))
    assert doc["order"] == "G907.2"
    assert doc["member_count"] == len(doc["member_files"])
    assert doc["surface_count"] == len(doc["surface_files"])
    assert doc["canary"]["delta"] >= 1, doc["canary"]
