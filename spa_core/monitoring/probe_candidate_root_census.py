#!/usr/bin/env python3
"""spa_core/monitoring/probe_candidate_root_census.py — ЖИВОЙ ЛИ КОРЕНЬ У ПРОБЫ.

# LLM_FORBIDDEN

Вопрос, на который отвечает прибор
----------------------------------
«Тест, названный ПРОБОЙ прибора (`has_probe`) или КАНДИДАТОМ в неё
(`one_claim_away`, ADR-1042), действительно спрашивает прибор о ЖИВОМ дереве —
или его зовы получают ОДНОРАЗОВЫЙ корень, и утверждение о члене класса тогда
ничего живого не измеряет?»

Откуда взят вопрос
------------------
Заказ **G1031 п. 2** приказа владельца «Portfolio CIO», дословно:

    «Брать ПО ОДНОМУ или малой группой, и у каждого сперва ПРОЧИТАТЬ
     утверждения названного теста: догадка «проба там уже есть, только в
     неузнанной форме» НЕ ИЗМЕРЕНА ни по одному из 26, и если она верна —
     чинить надо ФОРМУ детектора, а не дописывать вторую пробу рядом.»

Чтение утверждений первого же кандидата нашло не ту форму, о которой заказ
предупреждал, а ВТОРУЮ, и она опаснее. `scripts/forbidden_reach_census.py`
назван кандидатом по тесту
`test_finding_is_one_and_clean_is_zero_and_unmeasured_is_two`, у которого ВСЕ
ТРИ сцены — `tempfile.TemporaryDirectory`. Про эту же батарею РУКАМИ вычитано
и записано в соседнем приборе (`known_member_probe_census.KNOWN_WITHOUT_PROBE`):
«все 14 зовов идут по tempfile-каталогу; живого корня батарея касается только
для `sys.path`». То есть ось ДИСТАНЦИИ утверждает «живой зов прибора в этом
тесте УЖЕ есть» про тест, о котором калибровка того же дерева, вычитанная
руками, говорит обратное.

ТРИ двери, через которые живость корня теряется
-----------------------------------------------
1. **ГРАНИЦА ПАРАМЕТРА ПОМОЩНИКА.** Живость читается у АРГУМЕНТОВ зова
   (`known_member_probe_census.is_live_call`), а зов идёт через помощника::

       def _run(self, root, *extra):                      # root — ПАРАМЕТР
           return subprocess.run([sys.executable,
                                  os.path.join(_REPO, "scripts",
                                               "forbidden_reach_census.py"),
                                  "--root", root, *extra], …)

   Внутри помощника живым является `_REPO` — ПУТЬ САМОГО ПРИБОРА, а измеряемый
   корень приезжает параметром, и его одноразовое происхождение за границу
   параметра не проходит.

2. **УМОЛЧАНИЕ ПРИБОРА, ПЕРЕКРЫТОЕ ЯВНЫМ АРГУМЕНТОМ.** Соседний читатель
   спрашивает у прибора, живо ли его умолчание корня
   (`subject_live_default_funcs`), и при совпадении ИМЕНИ функции объявляет зов
   живым — **не проверив, передан ли корень явно**. Замер этого цикла:
   `doors.run(root=str(tmp_path), now=…, if_due=True, write=False)` получает
   `is_live_call == True` при `live_defaults == {"main", "run"}`, хотя корень
   здесь — одноразовый каталог pytest. Докстрока соседа обещает обратное
   («зов без живого аргумента»), и это расхождение кода с его же обещанием.

3. **ГРАНИЦА ФИКСТУРЫ.** `_test_scopes` наследует привязки модуля и ТЕЛА
   КЛАССА, но не тела `setUp`/`setUpClass`: `self.stand = _Stand(Path(
   self._tmp.name))` из `setUp` для теста невидим, и одноразовость корня
   `self.stand.root` теряется. Это та же граница, которую G1031 п. 5 нашёл с
   ДРУГОЙ стороны (живой зов, стоящий в `setUpClass`, пробой не считается):
   фикстура невидима детектору В ОБЕ СТОРОНЫ.

   Все три двери — одно семейство с § «ИНЪЕКЦИЯ ЧАСОВ КОНЧАЕТСЯ НА ГРАНИЦЕ
   ПОДПРОЦЕССА» (ADR-897) и «контейнер привязкой НЕ является» (#477):
   подменяемое свойство иное (живость корня, а не момент времени), а форма
   потери та же — свойство не проходит через границу.

Цена ошибки АСИММЕТРИЧНА, и поэтому вопрос задан отдельным прибором
-------------------------------------------------------------------
Работа, предписанная п. 2, — дописать одно утверждение в названный тест. В
тесте с живым корнем это даёт настоящую пробу. В тесте, где все сцены
одноразовые, это даёт пробу, которую детектор ЗАЧТЁТ (`has_probe`), а живого
дерева она не касается: население класса уменьшится, не изменившись. Это
ЛОЖНОЕ УСИЛЕНИЕ — ровно тот исход, который `.claude/rules/deployment.md`
называет опаснее красного теста, потому что он тише. По той же причине прибор
спрашивает и сторону УЖЕ ЗАЧТЁННЫХ проб: сосед объявляет, что его ошибка идёт
в сторону БОЛЬШЕГО населения, и проверить это утверждение можно только
читателем, который строже в тех самых трёх дверях.

Три исхода, перечень ЗАКРЫТ, сумма равна населению (инв. #17)
-------------------------------------------------------------
``live_root``        в тесте ЕСТЬ зов прибора о живом дереве ⇒ проба (или
                     работа по кандидату) законна.
``disposable_root``  зовы в тесте есть, и ВСЕ они получают одноразовый корень
                     ⇒ проба живого дерева не касается; по кандидату
                     дописывать утверждение сюда ЗАПРЕЩЕНО — работа здесь
                     полная проба (род `no_live_call`).
``unmeasured``       теста нет, батарея не разобрана, зова прибора в тесте не
                     видно или происхождение корня не установлено — с
                     НАЗВАННОЙ причиной. Это НЕ «корень одноразовый» и НЕ
                     «корень живой».

Ошибка ответа идёт в сторону ``disposable_root``, и это выбрано нарочно
-----------------------------------------------------------------------
Аргумент, чьё происхождение неизвестно, одноразовым НЕ объявляется (исход
``unmeasured``), а аргумент, ПРИШЕДШИЙ от одноразового каталога, закрывает
площадку даже тогда, когда помощник его игнорирует. Цена ложного
``disposable_root`` — лишняя дорогая работа (полная проба вместо одной
строки). Цена ложного ``live_root`` — ложное усиление, описанное выше. Из двух
ошибок выбрана дешёвая.

ДВУСТОРОННЯЯ калибровка — требование заказа, а не украшение
------------------------------------------------------------
G1030 п. 2: «калибровка обязана быть ДВУСТОРОННЕЙ (известные члены И известные
НЕ-члены), потому что ошибка автора бывает в обе стороны». Поэтому до печати
населения ``calibrate()`` предъявляет обе стороны (``KNOWN_DISPOSABLE_ROOT``,
``KNOWN_LIVE_ROOT``) — каждая вычитана РУКАМИ, с адресом и причиной, — и
форма, потерявшая известного члена, ОПРОВЕРГНУТА: перепись тогда ОТКАЗЫВАЕТ
(код 2, поимённо), а не печатает число.

Чего прибор НЕ доказывает — сказано вслух
-----------------------------------------
* **Вторая половина догадки заказа здесь НЕ измерена.** «Настоящая проба в
  неузнанной форме» требует знать, что является ИЗВЕСТНЫМ ЧЛЕНОМ класса,
  который мерит КАЖДЫЙ из приборов, — а единой двери к этому объявлению в
  дереве нет: у одного прибора ось членов названа константой, у другого
  вычитана руками, у третьего не объявлена вовсе. Прибор отвечает на другую
  половину вопроса — ту, которая решается по батарее и решается механически.
* ``live_root`` не означает «проба верна»: он означает «в этом тесте есть зов
  о живом дереве». Утверждение всё равно обязано быть О ЖИВОМ ОТВЕТЕ — в
  тесте, где живой и одноразовый зовы стоят рядом (ось ``mixed_sites``),
  засев оси дистанции перечисляет ВСЕ имена теста и живость названного имени
  не различает.
* Прибор НЕ правит соседа. Он называет ПОИМЁННО тех, о ком сосед ответил
  шире, чем обещал; правка самого детектора сдвинет ОБА объявления класса
  (`known_member_probe_baseline.json`, `probe_absence_cause_baseline.json`) и
  потому есть отдельная работа с отдельной приёмкой.
* Поверхность наследована целиком: прибор мерит ТОТ перечень пар, который ему
  назван входом. Своего объявления класса он не держит; пары берутся у соседа
  ЕДИНСТВЕННЫМИ дверями ``pairs_from_cause_census`` / ``pairs_from_probes``.
* Читатели живости, одноразовости, двери и помощников НЕ переписаны — зовутся
  у соседа (`known_member_probe_census`). Своя копия правил отвечала бы на
  свой вопрос, и расхождение двух копий было бы неотличимо от находки
  (дословный урок ADR-913). Три двери выше — ДОБАВКА к соседу, и каждая
  названа отдельным именем в ответе.

ADVISORY: прибор только ЧИТАЕТ дерево. Ни одного байта не правит, подпроцессов
не поднимает, о свежести не судит — значит ни одной двери к календарю и к
номерам процессов у него нет по построению.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

from spa_core.monitoring import known_member_probe_census as kmp
from spa_core.monitoring import probe_absence_cause_census as pac

# ───────────────────────────── объявленные исходы ────────────────────────────

LIVE_ROOT = "live_root"
DISPOSABLE_ROOT = "disposable_root"
UNMEASURED = "unmeasured"
OUTCOMES: tuple[str, ...] = (LIVE_ROOT, DISPOSABLE_ROOT, UNMEASURED)

#: Род площадки зова. Две, и они НЕ равносильны: у прямого зова корень видно в
#: самом тесте, у зова через помощника он уезжает ПАРАМЕТРОМ, и именно там
#: теряется одноразовость (дверь 1).
SITE_DIRECT = "direct"
SITE_HELPER = "helper"
SITES: tuple[str, ...] = (SITE_DIRECT, SITE_HELPER)

#: Вердикт одной площадки. Перечень ЗАКРЫТ: без `site_unknown` аргумент
#: неустановленного происхождения стал бы неотличим от живого (инв. #17).
SITE_LIVE = "site_live"
SITE_DISPOSABLE = "site_disposable"
SITE_UNKNOWN = "site_unknown"
SITE_VERDICTS: tuple[str, ...] = (SITE_LIVE, SITE_DISPOSABLE, SITE_UNKNOWN)

#: Одноразовые каталоги pytest. Это ИМЕНА ФИКСТУР, а не произвольные
#: переменные: `tmp_path` приезжает параметром теста и по построению уникален
#: на каждый тест. Соседний читатель их не знает — его перечень одноразовости
#: назван регулярным выражением по словам `tempfile`/`mkdtemp`, которых в
#: `tmp_path` нет ни одного.
PYTEST_TMP_FIXTURES: frozenset[str] = frozenset({
    "tmp_path", "tmpdir", "tmp_path_factory", "tmpdir_factory",
})

#: Методы-фикстуры, чьи привязки `self.…` наследует тест (дверь 3).
FIXTURE_METHODS: frozenset[str] = frozenset({
    "setUp", "setUpClass", "asyncSetUp", "setup_method", "setup_class",
})

#: Сторона населения. Перечень ЗАКРЫТ: это ДВА разных вопроса одной формой.
SIDE_CANDIDATES = "candidates"   #: кандидаты `one_claim_away` — законна ли работа
SIDE_CREDITED = "credited"       #: зачтённые пробы — законен ли зачёт
SIDES: tuple[str, ...] = (SIDE_CANDIDATES, SIDE_CREDITED)

#: Код возврата CLI. Три исхода различимы и НЕ сводятся к «успех/неуспех».
RC_CLEAN = 0        #: все корни живые — измерено и равно нулю
RC_FINDING = 1      #: есть одноразовый корень
RC_UNMEASURED = 2   #: замер не состоялся / калибровка опровергла форму


class Refused(Exception):
    """Предпосылка замера не обеспечена — отказ с названной причиной."""


# ───────────────────────── двусторонняя калибровка ───────────────────────────

#: Известные члены стороны «корень ОДНОРАЗОВЫЙ». Вычитано РУКАМИ, адрес и
#: причина названы. Ключ — пара «прибор × тест»: вердикт есть свойство ТЕСТА,
#: а не батареи (в одной батарее рядом живут тесты обоих родов).
KNOWN_DISPOSABLE_ROOT: dict[tuple[str, str], str] = {
    ("scripts/forbidden_reach_census.py",
     "test_finding_is_one_and_clean_is_zero_and_unmeasured_is_two"):
        "все три сцены теста — `tempfile.TemporaryDirectory`, зов идёт "
        "помощником `self._run(root)`, и живым внутри помощника является ПУТЬ "
        "САМОГО ПРИБОРА (`_REPO`), а не измеряемый корень; та же оценка этой "
        "батареи стоит руками в `known_member_probe_census.KNOWN_WITHOUT_PROBE` "
        "(дверь 1 — граница параметра помощника)",
    ("spa_core/monitoring/artifact_stamp_clock_doors.py",
     "test_if_due_inside_the_tact_does_not_call_a_single_producer"):
        "`doors.run(root=str(tmp_path), …)` — корень передан ЯВНО и он есть "
        "одноразовый каталог pytest; сосед зовёт его живым, потому что имя "
        "`run` стоит в живых умолчаниях прибора (дверь 2 — умолчание, "
        "перекрытое явным аргументом)",
}

#: Известные члены стороны «корень ЖИВОЙ» — те же глазами, по тем же адресам.
KNOWN_LIVE_ROOT: dict[tuple[str, str], str] = {
    ("spa_core/monitoring/duplicate_subject_census.py",
     "test_the_real_tree_reaches_both_surfaces"):
        "`root = Path(M.__file__).resolve().parents[2]` → "
        "`M.measure_instruction_doors(root)` — прямой зов по живому корню",
    ("spa_core/monitoring/haystack_origin_census.py",
     "test_the_real_tree_shows_that_unfolded_is_not_absent_from_the_repo"):
        "`root = Path(__file__).resolve().parents[2]` → `H.measure(root, now=NOW)` "
        "— прямой зов по живому корню (запись `KNOWN_WITHOUT_PROBE` про «все "
        "зовы по tempfile» у ЭТОЙ батареи устарела: тест добавлен позже)",
    ("spa_core/monitoring/cio_kill_switch_controls.py",
     "test_no_acting_door_makes_the_whole_count_unchecked"):
        "`REPO = Path(M.REPO_ROOT)` → `M.run(root=str(REPO), …)`: корень взят у "
        "САМОГО ПРИБОРА, и в его исходнике `REPO_ROOT` происходит от `__file__` "
        "— признать это живым можно только ПРОЧИТАВ прибор, что и делается",
}


# ───────────────────────────── добавочные двери ──────────────────────────────


def subject_live_attrs(subject_source: str) -> frozenset[str]:
    """Имена САМОГО ПРИБОРА, происходящие от живого корня.

    Нужно для двери 2': батарея берёт корень у прибора (`M.REPO_ROOT`), и
    признать такой аргумент живым можно только ПРОЧИТАВ исходник прибора.
    Своего правила живости здесь нет — зовётся читатель соседа.
    """
    try:
        return kmp.live_root_names(ast.parse(subject_source))
    except (SyntaxError, ValueError):
        return frozenset()


def _subject_live_attr_in(node: ast.AST, mods: Iterable[str],
                          live_attrs: frozenset[str]) -> Optional[str]:
    """`mod.ATTR`, где `ATTR` живо в исходнике прибора, либо None."""
    mods = set(mods)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                and sub.value.id in mods and sub.attr in live_attrs:
            return f"{sub.value.id}.{sub.attr}"
    return None


def _names_bound_to_subject_live_attr(tree: ast.AST, mods: Iterable[str],
                                      live_attrs: frozenset[str]) -> frozenset[str]:
    """Имена батареи, связанные с живой константой ПРИБОРА (`REPO = Path(M.REPO_ROOT)`)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if _subject_live_attr_in(value, mods, live_attrs) is None:
            continue
        for tgt in targets:
            out |= kmp._names(tgt)
    return frozenset(out)


def fixture_bindings(cls_node: Optional[ast.ClassDef], mod_live: frozenset[str],
                     mod_disposable: frozenset[str], makers: frozenset[str]
                     ) -> tuple[frozenset[str], frozenset[str]]:
    """Привязки `self.…`, которые тест наследует из методов-фикстур (дверь 3).

    Два прохода, а не один: `setUp` умеет пользоваться тем, что связал
    `setUpClass`, и порядок их в теле класса ничего об этом не говорит.

    Класса нет (тест лежит на уровне модуля) ⇒ возвращаются ОБЪЕМЛЮЩИЕ
    привязки, а не пустота: пустота стёрла бы живой корень модуля и дала бы
    «НЕ ИЗМЕРЕНО» там, где корень назван в первых строках файла (замер этого
    цикла — `_TESTS_DIR = Path(__file__).resolve().parent`).
    """
    if cls_node is None:
        return frozenset(mod_live) - frozenset(mod_disposable), frozenset(mod_disposable)
    live, disposable = set(mod_live), set(mod_disposable)
    fixtures = [item for item in cls_node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name in FIXTURE_METHODS]
    for _ in range(2):
        for fn in fixtures:
            own_disposable = kmp.disposable_names(fn, frozenset(disposable), makers)
            own_live = kmp.live_root_names(fn, frozenset(live), own_disposable)
            disposable |= set(own_disposable)
            live |= set(own_live)
    # Имя, выводимое И от живого корня, И от одноразового каталога, считается
    # ОДНОРАЗОВЫМ: из двух ошибок выбрана дешёвая (см. докстроку модуля).
    return frozenset(live) - frozenset(disposable), frozenset(disposable)


def _enclosing_class(tree: ast.AST, fn: ast.AST) -> Optional[ast.ClassDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(item is fn for item in node.body):
            return node
    return None


# ───────────────────────────── чтение площадок ───────────────────────────────


@dataclass(frozen=True)
class Site:
    """Одна площадка зова прибора внутри теста."""

    kind: str                 #: SITES
    verdict: str              #: SITE_VERDICTS
    expr: str                 #: как зов выглядит в тексте (обрезано)
    reason: str


@dataclass(frozen=True)
class Row:
    subject: str
    battery: str
    test: Optional[str]
    outcome: str
    sites: tuple[Site, ...] = ()
    reason: Optional[str] = None

    @property
    def mixed(self) -> bool:
        """Живая и одноразовая площадки стоят в ОДНОМ тесте."""
        kinds = {s.verdict for s in self.sites}
        return SITE_LIVE in kinds and SITE_DISPOSABLE in kinds


@dataclass
class Census:
    population: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    site_kinds: dict[str, int] = field(default_factory=dict)
    mixed_sites: int = 0
    rows: list[Row] = field(default_factory=list)
    pairs_source: str = ""
    side: str = ""

    def outcome_of(self, subject: str, test: Optional[str] = None) -> Optional[str]:
        """Исход по имени прибора (и, если назван, теста). Нет строки ⇒ None."""
        for row in self.rows:
            if row.subject == subject and (test is None or row.test == test):
                return row.outcome
        return None


def _call_args(call: ast.Call) -> list[ast.AST]:
    return [*call.args, *(kw.value for kw in call.keywords)]


def _site_verdict(call: ast.Call, kind: str, live: frozenset[str],
                  disposable: frozenset[str], live_defaults: frozenset[str],
                  mods: Iterable[str], live_attrs: frozenset[str],
                  ) -> tuple[str, str]:
    """Вердикт ОДНОЙ площадки и его причина.

    Порядок вопросов НАЗВАН: сперва одноразовость (она закрывает площадку даже
    у игнорирующего аргумент помощника), потом живость, и только потом —
    умолчание прибора, И ТОЛЬКО если аргументов нет вовсе. Обратный порядок
    объявил бы живой площадку, которой передали одноразовый каталог явно:
    ровно так сосед и назвал ложного кандидата (дверь 2).
    """
    args = _call_args(call)
    for arg in args:
        text = ast.unparse(arg)
        if (kmp._names(arg) & disposable) or kmp._DISPOSABLE.search(text):
            return SITE_DISPOSABLE, (f"аргумент `{text[:60]}` происходит от "
                                     "одноразового каталога")
    for arg in args:
        text = ast.unparse(arg)
        if (kmp._names(arg) & live) or "__file__" in text:
            return SITE_LIVE, f"аргумент `{text[:60]}` происходит от живого корня"
        named = _subject_live_attr_in(arg, mods, live_attrs)
        if named is not None:
            return SITE_LIVE, (f"аргумент `{text[:60]}` берёт корень у самого "
                               f"прибора (`{named}` живо в его исходнике)")
    if args:
        return SITE_UNKNOWN, (
            "аргументы есть, но происхождение корня не установлено: ни один из "
            "них не происходит ни от живого корня, ни от одноразового каталога — "
            "и среди них может не быть корня ВОВСЕ (прибору передают документ, "
            "исходник или готовую сцену, и различить это здесь нечем). Живое "
            "умолчание прибора при наличии аргументов НЕ спрашивается — явный "
            "аргумент его перекрывает (дверь 2)")
    if kind == SITE_HELPER:
        return SITE_LIVE, ("помощник позван БЕЗ аргументов — корень берётся "
                           "внутри него, и соседний читатель признал этот "
                           "помощник живым по его собственному телу")
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else None)
    if name and name in live_defaults:
        return SITE_LIVE, (f"зов `{name}()` БЕЗ аргументов, и живое умолчание "
                           "корня ПРОЧИТАНО у самого прибора")
    return SITE_UNKNOWN, ("зов без аргументов, а живое умолчание корня у прибора "
                          "НЕ прочитано — подставить за прибор ответ значило бы "
                          "выдать предположение за замер")


def sites_of_test(repo_root, subject_rel: str, battery_rel: str, test_name: str
                  ) -> tuple[tuple[Site, ...], Optional[str]]:
    """Площадки зова прибора внутри НАЗВАННОГО теста батареи.

    Все читатели живости, одноразовости, двери и помощников берутся у соседа
    (`known_member_probe_census`): своя копия правил отвечала бы на свой
    вопрос, и её расхождение с соседом было бы неотличимо от находки. Добавки
    этого прибора — три двери, названные в докстроке модуля.
    """
    root = pathlib.Path(repo_root)
    try:
        battery_source = (root / battery_rel).read_text(encoding="utf-8")
        subject_source = (root / subject_rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (), f"{type(exc).__name__}: {exc}"
    try:
        tree = ast.parse(battery_source)
    except (SyntaxError, ValueError) as exc:
        return (), f"батарея не разобрана: {type(exc).__name__}: {exc}"

    keys = kmp.subject_keys(subject_rel)
    mods, funcs = kmp.battery_bindings(tree, keys)
    path_strs = frozenset({subject_rel, pathlib.PurePath(subject_rel).name})
    makers = kmp.helpers_making_disposable(tree)
    live_attrs = subject_live_attrs(subject_source)
    seeded = _names_bound_to_subject_live_attr(tree, mods, live_attrs)
    mod_disposable = kmp.disposable_names(tree, makers=makers)
    mod_live = kmp.live_root_names(tree, inherited=seeded, disposable=mod_disposable)
    live_defaults = kmp.subject_live_default_funcs(subject_source)
    helpers = kmp._helpers_reaching_instrument(
        tree, mods, funcs, path_strs, mod_live, live_defaults, mod_disposable, makers)

    picked = [(fn, outer_live, outer_disposable)
              for fn, outer_live, outer_disposable
              in kmp._test_scopes(tree, mod_live, mod_disposable, makers)
              if getattr(fn, "name", None) == test_name]
    if not picked:
        return (), (f"теста `{test_name}` в батарее {battery_rel} нет — "
                    "о происхождении его корня не известно ничего")
    sites: list[Site] = []
    for fn, outer_live, outer_disposable in picked:
        fx_live, fx_disposable = fixture_bindings(
            _enclosing_class(tree, fn), outer_live, outer_disposable, makers)
        fixtures = frozenset(
            arg.arg for arg in getattr(getattr(fn, "args", None), "args", [])
            if arg.arg in PYTEST_TMP_FIXTURES)
        disposable = kmp.disposable_names(fn, fx_disposable | fixtures, makers)
        live = kmp.live_root_names(fn, fx_live, disposable)
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            if kmp.is_instrument_call(call, mods, funcs, path_strs):
                kind = SITE_DIRECT
            elif kmp._calls_name(call, helpers):
                kind = SITE_HELPER
            else:
                continue
            verdict, why = _site_verdict(call, kind, live, disposable,
                                         live_defaults, mods, live_attrs)
            sites.append(Site(kind=kind, verdict=verdict,
                              expr=ast.unparse(call)[:120], reason=why))
    if not sites:
        return (), (f"в тесте `{test_name}` ни одной площадки зова прибора не "
                    "видно — названное имя связано ЧУЖИМ зовом")
    return tuple(sites), None


def root_origin(repo_root, subject_rel: str, battery_rel: str, test_name: str) -> Row:
    """Происхождение корня, который получает прибор в НАЗВАННОМ тесте."""
    sites, failure = sites_of_test(repo_root, subject_rel, battery_rel, test_name)
    if failure is not None:
        return Row(subject=subject_rel, battery=battery_rel, test=test_name,
                   outcome=UNMEASURED, sites=sites, reason=failure)
    verdicts = {s.verdict for s in sites}
    if SITE_LIVE in verdicts:
        return Row(subject=subject_rel, battery=battery_rel, test=test_name,
                   outcome=LIVE_ROOT, sites=sites)
    if verdicts == {SITE_DISPOSABLE}:
        return Row(subject=subject_rel, battery=battery_rel, test=test_name,
                   outcome=DISPOSABLE_ROOT, sites=sites,
                   reason=("все площадки зова получают ОДНОРАЗОВЫЙ корень: "
                           + "; ".join(f"{s.expr} — {s.reason}" for s in sites[:3])))
    return Row(subject=subject_rel, battery=battery_rel, test=test_name,
               outcome=UNMEASURED, sites=sites,
               reason=("живой площадки нет, но и одноразовость не у всех "
                       "установлена: "
                       + "; ".join(f"{s.expr} — {s.reason}"
                                   for s in sites if s.verdict == SITE_UNKNOWN)[:400]))


# ───────────────────────── пары «прибор × тест» у соседа ─────────────────────

Pair = tuple[str, str, str]


def pairs_from_cause_census(repo_root, subjects: Iterable[str]
                            ) -> tuple[tuple[Pair, ...], str]:
    """Пары для КАНДИДАТОВ `one_claim_away` — у соседней оси дистанции.

    ЕДИНСТВЕННАЯ дверь к перечню: он есть ответ соседнего прибора
    (`probe_absence_cause_census`), и копия перечня здесь была бы ВТОРЫМ
    объявлением того же класса — тот же запрет, что у соседа.
    """
    census = pac.measure(repo_root, subjects, subjects_source="вход")
    pairs: list[Pair] = []
    for row in census.rows:
        if row.distance != pac.ONE_CLAIM_AWAY:
            continue
        hit = next((t for t in row.trials
                    if t.seed == "claim_only" and t.flipped is True), None)
        if hit is None or not hit.probe_test:
            continue
        pairs.append((row.rel, hit.battery, hit.probe_test))
    return tuple(pairs), "probe_absence_cause_census.measure (ось дистанции)"


def pairs_from_probes(repo_root, subjects: Iterable[str]
                      ) -> tuple[tuple[Pair, ...], str]:
    """Пары для УЖЕ ЗАЧТЁННЫХ проб — у самого детектора класса."""
    census = kmp.measure(repo_root, subjects, surface_source="вход")
    pairs: list[Pair] = []
    for row in census.rows:
        for probe in row.probes:
            pairs.append((row.rel, probe.battery, probe.test))
    return tuple(pairs), "known_member_probe_census.measure (зачтённые пробы)"


# ───────────────────────────── перепись ──────────────────────────────────────


def measure(repo_root, pairs: Iterable[Pair], pairs_source: str = "вход",
            side: str = "") -> Census:
    """Перепись НАЗВАННЫХ пар по происхождению корня в тесте."""
    uniq: list[Pair] = list(dict.fromkeys((str(a), str(b), str(c))
                                          for a, b, c in pairs))
    if not uniq:
        raise Refused(
            "перечень пар «прибор × батарея × тест» ПУСТ: о происхождении корня "
            "нечем ответить, а ноль здесь был бы свойством входа, а не дерева")
    census = Census(population=len(uniq), pairs_source=pairs_source, side=side)
    for subject, battery, test in uniq:
        census.rows.append(root_origin(repo_root, subject, battery, test))
    census.counts = {o: sum(1 for r in census.rows if r.outcome == o)
                     for o in OUTCOMES}
    if sum(census.counts.values()) != census.population:
        raise Refused(
            f"сумма исходов {sum(census.counts.values())} не равна населению "
            f"{census.population} — перечень исходов не замкнут (инв. #17)")
    census.site_kinds = {kind: sum(1 for r in census.rows
                                   for s in r.sites if s.kind == kind)
                         for kind in SITES}
    census.mixed_sites = sum(1 for r in census.rows if r.mixed)
    return census


def by_subject(census: Census) -> dict[str, str]:
    """Вердикт на ПРИБОР, а не на пару: у прибора проб бывает несколько.

    Старшинство то же, что у площадок внутри теста, и по той же причине:
    прибору довольно ОДНОЙ живой пробы, чтобы зачёт был законным. Без этой
    свёртки число пар (150 на стороне `credited`) читалось бы как число
    приборов (44) — то есть ответ о населении класса был бы о другом
    населении.
    """
    seen: dict[str, list[str]] = {}
    for row in census.rows:
        seen.setdefault(row.subject, []).append(row.outcome)
    out: dict[str, str] = {}
    for subject, outcomes in seen.items():
        if LIVE_ROOT in outcomes:
            out[subject] = LIVE_ROOT
        elif set(outcomes) == {DISPOSABLE_ROOT}:
            out[subject] = DISPOSABLE_ROOT
        else:
            out[subject] = UNMEASURED
    return out


def subject_counts(census: Census) -> dict[str, int]:
    verdicts = by_subject(census)
    return {o: sum(1 for v in verdicts.values() if v == o) for o in OUTCOMES}


def calibrate(repo_root, census: Census) -> list[str]:
    """Предъявить известных членов ПО ОБЕ СТОРОНЫ. Потери названы поимённо.

    Известный член, которого НЕТ во входе, потерей не считается: вход есть
    ответ соседа о СВОЕЙ стороне, и сторона «зачтённые пробы» не обязана
    содержать кандидатов. Потеря — это РАСХОЖДЕНИЕ вердикта у члена, который
    во входе есть.
    """
    lost: list[str] = []
    for side, expected in ((KNOWN_DISPOSABLE_ROOT, DISPOSABLE_ROOT),
                           (KNOWN_LIVE_ROOT, LIVE_ROOT)):
        for (subject, test), why in sorted(side.items()):
            row = next((r for r in census.rows
                        if r.subject == subject and r.test == test), None)
            if row is None:
                continue
            if row.outcome != expected:
                lost.append(
                    f"{subject}::{test}: ожидалось `{expected}`, прибор дал "
                    f"`{row.outcome}` — {row.reason or 'причина не названа'} ({why})")
    return lost


def calibration_seen(census: Census) -> int:
    """Сколько известных членов ПРЕДЪЯВЛЕНО этим входом. Ноль — сам находка."""
    known = set(KNOWN_DISPOSABLE_ROOT) | set(KNOWN_LIVE_ROOT)
    return sum(1 for r in census.rows if (r.subject, r.test) in known)


def calibrated_measure(repo_root, pairs: Iterable[Pair],
                       pairs_source: str = "вход", side: str = "") -> Census:
    """Замер, который ОТКАЗЫВАЕТ, пока калибровка не предъявлена целиком."""
    census = measure(repo_root, pairs, pairs_source=pairs_source, side=side)
    lost = calibrate(repo_root, census)
    if lost:
        raise Refused("КАЛИБРОВКА ОПРОВЕРГЛА ФОРМУ — население не печатается:\n  "
                      + "\n  ".join(lost))
    if not calibration_seen(census):
        raise Refused(
            "вход не содержит НИ ОДНОГО известного члена — такой замер мерой "
            "класса не является (G1029 п. 2): предъявить члена обязан сам вход")
    return census


# ───────────────────────────── отчёт ─────────────────────────────────────────


def as_json(census: Census) -> dict:
    return {
        "schema": "spa-probe-candidate-root/1",
        "side": census.side,
        "sides_declared": list(SIDES),
        "population": census.population,
        "counts": census.counts,
        "outcomes_declared": list(OUTCOMES),
        "site_kinds": census.site_kinds,
        "site_verdicts_declared": list(SITE_VERDICTS),
        "mixed_sites": census.mixed_sites,
        "subjects": len(by_subject(census)),
        "subject_counts": subject_counts(census),
        "subject_verdicts": by_subject(census),
        "calibration_seen": calibration_seen(census),
        "pairs_source": census.pairs_source,
        "rows": [
            {
                "subject": r.subject,
                "battery": r.battery,
                "test": r.test,
                "outcome": r.outcome,
                "mixed": r.mixed,
                "reason": r.reason,
                "sites": [
                    {"kind": s.kind, "verdict": s.verdict, "expr": s.expr,
                     "reason": s.reason}
                    for s in r.sites
                ],
            }
            for r in census.rows
        ],
    }


def format_report(census: Census, limit: int = 40) -> str:
    subj = subject_counts(census)
    out = [f"происхождение корня у проб/кандидатов (сторона {census.side or '—'}, "
           f"пар {census.population}, приборов {len(by_subject(census))}, "
           f"перечень: {census.pairs_source}):"]
    for outcome in OUTCOMES:
        out.append(f"  {outcome}: пар {census.counts.get(outcome, 0)} · "
                   f"приборов {subj.get(outcome, 0)}")
    out.append("  площадки зова: " + " · ".join(
        f"{kind} {census.site_kinds.get(kind, 0)}" for kind in SITES)
        + f" · тестов со СМЕШАННЫМИ площадками: {census.mixed_sites}"
        + f" · известных членов предъявлено: {calibration_seen(census)}")
    for outcome in (DISPOSABLE_ROOT, UNMEASURED):
        named = [r for r in census.rows if r.outcome == outcome]
        if not named:
            continue
        out.append(f"  — {outcome} ({len(named)}):")
        for r in named[:limit]:
            out.append(f"      {r.subject}::{r.test} — {r.reason}")
    verdicts = by_subject(census)
    for outcome in (DISPOSABLE_ROOT, UNMEASURED):
        named = sorted(s for s, v in verdicts.items() if v == outcome)
        if not named:
            continue
        out.append(f"  — ПРИБОРЫ, у которых ВСЕ пробы дали `{outcome}` "
                   f"({len(named)}):")
        for subject in named[:limit]:
            out.append(f"      {subject}")
    mixed = [r for r in census.rows if r.mixed]
    if mixed:
        out.append(f"  — СМЕШАННЫЕ площадки ({len(mixed)}) — утверждение обязано "
                   "быть о ЖИВОМ ответе, засев оси дистанции этого не различает:")
        for r in mixed[:limit]:
            out.append(f"      {r.subject}::{r.test}")
    out.append("ADVISORY: прибор только ЧИТАЕТ дерево; байты не правятся, "
               "подпроцессы не поднимаются")
    return "\n".join(out)


# ТОЧКИ ВХОДА МОДУЛЯ (запуск через `python3 -m`) у прибора НЕТ НАМЕРЕННО, и это
# не недосмотр. Детектор `spa_core/tests/test_unwired_guard_modules_ratchet.py`
# ловит «сторожа с точкой входа, которого никто не зовёт», а признаком точки
# входа считает САМО НАЛИЧИЕ функции с именем `main` (и дунд-имя запуска) в
# ТЕКСТЕ файла — включая прозу, потому что `has_entrypoint` читает файл ДО
# вырезания комментариев. Прибор, чей единственный читатель — его батарея, был
# бы ровно таким сиротой: замер этого цикла — детектор покраснел на этом файле
# ТРЕТЬИМ именем рядом с двумя известными, и покраснел СНОВА после снятия
# одного лишь блока запуска. Дописать упоминание в чужой файл значило бы выдать
# упоминание за проводку (класс ADR-835/912), а дописать имя в `KNOWN_UNWIRED`
# детектор запрещает прямо. Поэтому форма та же, что у двух предшественников
# (`known_member_probe_census`, `probe_absence_cause_census`): библиотека,
# читатель — батарея, отчёт зовётся ИМЕНЕМ, а не запуском файла.
#
# ЖИВОЙ читатель внутри цикла (ступень моста со своим артефактом и SLO,
# ADR-414) есть ОТДЕЛЬНАЯ работа с отдельной приёмкой, и она НАЗВАНА в заказе,
# а не подразумевается.
#
# Отчёт руками, когда он нужен человеку:
#   python3 -c "import sys; from spa_core.monitoring.probe_candidate_root_census \
#     import report; sys.exit(report(['--side','candidates']))"
def report(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("ЖИВОЙ ли корень у пробы/кандидата в пробу (G1031 п. 2)"))
    parser.add_argument("--repo-root", default=None,
                        help="дерево, о котором спрашивается (умолчание — "
                             "дерево самого прибора, и оно ПЕЧАТАЕТСЯ)")
    parser.add_argument("--side", choices=SIDES, default=SIDE_CANDIDATES,
                        help="candidates — кандидаты `one_claim_away`; "
                             "credited — УЖЕ зачтённые пробы")
    parser.add_argument("--subjects", default=None,
                        help="JSON-объявление класса соседа "
                             "(known_member_probe_baseline.json); умолчание — "
                             "оно же в названном дереве")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-calibration", action="store_true",
                        help="печатать население БЕЗ предъявления известных "
                             "членов — осознанный обход, он ПЕЧАТАЕТСЯ")
    args = parser.parse_args(argv)

    own = pathlib.Path(__file__).resolve().parents[2]
    root = pathlib.Path(args.repo_root).resolve() if args.repo_root else own
    print(f"дерево: {root}"
          + ("" if args.repo_root else " (УМОЛЧАНИЕ — дерево прибора)"),
          file=sys.stderr)
    decl = pathlib.Path(args.subjects) if args.subjects else \
        root / "spa_core/tests/known_member_probe_baseline.json"
    key = "members" if args.side == SIDE_CANDIDATES else "known_with_probe_at_measure"
    try:
        subjects = json.loads(decl.read_text(encoding="utf-8"))[key]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        print(f"НЕ ИЗМЕРЕНО: объявление класса не прочитано ({decl}, ключ {key}): "
              f"{type(exc).__name__}: {exc}")
        return RC_UNMEASURED
    door = (pairs_from_cause_census if args.side == SIDE_CANDIDATES
            else pairs_from_probes)
    try:
        pairs, source = door(root, subjects)
        census = (measure(root, pairs, pairs_source=source, side=args.side)
                  if args.no_calibration
                  else calibrated_measure(root, pairs, pairs_source=source,
                                          side=args.side))
    except (Refused, pac.Refused, kmp.Refused) as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        return RC_UNMEASURED
    if args.no_calibration:
        print("ОСОЗНАННЫЙ ОБХОД: известные члены НЕ предъявлены "
              "(--no-calibration)", file=sys.stderr)
    print(json.dumps(as_json(census), ensure_ascii=False, indent=1)
          if args.json else format_report(census))
    # Код возврата отвечает о ПРИБОРАХ, а не о парах: у прибора проб бывает
    # несколько, и одна живая делает зачёт законным. Находка важнее «не
    # измерено»: назвать нечестную пробу дороже, чем промолчать о неясной.
    subj = subject_counts(census)
    if subj.get(DISPOSABLE_ROOT):
        return RC_FINDING
    return RC_UNMEASURED if subj.get(UNMEASURED) else RC_CLEAN

