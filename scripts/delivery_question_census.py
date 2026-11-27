#!/usr/bin/env python3
"""Перепись класса «производная МЕРА, у которой нет вопроса в момент доставки».

Заказ G1100 п. 5 приказа владельца «Portfolio CIO»:

    «ЧЕТЫРНАДЦАТАЯ ДВЕРЬ — ПЯТАЯ ПОДРЯД, КОТОРАЯ СПРАШИВАЕТ ПРОИЗВОДНОЕ
    (ADR-889 реестр · ADR-1060 доска · ADR-1073 перепись · ADR-1112 свежесть
    ссылки · ADR-1126 личность претензии). Население класса „производная мера,
    у которой нет вопроса в момент доставки“ за пределами этих пяти
    НЕ ИЗМЕРЕНО — нулём это не считается.»

ЕДИНИЦА КЛАССА — МЕРА, А НЕ ФАЙЛ, И ЭТО ЗАМЕР, А НЕ ВЫБОР УДОБСТВА
─────────────────────────────────────────────────────────────────────────────
Первая редакция этой переписи считала единицей ОБЪЯВЛЕНИЕ (файл: реестр, доска,
база храповика) и была ОПРОВЕРГНУТА тремя замерами подряд — каждый терял
известных членов, то есть ПОДМЕНЯЛ класс (урок ADR-1074):

    форма «в имени есть `baseline`»            4 известных → нашла 1
    форма «сторож НАЗЫВАЕТ объявление
      модульной привязкой»                     4 известных → нашла 1
    форма «инструмент ПИШЕТ объявление и
      перечисляет каталог» (дорога значения)   4 известных → нашла 1

Третий замер объяснил, ПОЧЕМУ: у `scripts/python_git_ref_provenance.py`
писателя базы нет вовсе (её ведут руками), а сторожа доски и переписи
объявления не называют — они называют ПРОИЗВОДИТЕЛЯ и спрашивают его
(дисциплина «одна дверь»). То есть общего ФАЙЛОВОГО свойства у пяти членов
нет, а общее свойство МЕРЫ есть: **вердикт сторожа зависит от НАБОРА файлов на
диске, и доставка, его объявления не тронувшая, краснит его у ЧУЖОГО цикла.**

ТРИ ДВЕРИ, И НИ ОДНОЙ СВОЕЙ КОПИИ
─────────────────────────────────────────────────────────────────────────────
1. **Набор-зависимость** — `derived_artifact_census.measure_surface`
   (ADR-1073/1074). Своего обхода здесь НЕТ: разойдись он с прибором — число
   предмета отвечало бы на вопрос о моей копии. Охват прибора —
   `spa_core/tests/test_*.py` (`glob`); это ГРАНИЦА ОХВАТА, а не замер пустоты
   `tests/`, `scripts/tests/`, `studio_shell/`.
2. **Что ИМЕЕТ вопрос** — AST самих дверей доставки (`push_to_github*.py`):
   у каждого `enforce_delivery_*` берутся ПРОИЗВОДИТЕЛИ, которых он ввозит, и
   ПУТИ, которые он судит. Нужен ОДИН хоп через загрузчик: гейт реестра
   называет `scripts/adr_number.py` не сам, а через свой `_adr_number_module()`,
   и мерка без хопа находила 2 производителя из 5.
3. **Полнота перечня дверей — у РЕЕСТРА РЕШЕНИЙ**, а не у моего списка (урок
   ADR-1113: закрытый перечень известных членов зелен ПО ПОСТРОЕНИЮ). Реестр
   (`docs/decisions/INDEX.md` + архив) спрашивается на строки, чей ЗАГОЛОВОК
   объявляет дверь доставки; из решения читаются (а) имя гейта и (б) имена его
   сторожей. Реестр назвал гейт, которого в пушере нет ⇒ ОТКАЗ. Реестр назвал
   сторожей, и ни один не вышел `gated` ⇒ ОТКАЗ: связка «сторож ↔ дверь»
   сломана, и число предмета было бы ответом о моей мерке.

СВЯЗКА «СТОРОЖ ↔ ДВЕРЬ» — ТРИ ФОРМЫ, И ВСЕ ТРИ НУЖНЫ
─────────────────────────────────────────────────────────────────────────────
    производитель  сторож спрашивает тот же инструмент, что ввозит гейт
    каталог        сторож перечисляет каталог, под которым лежит судимый путь
    судимый путь   сторож НАЗЫВАЕТ путь, который гейт судит

Ни одной из трёх по отдельности не хватает: набор-зависимость сторожа ADR-889
идёт от `docs/journal`, а его связь с дверью — через судимый путь
`docs/decisions/INDEX.md`; у ADR-1126 связь только через производителя.

ИСХОДЫ РАЗЛИЧИМЫ (инв. #17)
─────────────────────────────────────────────────────────────────────────────
    gated       есть дверь доставки, спрашивающая о том же
    subject     набор-зависим, двери НЕТ — ПРЕДМЕТ класса
    unmeasured  путь сторожа прибором не разобран (`unresolved`)

Население предмета есть ВИЛКА `subject … subject + unmeasured`: неразобранные
пути нулём не считаются. «Красен сегодня» мерой класса НЕ является — бомба,
чей набор ещё не вырос, зелена и остаётся членом (урок ADR-897).

Коды возврата: 0 — предмета нет · 1 — предмет НАЗВАН · 2 — НЕ ИЗМЕРЕНО.
Прибор только ЧИТАЕТ: ни дверей доставки, ни баз, ни `data/` не меняет.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import pathlib
import re
import sys

GATED = "gated"
SUBJECT = "subject"
UNMEASURED = "unmeasured"

SOURCE_DIR = "source_dir"
UNRESOLVED = "unresolved"

PUSHERS = ("push_to_github.py", "push_to_github_batch.py")
REGISTERS = ("docs/decisions/INDEX.md", "docs/decisions/INDEX-ARCHIVE.md")

#: Строка реестра объявляет дверь доставки, если её ЗАГОЛОВОК несёт одну из
#: этих форм. Форма спрашивается у заголовка, а имя гейта — у тела решения:
#: два разных вопроса, и смешать их значило бы судить прозу вместо кода.
REGISTER_DOOR_FORMS = (
    re.compile(r"доставка не спрашивала", re.I),
    re.compile(r"\bдвер[ьи]\s+доставки", re.I),
    re.compile(r"дверь\s+семейства\s+доставки", re.I),
    re.compile(r"\b\d+-я\s+дверь", re.I),
)

#: Гейт двери доставки — НЕ только `enforce_delivery_*`. Первая редакция брала
#: один префикс, и положительный контроль РЕЕСТРА её опроверг: ADR-150 объявлен
#: дверью доставки, а его гейт зовётся `enforce_adr_numbers`. Соглашение об
#: имени полнотой перечня не является (урок ADR-1113 в третьей форме).
GATE_PREFIXES = ("enforce_", "guard_")
GATE_NAME = re.compile(r"\b(?:enforce|guard|check)_[a-z_]+")
GUARD_NAME = re.compile(r"\btest_[a-z0-9_]+\.py")

#: Каталоги, тест-файлы которых прибор набор-зависимости НЕ видит.
OUT_OF_PROBER_SCOPE = ("tests/", "scripts/tests/", "studio_shell/", "research/cards/")


class NotMeasured(RuntimeError):
    """Третий исход: вопрос не задан, и это НЕ ноль."""


# ────────────────────────── общие двери разбора ───────────────────────────

def _docstring_ids(tree: ast.AST) -> set:
    """Узлы-докстринги: имя, названное только в прозе, чтением не является.

    Урок #1217 (и его повтор #1272 на f-строке): AST-мерка «имя встречается»
    зачла упоминание в докстринге за проверку.
    """
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            out.add(id(body[0].value))
    return out


def _string_constants(tree: ast.AST) -> set:
    docs = _docstring_ids(tree)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
    }


def _parse(path: pathlib.Path):
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None
    try:
        return ast.parse(src), src
    except SyntaxError:
        return None, src


# ───────────────── дверь 2: что ИМЕЕТ вопрос в момент доставки ────────────

def _names_in(node, funcs, consts, docs, depth=0, seen=()) -> tuple:
    """Производители (`*.py`) и судимые пути, названные внутри гейта.

    ОДИН хоп через загрузчик того же модуля: гейт реестра называет
    `scripts/adr_number.py` не сам, а через `_adr_number_module()`.
    """
    producers, paths = set(), set()
    for inner in ast.walk(node):
        value = None
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str) and id(inner) not in docs:
            value = inner.value
        elif isinstance(inner, ast.Name) and inner.id in consts:
            value = consts[inner.id]
        if value and value not in (".py", "*.py") and "*" not in value:
            if value.endswith(".py"):
                producers.add(pathlib.PurePosixPath(value).name)
            if "/" in value and " " not in value:
                paths.add(value)
        if depth < 2 and isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                and inner.func.id in funcs and inner.func.id not in seen:
            sub_p, sub_q = _names_in(funcs[inner.func.id], funcs, consts, docs,
                                     depth + 1, seen + (inner.func.id,))
            producers |= sub_p
            paths |= sub_q
    return producers, paths


def delivery_doors(root: pathlib.Path) -> dict:
    """gate-имя → {producers, paths} по ОБЕИМ дверям доставки."""
    doors: dict = {}
    seen_pusher = False
    for name in PUSHERS:
        path = root / name
        if not path.is_file():
            continue
        tree, _ = _parse(path)
        if tree is None:
            raise NotMeasured(f"дверь доставки не разобрана: {name}")
        seen_pusher = True
        docs = _docstring_ids(tree)
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        consts = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for gate, node in funcs.items():
            if not gate.startswith(GATE_PREFIXES):
                continue
            producers, paths = _names_in(node, funcs, consts, docs)
            slot = doors.setdefault(gate, {"producers": set(), "paths": set(), "where": set()})
            slot["producers"] |= producers
            slot["paths"] |= paths
            slot["where"].add(name)
    if not seen_pusher:
        raise NotMeasured("ни одной двери доставки в дереве — пустота мерой не является")
    if not doors:
        raise NotMeasured("в дверях доставки нет ни одного `enforce_delivery_*`")
    return doors


# ───────── дверь 3: полнота перечня дверей — у РЕЕСТРА РЕШЕНИЙ ────────────

def register_doors(root: pathlib.Path) -> tuple:
    """Двери, объявленные РЕЕСТРОМ РЕШЕНИЙ, и провенанс замера."""
    rows: dict = {}
    read: list = []
    for rel in REGISTERS:
        path = root / rel
        if not path.is_file():
            read.append(f"{rel}: ОТСУТСТВУЕТ")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise NotMeasured(f"реестр решений не прочитан: {rel}: {exc}") from exc
        total = 0
        for line in text.splitlines():
            if not line.startswith("| ADR-"):
                continue
            total += 1
            cells = line.split("|")
            if len(cells) < 3:
                continue
            number, title = cells[1].strip(), cells[2].strip()
            if any(form.search(title) for form in REGISTER_DOOR_FORMS):
                rows[number] = (title, rel)
        read.append(f"{rel}: строк {total}")
    if not rows:
        raise NotMeasured(
            "реестр решений не назвал НИ ОДНОЙ двери доставки — форма заголовка "
            "перестала совпадать, и число предмета стало бы ответом о моём списке"
        )
    declared: dict = {}
    for number, (title, rel) in sorted(rows.items()):
        hits = sorted(root.glob(f"docs/decisions/{number}-*.md"))
        info = {"title": title[:140], "register": rel, "gates": [], "guards": [], "body": None}
        if not hits:
            info["body"] = "ОТСУТСТВУЕТ"
        else:
            try:
                body = hits[0].read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                info["body"] = f"НЕ ПРОЧИТАН: {exc}"
            else:
                info["body"] = hits[0].relative_to(root).as_posix()
                info["gates"] = sorted(set(GATE_NAME.findall(body)))
                info["guards"] = sorted(set(GUARD_NAME.findall(body)))
        declared[number] = info
    return declared, read


def _load_prober(root: pathlib.Path):
    """Прибор набор-зависимости берётся ПО ПУТИ из НАЗВАННОГО дерева.

    Ввоз ПО ИМЕНИ (`import derived_artifact_census`) отдал бы любой модуль, уже
    лежащий в `sys.modules` или на `sys.path`, — то есть перепись отвечала бы о
    ЧУЖОМ дереве и об этом не сказала бы ни строкой. Это ровно класс ADR-796
    («дерево, из которого читаются байты»), и сцена
    `test_missing_prober_refuses_instead_of_returning_zero` его и нашла: при
    удалённом из сцены приборе ввоз ПО ИМЕНИ УДАВАЛСЯ, и перепись объявляла бы
    число предмета, померив чужой прибор.
    """
    path = root / "scripts" / "derived_artifact_census.py"
    if not path.is_file():
        raise NotMeasured(f"прибор набор-зависимости не ввезён: нет файла {path}")
    sys.path.insert(0, str(root / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location("_dac_for_delivery_question", path)
        if spec is None or spec.loader is None:
            raise NotMeasured(f"прибор набор-зависимости не ввезён: спек не собран для {path}")
        module = importlib.util.module_from_spec(spec)
        # `dataclass` ищет модуль в `sys.modules[cls.__module__]`, поэтому до
        # исполнения прибор обязан быть ТАМ; после — снимается, чтобы подмена
        # не пережила зов и не досталась СОСЕДУ по процессу (урок ADR-1075).
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except NotMeasured:
        sys.modules.pop(spec.name if spec else "", None)
        raise
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(spec.name if spec else "", None)
        raise NotMeasured(f"прибор набор-зависимости не ввезён: {exc!r}") from exc
    finally:
        if sys.path and sys.path[0] == str(root / "scripts"):
            sys.path.pop(0)
    sys.modules.pop(spec.name, None)
    if not hasattr(module, "measure_surface"):
        raise NotMeasured("у прибора набор-зависимости нет двери `measure_surface`")
    return module


# ───────────────────────────── сам замер ──────────────────────────────────

def _guard_producers(entry) -> set:
    """Инструменты, которые сторож СПРАШИВАЕТ (один хоп, по ответу прибора)."""
    out = set()
    for call in entry.calls:
        attr = call.attr or ""
        if "@" in attr:
            out.add(attr.split("@", 1)[1])
        for token in (call.reason or "").split():
            if token.endswith(".py"):
                out.add(pathlib.PurePosixPath(token).name)
    return out


def measure(root: pathlib.Path) -> dict:
    doors = delivery_doors(root)
    declared, register_read = register_doors(root)

    gate_names = set(doors)
    register_gates = {g for info in declared.values() for g in info["gates"]}
    # Гейт, названный реестром и отсутствующий в дверях доставки, — НЕ ИЗМЕРЕНО
    # с названной причиной, а не отказ: он может жить в другом модуле, и судить
    # об этом — другой вопрос. Причина ПЕЧАТАЕТСЯ, молчания нет.
    elsewhere = sorted(register_gates - gate_names)

    door_producers = {p for slot in doors.values() for p in slot["producers"]}
    door_paths = {p for slot in doors.values() for p in slot["paths"] if p != "/"}
    door_dirs = {str(pathlib.PurePosixPath(p).parent) for p in door_paths}
    door_dirs.discard(".")

    dac = _load_prober(root)
    try:
        surface = dac.measure_surface(root)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"поверхность не измерена: {exc}") from exc

    guards: list = []
    for entry in surface.entries:
        if entry.kind == UNRESOLVED:
            guards.append({"path": entry.path, "verdict": UNMEASURED,
                           "reason": "путь сторожа прибором не разобран (`unresolved`)",
                           "ties": {}})
            continue
        if entry.kind != SOURCE_DIR:
            continue
        producers = _guard_producers(entry)
        dirs = set(entry.source_dirs or ())
        tree, _ = _parse(root / entry.path)
        named = _string_constants(tree) if tree is not None else set()
        tie_producer = sorted(producers & door_producers)
        # Связка по каталогу — только РАВЕНСТВО. Вложенность в любую сторону
        # пере-связывает: дверь ADR-889 судит ОДИН файл в `docs/decisions`, а не
        # проекцию всего `docs/`, и сторож, перечисляющий `docs/`, краснеет от
        # нового документа, о котором эта дверь не спрашивает ни разу.
        tie_dir = sorted(d for d in dirs if d in door_dirs)
        tie_path = sorted(
            p for p in door_paths
            if p in named or pathlib.PurePosixPath(p).name in named
        )
        ties = {"producer": tie_producer, "dir": tie_dir, "path": tie_path}
        verdict = GATED if (tie_producer or tie_dir or tie_path) else SUBJECT
        guards.append({"path": entry.path, "verdict": verdict,
                       "reason": "", "ties": ties,
                       "producers": sorted(producers)[:6], "dirs": sorted(dirs)[:6]})

    by_path = {g["path"]: g for g in guards}
    # ── положительный контроль: связку проверяет РЕЕСТР, а не мой список ──
    control: dict = {}
    for number, info in sorted(declared.items()):
        inside = [g for g in info["guards"] if f"spa_core/tests/{g}" in by_path]
        if not info["guards"]:
            control[number] = "решение не называет ни одного сторожа"
            continue
        if not inside:
            control[number] = "названные сторожа вне охвата прибора — граница ОХВАТА"
            continue
        verdicts = {g: by_path[f"spa_core/tests/{g}"]["verdict"] for g in inside}
        control[number] = verdicts
        if GATED not in verdicts.values():
            raise NotMeasured(
                f"{number} объявлен дверью доставки, его сторож(а) {sorted(verdicts)} "
                "внутри поверхности, и НИ ОДИН не вышел `gated` — связка «сторож ↔ дверь» "
                "сломана, число предмета было бы ответом о моей мерке"
            )

    counts: dict = {}
    for guard in guards:
        counts[guard["verdict"]] = counts.get(guard["verdict"], 0) + 1
    return {
        "root": str(root),
        "register_read": register_read,
        "register_doors": {n: i["title"] for n, i in declared.items()},
        "gates": sorted(gate_names),
        "gates_named_by_register_but_elsewhere": elsewhere,
        "door_producers": sorted(door_producers),
        "door_paths": sorted(door_paths),
        "prober_scope": "spa_core/tests/test_*.py",
        "out_of_scope": list(OUT_OF_PROBER_SCOPE),
        "control": control,
        "counts": counts,
        "guards": guards,
        "code": 1 if counts.get(SUBJECT) else 0,
    }


def render(report: dict, names: bool, limit: int) -> str:
    counts = report["counts"]
    subject = counts.get(SUBJECT, 0)
    unmeasured = counts.get(UNMEASURED, 0)
    out = [
        f"дерево: {report['root']}  (ВЫБОР НАПЕЧАТАН, не угадан)",
        "реестр решений (дверь 3, полнота перечня): " + " · ".join(report["register_read"]),
        f"реестр объявил дверей доставки: {len(report['register_doors'])} "
        f"({', '.join(sorted(report['register_doors']))})",
        f"гейтов в дверях доставки: {len(report['gates'])}; "
        f"производителей они ввозят {len(report['door_producers'])} "
        f"({', '.join(report['door_producers'])})",
        f"набор-зависимых мер: {subject + counts.get(GATED, 0)} — "
        f"ПРЕДМЕТ {subject} · под дверью {counts.get(GATED, 0)}",
        f"⚠️ НЕ ИЗМЕРЕНО {unmeasured} — нулём это не считается: население предмета "
        f"есть ВИЛКА {subject} … {subject + unmeasured}",
        "гейты, названные реестром и живущие ВНЕ дверей доставки (НЕ ИЗМЕРЕНО, "
        "не отказ): " + (", ".join(report["gates_named_by_register_but_elsewhere"]) or "нет"),
        f"охват прибора: {report['prober_scope']}; вне охвата (НЕ замер пустоты): "
        + ", ".join(report["out_of_scope"]),
    ]
    out.append("положительный контроль (связку проверяет РЕЕСТР):")
    for number, verdicts in sorted(report["control"].items()):
        if isinstance(verdicts, str):
            out.append(f"  {number}: {verdicts}")
        else:
            out.append(f"  {number}: " + ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items())))
    if names:
        shown = 0
        for guard in report["guards"]:
            if guard["verdict"] != SUBJECT:
                continue
            out.append(f"  ПРЕДМЕТ  {guard['path']} ← каталоги {guard.get('dirs')}")
            shown += 1
            if limit and shown >= limit:
                out.append(f"  … ещё {subject - shown} (предел печати {limit})")
                break
    out.append("— прибор только ЧИТАЕТ: ни дверей доставки, ни баз, ни data/ не меняет —")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=None, help="дерево, которое мерить")
    parser.add_argument("--names", action="store_true", help="печатать предмет поимённо")
    parser.add_argument("--limit", type=int, default=20, help="предел печати предмета")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.repo_root).resolve() if args.repo_root \
        else pathlib.Path(__file__).resolve().parent.parent
    try:
        report = measure(root)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report, args.names, args.limit))
    return report["code"]


if __name__ == "__main__":
    raise SystemExit(main())
