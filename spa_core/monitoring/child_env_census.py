#!/usr/bin/env python3
"""spa_core/monitoring/child_env_census.py — «отличит ли вызывающий „у ребёнка нет
инструмента" от „ребёнок ответил"?»

**Зачем.** Цикл #1055 (ADR-938) нашёл у СВОЕЙ мутационной пробы дефект, который
смотрел прямо в вердикт: проба собрала окружение дочернего прогона РУКАМИ, системный
`python3` в этом окружении не имел `pytest`, и все 14 мутаций «умерли» с
``No module named pytest``. Напечатано было «14 из 14 убито, 0 выжило» — то есть
ОТСУТСТВИЕ ИНСТРУМЕНТА было выдано за ЧИСЛО, и выдано в сторону ЛОЖНОГО УСИЛЕНИЯ.
Это тот же класс, что `pyflakes` в `.claude/rules/deployment.md` (§ «ЛИЧНОСТЬ
ПРОЦЕССА», «отсутствие инструмента — самостоятельный третий исход»), но с другой
стороны границы процесса: там инструмента не было У ПРИБОРА, здесь — У РЕБЁНКА,
которого прибор запустил.

Заказ G927 п. 5 (ADR-938) говорит дословно: один предмет найден и починен, а
**сколько ещё приборов в репозитории зовут дочерний процесс с собранным руками
``env=`` — не спрашивал никто**, и ошибка у класса идёт в сторону ложного усиления.
Этот модуль задаёт вопрос.

**ЧЕТЫРЕ двери, у каждой свой вопрос и свой третий исход (инв. #17).** Склеивать их
нельзя: они чинятся разным, и call-site, опасный по одной оси, может быть безвреден
по другой.

====================  ======================================================
дверь                 вопрос, на который она отвечает
====================  ======================================================
``env_door``          ТЕРЯЕТ ли ребёнок окружение родителя — происходит ли
                      значение ``env=`` от ``os.environ``
``tool_door``         ЕСТЬ ЛИ ЧТО ТЕРЯТЬ — ищется ли инструмент ребёнка
                      ЧЕРЕЗ окружение (``-m <модуль>`` зависит от
                      ``PYTHONPATH``, бинарь без слэша — от ``PATH``)
``evidence_door``     ТРЕБУЕТ ли вызывающий у ребёнка ДОКАЗАТЕЛЬСТВА прогона
                      или судит по одному коду возврата
``control_door``      есть ли ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ не через вывод —
                      чтение артефакта, который пишет только настоящий
                      прогон, либо проверка ЖИВОСТИ ребёнка
====================  ======================================================

**Поверхность — ДВА перехода, и второй добавлен ЗАМЕРОМ.** Прямые вызовы
``subprocess.*(env=…)`` — это 154 строки; но ЕДИНСТВЕННАЯ в дереве дверь дочернего
`pytest` (`spa_core/tests/_child_pytest.py::run_child_pytest`) окружение ребёнку
ПЕРЕДАЁТ, а не строит, и прибор, остановившийся у неё, ответил бы «предмет 0» о классе,
которого он не видел. Поэтому поверхность включает ОДИН переход через границу вызова к
ПОДЪЁМНИКАМ — функциям, у которых ``env=`` дочернего вызова происходит от их
СОБСТВЕННОГО параметра. Перечень подъёмников не объявлен списком и не взят из памяти:
он ИЗМЕРЕН (замер 07.11: **55**). Глубина перехода — **1**, и это ВЫБОР, печатаемый в
отчёте, а не свойство дерева.

**Почему ``evidence_door`` — про ВЫВОД, а не про код возврата.** Отсутствие
инструмента и честный отказ инструмента дают ОДИН И ТОТ ЖЕ ненулевой код. Различить
их можно только по выводу (``No module named pytest`` против сводки ``… failed``) или
отказом ``check=True``, при котором ошибка уходит в ШУМ (исключение), а не в ТИШИНУ
(«мутант убит»). Вызывающий, который прочитал только ``.returncode``, по построению не
может сказать, мерил ли он что-нибудь вообще — и именно эту форму имела авария #1055.

**Почему ``check=True`` считается доказательством, хотя вывод не читает.** Он не
отвечает на вопрос «что именно ответил ребёнок», но делает невозможным ГЛАВНЫЙ вред
класса: превратить молчание ребёнка в усиление вывода. Направление ошибки — вот
предмет; у ``check=True`` оно в шум.

**Предмет класса объявлен ДВУМЯ числами, а не одним.**

* ``subject`` — ДОКАЗАННЫЙ предмет: инструмент ищется через окружение **и** вывод не
  читается **и** положительного контроля нет — то есть «инструмента у ребёнка нет»
  НЕОТЛИЧИМО от «инструмент ответил» по тому, что вызывающий вообще читает.
* ``not_excluded`` — предмет НЕ ИСКЛЮЧЁН: хотя бы одна дверь ответила
  ``unmeasured``, а остальные стоят на опасной стороне. Это НЕ «чисто» и НЕ
  «найдено»; слить его с любым из двух значило бы сделать «не измерено»
  неотличимым от ответа.

**Предмет НЕ ЕСТЬ дефект, и это не оговорка, а граница утверждения.** Прибор
доказывает НЕРАЗЛИЧИМОСТЬ двух исходов у вызывающего. КУДА он от этой неразличимости
выводит — в ШУМ (красный тест) или в ТИШИНУ («мутант убит», «находок нет») — вопрос
СЛЕДУЮЩИЙ, и он НЕ ИЗМЕРЕН: мерить направление значило бы читать смысл, а не форму.
Вред класса живёт только в тишине, поэтому ``subject`` есть ВЕРХНЯЯ граница вреда.

**Чего прибор НЕ докладывает** (названо, а не умолчано):

* ВЫЗЫВАЕТСЯ ли этот call-site на самом деле — AST отвечает о форме, не об
  исполнении; мёртвый код в населении остаётся;
* КУДА выводит вызывающий из неразличимости (в шум или в тишину) — см. выше;
* цепочку из ДВУХ и более подъёмников: глубина перехода 1, поэтому найденное есть
  доказанный МИНИМУМ;
* ``derived``-окружение, из которого ПОТОМ выброшен нужный ключ (``pop("PYTHONPATH")``)
  — дверь спрашивает ПРОИСХОЖДЕНИЕ, а не итоговый состав; намеренное опустошение
  (``env["PATH"] = ""`` в `test_live_data_write_guard.py`) она тоже не видит;
* достаточно ли прочитанного вывода, чтобы отличить отсутствие инструмента: прибор
  видит, что вывод ЧИТАЮТ, и не судит, ЧТО в нём ищут;
* положительный контроль в СОСЕДНЕЙ функции того же файла. Это ровно случай
  единственного предмета замера 07.11: у `test_list_identity_census.py:448` три
  проверки отказа судят по коду возврата, а эталон (`test_both_given_is_accepted`,
  «обратная сторона: отказ обязан быть следствием нехватки») стои́т МЕТОДОМ РЯДОМ.
  Дверь его не видит ПО ПОСТРОЕНИЮ, и ошибка её поэтому уходит в сторону НАХОДКИ.

**Прибор только ЧИТАЕТ** — ни одного байта никуда не пишет, ничего не исполняет
(дочерние процессы он разбирает как текст, а не запускает).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Корни поверхности — ОБЪЯВЛЕНИЕ. Расширение перечня есть решение, а не умолчание:
# каталог, которого здесь нет, в население не входит, и это сказано вслух в отчёте.
DECLARED_ROOTS = ("spa_core", "scripts", "tests")

# Вложенные деревья того же клона несут КОПИИ тех же файлов; считать их значило бы
# умножить население на число worktree'ов, живущих внутри репозитория.
SKIP_PARTS = (".claude", "node_modules", ".git", "site-packages", "__pycache__")

# Имена, под которыми запускается дочерний процесс. Перечень ЗАМКНУТ: вызов под
# другим именем в поверхность не входит, и это цена, а не пробел.
SUBPROCESS_NAMES = ("run", "Popen", "check_output", "call", "check_call")

# Объявленные исходы каждой двери. Дверь, вернувшая имя вне своего списка, краснит
# сторожа, а не проезжает молча.
ENV_OUTCOMES = ("derived", "handbuilt", "unmeasured")
TOOL_OUTCOMES = ("needs_env_lookup", "named_absolutely", "unmeasured")
EVIDENCE_OUTCOMES = ("demands_evidence", "returncode_only", "unmeasured")
CONTROL_OUTCOMES = ("artifact_read", "liveness_checked", "none", "unmeasured")

# Опасная сторона ОСЕЙ ПРЕДМЕТА — ОБЪЯВЛЕНИЕ, с которым сверяется тест: иначе «что
# считается предметом» жило бы только в теле условия и расходилось бы молча.
#
# ПОЧЕМУ ОСЬ ОКРУЖЕНИЯ В ПРЕДМЕТ НЕ ВХОДИТ. Заказ G927 п. 5 (ADR-938) объявляет поверхностью
# вызовы с явным ``env=``, а ПРЕДМЕТОМ — «те, у которых нет положительного контроля на
# эталоне». То есть ``env=`` есть ПОВЕРХНОСТЬ, а не признак вреда. Поставить
# ``handbuilt`` ЧЕТВЁРТЫМ условием предмета значило бы получить ноль ПО ПОСТРОЕНИЮ
# (замер 07.11: ``handbuilt`` 2 из 220) и объявить класс пустым, не ответив на вопрос:
# ребёнок теряет инструмент и от ``derived``-окружения тоже — другим интерпретатором,
# опустошённым ``PATH``, чужим ``cwd``. Ось окружения поэтому ДОКЛАДЫВАЕТСЯ отдельно и
# помечает предмет как УСУГУБЛЁННЫЙ, но предметом не распоряжается.
SUBJECT_AXES = {
    "tool": "needs_env_lookup",
    "evidence": "returncode_only",
    "control": "none",
}
AGGRAVATING = {"env": "handbuilt"}


# --------------------------------------------------------------------------- #
# разрешение имён
# --------------------------------------------------------------------------- #

def _mentions_environ(node: ast.AST) -> bool:
    """Упоминает ли выражение ``os.environ`` — в любой из живых форм.

    ``os.environ.copy()`` · ``dict(os.environ)`` · ``{**os.environ, "K": "V"}`` ·
    ``os.environ | {...}`` · ``environ`` после ``from os import environ``.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "environ":
            return True
        if isinstance(sub, ast.Name) and sub.id == "environ":
            return True
    return False


def _assignment_map(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """Имя → все выражения, которые ему когда-либо присваивались в файле.

    Карта ПЛОСКАЯ (без областей видимости) намеренно: ошибка такой карты идёт в
    сторону ``derived`` только тогда, когда ОДНОИМЁННАЯ переменная в другой функции
    действительно происходит от ``os.environ``, — и это ослабление, которое названо,
    а не скрыто. Обратная ошибка (счесть ``derived`` рукотворным) привела бы к
    выдуманной находке, а находки обязаны быть настоящими.
    """
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _target_names(target):
                    out.setdefault(name, []).append(node.value)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if node.value is not None:
                for name in _target_names(node.target):
                    out.setdefault(name, []).append(node.value)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            for name in _target_names(node.optional_vars):
                out.setdefault(name, []).append(node.context_expr)
    for node in ast.walk(tree):
        # Словарь окружения ПОПОЛНЯЮТ, а не только присваивают, и две живые формы
        # пополнения — `env["K"] = v` и `env.update({...})`. Без них карта отвечала о
        # ФОРМЕ ЗАПИСИ: `rule_second_copy_census.py:8339` кладёт путь журнала ровно
        # через `update`, и дверь контроля назвала предметом код, у которого контроль
        # есть. Поймано СВОИМ тестом до доставки, а не на живом дереве.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    out.setdefault(target.value.id, []).append(node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("update", "setdefault")
              and isinstance(node.func.value, ast.Name)):
            for arg in node.args:
                out.setdefault(node.func.value.id, []).append(arg)
            for keyword in node.keywords:
                out.setdefault(node.func.value.id, []).append(keyword.value)
    return out


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    return []


def _resolve(node: ast.AST, assigns: dict[str, list[ast.AST]],
             predicate) -> tuple[bool, bool]:
    """Ищет ``predicate`` по выражению и по всем его именам ДО НЕПОДВИЖНОЙ ТОЧКИ.

    Возвращает ``(найдено, остались ли неразрешённые имена)``. Второе значение и есть
    третий исход: имя, пришедшее параметром функции или из импорта, в файле не
    разрешается, и утверждать о нём нельзя ни в одну сторону.
    """
    seen_names: set[str] = set()
    frontier: list[ast.AST] = [node]
    unresolved = False
    while frontier:
        current = frontier.pop()
        if predicate(current):
            return True, unresolved
        for sub in ast.walk(current):
            if not isinstance(sub, ast.Name) or sub.id in seen_names:
                continue
            seen_names.add(sub.id)
            if sub.id in assigns:
                frontier.extend(assigns[sub.id])
            else:
                unresolved = True
    return False, unresolved


# --------------------------------------------------------------------------- #
# дверь 1 — происхождение окружения
# --------------------------------------------------------------------------- #

def env_door(value: ast.AST, assigns: dict[str, list[ast.AST]]) -> dict:
    """ТЕРЯЕТ ли ребёнок окружение родителя.

    ``derived`` — значение происходит от ``os.environ`` · ``handbuilt`` — построено
    без него и ВСЕ имена разрешены · ``unmeasured`` — осталось имя, которого в файле
    нет.
    """
    if isinstance(value, ast.Constant) and value.value is None:
        return {"env": "derived",
                "env_reason": "env=None — ребёнок наследует окружение родителя целиком"}
    found, unresolved = _resolve(value, assigns, _mentions_environ)
    if found:
        return {"env": "derived", "env_reason": None}
    if unresolved:
        return {"env": "unmeasured",
                "env_reason": "значение пришло именем, которого в файле нет "
                              "(параметр, импорт или атрибут) — происхождение не разобрано"}
    return {"env": "handbuilt",
            "env_reason": "окружение построено БЕЗ os.environ: ребёнок не получит "
                          "ни PATH, ни PYTHONPATH родителя"}


# --------------------------------------------------------------------------- #
# дверь 2 — ищется ли инструмент через окружение
# --------------------------------------------------------------------------- #

def _unwrap_sequence_call(node: ast.AST) -> ast.AST:
    """``list(argv)`` / ``tuple(argv)`` → ``argv``.

    Обёртка в ``list()`` — чистая форма записи, и без её снятия ЕДИНСТВЕННАЯ дверь
    дочернего `pytest` отвечала «argv не читается литералами»: `run_child_pytest`
    передаёт ``list(argv)``. Прибор отвечал бы о скобках, а не об инструменте.
    """
    while (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in ("list", "tuple") and len(node.args) == 1):
        node = node.args[0]
    return node


def _return_map(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """Имя функции файла → выражения, которые она возвращает.

    Нужно ровно для одного шага: argv дочернего прогона в этом дереве СОБИРАЕТ
    отдельная функция (`child_pytest_argv`), и без этого шага единственная дверь
    дочернего `pytest` отвечала бы «argv не читается литералами» — то есть прибор
    не увидел бы ``-m pytest`` там, где он написан прямым текстом.
    """
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and sub.value is not None:
                out.setdefault(node.name, []).append(sub.value)
    return out


def _literal_argv(node: ast.AST, assigns: dict[str, list[ast.AST]],
                  returns: Optional[dict[str, list[ast.AST]]] = None) -> Optional[list[Any]]:
    """Список argv литералами либо ``None``, если литералами он не читается.

    Нелитеральный элемент становится ``None`` в списке — позиция сохраняется, потому
    что ``-m`` судится ПО ПОЗИЦИИ, и потеря позиции сдвинула бы ответ.
    """
    returns = returns or {}
    node = _unwrap_sequence_call(node)
    target: Optional[ast.AST] = node
    if isinstance(node, ast.Name):
        target = None
        for candidate in assigns.get(node.id, []):
            if isinstance(candidate, (ast.List, ast.Tuple)):
                target = candidate
                break
            if (isinstance(candidate, ast.Call) and isinstance(candidate.func, ast.Name)
                    and candidate.func.id in returns):
                for returned in returns[candidate.func.id]:
                    if isinstance(returned, (ast.List, ast.Tuple)):
                        target = returned
                        break
            if target is not None:
                break
        if target is None:
            return None
    if isinstance(target, ast.Call) and isinstance(target.func, ast.Name) \
            and target.func.id in returns:
        for returned in returns[target.func.id]:
            if isinstance(returned, (ast.List, ast.Tuple)):
                target = returned
                break
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value.split()
    if not isinstance(target, (ast.List, ast.Tuple)):
        return None
    out: list[Any] = []
    for elt in target.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
        elif isinstance(elt, ast.Attribute) and elt.attr == "executable":
            out.append("<sys.executable>")
        elif isinstance(elt, ast.Starred):
            out.append(None)
        else:
            out.append(None)
    return out


def tool_door(argv_node: Optional[ast.AST],
              assigns: dict[str, list[ast.AST]],
              returns: Optional[dict[str, list[ast.AST]]] = None) -> dict:
    """ЕСТЬ ЛИ ЧТО ТЕРЯТЬ: ищется ли инструмент ребёнка через окружение.

    ``needs_env_lookup`` — ``-m <модуль>`` (ищется по ``PYTHONPATH``) либо бинарь без
    слэша (ищется по ``PATH``) · ``named_absolutely`` — путь назван целиком, поиск
    окружения не касается · ``unmeasured`` — argv литералами не читается.
    """
    if argv_node is None:
        return {"tool": "unmeasured", "tool_reason": "argv не передан позиционно",
                "tool_name": None}
    argv = _literal_argv(argv_node, assigns, returns)
    if not argv:
        return {"tool": "unmeasured",
                "tool_reason": "argv не читается литералами (вычисляется в рантайме)",
                "tool_name": None}
    for index, item in enumerate(argv):
        if item == "-m" and index + 1 < len(argv):
            module = argv[index + 1]
            return {"tool": "needs_env_lookup",
                    "tool_reason": f"-m {module or '<вычисляется>'} — модуль ищется "
                                   f"по PYTHONPATH дочернего процесса",
                    "tool_name": module}
    head = argv[0]
    if head is None:
        return {"tool": "unmeasured",
                "tool_reason": "нулевой элемент argv вычисляется в рантайме",
                "tool_name": None}
    if head == "<sys.executable>" or head.startswith("/"):
        return {"tool": "named_absolutely",
                "tool_reason": "инструмент назван абсолютно — окружение на его поиск "
                               "не влияет",
                "tool_name": head}
    return {"tool": "needs_env_lookup",
            "tool_reason": f"{head} — бинарь без слэша, ищется по PATH дочернего процесса",
            "tool_name": head}


# --------------------------------------------------------------------------- #
# дверь 3 — требует ли вызывающий доказательства прогона
# --------------------------------------------------------------------------- #

#: Способы прочитать вывод ребёнка. ``communicate`` добавлен ЗАМЕРОМ, а не из головы:
#: без него прибор назвал предметом `test_capital_shadow_lifecycle.py:958/960`, где
#: вывод читается ровно им (``out1, err1 = p1.communicate(...)``) и попадает в
#: сообщение провала, — то есть прибор ВЫДУМАЛ находку. Поймано ручной сверкой
#: каждой строки предмета ДО того, как число попало в ADR.
OUTPUT_READS = ("stdout", "stderr", "output", "communicate")


def _reads_output_of(name: str, scope: ast.AST) -> bool:
    """Читается ли у имени ``name`` ВЫВОД ребёнка где-нибудь в области ``scope``."""
    for sub in ast.walk(scope):
        if (isinstance(sub, ast.Attribute) and sub.attr in OUTPUT_READS
                and isinstance(sub.value, ast.Name) and sub.value.id == name):
            return True
    return False


def evidence_door(call: ast.Call, func_name: str, scope: Optional[ast.AST],
                  bound_name: Optional[str]) -> dict:
    """ТРЕБУЕТ ли вызывающий у ребёнка ДОКАЗАТЕЛЬСТВА прогона.

    ``demands_evidence`` — ``check=True`` (ошибка уходит в шум, не в тишину), либо
    ``check_output`` (он сам поднимает на ненулевом коде и возвращает ВЫВОД), либо у
    связанного имени читается ``.stdout``/``.stderr`` · ``returncode_only`` — решение
    принимается по одному коду возврата · ``unmeasured`` — результат не связан именем
    и ``check=`` не объявлен, значит сказать, что именно судится, нечем.
    """
    for keyword in call.keywords:
        if keyword.arg == "check":
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return {"evidence": "demands_evidence",
                        "evidence_reason": "check=True — ненулевой код ребёнка поднимает "
                                           "исключение, молчание в усиление не превратится"}
            if not isinstance(keyword.value, ast.Constant):
                return {"evidence": "unmeasured",
                        "evidence_reason": "check= вычисляется в рантайме"}
    if func_name in ("check_output", "check_call"):
        return {"evidence": "demands_evidence",
                "evidence_reason": f"{func_name} сам поднимает на ненулевом коде"}
    if bound_name is None:
        return {"evidence": "unmeasured",
                "evidence_reason": "результат не связан именем и check= не объявлен — "
                                   "что судится, в этом месте не читается"}
    if scope is not None and _reads_output_of(bound_name, scope):
        return {"evidence": "demands_evidence",
                "evidence_reason": f"вывод ребёнка читается ({bound_name}.stdout/.stderr)"}
    return {"evidence": "returncode_only",
            "evidence_reason": "вывод ребёнка не читается нигде в этой области — "
                               "«инструмента нет» и «инструмент ответил» дают один "
                               "и тот же ненулевой код"}


# --------------------------------------------------------------------------- #
# дверь 4 — положительный контроль иным путём, чем вывод
# --------------------------------------------------------------------------- #

#: Чтения, которые доказывают, что ребёнок ДОБЕЖАЛ до записи своего артефакта.
ARTIFACT_READS = ("read_text", "read_bytes", "open", "exists", "is_file", "stat")

#: Обращения, которые доказывают, что ребёнок ЖИВ, то есть инструмент разрешился.
LIVENESS_READS = ("poll", "pid", "send_signal", "terminate", "kill")


def _carried_names(node: ast.AST, assigns: dict[str, list[ast.AST]]) -> set[str]:
    """Все имена, достижимые из выражения ДО НЕПОДВИЖНОЙ ТОЧКИ.

    Без раскрытия имён дверь контроля отвечала о ФОРМЕ ЗАПИСИ, а не о путях: у
    `rule_second_copy_census.py:8339` значение ``env=`` есть одно имя ``env``, а
    путь журнала попадает в него тремя строками выше (``env.update({…: str(ledger)})``),
    поэтому ``ledger`` не был виден, и дверь назвала предметом код, у которого
    контроль есть. Замер до раскрытия: предмет 2; после: предмет 1.
    """
    out: set[str] = set()
    frontier = [node]
    while frontier:
        current = frontier.pop()
        for sub in ast.walk(current):
            if isinstance(sub, ast.Name) and sub.id not in out:
                out.add(sub.id)
                frontier.extend(assigns.get(sub.id, []))
    return out


def control_door(argv_node: Optional[ast.AST], env_node: Optional[ast.AST],
                 assigns: dict[str, list[ast.AST]], scope: Optional[ast.AST],
                 bound_name: Optional[str]) -> dict:
    """ЕСТЬ ЛИ у вызывающего ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ не через вывод.

    Заказ G927 п. 5 спрашивает именно про положительный контроль, и у него есть ДВЕ
    живые формы, кроме чтения вывода, — обе найдены сверкой строк предмета руками, а
    не придуманы:

    * ``artifact_read`` — вызывающий читает ФАЙЛ, путь которого он сам передал ребёнку
      в argv. Инструмента нет ⇒ файла нет ⇒ чтение падает ГРОМКО (образец:
      `test_model_roles_probe.py` — ``rec = json.loads(out.read_text())``);
    * ``liveness_checked`` — вызывающий спрашивает, ЖИВ ли ребёнок (``poll()``,
      ``send_signal``). Инструмента нет ⇒ ребёнок умер немедленно ⇒ проверка падает
      (образец: `test_safe_terminate_ownership.py` — вывод отправлен в ``DEVNULL``
      НАМЕРЕННО, и контроль там единственно возможный такой).

    ``none`` — ни одной формы · ``unmeasured`` — argv не читается, и какие пути уехали
    ребёнку, сказать нечем.

    **Чего дверь НЕ докладывает:** достаточно ли контроля (чтение, обёрнутое в
    ``except OSError`` с третьим исходом, она считает контролем — третий исход там
    честен, но он НЕ эталон); и контроль, стоящий в ДРУГОЙ функции того же файла
    (образец: ``test_both_given_is_accepted`` рядом с тремя отказами) — это следующий
    вопрос, и ошибка двери уходит в сторону НАХОДКИ, а не тишины.
    """
    if scope is None:
        return {"control": "unmeasured",
                "control_reason": "область вызова не определена"}
    if bound_name is not None:
        for sub in ast.walk(scope):
            if (isinstance(sub, ast.Attribute) and sub.attr in LIVENESS_READS
                    and isinstance(sub.value, ast.Name) and sub.value.id == bound_name):
                return {"control": "liveness_checked",
                        "control_reason": f"живость ребёнка спрашивают "
                                          f"({bound_name}.{sub.attr})"}
    if argv_node is None and env_node is None:
        return {"control": "unmeasured",
                "control_reason": "ни argv, ни env не читаются — какие пути уехали "
                                  "ребёнку, сказать нечем"}
    # Путь артефакта уезжает ребёнку ДВУМЯ дорогами, и вторую нельзя не считать:
    # `rule_second_copy_census.py:8339` передаёт журнал повторных входов ПЕРЕМЕННОЙ
    # ОКРУЖЕНИЯ (`env.update({REENTRY_ENV: str(ledger)})`) и потом читает его
    # (`ledger.read_text()`). Дверь, смотревшая только в argv, назвала этот call-site
    # предметом — то есть ВЫДУМАЛА находку на коде, у которого контроль есть.
    carried: set[str] = set()
    for source in (argv_node, env_node):
        if source is not None:
            carried |= _carried_names(source, assigns)
    if not carried:
        return {"control": "none",
                "control_reason": "ни в argv, ни в env не уехало ни одного "
                                  "имени — читать нечего"}
    for sub in ast.walk(scope):
        if (isinstance(sub, ast.Attribute) and sub.attr in ARTIFACT_READS
                and isinstance(sub.value, ast.Name) and sub.value.id in carried):
            return {"control": "artifact_read",
                    "control_reason": f"читается артефакт, путь которого уехал ребёнку "
                                      f"({sub.value.id}.{sub.attr})"}
    return {"control": "none",
            "control_reason": "ни вывод, ни артефакт, ни живость — доказательства "
                              "прогона у вызывающего нет ни одного"}


# --------------------------------------------------------------------------- #
# перепись
# --------------------------------------------------------------------------- #

def _call_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    """Ребёнок → родитель, один проход на файл.

    Считать область и привязку поиском по всему дереву НА КАЖДЫЙ call-site значило бы
    платить за файл в 16 000 строк столько раз, сколько в нём вызовов, — цена замера
    не должна решать, измерен ли он.
    """
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _binding_of(call: ast.Call, parents: dict[int, ast.AST]) -> Optional[str]:
    """Имя, которому присвоен результат вызова, либо ``None``."""
    parent = parents.get(id(call))
    if isinstance(parent, ast.Assign) and parent.value is call:
        names: list[str] = []
        for target in parent.targets:
            names.extend(_target_names(target))
        return names[0] if names else None
    if isinstance(parent, (ast.AnnAssign, ast.AugAssign)) and parent.value is call:
        names = _target_names(parent.target)
        return names[0] if names else None
    if isinstance(parent, ast.withitem) and parent.context_expr is call:
        names = _target_names(parent.optional_vars) if parent.optional_vars else []
        return names[0] if names else None
    return None


def _enclosing_scope(call: ast.Call, parents: dict[int, ast.AST],
                     tree: ast.AST) -> Optional[ast.AST]:
    """Самая узкая объявленная область, внутри которой стои́т вызов."""
    node: Optional[ast.AST] = parents.get(id(call))
    while node is not None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
        node = parents.get(id(node))
    return tree


def _param_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = func.args
    names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _dotted(rel: str) -> str:
    """Путь файла → точечное имя модуля (``spa_core/tests/x.py`` → ``spa_core.tests.x``)."""
    stem = rel[:-3] if rel.endswith(".py") else rel
    return stem.replace("/", ".")


def _imported_names(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
    """Что файл ввёз: ``имя → модуль`` для ``from m import n`` и ``алиас → модуль``.

    Нужно затем, чтобы переход через границу вызова разрешался ИМПОРТОМ, а не
    совпадением имени. Совпадение имени здесь было бы ровно той ошибкой, против
    которой написано правило `.claude/rules/adapters.md` «одно имя — один объект»:
    функций с именем ``run``/``_run``/``push``/``git`` в дереве много, и потребитель
    получил бы ту, чьё имя короче набрать.
    """
    names: dict[str, str] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name] = alias.name
    return names, modules


def find_spawners(repo_root: Path, roots: Sequence[str] = DECLARED_ROOTS,
                  *, read_text=None) -> dict[tuple[str, str], dict]:
    """ПРОХОД 1: функции дерева, которые поднимают ребёнка с окружением ОТ ВЫЗЫВАЮЩЕГО.

    Первая редакция прибора объявила границу вызова слепой зоной — и немедленно в неё
    и уехал весь настоящий класс: ЕДИНСТВЕННАЯ в репозитории дверь дочернего `pytest`
    (`spa_core/tests/_child_pytest.py::run_child_pytest`) передаёт ребёнку
    ``env=dict(env) if env is not None else None``, то есть происхождение окружения
    решает КАЖДЫЙ ВЫЗЫВАЮЩИЙ, а в самой двери его нет. Прибор, остановившийся у этой
    двери, ответил бы «предмет 0» о классе, которого он не видел.

    Перечень таких дверей НЕ объявлен списком и НЕ взят из памяти — он ИЗМЕРЕН: дверью
    считается функция, у которой значение ``env=`` дочернего вызова происходит от её
    СОБСТВЕННОГО параметра. Список из головы разошёлся бы с кодом молча.

    Глубина — ОДИН переход, и это ВЫБОР, а не свойство дерева: он печатается в отчёте.
    Цепочка из двух помощников в население не входит, поэтому найденное есть доказанный
    МИНИМУМ.
    """
    reader = read_text or (lambda p: p.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], dict] = {}
    for path in _candidate_files(repo_root, roots):
        try:
            tree = ast.parse(reader(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        assigns = _assignment_map(tree)
        parents = _parent_map(tree)
        returns = _return_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in SUBPROCESS_NAMES:
                continue
            env_kw = [k for k in node.keywords if k.arg == "env"]
            if not env_kw:
                continue
            scope = _enclosing_scope(node, parents, tree)
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = _param_names(scope)
            if not params:
                continue
            # ПОДЪЁМНИК — тот, у кого окружение ребёнка ПРИХОДИТ СНАРУЖИ ЦЕЛИКОМ. Функция,
            # которая берёт `os.environ` САМА и лишь доливает в него параметр
            # (`env = os.environ.copy(); env.update(extra)`), подъёмником НЕ является:
            # обрезать такое окружение вызывающий не может, происхождение решено на месте.
            # Без этого условия перечень подъёмников раздулся 55 → 119, то есть прибор
            # начал судить вызывающих за окружение, которого они не выбирали.
            if env_door(env_kw[0].value, assigns)["env"] != "unmeasured":
                continue
            found, _ = _resolve(
                env_kw[0].value, assigns,
                lambda n, _p=params: any(isinstance(s, ast.Name) and s.id in _p
                                         for s in ast.walk(n)))
            if not found:
                continue
            argv_node = node.args[0] if node.args else None
            rel = str(path.relative_to(repo_root))
            out[(_dotted(rel), scope.name)] = {
                "spawner": scope.name,
                "spawner_file": rel,
                "spawner_module": _dotted(rel),
                "spawner_line": node.lineno,
                **tool_door(argv_node, assigns, returns),
            }
    return out


def _candidate_files(repo_root: Path,
                     roots: Sequence[str] = DECLARED_ROOTS) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            out.append(path)
    return out


def _dotted_chain(node: ast.AST) -> Optional[str]:
    """``pkg.helper`` из ``Attribute(Name('pkg'), 'helper')`` либо ``None``.

    Без цепочки форма ``import pkg.helper`` + ``pkg.helper.run_child(...)`` переходом
    НЕ считалась: разбор требовал, чтобы слева от точки стояло одно имя. Поймано
    своим тестом (одна из трёх живых форм импорта молча выпадала).
    """
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _scope_name(scope) -> Optional[str]:
    return scope.name if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _resolve_spawner(call: ast.Call, name: str, here: str,
                     imported: dict[str, str], imported_modules: dict[str, str],
                     spawners: dict[tuple[str, str], dict]) -> Optional[dict]:
    """Переход через границу вызова разрешается ИМПОРТОМ, а не совпадением имени.

    ЧЕТЫРЕ живых формы и ровно четыре ответа: функция ВВЕЗЕНА (``from m import f``) ·
    ВВЕЗЕН МОДУЛЬ (``import m`` → ``m.f(...)``) · ВВЕЗЕН МОДУЛЬ ИЗ ПАКЕТА
    (``from p import m`` → ``m.f(...)``) · функция определена В ЭТОМ ЖЕ файле.
    Имя, совпавшее с подъёмником, но не ввезённое ниоткуда, переходом НЕ считается —
    ошибка уходит в занижение населения, и это названо.

    Четвёртая форма добавлена ЗАМЕРОМ, а не из головы: без неё переход находился у 5
    вызовов из 12, потому что ПЯТЬ из семи вызывающих единственной двери дочернего
    `pytest` пишут именно ``from spa_core.tests import _child_pytest`` и зовут
    ``_child_pytest.run_child_pytest(...)``. Прибор, не знающий этой формы, ответил бы
    «предмет меньше» — и ответил бы о форме импорта, а не о классе.
    """
    if isinstance(call.func, ast.Attribute):
        base = _dotted_chain(call.func.value)
        if base is None:
            return None
        candidates = []
        if base in imported_modules:
            candidates.append(imported_modules[base])
        if base in imported:
            candidates.append(f"{imported[base]}.{base}")
        for module in candidates:
            if (module, name) in spawners:
                return spawners[(module, name)]
        return None
    module = imported.get(name)
    if module and (module, name) in spawners:
        return spawners[(module, name)]
    if (here, name) in spawners:
        return spawners[(here, name)]
    return None


def census(repo_root: str | Path = REPO_ROOT, *,
           roots: Sequence[str] = DECLARED_ROOTS,
           read_text=None) -> dict:
    """Перепись класса. Возвращает ``doc`` с поверхностью, строками и ДВУМЯ числами предмета."""
    root = Path(repo_root)
    reader = read_text or (lambda p: p.read_text(encoding="utf-8"))
    if not root.is_dir():
        return {"surface": {"repo_root": str(root), "reason": f"дерева нет: {root}",
                            "files_scanned": 0, "files_unparsed": 0, "call_sites": 0,
                            "roots": list(roots), "roots_missing": list(roots)},
                "rows": [], "subject": [], "not_excluded": [], "spawners": {},
                "axes": {"env": {}, "tool": {}, "evidence": {}, "control": {}}}

    roots_missing = [r for r in roots if not (root / r).is_dir()]
    files = _candidate_files(root, roots)
    spawners = find_spawners(root, roots, read_text=read_text)
    rows: list[dict] = []
    unparsed: list[dict] = []
    scanned = 0

    for path in files:
        try:
            source = reader(path)
        except (OSError, UnicodeDecodeError) as exc:
            unparsed.append({"file": str(path.relative_to(root)),
                             "reason": f"не прочитан: {exc}"})
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            unparsed.append({"file": str(path.relative_to(root)),
                             "reason": f"не разбирается: {exc}"})
            continue
        scanned += 1
        assigns = _assignment_map(tree)
        parents = _parent_map(tree)
        returns = _return_map(tree)
        rel = str(path.relative_to(root))
        here = _dotted(rel)
        imported, imported_modules = _imported_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name is None:
                continue
            env_kw = [k for k in node.keywords if k.arg == "env"]
            if not env_kw:
                continue
            direct = name in SUBPROCESS_NAMES
            spawner = None if direct else _resolve_spawner(
                node, name, here, imported, imported_modules, spawners)
            if not direct and spawner is None:
                continue
            scope = _enclosing_scope(node, parents, tree)
            row = {"file": rel, "line": node.lineno, "call": name}
            row.update(env_door(env_kw[0].value, assigns))
            argv_node = node.args[0] if node.args else None
            if direct:
                row.update(tool_door(argv_node, assigns, returns))
                # Тело самого ПОДЪЁМНИКА судить нельзя: происхождение окружения там
                # решает не этот код, а каждый вызывающий. Его строка в предмет НЕ
                # входит — иначе одна и та же дыра считалась бы дважды, и считалась бы
                # по месту, где её нечем ни найти, ни починить.
                row["hop"] = ("spawner_body" if (here, _scope_name(scope)) in spawners
                              else "direct")
            else:
                # argv ребёнка собирает ПОДЪЁМНИК, не вызывающий: спрашивать argv здесь
                # значило бы спросить не у того, кто его знает.
                assert spawner is not None  # ветка достигается только при переходе
                row["hop"] = "through_spawner"
                row.update({k: spawner[k] for k in ("tool", "tool_reason", "tool_name")})
                row["spawner"] = f"{spawner['spawner_file']}:{spawner['spawner_line']}"
            bound = _binding_of(node, parents)
            row.update(evidence_door(node, name, scope, bound))
            row.update(control_door(argv_node, env_kw[0].value, assigns,
                                    scope, bound))
            rows.append(row)

    axes = {axis: {outcome: 0 for outcome in outcomes}
            for axis, outcomes in (("env", ENV_OUTCOMES), ("tool", TOOL_OUTCOMES),
                                   ("evidence", EVIDENCE_OUTCOMES),
                                   ("control", CONTROL_OUTCOMES))}
    for row in rows:
        for axis in axes:
            axes[axis][row[axis]] = axes[axis].get(row[axis], 0) + 1

    subject, not_excluded = [], []
    for row in rows:
        row["aggravated"] = all(row[axis] == outcome
                                for axis, outcome in AGGRAVATING.items())
        if row["hop"] == "spawner_body":
            # Происхождение окружения здесь решает ВЫЗЫВАЮЩИЙ, и судится оно в его
            # строке. Считать тело подъёмника предметом значило бы считать одну дыру
            # дважды и указать на место, где её нечем ни найти, ни починить.
            continue
        verdicts = {axis: row[axis] for axis in SUBJECT_AXES}
        if any(v not in ("unmeasured", SUBJECT_AXES[axis])
               for axis, v in verdicts.items()):
            continue  # хоть одна ось предмета ДОКАЗАННО безопасна ⇒ вред невозможен
        if all(v == SUBJECT_AXES[axis] for axis, v in verdicts.items()):
            subject.append(row)
        else:
            not_excluded.append(row)

    return {
        "surface": {"repo_root": str(root), "roots": list(roots),
                    "roots_missing": roots_missing, "files_scanned": scanned,
                    "files_unparsed": len(unparsed), "unparsed": unparsed,
                    "call_sites": len(rows),
                    "sites_direct": sum(1 for r in rows if r["hop"] == "direct"),
                    "sites_through_spawner": sum(1 for r in rows
                                                 if r["hop"] == "through_spawner"),
                    "sites_spawner_body": sum(1 for r in rows
                                              if r["hop"] == "spawner_body"),
                    "spawners": len(spawners),
                    "hop_limit": 1,
                    "reason": ("ни один объявленный корень не найден"
                               if len(roots_missing) == len(list(roots)) else None)},
        "rows": rows, "axes": axes, "subject": subject,
        "not_excluded": not_excluded, "spawners": spawners,
    }


# --------------------------------------------------------------------------- #
# отчёт
# --------------------------------------------------------------------------- #

def format_report(doc: dict, max_rows: int = 12) -> list[str]:
    surface = doc["surface"]
    out = [f"перепись «обрезанное окружение дочернего прогона»: "
           f"call-site(ов) {surface['call_sites']} в корнях "
           f"{', '.join(surface['roots'])}"]
    if surface.get("reason"):
        out.append(f"   ⛔ НЕ ИЗМЕРЕНО: {surface['reason']}")
        return out
    out.append(f"   файлов разобрано {surface['files_scanned']} · "
               f"НЕ РАЗОБРАНО {surface['files_unparsed']}"
               + (" — «не разобрано» чистым не считается" if surface["files_unparsed"] else ""))
    for entry in surface.get("unparsed", [])[:4]:
        out.append(f"      ⛔ {entry['file']} — {entry['reason']}")
    if surface.get("roots_missing"):
        out.append(f"   ⛔ объявленных корней нет в дереве: "
                   f"{', '.join(surface['roots_missing'])}")
    axes = doc["axes"]
    out.append(f"   ось ОКРУЖЕНИЯ (теряет ли ребёнок наше): "
               f"derived {axes['env']['derived']} · "
               f"handbuilt {axes['env']['handbuilt']} · "
               f"НЕ ИЗМЕРЕНО {axes['env']['unmeasured']}")
    out.append(f"   ось ИНСТРУМЕНТА (ищется ли через окружение): "
               f"needs_env_lookup {axes['tool']['needs_env_lookup']} · "
               f"named_absolutely {axes['tool']['named_absolutely']} · "
               f"НЕ ИЗМЕРЕНО {axes['tool']['unmeasured']}")
    out.append(f"   ось ДОКАЗАТЕЛЬСТВА (судит вывод или один код возврата): "
               f"demands_evidence {axes['evidence']['demands_evidence']} · "
               f"returncode_only {axes['evidence']['returncode_only']} · "
               f"НЕ ИЗМЕРЕНО {axes['evidence']['unmeasured']}")
    out.append(f"   ось КОНТРОЛЯ (положительный контроль не через вывод): "
               f"artifact_read {axes['control']['artifact_read']} · "
               f"liveness_checked {axes['control']['liveness_checked']} · "
               f"НЕТ НИ ОДНОГО {axes['control']['none']} · "
               f"НЕ ИЗМЕРЕНО {axes['control']['unmeasured']}")
    out.append(f"   переходы: прямых {surface['sites_direct']} · через подъёмник "
               f"{surface['sites_through_spawner']} · тел подъёмников "
               f"{surface['sites_spawner_body']} (в предмет НЕ входят — окружение там "
               f"решает вызывающий) · подъёмников {surface['spawners']} · "
               f"глубина перехода {surface['hop_limit']} — ВЫБОР, не свойство дерева")
    out.append(f"   ПРЕДМЕТ КЛАССА (инструмент через окружение ∧ вывод не читается ∧ "
               f"контроля нет): {len(doc['subject'])}")
    out.append(f"   НЕ ИСКЛЮЧЁН (хотя бы одна ось не измерена, остальные опасны): "
               f"{len(doc['not_excluded'])} — это НЕ «чисто» и НЕ «найдено»")
    out.append(f"   УСУГУБЛЕНО (окружение ещё и собрано руками): "
               f"{sum(1 for r in doc['subject'] + doc['not_excluded'] if r['aggravated'])}")
    out.append("   ПРЕДМЕТ НЕ ЕСТЬ ДЕФЕКТ: доказана НЕРАЗЛИЧИМОСТЬ «инструмента нет» и "
               "«инструмент ответил»; куда вызывающий из неё выводит — в шум или в "
               "тишину — НЕ ИЗМЕРЕНО, и вред живёт только в тишине")
    for label, bucket in (("ПРЕДМЕТ", doc["subject"]), ("НЕ ИСКЛЮЧЁН", doc["not_excluded"])):
        for row in bucket[:max_rows]:
            out.append(f"   {'🔴' if label == 'ПРЕДМЕТ' else '▫️'} [{label}] "
                       f"{row['file']}:{row['line']} ({row['call']})")
            out.append(f"      окружение: {row['env']}"
                       + (f" — {row['env_reason']}" if row.get("env_reason") else ""))
            out.append(f"      инструмент: {row['tool']}"
                       + (f" — {row['tool_reason']}" if row.get("tool_reason") else ""))
            out.append(f"      доказательство: {row['evidence']}"
                       + (f" — {row['evidence_reason']}" if row.get("evidence_reason") else ""))
        if len(bucket) > max_rows:
            out.append(f"   …и ещё {len(bucket) - max_rows} того же вида")
    out.append("   НЕ ДОКЛАДЫВАЕТ: исполняется ли call-site · окружение, собранное за "
               "границей вызова · derived-окружение, из которого ключ выброшен потом · "
               "что именно ищут в прочитанном выводе · контроль в СОСЕДНЕЙ функции "
               "того же файла · цепочку из двух подъёмников")
    out.append("   ADVISORY: прибор только ЧИТАЕТ — ни байта никуда не записано, "
               "ни один дочерний процесс не запущен")
    return out


def exit_code(doc: dict) -> int:
    """0 — предмет пуст · 1 — предмет НАЙДЕН · 2 — НЕ ИЗМЕРЕНО (поверхность не прочитана)."""
    if doc["surface"].get("reason"):
        return 2
    return 1 if doc["subject"] else 0
