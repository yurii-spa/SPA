#!/usr/bin/env python3
"""Перепись зовов git по СИСТЕМЕ КООРДИНАТ пути (заказ цикла #574, ADR-353).

`git` разбирает путь ДВУМЯ разными способами внутри одного и того же репозитория:

* `<ref>:<путь>` (`cat-file blob HEAD:docs/STATE.md`, `show`, `rev-parse`, `ls-tree`)
  — **ОТ КОРНЯ рабочей копии**, каталог запуска не важен;
* pathspec (`rev-list HEAD -- docs/STATE.md`, `log`, `ls-files`, `diff`, `grep`)
  — **ОТ ТЕКУЩЕГО КАТАЛОГА**.

#574 нашёл это на живом стороже: `push_base_provenance` звался из каталога ФАЙЛА,
база (`HEAD:<путь>`) читалась верно, а перечисление предков (`rev-list -- <путь>`)
молча спрашивало про `docs/docs/STATE.md` и возвращало ПУСТО. Ноль предков
складывался в «ни один предок этого не объясняет» — «не посмотрели», выданное за
«посмотрели и не нашли». Оба настоящих обвала, ради которых прибор написан, лежат в
подкаталогах, то есть в доставленном виде он не остановил бы ни одного.

Вопрос заказа: **сколько ещё мест в наборе зовут git с путём, и у скольких из них
выбранный каталог запуска делает этот путь неверным?**

Ловушка названа заказом заранее: соблазн — грепнуть `git` и объявить долю. Это
ПРИЗНАК, а не замер, и он ошибается в обе стороны — путь бывает абсолютным, зов
бывает с `-C`, путь приходит переменной, которая уже абсолютна; и обратно, `cwd=`
в одном месте не означает, что там КОРЕНЬ. Поэтому прибор устроен так:

1. **Население** берётся AST, а не регуляркой: зов считается зовом git только если
   argv действительно начинается с `git` (список литералов) — присваивание, строка
   в докстринге и слово в комментарии населением не являются.
2. **Чувствительность формы устанавливается НАБЛЮДЕНИЕМ**, а не знанием автора о
   git: каждая форма (`rev-list -- <путь>`, `cat-file blob HEAD:<путь>`, …)
   реально прогоняется в одноразовом репозитории ИЗ ДВУХ каталогов одной рабочей
   копии, и сравнивается ОТВЕТ. «Путь передан как pathspec» НЕ равно «зов слеп» —
   слеп тот, у кого ответ МЕНЯЕТСЯ от каталога запуска, и это сказано наблюдением.
3. **Третий исход** (`НЕ ИЗМЕРЕНО` с названной причиной) обязателен везде, где
   argv не сложился статически, форму не удалось прогнать или каталог не назван.
   Ни один такой случай не выдаётся ни за «слеп», ни за «верно» (инв. #17).

Коды возврата (конвенция ADR-347 — единицу не занимать, её выдаёт CPython при
любом необработанном исключении, и тогда крах прибора неотличим от его находки):

    0 — измерено, слепых зовов и отпечатков #574 нет
    1 — (не наш) прибор упал, вердикта нет
    2 — НЕ ИЗМЕРЕНО: замер не состоялся вовсе
    3 — НАХОДКА: слепые зовы и/или отпечаток #574
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import shutil
import tempfile
import warnings
from pathlib import Path

EXIT_CLEAN = 0
EXIT_UNMEASURED = 2
EXIT_FINDING = 3

# Функции, чей первый позиционный аргумент — argv.
RUNNERS = {"run", "check_output", "check_call", "call", "Popen"}

# Подкоманды, у которых позиционный путь (или путь после `--`) — ПATHSPEC,
# то есть читается от текущего каталога.
PATHSPEC_SUBCOMMANDS = {
    "log", "rev-list", "ls-files", "diff", "diff-files", "diff-index",
    "status", "add", "checkout", "restore", "rm", "grep", "blame", "stash",
    "show", "commit", "clean", "shortlog",
}

# Подкоманды, умеющие форму `<ref>:<путь>` — она читается ОТ КОРНЯ.
REV_PATH_SUBCOMMANDS = {"cat-file", "show", "rev-parse", "ls-tree", "diff", "diff-tree"}

DYNAMIC = "\x00dyn"          # элемент argv, не сложившийся статически
PATH_PLACEHOLDER = "P.txt"   # чем подменяется путь при прогоне формы


# ─────────────────────────── разбор населения ───────────────────────────

def _literal(node):
    """Литерал элемента argv, либо DYNAMIC. f-строка со статическим хвостом
    сохраняется как шаблон — именно в ней живёт форма `HEAD:{repo_path}`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                out.append(DYNAMIC)
            else:
                return DYNAMIC
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if DYNAMIC in (left, right):
            return DYNAMIC
        return left + right
    return DYNAMIC


def _argv_of(node):
    """argv зова, если он статически похож на список/конкатенацию списков."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(e) for e in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _argv_of(node.left), _argv_of(node.right)
        if left is None or right is None:
            return None
        return left + right
    return None


def _expr_src(node, src_lines):
    """Исходный текст выражения — им опознаётся «тот же путь» в отпечатке."""
    try:
        return ast.get_source_segment("\n".join(src_lines), node) or DYNAMIC
    except Exception:
        return DYNAMIC


def _path_expr_of(node):
    """Для элемента argv — выражение, из которого взят путь (для f-строк — то,
    что подставлено). Нужно, чтобы отпечаток #574 узнавал ОДИН И ТОТ ЖЕ путь в
    двух системах координат, а не два разных пути рядом."""
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                return part.value
    return node


def _enclosing_scope(tree):
    """Карта узел → имя объемлющей функции (для отпечатка «в одном скоупе»)."""
    scope = {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
            else:
                scope[child] = name
                walk(child, name)
        scope[node] = name

    walk(tree, "<module>")
    return scope


def _git_helpers(tree):
    """Функции-ДВЕРИ: тело зовёт `subprocess.run(["git"] + <параметр>, cwd=<параметр>)`.

    Без этого шага прибор слеп ровно там, ради чего написан. `push_base_provenance`
    — та самая авария #574 — весь git зовёт через `_git_bytes(args, cwd)`, и в самом
    зове argv это `["git"] + args`, то есть НЕ СЛОЖИЛСЯ. Прибор, считающий такой зов
    «НЕ ИЗМЕРЕНО», честно молчит про население и при этом НЕ МОЖЕТ найти аварию, по
    следам которой он заказан: его положительный контроль был бы украшением
    (замер #575 до починки: 57 зовов из 117 — это двери, а не зовы).

    Возвращает {имя: {"argv_param": i|имя, "cwd_param": i|имя|None}}.
    """
    helpers = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
        if not params:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call) or not inner.args:
                continue
            fn = inner.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else None)
            if fname not in RUNNERS:
                continue
            argv_param = _argv_param_of(inner.args[0], params)
            if argv_param is None:
                continue
            cwd_param = None
            for kw in inner.keywords:
                if kw.arg == "cwd":
                    cwd_param = _param_name_in(kw.value, params)
            helpers[node.name] = {"argv_param": argv_param, "cwd_param": cwd_param,
                                  "params": params}
            break
    return helpers


def _param_name_in(node, params):
    """Имя параметра, из которого выражение происходит (`p`, `str(p)`, `Path(p)`)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in params:
            return sub.id
    return None


def _argv_param_of(node, params):
    """`["git"] + <параметр>` или `["git", *<параметр>]` → имя параметра."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _argv_of(node.left)
        if left == ["git"]:
            return _param_name_in(node.right, params)
        return None
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        first = _literal(node.elts[0])
        if first == "git" and len(node.elts) == 2 and isinstance(node.elts[1], ast.Starred):
            return _param_name_in(node.elts[1].value, params)
    return None


def _bind_arg(call, params, wanted):
    """Аргумент зова, привязанный к параметру `wanted` (позицией или именем)."""
    if wanted is None:
        return None
    for kw in call.keywords:
        if kw.arg == wanted:
            return kw.value
    try:
        idx = params.index(wanted)
    except ValueError:
        return None
    return call.args[idx] if idx < len(call.args) else None


def _root_proven_names(scope_node, helpers, src_lines):
    """Имена, чьё значение ПРОИСХОДИТ от `git rev-parse --show-toplevel`.

    Заменяет собой прежнюю догадку по ИМЕНИ переменной (`root`, `repo`, …).
    Догадка по имени ошибается в обе стороны, и обе стороны наблюдались тут же:
    `cwd=work` в `test_push_base_provenance` — настоящий корень временной копии,
    и прибор объявил четыре зова слепыми (ложная тревога), а любая переменная,
    названная `repo_path`, прошла бы за корень, им не будучи.

    Корень — это не имя, а ПРОВЕНАНС: значение, полученное от самого git ответом
    на вопрос «где корень». Всё остальное — не «наверное корень», а НЕ ДОКАЗАНО,
    и это третий исход, а не оправдание."""
    proven = set()
    assigns = []
    for node in ast.walk(scope_node):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets:
                assigns.append((targets, node.value))
    for _ in range(6):                      # до неподвижной точки
        grew = False
        for targets, value in assigns:
            if all(t in proven for t in targets):
                continue
            src = _expr_src(value, src_lines)
            asks_root = any(marker in src for marker in
                            ("--show-toplevel", "--show-cdup", "--git-common-dir"))
            from_proven = any(isinstance(n, ast.Name) and n.id in proven
                              for n in ast.walk(value))
            if asks_root or from_proven:
                proven.update(targets)
                grew = True
        if not grew:
            break
    return proven


def collect_sites(py_path: Path, repo_root: Path):
    """Все зовы git в одном файле — ПРЯМЫЕ и через дверь-помощник внутри модуля.

    Возвращает (сайты, причина-НЕ-ИЗМЕРЕНО|None)."""
    try:
        text = py_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"{py_path} не прочитан: {exc}"
    try:
        with warnings.catch_warnings():
            # Предупреждения ЧУЖОГО файла — не наш вердикт и не наш шум.
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"{py_path} не разобран AST: {exc}"

    src_lines = text.split("\n")
    scopes = _enclosing_scope(tree)
    helpers = _git_helpers(tree)
    sites = []

    proven_by_scope = {"<module>": _root_proven_names(tree, helpers, src_lines)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            proven_by_scope[node.name] = (
                _root_proven_names(node, helpers, src_lines)
                | proven_by_scope["<module>"])

    def add(node, argv, cwd_expr, elt_nodes, via):
        sites.append({
            "root_proven": proven_by_scope.get(scopes.get(node, "<module>"), set()),
            "file": str(py_path.relative_to(repo_root)),
            "line": node.lineno,
            "scope": scopes.get(node, "<module>"),
            "argv": argv,
            "cwd": cwd_expr,
            "via": via,
            "path_exprs": [_expr_src(_path_expr_of(e), src_lines) for e in elt_nodes],
        })

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)

        if fname in RUNNERS:
            argv = _argv_of(node.args[0])
            if argv is None or not argv or argv[0] != "git":
                continue
            # Зов ВНУТРИ опознанной двери — это сама дверь, а не зов через неё.
            # Считать его населением значит записать один и тот же git дважды:
            # один раз у каждого вызывающего (с настоящим argv) и ещё раз здесь,
            # где argv по построению не сложится никогда. Замер #575: таких
            # призраков было 68 из 159, и все они лежали в «НЕ ИЗМЕРЕНО».
            if scopes.get(node) in helpers and DYNAMIC in argv:
                continue
            cwd_expr = None
            for kw in node.keywords:
                if kw.arg == "cwd":
                    cwd_expr = _expr_src(kw.value, src_lines)
            elts = node.args[0].elts if isinstance(node.args[0], (ast.List, ast.Tuple)) else []
            add(node, argv, cwd_expr, elts, via=None)
            continue

        spec = helpers.get(fname)
        if spec is None:
            continue
        argv_node = _bind_arg(node, spec["params"], spec["argv_param"])
        tail = _argv_of(argv_node) if argv_node is not None else None
        if tail is None:
            continue                      # дверь позвали динамическим списком
        cwd_node = _bind_arg(node, spec["params"], spec["cwd_param"])
        cwd_expr = _expr_src(cwd_node, src_lines) if cwd_node is not None else None
        elts = ([ast.Constant(value="git")] +
                list(argv_node.elts if isinstance(argv_node, (ast.List, ast.Tuple)) else []))
        add(node, ["git"] + tail, cwd_expr, elts, via=fname)

    return sites, None


# ─────────────────────── классификация роли пути ───────────────────────

# Опции git, ЗАБИРАЮЩИЕ следующий аргумент. Без этого списка `git -c user.email=x
# commit` объявляет подкоманду `user.email=x`: 11 зовов набора уезжали в
# «НЕ ИЗМЕРЕНО» по дефекту разбора, а не по природе зова (замер #575).
OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                   "--exec-path", "--super-prefix",
                   # …и опции подкоманд, забирающие следующий аргумент. Без них
                   # значение `-L 12,12` у `git blame` становится «путём»
                   # (подкоманда `blame` читает голый позиционный как путь), и
                   # прибор называет переменной строки переменной ПУТИ.
                   "-L", "-S", "-G", "-n", "-o", "--since", "--until",
                   "--author", "--grep", "--pretty", "--format", "--max-count"}


def _subcommand(argv):
    skip_next = False
    for token in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if token == DYNAMIC:
            continue
        if token in OPTS_WITH_VALUE:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return token
    return None


# Подкоманды, у которых ГОЛЫЙ позиционный аргумент (до `--`) — уже путь.
# У `log`/`rev-list`/`diff`/`show` голый позиционный — РЕВИЗИЯ, а не путь:
# считать `origin/main` путём (в нём есть «/») значит изготовить находку из
# ничего. Путь у них появляется только после `--`.
BARE_PATH_SUBCOMMANDS = {"ls-files", "add", "rm", "restore", "clean",
                         "check-ignore", "status", "blame", "hash-object"}


def classify(site):
    """Роли аргументов: что git читает ОТ КОРНЯ, что ОТ КАТАЛОГА ЗАПУСКА.

    Используется для ОТПЕЧАТКА #574 и для оправданий (`-C`, абсолютный путь).
    Вердикт «слеп» на этом НЕ строится — его выносит наблюдение."""
    argv, sub = site["argv"], _subcommand(site["argv"])
    root_rel, pathspec = [], []
    abs_paths, dyn_paths = [], []
    after_ddash = False
    skip_next = False

    has_dash_c = "-C" in argv

    def expr_at(idx):
        return site["path_exprs"][idx] if idx < len(site["path_exprs"]) else DYNAMIC

    for idx, token in enumerate(argv[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            after_ddash = True
            continue
        if token in OPTS_WITH_VALUE:
            skip_next = True
            continue
        if token == DYNAMIC:
            if after_ddash or sub in BARE_PATH_SUBCOMMANDS:
                dyn_paths.append(idx)
                pathspec.append({"idx": idx, "token": token, "expr": expr_at(idx)})
            continue
        if token.startswith("-"):
            continue
        if token == sub and idx == argv.index(sub):
            continue

        # форма `<ревизия>:<путь>` — читается ОТ КОРНЯ рабочей копии
        if ":" in token and sub in REV_PATH_SUBCOMMANDS:
            ref, _, tail = token.partition(":")
            if tail and ref and not tail.startswith("/"):
                root_rel.append({"idx": idx, "token": token, "expr": expr_at(idx)})
                continue

        if after_ddash or sub in BARE_PATH_SUBCOMMANDS:
            if token.startswith("/"):
                abs_paths.append(idx)
                continue
            if DYNAMIC in token:
                dyn_paths.append(idx)
            pathspec.append({"idx": idx, "token": token, "expr": expr_at(idx)})

    dyn_expr = None
    for item in pathspec:
        if item["idx"] in dyn_paths:
            dyn_expr = item["expr"]
            break
    return {"subcommand": sub, "root_relative": root_rel, "pathspec": pathspec,
            "dash_c": has_dash_c, "dynamic_path": dyn_expr,
            "absolute_only": bool(abs_paths) and not pathspec}


# ───────────────── наблюдение: меняется ли ответ от каталога ─────────────────

# Сетевые подкоманды не прогоняем НИКОГДА: прибор не выходит в сеть, и «упало
# одинаково из двух каталогов» было бы вердиктом про отсутствие сети, а не про
# координаты. Третий исход с названной причиной, не «устойчив».
NETWORK_SUBCOMMANDS = {"fetch", "push", "pull", "clone", "remote", "submodule",
                       "ls-remote", "archive"}


def build_probe_repo(tmp: Path):
    """Эталонная рабочая копия, с которой перед КАЖДЫМ прогоном снимается копия.

    Геометрия — ровно геометрия аварии #574: `P.txt` есть В КОРНЕ и НЕТ в `sub/`,
    поэтому pathspec, прочитанный из подкаталога, указывает в пустоту, и git
    отвечает ПУСТОТОЙ, а не ошибкой. Пустота потом и складывается в «посмотрели
    и не нашли». Рядом лежит `sub/other.txt` и незакоммиченная правка — иначе
    подкоманды, чей ответ зависит от состояния дерева, отвечали бы пустотой по
    построению, и «не меняется» было бы свойством песочницы, а не зова."""
    env = dict(os.environ,
               GIT_AUTHOR_NAME="probe", GIT_AUTHOR_EMAIL="p@probe",
               GIT_COMMITTER_NAME="probe", GIT_COMMITTER_EMAIL="p@probe",
               GIT_CONFIG_GLOBAL=str(tmp / "gitconfig-none"),
               GIT_CONFIG_SYSTEM=str(tmp / "gitconfig-none"),
               GIT_TERMINAL_PROMPT="0",
               # Без этих трёх зов, которому не хватило аргумента, открывает
               # редактор или пейджер и ЖДЁТ — прибор выглядит зависшим, а не
               # медленным. Замер #575: первый прогон с подменой не завершился.
               GIT_EDITOR="true", GIT_PAGER="cat", PAGER="cat")
    def run(*a):
        subprocess.run(["git"] + list(a), cwd=str(tmp), env=env,
                       capture_output=True, check=True)
    run("init", "-q", "-b", "main")
    (tmp / "sub").mkdir()
    (tmp / PATH_PLACEHOLDER).write_text("root line 1\n")
    (tmp / "sub" / "other.txt").write_text("sub file\n")
    run("add", "-A")
    run("commit", "-qm", "c1")
    (tmp / PATH_PLACEHOLDER).write_text("root line 1\nroot line 2\n")
    run("add", "-A")
    run("commit", "-qm", "c2")
    (tmp / PATH_PLACEHOLDER).write_text("root line 1\nroot line 2\nuncommitted\n")
    return env


def _concrete_argv(argv, roles=None):
    """argv, пригодный для прогона в песочнице.

    Два правила, и оба выстраданы замером #575:

    * динамический элемент НЕ выбрасывается, а становится плейсхолдером —
      выброс превратил бы `rev-list HEAD -- <путь>` в `rev-list HEAD --`, то
      есть в зов БЕЗ пути, и прибор объявил бы устойчивым ровно тот зов, ради
      которого написан;
    * ЛИТЕРАЛЬНЫЙ pathspec тоже заменяется плейсхолдером. Прибор мерит ФОРМУ, а
      настоящего `landing/` в песочнице нет: `git diff … -- landing/` отвечал
      пустотой из обоих каталогов, и «ответ не меняется» было свойством
      песочницы, а не зова. Плейсхолдер существует в корне и отсутствует в
      `sub/` — ровно геометрия аварии."""
    spec_idx = {item["idx"] for item in (roles or {}).get("pathspec", [])}
    out = []
    for idx, token in enumerate(argv):
        if idx in spec_idx:
            out.append(PATH_PLACEHOLDER)
        elif token == DYNAMIC:
            out.append(PATH_PLACEHOLDER)
        elif DYNAMIC in token:
            out.append(token.replace(DYNAMIC, PATH_PLACEHOLDER))
        else:
            out.append(token)
    return out


NUMERIC_OPTS = ("--max-count=", "--depth=", "--unified=", "-n=")


def _neutralise(argv, roles, work: Path):
    """Второй заход: подменить всё, что мешает форме ИСПОЛНИТЬСЯ, кроме пути.

    Первый заход гонит argv как есть. Но настоящая ревизия (`origin/main`,
    переменная-sha) в одноразовой песочнице не разрешается, и git выходит со
    128 из ОБОИХ каталогов. Совпадение двух отказов — не «ответ не меняется», а
    отсутствие ответа, и прибор обязан сказать это третьим исходом. Беда в том,
    что под этот исход попадал сам эталонный зов аварии — `rev-list
    --max-count={N} HEAD -- {путь}`: прибор, заказанный по следам #574, не мог
    наблюдать #574.

    Поэтому ревизия заменяется на `HEAD`, числовое значение опции — на `10`,
    аргумент `-C` — на абсолютный каталог копии. ПУТЬ не трогается ничем, кроме
    плейсхолдера: подменяется ровно то, что к вопросу о координатах отношения не
    имеет. Подмена НАЗЫВАЕТСЯ в причине — вердикт «устойчив», полученный на
    подменённой ревизии, остаётся вердиктом о ФОРМЕ, и это сказано вслух."""
    sub = _subcommand(argv)
    spec_idx = {item["idx"] for item in roles.get("pathspec", [])}
    root_idx = {item["idx"] for item in roles.get("root_relative", [])}
    out, changed, skip_next = [], [], False
    after_ddash = False
    for idx, token in enumerate(argv):
        if after_ddash:
            # ВСЁ после `--` — путь, и подмене не подлежит НИКОГДА, даже если
            # классификация ролей его не назвала. Первая редакция смотрела
            # только в `roles`, и при неполных ролях объявляла путь ревизией:
            # `log HEAD -- P.txt` превращался в `log HEAD -- HEAD`, предмет
            # замера исчезал, и форма объявлялась устойчивой. Подменять то,
            # ради чего замер идёт, — тот же дефект, только изнутри прибора.
            out.append(token)
            continue
        if skip_next:
            out.append(str(work))
            changed.append("каталог `-C` → копия песочницы")
            skip_next = False
            continue
        if token == "-C":
            out.append(token)
            skip_next = True
            continue
        if token == "--":
            after_ddash = True
            out.append(token)
            continue
        if idx in spec_idx or idx in root_idx or token in ("git", sub):
            out.append(token)
            continue
        if token.startswith("-"):
            if DYNAMIC in token and token.startswith(NUMERIC_OPTS):
                out.append(token.split("=")[0] + "=10")
                changed.append(f"числовое значение {token.split('=')[0]} → 10")
            else:
                out.append(token)
            continue
        # голый позиционный, не признанный путём ⇒ это ревизия
        out.append("HEAD")
        changed.append("ревизия → HEAD")
    return out, sorted(set(changed))


def _snapshot(work: Path, env):
    """Ответ зова = (код, stdout) И СЛЕД, оставленный им в дереве.

    Без следа мутирующая подкоманда (`add <путь>`, `checkout -- <путь>`) выглядела
    бы «нечувствительной»: stdout у неё пуст в обоих прогонах, а сделала она в
    корне и в подкаталоге РАЗНОЕ."""
    probe = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=str(work),
                           env=env, capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
    return probe.stdout


def _run_form(argv, pristine: Path, rel_cwd: str, env, scratch: Path):
    """Прогон в СВЕЖЕЙ копии эталона ПО ТОМУ ЖЕ АБСОЛЮТНОМУ ПУТИ.

    Два прогона обязаны отличаться РОВНО каталогом запуска внутри копии. Первая
    редакция клала копии рядом (`w_root`/`w_sub`) — и `git rev-parse
    --show-toplevel`, зов без пути вообще, немедленно объявлялся «чувствительным»:
    он печатал два разных ИМЕНИ КОПИИ. Три из девяти первых находок прибора были
    этим и только этим (замер #575). Разница в имени каталога — свойство
    песочницы, а не зова, и находка из него изготовлена, а не измерена."""
    work = scratch / "w"
    if work.exists():
        shutil.rmtree(work)
    try:
        shutil.copytree(pristine, work, symlinks=True)
        res = subprocess.run(["git"] + argv[1:], cwd=str(work / rel_cwd), env=env,
                             capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
        return (res.returncode, res.stdout, _snapshot(work, env)), None
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"зов не выполнен: {exc}"


def observe_sensitivity(argv, roles, pristine: Path, env, scratch: Path):
    """Прогнать форму ИЗ ДВУХ каталогов одной рабочей копии и сравнить ОТВЕТ.

    Это и есть ответ на «слеп ли зов»: слеп тот, у кого ответ МЕНЯЕТСЯ от каталога
    запуска. «Путь передан как pathspec» — признак, а не вердикт.

    Возвращает ('sensitive'|'insensitive'|'unmeasured', причина|None)."""
    sub = _subcommand(argv)
    if sub is None:
        return "unmeasured", "подкоманда не сложилась статически"
    if sub in NETWORK_SUBCOMMANDS:
        return "unmeasured", f"подкоманда `{sub}` ходит в сеть — прибор в сеть не ходит"
    concrete = _concrete_argv(argv, roles)
    if len(concrete) < 2:
        return "unmeasured", "argv не сложился статически"

    note = ""
    for attempt in range(2):
        at_root, err1 = _run_form(concrete, pristine, "", env, scratch)
        at_sub, err2 = _run_form(concrete, pristine, "sub", env, scratch)
        if err1 or err2:
            return "unmeasured", err1 or err2
        if at_root != at_sub:
            return "sensitive", (note or None)
        # Одинаковый ОТКАЗ — не «ответ не меняется», а ОТСУТСТВИЕ ответа.
        # Совпадение двух неудач ничего не говорит о координатах, и выдавать
        # его за «устойчив» значит закрыть зов молча (инв. #17).
        if at_root[0] == 0:
            return "insensitive", (note or None)
        if attempt == 0:
            concrete, changed = _neutralise(concrete, roles, scratch / "w")
            if not changed:
                break
            note = "на подменённых не-путевых аргументах (" + ", ".join(changed) + ")"
            continue
    why = (at_root[1] or b"").decode("utf-8", "replace").strip()[:120]
    return "unmeasured", (f"форма не исполнилась в песочнице (код {at_root[0]})"
                          + (f" даже {note}" if note else "")
                          + (f": {why}" if why else ""))


# ─────────────────────────────── вердикт ───────────────────────────────

ROOTISH = ("root", "toplevel", "top_level", "repo", "worktree_root")


def _cwd_kind(cwd_expr, root_proven=()):
    """Что известно про каталог запуска зова. Три значения, и «не доказано» —
    самостоятельное, а не «наверное корень»."""
    if cwd_expr is None:
        return "ambient"                       # наследует каталог процесса
    for name in root_proven:
        if name and name in cwd_expr:
            return "pinned_proven_root"
    return "pinned_unproven"


def verdict_for(site, roles, sensitivity, reason):
    """Вердикт: наблюдение решает ЧУВСТВИТЕЛЬНОСТЬ, классификация — ПРЕДМЕТ.

    Предмет класса — «выбранный каталог запуска делает ПУТЬ неверным», поэтому
    зов, не несущий пути от каталога, в класс не входит вовсе. `git init` и
    `git rev-parse --show-toplevel` чувствительны к каталогу по своей природе и
    к этому классу отношения не имеют: первая редакция вердикта, выкинувшая это
    требование, объявила слепыми шесть таких зовов из девяти (замер #575).

    Путь, пришедший ПЕРЕМЕННОЙ, не объявляется слепым: он может оказаться
    абсолютным в рантайме, и статически это не видно. Это третий исход с
    названной причиной — ровно та ловушка, которую заказ назвал заранее."""
    # Порядок вопросов важен. «Подкоманда не сложилась» — единственный случай,
    # когда про наличие пути НЕЛЬЗЯ сказать ничего, и он обязан остаться третьим
    # исходом. А зов с известной подкомандой и БЕЗ пути от каталога просто не
    # входит в класс — гнать его через наблюдение незачем, и объявлять
    # «НЕ ИЗМЕРЕНО» неверно: измерено, просто не про него. Первая редакция
    # спрашивала в обратном порядке и записала 79 зовов в «не измерено», из
    # которых большинство путей не несут вовсе (замер #575).
    if roles["subcommand"] is None:
        return "UNMEASURED", reason or "подкоманда не сложилась статически"
    if not roles["pathspec"]:
        return "NO_PATH_FROM_CWD", "зов не несёт пути, читаемого от каталога запуска"
    if sensitivity == "unmeasured":
        return "UNMEASURED", reason
    if sensitivity == "insensitive":
        return "ROBUST", ("наблюдение: ответ не меняется от каталога запуска"
                          + (f" — замер {reason}" if reason else ""))
    if roles["dash_c"]:
        return "ROBUST", "`-C` сам задаёт каталог запуска"

    kind = _cwd_kind(site["cwd"], site.get("root_proven", ()))
    if kind == "pinned_proven_root":
        return "ROBUST", (f"каталог запуска ДОКАЗАННО корень: cwd={site['cwd']} "
                          f"происходит от `rev-parse --show-toplevel`")
    if kind == "pinned_unproven":
        return "UNMEASURED", (
            f"форма чувствительна, каталог закреплён выражением `{site['cwd']}` — "
            f"корень ли это, статически не доказано (провенанс от "
            f"`--show-toplevel` не прослеживается)")

    where = "каталог запуска не закреплён ничем"
    if roles["dynamic_path"]:
        return "UNMEASURED", (
            f"форма чувствительна и {where}, но путь приходит ПЕРЕМЕННОЙ "
            f"(`{roles['dynamic_path']}`) — абсолютен ли он в рантайме, "
            f"статически не видно")
    return "BLIND", f"ответ МЕНЯЕТСЯ от каталога, и {where}"


def fingerprint_574(sites_with_roles):
    """Отпечаток аварии #574: ОДНО И ТО ЖЕ выражение пути отдано в ОБЕ системы
    координат внутри одного скоупа.

    Форма сама по себе НЕ дефект — она дефект ровно тогда, когда каталог запуска
    у pathspec-зова не есть корень рабочей копии. В доставленном виде
    `push_base_provenance.base_provenance` несёт эту форму и БЕЗОПАСЕН: #574
    закрепил обоим зовам `cwd=root`. Поэтому отпечаток меряет форму И каталог, а
    не форму одну: иначе он краснел бы на уже починенном коде, и первый же цикл
    отключил бы его целиком.

    Возвращает список отпечатков; поле `unsafe` — вердикт, `safe_reason` — чем
    именно форма обезврежена."""
    by_scope = {}
    for site, roles, _v, _r in sites_with_roles:
        key = (site["file"], site["scope"])
        bucket = by_scope.setdefault(key, {"root": {}, "spec": {}})
        for item in roles["root_relative"]:
            if item["expr"] != DYNAMIC:
                bucket["root"].setdefault(item["expr"], []).append(site["line"])
        for item in roles["pathspec"]:
            if item["expr"] != DYNAMIC:
                bucket["spec"].setdefault(item["expr"], []).append(
                    (site["line"], site["cwd"], roles["dash_c"],
                     _cwd_kind(site["cwd"], site.get("root_proven", ()))))

    hits = []
    for (fname, scope), bucket in sorted(by_scope.items()):
        for expr in sorted(set(bucket["root"]) & set(bucket["spec"])):
            spec_sites = sorted(bucket["spec"][expr])
            unsafe, safe_reason = [], []
            for line, cwd, dash_c, kind in spec_sites:
                if dash_c:
                    safe_reason.append(f"строка {line}: `-C` задаёт каталог")
                elif kind == "pinned_proven_root":
                    safe_reason.append(
                        f"строка {line}: cwd={cwd} — доказанный корень")
                else:
                    unsafe.append(line)
            hits.append({
                "file": fname, "scope": scope, "path_expr": expr,
                "root_relative_lines": sorted(bucket["root"][expr]),
                "pathspec_lines": [l for l, _c, _d, _k in spec_sites],
                "unsafe_lines": unsafe,
                "unsafe": bool(unsafe),
                "safe_reason": "; ".join(safe_reason),
            })
    return hits


# ─────────────────────────────── перепись ───────────────────────────────

def census(repo_root: Path, subdirs=("scripts", "spa_core", "tests", "research")):
    repo_root = Path(repo_root).resolve()
    unmeasured_files, sites = [], []
    scanned = 0
    for sub in subdirs:
        base = repo_root / sub
        if not base.is_dir():
            unmeasured_files.append(f"каталога {sub}/ нет — не обойдён")
            continue
        for py in sorted(base.rglob("*.py")):
            scanned += 1
            found, why = collect_sites(py, repo_root)
            if why:
                unmeasured_files.append(why)
            sites.extend(found)

    shell_files = sorted(
        str(p.relative_to(repo_root))
        for sub in subdirs if (repo_root / sub).is_dir()
        for p in (repo_root / sub).rglob("*.sh"))

    with tempfile.TemporaryDirectory(prefix="git_coord_probe_") as td:
        base = Path(td)
        pristine, scratch = base / "pristine", base / "scratch"
        pristine.mkdir()
        scratch.mkdir()
        try:
            env = build_probe_repo(pristine)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"measured": False,
                    "reason": f"песочница для наблюдения не построена: {exc}"}
        cache = {}
        rows = []
        for site in sites:
            roles = classify(site)
            key = (tuple(site["argv"]),
                   tuple(sorted(i["idx"] for i in roles["pathspec"])))
            if key not in cache:
                cache[key] = observe_sensitivity(site["argv"], roles, pristine, env, scratch)
            sens, why = cache[key]
            v, reason = verdict_for(site, roles, sens, why)
            rows.append((site, roles, v, reason))

    with_path = [r for r in rows if r[1]["pathspec"] or r[1]["root_relative"]]
    population = [r for r in rows if r[1]["pathspec"]]
    return {
        "measured": True,
        "files_scanned": scanned,
        "calls_total": len(rows),
        "calls_with_path": len(with_path),
        "population": population,
        "population_cwd_not_root": [
            r for r in population
            if not r[1]["dash_c"]
            and _cwd_kind(r[0]["cwd"], r[0].get("root_proven", ()))
            != "pinned_proven_root"],
        "blind": [r for r in rows if r[2] == "BLIND"],
        "robust": [r for r in rows if r[2] == "ROBUST"],
        "unmeasured_calls": [r for r in rows if r[2] == "UNMEASURED"],
        "no_cwd_path": [r for r in rows if r[2] == "NO_PATH_FROM_CWD"],
        "fingerprint": fingerprint_574(with_path),
        "unmeasured_files": unmeasured_files,
        "shell_scripts": shell_files,
        "rows": rows,
    }


def render(result) -> str:
    if not result.get("measured"):
        return f"— НЕ ИЗМЕРЕНО: {result.get('reason', 'причина не названа')} —"
    unsafe = [h for h in result["fingerprint"] if h["unsafe"]]
    safe = [h for h in result["fingerprint"] if not h["unsafe"]]
    out = [
        "ПЕРЕПИСЬ ЗОВОВ git ПО СИСТЕМЕ КООРДИНАТ ПУТИ (заказ #574)",
        f"  файлов обойдено:                 {result['files_scanned']}",
        f"  зовов git всего (AST, не греп):  {result['calls_total']}",
        "",
        "  НАСЕЛЕНИЕ КЛАССА — зовы, несущие путь, читаемый ОТ КАТАЛОГА ЗАПУСКА:",
        f"    всего:                         {len(result['population'])}",
        f"    из них каталог НЕ корень:      {len(result['population_cwd_not_root'])}",
        "",
        "  «путь передан как pathspec» ≠ «зов слеп». Слеп тот, у кого ОТВЕТ МЕНЯЕТСЯ",
        "  от каталога запуска — и это сказано НАБЛЮДЕНИЕМ: каждая форма прогнана в",
        "  одноразовой копии из корня и из подкаталога, ответы сравнены.",
        f"    СЛЕПЫХ (доказано):             {len(result['blind'])}",
        f"    устойчивых:                    {len(result['robust'])}",
        f"    пути от каталога не несут:     {len(result['no_cwd_path'])}",
        f"    НЕ ИЗМЕРЕНО:                   {len(result['unmeasured_calls'])}",
    ]
    for site, _roles, _v, reason in result["blind"]:
        out.append(f"      🔴 {site['file']}:{site['line']} "
                   f"`git {' '.join(t for t in site['argv'][1:4])}` — {reason}")
    out.append("")
    out.append(f"  ОТПЕЧАТОК #574 — один путь в ОБЕИХ координатах в одном скоупе: "
               f"{len(result['fingerprint'])} "
               f"(опасных {len(unsafe)}, обезврежен каталогом {len(safe)})")
    for hit in result["fingerprint"]:
        mark = "🔴" if hit["unsafe"] else "🟢"
        tail = (f"каталог НЕ корень, строки {hit['unsafe_lines']}" if hit["unsafe"]
                else f"обезврежен — {hit['safe_reason']}")
        out.append(f"      {mark} {hit['file']}::{hit['scope']} путь `{hit['path_expr']}`: "
                   f"от корня {hit['root_relative_lines']}, "
                   f"pathspec {hit['pathspec_lines']} — {tail}")
    if result["unmeasured_files"]:
        out.append("")
        out.append(f"  файлов НЕ ИЗМЕРЕНО: {len(result['unmeasured_files'])}")
        for why in result["unmeasured_files"][:5]:
            out.append(f"      · {why}")
    out.append("")
    out.append(f"  ВНЕ ЗАМЕРА ПО ПОСТРОЕНИЮ: {len(result['shell_scripts'])} shell-скриптов —")
    out.append("  AST их не разбирает, каталог запуска задаётся `cd` в теле.")
    out.append("  Это НЕ «у них чисто» и НЕ находка о них: они НЕ ИЗМЕРЕНЫ.")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=None, help="корень рабочей копии")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    result = census(root)

    if args.json:
        printable = dict(result)
        printable.pop("rows", None)
        for key in ("blind", "robust", "unmeasured_calls", "no_cwd_path",
                    "population", "population_cwd_not_root"):
            if key in printable:
                printable[key] = [{"file": s["file"], "line": s["line"],
                                   "scope": s["scope"], "reason": r}
                                  for s, _ro, _v, r in printable[key]]
        print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(result))

    if not result.get("measured"):
        return EXIT_UNMEASURED
    if result["blind"] or any(h["unsafe"] for h in result["fingerprint"]):
        return EXIT_FINDING
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
