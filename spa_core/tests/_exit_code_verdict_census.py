"""Перепись ТРЕТЬЕГО НОСИТЕЛЯ вердикта — кода возврата — и его читаемости.

ЗАКАЗ ЦИКЛА #530 (ADR-266), дословно: оба прежних прибора меряют ПРОИЗВОДИТЕЛЯ
вердикта — #528 (`_finding_tick_census`) по ЗНАЧКАМ ПЕЧАТИ, #530
(`_severity_verdict_census`) по ВЕРДИКТ-ДАННЫМ (поле `severity`). Ни один не
меряет третий род носителя: вердикт, доезжающий до решения **кодом возврата**.
Именно им сторожа разговаривают с launchd, CI и обёртками.

ЛОВУШКА НАЗВАНА ЗАКАЗОМ ЗАРАНЕЕ, И ОНА ТРЕТЬЯ. У кода возврата НЕТ ключа
находки, поэтому «первое наблюдение» ему не с чем сопоставить: гистерезис-
потребитель, спасший `B3` в #530, здесь недоступен ПО ПОСТРОЕНИЮ — код возврата
потребляется немедленно и однократно. Отсюда единственный вывод: третий исход
обязан жить у САМОГО производителя (отдельный код) И быть читаемым у
потребителя. Поэтому мерится не «есть ли у сторожа третий код», а доезжает ли
он до того, кто по нему судит.

КТО ЗДЕСЬ ПОТРЕБИТЕЛЬ. Заказ называет его сам: обёртки `scripts/agent_*.sh` и
то, что делает с ненулевым кодом launchd. Прочитанный из launchd код попадает в
`spa_core/monitoring/agent_health_monitor.py` (`launchctl list` → поле `exit` →
`health.last_exit`), и там же выносится вердикт о здоровье агента. Это и есть
единственная дверь, за которой код возврата превращается в решение.

ЧТО ИЗМЕРЕНО У ПОТРЕБИТЕЛЯ (замер, а не пересказ). Правило потребителя
двузначно: `last_exit not in (None, 0)` ⇒ WARNING с голым `last_exit=N`.
Многозначно код читается РОВНО для тех меток, которые потребитель сравнивает
поимённо (`label == <константа>`) — сегодня такая метка одна,
`com.spa.daily_cycle` (словарь `spa_core/paper_trading/cycle_exit.py`, цикл
#219). Список меток здесь НЕ зашит: он ВЫВОДИТСЯ разбором потребителя, иначе
вторая появившаяся метка осталась бы прибору невидимой.

ПОЧЕМУ ПОПУЛЯЦИЯ — МАНИФЕСТ, А НЕ `scripts/agent_*.sh`. Заказ называет обёртки,
но обёртка — не население: `com.spa.daily_cycle`, единственный ПОЧИНЕННЫЙ сайт
класса, запускается `run_daily_paper_cycle.sh` и под маску `agent_*.sh` не
попадает вовсе. Прибор, построенный на маске имени, не увидел бы свой
собственный образец — то есть не смог бы доказать, что не краснеет на
исправном. Население берётся из объявления: активные агенты
`architecture/manifest.json` (`intent == "active"`), поле `program` — обёртка.

ПОЧЕМУ КОДЫ СОБИРАЮТСЯ ПО ВСЕЙ ЦЕПОЧКЕ. До launchd доезжает код ПОСЛЕДНЕГО
звена, а звеньев обычно два: собственная обёртка агента и общий
`scripts/agent_template.sh`, который запускает python и явно завершается его
кодом (`exit $RC`). Свои литералы есть и у шаблона (`64` — цель не задана,
`75` — окружение не готово после пробуждения). Их вклад считается отдельным
полем: вопрос «говорит ли САМ сторож тремя исходами» и вопрос «доезжает ли
трёхзначность от этой метки» — разные, и смешивать их значило бы ответить
верно не на тот.

ИСХОДЫ (форма, не текст).

* ``NO_CODE_VERDICT`` — до потребителя доезжает меньше ДВУХ различных ненулевых
  кодов. Третьего исхода на этом носителе нет — снимать нечего. НЕ дефект.
* ``LEGIBLE`` — ненулевых кодов ≥2 И потребитель сравнивает эту метку поимённо:
  у кода есть свои слова и свой вес. Третий исход достижим.
* ``ILLEGIBLE`` — ненулевых кодов ≥2, но поимённого разбора этой метки у
  потребителя НЕТ: любой ненулевой становится одним и тем же WARNING.
  **Дефект**: носитель многозначен, чтение двузначно.
* ``MUTED`` — собственный сторож агента ненулевой код производит, но тот
  гасится ДО потребителя (`--exit-zero`, `|| true` на строке запуска).
  **Дефект**, и он тяжелее предыдущего: до launchd не доезжает даже двузначный
  вердикт.
* ``UNRESOLVED`` — разобрать цепочку не вышло. Громко, с названной причиной:
  молчаливое выпадение из населения — ровно тот дефект, ради которого написаны
  все три переписи.

ЧЕГО ЭТОТ ПРИБОР НЕ ДЕЛАЕТ. Он не чинит ни одного сайта и ничего не гасит:
правило потребителя fail-CLOSED (ненулевой код всегда виден) и остаётся как
есть. Он отвечает на ОДИН вопрос — «читается ли третий исход там, где по нему
судят», — и о пределах говорит вслух ниже, в `census`.
"""

from __future__ import annotations

import ast
import json
import os
import re

#: Объявление населения: активные агенты конституции.
MANIFEST = os.path.join("architecture", "manifest.json")

#: Потребитель кода возврата: единственная дверь, за которой `last_exit`
#: превращается в вердикт о здоровье агента.
CONSUMER = os.path.join("spa_core", "monitoring", "agent_health_monitor.py")

#: Общая обёртка флота. Запускает python и завершается ЕГО кодом (`exit $RC`),
#: добавляя к носителю свои литералы.
SHARED_WRAPPER = "agent_template.sh"

NO_CODE_VERDICT = "no_code_verdict"  #: <2 ненулевых кодов — третьего исхода нет
LEGIBLE = "legible"                  #: многозначен и читается многозначно
ILLEGIBLE = "illegible"              #: многозначен, читается двузначно — дефект
MUTED = "muted"                      #: код САМОГО агента принудительно 0 — дефект
MUTED_SIDECAR = "muted_sidecar"      #: свой код цел, но у попутного сторожа погашен
UNRESOLVED = "unresolved"            #: не измерено — громко

_BASH_EXIT = re.compile(r'(?:^|[;&|]|\bthen\b|\belse\b|\bdo\b)\s*exit\s+(\d+)\b')
_PY_INVOKE = re.compile(r'(?:python3?|\$PYTHON|"\$PYTHON")\s')


class Site:
    """Один активный агент — один сайт носителя «код возврата»."""

    def __init__(self, label, program, targets, own, wrapper, carried,
                 outcome, why=""):
        self.label = label
        self.program = program
        self.targets = targets          # разрешённые цели (пути в дереве)
        self.own = own                  # ненулевые коды СОБСТВЕННОГО сторожа
        self.wrapper = wrapper          # ненулевые коды общей обёртки
        self.carried = carried          # что реально доезжает до потребителя
        self.outcome = outcome
        self.why = why

    @property
    def is_defect(self) -> bool:
        return self.outcome in (ILLEGIBLE, MUTED, MUTED_SIDECAR)

    def __repr__(self):  # pragma: no cover - диагностика
        return (f"<{self.label} {self.outcome} own={sorted(self.own)} "
                f"carried={sorted(self.carried)}>")


def _read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None


def _code_lines(src: str):
    """Строки bash, которые ЯВЛЯЮТСЯ КОМАНДАМИ, а не содержимым литерала.

    ЗАЧЕМ, И ЭТО ИЗМЕРЕНО НА ЖИВОМ СЛУЧАЕ. `scripts/agent_orchestrator.sh`
    собирает промпт сессии многострочным присваиванием `PROMPT="…"`, и внутри
    него ПРОЗОЙ написано `python3 scripts/consume_office_reports.py`. Первая
    редакция прибора зачла эту прозу за запуск и приписала
    `com.spa.orchestrator` коды `[1, 3]`, которых обёртка не производит, — то
    есть ИЗГОТОВИЛА находку. Тот же класс, что «перепись сирот считает ПРОЗУ
    в manifest.json проводкой».

    ПОЧЕМУ ПРИЗНАК УЗКИЙ, А НЕ «СОСТОЯНИЕ КАВЫЧКИ ВООБЩЕ». Вторая редакция
    тянула состояние кавычки через весь файл — и рассыпалась на комментариях и
    шаблонах вида `''|*[!0-9]*)`: у `agent_template.sh` пропал его собственный
    `exit 75`, то есть починка одной ложной находки СОЗДАЛА пропуск настоящих.
    Поэтому пропускаются ровно две конструкции, обе опознаваемые по началу:
    многострочное ПРИСВАИВАНИЕ в кавычках и heredoc. Всё прочее — команда.
    """
    lines = src.splitlines()
    out, i = [], 0
    assign = re.compile(r"""^\s*(?:export\s+)?\w+=(["'])""")
    heredoc = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?\s*$")
    while i < len(lines):
        raw = lines[i]
        here = heredoc.search(_strip_comments(raw))
        if here:
            out.append((i + 1, raw))
            terminator = here.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != terminator:
                i += 1
            i += 1
            continue
        m = assign.match(raw)
        if m and not _closes(raw[m.end():], m.group(1)):
            out.append((i + 1, raw))          # сама строка присваивания — команда
            i += 1
            while i < len(lines) and not _closes(lines[i], m.group(1)):
                i += 1
            i += 1
            continue
        out.append((i + 1, raw))
        i += 1
    return out


def _closes(text: str, quote: str) -> bool:
    """Есть ли в тексте НЕэкранированная закрывающая кавычка `quote`."""
    j = 0
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == quote:
            return True
        j += 1
    return False


def _strip_comments(line: str) -> str:
    """Отрезать хвостовой комментарий bash, не тронув `#` внутри кавычек."""
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def consumer_labels(root: str) -> tuple[set, str | None]:
    """Метки, чей КОД ВОЗВРАТА потребитель разбирает поимённо.

    Возвращает (метки, причина-неизмеримости). Список не зашит: вторая
    появившаяся метка обязана стать видимой прибору сама.

    ОБЛАСТЬ СРАВНЕНИЯ СУЖЕНА ЗАМЕРОМ, А НЕ ДОГАДКОЙ. Брать любое `label == …`
    в модуле нельзя: строкой 350 потребитель отбрасывает ШАПКУ вывода
    `launchctl list` (`label == "Label"`), и наивный сбор объявил бы слово
    «Label» меткой флота. Считаются только сравнения внутри функции, которая
    ЧИТАЕТ сам код возврата (`last_exit`), — то есть ровно там, где код
    превращается в вердикт.
    """
    path = os.path.join(root, CONSUMER)
    src = _read(path)
    if src is None:
        return set(), f"потребитель не прочитан: {CONSUMER}"
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return set(), f"потребитель не разобран: {exc}"

    # откуда потребитель импортирует константы меток
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module

    def reads_exit_code(func) -> bool:
        for sub in ast.walk(func):
            if isinstance(sub, ast.Attribute) and sub.attr == "last_exit":
                return True
            if isinstance(sub, ast.Name) and sub.id == "last_exit":
                return True
        return False

    deciders = [n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and reads_exit_code(n)]
    if not deciders:
        return set(), ("у потребителя нет ни одной функции, читающей `last_exit` — "
                       "дверь, за которой код становится вердиктом, не найдена")

    wanted = set()
    for func in deciders:
        for node in ast.walk(func):
            if not isinstance(node, ast.Compare):
                continue
            if not (isinstance(node.left, ast.Name) and node.left.id == "label"):
                continue
            if not any(isinstance(op, ast.Eq) for op in node.ops):
                continue
            for cmp_node in node.comparators:
                if isinstance(cmp_node, ast.Constant) and isinstance(cmp_node.value, str):
                    wanted.add(("<литерал>", cmp_node.value))
                elif isinstance(cmp_node, ast.Name):
                    wanted.add((cmp_node.id, None))

    labels, unresolved = set(), []
    for name, literal in wanted:
        if literal is not None:
            labels.add(literal)
            continue
        module = imported.get(name)
        if module is None:
            unresolved.append(name)
            continue
        mod_path = os.path.join(root, *module.split(".")) + ".py"
        mod_src = _read(mod_path)
        if mod_src is None:
            unresolved.append(name)
            continue
        try:
            mod_tree = ast.parse(mod_src)
        except SyntaxError:
            unresolved.append(name)
            continue
        found = False
        for node in ast.walk(mod_tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == name:
                        labels.add(node.value.value)
                        found = True
        if not found:
            unresolved.append(name)
    if unresolved:
        return labels, ("имя метки у потребителя не разрешилось: "
                        + ", ".join(sorted(unresolved)))
    return labels, None


def _bash_codes(src: str) -> set:
    """Ненулевые литералы `exit N` в bash. `exit "$rc"` — не литерал, а проброс."""
    codes = set()
    for _, raw in _code_lines(src):
        line = _strip_comments(raw)
        for m in _BASH_EXIT.finditer(line):
            code = int(m.group(1))
            if code:
                codes.add(code)
    return codes


def _muting(src: str, filename: str) -> list:
    """Строки, гасящие код запускаемого сторожа ДО потребителя.

    Признак — ФОРМА строки, а не наличие слова: и `--exit-zero`, и `|| true`
    считаются только там, где строка ДЕЙСТВИТЕЛЬНО запускает сторожа (python
    либо общая обёртка). Иначе гасящей объявлялась бы любая строка, где флаг
    просто упомянут — комментарий или `echo` в лог, — а прибор, краснеющий на
    упоминании, ничем не лучше прибора, молчащего на деле.
    """
    out = []
    for i, raw in _code_lines(src):
        line = _strip_comments(raw).strip()
        if not line:
            continue
        invokes = bool(_PY_INVOKE.search(line)) or SHARED_WRAPPER in line
        if not invokes:
            continue
        if "--exit-zero" in line:
            out.append(f"{filename}:{i} флаг --exit-zero гасит код у производителя")
        elif re.search(r'\|\|\s*true\s*$', line):
            out.append(f"{filename}:{i} `|| true` на строке запуска python")
    return out


def _preserves_rc(src: str) -> bool:
    """Сохраняет ли обёртка код запущенного сторожа собственным `exit $VAR`?

    РАЗЛИЧИЕ ИЗМЕРЕНО, А НЕ ПРЕДПОЛОЖЕНО. Обе обёртки ниже несут `|| true`, но
    последствия у них ПРОТИВОПОЛОЖНЫЕ, потому что статус скрипта — это статус
    ПОСЛЕДНЕЙ команды:

    * `agent_swarm_health.sh` берёт `RC=$?` сразу после общей обёртки и
      заканчивается `exit $RC` — код основного сторожа доезжает; погашены лишь
      ДВА попутных запуска;
    * `agent_aggressive_lab.sh` `$?` не берёт вовсе, и последней строкой стои́т
      `python3 … || true` — значит агент отдаёт launchd **ноль всегда**, и код
      основного сторожа (`aggressive_lab.run` отвечает `64` на неизвестный
      режим, fail-CLOSED) не доезжает НИКОГДА.

    Считать их одним исходом значило бы назвать верным словом две разные вещи.
    """
    for _, raw in _code_lines(src):
        line = _strip_comments(raw).strip()
        if re.match(r'^exit\s+"?\$\{?\w+', line):
            return True
    return False


def _wrapper_targets(src: str):
    """Цели, запускаемые обёрткой: (род, строка-цель).

    Разбираются ТОЛЬКО строки-команды (`_code_lines`): упоминание запуска
    внутри многострочного промпта — проза, а не проводка.
    """
    tg = []
    code_src = "\n".join(raw for _, raw in _code_lines(src))
    for m in re.finditer(r'^\s*(?:export\s+)?MODULE="([^"$]+)"', code_src, re.M):
        tg.append(("module", m.group(1)))
    for m in re.finditer(r'^\s*(?:export\s+)?RUN_SCRIPT="([^"$]+)"', code_src, re.M):
        tg.append(("script", m.group(1)))
    for m in re.finditer(r'agent_template\.sh(?:\s*\\\s*\n)?\s+(\S+)\s+([^\s"\';|]+)', code_src):
        target = m.group(2)
        tg.append(("script" if target.endswith(".py") else "module", target))
    for _, raw in _code_lines(src):
        line = _strip_comments(raw)
        for m in re.finditer(r'(?:python3?|\$PYTHON|"\$PYTHON")\s+-m\s+([\w\.]+)', line):
            tg.append(("module", m.group(1)))
        for m in re.finditer(r'(?:python3?|\$PYTHON|"\$PYTHON")\s+"?([^\s"\';|]+\.py)"?', line):
            tg.append(("script", m.group(1)))
    seen, out = set(), []
    for kind, target in tg:
        if (kind, target) not in seen:
            seen.add((kind, target))
            out.append((kind, target))
    return out


def _resolve_target(root: str, kind: str, target: str):
    if kind == "module":
        path = os.path.join(root, *target.split(".")) + ".py"
        return path if os.path.exists(path) else None
    path = target
    if "/Documents/SPA_Claude/" in path:
        path = os.path.join(root, path.split("/Documents/SPA_Claude/", 1)[1])
    elif not path.startswith("/"):
        path = os.path.join(root, path)
    return path if os.path.exists(path) else None


def _int_literal(node, consts, out):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            out.add(1 if node.value else 0)
        elif isinstance(node.value, int):
            out.add(node.value)
    elif isinstance(node, ast.Name) and node.id in consts:
        out.add(consts[node.id])
    elif isinstance(node, ast.IfExp):
        _int_literal(node.body, consts, out)
        _int_literal(node.orelse, consts, out)


def _python_codes(path: str):
    """Ненулевые коды, которыми python-цель отвечает миру. (коды, причина)."""
    src = _read(path)
    if src is None:
        return None, f"{os.path.basename(path)} не прочитан"
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as exc:
        return None, f"{os.path.basename(path)} не разобран: {exc}"

    consts: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int) and not isinstance(node.value.value, bool):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    consts[tgt.id] = node.value.value
        elif isinstance(node, ast.Assign) and node.targets \
                and isinstance(node.targets[0], ast.Tuple) and isinstance(node.value, ast.Tuple):
            names = [t.id for t in node.targets[0].elts if isinstance(t, ast.Name)]
            values = [e.value for e in node.value.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, int)
                      and not isinstance(e.value, bool)]
            if len(names) == len(values):
                consts.update(dict(zip(names, values)))

    codes: set = set()
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    roots = [funcs["main"]] if "main" in funcs else [tree]
    for root_node in roots:
        for node in ast.walk(root_node):
            if isinstance(node, ast.Return) and node.value is not None:
                _int_literal(node.value, consts, codes)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        is_exit = (isinstance(node.func, ast.Attribute) and node.func.attr == "exit"
                   and getattr(node.func.value, "id", None) == "sys")
        is_raise = isinstance(node.func, ast.Name) and node.func.id == "SystemExit"
        if not (is_exit or is_raise):
            continue
        if isinstance(node.args[0], ast.Call):
            continue                      # sys.exit(main()) — коды берутся из main
        _int_literal(node.args[0], consts, codes)
    return {c for c in codes if c}, None


def census(root: str) -> list[Site]:
    """Перепись сайтов носителя «код возврата».

    ПРЕДЕЛЫ, НАЗВАННЫЕ ВСЛУХ. (1) Прибор меряет ЛИТЕРАЛЬНЫЕ коды: код,
    вычисленный из данных, ему не виден — это закреплено отдельной сценой.
    (2) Он судит о ЧИТАЕМОСТИ у потребителя, а не о правильности самого кода:
    «код 5 значит ровно то, что о нём написано» — другой вопрос и другой
    сторож. (3) Население — ОБЪЯВЛЕНИЕ конституции; агент, живущий в launchd
    мимо манифеста, сюда не попадёт, и на этот вопрос отвечает
    `architecture_conformance`, а не эта перепись.
    """
    manifest_path = os.path.join(root, MANIFEST)
    raw = _read(manifest_path)
    if raw is None:
        return [Site("<манифест>", None, [], set(), set(), set(), UNRESOLVED,
                     why=f"{MANIFEST} не прочитан — населения нет")]
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        return [Site("<манифест>", None, [], set(), set(), set(), UNRESOLVED,
                     why=f"{MANIFEST} не разобран: {exc}")]

    labels, labels_error = consumer_labels(root)
    shared_src = _read(os.path.join(root, "scripts", SHARED_WRAPPER))
    shared_codes = _bash_codes(shared_src) if shared_src else set()

    out: list[Site] = []
    for agent in manifest.get("agents", []):
        if agent.get("intent") != "active":
            continue
        label = agent.get("label") or "<без метки>"
        program = agent.get("program")
        if not program:
            out.append(Site(label, program, [], set(), set(), set(), UNRESOLVED,
                            why="в манифесте у активного агента нет `program`"))
            continue
        wrapper_path = os.path.join(root, "scripts", program)
        src = _read(wrapper_path)
        if src is None:
            out.append(Site(label, program, [], set(), set(), set(), UNRESOLVED,
                            why=f"обёртка scripts/{program} не прочитана"))
            continue

        uses_shared = SHARED_WRAPPER in src and program != SHARED_WRAPPER
        wrapper_codes = _bash_codes(src) | (shared_codes if uses_shared else set())
        muting = _muting(src, program)

        own_codes: set = set()
        targets: list = []
        unresolved_reason = None
        for kind, target in _wrapper_targets(src):
            path = _resolve_target(root, kind, target)
            if path is None:
                continue                   # не наш производитель (uvicorn, npx, …)
            targets.append(os.path.relpath(path, root))
            codes, err = _python_codes(path)
            if codes is None:
                unresolved_reason = err
                break
            own_codes |= codes

        if unresolved_reason:
            out.append(Site(label, program, targets, set(), wrapper_codes, set(),
                            UNRESOLVED, why=unresolved_reason))
            continue

        if muting and own_codes:
            if _preserves_rc(src):
                # Код основного сторожа обёртка сохраняет (`exit $RC`); погашен
                # ПОПУТНЫЙ запуск — его вердикт не читает никто.
                out.append(Site(label, program, targets, own_codes, wrapper_codes,
                                own_codes | wrapper_codes, MUTED_SIDECAR,
                                why=("код основного сторожа обёртка сохраняет "
                                     "(`exit $RC`), но вердикт попутного запуска "
                                     "погашен и не доезжает ни до кого: "
                                     + "; ".join(muting))))
            else:
                out.append(Site(label, program, targets, own_codes, wrapper_codes,
                                set(), MUTED,
                                why=("обёртка `$?` не берёт, а последней командой "
                                     "стои́т глушение — агент отдаёт launchd НОЛЬ "
                                     "всегда, код сторожа не доезжает никогда: "
                                     + "; ".join(muting))))
            continue

        carried = own_codes | wrapper_codes
        # ВЕРДИКТ ВЫНОСИТСЯ ПО СОБСТВЕННЫМ КОДАМ СТОРОЖА, а не по всему, что
        # доезжает. Общая обёртка добавляет свои литералы КАЖДОМУ, кто её
        # зовёт, — это ОДИН факт про флот, а не 67 приговоров отдельным
        # агентам. Списывать общий вклад в актив каждому значило бы выдать
        # групповой срез за приговор элементу; сам общий вклад называется
        # отдельно (`shared_wrapper_contribution`) и ровно один раз.
        if len(own_codes) < 2:
            outcome = NO_CODE_VERDICT
            why = (f"собственных ненулевых кодов у сторожа {sorted(own_codes) or 'нет'}"
                   " — третьего исхода на этом носителе он не несёт")
        elif labels_error is not None:
            outcome = UNRESOLVED
            why = labels_error
        elif label in labels:
            outcome = LEGIBLE
            why = "потребитель разбирает эту метку поимённо — у кода свои слова и свой вес"
        else:
            outcome = ILLEGIBLE
            why = (f"сторож говорит кодами {sorted(own_codes)}, но поимённого "
                   "разбора этой метки у потребителя нет — любой ненулевой "
                   "становится одним и тем же WARNING")
        out.append(Site(label, program, targets, own_codes, wrapper_codes,
                        carried, outcome, why))

    out.sort(key=lambda s: s.label)
    return out


def defects(root: str) -> list[Site]:
    """Сайты с недостижимым третьим исходом и НЕразобранные — вместе.

    `UNRESOLVED` идёт СЮДА намеренно, как и в двух предыдущих переписях:
    «не измерено», выданное за «в порядке», — ровно тот дефект, против которого
    написан модуль.
    """
    return [s for s in census(root) if s.is_defect or s.outcome == UNRESOLVED]


def shared_wrapper_contribution(root: str) -> dict:
    """Что общая обёртка добавляет к носителю КАЖДОМУ, кто её зовёт.

    Отдельная функция, а не поле вердикта, — потому что это ОДИН факт про
    флот. `scripts/agent_template.sh` завершается собственными литералами
    (`64` — цель не задана, `75` — окружение не готово после пробуждения), и
    комментарий рядом с `75` прямо утверждает: «so monitoring can tell a
    transient wake failure apart from a logic failure (code=1) or a config
    failure (78)». Утверждение проверяемо у потребителя — и здесь считается,
    для скольких меток оно сегодня верно.

    Возвращает: коды обёртки, число агентов, которым она их даёт, и число
    меток, у которых потребитель эти коды разбирает поимённо.
    """
    shared_src = _read(os.path.join(root, "scripts", SHARED_WRAPPER))
    codes = _bash_codes(shared_src) if shared_src else set()
    labels, _ = consumer_labels(root)
    users = [s for s in census(root)
             if s.wrapper & codes and s.program != SHARED_WRAPPER]
    return {
        "codes": sorted(codes),
        "agents": len(users),
        "decoded_labels": sorted(label for label in labels
                                 if label in {s.label for s in users}),
    }
