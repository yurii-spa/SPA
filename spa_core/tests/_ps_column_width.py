"""Прибор класса «вердикт есть свойство того, как `ps` сегодня рисует вывод» (ADR-1032).

# LLM_FORBIDDEN

**Предмет.** GNU-`ps` (procps-ng, раннер CI) обрезает КАЖДУЮ строку вывода по ширине
экрана, а без терминала берёт **80 колонок**. BSD-`ps` (Мак) не обрезает ни с терминалом,
ни без — поэтому дома класс невидим целиком. ADR-1031 измерил ОДНУ дверь
(`scripts/delta_mutation_run.py`): прибор не узнавал СВОЕГО ЖЕ дочернего процесса, вердикт
о владельце окна выходил `unmeasured` при живом владельце, и это стоило **семи** красных
тестов в CI, зелёных на Маке. Причина была починена там же (`ps -ww`), а вред у остальных
восьми дверей остался НЕ ИЗМЕРЕН — нулём это не считалось (карточка
`inbox-shirina-vyvoda-ps-devyat-dverei-odnogo-k`, метод замера выписан в её теле).

**Класс — это ДВА разных вопроса, и сводить их в один нельзя.**

1. *Переворачивается ли ПРЕДИКАТ двери от обрезания строки до 80 колонок?* Свойство самого
   предиката и длины его субъектов. Дверь, чьё сравнение идёт по ГОЛОВЕ строки, не
   переворачивается, и это надо НАЗВАТЬ, а не засчитать нулём.
2. *Просит ли дверь `-ww`?* Свойство одной строки кода. Просит ⇒ обрезание до неё не
   доходит ни на одной машине.

**Членом класса дверь является, когда ДА на первый вопрос и НЕТ на второй.** Дописать
`-ww` всем девяти скопом значило бы объявить класс закрытым, не измерив его, — ровно
«ложное усиление» (ADR-940…944): дверь, чей предикат не переворачивается, от флага не
становится вернее, а замер населения теряется.

**Таблица процессов — ВХОД, а не окружение.** Живой `ps` этой машины отвечает на вопрос
«что запущено СЕЙЧАС», и тест, спросивший его, судил бы о сегодняшней загрузке хоста —
тот же дефект, против которого прибор написан (ср. `.claude/rules/deployment.md`
§ «ЛИЧНОСТЬ ПРОЦЕССА»: литеральный pid, проверяемый у живой ОС). Поэтому у каждой двери
есть ЗАМОРОЖЕННЫЙ субъект — настоящая строка, снятая с этой машины 2026-11-16 и
приведённая вместе с происхождением; живой замер остаётся у CLI (`--live`) и служит
переписи населения, а не вердикту сторожа.

Три исхода различимы (инв. #17): `flips` · `stable` (с НАЗВАННОЙ причиной) ·
`unmeasured` (с названной причиной). Четвёртый ярлык `unreachable` — не «чисто», а
отдельное наблюдение «80 колонок субъектами двери не достигается».
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[2]

#: Ширина, которую GNU-`ps` берёт без терминала. Не «примерно 80»: `procps-ng` читает
#: `COLUMNS`, затем размер окна, и в отсутствие обоих подставляет ровно это число.
GNU_DEFAULT_COLUMNS = 80

FLIPS = "flips"
STABLE = "stable"
UNREACHABLE = "unreachable"
UNMEASURED = "unmeasured"
OUTCOMES = (FLIPS, STABLE, UNREACHABLE, UNMEASURED)

#: Каталоги, в которых ищется поверхность. `spa_core/tests/` исключён намеренно: зов `ps`
#: внутри сцены есть МАТЕРИАЛ сцены, а не дверь системы к ОС.
SCAN_DIRS = ("spa_core", "scripts", "studio_shell", "research", "landing")


# ── 1. Поверхность: какие зовы `ps` вообще есть в дереве ─────────────────────

@dataclass(frozen=True)
class Site:
    path: str
    line: int
    argv: tuple[str, ...]

    @property
    def fmt(self) -> str:
        """Строка формата, несущая колонку `command`. Пусто — зов не член поверхности."""
        return next((a for a in self.argv if "command" in a), "")

    @property
    def key(self) -> str:
        """Ключ двери — ФАЙЛ и ФОРМАТ, а не номер строки.

        Номер строки съезжает от любой правки выше по файлу, и реестр, прибитый к нему,
        краснел бы на каждом касании соседнего кода — то есть учил бы править реестр
        вместо чтения. Формат зова — то, что у двери неизменно, пока дверь та же; номер
        строки прибор ИЗМЕРЯЕТ и печатает рядом.
        """
        return f"{self.path}::{self.fmt}"

    @property
    def carries_command(self) -> bool:
        """Формат зова несёт колонку `command` — иначе сравнивать нечего (метод, п. 1)."""
        return any("command" in a for a in self.argv)

    @property
    def asks_ww(self) -> bool:
        return "-ww" in self.argv or "-w" in self.argv


def surface(root: Path | str | None = None) -> dict:
    """Все литеральные зовы `ps` в дереве. Нечитаемый файл — третий исход, не ноль."""
    base = Path(root) if root is not None else _ROOT
    sites: list[Site] = []
    unreadable: list[dict] = []
    for name in SCAN_DIRS:
        d = base / name
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.py")):
            rel = p.relative_to(base).as_posix()
            if rel.startswith("spa_core/tests/") or "/tests/" in rel or p.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError) as exc:
                unreadable.append({"path": rel, "why": f"{type(exc).__name__}: {exc}"})
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for arg in node.args:
                    if not isinstance(arg, ast.List):
                        continue
                    elts = [e.value for e in arg.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    if elts and elts[0] == "ps":
                        sites.append(Site(rel, node.lineno, tuple(elts)))
    return {"sites": sites, "unreadable": unreadable,
            "with_command": [s for s in sites if s.carries_command],
            "without_command": [s for s in sites if not s.carries_command]}


# ── 2. Обрезание ─────────────────────────────────────────────────────────────

def truncate(text: str, columns: int = GNU_DEFAULT_COLUMNS) -> str:
    """Как режет GNU-`ps`: КАЖДУЮ строку по колонке, а не текст целиком."""
    return "\n".join(line[:columns] for line in text.splitlines())


# ── 3. Двери ─────────────────────────────────────────────────────────────────

def _load_script(name: str):
    """Модуль из `scripts/` по пути (пакетом они не являются)."""
    path = _ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_pscw_{name}", path)
    if spec is None or spec.loader is None:                        # pragma: no cover
        raise ImportError(f"не удалось загрузить {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Door:
    """Одна дверь класса.

    `verdict` принимает ТЕКСТ, который дверь читает, и отдаёт РЕШЕНИЕ двери (не текст):
    сравнивать тексты бессмысленно — обрезанный текст отличается от полного всегда.

    Субъект у двери НЕ ОДИН, и это не удобство, а предмет: дверь есть член класса, если
    вердикт переворачивается ХОТЯ БЫ на одном настоящем субъекте. Первая редакция прибора
    брала у живого `ps` ПЕРВЫЙ подходящий субъект и объявила `call_provenance` устойчивой,
    тогда как на другом — настоящем же — субъекте та же дверь переворачивается. «Не нашлось
    на первом» ответом о классе не является.
    """
    path: str
    name: str
    fmt: str
    decides: str
    verdict: Callable[[str], Any]
    frozen: tuple[str, ...]
    frozen_from: str
    live: Optional[Callable[[], Optional[list]]] = None
    stable_why: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Объявление двери — ФАЙЛ и ФОРМАТ, и БОЛЬШЕ НИЧЕГО.

        Просит ли дверь `-ww` — объявлением НЕ является ни в одну сторону: это ровно то,
        что прибор обязан ИЗМЕРИТЬ в коде. Первая редакция держала здесь полный `argv`,
        и после починки пяти дверей прибор честно напечатал «`-ww` НЕТ» про двери, у
        которых флаг уже стоял, — он читал СВОЁ объявление вместо исходника.
        """
        return f"{self.path}::{self.fmt}"


def _ps_line(argv: list[str]) -> str:
    """Одна строка `ps` БЕЗ срезания ведущих пробелов.

    `.strip()` здесь есть дефект, а не уборка: колонки `ps` подбиты пробелами СЛЕВА, и
    срезав их, читатель сдвигает все колонки на ширину паддинга. Прибор ADR-1032 поймал
    этот дефект В СЕБЕ САМОМ: у двери `call_provenance` маркер `scripts/agent_template.sh`
    кончается на колонке 84, а после `.strip()` — на 80, и дверь выходила «устойчивой»
    там, где она переворачивается. Тот же класс, что урок про `_git` и `status --porcelain`.
    """
    return _ps(argv).rstrip("\n")


def _ps(argv: list[str]) -> str:
    """Настоящий `ps` ЭТОЙ машины, всегда с `-ww`: прибору нужен НЕобрезанный текст."""
    cmd = ["ps", "-ww"] + [a for a in argv[1:] if a not in ("-w", "-ww")]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         env=dict(os.environ, LC_ALL="C"), timeout=30)
    return out.stdout or ""


# D1 ── scripts/check_concurrent_pytest.py:149 ────────────────────────────────

def _d1_verdict(text: str):
    mod = _load_script("check_concurrent_pytest")
    saved = mod._run
    try:
        mod._run = lambda cmd: text
        procs = mod.list_pytest_processes()
    finally:
        mod._run = saved
    return None if procs is None else tuple(sorted(p.pid for p in procs))


# D2 ── scripts/check_undelivered_work.py:285 ─────────────────────────────────

def _d2_verdict(text: str):
    mod = _load_script("check_undelivered_work")
    kinds = []
    for line in text.splitlines():
        if not line.strip():
            continue
        kind, _cmd = mod.anchor_kind(1, cmd_probe=lambda _pid, _l=line: (0, _l))
        kinds.append(kind)
    return tuple(kinds)


# D3 ── spa_core/monitoring/agent_code_freshness.py:233 ───────────────────────

def _d3_verdict(text: str):
    from spa_core.monitoring import agent_code_freshness as acf
    table = acf._process_table(lambda _cmd: text)
    wrappers = [r["pid"] for r in table if "agent_template.sh" in r["command"]]
    return tuple((p, acf._python_descendant(p, table)) for p in sorted(wrappers))


# D4 ── spa_core/monitoring/call_provenance.py:235 ────────────────────────────

def _d4_verdict(text: str):
    """Цепь родителей, ход за ходом.

    Текст — строки формата САМОЙ двери (`ppid=,command=`), по одной на ход цепи, в
    порядке обхода. Колонки `pid` у двери НЕТ, и подставлять её для удобства нельзя:
    обрезание идёт по СТРОКЕ, а лишняя колонка сдвинула бы предел на свою ширину.
    """
    from spa_core.monitoring import call_provenance as cp
    hops: list[tuple[int, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if not parts[0].lstrip("-").isdigit():
            continue
        hops.append((int(parts[0]), parts[1] if len(parts) > 1 else ""))
    if not hops:
        return None
    seq = iter(hops)

    def read_parent(_pid: int):
        return next(seq, None)

    doc = cp.launcher_provenance(start_pid=10 ** 6, read_parent=read_parent)
    return (doc.get("measured"), doc.get("kind"), doc.get("fleet_wrapper"))


# D5 ── spa_core/monitoring/resource_guard.py:213 ─────────────────────────────

def _policy() -> dict:
    return json.loads((_ROOT / "architecture" / "resource_policy.json").read_text("utf-8"))


def _d5_verdict(text: str):
    """Вердикт двери — КТО расходный и кто критический, а не «первые 15 по памяти».

    `top` отсортирован по RSS и несёт 15 строк из семисот: сравнивать его значило бы
    спрашивать «изменилась ли голова списка», тогда как действует (`protect`) дверь
    именно по `disposable`. Первая редакция прибора сравнивала `top` и ответила
    «не переворачивается» там, где переворачивались четыре строки из 753.
    """
    from spa_core.monitoring import resource_guard as rg
    rep = rg.measure_processes(_policy(), run=lambda cmd: (None if cmd[0] != "ps" else text))
    if rep.get("state") != rg.OK:
        return (rep.get("state"),)
    return (frozenset(r["pid"] for r in rep.get("disposable") or []),
            frozenset(r["pid"] for r in rep.get("critical") or []),
            rep.get("count"))


# D6 ── spa_core/monitoring/resource_guard.py:252 ─────────────────────────────

def _d6_verdict(text: str):
    """`_same_process` сверяет СНИМОК двери D5 с перечитанной строкой двери D6.

    Снимок и перечитывание берутся у РАЗНЫХ форматов (`pid=,ppid=,rss=,nice=,etime=,command=`
    против `command=`), поэтому обрезание по строке приходится на РАЗНЫЕ колонки команды.
    Текст двери здесь — две части, разделённые `\\x00`: снимок D5 и строка D6.
    """
    from spa_core.monitoring import resource_guard as rg
    snapshot_line, verify_line = (text.split("\x00") + ["", ""])[:2]
    parts = snapshot_line.split(None, 5)
    if len(parts) < 6 or not parts[0].isdigit():
        return None
    pid, snapshot_cmd = int(parts[0]), rg.redact_cmd(parts[5])[:240]
    saved = rg._run
    try:
        rg._run = lambda cmd: verify_line
        return rg._same_process(pid, snapshot_cmd)
    finally:
        rg._run = saved


# D7 ── spa_core/monitoring/telegram_health.py:221 ────────────────────────────

class _FakeCompleted:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.returncode = 0


def _d7_verdict(text: str):
    from spa_core.monitoring import telegram_health as th
    saved = th._run
    try:
        th._run = lambda cmd, **kw: _FakeCompleted(text)
        return th.poller_pids()
    finally:
        th._run = saved


# D8 ── spa_core/studio_os/director_report.py:283 ─────────────────────────────

def _d8_verdict(text: str):
    from spa_core.studio_os import director_report as dr
    return dr.count_claude_sessions(text)


# D9 ── scripts/delta_mutation_run.py:615 (починена ADR-1031) ────────────────

def _d9_verdict(text: str):
    mod = _load_script("delta_mutation_run")
    record = {"pid": 424242, "run_label": "c1171", "hostname": "h",
              "opened_at": "2026-11-16T00:00:00Z"}
    probe = lambda _pid: {"exists": True, "started_at": None,
                          "command": text.strip(), "why": None}
    return mod.owner_liveness(record, probe=probe, hostname="h", caller_pid=1)["verdict"]


# ── живые субъекты (перепись населения; у сторожа входом не служат) ──────────
#
# Каждый селектор отдаёт СПИСОК настоящих субъектов двери, а не первый подошедший:
# «не нашлось на первом» ответом о классе не является (см. докстроку `Door`).

LAUNCHD_PID = 1


def live_pair() -> Optional[list]:
    """Живая сцена двери :252 — снимок формата D5 плюс перечитывание формата D6."""
    table = _ps(["ps", "-axo", "pid=,ppid=,rss=,nice=,etime=,command="])
    picked = []
    for line in table.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        if len(parts[5]) <= GNU_DEFAULT_COLUMNS:
            continue
        one = _ps_line(["ps", "-o", "command=", "-p", parts[0]])
        if one:
            picked.append(f"{line}\x00{one}")
        if len(picked) >= 5:
            break
    return picked or None


def _live_anchor_lines() -> Optional[list]:
    """Субъекты двери D2: процессы-таймеры и процессы с ДЛИННЫМ первым токеном.

    Дверь читает `ps -p <pid> -o command=` по ОДНОМУ номеру, и её субъект — якорь,
    объявленный сессией. Весь список процессов субъектом не является: вопрос «а не
    таймер ли это» задаётся адресно.
    """
    table = _ps(["ps", "-ax", "-o", "command="])
    picked = []
    for line in table.splitlines():
        text = line.rstrip("\n")
        if not text.strip():
            continue
        head_token = text.split()[0]
        if os.path.basename(head_token) == "sleep" or len(head_token) > GNU_DEFAULT_COLUMNS:
            picked.append(text)
    return picked or None


def _live_fleet_chains() -> Optional[list]:
    """Субъекты двери D4: ВСЕ настоящие дети обёрток флота — ход за ходом, форматом двери."""
    table = _ps(["ps", "-ax", "-o", "pid=,ppid=,command="])
    kids: list[tuple[int, int]] = []
    wrappers: set[int] = set()
    for line in table.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        pid, ppid, cmd = int(parts[0]), int(parts[1]), parts[2]
        if "agent_template.sh" in cmd:
            wrappers.add(pid)
        kids.append((pid, ppid))
    chains = []
    for pid, ppid in kids:
        if ppid not in wrappers:
            continue
        hops, cur, seen = [], pid, set()
        while cur and cur not in seen and len(hops) < 8:
            seen.add(cur)
            # `.strip()` здесь ЗАПРЕЩЕН: колонка `ppid` подбита пробелами слева, и
            # срезав их, прибор подделал бы устойчивость двери — маркер
            # `scripts/agent_template.sh` кончался бы на колонке 80 вместо 84. Ровно
            # этот дефект прибор нашёл в себе самом при первом живом замере (ADR-1032).
            line = _ps_line(["ps", "-o", "ppid=,command=", "-p", str(cur)])
            if not line:
                hops = []
                break
            hops.append(line)
            parent = line.split(None, 1)[0]
            if not parent.isdigit():
                hops = []
                break
            cur = int(parent)
            if cur == LAUNCHD_PID:
                break
        if hops:
            chains.append("\n".join(hops))
        if len(chains) >= 5:
            break
    return chains or None


def _live_instrument_owner() -> Optional[list]:
    """Субъекты двери D9: строки ЖИВОГО мутационного прибора. Нет прогона — нет субъекта."""
    table = _ps(["ps", "-ax", "-o", "lstart=,command="])
    picked = [l.rstrip("\n") for l in table.splitlines()
              if "delta_mutation_run" in l and "_ps_column_width" not in l]
    return picked or None


def _live_table(argv: list[str]):
    return lambda: [_ps(argv)]


# ── замороженные субъекты (настоящие строки этой машины, 2026-11-16) ─────────
#
# Каждая строка снята живым `ps -ww` на Mac mini владельца и приведена ДОСЛОВНО, с
# происхождением. Срезать их до «показательного фрагмента» было бы подменой предмета:
# класс живёт в ДЛИНЕ, и длина обязана быть настоящей.

_F1 = (
    "28279 28266 Mon Nov 16 12:07:24 2026 /Users/yuriikulieshov/miniconda3/bin/python3 "
    "-m pytest spa_core/tests/test_state_md_length_ratchet.py -q --tb=short"
)
_F2_LONG_PATH = (
    "/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/"
    "FSEvents.framework/Versions/A/Support/fseventsd"
)
_F2_SLEEP = "sleep 36000"
_F3 = (
    "28279 28266 /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.telegram.bot\n"
    "28266     1 /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/"
    "agent_template.sh telegram_bot spa_core.telegram.bot"
)
_F4 = (
    "28266 /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.telegram.bot\n"
    "    1 /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/"
    "agent_template.sh telegram_bot spa_core.telegram.bot"
)
_F5 = (
    "28279 28266  92160  0    03:12 /Users/yuriikulieshov/miniconda3/bin/python3 "
    "-m pytest spa_core/tests/ -q -p no:randomly\n"
    "  512     1   4096  0 10-02:11 /usr/sbin/syslogd"
)
_F6 = (
    "28279 28266  92160  0    03:12 /Users/yuriikulieshov/miniconda3/bin/python3 "
    "-m pytest spa_core/tests/ -q -p no:randomly"
    "\x00"
    "/Users/yuriikulieshov/miniconda3/bin/python3 -m pytest spa_core/tests/ -q -p no:randomly"
)
_F7 = (
    "28266 /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/"
    "agent_template.sh telegram_bot spa_core.telegram.bot\n"
    "28279 /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.telegram.bot"
)
#: Два НАСТОЯЩИХ субъекта двери D8, снятых живым `ps` 2026-11-16: обёртка цикла (полная
#: длина 24 631 колонка) и сама headless-сессия (24 285). Хвост промпта отброшен на
#: колонке 160, и это НАЗВАНО, а не умолчано: ни одно из трёх условий двери не читает
#: дальше колонки 68, а потолок сканирования ширины — 240. Подделывать длину хвоста
#: филлером было бы выдумыванием наблюдения (`docs/37`); живой замер по ПОЛНОЙ таблице
#: идёт отдельно (`--live`) и дал 0 расхождений на всех 753 строках.
_F8_WRAPPER = (
    "/Users/yuriikulieshov/miniconda3/bin/python3 /Users/yuriikulieshov/Documents/"
    "SPA_Claude/scripts/claude_run_with_timeout.sh 3600 /Users/yuriikulieshov/.local/"
    "bin/claude -p \u0417\u0410\u041a\u0410\u0417"
)
_F8_SESSION = (
    "/Users/yuriikulieshov/.local/bin/claude -p \u0428\u0410\u0413 0a-\u0413\u041e"
    "\u041b\u041e\u0414 \u2014 \u041d\u0410\u0425\u041e\u0414\u041a\u0410, "
    "\u0438\u0441\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f "
    "\u041f\u0415\u0420\u0412\u042b\u041c, \u0434\u043e \u0448\u0430\u0433\u0430"
)
_F9 = (
    "/opt/hostedtoolcache/Python/3.11.18/x64/bin/python /tmp/spa_c1171/scripts/"
    "delta_mutation_run.py --repo-root /tmp/spa_c1171 --spec docs/mutations/ADR-1032.json"
)


DOORS: tuple[Door, ...] = (
    Door(
        path="scripts/check_concurrent_pytest.py",
        name="сторож параллельных прогонов pytest",
        fmt="pid=,ppid=,lstart=,command=",
        decides="номера процессов, крутящих pytest",
        verdict=_d1_verdict, frozen=(_F1,),
        frozen_from="живой прогон храповика на Маке; `pytest` стоит за колонкой lstart",
        live=_live_table(["ps", "-ax", "-o", "pid=,ppid=,lstart=,command="]),
    ),
    Door(
        path="scripts/check_undelivered_work.py",
        name="род якоря сессии (шаг 0a/0b)",
        fmt="command=",
        decides="`sleep`-таймер против процесса, способного быть сессией",
        verdict=_d2_verdict, frozen=(_F2_SLEEP, _F2_LONG_PATH),
        frozen_from="настоящий фоновый якорь `sleep 36000` и системный процесс, у "
                    "которого ПЕРВЫЙ ЖЕ токен длиннее 80 колонок (284 таких на этой машине)",
        live=_live_anchor_lines,
        stable_why="решение принимает ТОЛЬКО голова строки — `os.path.basename(cmd.split()[0])` "
                   "против литерала `sleep` длиной пять символов. Обрезание укорачивает "
                   "хвост; чтобы вердикт перевернулся, обрезанный путь обязан КОНЧИТЬСЯ на "
                   "`/sleep` ровно у колонки 80, и ни один из 284 длинноголовых процессов "
                   "этой машины такой формы не имеет",
    ),
    Door(
        path="spa_core/monitoring/agent_code_freshness.py",
        name="python-потомок обёртки флота",
        fmt="pid=,ppid=,command=",
        decides="номер python-процесса, держащего код агента",
        verdict=_d3_verdict, frozen=(_F3,),
        frozen_from="настоящая пара «обёртка флота → её python» (`com.spa.telegram_bot`)",
        live=_live_table(["ps", "-eo", "pid=,ppid=,command="]),
    ),
    Door(
        path="spa_core/monitoring/call_provenance.py",
        name="происхождение запуска (launchd или рука, ADR-997)",
        fmt="ppid=,command=",
        decides="прямое ли это задание launchd и обёртка ли флота его ребёнок",
        verdict=_d4_verdict, frozen=(_F4,),
        frozen_from="та же настоящая пара, форматом САМОЙ двери (`ppid=,command=`), ход "
                    "за ходом; маркер `scripts/agent_template.sh` занимает колонки "
                    "59…84 — конец ЗА пределом 80",
        live=_live_fleet_chains,
    ),
    Door(
        path="spa_core/monitoring/resource_guard.py",
        name="классификация процессов под давлением памяти",
        fmt="pid=,ppid=,rss=,nice=,etime=,command=",
        decides="класс каждого процесса (DISPOSABLE / CRITICAL / …)",
        verdict=_d5_verdict, frozen=(_F5,),
        frozen_from="настоящая строка прогона pytest рядом с системной; образцы класса "
                    "DISPOSABLE (`python -m pytest`) стоят за пятью колонками формата",
        live=_live_table(["ps", "-axo", "pid=,ppid=,rss=,nice=,etime=,command="]),
    ),
    Door(
        path="spa_core/monitoring/resource_guard.py",
        name="«тот же это процесс» перед снижением приоритета",
        fmt="command=",
        decides="совпал ли снимок команды с перечитанной строкой",
        verdict=_d6_verdict, frozen=(_F6,),
        frozen_from="снимок двери :213 и перечитывание двери :252 ОДНОГО процесса — "
                    "форматы разные, поэтому обрезание режет команду в разных местах",
        live=None,
        extra={"live_why": "сцена складывается из ДВУХ дверей разного формата; живой "
                           "замер собирает её `live_pair()`"},
    ),
    Door(
        path="spa_core/monitoring/telegram_health.py",
        name="поллеры бота (второй поллер = 409-конфликты у владельца)",
        fmt="pid=,command=",
        decides="номера python-процессов, крутящих модуль бота",
        verdict=_d7_verdict, frozen=(_F7,),
        frozen_from="настоящая пара «обёртка → python -m spa_core.telegram.bot»; у python "
                    "модуль кончается на колонке 75 — ЗАПАС пять символов",
        live=_live_table(["ps", "-eo", "pid=,command="]),
        stable_why="обрезание у этой двери ТЕРЯЕТ имя модуля, а не подменяет его, и строка "
                   "без имени модуля отбрасывается самой дверью (`module not in line`) — то "
                   "есть у длинных субъектов (обёртка, чужая оболочка) вердикт одинаков. "
                   "Решающая строка — короткая: `python3 -m spa_core.telegram.bot` кончается "
                   "на колонке 75, и прибор меряет переворот на ширине 74. ЗАПАС шесть "
                   "колонок, и он НЕ свойство предиката: он есть "
                   "длина пути к интерпретатору, и наблюдённый на раннере CI путь "
                   "(`/opt/hostedtoolcache/Python/3.11.18/x64/bin/python`) длиннее на шесть. "
                   "Дверь живёт только на Маке, где `ps` не режет вовсе — поэтому член "
                   "класса НЕ объявлен, но запас НАЗВАН, а не скрыт",
    ),
    Door(
        path="spa_core/studio_os/director_report.py",
        name="счёт headless-сессий Claude в отчёте директора",
        fmt="command",
        decides="сколько сессий `claude -p` идёт прямо сейчас",
        verdict=_d8_verdict, frozen=(_F8_WRAPPER, _F8_SESSION),
        frozen_from="настоящая обёртка `claude_run_with_timeout.sh` (исключение двери "
                    "кончается на колонке 88 — ЗА пределом 80) и настоящая headless-сессия "
                    "(` -p ` на колонке 40); хвосты промптов отброшены на колонке 160 с "
                    "названной причиной",
        live=_live_table(["ps", "-axo", "command"]),
        stable_why="три условия двери (`(^|/)claude(\\s|$)`, ` -p `, отсутствие "
                   "`claude_run_with_timeout`) стоя́т ОДНО ЗА ДРУГИМ в голове строки: у "
                   "обёртки имя-исключение кончается на колонке 68, у настоящей сессии "
                   "` -p ` стои́т на колонке 40. Обрезание убирает ПРОМПТ — хвост, которого "
                   "ни одно условие не читает",
    ),
    Door(
        path="scripts/delta_mutation_run.py",
        name="владелец окна мутационного прибора (ПОЧИНЕНА ADR-1031)",
        fmt="lstart=,command=",
        decides="жив ли владелец окна",
        verdict=_d9_verdict, frozen=(_F9,),
        frozen_from="строка раннера CI из ADR-1031: путь интерпретатора "
                    "`/opt/hostedtoolcache/…` сам занимает 50 колонок",
        live=_live_instrument_owner,
    ),
)


DOORS_BY_KEY = {d.key: d for d in DOORS}


#: Потолок поиска ширины срабатывания. Не «на всякий случай»: самая длинная строка
#: процесса на этой машине — 24 672 колонки (промпт headless-сессии), и сканировать её
#: целиком значило бы спрашивать дверь двадцать пять тысяч раз ни за что. Все известные
#: решающие совпадения стоя́т в голове строки, и потолок 240 покрывает их с запасом втрое.
FLIP_SCAN_CEILING = 240


def flip_width(door: "Door", subject: str, ceiling: int = FLIP_SCAN_CEILING):
    """САМАЯ ШИРОКАЯ колонка ≤ `ceiling`, на которой вердикт двери ещё отличается от полного.

    Отвечает на вопрос, которого нет у ярлыка «не переворачивается»: НАСКОЛЬКО дверь
    далека от переворота. Устойчивость с запасом в одну колонку и устойчивость с запасом
    в сорок — разные утверждения, и прозой они неразличимы. `None` — в пределах потолка
    вердикт не менялся ни на одной ширине.

    Монотонности здесь нет и предполагать её нельзя: предикат может читать несколько
    мест строки, поэтому ширина ищется перебором сверху вниз, а не делением отрезка.
    """
    try:
        full_v = door.verdict(subject)
    except Exception:                                               # noqa: BLE001
        return None
    top = min(ceiling, max((len(l) for l in subject.replace("\x00", "\n").splitlines()),
                           default=0))
    for width in range(top, 0, -1):
        try:
            if door.verdict(truncate(subject, width)) != full_v:
                return width
        except Exception:                                           # noqa: BLE001
            continue
    return None


# ── 4. Замер одной двери ─────────────────────────────────────────────────────

def measure(door: Door, texts: Optional[list] = None,
            columns: int = GNU_DEFAULT_COLUMNS) -> dict:
    """Вердикт двери на ПОЛНЫХ и на обрезанных субъектах. Три исхода различимы."""
    subjects = list(door.frozen if texts is None else texts)
    out = {"key": door.key, "path": door.path, "name": door.name, "decides": door.decides,
           "fmt": door.fmt, "asks_ww": None, "columns": columns, "subjects": len(subjects)}
    subjects = [t for t in subjects if str(t or "").strip()]
    if not subjects:
        out.update(outcome=UNMEASURED, subjects=0,
                   why="субъекта нет: дверь читать нечего — спрашивать вердикт не у чего")
        return out
    widest = 0
    flipped = None
    reached = False
    for text in subjects:
        widest = max(widest, max((len(l) for l in text.replace("\x00", "\n").splitlines()),
                                 default=0))
        if max((len(l) for l in text.replace("\x00", "\n").splitlines()), default=0) > columns:
            reached = True
        try:
            full_v = door.verdict(text)
            cut_v = door.verdict(truncate(text, columns))
        except Exception as exc:                                    # noqa: BLE001
            out.update(outcome=UNMEASURED,
                       why=f"дверь не ответила ({type(exc).__name__}: {exc}) — вердикт НЕ ИЗМЕРЕН")
            return out
        if full_v != cut_v and flipped is None:
            flipped = (full_v, cut_v)
    out["widest_line"] = widest
    if flipped is not None:
        out.update(outcome=FLIPS, verdict_full=repr(flipped[0]), verdict_cut=repr(flipped[1]),
                   why=(f"вердикт двери меняется: {flipped[0]!r} на полной строке против "
                        f"{flipped[1]!r} на обрезанной до {columns} колонок"))
        return out
    if not reached:
        out.update(outcome=UNREACHABLE,
                   why=(f"самая длинная строка субъектов — {widest} колонок при пределе "
                        f"{columns}: обрезание до субъектов двери НЕ ДОХОДИТ"))
        return out
    widths = [w for w in (flip_width(door, t) for t in subjects) if w is not None]
    out["flips_at_column"] = max(widths) if widths else None
    out["slack_columns"] = (columns - max(widths)) if widths else None
    slack = ("запас НЕ ИЗМЕРЕН: в пределах потолка сканирования вердикт не менялся ни "
             "на одной ширине" if not widths
             else f"вердикт переворачивается на ширине {max(widths)} — ЗАПАС "
                  f"{columns - max(widths)} колонок до предела {columns}")
    out.update(outcome=STABLE,
               why=(door.stable_why or "причина НЕ НАЗВАНА в объявлении двери") + f". {slack}")
    return out


def is_member(row: dict) -> bool:
    """Член класса — переворачивается И ИЗМЕРЕНО, что `-ww` не просит.

    `asks_ww is None` означает «не измерено» и членом класса НЕ делает: «не знаем» и
    «флага нет» — разные утверждения (инв. #17).
    """
    return row.get("outcome") == FLIPS and row.get("asks_ww") is False


# ── 5. Отчёт ─────────────────────────────────────────────────────────────────

def build_report(*, live: bool = False, root: Path | str | None = None) -> dict:
    surf = surface(root)
    rows = []
    for door in DOORS:
        text = None
        if live:
            try:
                text = door.live() if door.live is not None else live_pair()
                if isinstance(text, str):
                    text = [text]
            except Exception as exc:                                # noqa: BLE001
                rows.append({"key": door.key, "path": door.path, "name": door.name,
                             "outcome": UNMEASURED, "asks_ww": None,
                             "why": f"живой `ps` не ответил ({type(exc).__name__}: {exc})"})
                continue
        rows.append(measure(door, text))
    declared = set(DOORS_BY_KEY)
    measured_sites = {s.key for s in surf["with_command"]}
    lines = {s.key: s.line for s in surf["with_command"]}
    argv_seen = {s.key: list(s.argv) for s in surf["with_command"]}
    ww_seen = {s.key: s.asks_ww for s in surf["with_command"]}
    for r in rows:
        key = r.get("key")
        r["line"] = lines.get(key)
        r["argv_in_source"] = argv_seen.get(key)
        if key in ww_seen:
            r["asks_ww"] = ww_seen[key]          # ИЗМЕРЕНО в исходнике, не объявлено
        elif r.get("outcome") != UNMEASURED:
            r.update(outcome=UNMEASURED, asks_ww=None,
                     why=("дверь объявлена, а в поверхности её НЕТ: зов `ps` с форматом "
                          f"`{r.get('fmt')}` в {r.get('path')} не найден — спрашивать "
                          "`-ww` не у чего"))
    counters = {
        "зовов ps всего": len(surf["sites"]),
        "из них формат несёт command": len(surf["with_command"]),
        "дверей объявлено": len(DOORS),
        "переворачивается": sum(1 for r in rows if r.get("outcome") == FLIPS),
        "не переворачивается": sum(1 for r in rows if r.get("outcome") == STABLE),
        "предел не достигается": sum(1 for r in rows if r.get("outcome") == UNREACHABLE),
        "НЕ ИЗМЕРЕНО": sum(1 for r in rows if r.get("outcome") == UNMEASURED),
        "ЧЛЕНОВ КЛАССА": sum(1 for r in rows if is_member(r)),
    }
    return {"source": "живой ps" if live else "замороженные субъекты 2026-11-16",
            "rows": rows, "counters": counters,
            "unreadable": surf["unreadable"],
            "surface_not_declared": sorted(measured_sites - declared),
            "declared_not_in_surface": sorted(declared - measured_sites),
            "without_command": [s.key for s in surf["without_command"]]}


def format_report(rep: dict) -> str:
    out = [f"класс «вердикт есть свойство ширины вывода ps» — источник: {rep['source']}", ""]
    for r in rep["rows"]:
        mark = {FLIPS: "❌", STABLE: "✅", UNREACHABLE: "·", UNMEASURED: "⚠️"}.get(
            r.get("outcome"), "?")
        ww = {True: "-ww ЕСТЬ", False: "-ww НЕТ"}.get(r.get("asks_ww"), "-ww НЕ ИЗМЕРЕН")
        member = "  ← ЧЛЕН КЛАССА" if is_member(r) else ""
        where = f"{r['path']}:{r.get('line') or '?'}"
        out.append(f"{mark} {where} · {ww} · {r.get('outcome')}{member}")
        out.append(f"    решает: {r.get('decides', '—')}")
        out.append(f"    {r.get('why', '')}")
    out.append("")
    for k, v in rep["counters"].items():
        out.append(f"  {k}: {v}")
    if rep["surface_not_declared"]:
        out.append("")
        out.append("❌ зов `ps` с колонкой command, НЕ объявленный дверью: "
                   + ", ".join(rep["surface_not_declared"]))
    if rep["declared_not_in_surface"]:
        out.append("⚠️ объявленная дверь, которой нет в поверхности: "
                   + ", ".join(rep["declared_not_in_surface"]))
    if rep["unreadable"]:
        out.append("⚠️ НЕ ИЗМЕРЕНО (файл не разобран): "
                   + ", ".join(f"{u['path']} — {u['why']}" for u in rep["unreadable"]))
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--live", action="store_true",
                    help="спросить живой `ps` этой машины вместо замороженных субъектов")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = build_report(live=args.live)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else format_report(rep))
    if rep["counters"]["НЕ ИЗМЕРЕНО"] or rep["unreadable"] or rep["declared_not_in_surface"]:
        return 2
    if rep["counters"]["ЧЛЕНОВ КЛАССА"] or rep["surface_not_declared"]:
        return 1
    return 0


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(main())
