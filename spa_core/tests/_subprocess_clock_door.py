#!/usr/bin/env python3
"""ДЕВЯТАЯ дверь семейства «вердикт зависит от свойства хоста»: ПОДПРОЦЕСС.

Зачем
------------------------------------------------------------------------------
Инъекция часов (приём №1 правила ``.claude/rules/deployment.md``) закрывает дверь
``datetime.now()`` ВНУТРИ процесса теста. ``subprocess.run`` есть такая же дверь к
стенным часам, и она лежит ЗА границей процесса — поэтому измеритель претензии
``FROZEN-DATE-OK: injected-clock`` (:mod:`spa_core.tests._injected_clock`, цикл #477)
её не видит ПО ПОСТРОЕНИЮ: он разбирает AST ОДНОГО файла, а вторая половина сравнения
живёт в другом процессе.

Предмет найден падением, а не разбором (цикл #1010, ADR-897): пять проверок
``test_no_regression_producer_wiring.py`` покраснели 31.10 **от календаря** при
неизменных байтах кода — отметку отчёта сцена считала от якоря, а «сколько сейчас»
спрашивал производитель, уже в другом процессе.

Что отвечает этот прибор и чего он НЕ отвечает
------------------------------------------------------------------------------
**Поверхность класса НЕ ЕСТЬ класс.** Подпроцесс, который не судит о свежести, бомбой
не является; назвать всю поверхность находками значило бы выдать поверхность за класс,
а назвать одну починенную бомбу классом — выдать неизвестное за ноль. Поэтому прибор
отвечает на ДВА РАЗНЫХ вопроса, и у каждого свой режим:

``--surface`` (умолчание)
    Разбор AST: какие тест-файлы (а) выписали себе претензию ``injected-clock`` и
    (б) запускают подпроцесс. Это ПОВЕРХНОСТЬ. Рядом считается вторая ось —
    передаётся ли якорь подпроцессу (в argv или в ``env``); «не передаётся» это ещё
    не бомба, но это и есть место, где претензия НЕ ИЗМЕРЕНА для этой двери.

``--differential``
    Замер КЛАССА методом § «GIT-ОКРУЖЕНИЕ в тестах» того же правила, в ТРИ ступени:

    1. **база** — как есть;
    2. **сдвиг у РЕБЁНКА** — тест, сменивший вердикт, есть КАНДИДАТ класса; смена
       перемеряется третьим прогоном без сдвига (не вернулась ⇒ НЕ ИЗМЕРЕНО, шум);
    3. **сдвиг У ОБОИХ** (только по подтверждённым, поэтому ступень дешёвая) — и она
       отделяет настоящую бомбу от чувствительности к САМОЙ асимметрии замера. Если под
       сдвигом обоих вердикт возвращается, значит ОБЕ стороны сравнения взяты у часов, и
       календарной бомбой тест НЕ является (``both_sides_wall_clock``); если не
       возвращается — одна сторона ПРИБИТЫЙ ЯКОРЬ, и это предмет класса
       (``anchor_vs_clock``). **Без третьей ступени «сменил вердикт» было бы ВЕРХНЕЙ
       границей, выданной за замер.**

Как сдвигается календарь у подпроцесса (цена названа, а не угадана)
------------------------------------------------------------------------------
``faketime`` в дереве нет, системные часы двигать нельзя. Дверь — ``sitecustomize``:
интерпретатор импортирует его САМ при старте, до любого пользовательского импорта,
поэтому ``from datetime import datetime`` в целевом скрипте получает уже подменённый
класс. Шим попадает ТОЛЬКО в детей: плагин pytest подменяет ЕДИНСТВЕННУЮ дверь
``subprocess.Popen.__init__`` (через неё идут ``run``/``call``/``check_output`` и
``from subprocess import run``) и дописывает в окружение ребёнка ``PYTHONPATH`` шима и
сдвиг. Родительский процесс pytest при этом НЕ сдвинут — именно асимметрия «якорь в
родителе ↔ календарь в ребёнке» и есть предмет замера.

Прогон НЕ ЕДИНИЧНЫЙ намеренно: смена вердикта перемеряется третьим прогоном без
сдвига. Вернулся ⇒ смена принадлежит календарю ребёнка; не вернулся ⇒ **НЕ ИЗМЕРЕНО**
(шумный тест), и это третий исход, а не находка (инв. #17).

Три исхода (инв. #17)
------------------------------------------------------------------------------
Код возврата: **0** — измерено, класс ПУСТ · **1** — измерено, класс НЕ ПУСТ (имена
названы) · **2** — НЕ ИЗМЕРЕНО с названной причиной. Файл, который не прочитан или не
разобран, получает ``unmeasured`` поимённо и НИКОГДА не считается «прошедшим».

Где он живёт и почему не в ``scripts/``
------------------------------------------------------------------------------
Рядом со своими сверстниками — ``_injected_clock.py``, ``_unwired.py``,
``_freshness.py``: это ПОМОЩНИК набора, у которого есть настоящий импортёр
(батарея `test_subprocess_clock_door_census.py`), а не точка входа в ``scripts/``
без вызывающего. Первая редакция лежала в ``scripts/`` и честно покрасила
`test_unwired_scripts_ratchet` («новый скрипт, которого никто не вызывает») —
дописывать имя в базу запрещено, и правильный выход оказался структурным, а не
базовым. Руками зовётся как модуль:
``python3 -m spa_core.tests._subprocess_clock_door --differential --run-root <дерево>``.

ADVISORY: прибор только ЧИТАЕТ дерево и запускает pytest в УКАЗАННОМ каталоге; ни
одного файла набора он не правит.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Модуль живёт В ПАКЕТЕ (``python3 -m spa_core.tests._subprocess_clock_door``), поэтому
# корень дерева на ``sys.path`` уже есть. Строка-страховка оставлена НАМЕРЕННО: первая
# редакция лежала в ``scripts/``, и там ``sys.path[0]`` был каталогом скрипта (урок
# ADR-148) — вторая ось молча отвечала «НЕ ИЗМЕРЕНО 30 из 30», то есть прибор докладывал
# о СВОЁМ пути импорта, а не о дереве.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Претензия, которую этот прибор берётся дополнить. Имя берётся у ЕДИНСТВЕННОЙ двери
#: (:mod:`spa_core.tests._injected_clock`), а не пишется дословно: своя копия строки
#: выписала бы освобождение самому прибору, а своя копия регекса разошлась бы с мерой
#: сторожа — ровно класс «одно имя — один объект».
from spa_core.tests._injected_clock import CLAIM  # noqa: E402

#: **Канонический охват претензии — ОДИН каталог, и это замер, а не выбор.** Храповик
#: литеральных дат (:mod:`spa_core.tests.test_frozen_date_ratchet`) читает
#: ``spa_core/tests/test_*.py`` НЕрекурсивно (строки 107 и 355), и ровно эти файлы
#: претензия освобождает. Мерить поверхность шире значило бы считать претензии, которых
#: никто не читает; поэтому широкий охват тут ЕСТЬ, но объявлен ОТДЕЛЬНОЙ осью.
CANON_ROOT = "spa_core/tests"

#: Широкая ось: каталоги предписанного прогона CI (`CLAUDE.md`). Претензия в файле
#: ВНЕ канонического охвата ничего не освобождает — это своя находка, не эта.
WIDE_ROOTS = (
    "tests",
    "spa_core/tests",
    "scripts/tests",
    "spa_core/analytics/gross_of",
    "research/cards",
    "studio_shell",
)
DEFAULT_ROOTS = WIDE_ROOTS

# --- исходы одной оси ------------------------------------------------------
ON_SURFACE = "on_surface"      #: претензия + запуск подпроцесса
OFF_SURFACE = "off_surface"    #: претензия есть, подпроцесса нет
UNMEASURED = "unmeasured"      #: не прочитан / не разобран — НЕ «прошло»

ANCHOR_PASSED = "anchor_passed"          #: якорь уезжает ребёнку (argv или env)
ANCHOR_NOT_PASSED = "anchor_not_passed"  #: не уезжает — претензия НЕ ИЗМЕРЕНА для двери

#: Исходы ТРЕТЬЕЙ ступени — она отделяет настоящую бомбу от чувствительности к САМОЙ
#: асимметрии, которую вносит замер. Без неё «сменил вердикт» есть ВЕРХНЯЯ граница.
ANCHOR_VS_CLOCK = "anchor_vs_clock"              #: одна сторона ПРИБИТА — предмет класса
BOTH_SIDES_WALL_CLOCK = "both_sides_wall_clock"  #: обе стороны у часов — НЕ календарная бомба


def shim_source() -> str:
    """Исходник ``sitecustomize``, сдвигающего календарь РЕБЁНКА.

    Сдвиг читается из окружения: без переменной шим не делает НИЧЕГО, поэтому случайно
    попавший в ``PYTHONPATH`` шим безвреден. Подменяются ``datetime.datetime``,
    ``datetime.date`` и ``time.time``; ``monotonic`` не трогается намеренно — он не
    календарь.

    **Почему у подменных классов метакласс (замер этого цикла, цена уже заплачена).**
    Первая редакция просто кладла в модуль НАСЛЕДНИКА, и этого достаточно, чтобы
    `from datetime import datetime` в ребёнке взял сдвинутый класс. Но наследник ломает
    `isinstance(x, dt.datetime)` для НАСТОЯЩЕГО `datetime`: такой объект экземпляром
    наследника не является. Дифференциальный прогон на этом выдал ЛОЖНУЮ находку —
    `autonomy_mandate._as_date` отказал `TypeError: ожидалась дата/датавремя, получено
    datetime`, то есть **артефакт прибора был доложен как предмет класса**, ровно вторая
    находка ADR-897 с другой стороны. Поэтому проверка типа делегируется настоящему
    классу (``__instancecheck__``/``__subclasscheck__``), а имя подменных классов —
    дословно ``datetime``/``date``: код, спрашивающий ``type(x).__name__``, не должен
    видеть прибор.
    """
    return (
        "import os\n"
        "_raw = os.environ.get('SPA_CLOCK_SHIFT_DAYS')\n"
        "if _raw:\n"
        "    try:\n"
        "        _days = float(_raw)\n"
        "    except ValueError:\n"
        "        _days = 0.0\n"
        "    if _days:\n"
        "        import datetime as _dt, time as _time\n"
        "        _delta = _dt.timedelta(days=_days)\n"
        "        _real_dt, _real_date = _dt.datetime, _dt.date\n"
        "        def _delegating_meta(real):\n"
        "            class _Meta(type(real)):\n"
        "                def __instancecheck__(cls, obj):\n"
        "                    return isinstance(obj, real)\n"
        "                def __subclasscheck__(cls, sub):\n"
        "                    return issubclass(sub, real)\n"
        "            return _Meta\n"
        "        class datetime(_real_dt, metaclass=_delegating_meta(_real_dt)):\n"
        "            @classmethod\n"
        "            def now(cls, tz=None):\n"
        "                return _real_dt.now(tz) + _delta\n"
        "            @classmethod\n"
        "            def utcnow(cls):\n"
        "                return _real_dt.utcnow() + _delta\n"
        "            @classmethod\n"
        "            def today(cls):\n"
        "                return _real_dt.today() + _delta\n"
        "        class date(_real_date, metaclass=_delegating_meta(_real_date)):\n"
        "            @classmethod\n"
        "            def today(cls):\n"
        "                return (_real_dt.now() + _delta).date()\n"
        "        _dt.datetime = datetime\n"
        "        _dt.date = date\n"
        "        _secs = _days * 86400.0\n"
        "        _real_time = _time.time\n"
        "        _time.time = lambda: _real_time() + _secs\n"
    )


def plugin_source() -> str:
    """Плагин pytest: ЕДИНСТВЕННАЯ дверь к детям — ``Popen.__init__``.

    Через неё идут и ``subprocess.run``, и ``call``, и ``check_output``, и импортнутые
    по имени (``from subprocess import run``) — своя обёртка на каждую вернула бы класс
    «две копии разошлись». Окружение ребёнка ДОПОЛНЯЕТСЯ, а не заменяется: тест,
    передавший свой ``env=``, своё окружение сохраняет.
    """
    return (
        "import os\n"
        "import subprocess\n"
        "_SHIM = os.environ['SPA_CLOCK_SHIM_DIR']\n"
        "_SHIFT = os.environ['SPA_CLOCK_SHIFT_DAYS_FOR_CHILDREN']\n"
        "_orig_init = subprocess.Popen.__init__\n"
        "def _init(self, *a, **kw):\n"
        "    base = dict(os.environ if kw.get('env') is None else kw['env'])\n"
        "    prev = base.get('PYTHONPATH', '')\n"
        "    base['PYTHONPATH'] = _SHIM + (os.pathsep + prev if prev else '')\n"
        "    base['SPA_CLOCK_SHIFT_DAYS'] = _SHIFT\n"
        "    kw['env'] = base\n"
        "    return _orig_init(self, *a, **kw)\n"
        "subprocess.Popen.__init__ = _init\n"
    )


def materialise_shim(target: Path, *, shift_days: float) -> tuple[Path, Path]:
    """Выложить шим и плагин в каталог. Возвращает (каталог шима, файл плагина)."""
    shim_dir = target / "clock_shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(shim_source(), encoding="utf-8")
    plugin = target / "spa_clock_child_plugin.py"
    plugin.write_text(plugin_source(), encoding="utf-8")
    _ = shift_days  # сдвиг уезжает окружением, не в исходник — шим остаётся общим
    return shim_dir, plugin


# --- ось 1: поверхность ----------------------------------------------------
def claims_the_marker(src: str) -> bool:
    """Выписал ли файл освобождение по причине ``injected-clock``.

    Делегирует ЕДИНСТВЕННОЙ двери — мере сторожа #477. Своя копия регекса дала бы
    прибору, который считает не то население, что освобождает храповик.
    """
    from spa_core.tests._injected_clock import claims_injected_clock

    return claims_injected_clock(src)


_SPAWN_ATTRS = frozenset({"run", "Popen", "call", "check_call", "check_output"})


def _subprocess_bindings(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    """Имена, под которыми модуль ``subprocess`` и его функции попали в файл.

    Без этого вопроса прибор отвечал бы про ПРАВОПИСАНИЕ, а не про запуск ребёнка:
    ``from subprocess import run`` и затем ``run(...)`` — тот же подпроцесс, а слово
    ``subprocess`` в вызове не стои́т. Первая редакция этой переписи так недосчитала
    поверхность (замер: 30 против 32 у карточки), и ошибался ИНСТРУМЕНТ.
    """
    modules: set[str] = set()
    funcs: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name == "subprocess" or al.name.endswith(".subprocess"):
                    modules.add(al.asname or al.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module != "subprocess":
                continue
            for al in node.names:
                if al.name in _SPAWN_ATTRS:
                    funcs[al.asname or al.name] = al.name
    return modules, funcs


def _spawn_calls(tree: ast.AST) -> list[str]:
    """Вызовы, поднимающие подпроцесс. Имя — как написано, для печати в отчёте."""
    modules, funcs = _subprocess_bindings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in _SPAWN_ATTRS:
            base = f.value
            name = (base.id if isinstance(base, ast.Name) else
                    base.attr if isinstance(base, ast.Attribute) else None)
            if name in modules or name == "subprocess":
                found.append(f"{name}.{f.attr}")
        elif isinstance(f, ast.Name) and f.id in funcs:
            found.append(f"{f.id} (from subprocess import {funcs[f.id]})")
    return sorted(set(found))


def _anchor_reaches_child(tree: ast.AST) -> bool:
    """Уезжает ли ЯКОРЬ ребёнку: ISO-литерал внутри argv-списка или значения ``env``.

    Мера НАМЕРЕННО грубая и ошибается в сторону «уезжает» — её задача отделить файлы,
    где шов уже есть (ADR-897: вход ``--now <ISO>``), от тех, где его нет вовсе. Точный
    ответ даёт только дифференциальный прогон, и он здесь же, режимом ``--differential``.
    """
    from spa_core.tests import _injected_clock as ic  # ленивый: прибор зовут и без набора

    bound = ic._bound_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _spawn_calls(ast.Module(body=[ast.Expr(value=node)], type_ignores=[])):
            continue
        for part in list(node.args) + [k.value for k in node.keywords if k.arg]:
            for sub in ast.walk(part):
                if ic.is_anchor(sub) or ic.is_rooted(sub, bound):
                    return True
    return False


@dataclass
class FileVerdict:
    path: str
    surface: str
    anchor: str = ""
    spawns: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict:
        d = {"path": self.path, "surface": self.surface}
        if self.anchor:
            d["anchor"] = self.anchor
        if self.spawns:
            d["spawns"] = self.spawns
        if self.reason:
            d["reason"] = self.reason
        return d


def measure_surface(repo_root: Path, roots: tuple[str, ...], *,
                    recursive: bool = True) -> list[FileVerdict]:
    """Перепись поверхности. Нечитаемый/неразбираемый файл ⇒ ``unmeasured`` поимённо.

    ``recursive=False`` воспроизводит охват храповика литеральных дат дословно
    (``glob``, а не ``rglob``) — иначе прибор считал бы ДРУГОЕ население.
    """
    out: list[FileVerdict] = []
    for rel in roots:
        base = repo_root / rel
        if not base.is_dir():
            continue
        walk = base.rglob if recursive else base.glob
        for f in sorted(walk("test_*.py")):
            p = str(f.relative_to(repo_root))
            try:
                src = f.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 — нечитаемость это исход
                out.append(FileVerdict(p, UNMEASURED, reason=f"не прочитан: {exc}"))
                continue
            if not claims_the_marker(src):
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                out.append(FileVerdict(p, UNMEASURED, reason=f"не разобран: {exc}"))
                continue
            spawns = _spawn_calls(tree)
            if not spawns:
                out.append(FileVerdict(p, OFF_SURFACE))
                continue
            try:
                passed = _anchor_reaches_child(tree)
            except Exception as exc:  # noqa: BLE001 — вторая ось своя, её неответ свой
                out.append(FileVerdict(p, ON_SURFACE, UNMEASURED, spawns,
                                       f"ось якоря не разобрана: {exc}"))
                continue
            out.append(FileVerdict(
                p, ON_SURFACE, ANCHOR_PASSED if passed else ANCHOR_NOT_PASSED, spawns))
    return out


# --- КАНАРЕЙКА ПРОЗРАЧНОСТИ ТИПА ------------------------------------------
#: Шим подменяет ``datetime``/``date`` МОДУЛЬНЫМ атрибутом. Это двигает ЗНАЧЕНИЕ, но
#: трогает и ТИП — а на типе стои́т чужой код. Замер 02.11 (цикл #1011): pydantic делает
#: ``class ConstrainedDate(date, metaclass=ConstrainedNumberMeta)``
#: (``pydantic/v1/types.py:1180``), и подмена ``date`` классом со своим метаклассом даёт
#: ``TypeError: metaclass conflict`` на ИМПОРТЕ — то есть ребёнок падает по причине,
#: не имеющей отношения к календарю, а прибор видит смену вердикта.
TYPE_INTACT = "intact"
TYPE_BROKEN = "broken"

_TYPE_CANARY = (
    "import datetime as dt\n"
    "# (1) НАСТОЯЩИЙ datetime обязан остаться экземпляром dt.datetime\n"
    "plain = dt.datetime.fromtimestamp(0, dt.timezone.utc)\n"
    "assert isinstance(plain, dt.datetime), 'isinstance сломан'\n"
    "assert isinstance(plain, dt.date), 'isinstance(date) сломан'\n"
    "# (2) дословная форма pydantic: наследование date со СВОИМ метаклассом\n"
    "class _Meta(type): pass\n"
    "class _Derived(dt.date, metaclass=_Meta): pass\n"
    "# (3) и календарь обязан быть сдвинут — иначе канарейка зелена напрасно\n"
    "assert dt.datetime.now().year > 2026, dt.datetime.now().year\n"
    "print('OK')\n"
)


def type_transparency(workdir: Path, *, shift_days: float,
                      timeout_s: int = 180) -> tuple[str, str]:
    """Не ломает ли шим ТИП вместе со значением. Возвращает (исход, причина).

    Вопрос задаётся ОТДЕЛЬНО и ДО сцен — дословный урок ``pyflakes`` (§ про ``pid``):
    код возврата рабочего прогона на вопрос «исправен ли инструмент» не отвечает.
    """
    shim_dir, _ = materialise_shim(workdir, shift_days=shift_days)
    probe = workdir / "type_canary.py"
    probe.write_text(_TYPE_CANARY, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim_dir)
    env["SPA_CLOCK_SHIFT_DAYS"] = str(shift_days)
    try:
        out = subprocess.run([sys.executable, str(probe)], capture_output=True,
                             text=True, env=env, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return TYPE_BROKEN, f"канарейка не ответила: {exc}"
    if out.returncode == 0 and out.stdout.strip() == "OK":
        return TYPE_INTACT, ""
    return TYPE_BROKEN, (out.stderr.strip().splitlines() or ["код "
                         f"{out.returncode}"])[-1]


# --- ось 2: дифференциальный прогон ---------------------------------------
_OUTCOME_RE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS|SUBFAIL\w*)\s+(\S+)")


def _parse_outcomes(stdout: str) -> dict[str, str]:
    """Вердикт на nodeid из ``-v`` вывода pytest. ``SKIPPED`` различается намеренно.

    Урок #465: в дифференциальном замере тест, ушедший в ``skipped``, не краснеет и не
    проходит — он ИСЧЕЗАЕТ, и глазами это читается как «всё в порядке».
    """
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        # форма pytest -v: "<nodeid> PASSED [ 12%]"
        parts = line.split()
        if len(parts) >= 2 and "::" in parts[0]:
            verdict = parts[1].rstrip(",")
            if verdict in {"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS",
                           "SUBFAILED", "SUBFAIL"}:
                out[parts[0]] = verdict
    return out


def _run_pytest(tree_root: Path, files: list[str], *, shift_days: float | None,
                workdir: Path, timeout_s: int, label: str = "",
                shift_parent: bool = False) -> tuple[dict[str, str], str]:
    """Один прогон. ``shift_days=None`` ⇒ календарь ребёнка НЕ сдвинут.

    ``-q`` здесь НЕТ намеренно: он погасил бы ``-v``, вердикты по ``nodeid`` в вывод не
    попали бы вовсе, и пустой разбор был бы прочитан как «вердиктов нет».
    Прогресс печатается в ``stderr`` без буфера — долгий прогон обязан быть ВИДЕН
    (``.claude/rules/deployment.md``, § окна мутационного прибора, п. 8).
    """
    env = dict(os.environ)
    env["SPA_ENV"] = "ci"
    env["PYTHONHASHSEED"] = "0"
    # Маркер ПЕСОЧНИЦЫ C8(b) (ADR-580, храповик test_sandbox_wiring_ratchet): ребёнок
    # идёт против ОДНОРАЗОВОГО дерева, и читатель без своего `data_dir` иначе молча
    # уводит чтение/запись в ПРОД через `live_paths.DEFAULT_LIVE_ROOT` — дословная форма
    # INC-1. Переменные указывают на СВОЮ песочницу, а не просто объявляют её наличие.
    env["SPA_SANDBOX"] = "1"
    env["SPA_LIVE_ROOT"] = str(tree_root)
    env["SPA_DATA_DIR"] = str(tree_root / "data")
    # якорь rootdir (класс test_child_pytest_rootdir.py): РАЗРЕШЁННЫЙ корень дерева — `/var/folders` есть ссылка на
    # `/private/var`, и неразрешённый якорь ронял сбор целиком (замер 02.11 на live_registry_scene_census)
    argv = [sys.executable, "-u", "-m", "pytest", "-v", "-p", "no:randomly", *files,
            "--rootdir", str(Path(tree_root).resolve())]
    if shift_days is not None:
        shim_dir, plugin = materialise_shim(workdir, shift_days=shift_days)
        env["SPA_CLOCK_SHIM_DIR"] = str(shim_dir)
        env["SPA_CLOCK_SHIFT_DAYS_FOR_CHILDREN"] = str(shift_days)
        parts = [str(workdir)]
        if shift_parent:
            # сдвигаем И родителя: тогда ОБЕ стороны сравнения, взятые у стенных часов,
            # сохраняют разницу, и вердикт меняется только там, где одна сторона —
            # ПРИБИТЫЙ ЯКОРЬ. Без этой оси смена вердикта есть ВЕРХНЯЯ граница класса.
            parts.insert(0, str(shim_dir))
            env["SPA_CLOCK_SHIFT_DAYS"] = str(shift_days)
        if env.get("PYTHONPATH"):
            parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(parts)
        argv[5:5] = ["-p", plugin.stem]
    print(f"[прибор] прогон {label or 'без метки'}: файлов {len(files)}, "
          f"сдвиг у ребёнка {shift_days}", file=sys.stderr, flush=True)
    proc = subprocess.run(argv, cwd=str(tree_root), env=env, capture_output=True,
                          text=True, timeout=timeout_s)
    outcomes = _parse_outcomes(proc.stdout)
    print(f"[прибор] прогон {label or 'без метки'} завершён: код {proc.returncode}, "
          f"вердиктов {len(outcomes)}", file=sys.stderr, flush=True)
    return outcomes, proc.stdout[-4000:]


def differential(tree_root: Path, files: list[str], *, shift_days: float,
                 timeout_s: int) -> dict:
    """Базовый прогон → сдвинутый → перемер РОВНО изменившихся файлов.

    Третий прогон не формальность: он отделяет «вердикт принадлежит календарю ребёнка»
    от «тест шумит», и второе есть НЕ ИЗМЕРЕНО, а не находка.
    """
    with tempfile.TemporaryDirectory(prefix="spa_clock_door_") as td:
        work = Path(td)
        # Канарейка ПЕРВОЙ: она дешевле сорока минут прогона и решает, будет ли ответ
        # о классе ответом вообще. Смена вердикта при сломанном типе есть артефакт
        # прибора, и выдать её за предмет класса — ровно вторая находка ADR-897.
        t_verdict, t_reason = type_transparency(work, shift_days=shift_days)
        try:
            base, base_tail = _run_pytest(tree_root, files, shift_days=None,
                                          workdir=work, timeout_s=timeout_s,
                                          label="БАЗА")
            shifted, shift_tail = _run_pytest(tree_root, files, shift_days=shift_days,
                                              workdir=work, timeout_s=timeout_s,
                                              label="СДВИГ")
        except subprocess.TimeoutExpired as exc:
            return {"status": UNMEASURED, "reason": f"прогон не завершился: {exc}"}
        if not base:
            return {"status": UNMEASURED,
                    "reason": "базовый прогон не дал ни одного вердикта по nodeid",
                    "tail": base_tail}
        if not shifted:
            return {"status": UNMEASURED,
                    "reason": "сдвинутый прогон не дал ни одного вердикта по nodeid",
                    "tail": shift_tail}
        changed = {k: (base.get(k, "<ОТСУТСТВУЕТ>"), shifted.get(k, "<ОТСУТСТВУЕТ>"))
                   for k in sorted(set(base) | set(shifted))
                   if base.get(k) != shifted.get(k)}
        confirmed: dict[str, list[str]] = {}
        noisy: dict[str, list[str]] = {}
        if changed:
            touched = sorted({k.split("::", 1)[0] for k in changed})
            try:
                recheck, _ = _run_pytest(tree_root, touched, shift_days=None,
                                         workdir=work, timeout_s=timeout_s,
                                         label="ПЕРЕМЕР")
            except subprocess.TimeoutExpired as exc:
                return {"status": UNMEASURED, "reason": f"перемер не завершился: {exc}",
                        "changed": {k: list(v) for k, v in changed.items()}}
            for node, (was, now) in changed.items():
                back = recheck.get(node, "<ОТСУТСТВУЕТ>")
                (confirmed if back == was else noisy)[node] = [was, now, back]
        kinds: dict[str, str] = {}
        kind_unmeasured: dict[str, str] = {}
        if confirmed:
            # ТРЕТЬЯ ступень — только по подтверждённым, поэтому она дешёвая.
            both = sorted({k.split("::", 1)[0] for k in confirmed})
            try:
                par, _ = _run_pytest(tree_root, both, shift_days=shift_days,
                                     workdir=work, timeout_s=timeout_s,
                                     label="СДВИГ ОБОИХ", shift_parent=True)
            except subprocess.TimeoutExpired as exc:
                for node in confirmed:
                    kind_unmeasured[node] = f"прогон «сдвиг обоих» не завершился: {exc}"
                par = {}
            for node, (was, _now, _back) in confirmed.items():
                if node not in par:
                    kind_unmeasured.setdefault(
                        node, "в прогоне «сдвиг обоих» вердикта по этому nodeid нет")
                    continue
                kinds[node] = (BOTH_SIDES_WALL_CLOCK if par[node] == was
                               else ANCHOR_VS_CLOCK)
        measured = t_verdict == TYPE_INTACT
        return {
            # Прозрачность типа решает, ОТВЕТ это или КАНДИДАТЫ. Третий исход назван
            # причиной, а не тишиной (инв. #17).
            "status": "measured" if measured else UNMEASURED,
            "type_transparency": t_verdict,
            "type_reason": t_reason,
            "reason": "" if measured else (
                "шим ломает ТИП вместе со значением, поэтому смена вердикта "
                f"неотличима от артефакта прибора: {t_reason}"),
            "candidates_only": not measured,
            "shift_days": shift_days,
            "files": len(files),
            "nodeids_base": len(base),
            "nodeids_shifted": len(shifted),
            "changed": len(changed),
            "confirmed": confirmed,
            "noisy": noisy,
            "kinds": kinds,
            "kind_unmeasured": kind_unmeasured,
            "anchor_vs_clock": sorted(k for k, v in kinds.items()
                                      if v == ANCHOR_VS_CLOCK),
            "both_sides_wall_clock": sorted(k for k, v in kinds.items()
                                            if v == BOTH_SIDES_WALL_CLOCK),
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    ap.add_argument("--differential", action="store_true",
                    help="замерить КЛАСС: прогнать поверхность дважды со сдвигом у ребёнка")
    ap.add_argument("--run-root", default=None,
                    help="дерево ПРОГОНА (обязательно отдельное — правило доставки)")
    ap.add_argument("--shift-days", type=float, default=400.0)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--only", nargs="*", default=None,
                    help="прогнать ровно эти файлы вместо всей поверхности")
    ap.add_argument("--list", action="store_true", help="печатать только пути поверхности")
    ap.add_argument("--wide", action="store_true",
                    help="ШИРОКАЯ ось: шесть каталогов предписанного прогона, рекурсивно")
    ap.add_argument("--whole-repo", action="store_true",
                    help="мерить ВЕСЬ репозиторий, а не только шесть каталогов CI")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve()
    if a.whole_repo:
        roots, recursive = (".",), True
    elif a.wide:
        roots, recursive = WIDE_ROOTS, True
    else:
        roots, recursive = (CANON_ROOT,), False
    rows = measure_surface(root, roots, recursive=recursive)
    surface = [r for r in rows if r.surface == ON_SURFACE]
    unmeasured = [r for r in rows if r.surface == UNMEASURED]

    if a.list:
        for r in surface:
            print(r.path)
        return 2 if unmeasured else 0

    report: dict = {
        "claiming_files": len(rows),
        "on_surface": len(surface),
        "off_surface": sum(1 for r in rows if r.surface == OFF_SURFACE),
        "unmeasured": [r.as_dict() for r in unmeasured],
        "anchor_passed": sum(1 for r in surface if r.anchor == ANCHOR_PASSED),
        "anchor_not_passed": sum(1 for r in surface if r.anchor == ANCHOR_NOT_PASSED),
        "anchor_unmeasured": sum(1 for r in surface if r.anchor == UNMEASURED),
        "rows": [r.as_dict() for r in surface],
    }

    if a.differential:
        run_root = Path(a.run_root).resolve() if a.run_root else root
        if a.run_root is None:
            report["differential"] = {
                "status": UNMEASURED,
                "reason": ("дерево прогона НЕ НАЗВАНО: часть набора правит исходники НА "
                           "МЕСТЕ, и долгий прогон в дереве доставки ломает доставку "
                           "(.claude/rules/deployment.md, седьмая дверь). Передай --run-root"),
            }
        else:
            files = a.only if a.only else [r.path for r in surface]
            report["differential"] = differential(
                run_root, files, shift_days=a.shift_days, timeout_s=a.timeout)

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        scope = ("ВЕСЬ репозиторий" if a.whole_repo else
                 "ШИРОКАЯ (каталоги CI)" if a.wide else
                 f"КАНОН храповика ({CANON_ROOT}/test_*.py, НЕрекурсивно)")
        print(f"ПОВЕРХНОСТЬ девятой двери · охват {scope} · дерево {root}:")
        print(f"   файлов с претензией {CLAIM}: {report['claiming_files']}")
        print(f"   из них поднимают подпроцесс: {report['on_surface']}"
              f"  ·  не поднимают: {report['off_surface']}")
        print(f"   ось якоря у поверхности: уезжает ребёнку {report['anchor_passed']}"
              f" · НЕ уезжает {report['anchor_not_passed']}"
              f" · НЕ ИЗМЕРЕНО {report['anchor_unmeasured']}")
        for r in unmeasured:
            print(f"   ⛔ НЕ ИЗМЕРЕНО {r.path}: {r.reason}")
        for r in surface:
            if r.anchor == UNMEASURED:
                print(f"   ⛔ ось якоря НЕ ИЗМЕРЕНА {r.path}: {r.reason}")
        d = report.get("differential")
        if d:
            if d["status"] == UNMEASURED:
                print(f"   ⛔ КЛАСС НЕ ИЗМЕРЕН: {d['reason']}")
                for node in sorted(d.get("confirmed", {})):
                    print(f"     • КАНДИДАТ (находкой НЕ является) {node}")
            else:
                print(f"   КЛАСС (сдвиг {d['shift_days']} сут у РЕБЁНКА): вердиктов "
                      f"{d['nodeids_base']} → {d['nodeids_shifted']}, сменили "
                      f"{d['changed']}")
                for node, (was, now, back) in d["confirmed"].items():
                    print(f"     • ПРЕДМЕТ КЛАССА {node}: {was} → {now} (вернулся {back})")
                for node, (was, now, back) in d["noisy"].items():
                    print(f"     • НЕ ИЗМЕРЕНО (шумит) {node}: {was} → {now}, перемер {back}")
                if d.get("kinds") or d.get("kind_unmeasured"):
                    print(f"   РОД (сдвиг ОБОИХ): якорь против часов "
                          f"{len(d['anchor_vs_clock'])} · обе стороны у часов "
                          f"{len(d['both_sides_wall_clock'])} · НЕ ИЗМЕРЕН "
                          f"{len(d['kind_unmeasured'])}")
                    for node in d["anchor_vs_clock"]:
                        print(f"     • ЯКОРЬ ПРОТИВ ЧАСОВ {node}")
                    for node in d["both_sides_wall_clock"]:
                        print(f"     • обе стороны у часов (НЕ бомба) {node}")
                    for node, why in d["kind_unmeasured"].items():
                        print(f"     • род НЕ ИЗМЕРЕН {node}: {why}")

    if unmeasured:
        return 2
    d = report.get("differential")
    if d:
        if d["status"] == UNMEASURED:
            return 2
        if d.get("kind_unmeasured"):
            return 2
        if d.get("anchor_vs_clock"):
            return 1
        if d["noisy"]:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
