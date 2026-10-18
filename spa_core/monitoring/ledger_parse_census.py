"""Перепись ПОВТОРНОГО РАЗБОРА хеш-лент у читающих моделей (заказ G777 п. 1).

Цикл #893 ([ADR-777]) нашёл и снял один случай: читающая модель
``research_factory.read.latest()`` разбирала ``data/research_factory/ledger.jsonl``
(52 108 460 Б) **4 958 раз** за один вызов, и лекарство ADR-763 было вкручено в ОДНУ
точку входа, а не в саму модель. Заказ G777 п. 1 был сформулирован как «НЕ ИЗМЕРЕНО»:
*«прочие хеш-ленты (investment_cio, capital_shadow, sleeve_aggressive) имеют свои
читающие модели, и переехали ли они на тот же порядок — не измерено»*.

## Ответ на заказ (замер 2026-10-18, живое ``data/`` хоста)

===================  ==============  ==========  ========  ==========  ==========
лента                       байт     разбор, с   открытий   цена, с    запас, ×
===================  ==============  ==========  ========  ==========  ==========
research_factory         52 108 460      0.2147          2      0.429        2.3
capital_shadow            1 464 682      0.0041          5      0.021       48.8
investment_cio              892 441      0.0025          3      0.008      133.3
sleeve_aggressive            27 120      0.0002          1      0.000     5000.0
===================  ==============  ==========  ========  ==========  ==========

**Переехали — НЕТ, и переехать не могли:** порядок ADR-777 (область
:func:`spa_core.utils.hash_ledger.read_cache`) живёт в ОДНОЙ реализации ленты, а в
дереве их ЧЕТЫРЕ, и три из них не импортируют ``hash_ledger`` вовсе — у каждой свой
разборщик (``investment_cio/ledger.py::read_all``, ``capital_shadow/ledger.py::read_all``,
``strategy_lab/sleeve/composer.py::load_ledger``). Это стоячий класс «одно правило — одна
копия», и названный тут замер — его цена сегодня.

**Но дефекта у трёх сегодня НЕТ, и причина — не их устройство.** Они дешевы потому, что
их ФАЙЛЫ малы: 892 КБ и 1,4 МБ против 52 МБ. Размер файла есть свойство МИРА (сколько
дней накопилось), а не кода: лента append-only и не усыхает никогда. Поэтому цена каждого
такого читателя растёт сама, без единой правки, и ровно так созрел дефект
research_factory — он был невидим недели и нашёлся только тем, что тест встал на 27 минут.

**Что этот прибор добавляет к ADR-777.** У ADR-777 остался запас **2.3×** — наименьший в
населении, в двадцать раз меньше следующего, — и об этом не говорит сегодня ни один
сторож. Прибор переводит медленный рост в ЧИСЛО: «во сколько раз лента вправе вырасти,
прежде чем ОДИН вызов вида перестанет укладываться в бюджет».

## Как мерится «открытие» — ДВЕ двери, и это не придирка

Разбор считается у самого файла, а не у имён функций: число открытий ленты за один вызов
вида. Иначе прибор знал бы, где у каждой из четырёх реализаций лежит кэш, и разошёлся бы
с ними при первой правке. Дверей, однако, ДВЕ, и подменять надо обе:

* ``builtins.open`` — так читают три реализации (``with open(path) as f``);
* ``io.open`` — так читает ``pathlib`` (``Path.read_text``), то есть
  ``sleeve/composer.py::load_ledger``.

``io.open is builtins.open`` даёт ``True`` — это ОДИН объект, — но ``pathlib`` зовёт его
через пространство имён модуля ``io``, поэтому подмена одного ``builtins.open`` его НЕ
видит. Замер: при подменённом только ``builtins.open`` вид рукава даёт **0 открытий** при
49 прочитанных строках. Ноль тут означал бы «не читает файл», а правда — «дверь не
смотрели».

Отсюда правило третьего исхода, и оно самопроверяющее (инв. #17): **ноль открытий при
непустом ответе вида есть НЕ ИЗМЕРЕНО с названной причиной**, а не «измерено и равно
нулю». Пятая дверь (``os.open`` + ``os.read``) закрытой не объявляется — она объявляется
НЕНАБЛЮДАЕМОЙ, и член, читающий через неё, попадёт в третий исход, а не в тишину.

## Второй множитель: полная цена есть ПРОИЗВЕДЕНИЕ (заказ G778 п. 3, цикл #896)

До цикла #896 этот прибор отвечал на вопрос «сколько стои́т ОДИН вызов вида» и честно
печатал в своём же списке «НЕ ДОКЛАДЫВАЕТ»: *сколько РАЗ за сборку зовут сам вид*. Полная
цена, однако, есть произведение двух множителей, и второй не мерил никто — при том, что
на нём стояло ОБОСНОВАНИЕ бюджета ниже («вид зовут многократно внутри одной сборки»).
Обоснование решения опиралось на величину, которой не было.

Замер 2026-10-18 (живое ``data/`` хоста, три НАЗВАННЫХ прогона):

===================  ==============  =================  ================
вид                  ``mission_build``  ``telegram_sherlock``  ``telegram_oracle``
===================  ==============  =================  ================
research_factory                  2                  1                 0
capital_shadow                    1                  0                 0
investment_cio                    2                  0                 2
sleeve_aggressive                 0                  0                 0
===================  ==============  =================  ================

**Множитель не равен единице, и там, где он двойка, он стои́т дороже всего.** У
``research_factory`` запас ОДНОГО вызова — 2.3×, а сборка зовёт вид ДВАЖДЫ, то есть
полная цена сборки вдвое выше той, которую прибор печатал, а запас вдвое ниже.

**Второй вызов не виден из кода сборки.** Он приходит ИЗНУТРИ другой читающей модели:
``capital_shadow.read.latest → readiness.evaluate → _market_neutral_basis_reason →
research_factory.read.latest``. Это ровно класс ADR-777 («лекарство вкручено в точку
входа, а цена живёт в читающей модели») на уровень выше: цену платит вложенный читатель,
которого вызывающий не называет. У ``investment_cio`` вторая пара такая же:
``read.capital_sources`` сама зовёт ``read.latest``.

**Ноль — тоже ответ, но только когда прибор доказан.** ``sleeve_aggressive`` не зовётся НИ
ОДНИМ из трёх названных прогонов; его запас 5907× поэтому верен и ни к одному измеренному
прогону не относится — член уходит в третий исход
(:data:`U_NO_WORKLOAD_REACHES`), а не в «цена ноль». Обратная сторона того же правила:
прогон, у которого НУЛЬ вызовов у ВСЕХ членов, объявляется
:data:`U_PROBE_NOT_PROVEN` — условие приёма прогона в население состоит в том, что он
читает хотя бы одну ленту, поэтому сплошной ноль означает «счётчик не встал», а не
«прогон лент не читает».

**Население прогонов — РЕШЕНИЕ, а не замер, и оно так и названо.** Прибор не утверждает,
что названных прогонов три, — он утверждает, что измерил эти три. Чтобы «прогонов больше»
не было пустым словом, рядом печатается ЗАМЕР: сколько файлов не-тестового кода вообще
упоминают путь вида (:func:`view_reference_files`). Член, у которого упоминания есть, а
ни один объявленный прогон его не зовёт, виден по этим двум числам сразу.

**Дверь счётчика одна, и у неё есть обратная сторона.** Вызовы считаются подменой
АТРИБУТА МОДУЛЯ (``mod.attr``), потому что все сегодняшние потребители берут вид через
пространство имён модуля в момент вызова. Потребитель, связавший имя на импорте
(``from ...read import latest``), мимо такой подмены пройдёт молча — поэтому наличие таких
связываний ИЗМЕРЯЕТСЯ обходом дерева (:func:`direct_name_bindings`), и появление первого
есть находка, а не тишина.

## Бюджет и порог запаса — РЕШЕНИЯ, и названы как решения

:data:`REPARSE_BUDGET_S` = 1.0 с на ОДИН вызов вида. Это решение, а не замер: вид зовут
многократно внутри одной сборки и одного теста, и при секунде на вызов цена становится
минутами предписанного прогона — ровно тем признаком, которым дефект research_factory и
обнаружился. **Слово «многократно» в этом обосновании было догадкой до цикла #896**; теперь
оно замер: 2 · 1 · 2 · 0 по трём названным прогонам (таблица выше).

:data:`WORKLOAD_BUDGET_S` = 1.0 с на ОДИН НАЗВАННЫЙ ПРОГОН — сумма по всем вызовам вида
внутри него. Отдельное решение рядом с первым, а не замена ему: прежний бюджет судит
вызов, этот — прогон, и печатаются оба. Переопределять смысл уже стоящей константы молча
значило бы сменить предмет сторожа, не сказав об этом (инв. #16).

:data:`MIN_GROWTH_FACTOR` = 4.0. Тоже решение: менее чем четырёхкратный запас означает,
что обычный рост append-only ленты съест его без единой правки кода.

Упорядочивание членов по запасу от этих двух чисел НЕ зависит — зависит только граница
находки. Поэтому в отчёте печатаются и запас, и оба числа, по которым он посчитан.

## Замкнутость населения

Пятая лента не вправе появиться молча. Население объявлено ДВАЖДЫ и сверяется:

* :data:`LEDGERS` — четыре ленты со своими видами и объявленным числом открытий;
* :data:`LEDGER_CODE_FILES` — файлы, несущие литерал ``"ledger.jsonl"``.

Расхождение второго с деревом краснит сторожа (``test_ledger_parse_census.py``) — тот же
порядок, что у ``read.VIEW_ENTRY_POINTS`` (ADR-777).

ADVISORY: прибор только ЧИТАЕТ. Ни RiskPolicy, ни стоп-кран, ни живой трек, ни ленты он не
трогает; чинить он тоже ничего не умеет.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import builtins
import contextlib
import importlib
import io
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]

#: РЕШЕНИЕ (не замер): сколько секунд ОДИН вызов вида вправе потратить на разбор своей
#: ленты. Причина — в докстроке модуля: вид зовут многократно за сборку, и секунда на
#: вызов становится минутами предписанного прогона.
REPARSE_BUDGET_S = 1.0

#: РЕШЕНИЕ (не замер): во сколько раз лента обязана иметь право вырасти, не выйдя за
#: бюджет. Меньший запас обычный рост append-only ленты съедает без правок кода.
MIN_GROWTH_FACTOR = 4.0

#: РЕШЕНИЕ (не замер): сколько секунд ОДИН названный прогон (сборка, нажатие владельца)
#: вправе потратить на повторный разбор своих лент СУММАРНО. Отдельно от
#: :data:`REPARSE_BUDGET_S`, который судит один вызов: у двух разных предметов два числа.
WORKLOAD_BUDGET_S = 1.0

F_MARGIN_SHORT = "growth_margin_below_floor"
F_OPENS_DRIFTED = "opens_per_view_drifted"
F_CALLS_DRIFTED = "calls_per_workload_drifted"
F_WORKLOAD_MARGIN_SHORT = "workload_growth_margin_below_floor"
F_IMPORT_BOUND_VIEW = "view_name_bound_at_import"

U_VIEW_RAISED = "view_raised"
U_LEDGER_ABSENT = "ledger_absent"
U_DOOR_NOT_WATCHED = "zero_opens_with_a_non_empty_answer"
U_VIEW_UNRESOLVED = "view_unresolved"
U_WORKLOAD_RAISED = "workload_raised"
U_PROBE_NOT_PROVEN = "zero_calls_for_every_member_of_the_population"
U_NO_WORKLOAD_REACHES = "no_declared_workload_calls_this_view"
U_VIEW_NOT_PATCHABLE = "view_has_no_module_attribute_to_count_at"
U_PRICE_UNKNOWN = "per_call_price_not_measured"


@dataclass(frozen=True)
class Member:
    """Одна пара «лента ↔ читающий её вид»."""

    id: str
    ledger: str
    view: str | Callable
    declared_opens: int
    opens_reason: str
    scoped_door: bool
    scoped_reason: str


#: Объявленное население. `declared_opens` у каждого члена — ЗАМЕР 2026-10-18 с названной
#: причиной; расхождение в ЛЮБУЮ сторону есть находка, потому что у каждого числа причина,
#: и исчезновение необходимого разбора так же значимо, как появление лишнего.
LEDGERS: Tuple[Member, ...] = (
    Member(
        id="research_factory",
        ledger="research_factory/ledger.jsonl",
        view="spa_core.research_factory.read:latest",
        declared_opens=2,
        opens_reason=("два НАЗВАННЫХ числа (ADR-777): свежий verify(), который кэш не "
                      "обслуживает принципиально, плюс один разбор на всех помощников вида"),
        scoped_door=True,
        scoped_reason="читающая модель открывает область hash_ledger.read_cache (ADR-777)",
    ),
    Member(
        id="capital_shadow",
        ledger="capital_shadow/ledger.jsonl",
        view="spa_core.capital_shadow.read:latest",
        declared_opens=5,
        opens_reason=("своя реализация ledger.read_all БЕЗ кэша: каждый зов разбирает файл "
                      "заново; пять зовов за вид — замер, не проект"),
        scoped_door=False,
        scoped_reason="hash_ledger не импортируется — области нет, кэша нет",
    ),
    Member(
        id="investment_cio",
        ledger="investment_cio/ledger.jsonl",
        view="spa_core.investment_cio.read:latest",
        declared_opens=3,
        opens_reason=("своя реализация ledger.read_all БЕЗ кэша; три зова за вид — замер, "
                      "не проект"),
        scoped_door=False,
        scoped_reason="hash_ledger не импортируется — области нет, кэша нет",
    ),
    Member(
        id="sleeve_aggressive",
        ledger="sleeve_aggressive/ledger.jsonl",
        view="spa_core.strategy_lab.sleeve.composer:load_ledger",
        declared_opens=1,
        opens_reason=("читатель один и разбирает один раз; читает через pathlib "
                      "(Path.read_text) — именно он доказывает, что дверей ДВЕ"),
        scoped_door=False,
        scoped_reason="hash_ledger не импортируется — области нет, кэша нет",
    ),
)

#: Вторая, НЕЗАВИСИМАЯ запись населения: файлы дерева, несущие литерал имени ленты.
#: Сверяется со деревом сторожем — пятая лента не вправе появиться молча.
LEDGER_CODE_FILES: Tuple[str, ...] = (
    "spa_core/capital_shadow/contract.py",
    "spa_core/investment_cio/contract.py",
    "spa_core/research_factory/contract.py",
    "spa_core/strategy_lab/sleeve/composer.py",
    "spa_core/utils/hash_ledger.py",
)

LEDGER_LITERAL = '"ledger.jsonl"'

#: Единственное исключение из обхода, и причина у него названа: прибор, который СПРАШИВАЕТ
#: о литерале имени ленты, обязан нести этот литерал в себе — иначе он не мог бы спросить.
#: Молчаливого списка исключений у этой переписи нет; это одно, и оно печатается в отчёте.
SELF_REL = "spa_core/monitoring/ledger_parse_census.py"


@dataclass(frozen=True)
class Workload:
    """Один НАЗВАННЫЙ прогон — сборка или нажатие владельца, — за который считают вызовы.

    ``declared_calls`` — ЗАМЕР 2026-10-18 с названной причиной у каждого числа, не проект:
    расхождение в любую сторону есть находка ровно так же, как у ``declared_opens``.
    Условие приёма в население названо и самопроверяющееся: прогон обязан читать хотя бы
    одну ленту, поэтому сплошной ноль по всем членам есть «счётчик не встал»
    (:data:`U_PROBE_NOT_PROVEN`), а не «прогон лент не читает».
    """

    id: str
    run: Callable[[Path], object]
    reason: str
    declared_calls: Dict[str, int]
    calls_reason: Dict[str, str]


def _run_mission_build(data_dir: Path) -> object:
    """Сборка Mission Control — тот самый прогон, про который говорят ADR-763/777.

    ``mission_control.build()`` строит читающую модель В ПАМЯТИ и на диск не пишет ничего
    (пишет обёртка ``mission_build``, и она в прогон НЕ входит: предмет тут — чтение).
    Каталог данных у сборки задаётся корнем репозитория, а прибор получает ``data/``,
    поэтому корнем берётся родитель — связь названа, а не подразумевается.
    """
    from spa_core.studio_os import mission_control as mc
    return mc.build(mc.MCInputs(repo=Path(data_dir).parent))


@contextlib.contextmanager
def _capital_reads_from(data_dir: Path):
    """Телеграм-экраны берут каталог через ОБЪЯВЛЕННУЮ точку инъекции (``READERS``) — ту
    же, которой пользуются их собственные тесты. Возврат в ``finally``: прибор не вправе
    оставить после себя модуль, читающий чужой каталог."""
    from spa_core.telegram.views import capital as cap
    real = cap.READERS["data_dir"]
    cap.READERS["data_dir"] = lambda: Path(data_dir)
    try:
        yield cap
    finally:
        cap.READERS["data_dir"] = real


def _run_telegram_sherlock(data_dir: Path) -> object:
    """Одно нажатие владельца на экран Sherlock — читатель, которого ADR-777 назвал
    поимённо среди тех, кому лекарство ADR-763 не досталось."""
    with _capital_reads_from(data_dir) as cap:
        return cap.render_sherlock()


def _run_telegram_oracle(data_dir: Path) -> object:
    """Одно нажатие владельца на экран Oracle — второй названный там же читатель."""
    with _capital_reads_from(data_dir) as cap:
        return cap.render_oracle()


#: Объявленное население ПРОГОНОВ. Это РЕШЕНИЕ, а не замер, и прибор не утверждает, что
#: прогонов в системе ровно три — он утверждает, что измерил эти три. Насколько население
#: полно, видно по соседнему ЗАМЕРУ :func:`view_reference_files`.
WORKLOADS: Tuple[Workload, ...] = (
    Workload(
        id="mission_build",
        run=_run_mission_build,
        reason=("сборка Mission Control — прогон, на котором ADR-763/777 мерили цену "
                "повторного разбора (1 613 с против 18.3 с)"),
        declared_calls={"research_factory": 2, "capital_shadow": 1,
                        "investment_cio": 2, "sleeve_aggressive": 0},
        calls_reason={
            "research_factory": ("два НАЗВАННЫХ вызова: build → _research_universe_section, "
                                 "и ВЛОЖЕННЫЙ — capital_shadow.read.latest → readiness.evaluate "
                                 "→ _market_neutral_basis_reason; второй из кода сборки не виден"),
            "capital_shadow": "один вызов: build → _live_readiness_section",
            "investment_cio": ("два НАЗВАННЫХ вызова: build → _investment_cio_section, и "
                               "build → _capital_sources_section → read.capital_sources, "
                               "которая сама зовёт read.latest"),
            "sleeve_aggressive": "сборка рукавную ленту не читает вовсе — ноль тут ЗАМЕР",
        },
    ),
    Workload(
        id="telegram_sherlock",
        run=_run_telegram_sherlock,
        reason="одно нажатие владельца: экран Sherlock, назван читателем в ADR-777",
        declared_calls={"research_factory": 1, "capital_shadow": 0,
                        "investment_cio": 0, "sleeve_aggressive": 0},
        calls_reason={
            "research_factory": "один вызов: render_sherlock → READERS['research'] → read.latest",
            "capital_shadow": "экран этой ленты не читает",
            "investment_cio": "экран этой ленты не читает",
            "sleeve_aggressive": "экран этой ленты не читает",
        },
    ),
    Workload(
        id="telegram_oracle",
        run=_run_telegram_oracle,
        reason="одно нажатие владельца: экран Oracle, назван читателем в ADR-777",
        declared_calls={"research_factory": 0, "capital_shadow": 0,
                        "investment_cio": 2, "sleeve_aggressive": 0},
        calls_reason={
            "research_factory": "экран этой ленты не читает",
            "capital_shadow": "экран этой ленты не читает",
            "investment_cio": ("два вызова на ОДНО нажатие: READERS['cio'] → read.latest и "
                               "READERS['sources'] → read.capital_sources → read.latest"),
            "sleeve_aggressive": "экран этой ленты не читает",
        },
    ),
)

#: Форма, которой подмена атрибута модуля НЕ видна: имя вида связано на импорте. Сегодня
#: таких связываний в дереве нет (замер 2026-10-18) — и это проверяется, а не предполагается.
_IMPORT_BINDING = re.compile(
    r"^\s*from\s+[\w.]*\b(?P<mod>research_factory\.read|capital_shadow\.read|"
    r"investment_cio\.read|sleeve\.composer)\s+import\s+(?P<names>[^\n#]+)", re.M)


def direct_name_bindings(tree_root: Optional[Path] = None,
                         members: Sequence["Member"] = ()) -> List[str]:
    """Файлы, связавшие имя вида НА ИМПОРТЕ — то есть прошедшие бы мимо счётчика молча.

    Счётчик подменяет атрибут модуля; потребитель, сделавший ``from ...read import latest``,
    держит ссылку на НАСТОЯЩУЮ функцию и подмены не увидит. Поэтому «таких нет» обязано
    быть замером, а не умолчанием: появление первого — находка.
    """
    wanted = {str(m.view).partition(":")[2] for m in members if not callable(m.view)}
    root = Path(tree_root or _ROOT)
    hits: List[str] = []
    for base in ("spa_core", "scripts"):
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}" or rel == SELF_REL:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in _IMPORT_BINDING.finditer(text):
                names = {n.strip().split(" as ")[0].strip()
                         for n in m.group("names").split(",")}
                if names & wanted:
                    hits.append(f"{rel}: from …{m.group('mod')} import {m.group('names').strip()}")
    return hits


def view_reference_files(member: "Member", tree_root: Optional[Path] = None) -> List[str]:
    """ЗАМЕР рядом с решением: сколько файлов не-тестового кода вообще упоминают вид.

    Отвечает не на «полно ли население прогонов» (это решение), а на «есть ли у вида
    читатели за пределами измеренных» — числом, по которому неполноту видно сразу.
    """
    if callable(member.view):
        return []
    mod_name, _, attr = str(member.view).partition(":")
    parts = mod_name.split(".")
    pkg, mod = (parts[-2], parts[-1]) if len(parts) >= 2 else ("", parts[-1])
    #: обе формы ссылки на модуль вида, и вторая важнее первой: ВЛОЖЕННЫЙ читатель
    #: (capital_shadow.readiness → research_factory.read.latest) пишет именно её.
    ref = re.compile(rf"\b{re.escape(pkg)}\s*(?:\.|\s+import\s+){re.escape(mod)}\b"
                     if pkg else rf"\b{re.escape(mod)}\b")
    #: файл, где вид ОПРЕДЕЛЁН, — тоже ссылка: внутримодульные зовы живут там же
    #: (``composer.py`` зовёт свой ``load_ledger`` из ``run_sleeve_shadow``).
    own = mod_name.replace(".", "/") + ".py"
    root = Path(tree_root or _ROOT)
    hits: List[str] = []
    for base in ("spa_core", "scripts"):
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}" or rel == SELF_REL:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if attr in text and (rel == own or ref.search(text)):
                hits.append(rel)
    return hits


def resolve_view_site(member: "Member") -> Tuple[Optional[object], Optional[str], Optional[str]]:
    """Место, где вид ЛЕЖИТ (модуль + имя атрибута) — чтобы было что подменить счётчиком.

    Вид, переданный готовым вызываемым (стенды), места в модуле не имеет: считать его
    вызовы нечем, и это третий исход с причиной, а не ноль.
    """
    if callable(member.view):
        return None, None, f"{U_VIEW_NOT_PATCHABLE}: вид передан вызываемым, атрибута модуля нет"
    mod_name, _, attr = str(member.view).partition(":")
    if not attr:
        return None, None, f"{U_VIEW_UNRESOLVED}: в «{member.view}» нет имени функции после ':'"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as exc:  # noqa: BLE001 — причина НАЗЫВАЕТСЯ, а не съедается
        return None, None, f"{U_VIEW_UNRESOLVED}: {type(exc).__name__}: {exc}"
    if not callable(getattr(mod, attr, None)):
        return None, None, f"{U_VIEW_UNRESOLVED}: {member.view} не вызываемое"
    return mod, attr, None


def count_calls(members: Sequence["Member"], workload: Workload,
                data_dir: Path) -> Tuple[Dict[str, int], Dict[str, str], object, Optional[str]]:
    """Сколько раз ОДИН прогон зовёт КАЖДЫЙ вид — подменой атрибута модуля.

    Возврат: счётчики · члены, у которых считать нечем (с причиной) · ответ прогона ·
    причина отказа прогона (``None``, если прогон дошёл до конца).
    """
    counts: Dict[str, int] = {}
    cannot: Dict[str, str] = {}
    undo: List[Tuple[object, str, Callable]] = []
    for m in members:
        mod, attr, why = resolve_view_site(m)
        if mod is None:
            cannot[m.id] = why or U_VIEW_NOT_PATCHABLE
            continue
        real = getattr(mod, attr)
        counts[m.id] = 0

        def make(mid=m.id, real=real):
            def hook(*a, **k):
                counts[mid] += 1
                return real(*a, **k)
            hook.__wrapped__ = real
            return hook

        setattr(mod, attr, make())
        undo.append((mod, attr, real))
    try:
        answer = workload.run(Path(data_dir))
        err = None
    except Exception as exc:  # noqa: BLE001 — прогон упал ⇒ третий исход с причиной
        answer, err = None, f"{U_WORKLOAD_RAISED}: {type(exc).__name__}: {exc}"
    finally:
        for mod, attr, real in undo:
            setattr(mod, attr, real)
    return counts, cannot, answer, err


def measure_workloads(data_dir: Path | str, *, members: Sequence["Member"] = LEDGERS,
                      workloads: Sequence[Workload] = (),
                      price_by_id: Optional[Dict[str, Optional[float]]] = None,
                      budget_s: float = WORKLOAD_BUDGET_S,
                      min_factor: float = MIN_GROWTH_FACTOR) -> dict:
    """Второй множитель и полная цена прогона. Три исхода различимы у КАЖДОГО прогона."""
    data = Path(data_dir)
    price_by_id = price_by_id or {}
    rows: List[dict] = []
    reached: Dict[str, int] = {m.id: 0 for m in members}
    seen_measured = False
    for w in workloads:
        row: dict = {"id": w.id, "reason": w.reason, "calls": None,
                     "not_countable": None, "unmeasured": None,
                     "price_s": None, "growth_factor": None, "findings": []}
        counts, cannot, answer, err = count_calls(members, w, data)
        if cannot:
            row["not_countable"] = cannot
        if err:
            row["unmeasured"] = err
            rows.append(row)
            continue
        if counts and not any(counts.values()):
            row["unmeasured"] = (
                f"{U_PROBE_NOT_PROVEN}: прогон дошёл до конца, но ни один из "
                f"{len(counts)} видов не был вызван ни разу. Условие приёма прогона в "
                f"население — что он читает хотя бы одну ленту, поэтому сплошной ноль "
                f"означает, что счётчик не встал (имя вида связано на импорте либо "
                f"прогон подменён), а НЕ что лент он не читает")
            rows.append(row)
            continue
        if not counts:
            row["unmeasured"] = (
                f"{U_VIEW_NOT_PATCHABLE}: ни у одного члена нет атрибута модуля, "
                f"у которого можно считать вызовы")
            rows.append(row)
            continue
        seen_measured = True
        row["calls"] = counts
        for mid, n in counts.items():
            reached[mid] = max(reached.get(mid, 0), n)
        price = 0.0
        price_known = True
        for mid, n in counts.items():
            per_call = price_by_id.get(mid)
            if n and per_call is None:
                price_known = False
                continue
            price += n * (per_call or 0.0)
        row["price_s"] = price if price_known else None
        if not price_known:
            row["unmeasured"] = (
                f"{U_PRICE_UNKNOWN}: вызовы сосчитаны, но цена одного вызова измерена не у "
                f"всех вызванных видов — произведение без второго множителя не число")
            rows.append(row)
            continue
        for mid, n in counts.items():
            declared = w.declared_calls.get(mid)
            if declared is None or n == declared:
                continue
            row["findings"].append({
                "kind": F_CALLS_DRIFTED,
                "text": (f"{mid}: вызовов за прогон {n} против объявленных {declared} — у "
                         f"объявленного числа есть причина: "
                         f"{w.calls_reason.get(mid, 'причина не названа')}"),
            })
        if price > 0:
            row["growth_factor"] = budget_s / price
            if row["growth_factor"] < min_factor:
                row["findings"].append({
                    "kind": F_WORKLOAD_MARGIN_SHORT,
                    "text": (f"полная цена прогона {price:.3f} с — запас "
                             f"{row['growth_factor']:.1f}× ниже порога {min_factor:.1f}× при "
                             f"бюджете прогона {budget_s:.2f} с; цена ОДНОГО вызова этот "
                             f"запас завышает ровно во столько раз, сколько вызовов"),
                })
        rows.append(row)

    unreached: Dict[str, str] = {}
    if seen_measured:
        for m in members:
            if reached.get(m.id, 0) == 0:
                unreached[m.id] = (
                    f"{U_NO_WORKLOAD_REACHES}: ни один из {len(workloads)} объявленных "
                    f"прогонов этот вид не зовёт — запас одного вызова у него верен, но ни "
                    f"к одному измеренному прогону не относится")
    return {
        "budget_s": budget_s,
        "min_growth_factor": min_factor,
        "declared": len(workloads),
        "rows": rows,
        "calls_by_member": reached if seen_measured else {},
        "unreached": unreached,
        "unmeasured": [r for r in rows if r["unmeasured"]],
        "findings": [dict(f, id=r["id"]) for r in rows for f in r["findings"]],
    }


def ledger_code_files(tree_root: Optional[Path] = None) -> List[str]:
    """Файлы НЕ-тестового кода, несущие литерал имени ленты — замером по дереву.

    Отвечает на вопрос «сколько лент знает КОД», отдельно от вопроса «сколько лент знает
    этот модуль». Два ответа и сверяются; совпадение их — не тавтология, потому что
    добывались они по-разному.
    """
    root = Path(tree_root or _ROOT)
    found: List[str] = []
    for base in ("spa_core", "scripts"):
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}":
                continue
            if rel == SELF_REL:
                continue  # см. SELF_REL: причина исключения названа там, а не «и так понятно»
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if LEDGER_LITERAL in text:
                found.append(rel)
    return found


def resolve_view(member: Member) -> Tuple[Optional[Callable], Optional[str]]:
    """Вид как вызываемое. Неразрешимый вид — третий исход с причиной, не исключение."""
    if callable(member.view):
        return member.view, None
    try:
        mod_name, _, attr = str(member.view).partition(":")
        if not attr:
            return None, f"{U_VIEW_UNRESOLVED}: в «{member.view}» нет имени функции после ':'"
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, attr, None)
        if not callable(fn):
            return None, f"{U_VIEW_UNRESOLVED}: {member.view} не вызываемое"
        return fn, None
    except Exception as exc:  # noqa: BLE001 — причина обязана быть НАЗВАНА, а не съедена
        return None, f"{U_VIEW_UNRESOLVED}: {type(exc).__name__}: {exc}"


def count_opens(target: Path, call: Callable[[], object]) -> Tuple[int, object, Optional[str]]:
    """Сколько раз за ОДИН вызов ``call`` открывается файл ``target`` — по ОБЕИМ дверям.

    ``io.open is builtins.open`` истинно (один объект), но ``pathlib`` зовёт его через
    пространство имён ``io``, поэтому подмена одной двери другую не видит. Замерено на
    ``sleeve/composer.py::load_ledger``: только ``builtins.open`` даёт 0 открытий при 49
    прочитанных строках.
    """
    try:
        want = str(target.resolve())
    except OSError:  # pragma: no cover — путь без доступа к родителю
        want = str(target)
    hits = {"n": 0}
    real_builtin, real_io = builtins.open, io.open

    def make(real):
        def hook(file, *a, **k):
            try:
                if str(Path(file).resolve()) == want:
                    hits["n"] += 1
            except (OSError, TypeError, ValueError):
                pass
            return real(file, *a, **k)
        return hook

    builtins.open = make(real_builtin)
    io.open = make(real_io)
    try:
        answer = call()
        err = None
    except Exception as exc:  # noqa: BLE001 — вид упал ⇒ третий исход с причиной
        answer, err = None, f"{U_VIEW_RAISED}: {type(exc).__name__}: {exc}"
    finally:
        builtins.open, io.open = real_builtin, real_io
    return hits["n"], answer, err


def parse_seconds(path: Path, *, rounds: int = 3) -> Optional[float]:
    """Сколько стои́т ОДИН разбор ленты — замером, не оценкой. Лучшее из ``rounds``
    прогонов: шум машины завышает, и завышенная цена дала бы завышенную тревогу."""
    best: Optional[float] = None
    for _ in range(max(1, rounds)):
        t0 = time.perf_counter()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        json.loads(line)
        except (OSError, ValueError):
            return None
        took = time.perf_counter() - t0
        best = took if best is None else min(best, took)
    return best


def _answer_is_empty(answer: object) -> bool:
    """Пустой ответ вида. Пустота — законный ответ (ленты может не быть), и тогда ноль
    открытий есть ЗАМЕР. Непустой ответ при нуле открытий — наоборот, улика о двери."""
    if answer is None:
        return True
    if isinstance(answer, (list, tuple, set, dict, str)):
        return len(answer) == 0
    return False


def measure(data_dir: Path | str, *, members: Sequence[Member] = LEDGERS,
            budget_s: float = REPARSE_BUDGET_S,
            min_factor: float = MIN_GROWTH_FACTOR,
            tree_root: Optional[Path] = None,
            parse_rounds: int = 3,
            workloads: Sequence[Workload] = (),
            workload_budget_s: float = WORKLOAD_BUDGET_S) -> dict:
    """Замер по населению. Три исхода у КАЖДОГО члена различимы (инв. #17).

    ``workloads`` пусто ПО УМОЛЧАНИЮ намеренно: названные прогоны поднимают настоящую
    сборку и настоящие экраны, и подставлять их стенду, который мерит свой фальшивый вид,
    значило бы мерить не то, о чём спрашивают. Боевое население передаёт CLI.
    """
    data = Path(data_dir)
    rows: List[dict] = []
    for m in members:
        row: dict = {
            "id": m.id,
            "ledger": m.ledger,
            "declared_opens": m.declared_opens,
            "opens_reason": m.opens_reason,
            "scoped_door": m.scoped_door,
            "scoped_reason": m.scoped_reason,
            "opens": None,
            "bytes": None,
            "parse_s": None,
            "cost_s": None,
            "growth_factor": None,
            "unmeasured": None,
            "findings": [],
        }
        path = data / m.ledger
        fn, why = resolve_view(m)
        if fn is None:
            row["unmeasured"] = why
            rows.append(row)
            continue
        if not path.exists():
            row["unmeasured"] = f"{U_LEDGER_ABSENT}: {path}"
            rows.append(row)
            continue
        row["bytes"] = path.stat().st_size
        opens, answer, err = count_opens(path, lambda fn=fn: fn(data))
        if err:
            row["unmeasured"] = err
            rows.append(row)
            continue
        row["opens"] = opens
        if opens == 0 and not _answer_is_empty(answer):
            row["unmeasured"] = (
                f"{U_DOOR_NOT_WATCHED}: вид ответил непусто, а ни одна наблюдаемая дверь "
                f"({LEDGER_LITERAL} через builtins.open / io.open) не открывалась — "
                f"значит читает мимо них (например os.open), и ноль тут НЕ есть замер")
            rows.append(row)
            continue
        parse_s = parse_seconds(path, rounds=parse_rounds)
        if parse_s is None:
            row["unmeasured"] = f"{U_LEDGER_ABSENT}: цена разбора не измерена — {path} не прочитан"
            rows.append(row)
            continue
        row["parse_s"] = parse_s
        row["cost_s"] = opens * parse_s
        if opens != m.declared_opens:
            row["findings"].append({
                "kind": F_OPENS_DRIFTED,
                "text": (f"открытий за вид {opens} против объявленных {m.declared_opens} "
                         f"— у объявленного числа есть причина: {m.opens_reason}"),
            })
        if row["cost_s"] > 0:
            row["growth_factor"] = budget_s / row["cost_s"]
            if row["growth_factor"] < min_factor:
                row["findings"].append({
                    "kind": F_MARGIN_SHORT,
                    "text": (f"запас роста {row['growth_factor']:.1f}× ниже порога "
                             f"{min_factor:.1f}× — лента append-only и не усыхает, "
                             f"поэтому бюджет {budget_s:.2f} с будет пройден без единой "
                             f"правки кода"),
                })
        else:
            # Цена строго нулевая бывает только при нуле открытий у пустого ответа:
            # запас тогда не «бесконечен», а НЕ ОПРЕДЕЛЁН, и выдавать его числом нельзя.
            row["growth_factor"] = None
        rows.append(row)

    price_by_id = {r["id"]: r["cost_s"] for r in rows}
    wl = measure_workloads(data, members=members, workloads=workloads,
                           price_by_id=price_by_id, budget_s=workload_budget_s,
                           min_factor=min_factor)
    import_bound = direct_name_bindings(tree_root, members)
    refs = {m.id: view_reference_files(m, tree_root) for m in members}
    declared_files = sorted(LEDGER_CODE_FILES)
    tree_files = sorted(ledger_code_files(tree_root))
    doc = {
        "budget_s": budget_s,
        "min_growth_factor": min_factor,
        "data_dir": str(data),
        "rows": rows,
        "population": {
            "declared": len(members),
            "code_files_declared": declared_files,
            "code_files_in_tree": tree_files,
            "code_files_undeclared": [f for f in tree_files if f not in declared_files],
            "code_files_missing": [f for f in declared_files if f not in tree_files],
        },
        "measured": [r for r in rows if not r["unmeasured"]],
        "unmeasured": [r for r in rows if r["unmeasured"]],
        "workloads": wl,
        "import_bound_views": import_bound,
        "view_reference_files": {k: sorted(v) for k, v in refs.items()},
    }
    doc["findings"] = [dict(f, id=r["id"]) for r in rows for f in r["findings"]]
    doc["findings"].extend(wl["findings"])
    if import_bound:
        doc["findings"].append({
            "kind": F_IMPORT_BOUND_VIEW,
            "id": "counter",
            "text": ("имя вида связано НА ИМПОРТЕ — такой потребитель проходит мимо "
                     "счётчика вызовов молча: " + "; ".join(import_bound)),
        })
    return doc


def format_report(doc: dict) -> List[str]:
    out = [f"— повторный разбор хеш-лент у читающих моделей (заказ G777 п. 1) —",
           f"   каталог: {doc['data_dir']}",
           f"   РЕШЕНИЯ (не замеры): бюджет {doc['budget_s']:.2f} с на вызов вида · "
           f"порог запаса {doc['min_growth_factor']:.1f}×"]
    for r in sorted(doc["rows"], key=lambda x: (x["growth_factor"] is None,
                                                x["growth_factor"] or 0.0)):
        if r["unmeasured"]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {r['id']}: {r['unmeasured']}")
            continue
        door = "область кэша ЕСТЬ" if r["scoped_door"] else "области кэша НЕТ"
        factor = "—" if r["growth_factor"] is None else f"{r['growth_factor']:.1f}×"
        out.append(f"   {r['id']}: {r['bytes']:,} Б · разбор {r['parse_s']:.4f} с · "
                   f"открытий {r['opens']} · цена {r['cost_s']:.3f} с · запас {factor} · {door}")
    wl = doc.get("workloads") or {}
    if wl.get("declared"):
        out.append(f"   — второй множитель: сколько РАЗ прогон зовёт вид (заказ G778 п. 3) —")
        out.append(f"     РЕШЕНИЕ (не замер): бюджет прогона {wl['budget_s']:.2f} с · "
                   f"объявленных прогонов {wl['declared']} — прибор мерит эти, а не "
                   f"утверждает, что других нет")
        for r in wl["rows"]:
            if r["unmeasured"]:
                out.append(f"     [НЕ ИЗМЕРЕНО] {r['id']}: {r['unmeasured']}")
                continue
            calls = " · ".join(f"{k}×{v}" for k, v in sorted(r["calls"].items()) if v)
            factor = "—" if r["growth_factor"] is None else f"{r['growth_factor']:.1f}×"
            out.append(f"     {r['id']}: {calls or 'ни одного вызова'} · полная цена "
                       f"{r['price_s']:.3f} с · запас {factor}")
            if r["not_countable"]:
                for mid, why in sorted(r["not_countable"].items()):
                    out.append(f"       [НЕ ИЗМЕРЕНО] {mid}: {why}")
        for mid, why in sorted(wl["unreached"].items()):
            refs = (doc.get("view_reference_files") or {}).get(mid) or []
            out.append(f"     [НЕ ИЗМЕРЕНО] {mid}: {why}; упоминаний вида в не-тестовом "
                       f"коде: {len(refs)}")
        refs_all = doc.get("view_reference_files") or {}
        if refs_all:
            out.append("     ЗАМЕР рядом с решением — упоминаний вида в не-тестовом коде: "
                       + " · ".join(f"{k}:{len(v)}" for k, v in sorted(refs_all.items()))
                       + f" (прогонов измерено {wl['declared']}; разница и есть мера "
                         f"неполноты населения, а не доказательство полноты)")
        if doc.get("import_bound_views") is not None and not doc["import_bound_views"]:
            out.append("     счётчик подменяет АТРИБУТ МОДУЛЯ; связываний имени вида на "
                       "импорте в дереве не найдено — это ЗАМЕР обходом, а не умолчание")
    findings = doc["findings"]
    if findings:
        out.append(f"   🔴 НАХОДОК {len(findings)}:")
        for f in findings:
            out.append(f"      [{f['kind']}] {f['id']}: {f['text']}")
    else:
        out.append("   ✅ у каждого члена открытий столько, сколько объявлено, и запас выше порога")
    pop = doc["population"]
    if pop["code_files_undeclared"] or pop["code_files_missing"]:
        out.append(f"   ⚠️ население КОДА разошлось с объявленным: "
                   f"не объявлено {pop['code_files_undeclared']} · "
                   f"объявлено и отсутствует {pop['code_files_missing']}")
    else:
        out.append(f"   население замкнуто: лент {pop['declared']}, файлов кода "
                   f"{len(pop['code_files_in_tree'])} — объявленное и найденное совпали "
                   f"(единственное исключение обхода НАЗВАНО: {SELF_REL} — прибор несёт "
                   f"литерал по построению)")
    out.append("   НЕ ДОКЛАДЫВАЕТ: читает ли кто-то ленту через os.open (такой член уйдёт в "
               "третий исход, а не в тишину) · ПОЛНО ли население прогонов (это решение; "
               "замер рядом — число упоминаний вида в коде) · сколько раз за СУТКИ зовут "
               "сам прогон (третий множитель, и он не измерен) · верна ли сама лента "
               "(это вопрос verify(), не этого прибора)")
    out.append("   ADVISORY: прибор только ЧИТАЕТ (ничего не чинит, ни один гейт его не читает)")
    return out


def exit_code(doc: dict) -> int:
    """Вердикт в код возврата, ОТДЕЛЬНОЙ функцией — чтобы отображение «три исхода → три
    числа» проверялось тестом прямо, а не через настоящее население и настоящие ленты.

    Порядок намеренный: **НЕ ИЗМЕРЕНО сильнее находки**. Слепой член означает, что про
    часть населения мы не знаем ничего, и выдать код находки (то есть «измерено, вот что
    нашли») было бы ровно подменой третьего исхода вторым (инв. #17).
    """
    pop = doc["population"]
    wl = doc.get("workloads") or {}
    if doc["unmeasured"] or wl.get("unmeasured") or wl.get("unreached"):
        return 2
    if doc["findings"] or pop["code_files_undeclared"] or pop["code_files_missing"]:
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись повторного разбора хеш-лент у читающих моделей (заказ G777 п. 1)")
    ap.add_argument("--data-dir", default=str(_ROOT / "data"),
                    help="каталог data/ с лентами (ЧИТАЕТСЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--budget-s", type=float, default=REPARSE_BUDGET_S)
    ap.add_argument("--min-factor", type=float, default=MIN_GROWTH_FACTOR)
    ap.add_argument("--parse-rounds", type=int, default=3)
    ap.add_argument("--workload-budget-s", type=float, default=WORKLOAD_BUDGET_S)
    ap.add_argument("--no-workloads", action="store_true",
                    help="не поднимать названные прогоны (второй множитель останется НЕ ИЗМЕРЕН)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = measure(args.data_dir, budget_s=args.budget_s, min_factor=args.min_factor,
                  tree_root=Path(args.tree_root), parse_rounds=args.parse_rounds,
                  workloads=() if args.no_workloads else WORKLOADS,
                  workload_budget_s=args.workload_budget_s)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1, default=str))
    else:
        print("\n".join(format_report(doc)))
    return exit_code(doc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
