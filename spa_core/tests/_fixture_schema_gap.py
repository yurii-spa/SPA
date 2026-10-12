"""Объявленный путь `_READ_SCHEMA`, которого фикстура соседа НЕ НЕСЁТ.

# LLM_FORBIDDEN

Заказ **G697 п. 2** приказа владельца «Portfolio CIO» — дословный хвост
ADR-697:

    «Класс "объявленный ключ без ЗНАЧЕНИЯ в фикстуре соседа" повторился
    ЧЕТВЁРТЫЙ раз — мерить население, а не чинить по одному. #832, #834, #837
    и этот цикл платили одним и тем же: раздел объявляется читаемым у шага
    0-офис, сосед его не получает, и чужая сцена краснеет не о своём предмете.
    Четыре случая — это уже не совпадение, а форма. Замерить: сколько путей
    `_READ_SCHEMA` сегодня НЕ несут значения ни в одной фикстуре, которая
    строит документ того же производителя. Есть население ⇒ храповик (база
    только вниз); нет ⇒ записать и закрыть.»

## Что именно мерится — и почему НЕ «все словари в файле»

Вред случается у ОДНОЙ двери: тест отдаёт свой документ читателю офиса
(`consume_office_reports._summarize_json(<имя артефакта>, doc, …)`), а тот
первым делом считает `_schema_drift` — пути `_READ_SCHEMA`, которых в
документе нет. Поэтому населением класса является не «словарь, похожий на
отчёт», а **площадка вызова этой двери**: пара «тест × артефакт», у которой
документ до двери доезжает, а объявленного пути в нём нет.

Первая, отброшенная редакция мерки искала словари-литералы по пересечению
ключей с объявленными и ошибалась грубо: у `pre_trade_recheck_census.json`
«документом» оказался словарь циферблатов соседнего зонда, совпавший одним
ключом `tolerance_s`, и все 21 путь артефакта объявлялись ненесомыми. Мера по
ДВЕРИ такой ошибки не допускает по построению: документ берётся тот, который
дверь и получает.

## Поток значения, а не подстрока

Документ почти никогда не стои́т в аргументе литералом: его собирает помощник
(`self._doc()`), а внутри — имя (`counts = {...}`), и у помощника бывает
несколько `return`. Поэтому аргумент РАЗРЕШАЕТСЯ по потоку значения: словарь →
имя (объединение всех его присваиваний) → вызов помощника того же файла
(объединение всех его `return`) → `dict(...)` / `{**base, …}`. Глубина
ограничена; предел — свой третий исход, а не «полей нет».

Объединение здесь не небрежность: `counts.update(over)` и ветки `if` дают
несколько присваиваний одному имени, и фикстура считается несущей путь, если
его несёт хотя бы одна ветка. Обратная мерка (пересечение) объявила бы
находкой намеренный отрицательный контроль («документ БЕЗ раздела»).

## Три исхода, и третий называется вслух

| исход | что наблюдалось | что печатается |
|---|---|---|
| площадка | имя артефакта и документ разрешены | объявленные пути, которых нет |
| НЕ ИЗМЕРЕНО | имя артефакта не разрешается (переменная, которой нет в файле) | причина `artifact_name_unresolved` |
| НЕ ИЗМЕРЕНО | документ не разрешается до словаря | причина `doc_unresolved:<почему>` |
| НЕ ИЗМЕРЕНО | файл не разобран | причина `file_unparsed:<ошибка>` |
| НЕ ИЗМЕРЕНО | документ МУТИРОВАН формой, которой статике не дано | `mutation_unmodelled` со своей причиной |
| вне предмета | имя разрешено, но в `_READ_SCHEMA` его нет | `name_not_declared` — стеречь нечего |

«НЕ ИЗМЕРЕНО» никогда не сворачивается в «путей не хватает 0»: это ровно та
подмена, против которой инвариант #17.

## Намеренно минимальная фикстура — освобождение С ПРИЧИНОЙ

Часть площадок кормит дверь куцым документом ПО ПРЕДМЕТУ: ветка возраста,
generic-ветка, сцена «раздела нет ⇒ отчёт старого образца». Дописать им поля
значило бы сломать их предмет. Для них есть пометка в исходнике —
``# SCHEMA-GAP-OK: <причина>`` на строке вызова или в теле её функции, — и
освобождение ВИДНО и СЧИТАЕТСЯ. Пометка без причины освобождением НЕ является
(тот же порядок, что у `FROZEN-DATE-OK`): она попадает в население и
называется отдельной строкой.

## Чего мера НЕ говорит

* **Не говорит, что площадка КРАСНЕЕТ сегодня.** `_schema_drift` различает
  «производитель поле не пишет» и «отчёт старого образца», и вторая форма
  печатается без находки. Население здесь — ЛАТЕНТНОЕ: оно обращается в
  красный тест только у сцен, пришпиливающих вывод целиком (так и покраснели
  #832/#834/#837/#841).
* **Мутацию связанного имени мера ВИДИТ, но не всякую** (заказ G699 п. 3,
  ADR-705). `del d[k]`, `d.pop("k")`, `d["k"] = v`, `d.update(БАЗА)` и
  `d.setdefault("k", v)` применяются к скелету, если порядок дан статике —
  то есть мутация написана выше ТОЧКИ ВЫХОДА значения из своей области.
  Ветвление, нелитеральный ключ, `clear()`, неразрешённое добавляемое
  значение и нераскрытый родитель уводят площадку в СВОЙ третий исход
  (`census.mutation_unmodelled`, потолок в базе храповика), а не в «чисто».
  Замер 12.10: мутируют документ **27 площадок из 78**, вердикт меняется у
  **трёх** — у двух объявленный путь до двери не доезжает (понижение), у
  третьей обвинение было ЛОЖНЫМ (повышение).
* **Не мерит артефакты без площадки.** Производитель, чей документ в тестах
  собирается прогоном самого производителя, в население не входит: фикстуры у
  него нет, и объявлять ей нечего.
* **Не судит о правдивости схемы.** Обратный вопрос — «ветка читает поле, а
  схема молчит» — мерит СОСЕД `_office_read_sites.py` (заказ #563), и у него
  ДРУГОЕ население: он идёт от чтений ветки, эта мера — от объявленных путей к
  фикстурам. Два ответа не заменяют друг друга и не сравниваются.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
from dataclasses import dataclass, field

#: Дверь: читатель офиса, у которого и считается `_schema_drift`.
DOOR = "_summarize_json"

#: Заглушка листа. `_has_path` спрашивает «ЕСТЬ ли поле», не «истинно ли оно»,
#: поэтому значение листа мере безразлично — важно лишь, что ключ есть.
LEAF = "<leaf>"

#: Предел глубины разрешения потока. Упёрлись — третий исход, а не «нет поля».
MAX_DEPTH = 12

#: Освобождение намеренно куцей фикстуры. Причина ОБЯЗАТЕЛЬНА.
_EXEMPT_RE = re.compile(r"#\s*SCHEMA-GAP-OK\s*:\s*(?P<why>\S.*?)\s*$")
_EXEMPT_BARE_RE = re.compile(r"#\s*SCHEMA-GAP-OK\s*:?\s*$")

#: Причины, по которым документ до словаря-литерала не доводится ПО ПРИРОДЕ
#: выражения, а не из-за слабости разбора: его собрал ВЫЗОВ.
#:
#: `receiver_not_self` и `self_outside_class` добавлены заказом G699 п. 2 и
#: суть та же природа: тело зовомого в этом файле не опознаётся, значит
#: словаря-фикстуры у площадки нет. Причины НАЗВАНЫ врозь нарочно — так цена
#: отказа от одалживания считается в `census.built_by_call`, а не растворяется
#: в общем «вызов не разрешён».
_BUILT_BY_CALL = frozenset({"call_unresolved", "helper_returns_no_dict",
                            "receiver_not_self", "self_outside_class"})

#: Каталоги тестов — предмет замера. Передаются ВХОДОМ, здесь только умолчание.
DEFAULT_TEST_DIRS = ("spa_core/tests", "tests", "scripts/tests")

#: Мутация СВЯЗАННОГО имени после присваивания (заказ G699 п. 3).
#:
#: Копия фикстуры есть ТА ЖЕ фикстура — дословное правило ADR-698, и оно верно
#: про ПРОИСХОЖДЕНИЕ документа. Но `del d[k]` после копии отдаёт двери УЖЕ
#: ДРУГОЙ документ, и для вопроса «несёт ли фикстура объявленный путь» это
#: разница по предмету, а не косметика: у `test_consume_office_reports.py:252`
#: строка `del drifted["house_view"]["top_opportunities"]` и ЕСТЬ площадка, у
#: которой объявленный путь до двери не доезжает.
_REMOVE_CALLS = frozenset({"pop", "popitem", "clear"})
_ADD_CALLS = frozenset({"update", "setdefault"})

#: Ветвление: тело исполняется НЕ ВСЕГДА, поэтому документ у двери статике не
#: дан. `with` сюда не входит намеренно — его тело исполняется безусловно.
_BRANCHING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
              ast.ExceptHandler)


@dataclass(frozen=True)
class Site:
    """Площадка: один вызов двери с разрешённым именем и документом."""

    file: str
    line: int
    artifact: str
    missing: tuple[str, ...]
    declared: int
    exempt_reason: str | None = None

    @property
    def key(self) -> str:
        return f"{self.file}::{self.artifact}"


@dataclass
class Census:
    files_scanned: int = 0
    sites: list[Site] = field(default_factory=list)
    out_of_subject: list[tuple[str, int, str]] = field(default_factory=list)
    built_by_call: list[tuple[str, str]] = field(default_factory=list)
    unmeasured: list[tuple[str, str]] = field(default_factory=list)
    marker_without_reason: list[tuple[str, int]] = field(default_factory=list)
    #: Пара «площадка × объявленный путь», у которой ПРОМЕЖУТОЧНЫЙ контейнер
    #: разбором не раскрыт (его собрал вызов): `(где, артефакт, путь, родитель)`.
    #: Это НЕ «фикстура не несёт путь» и НЕ «документа нет» — см. ADR-701.
    nested_unresolved: list[tuple[str, str, str, str]] = field(
        default_factory=list)
    #: Площадки, у которых документ МУТИРОВАН после присваивания и мутация
    #: СМОДЕЛИРОВАНА: `(где, артефакт, формы)`. Это население ФОРМЫ, а не
    #: население класса: вердикт у такой площадки обычный.
    mutated: list[tuple[str, str, tuple[str, ...]]] = field(
        default_factory=list)
    #: Площадки, у которых мутация есть, а статике НЕ ДАНА (ветвление,
    #: нелитеральный ключ, `clear`, чужое тело): документ у двери неизвестен,
    #: и вердикт о нём НЕ ИЗМЕРЕН — свой третий исход со своим потолком
    #: (урок ADR-701: новый исход без потолка есть лазейка наружу).
    mutation_unmodelled: list[tuple[str, str, tuple[str, ...]]] = field(
        default_factory=list)

    @property
    def population(self) -> list[Site]:
        """Площадки класса: путь объявлен, фикстура его не несёт, не освобождены."""
        return [s for s in self.sites if s.missing and not s.exempt_reason]

    @property
    def exempt(self) -> list[Site]:
        return [s for s in self.sites if s.missing and s.exempt_reason]

    @property
    def pairs(self) -> int:
        """Пар «площадка × объявленный путь» без значения."""
        return sum(len(s.missing) for s in self.population)

    def by_key(self) -> dict[str, int]:
        """Ключ «файл::артефакт» → сколько РАЗНЫХ путей не несёт ни одна его
        площадка.

        Объединение, а не сумма: один и тот же артефакт кормится из файла по
        нескольку раз (у `loop_health.json` — семь площадок с одним и тем же
        куцым документом), и сумма меняла бы число от переноса строки, а не от
        предмета.
        """
        out: dict[str, set[str]] = {}
        for s in self.population:
            out.setdefault(s.key, set()).update(s.missing)
        return {k: len(v) for k, v in sorted(out.items())}

    def missing_by_key(self) -> dict[str, tuple[str, ...]]:
        out: dict[str, set[str]] = {}
        for s in self.population:
            out.setdefault(s.key, set()).update(s.missing)
        return {k: tuple(sorted(v)) for k, v in sorted(out.items())}


def _absent_because(doc: dict, path: str) -> str | None:
    """ПОЧЕМУ объявленного пути в документе нет: отсутствует или НЕ РАСКРЫТ.

    Мера НЕ переспрашивает «есть ли путь» — на это отвечает `has_path` шага
    0-офис, и второй копии правила здесь нет (то же основание, что у
    `measure`). Эта функция классифицирует УЖЕ полученный отрицательный
    ответ, и различение не косметическое: «фикстура ключа не несёт» и «я не
    смог заглянуть внутрь контейнера» — разные утверждения, и второе есть
    третий исход (инв. #17).

    Замер ADR-701: у `test_list_candidate_readers.py` документ собран
    литералом, но его `counts` — результат `census.tally(ROWS)`, то есть
    вызов ПРОИЗВОДИТЕЛЬСКОГО помощника вне файла. Разбор ставит там `LEAF`,
    и `has_path(doc, "counts.candidate_kind")` отвечает `False` — не потому,
    что фикстура ключа не несёт (она несёт его настоящим `tally`), а потому
    что заглянуть внутрь не удалось. 34 пары из 199 были обвинены ЛОЖНО.

    Возвращает путь-родителя, на котором разбор упёрся в лист, либо `None`,
    если путь ОТСУТСТВУЕТ по-настоящему.
    """
    cur = doc
    walked: list[str] = []
    for part in path.split("."):
        if cur == LEAF:
            # Контейнер есть, но он не раскрыт: вопрос НЕ ИЗМЕРЕН.
            return ".".join(walked)
        if not isinstance(cur, dict) or part not in cur:
            return None
        walked.append(part)
        cur = cur[part]
    return None


def _merge(dst: dict, src: dict) -> None:
    """Объединение ветвей — ГЛУБОКОЕ: «несёт хотя бы одна ветка».

    Плоский `dict.update` отвечал на другой вопрос: ветка с `counts: {}`
    СТИРАЛА богатый `counts` соседней ветки, и ответ зависел от ПОРЯДКА
    присваиваний, а не от предмета (замер ADR-699: у
    `test_list_identity_census_wiring.py::_text` так исчезали все 17 путей
    `counts.*`, которые полная фикстура несёт). Вопрос меры — «есть ли поле
    хоть у одной ветки», и глубокое слияние есть ровно он.

    Лист против словаря: словарь богаче и остаётся — он несёт пути глубже.
    """
    for key, value in src.items():
        have = dst.get(key)
        if isinstance(have, dict) and isinstance(value, dict):
            _merge(have, value)
        elif isinstance(have, dict):
            continue
        else:
            dst[key] = value


def _assigns_of(scope: ast.AST) -> dict[str, list[ast.AST]]:
    """Присваивания СВОЕЙ области: тело `scope` без вложенных функций и классов.

    Граница области и есть предмет: обход, спускающийся во вложенные тела,
    выдаёт за видимое то, что из `scope` голым именем не видно.
    """
    out: dict[str, list[ast.AST]] = {}

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Assign):
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name):
                        out.setdefault(tgt.id, []).append(child.value)
            elif (isinstance(child, ast.AnnAssign)
                  and isinstance(child.target, ast.Name)
                  and child.value is not None):
                out.setdefault(child.target.id, []).append(child.value)
            walk(child)

    walk(scope)
    return out


@dataclass(frozen=True)
class _Mutation:
    """Одна мутация связанного имени: что сделано, где написано, чем дано.

    `scope_id` — область, в ТЕЛЕ которой мутация написана (`None` = уровень
    модуля). Она нужна затем же, зачем области понадобились присваиваниям
    (ADR-699): порядок «мутация против вызова двери» сравним только внутри
    ОДНОГО тела, а уровень модуля исполняется на импорте, то есть раньше
    любой сцены.
    """

    name: str
    kind: str                      # "remove" | "add"
    form: str                      # del · pop · clear · subscript_assign · update · setdefault
    line: int
    path: tuple[str, ...] | None   # None ⇒ ключ не литерал либо снято ВСЁ
    scope_id: int | None = None
    value: ast.AST | None = None
    conditional: bool = False


def _chain(node: ast.AST) -> tuple[str, tuple[str, ...] | None] | None:
    """`d["a"]["b"]` → `("d", ("a", "b"))`; нелитеральный ключ ⇒ путь `None`.

    База обязана быть ИМЕНЕМ: `self.doc["k"]` статике здесь не дан — вопрос
    той же природы, что `receiver_not_self` у двери вызова, и угадывать
    получателя значило бы одалживать (урок заказа G699 п. 2).
    """
    parts: list[str] = []
    unknown = False
    cur = node
    while isinstance(cur, ast.Subscript):
        key = cur.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            parts.append(key.value)
        else:
            unknown = True
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    return cur.id, (None if unknown else tuple(reversed(parts)))


def _mutations_of(scope: ast.AST, scope_id: int | None) -> dict[str, list[_Mutation]]:
    """Мутации имён СВОЕЙ области: `del d[k]`, `d.pop(k)`, `d["k"] = v`, …

    Граница области — та же, что у `_assigns_of`, и по той же причине: обход,
    спускающийся во вложенные тела, выдал бы за видимое то, что из `scope`
    голым именем не видно.

    Ветвление ПОМЕЧАЕТСЯ, а не игнорируется и не применяется молча: `del` под
    `if` исполняется не всегда, и какой документ доедет до двери — статике не
    дано. Такая мутация объявляется немоделируемой (инв. #17).
    """
    out: dict[str, list[_Mutation]] = {}

    def record(target: ast.AST, kind: str, form: str, line: int,
               tail: tuple[str, ...] | None, value: ast.AST | None,
               conditional: bool) -> None:
        chain = _chain(target)
        if chain is None:
            return
        name, path = chain
        full = None if (path is None or tail is None) else path + tail
        out.setdefault(name, []).append(_Mutation(
            name=name, kind=kind, form=form, line=line, path=full,
            scope_id=scope_id, value=value, conditional=conditional))

    def literal_key(call: ast.Call) -> tuple[str, ...] | None:
        """Первый аргумент как литеральный ключ; не литерал ⇒ `None`."""
        if call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return (arg.value,)
        return None

    def classify(node: ast.AST, conditional: bool) -> None:
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Delete):
            for tgt in node.targets:
                # `del d` снимает САМУ привязку, а не ключ документа — это
                # другой предмет, и в мутации содержимого он не идёт.
                if isinstance(tgt, ast.Subscript):
                    record(tgt, "remove", "del", line, (), None, conditional)
            return
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Subscript):
                    record(tgt, "add", "subscript_assign", line, (),
                           node.value, conditional)
            return
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Subscript):
            record(node.target, "add", "aug_assign", line, (), None, conditional)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, base = node.func.attr, node.func.value
            if attr in _REMOVE_CALLS:
                tail = None if attr in ("clear", "popitem") else literal_key(node)
                record(base, "remove", attr if attr != "pop" else "pop",
                       line, tail, None, conditional)
            elif attr == "update":
                record(base, "add", "update", line, (),
                       node.args[0] if node.args else None, conditional)
            elif attr == "setdefault":
                record(base, "add", "setdefault", line, literal_key(node),
                       node.args[1] if len(node.args) > 1 else None, conditional)

    def walk(node: ast.AST, conditional: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            classify(child, conditional)
            walk(child, conditional or isinstance(child, _BRANCHING))

    walk(scope, False)
    return out


def _deep_copy(doc: dict) -> dict:
    """Своя копия скелета: мутация площадки не вправе задеть соседнюю."""
    return {k: _deep_copy(v) if isinstance(v, dict) else v
            for k, v in doc.items()}


def _enclosing_funcs(tree: ast.Module) -> dict[int, ast.AST]:
    """Строка → ближайшая объемлющая функция (самая внутренняя из объемлющих)."""
    owner: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            line = getattr(inner, "lineno", None)
            if line is None:
                continue
            prev = owner.get(line)
            if prev is None or node.lineno > prev.lineno:
                owner[line] = node
    return owner


def _enclosing_classes(tree: ast.Module) -> dict[int, ast.ClassDef]:
    """Строка → ближайший объемлющий КЛАСС (самый внутренний из объемлющих).

    Нужен затем же, зачем `_enclosing_funcs` понадобился присваиваниям: имя
    метода принадлежит КЛАССУ, и разрешать его по файлу значит одалживать
    (заказ G699 п. 2).
    """
    owner: dict[int, ast.ClassDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for inner in ast.walk(node):
            line = getattr(inner, "lineno", None)
            if line is None:
                continue
            prev = owner.get(line)
            if prev is None or node.lineno > prev.lineno:
                owner[line] = node
    return owner


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    """Узел → его НЕПОСРЕДСТВЕННЫЙ родитель.

    Метод отличается от вложенной функции именно родителем, а не объемлющим
    классом: `def _h()` внутри метода класса `C` объемлется `C`, но методом
    `C` НЕ является и голым именем из соседнего метода не виден.
    """
    out: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


class _ModuleFlow:
    """Разрешение выражения в скелет словаря — по потоку значения внутри файла."""

    def __init__(self, tree: ast.Module, aliases: dict[str, str], *,
                 model_mutation: bool = True):
        self.aliases = aliases
        #: Моделировать ли мутацию имени после присваивания. ВХОД, а не
        #: зашитое поведение: цена слепоты к ней мерится ПОДСТАНОВКОЙ в эту
        #: дверь (заказ G699 п. 3), а не сравнением двух копий разбора.
        self.model_mutation = model_mutation
        # Определения разводятся по ВЛАДЕЛЬЦУ, а не по имени (заказ G699 п. 2):
        # метод живёт у пары «класс × имя», свободная функция — у имени.
        parents = _parents(tree)
        self._classes = _enclosing_classes(tree)
        self._class_by_name: dict[str, ast.ClassDef] = {}
        self._methods: dict[tuple[int, str], list[ast.AST]] = {}
        self._free_funcs: dict[str, list[ast.AST]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._class_by_name.setdefault(node.name, node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(id(node))
                if isinstance(owner, ast.ClassDef):
                    self._methods.setdefault((id(owner), node.name), []).append(node)
                else:
                    self._free_funcs.setdefault(node.name, []).append(node)
        self._module_assigns = _assigns_of(tree)
        self._module_muts = _mutations_of(tree, None)
        self._func_assigns: dict[int, dict[str, list[ast.AST]]] = {}
        self._func_muts: dict[int, dict[str, list[_Mutation]]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._func_assigns[id(node)] = _assigns_of(node)
                self._func_muts[id(node)] = _mutations_of(node, id(node))
        self.assigns: dict[str, list[ast.AST]] = dict(self._module_assigns)
        self.mutations: dict[str, list[_Mutation]] = dict(self._module_muts)
        self._scope_func: ast.AST | None = None
        #: ТОЧКА ВЫХОДА текущей области — строка, на которой значение эту
        #: область покидает: вызов двери у площадки, `return` у помощника,
        #: строка зова у вызывающего. Мутация, написанная НИЖЕ неё, документа
        #: за пределами области уже не меняет. Привязывать порядок к строке
        #: ПЛОЩАДКИ было бы неверно: тела разные, и номера строк в них не
        #: сравнимы (первая редакция этого замера так объявила 19 площадок
        #: «чужой областью», хотя мутация стои́т в ТОЙ ЖЕ области, что и
        #: присваивание, которое она правит).
        self._exit_line: int | None = None
        #: Мутации, которых статике НЕ ДАНО, и те, что применены. Два списка,
        #: а не один счётчик: «применено» есть население формы, «не дано» —
        #: третий исход, и складывать их значило бы ответить на третий вопрос.
        self.mutation_unmodelled: list[str] = []
        self.mutation_applied: list[str] = []
        self._owners = _enclosing_funcs(tree)
        #: КОНКРЕТНОЕ определение → его вызовы вместе с областью зова.
        #: Нужен, чтобы ПАРАМЕТР разрешался у ВЫЗЫВАЮЩЕГО (заказ G698 п. 2).
        #:
        #: Ключ — определение, а НЕ имя: прежняя редакция спрашивала
        #: `self.calls.get(func.name)`, и это было ТО ЖЕ объединение по имени,
        #: что у `self.funcs`, только у второй двери (заказ G699 п. 2 назвал
        #: одну из двух; вторая найдена этим ходом). У `setUp`, определённого
        #: в файле семь раз, параметр помощника разрешался аргументами ВСЕХ
        #: семи вызовов — ровно одалживание, против которого введена область.
        self.calls: dict[int, list[tuple[ast.Call, ast.AST | None]]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            defs, _why = self.target_defs(node)
            for fdef in defs or ():
                self.calls.setdefault(id(fdef), []).append(
                    (node, self._owners.get(node.lineno)))

    def _lookup_method(self, cls: ast.ClassDef, name: str,
                       seen: tuple[int, ...] = ()) -> list[ast.AST] | None:
        """Метод по паре «класс × имя», затем по базам, объявленным В ФАЙЛЕ.

        Строгое «только свой класс» потеряло бы наследование: сцена-потомок
        зовёт `self._doc()`, определённый у базы, и объявить его ненайденным
        значило бы купить исправление потерей зрения. База вне файла
        (`unittest.TestCase`) честно не находится — документ собрал вызов.
        """
        if id(cls) in seen:
            return None
        defs = self._methods.get((id(cls), name))
        if defs:
            return defs
        for base in cls.bases:
            bname = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None)
            parent = self._class_by_name.get(bname) if bname else None
            if parent is None:
                continue
            found = self._lookup_method(parent, name, seen + (id(cls),))
            if found:
                return found
        return None

    def target_defs(self, node: ast.Call) -> tuple[list[ast.AST] | None, str | None]:
        """Определения, которые ДЕЙСТВИТЕЛЬНО зовёт этот вызов.

        Одно правило на обе двери (разрешение зовомого и разрешение
        вызывающего), и второй его копии нет: две копии разошлись бы молча.

        | форма вызова | чем разрешается |
        |---|---|
        | `f(...)` | свободные функции файла — метод голым именем не виден |
        | `self.f(...)` / `cls.f(...)` | пара «класс площадки × имя» + базы в файле |
        | `C.f(...)`, `C` — класс ФАЙЛА | пара «этот класс × имя» |
        | `mod.f(...)`, `mod` — импорт | тело вне файла ⇒ `call_unresolved` |
        | `other.f(...)` | получатель неизвестен ⇒ `receiver_not_self` |

        Последние две строки РАЗВЕДЕНЫ нарочно, и это не косметика: модуль —
        это «тела здесь нет по природе» (так `json.loads(raw)` и
        `producer.run()` отвечали с ADR-698), а неизвестный объект — «тело,
        может быть, и здесь, но КОТОРОЕ из одноимённых, статике не дано».
        Свернуть их в одну причину значило бы потерять различие между
        отсутствием предмета и отказом одалживать. Одалживать же
        неизвестному получателю любой одноимённый метод файла — ровно тот
        вред, который мерит заказ G699 п. 2, поэтому исход НАЗВАН, чтобы
        цена считалась в `census.built_by_call`, а не растворилась.
        """
        func = node.func
        if isinstance(func, ast.Name):
            return self._free_funcs.get(func.id), None
        if not isinstance(func, ast.Attribute):
            return None, "call_unresolved"
        receiver = func.value
        if not isinstance(receiver, ast.Name):
            return None, "receiver_not_self"
        if receiver.id in ("self", "cls"):
            cls = self._classes.get(node.lineno)
            if cls is None:
                return None, "self_outside_class"
            return self._lookup_method(cls, func.attr), None
        own = self._class_by_name.get(receiver.id)
        if own is not None:
            return self._lookup_method(own, func.attr), None
        if receiver.id in self.aliases:
            return None, "call_unresolved"
        return None, "receiver_not_self"

    def scope_to(self, func: ast.AST | None,
                 exit_line: int | None = None) -> None:
        """Связать имена так, как их связывает PYTHON — не весь файл.

        Прежняя редакция собирала `assigns` обходом ВСЕГО модуля, и имя `doc`
        объединяло присваивания из ВСЕХ функций файла. У той формы два вреда,
        и оба измерены (ADR-699): чужой словарь объявлялся документом площадки,
        которая его не видит (ЛОЖНАЯ находка — три площадки `_health.json`
        числились «не несёт 7 из 7», тогда как их настоящая фикстура
        `HEALTH_REAL` несёт все семь), и наоборот — богатый сосед ОДАЛЖИВАЛ
        куцей площадке свои ключи, пряча настоящий пробел.

        Область берётся по правилам языка: своя функция плюс уровень модуля.
        Тело класса СЮДА НЕ ВХОДИТ — имя, присвоенное в теле класса, из метода
        голым именем не видно (`NameError`), и считать его видимым значило бы
        вернуть то же одалживание под другим именем.
        """
        self.assigns = dict(self._module_assigns)
        self.mutations = dict(self._module_muts)
        self._scope_func = func
        self._exit_line = exit_line
        own = self._func_assigns.get(id(func)) if func is not None else None
        if own:
            for name, values in own.items():
                self.assigns[name] = values
        own_muts = self._func_muts.get(id(func)) if func is not None else None
        if own_muts:
            # Имя, присвоенное в теле, затеняет модульное — и мутации тоже
            # принадлежат ТОМУ имени, которое тело связывает.
            for name, muts in own_muts.items():
                self.mutations[name] = muts

    def _params(self, func: ast.AST) -> list[str]:
        a = func.args
        return [arg.arg for arg in (*a.posonlyargs, *a.args)]

    def _from_callers(self, param: str, depth: int, seen: tuple[str, ...]
                      ) -> tuple[dict | None, str | None]:
        """Значение ПАРАМЕТРА решает ВЫЗЫВАЮЩИЙ — спросить у него (G698 п. 2).

        Документ редко стои́т у двери литералом: сцена зовёт помощника
        (`self._render(self._doc())`), и внутри помощника имя — параметр,
        не присваивание. Областное связывание такое имя честно объявляет
        несвязанным, и остановиться здесь значило бы назвать «НЕ ИЗМЕРЕНО»
        ровно то, что статике ДАЁТСЯ: у помощника вызовов одна-две, и
        аргумент в них стои́т явно.

        Разрешение идёт в области ВЫЗЫВАЮЩЕГО, а не помощника: аргумент
        написан там, и связать его именами помощника значило бы повторить
        одалживание, против которого введена область.
        """
        func = self._scope_func
        if func is None or not isinstance(func, (ast.FunctionDef,
                                                 ast.AsyncFunctionDef)):
            return None, "name_unbound"
        params = self._params(func)
        if param not in params:
            return None, "name_unbound"
        index = params.index(param)
        # Вызовы ЭТОГО определения, а не всех одноимённых (заказ G699 п. 2).
        sites = self.calls.get(id(func)) or []
        if not sites:
            return None, "param_no_call_site"
        merged: dict = {}
        why: str | None = None
        got = False
        saved = (self.assigns, self.mutations, self._scope_func,
                 self._exit_line)
        try:
            for call, caller in sites:
                bound = self._argument(call, index, params)
                if bound is None:
                    why = why or "param_not_bound_at_call"
                    continue
                # Значение покидает область вызывающего НА СТРОКЕ ЗОВА.
                self.scope_to(caller, exit_line=call.lineno)
                sub, sub_why = self.skeleton(
                    bound, depth + 1, seen + ((id(func), param),))
                if sub is not None:
                    _merge(merged, sub)
                    got = True
                elif why is None:
                    why = sub_why
        finally:
            (self.assigns, self.mutations, self._scope_func,
             self._exit_line) = saved
        if got:
            return merged, why
        return None, why or "param_unresolved"

    @staticmethod
    def _argument(call: ast.Call, index: int, params: list[str]) -> ast.AST | None:
        """Аргумент, вставший на место параметра №`index`.

        `self` при вызове методом не передаётся позиционно, поэтому смещение
        читается из ФОРМЫ вызова, а не угадывается: `X.f(a)` связывает `a` со
        вторым параметром, `f(a)` — с первым.
        """
        offset = 1 if (isinstance(call.func, ast.Attribute)
                       and params and params[0] in ("self", "cls")) else 0
        position = index - offset
        if 0 <= position < len(call.args):
            arg = call.args[position]
            return None if isinstance(arg, ast.Starred) else arg
        for kw in call.keywords:
            if kw.arg == params[index]:
                return kw.value
        return None

    # --- имя артефакта ---------------------------------------------------
    def text(self, node: ast.AST, depth: int = 0) -> str | None:
        """Строка аргумента-пути: литерал, имя, f-строка, `mod.ATTR`, `a / b`."""
        if depth > MAX_DEPTH:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            for value in self.assigns.get(node.id, []):
                got = self.text(value, depth + 1)
                if got:
                    return got
            return None
        if isinstance(node, ast.Attribute):
            return self._module_attr(node, depth)
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                elif isinstance(part, ast.FormattedValue):
                    got = self.text(part.value, depth + 1)
                    if got is None:
                        return None
                    parts.append(got)
                else:
                    return None
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            # `data / mod.ARTIFACT` — имя файла несёт ПРАВЫЙ операнд.
            return self.text(node.right, depth + 1)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name == "str" and len(node.args) == 1:
                return self.text(node.args[0], depth + 1)
            return None
        return None

    def _module_attr(self, node: ast.Attribute, depth: int) -> str | None:
        """`mod.ARTIFACT` — спросить у НАСТОЯЩЕГО модуля, а не угадывать.

        Догадка по каталогу уже рождала выдуманные находки (урок #774):
        значение постоянной берётся из того модуля, которым имя связано в ЭТОМ
        файле, и ни из какого другого.
        """
        base = node.value
        if not isinstance(base, ast.Name):
            return None
        dotted = self.aliases.get(base.id)
        if not dotted:
            return None
        try:
            mod = importlib.import_module(dotted)
        except Exception:
            return None
        value = getattr(mod, node.attr, None)
        return value if isinstance(value, str) else None

    # --- документ --------------------------------------------------------
    def skeleton(self, node: ast.AST, depth: int = 0,
                 seen: tuple[str, ...] = ()) -> tuple[dict | None, str | None]:
        if depth > MAX_DEPTH:
            return None, "depth_limit"
        if isinstance(node, ast.Dict):
            return self._dict_skeleton(node, depth, seen)
        if isinstance(node, ast.Name):
            return self._name_skeleton(node, depth, seen)
        if isinstance(node, ast.Call):
            return self._call_skeleton(node, depth, seen)
        if isinstance(node, ast.Subscript):
            # `D.run(...)["doc"]` — документ достаётся из РЕЗУЛЬТАТА вызова.
            # Разрешать надо подчинённый узел, а причину — пробрасывать
            # как есть: иначе исход «собран вызовом» прочитался бы как
            # слабость разбора.
            inner, why = self.skeleton(node.value, depth + 1, seen)
            key = node.slice
            if (inner is not None and isinstance(key, ast.Constant)
                    and isinstance(key.value, str)):
                sub = inner.get(key.value)
                return (sub, why) if isinstance(sub, dict) else (None, why or "subscript_leaf")
            return None, why or "subscript_unresolved"
        if isinstance(node, ast.DictComp):
            # `{k: v for k, v in БАЗА.items() if k != "x"}` — отрицательный
            # контроль «документ БЕЗ поля». Предметом мерки является ФИКСТУРА,
            # а не её намеренное усечение, поэтому разрешается БАЗА включения
            # (то же правило объединения, что у нескольких присваиваний имени).
            return self._comprehension_skeleton(node, depth, seen)
        return None, "expr_unresolved"

    def _dict_skeleton(self, node: ast.Dict, depth: int,
                       seen: tuple[str, ...]) -> tuple[dict, str | None]:
        out: dict = {}
        why: str | None = None
        for key, value in zip(node.keys, node.values):
            if key is None:                               # {**base, …}
                sub, sub_why = self.skeleton(value, depth + 1, seen)
                if sub:
                    _merge(out, sub)
                elif why is None:
                    why = sub_why or "star_unresolved"
                continue
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                why = why or "non_literal_key"
                continue
            sub, _ = self.skeleton(value, depth + 1, seen)
            if sub is None:
                sub = self._first_in_sequence(value, depth + 1, seen)
            out[key.value] = sub if sub is not None else LEAF
        return out, why

    def _first_in_sequence(self, node: ast.AST, depth: int,
                           seen: tuple[str, ...]) -> dict | None:
        """Список записей: `_has_path` в элементы не спускается, но вложенный
        словарь-образец бывает единственным носителем формы раздела."""
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for element in node.elts:
                sub, _ = self.skeleton(element, depth, seen)
                if sub is not None:
                    return sub
        return None

    def _name_skeleton(self, node: ast.Name, depth: int,
                       seen: tuple) -> tuple[dict | None, str | None]:
        # Петля ищется по ПАРЕ «область × имя», а не по одному имени: после
        # перехода к вызывающему (G698 п. 2) у его локального `doc` то же
        # написание, что у параметра помощника, и проверка по одному имени
        # объявляла бы петлёй ОБЫЧНУЮ передачу аргумента (замер: 9 площадок
        # из 33 неизмеренных вместо 5).
        mark = (id(self._scope_func), node.id)
        if mark in seen:
            return None, "cycle"
        values = self.assigns.get(node.id)
        if not values:
            return self._from_callers(node.id, depth, seen)
        merged: dict = {}
        why: str | None = None
        got = False
        for value in values:
            sub, sub_why = self.skeleton(value, depth + 1, seen + (mark,))
            if sub is not None:
                _merge(merged, sub)
                got = True
            elif why is None:
                why = sub_why
        if not got:
            return None, why or "name_unresolved"
        if self.model_mutation:
            merged = self._mutated(node.id, merged, depth, seen)
        return merged, why

    def _mutated(self, name: str, doc: dict, depth: int,
                 seen: tuple) -> dict:
        """Скелет ПОСЛЕ мутаций этого имени — либо честное «статике не дано».

        Правило порядка объявлено, а не угадано:

        | где написана мутация | когда исполняется | что делает мера |
        |---|---|---|
        | та же область, ВЫШЕ точки выхода | до выхода значения | применяет |
        | та же область, НИЖЕ точки выхода | после выхода | не применяет |
        | уровень модуля, область — функция | на импорте, раньше сцены | применяет |
        | иное тело | порядок не сравним | третий исход (по построению пуст) |

        Всё, чего статике не дано — ветвление, нелитеральный ключ, снятие
        ВСЕГО (`clear`), неразрешённый родитель, неразрешённое добавляемое
        значение, — уводит площадку в СВОЙ третий исход, а не применяется
        молча и не замалчивается (инв. #17).
        """
        muts = self.mutations.get(name)
        if not muts:
            return doc
        current = self._scope_func
        out = doc
        for mut in muts:
            if mut.scope_id is not None and mut.scope_id != id(current):
                # По построению недостижимо: `self.mutations` несёт мутации
                # уровня модуля и ТЕКУЩЕЙ области, и ничьи больше. Исход
                # оставлен и ПЕЧАТАЕТСЯ: претензия «недостижимо» обязана быть
                # измеримой, а не объявленной.
                self._unmodelled(mut, "foreign_scope")
                continue
            if mut.scope_id is None and current is not None:
                if name in (self._func_assigns.get(id(current)) or {}):
                    # Имя связано В ТЕЛЕ и затеняет модульное: мутация
                    # модульной привязки к ЭТОМУ объекту не относится. То же
                    # правило, по которому `scope_to` затеняет присваивания, —
                    # иначе мера применила бы к документу площадки чужую
                    # правку, а это ровно одалживание ADR-699.
                    continue
                pass          # импорт раньше любой сцены — порядок известен
            elif self._exit_line is not None and mut.line >= self._exit_line:
                continue      # написана НИЖЕ точки выхода значения
            if mut.conditional:
                self._unmodelled(mut, "conditional")
                continue
            if mut.path is None:
                self._unmodelled(
                    mut, "whole_doc" if mut.form in ("clear", "popitem")
                    else "key_not_literal")
                continue
            out = self._apply(out, mut, depth, seen)
        return out

    def _unmodelled(self, mut: _Mutation, why: str) -> None:
        path = ".".join(mut.path) if mut.path else "*"
        self.mutation_unmodelled.append(
            f"{mut.name}[{path}] {mut.form}@{mut.line}: {why}")

    @staticmethod
    def _walk_to(doc: dict, path: tuple[str, ...]) -> dict | None:
        cur: object = doc
        for part in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur if isinstance(cur, dict) else None

    def _apply(self, doc: dict, mut: _Mutation, depth: int,
               seen: tuple) -> dict:
        """Применить ОДНУ мутацию к копии скелета.

        Копия своя (`_deep_copy`): вложенные словари скелета приходят из
        подчинённых разрешений, и править их на месте значило бы задеть
        соседнюю площадку — ровно та авария «мутация на месте», которой стоил
        живой реестр в #763.
        """
        path = mut.path or ()
        out = _deep_copy(doc)
        if mut.kind == "remove":
            parent = self._walk_to(out, path[:-1])
            if parent is None:
                self._unmodelled(mut, "parent_not_resolved")
                return doc
            parent.pop(path[-1], None)
            self.mutation_applied.append(f"{mut.name}[{'.'.join(path)}] {mut.form}")
            return out
        value: dict | None = None
        if mut.value is not None:
            value, _why = self.skeleton(mut.value, depth + 1, seen)
        if mut.form == "update":
            if value is None:
                self._unmodelled(mut, "value_unresolved")
                return doc
            parent = self._walk_to(out, path)
            if parent is None:
                self._unmodelled(mut, "parent_not_resolved")
                return doc
            _merge(parent, value)
        else:
            parent = self._walk_to(out, path[:-1])
            if parent is None:
                self._unmodelled(mut, "parent_not_resolved")
                return doc
            # Значение не разрешилось ⇒ ЛИСТ: ключ есть, внутрь не видно. Это
            # ровно то различение, которое `_absent_because` и несёт.
            parent[path[-1]] = value if value is not None else LEAF
        self.mutation_applied.append(f"{mut.name}[{'.'.join(path)}] {mut.form}")
        return out

    def _comprehension_skeleton(self, node: ast.DictComp, depth: int,
                                seen: tuple[str, ...]
                                ) -> tuple[dict | None, str | None]:
        for comp in node.generators:
            source = comp.iter
            if (isinstance(source, ast.Call)
                    and isinstance(source.func, ast.Attribute)
                    and source.func.attr in ("items", "copy")):
                source = source.func.value
            sub, why = self.skeleton(source, depth + 1, seen)
            if sub is not None:
                return sub, why
        return None, "comprehension_unresolved"

    @staticmethod
    def _json_round_trip(node: ast.Call) -> ast.AST | None:
        """`json.loads(json.dumps(X))` → `X`, иначе `None`."""
        def dotted(call: ast.Call, attr: str) -> bool:
            func = call.func
            return (isinstance(func, ast.Attribute) and func.attr == attr
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "json")

        if not (dotted(node, "loads") and len(node.args) == 1):
            return None
        arg = node.args[0]
        if isinstance(arg, ast.Call) and dotted(arg, "dumps") and arg.args:
            return arg.args[0]
        return None

    def _call_skeleton(self, node: ast.Call, depth: int,
                       seen: tuple[str, ...]) -> tuple[dict | None, str | None]:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        if name in ("deepcopy", "copy") and node.args:
            # Копия фикстуры ЕСТЬ та же фикстура — это верно про
            # ПРОИСХОЖДЕНИЕ документа, и затем идиом и опознаётся. Вторая
            # половина прежнего комментария («мутации после копии — это
            # отрицательные контроли, а не другой документ») была неверна
            # ВДВОЁМ и снята заказом G699 п. 3: мутация отдаёт двери другой
            # документ, и контролем она является не всегда (ADR-705).
            # Моделирует мутацию `_mutated`, а не этот идиом.
            return self.skeleton(node.args[0], depth + 1, seen)
        inner = self._json_round_trip(node)
        if inner is not None:
            # `json.loads(json.dumps(X))` — тот же идиом глубокой копии, что и
            # `deepcopy`, только написанный stdlib-ом (инв. #4). Не узнав его,
            # мера объявляла документ «собранным вызовом» и площадку теряла.
            return self.skeleton(inner, depth + 1, seen)
        if (name == "copy" and not node.args
                and isinstance(func, ast.Attribute)):
            return self.skeleton(func.value, depth + 1, seen)
        if name == "dict":
            out: dict = {}
            why: str | None = None
            for arg in node.args:
                sub, sub_why = self.skeleton(arg, depth + 1, seen)
                if sub:
                    _merge(out, sub)
                elif why is None:
                    why = sub_why or "star_unresolved"
            for kw in node.keywords:
                if kw.arg is None:
                    sub, sub_why = self.skeleton(kw.value, depth + 1, seen)
                    if sub:
                        _merge(out, sub)
                    elif why is None:
                        why = sub_why or "star_unresolved"
                else:
                    sub, _ = self.skeleton(kw.value, depth + 1, seen)
                    out[kw.arg] = sub if sub is not None else LEAF
            return out, why
        if name and name not in seen:
            # Разрешение по ВЛАДЕЛЬЦУ, а не по имени (заказ G699 п. 2): три
            # `_doc` в трёх классах `test_list_day_axis.py` зовутся каждый
            # своей сценой, а объединение по имени сливало их возвраты, и
            # богатый сосед ОПРАВДЫВАЛ куцую площадку.
            defs, why_target = self.target_defs(node)
            if not defs:
                return None, why_target or "call_unresolved"
            merged: dict = {}
            why = None
            got = False
            saved = (self.assigns, self.mutations, self._scope_func,
                     self._exit_line)
            try:
                for fdef in defs:
                    # Выражение `return` принадлежит ПОМОЩНИКУ, и связывать
                    # его имена областью ЗОВУЩЕГО значило бы то же
                    # одалживание, против которого введена область:
                    # `_health_with_house_view` строит документ в своём
                    # локальном `doc`, которого у сцены нет вовсе.
                    for ret in ast.walk(fdef):
                        if isinstance(ret, ast.Return) and ret.value is not None:
                            # Значение покидает помощника НА СВОЁМ `return`,
                            # и порядок мутаций считается до него.
                            self.scope_to(fdef, exit_line=ret.lineno)
                            sub, sub_why = self.skeleton(ret.value, depth + 1,
                                                         seen + (name,))
                            if sub is not None:
                                _merge(merged, sub)
                                got = True
                            elif why is None:
                                why = sub_why
            finally:
                (self.assigns, self.mutations, self._scope_func,
                 self._exit_line) = saved
            if got:
                return merged, why
            return None, why or "helper_returns_no_dict"
        return None, "call_unresolved"


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Имя в файле → точечное имя модуля (`import a.b as m`, `import_module`).

    Форма импорта теряется в плоском наборе имён (урок про `import a.b` против
    `from a.b import C`), поэтому собираются ровно те формы, что дают МОДУЛЬ:
    по ним и только по ним спрашивается значение постоянной.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            fname = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if fname != "import_module" or not node.value.args:
                continue
            arg = node.value.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = arg.value
    return out


def _exemption(lines: list[str], call_line: int,
               enclosing: tuple[int, int] | None) -> tuple[str | None, bool]:
    """Пометка освобождения: причина, и была ли пометка БЕЗ причины.

    Ищется на строке вызова и в теле её функции — там, где её и напишет автор
    куцей фикстуры. Пометка в докстринге невидима (урок #829): форма обязана
    быть `#`-комментарием, и регулярное выражение требует именно решётки.
    """
    span = [call_line]
    if enclosing:
        span = list(range(enclosing[0], enclosing[1] + 1))
    bare = False
    for number in span:
        if not (1 <= number <= len(lines)):
            continue
        text = lines[number - 1]
        hit = _EXEMPT_RE.search(text)
        if hit:
            return hit.group("why"), False
        if _EXEMPT_BARE_RE.search(text):
            bare = True
    return None, bare


def _enclosing_spans(tree: ast.Module) -> list[tuple[int, int]]:
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
    return spans


def _span_of(spans: list[tuple[int, int]], line: int) -> tuple[int, int] | None:
    best = None
    for start, end in spans:
        if start <= line <= end and (best is None or start > best[0]):
            best = (start, end)
    return best


def measure(*, schema: dict, has_path, root: str,
            test_dirs: tuple[str, ...] = DEFAULT_TEST_DIRS,
            model_mutation: bool = True) -> Census:
    """Перепись класса.

    `schema` и `has_path` приезжают ВХОДОМ — это правило шага 0-офис, и второй
    его копии здесь нет: пересчёт «что значит ЕСТЬ поле» был бы вторым
    правилом, расходящимся с первым молча.

    `model_mutation` — та же дверь ВХОДОМ (заказ G699 п. 3): цена слепоты к
    мутации после копии мерится ПОДСТАНОВКОЙ в сам прибор, двумя прогонами, а
    разница ответов и есть население класса. Вторая копия разбора ради замера
    расходилась бы с первой молча (урок #820).
    """
    census = Census()
    files: list[str] = []
    for directory in test_dirs:
        base = os.path.join(root, directory)
        for walk_root, _dirs, names in os.walk(base):
            files += [os.path.join(walk_root, n) for n in names if n.endswith(".py")]

    for path in sorted(files):
        rel = os.path.relpath(path, root)
        try:
            source = open(path, encoding="utf-8").read()
        except OSError as exc:
            census.unmeasured.append((rel, f"file_unreadable:{exc!r}"))
            continue
        if DOOR + "(" not in source:
            continue
        census.files_scanned += 1
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            census.unmeasured.append((rel, f"file_unparsed:{exc!r}"))
            continue
        lines = source.splitlines()
        flow = _ModuleFlow(tree, _aliases(tree), model_mutation=model_mutation)
        spans = _enclosing_spans(tree)
        owners = _enclosing_funcs(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name != DOOR or len(node.args) < 2:
                continue
            where = f"{rel}:{node.lineno}"
            # Имена связываются ОБЛАСТЬЮ площадки, а не файлом (ADR-699).
            flow.scope_to(owners.get(node.lineno))
            raw = flow.text(node.args[0])
            if raw is None:
                census.unmeasured.append((where, "artifact_name_unresolved"))
                continue
            artifact = os.path.basename(raw)
            if artifact not in schema:
                census.out_of_subject.append((rel, node.lineno, artifact))
                continue
            # Точка выхода площадки — строка вызова двери: мутация ниже неё
            # документа у двери уже не меняет.
            flow.scope_to(owners.get(node.lineno), exit_line=node.lineno)
            flow.mutation_unmodelled = []
            flow.mutation_applied = []
            doc, why = flow.skeleton(node.args[1])
            if doc is not None and flow.mutation_unmodelled:
                # Документ у двери статике не дан: вердикт о нём НЕ ИЗМЕРЕН.
                # Ни в население, ни в «путей не хватает 0» (инв. #17).
                census.mutation_unmodelled.append(
                    (where, artifact, tuple(dict.fromkeys(flow.mutation_unmodelled))))
                continue
            if doc is not None and flow.mutation_applied:
                census.mutated.append(
                    (where, artifact, tuple(dict.fromkeys(flow.mutation_applied))))
            if doc is None:
                if why in _BUILT_BY_CALL:
                    # Документ собран ВЫЗОВОМ (прогон производителя, чтение
                    # файла, помощник вне файла) — это НЕ словарь-фикстура, и
                    # класс «объявленный ключ без значения в фикстуре» к нему
                    # не относится по построению. Исход назван отдельно, а не
                    # свёрнут ни в население, ни в «НЕ ИЗМЕРЕНО»: то, что у
                    # мерки нет предмета, и то, что она не справилась, —
                    # разные ответы.
                    census.built_by_call.append((where, str(why)))
                else:
                    census.unmeasured.append((where, f"doc_unresolved:{why}"))
                continue
            missing_paths: list[str] = []
            for p in schema[artifact]:
                if has_path(doc, p):
                    continue
                parent = _absent_because(doc, p)
                if parent is not None:
                    # Третий исход: родитель собран ВЫЗОВОМ и не раскрыт.
                    # В население не входит и нулём не становится — он НАЗВАН.
                    census.nested_unresolved.append(
                        (where, artifact, p, parent))
                    continue
                missing_paths.append(p)
            missing = tuple(missing_paths)
            reason, bare = _exemption(lines, node.lineno,
                                      _span_of(spans, node.lineno))
            if bare and reason is None and missing:
                census.marker_without_reason.append((rel, node.lineno))
            census.sites.append(Site(file=rel, line=node.lineno,
                                     artifact=artifact, missing=missing,
                                     declared=len(schema[artifact]),
                                     exempt_reason=reason))
    return census


def compare(census: Census, baseline: dict) -> list[str]:
    """Сверка с базой: что ВЫРОСЛО и что появилось НОВЫМ.

    Вынесено из храповика в прибор нарочно: сама сверка и есть то поведение,
    которому нужен положительный контроль (авария #832/#834/#837/#841 —
    объявленный раздел и необновлённая фикстура), а тест, читающий живую базу,
    воспроизвести аварию не может, не правя живую базу.

    База может только УМЕНЬШАТЬСЯ, поэтому убывание ключа и его исчезновение
    молчат: это починка, а не регресс.
    """
    measured = census.by_key()
    detail = census.missing_by_key()
    report: list[str] = []
    for key, now in sorted(measured.items()):
        was = baseline.get(key)
        if was is None:
            report.append(f"  НОВЫЙ {key}: {now}\n"
                          f"        не несёт: {detail[key]}")
        elif now > was:
            report.append(f"  ВЫРОС {key}: {was} \u2192 {now}\n"
                          f"        не несёт: {detail[key]}")
    return report
