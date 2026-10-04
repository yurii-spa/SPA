"""Перепись мутационных подмен: сколько из них считаются ПРИМЕНЁННЫМИ, не спросив о якоре.

Заказ **G96, п. 2** приказа владельца «Portfolio CIO» (хвост
[ADR-508](../../docs/decisions/ADR-508-the-second-binding-and-the-freshness-question-that-changed-address.md),
поставлен 2026-09-29), самый старый непогашенный пункт ряда на 2026-10-04.

## Вопрос заказа, дословно

«Мутационная батарея, применяющая подмену „по файлу“, лжёт о своём покрытии.
Замер цикла #727: из 16 подмен применились 7, остальные девять молча
пропущены — якорь встречался дважды, потому что рядом живёт проба-образец.
Перемерить класс: сколько батарей репозитория считают применённой подмену,
не проверив единственность якоря, и сколько из них печатают „не применена“
отдельным исходом, а не молчат. „Не применена“ обязана быть третьим исходом,
а не тишиной.»

## Почему вред тихий, и почему он ВЫВЕРНУТ

У текстовой подмены две осечки, и обе беззвучны:

| осечка | что делает `str.replace` | как читается отчёт батареи |
|---|---|---|
| якоря в файле **НЕТ** | возвращает текст без изменений | мутант «выжил» — ложная дыра покрытия |
| якорь встречается **ДВАЖДЫ** | меняет ОБА места | мутант шире заявленного, либо батарея его молча пропускает |

Опаснее первая, и опасна она вывернутостью: батарея мутаций — прибор,
который МЕРИТ силу тестов. Осечка подмены делает его вердикт **строже**
правды («тесты слабее, чем они есть»), и такой вердикт никто не оспаривает,
потому что он звучит самокритично. А число «применено N» при этом ложно: оно
есть размер СПИСКА, а не размер замера.

Это тот же класс, что `pyflakes` из `.claude/rules/deployment.md`: отсутствие
предмета дало ЧИСЛО, и число прошло за измерение. Разница в знаке — там
fail-OPEN зеленил, здесь fail-CLOSED краснит, — а дефект один: **не применено
не отличимо от применено**, то есть инвариант #17 нарушен у производителя числа.

## Предмет: что здесь считается мутационной подменой

Место в коде, где ТЕКСТОВАЯ подмена применяется к значению, происходящему от
ЧТЕНИЯ ФАЙЛА. Происхождение значения ищется ПОТОКОМ до неподвижной точки, а не
по имени переменной: `src = path.read_text()` → `mutant = src.replace(a, b)` →
`mutant.replace(c, d)` — все три звена одного предмета (память: «token in the
file is not a reader»).

Формы подмены — три, и они НЕ равны по возможностям:

| форма | может ли сама сказать «не применена» |
|---|---|
| `text.replace(old, new)` | нет: возвращает текст, а не счёт |
| `text.replace(old, new, 1)` | нет; ограничивает кратность, но НЕ ловит ноль |
| `re.sub(pat, repl, text)` | нет |
| `re.subn(pat, repl, text)` | **да**: возвращает счёт вторым членом |

Третья колонка — не украшение: `re.subn`, чей счёт выброшен (`[0]`), есть
отказ от уже имеющегося ответа, и он печатается отдельной причиной.

## Четыре исхода оси ЯКОРЯ (инв. #17)

| вердикт | что он значит | находка |
|---|---|---|
| `anchor_unique_checked` | кратность спрошена и сверена с ЕДИНИЦЕЙ — адресность доказана | нет |
| `anchor_bound_asserted` | счёт ПРОЧИТАН и громко сверен с объявленной границей (многоместная подмена по построению) | нет |
| `anchor_presence_checked` | ноль отличим, а кратность — нет (счёт выброшен либо сверен лишь с истинностью) | **да** |
| `anchor_unchecked` | не спрошено ничем: ноль и единица неразличимы | **да** |
| `anchor_unmeasured` | разобрать не вышло ⇒ сказано вслух с причиной | нет (громко) |

`presence` и `unique` разделены НАМЕРЕННО. Замер #727 — именно про `presence`:
якорь БЫЛ, проверка наличия прошла бы, а подмена всё равно применилась не туда,
потому что мест оказалось два. Слить их в одно «проверка есть» значило бы
объявить ту аварию предотвращённой.

`bound_asserted` отделён от `unique_checked` по той же причине в другую сторону.
`re.sub` многоместен ПО ПОСТРОЕНИЮ, и единица у него не критерий вовсе: верная
форма — прочитать счёт и громко сверить его с объявленной границей
(`assertGreater(cut, 0)`). Требовать от неё единицы значило бы объявить дефектом
правильный код, то есть сделать перепись источником ложных карточек.

## Вторая ось: ПРОИЗНОСИТСЯ ли «не применена»

Заказ спрашивает два разных вопроса, и второй не следует из первого: проверка
может БЫТЬ и при этом гаснуть молча (`continue`, `pass`, пустой `return`). Тогда
список подмен тихо усыхает, а печатаемое «применено N» снова есть длина списка.

| вердикт | что он значит | находка |
|---|---|---|
| `not_applied_spoken` | ветка отказа громкая: `raise` · `fail` · `exit` · свой вердикт · печать | нет |
| `not_applied_silent` | ветка отказа `continue`/`pass`/пустой `return` — список усох молча | **да** |
| `not_applied_no_branch` | проверки нет вовсе ⇒ вопрос не стои́т (он уже задан осью якоря) | нет |
| `not_applied_unmeasured` | ветку не разобрать | нет (громко) |

## Третья ось: РОД места — и почему перепись шире заказа

Заказ назвал население «батареи (`scripts/`, тесты с „mutation“ в имени)». Искать
по ЭТОМУ признаку значило бы мерить форму имени файла, а не предмет, — ровно
дефект G125 п. 4. Поэтому сеть ставится по ФОРМЕ КОДА на всё дерево, а род места
объявляется отдельной осью:

* `mutation_battery` — модуль и мутирует текст, и сам производит вердикт о
  мутанте (словарь «мутант/выжил/убит/survivor/killed» + прогон или сверка);
* `source_rewriter` — текст правится без вердикта о мутанте (установщик,
  генератор, нормализатор). Это СОСЕДНИЙ класс с тем же дефектом, и он
  печатается отдельно, а не подмешивается в ответ заказа.

Головной ответ заказа берётся по роду `mutation_battery`. Число по всему дереву
печатается рядом — чтобы «находок ноль» нельзя было получить сужением сети.

## Чего перепись НЕ докладывает

применилась ли подмена в КОНКРЕТНОМ прогоне (это вопрос прогона, не формы) ·
верность самого якоря · подмену, собранную в рантайме из частей · батарею,
живущую вне дерева (одноразовый скрипт цикла в `/tmp` сюда не попадает по
построению) · достаточность громкой ветки.

## Перепись ничего не чинит

`applied=False`. Найденное место — предмет своей карточки, а не прицепа
(инв. #16). Храповика нет НАМЕРЕННО: заказ велит сперва назвать население
числом, а база с ложными срабатываниями учит дописывать в неё (тот же выбор и
та же причина, что у литерального pid и у имени ветки).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - путь импорта
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

# ── ось ЯКОРЯ ────────────────────────────────────────────────────────────────
ANCHOR_UNIQUE = "anchor_unique_checked"
ANCHOR_BOUND = "anchor_bound_asserted"
ANCHOR_PRESENCE = "anchor_presence_checked"
ANCHOR_UNCHECKED = "anchor_unchecked"
ANCHOR_UNMEASURED = "anchor_unmeasured"
ANCHOR_VERDICTS = (ANCHOR_UNIQUE, ANCHOR_BOUND, ANCHOR_PRESENCE,
                   ANCHOR_UNCHECKED, ANCHOR_UNMEASURED)
#: находка — только там, где ноль неотличим от применения либо кратность слепа.
#: `bound_asserted` находкой НЕ является: многоместная подмена по построению
#: (`re.sub`) с громко сверенным счётом отвечает на вопрос заказа полностью, и
#: требовать от неё единицы значило бы объявить дефектом верную форму.
ANCHOR_FINDINGS = (ANCHOR_PRESENCE, ANCHOR_UNCHECKED)

# ── ось ТРЕТЬЕГО ИСХОДА ──────────────────────────────────────────────────────
SPOKEN = "not_applied_spoken"
SILENT = "not_applied_silent"
NO_BRANCH = "not_applied_no_branch"
SPEECH_UNMEASURED = "not_applied_unmeasured"
SPEECH_VERDICTS = (SPOKEN, SILENT, NO_BRANCH, SPEECH_UNMEASURED)

# ── ось РОДА ─────────────────────────────────────────────────────────────────
KIND_BATTERY = "mutation_battery"
KIND_REWRITER = "source_rewriter"
KINDS = (KIND_BATTERY, KIND_REWRITER)

ARTIFACT = "mutation_application_census.json"

DEFAULT_ROOTS: Tuple[str, ...] = (
    "scripts", "spa_core", "tests", "research", "studio_shell", "landing",
)

#: чтение файла: дверь, за которой лежит ТЕКСТ источника.
READ_ATTRS = frozenset({"read_text", "read"})
#: запись файла: доказательство, что мутант доехал до диска.
WRITE_ATTRS = frozenset({"write_text", "write", "writelines"})

#: словарь «вердикт о мутанте» — им род места отличается от простого правщика.
#: Сверка по СЛОВУ, а не по подстроке: `permutation` содержит `mutation`, и
#: подстрочное совпадение объявило бы батареей любой модуль, считающий
#: перестановки (ADR-333 — «проба не проходит подстрокой», и прибор не вправе
#: носить тот дефект, который ищет у других).
BATTERY_WORDS = (
    "mutant", "mutants", "survivor", "survived", "killed", "mutation",
    "мутант", "мутаци", "выжи", "убит",
)
#: прогон, производящий вердикт (батарея обязана чем-то судить).
RUN_WORDS = ("pytest", "subprocess", "unittest")

NOT_REPORTED = (
    "применилась ли подмена в конкретном прогоне (это вопрос прогона, не формы)",
    "верность самого якоря",
    "подмену, собранную в рантайме из частей",
    "батарею вне дерева (одноразовый скрипт цикла в /tmp)",
    "достаточность громкой ветки",
)


class Unmeasured(RuntimeError):
    """Предпосылка замера не обеспечена — исход третий, а не ноль."""


def _stamp(now: Optional[dt.datetime] = None) -> str:
    moment = now or dt.datetime.now(dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────────────────
# Форма подмены
# ─────────────────────────────────────────────────────────────────────────────

def substitution_form(node: ast.AST) -> Optional[dict]:
    """Описание подмены, если `node` — её вызов; иначе ``None``.

    Возвращает ``{"form", "subject", "anchor", "self_counts", "bounded"}``:
    ``subject`` — узел ТЕКСТА, ``anchor`` — узел ЯКОРЯ, ``self_counts`` —
    умеет ли сама форма сказать «не применена» (только ``re.subn``).
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "replace":
        # ОДНО ИМЯ — ДВА ОБЪЕКТА, и первая редакция прибора на этом ошиблась.
        # `str.replace` требует старое И новое ПОЗИЦИОННО; `.replace(tzinfo=…)`
        # — это `datetime.replace`, подмена ПОЛЯ, а не текста. Замер первой
        # редакции дал десять таких «мест» (`watchdog`, `self_heal`,
        # `uptime_monitor` …) — и все десять были `datetime`, доехавшие до
        # предмета потому, что их значение действительно происходит от чтения
        # файла. Признак строковой подмены — АРИТЕТ, а не имя метода.
        if len(node.args) < 2 and not any(isinstance(a, ast.Starred) for a in node.args):
            return None
        # Якорь, не читаемый из разбора (`t.replace(*pair)`), из населения НЕ
        # выбрасывается: выброшенное место молча стало бы «батарей с дефектом
        # меньше», то есть ровно той подстановкой, против которой прибор и
        # написан. Оно входит в население с третьим исходом.
        unreadable = None
        anchor = None
        if not node.args or isinstance(node.args[0], ast.Starred):
            unreadable = ("якорь распакован из последовательности (`*args`) — "
                          "его значение в разборе отсутствует")
        else:
            anchor = node.args[0]
        return {
            "form": "str.replace",
            "subject": func.value,
            "anchor": anchor,
            "anchor_unreadable": unreadable,
            "self_counts": False,
            # `replace(a, b, 1)` ограничивает КРАТНОСТЬ и не ловит ноль.
            "bounded": len(node.args) > 2,
        }
    if (isinstance(func, ast.Attribute) and func.attr in ("sub", "subn")
            and isinstance(func.value, ast.Name) and func.value.id == "re"):
        if len(node.args) < 3:
            # Текст передан по имени (`re.sub(p, r, string=t)`) — САМО
            # членство в предмете не измерено, и выдать это за «не наш случай»
            # нельзя. Такие места собираются отдельным перечнем с причиной.
            return {
                "form": f"re.{func.attr}",
                "subject": None,
                "anchor": node.args[0] if node.args else None,
                "anchor_unreadable": "текст передан не позиционно — членство в "
                                     "предмете НЕ ИЗМЕРЕНО",
                "self_counts": func.attr == "subn",
                "bounded": False,
            }
        return {
            "form": f"re.{func.attr}",
            "subject": node.args[2],
            "anchor": node.args[0],
            "anchor_unreadable": None,
            "self_counts": func.attr == "subn",
            "bounded": len(node.args) > 3,
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Происхождение значения: ПОТОКОМ до неподвижной точки
# ─────────────────────────────────────────────────────────────────────────────

class _Origins:
    """Имена области, чьё значение происходит от чтения файла или от подмены."""

    def __init__(self) -> None:
        self.from_read: set = set()
        self.from_sub: set = set()

    def derives_read(self, node: ast.AST) -> bool:
        """Значение `node` происходит от чтения файла (или от подмены над ним)?"""
        if isinstance(node, ast.Name):
            return node.id in self.from_read or node.id in self.from_sub
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in READ_ATTRS:
                return True
            form = substitution_form(node)
            if form is not None:
                return self.derives_read(form["subject"])
            # `str.join`, `str.strip`, `textwrap.dedent(...)` и прочие
            # преобразования текста наследуют происхождение от аргументов и от
            # получателя: цепочка `path.read_text().strip().replace(...)` — одно
            # и то же значение, и терять его на первом же `.strip()` значило бы
            # объявить самую обычную форму отсутствующей.
            parts = list(node.args)
            if isinstance(node.func, ast.Attribute):
                parts.append(node.func.value)
            return any(self.derives_read(p) for p in parts)
        if isinstance(node, ast.Attribute):
            return self.derives_read(node.value)
        if isinstance(node, ast.Subscript):
            return self.derives_read(node.value)
        if isinstance(node, ast.BinOp):
            return self.derives_read(node.left) or self.derives_read(node.right)
        if isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            return any(self.derives_read(c) for c in ast.iter_child_nodes(node))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(self.derives_read(e) for e in node.elts)
        if isinstance(node, ast.Starred):
            return self.derives_read(node.value)
        if isinstance(node, ast.IfExp):
            return self.derives_read(node.body) or self.derives_read(node.orelse)
        return False

    def learn(self, body: Sequence[ast.AST], rounds: int = 4) -> None:
        """Пройти присваивания до неподвижной точки (имя может родиться позже)."""
        for _ in range(rounds):
            before = (len(self.from_read), len(self.from_sub))
            for node in body:
                for target, value in _assignments(node):
                    form = substitution_form(value)
                    if form is not None and self.derives_read(form["subject"]):
                        self.from_sub.add(target)
                    elif self.derives_read(value):
                        self.from_read.add(target)
            if (len(self.from_read), len(self.from_sub)) == before:
                return


def _assignments(node: ast.AST):
    """Пары «имя, значение» из всех форм присваивания внутри `node`."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                for name in _bound_names(tgt):
                    yield name, sub.value
        elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)) and sub.value is not None:
            for name in _bound_names(sub.target):
                yield name, sub.value
        elif isinstance(sub, ast.NamedExpr):
            for name in _bound_names(sub.target):
                yield name, sub.value
        elif isinstance(sub, ast.withitem) and sub.optional_vars is not None:
            for name in _bound_names(sub.optional_vars):
                yield name, sub.context_expr


def _bound_names(target: ast.AST) -> List[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: List[str] = []
        for elt in target.elts:
            out += _bound_names(elt)
        return out
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Области: каждый узел принадлежит РОВНО ОДНОЙ (внутренней) области
# ─────────────────────────────────────────────────────────────────────────────

def _scopes(tree: ast.Module) -> List[Tuple[str, ast.AST]]:
    """Список областей (имя, узел): модуль + каждая функция, от внутренних к внешним."""
    out: List[Tuple[str, ast.AST]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                out.append((name, child))
                walk(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    out.append(("<module>", tree))
    return out


def _owning_scope(node: ast.AST, scopes: Sequence[Tuple[str, ast.AST]]) -> Tuple[str, ast.AST]:
    """Внутренняя область, которой принадлежит `node` (список уже упорядочен)."""
    for name, scope in scopes:
        if any(n is node for n in ast.walk(scope)):
            return name, scope
    return "<module>", scopes[-1][1]


# ─────────────────────────────────────────────────────────────────────────────
# Ось якоря: спрошена ли применённость, и сверена ли КРАТНОСТЬ
# ─────────────────────────────────────────────────────────────────────────────

def _same(a: ast.AST, b: ast.AST) -> bool:
    """Два выражения — один и тот же якорь? Сверка по дереву разбора, не по тексту."""
    try:
        return ast.dump(a) == ast.dump(b)
    except Exception:  # pragma: no cover - нестандартный узел
        return False


def _parents(scope: ast.AST) -> Dict[int, ast.AST]:
    """Карта «узел → родитель» по id: нужна, чтобы дойти от счёта до его ВЕТКИ."""
    out: Dict[int, ast.AST] = {}
    for node in ast.walk(scope):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def _is_judging_call(node: ast.AST) -> bool:
    """Вызов, чей отказ громкий сам по себе: `assert*`, `fail*`, `require*`."""
    if not isinstance(node, ast.Call):
        return False
    name = node.func.attr if isinstance(node.func, ast.Attribute) else (
        node.func.id if isinstance(node.func, ast.Name) else "")
    low = name.lower()
    return low.startswith("assert") or "fail" in low or low.startswith("require")


def count_sites(scope: ast.AST, form: dict, site: ast.AST) -> Tuple[List[ast.AST], set]:
    """Узлы, дающие СЧЁТ применений ИМЕННО этого якоря, и имена, его несущие.

    Счёт приходит двумя дорогами: спрошенный явно (`text.count(anchor)`) и
    отданный самой формой (`re.subn` возвращает его вторым членом). Вторую
    дорогу нельзя пропустить: отказ от уже готового ответа и отсутствие ответа
    выглядят в коде по-разному, но стоя́т одного.
    """
    anchor = form["anchor"]
    nodes: List[ast.AST] = []
    names: set = set()
    for node in ast.walk(scope):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "count" and node.args
                and _same(node.args[0], anchor)):
            nodes.append(node)
    if form["self_counts"]:
        for node in ast.walk(scope):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if value is None or not any(n is site for n in ast.walk(value)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for tgt in targets:
                    if isinstance(tgt, (ast.Tuple, ast.List)) and len(tgt.elts) == 2:
                        second = tgt.elts[1]
                        nodes.append(second)
                        names |= set(_bound_names(second))
            if isinstance(node, ast.Subscript) and node.value is site:
                index = node.slice
                if isinstance(index, ast.Constant) and index.value == 1:
                    nodes.append(node)
    # Имя, в которое счёт переложили, несёт его дальше — иначе `office_cut = k1`
    # обрывал бы дорогу к громкому `assertGreater(office_cut, 0)`, и ЕДИНСТВЕННЫЙ
    # настоящий читатель счёта был бы объявлен отсутствующим (та же ошибка, что
    # ADR-550 нашёл у привязок конституции).
    for _ in range(4):
        before = len(names)
        for name, value in _assignments(scope):
            if any(n is value for n in nodes):
                names.add(name)
            elif isinstance(value, ast.Name) and value.id in names:
                names.add(name)
            elif any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(value)):
                names.add(name)
        if len(names) == before:
            break
    return nodes, names


def count_readers(scope: ast.AST, nodes: Sequence[ast.AST], names: set,
                  parents: Dict[int, ast.AST]) -> List[dict]:
    """Чем счёт ПРОЧИТАН: с единицей он сверен, с иной границей, и громко ли."""
    carriers = [n for n in ast.walk(scope)
                if any(n is c for c in nodes)
                or (isinstance(n, ast.Name) and n.id in names)]
    readers: List[dict] = []
    for carrier in carriers:
        node, hops = carrier, 0
        while node is not None and hops < 6:
            parent = parents.get(id(node))
            if parent is None:
                break
            if isinstance(parent, ast.Compare):
                operands = [parent.left] + list(parent.comparators)
                readers.append({
                    "against_one": _has_literal(operands, 1),
                    # Сверка с НУЛЁМ отличает только «применена / нет». Зачесть
                    # её за границу кратности значило бы выдать `assert n > 0`
                    # за доказательство адресности — а это ровно авария #727,
                    # где якорь БЫЛ, и мест оказалось два.
                    "zero_only": _has_literal(operands, 0),
                    "loud": _loudness(parent, parents)})
                break
            if isinstance(parent, ast.Assert):
                # `assert n` — проверка ИСТИННОСТИ: ноль отличим, кратность нет.
                readers.append({"against_one": False, "zero_only": True,
                                "loud": True})
                break
            if _is_judging_call(parent):
                readers.append({"against_one": _has_literal(parent.args, 1),
                                "zero_only": _has_literal(parent.args, 0)
                                or len(parent.args) <= 1,
                                "loud": True})
                break
            if isinstance(parent, ast.If) and parent.test is node:
                readers.append({"against_one": False, "zero_only": True,
                                "loud": _branch_is_loud(parent.body)})
                break
            node, hops = parent, hops + 1
    return readers


def _has_literal(nodes: Sequence[ast.AST], value: int) -> bool:
    """Среди операндов есть ИМЕННО этот числовой литерал (а не похожий)."""
    return any(isinstance(n, ast.Constant) and n.value == value
               and not isinstance(n.value, bool) for n in nodes)


def _loudness(node: ast.AST, parents: Dict[int, ast.AST]) -> Optional[bool]:
    """Громкость ВЕТКИ, которой распоряжается это сравнение."""
    cur, hops = node, 0
    while cur is not None and hops < 6:
        parent = parents.get(id(cur))
        if parent is None:
            return None
        if isinstance(parent, ast.Assert) or _is_judging_call(parent):
            return True
        if isinstance(parent, ast.If):
            return _branch_is_loud(parent.body)
        if isinstance(parent, ast.IfExp):
            return None
        cur, hops = parent, hops + 1
    return None


def presence_checks(scope: ast.AST, form: dict,
                    parents: Dict[int, ast.AST]) -> List[dict]:
    """Вопросы о НАЛИЧИИ якоря, не дающие счёта: `in` и «текст изменился».

    Громкость возвращается ВМЕСТЕ с вопросом: ось речи спрашивает «произносится
    ли „не применена“», и проверка наличия отвечает на это ровно так же, как
    проверка кратности. Считать громкой только вторую значило бы объявить
    безмолвным `assert "<якорь>" in text` — самую громкую форму из возможных.
    """
    anchor, subject = form["anchor"], form["subject"]
    out: List[dict] = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Compare):
            continue
        what = None
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops) and _same(node.left, anchor):
            what = "`якорь in текст`"
        else:
            operands = [node.left] + list(node.comparators)
            if (any(substitution_form(o) is not None for o in operands)
                    and any(_same(o, subject) for o in operands)):
                what = "«текст изменился»"
        if what is not None:
            out.append({"what": what, "loud": _loudness(node, parents)})
    return out


def _branch_is_loud(body: Sequence[ast.AST]) -> Optional[bool]:
    """Ветка отказа говорит вслух? ``None`` — разобрать не вышло."""
    if not body:
        return None
    saw_quiet = False
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Raise, ast.Assert)):
                return True
            # `return <значение>` — это и есть «третий исход» заказа: ветка
            # отдаёт СВОЙ вердикт («подмена не применена»), а не продолжает
            # молча. Так устроен `mutation_gate._apply_mutant`, и считать его
            # неразобранным значило бы не увидеть ЕДИНСТВЕННЫЙ в дереве
            # образец верной формы.
            if isinstance(node, ast.Return) and node.value is not None:
                return True
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                    node.func.id if isinstance(node.func, ast.Name) else "")
                if _is_loud_call(name):
                    return True
            if isinstance(node, (ast.Continue, ast.Pass)):
                saw_quiet = True
            if isinstance(node, ast.Return) and node.value is None:
                saw_quiet = True
    if saw_quiet:
        return False
    return None


#: Громкий вызов — ТОЧНОЕ имя либо префикс `assert`/`fail`. Подстрока здесь
#: врала бы в обе стороны: `add` совпадает с `addCleanup`, `warn` — с
#: `warned_at`, и ветка, ничего не сказавшая, объявлялась бы громкой.
_LOUD_CALL_NAMES = frozenset({
    "print", "append", "add", "exit", "error", "warn", "warning", "critical",
    "log", "exception", "insert", "extend",
})


def _is_loud_call(name: str) -> bool:
    low = name.lower()
    return (low in _LOUD_CALL_NAMES or low.startswith("assert")
            or low.startswith("fail") or low.startswith("raise"))


def classify_anchor(scope: ast.AST, form: dict, site: ast.AST) -> Tuple[str, str, List[dict]]:
    """Вердикт оси якоря, причина (всегда названная) и читатели счёта."""
    if form.get("anchor_unreadable"):
        return ANCHOR_UNMEASURED, str(form["anchor_unreadable"]), []
    parents = _parents(scope)
    nodes, names = count_sites(scope, form, site)
    counted = count_readers(scope, nodes, names, parents)
    presence = presence_checks(scope, form, parents)
    # Ось ЯКОРЯ судит только по читателям СЧЁТА: громкая проверка НАЛИЧИЯ
    # (`assert "<якорь>" in text`) о кратности не говорит ничего, и зачесть её
    # за границу значило бы выдать «ноль отличим» за «кратность доказана».
    # Громкость проверки наличия идёт в ось РЕЧИ — там она отвечает по делу.
    readers = counted + [{"against_one": False, "zero_only": True, "loud": c["loud"]}
                         for c in presence]
    if any(r["against_one"] for r in counted):
        return (ANCHOR_UNIQUE, "кратность якоря спрошена и сверена с ЕДИНИЦЕЙ — "
                "адресность подмены доказана", readers)
    if any(r["loud"] and not r["zero_only"] for r in counted):
        return (ANCHOR_BOUND, "счёт применений ПРОЧИТАН и громко сверен с объявленной "
                "границей — многоместная подмена по построению, ноль отличим", readers)
    if counted:
        return (ANCHOR_PRESENCE, "счёт применений спрошен, но сверен лишь с НУЛЁМ "
                "(или с истинностью): ноль отличим, ДВА от одного — нет", readers)
    if nodes:
        return (ANCHOR_UNCHECKED, "счёт применений спрошен и НЕ прочитан ни одной "
                "веткой — вопрос задан, ответ выброшен, то есть не спрошено ничего",
                readers)
    if presence:
        names_seen = sorted({c["what"] for c in presence})
        return (ANCHOR_PRESENCE,
                f"спрошено лишь наличие ({', '.join(names_seen)}) — два места пройдут",
                readers)
    why = "о применённости не спрошено ничего: не применённая подмена неотличима от применённой"
    if form["bounded"]:
        why += "; кратность ограничена аргументом, но ноль этим НЕ ловится"
    if form["self_counts"]:
        why += "; форма `re.subn` счёт ОТДАЁТ, и он выброшен — отказ от готового ответа"
    return ANCHOR_UNCHECKED, why, readers


# ─────────────────────────────────────────────────────────────────────────────
# Ось речи: громкая ли ветка «не применена»
# ─────────────────────────────────────────────────────────────────────────────

def classify_speech(anchor_verdict: str, readers: Sequence[dict]) -> Tuple[str, str]:
    """Произносится ли «не применена» отдельным исходом."""
    if anchor_verdict == ANCHOR_UNMEASURED:
        return (SPEECH_UNMEASURED,
                "якорь из разбора не читается — о его ветке НЕ СКАЗАНО НИЧЕГО")
    if anchor_verdict == ANCHOR_UNCHECKED:
        return NO_BRANCH, "проверки нет вовсе — вопрос уже задан осью якоря"
    judged = [r["loud"] for r in readers if r["loud"] is not None]
    if not judged:
        return (SPEECH_UNMEASURED,
                "применённость спрошена, а ветку её отказа разобрать не вышло")
    if any(judged):
        return SPOKEN, "ветка отказа громкая: отказ · печать · свой вердикт"
    return (SILENT, "ветка отказа тихая (`continue`/`pass`/пустой `return`) — "
            "список подмен усох молча, а печатаемое «применено N» осталось длиной списка")


# ─────────────────────────────────────────────────────────────────────────────
# Род места
# ─────────────────────────────────────────────────────────────────────────────

def _has_word(low: str, word: str) -> bool:
    """Слово встречается НЕ внутри другого слова (слева буквы быть не должно)."""
    return re.search(r"(?<![0-9A-Za-z_\u0400-\u04FF])" + re.escape(word), low) is not None


def classify_kind(source: str, path: str) -> Tuple[str, str]:
    """Батарея мутаций или просто правщик источника."""
    low = source.lower()
    words = sorted({w for w in BATTERY_WORDS if _has_word(low, w)})
    runs = sorted({w for w in RUN_WORDS if _has_word(low, w)})
    if words and runs:
        return KIND_BATTERY, f"словарь мутанта ({', '.join(words[:3])}) + прогон ({', '.join(runs)})"
    missing = "словаря мутанта" if not words else "прогона-судьи"
    return KIND_REWRITER, f"вердикта о мутанте нет: не найдено {missing}"


def _writes_file(scope: ast.AST) -> bool:
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in WRITE_ATTRS:
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Замер
# ─────────────────────────────────────────────────────────────────────────────

def census_file(path: Path, source: str, rel: str) -> Tuple[List[dict], List[dict]]:
    """Подмены одного файла с вердиктами по трём осям + места с НЕИЗМЕРИМЫМ членством."""
    tree = ast.parse(source)
    scopes = _scopes(tree)
    rows: List[dict] = []
    undecidable: List[dict] = []
    for node in ast.walk(tree):
        form = substitution_form(node)
        if form is None:
            continue
        scope_name, scope = _owning_scope(node, scopes)
        if form["subject"] is None:
            undecidable.append({
                "file": rel, "line": getattr(node, "lineno", 0),
                "col": getattr(node, "col_offset", 0), "scope": scope_name,
                "form": form["form"], "why": str(form.get("anchor_unreadable"))})
            continue
        origins = _Origins()
        origins.learn([scope])
        if not origins.derives_read(form["subject"]):
            continue
        anchor_verdict, anchor_why, readers = classify_anchor(scope, form, node)
        speech_verdict, speech_why = classify_speech(anchor_verdict, readers)
        kind, kind_why = classify_kind(source, rel)
        rows.append({
            "file": rel,
            # Столбец ВМЕСТЕ со строкой: `t.replace(a, b).replace(c, d)` — две
            # РАЗНЫЕ подмены на одной строке, и без столбца они выглядели бы
            # одной записью, напечатанной дважды.
            "line": getattr(node, "lineno", 0),
            "col": getattr(node, "col_offset", 0),
            # Конец выражения — ВТОРАЯ половина адреса, и без неё две подмены
            # цепочки `t.replace(a, b).replace(c, d)` неразличимы: у внешнего и
            # внутреннего вызова НАЧАЛО одно и то же (оба начинаются с `t`).
            "end_col": getattr(node, "end_col_offset", 0),
            "scope": scope_name,
            "form": form["form"],
            "kind": kind,
            "kind_why": kind_why,
            "anchor": anchor_verdict,
            "anchor_why": anchor_why,
            "speech": speech_verdict,
            "speech_why": speech_why,
            "reaches_disk": _writes_file(scope),
        })
    return rows, undecidable


def discover(root: Path, roots: Sequence[str] = DEFAULT_ROOTS) -> dict:
    """Все подмены дерева + честный счёт нечитаемых файлов (третий исход)."""
    files: List[Path] = []
    seen_roots: List[str] = []
    for name in roots:
        folder = root / name
        if not folder.is_dir():
            continue
        seen_roots.append(name)
        files += sorted(folder.rglob("*.py"))
    if not seen_roots:
        raise Unmeasured(
            f"ни одного объявленного каталога нет в дереве {root} — это «смотрели "
            f"не в то дерево», а не отсутствие класса (искали: {', '.join(roots)})")
    rows: List[dict] = []
    undecidable: List[dict] = []
    unreadable: List[dict] = []
    for path in files:
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append({"file": rel, "why": f"не прочитан: {exc.__class__.__name__}"})
            continue
        try:
            file_rows, file_undecidable = census_file(path, source, rel)
            rows += file_rows
            undecidable += file_undecidable
        except SyntaxError as exc:
            unreadable.append({"file": rel, "why": f"не разобран: {exc.__class__.__name__}"})
    return {"rows": rows, "undecidable": undecidable, "unreadable": unreadable,
            "files_scanned": len(files), "roots_present": seen_roots}


def is_finding(row: dict) -> bool:
    """Место — находка? Правило ФОРМО-ЗАВИСИМО, и это не послабление.

    `re.sub`/`re.subn` многоместны ПО ПОСТРОЕНИЮ: единица у них не критерий
    вовсе, и доказанного «ноль отличим» для ответа заказу достаточно. У
    адресной `str.replace` того же недостаточно — авария #727 случилась именно
    там, где якорь БЫЛ, а мест оказалось два.
    """
    if row["anchor"] == ANCHOR_UNCHECKED:
        return True
    if row["speech"] == SILENT:
        return True
    if row["anchor"] == ANCHOR_PRESENCE:
        return row["form"] == "str.replace"
    return False


def summarise(rows: Sequence[dict]) -> dict:
    anchor = {v: 0 for v in ANCHOR_VERDICTS}
    speech = {v: 0 for v in SPEECH_VERDICTS}
    kind = {k: 0 for k in KINDS}
    forms: Dict[str, int] = {}
    for row in rows:
        anchor[row["anchor"]] = anchor.get(row["anchor"], 0) + 1
        speech[row["speech"]] = speech.get(row["speech"], 0) + 1
        kind[row["kind"]] = kind.get(row["kind"], 0) + 1
        forms[row["form"]] = forms.get(row["form"], 0) + 1
    return {"anchor": anchor, "speech": speech, "kind": kind, "forms": forms}


def measure(root: Optional[Path] = None, *, roots: Sequence[str] = DEFAULT_ROOTS,
            now: Optional[dt.datetime] = None) -> dict:
    """Полный замер: население по форме кода + три оси вердиктов."""
    tree = Path(root) if root else _REPO_ROOT
    found = discover(tree, roots)
    rows = found["rows"]
    batteries = [r for r in rows if r["kind"] == KIND_BATTERY]
    for row in rows:
        row["finding"] = is_finding(row)
    findings = [r for r in batteries if r["finding"]]
    def _n(rows_: Sequence[dict], **kw) -> int:
        return sum(1 for r in rows_ if all(r[k] == v for k, v in kw.items()))

    answer = (
        f"подмен по форме кода {len(rows)} в {len({r['file'] for r in rows})} файл(ах); "
        f"род «батарея мутаций» — {len(batteries)} мест(о): применённость ДОКАЗАНА у "
        f"{_n(batteries, anchor=ANCHOR_UNIQUE) + _n(batteries, anchor=ANCHOR_BOUND)} "
        f"(сверка с единицей {_n(batteries, anchor=ANCHOR_UNIQUE)} · громкая граница "
        f"{_n(batteries, anchor=ANCHOR_BOUND)}), НЕ спрошена вовсе у "
        f"{_n(batteries, anchor=ANCHOR_UNCHECKED)}, спрошена слепо к кратности у "
        f"{_n(batteries, anchor=ANCHOR_PRESENCE)}; «не применена» МОЛЧИТ у "
        f"{_n(batteries, speech=SILENT)}"
    )
    return {
        "status": "OK",
        "generated_at": _stamp(now),
        "order": "G96 п. 2 (хвост ADR-508)",
        "applied": False,
        "tree": str(tree),
        "roots_declared": list(roots),
        "roots_present": found["roots_present"],
        "files_scanned": found["files_scanned"],
        "unreadable": found["unreadable"],
        "undecidable": found["undecidable"],
        "sites": len(rows),
        "files_with_sites": sorted({r["file"] for r in rows}),
        "counts": summarise(rows),
        "counts_batteries": summarise(batteries),
        "answer": answer,
        "rows": rows,
        "findings": [{k: r[k] for k in ("file", "line", "col", "end_col", "scope",
                                        "form", "anchor", "anchor_why", "speech",
                                        "speech_why")}
                     for r in findings],
        "not_reported": list(NOT_REPORTED),
    }


def run(root: "str | Path" = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True,
        now: Optional[dt.datetime] = None, **kw) -> dict:
    """Один замер для ступени моста (`findings_bridge.CENSUS_STAGE`).

    Такта у ступени НЕТ намеренно: замер есть разбор дерева в одном процессе
    (14 с на 8,5 тыс. файлов), и платить за него такт значило бы отвечать
    вчерашним числом там, где сегодняшнее стои́т секунд. Предмет при этом
    меняется КАЖДЫМ циклом, который пишет батарею, — то есть почти каждым.
    """
    base = Path(root)
    source = Path(data_dir) if data_dir is not None else base / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    try:
        doc = measure(base, now=now, **kw)
    except Unmeasured as exc:
        doc = {"status": "UNMEASURED", "reason": str(exc), "generated_at": _stamp(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 8) -> list:
    if str(doc.get("status")) != "OK":
        return [f"применённость мутационной подмены: НЕ ИЗМЕРЕНО — "
                f"{doc.get('reason', 'причина не названа')}",
                "  про батареи, лгущие о своём покрытии, НЕ СКАЗАНО НИЧЕГО — "
                "выдать это за «батарей с дефектом ноль» нельзя"]
    counts = observed(doc, "counts", kind=dict)
    battery_counts = observed(doc, "counts_batteries", kind=dict)
    if counts is None or battery_counts is None:
        absent = "counts" if counts is None else "counts_batteries"
        return [f"применённость мутационной подмены: НЕ ИЗМЕРЕНО — в замере нет поля {absent!r}",
                "  про батареи, лгущие о своём покрытии, НЕ СКАЗАНО НИЧЕГО"]
    anchor = observed(counts, "anchor", kind=dict) or {}
    speech = observed(battery_counts, "speech", kind=dict) or {}
    kind = observed(counts, "kind", kind=dict) or {}
    lines = [
        f"применённость мутационной подмены (заказ {doc.get('order')}): "
        f"мест {doc.get('sites')} · файлов с местами {len(doc.get('files_with_sites') or [])} "
        f"· НАХОДОК {len(doc.get('findings') or [])}",
        "  ОТВЕТ заказа: " + str(doc.get("answer")),
        "  ось якоря (всё дерево): " + " · ".join(f"{v} {anchor.get(v, 0)}" for v in ANCHOR_VERDICTS),
        "  ось речи (только батареи): " + " · ".join(f"{v} {speech.get(v, 0)}" for v in SPEECH_VERDICTS),
        "  род места: " + " · ".join(f"{k} {kind.get(k, 0)}" for k in KINDS)
        + " (сеть ставилась по ФОРМЕ КОДА на всё дерево, а не по имени файла — иначе мерили бы форму имени)",
    ]
    undecidable = doc.get("undecidable") or []
    if undecidable:
        lines.append(f"  НЕ ИЗМЕРЕНО членство у {len(undecidable)} мест(а): "
                     + " · ".join(f"{u['file']}:{u['line']} ({u['why']})"
                                  for u in undecidable[:3]))
    unreadable = doc.get("unreadable") or []
    if unreadable:
        lines.append(f"  НЕ ИЗМЕРЕНО у {len(unreadable)} файл(ов): "
                     + " · ".join(f"{u['file']} ({u['why']})" for u in unreadable[:3]))
    shown = 0
    for row in doc.get("findings") or []:
        if shown >= max_rows:
            break
        lines.append(f"  [{row['anchor']}/{row['speech']}] "
                     f"{row['file']}:{row['line']}:{row['col']}-{row['end_col']} "
                     f"({row['scope']}, {row['form']}) — {row['anchor_why']}")
        shown += 1
    total = len(doc.get("findings") or [])
    if total > max_rows:
        lines.append(f"  … ещё {total - max_rows} находок(и) того же вида (полный перечень — `--json`)")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc.get("not_reported") or []))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False) и батарей не правит")
    return lines


def format_report(doc: dict, max_rows: int = 8) -> list:
    return ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="перепись мутационных подмен: спрошена ли кратность якоря")
    parser.add_argument("--root", default=None, help="корень дерева (по умолчанию — своё)")
    parser.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS),
                        help="каталоги, по которым ставится сеть")
    parser.add_argument("--out", default=None, help="куда записать артефакт")
    parser.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = parser.parse_args(argv)
    try:
        doc = measure(Path(args.root) if args.root else None, roots=tuple(args.roots))
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        print("  про применённость мутационной подмены НЕ СКАЗАНО НИЧЕГО")
        return 2
    if args.out:
        atomic_save(doc, str(args.out))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc):
            print(line)
    return 1 if doc.get("findings") else 0


if __name__ == "__main__":
    raise SystemExit(main())
