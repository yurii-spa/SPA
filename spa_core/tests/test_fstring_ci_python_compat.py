"""Сторож: f-string, который разбирает ТОЛЬКО Python ≥ 3.12 (PEP 701), на `main` не уезжает.

Класс (ADR-1001, цикл #1120). Локальный интерпретатор на Маке — 3.13, CI (`.github/workflows/ci.yml`)
идёт на 3.11. С 3.12 внутри поля `{…}` f-string разрешены кавычки того же типа, что у внешней
строки, комментарии и обратные косые; 3.11 на том же байте отвечает `SyntaxError: f-string:
unmatched '['` (или `'('`, `'{'`) — и файл не разбирается ВОВСЕ. Прогон `SPA CI` 43374439898 на
вершине `782aa56fa`: `scripts/edge_crash_funding_hedge.py:406`
(`f"{… else f'{ch['notionals_for_half_hedge']:.1f}'}"`) — одна строка, и у неё ×13 падений одного
теста плюс семейство переписей, которые разбирают все скрипты AST (каждая честно ответила
«не разобран» и покраснела). Локально всё зелено: 3.13 этот байт разбирает. То есть вердикт зависит
от ХОСТА, а не от кода — тот же класс, что календарь, номер процесса и git-окружение
(`.claude/rules/deployment.md`), только дверь — версия интерпретатора.

Что здесь проверяется, и каждое — по исходу, не по подстроке:

* сторож находит форму «вложенная кавычка того же типа» (однокавычная внешняя: любая внутренняя
  строка с тем же символом; тройная внешняя: только та же тройная), «комментарий внутри поля»
  и «вложенная f-string с той же кавычкой» — на сценах, положительный контроль;
* не находит: разные кавычки, тройная внешняя + одинарная внутренняя (3.11 разбирает);
* три исхода различимы: чисто · находка · НЕ ИЗМЕРЕНО (файл не прочитан — отказ, не «чисто»);
* на ЖИВОМ дереве находок нет, пока CI объявляет Python < 3.12; версия CI читается из воркфлоу,
  не набрана здесь — не прочитана ⇒ НЕ ИЗМЕРЕНО, красный.

Чего сторож НЕ видит (вслух): обратную косую внутри выражения поля (3.12+) он не ловит —
токенизатор её не выделяет; под 3.11 такой файл не компилируется, и сторож на самом CI это назовёт
первым исходом. Под ≥ 3.12 это слепая зона, названная здесь.
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

_RE_PY_VERSION = re.compile(r"python-version:\s*['\"]?(\d+)\.(\d+)")


def ci_python_version(text: str) -> Optional[Tuple[int, int]]:
    """Версия Python, объявленная воркфлоу CI; None — не объявлена (НЕ ИЗМЕРЕНО)."""
    m = _RE_PY_VERSION.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _quote_of(tok: str) -> str:
    s = tok.lstrip("rRbBfFuUtT")
    return s[:3] if s[:3] in ('"""', "'''") else s[:1]


def _clashes(inner: str, outer: str) -> bool:
    """Внутренняя кавычка завершила бы внешнюю строку у токенизатора 3.11."""
    if len(outer) == 1:
        return inner[0] == outer
    return inner == outer


def pep701_findings(path: Path, src: str) -> List[str]:
    """Строки-находки `путь:строка: причина`. Пусто — файл разбирается и 3.11-совместим по форме."""
    try:
        compile(src, str(path), "exec")
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: не разбирается Python {sys.version_info[0]}.{sys.version_info[1]}: {exc.msg}"]
    if sys.version_info < (3, 12) or not hasattr(tokenize, "FSTRING_START"):
        return []                      # 3.11 сам разобрал ⇒ форм PEP 701 в файле нет по построению
    out: List[str] = []
    stack: List[str] = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.FSTRING_START:
            q = _quote_of(t.string)
            if any(_clashes(q, o) for o in stack):
                out.append(f"{path}:{t.start[0]}: вложенная f-string с кавычкой внешней ({q}) — только 3.12+")
            stack.append(q)
        elif t.type == tokenize.FSTRING_END:
            if stack:
                stack.pop()
        elif stack and t.type == tokenize.STRING:
            q = _quote_of(t.string)
            if any(_clashes(q, o) for o in stack):
                out.append(f"{path}:{t.start[0]}: строка {q} внутри поля f-string с той же кавычкой — только 3.12+")
        elif stack and t.type == tokenize.COMMENT:
            out.append(f"{path}:{t.start[0]}: комментарий внутри поля f-string — только 3.12+")
    return out


def scan(root: Path) -> Tuple[List[str], List[str], int]:
    """(находки, НЕ ИЗМЕРЕНО, сколько файлов разобрано)."""
    findings: List[str] = []
    unmeasured: List[str] = []
    n = 0
    for p in sorted(root.rglob("*.py")):
        if SKIP_PARTS & set(p.relative_to(root).parts):
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unmeasured.append(f"{p.relative_to(root)}: {exc}")
            continue
        try:
            findings.extend(pep701_findings(p.relative_to(root), src))
        except (tokenize.TokenError, IndentationError) as exc:   # compile прошёл, токенизатор нет
            unmeasured.append(f"{p.relative_to(root)}: tokenize: {exc}")
            continue
        n += 1
    return findings, unmeasured, n


# ─────────────────────────── сцены ───────────────────────────

NESTED_SAME_QUOTE = 'd = {"k": 1}\nx = f"{d["k"]}"\n'
NESTED_OTHER_QUOTE = 'd = {"k": 1}\nx = f"{d[\'k\']}"\n'
TRIPLE_OUTER_SINGLE_INNER = 'd = {"k": 1}\nx = f"""{d["k"]}"""\n'
TRIPLE_OUTER_TRIPLE_INNER = 'd = {"k": 1}\nx = f"""{d["""k"""]}"""\n'
NESTED_FSTRING_SAME_QUOTE = (
    "ch = {'n': 1.5}\n"
    "x = f\"{'—' if ch['n'] is None else f'{ch['n']:.1f}'}\"\n"   # форма edge_crash_funding_hedge:406
)
# Три уровня — три РАЗНЫХ кавычки (внешняя тройная): 3.11 разбирает. Вариант с `"n"` внутри
# однокавычной внешней `"…"` чист НЕ был бы — внутренняя `"` закрыла бы внешнюю у токенизатора 3.11.
NESTED_FSTRING_OTHER_QUOTE = (
    "ch = {'n': 1.5}\n"
    "x = f\"\"\"{'—' if ch['n'] is None else f'{ch[\"n\"]:.1f}'}\"\"\"\n"
)
COMMENT_IN_FIELD = 'x = 1\ny = f"{x  # comment\n}"\n'
PLAIN = 'x = 1\ny = f"{x}"\n'


class TestScenes(unittest.TestCase):
    """Положительный контроль: каждая форма класса ловится; совместимые — нет."""

    def _f(self, src: str) -> List[str]:
        return pep701_findings(Path("scene.py"), src)

    def test_nested_same_quote_is_a_finding(self):
        f = self._f(NESTED_SAME_QUOTE)
        self.assertEqual(len(f), 1, f)
        self.assertIn("scene.py:2", f[0])

    def test_nested_other_quote_is_clean(self):
        self.assertEqual(self._f(NESTED_OTHER_QUOTE), [])

    def test_triple_outer_single_inner_is_clean_311_parses_it(self):
        self.assertEqual(self._f(TRIPLE_OUTER_SINGLE_INNER), [])

    def test_triple_outer_triple_inner_is_a_finding(self):
        self.assertEqual(len(self._f(TRIPLE_OUTER_TRIPLE_INNER)), 1)

    def test_the_real_form_nested_fstring_reusing_the_outer_quote_is_a_finding(self):
        f = self._f(NESTED_FSTRING_SAME_QUOTE)
        self.assertTrue(f, "форма edge_crash_funding_hedge:406 не поймана")

    def test_nested_fstring_with_distinct_quotes_is_clean(self):
        self.assertEqual(self._f(NESTED_FSTRING_OTHER_QUOTE), [])

    def test_comment_inside_a_field_is_a_finding(self):
        self.assertTrue(self._f(COMMENT_IN_FIELD))

    def test_plain_fstring_is_clean(self):
        self.assertEqual(self._f(PLAIN), [])

    def test_a_file_this_interpreter_cannot_parse_is_a_finding_not_clean(self):
        """Первый исход: не разбирается ЗДЕСЬ ⇒ находка с номером строки (на CI 3.11 так читается PEP 701)."""
        f = self._f("def f(:\n    pass\n")
        self.assertEqual(len(f), 1, f)
        self.assertIn("не разбирается Python", f[0])
        self.assertIn("scene.py:1", f[0])

    def test_unreadable_file_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ok.py").write_text(PLAIN, encoding="utf-8")
            (root / "bad.py").write_bytes(b"\xff\xfe x = f\"{d[\"k\"]}\"\n")
            findings, unmeasured, n = scan(root)
            self.assertEqual(findings, [])
            self.assertEqual(len(unmeasured), 1, unmeasured)
            self.assertEqual(n, 1)

    def test_scan_names_the_finding_with_its_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pkg").mkdir()
            (root / "pkg" / "m.py").write_text(NESTED_SAME_QUOTE, encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "ignored.py").write_text(NESTED_SAME_QUOTE, encoding="utf-8")
            findings, unmeasured, n = scan(root)
            self.assertEqual(n, 1, "файлы под .git не разбираются")
            self.assertEqual(len(findings), 1)
            self.assertIn("pkg/m.py:2", findings[0].replace("\\", "/"))

    def test_ci_version_parser(self):
        self.assertEqual(ci_python_version("      python-version: '3.11'\n"), (3, 11))
        self.assertEqual(ci_python_version('python-version: "3.12"'), (3, 12))
        self.assertIsNone(ci_python_version("no version here"))


class TestTheLiveTree(unittest.TestCase):
    def test_ci_declares_a_python_version(self):
        self.assertTrue(CI_WORKFLOW.is_file(), f"НЕ ИЗМЕРЕНО: нет {CI_WORKFLOW}")
        ver = ci_python_version(CI_WORKFLOW.read_text(encoding="utf-8"))
        self.assertIsNotNone(ver, "НЕ ИЗМЕРЕНО: воркфлоу CI не объявляет python-version — "
                                  "о совместимости судить нечем")

    def test_no_file_in_the_repo_needs_a_newer_python_than_ci(self):
        ver = ci_python_version(CI_WORKFLOW.read_text(encoding="utf-8")) if CI_WORKFLOW.is_file() else None
        self.assertIsNotNone(ver, "НЕ ИЗМЕРЕНО: версия Python CI не прочитана")
        findings, unmeasured, n = scan(ROOT)
        self.assertGreater(n, 100, f"поверхность подозрительно мала ({n} файлов) — вакуум, не «чисто»")
        self.assertEqual(unmeasured, [], "НЕ ИЗМЕРЕНО у части файлов — «чисто» утверждать нельзя")
        if ver >= (3, 12):
            return                     # CI сам разбирает PEP 701 — класса нет; замер всё равно снят выше
        self.assertEqual(findings, [],
                         f"CI идёт на Python {ver[0]}.{ver[1]}, и эти файлы там НЕ РАЗБЕРУТСЯ "
                         f"(SyntaxError: f-string …) — вынести вложенную строку из поля:\n  "
                         + "\n  ".join(findings))


if __name__ == "__main__":
    unittest.main()
