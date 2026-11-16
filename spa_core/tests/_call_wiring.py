"""«Достижим» ≠ «зовётся»: упоминание стема проводкой не является.

# LLM_FORBIDDEN

Храповик `test_unwired_guard_modules_ratchet` и прибор `_mention_wiring`
стоят на ОДНОМ отношении — **упоминает**: встречается ли стем модуля в тексте
чужого файла (проза, комментарий, текст сообщения, груз пуша и путь тест-файла
срезаны четырьмя ужесточениями). `_root_reachability` (ADR-1027) спросил о
САМОМ упоминающем — достижим ли он от того, кто зовёт извне, — и вилку класса
«проводка упоминанием сироты» схлопнул в точку [3, 3].

Ни один из трёх не спрашивает того, чем проводка является по смыслу:
**зовёт ли упоминающий импортированное имя.** Файл, который написал
`from spa_core.monitoring import X` и больше ни разу `X` не тронул, числится
проводкой у всех трёх; то же — строка `"x_monitor"` в словаре артефактов и
ключ манифеста. Это ровно тот класс «доказательство слабее вызова», который
уже ловили четыре раза (#227 комментарий · #255 докстрока · #278 текст
сообщения · ADR-835 путь тест-файла), только на пятом носителе: **импорт без
использования.**

## Три исхода (инвариант #17)

* `CALLED` — хотя бы один упоминающий ЗОВЁТ: использует имя, связанное
  импортом, либо исполняет модуль строкой (`python -m …`, путь `…/X.py`).
* `MENTION_ONLY` — depth-1 числит субъекта подключённым, упоминающие есть, и
  НИ ОДИН не зовёт. **Предмет класса.**
* `CENSUS` — субъекта не упоминает никто; он уже на учёте храповика и
  предметом ЭТОГО класса не является.

«Не измерено» — ОТДЕЛЬНЫЙ исход, а не ноль: нечитаемый или неразбираемый
файл поверхности поднимает `Unmeasured` (он и мог быть настоящим вызывающим),
CLI выходит кодом 2.

## Знак ошибки объявлен: найденное население есть ПОЛ

Признак «зовёт» намеренно ЩЕДРЫЙ — сомнение трактуется в пользу вызова:

* dotted-импорт (`import a.b.c`) засчитывается использованным, если в файле
  тронут хотя бы корень цепочки;
* строка, содержащая путь модуля или `<стем>.py`, считается исполнением, не
  спрашивая, доходит ли она до `subprocess`;
* достижимость упоминающего (ось ADR-1027) здесь НЕ домножается — вопрос
  один, и composition с той осью дана отдельным числом.

Значит ошибка идёт в сторону «вызов есть» ⇒ МЕНЬШЕ членов класса. Найденное
число — **ПОЛ класса, а не потолок**; утверждать по нему «больше членов нет»
запрещено, ровно как у ADR-1026/1027.

## Почему прибор лежит в `spa_core/tests/`

Каталог `*/tests/*` исключён из поверхности скана храповика, поэтому прибор не
становится собственным подопечным (урок G1015 п. 1). ADVISORY: своего вердикта
в храповик не вносит, пока решение о храповике не принято отдельно.
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

from spa_core.tests import _mention_wiring as _mw
from spa_core.tests import test_unwired_guard_modules_ratchet as _ratchet

#: Поверхности и суффиксы берутся у прибора упоминаний — своей копии нет.
WATCHED_DIRS = _mw.WATCHED_DIRS
SCAN_SUBDIRS = _mw.SCAN_SUBDIRS
SCAN_SUFFIXES = _mw.SCAN_SUFFIXES
MIN_SUBJECTS = _mw.MIN_SUBJECTS

CALLED = "CALLED"
MENTION_ONLY = "MENTION_ONLY"
CENSUS = "CENSUS"

#: Как упоминающий ЗОВЁТ — род доказательства, печатается поимённо.
BY_IMPORT_USE = "import+use"
BY_DOTTED_ROOT = "import.dotted+root-use"
BY_EXEC_STRING = "exec-string"
NOT_A_CALL = "mention-only"


class Unmeasured(RuntimeError):
    """Поверхность не прочитана/не разобрана или тонка — это НЕ ноль находок."""


def _dotted(rel: str) -> str:
    """`spa_core/monitoring/x.py` → `spa_core.monitoring.x`."""
    return rel[:-3].replace("/", ".")


def _exec_string_re(stem: str, dotted: str) -> re.Pattern:
    """Форма ИСПОЛНЕНИЯ модуля строкой: `-m <путь>` либо путь `…/<стем>.py`.

    Щедро по построению (см. докстроку): до `subprocess` строка не
    прослеживается, поэтому «исполнение» засчитывается и там, где строка лишь
    лежит рядом. Ошибка — в сторону «вызов есть» ⇒ меньше членов класса.
    """
    return re.compile(
        r"(?:-m\s+" + re.escape(dotted) + r"\b)"
        r"|(?:\b" + re.escape(dotted) + r"\b)"
        r"|(?:[\w./-]*\b" + re.escape(stem) + r"\.py\b)")


def _import_bindings(tree: ast.AST, mentioner_rel: str,
                     dotted: str, stem: str) -> Tuple[Set[str], Set[str]]:
    """Имена, которые импорт СВЯЗАЛ с субъектом.

    Возвращает (простые имена, корни dotted-импортов). Относительный импорт
    разрешается от пакета упоминающего — иначе `from . import x` внутри
    `spa_core/monitoring/` остался бы невидим, а это самая частая его форма.
    """
    parent_pkg = dotted.rsplit(".", 1)[0]
    mentioner_pkg = _dotted(mentioner_rel).rsplit(".", 1)[0]
    simple: Set[str] = set()
    dotted_roots: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name != dotted:
                    continue
                if al.asname:
                    simple.add(al.asname)
                else:
                    dotted_roots.add(al.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                base = mentioner_pkg.split(".")
                base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
                mod = ".".join([*base, mod]) if mod else ".".join(base)
            if mod == dotted:
                # `from <субъект> import name` — используется имя ИЗ субъекта.
                for al in node.names:
                    simple.add(al.asname or al.name)
            elif mod == parent_pkg:
                for al in node.names:
                    if al.name == stem:
                        simple.add(al.asname or al.name)
    return simple, dotted_roots


def _loads_outside_imports(tree: ast.AST) -> Set[str]:
    """Простые имена, прочитанные (`Load`) ВНЕ самих операторов импорта."""
    inside: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            inside.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    used: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.lineno not in inside:
                used.add(node.id)
    return used


def classify_pair(mentioner_rel: str, raw: str, subject_rel: str) -> Tuple[str, str]:
    """Как упоминающий относится к субъекту: (зовёт?, род доказательства).

    Поднимает `Unmeasured`, если упоминающий `.py` не разбирается: он и мог
    быть настоящим вызывающим, и молчаливый пропуск сделал бы «не разобрали»
    неотличимым от «не зовёт».
    """
    stem = pathlib.Path(subject_rel).stem
    dotted = _dotted(subject_rel)
    if not mentioner_rel.endswith(".py"):
        # Обёртка, plist, манифест ссылаются на модуль СТРОКОЙ. Строка-путь или
        # `-m` — это вызов; остальное (ключ манифеста, имя артефакта) — нет.
        if _exec_string_re(stem, dotted).search(raw):
            return BY_EXEC_STRING, BY_EXEC_STRING
        return NOT_A_CALL, NOT_A_CALL
    try:
        tree = ast.parse(raw)
    except SyntaxError as exc:
        raise Unmeasured(
            f"упоминающий не разобран, а он и мог звать: {mentioner_rel} — {exc}"
        ) from exc
    simple, dotted_roots = _import_bindings(tree, mentioner_rel, dotted, stem)
    if simple or dotted_roots:
        used = _loads_outside_imports(tree)
        if simple & used:
            return BY_IMPORT_USE, BY_IMPORT_USE
        if dotted_roots & used:
            return BY_DOTTED_ROOT, BY_DOTTED_ROOT
    # Импорта нет либо связанное имя не тронуто — остаётся форма исполнения
    # строкой (`subprocess`, `python -m`), и её ищем в литералах.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _exec_string_re(stem, dotted).search(node.value):
                return BY_EXEC_STRING, BY_EXEC_STRING
    return NOT_A_CALL, NOT_A_CALL


def measure(root: Optional[pathlib.Path] = None,
            min_subjects: int = MIN_SUBJECTS) -> dict:
    """Замер населения класса «числится подключённым, но его не зовут»."""
    base = pathlib.Path(root) if root is not None else pathlib.Path(_mw._ROOT)
    base = base.resolve()
    try:
        subj = _mw.subjects(base)
        texts = _mw.tree_texts(base)
    except _mw.Unmeasured as exc:
        raise Unmeasured(str(exc)) from exc
    if len(subj) < min_subjects:
        raise Unmeasured(
            f"субъектов всего {len(subj)} при поле {min_subjects} — скан сузился, "
            "и «класс пуст» значило бы «мерить было нечем»")

    raw: Dict[str, str] = {}
    unreadable: List[str] = []
    for rel in texts:
        try:
            raw[rel] = (base / rel).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable.append(f"{rel}: {exc}")
    if unreadable:
        raise Unmeasured(
            "файлы поверхности не прочитаны, и любой мог быть настоящим "
            f"вызывающим: {unreadable}")

    stem = {m: pathlib.Path(m).stem for m in subj}
    mentioned_by = {m: sorted(p for p, body in texts.items()
                              if p != m and stem[m] in body) for m in subj}

    status: Dict[str, str] = {}
    evidence: Dict[str, List[dict]] = {}
    for m in subj:
        if not mentioned_by[m]:
            status[m] = CENSUS
            evidence[m] = []
            continue
        rows = []
        called = False
        for p in mentioned_by[m]:
            how, _ = classify_pair(p, raw[p], m)
            rows.append({"path": p, "how": how})
            if how != NOT_A_CALL:
                called = True
        status[m] = CALLED if called else MENTION_ONLY
        evidence[m] = rows

    population = [{"module": m, "mentioned_by": evidence[m]}
                  for m in subj if status[m] == MENTION_ONLY]
    return {
        "measured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "root": str(base),
        "subjects": len(subj),
        "census_depth1": sorted(m for m in subj if status[m] == CENSUS),
        "deemed_wired_depth1": sum(1 for m in subj if status[m] != CENSUS),
        "called": sum(1 for m in subj if status[m] == CALLED),
        "mention_only": population,
        "pairs_examined": sum(len(v) for v in evidence.values()),
        "floor_not_ceiling": True,
        "status": status,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись класса «числится подключённым, но его не зовут» (ADVISORY)")
    ap.add_argument("--root", default=None, help="дерево замера; умолчание ПЕЧАТАЕТСЯ")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-subjects", type=int, default=MIN_SUBJECTS,
                    help="пол непустоты поверхности; сдвиг ПЕЧАТАЕТСЯ")
    a = ap.parse_args(argv)
    if a.root is None:
        print(f"[дерево] умолчание: {_mw._ROOT}", file=sys.stderr)
    if a.min_subjects != MIN_SUBJECTS:
        print(f"[пол] объявлен {a.min_subjects} вместо {MIN_SUBJECTS} — "
              "осознанный сдвиг", file=sys.stderr)
    try:
        rep = measure(pathlib.Path(a.root) if a.root else None,
                      min_subjects=a.min_subjects)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if rep["mention_only"] else 0
    print(f"дерево: {rep['root']}")
    print(f"субъектов (точка входа, {len(WATCHED_DIRS)} каталога): {rep['subjects']}")
    print(f"перепись храповика (не упоминает НИКТО): {len(rep['census_depth1'])}")
    print(f"числятся подключёнными depth-1: {rep['deemed_wired_depth1']}"
          f" · из них ЗОВУТ: {rep['called']}"
          f" · пар «субъект × упоминающий» разобрано: {rep['pairs_examined']}")
    if not rep["mention_only"]:
        print("✅ население класса ПУСТО (это ПОЛ, а не потолок — см. докстроку)")
        return 0
    print(f"🔎 ЧИСЛИТСЯ ПОДКЛЮЧЁННЫМ, НО ЕГО НЕ ЗОВУТ: {len(rep['mention_only'])}")
    for item in rep["mention_only"]:
        print(f"  • {item['module']}")
        for m in item["mentioned_by"]:
            print(f"      ← {m['path']} [{m['how']}]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
