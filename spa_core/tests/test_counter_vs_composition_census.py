#!/usr/bin/env python3
"""Контроль прибора ADR-1110: «сторож закрепляет СЧЁТЧИК там, где предмет — СОСТАВ».

Каждая проверка здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ настоящего промаха, а не украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»). Промахи, которые
воспроизводятся ниже, были СДЕЛАНЫ этим прибором и измерены на живом корпусе, а не
придуманы:

* первая редакция формы отвечала **1310** членов из 2612 файлов — «любое целое против
  чего-то вычисленного», то есть ровно «перепись врёт в сторону находки»;
* вторая теряла ИЗВЕСТНОГО члена, потому что снимала предмет по закреплению состава
  у СОСЕДА по модулю, а соседом у известного члена был словарь ДВУХ ПОРОГОВ
  (`{"cap": 0.20, "cost": 0.0}`), а не контейнер имён;
* третья считала `ast.walk(tree)` перечислением каталога — дословно урок #1218
  («имя метода мерой НЕ является»), и объявляла предметом сцены, где корпуса нет;
* четвёртая не спрашивала, происходит ли корень перечисления от `__file__`, и числила
  предметом одноразовые сцены `create_card(..., tracker_dir=tmp_path)`.

Траектория замера на одном и том же дереве: **1310 → 100 → 83 → 136 → 123 → 37 → 0**
при вилке `0 … 3`. Каждое сужение сверено с известным членом В ОБЕ СТОРОНЫ; форма,
теряющая известного члена, класс не сужает, а ПОДМЕНЯЕТ.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBER = ROOT / "scripts" / "counter_vs_composition_census.py"
#: Побайтовая копия ИЗВЕСТНОГО ЧЛЕНА — состояние
#: `spa_core/tests/test_edge_boundary_dataflow_census.py` на `2fb147b7a^`
#: (md5 `f3d992625329910d4a9208576d26cf50`), то есть ДО починки #1254.
FIXTURE_BEFORE = Path(__file__).resolve().parent / "fixtures" / \
    "counter_vs_composition_known_member_before.py.txt"
#: Живой файл — состояние ПОСЛЕ починки #1254 (карта `CENSUS_100_SCREEN`).
LIVE_AFTER = ROOT / "spa_core" / "tests" / "test_edge_boundary_dataflow_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("cvc_prober", PROBER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cvc = _load()


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(textwrap.dedent(text), encoding="utf-8")
    return tmp_path


def _census(tmp_path: Path, files: dict[str, str]) -> dict:
    return cvc.census(_tree(tmp_path, files))


_CORPUS_HELPER = '''
    import contextlib
    from pathlib import Path

    def collect(root):
        return {"buckets": {"A": sorted(str(p) for p in Path(root).glob("*.py"))}}

    def section1_census(root):
        return {"population": 7, "buckets": {"A": sorted(Path(root).glob("*.py"))}}

    @contextlib.contextmanager
    def corpus_without_self(root):
        yield from (str(p) for p in Path(root).glob("*.py"))

    def required(node):
        return {}
'''

_MEMBER_SCENE = '''
    from pathlib import Path
    import helper

    ROOT = Path(__file__).resolve().parents[2]
    CORPUS = ROOT / "scripts"

    class T:
        def test_population(self):
            census = helper.collect(CORPUS)
            buckets = {k: len(v) for k, v in census["buckets"].items()}
            self.assertEqual(buckets["A"], 7)
'''


# ─────────────────────── известный член, ОБЕ стороны ───────────────────────

def test_the_known_member_before_the_fix_is_named_a_member(tmp_path):
    """Сквозной контроль на НАСТОЯЩИХ байтах: до починки #1254 — ЧЛЕН.

    Фрагмент бы здесь не годился: именно фрагментный контроль ОДИН РАЗ зеленел на
    форме, которая на целом файле известного члена ТЕРЯЛА.
    """
    assert FIXTURE_BEFORE.is_file(), f"фикстуры нет: {FIXTURE_BEFORE}"
    res = _census(tmp_path, {
        "spa_core/tests/test_known.py": FIXTURE_BEFORE.read_text(encoding="utf-8"),
        "scripts/edge_boundary_dataflow_census.py": _CORPUS_HELPER,
        "scripts/edge_split_protocol_diagnostic.py": _CORPUS_HELPER,
    })
    assert len(res["subject"]) == 1, json.dumps(res["subject"], ensure_ascii=False)
    assert res["subject"][0]["function"] == \
        "test_the_census_screens_the_population_100_published"


def test_the_known_nonmember_after_the_fix_is_not_a_member(tmp_path):
    """Обратная сторона на живом файле: после починки #1254 состав ЗАКРЕПЛЁН."""
    res = _census(tmp_path, {
        "spa_core/tests/test_known.py": LIVE_AFTER.read_text(encoding="utf-8"),
        "scripts/edge_boundary_dataflow_census.py": _CORPUS_HELPER,
        "scripts/edge_split_protocol_diagnostic.py": _CORPUS_HELPER,
    })
    assert res["subject"] == [], json.dumps(res["subject"], ensure_ascii=False)
    assert res["names_pinned_same_scene"] >= 1


def test_a_neighbour_pin_over_a_foreign_population_does_not_clear_the_subject(tmp_path):
    """Тот самый промах: пин у СОСЕДА снимал предмет и терял известного члена.

    Соседняя сцена закрепляет словарь ДВУХ ПОРОГОВ — к составу корпуса он не
    относится никак. Снимать предмет по такому соседу значило бы объявить
    охранённым ровно тот случай, ради которого класс измерен.
    """
    scene = _MEMBER_SCENE + '''
        def test_the_probe_shape(self):
            self.assertEqual(helper.required(None), {"cap": 0.20, "cost": 0.0})
    '''
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene,
                             "scripts/helper.py": _CORPUS_HELPER})
    assert len(res["subject"]) == 1, "сосед с порогами не охраняет состав корпуса"


def test_a_dict_of_thresholds_is_not_a_container_of_names():
    """Строки в позиции КЛЮЧА контейнером имён не делают (замер на известном члене)."""
    import ast
    thresholds = ast.parse('{"cap": 0.20, "cost": 0.0}').body[0].value
    names = ast.parse('("a.py", "b.py")').body[0].value
    assert cvc._is_name_container(thresholds) is False
    assert cvc._is_name_container(names) is True


def test_one_named_member_is_not_a_pinned_composition():
    """`assertIn("x.py", …)` называет ОДНОГО из тридцати пяти — это не состав."""
    import ast
    single = ast.parse('["edge_downside_parity.py"]').body[0].value
    assert cvc._is_name_container(single) is False


# ─────────────────────── ось «перечисление каталога» ───────────────────────

def test_ast_walk_is_not_a_directory_enumeration():
    """`ast.walk` обходит СИНТАКСИЧЕСКОЕ дерево; владелец решает, а не имя."""
    import ast
    assert cvc._enumerates_corpus(ast.parse("ast.walk(tree)")) is False
    assert cvc._enumerates_corpus(ast.parse("os.walk(root)")) is True
    assert cvc._enumerates_corpus(ast.parse("Path(root).glob('*.py')")) is True


def test_stdlib_is_not_an_unresolved_hop(tmp_path):
    """«Модуля `math` в дереве нет» причиной НЕ является — он не ходит по диску."""
    scene = '''
    from pathlib import Path
    import math

    ROOT = Path(__file__).resolve().parents[2]

    class T:
        def test_x(self):
            vals = math.fsum([1.0]), Path(ROOT).glob("*.py")
            self.assertEqual(len(list(vals[1])), 3)
    '''
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene})
    assert res["members_backing_unresolved"] == []


# ─────────────────────── ось «корень от __file__» ───────────────────────

def test_a_disposable_scene_is_not_the_subject(tmp_path):
    """Корень от фикстуры `tmp_path`: состав задан теми же строками, что считают."""
    scene = '''
    from pathlib import Path

    def test_two_files(tmp_path):
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "b.md").write_text("b")
        assert len(list(Path(tmp_path).glob("*.md"))) == 2
    '''
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene})
    assert res["subject"] == []


def test_a_fixture_built_tree_in_setUp_is_not_the_subject(tmp_path):
    """Одноразовое дерево строит `setUp`, а не сам метод — спрашивать надо КЛАСС."""
    scene = '''
    import tempfile
    from pathlib import Path

    class T:
        def setUp(self):
            self.tmp = tempfile.mkdtemp()

        def test_one(self):
            made = list(Path(self.tmp).glob("*.md"))
            self.assertEqual(len(made), 1, made)
    '''
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene})
    assert res["subject"] == []
    assert len(res["members_disposable_scene"]) + \
        len(res["members_not_repo_rooted"]) == 1


# ─────────────────────── прочие оси предмета ───────────────────────

def test_zero_is_not_pinned(tmp_path):
    """Пустой состав определён своим числом однозначно — подменять нечего."""
    scene = _MEMBER_SCENE.replace('self.assertEqual(buckets["A"], 7)',
                                  'self.assertEqual(buckets["A"], 0)')
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene,
                             "scripts/helper.py": _CORPUS_HELPER})
    assert res["subject"] == []


def test_a_counter_named_key_is_not_structural_proof(tmp_path):
    """`census["population"]` — ИМЯ ключа, а не доказательство мощности."""
    scene = _MEMBER_SCENE.replace(
        'buckets = {k: len(v) for k, v in census["buckets"].items()}\n'
        '            self.assertEqual(buckets["A"], 7)',
        'self.assertEqual(census["population"], 7)')
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene,
                             "scripts/helper.py": _CORPUS_HELPER})
    assert res["subject"] == []
    assert res["by_key_name_only"] == 1


def test_a_filter_pinned_identity_is_not_the_subject(tmp_path):
    """Отбор по НАЗВАННОЙ личности закрепляет состав сам: подмена двинет число."""
    scene = '''
    import ast
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    STAGE = "my_stage"

    class T:
        def test_called_once(self):
            tree = ast.parse((ROOT / "scripts" / "helper.py").read_text())
            calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and getattr(n.func, "id", "") == STAGE]
            self.assertEqual(len(calls), 1)
    '''
    res = _census(tmp_path, {"spa_core/tests/test_x.py": scene,
                             "scripts/helper.py": _CORPUS_HELPER})
    assert res["subject"] == []
    assert res["composition_pinned_by_filter"] == 1


def test_a_genuine_member_is_still_found(tmp_path):
    """Синтетический контур целиком: корпус от `__file__`, хоп, состав НЕ закреплён."""
    res = _census(tmp_path, {"spa_core/tests/test_x.py": _MEMBER_SCENE,
                             "scripts/helper.py": _CORPUS_HELPER})
    assert len(res["subject"]) == 1
    assert "helper.py:collect" in res["subject"][0]["backing"]["via"]


# ─────────────────────── три исхода (инв. #17) ───────────────────────

def test_an_unparseable_file_is_unmeasured_not_clean(tmp_path):
    """НЕ РАЗОБРАНО — третий исход с причиной, а не «чисто»."""
    res = _census(tmp_path, {"spa_core/tests/test_broken.py": "def f(:\n"})
    assert len(res["unmeasured"]) == 1
    assert "разбор не удался" in res["unmeasured"][0]["reason"]


def test_an_empty_surface_is_unmeasured_not_clean(tmp_path):
    """Поверхность пуста ⇒ НЕ ИЗМЕРЕНО, а не «членов нет»."""
    res = cvc.census(tmp_path)
    assert res["state"] == "unmeasured"
    assert "поверхность пуста" in res["reason"]


def test_the_three_exit_codes_are_distinguishable(tmp_path):
    """0 — членов нет · 1 — члены НАЗВАНЫ · 2 — НЕ ИЗМЕРЕНО."""
    clean = _tree(tmp_path / "clean", {"spa_core/tests/test_ok.py": "def test_x():\n    pass\n"})
    member = _tree(tmp_path / "member", {"spa_core/tests/test_x.py": _MEMBER_SCENE,
                                        "scripts/helper.py": _CORPUS_HELPER})
    broken = _tree(tmp_path / "broken", {"spa_core/tests/test_b.py": "def f(:\n"})
    codes = {}
    for label, root in (("clean", clean), ("member", member), ("broken", broken)):
        codes[label] = subprocess.run(
            [sys.executable, str(PROBER), "--repo-root", str(root)],
            capture_output=True, text=True).returncode
    assert codes == {"clean": 0, "member": 1, "broken": 2}, codes


def test_an_unexpected_crash_is_code_2_not_code_1(monkeypatch):
    """Падение с кодом 1 выдало бы «не измерено» за находку (инв. #17).

    Дверь ставится ЕДИНСТВЕННЫМ установщиком с возвратом: подмена, пережившая
    сцену, вредит СОСЕДУ по процессу, а не автору (`deployment.md`, § двенадцатая
    дверь).
    """
    def boom(*_a, **_kw):
        raise RuntimeError("дверь сломана")

    monkeypatch.setattr(cvc, "main", boom)
    assert cvc._guarded([]) == 2


def test_the_self_check_refuses_when_the_form_loses_the_known_member(monkeypatch):
    """Контроль обязан КРАСНЕТЬ на форме, которая известного члена теряет."""
    monkeypatch.setattr(cvc, "_is_name_container", lambda node: True)
    verdict = cvc.self_check(ROOT)
    assert verdict["ok"] is False
    assert any("членом НЕ назван" in p for p in verdict["problems"])


def test_the_cli_refuses_to_print_numbers_when_the_control_fails(tmp_path):
    """Контроль не сошёлся ⇒ код 2 и НИ ОДНОГО числа переписи в выводе."""
    broken = PROBER.read_text(encoding="utf-8").replace(
        "def _is_name_container(node: ast.AST) -> bool:",
        "def _is_name_container(node: ast.AST) -> bool:\n    return True\n", 1)
    assert broken != PROBER.read_text(encoding="utf-8")
    copy = tmp_path / "broken_prober.py"
    copy.write_text(broken, encoding="utf-8")
    res = subprocess.run([sys.executable, str(copy), "--repo-root", str(ROOT)],
                         capture_output=True, text=True)
    assert res.returncode == 2, res.stdout + res.stderr
    assert "ПРЕДМЕТ" not in res.stdout


def test_the_prober_names_which_tree_it_answered_about(tmp_path):
    """Умолчание ПЕЧАТАЕТСЯ: молча подставить своё дерево хуже ошибки."""
    root = _tree(tmp_path, {"spa_core/tests/test_ok.py": "def test_x():\n    pass\n"})
    named = subprocess.run([sys.executable, str(PROBER), "--repo-root", str(root)],
                           capture_output=True, text=True)
    assert "НАЗВАН входом" in named.stdout
    default = subprocess.run([sys.executable, str(PROBER)], cwd=str(root),
                             capture_output=True, text=True)
    assert "УМОЛЧАНИЕ" in default.stdout


def test_the_prober_itself_is_not_a_member_of_its_own_class():
    """Новый сторож не имеет права войти в класс, который мерит.

    Замер цикла #1182: новый прибор вышел НОВЫМ членом класса, который мерит
    (90 → 91). Вопрос задаётся прибором, а не глазами.
    """
    verdict = cvc.classify_module(
        Path(__file__).read_text(encoding="utf-8"), "self", ROOT, {})
    assert verdict["state"] == "parsed"
    corpus_backed = [m for m in verdict["members"]
                     if m["backing"]["state"] == "corpus"]
    assert corpus_backed == [], corpus_backed




# ───────────────────── контроль САМОЙ пробы приёмки ─────────────────────
# `.claude/rules/acceptance.md` п. 3: проба регистрируется только с тестом, где она
# зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с названным звеном.

from spa_core.monitoring import card_acceptance as _ca  # noqa: E402

PROBE = "counter_pins_composition_not_only_count"


def _probe(root: Path, arg: str | None = None) -> tuple[str, str]:
    return _ca.PROBES[PROBE](arg, repo_root=str(root))


def _whole_contour(tmp_path: Path) -> Path:
    """Одноразовое дерево с ЦЕЛЫМ контуром: прибор, фикстура, чистая поверхность."""
    root = tmp_path / "contour"
    (root / "scripts").mkdir(parents=True)
    (root / "spa_core" / "tests" / "fixtures").mkdir(parents=True)
    (root / "scripts" / "counter_vs_composition_census.py").write_text(
        PROBER.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "spa_core" / "tests" / "fixtures" /
     "counter_vs_composition_known_member_before.py.txt").write_text(
        FIXTURE_BEFORE.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "spa_core" / "tests" / "test_ok.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8")
    (root / "scripts" / "edge_boundary_dataflow_census.py").write_text(
        textwrap.dedent(_CORPUS_HELPER), encoding="utf-8")
    (root / "scripts" / "edge_split_protocol_diagnostic.py").write_text(
        textwrap.dedent(_CORPUS_HELPER), encoding="utf-8")
    return root


def test_probe_is_satisfied_on_the_whole_contour(tmp_path):
    verdict, detail = _probe(_whole_contour(tmp_path))
    assert verdict == _ca.SATISFIED, detail
    assert "вилке" in detail and "НЕ РАЗОБРАНО 0" in detail


def test_probe_is_satisfied_on_the_live_tree(tmp_path):
    """Живое дерево — тот же вердикт; иначе проба зелена только на синтетике."""
    verdict, detail = _probe(ROOT)
    assert verdict == _ca.SATISFIED, detail


def test_probe_refuses_an_argument(tmp_path):
    verdict, detail = _probe(_whole_contour(tmp_path), "spa_core/tests")
    assert verdict == _ca.UNMEASURED
    assert "не принимает аргумента" in detail


def test_probe_unmeasured_when_the_prober_is_absent(tmp_path):
    root = _whole_contour(tmp_path)
    (root / "scripts" / "counter_vs_composition_census.py").unlink()
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "прибора нет в названном дереве" in detail


def test_probe_unmeasured_when_the_known_member_fixture_is_absent(tmp_path):
    root = _whole_contour(tmp_path)
    (root / "spa_core" / "tests" / "fixtures" /
     "counter_vs_composition_known_member_before.py.txt").unlink()
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "фикстуры известного члена нет" in detail


def test_probe_unmeasured_when_the_prober_does_not_import(tmp_path):
    root = _whole_contour(tmp_path)
    (root / "scripts" / "counter_vs_composition_census.py").write_text(
        "def broken(:\n", encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "не импортируется" in detail


def test_probe_unmeasured_when_a_door_is_missing(tmp_path):
    root = _whole_contour(tmp_path)
    target = root / "scripts" / "counter_vs_composition_census.py"
    target.write_text(target.read_text(encoding="utf-8").replace(
        "def census(repo_root: Path) -> dict:", "def _census_renamed(repo_root):", 1),
        encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "нет двери `census`" in detail


def test_probe_unmeasured_when_the_form_loses_the_known_member(tmp_path):
    """Самое важное звено: форма, теряющая известного члена, НЕ зеленеет."""
    root = _whole_contour(tmp_path)
    target = root / "scripts" / "counter_vs_composition_census.py"
    target.write_text(target.read_text(encoding="utf-8").replace(
        "def _measured_cardinality(node: ast.AST, derived: set[str],\n"
        "                          card_names: set[str]) -> bool:",
        "def _measured_cardinality(node, derived, card_names) -> bool:\n"
        "    return False\n", 1), encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "ПОТЕРЯЛА известного члена" in detail or "НЕ СОШЁЛСЯ" in detail


def test_probe_not_satisfied_when_the_subject_is_not_empty(tmp_path):
    """Предмет непуст ⇒ находка НАЗВАНА, а не «проба не выполнена молча»."""
    root = _whole_contour(tmp_path)
    (root / "spa_core" / "tests" / "test_member.py").write_text(
        textwrap.dedent(_MEMBER_SCENE), encoding="utf-8")
    (root / "scripts" / "helper.py").write_text(
        textwrap.dedent(_CORPUS_HELPER), encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == _ca.NOT_SATISFIED, detail
    assert "test_member.py::test_population" in detail


def test_probe_unmeasured_when_a_surface_file_is_unparseable(tmp_path):
    root = _whole_contour(tmp_path)
    (root / "spa_core" / "tests" / "test_broken.py").write_text(
        "def f(:\n", encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "НЕ РАЗОБРАНЫ" in detail


def test_probe_unmeasured_when_the_surface_is_empty(tmp_path):
    root = _whole_contour(tmp_path)
    (root / "spa_core" / "tests" / "test_ok.py").unlink()
    verdict, detail = _probe(root)
    assert verdict == _ca.UNMEASURED
    assert "поверхность пуста" in detail


def test_probe_does_not_pass_by_substring(tmp_path):
    """Объявление в комментарии критерия не выполняет (ADR-333)."""
    root = _whole_contour(tmp_path)
    (root / "spa_core" / "tests" / "test_claim.py").write_text(
        "# counter_pins_composition_not_only_count: предмет пуст, честное слово\n"
        "def test_x():\n    pass\n", encoding="utf-8")
    (root / "scripts" / "counter_vs_composition_census.py").unlink()
    verdict, _ = _probe(root)
    assert verdict == _ca.UNMEASURED


def test_probe_is_registered_under_its_declared_name():
    assert PROBE in _ca.PROBES


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
