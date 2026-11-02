#!/usr/bin/env python3
"""Девятая дверь семейства — ПОДПРОЦЕСС: контроли прибора в ОБЕ стороны.

Карточка `inbox-inektsiya-chasov-konchaetsya-na-granitse` (заказ G893 п. 3).

Что здесь закреплено
------------------------------------------------------------------------------
Прибор :mod:`spa_core.tests._subprocess_clock_door` отвечает на два РАЗНЫХ вопроса —
ПОВЕРХНОСТЬ (разбор AST) и КЛАСС (дифференциальный прогон в ТРИ ступени: база → сдвиг
у РЕБЁНКА → сдвиг У ОБОИХ по подтверждённым, и третья отделяет настоящую бомбу от
чувствительности к самой асимметрии замера). У каждого ответа здесь контроль в обе
стороны, и у замера класса контроль
поднимает **НАСТОЯЩИЙ** ``differential()`` на настоящей сцене pytest, а не сверяет
словарь, собранный руками: урок «контроль строки на словаре РУКАМИ мерит свой словарь»
(мутация «секция под другим именем» выжила два цикла подряд, #944/#945).

Сцена класса — дословная форма аварии ADR-897: якорь закреплён в РОДИТЕЛЕ, а «сколько
сейчас» спрашивает РЕБЁНОК. Рядом — честный шов той же формы (якорь уезжает ребёнку
входом ``--now``), и он обязан остаться зелёным под тем же сдвигом. Один контроль без
другого ничего не доказывает: мера, краснеющая на всё, — украшение.

Литеральные даты ниже — фикстуры самих сцен, каждая существует, чтобы быть сдвинутой
или не сдвинутой. Освобождение честное и НЕ по проверяемой здесь причине:
# FROZEN-DATE-OK: door-scene-samples — даты здесь суть материал сцены прибора.
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

_REPO = Path(__file__).resolve().parents[2]


# Прибор — ПОМОЩНИК набора, поэтому импортируется обычным импортом: батарея и есть его
# настоящий импортёр. Первая редакция грузила его по пути из ``scripts/``, и загрузка по
# пути проводкой не является — `test_unwired_scripts_ratchet` сказал это вслух.
from spa_core.tests import _subprocess_clock_door as c

_MARK = f"# FROZEN-DATE-OK: {c.CLAIM} — часы приходят входом"

# --- сцена бомбы: якорь в РОДИТЕЛЕ, календарь в РЕБЁНКЕ --------------------
_CHILD_WALL_CLOCK = (
    "import sys\n"
    "from datetime import datetime\n"
    "# ребёнок спрашивает СТЕННЫЕ часы — ровно форма ADR-897. Отметка наивная у обеих\n"
    "# сторон НАМЕРЕННО: смешав наивную с осведомлённой, сцена падала бы на TypeError и\n"
    "# в ОБА прогона, то есть молча перестала бы быть сценой (замер этого цикла).\n"
    "print((datetime.now() - datetime.fromisoformat(sys.argv[1])).days)\n"
)
_CHILD_HONEST = (
    "import argparse\n"
    "from datetime import datetime\n"
    "p = argparse.ArgumentParser()\n"
    "p.add_argument('--stamp')\n"
    "p.add_argument('--now')\n"
    "a = p.parse_args()\n"
    "# шов ADR-897: момент приходит ВХОДОМ, стенных часов у вердикта нет\n"
    "print((datetime.fromisoformat(a.now) - datetime.fromisoformat(a.stamp)).days)\n"
)


def _bomb_test(child: Path) -> str:
    return (
        f'"""{_MARK}"""\n'
        "import subprocess, sys\n"
        "NOW = '2026-11-01T00:00:00'\n"
        "def test_child_sees_the_same_day():\n"
        f"    out = subprocess.run([sys.executable, {str(child)!r}, NOW],\n"
        "                         capture_output=True, text=True)\n"
        "    assert abs(int(out.stdout.strip())) < 30, out.stdout\n"
    )


#: ОБЕ стороны у стенных часов: родитель спрашивает `now`, ребёнок тоже. Под сдвигом
#: ТОЛЬКО ребёнка такой тест краснеет, под сдвигом ОБОИХ — нет; календарной бомбой он
#: НЕ является, и смешать его с бомбой значило бы выдать верхнюю границу за класс.
_PARENT_WALL_CLOCK = (
    "import subprocess, sys\n"
    "from datetime import datetime\n"
    "def test_parent_and_child_agree_on_today():\n"
    "    out = subprocess.run([sys.executable, {child!r},\n"
    "                          datetime.now().isoformat()],\n"
    "                         capture_output=True, text=True)\n"
    "    assert abs(int(out.stdout.strip())) < 30, out.stdout\n"
)


def _both_clocks_test(child: Path) -> str:
    return f'"""{_MARK}"""\n' + _PARENT_WALL_CLOCK.format(child=str(child))


def _honest_test(child: Path) -> str:
    return (
        f'"""{_MARK}"""\n'
        "import subprocess, sys\n"
        "NOW = '2026-11-01T00:00:00'\n"
        "def test_anchor_travels_to_the_child():\n"
        f"    out = subprocess.run([sys.executable, {str(child)!r},\n"
        "                          '--stamp', NOW, '--now', NOW],\n"
        "                         capture_output=True, text=True)\n"
        "    assert int(out.stdout.strip()) == 0, out.stdout\n"
    )


# --- 1. сам шим: три состояния различимы ----------------------------------
class ShimShiftsOnlyWhenAsked(unittest.TestCase):
    """Шим — прибор. Незамеренный прибор делает замер класса предположением."""

    def _probe(self, env_extra: dict) -> str:
        with tempfile.TemporaryDirectory() as td:
            shim, _ = c.materialise_shim(Path(td), shift_days=400.0)
            probe = Path(td) / "probe.py"
            probe.write_text("from datetime import datetime, date\nimport time\n"
                             "print(datetime.now().year, date.today().year, int(time.time()))\n",
                             encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONPATH"] = str(shim)
            env.update(env_extra)
            out = subprocess.run([sys.executable, str(probe)], capture_output=True,
                                 text=True, env=env, timeout=120)
            self.assertEqual(0, out.returncode, out.stderr)
            return out.stdout.strip()

    def test_the_child_calendar_moves_when_the_shift_is_declared(self):
        shifted = self._probe({"SPA_CLOCK_SHIFT_DAYS": "400"}).split()
        plain = self._probe({}).split()
        self.assertGreater(int(shifted[0]), int(plain[0]), "datetime.now не сдвинулся")
        self.assertGreater(int(shifted[1]), int(plain[1]), "date.today не сдвинулся")
        self.assertGreater(int(shifted[2]), int(plain[2]), "time.time не сдвинулся")

    def _assert_calendar_did_not_move(self, a: str, b: str) -> None:
        """«Календарь не двинулся» — не «вывод побайтово тот же».

        Две пробы идут одна за другой, и ``int(time.time())`` между ними отличается на
        секунду просто от хода времени: первая редакция сверяла строки целиком и
        покраснела ровно от этого. Предмет проверки — СДВИГ (400 суток = 34 560 000 с),
        поэтому год сверяется дословно, а эпоха — с допуском в секунды. Это починка
        фикстуры, а не ослабление: допуск меньше предмета в семь миллионов раз.
        """
        ay, ad, asec = a.split()
        by, bd, bsec = b.split()
        self.assertEqual((ay, ad), (by, bd), "год/дата сдвинулись")
        self.assertLess(abs(int(asec) - int(bsec)), 60,
                        "эпоха разошлась больше, чем на ход времени между пробами")

    def test_the_shim_is_silent_without_the_variable(self):
        """Шим, попавший в PYTHONPATH случайно, обязан не делать НИЧЕГО."""
        self._assert_calendar_did_not_move(
            self._probe({}), self._probe({"SPA_CLOCK_SHIFT_DAYS": ""}))

    def test_an_unparsable_shift_does_not_move_the_calendar(self):
        """Неразбираемое значение — не повод сдвинуть наугад."""
        self._assert_calendar_did_not_move(
            self._probe({}), self._probe({"SPA_CLOCK_SHIFT_DAYS": "вчера"}))

    def test_the_shim_does_not_break_type_identity(self):
        """Положительный контроль ДОСЛОВНОЙ ложной находки этого цикла.

        Первая редакция шима кладла в модуль просто НАСЛЕДНИКА, и настоящий ``datetime``
        перестал быть его экземпляром. `autonomy_mandate._as_date` отказал
        ``TypeError: ожидалась дата/датавремя, получено datetime``, прибор доложил смену
        вердикта, и **артефакт прибора был прочитан как предмет класса** — вторая
        находка ADR-897 с другой стороны. Вопрос задаётся отдельно от сдвига: прибор,
        подменяющий ТОЖДЕСТВО, меряет себя.
        """
        with tempfile.TemporaryDirectory() as td:
            shim, _ = c.materialise_shim(Path(td), shift_days=400.0)
            probe = Path(td) / "ident.py"
            probe.write_text(
                "import datetime as dt\n"
                "shifted = dt.datetime.now(dt.timezone.utc)\n"
                "plain = dt.datetime.fromtimestamp(0, dt.timezone.utc)\n"
                "assert isinstance(shifted, dt.datetime), 'сдвинутый не свой тип'\n"
                "assert isinstance(plain, dt.datetime), 'НАСТОЯЩИЙ datetime отвергнут'\n"
                "assert isinstance(plain, dt.date), 'НАСТОЯЩИЙ datetime не date'\n"
                "assert type(plain).__name__ == 'datetime', type(plain).__name__\n"
                "assert type(shifted).__name__ == 'datetime', type(shifted).__name__\n"
                "print(shifted.year)\n", encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONPATH"] = str(shim)
            env["SPA_CLOCK_SHIFT_DAYS"] = "400"
            out = subprocess.run([sys.executable, str(probe)], capture_output=True,
                                 text=True, env=env, timeout=120)
            self.assertEqual(0, out.returncode,
                             f"шим ломает тождество типа ⇒ он выдумывает находки:"
                             f"\n{out.stderr}")
            plain_year = subprocess.run([sys.executable, str(probe)], capture_output=True,
                                        text=True, timeout=120)
            self.assertGreater(int(out.stdout.strip()), int(plain_year.stdout.strip()),
                               "тождество сохранено, но календарь не сдвинулся")


# --- 2. ось поверхности: обе стороны --------------------------------------
class SurfaceMeasure(unittest.TestCase):
    def _scene(self, td: Path, name: str, body: str) -> None:
        d = td / "spa_core" / "tests"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body, encoding="utf-8")

    def _rows(self, td: Path):
        return {r.path: r for r in c.measure_surface(td, (c.CANON_ROOT,), recursive=False)}

    def test_claim_plus_spawn_is_on_surface_and_claim_alone_is_not(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            self._scene(td, "test_spawns.py",
                        f'"""{_MARK}"""\nimport subprocess\n'
                        "def test_x():\n    subprocess.run(['true'])\n")
            self._scene(td, "test_quiet.py",
                        f'"""{_MARK}"""\nNOW = "2026-11-01"\ndef test_y():\n    assert NOW\n')
            rows = self._rows(td)
            self.assertEqual(c.ON_SURFACE, rows["spa_core/tests/test_spawns.py"].surface)
            self.assertEqual(c.OFF_SURFACE, rows["spa_core/tests/test_quiet.py"].surface)

    def test_a_file_without_the_claim_is_not_counted_at_all(self):
        """Мера, считающая файлы без претензии, считала бы ДРУГОЕ население."""
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            self._scene(td, "test_nomark.py",
                        "import subprocess\ndef test_x():\n    subprocess.run(['true'])\n")
            self.assertEqual({}, self._rows(td))

    def test_the_spawn_door_sees_an_imported_name(self):
        """Положительный контроль ПОЧИНКИ: ``from subprocess import run`` — тот же ребёнок.

        Первая редакция переписи смотрела на ПРАВОПИСАНИЕ вызова и этот файл не видела.
        """
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            self._scene(td, "test_imported.py",
                        f'"""{_MARK}"""\nfrom subprocess import run\n'
                        "def test_x():\n    run(['true'])\n")
            row = self._rows(td)["spa_core/tests/test_imported.py"]
            self.assertEqual(c.ON_SURFACE, row.surface)
            self.assertTrue(any("from subprocess import run" in s for s in row.spawns),
                            row.spawns)

    def test_an_aliased_module_is_seen_and_a_namesake_is_not(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            self._scene(td, "test_alias.py",
                        f'"""{_MARK}"""\nimport subprocess as sp\n'
                        "def test_x():\n    sp.run(['true'])\n")
            self._scene(td, "test_namesake.py",
                        f'"""{_MARK}"""\nclass _Fake:\n    def run(self, *a): pass\n'
                        "shell = _Fake()\ndef test_y():\n    shell.run(['true'])\n")
            rows = self._rows(td)
            self.assertEqual(c.ON_SURFACE, rows["spa_core/tests/test_alias.py"].surface)
            self.assertEqual(c.OFF_SURFACE, rows["spa_core/tests/test_namesake.py"].surface)

    def test_an_unparsable_file_is_the_third_outcome_not_a_pass(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            self._scene(td, "test_broken.py", f'"""{_MARK}"""\ndef test_x(:\n')
            row = self._rows(td)["spa_core/tests/test_broken.py"]
            self.assertEqual(c.UNMEASURED, row.surface)
            self.assertIn("не разобран", row.reason)

    def test_the_anchor_axis_separates_the_seam_from_its_absence(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            self._scene(td, "test_seam.py",
                        f'"""{_MARK}"""\nimport subprocess, sys\n'
                        "NOW = '2026-11-01T00:00:00'\n"
                        "def test_x():\n"
                        "    subprocess.run([sys.executable, 'p.py', '--now', NOW])\n")
            self._scene(td, "test_noseam.py",
                        f'"""{_MARK}"""\nimport subprocess, sys\n'
                        "NOW = '2026-11-01T00:00:00'\n"
                        "def test_y():\n"
                        "    subprocess.run([sys.executable, 'p.py'])\n    assert NOW\n")
            rows = self._rows(td)
            self.assertEqual(c.ANCHOR_PASSED, rows["spa_core/tests/test_seam.py"].anchor)
            self.assertEqual(c.ANCHOR_NOT_PASSED,
                             rows["spa_core/tests/test_noseam.py"].anchor)


# --- 3. ось класса: НАСТОЯЩИЙ differential() на настоящей сцене -----------
class TypeTransparencyCanary(unittest.TestCase):
    """Канарейка — то, что отделяет ОТВЕТ о классе от артефакта прибора.

    Шим подменяет ``datetime``/``date`` модульным атрибутом: это двигает ЗНАЧЕНИЕ, но
    трогает и ТИП, а на типе стои́т чужой код. Замер цикла #1011: pydantic делает
    ``class ConstrainedDate(date, metaclass=ConstrainedNumberMeta)``, и подмена ``date``
    даёт ``TypeError: metaclass conflict`` на ИМПОРТЕ — ребёнок падает по причине, не
    имеющей отношения к календарю, а прибор видит смену вердикта.

    **Зелёной стороны у этой канарейки сегодня НЕТ, и это сказано вслух:** шима,
    двигающего календарь ребёнка БЕЗ подмены типа, в дереве не существует (``faketime``
    нет, системные часы двигать нельзя). Поэтому контроль «канарейка бывает зелена» не
    написан — его нечем обеспечить, а подделать его значило бы выдать неизмеренное за
    измеренное. Обе проверяемые стороны — РАЗНЫЕ причины отказа.
    """

    def test_the_canary_names_the_metaclass_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            verdict, reason = c.type_transparency(Path(td), shift_days=400.0)
        self.assertEqual(c.TYPE_BROKEN, verdict)
        self.assertIn("metaclass conflict", reason)

    def test_the_canary_also_watches_the_calendar_half(self):
        """Не вакуумна: при нулевом сдвиге отказ приходит по ДРУГОЙ причине.

        Канарейка спрашивает ДВЕ вещи — цел ли тип И сдвинут ли календарь. Мера,
        отвечающая «сломано» всегда одинаково, не различала бы эти половины.
        """
        with tempfile.TemporaryDirectory() as td:
            verdict, reason = c.type_transparency(Path(td), shift_days=0.0)
        self.assertEqual(c.TYPE_BROKEN, verdict)
        self.assertNotIn("metaclass conflict", reason,
                         "обе половины канарейки отвечают одно и то же")


class DifferentialOnARealScene(unittest.TestCase):
    """Контроль поднимает ``differential()`` целиком — канарейку, шим, плагин, прогоны.

    Сверять руками собранный словарь вердиктов значило бы мерить свой словарь, а не
    проводку (урок #944/#945). Поэтому сцена настоящая и pytest настоящий.

    **Что именно здесь закреплено после замера #1011:** пока канарейка сломана, ответ о
    КЛАССЕ не выдаётся вовсе — остаются КАНДИДАТЫ, и проводка трёх ступеней проверяется
    на них. Это и есть третий исход: «не измерено» с названной причиной, а не ноль.
    """

    def setUp(self) -> None:
        self._t = tempfile.TemporaryDirectory()
        self.td = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        (self.td / "child_wall.py").write_text(_CHILD_WALL_CLOCK, encoding="utf-8")
        (self.td / "child_honest.py").write_text(_CHILD_HONEST, encoding="utf-8")

    def _write(self, name: str, body: str) -> str:
        (self.td / name).write_text(body, encoding="utf-8")
        return name

    def test_a_broken_canary_withholds_the_class_answer(self):
        """Главный контроль цикла #1011: артефакт прибора не выдаётся за предмет.

        Бомба ОСТАЁТСЯ видимой — как КАНДИДАТ. Спрятать её было бы так же неверно, как
        назвать находкой: вопрос не «есть ли смена вердикта», а «чему она принадлежит».
        """
        bomb = self._write("test_bomb_scene.py", _bomb_test(self.td / "child_wall.py"))
        out = c.differential(self.td, [bomb], shift_days=400.0, timeout_s=900)
        self.assertEqual(c.UNMEASURED, out["status"], out)
        self.assertEqual(c.TYPE_BROKEN, out["type_transparency"])
        self.assertTrue(out["candidates_only"])
        self.assertIn("неотличима от артефакта прибора", out["reason"])
        self.assertIn("metaclass conflict", out["type_reason"])
        self.assertTrue(out["confirmed"], f"кандидат спрятан, а не назван: {out}")

    def test_the_bomb_is_a_candidate_and_the_seam_is_not(self):
        """Проводка трёх ступеней жива: разделение бомбы и честного шва ИЗМЕРЯЕТСЯ."""
        bomb = self._write("test_bomb_scene.py", _bomb_test(self.td / "child_wall.py"))
        honest = self._write("test_seam_scene.py",
                             _honest_test(self.td / "child_honest.py"))
        out = c.differential(self.td, [bomb, honest], shift_days=400.0, timeout_s=900)
        confirmed = out["confirmed"]
        self.assertTrue(confirmed, f"сдвиг календаря у ребёнка не поменял НИ ОДНОГО "
                                   f"вердикта — проводка прибора мертва: {out}")
        self.assertTrue(all("test_bomb_scene" in k for k in confirmed),
                        f"кандидатом назван не тот тест: {confirmed}")
        self.assertFalse(any("test_seam_scene" in k for k in confirmed),
                         f"честный шов назван кандидатом — мера краснеет на всё: "
                         f"{confirmed}")
        self.assertEqual({}, out["noisy"], out)
        (was, now, back), = confirmed.values()
        self.assertEqual(["PASSED", "FAILED", "PASSED"], [was, now, back],
                         "перемер не вернул вердикт — замер не закреплён")
        # третья ступень обязана назвать РОД даже у кандидата
        self.assertEqual(1, len(out["anchor_vs_clock"]), out)
        self.assertEqual([], out["both_sides_wall_clock"], out)
        self.assertEqual({}, out["kind_unmeasured"], out)

    def test_two_wall_clocks_are_separated_from_the_anchor(self):
        """Контроль ТРЕТЬЕЙ ступени: смена вердикта ≠ календарная бомба.

        Тест, у которого ОБЕ стороны взяты у часов, краснеет от САМОЙ асимметрии,
        внесённой замером. Без этой ступени он попал бы в один список с якорем.
        """
        pair = self._write("test_two_clocks_scene.py",
                           _both_clocks_test(self.td / "child_wall.py"))
        out = c.differential(self.td, [pair], shift_days=400.0, timeout_s=900)
        self.assertTrue(out["confirmed"], f"сдвиг ребёнка не поменял вердикт: {out}")
        self.assertEqual([], out["anchor_vs_clock"],
                         f"пара стенных часов названа якорем: {out}")
        self.assertEqual(1, len(out["both_sides_wall_clock"]), out)
        self.assertEqual({}, out["kind_unmeasured"], out)

    def test_a_tree_without_a_candidate_reports_none(self):
        """Обратная сторона: где кандидата нет, прибор обязан молчать."""
        honest = self._write("test_only_seam.py",
                             _honest_test(self.td / "child_honest.py"))
        out = c.differential(self.td, [honest], shift_days=400.0, timeout_s=900)
        self.assertEqual({}, out["confirmed"], out)
        self.assertEqual({}, out["noisy"], out)
        self.assertGreater(out["nodeids_base"], 0, "базовый прогон не дал вердиктов")

    def test_an_empty_base_run_is_unmeasured_with_its_own_reason(self):
        """Ноль вердиктов — НЕ «класс пуст», и причина у этого отказа СВОЯ."""
        out = c.differential(self.td, ["test_does_not_exist.py"], shift_days=400.0,
                             timeout_s=900)
        self.assertEqual(c.UNMEASURED, out["status"], out)
        self.assertIn("не дал ни одного вердикта", out["reason"])


# --- 4. разбор вердиктов: SKIPPED различается ------------------------------
class OutcomeParsing(unittest.TestCase):
    def test_skipped_is_its_own_verdict(self):
        """Урок #465: в дифференциальном замере тест не краснеет — он ИСЧЕЗАЕТ."""
        got = c._parse_outcomes(
            "a/b.py::test_one PASSED [ 50%]\n"
            "a/b.py::test_two SKIPPED [100%]\n"
            "a/b.py::test_three FAILED [100%]\n"
            "== short summary ==\n")
        self.assertEqual({"a/b.py::test_one": "PASSED",
                          "a/b.py::test_two": "SKIPPED",
                          "a/b.py::test_three": "FAILED"}, got)

    def test_a_line_without_a_nodeid_is_not_a_verdict(self):
        self.assertEqual({}, c._parse_outcomes("PASSED something\n3 passed in 1.0s\n"))


# --- 5. CLI: дерево прогона обязано быть НАЗВАНО --------------------------
class TheRunTreeMustBeNamed(unittest.TestCase):
    def test_differential_without_run_root_is_unmeasured_with_a_reason(self):
        """Долгий прогон в дереве доставки ломает доставку (седьмая дверь правила).

        Прибор не вправе выбрать дерево молча: умолчание и есть дефект.
        """
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            (td / "spa_core" / "tests").mkdir(parents=True)
            out = subprocess.run(
                [sys.executable, "-m", "spa_core.tests._subprocess_clock_door",
                 "--repo-root", str(td), "--differential", "--json"],
                cwd=str(_REPO),
                capture_output=True, text=True, timeout=300)
            self.assertEqual(2, out.returncode, out.stdout + out.stderr)
            doc = json.loads(out.stdout)
            self.assertEqual(c.UNMEASURED, doc["differential"]["status"])
            self.assertIn("дерево прогона НЕ НАЗВАНО", doc["differential"]["reason"])


# --- 6. одна дверь к претензии -------------------------------------------
class OneDoorToTheClaim(unittest.TestCase):
    def test_the_claim_is_read_by_the_guard_s_own_measure(self):
        """Своя копия регекса дала бы прибору ДРУГОЕ население, чем освобождает храповик."""
        from spa_core.tests import _injected_clock as ic

        self.assertEqual(ic.CLAIM, c.CLAIM)
        sample = f'"""{_MARK}"""\n'
        self.assertTrue(c.claims_the_marker(sample))
        self.assertEqual(ic.claims_injected_clock(sample), c.claims_the_marker(sample))
        self.assertFalse(c.claims_the_marker('"""просто docstring"""\n'))

    def test_the_canonical_scope_is_the_ratchet_s_own_scope(self):
        """Канон охвата — ЗАМЕР чужого кода, а не выбор: храповик читает один каталог."""
        src = (_REPO / "spa_core" / "tests" / "test_frozen_date_ratchet.py").read_text(
            encoding="utf-8")
        self.assertIn('glob("test_*.py")', src)
        self.assertNotIn('rglob("test_*.py")', src)
        self.assertEqual("spa_core/tests", c.CANON_ROOT)


if __name__ == "__main__":
    unittest.main()
