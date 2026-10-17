# LLM_FORBIDDEN
"""spa_core/tests/test_declared_git_environment.py — git-окружение есть ВХОД набора, а не свойство хоста.

**Класс.** `.claude/rules/deployment.md` уже держит два его члена: **календарь**
(«фиксированная дата — бомба замедленного действия») и **личность процесса**
(«литеральный pid — та же бомба от другого счётчика»). Оба про одно: вердикт
теста решает то, чего тест не объявлял, и код при этом не меняется ни на байт.
Здесь — **третий член семейства: git-окружение**. У него две двери, и обе
измерены прогоном `36222500219` (первый за 30 суток, доведённый до сводки:
`59 failed, 106199 passed` за 3:19:05).

**Дверь 1 — имя ветки по умолчанию.** `git init` без `-b` берёт его из
`init.defaultBranch`. На этом Маке системный конфиг Apple Git
(`/Library/Developer/CommandLineTools/usr/share/git-core/gitconfig`) ставит
`main`; на `ubuntu-latest`, где идёт CI, git даёт `master`. Фикстура, которая
`git init`-ит одноразовый репозиторий и потом называет `origin/main`, зелена
здесь и красна там — и это НЕ про код под проверкой.
Замер: `spa_core/tests/test_push_base_provenance.py` — **8 падений в CI,
воспроизведены 8 из 8** подстановкой `GIT_CONFIG_GLOBAL` c
`init.defaultBranch = master`, пофамильно.

**Дверь 2 — глубина клона.** Умолчание `actions/checkout` — `fetch-depth: 1`,
то есть **истории репозитория в CI нет**. Тест, чей предмет — настоящая авария
доставки (`test_delivery_name_loss.py` читает блобы и коммиты аварии 12.09),
при этом отказывает ГРОМКО («предпосылка теста НЕ ОБЕСПЕЧЕНА») — отказ ВЕРЕН
по инв. #17, но означает, что в CI он месяц не мерил ничего и держал `main`
красным. Замер: **13 падений в CI, воспроизведены 13 из 13** в клоне
`--depth 1` на этой машине, пофамильно.

**Почему разные лекарства.** Дверь 1 — дефект ФИКСТУРЫ: имя ветки принадлежит
сцене, и объявить его обязана она (`git init -b <имя>`). Дверь 2 — дефект
ХАРНЕССА: тест не может выдумать историю репозитория, её обязан положить
`checkout`. Лечить дверь 2 правкой теста значило бы понизить его предмет.

**Храповика по двери 1 здесь НЕТ намеренно**, и это тот же выбор, что у pid'а в
`.claude/rules/deployment.md`: форма («`git init` без `-b`») встречается в
десятках файлов, а вред — там, где сцена ПОТОМ называет ветку по имени. База с
десятками ложных срабатываний учила бы дописывать в неё. Класс держат правило,
объявление у сцены и контроль ниже, который доказывает, что объявленная форма
immune на ЛЮБОМ хосте, а унаследованная — нет.

**Fail-CLOSED.** Не нашли ни одного workflow, не разобрали YAML, не нашли ни
одной джобы с pytest — КРАСНОЕ с названной причиной. «Не измерено» никогда не
выдаётся за «чисто» (инв. #17).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

#: Значение `fetch-depth`, означающее «вся история».
_FULL_DEPTH = 0


def _yaml():
    """PyYAML — ВХОД этой проверки. Его отсутствие есть третий исход, а не скип.

    Скип сделал бы «не измерено» неотличимым от «прошло» — ровно тот дефект,
    который `.claude/rules/deployment.md` разбирает на примере `pyflakes`.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — защита от безмолвия
        raise AssertionError(
            "НЕ ИЗМЕРЕНО: PyYAML отсутствует, разобрать workflow нечем "
            f"({exc}). Это третий исход, а не чистый прогон") from exc
    return yaml


#: Пары `(программа, первый аргумент)`, означающие УСТАНОВКУ пакета.
#: Команда из этого набора упоминает `pytest` как ИМЯ ПАКЕТА, а не запускает его.
_INSTALLERS = frozenset({
    ("pip", "install"), ("pip3", "install"),
    ("uv", "pip"), ("uv", "add"), ("uv", "sync"),
    ("poetry", "add"), ("poetry", "install"),
    ("pipx", "install"),
    ("conda", "install"), ("mamba", "install"),
    ("apt", "install"), ("apt-get", "install"), ("brew", "install"),
})

#: Интерпретатор Python под любым именем: `python`, `python3`, `python3.11`.
_PYTHON = re.compile(r"^python(\d+(\.\d+)?)?$")

#: Разделители команд внутри одной строки скрипта. `||` разбирается ДО `|`.
_SEPARATORS = re.compile(r"&&|\|\||;|\|")

#: Обёртки, которые не меняют запускаемую программу.
_TRANSPARENT = frozenset({"env", "sudo", "exec", "time", "nice", "command"})

#: Как pytest вообще пишут. Устаревшее `py.test` подстроки `pytest` НЕ содержит,
#: и ранний выход по одной подстроке терял его целиком — нашёл контроль
#: `test_invocation_forms_are_recognised`, а не глаз автора.
_SPELLINGS = ("pytest", "py.test")


def mentions_pytest(text: str) -> bool:
    """Упоминает ли текст pytest под любым из написаний."""
    return any(spelling in text for spelling in _SPELLINGS)


def logical_lines(script: str) -> list[str]:
    r"""Строки скрипта шага: переносы `\` склеены, строки-комментарии сняты.

    Оба действия — ИЗМЕРЕНИЯ, а не догадки, и каждое закрывает свой ложный
    вердикт, замеренный на живых workflow 17.10:

    * **перенос.** `python scripts/ci_control.py run-shard \` … `-p
      spa_core.ci.pytest_stream_record` — одна команда, разорванная на пять
      строк. Разбор построчно судил бы хвост `-p …` как отдельную команду.
    * **комментарий.** `# run-shard: при аварии pytest …` — ОБРАЗЕЦ упоминания,
      а не команда. Ровно тот урок, которым `ci-lite.yml` уже платил за
      `'import anthropic' in src` (цикл #686): подстрока не отличает код от
      рассказа о коде.
    """
    out: list[str] = []
    buf = ""
    for raw in script.splitlines():
        line = raw.strip()
        if not buf and (not line or line.startswith("#")):
            continue
        if buf:
            line = f"{buf} {line}"
            buf = ""
        if line.endswith("\\"):
            buf = line[:-1].strip()
            continue
        out.append(line)
    if buf:
        out.append(buf)
    return out


def _module_arg(argv: list[str]) -> str | None:
    """Аргумент ключа `-m`, если он есть."""
    for i, tok in enumerate(argv):
        if tok == "-m" and i + 1 < len(argv):
            return argv[i + 1]
    return None


def classify_command(cmd: str) -> str | None:
    """Что ОДНА команда делает с pytest. `None` — про pytest речи нет.

    Четыре исхода, и они различимы (инв. #17):

    | вердикт | что это | пример |
    |---|---|---|
    | `invokes` | команда ЗАПУСКАЕТ pytest | `python -m pytest tests/` |
    | `installs` | команда СТАВИТ пакет | `pip install pytest==8.3.4` |
    | `unclassified` | pytest упомянут, программа не узнана | `python scripts/ci_control.py … -p spa_core.ci.pytest_stream_record` |
    | `unparsed` | строку не разобрать как команду | незакрытая кавычка |

    **Два последних исхода считаются прогоном** — см. :func:`step_pytest_verdicts`.
    """
    if not mentions_pytest(cmd):
        return None
    try:
        argv = shlex.split(cmd, comments=True)
    except ValueError:
        return "unparsed"
    while argv and (argv[0] in _TRANSPARENT
                    or ("=" in argv[0] and not argv[0].startswith("-")
                        and "/" not in argv[0].split("=", 1)[0])):
        argv = argv[1:]
    if not argv:
        return "unclassified"
    if not any(mentions_pytest(tok) for tok in argv):
        # упоминание жило в комментарии той же строки — его снял shlex
        return None
    prog = argv[0].rsplit("/", 1)[-1]
    rest = argv[1:]
    if prog in ("pytest", "py.test"):
        return "invokes"
    if _PYTHON.match(prog):
        module = _module_arg(rest)
        if module == "pytest":
            return "invokes"
        if module == "pip" and "install" in rest:
            return "installs"
    if rest and (prog, rest[0]) in _INSTALLERS:
        return "installs"
    return "unclassified"


def pytest_mentions(step: dict) -> list[tuple[str, str]]:
    """`(вердикт, команда)` для каждой команды шага, упомянувшей pytest."""
    run = step.get("run")
    if not isinstance(run, str) or not mentions_pytest(run):
        return []
    found: list[tuple[str, str]] = []
    for line in logical_lines(run):
        for cmd in _SEPARATORS.split(line):
            cmd = cmd.strip()
            verdict = classify_command(cmd)
            if verdict is not None:
                found.append((verdict, cmd))
    return found


def step_pytest_verdicts(step: dict) -> set[str]:
    """Вердикты, по которым шаг считается ПРОГОНОМ pytest, а не установкой.

    Пустое множество = шаг тестов не гоняет. Дверь ОДНА: и население, и поле
    `why` берутся отсюда. Первая редакция правки #891 держала рядом второй
    предикат `step_runs_pytest`, а население считала сама — и предикат остался
    БЕЗ ЕДИНОГО читателя в проде, то есть сторожем, которого не зовут. Нашёл
    это не глаз автора, а отрицательный контроль: возврат подстроки в предикат
    покрасил ОДИН тест из трёх, которые обязаны были покраснеть.

    **Почему не подстрока** (замер 17.10, цикл #891, заказ G774 п. 2). Здесь
    стояло `"pytest" in run`, и на чистом `origin/main` сторож был КРАСЕН:
    `ci-lite.yml:syntax-and-import` требовал истории репозитория, не запуская
    ни одного теста — его единственное упоминание pytest это шаг
    `pip install pytest==8.3.4`, поставленный циклом #787, чтобы импортировался
    ПЛАГИН. Ложный красный хуже молчания: он учит снимать сторожа, а снятый
    сторож не отвечает уже ни на что (инв. #16). Население 7 джоб → 6,
    находок 1 → 0; шесть настоящих названы поимённо в контроле ниже.

    **Направление ошибки сохранено.** Правило намеренно ГРУБОЕ и обязано
    ошибаться в сторону НАХОДКИ, поэтому прогоном считается всё, кроме
    УЗНАННОЙ установки: `unclassified` и `unparsed` идут в население. Это не
    вежливость — на этом держится `ci-control.yml:shards`, который зовёт pytest
    ЧУЖИМИ руками (`python scripts/ci_control.py run-shard … --`) и при
    «считаем только узнанный запуск» выпал бы из населения молча, то есть
    сузил бы сторожа ровно тем способом, против которого он написан.
    """
    return {verdict for verdict, _ in pytest_mentions(step) if verdict != "installs"}


def _checkout_depth(step: dict):
    """Глубина, объявленная шагом `actions/checkout`.

    Возвращает `None`, если шаг её не объявляет вовсе — это и есть
    унаследованное умолчание `1`, а не «глубина не важна».
    """
    with_ = step.get("with")
    if not isinstance(with_, dict):
        return None
    if "fetch-depth" not in with_:
        return None
    return int(with_["fetch-depth"])


def audit_workflow(doc: dict) -> list[dict]:
    """Джобы, которые гоняют pytest, с объявленной глубиной каждой.

    Правило ЗАКРЫТО: джоба либо объявляет глубину у своего `checkout`, либо
    строка выходит с `depth=None` — «не объявлено», отдельным значением.

    Поле `why` называет, ПОЧЕМУ джоба попала в население (`invokes` ·
    `unclassified` · `unparsed`, через `+`, если причин несколько). Без него
    красная строка не отличала бы «джоба правда гоняет тесты» от «сторож не
    смог разобрать её команду», то есть измеренное от неизмеренного (инв. #17).
    """
    rows: list[dict] = []
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return rows
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        verdicts: set[str] = set()
        for step in steps:
            if isinstance(step, dict):
                verdicts |= step_pytest_verdicts(step)
        if not verdicts:
            continue
        depth = None
        seen_checkout = False
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str) and uses.startswith("actions/checkout"):
                seen_checkout = True
                depth = _checkout_depth(step)
                break
        rows.append({"job": job_name, "checkout": seen_checkout, "depth": depth,
                     "why": "+".join(sorted(verdicts))})
    return rows


class TheSuiteDeclaresItsCloneDepth(unittest.TestCase):
    """Дверь 2: история репозитория — вход набора, и объявлять её обязан харнесс."""

    def setUp(self):
        yaml = _yaml()
        self.assertTrue(_WORKFLOWS_DIR.is_dir(),
                        f"НЕ ИЗМЕРЕНО: каталога {_WORKFLOWS_DIR} нет")
        self.files = sorted(_WORKFLOWS_DIR.glob("*.yml")) + \
            sorted(_WORKFLOWS_DIR.glob("*.yaml"))
        self.assertTrue(self.files, "НЕ ИЗМЕРЕНО: ни одного workflow не найдено")
        self.docs = {}
        for path in self.files:
            try:
                self.docs[path.name] = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                self.fail(f"НЕ ИЗМЕРЕНО: {path.name} не разобран: "
                          f"{type(exc).__name__}: {exc}")

    def test_the_population_is_not_empty(self):
        """Ноль джоб с pytest неотличим от сломанного разбора — значит КРАСНОЕ."""
        rows = [r for name, doc in self.docs.items() if isinstance(doc, dict)
                for r in audit_workflow(doc)]
        self.assertTrue(rows, "НЕ ИЗМЕРЕНО: ни одна джоба не зовёт pytest — "
                              "либо разбор сломан, либо набор выключен целиком")

    def test_every_pytest_job_declares_full_history(self):
        offenders = []
        for name, doc in self.docs.items():
            if not isinstance(doc, dict):
                continue
            for row in audit_workflow(doc):
                where = f"{name}:{row['job']} [{row['why']}]"
                if not row["checkout"]:
                    offenders.append(f"{where} — шага checkout нет вовсе")
                elif row["depth"] != _FULL_DEPTH:
                    shown = "не объявлена (умолчание 1)" if row["depth"] is None \
                        else row["depth"]
                    offenders.append(f"{where} — fetch-depth {shown}")
        self.assertFalse(offenders, "\n".join([
            "Джоба гоняет pytest, а историю репозитория ей не положили.",
            "Набор содержит тесты, чей ПРЕДМЕТ — настоящая история доставки;",
            "без неё они честно отказывают и месяц не мерят ничего:",
            *offenders]))


class TheRuleItselfIsControlled(unittest.TestCase):
    """Контроль на правило: оно обязано находить настоящий недосмотр и молчать на верном."""

    def test_a_job_without_declared_depth_is_found(self):
        yaml = _yaml()
        doc = yaml.safe_load(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: python -m pytest tests/\n")
        self.assertEqual([{"job": "test", "checkout": True, "depth": None,
                           "why": "invokes"}], audit_workflow(doc))

    def test_a_job_with_full_depth_is_clean(self):
        yaml = _yaml()
        doc = yaml.safe_load(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          fetch-depth: 0\n"
            "      - run: python -m pytest tests/\n")
        self.assertEqual([{"job": "test", "checkout": True, "depth": 0,
                           "why": "invokes"}], audit_workflow(doc))

    def test_a_job_that_does_not_run_pytest_is_not_this_guards_business(self):
        yaml = _yaml()
        doc = yaml.safe_load(
            "jobs:\n"
            "  lint:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: python scripts/lint.py\n")
        self.assertEqual([], audit_workflow(doc),
                         "джоба без pytest истории не требует — находка была бы ложной")

    def test_a_shallow_depth_is_not_mistaken_for_full(self):
        yaml = _yaml()
        doc = yaml.safe_load(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          fetch-depth: 50\n"
            "      - run: pytest\n")
        self.assertEqual(50, audit_workflow(doc)[0]["depth"])


class TheGuardMeasuresInvocationNotMention(unittest.TestCase):
    """Контроль на правку #891: «ставит pytest» и «гоняет pytest» — два разных факта.

    Каждый тест ниже — положительный контроль одной стороны, и у каждой стороны
    есть обратная: батарея, зелёная на классификаторе, который отвечает
    `installs` всегда, была бы бесполезна ровно так же, как зелёная на том,
    который отвечает `invokes` всегда. Обе такие подделки здесь краснеют.
    """

    #: Дословный шаг, который до #891 держал `main` красным (`ci-lite.yml`,
    #: поставлен циклом #787: ПЛАГИН pytest не импортируется без pytest).
    INSTALL_ONLY_STEP = {"name": "Install pytest — a pytest plugin cannot be "
                                 "imported without it",
                         "run": "pip install pytest==8.3.4\n"}

    #: Дословный шаг `ci-control.yml:shards`: pytest зовётся ЧУЖИМИ руками,
    #: команда разорвана переносами, а рядом живёт комментарий про pytest.
    SHARD_STEP = {"name": "Run shard", "run":
                  "set +e\n"
                  "# run-shard: при аварии pytest (INTERNALERROR / гибель процесса)\n"
                  "python scripts/ci_control.py run-shard \\\n"
                  "  --files ctl/shard-1.txt --max-resumes 3 -- \\\n"
                  "  -q --tb=short -p no:randomly \\\n"
                  "  -p spa_core.ci.pytest_stream_record\n"
                  "code=$?\n"}

    def test_the_accident_verbatim_an_installer_step_is_not_a_test_run(self):
        """Авария дословно: джоба, которая pytest только СТАВИТ, истории не требует."""
        self.assertEqual([], pytest_mentions(self.INSTALL_ONLY_STEP) and
                         [m for m in pytest_mentions(self.INSTALL_ONLY_STEP)
                          if m[0] != "installs"],
                         "установка прочитана как прогон — это и есть дефект #891")
        self.assertFalse(step_pytest_verdicts(self.INSTALL_ONLY_STEP))
        doc = _yaml().safe_load(
            "jobs:\n"
            "  syntax-and-import:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: pip install pytest==8.3.4\n")
        self.assertEqual([], audit_workflow(doc),
                         "джоба без запуска тестов попала в население — "
                         "сторож опять требует историю у того, кто её не читает")

    def test_the_same_job_with_a_real_run_is_still_found(self):
        """Обратная сторона: добавь настоящий прогон — и находка обязана вернуться."""
        doc = _yaml().safe_load(
            "jobs:\n"
            "  syntax-and-import:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: pip install pytest==8.3.4\n"
            "      - run: python -m pytest spa_core/tests/ -q\n")
        self.assertEqual([{"job": "syntax-and-import", "checkout": True,
                           "depth": None, "why": "invokes"}], audit_workflow(doc),
                         "правка сузила сторожа до слепоты: джоба ГОНЯЕТ тесты "
                         "без истории, и это настоящая находка")

    def test_installer_forms_are_recognised(self):
        for cmd in (
            "pip install pytest==8.3.4",
            "pip install pytest pytest-asyncio pytest-timeout mypy==2.1.0  # набор",
            "pip install pytest --quiet",
            "pip3 install pytest",
            "python3 -m pip install --quiet pytest",
            "python -m pip install pytest-timeout",
            "uv pip install pytest",
            "poetry add pytest",
            "conda install pytest",
        ):
            self.assertEqual("installs", classify_command(cmd),
                             f"установка не узнана: {cmd!r}")

    def test_invocation_forms_are_recognised(self):
        for cmd in (
            "pytest",
            "pytest -q tests/",
            "py.test tests/",
            "python -m pytest tests/",
            "python3 -m pytest spa_core/tests/ -q --tb=short",
            "python3.11 -m pytest tests/",
            "SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest tests/ -q",
            "./venv/bin/pytest -q",
            "env SPA_ENV=ci pytest -q",
        ):
            self.assertEqual("invokes", classify_command(cmd),
                             f"запуск не узнан: {cmd!r}")

    def test_an_install_and_a_run_on_one_line_is_a_run(self):
        """Строка — не команда: `&&` разделяет два разных факта."""
        step = {"run": "pip install pytest && pytest -q tests/\n"}
        self.assertEqual([("installs", "pip install pytest"),
                          ("invokes", "pytest -q tests/")], pytest_mentions(step))
        self.assertTrue(step_pytest_verdicts(step))

    def test_a_pipe_does_not_hide_the_invocation(self):
        step = {"run": "python -m pytest spa_core/tests/ -q 2>&1 | tee out.txt\n"}
        self.assertTrue(step_pytest_verdicts(step),
                        "запуск, чей вывод уходит в `tee`, остался запуском")

    def test_an_unknown_program_counts_as_a_run_and_names_why(self):
        """Правило грубое: не узнал программу — ошибается в сторону НАХОДКИ."""
        self.assertEqual("unclassified",
                         classify_command("bash run_tests.sh --pytest"))
        self.assertTrue(step_pytest_verdicts({"run": "bash run_tests.sh --pytest\n"}))
        doc = _yaml().safe_load(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: bash run_tests.sh --pytest\n")
        self.assertEqual("unclassified", audit_workflow(doc)[0]["why"],
                         "красная строка обязана сказать, что программа НЕ УЗНАНА, "
                         "иначе измеренное неотличимо от неизмеренного (инв. #17)")

    def test_an_unparsable_command_is_a_named_third_outcome(self):
        self.assertEqual("unparsed", classify_command('pytest -k "незакрытая'),
                         "неразобранная команда обязана иметь СВОЙ вердикт, "
                         "а не тихо выпасть из населения")
        self.assertTrue(step_pytest_verdicts({"run": 'pytest -k "незакрытая\n'}))

    def test_a_comment_is_not_a_command(self):
        """Образец упоминания — не запуск. Тот же урок, что `'import anthropic' in src`."""
        self.assertEqual([], pytest_mentions(
            {"run": "# раньше здесь стоял python -m pytest tests/\nls -la\n"}))

    def test_a_continuation_is_one_command_not_several(self):
        """Команда, разорванная переносами, судится целиком — и один раз."""
        mentions = pytest_mentions(self.SHARD_STEP)
        self.assertEqual(1, len(mentions),
                         f"команда разобрана по кускам: {mentions}")
        self.assertEqual("unclassified", mentions[0][0],
                         "pytest, позванный чужими руками, обязан остаться в населении")
        self.assertTrue(step_pytest_verdicts(self.SHARD_STEP))


class TheRealWorkflowsAreTheMeasurement(unittest.TestCase):
    """Замер на ЖИВЫХ workflow: правка сняла ровно одну ложную находку.

    Без этого класса правка была бы утверждением о дереве, а не замером его.
    Числа 17.10: население 7 → 6, находок 1 → 0.
    """

    #: Джобы, которые pytest РЕАЛЬНО гоняют (замер 17.10, пофамильно). Выпади
    #: любая из них из населения — сторож сужен молча, и это хуже ложного
    #: красного, который правка снимала.
    RUNS_PYTEST = (
        ("ci-control.yml", "manifest"),
        ("ci-control.yml", "shards"),
        ("ci.yml", "test"),
        ("proof-gate.yml", "proof-gate"),
        ("spa-run.yml", "run-and-export"),
        ("test.yml", "test"),
    )

    #: Джоба, чьё единственное упоминание pytest — установка плагина.
    INSTALLS_ONLY = ("ci-lite.yml", "syntax-and-import")

    def _jobs(self, filename: str) -> list[dict]:
        path = _WORKFLOWS_DIR / filename
        self.assertTrue(path.is_file(), f"НЕ ИЗМЕРЕНО: {path} не найден")
        doc = _yaml().safe_load(path.read_text(encoding="utf-8"))
        self.assertIsInstance(doc, dict, f"НЕ ИЗМЕРЕНО: {filename} не разобран")
        return audit_workflow(doc)

    def test_every_job_that_really_runs_pytest_is_still_in_the_population(self):
        for filename, job in self.RUNS_PYTEST:
            names = [row["job"] for row in self._jobs(filename)]
            self.assertIn(job, names,
                          f"{filename}:{job} гоняет pytest, но выпал из населения — "
                          f"правка #891 сузила сторожа молча")

    def test_the_job_that_only_installs_pytest_is_not_the_guards_business(self):
        filename, job = self.INSTALLS_ONLY
        names = [row["job"] for row in self._jobs(filename)]
        self.assertNotIn(job, names,
                         f"{filename}:{job} не гоняет ни одного теста, а сторож "
                         f"снова требует у него историю репозитория — ложный "
                         f"красный на чистом main (дефект #891)")

    def test_that_same_job_mentions_pytest_only_as_a_package(self):
        """Предпосылка теста выше — ИЗМЕРЕНА, а не предположена."""
        filename, job = self.INSTALLS_ONLY
        path = _WORKFLOWS_DIR / filename
        self.assertTrue(path.is_file(), f"НЕ ИЗМЕРЕНО: {path} не найден")
        doc = _yaml().safe_load(path.read_text(encoding="utf-8"))
        steps = doc["jobs"][job]["steps"]
        verdicts = {v for s in steps if isinstance(s, dict)
                    for v, _ in pytest_mentions(s)}
        self.assertEqual({"installs"}, verdicts,
                         f"{filename}:{job} теперь делает с pytest что-то ещё "
                         f"({verdicts}) — перемерить, а не править ожидание")


def _git(args, cwd, env):
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _env_with_default_branch(name: str, home: Path) -> dict:
    """Окружение, в котором `init.defaultBranch` равен `name` — ЯВНО.

    Так воспроизводится разница хостов: `main` у Apple Git на Маке против
    `master` у git на `ubuntu-latest`. Глобальный конфиг перекрывает системный,
    поэтому подстановка действует на ЛЮБОЙ машине, а не только там, где нам
    повезло с умолчанием.
    """
    cfg = home / "gitconfig"
    cfg.write_text(f"[init]\n\tdefaultBranch = {name}\n", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(cfg)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(home)
    return env


class TheAccidentOfTheInheritedBranchName(unittest.TestCase):
    """Дверь 1, положительный контроль: воспроизводим аварию и показываем иммунитет.

    Этот класс не сторожит чужой файл — он доказывает, что класс НАСТОЯЩИЙ:
    унаследованное имя ветки меняет вердикт при неизменном коде, а объявленное
    не меняет его ни на одном хосте.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _scene(self, host_default: str, init_args: list[str]) -> int:
        """Код возврата `git rev-parse main` в репозитории, созданном сценой."""
        home = self.root / f"home-{host_default}-{'-'.join(init_args) or 'bare'}"
        home.mkdir(parents=True)
        env = _env_with_default_branch(host_default, home)
        repo = self.root / f"repo-{host_default}-{'-'.join(init_args) or 'bare'}"
        repo.mkdir()
        self.assertEqual(0, _git(["init", "-q", *init_args], repo, env).returncode,
                         "предпосылка НЕ ОБЕСПЕЧЕНА: git init не отработал")
        for key, value in (("user.email", "t@t.t"), ("user.name", "t")):
            _git(["config", key, value], repo, env)
        (repo / "f.txt").write_text("x", encoding="utf-8")
        _git(["add", "-A"], repo, env)
        self.assertEqual(0, _git(["commit", "-qm", "c1"], repo, env).returncode,
                         "предпосылка НЕ ОБЕСПЕЧЕНА: коммит не сделан")
        return _git(["rev-parse", "--verify", "-q", "main"], repo, env).returncode

    def test_an_inherited_name_makes_the_same_scene_red_on_the_other_host(self):
        self.assertEqual(0, self._scene("main", []),
                         "на хосте с умолчанием main унаследованная сцена зелена")
        self.assertNotEqual(0, self._scene("master", []),
                            "…а на хосте с умолчанием master она обязана краснеть: "
                            "именно это и происходило в CI 30 суток")

    def test_a_declared_name_is_immune_on_both_hosts(self):
        self.assertEqual(0, self._scene("main", ["-b", "main"]))
        self.assertEqual(0, self._scene("master", ["-b", "main"]),
                         "объявленное имя ветки не зависит от хоста — в этом вся правка")

    def test_the_fixture_that_actually_broke_now_declares_its_branch(self):
        """Регрессия, поимённо: тот самый файл, чьи 8 падений измерены в CI."""
        victim = Path(__file__).resolve().parent / "test_push_base_provenance.py"
        self.assertTrue(victim.is_file(), f"НЕ ИЗМЕРЕНО: {victim} не найден")
        text = victim.read_text(encoding="utf-8")
        self.assertIn('"init", "-q", "-b", FIXTURE_BRANCH', text,
                      "фикстура снова наследует имя ветки у хоста — "
                      "вердикт её восьми тестов опять решает не код")


if __name__ == "__main__":
    unittest.main()
