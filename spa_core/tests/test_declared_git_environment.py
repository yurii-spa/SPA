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


def _is_pytest_step(step: dict) -> bool:
    run = step.get("run")
    return isinstance(run, str) and "pytest" in run


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
        runs_pytest = any(_is_pytest_step(s) for s in steps if isinstance(s, dict))
        if not runs_pytest:
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
        rows.append({"job": job_name, "checkout": seen_checkout, "depth": depth})
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
                if not row["checkout"]:
                    offenders.append(f"{name}:{row['job']} — шага checkout нет вовсе")
                elif row["depth"] != _FULL_DEPTH:
                    shown = "не объявлена (умолчание 1)" if row["depth"] is None \
                        else row["depth"]
                    offenders.append(f"{name}:{row['job']} — fetch-depth {shown}")
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
        self.assertEqual([{"job": "test", "checkout": True, "depth": None}],
                         audit_workflow(doc))

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
        self.assertEqual([{"job": "test", "checkout": True, "depth": 0}],
                         audit_workflow(doc))

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
