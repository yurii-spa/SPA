#!/usr/bin/env python3
"""
scripts/push_door_census.py — перепись ДВЕРЕЙ ДОСТАВКИ (заказ цикла #571).

Вопрос заказа дословно: «через какие из дверей реально ходит доставка, и сколько
коммитов на `origin/main` пришло через дверь БЕЗ стража?»

И там же названа ЛОВУШКА: «соблазн — сосчитать вызовы в коде и объявить долю; это
ПРИЗНАК, а не замер». Ловушка сработала на самом заказе. Его посылка — «страж
закрывает только `push_to_github.py`, а `push_to_github_batch.py` зовёт
`guard_overwrite` ноль раз, `scripts/push_to_github.py` — тоже ноль» — получена
подсчётом вхождений и ОБЕ названные двери описывает неверно:

  * `push_to_github_batch.py` действительно не зовёт стража САМ, но его CLI зовёт
    `batch_push`, а тот — `build_entries`, а тот — `guard_overwrite`. Дверь закрыта
    ДЕЛЕГИРОВАНИЕМ, и текст файла об этом не свидетельствует.
  * `scripts/push_to_github.py` — тонкий шим (60 строк, своей логики нет), который
    исполняет `main()` канонического корневого модуля. Он «не знает `--allow-overwrite`»
    ровно в том смысле, в каком не знает ничего: он делегирует CLI целиком.

Поэтому прибор меряет не вхождения, а ТРИ разных вопроса, и ни один не заменяет
другого (порядок тот же, что у четырёх сторожей доставки в .claude/rules/deployment.md):

  1. ПИШЕТ ли дверь в origin — сама или делегированием;
  2. ЛЕЖИТ ли вызов стража на её пути записи — сам или делегированием (достижимость
     по графу вызовов, а не совпадение имени в тексте);
  3. Есть ли у двери НАБЛЮДАЕМЫЙ запускающий — plist `ProgramArguments`, вызов из
     обёртки. Упоминание в доках, в тестах и в комментарии проводкой НЕ считается
     (тот же принцип, что в `spa_core/tests/_unwired.py`).

Находкой является только СОВПАДЕНИЕ трёх: дверь пишет · стража на пути нет ·
запускающий наблюдается. Дверь без запускающего — не находка и не «мёртвая»: это
измеренный пустой набор запускающих, и он назван так прямо.

ЧЕТЫРЕ различения, без которых замер врёт (у каждого — положительный контроль
в `spa_core/tests/test_push_door_census.py`, каждый воспроизводит настоящую ошибку
посылки заказа):

  A. ПЕРЕ-ЭКСПОРТ ≠ ВЫЗОВ. `guard_overwrite = _root_push.guard_overwrite` — это
     присваивание. `grep -c` даёт 1 и читается как «страж зовётся»; вызовов ноль.
  B. ДЕЛЕГИРОВАНИЕ СЧИТАЕТСЯ. Страж на пути, даже если он в другом модуле.
  C. ФАЙЛ-АРГУМЕНТ ≠ ЗАПУСКАЮЩИЙ. `scripts/push_all_session.sh` содержит строку
     `.../auto_push.py`, но это ГРУЗ — элемент списка `--files` у другого пушера.
     Текстовый поиск «кто упоминает дверь» объявил бы его запускающим.
  D. КОММЕНТАРИЙ ≠ `ProgramArguments`. В шапке `scripts/com.spa.autopush.plist`
     написано `CLI: python3 auto_push.py`, а исполняется `scripts/auto_push.sh`.
     Читать надо исполняемое поле, а не прозу рядом (то же правило, что «читать
     значение, а не ключ» у `KeepAlive` в .claude/rules/deployment.md).

Третий исход. Файл не разобран, делегирование не разрешено, каталог не найден ⇒
`unmeasured` с НАЗВАННОЙ причиной и ненулевой код возврата. «Не измерено» никогда
не выдаётся за «чисто» (инвариант #17).

Коды возврата:
  0 — измерено, находок нет
  1 — НАХОДКА: пишущая дверь без стража И с наблюдаемым запускающим
  2 — НЕ ИЗМЕРЕНО (причина названа)

stdlib-only.
"""
from __future__ import annotations

import argparse
import ast
import json
import plistlib
import re
import shlex
import sys
from pathlib import Path

# ── Двери-кандидаты: любой .py в корне или scripts/, чьё имя говорит о пуше ──────
# Население берётся ОБХОДОМ КАТАЛОГА, а не списком литералов: список пришлось бы
# править руками, и новая дверь не попала бы в перепись молча. Ровно так заказ #571
# и получил «три двери» там, где их семь.
DOOR_NAME = re.compile(r"push", re.IGNORECASE)

# Признак записи в GitHub: СЕТЕВОЙ ВЫЗОВ в коде плюс эндпоинт в строке-литерале.
# Мерить regex'ом по тексту файла нельзя: прибор поймал бы собственные литералы в
# докстринге и объявил СЕБЯ пишущей дверью — ровно тот класс «признак вместо замера»,
# против которого он и написан (поймано на первом же прогоне).
NET_CALLS = {"urlopen", "Request", "HTTPSConnection", "post", "put", "patch"}
WRITE_ENDPOINT = re.compile(r"/contents/|git/(refs|trees|commits|blobs)|git/ref/")

GUARDS = {"guard_overwrite", "guard_name_loss"}

INTERPRETERS = {"python", "python3", "bash", "sh", "zsh", "/bin/bash", "/bin/sh"}


SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}
_DOOR_PY = re.compile(r"[\w.]*push[\w._]*\.py")


def _spawn_targets(tree: ast.AST, own: Path) -> set[str]:
    """Двери, которые модуль ЗАПУСКАЕТ подпроцессом (различение C, вторая его половина).

    Мерить подстрокой нельзя — на этом прибор ошибся дважды подряд, и оба раза в
    безопасную с виду сторону:
      * он поймал СВОЙ литерал `"subprocess"` в собственном исходнике и объявил себя
        делегирующей дверью;
      * он принял МЁРТВУЮ константу `PUSH_SCRIPT = SPA_DIR / "push_to_github.py"` в
        `auto_push.py` за делегирование — а она присвоена и не используется ни разу.
        Ложное «дверь закрыта стражем» на ЕДИНСТВЕННОЙ незакрытой двери: подстрока
        не просто неточна, она оправдала ровно то, ради чего писалась перепись.

    Поэтому: имя двери засчитывается, только если оно достижимо из АРГУМЕНТА вызова
    `subprocess.*` — литералом или через имя, связанное со строкой/путём.
    """
    # Имя двери приезжает в вызов через цепочку связываний:
    #   _BATCH = _REPO_ROOT / "push_to_github_batch.py"
    #   cmd    = [sys.executable, str(_BATCH), ...]
    #   subprocess.run(cmd, ...)
    # Поэтому связывания разрешаются ДО НЕПОДВИЖНОЙ ТОЧКИ; один проход потерял бы
    # обе делегирующие двери сайта и автопуша.
    assigns: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    assigns.append((tgt.id, node.value))

    consts: dict[str, str] = {}
    for _ in range(len(assigns) + 1):
        changed = False
        for name, value in assigns:
            text = ""
            for n in ast.walk(value):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    text += " " + n.value
                elif isinstance(n, ast.Name):
                    text += " " + consts.get(n.id, "")
            text = text.strip()
            if text and consts.get(name) != text:
                consts[name] = text
                changed = True
        if not changed:
            break

    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in SPAWNERS):
            continue
        blob = ""
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for n in ast.walk(arg):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    blob += " " + n.value
                elif isinstance(n, ast.Name):
                    blob += " " + consts.get(n.id, "")
        for m in _DOOR_PY.findall(blob):
            if Path(m).name != own.name:
                found.add(m)
    return found


class Unmeasured(Exception):
    """Замер не состоялся; причина обязана быть названа."""


# ────────────────────────────── разбор одной двери ──────────────────────────────

def _aliases(tree: ast.AST) -> dict[str, str]:
    """Имена, пере-экспортированные из другого модуля: `X = _mod.X` → {X: 'X'}.

    Различение A: это ПРИСВАИВАНИЕ, не вызов. Возвращаем карту локальное→исходное,
    чтобы достижимость можно было продолжить в каноническом модуле.
    """
    out: dict[str, str] = {}
    # ТОЛЬКО модульный уровень. Внутри функций `x = obj.attr` — обычная работа со
    # структурой (`fn = node.func`), и считать её пере-экспортом значит объявить
    # делегирующей почти любую дверь; прибор так и сделал на самом себе.
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            base = node.value.value
            if not isinstance(base, ast.Name):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = node.value.attr
    return out


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_names(node: ast.AST) -> set[str]:
    """Имена, стоящие в позиции ВЫЗОВА внутри узла (различение A)."""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _reaches_guard(entry: str, funcs: dict[str, ast.AST], canon: dict[str, ast.AST],
                   aliases: dict[str, str], delegates: bool) -> tuple[bool, list[str]]:
    """Достижим ли вызов стража из `entry` по графу вызовов (различение B).

    Ищем до неподвижной точки в объединении «функции двери» + «функции канонического
    модуля», связывая их через пере-экспортированные имена. Возвращаем (достижим, путь).
    """
    seen: set[str] = set()
    stack: list[tuple[str, list[str]]] = [(entry, [entry])]
    while stack:
        name, path = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        body = funcs.get(name)
        if body is None and (name in aliases or delegates):
            # В канонический модуль заглядываем ТОЛЬКО если дверь в него и правда
            # делегирует. Иначе дверь без собственного `main` наследовала бы `main`
            # канонического модуля и объявлялась закрытой стражем — прибор так
            # оправдал бы любую дверь, у которой просто нет функции с этим именем.
            body = canon.get(aliases.get(name, name)) or canon.get(name)
        if body is None:
            continue
        for callee in _called_names(body):
            if callee in GUARDS:
                return True, path + [callee]
            stack.append((callee, path + [callee]))
    return False, []


def inspect_door(path: Path, canon_tree: ast.AST | None) -> dict:
    """Три вопроса к одной двери. Любая неудача разбора → третий исход."""
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Unmeasured(f"{path}: файл не прочитан ({exc})")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise Unmeasured(f"{path}: не разобран как Python ({exc})")

    funcs = _functions(tree)
    aliases = _aliases(tree)
    canon = _functions(canon_tree) if canon_tree is not None else {}

    # (1) пишет ли — сама (сетевой вызов И эндпоинт в ЛИТЕРАЛЕ) или делегированием:
    #     пере-экспортом имён канонического модуля либо запуском другой двери
    #     подпроцессом.
    has_net = any(c in NET_CALLS for c in _called_names(tree))
    has_endpoint = any(
        isinstance(n, ast.Constant) and isinstance(n.value, str)
        and WRITE_ENDPOINT.search(n.value)
        for n in ast.walk(tree)
    )
    writes_直 = has_net and has_endpoint
    # ТРЕТЬЕ подряд самосовпадение подстроки: условие `"spec_from_file_location" in src`
    # истинно в файле, где написано само это условие. Прибор объявлял делегирующей
    # дверью себя. Спрашиваем AST о ВЫЗОВЕ, а не текст о вхождении.
    loads_module = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"spec_from_file_location", "exec_module"}
        for n in ast.walk(tree)
    )
    delegates = bool(aliases) or loads_module
    spawns = sorted(_spawn_targets(tree, path))
    writes = writes_直 or delegates or bool(spawns)

    # (2) страж на пути записи. Точки входа — main и всё пере-экспортированное,
    #     плюс сами функции двери: CLI может звать любую из них.
    entries = ["main", *aliases.keys(), *funcs.keys()]
    guarded, guard_path = False, []
    for e in entries:
        ok, p = _reaches_guard(e, funcs, canon, aliases, delegates)
        if ok:
            guarded, guard_path = True, p
            break

    return {
        "door": str(path),
        "writes": writes,
        "writes_directly": writes_直,
        "delegates": delegates,
        "guarded": guarded,
        "guard_path": " → ".join(guard_path) if guard_path else None,
        "direct_guard_calls": sum(
            1 for f in funcs.values() for c in _called_names(f) if c in GUARDS
        ),
        "reexported_guard_names": sorted(set(aliases) & GUARDS),
        "spawns": spawns,
    }


# ────────────────────────────── наблюдаемые запускающие ─────────────────────────

def launchers_in_plist(plist: Path, door: Path) -> list[str]:
    """Различение D: читаем ТОЛЬКО ProgramArguments, не комментарии рядом."""
    try:
        with plist.open("rb") as fh:
            data = plistlib.load(fh)
    except Exception as exc:  # noqa: BLE001 — любая неудача разбора = третий исход
        raise Unmeasured(f"{plist}: plist не разобран ({exc})")
    args = data.get("ProgramArguments") or []
    if any(Path(str(a)).name == door.name for a in args):
        return [f"{plist.name}:ProgramArguments"]
    return []


def launchers_in_shell(script: Path, door: Path) -> list[str]:
    """Различение C: дверь считается запущенной только в ПОЗИЦИИ КОМАНДЫ.

    `python3 auto_push.py` — запуск. `--files /abs/auto_push.py` — груз: дверь здесь
    аргумент ЧУЖОГО пушера, и объявить её запущенной значило бы ответить уверенно
    не на тот вопрос.
    """
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Unmeasured(f"{script}: файл не прочитан ({exc})")
    # склеиваем продолжения строк: список --files переносится обратными слэшами
    text = text.replace("\\\n", " ")
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or door.name not in stripped:
            continue
        try:
            toks = shlex.split(stripped, comments=True)
        except ValueError:
            toks = stripped.split()
        for i, tok in enumerate(toks):
            if Path(tok).name != door.name:
                continue
            prev = toks[i - 1] if i else ""
            prev_base = Path(prev).name if prev else ""
            if not (prev_base in INTERPRETERS or prev.startswith("$") or i == 0):
                break  # груз (элемент списка после --files) — НЕ запуск (различение C)
            # Две двери могут носить ОДНО имя (корневой пушер и шим scripts/).
            # Абсолютный токен различает их точно; голое имя — нет, и выдавать
            # догадку за наблюдение здесь нельзя: помечаем неоднозначность.
            tok_path = Path(tok)
            if tok_path.is_absolute():
                if tok_path.resolve() != door.resolve():
                    break
                hits.append(f"{script.name}:{lineno}")
            else:
                hits.append(f"{script.name}:{lineno}?неоднозначно-по-имени")
            break
    return hits


#: Каталоги, которые НЕ являются поверхностью доставки этого репозитория.
#: `.claude/worktrees/` — рабочие копии ЧУЖИХ сессий, часто на давних ревизиях: замер
#: 12.09 нашёл там два plist-а времён до ADR-032, которые зовут `auto_push.py` в
#: `ProgramArguments`. Ни один из них не установлен (`~/Library/LaunchAgents` зовёт
#: `scripts/auto_push.sh`) и ни один не доставляется. Считать их запускающими значит
#: вынести приговор о ДРУГОМ дереве — верный ответ не на тот вопрос.
#: Исключение НАЗЫВАЕТСЯ в выводе числом пропущенных файлов, а не молчит.
_NOT_DELIVERY_SURFACE = (".git", ".claude", "attic", "node_modules", "__pycache__")


def _in_scope(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return not any(p in _NOT_DELIVERY_SURFACE for p in parts)


def find_launchers(root: Path, door: Path) -> tuple[list[str], list[str], int]:
    """Наблюдаемые запускающие двери + названные причины пропуска + число вне охвата."""
    found: list[str] = []
    notes: list[str] = []
    skipped = 0
    for cand in sorted(root.rglob("*.plist")) + sorted(root.rglob("*.sh")):
        if not _in_scope(cand, root):
            skipped += 1
            continue
        probe = launchers_in_plist if cand.suffix == ".plist" else launchers_in_shell
        try:
            for hit in probe(cand, door):
                found.append(f"{cand.relative_to(root)}{hit[hit.rfind(':'):]}")
        except Unmeasured as exc:
            notes.append(str(exc))
    return sorted(set(found)), sorted(set(notes)), skipped


# ────────────────────────────────── перепись ────────────────────────────────────

def census(root: Path) -> dict:
    if not root.is_dir():
        raise Unmeasured(f"каталог не найден: {root}")
    canon_path = root / "push_to_github.py"
    canon_tree = None
    if canon_path.exists():
        try:
            canon_tree = ast.parse(canon_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise Unmeasured(f"канонический модуль не разобран: {exc}")
    else:
        raise Unmeasured(f"канонического модуля нет: {canon_path}")

    doors: list[Path] = []
    for d in (root, root / "scripts"):
        if not d.is_dir():
            continue
        doors += [p for p in sorted(d.glob("*.py")) if DOOR_NAME.search(p.name)]
    if not doors:
        raise Unmeasured(f"дверей-кандидатов не найдено в {root} — перепись пуста "
                         "ПО ПОСТРОЕНИЮ, а это не «дверей нет»")

    rows, notes = [], []
    for door in doors:
        rows.append(inspect_door(door, canon_tree))

    # Страж, стоящий за подпроцессом, закрывает и зовущую дверь: `safe_site_push.py`
    # сам стража не зовёт, но запускает `push_to_github_batch.py`, а тот закрыт.
    # Считаем до неподвижной точки — цепочка может быть длиннее одного звена.
    by_name = {Path(r["door"]).name: r for r in rows}
    changed = True
    while changed:
        changed = False
        for r in rows:
            if r["guarded"]:
                continue
            for target in r["spawns"]:
                tgt = by_name.get(Path(target).name)
                if tgt and tgt["guarded"]:
                    r["guarded"] = True
                    r["guard_path"] = f"подпроцесс → {Path(target).name}: {tgt['guard_path']}"
                    changed = True
                    break

    skipped_total = 0
    for r in rows:
        launchers, ln, skipped = find_launchers(root, Path(r["door"]))
        notes += ln
        skipped_total = max(skipped_total, skipped)
        r["launchers"] = launchers
        r["finding"] = bool(r["writes"] and not r["guarded"] and launchers)
    return {"root": str(root), "doors": rows, "notes": sorted(set(notes)),
            "skipped_outside_delivery_surface": skipped_total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--root", default=".", help="корень репозитория")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)

    try:
        result = census(Path(args.root).resolve())
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"перепись дверей доставки (корень {result['root']}): "
              f"{len(result['doors'])} кандидат(ов)")
        for r in result["doors"]:
            door = Path(r["door"]).relative_to(result["root"])
            if not r["writes"]:
                verdict = "не пишет в origin"
            elif r["guarded"]:
                verdict = f"ЗАКРЫТА стражем ({r['guard_path']})"
            elif r["launchers"]:
                verdict = "🚨 БЕЗ СТРАЖА и ЗАПУСКАЕТСЯ"
            else:
                verdict = "без стража, но запускающих НЕ НАБЛЮДАЕТСЯ (пустой набор — замер)"
            print(f"  {str(door):34s} {verdict}")
            if r["reexported_guard_names"]:
                print(f"       ↳ пере-экспорт (НЕ вызов): {r['reexported_guard_names']}")
            if r["launchers"]:
                shown = r["launchers"][:4]
                more = len(r["launchers"]) - len(shown)
                tail = f" … и ещё {more}" if more > 0 else ""
                print(f"       ↳ запускающих {len(r['launchers'])}: "
                      f"{', '.join(shown)}{tail}  (полный список — `--json`)")
        for n in result["notes"]:
            print(f"  [НЕ ИЗМЕРЕНО] {n}")
        if result["skipped_outside_delivery_surface"]:
            print(f"  [ВНЕ ОХВАТА] пропущено {result['skipped_outside_delivery_surface']} "
                  f"файл(ов) в {', '.join(_NOT_DELIVERY_SURFACE)} — это не поверхность "
                  "доставки ЭТОГО дерева (чужие worktree, карантин, кэш)")

    return 1 if any(r["finding"] for r in result["doors"]) else 0


if __name__ == "__main__":
    sys.exit(main())
