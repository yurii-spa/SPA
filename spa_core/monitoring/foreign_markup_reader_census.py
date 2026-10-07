"""Кто ещё ищет КОНКРЕТНУЮ личность элемента в ЧУЖОЙ разметке — и права ли эта претензия.

Заказ владельца **G103 п. 2** (хвост `ADR-523`, поставлен 30.09, перевыставлялся
тридцатью шестью заказами подряд — G104…G139) дословно:

> «**Класс шире кустодиана: сторож, читающий ЧУЖУЮ разметку по литеральному id.**
> Тот же вред — «искали то, чего страница больше не отдаёт» — не измерен ни у
> одного другого читателя `landing/`. Мерить у ЧИТАТЕЛЯ (кто ищет ``id="…"`` в
> чужом HTML), а не по имени файла; три исхода обязательны.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
`ADR-523` закрыл ОДНОГО читателя — кустодиана сайта, — и `ADR-594` (G103 п. 1)
спросил у живой страницы верность его реестра: из 11 объявлений **3**
опровергнуты, и все три МОЛЧА. Но сам класс кустодианом не исчерпывается:
литеральная личность элемента есть претензия к разметке, которую пишет кто-то
другой, и переезд этой личности ломает читателя БЕЗ ЕДИНОГО СЛОВА ровно тогда,
когда промах читателя не возводится в отказ.

Поэтому прибор мерит ТРИ независимых оси, и складывать их между собой нельзя:

``личность``   литеральна ли искомая личность (:data:`IDENTITY_LITERAL`) или
               она собирается в рантайме и статикой не свёрнута
               (:data:`IDENTITY_UNRESOLVED` — третий исход, не «нет находок»).
``стог``       откуда пришла разметка: сеть · файл · параметр (всё это ЧУЖАЯ
               по построению) · построена ЭТИМ ЖЕ модулем (``own`` — вне
               класса) · не свёрнута (третий исход).
``верность``   несёт ли эту личность хоть один производитель разметки дерева:
               :data:`CONFIRMED` · :data:`REFUTED` · третий исход.

И отдельной, ЧЕТВЁРТОЙ осью — ГРОМКОСТЬ промаха. Она не часть вопроса «права
ли претензия», она часть вопроса «узнаем ли мы, что она неправа»:
опровергнутая претензия у `str.index` поднимает `ValueError` на первом же
прогоне, а та же претензия в `if elem_id in html` молча даёт `False`. Лекарство
у них разное, поэтому и числа разные.

Почему «по читателю», а не по имени файла
---------------------------------------------------------------------------
Заказ требует этого дословно, и требование не формальное. Разведка 07.10 по
ИМЕНИ (литерал ``id="…"`` в файле) дала **60** файлов, из которых подавляющая
часть — ПРОИЗВОДИТЕЛИ разметки (`portal_render`, `tear_sheet_html`,
`export_data`, `build_snapshot`): у них претензии к чужой разметке нет вовсе,
они её пишут. Обратная ошибка того же признака дороже: КУСТОДИАН, то есть
единственный уже известный член класса, в выборку «литерал как аргумент
чтения» **НЕ ПОПАЛ** — его личность живёт в таблице
``SITE_NUMBER_SOURCES``, а чтение идёт `re.search(pattern, html)`, где
`pattern` пришёл из деструктуризации строки таблицы. Признак «литерал рядом с
чтением» объявил бы класс населённым нулём известных членов, то есть ответил бы
на свой вопрос вместо нужного.

Поэтому личность ищется **потоком значения до неподвижной точки** (§
:func:`_module_env`), и деструктуризация контейнера разбирается ПОПОЗИЦИОННО:
``for page, elem_id, pattern, why in table[label]`` обязан связать `pattern`
именно с третьим полем строки, а не со всеми её литералами. Грубое связывание
«все литералы строки — каждому имени» было измерено на разведке и отвергнуто:
оно родило **42** вердикта «ОПРОВЕРГНУТО» из воздуха (личности `view-gone`,
`view-misc`, которых ни один сайт не ищет). Выдуманная находка хуже третьего
исхода: третий исход громкий и чинится, выдуманная находка тратит цикл.

Односторонность — НАЗВАНА ЗАРАНЕЕ, до всякого вердикта
---------------------------------------------------------------------------
* **Оракул — ДЕРЕВО, а не живая страница.** Прибор не ходит в сеть (той же
  дверью, что `ADR-594`: сеть — дверь кустодиана). Поэтому `REFUTED` означает
  «ни один производитель разметки В ДЕРЕВЕ этой личности не пишет», а НЕ «её
  нет на earn-defi.com»: старая сборка на CDN умеет нести id, которого в
  исходниках уже нет — именно это и показали `sl-day`/`sl-gates`/`sl-apy`.
  Обратное тоже верно: `CONFIRMED` не доказывает, что личность доезжает до
  посетителя.
* **Производитель, собирающий личность в рантайме, оракулу невидим.**
  `web_shell` пишет ``id="view-{key}"``; литерала `view-build` в дереве нет
  ВОВСЕ. Называть такую претензию опровергнутой было бы ложью, поэтому у неё
  СВОЙ исход :data:`UNMEASURED_ASSEMBLED` — и он третий, а не «подтверждён».
* **Громкость измерена УЗКО и это объявлено:** громким признаётся промах,
  который поднимает исключение ПО ПОСТРОЕНИЮ (`str.index`, `.remove`) либо
  стоит прямо под `assert`. Всё остальное — :data:`LOUDNESS_UNMEASURED`, а не
  «молча»: назвать молчаливым непросмотренный путь значило бы выдать
  неизмеренное за находку.
* **Прибор ничего не чинит** (``applied=False``). Ни одной страницы
  `landing/**`, ни одного сторожа, ни одного вердикта он не правит; предмет №2
  границы `ADR-285` не задет.
* **Он не судит, ПРАВ ли читатель по существу** — только права ли его претензия
  к личности элемента.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import collections
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

ARTIFACT = "foreign_markup_reader_census.json"
PRODUCER = "spa_core/monitoring/foreign_markup_reader_census.py"
ORDER = "G103 п. 2 (хвост ADR-523)"

#: ЕДИНСТВЕННЫЙ член класса, который уже был известен (ADR-523/ADR-594). Имя
#: названо КОНСТАНТОЙ, чтобы контроль «признак нашёл известного члена» мог
#: спросить о нём, а не искать его глазами.
REGISTRY_READER = "scripts/site_freshness_monitor.py"

#: Каталоги кода, в которых ищутся ЧИТАТЕЛИ. `landing/` здесь нет намеренно:
#: там живёт разметка, а не её читатели, и она попадает в ОРАКУЛ.
CODE_ROOTS = ("spa_core", "scripts", "studio_shell", "cabinet", "research",
              "tests", "landing")

#: Расширения, которые считаются РАЗМЕТКОЙ (оракул «кто пишет личность»).
MARKUP_SUFFIXES = (".astro", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx",
                   ".svelte", ".vue")

#: Проза (`.md`) производителем НЕ является — она личность НАЗЫВАЕТ. Первая
#: редакция считала её разметкой, и в ту же минуту текст ЭТОГО решения
#: «подтвердил» ровно те две личности, которые оно опровергает
#: (`spa-freshness-banner`, `spa-hero-asof` ушли из находки, потому что
#: `docs/decisions/ADR-620-*.md` их упоминает). `docs/` полон таких упоминаний,
#: и это самый дорогой fail-OPEN класса: разбор находки ОТМЕНЯЕТ находку.
#: Проза считается производителем ТОЛЬКО под корнем, который отдаёт страницы
#: (`landing/`): там `.mdx` — настоящая страница, а не разбор.
PROSE_SUFFIXES = (".md", ".mdx")
PAGE_SERVING_ROOTS = ("landing",)

#: Каталоги, не принадлежащие дереву как источнику.
SKIP_PARTS = ("node_modules", ".git", "dist", ".astro", "__pycache__",
              ".pytest_cache", ".venv", "site-packages")

#: ФОРМЫ ССЫЛКИ НА ЛИЧНОСТЬ ЭЛЕМЕНТА. Перечень УЗКИЙ и объявленный: форма вне
#: него прибору невидима, и это сказано вслух, а не оставлено свойством
#: реализации. `class=`/`data-*` сюда НЕ входят — они адресуют множество, а
#: заказ говорит про личность.
IDENTITY_PATTERNS = (
    ("attribute", re.compile(
        r'''(?<![\w-])id\s*=\s*(\\?["'])([A-Za-z][\w:.\-]*)\1''')),
    ("getElementById", re.compile(
        r'''getElementById\(\s*(\\?["'])([A-Za-z][\w:.\-]*)\1''')),
    ("querySelector", re.compile(
        r'''querySelector(?:All)?\(\s*(\\?["'])#([A-Za-z][\w:.\-]*)\1''')),
)

#: Отсылка к личности БЕЗ закрытой кавычки: имя обрывается, и полную личность
#: собирает рантайм. Отдельный исход, а не «нет ссылки»: `web_shell` пишет
#: ``id="view-{key}"``, и объявить такой сайт беспредметным значило бы потерять
#: члена класса, чью претензию просто нельзя проверить статикой.
_PREFIX_REF = re.compile(r'''(?<![\w-])id\s*=\s*\\?["\']([A-Za-z][\w:.\-]*)(?!\\?["\'])''')

#: Признак того, что личность в литерале НЕ литеральна: на её месте стоит
#: регекспный класс или подставленное значение. Такой литерал есть ПЕРЕЧИСЛИТЕЛЬ
#: («дай мне все id»), а не претензия к одной личности, и в класс он не входит.
_ENUMERATING = re.compile(r'''(?<![\w-])id\s*=\s*\\?["']?[\[({]''')

#: Функции модуля `re`, у которых стог — ВТОРОЙ аргумент.
RE_SEARCH_FUNCS = ("search", "match", "fullmatch", "findall", "finditer",
                   "sub", "subn", "split")
#: Методы скомпилированного шаблона, у которых стог — ПЕРВЫЙ аргумент.
RX_SEARCH_METHODS = RE_SEARCH_FUNCS
#: Методы строки-стога, у которых иголка — первый аргумент.
STR_SEARCH_METHODS = ("count", "find", "rfind", "index", "split", "partition",
                      "rpartition", "startswith", "endswith")
#: Методы строки, промах которых поднимает исключение ПО ПОСТРОЕНИЮ.
RAISING_METHODS = ("index", "rindex", "remove")

# ── ось 1: личность ────────────────────────────────────────────────────────
IDENTITY_LITERAL = "the_identity_is_spelled_as_a_literal"
IDENTITY_UNRESOLVED = "the_identity_is_assembled_and_did_not_fold_statically"
#: Литерал просит ВСЕ личности разом (``id="([A-Za-z0-9_-]+)"``). Претензии к
#: ОДНОЙ личности у него нет, значит и неправым о ней он быть не может — вне
#: класса. Это НЕ третий исход: третий исход говорит «не знаю», а здесь
#: известно точно, что предмета нет.
IDENTITY_ENUMERATING = "the_literal_asks_for_every_identity_not_one"
#: Ссылка на личность есть, но имя не закрыто кавычкой: ``id="view-`` —
#: литерал несёт ПРЕФИКС, а полную личность собирают в рантайме.
IDENTITY_TRUNCATED = "the_identity_is_a_prefix_and_is_completed_at_runtime"
_IDENTITY_OUTCOMES = (IDENTITY_LITERAL, IDENTITY_UNRESOLVED,
                      IDENTITY_ENUMERATING, IDENTITY_TRUNCATED)

# ── ось 2: стог ────────────────────────────────────────────────────────────
HAY_NETWORK = "the_markup_came_over_the_network"
HAY_FILE = "the_markup_was_read_from_a_file"
HAY_PARAMETER = "the_markup_arrived_as_a_parameter"
#: Разметку ВЕРНУЛ ВЫЗОВ, перешагнувший границу модуля (вызов функции другого
#: модуля). Четвёртая дверь наружу, и в живом дереве она САМАЯ населённая:
#: замер 07.10 — без неё 19 сайтов из 49 уходили в «происхождение не
#: свёрнуто», то есть настоящие члены класса (тесты картографа, читающие
#: страницу, которую рисует `portal_render`/`web_shell`) объявлялись
#: неизмеренными. Вызов функции ЭТОГО ЖЕ модуля сюда НЕ входит: такой
#: результат модуль умеет собрать из своих литералов, и звать его чужим
#: значило бы угадывать.
HAY_PRODUCER_CALL = "the_markup_was_returned_by_a_call_across_a_module_border"
HAY_OWN = "the_markup_was_built_by_this_very_module"
HAY_UNRESOLVED = "the_origin_of_the_markup_did_not_fold_statically"
#: Чужой по построению — три двери наружу. `own` в класс НЕ входит, `unresolved`
#: входит как ТРЕТИЙ исход, а не как «чужой».
FOREIGN_ORIGINS = (HAY_NETWORK, HAY_FILE, HAY_PARAMETER, HAY_PRODUCER_CALL)

# ── ось 3: верность претензии ──────────────────────────────────────────────
#: Личность пишет ФАЙЛ РАЗМЕТКИ (`landing/**`, `.astro`, `.html`, `.js`…).
#: Сильнейшее подтверждение, доступное дереву.
CONFIRMED = "a_markup_file_in_the_tree_writes_this_identity"
#: Личность пишет python-модуль, который НЕ ввозит читателя. Тоже настоящий
#: производитель — часть страниц дерева собирает python (`tear_sheet_html`,
#: `portal_render`), — но слабее файла разметки, и сказано это отдельно.
CONFIRMED_BY_PYTHON = "only_a_python_producer_writes_this_identity"
#: ЛИЧНОСТЬ ЖИВЁТ ТОЛЬКО В СЦЕНЕ САМОГО ЧИТАТЕЛЯ: её пишут лишь модули,
#: ввозящие читателя (его фикстуры), и ни один файл разметки. Это НЕ
#: подтверждение, а претензия, подтверждающая себя своей же копией, — и
#: вред у неё тот же, что у опровергнутой. Положительный контроль этого
#: исхода — `sl-day`/`sl-gates`/`sl-apy`: `ADR-594` ЖИВЫМ запросом назвал их
#: опровергнутыми, а первая редакция ЭТОГО прибора объявила подтверждёнными,
#: потому что их пишут `test_site_freshness_monitor.py` и
#: `test_site_shelf_is_the_operand.py` — фикстуры того самого кустодиана.
ECHOED_BY_OWN_SCENE = "only_the_readers_own_scene_writes_this_identity"
REFUTED = "no_producer_in_the_tree_writes_this_identity"
UNMEASURED_ASSEMBLED = "a_producer_assembles_this_identity_at_runtime"
UNMEASURED_NO_ORACLE = "no_markup_was_readable_so_the_oracle_is_empty"
UNMEASURED_IDENTITY = "the_identity_itself_is_unresolved_so_nothing_is_judged"
_PARITY_OUTCOMES = (CONFIRMED, CONFIRMED_BY_PYTHON, ECHOED_BY_OWN_SCENE,
                    REFUTED, UNMEASURED_ASSEMBLED, UNMEASURED_NO_ORACLE,
                    UNMEASURED_IDENTITY)
#: Исходы, при которых претензия НЕ подтверждена ничем, кроме себя. Считаются
#: ОДНИМ числом вреда — лекарство у них одно (посмотреть на живую страницу),
#: а у подтверждённых его нет вовсе.
UNSUPPORTED_OUTCOMES = (REFUTED, ECHOED_BY_OWN_SCENE)

# ── ось 4: громкость промаха ───────────────────────────────────────────────
LOUD_RAISES = "a_miss_raises_by_construction"
LOUD_ASSERTED = "a_miss_fails_an_assert"
SILENT_MEMBERSHIP = "a_miss_yields_a_falsy_value_and_says_nothing"
LOUDNESS_UNMEASURED = "the_fate_of_a_miss_was_not_traced"
#: Промах возводится в отказ — НО весь модуль умеет скипнуть себя на импорте
#: (``pytest.skip(..., allow_module_level=True)``). Тогда «громко» сказано о
#: пути, которого может не быть вовсе, и назвать это громким без оговорки
#: значило бы выдать НЕ ИЗМЕРЕННОЕ за пройденное (инв. #17, урок #465).
LOUD_BEHIND_MODULE_SKIP = "a_miss_raises_but_the_module_can_skip_itself_whole"
_LOUDNESS_OUTCOMES = (LOUD_RAISES, LOUD_ASSERTED, LOUD_BEHIND_MODULE_SKIP,
                      SILENT_MEMBERSHIP, LOUDNESS_UNMEASURED)

# ── отказы САМОГО шага. Ни один не есть «ноль находок» ─────────────────────
GAP_NO_TREE = "the_tree_root_does_not_exist"
GAP_NO_CODE = "not_a_single_python_file_was_parsed"


class NotMeasured(RuntimeError):
    """Отказ шага: предпосылка не обеспечена. Третий исход, не вердикт."""

    def __init__(self, gap: str, why: str) -> None:
        super().__init__(f"{gap}: {why}")
        self.gap = gap
        self.why = why


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _skipped(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


# ───────────────────────── поток значения до неподвижной точки ─────────────

#: Метка подставленного значения внутри f-строки. Без неё `f'id="view-{key}"'`
#: склеивается в `id="view-"` — и регексп, требующий закрытой кавычки, читает
#: ВЫДУМАННУЮ личность `view-`. Замер 07.10: именно так родился третий
#: «опровергнутый» в первой редакции прибора. Символ выбран невозможный в
#: имени элемента, поэтому склейка через него не закрывается никогда.
INTERPOLATION_MARK = "\x00"


def _joined_text(node: ast.JoinedStr) -> str:
    """Текст f-строки с МЕТКОЙ на месте каждой подстановки."""
    parts: List[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append(INTERPOLATION_MARK)
    return "".join(parts)


def _literals(node: ast.AST, env: Dict[str, Set[str]], depth: int = 0
              ) -> Set[str]:
    """Строковые литералы, из которых МОЖЕТ состоять значение узла.

    Мера над-приблизительная ПО НАПРАВЛЕНИЮ: лишний литерал делает личность
    кандидатом, пропущенный делает члена класса невидимым. Выбрано первое —
    но только для ПОИСКА сайта; вердикт по личности выносится уже после
    попозиционного разбора (см. :func:`_rows_of`).
    """
    if depth > 8:
        return set()
    out: Set[str] = set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.add(node.value)
    elif isinstance(node, ast.JoinedStr):
        out.add(_joined_text(node))
    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for elt in node.elts:
            out |= _literals(elt, env, depth + 1)
    elif isinstance(node, ast.Dict):
        for elt in list(node.values) + [k for k in node.keys if k is not None]:
            out |= _literals(elt, env, depth + 1)
    elif isinstance(node, ast.BinOp):
        out |= _literals(node.left, env, depth + 1)
        out |= _literals(node.right, env, depth + 1)
    elif isinstance(node, ast.IfExp):
        out |= _literals(node.body, env, depth + 1)
        out |= _literals(node.orelse, env, depth + 1)
    elif isinstance(node, ast.Starred):
        out |= _literals(node.value, env, depth + 1)
    elif isinstance(node, ast.Name):
        out |= env.get(node.id, set())
    elif isinstance(node, ast.Subscript):
        # ЭЛЕМЕНТ контейнера, связанного ИМЕНЕМ, литералами контейнера НЕ
        # является. Это та же утечка, что у грубой деструктуризации (дефект 2),
        # только через индекс: `row["identity"]` в батарее этого же прибора
        # наследовал ВСЕ литералы файла и давал два выдуманных опровержения
        # (`ghost`, `hero-day` — замер 07.10). Литеральный контейнер прямо
        # на месте разбирается по-прежнему.
        if not isinstance(node.value, ast.Name):
            out |= _literals(node.value, env, depth + 1)
    elif isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in (
                "get", "items", "values", "keys", "copy"):
            out |= _literals(func.value, env, depth + 1)
        for arg in node.args:
            out |= _literals(arg, env, depth + 1)
    return out


def _rows_of(node: ast.AST, env: Dict[str, Set[str]],
             rows: Dict[str, List[Tuple[Set[str], ...]]], depth: int = 0
             ) -> Optional[List[Tuple[Set[str], ...]]]:
    """Строки контейнера ПОПОЗИЦИОННО, если контейнер свернулся статикой.

    `None` — не свернулся. Это и есть граница, за которой личность уходит в
    :data:`IDENTITY_UNRESOLVED`, а не угадывается по соседним литералам.
    """
    if depth > 6:
        return None
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out: List[Tuple[Set[str], ...]] = []
        for elt in node.elts:
            if isinstance(elt, (ast.Tuple, ast.List)):
                out.append(tuple(_literals(e, env, depth + 1)
                                 for e in elt.elts))
            else:
                return None
        return out or None
    if isinstance(node, ast.Dict):
        out = []
        for val in node.values:
            sub = _rows_of(val, env, rows, depth + 1)
            if sub is None:
                return None
            out.extend(sub)
        return out or None
    if isinstance(node, ast.Name):
        return rows.get(node.id)
    if isinstance(node, ast.IfExp):
        return (_rows_of(node.body, env, rows, depth + 1)
                or _rows_of(node.orelse, env, rows, depth + 1))
    if isinstance(node, ast.Subscript):
        return _rows_of(node.value, env, rows, depth + 1)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in ("get", "values", "copy"):
            return _rows_of(node.func.value, env, rows, depth + 1)
        if node.func.attr == "items":
            # `for k, v in d.items()` — вторая позиция есть значение словаря
            sub = _rows_of(node.func.value, env, rows, depth + 1)
            return None if sub is None else [(set(), *row) for row in sub]
    return None


def _target_names(target: ast.AST) -> List[Optional[str]]:
    """Имена цели присваивания В ПОРЯДКЕ позиций. `None` — позиция не имя."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: List[Optional[str]] = []
        for elt in target.elts:
            out.append(elt.id if isinstance(elt, ast.Name) else None)
        return out
    return [None]


def _bindings(tree: ast.AST) -> Tuple[Dict[str, Set[str]],
                                      Dict[str, List[Tuple[Set[str], ...]]],
                                      Dict[str, Set[str]]]:
    """Три карты модуля, до неподвижной точки.

    ``env``       имя → литералы, которые его значение МОЖЕТ нести;
    ``rows``      имя → строки контейнера попозиционно (если свернулся);
    ``positional`` имя → литералы ТОЛЬКО своей позиции в деструктуризации.

    Третья карта и есть противоядие от выдуманной находки: вердикт по личности
    берётся из неё, а не из ``env``.
    """
    env: Dict[str, Set[str]] = collections.defaultdict(set)
    rows: Dict[str, List[Tuple[Set[str], ...]]] = {}
    positional: Dict[str, Set[str]] = collections.defaultdict(set)
    destructured: Set[str] = set()

    def pairs(node: ast.AST):
        if isinstance(node, ast.Assign):
            return node.targets, node.value, False
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            return [node.target], node.value, False
        if isinstance(node, (ast.For, ast.AsyncFor)):
            return [node.target], node.iter, True
        if isinstance(node, ast.comprehension):
            return [node.target], node.iter, True
        if isinstance(node, ast.withitem) and node.optional_vars is not None:
            return [node.optional_vars], node.context_expr, False
        return None

    nodes = list(ast.walk(tree))
    for _ in range(8):
        grew = False
        for node in nodes:
            got = pairs(node)
            if got is None:
                continue
            targets, value, is_loop = got
            lits = _literals(value, env)
            container = _rows_of(value, env, rows) if is_loop else None
            for target in targets:
                names = _target_names(target)
                # попозиционно — только когда контейнер свернулся И арность
                # цели совпадает с арностью строк. Иначе позиции НЕТ, и
                # угадывать её запрещено.
                if container and len(names) > 1 and all(
                        len(row) == len(names) for row in container):
                    for idx, name in enumerate(names):
                        if name is None:
                            continue
                        destructured.add(name)
                        got_lits = set().union(*[row[idx] for row in container])
                        if not got_lits <= positional[name]:
                            positional[name] |= got_lits
                            grew = True
                        if not got_lits <= env[name]:
                            env[name] |= got_lits
                            grew = True
                    continue
                if len(names) > 1 and is_loop:
                    # деструктуризация без свёрнутого контейнера: имена
                    # помечаются неразрешёнными, литералы в env НЕ подставляются
                    for name in names:
                        if name:
                            destructured.add(name)
                    continue
                for name in names:
                    if name is None:
                        continue
                    if lits and not lits <= env[name]:
                        env[name] |= lits
                        grew = True
                    if lits and name not in destructured and \
                            not lits <= positional[name]:
                        positional[name] |= lits
                        grew = True
                    sub = _rows_of(value, env, rows)
                    if sub is not None and rows.get(name) != sub:
                        rows[name] = sub
                        grew = True
        if not grew:
            break
    return env, rows, positional


def _module_env(source: str):
    """Разобрать модуль и вернуть `(tree, env, rows, positional)`."""
    tree = ast.parse(source)
    env, rows, positional = _bindings(tree)
    return tree, env, rows, positional


# ───────────────────────── личность в литерале ─────────────────────────────

def identities_in(text: str) -> List[Tuple[str, str]]:
    """`[(форма, личность)]`, названные этим текстом. Перечислители — пусто."""
    out: List[Tuple[str, str]] = []
    for form, rx in IDENTITY_PATTERNS:
        for match in rx.finditer(text):
            out.append((form, match.group(2)))
    return out


def _is_enumerating(text: str) -> bool:
    """Литерал просит ВСЕ личности, а не одну. В класс не входит."""
    return bool(_ENUMERATING.search(text))


def _identity_claims(texts: Iterable[str]
                     ) -> Tuple[List[Tuple[str, str]], bool, bool]:
    """`(личности, был ли перечислитель, был ли префикс)`.

    Три ответа, а не два: перечислитель предмета НЕ ИМЕЕТ (вне класса), а
    префикс имеет предмет, который статикой не проверить (третий исход).
    Свалить их в одно «личности нет» значило бы стереть эту разницу.
    """
    claims: List[Tuple[str, str]] = []
    enumerating = False
    prefix = False
    for text in texts:
        found = identities_in(text)
        claims.extend(found)
        if _is_enumerating(text):
            enumerating = True
        if not found and _PREFIX_REF.search(text):
            prefix = True
    return claims, enumerating, prefix


# ───────────────────────── происхождение стога ─────────────────────────────

_NETWORK_NAMES = ("urlopen", "urlretrieve", "requests", "HTTPSConnection",
                  "HTTPConnection", "http_get", "fetch")
_FILE_NAMES = ("read_text", "read_bytes", "readlines", "open")


def _local_functions(tree: ast.AST) -> Set[str]:
    """Имена функций, определённых В ЭТОМ модуле (любой уровень)."""
    return {node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _origin_of(node: ast.AST, tree: ast.AST, scope_args: Set[str],
               depth: int = 0, local: Optional[Set[str]] = None) -> str:
    """Откуда пришла разметка. Четыре двери наружу, своя, и третий исход."""
    if local is None:
        local = _local_functions(tree)
    if depth > 8:
        return HAY_UNRESOLVED
    if isinstance(node, ast.Constant) or isinstance(node, ast.JoinedStr):
        return HAY_OWN
    if isinstance(node, ast.Name):
        if node.id in scope_args:
            return HAY_PARAMETER
        return _origin_of_name(node.id, tree, scope_args, depth + 1, local)
    if isinstance(node, ast.Attribute):
        return _origin_of(node.value, tree, scope_args, depth + 1, local)
    if isinstance(node, ast.Subscript):
        return _origin_of(node.value, tree, scope_args, depth + 1, local)
    if isinstance(node, ast.BinOp):
        left = _origin_of(node.left, tree, scope_args, depth + 1, local)
        right = _origin_of(node.right, tree, scope_args, depth + 1, local)
        for origin in FOREIGN_ORIGINS:
            if origin in (left, right):
                return origin
        return left if left == right else HAY_UNRESOLVED
    if isinstance(node, ast.BoolOp):
        # `(pages or {}).get(page)` — форма кустодиана. Чужая дверь одного из
        # операндов делает чужим всё выражение: защита от `None` источник не
        # меняет.
        seen = [_origin_of(v, tree, scope_args, depth + 1, local)
                for v in node.values]
        for origin in FOREIGN_ORIGINS:
            if origin in seen:
                return origin
        return seen[0] if len(set(seen)) == 1 else HAY_UNRESOLVED
    if isinstance(node, ast.IfExp):
        branches = (_origin_of(node.body, tree, scope_args, depth + 1, local),
                    _origin_of(node.orelse, tree, scope_args, depth + 1, local))
        for origin in FOREIGN_ORIGINS:
            if origin in branches:
                return origin
        return branches[0] if branches[0] == branches[1] else HAY_UNRESOLVED
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name in _NETWORK_NAMES:
            return HAY_NETWORK
        if name in _FILE_NAMES:
            return HAY_FILE
        if name in ("read", "text", "decode") and isinstance(
                node.func, ast.Attribute):
            inner = _origin_of(node.func.value, tree, scope_args, depth + 1, local)
            return HAY_FILE if inner == HAY_UNRESOLVED else inner
        if name in ("join", "format", "strip", "lower", "upper", "replace",
                    "get", "pop", "setdefault"):
            if isinstance(node.func, ast.Attribute):
                return _origin_of(node.func.value, tree, scope_args,
                                  depth + 1, local)
        # ВЫЗОВ, ПЕРЕШАГНУВШИЙ ГРАНИЦУ МОДУЛЯ. Функция ЭТОГО модуля сюда не
        # попадает: её результат модуль умеет собрать сам, и чужим его звать
        # нельзя — это была бы догадка, а не замер.
        if name is not None and name not in local:
            return HAY_PRODUCER_CALL
        return HAY_UNRESOLVED
    return HAY_UNRESOLVED


def _call_name(func: ast.AST) -> Optional[str]:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _origin_of_name(name: str, tree: ast.AST, scope_args: Set[str],
                    depth: int, local: Optional[Set[str]] = None) -> str:
    """Происхождение ИМЕНИ: ищется ближайшее присваивание ему в модуле."""
    seen: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            targets, value = [node.optional_vars], node.context_expr
        else:
            continue
        if name not in [n for t in targets for n in _target_names(t) if n]:
            continue
        origin = _origin_of(value, tree, scope_args, depth + 1, local)
        seen.add(origin)
    for origin in FOREIGN_ORIGINS:
        if origin in seen:
            return origin
    if seen == {HAY_OWN}:
        return HAY_OWN
    return HAY_UNRESOLVED


def _enclosing_args(tree: ast.AST) -> Dict[int, Set[str]]:
    """lineno → имена параметров объемлющей функции."""
    out: Dict[int, Set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        names = {a.arg for a in list(args.posonlyargs) + list(args.args)
                 + list(args.kwonlyargs)}
        if args.vararg:
            names.add(args.vararg.arg)
        if args.kwarg:
            names.add(args.kwarg.arg)
        for inner in ast.walk(node):
            line = getattr(inner, "lineno", None)
            if line is not None:
                out.setdefault(line, set()).update(names)
    return out


# ───────────────────────── сайты чтения ────────────────────────────────────

def _compiled_patterns(tree: ast.AST, env: Dict[str, Set[str]]
                       ) -> Dict[str, Set[str]]:
    """имя → литералы шаблона, если имя связано `re.compile(...)`."""
    out: Dict[str, Set[str]] = collections.defaultdict(set)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not (isinstance(value, ast.Call)
                and _call_name(value.func) == "compile" and value.args):
            continue
        lits = _literals(value.args[0], env)
        for target in targets:
            for name in _target_names(target):
                if name:
                    out[name] |= lits
    return out


def _read_sites(tree: ast.AST, env, positional, compiled):
    """`[(узел, форма, узел-иголка, узел-стог, литералы-иголки)]`."""
    sites = []

    def needle_literals(node: ast.AST) -> Set[str]:
        """Литералы иголки — ПОПОЗИЦИОННЫЕ, если имя деструктурировано."""
        if isinstance(node, ast.Name):
            if node.id in compiled and compiled[node.id]:
                return compiled[node.id]
            return set(positional.get(node.id, set()))
        return _literals(node, env)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            owner = func.value
            if (func.attr in RE_SEARCH_FUNCS and isinstance(owner, ast.Name)
                    and owner.id == "re" and len(node.args) >= 2):
                sites.append((node, f"re.{func.attr}", node.args[0],
                              node.args[1], needle_literals(node.args[0])))
            elif (func.attr in RX_SEARCH_METHODS and len(node.args) >= 1
                  and isinstance(owner, ast.Name) and owner.id in compiled):
                sites.append((node, f"compiled.{func.attr}", owner,
                              node.args[0], needle_literals(owner)))
            elif (func.attr in STR_SEARCH_METHODS and len(node.args) >= 1
                  and not isinstance(owner, (ast.Constant, ast.JoinedStr))):
                sites.append((node, f"str.{func.attr}", node.args[0],
                              owner, needle_literals(node.args[0])))
        elif isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            sites.append((node, "in", node.left, node.comparators[0],
                          needle_literals(node.left)))
    return sites


def _loudness(node: ast.AST, form: str, asserted_lines: Set[int],
              module_skips: bool = False) -> str:
    """Судьба промаха — УЗКО и объявленно.

    Оговорка про модульный скип БЬЁТ громкость, а не дополняет её: сайт,
    чей модуль умеет исчезнуть целиком, громким называть нельзя — его отказ
    может не наступить ни разу.
    """
    loud = None
    if form.startswith("str.") and form.split(".", 1)[1] in RAISING_METHODS:
        loud = LOUD_RAISES
    else:
        line = getattr(node, "lineno", None)
        if line is not None and line in asserted_lines:
            loud = LOUD_ASSERTED
    if loud is not None:
        return LOUD_BEHIND_MODULE_SKIP if module_skips else loud
    if form == "in":
        return SILENT_MEMBERSHIP
    return LOUDNESS_UNMEASURED


def _module_level_skip(tree: ast.AST) -> bool:
    """Умеет ли модуль снять себя целиком на импорте.

    Форма УЗКАЯ и объявленная: `pytest.skip(..., allow_module_level=True)` на
    верхнем уровне модуля. Условие скипа прибор НЕ разбирает и не утверждает,
    что он срабатывает СЕГОДНЯ — он утверждает лишь, что такой путь есть, и
    поэтому «громко» у этого сайта идёт с оговоркой.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) != "skip":
            continue
        for kw in node.keywords:
            if kw.arg == "allow_module_level" and isinstance(
                    kw.value, ast.Constant) and kw.value.value is True:
                return True
    return False


def _assert_lines(tree: ast.AST) -> Set[int]:
    out: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for inner in ast.walk(node.test):
                line = getattr(inner, "lineno", None)
                if line is not None:
                    out.add(line)
    return out


def scan_module(rel_path: str, source: str) -> List[dict]:
    """Сайты чтения ОДНОГО модуля. Нераспознанный исходник — пустой список."""
    try:
        tree, env, _rows, positional = _module_env(source)
    except SyntaxError:
        return []
    compiled = _compiled_patterns(tree, env)
    asserted = _assert_lines(tree)
    args_at = _enclosing_args(tree)
    module_skips = _module_level_skip(tree)
    out: List[dict] = []
    for node, form, needle, hay, lits in _read_sites(
            tree, env, positional, compiled):
        claims, enumerating, prefix = _identity_claims(lits)
        if not (claims or enumerating or prefix):
            continue        # ссылки на личность нет вовсе — не наш класс
        line = getattr(node, "lineno", 0)
        scope_args = args_at.get(line, set())
        origin = _origin_of(hay, tree, scope_args)
        base = {
            "file": rel_path,
            "line": line,
            "form": form,
            "haystack": ast.unparse(hay)[:80],
            "haystack_origin": origin,
            "module_level_skip": module_skips,
            "loudness": _loudness(node, form, asserted, module_skips),
        }
        for identity_form, identity in sorted(set(claims)):
            out.append({**base, "identity": identity,
                        "identity_form": identity_form,
                        "identity_outcome": IDENTITY_LITERAL})
        if claims:
            continue
        # предмета нет (перечислитель) ИЛИ есть, но не свёрнут (префикс).
        # Порядок проверки — префикс ПЕРВЫМ: литерал умеет быть и тем и другим,
        # а префикс несёт предмет, значит и исход у него должен быть его.
        outcome = IDENTITY_TRUNCATED if prefix else IDENTITY_ENUMERATING
        out.append({**base, "identity": None, "identity_form": None,
                    "identity_outcome": outcome})
    return out


# ───────────────────────── оракул: кто ПИШЕТ личность ──────────────────────

def build_oracle(root: Path) -> Tuple[Dict[str, Set[str]], Set[str], int]:
    """`(личность → файлы-производители, собираемые префиксы, файлов прочитано)`.

    Собираемый префикс — личность, записанная в разметке с подстановкой
    (``id="view-{key}"``). Он не подтверждает и не опровергает НИЧЕГО; он
    переводит вердикт в третий исход.
    """
    produced: Dict[str, Set[str]] = collections.defaultdict(set)
    prefixes: Set[str] = set()
    seen = 0
    assembled = re.compile(
        r'''(?<![\w-])id\s*=\s*\\?["']([A-Za-z][\w:.\-]*)?[-_]?[{$]''')
    for path in root.rglob("*"):
        if not path.is_file() or _skipped(path):
            continue
        suffix = path.suffix.lower()
        if suffix in PROSE_SUFFIXES:
            if not any(part in PAGE_SERVING_ROOTS for part in path.parts):
                continue        # проза НАЗЫВАЕТ личность, а не пишет её
        elif suffix not in MARKUP_SUFFIXES:
            continue
        seen += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        for form, rx in IDENTITY_PATTERNS:
            for match in rx.finditer(text):
                produced[match.group(2)].add(rel)
        for match in assembled.finditer(text):
            if match.group(1):
                prefixes.add(match.group(1))
    return produced, prefixes, seen


def _referenced_modules(source: str) -> Set[str]:
    """На какие модули файл СОСЛАЛСЯ — ТРИ объявленные формы, не одна.

    Одной (статический ввоз) НЕ ХВАТАЕТ, и это измерено: фикстура кустодиана
    `test_site_freshness_monitor.py` грузит его через
    ``importlib.util.spec_from_file_location`` — статического ввоза нет
    ВОВСЕ, и по одной форме сцена читателя выглядела бы независимым
    производителем (замер 07.10: так `sl-day`/`sl-gates`/`sl-apy` ушли из
    исхода «только своя сцена» в «подтверждено python-производителем», то
    есть ровно в тот fail-OPEN, который прибор и ловит).

    Формы: (1) `import`/`from … import`; (2) имя модуля внутри СТРОКОВОГО
    литерала (путь в `spec_from_file_location`, `Path("scripts/…")`);
    (3) путь файла внутри строкового литерала. Ошибка этой меры лежит в
    сторону ЭХА, а не в сторону подтверждения, и направление выбрано
    намеренно: ложное подтверждение прячет вред, ложное эхо его преувеличивает.
    """
    out: Set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.update(node.module.split("."))
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for part in re.split(r"[^\w.]+", node.value):
                if not part:
                    continue
                out.add(part[:-3] if part.endswith(".py") else part)
                out.update(part.split("."))
    return out


def _python_producers(code_files: Sequence[Tuple[str, str]],
                      read_identities: Dict[str, Set[str]]
                      ) -> Tuple[Dict[str, Set[str]], Set[str],
                                 Dict[str, Set[str]], Set[str]]:
    """`(личность → python-производители, префиксы, ссылки, своя сцена)`.

    Python тоже ПИШЕТ разметку (`portal_render`, `tear_sheet_html`), поэтому
    оракул без него объявил бы читателей этих страниц неподтверждёнными.

    Производителем считается литерал ВНЕ сайта чтения ЭТОГО ЖЕ файла: иначе
    таблица кустодиана, из которой он и читает, подтверждала бы сама себя.
    """
    produced: Dict[str, Set[str]] = collections.defaultdict(set)
    prefixes: Set[str] = set()
    references: Dict[str, Set[str]] = {}
    own_scene: Set[str] = set()
    self_name = Path(PRODUCER).stem
    assembled = re.compile(
        r'''(?<![\w-])id\s*=\s*\\?["\']([A-Za-z][\w:.\-]*)?[-_]?[{%]''')
    for rel, source in code_files:
        references[rel] = _referenced_modules(source)
        # ПРИБОР ЖИВЁТ В НАСЕЛЕНИИ, КОТОРОЕ МЕРИТ. Его батареи пишут
        # синтетическую разметку (`id="hero-day"`, `id="m-days"`), и зачесть
        # её в оракул значило бы разрешить фикстурам ПРИБОРА подтверждать
        # претензии ТРЕТЬИХ читателей — тот же вред, что `ECHOED_BY_OWN_SCENE`,
        # но на уровень выше. Отбор структурный, по ССЫЛКЕ на прибор, не по
        # имени файла; число таких файлов печатается полем, иначе доставка
        # прибора молча меняла бы ответ о дереве (урок #776).
        if rel != PRODUCER and self_name in references[rel]:
            # В поле попадает только файл, который РЕАЛЬНО ВЗНЁС БЫ личность:
            # ступень моста и секция офиса ссылаются на прибор по проводке и
            # разметки не несут, и перечислить их как «исключённую сцену»
            # значило бы напечатать исключение, которого не было.
            if any(rx.search(source) for _f, rx in IDENTITY_PATTERNS):
                own_scene.add(rel)
            continue
        own_reads = read_identities.get(rel, set())
        for _form, rx in IDENTITY_PATTERNS:
            for match in rx.finditer(source):
                identity = match.group(2)
                if identity in own_reads:
                    continue        # свой же сайт чтения — не производитель
                produced[identity].add(rel)
        for match in assembled.finditer(source):
            if match.group(1):
                prefixes.add(match.group(1))
    return produced, prefixes, references, own_scene


def _module_basenames(rel_path: str) -> Set[str]:
    """Имена, под которыми модуль может быть НАЗВАН (без догадок о смысле).

    Каталоги в набор НЕ входят: `scripts` ссылкой на читателя не является, и
    включать его значило бы объявить эхом каждый файл, где это слово
    встретилось. В набор идёт только собственное имя модуля.
    """
    stem = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    return {stem.split("/")[-1], stem}


def _parity(row: dict, markup: Dict[str, Set[str]],
            python_produced: Dict[str, Set[str]],
            references: Dict[str, Set[str]], prefixes: Set[str],
            oracle_files: int) -> str:
    """Вердикт по ОДНОЙ претензии. Подтверждения разной силы НЕ сливаются."""
    if row["identity_outcome"] != IDENTITY_LITERAL:
        return UNMEASURED_IDENTITY
    if oracle_files == 0:
        return UNMEASURED_NO_ORACLE
    identity = row["identity"]
    if set(markup.get(identity, ())) - {row["file"]}:
        return CONFIRMED
    writers = set(python_produced.get(identity, ())) - {row["file"]}
    if writers:
        # СЦЕНА ЧИТАТЕЛЯ или настоящий производитель? Вопрос решается ввозом:
        # модуль, ввозящий читателя, пишет разметку ДЛЯ НЕГО, и его согласие
        # есть копия претензии, а не её подтверждение.
        reader_names = _module_basenames(row["file"])
        outsiders = [w for w in writers
                     if not (references.get(w, set()) & reader_names)]
        return CONFIRMED_BY_PYTHON if outsiders else ECHOED_BY_OWN_SCENE
    if any(identity.startswith(prefix) and identity != prefix
           for prefix in prefixes):
        return UNMEASURED_ASSEMBLED
    return REFUTED


def _code_files(root: Path) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for name in CODE_ROOTS:
        base = root / name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if _skipped(path):
                continue
            try:
                out.append((str(path.relative_to(root)),
                            path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return out


# ───────────────────────── замер ───────────────────────────────────────────

def measure(root: str | Path = _ROOT, *, now: Optional[dt.datetime] = None
            ) -> dict:
    root = Path(root)
    now = now or _utcnow()
    if not root.exists():
        raise NotMeasured(GAP_NO_TREE, f"корня {root} нет на диске")
    code = _code_files(root)
    if not code:
        raise NotMeasured(
            GAP_NO_CODE,
            f"ни одного .py не прочитано под {root} в {list(CODE_ROOTS)}")

    sites: List[dict] = []
    for rel, source in code:
        sites.extend(scan_module(rel, source))

    markup, prefixes, oracle_files = build_oracle(root)
    read_identities: Dict[str, Set[str]] = collections.defaultdict(set)
    for row in sites:
        if row["identity"]:
            read_identities[row["file"]].add(row["identity"])
    py_produced, py_prefixes, references, own_scene = _python_producers(
        code, read_identities)
    prefixes |= py_prefixes

    for row in sites:
        row["parity"] = _parity(row, markup, py_produced, references, prefixes,
                                oracle_files)
        row["foreign"] = row["haystack_origin"] in FOREIGN_ORIGINS

    # КЛАСС: чужой стог И претензия к личности. Перечислитель предмета не
    # имеет и в класс не входит — это не допуск, а отсутствие предмета.
    in_class = [r for r in sites if r["foreign"]
                and r["identity_outcome"] != IDENTITY_ENUMERATING]
    judged = [r for r in in_class if r["identity_outcome"] == IDENTITY_LITERAL]
    # ВРЕД: претензия, которую не подтверждает ничто, кроме себя. Оба исхода
    # считаются одним числом — лекарство у них одно.
    refuted = [r for r in judged if r["parity"] in UNSUPPORTED_OUTCOMES]
    silent_refuted = [r for r in refuted
                      if r["loudness"] == SILENT_MEMBERSHIP]
    unmeasured_loudness = [r for r in refuted
                           if r["loudness"] == LOUDNESS_UNMEASURED]

    return {
        "generated_at": now.isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "MEASURED",
        "order": ORDER,
        "applied": False,
        "question": ("сколько читателей дерева ищут КОНКРЕТНУЮ личность "
                     "элемента в ЧУЖОЙ разметке, и сколько из этих претензий "
                     "дерево подтверждает, опровергает, не измеряет"),
        "files_scanned": len(code),
        "oracle_markup_files": oracle_files,
        "oracle_identities": len(markup),
        "oracle_python_identities": len(py_produced),
        # Файлы СВОЕЙ сцены, исключённые из оракула. Печатается всегда, в том
        # числе нулём: иначе «прибор себя не считает» было бы утверждением о
        # себе, а не замером.
        "oracle_own_scene_files_excluded": sorted(own_scene),
        "oracle_assembled_prefixes": sorted(prefixes),
        # НАСЕЛЕНИЕ: все сайты чтения с ссылкой на личность, включая `own`.
        "population": len(sites),
        # КЛАСС ЗАКАЗА: стог ЧУЖОЙ по построению.
        "foreign_population": len(in_class),
        "own_markup": len([r for r in sites
                           if r["haystack_origin"] == HAY_OWN]),
        "origin_unresolved": len([r for r in sites
                                  if r["haystack_origin"] == HAY_UNRESOLVED]),
        "haystack_origins": dict(collections.Counter(
            r["haystack_origin"] for r in sites)),
        "identity_outcomes": {
            k: len([r for r in sites if r["foreign"]
                    and r["identity_outcome"] == k])
            for k in _IDENTITY_OUTCOMES},
        "enumerators_out_of_class": len(
            [r for r in sites
             if r["identity_outcome"] == IDENTITY_ENUMERATING]),
        "behind_a_module_level_skip": len(
            [r for r in in_class if r["module_level_skip"]]),
        "parity_outcomes": {k: len([r for r in in_class if r["parity"] == k])
                            for k in _PARITY_OUTCOMES},
        "loudness_outcomes": {k: len([r for r in judged
                                      if r["loudness"] == k])
                              for k in _LOUDNESS_OUTCOMES},
        # ЧИСЛО ЗАКАЗА: претензий, не подтверждённых ничем, кроме себя.
        "judged": len(judged),
        "unsupported": len(refuted),
        # РАЗДЕЛЕНО по причине — «нигде вовсе» и «только своя сцена» чинятся
        # одинаково, но читаются по-разному, и слить их значило бы потерять,
        # что у второго подтверждение ЕСТЬ и оно поддельное.
        "refuted": len([r for r in judged if r["parity"] == REFUTED]),
        "echoed_by_own_scene": len(
            [r for r in judged if r["parity"] == ECHOED_BY_OWN_SCENE]),
        # ТО ЖЕ ЧИСЛО по громкости — лекарство разное, складывать нельзя.
        "refuted_silently": len(silent_refuted),
        "refuted_loudness_unmeasured": len(unmeasured_loudness),
        "readers": sorted({r["file"] for r in in_class}),
        "refuted_rows": [
            {k: r[k] for k in ("file", "line", "form", "identity",
                               "haystack_origin", "loudness",
                               "module_level_skip", "parity")}
            for r in refuted],
        "rows": [{k: r[k] for k in ("file", "line", "form", "identity",
                                    "identity_outcome", "haystack_origin",
                                    "parity", "loudness",
                                    "module_level_skip")}
                 for r in in_class],
        "what_it_does_not_prove": [
            "что ОПРОВЕРГНУТАЯ личность отсутствует на живом сайте: оракул "
            "есть ДЕРЕВО, а старая сборка на CDN умеет нести id, которого в "
            "исходниках больше нет — ровно случай sl-day/sl-gates/sl-apy",
            "что ПОДТВЕРЖДЁННАЯ личность доезжает до посетителя: подтверждено "
            "лишь то, что её пишет какой-то производитель дерева",
            "что читатель прав по СУЩЕСТВУ — измерена претензия к личности "
            "элемента, а не смысл сверки",
            "что личность, собираемая производителем в рантайме, верна или "
            "неверна: у неё ТРЕТИЙ исход, и он не «подтверждён»",
            "что промах, у которого громкость НЕ ИЗМЕРЕНА, молчит: узость "
            "измерения громкости объявлена, и неизмеренное за находку не "
            "выдаётся",
        ],
    }


def report(doc: dict) -> List[str]:
    if str(doc.get("status")) != "MEASURED":
        return [f"❌ НЕ ИЗМЕРЕНО ({doc.get('gap')}): {doc.get('reason')}",
                f"   заказ {doc.get('order')} — третий исход, не «ноль находок»"]
    head = (f"читатели ЧУЖОЙ разметки по литеральной личности "
            f"(заказ {doc['order']}): население {doc['population']} · "
            f"чужой стог {doc['foreign_population']} · судимо {doc['judged']} "
            f"· НЕ ПОДТВЕРЖДЕНО НИЧЕМ, КРОМЕ СЕБЯ {doc['unsupported']} "
            f"(нигде {doc['refuted']} · только своя сцена "
            f"{doc['echoed_by_own_scene']})")
    lines = [head]
    lines_unresolved = doc.get("origin_unresolved", 0)
    if lines_unresolved:
        lines.append(
            f"   ⚠️ НЕ ИЗМЕРЕНО происхождение стога у {lines_unresolved} "
            f"сайт(ов) — они в класс НЕ зачтены, и это остаток, а не чистота")
    for row in doc.get("refuted_rows", [])[:16]:
        lines.append(f"   НЕ ПОДТВЕРЖДЕНА #{row['identity']} "
                     f"({row['parity']}) — "
                     f"{row['file']}:{row['line']} [{row['form']}] "
                     f"стог: {row['haystack_origin']} · {row['loudness']}"
                     + (" · МОДУЛЬ УМЕЕТ СКИПНУТЬ СЕБЯ ЦЕЛИКОМ"
                        if row.get("module_level_skip") else ""))
    parity = doc.get("parity_outcomes", {})
    lines.append(f"   подтверждено разметкой {parity.get(CONFIRMED, 0)} · "
                 f"только python-производителем "
                 f"{parity.get(CONFIRMED_BY_PYTHON, 0)} · собирается в "
                 f"рантайме {parity.get(UNMEASURED_ASSEMBLED, 0)} · личность "
                 f"не свёрнута {parity.get(UNMEASURED_IDENTITY, 0)}")
    lines.append(f"   из НЕподтверждённых МОЛЧА {doc['refuted_silently']} · "
                 f"громкость НЕ ИЗМЕРЕНА "
                 f"{doc['refuted_loudness_unmeasured']}")
    lines.append(f"   оракул: {doc['oracle_markup_files']} файл(ов) разметки, "
                 f"{doc['oracle_identities']} личностей; ADVISORY "
                 "(applied=False) — ни разметки, ни сторожей он не правит")
    return lines


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Сжатая отрисовка для шага 0-офис — правило отрисовки У ПРОИЗВОДИТЕЛЯ."""
    lines = report(doc)
    if str(doc.get("status")) != "MEASURED":
        return lines
    head = [line for line in lines if not line.startswith("   ")]
    rows = [line for line in lines if line.startswith("   НЕ ПОДТВЕРЖДЕНА")]
    tail = [line for line in lines
            if line.startswith("   ") and not line.startswith("   НЕ ПОДТВЕРЖДЕНА")]
    hidden = max(0, len(rows) - max_rows)
    out = head[:1] + rows[:max_rows]
    if hidden:
        out.append(f"   … и ещё {hidden} опровергнутых — обрезка ПОКАЗА, не "
                   f"населения (всё в артефакте)")
    return out + tail + head[1:]


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "order": ORDER,
            "applied": False,
            "gap": exc.gap,
            "reason": str(exc),
            "rows": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") == "MEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("читатели ЧУЖОЙ разметки по литеральной личности "
                     "элемента (заказ G103 п. 2)"))
    parser.add_argument("--root", default=str(_ROOT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    outcome = run(Path(args.root),
                  dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    for line in report(outcome["doc"]):
        print(line)
    return 0 if outcome["measured"] else 2


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
