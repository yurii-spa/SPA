"""Сторож инварианта #3 обязан отличать ТЕКСТ от ЗОВА и спрашивать ОДНУ дверь.

Положительный контроль воспроизводит настоящую аварию цикла #1237, найденную
дельтой красного набора контрольного прогона `45450462551` (заказ G1076 п. 1):

* `spa_core/monitoring/rules_watchdog.check_llm_forbidden_violations` держал
  СВОЮ копию правила и сравнивал ПОДСТРОКИ в строках файла, хотя докстринг
  утверждал «token-level detection … not string literals»;
* строковый литерал сцены соседней пробы (`card_acceptance.py:21637`,
  `HINT = "import anthropic"`, положенный туда НАМЕРЕННО, чтобы проверить «зов
  против текста» у правила аналитики) стал «нарушением», и `overall` сторожа
  встал на `CRITICAL` навсегда. С этой минуты НАСТОЯЩИЙ ввоз SDK в `monitoring`
  был от строки сцены неотличим: тревога горит всегда и не отвечает ни на что;
* красными стали `spa_core/tests/test_rules_watchdog_honesty.py::
  TestEndToEndOnSandboxState::test_healthy_state_reports_ok` и
  `tests/test_policy_enforcer.py::TestWatchdogChecks::
  test_check_llm_forbidden_violations`.

Та же копия была слепа и в ДРУГУЮ сторону: она знала ДВА запрещённых модуля из
пяти канонических (`litellm`, `langchain`, `google.generativeai` ей невидимы) и
про дверь-запуск (бинарь LLM подпроцессом) не знала вовсе.

Здесь проверяются ДВЕ вещи и обе в обе стороны: (1) сам сторож на сценах;
(2) проба приёмки `llm_watchdog_asks_one_ast_door` — она обязана краснеть на
КАЖДОМ порванном звене и называть, какое именно порвано.
"""

from __future__ import annotations

import pathlib
import types as _types

import pytest

from spa_core.monitoring import rules_watchdog as w
from spa_core.monitoring.card_acceptance import (
    NOT_SATISFIED,
    PROBES,
    SATISFIED,
    UNMEASURED,
)

_PROBE = "llm_watchdog_asks_one_ast_door"
_DOMAINS = ("spa_core/risk", "spa_core/execution", "spa_core/monitoring")

# Слова запрета собираются СЛОЖЕНИЕМ, чтобы этот файл не стал сам сценой для
# линтера, если каталог тестов когда-нибудь войдёт в охраняемые домены.
_SDK = "anthropic"
_SDK2 = "litellm"


def _tree(base: pathlib.Path, files: "dict[str, str]") -> pathlib.Path:
    for d in _DOMAINS:
        (base / d).mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        (base / rel).write_text(body, encoding="utf-8")
    return base


# ── сам сторож ─────────────────────────────────────────────────────────────


class TestTheWatchdogTellsTextFromACall:

    def test_a_string_literal_is_not_a_violation(self, tmp_path):
        """Авария #1237 дословно: литерал со словами запрета ⇒ OK."""
        tree = _tree(tmp_path, {
            "spa_core/monitoring/hint.py":
                'HINT = "' + "import " + _SDK + ' # ТЕКСТ, а не зов"\n',
        })
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert res.status == "OK", res.detail.get("violations")

    def test_a_real_import_is_a_violation(self, tmp_path):
        tree = _tree(tmp_path, {
            "spa_core/monitoring/real.py": "import " + _SDK + "\n",
        })
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert res.status == "CRITICAL"
        assert any("real.py" in v for v in res.detail["violations"])

    def test_the_module_list_comes_from_the_canonical_door(self, tmp_path):
        """`litellm` канон знает, прежняя копия сторожа — нет."""
        tree = _tree(tmp_path, {
            "spa_core/risk/wide.py": "import " + _SDK2 + "\n",
        })
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert res.status == "CRITICAL", (
            "перечень запрещённых модулей взят не у канонической двери")

    def test_the_subprocess_launch_door_is_asked_too(self, tmp_path):
        tree = _tree(tmp_path, {
            "spa_core/monitoring/launcher.py":
                "import subprocess\n"
                "def go():\n"
                '    return subprocess.run(["claude", "-p", "hi"])\n',
        })
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert res.status == "CRITICAL"
        assert any("launches" in v for v in res.detail["violations"])

    def test_an_unparsable_file_is_the_third_outcome(self, tmp_path):
        """инв. #17: «не разобрали» ≠ «чисто» и ≠ «нарушение»."""
        tree = _tree(tmp_path, {"spa_core/monitoring/broken.py": "def f(:\n"})
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert res.status == "SKIPPED"
        assert any("broken.py" in u for u in res.detail["unscanned"])
        assert res.detail["violations"] == []

    def test_a_missing_domain_is_not_a_clean_bill(self, tmp_path):
        tree = _tree(tmp_path, {"spa_core/risk/ok.py": "VALUE = 1\n"})
        import shutil
        shutil.rmtree(tree / "spa_core" / "execution")
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert res.status == "SKIPPED"
        assert "spa_core/execution" in res.message

    def test_an_absent_door_is_loud_not_clean(self, tmp_path):
        """Своей копии правила нет ⇒ «спросить было нечем» обязано быть слышно."""
        tree = _tree(tmp_path, {"spa_core/risk/ok.py": "VALUE = 1\n"})
        res = w.check_llm_forbidden_violations(repo_root=tree, door=object())
        assert res.status == "SKIPPED"
        assert res.detail["decision_by"] is None

    def test_a_half_door_is_refused(self, tmp_path):
        """«Половина починки, оставившая второй сайт» — знакомый класс."""
        class _HalfDoor:
            @staticmethod
            def find_forbidden_imports(source, filename="<string>"):
                return []

        tree = _tree(tmp_path, {"spa_core/risk/ok.py": "VALUE = 1\n"})
        res = w.check_llm_forbidden_violations(repo_root=tree, door=_HalfDoor)
        assert res.status == "SKIPPED"
        assert "find_llm_subprocess_launches" in res.message

    def test_the_verdict_names_the_door_that_actually_decided(self, tmp_path):
        """`decision_by` обязан СЛЕДОВАТЬ двери, а не быть вписанным литералом.

        Литерал «канон» был бы ложью ровно тогда, когда решала не она, — то
        есть именно в случае, ради которого поле и печатается.
        """
        # Объект, а НЕ класс: у класса `__name__` отдаёт метакласс, и
        # присваивание в теле класса до него не доходит (первая редакция этого
        # теста так и покраснела — дефект МОЕЙ сцены, не кода).
        other = _types.SimpleNamespace(
            __name__="an_entirely_other_door",
            FORBIDDEN_IMPORTS=frozenset({"a", "b", "c", "d", "e"}),
            FORBIDDEN_DIRS=("spa_core/risk",),
            find_forbidden_imports=lambda source, filename="<string>": [],
            find_llm_subprocess_launches=lambda source, filename="<string>": [],
        )
        tree = _tree(tmp_path, {"spa_core/risk/ok.py": "VALUE = 1\n"})
        res = w.check_llm_forbidden_violations(repo_root=tree, door=other)
        assert res.status == "OK"
        assert res.detail["decision_by"] == "an_entirely_other_door"

    def test_the_verdict_names_who_decided(self, tmp_path):
        tree = _tree(tmp_path, {"spa_core/risk/ok.py": "VALUE = 1\n"})
        res = w.check_llm_forbidden_violations(repo_root=tree)
        assert "llm_forbidden_lint" in res.detail["decision_by"]
        assert len(res.detail["doors_asked"]) == 2
        assert len(res.detail["modules_forbidden"]) >= 5

    def test_both_domain_lists_are_printed_not_silently_equal(self, tmp_path):
        """Область ЭТОГО сторожа уже канонической, и расхождение ПЕЧАТАЕТСЯ.

        Выравнивать её наугад запрещено (заказ G1076 п. 3): «какие каталоги
        охраняет инвариант #3» — отдельный вопрос с отдельной мерой. Молчаливое
        расширение вынесло бы вердикт о домене, про который этот сторож никогда
        не говорил.
        """
        tree = _tree(tmp_path, {"spa_core/risk/ok.py": "VALUE = 1\n"})
        res = w.check_llm_forbidden_violations(repo_root=tree)
        here = res.detail["domains_declared_here"]
        canonical = res.detail["domains_of_the_canonical_door"]
        assert set(here) <= set(canonical)
        assert set(canonical) - set(here), (
            "расхождение областей исчезло — тогда и печатать два перечня "
            "незачем, а пока оно есть, читатель обязан его видеть")

    def test_the_real_tree_is_measured_and_clean(self):
        """Конец-в-конец на настоящем дереве: авария больше не воспроизводится."""
        res = w.check_llm_forbidden_violations()
        assert res.status == "OK", res.message
        assert res.detail["files_scanned"] > 0
        assert res.detail["unscanned"] == []

    def test_the_watchdog_itself_is_inside_the_population(self):
        """Самоисключение снято: ввоз SDK в самом стороже прежде был невидим."""
        tree_self = pathlib.Path(w.__file__).resolve()
        res = w.check_llm_forbidden_violations()
        assert res.status == "OK"
        # Файл сторожа лежит в охраняемом домене и обязан быть посчитан.
        assert tree_self.parent.name == "monitoring"
        counted = sum(
            1 for p in tree_self.parent.rglob("*.py")
            if "__pycache__" not in p.parts)
        assert res.detail["files_scanned"] >= counted


# ── проба приёмки: красна на КАЖДОМ порванном звене ────────────────────────


def _substring_copy(repo_root=None, *, door=None):
    """Дословная прежняя редакция: подстрока в строке файла.

    Это и есть исторический дефект — он обязан провалить сцену ТЕКСТ.
    """
    root = pathlib.Path(repo_root) if repo_root is not None else w._REPO
    pairs = [("import", _SDK), ("from", _SDK), ("import", "openai"),
             ("from", "openai")]
    found, unscanned, scanned = [], [], 0
    for d in _DOMAINS:
        base = root / d
        if not base.is_dir():
            unscanned.append("{} does not exist".format(d))
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            scanned += 1
            for lineno, line in enumerate(
                    p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                for kw, lib in pairs:
                    if s.startswith(kw + " " + lib) or (kw + " " + lib + " " in s):
                        found.append("{}:{}: {} {}".format(p.name, lineno, kw, lib))
    detail = {"files_scanned": scanned, "violations": found,
              "unscanned": unscanned, "decision_by": "substring copy",
              "doors_asked": ["substring"], "modules_forbidden": [_SDK, "openai"],
              "domains_declared_here": list(_DOMAINS),
              "domains_of_the_canonical_door": list(_DOMAINS)}
    if found:
        return w.CheckResult("llm_forbidden_violations", "CRITICAL", "x", detail)
    if unscanned:
        return w.CheckResult("llm_forbidden_violations", "SKIPPED", "x", detail)
    return w.CheckResult("llm_forbidden_violations", "OK", "x", detail)


def _ast_but_narrow(repo_root=None, *, door=None):
    """AST, но перечень модулей — СВОЙ и короткий: `litellm` невидим."""
    from spa_core.ci import llm_forbidden_lint as real
    import ast as _ast
    root = pathlib.Path(repo_root) if repo_root is not None else w._REPO
    found, unscanned, scanned = [], [], 0
    for d in _DOMAINS:
        base = root / d
        if not base.is_dir():
            unscanned.append("{} does not exist".format(d))
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            try:
                tree = _ast.parse(src)
            except SyntaxError as exc:
                unscanned.append("{} does not parse ({})".format(p.name, exc.msg))
                continue
            scanned += 1
            for node in _ast.walk(tree):
                mods = []
                if isinstance(node, _ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, _ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    if m.split(".")[0] in {_SDK, "openai"}:
                        found.append("{}:{}: imports {}".format(p.name, node.lineno, m))
            for lv in real.find_llm_subprocess_launches(src, p.name):
                found.append("{}:{}: launches {} via {}".format(
                    p.name, lv.line, lv.binary, lv.via))
    detail = {"files_scanned": scanned, "violations": found,
              "unscanned": unscanned, "decision_by": "llm_forbidden_lint (partly)",
              "doors_asked": ["own_ast", "find_llm_subprocess_launches"],
              "modules_forbidden": [_SDK, "openai"],
              "domains_declared_here": list(_DOMAINS),
              "domains_of_the_canonical_door": list(_DOMAINS)}
    if found:
        return w.CheckResult("llm_forbidden_violations", "CRITICAL", "x", detail)
    if unscanned:
        return w.CheckResult("llm_forbidden_violations", "SKIPPED", "x", detail)
    return w.CheckResult("llm_forbidden_violations", "OK", "x", detail)


def _imports_only(repo_root=None, *, door=None):
    """Канон, но спрошена ОДНА дверь: запуск бинаря невидим."""
    from spa_core.ci import llm_forbidden_lint as real
    root = pathlib.Path(repo_root) if repo_root is not None else w._REPO
    found, unscanned, scanned = [], [], 0
    for d in _DOMAINS:
        base = root / d
        if not base.is_dir():
            unscanned.append("{} does not exist".format(d))
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            try:
                hits = real.find_forbidden_imports(src, p.name)
            except SyntaxError as exc:
                unscanned.append("{} does not parse ({})".format(p.name, exc.msg))
                continue
            scanned += 1
            found += ["{}:{}: imports {}".format(p.name, h.line, h.module) for h in hits]
    detail = {"files_scanned": scanned, "violations": found,
              "unscanned": unscanned, "decision_by": "llm_forbidden_lint",
              "doors_asked": ["find_forbidden_imports"],
              "modules_forbidden": sorted(real.FORBIDDEN_IMPORTS),
              "domains_declared_here": list(_DOMAINS),
              "domains_of_the_canonical_door": list(real.FORBIDDEN_DIRS)}
    if found:
        return w.CheckResult("llm_forbidden_violations", "CRITICAL", "x", detail)
    if unscanned:
        return w.CheckResult("llm_forbidden_violations", "SKIPPED", "x", detail)
    return w.CheckResult("llm_forbidden_violations", "OK", "x", detail)


def _always_ok(repo_root=None, *, door=None):
    return w.CheckResult(
        "llm_forbidden_violations", "OK", "x",
        {"files_scanned": 1, "violations": [], "unscanned": [],
         "decision_by": "llm_forbidden_lint", "doors_asked": ["a", "b"],
         "modules_forbidden": ["1", "2", "3", "4", "5"],
         "domains_declared_here": list(_DOMAINS),
         "domains_of_the_canonical_door": list(_DOMAINS)})


def _unparsed_as_clean(repo_root=None, *, door=None):
    """Канон, но неразбираемый файл свёрнут в «чисто» — исходный инв. #17."""
    res = _imports_only(repo_root, door=door)
    if res.status == "SKIPPED" and not res.detail["violations"]:
        res.detail["unscanned"] = []
        return w.CheckResult("llm_forbidden_violations", "OK", "x", res.detail)
    return res


# Настоящая функция СВЯЗЫВАЕТСЯ на импорте: подмена через `monkeypatch` ниже
# иначе уехала бы в саму себя (дефект СЦЕНЫ, найденный первым прогоном —
# RecursionError, а не находка о коде).
_REAL_CHECK = w.check_llm_forbidden_violations


def _unparsed_is_a_violation(repo_root=None, *, door=None):
    """Неразбираемый файл объявлен НАРУШЕНИЕМ, но в `unscanned` НАЗВАН.

    Сцена РАЗЛИЧАЕТ два подзвена «третьего исхода»: «статус не SKIPPED» и
    «SKIPPED без имени файла». Без неё снятие первого подзвена ловилось бы
    вторым (мутация M11 первого прогона так и ВЫЖИЛА — и это была настоящая
    дыра покрытия, а не эквивалентный мутант: мера перестала бы отличать
    `CRITICAL` от `SKIPPED` на том же файле).
    """
    res = _imports_only(repo_root, door=door)
    if res.status == "SKIPPED" and not res.detail["violations"]:
        return w.CheckResult("llm_forbidden_violations", "CRITICAL", "x", res.detail)
    return res


def _door_absence_is_clean(repo_root=None, *, door=None):
    """Канон, но «двери нет» свёрнуто в «чисто» — fail-OPEN вместо отказа."""
    if door is not None and not callable(
            getattr(door, "find_llm_subprocess_launches", None)):
        return _always_ok(repo_root)
    return _REAL_CHECK(repo_root=repo_root, door=door)


def _only_a_half_door_is_clean(repo_root=None, *, door=None):
    """Дверь с ОДНОЙ половиной принята за целую, дверь БЕЗ половин — отказ.

    Эта сцена РАЗЛИЧАЕТ два звена пробы: «дверь неполна» и «двери нет». Без
    неё снятие первого звена ловилось бы вторым, и мутация выжила бы — не
    потому, что код дыряв, а потому, что сцена не различала (урок #1202).
    """
    halves = [n for n in ("find_forbidden_imports", "find_llm_subprocess_launches")
              if callable(getattr(door, n, None))]
    if door is not None and len(halves) == 1:
        return _always_ok(repo_root)
    return _REAL_CHECK(repo_root=repo_root, door=door)


class TestTheProbeIsRedOnEveryBrokenLink:
    """Каждое звено рвётся ПОИМЁННО, и проба обязана назвать именно его."""

    @pytest.mark.parametrize("replacement,expect_word", [
        (_substring_copy, "ТЕКСТ"),
        (_always_ok, "ЗОВ"),
        (_ast_but_narrow, "ШИРИНА ПЕРЕЧНЯ"),
        (_imports_only, "ВТОРАЯ ДВЕРЬ"),
        (_unparsed_as_clean, "ТРЕТИЙ ИСХОД"),
        (_unparsed_is_a_violation, "ТРЕТИЙ ИСХОД"),
        (_only_a_half_door_is_clean, "ДВЕРЬ НЕПОЛНА"),
        (_door_absence_is_clean, "ДВЕРИ НЕТ"),
    ])
    def test_a_broken_link_is_named(self, monkeypatch, replacement, expect_word):
        # monkeypatch, а не присваивание: подмена, пережившая сцену, вредит
        # СОСЕДУ по процессу (.claude/rules/deployment.md § СОСЕД ПО ПРОЦЕССУ).
        monkeypatch.setattr(w, "check_llm_forbidden_violations", replacement)
        verdict, message = PROBES[_PROBE](None)
        assert verdict == NOT_SATISFIED, (replacement.__name__, verdict, message)
        assert expect_word in message, (replacement.__name__, message)

    def test_the_whole_contour_is_satisfied(self):
        verdict, message = PROBES[_PROBE](None)
        assert verdict == SATISFIED, message

    def test_an_absent_watchdog_is_unmeasured_not_a_failure(self, tmp_path):
        """Третий исход у самой пробы: дерева без сторожа она не судит."""
        (tmp_path / "spa_core" / "ci").mkdir(parents=True)
        verdict, message = PROBES[_PROBE](None, repo_root=str(tmp_path))
        assert verdict == UNMEASURED, (verdict, message)
        assert "rules_watchdog.py" in message

    def test_a_watchdog_without_the_check_is_unmeasured(self, monkeypatch):
        monkeypatch.delattr(w, "check_llm_forbidden_violations")
        verdict, message = PROBES[_PROBE](None)
        assert verdict == UNMEASURED, (verdict, message)

    def test_the_probe_does_not_pass_by_substring(self):
        """ADR-333: сцена ТЕКСТ оставляет в дереве ВСЕ искомые слова.

        Поэтому подстрочная мера пробу не проходит — это и доказывает
        `_substring_copy` выше, а здесь закреплено, что искомые слова в сцене
        ДЕЙСТВИТЕЛЬНО есть: иначе контроль был бы пустым.
        """
        src = pathlib.Path(
            PROBES[_PROBE].__code__.co_filename).read_text(encoding="utf-8")
        start = src.index("_TEXT_SCENE = {")
        scene = src[start:src.index("_CALL_SCENE", start)]
        assert "import " + _SDK in scene
        assert "from openai" in scene
