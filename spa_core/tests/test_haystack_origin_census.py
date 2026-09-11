#!/usr/bin/env python3
"""Приёмка прибора «откуда пришло содержимое стога» (заказ #568, ADR-343).

Каждый тест здесь — положительный контроль: он воспроизводит НАЗВАННУЮ заказом
ловушку или дефект, найденный при постройке прибора, и краснеет, если защита
снята. Синтетическое дерево строится в tmp и повторяет форму набора (каталоги
`tests/`, `spa_core/tests/`), потому что население прибор берёт у
`substring_structure_assertions.forward_sites`, а тот ходит по этим каталогам.

Ни один существующий тест этим файлом не правится, не скипается и не сужается
(инв. #16).
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import haystack_origin_census as H
from spa_core.tests._freshness import now_utc

NOW = now_utc()


# ────────────────────── синтетическое дерево ──────────────────────

def _tree(files: dict) -> TemporaryDirectory:
    """Дерево-песочница: {относительный путь: текст}. Возвращает сам каталог."""
    tmp = TemporaryDirectory()
    root = Path(tmp.name)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp


#: Модуль-сосед под корнем дерева: он НЕСЁТ структуру, о которой судит тест.
NEIGHBOUR = '''
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SPEC = {"report.json": ("status", "counts", "blindness")}
'''


def _verdict(doc: dict, file_suffix: str, line: int = None) -> dict:
    for name in ("repo_neighbour", "repo_copy"):
        for row in doc["split"][name]:
            if row["file"].endswith(file_suffix) and (line is None or row["line"] == line):
                return {"verdict": name, **row}
    for row in doc["split"]["self_written"]:
        if row["file"].endswith(file_suffix) and (line is None or row["line"] == line):
            return {"verdict": "self_written", **row}
    for row in doc["split"]["unmeasured"]:
        if row["file"].endswith(file_suffix) and (line is None or row["line"] == line):
            return {"verdict": "unmeasured", **row}
    raise AssertionError(f"сайт {file_suffix}:{line} вообще не попал в население — "
                         f"замер отвечает не на тот вопрос")


class TestSeparation(unittest.TestCase):
    """Разделение — ПРОИСХОЖДЕНИЕМ ЗНАЧЕНИЯ, и обе стороны достижимы."""

    def test_a_real_neighbour_named_by_os_path_join_is_repo_side(self):
        """Авария границы #568: путь назван `open()` + `os.path.join`, и ADR-338
        отложил сайт как «не свернулся». Файл при этом лежит в репозитории."""
        tmp = _tree({
            "pkg/neighbour.py": NEIGHBOUR,
            "tests/test_x.py": '''
import os
import unittest
from pkg import neighbour as N


class T(unittest.TestCase):
    def test_it(self):
        path = os.path.join(N.REPO_ROOT, "pkg", "neighbour.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('"report.json": ("status", "counts",', src)
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_x.py")
        self.assertEqual(got["verdict"], "repo_neighbour", got)
        self.assertEqual(got["repo_file"], "pkg/neighbour.py")

    def test_a_file_the_test_wrote_itself_is_not_the_subject(self):
        """Тест пишет файл и судит о СВОИХ ЖЕ байтах — предмета заказа нет."""
        tmp = _tree({
            "tests/test_y.py": '''
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class T(unittest.TestCase):
    def test_it(self):
        box = TemporaryDirectory()
        card = Path(box.name) / "card.md"
        card.write_text('SPEC = {"report.json": ("status", "counts")}\\n',
                        encoding="utf-8")
        self.assertIn('"report.json": ("status", "counts",', card.read_text())
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_y.py")
        self.assertEqual(got["verdict"], "self_written", got)

    def test_a_fixture_copying_a_repo_file_keeps_the_subject(self):
        """ПЕРВАЯ ПОЛОВИНА ЛОВУШКИ ЗАКАЗА, дословно: фикстура копирует
        НАСТОЯЩИЙ файл репозитория во временный каталог. Путь ведёт в tmp,
        запись по нему есть — и всё-таки предмет ЕСТЬ, потому что содержимое
        пришло из-под корня дерева."""
        tmp = _tree({
            "pkg/neighbour.py": NEIGHBOUR,
            "tests/test_z.py": '''
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pkg import neighbour as N


class T(unittest.TestCase):
    def test_it(self):
        box = TemporaryDirectory()
        copy = Path(box.name) / "neighbour.py"
        src_path = os.path.join(N.REPO_ROOT, "pkg", "neighbour.py")
        copy.write_text(Path(src_path).read_text(encoding="utf-8"), encoding="utf-8")
        self.assertIn('"report.json": ("status", "counts",', copy.read_text())
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_z.py")
        self.assertEqual(got["verdict"], "repo_copy", got)
        self.assertEqual(got["repo_file"], "pkg/neighbour.py")

    def test_an_interprocedural_helper_write_still_counts_as_self_written(self):
        """Хелпер пишет файл и ВОЗВРАЩАЕТ его, тест читает возвращённое.

        Без подстановки параметров терм записи и терм чтения жили бы в разных
        системах координат и не совпали бы никогда — «написан тестом»
        выродилось бы в «не измерено» на всём населении фикстур.
        """
        tmp = _tree({
            "tests/test_h.py": '''
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _card(box, name="own.md"):
    p = Path(box) / name
    p.write_text('SPEC = {"report.json": ("status", "counts")}\\n', encoding="utf-8")
    return p


class T(unittest.TestCase):
    def test_it(self):
        box = TemporaryDirectory()
        card = _card(box.name)
        self.assertIn('"report.json": ("status", "counts",', card.read_text())
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_h.py")
        self.assertEqual(got["verdict"], "self_written", got)


    def test_a_write_inside_a_side_effect_helper_is_still_found(self):
        """Хелпер зовётся РАДИ ПОБОЧНОГО ДЕЙСТВИЯ, путь собирается в тесте.

        Кадр такого хелпера при разрешении ЧТЕНИЯ не посещается никогда, и без
        второго рода кадров сайт ушёл бы в «не измерено» по свойству ПРИБОРА, а
        не предмета. Сцена различает и подстановку: без неё терм записи остался
        бы в системе координат хелпера.
        """
        tmp = _tree({
            "tests/test_side.py": '''
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _seed(box, name="own.md"):
    (Path(box) / name).write_text(
        'SPEC = {"report.json": ("status", "counts")}', encoding="utf-8")


class T(unittest.TestCase):
    def test_it(self):
        box = TemporaryDirectory()
        _seed(box.name)
        card = Path(box.name) / "own.md"
        self.assertIn('"report.json": ("status", "counts",', card.read_text())
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_side.py")
        self.assertEqual(got["verdict"], "self_written", got)


class TestTheNamedTrap(unittest.TestCase):
    """Ловушка заказа: имя переменной — ПРИЗНАК, и он ошибается в обе стороны."""

    def test_a_tmp_looking_name_pointing_at_a_repo_file_is_repo_side(self):
        """Имя кричит «временный», а читается файл репозитория."""
        tmp = _tree({
            "pkg/neighbour.py": NEIGHBOUR,
            "tests/test_sign_a.py": '''
import os
import unittest
from pkg import neighbour as N


class T(unittest.TestCase):
    def test_it(self):
        tmpdir_src = os.path.join(N.REPO_ROOT, "pkg", "neighbour.py")
        with open(tmpdir_src, encoding="utf-8") as fh:
            temp_text = fh.read()
        self.assertIn('"report.json": ("status", "counts",', temp_text)
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_sign_a.py")
        self.assertEqual(got["verdict"], "repo_neighbour", got)
        self.assertTrue(
            doc["name_sign_vs_measure"]["sign_says_tmp_but_measure_says_repo"],
            "признак назвал бы этот сайт временным — расхождение обязано быть "
            "названо поимённо, иначе ловушка не измерена, а пересказана")

    def test_an_honest_looking_name_pointing_at_generated_text_is_self_written(self):
        """Обратная сторона: имя `repo_src` указывает на сгенерированный текст."""
        tmp = _tree({
            "tests/test_sign_b.py": '''
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class T(unittest.TestCase):
    def test_it(self):
        box = TemporaryDirectory()
        repo_src = Path(box.name) / "neighbour.py"
        repo_src.write_text('SPEC = {"report.json": ("status", "counts")}\\n',
                            encoding="utf-8")
        self.assertIn('"report.json": ("status", "counts",', repo_src.read_text())
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_sign_b.py")
        self.assertEqual(got["verdict"], "self_written", got)

    def test_name_sign_never_decides_a_verdict(self):
        """МУТАЦИЯ: вычистить из дерева всякий след слов `tmp`/`temp`.

        Вердикты обязаны остаться теми же до единого. Если хоть один поменялся —
        значит имя участвует в решении, то есть прибор воспроизводит ровно тот
        дефект, против которого написан.
        """
        files = {
            "pkg/neighbour.py": NEIGHBOUR,
            "tests/test_m.py": '''
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pkg import neighbour as N


class T(unittest.TestCase):
    def test_repo(self):
        path = os.path.join(N.REPO_ROOT, "pkg", "neighbour.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('"report.json": ("status", "counts",', src)

    def test_own(self):
        tmpdir = TemporaryDirectory()
        card = Path(tmpdir.name) / "card.md"
        card.write_text('SPEC = {"report.json": ("status", "counts")}\\n',
                        encoding="utf-8")
        self.assertIn('"report.json": ("status", "counts",', card.read_text())
''',
        }
        with _tree(files) as before_dir:
            before = H.measure(Path(before_dir), now=NOW)
        renamed = dict(files)
        renamed["tests/test_m.py"] = (
            files["tests/test_m.py"]
            .replace("TemporaryDirectory", "BoxMaker")
            .replace("tmpdir", "box")
            .replace("from tempfile import BoxMaker",
                     "from tempfile import TemporaryDirectory as BoxMaker"))
        with _tree(renamed) as after_dir:
            after = H.measure(Path(after_dir), now=NOW)

        def shape(doc):
            return {k: sorted((r["file"], r["line"]) for r in v)
                    for k, v in doc["split"].items() if k != "unmeasured"}

        self.assertEqual(shape(before), shape(after),
                         "переименование убрало/добавило вердикт — имя решает")
        self.assertEqual(before["counts"]["repo_neighbour"], 1)
        self.assertEqual(before["counts"]["self_written"], 1)

    def test_the_sign_answers_where_the_measurement_refuses(self):
        """Главное свойство признака: он отвечает ВСЕГДА, в том числе там, где
        происхождение не прослежено. Это считается, а не оговаривается."""
        tmp = _tree({
            "tests/test_u.py": '''
import json
import unittest
from pathlib import Path


class T(unittest.TestCase):
    def test_it(self, box=None):
        state = Path(box) / "state.json"
        live = Path(json.loads(state.read_text())["pushes"][-1]["card"])
        self.assertIn('"report.json": ("status", "counts",',
                      live.read_text(encoding="utf-8"))
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_u.py")
        self.assertEqual(got["verdict"], "unmeasured", got)
        refuses = doc["name_sign_vs_measure"]["sign_answers_where_measure_refuses"]
        self.assertTrue(any(r["file"].endswith("test_u.py") for r in refuses),
                        "признак обязан быть показан отвечающим там, где замер "
                        "отказался — иначе цена подмены не измерена")


class TestTheThirdOutcome(unittest.TestCase):
    """«Не измерено» с НАЗВАННОЙ причиной, и никогда — «временный»."""

    def test_a_runtime_named_path_is_unmeasured_with_its_own_reason(self):
        """Путь назван СОДЕРЖИМЫМ другого файла: статикой он не определён по
        построению, и причина обязана сказать именно это. Прежняя редакция
        писала «словарь не сведён» — и свойство ПРЕДМЕТА читалось как
        недоработка ПРИБОРА."""
        tmp = _tree({
            "tests/test_r.py": '''
import json
import unittest
from pathlib import Path


class T(unittest.TestCase):
    def test_it(self, box=None):
        state = Path(box) / "state.json"
        live = Path(json.loads(state.read_text())["pushes"][-1]["card"])
        self.assertIn('"report.json": ("status", "counts",',
                      live.read_text(encoding="utf-8"))
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_r.py")
        self.assertEqual(got["verdict"], "unmeasured")
        self.assertIn("СОДЕРЖИМЫМ файла в рантайме", got["reason"])

    def test_a_haystack_that_is_not_a_file_read_is_unmeasured_not_self_written(self):
        """Стог — вывод зова, а не чтение файла (пометка соседа по ИМЕНИ
        огрублена, и он сам это говорит). Записать такому сайту «написан
        тестом» значило бы уверенно ответить не на тот вопрос — ровно подмена,
        против которой написан заказ."""
        tmp = _tree({
            "tests/test_call.py": '''
import unittest
from pathlib import Path


def render(rows):
    return "".join(rows)


class T(unittest.TestCase):
    def test_reads_a_file_into_the_SAME_name(self):
        src = Path("neighbour.py").read_text(encoding="utf-8")
        self.assertIn("SPEC", src)

    def test_it(self):
        src = render(["SPEC = ", '{"report.json": ("status", "counts")}'])
        self.assertIn('"report.json": ("status", "counts",', src)
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
            got = _verdict(doc, "test_call.py")
        self.assertEqual(got["verdict"], "unmeasured", got)
        self.assertIn("не являющийся чтением файла", got["reason"])

    def test_unmeasured_is_never_folded_into_a_share(self):
        """Четыре исхода складываются в население РОВНО, без округления вниз."""
        tmp = _tree({
            "pkg/neighbour.py": NEIGHBOUR,
            "tests/test_s.py": '''
import os
import unittest
from pkg import neighbour as N


class T(unittest.TestCase):
    def test_it(self):
        path = os.path.join(N.REPO_ROOT, "pkg", "neighbour.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('"report.json": ("status", "counts",', src)
''',
        })
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
        c = doc["counts"]
        self.assertEqual(
            c["repo_neighbour"] + c["repo_copy"] + c["self_written"] + c["unmeasured"],
            c["boundary"],
            "сумма исходов разошлась с населением — доля названа не от того целого")


class TestThePopulationIsBorrowedNotRebuilt(unittest.TestCase):
    """Население — РОВНО остаток ADR-338, и расхождение с ним есть находка."""

    def test_boundary_reason_string_is_the_one_adr_338_writes(self):
        """Строка-причина сверяется с СОСЕДОМ, а не пересказывается.

        Перепишут причину в #568 — этот тест покраснеет, и население не уедет
        молча в ноль: пустой остаток читался бы как «предмета нет».
        """
        from spa_core.monitoring import substring_structure_assertions as S
        src = Path(S.__file__).read_text(encoding="utf-8")
        self.assertIn(H.BOUNDARY_REASON, src,
                      "прибор отбирает население по строке, которой сосед уже "
                      "не пишет — остаток стал бы пустым, а не измеренным")

    def test_the_real_tree_shows_that_unfolded_is_not_absent_from_the_repo(self):
        """Ответ заказа на ЖИВОМ дереве: «путь не свернулся» не равно «соседа
        нет в репозитории». Ноль здесь означал бы, что утверждение не доказано."""
        root = Path(__file__).resolve().parents[2]
        doc = H.measure(root, now=NOW)
        self.assertGreater(
            doc["counts"]["repo_neighbour"] + doc["counts"]["repo_copy"], 0,
            "ни один сайт за границей #568 не сведён к файлу под корнем — "
            "утверждение «не свернулся ≠ нет в репозитории» не доказано")
        self.assertFalse(
            doc["population_source_disagrees"],
            f"население за границей = {doc['counts']['boundary']}, а ADR-338 "
            f"опубликовал {H.PUBLISHED_BOUNDARY}: доля несопоставима")

    def test_a_disagreement_with_the_published_number_is_critical(self):
        """Доля, названная от ДРУГОГО целого, несопоставима с опубликованной."""
        tmp = _tree({"tests/test_empty.py": "x = 1\n"})
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
        self.assertTrue(doc["population_source_disagrees"])
        self.assertEqual(doc["status"], H.STATUS_CRITICAL)
        self.assertTrue(any("несопоставима" in f for f in doc["findings"]))


class TestTheInstrumentsOwnDefects(unittest.TestCase):
    """Три дефекта, найденные при постройке. Каждый — положительный контроль."""

    def test_the_return_of_a_NESTED_function_is_not_the_helpers_return(self):
        """Взять возврат вложенной функции за возврат внешней значило бы
        приписать значению чужое происхождение."""
        tree = ast.parse('''
def outer(box):
    p = box / "own.md"
    if p:
        return p

    def inner():
        return "НЕ ЭТОТ"
''')
        # Возврат вложенной стои́т ПОЗЖЕ по тексту намеренно: иначе выбор по
        # номеру строки дал бы верный ответ и без отвода вложенных, а сцена
        # оказалась бы истинной по построению.
        func = tree.body[0]
        got = H._return_expr(func)
        self.assertIsInstance(got, ast.Name)
        self.assertEqual(got.id, "p")

    def test_the_last_return_is_chosen_by_LINE_not_by_walk_order(self):
        """`ast.walk` обходит в ширину: «последний встреченный» не есть
        «последний по тексту»."""
        tree = ast.parse('''
def outer(box):
    if box:
        return box / "first.md"
    return box / "last.md"
''')
        got = H._return_expr(tree.body[0])
        self.assertEqual(ast.unparse(got), "box / 'last.md'")

    def test_the_sign_is_measured_on_the_binding_chain_not_on_the_absolute_path(self):
        """Дерево цикла живёт в `/private/tmp/...`. Мерить признак по
        АБСОЛЮТНОМУ пути значило бы найти «tmp» у каждого соседа под корнем и
        изготовить расхождение из МЕСТА ЗАПУСКА."""
        self.assertTrue(H.name_sign("box = tmp_path / 'card.md'"))
        self.assertFalse(H.name_sign("os.path.join(N.REPO_ROOT, 'pkg', 'x.py')"))


class TestWiredAtBirth(unittest.TestCase):
    """Проводка при рождении. Каждое утверждение — СТРУКТУРНОЕ.

    Это не стиль, а прямой урок ADR-338, ради которого и затеян весь заказ:
    судить о структуре соседа ПОДСТРОКОЙ её текста значит не видеть того, что
    стоит за концом литерала. Поэтому схема и ветка проверяются разбором AST и
    сравнением ПОЛНЫХ кортежей, а не поиском куска строки.
    """

    ROOT = Path(__file__).resolve().parents[2]
    ARTIFACT = "data/haystack_origin_census.json"
    MODULE = "spa_core/monitoring/haystack_origin_census.py"

    @staticmethod
    def _module_consts(path: Path) -> dict:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        out[tgt.id] = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None \
                    and isinstance(node.target, ast.Name):
                out[node.target.id] = node.value
        return out

    def test_the_office_step_declares_the_FULL_field_tuple(self):
        """Полный кортеж полей, а не подстрока его начала: пропажа последнего
        ключа обязана краснеть — иначе повторяется ровно дефект ADR-338."""
        consts = self._module_consts(self.ROOT / "scripts" / "consume_office_reports.py")
        spec = consts.get("_READ_SCHEMA")
        self.assertIsNotNone(spec, "у шага 0-офис нет таблицы полей `_READ_SCHEMA`")
        entry = None
        for key, val in zip(spec.keys, spec.values):
            if isinstance(key, ast.Constant) and key.value == "haystack_origin_census.json":
                entry = val
        self.assertIsNotNone(entry, "артефакта нет в таблице полей шага 0-офис")
        got = tuple(e.value for e in entry.elts if isinstance(e, ast.Constant))
        self.assertEqual(
            got, ("status", "counts", "split", "name_sign_vs_measure", "findings",
                  "advisory"),
            "схема отчёта разошлась с объявленной: `name_sign_vs_measure` несёт "
            "ЗАМЕР названной заказом ловушки, и его пропажа читалась бы как "
            "«ловушки нет»")

    def test_the_office_step_has_a_NAMED_printing_branch(self):
        """Ветка, а не упоминание имени: имя есть и в таблице полей."""
        tree = ast.parse((self.ROOT / "scripts" / "consume_office_reports.py")
                         .read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or len(node.comparators) != 1:
                continue
            left, right = node.left, node.comparators[0]
            if isinstance(left, ast.Name) and left.id == "name" \
                    and isinstance(right, ast.Constant) \
                    and right.value == "haystack_origin_census.json":
                found = True
        self.assertTrue(found, "у отчёта нет ИМЕННОЙ печатающей ветки шага 0-офис")

    def test_the_bridge_declares_the_artifact_and_CALLS_the_producer(self):
        """`PRODUCES` — обещание; без строки вызова артефакта не будет вовсе."""
        from spa_core.monitoring import findings_bridge
        self.assertIn(self.ARTIFACT, findings_bridge.PRODUCES)
        tree = ast.parse(Path(findings_bridge.__file__.replace(".pyc", ".py"))
                         .read_text(encoding="utf-8"))
        called = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "run" \
                    and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "haystack_origin_census":
                called = True
        self.assertTrue(called, "мост объявляет артефакт, но не зовёт его производителя")

    def test_the_artifact_has_BOTH_manifest_homes(self):
        """Дом артефакта — ДВЕ записи: реестр `artifacts[]` и паспорт агента
        `produces[]`. Парити-тест краснеет только на второй, поэтому пропажа
        одной из них молчит ровно до следующего сторожа."""
        manifest = json.loads((self.ROOT / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        arts = [a for a in manifest["artifacts"] if a.get("path") == self.ARTIFACT]
        self.assertEqual(len(arts), 1, "нет записи в реестре артефактов")
        self.assertEqual(arts[0]["status"], "active")
        homes = [a for agent in manifest["agents"]
                 for a in agent.get("produces", [])
                 if a.get("artifact") == self.ARTIFACT]
        self.assertEqual(len(homes), 1, "нет записи в паспорте агента-производителя")


class TestAdvisory(unittest.TestCase):
    def test_the_module_writes_nothing_into_the_set(self):
        """Прибор ЧИТАЕТ. Ни одного зова записи по исходникам набора."""
        src = Path(H.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(
                    node.func.attr, ("write_text", "write_bytes", "unlink", "rmtree"),
                    "прибор правит дерево — он обязан только читать его")

    def test_advisory_line_names_the_money_path_as_untouched(self):
        doc_keys = ("POLLED_ADAPTERS", "RiskPolicy", "стоп-кран", "живой трек")
        tmp = _tree({"tests/test_empty.py": "x = 1\n"})
        with tmp:
            doc = H.measure(Path(tmp.name), now=NOW)
        for key in doc_keys:
            self.assertIn(key, doc["advisory"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
