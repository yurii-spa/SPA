#!/usr/bin/env python3
"""КУДА ведёт доказанный `cd` у зовов git в shell-скриптах (ЗАКАЗ #578).

ADR-355 доказал, что `cd` **исполняется**: из 58 зовов git в 185 shell-скриптах
у 48 каталог задан собственным `cd`, и предмет прежнего класса («каталог не
задан ничем») оказался пуст. Но ни разу не был задан второй вопрос — **КУДА
этот `cd` ведёт**. «Каталог задан» и «каталог тот самый» — разные утверждения,
и первое молча выдавалось за второе.

Вопрос заказа дословно: **у скольких из 48 зовов «сам `cd`» каталог доказанно
есть корень ТОГО репозитория, о котором зов говорит?**

## Ловушка названа заказом заранее, и она НЕ та, что была у координат

Соблазн — прочитать умолчание и объявить корень:
`REPO="${SPA_SYNC_REPO:-$HOME/Documents/SPA_Claude}"` выглядит как путь к
прод-дереву, а следующей строкой тот же файл делает `checkout origin/main --
<пути>`. Но значение приходит от ОКРУЖЕНИЯ (launchd `EnvironmentVariables`,
экспорт обёртки, наследование от позвавшего), `$HOME` под launchd и в сессии —
разные вещи, а рядом с прод-деревом на этой же машине живут `.claude/worktrees`
и `/tmp/spa_cNNN` — копии репозитория на СТАРЫХ ревизиях, где тот же `checkout`
означает совсем другое. **«У переменной есть умолчание» НЕ равно «каталог
известен».**

Поэтому прибор ничего не ЧИТАЕТ из умолчания. Он НАБЛЮДАЕТ источник значения
двумя дифференциалами:

1. **дифференциал по ОКРУЖЕНИЮ** — то же выражение считается дважды, в двух
   окружениях, различающихся во всех внешних именах, которые оно поминает.
   Ответ изменился ⇒ значение задаёт окружение ⇒ **НЕ ОПРЕДЕЛЕНО**;
2. **дифференциал по МЕСТУ КОПИИ** — то же выражение считается дважды, из двух
   разных деревьев, куда положена копия скрипта на его настоящем относительном
   пути. Ответ изменился ⇒ значение идёт от места скрипта (`$0`,
   `${BASH_SOURCE[0]}`) ⇒ зов следует за СВОЕЙ копией. Не изменился ⇒ значение
   ПРИКОЛОЧЕНО к фиксированному пути, каким бы деревом его ни запустили.

Только после этих двух наблюдений спрашивается третье: совпал ли полученный
каталог с корнем дерева, в котором живёт исполняемая копия.

## Три исхода, и третий не складывается в первый (инвариант #17)

| исход | что доказано |
|---|---|
| `proven_root` | каталог доказанно есть корень ТОГО дерева, о котором зов |
| `other_tree` | каталог доказанно НЕ он: другое дерево или не корень |
| `undetermined` | значение задаёт окружение — прибор его не знает и не выдумывает |

«Приколочено к прод-дереву» — это НЕ порок сам по себе, а СВОЙСТВО: зов
перестаёт следовать за копией, которая его запустила. Для `rev-parse` это
безразлично, для `reset --hard` / `checkout` / `push` — нет. Поэтому исход
называется фактом, а предметом класса (код 3) объявлен только `undetermined`.

**Вердикт `other_tree` для приколоченного пути — функция того, ОТКУДА спросили.**
Из прод-дерева тот же зов даёт `proven_root`. Это не дефект прибора, а ответ:
у приколоченных зовов «корень-ность» есть свойство КОПИИ, а не кода, и прибор
обязан называть дерево, из которого мерил. Он его называет (`root` в отчёте).

Коды возврата (ADR-347): 0 — предмет пуст · 3 — предмет непуст · 2 — НЕ
ИЗМЕРЕНО с названной причиной. 1 оставлен CPython, чтобы падение прибора
никогда не выглядело его находкой.
"""
from __future__ import annotations

import os
import re
import sys
import json
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shell_git_cwd_census import (                      # noqa: E402
    shell_files, collect_calls, cwd_source, dominating_cd,
    _plist_index, _caller_index, _INVOCATIONS,
)

# Подстановки, которые прибору позволено ИСПОЛНИТЬ, считая выражение.
# Список нужен не для вердикта, а для безопасности: значение `cd`-аргумента
# приходится ВЫЧИСЛЯТЬ, а вычисление `$(...)` есть запуск чужой команды. Всё,
# чего тут нет, даёт третий исход «НЕ ИЗМЕРЕНО» с названной причиной, а не
# догадку и не тихий пропуск.
SAFE_SUBST_HEADS = {"cd", "pwd", "dirname", "basename", "readlink", "realpath",
                    "echo", "printf", "true", ":"}

# Имена, которые bash назначает САМ при запуске скрипта. В дифференциале по
# окружению они не участвуют — и это решение ЗАМЕРЕНО, а не прочитано из
# документации: `env BASH_SOURCE=/hij bash script.sh` на bash 3.2.57 (macOS)
# ПЕРЕБИВАЕТ `${BASH_SOURCE[0]}`, а на bash 5.x — нет. Пусти это свойство в
# главный вердикт — и он станет функцией ХОСТА, ровно та бомба, что описана в
# `.claude/rules/deployment.md` про личность процесса. Поэтому перехват меряется
# ОТДЕЛЬНОЙ пробой и докладывается отдельной строкой с названной версией bash.
SHELL_SET_NAMES = {
    "BASH_SOURCE", "BASH_LINENO", "BASH_ARGV", "BASH_ARGC", "BASH_COMMAND",
    "BASH_SUBSHELL", "BASH_VERSION", "BASH_VERSINFO", "BASH", "BASHPID",
    "FUNCNAME", "LINENO", "PWD", "OLDPWD", "SHLVL", "RANDOM", "SECONDS",
    "PPID", "UID", "EUID", "OPTIND", "IFS", "OSTYPE", "MACHTYPE", "HOSTTYPE",
}

NAME_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
ASSIGN_HEAD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)


# ─────────────────────── СЫРОЙ разбор слов (зачем свой) ───────────────────────

def raw_words(text: str):
    """Слова shell с СОХРАНЁННЫМ исходным текстом.

    Лексер ADR-355 намеренно СТИРАЕТ значение: любая подстановка становится
    `dyn`, потому что тому вопросу («исполнится ли `cd`») значение было не
    нужно. Здесь вопрос ровно про значение, поэтому нужен разбор, который
    кавычки понимает, а текст не теряет.
    """
    out, i, n, line = [], 0, len(text), 1
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            line += text[i + 1] == "\n"
            i += 2
            continue
        if ch in " \t":
            i += 1
            continue
        if ch == "\n":
            out.append(("\n", line, True))
            line += 1
            i += 1
            continue
        if ch == "#" and (not out or out[-1][2]):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith(("&&", "||", ";;"), i):
            out.append((text[i:i + 2], line, True))
            i += 2
            continue
        if ch in ";&|()<>":
            out.append((ch, line, True))
            i += 1
            continue
        start, start_line = i, line
        while i < n and text[i] not in " \t\n;&|()<>":
            c = text[i]
            if c == "\\" and i + 1 < n:
                if text[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if c == "'":
                i += 1
                while i < n and text[i] != "'":
                    line += text[i] == "\n"
                    i += 1
                i += 1
                continue
            if c == '"':
                i += 1
                depth = 0
                while i < n:
                    if text[i] == "\\":
                        i += 2
                        continue
                    if text[i] == '"' and depth == 0:
                        break
                    if text.startswith("$(", i):
                        depth += 1
                        i += 2
                        continue
                    if text[i] == ")" and depth:
                        depth -= 1
                    line += text[i] == "\n"
                    i += 1
                i += 1
                continue
            if text.startswith("$(", i):
                depth, i = 1, i + 2
                while i < n and depth:
                    if text[i] == "\\":
                        i += 2
                        continue
                    if text[i] == "'":
                        i += 1
                        while i < n and text[i] != "'":
                            i += 1
                    elif text.startswith("$(", i):
                        depth += 1
                        i += 1
                    elif text[i] == ")":
                        depth -= 1
                    line += text[i] == "\n" if i < n else 0
                    i += 1
                continue
            i += 1
        out.append((text[start:i], start_line, False))
    return out


def cd_argument(text: str, line: int):
    """Сырой текст аргумента `cd` на названной строке.

    Возвращает (аргумент, None) либо (None, причина-НЕ-ИЗМЕРЕНО)."""
    words = raw_words(text)
    for k, (w, ln, is_op) in enumerate(words):
        if is_op or ln != line or w not in ("cd", "pushd"):
            continue
        for w2, _ln2, op2 in words[k + 1:]:
            if op2:
                break
            if w2.startswith("-"):        # `cd -P`, `cd --`
                continue
            return w2, None
        return None, f"строка {line}: у `cd` нет аргумента (возврат в $HOME)"
    return None, f"строка {line}: `cd` не найден сырым разбором"


def assignments(text: str):
    """имя → (сырой RHS, строка). Последнее присваивание в файле побеждает."""
    out: dict[str, tuple[str, int]] = {}
    for w, ln, is_op in raw_words(text):
        if is_op:
            continue
        m = ASSIGN_HEAD_RE.match(w)
        if m and not m.group(1) in ("if", "then"):
            out[m.group(1)] = (m.group(2), ln)
    return out


def referenced(expr: str):
    return set(NAME_RE.findall(expr))


def resolve_chain(expr: str, assigns: dict, before_line: int):
    """Присваивания, от которых выражение зависит, — до неподвижной точки.

    Берутся ТОЛЬКО имена, участвующие в выражении, и рекурсивно их собственные
    зависимости. Тянуть весь пролог файла было бы и неточно (посторонние
    присваивания к вопросу не относятся), и опасно (их подстановки пришлось бы
    исполнить)."""
    need, seen, chain = set(referenced(expr)), set(), []
    while need:
        name = need.pop()
        if name in seen:
            continue
        seen.add(name)
        got = assigns.get(name)
        if not got or got[1] >= before_line:
            continue                       # внешнее имя: решает окружение
        rhs, ln = got
        chain.append((name, rhs, ln))
        need |= referenced(rhs)
    chain.sort(key=lambda t: t[2])
    external = {n for n in seen
                if n not in assigns or assigns[n][1] >= before_line}
    ambient = {n for n in external if n not in SHELL_SET_NAMES}
    return chain, ambient, external & SHELL_SET_NAMES


SUBST_HEAD_RE = re.compile(r"\$\(\s*([^\s()]+)")


def unsafe_substitutions(pieces):
    """Головы командных подстановок, которых нет в белом списке."""
    bad = set()
    for p in pieces:
        for head in SUBST_HEAD_RE.findall(p):
            if head.strip('"\'') not in SAFE_SUBST_HEADS:
                bad.add(head)
        if "`" in p:
            bad.add("`…` (обратные кавычки)")
    return bad


# ─────────────────────────────── наблюдение ───────────────────────────────

def _git(args, cwd=None):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                          text=True, timeout=60)


def make_tree(path: Path, script_rel: str, body: str):
    """Одноразовое дерево-репозиторий с копией скрипта на его НАСТОЯЩЕМ пути.

    Относительный путь важен: `$(dirname "$0")/..` даёт корень только если
    скрипт лежит в подкаталоге первого уровня, и прибор обязан узнать это
    наблюдением, а не подсчётом `..` в тексте."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], cwd=path)
    probe = path / script_rel
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(body, encoding="utf-8")
    probe.chmod(0o755)
    return probe


def probe_value(probe: Path, env: dict, scratch: Path):
    """Значение `cd`-аргумента, как его увидит bash. (значение, None) | (None, причина)."""
    try:
        r = subprocess.run(["bash", "--noprofile", "--norc", str(probe)],
                           cwd=str(scratch), env=env, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"bash не запущен: {exc}"
    if r.returncode != 0:
        return None, f"проба вернула код {r.returncode}: {r.stderr.strip()[:160]}"
    return r.stdout, None


def _env(home: Path, externals, filler):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": str(home), "LANG": "C", "SHELL": "/bin/bash"}
    if filler is not None:
        for name in externals:
            if name not in ("HOME",):
                env[name] = f"{filler}/{name}"
    return env


def bash_version():
    r = subprocess.run(["bash", "--version"], capture_output=True, text=True)
    return (r.stdout.splitlines() or [""])[0].strip()


def observe(call, cd_arg, chain, ambient, shell_set, workdir: Path):
    """Два дифференциала и проверка корня. Возвращает (исход, подробности)."""
    script_rel = call["file"]
    body = "#!/bin/bash\n" + "".join(f"{n}={rhs}\n" for n, rhs, _ in chain) \
           + f"printf '%s' {cd_arg}\n"

    treeA = workdir / "A" / "tree"
    treeB = workdir / "B" / "another" / "deeper" / "tree"
    scratch = workdir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    probeA = make_tree(treeA, script_rel, body)
    probeB = make_tree(treeB, script_rel, body)

    homeA, homeB = workdir / "homeA", workdir / "homeB"
    for h in (homeA, homeB):
        h.mkdir(parents=True, exist_ok=True)

    # 1. дифференциал по ОКРУЖЕНИЮ (дерево одно, окружения два)
    v_env1, err = probe_value(probeA, _env(homeA, ambient, None), scratch)
    if err:
        return "unmeasured", {"why": f"{script_rel}: {err}"}
    v_env2, err = probe_value(probeA, _env(homeB, ambient, str(workdir / "ext")),
                              scratch)
    if err:
        return "unmeasured", {"why": f"{script_rel}: {err}"}
    if v_env1 != v_env2:
        return "undetermined", {
            "why": ("значение задаёт ОКРУЖЕНИЕ: два окружения дали разные "
                    f"каталоги ({v_env1!r} ≠ {v_env2!r})"),
            "ambient": sorted(ambient), "value": None}

    # 1б. ОТДЕЛЬНАЯ проба: перебиваются ли имена, которые bash ставит сам.
    # В главный вердикт не идёт (свойство хоста, см. SHELL_SET_NAMES) — но
    # молчать о ней нельзя: `secure_git_push.sh` выводит корень из
    # `${BASH_SOURCE[0]}` и делает `git push`.
    hijack = None
    if shell_set:
        v_hi, herr = probe_value(
            probeA, _env(homeA, shell_set, str(workdir / "hij")), scratch)
        hijack = {"names": sorted(shell_set), "bash": bash_version(),
                  "taken": (herr is not None or v_hi != v_env1)}

    # 2. дифференциал по МЕСТУ КОПИИ (окружение одно, деревья два)
    v_locB, err = probe_value(probeB, _env(homeA, ambient, None), scratch)
    if err:
        return "unmeasured", {"why": f"{script_rel}: {err}"}

    follows_copy = v_env1 != v_locB
    rootA, rootB = str(treeA.resolve()), str(treeB.resolve())
    if follows_copy:
        okA = Path(v_env1).resolve() == treeA.resolve()
        okB = Path(v_locB).resolve() == treeB.resolve()
        if okA and okB:
            return "proven_root", {
                "why": ("каталог идёт от МЕСТА скрипта и в обоих деревьях "
                        "совпал с их корнем"),
                "pinned": False, "value": None, "hijack": hijack}
        rel = os.path.relpath(v_env1, rootA)
        return "other_tree", {
            "why": ("каталог идёт от места скрипта, но корнем НЕ является: "
                    f"в дереве-пробе он {rel!r} от корня"),
            "pinned": False, "value": None, "hijack": hijack}

    if not v_env1.strip():
        return "unmeasured", {
            "why": (f"{script_rel}: `cd`-аргумент раскрылся в ПУСТО — пустая строка "
                    "означала бы «текущий каталог», а он тут и есть вопрос")}
    return "pinned", {"why": "каталог ПРИКОЛОЧЕН: не зависит ни от окружения, "
                             "ни от того, какая копия запущена",
                      "pinned": True, "value": v_env1, "hijack": hijack}


def target_is_repo_root(path: str):
    """Наблюдение о приколоченном пути: он вообще корень репозитория?

    Три исхода и здесь: да · нет · не измерено (пути нет на ЭТОЙ машине —
    это не «нет», скрипт может исполняться там, где он есть)."""
    p = Path(path)
    if not p.is_dir():
        return "unmeasured", f"каталога {path!r} нет на этой машине"
    r = _git(["rev-parse", "--show-toplevel"], cwd=str(p))
    if r.returncode != 0:
        return "no", f"{path!r} не рабочая копия git"
    top = Path(r.stdout.strip())
    if top.resolve() == p.resolve():
        return "yes", f"{path!r} — корень рабочей копии"
    return "no", f"{path!r} лежит внутри {str(top)!r}, но корнем не является"


# ─────────────────────────────── перепись ───────────────────────────────

def census(repo_root: Path):
    repo_root = repo_root.resolve()
    r = _git(["rev-parse", "--show-toplevel"], cwd=str(repo_root))
    if r.returncode != 0 or Path(r.stdout.strip()).resolve() != repo_root:
        return {"unmeasured_fatal": (
            f"--root {str(repo_root)!r} не есть корень рабочей копии git: "
            "вопрос «тот ли это корень» без корня не имеет смысла")}

    files = shell_files(repo_root)
    plists, _ = _plist_index([repo_root / "launchd", repo_root / "scripts",
                              Path.home() / "Library" / "LaunchAgents"])
    callers, _ = _caller_index(repo_root, files)

    rows, unmeasured = [], []
    texts: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="cdtarget-") as td:
        work = Path(td)
        cache: dict[tuple, tuple] = {}
        for p in files:
            calls, cds, err = collect_calls(p, repo_root)
            if err:
                unmeasured.append(err)
                continue
            rel = str(p.relative_to(repo_root))
            invs = _INVOCATIONS.get(rel, [])
            text = texts.setdefault(rel, p.read_text(encoding="utf-8"))
            for call in calls:
                src, _why = cwd_source(call, cds, plists, callers, invs)
                if src != "self":
                    continue
                cd, _ = dominating_cd(cds, call, invs)
                key = (rel, cd["line"])
                if key not in cache:
                    cache[key] = _classify_cd(rel, text, cd, work, len(cache))
                verdict, detail = cache[key]
                rows.append({"file": rel, "line": call["line"],
                             "cd_line": cd["line"], "verdict": verdict,
                             "detail": detail,
                             "call": " ".join(call["argv"])[:70]})
    for row in rows:
        if row["verdict"] == "pinned":
            value = row["detail"]["value"]
            same = Path(value).resolve() == repo_root if value else False
            row["verdict"] = "proven_root" if same else "other_tree"
            row["detail"] = {**row["detail"], "same_tree": same}
    return {"root": str(repo_root), "files": len(files), "rows": rows,
            "unread": unmeasured}


def _classify_cd(rel, text, cd, work, seq):
    cd_arg, err = cd_argument(text, cd["line"])
    if err:
        return "unmeasured", {"why": f"{rel}: {err}"}
    assigns = assignments(text)
    chain, ambient, shell_set = resolve_chain(cd_arg, assigns, cd["line"])
    bad = unsafe_substitutions([cd_arg] + [rhs for _n, rhs, _l in chain])
    if bad:
        return "unmeasured", {
            "why": (f"{rel}:{cd['line']}: подстановка вне белого списка "
                    f"({', '.join(sorted(bad))}) — исполнять чужую команду "
                    "ради замера прибор не станет")}
    return observe({"file": rel}, cd_arg, chain, ambient, shell_set,
                   work / f"c{seq}")


# ─────────────────────────────── отчёт ───────────────────────────────

ORDER = ["proven_root", "other_tree", "undetermined", "unmeasured"]
TITLE = {"proven_root": "ДОКАЗАННЫЙ КОРЕНЬ того дерева, о котором зов",
         "other_tree": "доказанно ДРУГОЕ дерево / не корень",
         "undetermined": "НЕ ОПРЕДЕЛЕНО (значение задаёт окружение)",
         "unmeasured": "НЕ ИЗМЕРЕНО"}


def subject_keys(rows):
    return sorted({f"{r['file']}:{r['line']}" for r in rows
                   if r["verdict"] == "undetermined"})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", default=None,
                    help="храповик: предмет обязан быть ПОДМНОЖЕСТВОМ базы; "
                         "база может только уменьшаться, дописывать запрещено")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    res = census(root)
    if "unmeasured_fatal" in res:
        print(f"⛔ НЕ ИЗМЕРЕНО: {res['unmeasured_fatal']}")
        return 2

    rows, groups = res["rows"], {}
    for r in rows:
        groups.setdefault(r["verdict"], []).append(r)
    subject = subject_keys(rows)
    unmeasured = groups.get("unmeasured", []) + [{"detail": {"why": u}}
                                                 for u in res["unread"]]

    if args.json:
        print(json.dumps({"root": res["root"], "files": res["files"],
                          "calls": len(rows),
                          "by_verdict": {k: len(groups.get(k, []))
                                         for k in ORDER},
                          "subject": subject,
                          "unmeasured": [u["detail"]["why"] for u in unmeasured]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"КУДА ведёт доказанный `cd` — {len(rows)} зовов «сам cd» "
              f"в {res['files']} shell-скриптах")
        print(f"мерено ИЗ дерева: {res['root']}")
        print("  (у приколоченных зовов «корень-ность» есть свойство КОПИИ: "
              "из другого дерева тот же зов даст другой исход)")
        for k in ORDER:
            got = groups.get(k, [])
            print(f"\n── {TITLE[k]}: {len(got)}")
            for r in sorted(got, key=lambda x: (x["file"], x["line"])):
                print(f"   · {r['file']}:{r['line']}  (cd строкой "
                      f"{r['cd_line']})  {r['call']}")
                print(f"     {r['detail']['why']}")
                hij = r["detail"].get("hijack")
                if hij and hij["taken"]:
                    print(f"     ⚠️  значение ПЕРЕБИВАЕТСЯ экспортом "
                          f"{', '.join(hij['names'])} на этом хосте ({hij['bash']}); "
                          "в главный вердикт не идёт — свойство хоста, не кода")
                if r["detail"].get("pinned"):
                    state, why = target_is_repo_root(r["detail"]["value"])
                    print(f"     цель: {r['detail']['value']} — корень? "
                          f"{state} ({why})")
        for u in [x for x in unmeasured if "file" not in x]:
            print(f"   · {u['detail']['why']}")

    def say(msg):
        if not args.json:
            print(msg)

    if unmeasured:
        say(f"\n⛔ НЕ ИЗМЕРЕНО: {len(unmeasured)} — код 2 "
            "(«не измерено» не выдаётся за «чисто»)")
        return 2

    if args.baseline:
        try:
            base = set(json.loads(Path(args.baseline).read_text("utf-8"))["undetermined"])
        except (OSError, ValueError, KeyError) as exc:
            say(f"\n⛔ НЕ ИЗМЕРЕНО: база {args.baseline} не прочитана: {exc}")
            return 2
        new = [k for k in subject if k not in base]
        if new:
            say(f"\n🔴 НОВЫЕ зовы с неопределённым каталогом ({len(new)}): "
                f"{', '.join(new)}")
            say("   база может только УМЕНЬШАТЬСЯ; дописывать в неё запрещено")
            return 3
        gone = sorted(base - set(subject))
        say(f"\n✅ предмет ⊆ база ({len(subject)}/{len(base)})"
            + (f"; вышли из класса: {', '.join(gone)}" if gone else ""))
        return 0

    if subject:
        say(f"\n🔴 НЕ ОПРЕДЕЛЕНО у {len(subject)} зовов — код 3")
        return 3
    say("\n✅ предмет пуст")
    return 0


if __name__ == "__main__":
    sys.exit(main())
