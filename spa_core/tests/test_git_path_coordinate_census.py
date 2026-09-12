"""Сторож прибора переписи зовов git по системе координат пути (заказ #574).

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на дефект, который прибор РЕАЛЬНО
выдал по дороге, а не воображаемый. Порядок проверок ровно тот, в котором
дефекты находились (журнал 2026-W37, цикл #575):

*  9 ложных «слепых» из-за геометрии песочницы (две копии лежали по РАЗНЫМ
   путям, и `git rev-parse --show-toplevel` печатал два разных имени);
*  4 ложных «слепых» из-за классификации каталога ПО ИМЕНИ переменной;
* 80 зовов, молча исчезнувших из всех вёдер отчёта (фильтр искал старую строку
   вердикта);
* 68 зовов-призраков — тело двери-помощника, посчитанное зовом ЧЕРЕЗ дверь;
* «устойчив», выданный форме, которая в песочнице вообще НЕ ИСПОЛНИЛАСЬ.

Проверка про сам предмет — differential: прибор обязан находить аварию #574 на
коде, где её вернули, и молчать на коде, где её починили.
"""
import importlib.util
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SPEC = importlib.util.spec_from_file_location(
    "git_path_coordinate_census",
    Path(__file__).resolve().parents[2] / "scripts" / "git_path_coordinate_census.py")
census_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census_mod)


def _tree(tmp: Path, **modules):
    """Крошечное дерево из одного каталога `pkg` с названными модулями."""
    pkg = tmp / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    for name, body in modules.items():
        (pkg / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return census_mod.census(tmp, subdirs=("pkg",))


def _rows(result, verdict):
    return [r for r in result["rows"] if r[2] == verdict]


class FingerprintOf574(unittest.TestCase):
    """Отпечаток аварии: один путь в ОБЕИХ координатах внутри одного скоупа."""

    SHAPE = """
        import subprocess

        def _git(args, cwd):
            return subprocess.run(["git"] + args, cwd=str(cwd),
                                  capture_output=True).stdout

        def base_provenance(worktree, repo_path):
            given = worktree
            %s
            blob = _git(["cat-file", "blob", f"HEAD:{repo_path}"], %s)
            seen = _git(["rev-list", "--max-count=12", "HEAD", "--", repo_path], %s)
            return blob, seen
    """

    def test_fires_when_the_launch_directory_is_not_a_proven_root(self):
        """Ровно код, доставленный #573: каталог ФАЙЛА, а не корень репозитория."""
        res = _tree(Path(self.tmp), m=self.SHAPE % ("", "given", "given"))
        hits = res["fingerprint"]
        self.assertEqual(len(hits), 1, "форма #574 не опознана вовсе")
        self.assertTrue(hits[0]["unsafe"],
                        "форма #574 при НЕдоказанном корне обязана быть находкой")
        self.assertEqual(hits[0]["path_expr"], "repo_path")

    def test_silent_when_the_launch_directory_is_a_proven_root(self):
        """Ровно код, доставленный #574: обоим зовам закреплён корень.

        Обратная сторона контроля выше. Без неё прибор краснел бы на уже
        починенном коде, и первый же цикл отключил бы его целиком."""
        fixed = self.SHAPE % (
            'root = _git(["rev-parse", "--show-toplevel"], given).decode().strip()',
            "root", "root")
        res = _tree(Path(self.tmp), m=fixed)
        hits = res["fingerprint"]
        self.assertEqual(len(hits), 1, "форма обязана быть ВИДНА и в починенном коде")
        self.assertFalse(hits[0]["unsafe"],
                         f"починенный код объявлен находкой: {hits[0]['safe_reason']}")
        self.assertIn("доказанный корень", hits[0]["safe_reason"])

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)


class RootIsProvenanceNotAName(unittest.TestCase):
    """Каталог-корень опознаётся ПРОВЕНАНСОМ, а не именем переменной.

    Догадка по имени ошибается в ОБЕ стороны, и обе наблюдались на живом наборе:
    `cwd=work` (настоящий корень временной копии) дал четыре ложные находки, а
    любая переменная по имени `repo_path` прошла бы за корень, им не будучи."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)

    BODY = """
        import subprocess

        def _git(args, cwd):
            return subprocess.run(["git"] + args, cwd=str(cwd),
                                  capture_output=True).stdout

        def f(where, repo_path):
            %s
            _git(["cat-file", "blob", f"HEAD:{repo_path}"], %s)
            _git(["rev-list", "HEAD", "--", repo_path], %s)
    """

    def test_a_variable_merely_named_root_is_not_accepted(self):
        res = _tree(Path(self.tmp), m=self.BODY % ("root = where", "root", "root"))
        hits = res["fingerprint"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["unsafe"],
                        "имя `root` принято за корень без единого доказательства")

    def test_a_variable_named_work_IS_accepted_when_it_came_from_git(self):
        proven = self.BODY % (
            'work = _git(["rev-parse", "--show-toplevel"], where).decode()',
            "work", "work")
        res = _tree(Path(self.tmp), m=proven)
        hits = res["fingerprint"]
        self.assertEqual(len(hits), 1)
        self.assertFalse(hits[0]["unsafe"],
                         "доказанный корень отвергнут из-за своего имени")


class HelperDoorIsResolved(unittest.TestCase):
    """Зов через дверь-помощник обязан входить в население.

    Без этого шага прибор слеп ровно там, ради чего заказан: `push_base_provenance`
    весь git зовёт через `_git_bytes(args, cwd)`, и в самом зове argv это
    `["git"] + args` — не сложился. Замер #575 до починки: 57 зовов из 117 были
    дверьми, а не зовами, и авария #574 прибору была НЕ ВИДНА."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_call_through_a_door_carries_the_callers_argv(self):
        res = _tree(Path(self.tmp), m="""
            import subprocess

            def _git(args, cwd):
                return subprocess.run(["git"] + args, cwd=str(cwd)).stdout

            def f(where):
                _git(["ls-files", "docs/STATE.md"], where)
        """)
        through = [r for r in res["rows"] if r[0]["via"] == "_git"]
        self.assertEqual(len(through), 1, "зов через дверь не опознан")
        self.assertEqual(through[0][0]["argv"], ["git", "ls-files", "docs/STATE.md"])

    def test_the_door_body_itself_is_not_counted_as_a_call(self):
        """Тело двери — не зов через неё. Считать его населением значит
        записать один и тот же git дважды и посадить призрак в «НЕ ИЗМЕРЕНО»."""
        res = _tree(Path(self.tmp), m="""
            import subprocess

            def _git(args, cwd):
                return subprocess.run(["git"] + args, cwd=str(cwd)).stdout

            def f(where):
                _git(["ls-files", "docs/STATE.md"], where)
        """)
        self.assertEqual(len(res["rows"]), 1,
                         f"призрак двери попал в население: {[r[0] for r in res['rows']]}")


class ProbeGeometry(unittest.TestCase):
    """Два прогона обязаны отличаться РОВНО каталогом запуска."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.addCleanup(self._td.cleanup)
        self.pristine = self.tmp / "pristine"
        self.scratch = self.tmp / "scratch"
        self.pristine.mkdir()
        self.scratch.mkdir()
        self.env = census_mod.build_probe_repo(self.pristine)

    def _observe(self, argv, roles=None):
        return census_mod.observe_sensitivity(
            argv, roles or {"pathspec": [], "root_relative": []},
            self.pristine, self.env, self.scratch)

    def test_show_toplevel_is_insensitive(self):
        """Зов БЕЗ пути вообще. Первая редакция клала копии по разным путям
        (`w_root`/`w_sub`), и он немедленно объявлялся чувствительным — печатал
        два разных ИМЕНИ КОПИИ. Три из девяти первых находок были этим."""
        verdict, why = self._observe(["git", "rev-parse", "--show-toplevel"])
        self.assertEqual(verdict, "insensitive", f"ложная чувствительность: {why}")

    def test_neutralisation_never_touches_what_follows_a_double_dash(self):
        """Подмена не-путевых аргументов обязана обходить ПУТЬ стороной, даже
        когда роли пришли пустыми. Первая редакция превращала
        `log HEAD -- P.txt` в `log HEAD -- HEAD`: предмет замера исчезал, и
        форма объявлялась устойчивой — прибор гасил сам себя."""
        out, changed = census_mod._neutralise(
            ["git", "log", "no/such/ref", "--", census_mod.PATH_PLACEHOLDER],
            {"pathspec": [], "root_relative": []}, Path(self.tmp))
        self.assertEqual(out[-1], census_mod.PATH_PLACEHOLDER)
        self.assertEqual(changed, ["ревизия → HEAD"])
        verdict, _why = self._observe(
            ["git", "log", "no/such/ref", "--", census_mod.PATH_PLACEHOLDER])
        self.assertEqual(verdict, "sensitive",
                         "путь уничтожен подменой — замер отвечает не на свой вопрос")

    def test_pathspec_form_is_observed_sensitive(self):
        """Обратная сторона: настоящая чувствительность обязана быть ВИДНА,
        иначе тест выше проходил бы и на приборе, всегда говорящем «устойчив»."""
        roles = {"pathspec": [{"idx": 4, "token": census_mod.PATH_PLACEHOLDER,
                               "expr": "p"}], "root_relative": []}
        verdict, _why = self._observe(
            ["git", "rev-list", "HEAD", "--", census_mod.PATH_PLACEHOLDER], roles)
        self.assertEqual(verdict, "sensitive")

    def test_rev_path_form_is_observed_insensitive(self):
        """`HEAD:<путь>` читается ОТ КОРНЯ — вторая координата, и она тоже
        установлена наблюдением, а не знанием автора про git."""
        verdict, _why = self._observe(
            ["git", "cat-file", "blob", f"HEAD:{census_mod.PATH_PLACEHOLDER}"])
        self.assertEqual(verdict, "insensitive")

    def test_a_form_that_did_not_run_is_unmeasured_not_robust(self):
        """Два одинаковых ОТКАЗА — отсутствие ответа, а не «ответ не меняется».
        Прибор выдавал такой зов за устойчивый (инв. #17)."""
        verdict, why = self._observe(["git", "grep"])   # без образца git падает
        self.assertEqual(verdict, "unmeasured", f"несостоявшийся замер выдан за вердикт: {why}")
        self.assertIn("не исполнилась", why)


class PopulationBoundaries(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_bare_positional_of_log_is_a_revision_not_a_path(self):
        """`origin/main` — ревизия. Считать её путём, потому что в ней есть «/»,
        значит изготовить находку из ничего."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            subprocess.run(["git", "log", "--oneline", "origin/main"])
        """)
        self.assertEqual(len(res["population"]), 0,
                         "ревизия посчитана путём от каталога запуска")

    def test_option_value_is_not_mistaken_for_a_subcommand(self):
        """`git -c user.email=x commit` — подкоманда `commit`, а не `user.email=x`.
        На живом наборе 11 зовов уезжали в «НЕ ИЗМЕРЕНО» по этому дефекту разбора."""
        argv = ["git", "-c", "user.email=t@t", "log", "--oneline"]
        self.assertEqual(census_mod._subcommand(argv), "log")

    def test_blame_line_range_is_not_a_path(self):
        """`-L 12,12` забирает следующий аргумент; без списка таких опций
        прибор называл переменную СТРОКИ переменной ПУТИ."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            def f(lineno, filepath):
                subprocess.run(["git", "blame", "-L", f"{lineno},{lineno}",
                                "-p", filepath])
        """)
        self.assertEqual(len(res["population"]), 1)
        self.assertEqual(res["population"][0][1]["dynamic_path"], "filepath")

    def test_a_call_without_a_cwd_relative_path_is_out_of_the_class(self):
        """`git init` чувствителен к каталогу ПО ПРИРОДЕ и к этому классу
        отношения не имеет. Редакция вердикта без этого вопроса объявила
        слепыми шесть таких зовов из девяти."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            subprocess.run(["git", "init", "-q", "-b", "main"])
        """)
        self.assertEqual([r[2] for r in res["rows"]], ["NO_PATH_FROM_CWD"])

    def test_every_call_lands_in_exactly_one_bucket(self):
        """Вёдра отчёта обязаны РАЗБИВАТЬ население. Фильтр, искавший старую
        строку вердикта, ронял 80 зовов из 155 молча — ни в одном ведре."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            def f(p, where):
                subprocess.run(["git", "init"])
                subprocess.run(["git", "ls-files", "docs/STATE.md"], cwd=where)
                subprocess.run(["git", "hash-object", p])
        """)
        buckets = sum(len(res[k]) for k in
                      ("blind", "robust", "unmeasured_calls", "no_cwd_path"))
        self.assertEqual(buckets, res["calls_total"],
                         "вёдра не разбивают население — часть зовов исчезла молча")


class ThirdOutcome(unittest.TestCase):
    """Инв. #17: «не измерено» отличимо и от «чисто», и от находки."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_variable_path_is_unmeasured_not_blind(self):
        """Путь переменной может оказаться абсолютным в рантайме. Объявлять
        такой зов слепым — изготовить находку; ловушка названа заказом заранее."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            def f(p):
                subprocess.run(["git", "hash-object", p])
        """)
        self.assertEqual(len(res["blind"]), 0)
        self.assertEqual(len(res["unmeasured_calls"]), 1)
        self.assertIn("ПЕРЕМЕННОЙ", res["unmeasured_calls"][0][3])

    def test_literal_relative_path_without_any_pin_is_blind(self):
        """Обратная сторона: доказуемо слепой зов обязан БЫТЬ находкой, иначе
        тест выше проходил бы и на приборе, который не находит ничего."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            subprocess.run(["git", "ls-files", "docs/STATE.md"])
        """)
        self.assertEqual(len(res["blind"]), 1, [r[2:] for r in res["rows"]])
        self.assertIn("не закреплён", res["blind"][0][3])

    def test_pinned_but_unproven_directory_is_unmeasured(self):
        res = _tree(Path(self.tmp), m="""
            import subprocess
            def f(somewhere):
                subprocess.run(["git", "ls-files", "docs/STATE.md"], cwd=somewhere)
        """)
        self.assertEqual(len(res["blind"]), 0)
        self.assertIn("не доказано", res["unmeasured_calls"][0][3])

    def test_unparsable_file_is_named_not_skipped(self):
        tmp = Path(self.tmp)
        (tmp / "pkg").mkdir()
        (tmp / "pkg" / "broken.py").write_text("def (:\n", encoding="utf-8")
        res = census_mod.census(tmp, subdirs=("pkg",))
        self.assertTrue(res["unmeasured_files"])
        self.assertIn("не разобран AST", res["unmeasured_files"][0])

    def test_shell_scripts_are_named_as_outside_the_measurement(self):
        tmp = Path(self.tmp)
        (tmp / "pkg").mkdir()
        (tmp / "pkg" / "a.sh").write_text("cd /tmp && git ls-files docs/\n")
        res = census_mod.census(tmp, subdirs=("pkg",))
        self.assertEqual(res["shell_scripts"], ["pkg/a.sh"])
        self.assertIn("НЕ ИЗМЕРЕНЫ", census_mod.render(res))

    def test_an_unobservable_form_without_a_path_is_still_out_of_the_class(self):
        """Порядок вопросов в вердикте. `git fetch` в сеть не пойдёт (прибор не
        ходит), то есть форма НЕ НАБЛЮДАЕМА — но пути от каталога она не несёт,
        и значит к классу отношения не имеет. Спрашивать про наблюдение РАНЬШЕ,
        чем про наличие пути, значит записать в «НЕ ИЗМЕРЕНО» зовы, которые
        измерять и не требовалось: на живом наборе так набиралось 87 вместо 74,
        и раздутое «не измерено» прячет настоящее."""
        res = _tree(Path(self.tmp), m="""
            import subprocess
            subprocess.run(["git", "fetch", "origin", "main"])
        """)
        self.assertEqual([r[2] for r in res["rows"]], ["NO_PATH_FROM_CWD"],
                         "ненаблюдаемая форма БЕЗ пути записана в «НЕ ИЗМЕРЕНО»")

    def test_a_network_subcommand_carrying_a_path_is_unmeasured(self):
        """Обратная сторона: если сетевая подкоманда путь всё-таки несёт,
        вердикта у неё нет — прибор в сеть не ходит, и «упало одинаково» было бы
        вердиктом про отсутствие сети, а не про координаты."""
        verdict, why = census_mod.observe_sensitivity(
            ["git", "fetch", "origin", "--", "P.txt"],
            {"pathspec": [{"idx": 4, "token": "P.txt", "expr": "p"}],
             "root_relative": []},
            Path(self.tmp), dict(), Path(self.tmp))
        self.assertEqual(verdict, "unmeasured")
        self.assertIn("сет", why)

    def test_unbuildable_sandbox_is_unmeasured_not_clean(self):
        """Если песочница не построилась — вердикта нет вовсе, и код возврата
        обязан это сказать."""
        broken = {"measured": False, "reason": "песочница не построена"}
        self.assertIn("НЕ ИЗМЕРЕНО", census_mod.render(broken))


class ExitCodes(unittest.TestCase):
    """ADR-347: единицу не занимать — её выдаёт CPython при любом исключении,
    и тогда крах прибора неотличим от его находки."""

    def test_codes_are_distinct_and_one_is_left_to_the_interpreter(self):
        self.assertEqual(census_mod.EXIT_CLEAN, 0)
        self.assertEqual(census_mod.EXIT_UNMEASURED, 2)
        self.assertEqual(census_mod.EXIT_FINDING, 3)
        self.assertNotIn(1, {census_mod.EXIT_CLEAN, census_mod.EXIT_UNMEASURED,
                             census_mod.EXIT_FINDING})

    def test_a_crashing_run_exits_one_and_is_therefore_not_a_verdict(self):
        script = Path(census_mod.__file__)
        res = subprocess.run(
            ["python3", "-c",
             f"import runpy,sys; sys.argv=['x','--root','/nope/nope'];"
             f" runpy.run_path({str(script)!r}, run_name='__main__')"],
            capture_output=True, timeout=120)
        self.assertNotEqual(res.returncode, census_mod.EXIT_FINDING,
                            "крах прибора предъявлен как его находка")


if __name__ == "__main__":
    unittest.main()
