"""Сколько привязок конституции держится ПРОЗОЙ — и у скольких из них есть второй читатель.

Заказ **G94 п. 3** приказа владельца «Portfolio CIO» (хвост ADR-506), дословно:

    «Привязка живёт прозой у ВСЕХ десяти. Перенос в поле (`s49_criterion` у
     артефакта манифеста, а не только у пробы) снял бы разбор заметок целиком —
     но объявлять поле механически нельзя (урок G86 п. 4): сначала замер,
     сколько привязок конституции вообще держится на прозе и у скольких из них
     есть второй читатель.»

Прибор отвечает ровно на этот вопрос и ничего не предписывает.

## Что здесь называется ПРИВЯЗКОЙ

Привязка — утверждение конституции (``architecture/manifest.json``) о том, что
данная запись **управляется названным текстом системы**: решением (ADR),
критерием приказа владельца (``§49``), инвариантом, path-правилом,
заказом ряда G-nn. Отдельно считается ССЫЛКА НА ПРОИСХОЖДЕНИЕ (номер цикла) —
она ничем не управляет, и складывать её с управляющими значило бы выдать
историю за правило.

Привязка бывает в ПОЛЕ (``governed_by``: машина читает ключ) и в ПРОЗЕ
(``notes``: машина читает свободный текст — то есть не читает). Проза вердиктом
не становится (ADR-504), и **у двух половин конституции разные возможности**:

* у **агента** поле ``governed_by`` ЕСТЬ. Привязка в прозе здесь не нехватка
  поля, а его ОБХОД: читатель поля такую запись не видит СЕГОДНЯ;
* у **артефакта** поля нет НИ ОДНОГО. Проза здесь — единственное доступное
  место, и цена привязки — объявить поле, а не переписать заметку.

Слить эти два положения в одно слово «проза» значило бы повторить дефект
ADR-506: десять одинаковых ``НЕ ИЗМЕРЕНО`` читались как десять одинаковых дыр,
а чинились разным.

## Четыре исхода у места привязки

``field``
    привязка в поле, и проза её НЕ повторяет. Единственный здоровый исход.
``both``
    привязка и в поле, и в прозе — ВТОРАЯ КОПИЯ правила (ADR-220): две копии
    расходятся молча, и какая из них в силе, конституция не говорит.
``field_bypassed``
    поле у этой половины ЕСТЬ и пусто, а проза привязку называет. Читатель поля
    слеп к записи уже сегодня — это не будущая цена, а текущая потеря.
``no_field_for_kind``
    поля для этого рода привязки у этой половины НЕТ ВОВСЕ. Проза — не
    небрежность автора, а единственное доступное место.

## Вторая ось: ЧИТАТЕЛИ

«Держится на прозе» — половина ответа. Вторая половина: **читает ли эту прозу
хоть кто-нибудь как привязку.** Прибор перебирает модули дерева (вне тестов),
которые (а) называют литералом адрес конституции и (б) читают ключ ``notes``
литералом, и у каждого спрашивает, что он с прочитанным ДЕЛАЕТ:

``binding_parser``
    до значения заметки доезжает литерал, несущий опознавательный токен рода
    (``§49``, ``ADR-``, ``инв.``…). Только это считается читателем привязки.
``text_consumer``
    ни один опознавательный литерал до значения не доехал: модуль берёт прозу
    как ТЕКСТ (поиск, склейка, сличение двух снимков). Это ИЗМЕРЕННОЕ
    отсутствие разбора — осмотрены все вызовы модуля, — а то, что со значением
    происходило помимо разбора (склейка · укладка в контейнер · передача
    ввезённому коду), названо рядом ОГРАНИЧЕНИЕМ, не вердиктом.
``unmeasured``
    ЕДИНСТВЕННЫЙ третий исход этой оси, и причин у него три: исходник не
    прочитан, не разобран, либо образец собран ВЫЧИСЛЕНИЕМ — токена в нём
    назвать нечем. Ни «читатель есть», ни «читателя нет» о таком модуле не
    сказано.

**К ПОЛЮ прикладывается ДРУГАЯ мерка, и это не бедность замера, а его
предмет.** Прозе нужен РАЗБОР — читатель обязан пронести до значения литерал с
токеном рода. Полю довольно КЛЮЧА: прочитал ``governed_by`` — прочитал
привязку. Спросить у поля «а есть ли у него образец?» значило бы задать ему
чужой вопрос и получить ноль читателей там, где их несколько. Асимметрия двух
мерок И ЕСТЬ цена прозы, посчитанная в читателях.

## Как значение трассируется до литерала (и почему не грепом)

Присутствие токена в файле читателем НЕ является: докстрока прибора §49
упоминает ADR-504 и ADR-505, и грep объявил бы её читателем привязки ``adr``,
которой она не читает. Поэтому связь измеряется **потоком значения до
неподвижной точки внутри модуля**:

1. чтение ``notes`` литералом даёт СЕМЯ — пару «функция × имя»;
2. присваивание, чей правый край упоминает семя, делает цель семенем
   (``tail = note[pos:pos + 160]``);
3. ``for x in <семя>`` делает ``x`` семенем;
4. вызов функции ТОГО ЖЕ модуля с семенем в аргументе делает соответствующий
   параметр семенем (``_iter_mentions(note)`` → ``re.finditer("§49", note)``
   внутри помощника — без этого шага единственный настоящий читатель системы
   был бы объявлен отсутствующим);
5. литерал «доезжает», если он — образец ``re.<метод>(lit, семя)``, образец
   предкомпилированной константы модуля, применённой к семени, аргумент
   строкового метода семени либо левый операнд ``lit in семя``.

Шага «наружу из модуля» нет намеренно: что делает с прозой ЧУЖОЙ модуль,
названо слепотой (ниже), а не досмотрено наугад.

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Верность привязки.** Что ADR-549 действительно управляет артефактом, прозой
  утверждается, а не доказывается; верность проверяет контроль пробы в обе
  стороны (`.claude/rules/acceptance.md`, п. 3), не этот прибор.
* **Верность разбора у читателя.** «Литерал с токеном доезжает до значения»
  означает претензию модуля на разбор рода, а не её правильность.
* **Читателя через границу модуля.** Второй хоп (чужой модуль читает поле,
  извлечённое третьим) не измеряется: ``portal_render`` печатает
  ``governed_by`` из выжимки, а не из конституции, и считать его читателем
  конституции значило бы считать читателем всякого, кто держит копию.
* **Привязки вне конституции.** Докстроки кода полны ссылок на ADR; они не
  манифест, и население прибора ими не растёт.
* **Что делать.** Объявлять поле или нет — решение (урок G86 п. 4); прибор
  называет население и цену, а не исход решения.

## Коды возврата

* **0** — замер состоялся, и ни одной привязки в прозе не осталось.
* **1** — замер состоялся и есть находка: проза обходит существующее поле,
  либо род привязки живёт в прозе без единого читателя, либо привязка лежит
  в двух местах. «Не измерено» за «чисто» не выдаётся.
* **2** — замера НЕТ ВОВСЕ (конституция не прочитана, половин нет, население
  пусто). Про привязки при этом НЕ СКАЗАНО НИЧЕГО.

LLM_FORBIDDEN. Только stdlib · ADVISORY: ничего не гасит и не чинит; risk-логику,
стоп-кран, аллокатор, живой трек и ``landing/**`` не трогает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "prose_binding_census.json"

#: Конституция флота: где объявлены записи, их поля и их заметки.
MANIFEST_REL = "architecture/manifest.json"

#: Ключ ПРОЗЫ. Один, литералом: перебирать «что-нибудь похожее» значило бы
#: завести второе правило имени поля (урок #467, `_TS_FIELD`).
PROSE_KEY = "notes"

#: Ключ ПОЛЯ привязки — там, где поле существует.
FIELD_KEY = "governed_by"

#: Половины конституции и ключ, которым запись себя называет.
HALVES: tuple[tuple[str, str], ...] = (("artifacts", "path"), ("agents", "label"))

#: Роль привязки. Управляющая привязка и ссылка на происхождение НЕ складываются:
#: номер цикла ничем не управляет, и общая сумма выдала бы историю за правило.
GOVERNANCE = "governance"
PROVENANCE = "provenance"

#: Ключ перечня мест в замере. Литералом в ОДНОМ месте: два написания ключа
#: развели бы производителя и отрисовку молча.
PLACES_KEY = "places"

#: Где лежит привязка.
IN_FIELD = "field"
IN_BOTH = "both"
FIELD_BYPASSED = "field_bypassed"
NO_FIELD = "no_field_for_kind"

PLACE_RU = {
    IN_FIELD: "в поле, проза не повторяет — здоровый исход",
    IN_BOTH: "и в поле, и в прозе — ВТОРАЯ КОПИЯ, какая в силе не сказано",
    FIELD_BYPASSED: "поле ЕСТЬ и пусто, привязка в прозе — читатель поля слеп уже сегодня",
    NO_FIELD: "поля для этого рода НЕТ — проза единственное доступное место",
}

#: Что модуль делает с прочитанной ПРОЗОЙ.
BINDING_PARSER = "binding_parser"
TEXT_CONSUMER = "text_consumer"
READER_UNMEASURED = "unmeasured"

#: Что модуль делает с ПОЛЕМ. Вердикт один, и это не бедность мерки: полю
#: довольно ключа, и спрашивать у него образец значило бы задать чужой вопрос.
KEY_READER = "key_reader"

#: Причины, по которым о читателе НЕ сказано ничего. Каждая чинится своим.
SOURCE_UNREADABLE = "source_unreadable"
SOURCE_UNPARSED = "source_unparsed"
PATTERN_NOT_LITERAL = "pattern_not_literal"

READER_CAUSE_RU = {
    SOURCE_UNREADABLE: "исходник модуля не прочитан",
    SOURCE_UNPARSED: "исходник модуля не разобран (синтаксис)",
    PATTERN_NOT_LITERAL: "образец собран вычислением — токен назвать нечем",
}


class Kind:
    """Один род привязки: как его видно в прозе и чем его опознаёт читатель.

    ``signature`` ищет привязку в ТЕКСТЕ конституции. ``token`` — то, что
    обязано встретиться в ЛИТЕРАЛЕ читателя, чтобы претензия на разбор этого
    рода была предъявлена. Это ДВА разных предмета, и одно выражение на оба не
    годится: регулярное выражение, приложенное к регулярному выражению, ответа
    не даёт.
    """

    __slots__ = ("name", "role", "signature", "token", "fields")

    def __init__(self, name: str, role: str, signature: str, token: str,
                 fields: dict):
        self.name = name
        self.role = role
        self.signature = re.compile(signature)
        self.token = token
        self.fields = fields

    def field_of(self, half: str) -> Optional[str]:
        return self.fields.get(half)


#: Перечень родов ЗАКРЫТ намеренно: открытый («возьмём всякое упоминание»)
#: превратил бы любую соседнюю фразу в привязку, и население бесшумно выросло бы
#: (тот же выбор, что у `_BINDING_FORMS` в `s49_criterion_price`).
#:
#: Поле объявлено ПО ПОЛОВИНАМ, потому что у половин оно разное: ``governed_by``
#: есть у агента и отсутствует у артефакта. Записать одно значение на обе
#: половины значило бы соврать про одну из них.
KINDS: tuple[Kind, ...] = (
    Kind("adr", GOVERNANCE, r"ADR-(?:YL-)?\d{3}", "ADR-",
         {"agents": FIELD_KEY, "artifacts": None}),
    Kind("s49", GOVERNANCE, r"§\s?49", "§49",
         {"agents": None, "artifacts": None}),
    Kind("invariant", GOVERNANCE, r"инв\.\s*#\s*\d+", "инв.",
         {"agents": None, "artifacts": None}),
    Kind("rule", GOVERNANCE, r"\.claude/rules/[\w.-]+\.md", ".claude/rules/",
         {"agents": None, "artifacts": None}),
    Kind("order", GOVERNANCE, r"[Зз]аказ\s+(?:#\d+|G\d+)", "аказ",
         {"agents": None, "artifacts": None}),
    Kind("cycle", PROVENANCE, r"цикл\w*\s*#\d+", "цикл",
         {"agents": None, "artifacts": None}),
)

#: Каталоги, в которых прибор ищет читателей. Тесты исключены по построению:
#: тест не читатель системы, и считать его таковым значило бы объявить привязку
#: прочитанной там, где её читает только проверка.
READER_ROOTS = ("spa_core", "scripts")

#: Строковые методы, чей аргумент есть образец поиска по значению.
_MATCH_METHODS = ("startswith", "endswith", "find", "rfind", "index", "count",
                  "split", "rsplit", "partition", "rpartition", "replace")

#: Методы скомпилированного выражения, чей subject есть значение.
_RE_METHODS = ("match", "search", "fullmatch", "findall", "finditer", "sub",
               "subn", "split")


class Unmeasured(Exception):
    """Замера нет вовсе. Про привязки при этом не сказано НИЧЕГО."""


def _stamp(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


# --------------------------------------------------------------------------- #
# Ось 1 — где лежит привязка
# --------------------------------------------------------------------------- #

def read_manifest(path: Path) -> dict:
    """Прочитать конституцию. Непрочитанная конституция — `Unmeasured`, не пустота."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise Unmeasured(f"{MANIFEST_REL} не прочитан ({exc}) — о привязках НЕ "
                         f"СКАЗАНО НИЧЕГО") from exc


def _field_values(entry: dict, field: Optional[str]) -> list:
    """Значения поля привязки как список строк. Поля нет ⇒ пусто."""
    if field is None:
        return []
    raw = entry.get(field)
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def bindings(manifest: dict) -> list:
    """Перечислить привязки обеих половин конституции — по одной строке на (запись × род)."""
    rows: list = []
    seen_half = 0
    for half, name_key in HALVES:
        entries = observed(manifest, half, kind=list)
        if entries is None:
            continue
        seen_half += 1
        for entry in entries:
            if not isinstance(entry, dict):
                raise Unmeasured(f"в {MANIFEST_REL} член `{half}` не словарь "
                                 f"({type(entry).__name__}) — половина разобрана НЕ БЫЛА")
            name = observed(entry, name_key, kind=str)
            if name is None:
                raise Unmeasured(f"в {MANIFEST_REL} у записи `{half}` нет поля "
                                 f"`{name_key}` — адрес привязки НЕИЗВЕСТЕН")
            prose = observed(entry, PROSE_KEY, kind=str) or ""
            for kind in KINDS:
                field = kind.field_of(half)
                in_prose = kind.signature.findall(prose)
                in_field = [hit for value in _field_values(entry, field)
                            for hit in kind.signature.findall(value)]
                if not in_prose and not in_field:
                    continue
                if field is None:
                    place = NO_FIELD
                elif in_field and in_prose:
                    place = IN_BOTH
                elif in_field:
                    place = IN_FIELD
                else:
                    place = FIELD_BYPASSED
                rows.append({
                    "half": half, "entry": name, "kind": kind.name,
                    "role": kind.role, "place": place, "field": field,
                    "prose_mentions": len(in_prose), "field_mentions": len(in_field),
                })
    if not seen_half:
        raise Unmeasured(f"в {MANIFEST_REL} нет ни одной половины из "
                         f"{[half for half, _ in HALVES]} — населения не существует")
    return rows


# --------------------------------------------------------------------------- #
# Ось 2 — читатели: трассировка значения до литерала
# --------------------------------------------------------------------------- #

def _owner_functions(tree: ast.Module) -> dict:
    """Имя функции → её узел. Модульный уровень носит имя пустой строки."""
    out: dict = {"": tree}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
    return out


def _enclosing(tree: ast.Module) -> dict:
    """Узел → имя функции, в которой он лежит (ближайшей). Модульный уровень — ``""``."""
    owner: dict = {}
    for name, fn in _owner_functions(tree).items():
        if name == "":
            continue
        for node in ast.walk(fn):
            owner[node] = name
    return owner


def _compiled_literals(tree: ast.Module) -> dict:
    """Имя константы модуля → литерал образца для ``X = re.compile("lit")``."""
    out: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        func = value.func
        if not (isinstance(func, ast.Attribute) and func.attr == "compile"):
            continue
        if value.args and isinstance(value.args[0], ast.Constant) \
                and isinstance(value.args[0].value, str):
            out[target.id] = value.args[0].value
    return out


def _reads_key(node: ast.AST, key: str) -> bool:
    """Это литеральное чтение ключа ``key``? Три формы, объявленные явно."""
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == key
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get":
            return any(isinstance(arg, ast.Constant) and arg.value == key
                       for arg in node.args)
        if isinstance(func, ast.Name) and func.id == "observed" and len(node.args) >= 2:
            return isinstance(node.args[1], ast.Constant) and node.args[1].value == key
    return False


def _assigned_names(node: ast.AST) -> list:
    """Имена, которым узел присваивает значение."""
    targets: list = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        targets = [node.target]
    elif isinstance(node, ast.withitem):
        targets = [node.optional_vars] if node.optional_vars else []
    out: list = []
    for target in targets:
        for name in ast.walk(target):
            if isinstance(name, ast.Name):
                out.append(name.id)
    return out


def _mentions(node: Optional[ast.AST], names: set, anchors=frozenset()) -> bool:
    """Упоминает ли поддерево значение — ИМЕНЕМ либо САМИМ чтением ключа.

    Второй случай обязателен: `re.search("§49", entry["notes"])` не связывает
    прочитанное ни с одним именем, и трассировка только по именам объявила бы
    единственного настоящего читателя «берущим прозу как текст» — то есть
    соврала бы в сторону здоровья.
    """
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        if sub in anchors:
            return True
    return False


def _seed_flow(tree: ast.Module, seeds: set, anchors) -> set:
    """Неподвижная точка потока значения по парам «функция × имя» ВНУТРИ модуля.

    Четыре шага (присваивание · обход · вызов своей функции · параметр), и
    пятого — «наружу из модуля» — нет намеренно: значение, ушедшее в чужой
    модуль, объявляется третьим исходом, а не досматривается наугад.
    """
    functions = _owner_functions(tree)
    owner = _enclosing(tree)
    anchor_scopes = {owner.get(node, "") for node in anchors}
    grown = set(seeds)
    changed = True
    while changed:
        changed = False
        for fn_name, fn in functions.items():
            here = {name for scope, name in grown if scope == fn_name}
            if not here and fn_name not in anchor_scopes:
                continue
            for node in ast.walk(fn):
                # шаг 2/3: присваивание и обход — цель наследует значение
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                     ast.For, ast.AsyncFor, ast.withitem)):
                    if isinstance(node, (ast.For, ast.AsyncFor)):
                        source = node.iter
                    elif isinstance(node, ast.withitem):
                        source = node.context_expr
                    else:
                        source = node.value
                    if _mentions(source, here, anchors):
                        for name in _assigned_names(node):
                            pair = (owner.get(node, fn_name), name)
                            if pair not in grown:
                                grown.add(pair)
                                changed = True
                # шаг 4: вызов функции ТОГО ЖЕ модуля — параметр наследует
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    callee = functions.get(node.func.id)
                    if not isinstance(callee, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    params = [arg.arg for arg in callee.args.args]
                    for index, arg in enumerate(node.args):
                        if index < len(params) and _mentions(arg, here, anchors):
                            pair = (callee.name, params[index])
                            if pair not in grown:
                                grown.add(pair)
                                changed = True
                    for keyword in node.keywords:
                        if keyword.arg and _mentions(keyword.value, here, anchors):
                            pair = (callee.name, keyword.arg)
                            if pair not in grown:
                                grown.add(pair)
                                changed = True
    return grown


class _Reach:
    """Что доехало до значения: литералы-образцы, ограничения и ОДИН третий исход.

    ``computed`` — образец собран вычислением. Это ЕДИНСТВЕННЫЙ третий исход
    этой оси: про такой модуль нельзя сказать ни «разбирает», ни «не
    разбирает», потому что токена в образце назвать нечем.

    ``limits`` — что со значением в модуле ПРОИСХОДИЛО помимо разбора
    (склейка · укладка в контейнер · передача ввезённому коду). Это НЕ третий
    исход: все вызовы модуля осмотрены, и «объявленная форма разбора до
    значения не доехала» — измеренное утверждение. Неизмеренным остаётся лишь
    то, что делает с прозой ЧУЖОЙ модуль, и эта слепота названа отдельно
    (`not_reported`).
    """

    __slots__ = ("literals", "limits", "computed")

    def __init__(self):
        self.literals: set = set()
        self.limits: set = set()
        self.computed = False

    def pattern(self, node: Optional[ast.AST]) -> None:
        """Образец: литерал запоминается, вычисленный — называется таковым."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self.literals.add(node.value)
        elif node is not None:
            self.computed = True


#: Вызовы, которые значение НЕ уносят: они возвращают о нём факт, а не
#: передают его разбирающему чужому коду. Перечень закрыт — открытый («всё
#: встроенное безвредно») прятал бы `print`, то есть настоящий уход.
_HARMLESS_CALLS = ("len", "bool", "str", "repr", "isinstance", "type")

#: Методы, которые значение СКЛЕИВАЮТ. Это и есть «проза как текст»: склейка
#: привязку не читает, и объявлять из-за неё третий исход значило бы скрывать
#: ИЗМЕРЕННЫЙ ответ под словом «не измерено».
_CONCAT_METHODS = ("join", "format")

#: Методы, которые значение УКЛАДЫВАЮТ в контейнер. Дальше контейнер читает
#: кто-то ещё, и прибор туда не идёт — но все вызовы ЭТОГО модуля осмотрены,
#: поэтому ограничение НАЗЫВАЕТСЯ, а вердикт остаётся измеренным.
_STORE_METHODS = ("append", "extend", "add", "update", "insert", "setdefault")

#: Что со значением происходило помимо разбора — названные ограничения.
LIMIT_CONCATENATED = "concatenated"
LIMIT_STORED = "stored_in_container"
LIMIT_HANDED_OUT = "handed_to_code_outside_the_module"

LIMIT_RU = {
    LIMIT_CONCATENATED: "значение склеено в текст",
    LIMIT_STORED: "значение уложено в контейнер — его дальнейших читателей прибор не идёт смотреть",
    LIMIT_HANDED_OUT: "значение отдано коду вне модуля",
}


def _literals_reaching(tree: ast.Module, seeds: set, anchors) -> _Reach:
    """Литералы-образцы, доехавшие до значения, и названные ограничения."""
    patterns = _compiled_literals(tree)
    owner = _enclosing(tree)
    functions = _owner_functions(tree)
    anchor_scopes = {owner.get(node, "") for node in anchors}
    reach = _Reach()

    for fn_name, fn in functions.items():
        here = {name for scope, name in seeds if scope == fn_name}
        if not here and fn_name not in anchor_scopes:
            continue

        def holds(node: Optional[ast.AST]) -> bool:
            return _mentions(node, here, anchors)

        for node in ast.walk(fn):
            # шаг 5г: `lit in значение`
            if isinstance(node, ast.Compare):
                for op, right in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.In, ast.NotIn)) and holds(right):
                        reach.pattern(node.left)
                continue
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                # вызов не своей функции со значением в аргументе — значение ушло
                if isinstance(func, ast.Name) and func.id not in functions \
                        and func.id not in _HARMLESS_CALLS \
                        and any(holds(arg) for arg in node.args):
                    reach.limits.add(LIMIT_HANDED_OUT)
                continue
            subject = func.value
            carried = any(holds(arg) for arg in node.args)
            if func.attr in _RE_METHODS and isinstance(subject, ast.Name) and carried:
                if subject.id == "re":
                    # шаг 5а: `re.<метод>(lit, значение)`
                    if len(node.args) >= 2 and holds(node.args[1]):
                        reach.pattern(node.args[0])
                elif subject.id in patterns:
                    # шаг 5б: образец предкомпилированной константы модуля
                    reach.literals.add(patterns[subject.id])
                else:
                    reach.computed = True
                continue
            if func.attr in _MATCH_METHODS and holds(subject):
                # шаг 5в: строковый метод САМОГО значения
                if node.args:
                    reach.pattern(node.args[0])
                continue
            if carried and not holds(subject):
                # метод чужого объекта, которому значение отдано аргументом:
                # склейка · укладка в контейнер · всё прочее. Три РАЗНЫХ
                # ограничения, и слить их в одно значило бы потерять ровно то
                # различие, из-за которого «берёт как текст» измеримо.
                if func.attr in _CONCAT_METHODS:
                    reach.limits.add(LIMIT_CONCATENATED)
                elif func.attr in _STORE_METHODS:
                    reach.limits.add(LIMIT_STORED)
                else:
                    reach.limits.add(LIMIT_HANDED_OUT)
    return reach


def _candidate_sources(root: Path) -> list:
    """Файлы-кандидаты: лежат вне тестов, под объявленными корнями."""
    found: list = []
    for top in READER_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}":
                continue
            found.append((rel, path))
    return found


def _names_manifest(tree: ast.Module) -> bool:
    """Называет ли модуль адрес конституции ЛИТЕРАЛОМ."""
    return any(isinstance(node, ast.Constant) and isinstance(node.value, str)
               and MANIFEST_REL in node.value for node in ast.walk(tree))


def prose_readers(root: Path) -> list:
    """Что каждый кандидат ДЕЛАЕТ с прочитанной ПРОЗОЙ конституции."""
    key = PROSE_KEY
    rows: list = []
    for rel, path in _candidate_sources(root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            rows.append({"module": rel, "key": key, "verdict": READER_UNMEASURED,
                         "cause": SOURCE_UNREADABLE, "detail": str(exc), "kinds": []})
            continue
        # Дешёвый отсев ДО разбора: ни адреса конституции, ни ключа в тексте —
        # кандидатом файл не является. Это ускорение, а не суждение: оба
        # признака затем перепроверяются по дереву разбора.
        if MANIFEST_REL not in source or key not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            rows.append({"module": rel, "key": key, "verdict": READER_UNMEASURED,
                         "cause": SOURCE_UNPARSED, "detail": str(exc), "kinds": []})
            continue
        if not _names_manifest(tree):
            continue
        owner = _enclosing(tree)
        anchors = {node for node in ast.walk(tree) if _reads_key(node, key)}
        if not anchors:
            continue
        seeds: set = set()
        for holder in ast.walk(tree):
            if not isinstance(holder, (ast.Assign, ast.AnnAssign)) or holder.value is None:
                continue
            if not any(node in anchors for node in ast.walk(holder.value)):
                continue
            for name in _assigned_names(holder):
                seeds.add((owner.get(holder, ""), name))
        grown = _seed_flow(tree, seeds, anchors)
        reach = _literals_reaching(tree, grown, anchors)
        kinds = sorted({kind.name for kind in KINDS
                        for literal in reach.literals if kind.token in literal})
        limits = sorted(reach.limits)
        if kinds:
            rows.append({"module": rel, "key": key, "verdict": BINDING_PARSER,
                         "cause": None, "detail": None, "kinds": kinds,
                         "reach_limits": limits})
        elif reach.computed:
            # ЕДИНСТВЕННЫЙ третий исход оси: образец собран вычислением, и
            # токена в нём назвать нечем. Ни «разбирает», ни «не разбирает».
            rows.append({"module": rel, "key": key, "verdict": READER_UNMEASURED,
                         "cause": PATTERN_NOT_LITERAL, "detail": None,
                         "kinds": [], "reach_limits": limits})
        else:
            # ИЗМЕРЕННОЕ отсутствие разбора: все вызовы модуля осмотрены, ни
            # одна объявленная форма до значения не доехала. Ограничения
            # названы рядом, а не подменяют вердикт.
            rows.append({"module": rel, "key": key, "verdict": TEXT_CONSUMER,
                         "cause": None, "detail": None, "kinds": [],
                         "reach_limits": limits})
    return rows


def field_readers(root: Path) -> list:
    """Кто читает привязку ПОЛЕМ. Образец здесь не нужен — и в этом вся разница.

    Прозе нужен РАЗБОР: читатель обязан пронести до значения литерал с токеном
    рода. Полю нужен только КЛЮЧ. Приложить к полю мерку прозы («а есть ли у
    него образец?») значило бы спросить у него чужой вопрос и получить ноль
    читателей там, где их несколько. Асимметрия мерки и есть предмет замера.
    """
    rows: list = []
    for rel, path in _candidate_sources(root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            rows.append({"module": rel, "key": FIELD_KEY, "verdict": READER_UNMEASURED,
                         "cause": SOURCE_UNREADABLE, "detail": str(exc)})
            continue
        if MANIFEST_REL not in source or FIELD_KEY not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            rows.append({"module": rel, "key": FIELD_KEY, "verdict": READER_UNMEASURED,
                         "cause": SOURCE_UNPARSED, "detail": str(exc)})
            continue
        if not _names_manifest(tree):
            continue
        reads = [node for node in ast.walk(tree) if _reads_key(node, FIELD_KEY)]
        if not reads:
            continue
        rows.append({"module": rel, "key": FIELD_KEY, "verdict": KEY_READER,
                     "cause": None, "detail": None, "reads": len(reads)})
    return rows


# --------------------------------------------------------------------------- #
# Сводка
# --------------------------------------------------------------------------- #

def measure(root: Optional[Path] = None, *, manifest: Optional[Path] = None,
            now: Optional[datetime] = None) -> dict:
    """Один замер: население привязок × их место, и читатели прозы против поля."""
    base = Path(root) if root is not None else _REPO_ROOT
    man = Path(manifest) if manifest is not None else base / MANIFEST_REL
    rows = bindings(read_manifest(man))
    if not rows:
        raise Unmeasured(f"в {MANIFEST_REL} не нашлось ни одной привязки "
                         f"объявленных родов — это НЕ «привязок ноль», это "
                         f"«искали не той формой»")

    prose = prose_readers(base)
    field = field_readers(base)

    places: dict = {}
    by_kind: dict = {}
    for row in rows:
        places[row["place"]] = places.get(row["place"], 0) + 1
        slot = by_kind.setdefault(
            row["kind"],
            {"role": row["role"], "places": {}, "prose_entries": 0, "total": 0})
        slot["places"][row["place"]] = slot["places"].get(row["place"], 0) + 1
        slot["total"] += 1
        if row["place"] in (NO_FIELD, FIELD_BYPASSED, IN_BOTH):
            slot["prose_entries"] += 1

    parsed_kinds: dict = {}
    for row in prose:
        for kind in row["kinds"]:
            parsed_kinds.setdefault(kind, []).append(row["module"])
    for name, slot in by_kind.items():
        slot["prose_parsers"] = sorted(parsed_kinds.get(name, []))
        slot["second_reader"] = len(slot["prose_parsers"]) >= 2

    on_prose = sum(count for place, count in places.items() if place != IN_FIELD)
    findings = [row for row in rows if row["place"] in (FIELD_BYPASSED, IN_BOTH)]
    findings.sort(key=lambda row: (row["place"] != FIELD_BYPASSED, row["entry"]))
    orphan_kinds = sorted(name for name, slot in by_kind.items()
                          if slot["prose_entries"] and not slot["prose_parsers"])
    verdict = ("every_binding_in_a_field" if on_prose == 0
               else "bindings_rest_on_prose")
    return {
        "status": "OK",
        "generated_at": _stamp(now),
        "population": len(rows),
        "on_prose": on_prose,
        PLACES_KEY: places,
        "by_kind": by_kind,
        "kinds_without_a_prose_parser": orphan_kinds,
        "prose_readers": prose,
        "field_readers": field,
        "reader_tally": {
            PROSE_KEY: _reader_tally(prose),
            # У поля вердикт один по построению: ему довольно ключа. Считать по
            # нему «разбирающих» значило бы приложить мерку прозы к полю.
            FIELD_KEY: {KEY_READER: sum(1 for row in field
                                        if row["verdict"] == KEY_READER),
                        READER_UNMEASURED: sum(1 for row in field
                                               if row["verdict"] == READER_UNMEASURED)},
        },
        "rows": rows,
        "findings": findings,
        "verdict": verdict,
        "measured_from": {"manifest": str(man), "tree": str(base),
                          "reader_roots": list(READER_ROOTS)},
        "not_reported": [
            "верность самой привязки (прозой утверждается, не доказывается)",
            "верность разбора у читателя (претензия, а не её правильность)",
            "читатель через границу модуля (второй хоп)",
            "привязки вне конституции (докстроки кода)",
            "что делать — объявлять поле или нет есть решение (урок G86 п. 4)",
        ],
    }


def _reader_tally(rows: list) -> dict:
    tally: dict = {BINDING_PARSER: 0, TEXT_CONSUMER: 0, READER_UNMEASURED: 0}
    for row in rows:
        tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1
    return tally


def run(root: str | Path = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True,
        now: Optional[datetime] = None, **kw) -> dict:
    """Один замер для ступени моста (`findings_bridge.CENSUS_STAGE`).

    Такта у ступени НЕТ намеренно: замер есть разбор конституции и дерева в
    одном процессе, и платить за него такт значило бы отвечать вчерашним
    числом там, где сегодняшнее стои́т доли секунды.
    """
    base = Path(root)
    source = Path(data_dir) if data_dir is not None else base / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    try:
        doc = measure(root=base, now=now, **kw)
    except Unmeasured as exc:
        doc = {"status": "UNMEASURED", "reason": str(exc), "generated_at": _stamp(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 12) -> list:
    """Отрисовка для шага 0-офис. Делегирована ПРОИЗВОДИТЕЛЮ (ADR-158)."""
    lines: list = []
    if str(doc.get("status")) != "OK":
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason', 'причина не названа')}")
        lines.append("  про привязки конституции НЕ СКАЗАНО НИЧЕГО — выдать это "
                     "за «привязки в поле» нельзя")
        return lines
    places = observed(doc, PLACES_KEY, kind=dict)
    if places is None:
        # Перечня мест НЕТ — это не «мест ноль». Подставить здесь нули значило
        # бы напечатать уверенное «всё в поле» про замер, которого не читали.
        lines.append("НЕ ИЗМЕРЕНО: в замере нет перечня мест привязок — про "
                     "прозу НЕ СКАЗАНО НИЧЕГО")
        return lines

    def _num(key):
        """Отсутствие КЛЮЧА внутри прочитанного перечня есть измеренный ноль.

        Перечень строит сам производитель, пересчитывая КАЖДУЮ привязку, —
        место, не встретившееся ни разу, в словарь не попадает по построению.
        Отсутствие же САМОГО перечня — другое положение дел, и оно отсечено
        выше третьим исходом.
        """
        value = places.get(key)
        return 0 if value is None else int(value)

    lines.append(
        f"Привязки конституции: держится ПРОЗОЙ {doc.get('on_prose')} из "
        f"{doc.get('population')} · в поле {_num(IN_FIELD)} · поле ОБХОДИТСЯ "
        f"{_num(FIELD_BYPASSED)} · в двух местах {_num(IN_BOTH)} · поля для рода "
        f"НЕТ {_num(NO_FIELD)} (заказ G94 п. 3)")
    for row in (doc.get("findings") or [])[:max_rows]:
        lines.append(
            f"  [{row.get('place')}] {row.get('half')}/{row.get('entry')} "
            f"род `{row.get('kind')}`: поле `{row.get('field')}` несёт "
            f"{row.get('field_mentions')}, проза — {row.get('prose_mentions')}; "
            f"{PLACE_RU.get(row.get('place'), '')}")
    extra = len(doc.get("findings") or []) - max_rows
    if extra > 0:
        lines.append(f"  … ещё {extra} привязк(и) того же вида (полный перечень — `--json`)")
    by_kind = observed(doc, "by_kind", kind=dict) or {}
    for name in sorted(by_kind):
        slot = by_kind[name] or {}
        parsers = slot.get("prose_parsers") or []
        lines.append(
            f"  род `{name}` ({slot.get('role')}): прозой {slot.get('prose_entries')} "
            f"из {slot.get('total')} · читателей прозы "
            f"{len(parsers)}{' (' + ', '.join(parsers) + ')' if parsers else ' — НИ ОДНОГО'}"
            f"{' · ВТОРОЙ ЧИТАТЕЛЬ ЕСТЬ' if slot.get('second_reader') else ''}")
    orphans = doc.get("kinds_without_a_prose_parser") or []
    lines.append(
        "  родов в прозе БЕЗ ЕДИНОГО читателя: "
        + (", ".join(orphans) if orphans else "нет"))
    tally = observed(doc, "reader_tally", kind=dict) or {}
    prose_slot = tally.get(PROSE_KEY) or {}
    field_slot = tally.get(FIELD_KEY) or {}
    lines.append(
        f"  ПРОЗЕ нужен РАЗБОР: кандидатов {len(doc.get('prose_readers') or [])} — "
        f"разбирают привязку {prose_slot.get(BINDING_PARSER)} · берут как ТЕКСТ "
        f"{prose_slot.get(TEXT_CONSUMER)} · НЕ ИЗМЕРЕНО "
        f"{prose_slot.get(READER_UNMEASURED)}")
    lines.append(
        f"  ПОЛЮ довольно КЛЮЧА: читателей {field_slot.get(KEY_READER)} · НЕ ИЗМЕРЕНО "
        f"{field_slot.get(READER_UNMEASURED)} — мерки разные НАМЕРЕННО, спросить у "
        f"поля образец значило бы задать ему чужой вопрос")
    limits = sorted({limit for row in (doc.get("prose_readers") or [])
                     for limit in (row.get("reach_limits") or [])})
    if limits:
        lines.append("  со прозой в модуле происходило (ограничение, НЕ вердикт): "
                     + " · ".join(f"{limit} ({LIMIT_RU.get(limit, 'не названо')})"
                                  for limit in limits))
    causes = sorted({row.get("cause") for row in
                     (doc.get("prose_readers") or []) + (doc.get("field_readers") or [])
                     if row.get("cause")})
    if causes:
        lines.append("  о читателе не сказано, по причинам: " + " · ".join(
            f"{cause} ({READER_CAUSE_RU.get(cause, 'причина не названа')})"
            for cause in causes))
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc.get("not_reported") or []))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ — конституцию он не правит")
    return lines


def format_report(doc: dict, max_rows: int = 6) -> list:
    return ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="перепись привязок конституции: сколько держится прозой")
    parser.add_argument("--root", default=None, help="корень дерева (по умолчанию — своё)")
    parser.add_argument("--manifest", default=None, help=f"путь к {MANIFEST_REL}")
    parser.add_argument("--out", default=None,
                        help="куда записать артефакт (по умолчанию не писать)")
    parser.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = parser.parse_args(argv)
    try:
        doc = measure(Path(args.root) if args.root else None,
                      manifest=Path(args.manifest) if args.manifest else None)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        print("  про привязки конституции НЕ СКАЗАНО НИЧЕГО")
        return 2
    if args.out:
        atomic_save(doc, str(args.out))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc):
            print(line)
    return 1 if (doc.get("findings") or doc.get("kinds_without_a_prose_parser")
                 or doc.get("on_prose")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
