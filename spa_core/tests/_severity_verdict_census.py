"""Перепись ВЕРДИКТ-ДАННЫХ и достижимости у каждой находки третьего исхода.

ЗАКАЗ ЦИКЛА #528, и он назван там дословно: перепись #528
(`_finding_tick_census`) спросила класс целиком у ОДНОГО читателя — шага
0-офис, — потому что прибор построен на ЗНАЧКАХ ПЕЧАТИ. У второго читателя
того же вопроса, `spa_core/monitoring/architecture_conformance.py`, печатей со
значком нет вовсе: он выносит вердикт **данными** — полем `severity` в
`findings[]`. Ограничение было названо, а не обойдено, и заказан перенос
переписи на вердикт-данные.

ЧТО ЗДЕСЬ МЕРИТСЯ. Тот же вопрос, что и в #528, только предмет другой: у
каждого присвоения `severity` — достижим ли ТРЕТИЙ ИСХОД «производитель ещё
не должен был». Утверждение, которое следующий такт снял бы САМ, не имеет
права печататься находкой: у потребителя вердикта
(`findings_bridge.collect_findings` берёт КАЖДУЮ находку этого сторожа БЕЗ
фильтра по severity) слово становится карточкой владельцу.

ЛОВУШКА ЗАКАЗА НАЗВАНА ЗАРАНЕЕ И ОНА ДРУГАЯ, ЧЕМ В #528. У сторожа
архитектуры предмет вердикта — не отчёт соседа, а сам манифест, дерево и
флот, и у БОЛЬШЕЙ ЧАСТИ находок производителя с тактом нет ПО ПРИРОДЕ
(«агент объявлен, точки входа нет»; «локальная курация разошлась с origin»).
Такой ответ полный — но его надо ИЗМЕРИТЬ, а не объявить. Здесь он и
меряется: `BY_NATURE` не берётся на веру ни для одного сайта, он ВЫВОДИТСЯ из
формы сторожа.

КАК РАЗЛИЧАЮТСЯ ИСХОДЫ (форма, не текст).

Утверждение находки САМОРАССАСЫВАЮЩЕЕСЯ ровно тогда, когда её сторож читает
наблюдение, которое производит ОБЪЯВЛЕННЫЙ КОНСТИТУЦИЕЙ ТАКТ. В этом модуле
таких дверей ровно две, и обе — параметры чистого `run_checks`:

* ``ts_of(path)``      — отметка артефакта, её ставит такт ПРОИЗВОДИТЕЛЯ;
* ``receipts[path]``   — ресит потребления, его ставит такт ЧИТАТЕЛЯ.

Всё прочее (``fleet``, ``manifest``, ``drift_problems``, ``curation``,
``contract_audit``, ``manifest_parity``, ``freshness_parity``) — это
ОБЪЯВЛЕНИЕ либо состояние дерева. Их не переписывает никакой такт: чтобы
такая находка ушла, нужна правка кода, манифеста или состава флота. Отсюда
три исхода:

* ``BY_NATURE``  — сторож не читает ни одной тактовой двери. Третий исход
  полон по природе: снимать нечему. НЕ дефект.
* ``TICK_AWARE`` — сторож читает тактовую дверь И спрашивает у такта: в
  условиях, управляющих печатью, стои́т имя, происходящее от ответчика такта
  (``absence_of``, ``freshness_floor``, ``consumption_floor``,
  ``producer_tick_hours``, ``consumer_tick_hours``). Третий исход достижим.
* ``TICK_BLIND`` — сторож читает тактовую дверь и такта НЕ спрашивает.
  **Дефект**: следующий прогон снял бы строку сам, а она уже уехала карточкой.
* ``UNRESOLVED`` — разобрать не вышло. Громко, с названной причиной; молчаливое
  выпадение из населения — ровно тот дефект, ради которого модуль написан.

ПОЧЕМУ ПРОИСХОЖДЕНИЕ ИЩЕТСЯ ДО НЕПОДВИЖНОЙ ТОЧКИ. `budget` происходит от
`floor_h`, тот — от `floor`, тот — от `consumption_floor(...)`. Оборвать цепь
на одном шаге значило бы объявить тактовый бюджет нетактовым и покрасить
исправный сайт. Тот же приём, что у сторожа претензии `injected-clock`
(`spa_core/tests/_injected_clock.py`).

ПОЧЕМУ РАННИЙ ВЫХОД СЧИТАЕТСЯ СТОРОЖЕМ. `B2:missing` спрашивает такт НЕ
объемлющим `if`, а предшествующим `if absence.not_yet: ...; continue`. Это
управляющая конструкция ровно того же действия: печать достижима только когда
условие ложно. Считать сторожем лишь объемлющий `if` значило бы объявить
единственный ПОЧИНЕННЫЙ сайт дефектным — то есть получить прибор, который
краснеет на образце.
"""

from __future__ import annotations

import ast
import os

#: Единственная фабрика вердикт-данных этого сторожа. Вердикт, собранный
#: мимо неё, переписью не виден — и это ограничение проверяется отдельной
#: сценой (`severity` в словаре не через `_finding`).
VERDICT_FACTORY = "_finding"

#: Двери, за которыми лежит НАБЛЮДЕНИЕ, производимое объявленным тактом.
#: Проводка мерится ФОРМОЙ вызова: `ts_of(...)` и `receipts.get(...)` /
#: `receipts[...]`. Переименование локальной переменной её не подделает.
TICK_OBSERVATIONS = ("ts_of", "receipts")

#: Ответчики такта: тот, кто превращает такт конституции в ответ «ещё не
#: должен был». Имя, происходящее от любого из них, считается тактовым.
TICK_ANSWERERS = ("absence_of", "freshness_floor", "consumption_floor",
                  "producer_tick_hours", "consumer_tick_hours")

BY_NATURE = "by_nature"      #: тактовой двери нет — снимать нечему
TICK_AWARE = "tick_aware"    #: тактовая дверь есть, такт спрошен
TICK_BLIND = "tick_blind"    #: тактовая дверь есть, такт НЕ спрошен — дефект
UNRESOLVED = "unresolved"    #: разобрать не вышло — громко, с причиной


class Verdict:
    """Одно присвоение `severity` — один сайт вердикт-данных."""

    def __init__(self, line, func, key, check, severity, outcome, why=""):
        self.line = line
        self.func = func
        self.key = key
        self.check = check
        self.severity = severity
        self.outcome = outcome
        self.why = why

    @property
    def is_defect(self) -> bool:
        return self.outcome == TICK_BLIND

    def __repr__(self):  # pragma: no cover - диагностика
        return (f"<{self.check}:{self.key} стр.{self.line} "
                f"{self.severity} {self.outcome}>")


def _key_prefix(node) -> str | None:
    """Первый аргумент фабрики — ключ находки; берём его СТАБИЛЬНУЮ часть.

    `f"B3:no_consumption:{path}"` ⇒ `B3:no_consumption`. Хвост подставляется и
    к делу не относится: класс находки задаёт именно голова ключа.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        head = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                head += part.value
            else:
                break
        return head.rstrip(":") or None
    return None


def _literal(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def census(path: str) -> list[Verdict]:
    """Перепись сайтов вердикт-данных. Не разобрали файл ⇒ ОДНА `UNRESOLVED`."""
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError) as exc:
        return [Verdict(0, "<файл>", None, None, None, UNRESOLVED,
                        why=f"{os.path.basename(path)} не разобран: {exc}")]

    parent: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def ancestors(node):
        while node in parent:
            node = parent[node]
            yield node

    def enclosing_func(node):
        for anc in ancestors(node):
            if isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return anc
        return None

    def names_in(node) -> set:
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    def reads_observation(node) -> bool:
        """Выражение ЧИТАЕТ тактовую дверь — по форме вызова, не по имени."""
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id in TICK_OBSERVATIONS):
                return True
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and getattr(sub.func.value, "id", None) in TICK_OBSERVATIONS):
                return True
            if (isinstance(sub, ast.Subscript)
                    and getattr(sub.value, "id", None) in TICK_OBSERVATIONS):
                return True
        return False

    def calls_answerer(node) -> bool:
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id in TICK_ANSWERERS):
                return True
        return False

    def origins(fnode) -> tuple[set, set]:
        """Имена, ПРОИСХОДЯЩИЕ от тактовой двери и от ответчика такта.

        Ищется до неподвижной точки: `budget` ← `floor_h` ← `floor` ←
        `consumption_floor(...)`. Обрыв цепи на одном шаге объявил бы
        тактовый бюджет нетактовым.
        """
        assigns = []
        for node in ast.walk(fnode):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    for nm in (t for t in ast.walk(tgt) if isinstance(t, ast.Name)):
                        assigns.append((nm.id, node.value))
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value:
                if isinstance(node.target, ast.Name):
                    assigns.append((node.target.id, node.value))
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                if isinstance(node.optional_vars, ast.Name):
                    assigns.append((node.optional_vars.id, node.context_expr))

        observed: set = set()
        answered: set = set()
        for _ in range(len(assigns) + 2):        # до неподвижной точки
            grew = False
            for name, value in assigns:
                if name not in observed and (reads_observation(value)
                                             or names_in(value) & observed):
                    observed.add(name)
                    grew = True
                if name not in answered and (calls_answerer(value)
                                             or names_in(value) & answered):
                    answered.add(name)
                    grew = True
            if not grew:
                break
        return observed, answered

    def governing_tests(node, fnode) -> list:
        """Условия, управляющие достижимостью печати.

        Два рода, и второй обязателен: объемлющий `if/else` — и ПРЕДШЕСТВУЮЩИЙ
        в том же блоке `if <тест>: ... continue/return/raise`. Ранний выход
        управляет достижимостью ровно так же, и без него единственный
        починенный сайт (`B2:missing`, исход `b2_not_yet` цикла #525) был бы
        объявлен дефектным.
        """
        tests = []
        cur = node
        while cur in parent and cur is not fnode:
            par = parent[cur]
            if isinstance(par, ast.If) and (cur in par.body or cur in par.orelse):
                tests.append(par.test)
            for field in ("body", "orelse", "finalbody"):
                block = getattr(par, field, None)
                if not isinstance(block, list) or cur not in block:
                    continue
                for prev in block[:block.index(cur)]:
                    if not isinstance(prev, ast.If):
                        continue
                    if any(isinstance(s, (ast.Continue, ast.Return, ast.Raise))
                           for s in ast.walk(prev)):
                        tests.append(prev.test)
            cur = par
        return tests

    out: list[Verdict] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == VERDICT_FACTORY):
            continue
        if isinstance(parent.get(node), ast.FunctionDef):
            continue                                  # само определение
        fnode = enclosing_func(node)
        if fnode is None:
            out.append(Verdict(node.lineno, "<модуль>", None, None, None,
                               UNRESOLVED,
                               why="вызов фабрики вне функции — сторожа не разобрать"))
            continue
        args = node.args
        key = _key_prefix(args[0]) if len(args) > 0 else None
        check = _literal(args[1]) if len(args) > 1 else None
        severity = _literal(args[2]) if len(args) > 2 else None
        if key is None or severity is None:
            out.append(Verdict(node.lineno, fnode.name, key, check, severity,
                               UNRESOLVED,
                               why="ключ или severity не литерал — класс находки "
                                   "не назвать, судить о её сторожe нечем"))
            continue

        observed, answered = origins(fnode)
        tests = governing_tests(node, fnode)
        if not tests:
            out.append(Verdict(node.lineno, fnode.name, key, check, severity,
                               UNRESOLVED,
                               why="печать не управляется ни одним условием — "
                                   "сторожа нет, третий исход не о чем спрашивать"))
            continue

        touches_tick = any(reads_observation(t) or (names_in(t) & observed)
                           for t in tests)
        asks_tick = any(calls_answerer(t) or (names_in(t) & answered)
                        for t in tests)
        if not touches_tick:
            outcome, why = BY_NATURE, ("сторож не читает ни ts_of, ни receipts — "
                                       "предмет объявлен либо наблюдён в дереве, "
                                       "и никакой такт находку не снимет")
        elif asks_tick:
            outcome, why = TICK_AWARE, ("сторож читает тактовую дверь и спрашивает "
                                        "такт — третий исход достижим")
        else:
            outcome, why = TICK_BLIND, ("сторож читает тактовую дверь, но такт НЕ "
                                        "спрошен — следующий прогон снял бы строку "
                                        "сам, а она уже уехала карточкой")
        out.append(Verdict(node.lineno, fnode.name, key, check, severity,
                           outcome, why))

    out.sort(key=lambda v: v.line)
    return out


def defects(path: str) -> list[Verdict]:
    """Сайты, у которых третий исход недостижим, и неразобранные — вместе.

    `UNRESOLVED` идёт СЮДА намеренно: «не измерено», выданное за «в порядке», —
    ровно тот дефект, против которого написан модуль.
    """
    return [v for v in census(path) if v.outcome in (TICK_BLIND, UNRESOLVED)]
