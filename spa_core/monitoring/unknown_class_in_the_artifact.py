"""Встречался ли НЕЗНАКОМЫЙ класс в ЖИВОМ артефакте — у каждого недостижимого раскола.

Заказ владельца **G98 п. 1** (хвост `ADR-517`, 29.09) дословно:

> «Четыре недостижимых раскола — это четыре ЖИВЫХ прибора, падающих на
> незнакомом классе. Достижимость мерит ДОРОГУ; событие не мерил никто.
> Спросить у АРТЕФАКТА каждого из четырёх, встречался ли класс вне
> объявленного перечня хоть раз, и развести «не встречался» от «артефакта
> нет» третьим исходом. Число „сколько раз прибор упал бы сегодня“ есть
> наблюдение, а не теория.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
Шаг `ADR-517` нашёл четыре раскола, стоящих на СТРОГОМ накопителе
(`{v: 0 for v in _VERDICTS}` + `+=`): незнакомый класс до расколотого читателя
не доезжает, потому что писатель падает `KeyError` раньше. Шаг назвал такую
находку НЕДОСТИЖИМОЙ и честно оговорил границу своего вердикта: «`reachable`
доказывает ДОРОГУ, а не событие».

Оговорка и есть предмет. «Писатель УПАЛ БЫ» — утверждение о коде; «класс вне
перечня в артефакте ЕСТЬ» — наблюдение. Между ними живут три разных мира, и
снаружи они выглядят одинаково:

* перечень не менялся, прибор исправен — артефакт чист по существу;
* перечень РАЗОШЁЛСЯ с тем, которым артефакт писался (класс переименован,
  добавлен, убран) — в артефакте стои́т ключ, которого сегодняшний писатель не
  заводит, и следующий прогон упадёт;
* артефакта нет вовсе — сказать нечего, и это НЕ «класс не встречался».

Третий мир тише первых двух и потому опаснее: пустая строка отчёта читается как
зелёная. Поэтому у прибора три исхода, а не два.

Как мерится: ДВЕ дороги в артефакт, и они отвечают на РАЗНОЕ
---------------------------------------------------------------------------
**Дорога писателя — КАРТА СЧЁТЧИКА в артефакте.** Ключи опубликованной карты
вне объявленного перечня. Только эта дорога может доказать, что писатель
незнакомый класс ВПУСТИЛ: у строгого накопителя посторонний ключ в карте
означает, что артефакт писался ДРУГИМ перечнем. Число по этой дороге и есть
«сколько раз прибор упал бы сегодня».

**Дорога записи — КЛАСС В ЗАПИСЯХ, которые артефакт публикует.** Значение,
стоя́щее в записи на месте класса, может лежать ВНЕ перечня и при этом ни разу
не дойти до счётчика: ветка, в которой счётчик растёт, до такой записи не
добирается. Отличить одно от другого обязана АРИФМЕТИКА, а не догадка:

    приращения ОБЪЯВЛЕННЫХ классов  ==  число записей, чей класс объявлен

Сумма берётся по объявленным ключам, а не по всем: приращения НЕЗНАКОМОГО
ключа — находка дороги писателя, и записью объявленного класса они не
объяснимы по построению. Сошлось ⇒ каждое приращение объяснено записью, значит
записи вне перечня до писателя НЕ ДОХОДИЛИ: их исход зовётся
:data:`REC_RIDES` и в число «упал бы» НЕ ВХОДИТ. Не сошлось ⇒ две дороги
спорят, и спор есть ТРЕТИЙ ИСХОД (:data:`GAP_ARITHMETIC`), а не вердикт.

**Эта арифметика — не украшение, она сняла ВЫДУМАННУЮ НАХОДКУ.** Замер 05.10:
у `unresolved_path_census` в опубликованных записях **189** значений `place`
вне перечня (`None`). Первая редакция правила объявила бы их наблюдением
«прибор упал бы 189 раз сегодня» — и это была бы ложь: `place` ставится в
запись только в разрешённой ветке, а `by_place[place] += 1` стои́т ровно в ней.
Арифметика показала равенство `49 == 49` и тем доказала, что до писателя ни
одно из 189 значений не доехало. Выдуманную находку от настоящей читатель не
отличает — поэтому дорога записи без арифметики к вердикту не допускается.

Адрес артефакта МЕРИТСЯ, а не берётся у константы
---------------------------------------------------------------------------
«Имя не есть адрес» (урок `ADR-465`): прибор, доверившийся константе
`ARTIFACT` производителя, судил бы его по ЧУЖОМУ файлу и ответил бы уверенно
и неверно. Поэтому адрес подтверждает САМ АРТЕФАКТ: годен только файл, чьё
поле `generated_by` равно разбираемому производителю. Константа — лишь
кандидат, и её согласие с найденным адресом печатается числом
(`artifact_constant_is_not_the_address`), а не замалчивается. Кандидат не
подошёл ⇒ обход ОБЪЯВЛЕННОГО набора поиска (:data:`SEARCH_GLOBS`); не нашлось
ничего ⇒ :data:`GAP_NO_ARTIFACT`, нашлось двое ⇒
:data:`GAP_MANY_ARTIFACTS`. «Не нашлось» есть утверждение о НАЗВАННОМ наборе,
а не о дереве вообще.

**Гипотеза, ради которой проверка и писалась, ОПРОВЕРГНУТА — замером, и она
была моей.** Читая дерево глазами, я увидел у `vacuous_guard_probe`
`ARTIFACT = census.PROBE_LEDGER` и счёл, что константа указывает на журнал
соседа (`rule_second_copy_census.PROBE_LEDGER` =
`copy_independence_ledger.json`). Псевдоним `census` в этом файле означает
`vacuous_guard_census`, и ЕГО `PROBE_LEDGER` называет
`vacuous_guard_ledger.json` — то есть собственный журнал зонда. Замер:
константа есть адрес у **4 из 4**.

Проверка остаётся, и не из вежливости к опровергнутой догадке: ровно она и
опровергла её. Выдумать «у соседа константа врёт» ничего не стоило —
отличить выдуманное от настоящего мог только разбор псевдонима и поле
`generated_by`. Это второй случай за одну работу, когда дешёвая догадка
обернулась бы напечатанной ложью (первый — 189 «падений» ниже).

Население — СОСЕДСКОЕ, и сверяется двумя дорогами
---------------------------------------------------------------------------
Расколы и их достижимость приходят от шага `ADR-517`
(`rule_second_copy_census.split_reachability_at_the_writer`). Своего правила
«что есть раскол», «какой счётчик открыт» и «какой накопитель строгий» здесь
нет ни одной строки — вторая копия такого правила и была бы предметом, который
весь ряд ищет.

Обход идёт соседскими же функциями (`_reach_sites` по `OPEN_COUNTER_DIRS`), а
ЧИСЛО недостижимых сверяется с ОПУБЛИКОВАННЫМ числом соседа из его живого
артефакта. Разошлись ⇒ шаг отказывает целиком.

**Почему обход нужен, хотя артефакт соседа есть.** Сосед печатает поимённо
лишь `unreachable_sample`, а он обрезан ценой показа (`COSTED_SAMPLE = 3`):
замер 05.10 — недостижимых **4**, названо **3**. Судить четырёх по трём
названным значило бы выдать обрезку показа за население.

Чего прибор НЕ говорит
---------------------------------------------------------------------------
* **`NEVER` есть утверждение о ВОЗРАСТЕ артефакта.** Два из четырёх журналов
  замера 05.10 старше двух недель (19.09): «класс не встречался» там сказано
  про дерево позапрошлой недели, и возраст печатается рядом с вердиктом, а не в
  сноске.
* **Прибор не судит, ПРАВ ли перечень.** Он сверяет артефакт с перечнем,
  который писатель заводит СЕГОДНЯ; верность самого перечня — другой вопрос.
* **Он не чинит ни одного счётчика** (`applied=False`) и ничего не
  перезапускает: артефакт читается как лежит.
* **`SEEN` не означает «прибор упал»** — он означает, что в артефакте стои́т
  класс, которого сегодняшний писатель не заводит, то есть следующий прогон
  упадёт на нём, если класс встретится снова.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as census  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "unknown_class_in_the_artifact.json"
PRODUCER = "spa_core/monitoring/unknown_class_in_the_artifact.py"
ORDER = "G98 п. 1 (хвост ADR-517)"

#: Артефакт соседа, у которого берётся ОПУБЛИКОВАННОЕ число недостижимых.
NEIGHBOUR_ARTIFACT = "data/rule_second_copy_census.json"
#: Ключ соседского шага в его артефакте — имя соседской функции, не своё.
NEIGHBOUR_STEP = "split_reachability_at_the_writer"

#: НАБОР ПОИСКА адреса артефакта, объявленный ЗАРАНЕЕ: «файла нет» есть
#: утверждение об этом наборе, а не о дереве вообще.
SEARCH_GLOBS = ("data/*.json", "spa_core/monitoring/*.json")

#: Пределов разбора ДО НЕПОДВИЖНОЙ ТОЧКИ: имя через имя через ввезённую
#: константу. Число есть ВЫБОР, а не свойство дерева; упёрлись в предел ⇒
#: перечень честно останется неразобранным, то есть третьим исходом.
_RESOLVE_PASSES = 6

#: Сколько строк печатать поимённо. Обрезка показа — ВЫБОР, и он назван:
#: население здесь мало (4), поэтому обрезка не наступает ни разу, но
#: молчаливой её быть не должно (урок `COSTED_SAMPLE = 3` у соседа).
NAMED_ROWS = 12

# --- исходы по ОДНОМУ недостижимому расколу --------------------------------
#: В артефакте стои́т класс, которого сегодняшний писатель не заводит.
SEEN = "unknown_class_is_in_the_artifact"
#: В артефакте только объявленные классы. Утверждение о ВОЗРАСТЕ артефакта.
NEVER = "only_declared_classes_are_in_the_artifact"
#: ТРЕТИЙ ИСХОД с названной причиной. Не «да» и не «нет».
UNMEASURED = "presence_of_an_unknown_class_is_not_measured"
_OUTCOMES = (SEEN, NEVER, UNMEASURED)

# --- причины третьего исхода, и они разные потому, что чинятся разным ------
GAP_NO_ARTIFACT = "no_file_in_the_declared_search_set_claims_this_producer"
GAP_MANY_ARTIFACTS = "two_or_more_files_claim_this_producer"
GAP_ARTIFACT_UNREADABLE = "the_file_that_claims_this_producer_is_unreadable"
GAP_ENUMERATION = "declared_enumeration_is_not_resolvable_at_the_binding"
GAP_NOT_PUBLISHED = "the_artifact_does_not_publish_this_counter"
GAP_COUNTER_SHAPE = "the_published_counter_is_not_a_mapping_of_counts"
GAP_SITE = "the_write_site_is_not_found_at_the_node_the_neighbour_named"
GAP_ARITHMETIC = "the_counter_total_and_the_declared_class_records_disagree"
_GAPS = (GAP_NO_ARTIFACT, GAP_MANY_ARTIFACTS, GAP_ARTIFACT_UNREADABLE,
         GAP_ENUMERATION, GAP_NOT_PUBLISHED, GAP_COUNTER_SHAPE, GAP_SITE,
         GAP_ARITHMETIC)

# --- ВТОРАЯ ось: дорога записи. Своё имя, потому что своё утверждение ------
#: Каждая запись несёт объявленный класс.
REC_CLEAN = "every_record_class_is_declared"
#: Класс вне перечня в записи ЕСТЬ, но счётчик его НЕ ВИДЕЛ (арифметика сошлась).
REC_RIDES = "a_class_outside_the_enumeration_rides_in_the_record_unaccounted"
#: Две дороги спорят — и это отказ, а не вердикт.
REC_DISAGREES = "the_counter_total_and_the_records_disagree"
#: Источник класса или список записей по дереву не разобран.
REC_UNRESOLVED = "the_class_source_or_the_record_list_is_not_resolvable"
_REC_OUTCOMES = (REC_CLEAN, REC_RIDES, REC_DISAGREES, REC_UNRESOLVED)

# --- отказы САМОГО шага. Ни один из них не есть ноль -----------------------
UNMEASURED_NEIGHBOUR = "neighbour_reachability_step_is_absent_or_unmeasured"
UNMEASURED_POPULATION = "second_walk_disagrees_with_the_published_step"


class NotMeasured(RuntimeError):
    """Отказ шага: предпосылка не обеспечена. Третий исход, не вердикт."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ===========================================================================
# Перечень, объявленный У СВЯЗЫВАНИЯ
# ===========================================================================

def _module_strings(tree: ast.Module,
                   foreign: Optional[Dict[str, object]] = None
                   ) -> Dict[str, object]:
    """Строковые константы модуля и кортежи/списки из них.

    Нужны ровно для одного: перечень классов почти всегда объявлен именем
    (`_VERDICTS`, `_REMEDY_CLASSES`), а не литералами на месте. Имя,
    значение которого не разбирается, в словарь НЕ попадает — и перечень,
    на него опирающийся, станет третьим исходом, а не догадкой.

    Разбор идёт ДО НЕПОДВИЖНОЙ ТОЧКИ, и это не стиль: `_VERDICTS` собран из
    имён, каждое из которых само есть ввезённая константа
    (`VERDICT_DRIFT_SILENT = census.PROBE_DRIFT_SILENT`). Один проход сверху
    вниз объявил бы перечень неразобранным — замер 05.10 поймал на этом ДВА
    раскола из четырёх, то есть половину населения.
    """
    foreign = foreign or {}
    out: Dict[str, object] = {}
    for _ in range(_RESOLVE_PASSES):
        grew = False
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names or node.value is None:
                continue
            value = _literal(node.value, out, foreign)
            if value is None:
                continue
            for name in names:
                if out.get(name) != value:
                    out[name] = value
                    grew = True
        if not grew:
            break
    return out


def _literal(node: ast.AST, known: Dict[str, object],
             foreign: Optional[Dict[str, object]] = None) -> Optional[object]:
    """Значение выражения, если оно РАЗБИРАЕТСЯ: строка или их набор."""
    foreign = foreign or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.Attribute):
        # `census.PROBE_DRIFT_SILENT` — константа ВВЕЗЁННОГО модуля. Глубина
        # ровно один шаг, и предел назван: цепочка через третий модуль не
        # разбирается и станет третьим исходом, а не догадкой.
        return foreign.get(_dotted(node) or "")
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        values: List[str] = []
        for item in node.elts:
            got = _literal(item, known, foreign)
            if not isinstance(got, str):
                return None
            values.append(got)
        return tuple(values)
    return None


def _import_alias_modules(tree: ast.Module) -> Dict[str, str]:
    """Псевдоним ввоза → точечное имя модуля (`census` → `spa_core…census`)."""
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return out


def _foreign_strings(root: Path, tree: ast.Module) -> Dict[str, object]:
    """Строковые константы модулей, ВВЕЗЁННЫХ как `import m as x`.

    Один шаг, и его предел назван: `census.PLACE_REPO` разбирается, цепочка
    через третий модуль — нет, и тогда перечень честно станет третьим исходом.
    """
    out: Dict[str, object] = {}
    for alias, dotted in _import_alias_modules(tree).items():
        path = root / (dotted.replace(".", "/") + ".py")
        if not path.is_file():
            continue
        try:
            parsed = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for name, value in _module_strings(parsed).items():
            out[f"{alias}.{name}"] = value
    return out


def _dotted(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _enumeration(scope: ast.AST, counter: str, known: Dict[str, object],
                 foreign: Dict[str, object]) -> Tuple[Optional[List[str]], Optional[str]]:
    """Классы, которые писатель ЗАВОДИТ при связывании счётчика.

    Правило ОДНО и оно про связывание, а не про имя: берутся выражения,
    которыми счётчик связан в ТОЙ ЖЕ области (соседская
    :func:`census._scope_bindings` — не вторая копия), и из них читаются
    ключи. Две формы, и обе населены замером:

    * словарь на месте — `{PLACE_REPO: 0, PLACE_FIXTURE: 0, …}`;
    * охват по перечню — `{v: 0 for v in _VERDICTS}` (перечень именем или
      набором на месте).

    Не разобралось — возвращается причина, а не пустой перечень: пустой
    перечень объявил бы НЕЗНАКОМЫМ каждый класс артефакта.
    """
    binds = census._scope_bindings(scope).get(counter) or []
    if not binds:
        return None, "счётчик не связан ни одним выражением в своей области"
    seeded: List[str] = []
    for expr in binds:
        if isinstance(expr, ast.Dict):
            for key in expr.keys:
                if key is None:
                    return None, "в словаре счётчика есть распаковка `**`"
                got = _literal(key, known, foreign)
                if not isinstance(got, str):
                    return None, (f"ключ словаря счётчика не разобран: "
                                  f"{ast.dump(key)[:80]}")
                seeded.append(got)
            continue
        if isinstance(expr, ast.DictComp) and len(expr.generators) == 1:
            source = expr.generators[0].iter
            got = _literal(source, known, foreign)
            if isinstance(got, str):
                got = (got,)
            if not isinstance(got, tuple):
                return None, (f"перечень охвата не разобран: "
                              f"{_dotted(source) or type(source).__name__}")
            seeded.extend(got)
            continue
        return None, (f"связывание счётчика — не словарь и не охват: "
                      f"{type(expr).__name__}")
    return sorted(set(seeded)), None


# ===========================================================================
# Публикация: какой КЛЮЧ артефакта несёт это имя
# ===========================================================================

def _published_key(scope: ast.AST, name: str) -> Tuple[Optional[str], Optional[str]]:
    """Ключ возвращаемого словаря, под которым публикуется имя `name`.

    Имя ключа НЕ угадывается по имени переменной: `by_place` и `counts`
    совпадают с ним, а `remedy_counts` — дело случая. Берётся `return`
    области и ищется значение, которое есть ровно это имя.
    """
    found: List[str] = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if (isinstance(value, ast.Name) and value.id == name
                    and isinstance(key, ast.Constant)
                    and isinstance(key.value, str)):
                found.append(key.value)
    distinct = sorted(set(found))
    if len(distinct) == 1:
        return distinct[0], None
    if not distinct:
        return None, f"ни один `return` области не публикует имя `{name}`"
    return None, (f"имя `{name}` публикуется под разными ключами: "
                  f"{', '.join(distinct)}")


# ===========================================================================
# Источник КЛАССА у места записи
# ===========================================================================

def _write_site(scope: ast.AST, counter: str, line: int) -> Optional[ast.AugAssign]:
    """Приращение счётчика в узле, который НАЗВАЛ сосед (файл и строка)."""
    for node in ast.walk(scope):
        if (isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Subscript)
                and isinstance(node.target.value, ast.Name)
                and node.target.value.id == counter
                and getattr(node, "lineno", None) == line):
            return node
    return None


def _enclosing_for(scope: ast.AST, node: ast.AST) -> Optional[ast.For]:
    """Ближайший `for`, в теле которого лежит это приращение."""
    best: Optional[ast.For] = None
    for cand in ast.walk(scope):
        if not isinstance(cand, ast.For):
            continue
        if any(inner is node for inner in ast.walk(cand)):
            if best is None or (cand.lineno or 0) > (best.lineno or 0):
                best = cand
    return best


def _record_field(key: ast.AST, var: Optional[str]) -> Optional[str]:
    """Поле записи, если класс берётся у ПЕРЕМЕННОЙ ЦИКЛА (`форма A`)."""
    if var is None:
        return None
    if (isinstance(key, ast.Call) and isinstance(key.func, ast.Attribute)
            and key.func.attr == "get"
            and isinstance(key.func.value, ast.Name)
            and key.func.value.id == var
            and key.args and isinstance(key.args[0], ast.Constant)
            and isinstance(key.args[0].value, str)):
        return key.args[0].value
    if (isinstance(key, ast.Subscript) and isinstance(key.value, ast.Name)
            and key.value.id == var and isinstance(key.slice, ast.Constant)
            and isinstance(key.slice.value, str)):
        return key.slice.value
    return None


def _stored_field(loop: ast.For, scope: ast.AST, class_name: str
                  ) -> Optional[Tuple[str, str]]:
    """Поле и список, если класс — ИМЯ, уложенное в запись (`форма B`).

    `by_place[place] += 1` берёт класс у имени, а не у поля записи. Связь с
    артефактом идёт ПОТОКОМ ЗНАЧЕНИЯ: то же имя укладывается в запись
    (`row["place"] = place`), а запись добавляется в список
    (`rows.append(row)`). Без этой формы раскол `unresolved_path_census`
    выпал бы из населения молча — а он один из четырёх.

    **Укладка и добавление живут в РАЗНЫХ циклах, и это не исключение.**
    `row["place"] = place` стои́т во ВНУТРЕННЕМ цикле (`for cut in range(…)`),
    а `rows.append(row)` — во внешнем: внутренний ищет разрешение и выходит
    `break`, запись добавляется один раз независимо от исхода. Правило,
    искавшее добавление в том же цикле, что и укладку, объявило дорогу
    записи неразобранной и потеряло ровно тот раскол, на котором потом
    нашлась выдуманная находка в 189 падений. Поэтому укладка ищется в
    ЦИКЛЕ (там поток значения), а добавление — в ОБЛАСТИ.
    """
    field: Optional[Tuple[str, str]] = None   # (имя записи, имя поля)
    for node in ast.walk(loop):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
                and isinstance(node.targets[0].slice, ast.Constant)
                and isinstance(node.targets[0].slice.value, str)
                and isinstance(node.value, ast.Name)
                and node.value.id == class_name):
            field = (node.targets[0].value.id, node.targets[0].slice.value)
    if field is None:
        return None
    record, name = field
    for node in ast.walk(scope):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and len(node.args) == 1 and isinstance(node.args[0], ast.Name)
                and node.args[0].id == record):
            return name, node.func.value.id
    return None


def _class_source(scope: ast.AST, counter: str, line: int
                  ) -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """Поле записи и имя списка, из которых класс попадает к счётчику."""
    site = _write_site(scope, counter, line)
    if site is None:
        return None, GAP_SITE
    loop = _enclosing_for(scope, site)
    if loop is None:
        return None, "приращение счётчика не лежит ни в одном `for`"
    var = loop.target.id if isinstance(loop.target, ast.Name) else None
    key = site.target.slice if isinstance(site.target, ast.Subscript) else None
    if key is None:
        return None, "класс берётся не подстрокой счётчика"
    field = _record_field(key, var)
    if field is not None:
        if not isinstance(loop.iter, ast.Name):
            return None, "список цикла — не имя, публикации у него нет"
        return (field, loop.iter.id), None
    if isinstance(key, ast.Name):
        stored = _stored_field(loop, scope, key.id)
        if stored is not None:
            return stored, None
        return None, (f"имя класса `{key.id}` не укладывается ни в одну "
                      f"запись публикуемого списка")
    return None, f"источник класса не разобран: {type(key).__name__}"


# ===========================================================================
# Адрес артефакта — ПОДТВЕРЖДЁННЫЙ самим артефактом
# ===========================================================================

def _claimed_by(path: Path, producer: str) -> Tuple[Optional[bool], Optional[str]]:
    """Заявляет ли файл этого производителя. Третий исход — `None`."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, "артефакт — не документ"
    return observed(doc, "generated_by", kind=str) == producer, None


def _constant_candidates(root: Path, tree: ast.Module, producer_rel: str
                         ) -> List[Path]:
    """Кандидаты из константы `ARTIFACT` модуля — КАНДИДАТЫ, не адрес."""
    foreign = _foreign_strings(root, tree)
    known = _module_strings(tree, foreign)
    value: Optional[object] = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "ARTIFACT"
                   for t in node.targets):
            continue
        value = _literal(node.value, known, foreign)
    if not isinstance(value, str):
        return []
    # Производители кладут артефакт и рядом с кодом, и в `data/` — обе формы
    # есть в дереве, поэтому обе и проверяются; выбирает `generated_by`.
    return [root / value, root / "data" / value]


def _artifact_address(root: Path, producer_rel: str, tree: ast.Module) -> dict:
    """Адрес артефакта этого производителя — ИЗМЕРЕННЫЙ, а не названный."""
    unreadable: List[dict] = []
    for cand in _constant_candidates(root, tree, producer_rel):
        if not cand.is_file():
            continue
        claims, why = _claimed_by(cand, producer_rel)
        if claims:
            return {"artifact": cand.relative_to(root).as_posix(),
                    "constant_is_the_address": True, "gap": None,
                    "searched": False, "unreadable": unreadable}
        if claims is None:
            unreadable.append({"file": cand.relative_to(root).as_posix(),
                               "reason": why})
    found: List[str] = []
    for pattern in SEARCH_GLOBS:
        for path in sorted(root.glob(pattern)):
            claims, why = _claimed_by(path, producer_rel)
            if claims:
                found.append(path.relative_to(root).as_posix())
            elif claims is None:
                unreadable.append({"file": path.relative_to(root).as_posix(),
                                   "reason": why})
    if len(found) == 1:
        return {"artifact": found[0], "constant_is_the_address": False,
                "gap": None, "searched": True, "unreadable": unreadable}
    if len(found) > 1:
        return {"artifact": None, "constant_is_the_address": False,
                "gap": GAP_MANY_ARTIFACTS, "searched": True,
                "claimants": found, "unreadable": unreadable}
    gap = GAP_ARTIFACT_UNREADABLE if unreadable else GAP_NO_ARTIFACT
    return {"artifact": None, "constant_is_the_address": None, "gap": gap,
            "searched": True, "unreadable": unreadable}


# ===========================================================================
# Один раскол
# ===========================================================================

def _age_hours(doc: dict, now: dt.datetime) -> Optional[float]:
    raw = observed(doc, "generated_at", kind=str)
    if raw is None:
        return None
    try:
        stamp = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return round((now - stamp).total_seconds() / 3600.0, 2)


def _ask_one(root: Path, row: dict, now: dt.datetime) -> dict:
    """Встречался ли незнакомый класс в артефакте ОДНОГО раскола."""
    out = {"file": row["file"], "line": row["line"], "owner": row["owner"],
           "counter": row["counter"], "found_by": row.get("split_found_by"),
           "artifact": None, "artifact_age_hours": None,
           "artifact_constant_is_the_address": None,
           "declared": None, "declared_count": None,
           "counter_key": None, "record_field": None, "record_key": None,
           "unknown_keys": [], "would_raise_today": 0,
           "records_outside": 0, "counter_total": None,
           "declared_total": None, "records_accounted": None,
           "record_route": REC_UNRESOLVED, "record_gap": None,
           "outcome": UNMEASURED, "gap": None}
    path = root / row["file"]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        out["gap"] = GAP_SITE
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out
    scope = next((n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == row["owner"]), None)
    if scope is None:
        out["gap"] = GAP_SITE
        out["reason"] = f"области `{row['owner']}` в файле нет"
        return out

    foreign = _foreign_strings(root, tree)
    known = _module_strings(tree, foreign)
    declared, why = _enumeration(scope, row["counter"], known, foreign)
    if declared is None:
        out["gap"] = GAP_ENUMERATION
        out["reason"] = why
        return out
    out["declared"] = declared
    out["declared_count"] = len(declared)

    address = _artifact_address(root, row["file"], tree)
    out["artifact"] = address["artifact"]
    out["artifact_constant_is_the_address"] = address["constant_is_the_address"]
    if address["gap"] is not None:
        out["gap"] = address["gap"]
        out["reason"] = (f"набор поиска {', '.join(SEARCH_GLOBS)}: "
                         f"заявителей {len(address.get('claimants') or [])}, "
                         f"нечитаемых {len(address['unreadable'])}")
        if address.get("claimants"):
            out["claimants"] = address["claimants"]
        return out

    doc = json.loads((root / address["artifact"]).read_text(encoding="utf-8"))
    out["artifact_age_hours"] = _age_hours(doc, now)

    counter_key, why = _published_key(scope, row["counter"])
    if counter_key is None:
        out["gap"] = GAP_NOT_PUBLISHED
        out["reason"] = why
        return out
    out["counter_key"] = counter_key
    counts = observed(doc, counter_key, kind=dict)
    if counts is None or not all(isinstance(v, int) for v in counts.values()):
        out["gap"] = GAP_COUNTER_SHAPE
        out["reason"] = (f"ключ `{counter_key}` артефакта не есть карта "
                         f"целых — сравнивать перечень не с чем")
        return out

    # --- ДОРОГА ПИСАТЕЛЯ: ключи карты вне перечня ------------------------
    unknown = {k: v for k, v in counts.items() if k not in declared}
    out["unknown_keys"] = sorted(unknown)
    out["would_raise_today"] = sum(unknown.values())
    out["counter_total"] = sum(counts.values())
    # Арифметика сверяется с приращениями ОБЪЯВЛЕННЫХ классов, а не со всеми:
    # приращения НЕЗНАКОМОГО ключа — это находка дороги писателя, и
    # записями объявленного класса они не объяснимы ПО ПОСТРОЕНИЮ. Правило,
    # сверявшее полную сумму, объявляло бы каждую свою находку «спором двух
    # дорог» и гасило её третьим исходом — поймано собственным контролем
    # (`test_unknown_key_in_the_counter_map_is_seen`).
    out["declared_total"] = sum(v for k, v in counts.items() if k in declared)

    # --- ДОРОГА ЗАПИСИ: класс в опубликованных записях -------------------
    source, why = _class_source(scope, row["counter"], row["line"])
    if source is None:
        out["record_route"] = REC_UNRESOLVED
        out["record_gap"] = why
    else:
        field, listname = source
        out["record_field"] = field
        record_key, why = _published_key(scope, listname)
        out["record_key"] = record_key
        records = (observed(doc, record_key, kind=list)
                   if record_key is not None else None)
        if records is None:
            out["record_route"] = REC_UNRESOLVED
            out["record_gap"] = (why or f"ключ `{record_key}` артефакта не "
                                        f"есть список записей")
        else:
            rows = [r for r in records if isinstance(r, dict)]
            accounted = sum(1 for r in rows if r.get(field) in declared)
            outside = len(rows) - accounted
            out["records_accounted"] = accounted
            out["records_outside"] = outside
            if accounted != out["declared_total"]:
                out["record_route"] = REC_DISAGREES
                out["record_gap"] = (
                    f"карта счётчика насчитала {out['declared_total']} "
                    f"приращений объявленных классов, а записей такого класса "
                    f"{accounted} — это ДВЕ дороги к одному событию, и "
                    f"разойдясь, они отвечают на разные вопросы")
            elif outside:
                out["record_route"] = REC_RIDES
            else:
                out["record_route"] = REC_CLEAN

    if out["record_route"] == REC_DISAGREES:
        out["gap"] = GAP_ARITHMETIC
        out["reason"] = out["record_gap"]
        return out
    out["outcome"] = SEEN if unknown else NEVER
    out["gap"] = None
    return out


# ===========================================================================
# Шаг
# ===========================================================================

def _published_unreachable(root: Path) -> Tuple[Optional[int], Optional[str]]:
    """Сколько недостижимых раскола ОПУБЛИКОВАЛ сосед в своём артефакте."""
    path = root / NEIGHBOUR_ARTIFACT
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{NEIGHBOUR_ARTIFACT}: {type(exc).__name__}: {exc}"
    step = observed(doc, NEIGHBOUR_STEP, kind=dict)
    if step is None:
        return None, (f"в {NEIGHBOUR_ARTIFACT} нет шага `{NEIGHBOUR_STEP}` — "
                      f"населения «недостижимый раскол» не существует")
    if str(step.get("status")) != "MEASURED":
        return None, (f"шаг `{NEIGHBOUR_STEP}` соседа не измерен "
                      f"({step.get('status')}) — это НЕ «недостижимых нет»")
    outcomes = observed(step, "reach_outcomes", kind=dict)
    if outcomes is None:
        return None, "сосед не назвал исходов достижимости"
    declared = observed(outcomes, census.REACH_UNREACHABLE, kind=int)
    if declared is None:
        return None, (f"у соседа нет числа `{census.REACH_UNREACHABLE}`: "
                      f"отсутствие поля не есть ноль")
    return declared, None


def _walk_unreachable(root: Path) -> Tuple[List[dict], List[dict], int]:
    """Недостижимые расколы — СОСЕДСКИМ обходом, без своего правила."""
    rows: List[dict] = []
    unreadable: List[dict] = []
    scanned = 0
    for sub in census.OPEN_COUNTER_DIRS:
        base = root / sub
        if not base.is_dir():
            unreadable.append({"file": sub, "reason": "каталога нет в дереве"})
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if any(rel.startswith(skip) for skip in census.OPEN_COUNTER_SKIP):
                continue
            scanned += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                unreadable.append({"file": rel,
                                   "reason": f"{type(exc).__name__}: {exc}"})
                continue
            rows.extend(r for r in census._reach_sites(rel, tree)
                        if r["reach"] == census.REACH_UNREACHABLE)
    return rows, unreadable, scanned


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            published: Optional[int] = None) -> dict:
    """Встречался ли класс вне перечня в артефакте каждого недостижимого.

    `published` — число недостижимых, объявленное соседом. По умолчанию
    читается из его живого артефакта; сцена подаёт его прямо, потому что
    артефакта соседа в одноразовом дереве нет по построению.
    """
    now = now or _utcnow()
    if published is None:
        published, why = _published_unreachable(root)
        if published is None:
            raise NotMeasured(why or "сосед не прочитан")
    rows, unreadable, scanned = _walk_unreachable(root)
    if unreadable:
        raise NotMeasured(
            f"{len(unreadable)} файл(ов) или каталог(ов) не прочитано — "
            f"население неполно, а неполное население не есть измеренное: "
            f"{unreadable[0]['file']} ({unreadable[0]['reason']})")
    if len(rows) != published:
        raise NotMeasured(
            f"свой обход нашёл {len(rows)} недостижимых раскол(ов), сосед "
            f"опубликовал {published} — это ДВЕ разные дороги к одному "
            f"населению, и разойдясь, они отвечают на разные вопросы")
    asked = [_ask_one(root, row, now) for row in rows]
    outcomes = {cls: sum(1 for r in asked if r["outcome"] == cls)
                for cls in _OUTCOMES}
    gaps = {gap: sum(1 for r in asked if r.get("gap") == gap)
            for gap in _GAPS}
    record_routes = {cls: sum(1 for r in asked if r["record_route"] == cls)
                     for cls in _REC_OUTCOMES}
    ages = [r["artifact_age_hours"] for r in asked
            if r["artifact_age_hours"] is not None]
    lying = sum(1 for r in asked
                if r["artifact_constant_is_the_address"] is False)
    return {
        "generated_at": now.isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "MEASURED",
        "question": ("встречался ли в ЖИВОМ артефакте недостижимого раскола "
                     "класс вне перечня, который писатель заводит сегодня"),
        "order": ORDER,
        "applied": False,
        "neighbour_step": NEIGHBOUR_STEP,
        "search_globs": list(SEARCH_GLOBS),
        "population": len(asked),
        "published_population": published,
        "files_scanned": scanned,
        "outcomes": outcomes,
        "unmeasured_reasons": gaps,
        "record_routes": record_routes,
        # ЧИСЛО ЗАКАЗА: сколько раз писатель уже впустил незнакомый класс.
        "would_raise_today": sum(r["would_raise_today"] for r in asked),
        # ДРУГОЕ утверждение, и складывать его с предыдущим ЗАПРЕЩЕНО:
        # значение вне перечня в записи, которого счётчик не видел.
        "rides_in_the_record_only": sum(r["records_outside"] for r in asked
                                        if r["record_route"] == REC_RIDES),
        "artifact_constant_is_not_the_address": lying,
        "oldest_artifact_hours": max(ages) if ages else None,
        "newest_artifact_hours": min(ages) if ages else None,
        "rows": asked[:NAMED_ROWS],
        "named_rows_limit": NAMED_ROWS,
        "what_it_does_not_prove": [
            "что `only_declared_classes_are_in_the_artifact` означает "
            "«прибор исправен»: это утверждение о ВОЗРАСТЕ артефакта, и "
            "возраст напечатан рядом с вердиктом",
            "что перечень, который писатель заводит сегодня, ВЕРЕН — сверка "
            "идёт с ним, а не с истиной",
            "что `unknown_class_is_in_the_artifact` означает «прибор упал»: "
            "он означает, что в артефакте стои́т класс, которого сегодняшний "
            "писатель не заводит",
            "что значение вне перечня В ЗАПИСИ дошло до писателя: это "
            "решает АРИФМЕТИКА, и несошедшаяся арифметика есть отказ, а не "
            "вердикт",
            "что «файла нет» сказано о дереве: оно сказано об объявленном "
            f"наборе поиска ({', '.join(SEARCH_GLOBS)})",
            "что достижимые расколы здесь измерены — у них писатель молчит, "
            "и вопрос «упал бы» к ним не относится вовсе",
        ],
    }


def report(doc: dict) -> List[str]:
    status = str(doc.get("status"))
    if status != "MEASURED":
        return [f"НЕ ИЗМЕРЕНО — "
                f"{observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    outcomes = observed(doc, "outcomes", kind=dict) or {}
    routes = observed(doc, "record_routes", kind=dict) or {}
    out = [
        f"незнакомый класс в артефакте недостижимого раскола (заказ "
        f"{doc.get('order')}): {status} · недостижимых "
        f"{doc.get('population')} · ЕСТЬ В АРТЕФАКТЕ {outcomes.get(SEEN)} · "
        f"только объявленные {outcomes.get(NEVER)} · НЕ ИЗМЕРЕНО "
        f"{outcomes.get(UNMEASURED)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[ЧИСЛО ЗАКАЗА] писатель уже впустил незнакомый класс "
        f"{doc.get('would_raise_today')} раз(а) — это и есть «сколько раз "
        f"прибор упал бы сегодня»",
        f"[ДРУГОЕ УТВЕРЖДЕНИЕ] значений вне перечня, которые ЕДУТ В ЗАПИСИ, "
        f"но счётчика не касались: {doc.get('rides_in_the_record_only')} "
        f"(складывать с предыдущим нельзя — счётчик их не видел)",
        f"[ВОЗРАСТ] «не встречался» сказано про артефакты возрастом от "
        f"{doc.get('newest_artifact_hours')}ч до "
        f"{doc.get('oldest_artifact_hours')}ч",
    ]
    if doc.get("artifact_constant_is_not_the_address"):
        out.append(
            f"[ИМЯ НЕ ЕСТЬ АДРЕС] у {doc.get('artifact_constant_is_not_the_address')} "
            f"производител(я/ей) константа `ARTIFACT` указывает НЕ на их "
            f"артефакт — адрес подтверждён полем `generated_by`, а не "
            f"константой")
    if routes.get(REC_DISAGREES):
        out.append(f"[ОТКАЗ] у {routes.get(REC_DISAGREES)} раскол(ов) две "
                   f"дороги к одному событию спорят — вердикта нет")
    for row in (observed(doc, "rows", kind=list) or []):
        if not isinstance(row, dict):
            continue
        if row.get("outcome") == SEEN:
            out.append(f"   [ЕСТЬ] {row['file']}:{row['line']} "
                       f"`{row['counter']}` — классы вне перечня "
                       f"{', '.join(row.get('unknown_keys') or [])} "
                       f"({row.get('would_raise_today')} приращений)")
        elif row.get("outcome") == UNMEASURED:
            out.append(f"   [НЕ ИЗМЕРЕНО] {row['file']}:{row['line']} "
                       f"`{row['counter']}` — {row.get('gap')}: "
                       f"{row.get('reason')}")
        else:
            rides = (f" · едет в записи {row['records_outside']}"
                     if row.get("record_route") == REC_RIDES else "")
            out.append(f"   [ТОЛЬКО ОБЪЯВЛЕННЫЕ] {row['file']}:{row['line']} "
                       f"`{row['counter']}` — перечень "
                       f"{row.get('declared_count')} · артефакт "
                       f"{row.get('artifact')} ({row.get('artifact_age_hours')}ч)"
                       f"{rides}")
    out.append("НЕ ДОКЛАДЫВАЕТ: "
               + " · ".join(observed(doc, "what_it_does_not_prove",
                                     kind=list) or []))
    out.append("ADVISORY: прибор только ЧИТАЕТ дерево и артефакты "
               "(applied=False) — ни счётчика, ни читателя, ни гейта он не "
               "правит")
    return out


def format_report(doc: dict, *, max_rows: int = 4) -> List[str]:
    """Сжатая отрисовка для шага 0-офис — правило отрисовки У ПРОИЗВОДИТЕЛЯ.

    Вторая копия правила «как это читать» разошлась бы молча (ADR-220), а
    артефакт без ветки отрисовки читается ВХОЛОСТУЮ: квитанция о потреблении
    есть, а ни одного числа читатель не видит.
    """
    lines = report(doc)
    if str(doc.get("status")) != "MEASURED":
        return lines
    head = [line for line in lines if not line.startswith("   ")]
    rows = [line for line in lines if line.startswith("   ")]
    hidden = max(0, len(rows) - max_rows)
    out = head[:1] + rows[:max_rows]
    if hidden:
        out.append(f"   … и ещё {hidden} раскол(ов) — обрезка ПОКАЗА, не "
                   f"населения (всё в артефакте)")
    return out + head[1:]


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        published: Optional[int] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now, published=published)
    except (NotMeasured, census.NotMeasured) as exc:
        # Третий исход обязан быть ИСХОДОМ на любой глубине, иначе он им не
        # является: трассировка вместо вердикта читается как «упало», а не
        # как «не измерено».
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "order": ORDER,
            "applied": False,
            "reason": str(exc),
            "rows": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") == "MEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("незнакомый класс в артефакте недостижимого раскола "
                     "(заказ G98 п. 1)"))
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    for line in report(outcome["doc"]):
        print(line)
    return 0 if outcome["measured"] else 2


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
