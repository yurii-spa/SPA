# LLM_FORBIDDEN
"""Сторож переписи «ЧЕТВЁРТАЯ переменная рода „канал наблюдения"» (ADR-1040).

Заказ G1028 п. 1 назвал предмет и способ: «переменные, которые воркфлоу объявляет
шагу pytest, × те, что читает ``pytest_configure`` любого нашего плагина; затем
дифференциал (ребёнок с унаследованным окружением против ребёнка с чистым)».

**Каждая проверка здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ.** Она либо воспроизводит настоящую
аварию (`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»), либо
воспроизводит ЛОЖНЫЙ ОТВЕТ, который прибор выдал на живом дереве в этом же цикле и
который был снят ДО того, как число попало в ADR. Таких ложных ответов было ТРИ, и
каждый терял ОДНОГО И ТОГО ЖЕ известного члена класса — ``SPA_PYTEST_RESUME_ONLY``,
— но по РАЗНОЙ причине:

1. **одно место объявления.** Ось «объявлено шагу pytest» спрашивала только ``env:``
   воркфлоу — ровно как сказано в заказе. Этой переменной ни один воркфлоу не
   объявляет: её кладёт ``scripts/ci_control.py`` в окружение дочернего pytest при
   доигрывании. Замер, не нашедший известного члена, мерой класса не является;
2. **«RHS упоминает засеянное имя» вместо ФОРМЫ отображения.** Такое правило
   засевает ``code = subprocess.run(cmd, env=e)`` и каскадом уходит по всему модулю:
   засев не сошёлся за шесть кругов у ЧЕТЫРЁХ модулей, среди них — тот самый
   ``ci_control.py``. Третий исход при этом сработал ВЕРНО и бесполезно;
3. **засев глубиной 1.** ``e = dict(base_env)``, а ``base_env = dict(os.environ if
   env is None else env)`` — два хопа И тернарный выбор. Без неподвижной точки и без
   ветви ``IfExp`` член терялся снова.

**Отдельно воспроизводится авария 17.10 — прибором НА СЕБЕ.** Первый зов
дифференциала положил в ``SPA_PYTEST_RESUME_ONLY`` ПУСТОЙ файл, и сцена погасла
целиком («1 deselected», код 5). Это ровно тот вред, ради которого ту переменную
снимают с окружения, — и прибор ответил о нём честным третьим исходом, а не нулём.

Ни один тест здесь не спрашивает ни календарь, ни ``ps``, ни номер процесса: классы
`.claude/rules/deployment.md` про КАЛЕНДАРЬ, ЛИЧНОСТЬ ПРОЦЕССА и ГЛУБИНУ КЛОНА к
этому файлу не применимы, и литеральных дат в нём нет.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import observation_channel_env_census as oc

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PLUGINS = ("spa_core.ci.pytest_stream_record", "spa_core.ci.pytest_collect_manifest")


def _tmp():
    class _Ctx:
        def __enter__(self) -> Path:
            self._d = tempfile.TemporaryDirectory(prefix="oc_env_census_")
            return Path(self._d.name)

        def __exit__(self, *exc) -> None:
            self._d.cleanup()

    return _Ctx()


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


_WORKFLOW = """\
name: scene
env:
  TOP_LEVEL: top
jobs:
  test:
    steps:
      - name: Install
        run: pip install pytest==9.1.1
        env:
          NOT_A_CHANNEL: never
      - name: Install bare
        run: pip install pytest
        env:
          BARE_PIP_NOT_A_CHANNEL: never
      - name: Run
        run: |
          python -m pytest spa_core/tests/ -q -p pkg.plugin
        env:
          SCENE_CHANNEL: out/scene.jsonl
          SCENE_MODE: ci
"""

_PLUGIN = """\
import os

CHANNEL_ENV = "SCENE_CHANNEL"
_FH = None


def pytest_configure(config):
    global _FH
    path = os.environ.pop(CHANNEL_ENV, None)
    mode = os.environ.get("SCENE_MODE")
    if path:
        _FH = open(path, "w", encoding="utf-8")
"""


class AxisOneHasTwoDeclarationPlaces(unittest.TestCase):
    """Ложный ответ №1: один замер — одно место объявления — теряет члена класса."""

    def test_the_workflow_axis_alone_misses_a_variable_declared_by_code(self) -> None:
        with _tmp() as tmp:
            root = _tree(tmp, {
                ".github/workflows/scene.yml": _WORKFLOW,
                "pkg/plugin.py": _PLUGIN,
                # Площадка КОДА: переменную кладёт модуль, поднимающий дочерний pytest.
                "scripts/runner.py": (
                    "import os, subprocess, sys\n\n"
                    "RESUME_ENV = 'SCENE_RESUME'\n\n\n"
                    "def run(env=None):\n"
                    "    base_env = dict(os.environ if env is None else env)\n"
                    "    e = dict(base_env)\n"
                    "    e[RESUME_ENV] = '/tmp/resume.txt'\n"
                    "    return subprocess.run([sys.executable, '-m', 'pytest'], env=e)\n"),
            })
            doc = oc.census(root, roots=("scripts", "pkg"))
            self.assertEqual(doc["status"], "measured", doc.get("why"))
            self.assertIn(
                "SCENE_RESUME", doc["declared"],
                "ось объявления не увидела переменную, объявленную КОДОМ — ровно "
                "ложный ответ первой редакции, потерявший SPA_PYTEST_RESUME_ONLY")
            places = {d["place"] for d in doc["declared"]["SCENE_RESUME"]}
            self.assertEqual(places, {"code"}, places)
            self.assertEqual(
                {d["place"] for d in doc["declared"]["SCENE_CHANNEL"]}, {"workflow"})

    def test_a_pip_install_line_is_not_a_pytest_invocation(self) -> None:
        """Установка инструмента каналом не распоряжается — шаг в ось не входит.

        Сцена несёт ДВЕ формы установки, и РАЗЛИЧАЮЩАЯ здесь вторая. Первая
        редакция сцены имела только ``pip install pytest==9.1.1``, где слово
        ``pytest`` упирается в ``=``: такую строку отклоняет сам образец вызова, а
        не отсечка ``pip``, — и мутация «считать `pip install` зовущим pytest»
        ВЫЖИЛА (замер этого цикла). Мутация без различающей сцены выживает; ответ —
        сцена, а не правка мутации.
        """
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": _PLUGIN})
            doc = oc.census(root, roots=("pkg",))
            for name in ("NOT_A_CHANNEL", "BARE_PIP_NOT_A_CHANNEL"):
                self.assertNotIn(
                    name, doc["declared"],
                    f"окружение шага `pip install` ({name}) попало в ось объявления: "
                    "шаг, который pytest не зовёт, каналом не распоряжается")
            self.assertEqual([s["step"] for s in doc["steps"]], ["Run"])
            self.assertFalse(oc.invokes_pytest("pip install pytest"))
            self.assertTrue(oc.invokes_pytest("python -m pytest tests/ -q"))

    def test_the_env_of_the_workflow_and_of_the_job_is_visible_to_the_step(self) -> None:
        """Ребёнок наследует ОБЪЕДИНЕНИЕ трёх уровней, а не только ``env`` шага."""
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": _PLUGIN})
            doc = oc.census(root, roots=("pkg",))
            self.assertIn("TOP_LEVEL", doc["declared"])


class TheEnvMappingIsSeededToAFixedPoint(unittest.TestCase):
    """Ложные ответы №2 и №3: форма засева и его глубина."""

    def test_two_hops_and_a_ternary_choice_still_name_the_variable(self) -> None:
        """``e = dict(base_env)``, ``base_env = dict(os.environ if … else env)``."""
        with _tmp() as tmp:
            root = _tree(tmp, {
                "scripts/runner.py": (
                    "import os, subprocess, sys\n\n"
                    "K = 'SCENE_DEEP'\n\n\n"
                    "def run(env=None):\n"
                    "    base_env = dict(os.environ if env is None else env)\n"
                    "    mid = base_env.copy()\n"
                    "    e = dict(mid)\n"
                    "    e[K] = 'x'\n"
                    "    return subprocess.run([sys.executable, '-m', 'pytest'], env=e)\n"),
            })
            rows = oc.declared_by_code(root, ("scripts",))
            self.assertEqual(rows["unreadable"], [], rows["unreadable"])
            self.assertIn("SCENE_DEEP", rows["rows"],
                          "засев не дошёл до третьего хопа — член класса потерян")

    def test_an_ordinary_dict_key_is_not_an_environment_variable(self) -> None:
        """Ось объявления, считающая ключом окружения ЛЮБУЮ запись индексом, нечитаема.

        Первая редакция так дала 276 «переменных» на живом дереве — среди них
        ``aave_v3``, ``cmd``, ``path``. Шум не ломает пересечение, но делает
        поверхность непроверяемой, а непроверяемая поверхность мерой не является.
        """
        with _tmp() as tmp:
            root = _tree(tmp, {
                "scripts/runner.py": (
                    "import os, subprocess, sys\n\n\n"
                    "def run():\n"
                    "    e = dict(os.environ)\n"
                    "    e['REAL_ENV'] = '1'\n"
                    "    totals = {}\n"
                    "    totals['aave_v3'] = 7\n"
                    "    return subprocess.run([sys.executable, '-m', 'pytest'], env=e)\n"),
            })
            rows = oc.declared_by_code(root, ("scripts",))["rows"]
            self.assertIn("REAL_ENV", rows)
            self.assertNotIn("aave_v3", rows,
                             "ключ обычного словаря выдан за переменную окружения")

    def test_a_result_of_a_call_taking_the_env_is_not_itself_an_env(self) -> None:
        """``code = subprocess.run(cmd, env=e)`` засевать НЕЛЬЗЯ — отсюда каскад."""
        with _tmp() as tmp:
            root = _tree(tmp, {
                "scripts/runner.py": (
                    "import os, subprocess, sys\n\n\n"
                    "def run():\n"
                    "    e = dict(os.environ)\n"
                    "    code = subprocess.run([sys.executable, '-m', 'pytest'], env=e)\n"
                    "    code['NOT_AN_ENV_KEY'] = 1\n"
                    "    return code\n"),
            })
            out = oc.declared_by_code(root, ("scripts",))
            self.assertEqual(out["unreadable"], [], out["unreadable"])
            self.assertNotIn("NOT_AN_ENV_KEY", out["rows"],
                             "каскад засева вернулся: результат вызова объявлен окружением")

    def test_an_unconverged_seeding_is_a_named_third_outcome(self) -> None:
        """Исчерпание кругов — «НЕ ИЗМЕРЕНО» с причиной, а не тихая остановка."""
        chain = "    a0 = dict(os.environ)\n" + "".join(
            f"    a{i + 1} = dict(a{i})\n" for i in range(oc._SEED_ROUNDS + 3))
        with _tmp() as tmp:
            root = _tree(tmp, {
                "scripts/runner.py": (
                    "import os, subprocess, sys\n\n\n"
                    "def run():\n" + chain
                    + f"    a{oc._SEED_ROUNDS + 3}['LAST'] = '1'\n"
                    "    return subprocess.run([sys.executable, '-m', 'pytest'])\n"),
            })
            out = oc.declared_by_code(root, ("scripts",))
            self.assertEqual(len(out["unreadable"]), 1, out)
            self.assertIn("НЕ ИЗМЕРЕН", out["unreadable"][0]["why"])
            self.assertNotIn("LAST", out["rows"],
                             "непросчитанный модуль отдал ключи как измеренные")


class AxisTwoReadsTheConfigureOfThePlugin(unittest.TestCase):
    """Ось 2: что читает ``pytest_configure`` (и уровень модуля) нашего плагина."""

    def test_the_plugin_list_is_measured_from_the_workflow_not_remembered(self) -> None:
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": _PLUGIN})
            doc = oc.census(root, roots=("pkg",))
            self.assertEqual(sorted(doc["plugins"]["found"]), ["pkg.plugin"])
            self.assertIn("SCENE_CHANNEL", doc["read"])
            self.assertIn("SCENE_MODE", doc["read"])

    def test_a_plugin_the_workflow_never_loads_is_outside_the_surface(self) -> None:
        """ЦЕНА названа: загруженным в CI такой плагин не бывает."""
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": _PLUGIN,
                               "pkg/stranger.py": _PLUGIN.replace("SCENE_CHANNEL",
                                                                  "STRANGER_CHANNEL")})
            doc = oc.census(root, roots=("pkg",))
            self.assertNotIn("pkg.stranger", doc["plugins"]["found"])

    def test_a_key_built_by_an_expression_is_unresolved_not_silent(self) -> None:
        plugin = ("import os\n\n\n"
                  "def pytest_configure(config):\n"
                  "    os.environ.pop('PRE' + 'FIX', None)\n")
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": plugin})
            doc = oc.census(root, roots=("pkg",))
            self.assertTrue(doc["unresolved"], "имя-выражение проехало молча")
            self.assertTrue(all(r["why"] for r in doc["unresolved"]))

    def test_setdefault_is_a_write_and_never_makes_a_channel(self) -> None:
        """``os.environ.setdefault`` — запись в СВОЁ окружение, не чтение канала."""
        plugin = ("import os\n\n"
                  "os.environ.setdefault('SCENE_CHANNEL', 'x')\n")
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": plugin})
            doc = oc.census(root, roots=("pkg",))
            self.assertNotIn("SCENE_CHANNEL", doc["candidates"],
                             "`setdefault` сделал переменную кандидатом в канал")


class TheThirdOutcomeIsNeverAZero(unittest.TestCase):
    """Инв. #17 у каждой двери: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО."""

    def test_a_missing_workflow_directory_is_unmeasured_with_a_reason(self) -> None:
        with _tmp() as tmp:
            doc = oc.census(tmp, roots=())
            self.assertEqual(doc["status"], "unmeasured")
            self.assertIn("не прочитан", str(doc["why"]))

    def test_an_unparsable_workflow_is_named_not_skipped(self) -> None:
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/broken.yml": "a: [unclosed\n",
                               "pkg/plugin.py": _PLUGIN})
            doc = oc.census(root, roots=("pkg",))
            self.assertEqual(doc["status"], "unmeasured")
            self.assertIn("broken.yml", str(doc["why"]))

    def test_every_status_and_verdict_the_doors_return_is_declared(self) -> None:
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": _PLUGIN})
            doc = oc.census(root, roots=("pkg",))
            self.assertIn(doc["status"], oc.DECLARED_STATUSES)
            probe = {"status": "unmeasured", "seen": {}, "why": "сцена не поднималась"}
            for row in oc.verdicts(doc, probe).values():
                self.assertIn(row["verdict"], oc.DECLARED_VERDICTS, row)

    def test_a_probe_that_did_not_report_is_not_read_as_nothing_inherited(self) -> None:
        """«Доклада ребёнка нет» и «ребёнок ничего не унаследовал» — РАЗНЫЕ ответы."""
        with _tmp() as tmp:
            root = _tree(tmp, {".github/workflows/scene.yml": _WORKFLOW,
                               "pkg/plugin.py": _PLUGIN})
            doc = oc.census(root, roots=("pkg",))
            silent = {"status": "unmeasured", "seen": {}, "why": "доклада ребёнка нет"}
            rows = oc.verdicts(doc, silent)
            self.assertTrue(rows)
            for name, row in rows.items():
                self.assertEqual(row["verdict"], "unmeasured", (name, row))
                self.assertNotEqual(row["verdict"], "door_closed")


class TheDifferentialDecidesMembershipNotTheClaim(unittest.TestCase):
    """Членство — ПО ИСХОДУ живой сцены, а не по ``pop`` рядом с абзацем про снятие.

    Записка не есть инъекция (цикл #477): претензию обязан мерить прибор. Здесь
    претензия ``claim_removed`` и исход дифференциала сверяются, и расхождение
    НАЗЫВАЕТСЯ полем ``claim_holds``.
    """

    def _probe(self, tmp: Path, watched: list[str]) -> dict:
        scene = tmp / "scene"
        scene.mkdir(parents=True, exist_ok=True)
        resume = scene / "resume.txt"
        resume.write_text(oc.PROBE_SCENE_NODEID + "\n", encoding="utf-8")
        env_values = {
            "SPA_ENV": "ci",
            "SPA_PYTEST_MANIFEST": str(tmp / "collected.jsonl"),
            "SPA_PYTEST_STREAM": str(tmp / "stream.jsonl"),
            "SPA_PYTEST_RESUME_ONLY": str(resume),
        }
        return oc.inheritance_probe(watched, scene, plugins=_PLUGINS,
                                    env_values=env_values)

    def test_the_three_closed_channels_do_not_reach_the_child(self) -> None:
        """ЖИВОЙ замер: обе переменные ADR-1039 и список доигрывания — у ребёнка НЕТ."""
        watched = ["SPA_PYTEST_STREAM", "SPA_PYTEST_MANIFEST", "SPA_PYTEST_RESUME_ONLY"]
        with _tmp() as tmp:
            probe = self._probe(tmp, watched)
            self.assertEqual(probe["status"], "measured", probe["why"])
            for name in watched:
                self.assertIsNone(
                    probe["seen"].get(name),
                    f"{name} дошла до ребёнка — дверь ADR-1039 ОТКРЫТА: {probe['seen']}")

    def test_the_child_of_the_probe_pins_its_rootdir_to_the_scene(self) -> None:
        """Якорь `rootdir` у ребёнка — не украшение, а цена 300 с (замер #382).

        Без якоря pytest считает rootdir общим предком cwd и аргумента и обходит
        scandir'ом весь системный временный каталог. Сторож
        `test_child_pytest_rootdir` считает такой зов членом своего предмета, и
        приехать НОВЫМ членом в уже красный храповик значило бы молча его ослабить
        (инв. #16) — поэтому утверждение закреплено ЗДЕСЬ, у виновника.

        Имена флагов сверяются с КАНОНОМ (`_child_pytest.ROOTDIR_FLAGS`): литерал
        рядом с каноном без сверки — та же «записка вместо инъекции» (цикл #477).
        """
        from spa_core.tests import _child_pytest

        self.assertEqual(tuple(_child_pytest.ROOTDIR_FLAGS),
                         ("--rootdir", "--confcutdir"),
                         "канон флагов якоря переименован — сверить с ним литералы ниже")
        source = Path(oc.__file__).read_text(encoding="utf-8")
        for flag in ("--rootdir", "--confcutdir"):
            self.assertIn(
                f"{flag}={{scene_dir}}", source,
                f"дочерний pytest прибора не пинит {flag} на каталог СЦЕНЫ")

    def test_the_probe_declares_itself_a_sandbox_and_names_its_own_tree(self) -> None:
        """Дверь песочницы (C8(b), ADR-580) — у ПРИБОРА, а не только у сторожа.

        Прибор ADR-1038 приехал без этой двери и покрасил `test_sandbox_wiring_ratchet`
        в ДЕНЬ доставки. Здесь то же утверждение закреплено СВОЕЙ пробой: ребёнок
        обязан видеть маркер песочницы И каталог данных, лежащий ВНУТРИ сцены, —
        иначе его запись ушла бы в прод (класс INC-1).
        """
        from spa_core.utils import live_paths as lp

        watched = [lp.SANDBOX_ENV, lp.DATA_DIR_ENV, lp.LIVE_ROOT_ENV]
        with _tmp() as tmp:
            probe = self._probe(tmp, watched)
            self.assertEqual(probe["status"], "measured", probe["why"])
            self.assertEqual(probe["seen"].get(lp.SANDBOX_ENV), "1",
                             f"маркер песочницы до ребёнка не дошёл: {probe['seen']}")
            for name in (lp.DATA_DIR_ENV, lp.LIVE_ROOT_ENV):
                value = probe["seen"].get(name)
                self.assertTrue(value, f"{name} ребёнку не назван: {probe['seen']}")
                self.assertTrue(
                    str(value).startswith(str(tmp)),
                    f"{name} указывает ВНЕ сцены ({value}) — это и есть утечка в прод")

    def test_the_probe_can_SEE_an_inherited_variable(self) -> None:
        """ОТРИЦАТЕЛЬНЫЙ контроль: прибор, не видящий наследования, бесполезен.

        Без этого теста «членов 0» неотличимо от «прибор слеп». ``SPA_ENV`` до
        ребёнка ДОХОДИТ (и это штатно — режим прогона), и именно поэтому он служит
        доказательством зрения прибора.
        """
        with _tmp() as tmp:
            probe = self._probe(tmp, ["SPA_ENV", "SPA_PYTEST_STREAM"])
            self.assertEqual(probe["status"], "measured", probe["why"])
            self.assertEqual(
                probe["seen"].get("SPA_ENV"), "ci",
                "прибор НЕ ВИДИТ наследования вовсе — тогда и ноль членов ничего "
                f"не значит: {probe['seen']}")
            self.assertIsNone(probe["seen"].get("SPA_PYTEST_STREAM"))

    def test_an_inherited_mode_is_benign_and_an_inherited_path_is_a_member(self) -> None:
        """Два условия членства развязаны: наследование ≠ канал."""
        doc = {"candidates": {
            "MODE": {"claim_removed": False, "plugin_writes_a_file": True,
                     "channel_shape": "mode"},
            "CHANNEL": {"claim_removed": False, "plugin_writes_a_file": True,
                        "channel_shape": "path"},
            "READONLY": {"claim_removed": False, "plugin_writes_a_file": False,
                         "channel_shape": "path"},
        }}
        probe = {"status": "measured", "why": None,
                 "seen": {"MODE": "ci", "CHANNEL": "/tmp/a.jsonl", "READONLY": "/tmp/b"}}
        rows = oc.verdicts(doc, probe)
        self.assertEqual(rows["MODE"]["verdict"], "inherited_benign")
        self.assertEqual(rows["CHANNEL"]["verdict"], "member")
        self.assertEqual(rows["READONLY"]["verdict"], "inherited_benign")

    def test_a_claim_contradicted_by_the_outcome_is_named(self) -> None:
        doc = {"candidates": {"X": {"claim_removed": True,
                                    "plugin_writes_a_file": True,
                                    "channel_shape": "path"}}}
        probe = {"status": "measured", "why": None, "seen": {"X": "/tmp/x.jsonl"}}
        row = oc.verdicts(doc, probe)["X"]
        self.assertFalse(row["claim_holds"],
                         "претензия «снято» подтверждена над унаследованной переменной")
        self.assertEqual(row["verdict"], "member")

    def test_an_unmeasured_channel_shape_does_not_clear_a_member(self) -> None:
        """Форма НЕ ИЗМЕРЕНА ⇒ ошибка идёт в сторону НАХОДКИ, а не «режим»."""
        doc = {"candidates": {"X": {"claim_removed": False,
                                    "plugin_writes_a_file": True,
                                    "channel_shape": "unmeasured"}}}
        probe = {"status": "measured", "why": None, "seen": {"X": "/tmp/x"}}
        self.assertEqual(oc.verdicts(doc, probe)["X"]["verdict"], "member")


class TheShapeOfTheValueSeparatesChannelFromMode(unittest.TestCase):
    def test_a_path_shaped_value_is_a_channel_and_a_word_is_a_mode(self) -> None:
        self.assertEqual(oc.channel_shape(["ctl/collected.jsonl"]), "path")
        self.assertEqual(oc.channel_shape(["stream.jsonl"]), "path")
        self.assertEqual(oc.channel_shape(["ci"]), "mode")
        self.assertEqual(oc.channel_shape(["0"]), "mode")

    def test_a_value_declared_only_by_code_is_unmeasured_not_a_mode(self) -> None:
        self.assertEqual(oc.channel_shape([""]), "unmeasured")
        self.assertEqual(oc.channel_shape([]), "unmeasured")


class TheLiveTreeIsMeasuredAndTheAnswerIsNamed(unittest.TestCase):
    """ЗАМЕР ЖИВОГО ДЕРЕВА — объявлен в имени теста, как требует § про сцены.

    Этот тест отвечает на вопрос заказа: существует ли ЧЕТВЁРТАЯ переменная рода.
    Он НЕ закрепляет число кандидатов константой — закреплять замер литералом значило
    бы краснеть от собственного производителя (урок #1119). Закрепляется СВОЙСТВО:
    все три известных члена обязаны быть НАЙДЕНЫ поверхностью, иначе прибор мерит
    не тот класс.
    """

    KNOWN = ("SPA_PYTEST_STREAM", "SPA_PYTEST_MANIFEST", "SPA_PYTEST_RESUME_ONLY")

    def test_the_surface_finds_every_known_member_of_the_class(self) -> None:
        doc = oc.census(_REPO_ROOT)
        self.assertEqual(doc["status"], "measured", doc.get("why"))
        for name in self.KNOWN:
            self.assertIn(
                name, doc["candidates"],
                f"поверхность не нашла ИЗВЕСТНОГО члена {name}: "
                f"кандидаты {sorted(doc['candidates'])} — замер, не нашедший "
                "известного члена, мерой класса не является")

    def test_both_declaration_places_are_live_in_this_tree(self) -> None:
        doc = oc.census(_REPO_ROOT)
        places = {p for info in doc["candidates"].values()
                  for p in info["declared_places"]}
        self.assertEqual(places, {"workflow", "code"}, places)

    def test_nothing_is_left_unread_without_a_reason(self) -> None:
        doc = oc.census(_REPO_ROOT)
        for row in doc["unreadable"]:
            self.assertTrue(row.get("why"), row)
        for row in doc["unresolved"]:
            self.assertTrue(row.get("why"), row)


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
