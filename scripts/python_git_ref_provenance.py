#!/usr/bin/env python3
"""ТА ЖЕ ССЫЛКА, ДРУГАЯ ПОВЕРХНОСТЬ: `origin/main` из python (ЗАКАЗ #583).

Цепь #574…#582 мерила ТОЛЬКО shell. ADR-361 сказал это вслух — «python-поверхность
не измерена» — и сделал её заказом, а не умолчанием. Между тем решение «что
считать доставленным» принимают именно python-зовы: `push_to_github.py` сверяет
набор с базой, шаг 0a сверяет рабочие деревья с `origin/main`, очередь владельца
читает карточки «в версии origin».

Вопрос заказа дословно: **у скольких python-зовов, решающих, что считать
доставленным, доказано, что значение `origin/main` спрошено у сервера в этом же
пути, а не взято из кэша последнего чужого `fetch`?**

## Почему поверхность другая, хотя ссылка та же

`refs/remotes/origin/main` — обычная локальная ссылка; она хранит ЗНАЧЕНИЕ и не
хранит ни возраста, ни провенанса. Это ADR-361 уже доказал, и здесь не
повторяется. Ново другое: в shell зов виден глазами (`git reset --hard
origin/main` — одна строка), а в python **зова с литералом почти нет**. Замер
этого дерева: прямых `subprocess`-вызовов, в argv которых лежит литерал
remote-tracking ссылки, — ДВА. Всё остальное ходит через СВОИ ОБЁРТКИ
(`_git_out`, `_git_bytes`, `_run`), а ссылка приезжает в них параметром, чьё
умолчание объявлено модульной константой (`DEFAULT_BASE = "origin/main"`,
`DEFAULT_REF`, `ref = f"refs/remotes/origin/{branch}"`).

Поэтому мерка «искать литерал в argv» здесь ответила бы «2» — и это был бы
верный ответ на НЕ ТОТ вопрос. Прибор разрешает три вещи, без которых население
вырождается:

1. **Дверь к git.** Функция объявляется дверью, если в её теле есть
   `subprocess`-вызов, чей argv начинается с `git`, И в этот argv втекает её
   собственный параметр (`*args`, `[…, param, …]`). Двери ищутся до неподвижной
   точки: обёртка над обёрткой — тоже дверь.
2. **Значение аргумента.** Литерал · f-строка · модульная константа · локальное
   присваивание выше по телу · УМОЛЧАНИЕ параметра. Последнее — не роскошь:
   `DEFAULT_BASE = "origin/main"` в сигнатуре есть самый частый способ, которым
   ссылка попадает в зов в этом дереве.
3. **Господство по ГРАФУ ВЫЗОВОВ, а не по строкам.** Ловушка названа в заказе
   заранее, и она не теоретическая: ADR-361 поймал её на
   `code_sync_from_origin.sh`, где читатели стоят ВЫШЕ `fetch` по строкам и
   ПОЗЖЕ него по исполнению.

## Что объявлено ДОКАЗАТЕЛЬСТВОМ — заранее, тем же порядком, что в ADR-361

**Ось 1 — СВЕЖЕСТЬ.** Значение спрошено у сервера на этом пути: господствующий
обновитель (`git fetch` / `git pull` / `git remote update`), который (а) пишет
именно эту ссылку, (б) господствует по графу вызовов и (в) чей ОТКАЗ прекращает
путь.

Пункт (в) в python ТИШЕ, чем в shell, и это вторая названная заказом ловушка.
`subprocess.run(["git","fetch"])` при недоступной сети не поднимает ничего:
исключения нет, объект результата просто не смотрят, ссылка остаётся прежней, и
следующая строка читает кэш. Поэтому «прекращает путь» здесь измеряется формой
вызова, а не намерением:

| форма | прекращает ли отказ путь |
|---|---|
| `check_call` / `check_output` | ДА — исключение по построению |
| `run(..., check=True)` | ДА |
| `run(...)`, результат связан и `returncode` прочитан с `raise`/`return`/`sys.exit` | ДА |
| `run(...)`, результат не связан либо связан и не прочитан | НЕТ — `asked_not_gated` |

**Ось 2 — ЛИЧНОСТЬ УДАЛЁННОГО.** `by_url` (удалённый назван URL-литералом —
утверждение путешествует с кодом) · `by_config` (назван ИМЕНЕМ — решает
`.git/config` той копии, где зов исполнится) · `by_var` (пришёл из
неразрешённого значения — НЕ ИЗМЕРЕНО).

## Три исхода, и третий не складывается в первый (инвариант #17)

| исход | что доказано |
|---|---|
| `asked_and_gated` | спрошено у сервера, и отказ спроса прекращает путь |
| `asked_not_gated` | спрос есть, его отказ ничего не прекращает — при недоступной сети читается кэш |
| `cache_only` | спроса на этом пути нет вовсе |
| `unmeasured` | прибор не разобрал файл, дверь или ссылку; причина названа, код возврата ненулевой |

«Не разобрал вызов» — НЕ «доказано». Это сказано в заказе и закреплено тестом.

## Предмет храповика УЖЕ, чем ответ — ровно как в ADR-361

Ответ даётся по обеим осям. Предмет храповика — только ось свежести
(`asked_not_gated` + `cache_only` + `unmeasured`). `by_config` есть обычная
идиома git, и храповик, краснеющий на каждом `origin/main`, научил бы дописывать
в базу — то есть был бы дефектом, против которого храповики и существуют
(`.claude/rules/deployment.md`).

## Чего прибор НЕ меряет — сказано вслух, а не опущено

- **HTTP-путь к серверу.** `push_to_github.get_base_ref` спрашивает базу у
  GitHub API, а не у локальной ссылки. Такой зов в население НЕ входит по
  построению — он не читает remote-tracking ссылку вовсе, — и прибор про него
  молчит намеренно: смешать локальную ссылку и HTTP в одном счёте значило бы
  сравнивать несравнимое. Число по HTTP-двери названо отдельной строкой в
  ADR-362 и не выводится этим прибором.
- **Возраст кэша в момент зова.** Статически не выводится; ADR-361 замерил его
  по reflog этого хоста (медиана 0.26 ч, максимум 224.5 ч).
- **Успех обновителя в конкретном прогоне.** Речь о том, что код ДЕЛАЕТ при
  отказе, а не о том, отказал ли он сегодня.
"""

from __future__ import annotations

import ast
import re
import sys
import json
import argparse
from pathlib import Path

#: Каталоги, которые в население не входят. `.claude/worktrees` и `/tmp`-копии —
#: ЧУЖИЕ деревья на старых ревизиях: находка о них была бы находкой о другом
#: дереве (урок обхода прод-дерева).
SKIP_PARTS = ("/tests/", "/test_", "node_modules", ".claude/worktrees",
              "/.git/", "/site-packages/", "/build/", "/.venv/")

#: Раннеры subprocess. `getoutput`/`getstatusoutput` — оболочечные, argv у них
#: строкой; они разбираются той же дорогой.
RUNNERS = {"run", "check_output", "check_call", "call", "Popen",
           "getoutput", "getstatusoutput"}

#: Раннеры, чей ОТКАЗ поднимает исключение по построению.
RAISING_RUNNERS = {"check_output", "check_call"}

#: Обновители remote-tracking ссылок. `ls-remote` сюда НЕ входит намеренно (как
#: и в ADR-361): он спрашивает сервер, но НИЧЕГО не записывает — ссылку не
#: освежает. Он же — честная форма «спросить сервер, не трогая кэш».
UPDATERS = {"fetch", "pull"}

#: Подкоманды, МЕНЯЮЩИЕ дерево или историю: читающий зов на стухшем кэше печатает
#: неверное число, мутирующий — переписывает дерево на чужую ревизию.
MUTATORS = {"reset", "rebase", "checkout", "merge", "switch", "restore",
            "cherry-pick", "revert", "clean"}

DEFAULT_REMOTES = {"origin", "upstream"}

URL_RE = re.compile(r"^(https?://|ssh://|git://|file://|git@|/)")
REF_RE = re.compile(r"^(?P<remote>[A-Za-z_][\w.\-]*)/(?P<branch>[\w.\-/]+)$")

#: Чем прибор обозначает кусок, который он НЕ разрешил. Отдельное значение, а не
#: пустая строка: «не разрешено» обязано быть отличимо от «пусто» (инвариант #17).
DYN = "\x00dyn"


# ───────────────────────────── разбор ссылок ─────────────────────────────

def ref_candidates(token: str):
    """Куски аргумента, которые МОГУТ быть ссылками.

    Три формы, и все три встречаются в этом дереве: `origin/main` ·
    `origin/main:docs/X.md` (`git show`) · `HEAD..origin/main` (`rev-list`).
    Двоеточие режется только СЛЕВА: `refs/remotes/…` двоеточий не содержит, а
    путь справа ссылкой не является."""
    if not token or token.startswith("-") or DYN in token:
        # Хвост с неразрешённой подстановкой всё же может нести ссылку слева:
        # `f"{ref}:{path}"` разрешается в `origin/main:\x00dyn`.
        if not token or token.startswith("-"):
            return []
    head = token.split(":", 1)[0] if ":" in token else token
    parts = re.split(r"\.\.\.?", head)
    return [p for p in parts if p and DYN not in p]


def remote_ref(token: str, remotes):
    """(удалённый, ветка) — либо None, если это не remote-tracking ссылка.

    `refs/remotes/<имя>/<ветка>` признаётся всегда: форма самодостаточна.
    `<имя>/<ветка>` — только когда имя ЗАМЕРЕНО как имя удалённого; иначе
    прибор принял бы за ссылку любой путь со слэшем (`docs/STATE.md`)."""
    if token.startswith("refs/remotes/"):
        rest = token[len("refs/remotes/"):]
        if "/" not in rest:
            return None
        name, _, branch = rest.partition("/")
        return (name, branch) if branch else None
    m = REF_RE.match(token)
    if m and m.group("remote") in remotes:
        return (m.group("remote"), m.group("branch"))
    return None


def ref_in(token: str, remotes):
    for cand in ref_candidates(token):
        got = remote_ref(cand, remotes)
        if got:
            return cand, got
    return None, None


# ───────────────────────── разрешение строковых значений ─────────────────────

class Resolver:
    """Значения строковых выражений в пределах ОДНОГО модуля.

    Сознательная граница: межмодульных констант прибор не разрешает и говорит об
    этом `unmeasured`, а не молчанием. Внутри модуля разрешаются модульные
    константы, локальные присваивания выше по телу и УМОЛЧАНИЯ параметров."""

    def __init__(self, tree: ast.AST):
        self.module = {}
        # Умолчания argparse и имена, связанные с результатом `parse_args()`.
        # Это не роскошь: `ap.add_argument("--base", default=DEFAULT_BASE)` есть
        # штатный способ, которым `origin/main` доезжает до зова в этом дереве
        # (`adr_number.py`, `check_undelivered_work.py`). Без разрешения этой
        # формы ссылка «исчезает» между объявлением и употреблением.
        self.argparse_defaults = {}
        self.namespaces = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                val = self._literal(node.value)
                if val is not None:
                    self.module[node.targets[0].id] = val
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "add_argument" and node.args:
                    flag = self._literal(node.args[0])
                    default = next((k.value for k in node.keywords
                                    if k.arg == "default"), None)
                    if flag and flag.startswith("--") and default is not None:
                        got = self._literal(default)
                        if got is None and isinstance(default, ast.Name):
                            got = self.module.get(default.id)
                        if got is not None:
                            self.argparse_defaults[
                                flag[2:].replace("-", "_")] = got
                if node.func.attr == "parse_args":
                    pass
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Call) \
                    and isinstance(node.value.func, ast.Attribute) \
                    and node.value.func.attr in ("parse_args",
                                                 "parse_known_args"):
                self.namespaces.add(node.targets[0].id)
        self.local = {}

    @staticmethod
    def _literal(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def enter(self, fn: ast.AST, inherited=None):
        """Таблица имён функции: параметры с умолчаниями + присваивания тела.

        Присваивания берутся БЕЗ учёта порядка строк намеренно: имя,
        присвоенное ниже зова, в python обычно означает переприсваивание в
        цикле, а не «значения ещё нет». Осторожная сторона здесь — признать
        значение и отдать зов в население, а не потерять его."""
        self.local = {}
        args = fn.args
        params = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
        defaults = list(args.defaults)
        positional = list(args.posonlyargs) + list(args.args)
        for name, default in zip(positional[len(positional) - len(defaults):],
                                 defaults):
            got = self.resolve(default)
            if got is not None and DYN not in got:
                self.local[name.arg] = got
        for name, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is None:
                continue
            got = self.resolve(default)
            if got is not None and DYN not in got:
                self.local[name.arg] = got
        for name, val in (inherited or {}).items():
            self.local.setdefault(name, val)
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                got = self.resolve(node.value)
                if got is not None:
                    self.local.setdefault(node.targets[0].id, got)
        return [p.arg for p in params]

    def resolve(self, node):
        """Строковое значение выражения, либо None. `DYN` — «часть не разрешена»."""
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, str) else None
        if isinstance(node, ast.Name):
            if node.id in self.local:
                return self.local[node.id]
            return self.module.get(node.id)
        if isinstance(node, ast.Attribute):
            # `args.base` — умолчание, объявленное `add_argument`. Разрешается
            # только для имени, ЗАМЕРЕННО связанного с `parse_args()`: иначе
            # прибор принял бы за ссылку любой одноимённый атрибут.
            if isinstance(node.value, ast.Name) and node.value.id in self.namespaces:
                return self.argparse_defaults.get(node.attr)
            return None
        if isinstance(node, ast.JoinedStr):
            out = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out.append(part.value)
                elif isinstance(part, ast.FormattedValue):
                    got = self.resolve(part.value)
                    out.append(got if got is not None and DYN not in got else DYN)
                else:
                    out.append(DYN)
            return "".join(out)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.resolve(node.left), self.resolve(node.right)
            if left is None and right is None:
                return None
            return (left or DYN) + (right or DYN)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return self.resolve(node.left)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "format":
            return self.resolve(node.func.value)
        return None

    def tokens(self, node):
        """Все строки, втекающие в выражение (список argv разворачивается)."""
        out = []
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                if isinstance(elt, ast.Starred):
                    out.append(DYN)
                    continue
                got = self.resolve(elt)
                out.append(got if got is not None else DYN)
            return out
        got = self.resolve(node)
        if got is None:
            return [DYN]
        # Оболочечная форма: одна строка — вся команда.
        return got.split() if " " in got else [got]


# ───────────────────────────── двери к git ─────────────────────────────

def _runner_name(call: ast.Call):
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _callee_name(call: ast.Call):
    """Имя зовомого: `f(...)` → 'f'; `mod.f(...)` → 'f'; иначе None."""
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _argv_node(call: ast.Call):
    """Выражение argv раннера: первый позиционный либо `args=`."""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "args":
            return kw.value
    return None


def subcommand(tokens):
    """Подкоманда git: первый токен после `git`, не являющийся опцией.

    `-C <path>` и `-c k=v` съедают следующий токен — иначе путь был бы принят
    за подкоманду."""
    out, skip = None, False
    seen_git = False
    for tok in tokens:
        if not seen_git:
            if tok == "git" or tok.endswith("/git"):
                seen_git = True
            continue
        if skip:
            skip = False
            continue
        if tok in ("-C", "-c", "--git-dir", "--work-tree"):
            skip = True
            continue
        if tok.startswith("-") or tok == DYN:
            continue
        out = tok
        break
    return out


def _names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def module_index(mods) -> dict:
    """точечное имя модуля → rel-путь; плюс голое имя файла.

    Голое имя нужно потому, что скрипты добирают соседей через
    `sys.path.insert(…, scripts/)`: `from check_undelivered_work import _git` —
    это ровно та строка, которой `adr_number.py` берёт дверь СОСЕДНЕГО модуля.
    Без неё прибор объявил бы «дверей нет» там, где дверь просто импортирована."""
    idx = {}
    for m in mods:
        dotted = m.rel[:-3].replace("/", ".")
        idx.setdefault(dotted, m.rel)
        idx.setdefault(Path(m.rel).stem, m.rel)
    return idx


def resolve_door(m, name, doors, mod_index, fn=None):
    """Дверь, стоящая за именем: своя · внедрённая параметром · импортированная."""
    if (m.rel, name) in doors:
        return doors[(m.rel, name)]
    if fn is not None:
        alias = _door_aliases(fn, doors, m.rel, m, mod_index).get(name)
        if alias and alias in doors:
            return doors[alias]
    src = m.imported.get(name)
    if src:
        rel = mod_index.get(src) or mod_index.get(src.rsplit(".", 1)[-1])
        if rel and (rel, name) in doors:
            return doors[(rel, name)]
    return None


def _door_aliases(fn, doors, rel, m=None, mod_index=None):
    """{имя параметра: ключ двери} — двери, ВНЕДРЁННЫЕ через умолчание параметра.

    `def other_refs(root, base_ref=DEFAULT_BASE, git=_git)` и внутри `git(...)`.
    Зов идёт по ИМЕНИ ПАРАМЕТРА, и по тексту тела он неотличим от любого другого
    вызова: дверь видна только в сигнатуре. Форма внедрения выбрана в этом дереве
    ради тестируемости (подменить `git=` фейком), и именно она делает наивный
    поиск «зовов git» слепым."""
    out = {}
    if fn is None:
        return out
    args = fn.args
    positional = list(args.posonlyargs) + list(args.args)
    pairs = list(zip(positional[len(positional) - len(args.defaults):],
                     args.defaults))
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults)
              if d is not None]
    for param, default in pairs:
        if not isinstance(default, ast.Name):
            continue
        if (rel, default.id) in doors:
            out[param.arg] = (rel, default.id)
        elif m is not None and mod_index is not None:
            # Дверь может быть ИМПОРТИРОВАНА: `from check_undelivered_work
            # import _git` в `adr_number.py` — и без этой ветки крупнейший
            # потребитель ссылки (номера ADR решаются по origin/main) выпадает
            # из населения целиком.
            src = m.imported.get(default.id)
            if src:
                rel2 = mod_index.get(src) or mod_index.get(src.rsplit(".", 1)[-1])
                if rel2 and (rel2, default.id) in doors:
                    out[param.arg] = (rel2, default.id)
    return out


def _param_names(fn) -> set:
    """ВСЕ имена параметров, включая `*args` / `**kwargs`.

    Пропустить `*args` — значит потерять самую частую форму двери в этом дереве:
    `def _git(cwd, *args): subprocess.run(["git", "-C", str(cwd), *args])`.
    Ровно она стои́т в `check_undelivered_work.py` и в `adr_number.py`, то есть
    в двух крупнейших потребителях ссылки; первая редакция прибора их
    ПОТЕРЯЛА, и это была ошибка в сторону занижения населения."""
    out = {a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs}
    if fn.args.vararg:
        out.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        out.add(fn.args.kwarg.arg)
    return out


def _is_git_argv(tokens):
    return any(t == "git" or t.endswith("/git") for t in tokens if t != DYN)


def _gating(call: ast.Call, stmt, runner: str) -> bool:
    """Прекращает ли ОТКАЗ этого вызова путь.

    Вторая ловушка заказа живёт здесь: `subprocess.run` при недоступной сети не
    поднимает ничего, и результат просто не смотрят. Поэтому судится ФОРМА."""
    if runner in RAISING_RUNNERS:
        return True
    for kw in call.keywords:
        if kw.arg == "check" and isinstance(kw.value, ast.Constant) \
                and kw.value.value is True:
            return True
    # `run(...)` со связанным результатом: отказ прекращает путь, только если
    # `returncode` прочитан и ветка обрывает исполнение.
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
            and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id          # проверяется вызывающим контекстом
    return False


class ModuleScan:
    """Один разобранный модуль: двери, обновители, зовы.

    Индексы (`owner`, `stmt`) строятся ОДИН раз: перепись обходит дерево
    многократно, и пересборка на каждом обходе делала прогон минутным."""

    def __init__(self, path: Path, rel: str, tree: ast.AST, src: str):
        self.path, self.rel, self.tree, self.src = path, rel, tree, src
        self.res = Resolver(tree)
        self.functions = {}
        self.imported = {}
        self._owner = None
        self._stmt = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    self.imported[alias.asname or alias.name] = node.module

    @property
    def owner(self):
        if self._owner is None:
            self._owner = _enclosing_func(self.tree)
        return self._owner

    @property
    def stmt(self):
        if self._stmt is None:
            self._stmt = _stmt_of(self.tree)
        return self._stmt

    @property
    def calls(self):
        if not hasattr(self, "_calls"):
            self._calls = [n for n in ast.walk(self.tree)
                           if isinstance(n, ast.Call)]
        return self._calls

    @property
    def funcs(self):
        if not hasattr(self, "_funcs"):
            self._funcs = {n.name: n for n in ast.walk(self.tree)
                           if isinstance(n, (ast.FunctionDef,
                                             ast.AsyncFunctionDef))}
        return self._funcs


def _stmt_index(fn):
    """statement → цепочка ОБЪЕМЛЮЩИХ узлов (для суждения о ветвлении).

    Цепочка обязана содержать сам объемлющий `if`, а не только функцию: первая
    редакция передавала вниз родителя ребёнка вместо самого ребёнка, поэтому
    оператор внутри `if net:` получал цепочку `[func]` — без `If`, — и
    обновитель в теле ветвления объявлялся безусловным. `ExceptHandler` не
    является `ast.stmt` и потому добавляется отдельной веткой: без неё `fetch`
    внутри `except` тоже сошёл бы за безусловный."""
    chain = {}

    def walk(node, path):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                chain[child] = path
                walk(child, path + [child])
            elif isinstance(child, ast.excepthandler):
                walk(child, path + [child])
            else:
                walk(child, path)
    walk(fn, [])
    return chain


BRANCHING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
             ast.Match)


def _unconditional(stmt, chain) -> bool:
    """Исполнится, если до него дошли: не в теле ветвления и не в обработчике.

    Тела `try:` и `with:` ветвлением НЕ считаются — они исполняются. Тело
    `except:` считается: оно исполняется только при отказе."""
    return not any(isinstance(n, BRANCHING) for n in chain.get(stmt, []))


# ───────────────────────────── перепись ─────────────────────────────

def python_files(root: Path):
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = str(p.relative_to(root))
        full = "/" + rel
        if any(s in full for s in SKIP_PARTS):
            continue
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        out.append((p, rel))
    return out


def _enclosing_func(tree):
    """узел → объемлющая функция (или None для модульного уровня)."""
    owner = {}

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            nxt = child if isinstance(child, (ast.FunctionDef,
                                              ast.AsyncFunctionDef)) else fn
            owner[child] = fn
            walk(child, nxt)
    walk(tree, None)
    return owner


def _stmt_of(tree):
    """узел-выражение → объемлющий statement."""
    out = {}

    def walk(node, stmt):
        for child in ast.iter_child_nodes(node):
            nxt = child if isinstance(child, ast.stmt) else stmt
            out[child] = nxt
            walk(child, nxt)
    walk(tree, None)
    return out


def inherited_params(mods, rounds: int = 4) -> dict:
    """{(rel, функция): {параметр: значение}} — значения, пришедшие от ВЫЗЫВАЮЩИХ.

    Без этого прохода ссылка исчезает ровно там, где она важнее всего:
    `def _origin_index(root, base_ref, git=_git)` умолчания не имеет, а зовётся
    из `taken_keys(root, base_ref=DEFAULT_BASE)`. По телу функции `base_ref`
    неразрешим — и первая редакция прибора ТЕРЯЛА чтение реестра ADR целиком,
    то есть тот самый зов, который решает, занят ли номер решения на origin.

    Связывается только ОДНОЗНАЧНОЕ: если разные вызывающие передают разное,
    имя остаётся несвязанным — догадка тут была бы хуже пропуска, и она не
    нужна, потому что несвязанное имя даёт `unmeasured`, а не «доказано»."""
    out = {}
    for _ in range(rounds):
        changed = False
        for m in mods:
            owner, funcs = m.owner, m.funcs
            for node in m.calls:
                name = _callee_name(node)
                target = funcs.get(name) if name else None
                if target is None:
                    continue
                caller = owner.get(node)
                m.res.enter(caller, out.get((m.rel, caller.name))
                            if caller else None) if caller else \
                    setattr(m.res, "local", {})
                pmap = _param_map(target, node)
                if pmap is None:
                    continue
                key = (m.rel, name)
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    pname = pmap.get(id(arg))
                    if pname is None:
                        continue
                    got = m.res.resolve(arg)
                    if got is None or DYN in got:
                        continue
                    slot = out.setdefault(key, {})
                    if pname in slot and slot[pname] != got:
                        slot[pname] = DYN          # разные вызывающие — не связывать
                    elif pname not in slot:
                        slot[pname] = got
                        changed = True
        if not changed:
            break
    return {k: {p: v for p, v in vals.items() if v != DYN}
            for k, vals in out.items()}


def scan_module(path: Path, rel: str):
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    return ModuleScan(path, rel, tree, src)


def collect(mods, inherit):
    """(invocations, doors) — зовы git и функции-двери, до неподвижной точки."""
    invocations, doors = [], {}
    mod_index = module_index(mods)
    for m in mods:
        owner, stmt_of = m.owner, m.stmt
        for node in m.calls:
            runner = _runner_name(node)
            if runner not in RUNNERS:
                continue
            argv = _argv_node(node)
            if argv is None:
                continue
            fn = owner.get(node)
            if fn is not None:
                m.res.enter(fn, inherit.get((m.rel, fn.name)))
            else:
                m.res.local = {}
            tokens = m.res.tokens(argv)
            if not _is_git_argv(tokens):
                continue
            stmt = stmt_of.get(node)
            rec = {"mod": m, "func": fn, "func_name": fn.name if fn else None,
                   "line": node.lineno, "tokens": tokens, "runner": runner,
                   "call": node, "stmt": stmt,
                   "sub": subcommand(tokens),
                   "gating": _gating(node, stmt, runner)}
            invocations.append(rec)
            if fn is not None:
                flowing = _names_in(argv) & _param_names(fn)
                if flowing:
                    key = (m.rel, fn.name)
                    doors.setdefault(key, {"params": set(), "mod": m, "fn": fn,
                                           "sub": rec["sub"], "tokens": tokens,
                                           "level": 0})
                    doors[key]["params"] |= flowing
    # Неподвижная точка: обёртка над дверью — тоже дверь.
    changed = True
    while changed:
        changed = False
        for m in mods:
            owner = m.owner
            for node in m.calls:
                name = _callee_name(node)
                if name is None:
                    continue
                fn = owner.get(node)
                target = resolve_door(m, name, doors, mod_index, fn)
                if target is None:
                    continue
                if fn is None or fn.name == name:
                    continue
                own = _param_names(fn)
                flowing = set()
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    flowing |= (_names_in(arg) & own)
                if not flowing:
                    continue
                key = (m.rel, fn.name)
                before = set(doors.get(key, {}).get("params", ()))
                doors.setdefault(key, {"params": set(), "mod": m, "fn": fn,
                                       "sub": target["sub"],
                                       "tokens": target["tokens"],
                                       "level": target.get("level", 0) + 1})
                doors[key]["params"] |= flowing
                if doors[key]["params"] != before:
                    changed = True
    return invocations, doors


def known_remotes(invocations) -> set:
    """Имена удалённых, ЗАМЕРЕННЫЕ по коду, плюс умолчания по построению."""
    out = set(DEFAULT_REMOTES)
    for inv in invocations:
        if inv["sub"] in ("fetch", "pull", "push"):
            tail = inv["tokens"][inv["tokens"].index(inv["sub"]) + 1:] \
                if inv["sub"] in inv["tokens"] else []
            rest = [t for t in tail if not t.startswith("-") and t != DYN]
            if rest and "/" not in rest[0] and not URL_RE.match(rest[0]):
                out.add(rest[0])
    return out


def _param_map(fn, node: ast.Call):
    """аргумент зова → имя параметра двери. None — соответствие не установлено."""
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    out = {}
    for i, arg in enumerate(node.args):
        if isinstance(arg, ast.Starred):
            return None
        if i < len(names):
            out[id(arg)] = names[i]
        elif fn.args.vararg:
            out[id(arg)] = fn.args.vararg.arg
        else:
            return None
    for kw in node.keywords:
        if kw.arg is None:
            return None
        out[id(kw.value)] = kw.arg
    return out


def find_readers(mods, doors, remotes, mod_index, inherit):
    """Зовы, ЧИТАЮЩИЕ remote-tracking ссылку: прямые и через двери."""
    readers, outer = [], []
    for m in mods:
        owner, stmt_of = m.owner, m.stmt
        for node in m.calls:
            fn = owner.get(node)
            if fn is not None:
                m.res.enter(fn, inherit.get((m.rel, fn.name)))
            else:
                m.res.local = {}

            runner = _runner_name(node)
            direct = runner in RUNNERS and _argv_node(node) is not None
            tokens, via, door_sub = [], None, None

            if direct:
                tokens = m.res.tokens(_argv_node(node))
                if not _is_git_argv(tokens):
                    direct = False
            if not direct:
                name = _callee_name(node)
                door = resolve_door(m, name, doors, mod_index, fn) if name else None
                if door is None:
                    continue
                if door["fn"] is fn:          # рекурсия двери в себя — не зов
                    continue
                if door.get("level", 0) != 0:
                    # ТОТ ЖЕ read, увиденный дальше от git: обёртка над дверью
                    # лишь передаёт ссылку вниз. Считать и её значило бы
                    # посчитать одно чтение дважды и раздуть знаменатель.
                    # Считается отдельным числом, вердикта не несёт.
                    outer.append({"file": m.rel, "line": node.lineno,
                                  "via": name})
                    continue
                pmap = _param_map(door["fn"], node)
                if pmap is None:
                    readers.append({"file": m.rel, "line": node.lineno,
                                    "func": fn.name if fn else None,
                                    "ref": None, "basis": "by_var",
                                    "verdict": "unmeasured", "mutating": False,
                                    "sub": None, "mod": m, "node": node,
                                    "stmt": stmt_of.get(node), "fnode": fn,
                                    "why": (f"зов двери {name}() разобран не до "
                                            f"конца: соответствие аргументов "
                                            f"параметрам не установлено (*args "
                                            f"или **kwargs)")})
                    continue
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    pname = pmap.get(id(arg))
                    if pname is None or pname not in door["params"]:
                        continue
                    for tok in m.res.tokens(arg):
                        tokens.append(tok)
                if not tokens:
                    continue
                via, door_sub = name, door["sub"]

            found_ref, pair = None, None
            for tok in tokens:
                got, gotpair = ref_in(tok, remotes)
                if got:
                    found_ref, pair = got, gotpair
                    break
            if not found_ref:
                continue

            sub = subcommand(tokens) if direct else (
                next((t for t in tokens if t in MUTATORS or t in
                      ("rev-parse", "show", "cat-file", "merge-base", "log",
                       "diff", "ls-tree", "rev-list", "branch", "for-each-ref",
                       "describe", "name-rev")), door_sub))
            readers.append({
                "file": m.rel, "line": node.lineno,
                "func": fn.name if fn else None,
                "ref": found_ref, "remote": pair[0], "branch": pair[1],
                "basis": "by_config",
                "why": (f"удалённый назван ИМЕНЕМ {pair[0]!r} — личность решает "
                        f".git/config той копии, где зов исполнится"),
                # Три исхода, а не два: подкоманда, которую прибор не разрешил,
                # не есть «не мутирует». Инвариант #17 — про ПРЕДСТАВЛЕНИЕ
                # отсутствия наблюдения, и здесь цена разная: читающий зов на
                # стухшем кэше печатает неверное число, мутирующий переписывает
                # дерево на чужую ревизию.
                "mutating": (None if sub is None else sub in MUTATORS),
                "sub": sub, "via": via, "mod": m, "node": node,
                "stmt": stmt_of.get(node), "fnode": fn})
    return readers, outer


def _call_sites(mods, mod_rel, func_name):
    """Зовы функции — в ЕЁ ЖЕ модуле.

    Граница названа вслух: межмодульных вызывающих прибор не ищет, и там, где
    их нет в своём модуле, дорога «каждый зов господствуем» просто не даёт
    доказательства — то есть ошибается В СТОРОНУ отказа, а не допуска."""
    out = []
    for m in mods:
        if m.rel != mod_rel:
            continue
        owner = m.owner
        for node in m.calls:
            if _callee_name(node) == func_name:
                fn = owner.get(node)
                if fn is not None and fn.name == func_name:
                    continue
                out.append({"line": node.lineno, "func": fn.name if fn else None,
                            "mod": m, "node": node,
                            "fnode": fn})
    return out


def _updater_writes(inv, remotes):
    """Какую ссылку освежает обновитель: (имя удалённого | None, ветки | '*')."""
    toks = inv["tokens"]
    if inv["sub"] not in toks:
        return None, None, "by_var"
    tail = [t for t in toks[toks.index(inv["sub"]) + 1:] if not t.startswith("-")]
    if not tail:
        return "origin", "*", "by_config"          # умолчание конфига
    first = tail[0]
    if first == DYN:
        return None, None, "by_var"
    if URL_RE.match(first):
        # URL без refspec'а НЕ пишет в кэш вовсе (только FETCH_HEAD) —
        # различение не придирка, а разница между «освежил» и «не освежил».
        return None, None, "by_url"
    if first not in remotes:
        return "origin", "*", "by_config"
    specs = tail[1:]
    if not specs:
        return first, "*", "by_config"
    branches = set()
    for spec in specs:
        if spec == DYN:
            return first, None, "by_config"
        src, _, dst = spec.partition(":")
        branches.add(src)
    return first, branches, "by_config"


def _gated_in_context(inv) -> bool:
    """Прекращает ли отказ обновителя путь — с учётом контекста присваивания."""
    g = inv["gating"]
    if g is True:
        return True
    if not isinstance(g, str):
        return False
    # Результат связан именем: ищем чтение `.returncode` с обрывом пути — но
    # ТОЛЬКО ДО ТОГО, как имя переприсвоено.
    #
    # Оговорка не теоретическая, и на ней прибор поймал сам себя (цикл #583).
    # `scripts/deploy_site_snapshot.py`:
    #
    #     r = subprocess.run([... "fetch" ...])      # 118
    #     r = subprocess.run([... "show", "origin/main:…"])   # 120
    #     if r.returncode != 0: return True          # 122
    #
    # Код возврата ФЕТЧА не читает никто: строка 122 судит о `show`. Первая
    # редакция искала `if <имя>.returncode` где угодно в функции, находила 122 и
    # объявляла зов ДОКАЗАННО СВЕЖИМ — то есть ровно «asked_not_gated», выданное
    # за «asked_and_gated». Тень имени тише, чем отсутствие проверки: проверка
    # есть, она просто не про этот вызов.
    fn = inv["func"]
    if fn is None:
        return False
    start = inv["stmt"].lineno if inv["stmt"] is not None else inv["line"]
    rebind = min(
        (n.lineno for n in ast.walk(fn)
         if isinstance(n, ast.Assign) and n.lineno > start
         and any(isinstance(t, ast.Name) and t.id == g for t in n.targets)),
        default=None)
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or node.lineno <= start:
            continue
        if rebind is not None and node.lineno >= rebind:
            continue
        reads = any(isinstance(n, ast.Attribute) and n.attr == "returncode"
                    and isinstance(n.value, ast.Name) and n.value.id == g
                    for n in ast.walk(node.test))
        if reads and any(isinstance(n, (ast.Raise, ast.Return))
                         for n in ast.walk(node)):
            return True
    return False


def dominating_updater(updaters, reader, mods, remotes, _seen=None):
    """Обновитель, про который ДОКАЗАНО, что он исполнился до зова.

    Две дороги, и вторая обязательна: без неё повторилась бы ложная находка
    ADR-361 на `code_sync_from_origin.sh` — читатели выше обновителя по
    СТРОКАМ и позже него по ИСПОЛНЕНИЮ."""
    _seen = _seen or set()
    same = [u for u in updaters
            if u["mod"].rel == reader["mod"].rel
            and u["func_name"] == reader.get("func")
            and u["line"] < reader["line"]
            and _unconditional(u["stmt"], _stmt_index(u["func"]))
            and _writes_this_ref(u, reader, remotes)]
    if same:
        return same[-1], (f"обновитель строкой {same[-1]['line']} в той же "
                          f"функции, безусловно")

    fname = reader.get("func")
    key = (reader["mod"].rel, fname)
    if fname and key not in _seen:
        sites = _call_sites(mods, reader["mod"].rel, fname)
        if sites:
            chain = []
            for site in sites:
                probe = {"mod": site["mod"], "line": site["line"],
                         "func": site["func"], "fnode": site["fnode"],
                         "remote": reader.get("remote"),
                         "branch": reader.get("branch")}
                got, _why = dominating_updater(updaters, probe, mods, remotes,
                                               _seen | {key})
                if not got:
                    break
                chain.append((site, got))
            else:
                site, got = chain[0]
                return got, (f"обновитель строкой {got['line']}: {fname}() "
                             f"зовётся строкой {site['line']}, и каждый её зов "
                             f"({len(sites)}) господствуем")
    return None, None


def _writes_this_ref(updater, reader, remotes) -> bool:
    name, branches, _basis = _updater_writes(updater, remotes)
    if name is None:
        return False
    if reader.get("remote") and name != reader["remote"]:
        return False
    if branches == "*" or branches is None:
        return branches == "*"
    return reader.get("branch") in branches


#: Модуль, в тексте которого нет НИ ОДНОГО из этих слов, не может ни завести
#: дверь к git (для неё нужен литерал `git` в argv), ни назвать remote-tracking
#: ссылку. Отбор — ради времени, а не ради сокрытия: множество строк отчёта до
#: и после отбора сверяется тестом-контролем, иначе «быстрее» означало бы
#: «меряем меньше и не говорим об этом».
PRESCREEN = ("git", "origin", "refs/remotes")


def census(root: Path) -> dict:
    files = python_files(root)
    if not files:
        return {"unmeasured_fatal": f"в {root} не найдено ни одного .py — "
                                    "мерить нечего; это НЕ «чисто»"}
    mods, unread, screened = [], [], 0
    for path, rel in files:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:                          # noqa: BLE001
            unread.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        if not any(w in src for w in PRESCREEN):
            screened += 1
            continue
        try:
            mods.append(ModuleScan(path, rel, ast.parse(src), src))
        except Exception as exc:                          # noqa: BLE001
            unread.append(f"{rel}: {type(exc).__name__}: {exc}")
    inherit = inherited_params(mods)
    invocations, doors = collect(mods, inherit)
    remotes = known_remotes(invocations)
    updaters = [i for i in invocations if i["sub"] in UPDATERS]
    readers, outer = find_readers(mods, doors, remotes, module_index(mods),
                                  inherit)

    rows = []
    for r in readers:
        if r["verdict"] == "unmeasured" if "verdict" in r else False:
            rows.append({k: r[k] for k in
                         ("file", "line", "func", "ref", "basis", "verdict",
                          "mutating", "sub", "why")})
            continue
        got, why = dominating_updater(updaters, r, mods, remotes)
        if got is None:
            verdict = "cache_only"
            note = ("обновителя, про который доказано, что он исполнился до "
                    "зова и освежил ИМЕННО эту ссылку, на пути нет")
        elif _gated_in_context(got):
            verdict, note = "asked_and_gated", why
        else:
            verdict = "asked_not_gated"
            note = (f"{why}, но его ОТКАЗ ничего не прекращает: результат "
                    f"{got['runner']}(…) не гейтит путь — при недоступной сети "
                    f"зов читает кэш")
        rows.append({"file": r["file"], "line": r["line"], "func": r.get("func"),
                     "ref": r["ref"], "basis": r["basis"], "verdict": verdict,
                     "mutating": r["mutating"], "sub": r.get("sub"),
                     "why": f"{r['why']}; {note}" if verdict != "asked_and_gated"
                            else f"{r['why']}; {note}"})
    rows.sort(key=lambda x: (x["file"], x["line"]))
    return {"root": str(root), "files": len(files), "modules": len(mods),
            "screened_out": screened,
            "remotes": sorted(remotes), "doors": len(doors),
            "invocations": len(invocations), "updaters": len(updaters),
            "rows": rows, "outer": outer, "unread": unread}


def subject_keys(rows) -> list:
    """Предмет ЭТОГО прибора — ось СВЕЖЕСТИ, и только она (как в ADR-361)."""
    return sorted({f"{r['file']}:{r['line']}" for r in rows
                   if r["verdict"] in ("asked_not_gated", "cache_only",
                                       "unmeasured")})


ORDER = ["asked_and_gated", "asked_not_gated", "cache_only", "unmeasured"]
TITLE = {"asked_and_gated": "СПРОШЕНО У СЕРВЕРА, и отказ прекращает путь",
         "asked_not_gated": "спрос есть, но его ОТКАЗ ничего не прекращает "
                            "(при недоступной сети — кэш)",
         "cache_only": "спроса нет вовсе — читается КЭШ",
         "unmeasured": "НЕ ИЗМЕРЕНО"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="ЗАКАЗ #583: origin/main из python — кэш или вопрос к серверу")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", default=None,
                    help="храповик: файл с замороженным предметом")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    rep = census(root)

    if "unmeasured_fatal" in rep:
        msg = f"⛔ НЕ ИЗМЕРЕНО: {rep['unmeasured_fatal']}"
        if args.json:
            # stdout остаётся РОВНО одним документом, но человеческая строка
            # обязана прозвучать: иначе в json-режиме отказ выглядит молчанием.
            print(json.dumps({"unmeasured": rep["unmeasured_fatal"]},
                             ensure_ascii=False))
            print(msg, file=sys.stderr)
        else:
            print(msg)
        return 2

    rows = rep["rows"]
    subject = subject_keys(rows)
    groups = {}
    for r in rows:
        groups.setdefault(r["verdict"], []).append(r)
    by_basis = {b: sum(1 for r in rows if r["basis"] == b)
                for b in ("by_url", "by_config", "by_var")}
    proven_both = [f"{r['file']}:{r['line']}" for r in rows
                   if r["verdict"] == "asked_and_gated" and r["basis"] == "by_url"]

    frozen, ratchet_err = None, None
    if args.baseline:
        bp = Path(args.baseline)
        if not bp.is_file():
            ratchet_err = f"базы храповика нет: {args.baseline!r}"
        else:
            try:
                frozen = sorted(set(json.loads(bp.read_text("utf-8"))["subject"]))
            except Exception as exc:                      # noqa: BLE001
                ratchet_err = f"база храповика не разобрана ({exc})"

    # `--json` печатает РОВНО один документ; человеческие строки — в stderr.
    def say(msg):
        print(msg, file=sys.stderr if args.json else sys.stdout)

    if args.json:
        print(json.dumps({
            "root": rep["root"], "files": rep["files"], "remotes": rep["remotes"],
            "modules": rep["modules"], "screened_out": rep["screened_out"],
            "doors": rep["doors"], "git_invocations": rep["invocations"],
            "outer_wrapper_sites": len(rep["outer"]),
            "updaters": rep["updaters"], "reads": len(rows),
            "by_verdict": {k: len(groups.get(k, [])) for k in ORDER},
            "by_basis": by_basis,
            "mutating": sum(1 for r in rows if r["mutating"] is True),
            "mutating_unmeasured": sum(1 for r in rows if r["mutating"] is None),
            "proven_both_axes": proven_both,
            "subject": subject, "unread": rep["unread"],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"origin/main ИЗ PYTHON: кэш или вопрос к серверу — мерено из "
              f"{rep['root']!r}")
        print(f"  модулей прочитано: {rep['modules']} · дверей к git: "
              f"{rep['doors']} · зовов git: {rep['invocations']} · из них "
              f"обновителей: {rep['updaters']}")
        print(f"  имена удалённых: {', '.join(rep['remotes'])}")
        print(f"  зовов, ЧИТАЮЩИХ remote-tracking ссылку: {len(rows)} "
              f"(мутирующих: {sum(1 for r in rows if r['mutating'] is True)} · "
              f"мутирование НЕ ИЗМЕРЕНО у "
              f"{sum(1 for r in rows if r['mutating'] is None)})\n")
        for key in ORDER:
            grp = groups.get(key, [])
            print(f"── {TITLE[key]}: {len(grp)}")
            for r in grp:
                mark = ("МУТИРУЕТ" if r["mutating"] is True else
                        "читает" if r["mutating"] is False else
                        "мутирование НЕ ИЗМЕРЕНО")
                print(f"   {r['file']}:{r['line']}  [{r['basis']}] {mark} "
                      f"{r['ref']} ({r['sub']}) — {r['why'][:150]}")
            print()
        print(f"основание личности удалённого: by_url={by_basis['by_url']} "
              f"(путешествует) · by_config={by_basis['by_config']} (решает "
              f".git/config той копии) · by_var={by_basis['by_var']} (не измерено)")
        print(f"ДОКАЗАНО ПО ОБЕИМ ОСЯМ: {len(proven_both)} из {len(rows)}"
              + (" — " + ", ".join(proven_both) if proven_both else ""))

    if rep["unread"]:
        say(f"⛔ НЕ ИЗМЕРЕНО: {len(rep['unread'])} файл(ов) не прочитаны — "
            f"{rep['unread'][0]}")
        return 2
    if ratchet_err:
        say(f"\n⛔ НЕ ИЗМЕРЕНО: {ratchet_err} — «нет базы» не есть «чисто»")
        return 2

    if frozen is not None:
        new = [k for k in subject if k not in frozen]
        if new:
            say(f"\n🔴 ХРАПОВИК: предмет ВЫРОС на {len(new)} — " + ", ".join(new))
            return 3
        gone = [k for k in frozen if k not in subject]
        if gone:
            say(f"\n🟢 предмет сократился на {len(gone)}: " + ", ".join(gone)
                + " — обнови базу")
        say("\n✅ храповик: предмет не вырос")
        return 0

    if subject:
        say(f"\n🔴 ПРЕДМЕТ НЕПУСТ: {len(subject)} зов(ов) читают ссылку, "
            "свежесть которой не доказана")
        return 3
    say("\n✅ предмет пуст")
    return 0


if __name__ == "__main__":
    sys.exit(main())
