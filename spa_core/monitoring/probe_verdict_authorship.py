"""Чья мера произвела вердикт пробы приёмки: ПРИБОР или САМА ПРОБА.

Заказ владельца **G96 п. 3** (хвост `ADR-508`, 29.09) дословно: «Проба, не имеющая
своего порога, обязана быть отличима от пробы, имеющей его. Две привязки
(`Economics`, `Persistence`) переносят вердикт прибора целиком; остальные пробы
реестра судят сами. Сегодня в реестре это не объявлено ничем, и читатель сводки не
может отличить „критерий не выполнен по мере прибора“ от „критерий не выполнен по
мере пробы“. Замерить население обоих родов и решить, объявляется ли род полем.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
Сводка §49 (`scripts/cio_acceptance_rollup.py`) печатает строку вида
``❌ НЕ ВЫПОЛНЕН  Economics  [economics_net_return_dominates_keep]`` — и у читателя
нет НИ ОДНОГО признака, по которому он отличил бы два разных утверждения:

* «перепись `keep_dominance_census` объявила находку» — порог чужой, обоснован
  докладом прибора и закреплён его тестами;
* «проба сама сравнила число с порогом, который написан у неё в теле» — порог её
  собственный, и спорить о нём надо с ней.

Цена различия не в аккуратности формулировки. Красная строка первого рода
оспаривается у прибора, вторая — у пробы; читатель, не знающий рода, идёт не к тому
адресату и правит не то место. Это тот же дефект, что `.claude/rules/site-numbers.md`
называет «вторым местом для числа», только здесь второе место — для ПОРОГА.

Род НЕ объявляется рукописным полем — он ИЗМЕРЯЕТСЯ (решение ADR-559)
---------------------------------------------------------------------------
Заказ оставил выбор открытым: «решить, объявляется ли род полем». Решение —
**не объявлять**, и причина измерена этим же рядом дважды:

* рукописное поле есть ПРЕТЕНЗИЯ о форме кода, а претензии в этом репозитории
  ветшают молча: пометка ``FROZEN-DATE-OK: injected-clock`` держалась на 51 файле
  и до цикла #477 её не сверял с кодом НИКТО (`.claude/rules/deployment.md`);
* род механически читается из решающего пути самой пробы, поэтому поле было бы
  второй копией уже имеющегося факта — и разошлось бы с ним при первой же правке
  тела пробы (ADR-220: две копии одной мерки расходятся молча).

Объявляется другое, и оно уже объявлено: ИМЯ прибора. Проба грузит его по имени
(`_keep_dominance_module` → `KEEP_DOMINANCE_MODULE`), и это объявление невозможно
забыть обновить — без него проба не работает вовсе.

Как мерится род: ОТ ВЕРДИКТА НАЗАД
---------------------------------------------------------------------------
Провенанс мерится от потребителя назад (урок ADR-258), а потребитель здесь —
``return``, отдающий вердикт. Для каждой зарегистрированной пробы:

1. собираются РЕШАЮЩИЕ места — ``return``, чей нулевой слот есть `satisfied` или
   `not_satisfied`;
2. у каждого места собирается ОХРАНА — тесты объемлющих ``if``, тест условного
   выражения в самом ``return`` и тесты ПРЕДШЕСТВУЮЩИХ ``if`` того же блока (место,
   до которого дошли проваливанием, охраняется их отрицанием, и не считать их
   охраной значило бы объявить безусловным последний ``return`` цепочки);
3. охрана, сравнивающая значение с КОНСТАНТОЙ ВЕРДИКТА чужого прибора, означает
   перенос; любая другая — собственное правило.

**Решающий путь — только `satisfied`/`not_satisfied`, и это существенно.** У
`Economics` есть свои пороги (`DECISION_JOURNAL_MAX_AGE_D`), но они стои́т на
ТРЕТЬЕМ исходе: ими проба отказывается мерить, а не судит критерий. Правило,
читающее всё тело, назвало бы её судящей самой — и дало бы ложным членом каждую
пробу ряда, потому что отказ по свежести есть у всех. Это ровно тот разбор, что
ADR-558 провёл над `.replace`: признак надо брать у ПРЕДМЕТА, а не у окрестности.

**Константа вердикта узнаётся ПО СЛОВУ, а не по приставке.** В дереве два диалекта
одного объекта — `census.STATUS_OK` и `meter.CRITERION_SATISFIED`; правило по
приставке ``STATUS_`` потеряло бы три пробы из восьми. И наоборот: `ds.STATUS_FILENAME`
приставку несёт, а вердиктом не является вовсе — это ИМЯ ФАЙЛА. Поэтому имя
атрибута разбирается на слова по ``_`` и хотя бы одно слово обязано быть словом
вердикта (ADR-333: сверка по слову, не подстрокой).

**База сравнения обязана быть ЧУЖИМ ПРИБОРОМ, а не любым именем.** Имя признаётся
прибором, только если оно связано в той же области видимости вызовом функции,
которая ВОЗВРАЩАЕТ МОДУЛЬ (в теле — `importlib.import_module` либо
`spec_from_file_location`). Признак «имя похоже на прибор» здесь был бы той же
претензией без сверки.

**Вердикт, перенесённый через помощника, остаётся вердиктом ПОМОЩНИКА.** Пробы
`Risk`, `Anti-churn`, `Pre-trade safety` отдают `return verdict, why`, где `verdict`
пришёл из помощника того же модуля. Шаг в помощника несущий (иначе место стало бы
«непрочитанным»), но авторство берётся у ТОГО, кто вердикт произвёл; якорь звавшего
только впускал к нему.

Четыре исхода, и они различимы (инв. #17)
---------------------------------------------------------------------------
``transcribed`` — все решающие места охраняются чужой константой вердикта ·
``self_judged`` — ни одно · ``mixed`` — часть да, часть нет (читатель не может
приписать красную строку никому) · ``unmeasured`` — решающий путь ПРОЧИТАТЬ НЕ
ВЫШЛО (нулевой слот не разобран, глубина помощников исчерпана, решающих мест нет
вовсе). Последнее — не ноль и не «чисто»: причина называется, код возврата
ненулевой.

Прибор только ЧИТАЕТ: `applied=False`. Он не правит ни одной пробы и ни одного
реестра.

НЕ ДОКЛАДЫВАЕТ
---------------------------------------------------------------------------
* откуда взят ЛЕВЫЙ операнд сравнения с константой вердикта (что он пришёл из
  доклада прибора — не спрашивается);
* существует ли названная константа у прибора на самом деле (сравнение с
  несуществующим атрибутом было бы мёртвым переносом);
* ПРАВ ли прибор, чей вердикт переносится, — род отвечает на вопрос «чья мера»,
  а не «верна ли она»;
* пробу, собирающую вердикт в рантайме (имя функции из строки) — такой в реестре
  сегодня нет, и её появление прибор назовёт `unmeasured`, а не пропустит.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys

#: Разбираемый источник — модуль реестра проб. Один файл, и это не экономия:
#: реестр `PROBES` и тела проб обязаны читаться из ОДНОЙ копии, иначе прибор
#: судил бы о паре «реестр одного дерева × тело другого».
SOURCE_REL = "spa_core/monitoring/card_acceptance.py"

KIND_TRANSCRIBED = "transcribed"
KIND_SELF_JUDGED = "self_judged"
KIND_MIXED = "mixed"
KIND_UNMEASURED = "unmeasured"

KIND_RU = {
    KIND_TRANSCRIBED: "ПРИБОР (перенос вердикта)",
    KIND_SELF_JUDGED: "САМА ПРОБА (свой порог)",
    KIND_MIXED: "СМЕШАННАЯ (часть мест переносит, часть судит сама)",
    KIND_UNMEASURED: "НЕ ИЗМЕРЕНА (решающий путь не прочитан)",
}

#: Нулевой слот, в котором стои́т `None`, означает «вердикта НЕТ» — помощник
#: отказался судить и отдал решение звавшему. Это ПРОЧИТАННОЕ значение, а не
#: непрочитанное: смешать их значило бы объявить непрочитанным решающий путь
#: каждой пробы ряда, которая спрашивает помощника о живости дерева.
NO_VERDICT = "NO_VERDICT"

GUARD_FOREIGN = "foreign_verdict"
GUARD_OWN = "own_rule"
GUARD_UNREADABLE = "unreadable"

#: Слова вердикта. Это ВЫБОР прибора, а не свойство дерева, поэтому отвергнутые
#: словарём атрибуты печатаются отдельной осью: читатель видит цену выбора, а не
#: верит ему на слово.
VERDICT_WORDS = frozenset({"OK", "WARNING", "CRITICAL", "SATISFIED", "UNMEASURED"})

#: Предел обхода помощников. ВЫБОР, и он назван: цепочка глубже предела даёт
#: третий исход с причиной, а не молчаливое «своё правило».
HELPER_DEPTH = 6


class Unmeasured(RuntimeError):
    """Источник не прочитан: вердикта о населении нет ВОВСЕ, и это не ноль."""


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _module_constants(tree: ast.Module) -> dict:
    """Модульные строковые константы источника: имя → значение."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _loader_names(tree: ast.Module) -> dict:
    """Функции источника, ВОЗВРАЩАЮЩИЕ чужой модуль: имя → имя модуля (или None).

    Признак — не имя функции, а наличие в её теле настоящей двери импорта.
    Имя функции здесь было бы претензией, а дверь — наблюдением.
    """
    consts = _module_constants(tree)
    out = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dotted = None
        found = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fname = sub.func.attr if isinstance(sub.func, ast.Attribute) else \
                getattr(sub.func, "id", "")
            if fname in ("import_module", "spec_from_file_location", "__import__"):
                found = True
                for arg in sub.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        dotted = dotted or arg.value
                    elif isinstance(arg, ast.Name) and arg.id in consts:
                        dotted = dotted or consts[arg.id]
        if found:
            out[node.name] = dotted
    return out


def _is_verdict_attr(attr: str) -> bool:
    """Имя атрибута названо вердиктом ПО СЛОВУ (`STATUS_FILENAME` — нет)."""
    return bool(VERDICT_WORDS & set(attr.split("_")))


class _Scope:
    """Одна функция источника: её возвраты, охраны и связанные имена."""

    def __init__(self, fn: ast.AST):
        self.fn = fn
        self.name = getattr(fn, "name", "<lambda>")
        self.bindings: dict = {}      # имя → ast.Call, которым оно связано
        self.nested: dict = {}        # вложенные определения этой области
        self.sites: list = []         # (Return, объемлющие тесты, предшествующие if)
        self._collect(fn.body, (), ())

    def _collect(self, body, enclosing, preceding):
        running = list(preceding)
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Вложенное определение — СВОЯ область: у его `return` свой звавший,
                # и приписывать его исход внешней мере нельзя.
                self.nested[stmt.name] = stmt
                continue
            if isinstance(stmt, ast.ClassDef):
                continue
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        # Имя связано ЦЕЛЫМ возвратом вызова: нулевой слот у него
                        # тот же, что у вызванного.
                        self.bindings[target.id] = (stmt.value, 0)
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        # Распаковка `verdict, why = helper(...)` — ровно та форма,
                        # которой пользуются пробы ряда. Запоминается НОМЕР слота:
                        # имя из первого слота несёт вердикт, из второго — причину,
                        # и путать их значило бы судить о тексте как о статусе.
                        for idx, elt in enumerate(target.elts):
                            if isinstance(elt, ast.Name):
                                self.bindings[elt.id] = (stmt.value, idx)
            if isinstance(stmt, ast.Return):
                self.sites.append((stmt, enclosing, tuple(running)))
                continue
            if isinstance(stmt, ast.If):
                self._collect(stmt.body, enclosing + (stmt.test,), tuple(running))
                self._collect(stmt.orelse, enclosing + (stmt.test,), tuple(running))
                # Место, до которого дошли ПРОВАЛИВАНИЕМ, охраняется отрицанием
                # этого теста — но отрицание переносит вердикт НЕ ВСЕГДА, поэтому
                # предшествующие `if` живут ОТДЕЛЬНЫМ списком, а не в одном
                # кортеже с объемлющими (разбор — в `_fallthrough_anchor`).
                running.append(stmt)
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.With,
                                 ast.AsyncWith, ast.Try)):
                for attr in ("body", "orelse", "finalbody"):
                    self._collect(getattr(stmt, attr, None) or [], enclosing,
                                  tuple(running))
                for handler in getattr(stmt, "handlers", None) or []:
                    self._collect(handler.body, enclosing, tuple(running))
                continue
            if isinstance(stmt, ast.Match):
                for case in stmt.cases:
                    self._collect(case.body, enclosing, tuple(running))
                continue

    def instruments(self, loaders: dict) -> dict:
        """Имена этой области, связанные чужим прибором: имя → имя модуля."""
        out = {}
        for name, (call, _slot) in self.bindings.items():
            callee = call.func
            fname = callee.attr if isinstance(callee, ast.Attribute) else \
                getattr(callee, "id", "")
            if fname in loaders:
                out[name] = loaders[fname] or fname
            elif fname in ("import_module", "__import__"):
                arg = call.args[0] if call.args else None
                out[name] = arg.value if isinstance(arg, ast.Constant) else fname
        return out


def _guard_anchor(tests, instruments) -> str | None:
    """Чужая константа вердикта в охране — вернуть её запись, иначе None."""
    for test in tests:
        for node in ast.walk(test):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if not isinstance(base, ast.Name) or base.id not in instruments:
                continue
            if _is_verdict_attr(node.attr):
                return f"{base.id}.{node.attr} ({instruments[base.id]})"
    return None


def _rejected_anchors(scope: _Scope, instruments) -> list:
    """Атрибуты прибора, отвергнутые СЛОВАРЁМ — цена выбора словаря, вслух."""
    out = []
    for node in ast.walk(scope.fn):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in instruments and not _is_verdict_attr(node.attr):
            out.append(f"{node.value.id}.{node.attr}")
    return sorted(set(out))


def _slot_zero(value: ast.AST) -> list:
    """Выражения НУЛЕВОГО слота возврата и тест, выбравший каждое (IfExp)."""
    first = value.elts[0] if isinstance(value, ast.Tuple) and value.elts else value
    if isinstance(first, ast.IfExp):
        return [(first.body, first.test), (first.orelse, first.test)]
    return [(first, None)]


class _Reader:
    """Разбор одного источника: от вердикта назад, с памятью по областям."""

    def __init__(self, path: pathlib.Path):
        try:
            self.text = path.read_text(encoding="utf-8")
            self.tree = ast.parse(self.text)
        except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
            raise Unmeasured(f"{path} не разобран: {type(exc).__name__}: {exc}") from exc
        self.path = path
        self.consts = _module_constants(self.tree)
        self.loaders = _loader_names(self.tree)
        self.funcs = {n.name: n for n in self.tree.body
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.registry = self._registry()
        self.status_by_name = {k: v for k, v in self.consts.items()
                               if k in ("SATISFIED", "NOT_SATISFIED", "UNMEASURED")}
        self.status_by_value = {v: k for k, v in self.status_by_name.items()}
        self._scopes: dict = {}

    def _registry(self) -> dict:
        """Реестр `PROBES` из разбора, а не из импорта.

        Из разбора — потому что прибор обязан судить о ТОМ ЖЕ тексте, у которого
        читает тела проб: импортированный реестр пришёл бы из `sys.path`, то есть
        возможно из другого дерева, и пара «реестр × тело» разъехалась бы молча.
        """
        for node in self.tree.body:
            target = None
            if isinstance(node, ast.AnnAssign):
                target = node.target
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != "PROBES":
                continue
            if not isinstance(node.value, ast.Dict):
                raise Unmeasured("реестр PROBES не является словарём в разборе — "
                                 "население проб НЕ ИЗМЕРЕНО")
            out = {}
            for key, val in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and isinstance(val, ast.Name):
                    out[key.value] = val.id
                else:
                    out[ast.dump(key)[:40]] = None
            return out
        raise Unmeasured("реестра PROBES в источнике нет — мерить население нечем")

    def scope(self, fn) -> _Scope:
        key = id(fn)
        if key not in self._scopes:
            self._scopes[key] = _Scope(fn)
        return self._scopes[key]

    def _resolve_status(self, expr, scope: _Scope, depth: int):
        """Нулевой слот → список статусов (имена констант) либо None, если не прочитан."""
        if isinstance(expr, ast.Name):
            if expr.id in self.status_by_name:
                return [expr.id]
            bound = scope.bindings.get(expr.id)
            if bound is not None:
                call, slot = bound
                if slot != 0:
                    # Имя из НЕнулевого слота вердиктом не является по
                    # построению; выдать его за статус значило бы судить о
                    # строке причины как о вердикте.
                    return None
                return self._statuses_of_call(call, scope, depth)
            return None
        if isinstance(expr, ast.Constant):
            if expr.value is None:
                return [NO_VERDICT]
            if isinstance(expr.value, str):
                got = self.status_by_value.get(expr.value)
                return [got] if got else None
            return None
        if isinstance(expr, ast.Call):
            return self._statuses_of_call(expr, scope, depth)
        return None

    def _statuses_of_call(self, call: ast.Call, scope: _Scope, depth: int):
        callee = call.func
        name = getattr(callee, "id", None)
        if name is None:
            return None
        target = scope.nested.get(name) or self.funcs.get(name)
        if target is None:
            return None
        if depth >= HELPER_DEPTH:
            return None
        sites = self.sites_of(target, depth + 1)
        if any(s["guard"] == GUARD_UNREADABLE for s in sites):
            return None
        return sorted({s["status"] for s in sites})

    def sites_of(self, fn, depth: int = 0) -> list:
        """Места возврата функции: статус · охрана · строка · через кого.

        Проходов ДВА, и второй существует из-за ИЗМЕРЕННОГО ложного члена
        (`pr_work_arrived_on_main`): сперва читаются ОБЪЕМЛЮЩИЕ охраны, и только
        потом — проваливание, потому что вопрос «а что отдала та ветка» имеет
        ответ лишь после первого прохода.
        """
        scope = self.scope(fn)
        instruments = scope.instruments(self.loaders)
        raw = []
        for node, enclosing, preceding in scope.sites:
            if node.value is None:
                continue
            for expr, extra in _slot_zero(node.value):
                tests = list(enclosing) + ([extra] if extra is not None else [])
                raw.append({"node": node, "expr": expr, "tests": tests,
                            "preceding": preceding,
                            "anchor": _guard_anchor(tests, instruments),
                            "statuses": self._resolve_status(expr, scope, depth)})

        # Проход 1: какие `if` своей ВЕТКОЙ отдали РЕШАЮЩИЙ вердикт по чужому
        # якорю. Только такие переносят вердикт и проваливанием.
        carried = set()
        for item in raw:
            if not item["anchor"] or not item["statuses"]:
                continue
            if not ({"SATISFIED", "NOT_SATISFIED"} & set(item["statuses"])):
                continue
            for test in item["tests"]:
                carried.add(id(test))

        out = []
        for item in raw:
            node, expr, statuses = item["node"], item["expr"], item["statuses"]
            if statuses is None:
                out.append({"status": None, "guard": GUARD_UNREADABLE,
                            "line": node.lineno, "via": None, "anchor": None,
                            "expr": ast.dump(expr)[:70]})
                continue
            anchor = item["anchor"]
            if not anchor and not item["tests"]:
                # Проваливание спрашивается ТОЛЬКО у места без собственной
                # охраны. Место, стоящее внутри своего `if`, добавило к ответу
                # прибора СВОЁ условие — и вердикт там уже не чужой, даже если
                # предшествующая анкерная ветка была решающей.
                anchor = self._fallthrough_anchor(item["preceding"], carried,
                                                  instruments)
            via = None
            if isinstance(expr, (ast.Name, ast.Call)) and \
                    not (isinstance(expr, ast.Name) and expr.id in self.status_by_name):
                if isinstance(expr, ast.Call):
                    callee = expr.func
                else:
                    bound = scope.bindings.get(expr.id)
                    callee = bound[0].func if bound else None
                via = getattr(callee, "id", None)
            for status in statuses:
                # Вердикт, пришедший ЧЕРЕЗ помощника, остаётся вердиктом
                # помощника: авторство у того, кто его произвёл, а якорь
                # звавшего лишь впускал к нему.
                if via is not None:
                    inner = self._inner_guard(via, scope, depth, status)
                    guard = inner if inner is not None else GUARD_OWN
                    inner_anchor = None
                else:
                    guard = GUARD_FOREIGN if anchor else GUARD_OWN
                    inner_anchor = anchor
                out.append({"status": status, "guard": guard,
                            "line": node.lineno, "via": via,
                            "anchor": inner_anchor, "expr": None})
        return out

    @staticmethod
    def _fallthrough_anchor(preceding, carried, instruments):
        """Якорь, доставшийся месту ПРОВАЛИВАНИЕМ, — и только от решающей ветки.

        Предшествующий `if`, чья ветка ОТКАЗАЛАСЬ мерить (третий исход), вердикта
        не переносит: «прибор не отказал» и «прибор сказал ОК» — два разных
        утверждения, и считать первое вторым значило бы записать собственное
        правило пробы на счёт прибора.

        ИЗМЕРЕНО, а не предположено. Первая редакция правила считала охраной любой
        предшествующий `if` и дала ЛОЖНЫМ ЧЛЕНОМ `pr_work_arrived_on_main`: его
        `satisfied` стои́т за `if blind or report["state"] == M.UNMEASURED`, то есть
        за ОТКАЗОМ прибора, а население `bad`/`blind` проба строит своим правилом
        над построчным состоянием. Признак переноса — что анкерная ветка отдаёт
        РЕШАЮЩИЙ вердикт, а не то, что в ней упомянут прибор.

        Второе условие — у ЗВАВШЕГО, и оно проверяется до зова этой функции:
        проваливание переносит вердикт лишь там, где у места НЕТ собственной
        охраны. Иначе переносящей оказалась бы и проба, которая после «прибор не
        сказал CRITICAL» применяет свой порог, — а это смешанный род, и слить его
        в перенос значило бы спрятать именно то, что заказ велел различить.
        """
        for stmt in preceding:
            if id(stmt.test) not in carried:
                continue
            got = _guard_anchor([stmt.test], instruments)
            if got:
                return got
        return None

    def _inner_guard(self, helper: str, scope: _Scope, depth: int, status: str):
        target = scope.nested.get(helper) or self.funcs.get(helper)
        if target is None or depth >= HELPER_DEPTH:
            return None
        kinds = {s["guard"] for s in self.sites_of(target, depth + 1)
                 if s["status"] == status}
        if not kinds:
            return None
        if kinds == {GUARD_FOREIGN}:
            return GUARD_FOREIGN
        if GUARD_UNREADABLE in kinds:
            return GUARD_UNREADABLE
        return GUARD_OWN

    def probe(self, probe_name: str, fn_name: str | None) -> dict:
        if not fn_name or fn_name not in self.funcs:
            return {"probe": probe_name, "function": fn_name,
                    "kind": KIND_UNMEASURED, "instruments": [], "sites": [],
                    "decisive": 0,
                    "reason": (f"функции {fn_name!r} в источнике нет — тело пробы "
                               f"не прочитано, и род её вердикта НЕ ИЗМЕРЕН")}
        fn = self.funcs[fn_name]
        scope = self.scope(fn)
        instruments = scope.instruments(self.loaders)
        sites = self.sites_of(fn)
        decisive = [s for s in sites
                    if s["status"] in ("SATISFIED", "NOT_SATISFIED")
                    or s["guard"] == GUARD_UNREADABLE]
        unreadable = [s for s in decisive if s["guard"] == GUARD_UNREADABLE]
        judged = [s for s in decisive if s["guard"] != GUARD_UNREADABLE]
        reason = None
        if unreadable:
            kind = KIND_UNMEASURED
            reason = (f"нулевой слот {len(unreadable)} возврат(ов) не разобран "
                      f"(строки {', '.join(str(s['line']) for s in unreadable[:4])}) — "
                      f"решающий путь прочитан НЕ ЦЕЛИКОМ, и назвать род значило бы "
                      f"выдать догадку за замер")
        elif not judged:
            kind = KIND_UNMEASURED
            reason = ("решающих возвратов (`satisfied`/`not_satisfied`) у пробы нет "
                      "ни одного — она не выносит вердикта о критерии вовсе")
        else:
            kinds = {s["guard"] for s in judged}
            if kinds == {GUARD_FOREIGN}:
                kind = KIND_TRANSCRIBED
            elif kinds == {GUARD_OWN}:
                kind = KIND_SELF_JUDGED
            else:
                kind = KIND_MIXED
                reason = ("часть решающих мест переносит вердикт прибора, часть "
                          "судит сама — красную строку такой пробы читатель не "
                          "может приписать ни прибору, ни пробе")
        return {"probe": probe_name, "function": fn_name, "kind": kind,
                "instruments": sorted(set(instruments.values())),
                "decisive": len(judged),
                "sites": sorted(judged, key=lambda s: (s["line"], s["status"])),
                "rejected_anchors": _rejected_anchors(scope, instruments),
                "reason": reason}


def measure(repo_root: str | None = None, *, source: str | None = None) -> dict:
    """Перепись родов вердикта по реестру проб. Только читает.

    `source` — путь к разбираемому файлу (умолчание: `SOURCE_REL` в дереве).
    """
    root = repo_root or _repo_root()
    path = pathlib.Path(source) if source else pathlib.Path(root) / SOURCE_REL
    if not path.exists():
        raise Unmeasured(f"{path} в этом дереве нет — реестр проб НЕ ПРОЧИТАН, и "
                         f"население родов не измерено (это не ноль)")
    reader = _Reader(path)
    probes = [reader.probe(name, fn) for name, fn in reader.registry.items()]
    counts = {k: 0 for k in (KIND_TRANSCRIBED, KIND_SELF_JUDGED,
                             KIND_MIXED, KIND_UNMEASURED)}
    for row in probes:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    findings = [r for r in probes if r["kind"] in (KIND_MIXED, KIND_UNMEASURED)]
    rejected = sorted({a for r in probes for a in (r.get("rejected_anchors") or [])})
    return {
        "measured": True,
        "source": str(path),
        "population": len(probes),
        "counts": counts,
        "probes": sorted(probes, key=lambda r: r["probe"]),
        "findings": findings,
        "instrumented_but_self_judged": sorted(
            r["probe"] for r in probes
            if r["kind"] == KIND_SELF_JUDGED and r["instruments"]),
        "rejected_by_vocabulary": rejected,
        "vocabulary": sorted(VERDICT_WORDS),
        "helper_depth": HELPER_DEPTH,
        "not_reported": [
            "откуда взят ЛЕВЫЙ операнд сравнения с константой вердикта",
            "существует ли названная константа у прибора на самом деле",
            "ПРАВ ли прибор, чей вердикт переносится",
            "пробу, собирающую имя своей меры в рантайме",
        ],
        "applied": False,
    }


def authorship_of(probe_name: str, repo_root: str | None = None,
                  *, report: dict | None = None) -> dict | None:
    """Род вердикта ОДНОЙ пробы — для читателя сводки §49.

    Возврат `None` означает «пробы с таким именем в реестре разбора нет», и
    читатель обязан напечатать это как НЕ ИЗМЕРЕНО, а не как «своя мера».
    """
    doc = report or measure(repo_root)
    for row in doc["probes"]:
        if row["probe"] == probe_name:
            return row
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--repo-root", default=None, help="дерево, о котором мерить")
    ap.add_argument("--source", default=None, help="разбираемый файл реестра проб")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)

    try:
        report = measure(args.repo_root, source=args.source)
    except Unmeasured as exc:
        if args.json:
            print(json.dumps({"measured": False, "reason": str(exc)},
                             ensure_ascii=False, indent=2))
        else:
            print(f"НЕ ИЗМЕРЕНО: {exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["findings"] else 0

    counts = report["counts"]
    print(f"Чья мера произвела вердикт пробы (заказ G96 п. 3) — источник "
          f"{report['source']}")
    print(f"  проб в реестре {report['population']} · ПРИБОР "
          f"{counts[KIND_TRANSCRIBED]} · САМА ПРОБА {counts[KIND_SELF_JUDGED]} · "
          f"СМЕШАННАЯ {counts[KIND_MIXED]} · НЕ ИЗМЕРЕНА {counts[KIND_UNMEASURED]}")
    for row in report["probes"]:
        where = (" ← " + ", ".join(row["instruments"])) if row["instruments"] else ""
        print(f"  [{row['kind']}] {row['probe']}{where}")
        if row["reason"]:
            print(f"      {row['reason']}")
    if report["instrumented_but_self_judged"]:
        print(f"  ⚠️  судят САМИ над отчётом ЧУЖОГО прибора "
              f"({len(report['instrumented_but_self_judged'])}): "
              f"{', '.join(report['instrumented_but_self_judged'])} — читателю такая "
              f"строка выглядит как вердикт прибора, а порог в ней свой")
    if report["rejected_by_vocabulary"]:
        print(f"  цена словаря: атрибутов прибора отвергнуто словарём "
              f"{len(report['rejected_by_vocabulary'])} "
              f"({', '.join(report['rejected_by_vocabulary'][:6])}"
              f"{'…' if len(report['rejected_by_vocabulary']) > 6 else ''})")
    print(f"  НЕ ДОКЛАДЫВАЕТ: {' · '.join(report['not_reported'])}")
    print("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
