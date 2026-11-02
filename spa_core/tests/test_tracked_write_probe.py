"""Контроль пробы `tracked_data_untouched_by_declared_runs` (ADR-900, цикл #1013).

Проба отвечает на вопрос «трогает ли прогон объявленных тест-модулей хоть один
git-tracked файл `data/`». Сессионный сторож `tracked_write_guard` поднимает
`exitstatus` сессии, поэтому при живом дефекте КАЖДЫЙ шард контрольного прогона
кончается кодом 1 ПО ПОСТРОЕНИЮ — замер по логам прогона `41435243848`
(`8f34a8894`): 12 шардов из 12, 68 нарушений, свод назвал 0 (ADR-899).

Устройство контроля (`.claude/rules/acceptance.md` §3 — «зелёная на целом
контуре и красная на КАЖДОМ порванном звене, с названным звеном»):

* **целый контур** — настоящий `tracked_write_judge` на сцене, чей прогон
  НИЧЕГО не пишет ⇒ `satisfied`;
* **порванное звено** — та же сцена, но прогон пишет РОВНО ОДИН файл `data/`
  ⇒ `not_satisfied`, и имя файла НАЗВАНО. Проверяется на каждом из нескольких
  файлов по отдельности, и имя соседнего файла в вердикте отсутствовать обязано;
* **НЕ подстрокой** (ADR-333) — сцена, в исходнике которой стои́т слово
  `_default_file`, но прогон всё равно пишет, обязана остаться `not_satisfied`:
  проба мерит ИСХОД на диске, а не текст файла;
* **три исхода различимы** (инв. #17) — «прогон не ответил», «сводки нет»,
  «собрано ноль тестов», «в `data/` сцены пусто» и «каталога `data/` нет» дают
  ПЯТЬ РАЗНЫХ строк `unmeasured`, и ни одна не выдаётся за «чисто».

Сцена синтетическая НАМЕРЕННО: предмет пробы — её решающая часть, а не скорость
`git archive`. Боевая сборка сцены проверяется отдельным тестом ниже, и её
отказ — третий исход с названной причиной, а не красный тест.

FROZEN-DATE-OK: нет ни одной литеральной даты — сцена строится в tmp_path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca

_DATA_FILES = ("alpha_log.json", "beta_log.json", "gamma_log.json")


def _scene(root: Path, writes: tuple[str, ...] = (), *, decoy_text: str = "") -> Path:
    """Сцена: `data/` с тремя файлами и один тест-модуль, пишущий `writes`."""
    (root / "data").mkdir(parents=True, exist_ok=True)
    for name in _DATA_FILES:
        (root / "data" / name).write_text(json.dumps([{"before": True}]),
                                          encoding="utf-8")
    body = [
        "# " + decoy_text if decoy_text else "",
        "import json, os",
        "from pathlib import Path",
        "",
        "def test_scene():",
        "    root = Path(__file__).resolve().parent",
    ]
    for name in writes:
        body.append(f'    (root / "data" / "{name}").write_text('
                    f'json.dumps([{{"after": True}}]), encoding="utf-8")')
    body.append("    assert True")
    (root / "test_scene_module.py").write_text("\n".join(body) + "\n", encoding="utf-8")
    return root


def _runner(scene, runs):
    env = dict(os.environ, SPA_ENV="ci", PYTHONHASHSEED="0")
    env.pop("SPA_DATA_DIR", None)
    # `--rootdir` объявлен НАМЕРЕННО: без него дочерний pytest ищет ini вверх от
    # cwd, и вердикт начинает зависеть от того, что лежит в $TMPDIR раннера.
    run = subprocess.run([sys.executable, "-m", "pytest", *runs, "-q", "--tb=short",
                          "--rootdir", str(scene),
                          "-p", "no:randomly", "-p", "no:cacheprovider"],
                         cwd=scene, capture_output=True, text=True, timeout=600, env=env)
    return run.returncode, (run.stdout or "")


class WholeContourIsGreen(unittest.TestCase):

    def test_scene_that_writes_nothing_is_satisfied(self):
        with TemporaryDirectory() as td:
            scene = _scene(Path(td))
            status, detail = ca.tracked_write_judge(
                scene, ("test_scene_module.py",), _runner, ref="сцена")
            self.assertEqual(status, ca.SATISFIED, detail)
            self.assertIn("равно нулю", detail)
            self.assertIn("ОБЛАСТЬ ОТВЕТА", detail,
                          "зелёный вердикт обязан называть свою область — иначе "
                          "он читается как «класс закрыт»")


class EveryBrokenLinkIsRedAndNamed(unittest.TestCase):

    def test_each_written_file_is_named_and_its_neighbour_is_not(self):
        for name in _DATA_FILES:
            with self.subTest(file=name):
                with TemporaryDirectory() as td:
                    scene = _scene(Path(td), writes=(name,))
                    status, detail = ca.tracked_write_judge(
                        scene, ("test_scene_module.py",), _runner, ref="сцена")
                    self.assertEqual(status, ca.NOT_SATISFIED, detail)
                    self.assertIn(name, detail, "порванное звено обязано быть НАЗВАНО")
                    for other in _DATA_FILES:
                        if other != name:
                            self.assertNotIn(other, detail,
                                             "вердикт называет файл, которого никто "
                                             "не трогал — имена не доказательство")

    def test_two_written_files_are_both_counted(self):
        with TemporaryDirectory() as td:
            scene = _scene(Path(td), writes=_DATA_FILES[:2])
            status, detail = ca.tracked_write_judge(
                scene, ("test_scene_module.py",), _runner, ref="сцена")
            self.assertEqual(status, ca.NOT_SATISFIED, detail)
            self.assertIn("ТРОНУЛ 2 из 3", detail)


class VerdictIsNotASubstringMatch(unittest.TestCase):
    """ADR-333: дверь в исходнике не есть исход на диске."""

    def test_source_naming_the_door_does_not_make_the_scene_clean(self):
        with TemporaryDirectory() as td:
            scene = _scene(Path(td), writes=(_DATA_FILES[0],),
                           decoy_text="_default_file own_data_dir SPA_DATA_DIR")
            status, detail = ca.tracked_write_judge(
                scene, ("test_scene_module.py",), _runner, ref="сцена")
            self.assertEqual(status, ca.NOT_SATISFIED, detail)
            self.assertIn(_DATA_FILES[0], detail)

    def test_scene_without_the_door_in_source_can_still_be_clean(self):
        """Обратная сторона: отсутствие слова в исходнике пробу НЕ краснит."""
        with TemporaryDirectory() as td:
            scene = _scene(Path(td))
            status, _detail = ca.tracked_write_judge(
                scene, ("test_scene_module.py",), _runner, ref="сцена")
            self.assertEqual(status, ca.SATISFIED)


class ThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» никогда не выдаётся за «чисто»."""

    def _judge(self, scene, runner):
        return ca.tracked_write_judge(scene, ("test_scene_module.py",), runner,
                                      ref="сцена")

    def test_runner_that_raises_is_unmeasured_with_a_reason(self):
        def _boom(_scene, _runs):
            raise OSError("дверь закрыта")
        with TemporaryDirectory() as td:
            status, detail = self._judge(_scene(Path(td)), _boom)
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("прогон не ответил", detail)
        self.assertIn("дверь закрыта", detail)

    def test_run_without_a_summary_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as td:
            status, detail = self._judge(_scene(Path(td)), lambda s, r: (0, "тишина"))
        self.assertEqual(status, ca.UNMEASURED,
                         "нет сводки ⇒ НЕ ИЗМЕРЕНО; «чисто» здесь было бы fail-OPEN")
        self.assertIn("не дал сводки", detail)

    def test_zero_collected_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as td:
            status, detail = self._judge(_scene(Path(td)),
                                         lambda s, r: (5, "0 passed in 0.01s\n"))
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("ноль тестов", detail)

    def test_empty_data_dir_is_unmeasured(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            status, detail = self._judge(root, lambda s, r: (0, "1 passed in 0.01s\n"))
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("ни одного файла", detail)

    def test_missing_data_dir_is_unmeasured(self):
        with TemporaryDirectory() as td:
            status, detail = self._judge(Path(td), lambda s, r: (0, "1 passed\n"))
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("нет каталога data/", detail)

    def test_five_unmeasured_reasons_are_five_different_strings(self):
        """Склеенные исходы и есть fail-OPEN — он тише красного теста."""
        def _boom(_s, _r):
            raise OSError("x")
        seen = []
        with TemporaryDirectory() as td:
            seen.append(self._judge(_scene(Path(td)), _boom)[1])
        with TemporaryDirectory() as td:
            seen.append(self._judge(_scene(Path(td)), lambda s, r: (0, "тишина"))[1])
        with TemporaryDirectory() as td:
            seen.append(self._judge(_scene(Path(td)),
                                    lambda s, r: (5, "0 passed in 0.01s\n"))[1])
        with TemporaryDirectory() as td:
            (Path(td) / "data").mkdir()
            seen.append(self._judge(Path(td), lambda s, r: (0, "1 passed\n"))[1])
        with TemporaryDirectory() as td:
            seen.append(self._judge(Path(td), lambda s, r: (0, "1 passed\n"))[1])
        self.assertEqual(len(set(seen)), 5, seen)


class DeclaredSurfaceIsTheSubject(unittest.TestCase):

    #: Население класса «тест пишет в git-tracked `data/`», ИЗМЕРЕННОЕ по логам
    #: КОНТРОЛЬНОГО прогона `41435243848` (`8f34a8894`, 12 шардов из 12, 68
    #: нарушений — ADR-899/900): **68 тест-модулей · 71 файл `data/`**. Это замер,
    #: а не выбор: заказ G895 называл семь, и семь были срезом ОДНОГО шарда.
    MEASURED_POPULATION = 68

    def test_surface_covers_the_measured_population_and_can_only_grow(self):
        """Поверхность не вправе сузиться — ни молча, ни с объяснением.

        ADR-901: до этой проверки `test_surface_is_not_empty_and_every_module_exists`
        спрашивало только «список непуст и файлы на месте», поэтому модуль, УБРАННЫЙ
        из списка, переставал измеряться и ни один тест этого не говорил — ровно тот
        дефект, которого боялся заказ G896 п. 3. Порог — ИЗМЕРЕННОЕ население, и
        храповик ходит только вверх: нашлось больше ⇒ расширить список И это число
        (замером, не памятью); стало меньше ⇒ красный.
        """
        self.assertGreaterEqual(
            len(ca.TRACKED_WRITE_RUNS), self.MEASURED_POPULATION,
            f"объявленная поверхность {len(ca.TRACKED_WRITE_RUNS)} МЕНЬШЕ "
            f"измеренного населения класса {self.MEASURED_POPULATION}: "
            f"модуль, выпавший из списка, перестаёт измеряться МОЛЧА")
        self.assertEqual(
            len(set(ca.TRACKED_WRITE_RUNS)), len(ca.TRACKED_WRITE_RUNS),
            "в поверхности есть дубль — он завышает её размер, ничего не измеряя")

    def test_surface_is_not_empty_and_every_module_exists(self):
        root = Path(ca.__file__).resolve().parents[2]
        self.assertTrue(ca.TRACKED_WRITE_RUNS, "пустая поверхность мерит ничто")
        missing = [m for m in ca.TRACKED_WRITE_RUNS if not (root / m).is_file()]
        self.assertEqual(missing, [], "объявленный модуль исчез — поверхность "
                                      "сузилась бы МОЛЧА")

    def test_default_call_does_not_pay_the_heavy_price(self):
        """Цена сцены платится РАЗ в цикл, а не на каждом из 12 шардов CI.

        `test_card_acceptance.py::TestRegisteredProbesAreReal` зовёт КАЖДУЮ пробу
        реестра. Без этой ветки каждый шард строил бы сцену ~156 МБ и гонял бы
        вложенный pytest по 50 модулям — класс карточки
        `inbox-pribory-brosayut-odnorazovyi-stend-87-gb`.
        """
        status, detail = ca.PROBES["tracked_data_untouched_by_declared_runs"](None)
        self.assertEqual(status, ca.UNMEASURED,
                         "без аргумента проба обязана СКАЗАТЬ «не измерено», а не "
                         "вернуть «чисто» (инв. #17)")
        self.assertIn(":run", detail, "отказ обязан назвать, КАК его позвать")

    def test_the_card_declares_the_heavy_spec(self):
        """Критерий карточки обязан нести `:run` — иначе он никогда не мерится."""
        root = Path(ca.__file__).resolve().parents[2]
        card = root / "nimbalyst-local/tracker/inbox-testy-pishut-v-git-tracked-data-sessionn.md"
        if not card.is_file():
            self.fail(f"карточки предмета нет в дереве: {card}")
        declared = [ln for ln in card.read_text(encoding="utf-8").splitlines()
                    if ln.startswith("acceptance_probe:")]
        self.assertEqual(len(declared), 1, declared)
        self.assertIn("tracked_data_untouched_by_declared_runs:run", declared[0])

    def test_empty_surface_is_unmeasured_not_satisfied(self):
        saved = ca.TRACKED_WRITE_RUNS
        try:
            ca.TRACKED_WRITE_RUNS = ()
            status, detail = ca.PROBES["tracked_data_untouched_by_declared_runs"]("run")
        finally:
            ca.TRACKED_WRITE_RUNS = saved
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("поверхность пуста", detail)

    def test_probe_is_registered_under_its_name(self):
        self.assertIn("tracked_data_untouched_by_declared_runs", ca.PROBES)


class LiveSceneBuilderAnswersOrNamesWhyNot(unittest.TestCase):
    """Боевая сборка сцены обязана отдать ОБЪЯВЛЕННУЮ поверхность."""

    def test_archive_scene_either_carries_the_surface_or_names_the_reason(self):
        with TemporaryDirectory() as td:
            ok, why = ca._tracked_write_scene("HEAD", Path(td))
            # Скипа здесь нет НАМЕРЕННО (урок #465: скип не краснеет и не
            # проходит — он ИСЧЕЗАЕТ). `git archive HEAD` отдаёт ДЕРЕВО вершины
            # и глубины истории не требует, поэтому отказ здесь есть находка.
            self.assertTrue(ok, f"сцена не собралась: {why}")
            self.assertTrue((Path(td) / "data").is_dir())
            self.assertTrue((Path(td) / ca.TRACKED_WRITE_RUNS[0]).is_file())
            # Пути сцены объявлены ПОИМЁННО — проверяем, что объявление и есть
            # то, что приехало: лишний каталог означал бы вернувшуюся цену.
            got = {q.name for q in Path(td).iterdir()}
            self.assertTrue(got <= set(ca.TRACKED_WRITE_SCENE_PATHS),
                            f"в сцене есть незаявленное: "
                            f"{sorted(got - set(ca.TRACKED_WRITE_SCENE_PATHS))}")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
