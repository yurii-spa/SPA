#!/usr/bin/env python3
"""scripts/lint_forbidden_imports.py — запрещённый ИМПОРТ, а не запрещённая СТРОКА.

Вопрос, на который отвечает прибор
----------------------------------
«Импортирует ли модуль рантайм-домена библиотеку, запрещённую инвариантом?»
Два инварианта, два КЛАССА находок, и они не смешиваются:

* ``llm_sdk``            — инв. #3: LLM запрещён в risk / execution / monitoring;
* ``third_party_runtime`` — инв. #4: в рантайме только stdlib.

Почему прибор появился (замер 23.09.2026, цикл #686)
---------------------------------------------------
Шаг `Forbidden import check` в ``.github/workflows/ci-lite.yml`` нёс СВОЮ копию
правила и спрашивал подстрокой: ``'import anthropic' in src``. Подстрока не
умеет отличить код от ОБРАЗЦА кода, и 07.09 в дерево приехал сторож
``spa_core/monitoring/cio_architecture_constraints.py``, у которого образец
нарушения лежит строковым литералом прямо в теле (``"sdk_import": "import
anthropic\\n..."``). С этого дня `SPA CI-Lite` на `main` КРАСЕН — на сторожа
инварианта #3, который сам никакого SDK не ввозит.

Замер того же дня по тем же пяти каталогам:

    подстрока — 2 находки: cio_architecture_constraints.py (ОБРАЗЕЦ в строке)
                           и spa_core/adapters/sky_susds_feed.py: requests
    AST       — 1 находка: spa_core/adapters/sky_susds_feed.py: requests

То есть крашеная половина замера была ложной, а НАСТОЯЩИЙ ``import requests``
в адаптере не видел никто: инлайн-проверка ходит по трём каталогам и адаптеров
среди них нет, а ``scripts/lint_llm_forbidden.py`` (пять каталогов) о
третьесторонних библиотеках не спрашивает вовсе. Две копии одного вопроса,
и обе отвечали не на него.

Почему AST — это УЖЕСТОЧЕНИЕ, а не ослабление (инв. #16)
--------------------------------------------------------
Против подстроки прибор ловит СТРОГО БОЛЬШЕ:

* каталогов 5 вместо 3 (добавлены ``allocator`` и ``adapters``);
* библиотек 11 вместо 7 (добавлены ``google.generativeai``, ``llama``,
  ``llama_index``, ``httpx``);
* форм больше: ``import x``, ``import x.y``, ``from x import ...``,
  ``import x as y`` И динамическая дверь — ``importlib.import_module("x")``,
  ``__import__("x")`` с литеральным именем. Подстрока динамическую дверь не
  видела ни в одной форме.

Теряется ровно одно: совпадение ВНУТРИ строкового литерала или комментария.
Это не импорт по определению языка — ни один такой «импорт» не исполняется.

НЕ ДОКЛАДЫВАЕТ (названо, а не умолчано)
---------------------------------------
* ``exec``/``eval`` кода, собранного из строк: имя там не литерал вызова
  импорта, и разобрать его статически нечем;
* импорт из библиотеки, переименованной в ``sys.modules`` третьим лицом;
* сам факт ИСПОЛЬЗОВАНИЯ библиотеки без импорта (через уже импортировавший
  её модуль) — это вопрос о проводке, а не об импорте.

Третий исход
------------
«Не измерено» отделено от «чисто» и от «нарушение»: файл, который не
разобрался (``SyntaxError``), и отсутствующий каталог домена дают код возврата
**2** с названной причиной. Ноль находок при нуле осмотренных файлов —
тоже код 2, а не успех (инв. #17).

База известных нарушений
------------------------
``scripts/forbidden_import_baseline.json`` перечисляет нарушения, уже жившие в
дереве на день появления прибора, — каждое с причиной и карточкой. База может
только УБЫВАТЬ; дописывать в неё, чтобы погасить падение, запрещено (тот же
порядок, что у ``frozen_date_baseline.json``). Устаревшую запись (нарушение
исчезло) прибор НАЗЫВАЕТ, а сторож ``scripts/tests/test_lint_forbidden_imports.py``
краснит — иначе база перестала бы убывать молча.

Коды возврата: 0 — чисто (вне базы нарушений нет) · 1 — есть нарушение вне
базы · 2 — НЕ ИЗМЕРЕНО (нечитаемый файл / нет каталога / осмотрено ноль).

Только stdlib. LLM_FORBIDDEN — это разбор синтаксиса, не суждение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from typing import Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLASS_LLM = "llm_sdk"
CLASS_RUNTIME = "third_party_runtime"

#: Библиотека → класс инварианта. Корень сравнивается по ТОЧКЕ, поэтому
#: ``anthropic`` ловит и ``anthropic.types``, но никогда не ``anthropicish``.
FORBIDDEN: dict[str, str] = {
    "anthropic": CLASS_LLM,
    "openai": CLASS_LLM,
    "google.generativeai": CLASS_LLM,
    "langchain": CLASS_LLM,
    "llama": CLASS_LLM,
    "llama_index": CLASS_LLM,
    "numpy": CLASS_RUNTIME,
    "pandas": CLASS_RUNTIME,
    "requests": CLASS_RUNTIME,
    "aiohttp": CLASS_RUNTIME,
    "httpx": CLASS_RUNTIME,
}

#: Каталоги рантайм-доменов. Объединение двух прежних списков: трёх из
#: ci-lite.yml и пяти из scripts/lint_llm_forbidden.py.
DOMAINS: tuple[str, ...] = (
    "spa_core/risk",
    "spa_core/execution",
    "spa_core/monitoring",
    "spa_core/allocator",
    "spa_core/adapters",
)

BASELINE_REL = "scripts/forbidden_import_baseline.json"

#: Вызовы, которыми модуль ввозит библиотеку по ИМЕНИ-СТРОКЕ.
_DYNAMIC_CALLS = ("import_module", "__import__")


class Finding:
    """Одна находка: где, что, какой формой и какого класса."""

    __slots__ = ("path", "lib", "kind", "lineno", "form")

    def __init__(self, path: str, lib: str, lineno: int, form: str):
        self.path = path
        self.lib = lib
        self.kind = FORBIDDEN[lib]
        self.lineno = lineno
        self.form = form

    @property
    def key(self) -> str:
        """Ключ для базы: путь и библиотека. НЕ номер строки — он ездит от правок."""
        return f"{self.path}::{self.lib}"

    def __str__(self) -> str:
        return (f"{self.path}:{self.lineno}: запрещённый импорт «{self.lib}» "
                f"({self.kind}, форма {self.form})")


def _root_of(dotted: str) -> Iterable[str]:
    """Все запрещённые корни, которыми накрывается точечное имя."""
    for lib in FORBIDDEN:
        if dotted == lib or dotted.startswith(lib + "."):
            yield lib


def _literal_name(node: ast.AST) -> str | None:
    """Строковый литерал первого аргумента динамического импорта, иначе None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_source(path: str, src: str) -> list[Finding]:
    """Разобрать ОДИН файл. SyntaxError наружу — это третий исход, не ноль находок."""
    tree = ast.parse(src)
    found: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for lib in _root_of(alias.name):
                    found.append(Finding(path, lib, node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom):
            # level > 0 — относительный импорт внутри пакета: чужой библиотеки
            # там быть не может по построению.
            if node.level:
                continue
            for lib in _root_of(node.module or ""):
                found.append(Finding(path, lib, node.lineno, "from-import"))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else None)
            if name not in _DYNAMIC_CALLS or not node.args:
                continue
            literal = _literal_name(node.args[0])
            if literal is None:
                continue
            for lib in _root_of(literal):
                found.append(Finding(path, lib, node.lineno, "dynamic"))
    return found


def load_baseline(root: str) -> dict:
    """Прочитать базу. Нет файла — пустая база (это не ошибка: база может исчезнуть,
    когда исчезло последнее нарушение). Битый файл — исключение наружу: молча
    считать базу пустой значило бы покраснеть не тем вопросом."""
    path = os.path.join(root, BASELINE_REL)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc.get("known", {})


def scan_tree(root: str, domains: Iterable[str] = DOMAINS):
    """Обойти домены. Возврат: (находки, непрочитанные, осмотрено файлов)."""
    findings: list[Finding] = []
    unmeasured: list[str] = []
    scanned = 0
    for domain in domains:
        abs_domain = os.path.join(root, domain)
        if not os.path.isdir(abs_domain):
            unmeasured.append(f"{domain}: каталога нет — домен НЕ ИЗМЕРЕН")
            continue
        for dirpath, dirnames, filenames in os.walk(abs_domain):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                abs_path = os.path.join(dirpath, filename)
                rel = os.path.relpath(abs_path, root)
                try:
                    with open(abs_path, encoding="utf-8") as fh:
                        src = fh.read()
                except OSError as exc:
                    unmeasured.append(f"{rel}: не прочитан ({exc}) — НЕ ИЗМЕРЕН")
                    continue
                try:
                    findings.extend(scan_source(rel, src))
                except SyntaxError as exc:
                    unmeasured.append(f"{rel}: не разобран ({exc}) — НЕ ИЗМЕРЕН")
                    continue
                scanned += 1
    return findings, unmeasured, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=REPO_ROOT,
                        help="корень дерева (по умолчанию — корень репозитория)")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    try:
        baseline = load_baseline(root)
    except (OSError, ValueError) as exc:
        print(f"НЕ ИЗМЕРЕНО: база {BASELINE_REL} не прочитана ({exc})")
        return 2

    findings, unmeasured, scanned = scan_tree(root)
    fresh = [f for f in findings if f.key not in baseline]
    known = [f for f in findings if f.key in baseline]
    stale = sorted(set(baseline) - {f.key for f in findings})

    if args.json:
        print(json.dumps({
            "scanned_files": scanned,
            "violations": [{"path": f.path, "lib": f.lib, "class": f.kind,
                            "line": f.lineno, "form": f.form,
                            "known": f.key in baseline} for f in findings],
            "stale_baseline": stale,
            "unmeasured": unmeasured,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"=== Запрещённые импорты: осмотрено {scanned} файл(ов) "
              f"в {len(DOMAINS)} доменах ===")
        for f in fresh:
            print(f"НАРУШЕНИЕ  {f}")
        for f in known:
            print(f"ИЗВЕСТНОЕ  {f} — {baseline[f.key]}")
        for key in stale:
            print(f"БАЗА УБЫЛА {key}: нарушения больше нет — удалить запись из "
                  f"{BASELINE_REL}")
        for line in unmeasured:
            print(f"НЕ ИЗМЕРЕНО {line}")

    if unmeasured:
        return 2
    if not scanned:
        # Ноль осмотренных файлов — это «мерить было нечем», а не «чисто».
        if not args.json:
            print("НЕ ИЗМЕРЕНО: осмотрено ноль файлов")
        return 2
    if fresh:
        return 1
    if not args.json:
        print("Forbidden import check PASSED"
              + (f" (известных нарушений в базе: {len(known)})" if known else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
