#!/usr/bin/env python3
"""Перепись «трёхисходная дверь — двухисходный читатель» (ADR-870, класс ADR-869).

Каждый случай ниже — контроль в ОБЕ стороны: сцена, где читатель исходы СВОДИТ, и
сцена, отличающаяся РОВНО одним звеном, где он их РАЗЛИЧАЕТ. Проверка «есть ли
модуль» здесь была бы бесполезна: предмет переписи — ИСХОД её вердикта, а не её
наличие, и подтвердить себя своими же словами она не должна (ADR-333).

Вторая половина — живой эталон: НАСТОЯЩИЙ читатель из дерева
(`push_to_github.mutation_window_verdict`) на двух сценах, отличающихся РОВНО кодом,
которым отвечает дверь. Эта половина отвечает на другой вопрос — что различение в
этом дереве ДОСТИЖИМО, то есть находка статической оси есть дефект читателя, а не
свойство языка.

Время и личность процесса тут не при чём: сцены собираются целиком, литеральных дат
нет, живость ОС не спрашивается (`.claude/rules/deployment.md`, §§ о календаре и
личности процесса).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spa_core.monitoring import three_outcome_reader_census as c  # noqa: E402


# ── материал сцен ────────────────────────────────────────────────────────────

DOOR_THREE_OUTCOMES = '''#!/usr/bin/env python3
"""Дверь с тремя исходами, словарь объявлен В КОДЕ."""
import sys

PASS, FAIL, NOT_MEASURED = 0, 1, 2


def main() -> int:
    return PASS


if __name__ == "__main__":
    raise SystemExit(main())
'''

DOOR_PROSE_ONLY = '''#!/usr/bin/env python3
"""Дверь, объявившая словарь ТОЛЬКО прозой: 0 — чисто, 1 — находка, 2 — НЕ ИЗМЕРЕНО."""
import sys


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

READER_COLLAPSES = '''import subprocess, sys

DOOR = "scripts/the_door.py"


def read() -> int:
    rc = subprocess.run([sys.executable, DOOR]).returncode
    if rc != 0:
        print("BLOCKED: дверь не пропустила")
        return 3
    return 0
'''

READER_DISTINGUISHES = '''import subprocess, sys

DOOR = "scripts/the_door.py"


def read() -> int:
    rc = subprocess.run([sys.executable, DOOR]).returncode
    if rc == 0:
        return 0
    if rc == 1:
        print("ОТКАЗ: дверь назвала находки")
        return 3
    print("НЕ ИЗМЕРЕНО: дверь не ответила")
    return 2
'''

READER_FAIL_OPEN = '''import subprocess, sys

DOOR = "scripts/the_door.py"


def read() -> int:
    rc = subprocess.run([sys.executable, DOOR]).returncode
    if rc == 1:
        print("ОТКАЗ")
        return 3
    return 0
'''

READER_IGNORES = '''import subprocess, sys

DOOR = "scripts/the_door.py"


def read() -> int:
    subprocess.run([sys.executable, DOOR])
    return 0
'''

READER_VIA_NAME_CHAIN = '''import os, subprocess, sys


def read(base) -> int:
    probe = os.path.join(base, "scripts", "the_door.py")
    guard = probe
    rc = subprocess.run([sys.executable, guard]).returncode
    if rc != 0:
        return 3
    return 0
'''

READER_VIA_MODULE_CONST = '''import subprocess, sys
from pathlib import Path

DOOR = Path("scripts") / "the_door.py"


def read() -> int:
    cmd = [sys.executable, str(DOOR)]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        return 3
    return 0
'''

READER_OTHER_CHANNEL = '''import json, subprocess, sys
from pathlib import Path

DOOR = Path("scripts") / "the_door.py"
_GATE_NOT_MEASURED = 2


def read() -> int:
    cp = subprocess.run([sys.executable, str(DOOR), "--json"],
                        capture_output=True, text=True)
    try:
        res = json.loads(cp.stdout)
    except Exception:
        return _GATE_NOT_MEASURED
    return int(res.get("outcome", _GATE_NOT_MEASURED))
'''


def build_tree(root: Path, readers: "dict[str, str]", *,
               door: str = DOOR_THREE_OUTCOMES,
               door_rel: str = "scripts/the_door.py") -> None:
    """Одноразовое дерево: одна дверь и названные читатели. Ничего лишнего."""
    door_path = root / door_rel
    door_path.parent.mkdir(parents=True, exist_ok=True)
    door_path.write_text(door, encoding="utf-8")
    for rel, src in readers.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")


# ── статическая ось ──────────────────────────────────────────────────────────


class CensusNamesTheCollapsingReader(unittest.TestCase):
    """Сцены отличаются РОВНО читателем; вердикт обязан отличаться вместе с ним."""

    def _census(self, readers, **kw):
        with tempfile.TemporaryDirectory(prefix="toc_census_") as tmp:
            root = Path(tmp)
            build_tree(root, readers, **kw)
            return c.run_census(root)

    def test_a_binary_reader_of_a_three_outcome_door_is_a_finding(self):
        rep = self._census({"reader.py": READER_COLLAPSES})
        self.assertEqual(rep["door_count"], 1, rep["doors"])
        self.assertEqual(rep["reader_count"], 1, rep["readers"])
        row = rep["readers"][0]
        self.assertEqual(row["verdict"], c.COLLAPSED, row)
        self.assertEqual(row["clash"], [1], row)
        self.assertEqual(len(rep["findings"]), 1)

    def test_the_same_scene_with_a_distinguishing_reader_is_clean(self):
        """ОБРАТНАЯ сторона: отличие РОВНО одно — тело читателя."""
        rep = self._census({"reader.py": READER_DISTINGUISHES})
        self.assertEqual(rep["reader_count"], 1, rep["readers"])
        row = rep["readers"][0]
        self.assertEqual(row["verdict"], c.DISTINGUISHES, row)
        self.assertEqual(row["clash"], [], row)
        self.assertEqual(rep["findings"], [])
        self.assertEqual(rep["verdict"], c.DISTINGUISHES)

    def test_unmeasured_sharing_a_class_with_success_is_fail_open(self):
        """«Не измерено» в классе нуля — худший исход, и он НАЗВАН отдельно."""
        rep = self._census({"reader.py": READER_FAIL_OPEN})
        row = rep["readers"][0]
        self.assertEqual(row["verdict"], c.FAIL_OPEN, row)
        self.assertEqual(row["clash"], [0], row)
        self.assertEqual(rep["verdict"], c.FAIL_OPEN)

    def test_a_reader_that_never_looks_at_the_code_is_a_finding(self):
        rep = self._census({"reader.py": READER_IGNORES})
        row = rep["readers"][0]
        self.assertEqual(row["verdict"], c.IGNORED, row)
        self.assertIn("ни одним сторожем", row["reason"])

    def test_the_door_path_built_through_a_name_chain_is_still_found(self):
        """`guard = probe` — форма, на которой первая редакция сказала «читателей 0»."""
        rep = self._census({"reader.py": READER_VIA_NAME_CHAIN})
        self.assertEqual(rep["reader_count"], 1, rep["readers"])
        self.assertEqual(rep["readers"][0]["verdict"], c.COLLAPSED)

    def test_the_door_path_crossing_the_scope_boundary_is_still_found(self):
        """Модульная константа → локальная команда → вызов: та же цепочка, что у
        `safe_site_push` (`_VERIFY` → `cmd` → `subprocess.run`).

        Замер мутациями 30.10: снятие семени модульной таблицы ВЫЖИЛО — ни одна сцена
        не проходила через границу области, и единственный читатель дерева с этой формой
        терялся молча. Форма без семени даёт «читателей 0», а не красный тест.
        """
        rep = self._census({"reader.py": READER_VIA_MODULE_CONST})
        self.assertEqual(rep["reader_count"], 1, rep["readers"])
        self.assertEqual(rep["readers"][0]["verdict"], c.COLLAPSED, rep["readers"])

    def test_a_verdict_travelling_by_field_is_not_called_a_defect(self):
        """Читатель, ПОЧИНЕННЫЙ ADR-869, читает поле вывода, а не код возврата.

        Назвать его дефектным значило бы опровергнуть ADR-869 его же мерой: это свой
        исход, и он НЕ находка.
        """
        rep = self._census({"reader.py": READER_OTHER_CHANNEL})
        row = rep["readers"][0]
        self.assertEqual(row["verdict"], c.OTHER_CHANNEL, row)
        self.assertEqual(rep["findings"], [])
        self.assertIn("НЕ ИЗМЕРЕНО", row["reason"])

    def test_a_deliberate_residual_class_is_weaker_than_a_binary_reader(self):
        """Читатель, выделивший код явно, судится СЛАБЕЕ — и это НЕ находка.

        Население этого исхода в живом дереве — `mutation_window_verdict`: он
        различает 0/1, а коды 2…4 делят остаток. Прочитан ли остаток как «не
        измерено», статическая ось не знает, и выдавать незнание за дефект нельзя.
        """
        door = DOOR_THREE_OUTCOMES.replace(
            "PASS, FAIL, NOT_MEASURED = 0, 1, 2",
            "PASS, FAIL, NOT_MEASURED, LIVE_OWNER = 0, 1, 2, 4")
        rep = self._census({"reader.py": READER_DISTINGUISHES}, door=door)
        row = rep["readers"][0]
        self.assertEqual(row["verdict"], c.RESIDUAL_SHARED, row)
        self.assertEqual(row["clash"], [4], row)
        self.assertEqual(rep["findings"], [])

    def test_a_two_outcome_door_is_not_a_door_of_this_class(self):
        """Дверь ровно с ДВУМЯ исходами предметом не является — иначе класс стал бы «всё».

        Сцена НАМЕРЕННО несёт имя «не измерено»: иначе её отвергал бы другой сторож
        (нет имени ⇒ не дверь), и порог «≥3 исхода» остался бы непроверенным. Замер
        мутациями 30.10 вскрыл ровно это: подмена порога на «≥2» ВЫЖИЛА, потому что
        прежняя сцена отвергалась по второму признаку, а не по порогу.
        """
        door = DOOR_THREE_OUTCOMES.replace("PASS, FAIL, NOT_MEASURED = 0, 1, 2",
                                           "PASS, NOT_MEASURED = 0, 2")
        rep = self._census({"reader.py": READER_COLLAPSES}, door=door)
        self.assertEqual(rep["door_count"], 0, rep["doors"])
        self.assertEqual(rep["reader_count"], 0, rep["readers"])

    def test_a_vocabulary_without_an_unmeasured_name_is_not_a_door(self):
        """Второй признак двери — отдельным случаем, чтобы он не подменял порог."""
        door = DOOR_THREE_OUTCOMES.replace("PASS, FAIL, NOT_MEASURED = 0, 1, 2",
                                           "PASS, FAIL, REFUSED = 0, 1, 2")
        rep = self._census({"reader.py": READER_COLLAPSES}, door=door)
        self.assertEqual(rep["door_count"], 0, rep["doors"])

    def test_a_prose_only_vocabulary_is_named_not_counted(self):
        """Словарь из docstring дверью НЕ считается, и цена туготы ПЕЧАТАЕТСЯ числом."""
        rep = self._census({"reader.py": READER_COLLAPSES}, door=DOOR_PROSE_ONLY)
        self.assertEqual(rep["door_count"], 0, rep["doors"])
        self.assertEqual(rep["doors_declared_in_prose_only"], ["scripts/the_door.py"])

    def test_the_door_calling_itself_is_not_its_own_reader(self):
        door = DOOR_THREE_OUTCOMES + (
            "\n\ndef again():\n    import subprocess\n"
            "    subprocess.run([sys.executable, 'scripts/the_door.py'])\n")
        rep = self._census({}, door=door)
        self.assertEqual(rep["door_count"], 1)
        self.assertEqual(rep["reader_count"], 0, rep["readers"])

    def test_surfaces_this_census_does_not_parse_are_counted_not_zeroed(self):
        """Оболочка и воркфлоу — «НЕ ИЗМЕРЕНО» ЧИСЛОМ, а не нулём (инв. #17)."""
        with tempfile.TemporaryDirectory(prefix="toc_surface_") as tmp:
            root = Path(tmp)
            build_tree(root, {})
            (root / "run.sh").write_text("python3 scripts/the_door.py\n", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "x.yml").write_text(
                "jobs:\n  a:\n    steps:\n      - run: python3 scripts/the_door.py\n",
                encoding="utf-8")
            rep = c.run_census(root)
        nm = rep["not_measured_surfaces"]
        self.assertEqual(nm["shell_sites"], 1, nm)
        self.assertEqual(nm["workflow_sites"], 1, nm)

    def test_a_missing_tree_is_unmeasured_not_clean(self):
        rep = c.run_census(Path(tempfile.gettempdir()) / "toc_no_such_tree_987")
        self.assertEqual(rep["verdict"], c.UNMEASURED)
        self.assertIn("каталога дерева нет", rep["reason"])

    def test_tests_are_not_parsed_as_wiring(self):
        """Сцена теста — не проводка: иначе эти же файлы и были бы населением класса."""
        rep = self._census({"spa_core/tests/test_scene.py": READER_COLLAPSES})
        self.assertEqual(rep["reader_count"], 0, rep["readers"])


class CliSpeaksItsDeclaredVocabulary(unittest.TestCase):
    """У CLI переписи три исхода, и они РАЗЛИЧИМЫ — иначе прибор повторял бы предмет."""

    def _main(self, root, extra=()):
        return c.main(["--root", str(root), *extra])

    def test_clean_tree_returns_zero_and_findings_return_one(self):
        with tempfile.TemporaryDirectory(prefix="toc_cli_") as tmp:
            clean, dirty = Path(tmp) / "clean", Path(tmp) / "dirty"
            build_tree(clean, {"reader.py": READER_DISTINGUISHES})
            build_tree(dirty, {"reader.py": READER_COLLAPSES})
            self.assertEqual(self._main(clean), c.RC_CLEAN)
            self.assertEqual(self._main(dirty), c.RC_FINDING)

    def test_a_tree_that_cannot_be_read_returns_the_unmeasured_code(self):
        missing = Path(tempfile.gettempdir()) / "toc_no_such_tree_987b"
        self.assertEqual(self._main(missing), c.RC_UNMEASURED)

    def test_the_declared_vocabulary_has_three_distinct_values(self):
        self.assertEqual(len({c.RC_CLEAN, c.RC_FINDING, c.RC_UNMEASURED}), 3)

    def test_the_census_finds_its_own_cli_as_a_door(self):
        """Прибор обязан выдерживать свою меру: его словарь объявлен В КОДЕ."""
        src = Path(c.__file__).read_text(encoding="utf-8")
        door = c.door_of(Path(c.__file__), src)
        self.assertIsNotNone(door, "прибор не проходит собственного определения двери")
        self.assertEqual(door["codes"], [0, 1, 2], door)
        self.assertEqual(door["unmeasured"], [c.RC_UNMEASURED], door)


# ── живая ось ────────────────────────────────────────────────────────────────


class LiveExemplarDistinguishesTheDoorsOutcomes(unittest.TestCase):
    """НАСТОЯЩИЙ читатель дерева на двух сценах, отличающихся РОВНО кодом двери."""

    def test_the_exemplar_tells_refused_from_did_not_answer(self):
        res = c.drive_exemplar(REPO_ROOT)
        if res["kind"] == c.DRIVE_UNMEASURED:
            self.fail(f"эталон НЕ ИЗМЕРЕН: {res.get('reason')} — «не измерено» "
                      f"не выдаётся за «прошло»")
        self.assertEqual(res["kind"], c.DRIVE_DISTINGUISHES, res)
        scenes = res["scenes"]
        self.assertEqual((scenes["door_refused"]["findings"],
                          scenes["door_refused"]["unmeasured"]), (1, 0), scenes)
        self.assertEqual((scenes["door_did_not_answer"]["findings"],
                          scenes["door_did_not_answer"]["unmeasured"]), (0, 1), scenes)

    def test_the_exemplar_verdict_tells_three_outcomes_apart(self):
        """Контроль САМОГО вердикта о сценах, а не только их чисел.

        Замер мутациями 30.10: подмена всей проверки направления на `ok = True` ВЫЖИЛА —
        живые сцены отвечают верно, поэтому утверждения о числах держались, а род исхода
        не держало ничего. Проба приёмки решает по `kind`, значит на СВОДЯЩЕМ читателе она
        прошла бы: fail-OPEN. Сцену с неверным читателем в живом дереве взять негде, поэтому
        вердикт вынесен в шов и проверяется прямо — в ОБЕ стороны и по третьему исходу.
        """
        self.assertEqual(
            c.exemplar_verdict({"findings": 1, "unmeasured": 0},
                               {"findings": 0, "unmeasured": 1})["kind"],
            c.DRIVE_DISTINGUISHES)
        conflating = c.exemplar_verdict({"findings": 0, "unmeasured": 1},
                                        {"findings": 0, "unmeasured": 1})
        self.assertEqual(conflating["kind"], c.DRIVE_CONFLATES, conflating)
        self.assertIn("один и тот же род", conflating["reason"])
        reversed_ = c.exemplar_verdict({"findings": 0, "unmeasured": 1},
                                       {"findings": 1, "unmeasured": 0})
        self.assertEqual(reversed_["kind"], c.DRIVE_UNMEASURED, reversed_)
        self.assertIn("НЕ в объявленную сторону", reversed_["reason"])

    def test_the_probe_refuses_a_conflating_exemplar(self):
        """Проба приёмки обязана отличать «сводит» от «различает» — иначе шов бесполезен."""
        from spa_core.monitoring import card_acceptance as ca
        probe = ca.PROBES["three_outcome_reader_population_named"]
        real = c.drive_exemplar
        try:
            c.drive_exemplar = lambda *a, **kw: {"kind": c.DRIVE_CONFLATES,
                                                "reader": "сцена контроля"}
            verdict, detail = probe(None)
            self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
            c.drive_exemplar = lambda *a, **kw: {"kind": c.DRIVE_UNMEASURED,
                                                 "reason": "сцена контроля"}
            verdict, detail = probe(None)
            self.assertEqual(verdict, ca.UNMEASURED, detail)
        finally:
            c.drive_exemplar = real
        verdict, detail = probe(None)
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_the_exemplar_scenes_differ_in_exactly_the_doors_code(self):
        """Положительный контроль самой сцены: подменена РОВНО дверь, и ничего больше."""
        one = c._STUB_DOOR.format(code=1)
        two = c._STUB_DOOR.format(code=2)
        diff = [(a, b) for a, b in zip(one.splitlines(), two.splitlines()) if a != b]
        self.assertEqual(diff, [("CODE = 1", "CODE = 2")], diff)


# ── храповик ─────────────────────────────────────────────────────────────────


class BaselineRatchetOnlyShrinks(unittest.TestCase):
    """База сводящих читателей может только УМЕНЬШАТЬСЯ (инв. #16)."""

    def setUp(self):
        self.baseline = c.load_baseline(REPO_ROOT)
        self.report = c.run_census(REPO_ROOT)

    def test_the_baseline_file_exists_and_names_its_measurement(self):
        self.assertTrue(self.baseline, "базы нет — храповик нечем держать")
        self.assertIn("collapsing_readers", self.baseline)
        self.assertIn("_measured_at", self.baseline)
        self.assertIn("_measured_by", self.baseline)

    def test_no_new_collapsing_reader_appears(self):
        measured = {c.finding_key(r) for r in self.report["findings"]}
        allowed = set(self.baseline.get("collapsing_readers") or [])
        new = sorted(measured - allowed)
        self.assertEqual(new, [], (
            "НОВЫЙ читатель сводит «не измерено» с «отказано» — чинить ЧИТАТЕЛЯ, "
            "а не дописывать его в scripts/three_outcome_reader_baseline.json "
            f"(запрещено, инв. #16): {new}"))

    def test_the_baseline_carries_no_reader_that_is_already_fixed(self):
        """База УМЕНЬШАЕТСЯ: запись о починенном читателе обязана уйти из неё."""
        measured = {c.finding_key(r) for r in self.report["findings"]}
        stale = sorted(set(self.baseline.get("collapsing_readers") or []) - measured)
        self.assertEqual(stale, [], (
            "эти читатели больше не сводят исходы — снять их из базы, иначе храповик "
            f"перестанет держать достигнутое: {stale}"))

    def test_the_live_tree_has_the_measured_population(self):
        """Замер дня 30.10 НАЗВАН числом: перепись из одного экземпляра не вывод."""
        counts = self.report["counts"]
        self.assertGreaterEqual(self.report["door_count"], 1)
        self.assertGreaterEqual(self.report["reader_count"],
                                len(self.baseline.get("collapsing_readers") or []))
        self.assertEqual(counts[c.FAIL_OPEN], 0,
                         "fail-OPEN у двери с «не измерено» — это авария, не находка")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
