#!/usr/bin/env python3
"""Перепись ПОВЕРХНОСТИ класса «прибор, объявляющий вердикт о населении/классе».

Заказ G922 п. 3 приказа владельца «Portfolio CIO» (ADR-935).

ЧТО ЭТО МЕРИТ И ПОЧЕМУ ВОПРОС ВООБЩЕ ВОЗНИК
─────────────────────────────────────────────────────────────────────────────
ADR-934 (цикл #1049) спросил ШЕСТЬ приборов о СВОЕЙ аварии и получил
`население 6 · sees 6 · BLIND 0`. Эта запись честна ровно о том, о чём
спрашивала, и заказ G922 п. 3 назвал её границу вслух:

    «Шесть сцен — это шесть ОБЪЯВЛЕННЫХ приборов, а не все приборы дерева.»

То есть `население 6` есть население СПИСКА, а не население КЛАССА, и
разница между ними до этой переписи была НЕ ИЗМЕРЕНА. Это ровно тот дефект,
который ADR-932/ADR-934 находили у других: прибор отвечает о СВОЁМ ОХВАТЕ
под видом ответа о дереве. Здесь он стоял у самого свежего прибора семьи.

ОТВЕТ ЕСТЬ ВЕРХНЯЯ ГРАНИЦА, И ЭТО СКАЗАНО ВСЛУХ
─────────────────────────────────────────────────────────────────────────────
Перепись мерит ФОРМУ, а не годность к замеру. Прибор, у которого нет
ВОССТАНОВИМОЙ аварии, в класс ADR-934 не входит — и это ТРЕТИЙ ИСХОД
(`restorability_unmeasured`), а не «видит» и не «слеп». Поэтому:

    население класса ADR-934  ≤  `in_form`

Ошибка переписи идёт в сторону БОЛЬШЕЙ поверхности, и это выбрано нарочно:
мера, ошибающаяся в сторону МЕНЬШЕЙ, умеет сказать «поверхность исчерпана»
про поверхность, которой не видела, — ровно та ложь, против которой написан
весь класс. Завысить поверхность значит позвать лишнего кандидата; занизить
значит объявить работу законченной.

ФОРМА КАЛИБРОВАНА ЗАМЕРОМ, А НЕ ВКУСОМ
─────────────────────────────────────────────────────────────────────────────
Заказ предложил форму «(а) разбирают AST и (б) объявляют вердикт о
ПОПУЛЯЦИИ/КЛАССЕ». Первая половина подтвердилась замером: AST разбирают
6 из 6. Вторая ОПРОВЕРГНУТА на собственных членах класса, дважды, и обе
находки сохранены здесь как причины, по которым критерий НЕ взят:

* «объявляет третий исход модульной константой» теряет
  `forbidden_reach_census` (1 из 6): его `unmeasured` — ЛОКАЛЬНЫЙ список,
  а не константа модуля;
* «сводит предметы в счёт» теряет `_injected_clock` и
  `_subprocess_clock_door` (2 из 6): это ПОШТУЧНЫЕ классификаторы, вердикт
  о населении собирает их ВЫЗЫВАЮЩИЙ. У трети объявленного класса
  критерий (б) живёт ЗА границей модуля, и ни один замер по одному файлу
  его там не достанет.

Поэтому форма — та, что НЕ теряет ни одного известного члена:

    (а) модуль читает код как AST   (`ast.parse` / `walk` / `NodeVisitor` /
        `iter_child_nodes` / `NodeTransformer`), И
    (б) объявляет на уровне модуля ≥2 ЯРЛЫКА ИСХОДА — константу `UPPER_CASE`
        со строковым значением вида идентификатора, — и КАЖДЫЙ из них где-то
        в модуле УПОТРЕБЛЯЕТ (объявление без употребления ярлыком не является:
        это имя файла, ключ или сообщение).

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — ЗАВЕДОМО НЕПУСТОЙ ПРЕДМЕТ
─────────────────────────────────────────────────────────────────────────────
Шесть приборов ADR-934 суть ИЗВЕСТНЫЕ члены класса, и перечень берётся из
`_own_accident_control._scenes()`, а не переписывается сюда: списку,
скопированному руками, нечем состариться вместе с источником. Форма,
потерявшая известного члена, ОПРОВЕРГНУТА — перепись тогда ОТКАЗЫВАЕТ
(код 2, `declared_outside_form` поимённо), а не печатает число. Это и есть
причина, по которой «мои критерии верны» здесь не утверждение автора.

ADVISORY: прибор только ЧИТАЕТ дерево. Ни одного байта не правит, ни одного
подпроцесса не поднимает, о свежести не судит (значит ни одной двери к
календарю и к номерам процессов у него нет по построению).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

#: Исход предмета переписи.
IN_FORM = "in_form"            #: форма совпала — КАНДИДАТ в класс ADR-934
OUT_OF_FORM = "out_of_form"    #: прочитан и разобран, формы нет — измеренный НОЛЬ
UNMEASURED = "unmeasured"      #: не прочитан / не разобран — НЕ «формы нет»
OUTCOMES: tuple[str, ...] = (IN_FORM, OUT_OF_FORM, UNMEASURED)

#: Роль предмета внутри формы.
DECLARED = "declared"          #: уже спрошен о своей аварии (сцена ADR-934)
CANDIDATE = "candidate"        #: в форме, о своей аварии НЕ СПРОШЕН
ROLES: tuple[str, ...] = (DECLARED, CANDIDATE)

#: Атрибуты `ast`, по которым модуль читает КОД, а не текст.
_AST_READERS = frozenset({
    "parse", "walk", "NodeVisitor", "NodeTransformer", "iter_child_nodes",
})

#: Значение-ЯРЛЫК: голый идентификатор. Путь, сообщение, шаблон и имя файла
#: этой формы не имеют — у них есть пробел, точка, косая или проценты.
_LABEL_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

#: Каталоги, в которые перепись не ходит. `.git` здесь — СВОЙ административный
#: каталог; чужие клоны отрезаются НАЛИЧИЕМ `.git` у каталога (ADR-930), а не
#: literal'ом имени: 88,7 % файлов прод-дерева — вложенные чужие worktree, и
#: отрезать их по имени `.claude/worktrees` значило бы пропустить все прочие.
_SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", ".mypy_cache"})


@dataclass(frozen=True)
class Subject:
    """Один файл дерева и что о нём измерено."""

    rel: str
    outcome: str
    role: Optional[str] = None
    #: ярлыки исхода, которые модуль объявил И употребил
    labels: tuple[str, ...] = ()
    reads_ast: bool = False
    #: причина, по которой исход `unmeasured`
    reason: Optional[str] = None


@dataclass
class Census:
    population: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    roles: dict[str, int] = field(default_factory=dict)
    subjects: list[Subject] = field(default_factory=list)
    declared_outside_form: list[str] = field(default_factory=list)
    declared_source: str = ""
    unmeasured_reasons: list[str] = field(default_factory=list)
    #: Пробелы ОБХОДА — две разные двери, и обе дают неполный обход:
    #: каталог не отдан ОС · принадлежность каталога чужому клону НЕ ИЗМЕРЕНА.
    #: Считаются вместе, потому что следствие одно: население вышло НИЖНЕЙ
    #: границей там, где обещана верхняя. Причина у каждого пробела названа
    #: поимённо в `unmeasured_reasons`.
    walk_gaps: int = 0


class Refused(Exception):
    """Предпосылка переписи не обеспечена — отказ с названной причиной."""


# ───────────────────────────── объявленный перечень ──────────────────────────


def declared_instruments(repo_root: pathlib.Path) -> tuple[frozenset[str], str]:
    """Пути приборов, которые ADR-934 УЖЕ спросил о своей аварии.

    Берутся у источника (`_own_accident_control._scenes()`), а не из копии:
    копия не умеет состариться вместе с источником, и перепись тогда
    хвалила бы охват, которого больше нет. Источник не ввозится ⇒ ОТКАЗ:
    без известных членов у формы нет положительного контроля, а форма без
    контроля есть мнение автора.
    """
    source = "spa_core/tests/_own_accident_control.py"
    path = repo_root / source
    if not path.exists():
        raise Refused(
            f"перечень объявленных приборов НЕ ПРОЧИТАН: {source} нет в дереве "
            f"{repo_root} — форму нечем проверить на известных членах"
        )
    # Разбор AST, а не импорт: ввоз чужого модуля из ЧУЖОГО дерева взял бы
    # код из `sys.path`, то есть ответил бы о СВОЁМ дереве под видом ответа
    # о названном (урок ADR-796 — «дерево, из которого читаются байты»).
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise Refused(
            f"перечень объявленных приборов НЕ ПРОЧИТАН: {source} не разобран "
            f"({type(exc).__name__}: {exc})"
        ) from exc

    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "Scene":
            continue
        for kw in node.keywords:
            if kw.arg == "instrument" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                found.add(kw.value.value)
    if not found:
        raise Refused(
            f"перечень объявленных приборов ПУСТ в {source}: ни одной `Scene("
            "instrument=…)` — положительного контроля у формы нет, а «ноль "
            "известных членов» формой не проверяется"
        )
    return frozenset(found), source


# ───────────────────────────── форма одного файла ────────────────────────────


def measure_file(path: pathlib.Path, rel: str) -> Subject:
    """Совпала ли форма у ОДНОГО файла. Третий исход назван причиной."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Subject(rel=rel, outcome=UNMEASURED,
                       reason=f"байты не прочитаны ({type(exc).__name__}: {exc})")
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return Subject(rel=rel, outcome=UNMEASURED,
                       reason=f"не разобран ({type(exc).__name__}: {exc})")

    reads_ast = False
    declared: dict[str, str] = {}
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target is None or value is None:
            continue
        if target.isupper() and isinstance(value, ast.Constant) \
                and isinstance(value.value, str) and _LABEL_VALUE.match(value.value):
            declared[target] = value.value

    # Кратность, а не множество: объявление ярлыка — тоже `ast.Name`, поэтому
    # ярлык обязан встретиться ЕЩЁ раз. Объявление без употребления ярлыком не
    # является (это имя файла, ключ словаря или заготовка).
    hits: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "ast" and node.attr in _AST_READERS:
            reads_ast = True
        # Подкласс `ast.NodeVisitor` читает код, не называя `ast.walk`.
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) \
                        and base.value.id == "ast" and base.attr in _AST_READERS:
                    reads_ast = True
        if isinstance(node, ast.Name) and node.id in declared:
            hits[node.id] = hits.get(node.id, 0) + 1
    labels = tuple(sorted(name for name, n in hits.items() if n >= 2))

    if reads_ast and len(labels) >= 2:
        return Subject(rel=rel, outcome=IN_FORM, labels=labels, reads_ast=True)
    return Subject(rel=rel, outcome=OUT_OF_FORM, labels=labels, reads_ast=reads_ast)


# ───────────────────────────── обход дерева ──────────────────────────────────


def python_files(repo_root: pathlib.Path) -> tuple[list[str], list[str]]:
    """Пути `*.py` НАШЕГО дерева и причины, по которым обход был неполон.

    Чужие клоны отрезаются наличием `.git` У КАТАЛОГА: в прод-дереве их
    десятки, и каждый несёт свою копию тех же приборов — посчитать их значило
    бы умножить население на число клонов (замер: 43 192 из 48 704 файлов
    прод-дерева принадлежат вложенным чужим деревьям).
    """
    out: list[str] = []
    blind: list[str] = []

    def _unwalkable(exc: OSError) -> None:
        # Каталог, не отданный ОС, есть «НЕ ИЗМЕРЕНО» с названной причиной, а не
        # пропуск: молчаливый пропуск сделал бы неполный обход неотличимым от
        # полного, и население вышло бы НИЖНЕЙ границей, выданной за верхнюю.
        blind.append(f"{getattr(exc, 'filename', '?')}: каталог не обойдён "
                     f"({type(exc).__name__}: {exc})")

    for dirpath, dirnames, filenames in os.walk(repo_root, onerror=_unwalkable):
        keep = []
        for name in dirnames:
            if name in _SKIP_DIRS:
                continue
            child = pathlib.Path(dirpath) / name
            try:
                if (child / ".git").exists():
                    continue  # чужой клон: его файлы не наши
            except OSError as exc:
                blind.append(f"{child}: принадлежность НЕ ИЗМЕРЕНА ({exc})")
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            if name.endswith(".py"):
                full = pathlib.Path(dirpath) / name
                out.append(str(full.relative_to(repo_root)))
    return sorted(out), blind


def measure(repo_root: str) -> Census:
    """Перепись поверхности. Отказ — исключение `Refused`, не число."""
    root = pathlib.Path(repo_root).resolve()
    if not (root / ".git").exists():
        raise Refused(f"не git-дерево: {root} — обход не назвал бы своих границ")

    # ПОРЯДОК ЗНАЧИМ, и он исправлен мутацией №16 этого же цикла. Пока перечень
    # известных членов читался ПЕРВЫМ, ветка «ни одного .py» была НЕДОСТИЖИМА:
    # сам перечень лежит в `.py`-файле, поэтому «перечень прочитан» влекло
    # «файлов ≥ 1». Мутант, снявший эту ветку, ВЫЖИЛ — и был прав: ветка была
    # украшением, а проверка о ней проходила по ДРУГОЙ причине (отказ перечня).
    # Обход идёт первым, и теперь у каждого отказа СВОЙ достижимый повод.
    files, blind = python_files(root)
    if not files:
        raise Refused(
            f"ни одного файла .py в {root}: «ноль предметов» и «обход не "
            "состоялся» здесь неотличимы, поэтому это отказ, а не ноль"
        )
    declared, source = declared_instruments(root)

    census = Census(declared_source=source)
    census.unmeasured_reasons.extend(blind)
    census.walk_gaps = len(blind)
    for rel in files:
        subj = measure_file(root / rel, rel)
        if subj.outcome == IN_FORM:
            role = DECLARED if rel in declared else CANDIDATE
            subj = Subject(rel=rel, outcome=IN_FORM, role=role,
                           labels=subj.labels, reads_ast=True)
        census.subjects.append(subj)
        census.counts[subj.outcome] = census.counts.get(subj.outcome, 0) + 1
        if subj.role:
            census.roles[subj.role] = census.roles.get(subj.role, 0) + 1
        if subj.outcome == UNMEASURED and subj.reason:
            census.unmeasured_reasons.append(f"{rel}: {subj.reason}")

    for key in OUTCOMES:
        census.counts.setdefault(key, 0)
    for key in ROLES:
        census.roles.setdefault(key, 0)
    census.population = census.counts[IN_FORM]

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: известный член, не попавший в форму, ОПРОВЕРГАЕТ
    # форму. Молча считать его «вне формы» значило бы подогнать меру под ответ.
    in_form = {s.rel for s in census.subjects if s.outcome == IN_FORM}
    census.declared_outside_form = sorted(declared - in_form)
    return census


# ───────────────────────────── печать ────────────────────────────────────────


def report(census: Census) -> list[str]:
    out = [
        f"перепись поверхности класса «вердикт о населении»: предметов "
        f"{sum(census.counts[k] for k in OUTCOMES)}",
        f"   исходы: {IN_FORM} {census.counts[IN_FORM]} · "
        f"{OUT_OF_FORM} {census.counts[OUT_OF_FORM]} · "
        f"{UNMEASURED} {census.counts[UNMEASURED]}",
        f"   роль внутри формы: {DECLARED} {census.roles[DECLARED]} (спрошены о своей "
        f"аварии, ADR-934) · {CANDIDATE} {census.roles[CANDIDATE]} (НЕ спрошены)",
        f"   перечень объявленных взят у источника: {census.declared_source}",
    ]
    if census.declared_outside_form:
        out.append(
            "   ❌ ФОРМА ОПРОВЕРГНУТА: известный член класса вне формы — "
            + ", ".join(census.declared_outside_form)
        )
    else:
        out.append(
            f"   ✅ положительный контроль: все {census.roles[DECLARED]} объявленных "
            "прибора внутри формы"
        )
    if census.population:
        share = f"{100.0 * census.roles[DECLARED] / census.population:.1f} %"
    else:
        # Пустое население есть ИЗМЕРЕННЫЙ НОЛЬ (так выглядит дерево, где
        # формы нет ни у кого), и доля у него не определена. Печатать «0 %»
        # значило бы выдать неопределённое за измеренное; делить — уронить
        # отчёт ровно там, где он обязан назвать ноль вслух.
        share = "НЕ ОПРЕДЕЛЁН (население ноль)"
    out.append(
        f"   ОТВЕТ: население класса ADR-934 ≤ {census.population}; ADR-934 спросил "
        f"{census.roles[DECLARED]}, то есть охват {share} ВЕРХНЕЙ границы"
    )
    out.append(
        "   НЕ ДОКЛАДЫВАЕТ: есть ли у кандидата ВОССТАНОВИМАЯ авария — это третий "
        "исход, а не «видит»; годность к замеру решает читатель, не форма"
    )
    mine = str(pathlib.Path(__file__).resolve())
    if any(s.outcome == IN_FORM and mine.endswith(s.rel) for s in census.subjects):
        out.append(
            "   САМОССЫЛКА НАЗВАНА: сам этот прибор внутри своей формы (он читает "
            "AST и объявляет ярлыки) — он учтён в населении, и о СВОЕЙ аварии тоже "
            "не спрошен"
        )
    if census.unmeasured_reasons:
        out.append(f"   НЕ ИЗМЕРЕНО у {len(census.unmeasured_reasons)}:")
        for reason in census.unmeasured_reasons[:5]:
            out.append(f"      ▫️ {reason}")
        if len(census.unmeasured_reasons) > 5:
            out.append(f"      …и ещё {len(census.unmeasured_reasons) - 5}")
    out.append("   ADVISORY: прибор только ЧИТАЕТ (ни одного байта не правит)")
    return out


def as_json(census: Census) -> dict:
    return {
        "population": census.population,
        "counts": dict(census.counts),
        "roles": dict(census.roles),
        "declared_source": census.declared_source,
        "declared_outside_form": list(census.declared_outside_form),
        "unmeasured_reasons": list(census.unmeasured_reasons),
        "walk_gaps": census.walk_gaps,
        "candidates": [s.rel for s in census.subjects
                       if s.outcome == IN_FORM and s.role == CANDIDATE],
        "declared": [s.rel for s in census.subjects
                     if s.outcome == IN_FORM and s.role == DECLARED],
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево, О КОТОРОМ спрашивают (умолчание печатается)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-candidates", action="store_true",
                    help="печатать кандидатов поимённо")
    args = ap.parse_args(argv)

    root = args.repo_root
    if root is None:
        root = str(pathlib.Path(__file__).resolve().parents[2])
        if not args.json:
            print(f"— дерево НЕ НАЗВАНО, взято своё: {root} —", file=sys.stderr)

    try:
        census = measure(root)
    except Refused as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(as_json(census), ensure_ascii=False, sort_keys=True))
    else:
        for line in report(census):
            print(line)
        if args.list_candidates:
            for subj in census.subjects:
                if subj.outcome == IN_FORM and subj.role == CANDIDATE:
                    print(f"      · {subj.rel}  ({len(subj.labels)} ярлык(а/ов))")

    if census.declared_outside_form:
        return 2        # форма опровергнута — число не выдаётся за ответ
    if census.counts[UNMEASURED] or census.walk_gaps:
        return 1        # измерено НЕ ПОЛНОСТЬЮ, и это видно по коду возврата
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
