#!/usr/bin/env python3
"""ПОЛОВИНА инъекции часов: отметка наблюдения приходит из ``mtime`` ФАЙЛА.

Зачем
------------------------------------------------------------------------------
Правило ``.claude/rules/deployment.md`` (§ «Время в тестах», приём №1) закрывает дверь
``datetime.now()`` ВНУТРИ процесса: сцена передаёт ``now`` аргументом и закрепляет свои
отметки якорем. Девятая дверь семейства (``_subprocess_clock_door``, ADR-897) закрыла
ту же дверь ЗА границей процесса. Остаётся третья, и она не в коде, а в ФАЙЛОВОЙ
СИСТЕМЕ: отметку, которую продукционный код берёт из ``st_mtime``, ставит ОС стенными
часами — и если сцена её не закрепила, одна сторона сравнения прибита к якорю, а вторая
уезжает с календарём.

Предмет найден падением, а не разбором (цикл #1232, ADR-1086): сцена
``test_mission_control_contract.py`` пиновала КАЖДУЮ свою текстовую отметку от якоря
``NOW``, а отметку архива резерва модель берёт из ``mtime`` файла — её сцена оставляла
стенным часам. 24.11 разрыв «якорь ↔ календарь» дал **девять** красных имён на ``main``
при неизменных байтах теста.

**Сторож претязания ``FROZEN-DATE-OK: injected-clock`` (цикл #477) этот класс НЕ видит
ПО ПОСТРОЕНИЮ:** он разбирает AST ОДНОГО файла и подтверждает претензию, найдя
``now=NOW`` у вызова, — а вторая сторона сравнения приходит из ``stat()``. Притязание
бывает верным по AST и ложным по предмету.

Что отвечает прибор и чего он НЕ отвечает
------------------------------------------------------------------------------
**Поверхность класса НЕ ЕСТЬ класс.** Сцена, создающая файл, чей ``mtime`` никто не
читает как ВОЗРАСТ, бомбой не является; назвать всю поверхность находками значило бы
выдать поверхность за класс, а назвать одну починенную бомбу классом — выдать
неизвестное за ноль (замер карточки
``inbox-polovina-inektsii-chasov-mtime-stseny-ne``: ``st_mtime`` читают 102 места в
68 файлах продукции — это ВЕРХНЯЯ граница носителей, а не класс).

``--surface`` (умолчание)
    Разбор AST: какие тест-файлы (а) выписали себе претензию ``injected-clock`` и
    (б) СОЗДАЮТ файлы на диске. Рядом считается третья ось — пинует ли сцена
    ``mtime`` вообще (``os.utime`` с ЯВНЫМИ временами). «Не пинует» это ещё не бомба,
    но это и есть место, где претензия НЕ ИЗМЕРЕНА для ЭТОЙ двери.

``--differential``
    Замер КЛАССА методом § «ЛИЧНОСТЬ ПРОЦЕССА» / § «GIT-ОКРУЖЕНИЕ» того же правила, в
    три ступени:

    1. **база** — как есть;
    2. **сдвиг НЕЗАПИНОВАННЫХ отметок** — тест, сменивший вердикт, есть КАНДИДАТ;
    3. **перемер без сдвига** — смена не вернулась ⇒ **НЕ ИЗМЕРЕНО** (шумный тест), а
       не находка (инв. #17).

Почему возмущение ТОЧНОЕ, а не эвристика
------------------------------------------------------------------------------
Двигать ``st_mtime`` у ВСЕХ файлов сцены нельзя: сцена, которая отметку ЗАКРЕПИЛА,
сменила бы вердикт тоже, и прибор назвал бы находкой починенный код. Поэтому у
возмущения ДВЕ двери, и обе единственные:

* ``os.utime`` — через неё и ТОЛЬКО через неё сцена закрепляет отметку. Плагин
  запоминает пути, которым сцена дала ЯВНЫЕ времена. ``os.utime(p, None)`` пином НЕ
  считается: это штамп СТЕННЫМИ часами, то есть ровно предмет класса;
* ``os.stat`` / ``os.lstat`` — через них (и только через них) идут
  ``Path.stat``, ``Path.lstat``, ``os.path.getmtime`` и ``os.path.getctime``. Сдвиг
  применяется к пути, который (а) лежит под НАЗВАННЫМ корнем сцены и (б) НЕ пинован.

Отсюда и контроль в обе стороны у самого прибора: байты
``test_mission_control_contract.py`` ДО ADR-1086 (отметка архива не пинована) обязаны
дать находку, а ПОСЛЕ (``_stamp(arch, NOW - 10 мин)`` зовёт ``os.utime`` с явными
временами) — не дать.

Канарейка прозрачности (урок ADR-898)
------------------------------------------------------------------------------
Подмена ``os.stat`` обязана вернуть РОВНО ``os.stat_result``, иначе чужой код
сломается от прибора, и его возмущение будет прочитано как класс. Поэтому плагин ДО
сцен прогоняет канарейку на двух своих файлах (пинованный — не сдвинут · непинованный
— сдвинут · тип сохранён) и пишет вердикт в файл. Канарейка не сошлась ⇒ ответа о
классе НЕТ (``unmeasured``, код 2), кандидаты печатаются поимённо КАК КАНДИДАТЫ.

Три исхода (инв. #17)
------------------------------------------------------------------------------
Код возврата: **0** — измерено, класс ПУСТ · **1** — измерено, класс НЕ ПУСТ (имена
названы) · **2** — НЕ ИЗМЕРЕНО с названной причиной. Файл, который не прочитан или не
разобран, получает ``unmeasured`` поимённо и НИКОГДА не считается «прошедшим».

Направление сдвига — ВХОД, и класс есть ОБЪЕДИНЕНИЕ двух прогонов
------------------------------------------------------------------------------
Умолчание — НАЗАД (``--shift-days -400``): файл выглядит СТАРЫМ, и это читает любой
срок свежести. Сдвиг ВПЕРЁД (``--shift-days 400``) — отметка «из будущего», предмет
ADR-1085.

**Одного направления классу НЕ ХВАТАЕТ, и это ИЗМЕРЕНО** (замер #1233 на настоящей
сцене ADR-1086 со снятым пином): НАЗАД она даёт **4** смены вердикта — и смена идёт
``FAILED → PASSED``, потому что в своей аварийной форме сцена красна УЖЕ НА БАЗЕ, а
сдвиг назад её ЛЕЧИТ; ВПЕРЁД — **НОЛЬ**, дальше в будущее она уже красна. Поэтому
«член» определён как ЛЮБАЯ смена вердикта (а не как «позеленел» или «покраснел»), и
полный ответ о классе есть ОБЪЕДИНЕНИЕ прогонов в оба направления. Прогон в одну
сторону отвечает на СВОЙ вопрос, а не на нужный.

Где он живёт и почему не в ``scripts/``
------------------------------------------------------------------------------
Рядом со сверстниками — ``_subprocess_clock_door.py``, ``_injected_clock.py``,
``_freshness.py``: это ПОМОЩНИК набора с настоящим импортёром (батарея
``test_mtime_clock_door_census.py``), а не точка входа без вызывающего (первая редакция
сверстника лежала в ``scripts/`` и честно покрасила ``test_unwired_scripts_ratchet``).
Руками зовётся как модуль::

    python3 -m spa_core.tests._mtime_clock_door --surface
    python3 -m spa_core.tests._mtime_clock_door --differential --run-root <дерево>

ADVISORY: прибор только ЧИТАЕТ дерево и запускает pytest в УКАЗАННОМ каталоге; ни
одного файла набора он не правит.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:  # дверь притязания — ЕДИНСТВЕННАЯ, своей копии у прибора нет
    from spa_core.tests._injected_clock import claims_injected_clock
except Exception:  # pragma: no cover - ввоз двери есть предпосылка, а не поведение
    claims_injected_clock = None  # type: ignore[assignment]

#: Канонический охват — тот же, что у храповика притязания: `glob`, не `rglob`.
DEFAULT_ROOTS: tuple[str, ...] = ("spa_core/tests",)

MEASURED_EMPTY = 0
MEASURED_NONEMPTY = 1
UNMEASURED_CODE = 2

#: Вердикты ОСИ ПОВЕРХНОСТИ.
IN_SURFACE = "in_surface"        #: претензия + запись + ОДИН ХОП до читателя отметки
NO_READER = "no_reader"          #: претензия + запись, но читателя отметки не ввозит
NO_CLAIM = "no_claim"            #: якоря не объявлял — у этой двери судить нечего
NO_WRITES = "no_writes"          #: файлов не создаёт — отметки наблюдения нет
UNMEASURED = "unmeasured"        #: не прочитан / не разобран — НЕ «прошло»

#: Вердикты ОСИ КЛАССА (после дифференциального прогона).
MEMBER = "member"                #: вердикт сменился под сдвигом и вернулся без него
STABLE = "stable"                #: вердикт не дрогнул — отметка закреплена либо не читается
NOISY = "noisy"                  #: смена не вернулась — НЕ ИЗМЕРЕНО, а не находка

#: Имена методов/функций, которыми сцена СОЗДАЁТ файл на диске.
_WRITE_ATTRS = frozenset({
    "write_text", "write_bytes", "touch", "dump", "writestr", "write",
    "copy", "copy2", "copyfile", "copytree", "move", "make_archive",
})
_WRITE_FUNCS = frozenset({
    "open", "mkstemp", "NamedTemporaryFile", "TemporaryFile",
})
#: Чтение отметки файла — третья, ОСВЕДОМИТЕЛЬНАЯ ось (не входит в поверхность).
_MTIME_READS = ("st_mtime", "getmtime", "getctime", "st_ctime")


# --- ось 1: поверхность ----------------------------------------------------
def _is_write_mode(node: ast.Call) -> bool:
    """``open(path, "w")`` — запись; ``open(path)`` и ``open(path, "r")`` — нет."""
    args = list(node.args) + [kw.value for kw in node.keywords if kw.arg == "mode"]
    for a in args[1:]:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            if any(ch in a.value for ch in "wxa+"):
                return True
    return False


def writes_files(tree: ast.AST) -> list[int]:
    """Строки, на которых сцена создаёт файл. Пусто ⇒ отметки наблюдения нет."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute):
            if fn.attr in _WRITE_ATTRS:
                lines.append(node.lineno)
            continue
        if isinstance(fn, ast.Name):
            if fn.id == "open":
                if _is_write_mode(node):
                    lines.append(node.lineno)
            elif fn.id in _WRITE_FUNCS:
                lines.append(node.lineno)
    return sorted(set(lines))


def pins_mtime(tree: ast.AST) -> list[int]:
    """Строки, где сцена закрепляет отметку ЯВНЫМИ временами.

    ``os.utime(p, None)`` и ``os.utime(p)`` пином НЕ считаются: это штамп СТЕННЫМИ
    часами, то есть ровно предмет класса, а не выход из него.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name != "utime":
            continue
        explicit = [a for a in node.args[1:]]
        explicit += [kw.value for kw in node.keywords if kw.arg in {"times", "ns"}]
        if any(not (isinstance(a, ast.Constant) and a.value is None) for a in explicit):
            lines.append(node.lineno)
    return sorted(set(lines))


@dataclass
class FileVerdict:
    """Вердикт о ФАЙЛЕ по оси поверхности (и, после прогона, по оси класса)."""
    path: str
    surface: str
    reason: str = ""
    write_lines: tuple[int, ...] = ()
    pin_lines: tuple[int, ...] = ()
    reads_mtime: bool = False
    reader_hits: tuple[str, ...] = ()
    klass: str = ""
    changed: tuple[str, ...] = field(default_factory=tuple)

    def as_json(self) -> dict:
        return {
            "path": self.path,
            "surface": self.surface,
            "reason": self.reason,
            "write_lines": list(self.write_lines),
            "pin_lines": list(self.pin_lines),
            "reads_mtime": self.reads_mtime,
            "reader_hits": list(self.reader_hits),
            "class": self.klass,
            "changed": list(self.changed),
        }


def measure_surface(repo_root: Path,
                    roots: tuple[str, ...] = DEFAULT_ROOTS,
                    *, readers: set[str] | None = None) -> list[FileVerdict]:
    """Поверхность класса. Нечитаемый файл — ``unmeasured`` ПОИМЁННО, не пропуск.

    ``_injected_clock.claiming_files`` здесь НЕ зовётся намеренно: он глотает
    нечитаемый файл молча (``except: continue``), и «не прочитан» стало бы
    неотличимо от «претензии не заявлял» — инв. #17 на входе собственного замера.
    """
    if claims_injected_clock is None:
        raise RuntimeError("дверь притязания не ввезена: spa_core.tests._injected_clock")
    if readers is None:
        readers, reader_unmeasured = mtime_reader_modules(repo_root)
    else:
        reader_unmeasured = []
    out: list[FileVerdict] = [
        FileVerdict(path=u.split(":", 1)[0], surface=UNMEASURED,
                    reason=f"читатель отметки не разобран: {u}")
        for u in reader_unmeasured
    ]
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            out.append(FileVerdict(path=root, surface=UNMEASURED,
                                   reason=f"каталог не найден: {base}"))
            continue
        for f in sorted(base.glob("test_*.py")):
            rel = str(f.relative_to(repo_root))
            try:
                src = f.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 — нечитаемость это ИСХОД
                out.append(FileVerdict(path=rel, surface=UNMEASURED,
                                       reason=f"файл не прочитан: {exc}"))
                continue
            if not claims_injected_clock(src):
                out.append(FileVerdict(path=rel, surface=NO_CLAIM))
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                out.append(FileVerdict(path=rel, surface=UNMEASURED,
                                       reason=f"не разобран: {exc}"))
                continue
            writes = tuple(writes_files(tree))
            pins = tuple(pins_mtime(tree))
            reads = any(tok in src for tok in _MTIME_READS)
            if not writes:
                out.append(FileVerdict(path=rel, surface=NO_WRITES, pin_lines=pins,
                                       reads_mtime=reads))
                continue
            hits = tuple(reaches_a_reader(imported_modules(tree), readers))
            kind = IN_SURFACE if hits else NO_READER
            out.append(FileVerdict(path=rel, surface=kind, write_lines=writes,
                                   pin_lines=pins, reads_mtime=reads,
                                   reader_hits=hits))
    return out


# --- ось 1б: ОДИН ХОП до читателя отметки ----------------------------------
#: Каталоги продукции, в которых ищется читатель отметки файла.
PRODUCTION_ROOTS: tuple[str, ...] = ("spa_core", "scripts")


def _reads_mtime_source(tree: ast.AST) -> bool:
    """Модуль читает отметку ФАЙЛА? ``st_mtime``/``st_ctime`` либо ``get*time``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {
                "st_mtime", "st_mtime_ns", "st_ctime", "st_ctime_ns"}:
            return True
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in {"getmtime", "getctime"}:
                return True
    return False


def mtime_reader_modules(repo_root: Path) -> tuple[set[str], list[str]]:
    """Точечные имена продукционных модулей, читающих отметку файла.

    Возвращает (имена, НЕ ИЗМЕРЕНО поимённо). Тесты исключены намеренно: предмет —
    отметка, которую читает ПРОДУКЦИЯ, а не собственная проверка сцены.
    """
    names: set[str] = set()
    unmeasured: list[str] = []
    for root in PRODUCTION_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            unmeasured.append(f"{root}: каталог не найден")
            continue
        for f in sorted(base.rglob("*.py")):
            rel = f.relative_to(repo_root)
            if "tests" in rel.parts:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — нечитаемость это ИСХОД
                unmeasured.append(f"{rel}: {exc}")
                continue
            if _reads_mtime_source(tree):
                dotted = ".".join(rel.with_suffix("").parts)
                names.add(dotted)
    return names, unmeasured


def imported_modules(tree: ast.AST) -> set[str]:
    """Точечные имена, которые файл ВВОЗИТ (оба написания импорта)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.add(node.module)
                for a in node.names:
                    out.add(f"{node.module}.{a.name}")
    return out


def reaches_a_reader(imports: set[str], readers: set[str]) -> list[str]:
    """Названные ввозы, которые ЕСТЬ читатель отметки (ровно ОДИН хоп).

    Население за границей одного хопа НЕ ИЗМЕРЕНО — та же граница, что у сторожа
    притязания ``injected-clock`` и у переписи производных артефактов (ADR-1074).
    """
    hits = sorted(i for i in imports if i in readers)
    return hits


# --- ось 2: возмущение -----------------------------------------------------
def plugin_source() -> str:
    """Плагин pytest: ДВЕ единственные двери — ``os.utime`` (пин) и ``os.stat`` (чтение).

    Плагин живёт в ТОМ ЖЕ процессе, что сцены (в отличие от сверстника про подпроцесс),
    поэтому подмена идёт по месту и ``sitecustomize`` не нужен.
    """
    return (
        "import os\n"
        "import sys\n"
        "import json\n"
        "import tempfile\n"
        "_SHIFT = float(os.environ['SPA_MTIME_SHIFT_DAYS']) * 86400.0\n"
        "_CANARY = os.environ.get('SPA_MTIME_CANARY_FILE', '')\n"
        "_PINNED = set()\n"
        "_orig_utime = os.utime\n"
        "_orig_stat = os.stat\n"
        "_orig_lstat = os.lstat\n"
        "_orig_realpath = os.path.realpath\n"
        # Корни считаются ДО подмены и БЕЗ неё: `realpath` зовёт `os.lstat`, и
        # если корень (или ключ пути) считать уже подменённой дверью, обёртка
        # уйдёт в рекурсию через саму себя. Замер #1233: такой зов держал
        # тривиальную сцену ВОСЕМЬ минут и выглядел зависанием, а не дефектом.
        "_RAW = tuple(p for p in os.environ.get('SPA_MTIME_SHIFT_ROOTS', '')"
        ".split(os.pathsep) if p)\n"
        "_ROOTS = tuple({r for p in _RAW for r in"
        " (os.path.abspath(p), _orig_realpath(p))})\n"
        "def _key(path):\n"
        "    if isinstance(path, int):\n"
        "        return None\n"
        "    try:\n"
        "        return os.path.abspath(os.fspath(path))\n"
        "    except Exception:\n"
        "        return None\n"
        "def _under(k):\n"
        "    return any(k == r or k.startswith(r + os.sep) for r in _ROOTS)\n"
        "def _utime(path, times=None, **kw):\n"
        "    explicit = times is not None or kw.get('ns') is not None\n"
        "    k = _key(path)\n"
        "    if explicit and k is not None:\n"
        "        _PINNED.add(k)\n"
        "    return _orig_utime(path, times, **kw)\n"
        "def _shift(st):\n"
        "    base = list(st[:10])\n"
        "    base[8] = int(base[8] + _SHIFT)\n"
        "    extra = {'st_atime': st.st_atime, 'st_ctime': st.st_ctime,\n"
        "             'st_mtime': st.st_mtime + _SHIFT,\n"
        "             'st_atime_ns': st.st_atime_ns, 'st_ctime_ns': st.st_ctime_ns,\n"
        "             'st_mtime_ns': int(st.st_mtime_ns + _SHIFT * 1e9)}\n"
        "    for name in ('st_birthtime',):\n"
        "        if hasattr(st, name):\n"
        "            extra[name] = getattr(st, name)\n"
        "    return os.stat_result(tuple(base), extra)\n"
        "_BUSY = set()\n"
        "def _wrap(orig):\n"
        "    def _f(path, *a, **kw):\n"
        "        st = orig(path, *a, **kw)\n"
        "        ident = id(_f)\n"
        "        if ident in _BUSY:\n"
        "            return st\n"
        "        _BUSY.add(ident)\n"
        "        try:\n"
        "            k = _key(path)\n"
        "            if k is not None and _under(k) and k not in _PINNED:\n"
        "                return _shift(st)\n"
        "            return st\n"
        "        finally:\n"
        "            _BUSY.discard(ident)\n"
        "    return _f\n"
        "os.utime = _utime\n"
        "os.stat = _wrap(_orig_stat)\n"
        "os.lstat = _wrap(_orig_lstat)\n"
        "def _canary():\n"
        "    out = {'ok': False, 'checks': {}}\n"
        "    try:\n"
        "        d = tempfile.mkdtemp(prefix='spa_mtime_canary_', dir=_ROOTS[0])\n"
        "        free = os.path.join(d, 'free'); pinned = os.path.join(d, 'pinned')\n"
        "        for p in (free, pinned):\n"
        "            with open(p, 'w') as fh:\n"
        "                fh.write('x')\n"
        "        raw_free = _orig_stat(free).st_mtime\n"
        "        at = raw_free - 1234.0\n"
        "        os.utime(pinned, (at, at))\n"
        "        seen_free = os.stat(free)\n"
        "        seen_pin = os.stat(pinned)\n"
        "        out['checks']['type_preserved'] = type(seen_free) is os.stat_result\n"
        "        out['checks']['free_shifted'] = abs(\n"
        "            (seen_free.st_mtime - raw_free) - _SHIFT) < 1.0\n"
        "        out['checks']['pinned_untouched'] = abs(seen_pin.st_mtime - at) < 1.0\n"
        "        out['checks']['getmtime_follows'] = abs(\n"
        "            os.path.getmtime(free) - seen_free.st_mtime) < 1.0\n"
        "        from pathlib import Path as _P\n"
        "        out['checks']['pathlib_follows'] = abs(\n"
        "            _P(free).stat().st_mtime - seen_free.st_mtime) < 1.0\n"
        "        out['ok'] = all(out['checks'].values())\n"
        "    except Exception as exc:\n"
        "        out['error'] = repr(exc)\n"
        "    if _CANARY:\n"
        "        with open(_CANARY, 'w') as fh:\n"
        "            json.dump(out, fh)\n"
        "    return out\n"
        "_CANARY_RESULT = _canary()\n"
        "if not _CANARY_RESULT.get('ok'):\n"
        "    print('[прибор] КАНАРЕЙКА НЕ СОШЛАСЬ: ' + json.dumps(_CANARY_RESULT),\n"
        "          file=sys.stderr, flush=True)\n"
    )


def materialise_plugin(target: Path) -> Path:
    """Выложить плагин в каталог. Возвращает путь файла плагина."""
    target.mkdir(parents=True, exist_ok=True)
    plugin = target / "spa_mtime_shift_plugin.py"
    plugin.write_text(plugin_source(), encoding="utf-8")
    return plugin


def _parse_outcomes(stdout: str) -> dict[str, str]:
    """Вердикт на nodeid из ``-v`` вывода pytest. ``SKIPPED`` различается намеренно.

    Урок #465: в дифференциальном замере тест, ушедший в ``skipped``, не краснеет и не
    проходит — он ИСЧЕЗАЕТ, и глазами это читается как «всё в порядке».
    """
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "::" in parts[0]:
            verdict = parts[1].rstrip(",")
            if verdict in {"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS",
                           "SUBFAILED", "SUBFAIL"}:
                out[parts[0]] = verdict
    return out


def default_shift_roots() -> tuple[str, ...]:
    """Корень сдвига по УМОЛЧАНИЮ — системный каталог временных файлов.

    Он ВХОД, а не константа: иначе «сдвигаем только сцену» нечем проверить по
    исходу — мутация «сдвигать ЛЮБОЙ путь» ВЫЖИЛА у первой редакции батареи
    (замер #1233), потому что проверка смотрела в исходник, а не на поведение.
    """
    return (os.path.realpath(tempfile.gettempdir()),)


def _run_pytest(tree_root: Path, files: list[str], *, shift_days: float | None,
                workdir: Path, timeout_s: int, label: str = "",
                shift_roots: tuple[str, ...] | None = None
                ) -> tuple[dict[str, str], str, dict]:
    """Один прогон. ``shift_days=None`` ⇒ отметки файлов НЕ сдвинуты.

    ``-q`` здесь НЕТ намеренно: он погасил бы ``-v``, вердикты по ``nodeid`` в вывод не
    попали бы вовсе, и пустой разбор был бы прочитан как «вердиктов нет». Прогресс
    печатается в ``stderr`` без буфера — долгий прогон обязан быть ВИДЕН
    (``.claude/rules/deployment.md``, § окна мутационного прибора, п. 8).
    """
    env = dict(os.environ)
    env["SPA_ENV"] = "ci"
    env["PYTHONHASHSEED"] = "0"
    # Маркер ПЕСОЧНИЦЫ (ADR-580): читатель без своего `data_dir` иначе молча уводит
    # чтение/запись в ПРОД через `live_paths.DEFAULT_LIVE_ROOT`.
    env["SPA_SANDBOX"] = "1"
    env["SPA_LIVE_ROOT"] = str(tree_root)
    env["SPA_DATA_DIR"] = str(tree_root / "data")
    basetemp = workdir / f"bt_{label or 'run'}"
    argv = [sys.executable, "-u", "-m", "pytest", "-v", "-p", "no:randomly", *files,
            "--rootdir", str(Path(tree_root).resolve()),
            "--basetemp", str(basetemp)]
    canary: dict = {}
    canary_file = workdir / f"canary_{label or 'run'}.json"
    if shift_days is not None:
        plugin = materialise_plugin(workdir)
        env["SPA_MTIME_SHIFT_DAYS"] = str(shift_days)
        # Корень сдвига НАЗВАН и ПЕЧАТАЕТСЯ: молча подставленный корень не отличить
        # от «сдвигаем всё». Файлы вне корня не сдвигаются — названная граница.
        roots = tuple(shift_roots) if shift_roots else default_shift_roots()
        env["SPA_MTIME_SHIFT_ROOTS"] = os.pathsep.join(roots)
        print(f"[прибор] корень сдвига: {' · '.join(roots)}", file=sys.stderr,
              flush=True)
        env["SPA_MTIME_CANARY_FILE"] = str(canary_file)
        parts = [str(workdir)]
        if env.get("PYTHONPATH"):
            parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(parts)
        argv[5:5] = ["-p", plugin.stem]
    print(f"[прибор] прогон {label or 'без метки'}: файлов {len(files)}, "
          f"сдвиг отметок {shift_days}", file=sys.stderr, flush=True)
    proc = subprocess.run(argv, cwd=str(tree_root), env=env, capture_output=True,
                          text=True, timeout=timeout_s)
    outcomes = _parse_outcomes(proc.stdout)
    if shift_days is not None:
        try:
            canary = json.loads(canary_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — отсутствие канарейки это ИСХОД
            canary = {"ok": False, "error": f"канарейка не прочитана: {exc}"}
    print(f"[прибор] прогон {label or 'без метки'} завершён: код {proc.returncode}, "
          f"вердиктов {len(outcomes)}", file=sys.stderr, flush=True)
    return outcomes, proc.stdout[-4000:], canary


def differential(tree_root: Path, files: list[str], *, shift_days: float,
                 workdir: Path, timeout_s: int = 1800,
                 shift_roots: tuple[str, ...] | None = None) -> dict:
    """Три ступени. Возвращает документ замера; вердикт о классе — у вызывающего."""
    roots = tuple(shift_roots) if shift_roots else default_shift_roots()
    doc: dict = {
        "files": list(files),
        "shift_days": shift_days,
        "shift_roots": list(roots),
        "stages": {},
        "candidates": {},
        "verdict": {},
        "unmeasured": [],
    }
    if not files:
        doc["unmeasured"].append({"what": "поверхность", "reason": "ни одного файла"})
        return doc
    base, base_tail, _ = _run_pytest(tree_root, files, shift_days=None,
                                     workdir=workdir, timeout_s=timeout_s, label="base")
    doc["stages"]["base"] = {"verdicts": len(base), "tail": base_tail[-1200:]}
    if not base:
        doc["unmeasured"].append({"what": "база",
                                  "reason": "pytest не выдал ни одного вердикта"})
        return doc
    shifted, shifted_tail, canary = _run_pytest(
        tree_root, files, shift_days=shift_days, workdir=workdir,
        timeout_s=timeout_s, label="shifted", shift_roots=roots)
    doc["stages"]["shifted"] = {"verdicts": len(shifted), "tail": shifted_tail[-1200:],
                                "canary": canary}
    if not canary.get("ok"):
        # Канарейка прозрачности не сошлась ⇒ ответа о классе НЕТ (урок ADR-898):
        # кандидаты печатаются КАК КАНДИДАТЫ, а не как члены класса.
        doc["unmeasured"].append({
            "what": "канарейка прозрачности",
            "reason": f"подмена os.stat не прозрачна: {json.dumps(canary, ensure_ascii=False)}",
        })
    changed = sorted(n for n in set(base) | set(shifted)
                     if base.get(n, "ABSENT") != shifted.get(n, "ABSENT"))
    doc["candidates"] = {n: [base.get(n, "ABSENT"), shifted.get(n, "ABSENT")]
                         for n in changed}
    if not changed:
        return doc
    files_of_changed = sorted({n.split("::", 1)[0] for n in changed})
    again, again_tail, _ = _run_pytest(tree_root, files_of_changed, shift_days=None,
                                       workdir=workdir, timeout_s=timeout_s,
                                       label="remeasure")
    doc["stages"]["remeasure"] = {"verdicts": len(again), "tail": again_tail[-1200:]}
    for n in changed:
        returned = again.get(n, "ABSENT") == base.get(n, "ABSENT")
        doc["verdict"][n] = MEMBER if returned else NOISY
    return doc


# --- CLI -------------------------------------------------------------------
def _surface_report(verdicts: list[FileVerdict]) -> tuple[str, int]:
    buckets: dict[str, list[FileVerdict]] = {}
    for v in verdicts:
        buckets.setdefault(v.surface, []).append(v)
    surf = buckets.get(IN_SURFACE, [])
    unm = buckets.get(UNMEASURED, [])
    lines = [
        "ПОВЕРХНОСТЬ класса «половина инъекции часов через mtime» "
        f"(охват {', '.join(DEFAULT_ROOTS)}/test_*.py, glob):",
        f"  файлов прочитано: {len(verdicts) - len(unm)}",
        f"  претензии injected-clock не заявляли: {len(buckets.get(NO_CLAIM, []))}",
        f"  заявили, но файлов НЕ создают:        {len(buckets.get(NO_WRITES, []))}",
        f"  претензия + запись (ВЕРХНЯЯ граница): "
        f"{len(surf) + len(buckets.get(NO_READER, []))}",
        f"    из них читателя отметки НЕ ввозят:  {len(buckets.get(NO_READER, []))}",
        f"  ПРЕДМЕТ (претензия + запись + один хоп до читателя): {len(surf)}",
        f"  НЕ ИЗМЕРЕНО:                          {len(unm)}",
    ]
    pinned = [v for v in surf if v.pin_lines]
    reads = [v for v in surf if v.reads_mtime]
    lines += [
        f"    из них пинуют mtime явными временами: {len(pinned)}",
        f"    из них сами упоминают чтение отметки: {len(reads)}",
        "  ⚠️ предмет есть ВЕРХНЯЯ граница, а не класс: члена называет только "
        "дифференциальный прогон (--differential)",
        "  ⚠️ население за границей ОДНОГО хопа НЕ ИЗМЕРЕНО и нулём не считается: "
        "ввоз читателя через общего помощника числится вне предмета",
    ]
    for v in surf:
        mark = "pin" if v.pin_lines else "НЕТ ПИНА"
        lines.append(f"     • {v.path} — записей {len(v.write_lines)}, {mark}, "
                     f"читатель: {', '.join(v.reader_hits[:2])}")
    for v in unm:
        lines.append(f"     ⚠️ НЕ ИЗМЕРЕНО {v.path}: {v.reason}")
    code = UNMEASURED_CODE if unm else MEASURED_EMPTY
    return "\n".join(lines), code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="прибор класса «половина инъекции часов: отметка из mtime файла»")
    ap.add_argument("--surface", action="store_true",
                    help="разбор AST: поверхность класса (умолчание)")
    ap.add_argument("--differential", action="store_true",
                    help="замер КЛАССА: прогон поверхности трижды")
    ap.add_argument("--repo-root", default=None,
                    help="дерево, поверхность которого разбирается")
    ap.add_argument("--run-root", default=None,
                    help="ОДНОРАЗОВОЕ дерево, в котором идёт прогон (ОБЯЗАТЕЛЕН "
                         "для --differential: долгий прогон не живёт в дереве доставки)")
    ap.add_argument("--shift-days", type=float, default=-400.0,
                    help="сдвиг незапинованных отметок, суток; НАЗАД по умолчанию "
                         "(умолчание: %(default)s). Вперёд — вторая ось класса "
                         "(ADR-1085), этим прогоном она НЕ измеряется")
    ap.add_argument("--files", nargs="*", default=None,
                    help="прогнать НАЗВАННЫЕ файлы вместо измеренной поверхности")
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--json", action="store_true", help="документ на stdout")
    ns = ap.parse_args(argv)

    repo_root = Path(ns.repo_root).resolve() if ns.repo_root else \
        Path(__file__).resolve().parents[2]
    try:
        verdicts = measure_surface(repo_root)
    except RuntimeError as exc:
        print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return UNMEASURED_CODE

    if not ns.differential:
        text, code = _surface_report(verdicts)
        if ns.json:
            print(json.dumps({"surface": [v.as_json() for v in verdicts]},
                             ensure_ascii=False, indent=2))
        else:
            print(text)
        return code

    if not ns.run_root:
        print("⚠️ НЕ ИЗМЕРЕНО: --differential требует --run-root (одноразовое дерево): "
              "долгий прогон не живёт в дереве доставки "
              "(.claude/rules/deployment.md § «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ КОДОМ», п. 1)",
              file=sys.stderr)
        return UNMEASURED_CODE
    run_root = Path(ns.run_root).resolve()
    if not (run_root / "spa_core").is_dir():
        print(f"⚠️ НЕ ИЗМЕРЕНО: названное дерево не читается как репозиторий: {run_root}",
              file=sys.stderr)
        return UNMEASURED_CODE

    files = list(ns.files) if ns.files else [v.path for v in verdicts
                                            if v.surface == IN_SURFACE]
    with tempfile.TemporaryDirectory(prefix="spa_mtime_door_") as tmp:
        doc = differential(run_root, files, shift_days=ns.shift_days,
                           workdir=Path(tmp), timeout_s=ns.timeout_s)
    members = sorted(n for n, v in doc["verdict"].items() if v == MEMBER)
    noisy = sorted(n for n, v in doc["verdict"].items() if v == NOISY)
    doc["summary"] = {"members": members, "noisy": noisy,
                      "unmeasured": doc["unmeasured"]}
    if ns.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"ЗАМЕР КЛАССА (сдвиг {ns.shift_days} сут, дерево {run_root}):")
        print(f"  файлов поверхности прогнано: {len(files)}")
        print(f"  кандидатов (сменили вердикт): {len(doc['candidates'])}")
        print(f"  ЧЛЕНОВ класса:               {len(members)}")
        for n in members:
            print(f"     • {n}: {doc['candidates'][n][0]} → {doc['candidates'][n][1]}")
        print(f"  НЕ ИЗМЕРЕНО (шум, смена не вернулась): {len(noisy)}")
        for n in noisy:
            print(f"     ⚠️ {n}")
        for u in doc["unmeasured"]:
            print(f"  ⚠️ НЕ ИЗМЕРЕНО {u['what']}: {u['reason']}")
    if doc["unmeasured"]:
        return UNMEASURED_CODE
    return MEASURED_NONEMPTY if members else MEASURED_EMPTY


if __name__ == "__main__":  # pragma: no cover - точка входа
    raise SystemExit(main())
