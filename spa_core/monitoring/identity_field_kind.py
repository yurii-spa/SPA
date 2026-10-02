#!/usr/bin/env python3
"""Род поля-кандидата в ЛИЧНОСТЬ — машинным признаком, а не суждением человека.

Заказ **G91 п. 1** приказа владельца «Portfolio CIO» (поставлен ADR-503).
Дословно: «Род поля — машинным признаком, а не суждением. Сегодня „имя против
момента производства“ различает человек. Дешёвая половина проверяема уже
сейчас: поле, которое производитель копирует из своего ``generated_at`` (или из
другого имени ``CLOCK_FIELDS``), личностью быть не вправе — это утверждение о
КОДЕ производителя, а не о значении, и разбирается AST'ом. Дорогая половина
(„это замер, а не имя“) признака пока не имеет, и выдумывать его эвристикой
запрещено: сначала замер населения, потом правило.»

Чего здесь НЕТ и почему
------------------------------------------------------------------------------
Признак построен и измерен. **Правило, которое заказ к нему приставил, —
отвергнуто, и отвергнуто ЗАМЕРОМ, а не осторожностью.** Импликация «копирует
часы ⇒ личностью быть не вправе» ложна в ОБЕ стороны, и у каждой стороны есть
названный пример на живом коде (оба перемеряются батареей, а не пересказываются):

* **Признак не ловит тот самый случай, ради которого назван.**
  ``record_generated_at`` — имя, отвергнутое ADR-503 именно этим рассуждением, —
  у своего производителя (``decision_record_run_identity.py``) стенными часами
  НЕ производится: там стои́т ``record.get("generated_at")``, то есть чтение
  отметки ВХОДНОЙ записи. Производитель её не ставит, он её переписывает.
* **Признак ловит то, что личностью быть ВПРАВЕ.** ``cycle_date`` (имя из
  ``_HAND_PICKED_IDENTITY_FIELDS``), ``date`` и ``day`` (последнее дописано
  ЗАМЕРОМ, ADR-503) у своих производителей производятся стенными часами
  буквально: ``today = datetime.now(timezone.utc).strftime("%Y-%m-%d")``,
  ``day = as_of or now.date().isoformat()``. И это не дефект: у суточного ряда
  день и ЕСТЬ предмет элемента. Координата ``[day="2026-10-02"]`` переезжает не
  потому, что переименовался тот же элемент, а потому, что пришёл новый день.

Отсюда вывод, который дороже самого признака: водораздел проходит не по
«производят ли значение часы», а по тому, **чей предмет этот момент** — ряда или
записи. Этого признака у меры нет, и выдумывать его запрещено тем же заказом.
Поэтому документ несёт ``fitness_rule.verdict = "REFUSED"`` с причиной, а не
гейт, и ни один потребитель не получает отсюда права отвергнуть имя.

Три оси, и смешивать их нельзя
------------------------------------------------------------------------------
``arithmetic_derived`` (заказ **G91 п. 3**)
    Значение ПОСЧИТАНО по данным: счёт, сумма, округление, разность, доля.
    Эта ось отвечает на слово самого заказа — «первые два суть ЗАМЕРЫ», — и
    отвечает машиной: до неё «замер против имени» различал человек, а дорогая
    половина признака объявлялась ненайденной. Найдена не вся: ось ловит замер
    АРИФМЕТИЧЕСКИЙ и молчит о замере, пришедшем из чужого модуля готовым
    числом. Односторонность названа ниже и ЗАМЕРЕНА, а не оговорена.

    **Род называет не оператор, а операнд.** ``/`` бывает склейкой путей
    (``root / "data"`` — в этом дереве чаще, чем делением), ``-`` — разностью
    множеств, ``+`` — склейкой строк. Числом выражение делает операнд,
    **числовой ПО ПОСТРОЕНИЮ**: числовой литерал либо счёт/сумма/округление.
    При таком операнде второй обязан быть числом — иначе выражение не
    исполнилось бы вовсе (``"a" - 1`` есть ``TypeError``). Признак поэтому
    утверждение о коде, а не догадка по виду оператора; и он односторонний в
    сторону «чисто»: ``a - b``, где оба имени неизвестны, находкой НЕ является.

    **Литерал-число сам по себе замером НЕ является.** ``{"window_s": 300}`` —
    постоянная, а не наблюдение: координата по ней не переезжает. Ось ловит
    ВЫЧИСЛЕНИЕ, и это различие проверяется контролем в обе стороны.

    **Прочтений у оси ДВА, и они не складываются.** Сильное — значение ЕСТЬ
    посчитанное число. Слабое (``arithmetic_formatted``) — значение есть ТЕКСТ,
    собранный из посчитанного числа. Разделить их пришлось ЗАМЕРОМ, а не из
    любви к порядку: f-строка рода не называет, потому что AST не отличает
    отформатированный замер (``f"{share:.1f}%"``) от СГЕНЕРИРОВАННОГО ИМЕНИ
    (``f"protocol_{i % 12}"`` — настоящая строка ``scripts/dfb_perf_budget.py``,
    и имя там именно имя). Первая редакция держала f-строку в сильном прочтении
    и обвиняла этим ``protocol`` — имя из ``_HAND_PICKED_IDENTITY_FIELDS``.
    Слабое прочтение печатается отдельным числом ровно как
    ``clock_named_read`` у соседней оси.

``wall_clock_derived``
    Значение производится СТЕННОЙ ДВЕРЬЮ самого модуля: ``datetime.now()``,
    ``datetime.utcnow()``, ``date.today()``, ``time.time()`` — напрямую, через
    привязку или через обёртку, КОТОРАЯ ИХ ВОЗВРАЩАЕТ. Утверждение о коде
    производителя, суждения в нём нет.

``clock_named_read``
    Значение — чтение имени из :data:`CLOCK_FIELDS` у какого-то отображения
    (``rec["timestamp"]``, ``record.get("generated_at")``). Это и есть ось,
    названная заказом дословно, и она **СЛАБАЯ**: отображение бывает ВХОДОМ.
    Замер поимённо: ``spa_core/export_data.py`` кладёт в поле ``date`` значение
    ``rec["timestamp"]``, где ``rec`` — точка СИНТЕТИЧЕСКОЙ ИСТОРИИ, то есть
    календарная дата наблюдения, а не момент производства. Ровно про это
    предупреждает сам ``run_identity_key_price``: «``feed_coverage.as_of`` — это
    ВХОД, а не часы». Поэтому ось печатается отдельным числом и в сильную не
    складывается.

Три исхода, и «не измерено» не выдаётся за «чисто»
------------------------------------------------------------------------------
Файл не разобрался (синтаксис, кодировка) ⇒ :data:`UNMEASURED` с названной
причиной. У имени не нашлось НИ ОДНОГО производителя ⇒ тоже
:data:`UNMEASURED`, а не :data:`NOT_DERIVED`: «мы не нашли, кто это пишет» и «мы
проверили писателей, часов там нет» — разные ответы, и склеить их значило бы
повторить урок ``pyflakes`` (fail-OPEN тише красного).

Чего мера НЕ ДОКЛАДЫВАЕТ
------------------------------------------------------------------------------
* годен ли род в личность — см. ``fitness_rule`` выше: правила нет;
* производителя вне разобранных каталогов (имя поля не есть адрес);
* значение, пришедшее из ЧУЖОГО модуля через вызов (``build(...)``): вызов,
  чьи АРГУМЕНТЫ содержат часы, стенным не считается — иначе всякий потребитель
  часов стал бы их производителем (это ровно «контейнер не есть привязка» из
  ``.claude/rules/deployment.md``, и первая редакция этой меры на нём ошиблась:
  ``{"source": status_dict.get("source")}`` объявлялось стенным лишь потому, что
  ``check_sky_status_live()`` где-то внутри трогает часы);
* область видимости за пределами модуля (``global``/``nonlocal`` не прослежены);
* **замыкание над привязкой ОБЪЕМЛЮЩЕЙ функции.** Вложенная область наследует
  привязки МОДУЛЬНОЙ, а не внешней функции, поэтому часы, связанные в объемлющей
  функции и прочитанные во вложенной, мера НЕ увидит. Односторонность названа
  вслух: этот промах — в сторону «чисто», то есть противоположен выбору в случае
  неоднозначности порядка привязок, и оба выбора сделаны по одной причине —
  ось не есть гейт, поэтому цена промаха есть недостающая строка отчёта, а не
  отвергнутое имя. Замер населения этого класса в задел: заказ G113 п. 3;
* ПОРЯДОК двух привязок одного имени ВНУТРИ одной области: за потоком
  управления мера не следит. Выбранная сторона — находка, и выбор обоснован тем,
  что ось не есть гейт: ложная находка стои́т строки в отчёте, а ложное «чисто»
  спрятало бы настоящие часы. Цена замерена — ни одна из находок по
  ``_IDENTITY_FIELDS`` на этой неоднозначности не стои́т: из **52** находок по
  этим именам ни у одной привязки нет КОНКУРИРУЮЩЕГО нечасового связывания того
  же имени в той же области (замер, не рассуждение). МЕЖДУ областями
  неоднозначности нет: имя, связанное в другой функции, переменную обхода не
  отравляет (и это закреплено в обе стороны).

Только stdlib. LLM здесь запрещён — это измерение, не суждение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.run_identity_key_price import (  # noqa: E402
    CLOCK_FIELDS, _IDENTITY_FIELDS,
)

SCHEMA = "identity_field_kind.v1"

#: Вердикты рода. Четыре, и четвёртый — самостоятельный исход (инв. #17).
WALL_CLOCK = "wall_clock_derived"
CLOCK_NAMED_READ = "clock_named_read"
NOT_DERIVED = "not_derived"
UNMEASURED = "unmeasured"

#: Вердикты ТРЕТЬЕЙ оси (заказ **G91 п. 3**). Своя тройка, а не члены прежней:
#: «часов нет» и «арифметики нет» — разные ответы, и сложить их в один
#: ``not_derived`` значило бы потерять ровно ту половину признака, которую заказ
#: назвал дорогой.
ARITH_DERIVED = "arithmetic_derived"
#: СЛАБОЕ прочтение той же оси: текст, собранный из посчитанного числа. Отдельным
#: вердиктом, а не членом сильного: f-строка рода не называет (см. справку).
ARITH_FORMATTED = "arithmetic_formatted"
NOT_ARITH = "not_arithmetic"

#: Вызовы, чьё значение есть ЧИСЛО, посчитанное ПО ДАННЫМ. Названы поимённо по
#: той же причине, что `_DOOR_ATTRS`: по «числовому виду» признак утащил бы и
#: конвертеры входа (`int("3")` переводит ДАННОЕ значение и ничего не считает).
#: ``max``/``min`` здесь НЕТ намеренно: они ВЫБИРАЮТ один из поданных элементов,
#: а не вычисляют новый, и выбранным вполне может оказаться имя.
_ARITH_CALLS = frozenset({"sum", "len", "round", "abs", "mean", "median",
                          "fmean", "stdev", "variance"})

#: Узлы, у которых значение происходит от детей НА ЭТОЙ оси. Короче, чем
#: `_TRANSPARENT`: ``Attribute`` здесь нет (``obj.name`` числом от числового
#: ``obj`` не становится), ``Subscript`` нет (ключ отображения своим значением
#: арифметики не делает), ``Await`` нет. ``JoinedStr``/``FormattedValue`` ЕСТЬ:
#: текст, собранный из посчитанного числа (``f"{share:.1f}%"``), переезжает
#: вместе с числом, и координата по нему ездила бы так же.
_ARITH_TRANSPARENT = (ast.IfExp, ast.BoolOp, ast.UnaryOp, ast.NamedExpr)

#: Вызовы, превращающие число в ТЕКСТ. Отсюда начинается СЛАБОЕ прочтение оси.
_TEXT_FORMATTERS = frozenset({"str", "format", "repr"})

#: Вызовы, у которых число ОСТАЁТСЯ числом. Своя тройка рядом с `_FORMATTERS`
#: соседней оси, и это не дублирование: для часов `str(now)` — «те же часы в
#: другом виде», а для счёта `str(n)` — уже ТЕКСТ, и место ему в слабом
#: прочтении. Держать один список на обе оси значило бы, что `str(len(xs))`
#: сильное, а `f"{len(xs)}"` слабое — одна и та же мысль в двух вердиктах.
#: Нашла расхождение МУТАЦИЯ, а не чтение глазами.
_NUM_FORMATTERS = frozenset({"int", "float", "round", "abs"})

#: Контейнерные литералы и выражения-генераторы: спуск в них ЗАПРЕЩЁН на обеих
#: осях. Словарь, в котором лежит посчитанное число, сам числом не является —
#: иначе всякое поле-документ объявлялось бы замером («контейнер не есть
#: привязка», `.claude/rules/deployment.md`).
_CONTAINERS = (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.ListComp,
               ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.Lambda)

#: Имена методов, которые СПРАШИВАЮТ у операционной системы время. Названы
#: поимённо по той же причине, по которой поимённо названы `CLOCK_FIELDS`:
#: регулярка по «датному виду» утащила бы и конвертеры входа (`fromisoformat`,
#: `fromtimestamp` — они переводят ДАННОЕ им значение и часов не спрашивают).
_DOOR_ATTRS = frozenset({"now", "utcnow", "today", "time", "time_ns", "monotonic",
                         "perf_counter"})

#: Корни, на которых эти методы и есть стенные часы. Без корня `x.now()` мог бы
#: оказаться чем угодно — например методом доменного объекта.
_DOOR_ROOTS = frozenset({"datetime", "dt", "date", "time", "_dt", "_time",
                         "_datetime"})

#: Вызовы, ФОРМАТИРУЮЩИЕ уже полученное значение. Переданное им производное от
#: часов остаётся производным от часов: `str(now)` — те же часы в другом виде.
_FORMATTERS = frozenset({"str", "int", "float", "round", "format", "repr"})

#: Узлы, у которых ЗНАЧЕНИЕ происходит от детей. Контейнерных литералов здесь
#: НЕТ намеренно: словарь, в котором лежит отметка, сам отметкой не является —
#: иначе каждое поле-документ объявлялось бы стенным.
#: ``FormattedValue`` стои́т здесь НЕ для красоты: без него f-строка,
#: собранная из часов (``f"{age_hours:.1f}h old"``), оставалась невидимой —
#: спуск доходил до ``JoinedStr`` и упирался в её обёртку. Текст, собранный из
#: часов, переезжает каждый прогон ровно так же, как само число.
_TRANSPARENT = (ast.Attribute, ast.BinOp, ast.IfExp, ast.BoolOp, ast.UnaryOp,
                ast.JoinedStr, ast.FormattedValue, ast.Await, ast.NamedExpr)


@dataclass(frozen=True)
class Evidence:
    """Одно место, где ИМЕНОВАННОЕ поле получает значение, и чем оно оказалось.

    ``arith`` — ТРЕТЬЯ ось отдельным полем, а не ещё одно значение ``verdict``.
    Это не оформление: поле, посчитанное арифметикой, и поле, скопированное с
    часов, — разные утверждения о коде, и они бывают верны ОБА сразу
    (``{"age_h": (now - then).total_seconds() / 3600}``). Склеить их в одну
    строку вердикта значило бы сделать вторую находку невидимой ровно там, где
    она дороже всего.
    """
    module: str
    line: int
    verdict: str
    how: str
    arith: str = ""
    arith_text: str = ""

    def __str__(self) -> str:                                # pragma: no cover
        tail = (f" +{ARITH_DERIVED}({self.arith})" if self.arith
                else f" +{ARITH_FORMATTED}({self.arith_text})" if self.arith_text
                else "")
        return f"{self.module}:{self.line} {self.verdict} ({self.how}){tail}"


# ── стенные двери ────────────────────────────────────────────────────────────

def door_call(node: ast.AST) -> Optional[str]:
    """Это ВЫЗОВ стенных часов? Возвращает его запись или ``None``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _DOOR_ATTRS:
        return None
    root: ast.AST = func.value
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name) and root.id in _DOOR_ROOTS:
        return f"{root.id}.{func.attr}()"
    return None


def _returns(func: ast.AST) -> List[ast.AST]:
    """Выражения, КОТОРЫЕ функция возвращает — без спуска во вложенные функции."""
    out: List[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            out.append(node.value)
        stack.extend(ast.iter_child_nodes(node))
    if isinstance(func, ast.Lambda):
        out.append(func.body)
    return out


def _wrappers(tree: ast.Module, derive) -> FrozenSet[str]:
    """Функции модуля, КОТОРЫЕ ОТДАЮТ значение искомого рода — до неподвижной точки.

    Одна копия правила на обе оси. Вторая его копия означала бы, что «обёртка
    часов» и «обёртка счёта» ищутся по разным правилам, а расходятся такие
    копии молча — это и есть урок ADR-502 (``scalar_refusal``: одно правило,
    один дом).

    Признак — РЕЗУЛЬТАТ, а не «в теле где-то есть». Это различие и есть вся
    цена первой редакции меры: ``check_sky_status_live()`` трогает часы внутри,
    а отдаёт словарь состояния, и по «содержит» её результат объявлялся
    стенным — вместе с полем ``source``, которое к часам не имеет отношения.
    """
    funcs: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)
    wrappers: Set[str] = set()
    for _ in range(len(funcs) + 1):
        grew = False
        for name, node in funcs.items():
            if name in wrappers:
                continue
            scope = _Scope(frozenset(), frozenset(wrappers))
            if any(derive(expr, scope) for expr in _returns(node)):
                wrappers.add(name)
                grew = True
        if not grew:
            break
    return frozenset(wrappers)


def clock_wrappers(tree: ast.Module) -> FrozenSet[str]:
    """Функции модуля, КОТОРЫЕ ОТДАЮТ стенное время (``_utcnow`` и родня)."""
    return _wrappers(tree, derivation)


def arith_wrappers(tree: ast.Module) -> FrozenSet[str]:
    """Функции модуля, КОТОРЫЕ ОТДАЮТ посчитанное число (``_share_pct`` и родня)."""
    return _wrappers(tree, arith_derivation)


# ── происхождение значения ───────────────────────────────────────────────────

def value_children(node: ast.AST) -> List[ast.AST]:
    """Дети, чьё значение МОЖЕТ стать значением узла. Одна копия на обе оси.

    Нужна из-за ``IfExp``: у ``a if test else b`` значение приходит из ветвей и
    НИКОГДА из условия. Обе оси спускались во ВСЕХ детей, и это давало ложную
    находку на живом коде — ``stability_tracker.py:202``, где
    ``message = f"…" + (f"…" if n_fails else "")``: склейка СТРОК объявлялась
    посчитанным числом, потому что числом оказалось ``n_fails`` в УСЛОВИИ.
    Условие управляет выбором, но значением не становится; считать иначе
    значило бы обвинять всякое выражение, в чьей развилке стои́т счётчик.

    Остальные узлы прозрачны всеми детьми по праву: у ``or``/``and`` значением
    становится один из операндов, у унарного оператора — его операнд, у ``:=`` —
    присваиваемое значение.
    """
    if isinstance(node, ast.IfExp):
        return [node.body, node.orelse]
    return list(ast.iter_child_nodes(node))


@dataclass(frozen=True)
class _Scope:
    """Что в ЭТОЙ области видимости происходит от часов, и какие обёртки известны."""
    derived: FrozenSet[str]
    wrappers: FrozenSet[str]


def derivation(node: Optional[ast.AST], scope: _Scope, depth: int = 0) -> Optional[str]:
    """ПРОИСХОДИТ ли значение выражения от стенных часов — и как.

    Прозрачны только те узлы, у которых значение ЕСТЬ значение ребёнка. Вызов
    прозрачен лишь двумя способами: часы его ПОЛУЧАТЕЛЬ (``now.isoformat()``)
    либо он форматирует переданное (``str(now)``). Вызов, которому часы ушли
    АРГУМЕНТОМ (``read_observation(data_dir, now=now)``), стенным не является:
    он их потребитель, и считать иначе значило бы объявить стенным всякий
    результат, к которому часы когда-либо прикасались.
    """
    if node is None or depth > 16:
        return None
    direct = door_call(node)
    if direct:
        return direct
    if isinstance(node, ast.Name):
        return f"name:{node.id}" if node.id in scope.derived else None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in scope.wrappers and func.id not in scope.derived:
                return f"{func.id}()"
            if func.id in _FORMATTERS and node.args:
                return derivation(node.args[0], scope, depth + 1)
            return None
        if isinstance(func, ast.Attribute):
            # метод НА часах: NOW.isoformat(), now.strftime("%Y-%m-%d")
            got = derivation(func.value, scope, depth + 1)
            if got:
                return got
            if func.attr in scope.wrappers:
                return f"{func.attr}()"
        return None
    if isinstance(node, ast.Subscript):
        # Индексация часов (`now[0]`) мыслима, индексация СЛОВАРЯ — нет: ключ
        # отображения своим значением часы не делает. Спускаемся только в
        # получателя, и только если он сам производное.
        return derivation(node.value, scope, depth + 1)
    if isinstance(node, _TRANSPARENT):
        for child in value_children(node):
            if isinstance(child, _CONTAINERS):
                continue
            got = derivation(child, scope, depth + 1)
            if got:
                return got
    return None


# ── посчитанное число (третья ось, заказ G91 п. 3) ───────────────────────────

def arith_door(node: ast.AST) -> Optional[str]:
    """Это ВЫЗОВ, считающий число по данным? Возвращает его запись или ``None``.

    Имя берётся и у простого вызова (``sum(xs)``), и у метода
    (``statistics.mean(xs)``, ``rows.count(x)``) — чей это модуль, признак не
    спрашивает: вопрос в том, ЧТО вызов отдаёт, а не кому он принадлежит.
    Вызов без аргументов счётом не является (``round()`` не существует).
    """
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    name = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    return f"{name}()" if name in _ARITH_CALLS else None


def _numeric_operand(node: ast.AST, scope: "_Scope", depth: int) -> Optional[str]:
    """Операнд, числовой ПО ПОСТРОЕНИЮ — литерал-число либо посчитанное число.

    ``bool`` исключён типом, а не вычитанием из списка: ``True`` есть ``int`` по
    наследству, и ``isinstance`` пропустил бы флаг в арифметику. Поэтому тип
    спрашивается точным совпадением.
    """
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return f"literal:{node.value!r}"
    return arith_derivation(node, scope, depth)


def arith_derivation(node: Optional[ast.AST], scope: "_Scope",
                     depth: int = 0) -> Optional[str]:
    """ПОСЧИТАНО ли значение выражения по данным — и чем.

    Литерал-число, стоящий ОДИН, находкой не является: постоянная не переезжает.
    Находкой его делает только соседство с оператором, то есть ВЫЧИСЛЕНИЕ.
    """
    if node is None or depth > 16:
        return None
    direct = arith_door(node)
    if direct:
        return direct
    if isinstance(node, ast.Name):
        return f"name:{node.id}" if node.id in scope.derived else None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in scope.wrappers and func.id not in scope.derived:
                return f"{func.id}()"
            if func.id in _NUM_FORMATTERS and node.args:
                return arith_derivation(node.args[0], scope, depth + 1)
        elif isinstance(func, ast.Attribute) and func.attr in scope.wrappers:
            return f"{func.attr}()"
        return None
    if isinstance(node, ast.BinOp):
        # Род называет ОПЕРАНД, а не оператор: `/` в этом дереве чаще склейка
        # путей, чем деление. Числовой по построению операнд обязывает второй
        # быть числом — иначе выражение не исполнилось бы вовсе.
        for side in (node.left, node.right):
            if isinstance(side, _CONTAINERS):
                continue
            got = _numeric_operand(side, scope, depth + 1)  # IfExp внутри —
            # по тому же правилу `value_children`: условие значением не станет
            if got:
                return got
        return None
    if isinstance(node, _ARITH_TRANSPARENT):
        for child in value_children(node):
            if isinstance(child, _CONTAINERS):
                continue
            got = arith_derivation(child, scope, depth + 1)
            if got:
                return got
    return None


def arith_formatted(node: Optional[ast.AST], scope: "_Scope",
                    depth: int = 0) -> Optional[str]:
    """ТЕКСТ, собранный из посчитанного числа — СЛАБОЕ прочтение оси.

    Почему отдельно, а не членом сильного прочтения: AST не отличает
    отформатированный замер от сгенерированного имени, и это измерено на живом
    коде поимённо (``f"protocol_{i % 12}"`` против ``f"{pct:.1f}%"``). Держать
    их в одном вердикте значило бы обвинять имя за то, что в нём есть номер.

    У f-строки спрашиваются её ПОДСТАНОВКИ (``FormattedValue.value``), а не всё
    поддерево: обход всем деревом утащил бы и числа из вложенного словаря, а
    контейнер привязкой не является.
    """
    if node is None or depth > 16:
        return None
    if isinstance(node, ast.JoinedStr):
        for piece in node.values:
            if isinstance(piece, ast.FormattedValue):
                got = arith_derivation(piece.value, scope)
                if got:
                    return f"f-string({got})"
        return None
    if isinstance(node, ast.FormattedValue):
        got = arith_derivation(node.value, scope)
        return f"f-string({got})" if got else None
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _TEXT_FORMATTERS and node.args):
        got = arith_derivation(node.args[0], scope)
        if got:
            return f"{node.func.id}({got})"
        # Спуск продолжается СЛАБЫМ прочтением, а не кончается здесь. Дыру
        # нашёл собственный прогон: `str(row.get("trade_id") or f"#{len(moves)+1}")`
        # (`book_oscillation_census.py:229`) — текст, собранный из счёта, —
        # обеими прочтениями молчал, потому что между `str()` и f-строкой стои́т
        # развилка `or`, а сильное прочтение в f-строку не ходит по построению.
        inner = arith_formatted(node.args[0], scope, depth + 1)
        return f"{node.func.id}({inner})" if inner else None
    if isinstance(node, (ast.BinOp, ast.IfExp, ast.BoolOp, ast.NamedExpr)):
        for child in value_children(node):
            if isinstance(child, _CONTAINERS):
                continue
            got = arith_formatted(child, scope, depth + 1)
            if got:
                return got
    return None


def _targets(node: ast.AST) -> Set[str]:
    """Имена, которые узел СВЯЗЫВАЕТ (и тем самым затеняет внешнее значение)."""
    out: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            out.add(sub.id)
    return out


def _shadowed(scope_node: ast.AST) -> Set[str]:
    """Имена, связанные В ЭТОЙ области НЕ присваиванием: параметры, циклы, with.

    Область видимости — не украшение замера, а его правильность. Первая
    редакция держала одно множество привязок на модуль, и имя ``p``, связанное
    в одной функции результатом обёртки, объявляло стенным ``{"protocol": p}``
    в ДРУГОЙ функции, где ``p`` — переменная обхода ``for p in sorted(...)``.
    Находка была ложной целиком, и ложной в опасную сторону: обвинялось имя из
    ``_HAND_PICKED_IDENTITY_FIELDS``.
    """
    out: Set[str] = set()
    args = getattr(scope_node, "args", None)
    if isinstance(args, ast.arguments):
        for group in (args.posonlyargs, args.args, args.kwonlyargs):
            out.update(a.arg for a in group)
        for extra in (args.vararg, args.kwarg):
            if extra is not None:
                out.add(extra.arg)
    for node in _own_body(scope_node):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            out |= _targets(node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    out |= _targets(item.optional_vars)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, comprehension_types()):
            for gen in node.generators:
                out |= _targets(gen.target)
    return out


def comprehension_types() -> Tuple[type, ...]:
    return (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _own_body(scope_node: ast.AST) -> Iterable[ast.AST]:
    """Узлы области БЕЗ спуска во вложенные функции — у тех своя область."""
    stack = list(ast.iter_child_nodes(scope_node))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                             ast.ClassDef)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def scope_derived(scope_node: ast.AST, outer: _Scope, derive=None) -> _Scope:
    """Привязки ЭТОЙ области: внешние минус затенённые плюс свои, до неподвижной точки.

    ``derive`` — та же область видимости, но для другой оси. Параметр, а не
    вторая копия функции: правило «параметр затеняет внешнюю привязку» должно
    быть одно на обе оси, иначе ложная находка, закрытая на одной оси, вернётся
    на другой (это и была первая ложная находка меры — имя ``p`` из одной
    функции, обвинявшее ``{"protocol": p}`` в другой).
    """
    derive = derivation if derive is None else derive
    shadow = _shadowed(scope_node)
    derived: Set[str] = set(outer.derived) - shadow
    body = list(_own_body(scope_node))
    for _ in range(8):
        grew = False
        probe = _Scope(frozenset(derived), outer.wrappers)
        for node in body:
            value = getattr(node, "value", None)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and value is not None:
                if derive(value, probe) is None:
                    continue
                names = _targets(node.target) if hasattr(node, "target") else set()
                for target in getattr(node, "targets", []):
                    names |= _targets(target)
                for name in names:
                    if name not in derived:
                        derived.add(name)
                        grew = True
        if not grew:
            break
    return _Scope(frozenset(derived), outer.wrappers)


# ── чтение имени из CLOCK_FIELDS (слабая ось) ────────────────────────────────

def clock_named_read(node: Optional[ast.AST]) -> Optional[str]:
    """Значение — ЧТЕНИЕ имени из ``CLOCK_FIELDS`` у отображения?

    Ось, названная заказом дословно. Слабая по построению: отображение бывает
    ВХОДОМ, и один такой случай измерен поимённо (см. модульную справку).
    """
    if node is None:
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "get" and node.args:
            key = node.args[0]
            if isinstance(key, ast.Constant) and key.value in CLOCK_FIELDS:
                return f'.get("{key.value}")'
        inner = clock_named_read(node.func.value)
        if inner:
            return inner
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        if node.slice.value in CLOCK_FIELDS:
            return f'["{node.slice.value}"]'
    if isinstance(node, (ast.Attribute,)):
        return clock_named_read(node.value)
    return None


# ── места, где поле получает значение ────────────────────────────────────────

def field_assignments(tree: ast.Module) -> List[Tuple[str, ast.AST, int, ast.AST]]:
    """``(имя поля, выражение, строка, область)`` для каждого НАЗВАННОГО поля.

    Три формы, все три — настоящие формы производителя: литерал словаря,
    ``doc["имя"] = …`` и ``doc.setdefault("имя", …)``. Ключ — только строковый
    литерал: вычисленный ключ именем поля не является по построению.
    """
    out: List[Tuple[str, ast.AST, int, ast.AST]] = []
    for scope_node in _scopes(tree):
        for node in _own_body(scope_node):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        out.append((key.value, value, getattr(key, "lineno", 0),
                                    scope_node))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.slice, ast.Constant)
                            and isinstance(target.slice.value, str)):
                        out.append((target.slice.value, node.value, node.lineno,
                                    scope_node))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "setdefault" and len(node.args) == 2
                  and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)):
                out.append((node.args[0].value, node.args[1], node.lineno,
                            scope_node))
    return out


def _scopes(tree: ast.Module) -> List[ast.AST]:
    """Все области видимости модуля — модуль первым, функции за ним."""
    out: List[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            out.append(node)
    return out


def module_kinds(source: str,
                 wanted: Optional[Set[str]] = None
                 ) -> Tuple[Dict[str, List[Evidence]], str]:
    """Род КАЖДОГО названного поля модуля. Вторым — причина, если не измерено.

    Исход :data:`NOT_DERIVED` возвращается НАРАВНЕ с остальными, и это не
    расточительность. Первая редакция его отбрасывала, и перепись читала
    отсутствие строк как «производителя не нашли»: одиннадцать имён из
    ``_IDENTITY_FIELDS`` — ``code``, ``id``, ``key``, ``protocol``… — получали
    ``unmeasured`` при том, что каждое измерено и чисто. «Не измерено»,
    выданное за «не найдено», — та же подмена, только в другую сторону
    (инв. #17), и поймал её собственный прогон на живом дереве.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return {}, f"не разобрано: {type(exc).__name__}"
    scopes = _scope_table(tree, derivation, clock_wrappers(tree))
    arith_scopes = _scope_table(tree, arith_derivation, arith_wrappers(tree))
    out: Dict[str, List[Evidence]] = {}
    for name, value, line, scope_node in field_assignments(tree):
        if wanted is not None and name not in wanted:
            continue
        scope = scopes.get(id(scope_node), scopes[id(tree)])
        how = derivation(value, scope)
        if how:
            verdict = WALL_CLOCK
        else:
            how = clock_named_read(value)
            verdict = CLOCK_NAMED_READ if how else NOT_DERIVED
        arith_scope = arith_scopes.get(id(scope_node), arith_scopes[id(tree)])
        arith = arith_derivation(value, arith_scope)
        # Слабое прочтение спрашивается ТОЛЬКО когда сильное молчит: текст,
        # собранный из числа, которое и само уже находка, второй находкой не
        # является — иначе одно место кода считалось бы дважды.
        text = "" if arith else (arith_formatted(value, arith_scope) or "")
        out.setdefault(name, []).append(
            Evidence("", line, verdict, how or "", arith or "", text))
    return out, ""


def _scope_table(tree: ast.Module, derive, wrappers: FrozenSet[str]
                 ) -> Dict[int, _Scope]:
    """Привязки каждой области модуля для ОДНОЙ оси. Две оси — две таблицы.

    Общей таблицы быть не может: имя, производное от часов, и имя, производное
    от счёта, — разные множества, и слить их значило бы объявить стенным всё,
    что посчитано, и посчитанным всё, что стенное.
    """
    table: Dict[int, _Scope] = {}
    root = scope_derived(tree, _Scope(frozenset(), wrappers), derive)
    table[id(tree)] = root
    for scope_node in _scopes(tree):
        if id(scope_node) not in table:
            table[id(scope_node)] = scope_derived(scope_node, root, derive)
    return table


# ── перепись по дереву ───────────────────────────────────────────────────────

#: Каталоги, у которых спрашивается род. Тесты исключены НАМЕРЕННО: фикстура
#: пишет часы в поля сознательно, и считать её производителем значило бы мерить
#: не население кода, а население сцен.
DEFAULT_ROOTS = ("spa_core", "scripts")


def census(names: Sequence[str], tree_root: Path,
           roots: Sequence[str] = DEFAULT_ROOTS) -> dict:
    """Род каждого имени из ``names`` — по ВСЕМ найденным производителям."""
    per_name: Dict[str, List[Evidence]] = {n: [] for n in names}
    unmeasured_files: Dict[str, str] = {}
    files_parsed = 0
    wanted = set(names)
    for root in roots:
        base = Path(tree_root) / root
        if not base.is_dir():
            unmeasured_files[root] = "каталога нет в дереве"
            continue
        for path in sorted(base.rglob("*.py")):
            rel = str(path.relative_to(tree_root))
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                unmeasured_files[rel] = f"не прочитано: {type(exc).__name__}"
                continue
            kinds, why = module_kinds(source, wanted)
            if why:
                unmeasured_files[rel] = why
                continue
            files_parsed += 1
            for name, rows in kinds.items():
                if name not in wanted:
                    continue
                # Пересборка с АДРЕСОМ файла. Перечислять поля по одному здесь
                # нельзя: первая редакция третьей оси так и потеряла её —
                # `arith` в этот конструктор не попал, и КАЖДАЯ находка оси
                # приезжала в свод как `not_arithmetic`, то есть «измерено и
                # ноль». Молчаливый ноль вместо находки — ровно инв. #17, и
                # поймал его собственный прогон по живому дереву, а не разбор
                # глазами. Поэтому адрес ДОПИСЫВАЕТСЯ к готовой улике
                # (`replace`), и новое поле оси физически не может отвалиться.
                per_name[name].extend(
                    dataclasses.replace(r, module=rel) for r in rows)
    fields: Dict[str, dict] = {}
    for name in names:
        rows = per_name[name]
        wall = [r for r in rows if r.verdict == WALL_CLOCK]
        read = [r for r in rows if r.verdict == CLOCK_NAMED_READ]
        clean = [r for r in rows if r.verdict == NOT_DERIVED]
        counted = [r for r in rows if r.arith]
        formatted = [r for r in rows if r.arith_text]
        if not files_parsed:
            arith_verdict, arith_why = UNMEASURED, "ни один файл дерева не разобран"
        elif not rows:
            arith_verdict, arith_why = UNMEASURED, "производитель поля не найден в дереве"
        elif counted:
            arith_verdict, arith_why = ARITH_DERIVED, ""
        elif formatted:
            arith_verdict, arith_why = ARITH_FORMATTED, ""
        else:
            arith_verdict, arith_why = NOT_ARITH, ""
        if not files_parsed:
            verdict, why = UNMEASURED, "ни один файл дерева не разобран"
        elif not rows:
            # Производителя не нашли. Это НЕ «часов нет»: мы не знаем, кто
            # пишет это поле. Склеить два ответа значило бы выдать «не
            # измерено» за «чисто» (урок pyflakes, инв. #17).
            verdict, why = UNMEASURED, "производитель поля не найден в дереве"
        elif wall:
            verdict, why = WALL_CLOCK, ""
        elif read:
            verdict, why = CLOCK_NAMED_READ, ""
        else:
            verdict, why = NOT_DERIVED, ""
        fields[name] = {
            "verdict": verdict,
            "why_unmeasured": why,
            "wall_clock_sites": [str(r) for r in wall[:8]],
            "clock_named_read_sites": [str(r) for r in read[:8]],
            "wall_clock_count": len(wall),
            "clock_named_read_count": len(read),
            "not_derived_count": len(clean),
            # Третья ось — ОТДЕЛЬНЫМ вердиктом рядом, а не членом прежнего.
            # «Часов нет» и «арифметики нет» суть разные ответы о коде, и
            # у каждого свой третий исход (инв. #17).
            "arithmetic_verdict": arith_verdict,
            "why_arithmetic_unmeasured": arith_why,
            "arithmetic_sites": [f"{r.module}:{r.line} {r.arith}"
                                 for r in counted[:8]],
            "arithmetic_count": len(counted),
            "arithmetic_formatted_sites": [f"{r.module}:{r.line} {r.arith_text}"
                                           for r in formatted[:8]],
            "arithmetic_formatted_count": len(formatted),
        }
    return {
        "schema": SCHEMA,
        "files_parsed": files_parsed,
        "files_unmeasured": unmeasured_files,
        "fields": fields,
        "fitness_rule": FITNESS_RULE,
    }


#: Правило «род ⇒ годность» — ОТВЕРГНУТО, и отвергнуто замером. Лежит в
#: документе, а не только в ADR, чтобы ни один потребитель не смог взять ось за
#: гейт, не прочитав причину. Контрпримеры ПЕРЕМЕРЯЮТСЯ батареей: исчезни они из
#: кода — тест краснеет и отказ пересматривается, а не ветшает молча.
FITNESS_RULE = {
    "verdict": "REFUSED",
    "why": ("импликация «производится стенными часами ⇒ личностью быть не вправе» "
            "ложна в обе стороны; водораздел проходит по тому, ЧЕЙ предмет этот "
            "момент — ряда или записи, а такого признака у меры нет"),
    "counterexamples": [
        {"field": "record_generated_at",
         "producer": "spa_core/monitoring/decision_record_run_identity.py",
         "claim": "отвергнут ADR-503 этим рассуждением, но стенными часами "
                  "производителя НЕ производится — переписывает отметку ВХОДА",
         "expect_verdict": CLOCK_NAMED_READ},
        {"field": "day",
         "producer": "spa_core/strategy_lab/swarm/dwell_hysteresis_forward.py",
         "claim": "производится стенными часами и при этом ПРИНЯТ в "
                  "_MEASURED_IDENTITY_FIELDS замером ADR-503: у суточного ряда "
                  "день и есть предмет элемента",
         "expect_verdict": WALL_CLOCK},
    ],
}


#: Правило «посчитано ⇒ личностью быть не вправе» — предмет заказа **G91 п. 3**,
#: который назвал два имени четвёрки «ЗАМЕРАМИ». Слово заказа теперь измеримо
#: машиной; САМО ПРАВИЛО при этом отвергнуто, и вердикт его не объявлен строкой,
#: а ВЫЧИСЛЯЕТСЯ из двух условий (:func:`measure_rule`): исчезни условие — отказ
#: пересматривается решением, а не ветшает молча.
MEASURE_RULE_COUNTEREXAMPLES = (
    {"field": "day",
     "producer": "spa_core/backtesting/replay.py",
     "claim": "посчитан арифметикой (`best_idx + 1`) и личностью быть ВПРАВЕ: "
              "вычисленный ПОРЯДКОВЫЙ НОМЕР именно и называет, который это "
              "элемент ряда",
     "admitted": True},
    {"field": "code",
     "producer": "scripts/check_undelivered_work.py",
     "claim": "у ЭТОГО производителя держит `len(b[\"code\"])` — СЧЁТ, а у "
              "прочих то же имя держит имя. Род есть свойство МЕСТА, а "
              "`_IDENTITY_FIELDS` есть множество ИМЁН: granularity не та, и "
              "правило по имени неисполнимо в принципе",
     "admitted": True},
)

#: Имена, которые заказ G91 п. 3 назвал ЗАМЕРАМИ. Ось обязана поймать хотя бы
#: одно — иначе она не делает работы, ради которой названа.
MEASURE_RULE_SUBJECTS = ("realised_usd_per_day", "best_net_usd")


def measure_rule(doc: dict) -> dict:
    """Вердикт правила «посчитано ⇒ не личность» — ВЫЧИСЛЕН из замера.

    Два условия, и оба читаются из того же документа, что и находки:

    1. **ось делает работу** — хотя бы одно имя, названное заказом замером,
       поймано СИЛЬНЫМ прочтением;
    2. **ось щадит принятое** — ни одно имя из ``_IDENTITY_FIELDS`` сильным
       прочтением не поймано.

    Правило принимается только при обоих. Имя, которого в документе нет вовсе,
    условием не считается ни за, ни против: ``UNMEASURED`` — третий исход, а не
    голос (инв. #17).
    """
    fields = doc.get("fields") or {}

    def strong(name: str) -> Optional[bool]:
        row = fields.get(name)
        if row is None or row.get("arithmetic_verdict") == UNMEASURED:
            return None
        return row.get("arithmetic_verdict") == ARITH_DERIVED

    caught = [n for n in MEASURE_RULE_SUBJECTS if strong(n) is True]
    missed = [n for n in MEASURE_RULE_SUBJECTS if strong(n) is False]
    subj_unmeasured = [n for n in MEASURE_RULE_SUBJECTS if strong(n) is None]
    admitted_caught = [n for n in _IDENTITY_FIELDS if strong(n) is True]
    admitted_unmeasured = [n for n in _IDENTITY_FIELDS if strong(n) is None]
    asked = [n for n in MEASURE_RULE_SUBJECTS + tuple(_IDENTITY_FIELDS)
             if n in fields]
    if not asked:
        return {"verdict": UNMEASURED,
                "why": "ни одно имя предмета не спрошено у этого документа",
                "axis_does_work": None, "axis_spares_admitted": None}
    does_work = bool(caught)
    spares = not admitted_caught
    verdict = "ACCEPTED" if (does_work and spares) else "REFUSED"
    why = []
    if not does_work:
        why.append("сильное прочтение не поймало ни одного имени, названного "
                   "заказом замером ⇒ ось не делает работы")
    if admitted_caught:
        why.append("сильным прочтением поймано УЖЕ ПРИНЯТОЕ имя: "
                   + ", ".join(admitted_caught)
                   + " ⇒ импликация ложна в ту сторону, которая и была нужна")
    return {
        "verdict": verdict,
        "why": "; ".join(why),
        "axis_does_work": does_work,
        "axis_spares_admitted": spares,
        "subjects_caught": caught,
        "subjects_missed_by_the_axis": missed,
        "subjects_unmeasured": subj_unmeasured,
        "admitted_names_caught": admitted_caught,
        "admitted_names_unmeasured": admitted_unmeasured,
        "counterexamples": list(MEASURE_RULE_COUNTEREXAMPLES),
        "one_sidedness": (
            "ось ловит замер АРИФМЕТИЧЕСКИЙ и молчит о числе, пришедшем "
            "готовым из чужого модуля (`(enum[...] or {}).get(\"net_usd\")`); "
            "промах в сторону «чисто» и назван, а не оговорён"),
    }


def report(doc: dict, *, max_rows: int = 40) -> str:
    lines = [f"род поля-кандидата в личность (заказ G91 п. 1), схема {doc['schema']}",
             f"  файлов разобрано: {doc['files_parsed']} · "
             f"не измерено файлов: {len(doc['files_unmeasured'])}"]
    fields = doc["fields"]
    tally: Dict[str, int] = {}
    for row in fields.values():
        tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1
    lines.append("  вердикты имён: " + " · ".join(
        f"{k} {v}" for k, v in sorted(tally.items())))
    for name in list(fields)[:max_rows]:
        row = fields[name]
        mark = {WALL_CLOCK: "⏰", CLOCK_NAMED_READ: "≈", NOT_DERIVED: "·",
                UNMEASURED: "?"}[row["verdict"]]
        extra = row["why_unmeasured"] or (
            row["wall_clock_sites"] or row["clock_named_read_sites"] or [""])[0]
        lines.append(f"  {mark} {name}: {row['verdict']} — {extra}")
    counted = sum(1 for r in fields.values()
                  if r.get("arithmetic_verdict") == ARITH_DERIVED)
    formatted = sum(1 for r in fields.values()
                    if r.get("arithmetic_verdict") == ARITH_FORMATTED)
    lines.append(f"  ось «посчитано» (G91 п. 3): сильное прочтение {counted} имён · "
                 f"слабое (текст из числа) {formatted} — прочтения НЕ складываются")
    rule = doc["fitness_rule"]
    lines.append(f"  правило «род ⇒ годность»: {rule['verdict']} — {rule['why']}")
    mrule = measure_rule(doc)
    lines.append(f"  правило «посчитано ⇒ не личность»: {mrule['verdict']}"
                 + (f" — {mrule['why']}" if mrule.get("why") else ""))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ исходники; _IDENTITY_FIELDS, "
                 "координаты, RiskPolicy v1.0, стоп-кран и живой трек не трогает")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--field", action="append", default=None,
                    help="имя поля (по умолчанию — всё _IDENTITY_FIELDS)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    names = tuple(args.field) if args.field else tuple(_IDENTITY_FIELDS)
    doc = census(names, Path(args.tree_root))
    print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
          if args.json else report(doc))
    # Ненулевой код ТОЛЬКО на «не измерено»: находка оси здесь не есть дефект —
    # правило, по которому она стала бы дефектом, отвергнуто выше.
    unmeasured = sum(1 for r in doc["fields"].values()
                     if r["verdict"] == UNMEASURED)
    return 2 if (unmeasured or not doc["files_parsed"]) else 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
