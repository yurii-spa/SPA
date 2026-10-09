#!/usr/bin/env python3
"""Причина провала фазы `call` — перепись по junit-записи прогона (заказ G108 п. 1).

**Зачем (цикл #812, 2026-10-09, ADR-675; заказ поставлен ADR-534 01.10, лежал остатком
восемь суток).** ADR-534 измерил, КУДА уходит время шага тестов, и попутно назвал
население провалов: **61 на фазе `call` и 19 «ошибок»**. Вторую половину он закрыл сам —
девятнадцать «ошибок» оказались ЧЕТЫРЬМЯ сломанными `setUpClass`, то есть число
дефектов там в пять раз меньше числа провалов. Первая половина осталась словом:

> «у провалов фазы `call` общего класса нет, и свести их к числу ДЕФЕКТОВ можно только
> по причине — а она живёт в junit-записи (полный `longrepr`), не в потоковой (там
> первая строка). Мерить надо у junit, когда он есть, и объявлять НЕ ИЗМЕРЕНО, когда
> сессия оборвана».

Почему это не арифметика: «80 провалов» читается как «80 поломок», и на этом числе
принимают решение — брать ли красный набор в работу и сколько это стоит. Замер ниже
говорит, что множитель между провалами и дефектами существует и на фазе `call` тоже.

**Что меряет прибор — ровно одно:** население провалов junit-записи, разложенное по
ТРЁМ закрытым наборам исходов (фаза · опознание причины · опознание места), и число
ПРИЧИН среди провалов фазы `call`. Сумма каждого набора равна населению (инв. #17):
без тождества «свести к причине» отвечается долей от доли, а остаток исчезает молча.

**Ответом служит ВИЛКА, а не одно число.** Механический ключ причины односторонен в
ОБЕ стороны, и обе названы:

* **слияние занижает.** Два `KeyError: 'identity'` из несвязанных модулей ключ склеит
  в одну причину. Поэтому нижний край — не число ключей, а число СВЯЗНЫХ КОМПОНЕНТ
  графа, где ребро ставит либо равенство причины, либо общий НАЗВАННЫЙ след в тексте
  исключения (`<путь>.py:<строка>` внутри самого сообщения). Компонент не больше, чем
  ключей, — значит это нижний край.
* **дробление завышает.** Одна поломка, предъявленная из двух разных тестов, даёт два
  места и два ключа `причина+место`. Поэтому верхний край — число ключей
  `причина+место`.

Ни один край не теорема, и это сказано вслух: причина, предъявленная ДВУМЯ разными
типами исключения и без общего следа, разойдётся на два компонента, то есть нижний
край может оказаться выше истины. Прибор печатает, сколько провалов склеило именно
ребро следа (`merged_by_evidence`) — чтобы цена слияния была числом, а не допущением.

**Фаза `<error>` читается ПРЕФИКСОМ, который печатает сам pytest, и СВЕРЯЕТСЯ со
второй записью.** В junit-XML машинного поля фазы нет вовсе: `<failure>` пишется для
`call`, `<error>` — для установки, разборки и сбора, а что именно случилось, стои́т в
атрибуте `message` литеральным префиксом писателя (`failed on setup with`, …). Разбор
прозы подстрокой запрещён правилом — поэтому префикс здесь не последнее слово: при
переданной потоковой записи (`--stream`) фаза берётся из её МАШИННОГО поля `w`, а
чтение префикса становится проверяемым утверждением (печатаются согласие, расхождение
и «в потоковой записи нет»). Префикс, не совпавший ни с одним известным, даёт
НАЗВАННЫЙ третий исход `phase_unnamed`, а не догадку.

**Нет junit-записи ⇒ НЕ ИЗМЕРЕНО, и это сам ответ.** junit пишется В КОНЦЕ сессии;
оборванная сессия своей записи не оставляет никогда (ADR-474). Замер 08.10 на прогоне
5853 поймал это живьём: у ноги 3.12 `junit-spa_core.xml` есть, у ноги 3.11 его нет —
одна и та же команда, два разных исхода, и выдать второй за «провалов не было» значило
бы нарушить инв. #17 внутри прибора, который этот класс и ловит.

**Ноль провалов — измерено и равно нулю, а не «не измерено».** Запись есть, случаи в
ней есть, провалов нет: третий исход сюда не относится, и различие печатается словами.

Прибор только ЧИТАЕТ: ни одного теста, порога, базы храповика или воркфлоу он не
трогает. Коды возврата: **0** — измерено (в том числе ноль провалов) · **2** — НЕ
ИЗМЕРЕНО с названной причиной. Только stdlib (инв. #4).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, NamedTuple

# --- исходы чтения записи (контракт, читается тестами) --------------------------
READ_OK = "read"
READ_ABSENT = "record_absent"
READ_UNREADABLE = "record_unreadable"
READ_NO_SUITE = "no_testsuite"
READ_NO_CASES = "no_testcases"

# --- закрытый набор фаз --------------------------------------------------------
PHASE_CALL = "call"
PHASE_SETUP = "setup"
PHASE_TEARDOWN = "teardown"
PHASE_COLLECT = "collect"
PHASE_UNNAMED = "phase_unnamed"
PHASES = (PHASE_CALL, PHASE_SETUP, PHASE_TEARDOWN, PHASE_COLLECT, PHASE_UNNAMED)

# Префиксы, которые печатает САМ писатель junit у элемента <error>. Это литералы
# чужого кода, не проза отчёта; несовпадение даёт PHASE_UNNAMED, а не догадку.
_ERROR_PREFIXES = (
    ("failed on setup", PHASE_SETUP),
    ("test setup failure", PHASE_SETUP),
    ("failed on teardown", PHASE_TEARDOWN),
    ("test teardown failure", PHASE_TEARDOWN),
    ("collection failure", PHASE_COLLECT),
    ("collection error", PHASE_COLLECT),
)

# --- закрытый набор исходов опознания причины ----------------------------------
CAUSE_NAMED = "cause_named"
CAUSE_NO_TYPE = "cause_no_exception_type"
CAUSE_NO_MESSAGE = "cause_no_message"
CAUSE_CLASSES = (CAUSE_NAMED, CAUSE_NO_TYPE, CAUSE_NO_MESSAGE)

# --- закрытый набор исходов опознания места ------------------------------------
SITE_REPO = "site_repo_frame"
SITE_FOREIGN = "site_only_foreign_frames"
SITE_NONE = "site_no_frames"
SITE_CLASSES = (SITE_REPO, SITE_FOREIGN, SITE_NONE)

# Кадр `--tb=short`: «путь:строка: in имя».
_FRAME = re.compile(r"^(?P<file>[^\s][^:]*):(?P<line>\d+): in (?P<func>.+)$")

# Строку текста исключения pytest помечает `E` в первой позиции. Её надо отбросить
# ДО разбора кадров, и это не украшение: в этом наборе полно тестов, которые гоняют
# дочерний pytest и судят по его выводу, а вывод несёт кадры ЧУЖОГО прогона. Якорь
# `^` их не отсекает — `[^:]*` съедает и `E`, и пробелы, поэтому `E   a/b.py:9: in f`
# разбирается как кадр с «файлом» `E   a/b.py` (замер цикла #812 на собственном
# контроле). Место провала тогда берётся у чужого прогона, и верхний край вилки
# дробится по ложному признаку.
_ERROR_TEXT_LINE = re.compile(r"^E(\s|$)")

# Чужой кадр: интерпретатор и его пакеты. Путь репозитория относителен по построению
# (pytest печатает его от rootdir), чужой — абсолютен либо лежит в site-packages.
_FOREIGN = ("/site-packages/", "/hostedtoolcache/", "/lib/python", "<frozen ")

# Тип исключения в голове сообщения: «Имя: …» либо «пакет.Имя: …».
_EXC_HEAD = re.compile(r"^(?P<kind>[A-Za-z_][\w.]*(?:\.[A-Za-z_]\w*)*)\s*:\s")

# Названный след внутри САМОГО сообщения исключения (не в кадрах): место, на которое
# жалуется проваленное утверждение. Ребро графа ставится именно по нему.
_EVIDENCE = re.compile(r"[\w./-]*[\w-]\.py:\d+")

# Нормализация сообщения в скелет причины. ДВА набора, и различие между ними — это
# и есть измеренная цена слияния: кавычки несут ИМЯ (у `KeyError: \'identity\'` имя ключа
# и есть причина), поэтому грубый скелет их стирает и склеивает, а точный сохраняет.
# Порядок внутри набора существен: кавычки сперва, иначе путь внутри кавычек уже
# заменён и перестаёт быть путём.
_SUBS_LITERALS = (
    (re.compile(r"'[^']*'"), "'…'"),
    (re.compile(r'"[^"]*"'), '"…"'),
)
_SUBS_COMMON = (
    (re.compile(r"[\w./-]*[\w-]\.(?:py|json|jsonl|md|yml|yaml|xml|sh|txt)\b"), "<путь>"),
    (re.compile(r"\b[0-9a-f]{8,}\b"), "<hash>"),
    (re.compile(r"\d+(?:[.,]\d+)?"), "#"),
)
_SKELETON_MAX = 120


class Failure(NamedTuple):
    """Один провал записи. ``kind`` = ``None`` ⇒ тип исключения не опознан."""

    classname: str
    name: str
    tag: str                    # failure | error
    phase: str                  # из PHASES
    message: str                # атрибут message, как есть
    kind: str | None            # тип исключения
    skeleton: str               # точный скелет сообщения (кавычки сохранены)
    coarse: str                 # грубый скелет (кавычки стёрты) — ключ слияния
    site: str | None            # глубочайший кадр репозитория «файл:строка»
    frames: int                 # сколько кадров разобрано
    foreign_frames: int
    evidence: frozenset[str]    # названные следы внутри сообщения

    @property
    def nodeid(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name

    @property
    def cause_class(self) -> str:
        if not self.message.strip():
            return CAUSE_NO_MESSAGE
        return CAUSE_NAMED if self.kind else CAUSE_NO_TYPE

    @property
    def site_class(self) -> str:
        if self.site:
            return SITE_REPO
        return SITE_FOREIGN if self.foreign_frames else SITE_NONE

    @property
    def cause_key(self) -> tuple[str, str]:
        return (self.kind or "«тип не назван»", self.skeleton)

    @property
    def coarse_key(self) -> tuple[str, str]:
        return (self.kind or "«тип не назван»", self.coarse)

    @property
    def cause_site_key(self) -> tuple[str, str, str]:
        return (*self.cause_key, self.site or "«место не названо»")


class Census(NamedTuple):
    """Итог переписи одной junit-записи. ``read != READ_OK`` ⇒ числа бессмысленны."""

    read: str
    reason: str
    path: str
    collected: int                        # <testcase> всего
    failures: tuple[Failure, ...]
    # сверка фазы со второй записью
    stream_agreed: int
    stream_disagreed: int
    stream_absent_for: int
    stream_read: str | None

    # --- тождества учёта (инв. #17) ---
    @property
    def population(self) -> int:
        return len(self.failures)

    def by_phase(self) -> Counter:
        return Counter(f.phase for f in self.failures)

    def by_cause_class(self) -> Counter:
        return Counter(f.cause_class for f in self.failures)

    def by_site_class(self) -> Counter:
        return Counter(f.site_class for f in self.failures)

    def identities_hold(self) -> bool:
        """Сумма ОБЪЯВЛЕННЫХ имён набора равна населению.

        Сумма значений самого счётчика равнялась бы населению ВСЕГДА — такое
        тождество неопровержимо, то есть не является проверкой. Считать надо по
        перечню имён, который печатается читателю: род, в перечень не попавший,
        исчезает из строки молча, и именно это обязано краснеть.
        """
        n = self.population
        phase, cause, site = self.by_phase(), self.by_cause_class(), self.by_site_class()
        return (sum(phase.get(k, 0) for k in PHASES) == n
                and sum(cause.get(k, 0) for k in CAUSE_CLASSES) == n
                and sum(site.get(k, 0) for k in SITE_CLASSES) == n)

    @property
    def call(self) -> tuple[Failure, ...]:
        return tuple(f for f in self.failures if f.phase == PHASE_CALL)

    @property
    def measured(self) -> bool:
        return self.read == READ_OK


class Fork(NamedTuple):
    """Вилка числа дефектов по населению одной фазы. Края НАЗВАНЫ, не выведены."""

    population: int
    cause_groups: int           # ключей «тип + точный скелет»
    coarse_groups: int          # ключей «тип + грубый скелет» (кавычки стёрты)
    lower: int                  # связные компоненты (слияние)
    upper: int                  # ключи «причина+место» (дробление)
    merged_by_evidence: int     # провалов, склеенных ребром следа сверх равенства причин
    largest_component: int
    groups: tuple[tuple[tuple[str, str], int], ...]


def _unreadable(kind: str, reason: str, path: str) -> Census:
    return Census(read=kind, reason=reason, path=path, collected=0, failures=(),
                  stream_agreed=0, stream_disagreed=0, stream_absent_for=0,
                  stream_read=None)


def skeleton_of(message: str, *, erase_literals: bool = False) -> str:
    """Скелет сообщения: пути, хэши и числа заменены на род.

    ``erase_literals=True`` стирает ещё и содержимое кавычек — это ГРУБЫЙ скелет,
    которым ставится ребро слияния. Он склеивает `KeyError: \'identity\'` с
    `KeyError: \'verdict\'`, то есть заведомо занижает; цена этого склеивания и есть
    то, что печатается вилкой, а не прячется в выборе одного ключа.

    Берётся ПЕРВАЯ строка: дальше у `--tb=short` идёт развёрнутое сравнение, и оно
    меняется у каждого случая, из-за чего один дефект разошёлся бы на столько причин,
    сколько у него проваленных утверждений.
    """
    head = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    body = head
    exc = _EXC_HEAD.match(body)
    if exc:
        body = body[exc.end():]
    for pattern, placeholder in (_SUBS_LITERALS if erase_literals else ()) + _SUBS_COMMON:
        body = pattern.sub(placeholder, body)
    body = re.sub(r"\s+", " ", body).strip()
    return body[:_SKELETON_MAX]


def kind_of(message: str) -> str | None:
    """Тип исключения из головы сообщения. Нет головы ⇒ ``None``, а не «unknown»."""
    head = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    exc = _EXC_HEAD.match(head)
    return exc.group("kind") if exc else None


def phase_of(tag: str, message: str) -> str:
    """Фаза провала по элементу junit.

    ``<failure>`` писатель junit ставит ТОЛЬКО фазе `call`; у ``<error>`` фазу несёт
    литеральный префикс сообщения. Неизвестный префикс ⇒ PHASE_UNNAMED.
    """
    if tag == "failure":
        return PHASE_CALL
    low = (message or "").strip().lower()
    for prefix, phase in _ERROR_PREFIXES:
        if low.startswith(prefix):
            return phase
    return PHASE_UNNAMED


def frames_of(text: str) -> tuple[list[tuple[str, int]], int]:
    """Кадры `--tb=short`: (кадры репозитория, число чужих кадров)."""
    mine: list[tuple[str, int]] = []
    foreign = 0
    for line in (text or "").splitlines():
        if _ERROR_TEXT_LINE.match(line):
            continue
        hit = _FRAME.match(line.rstrip())
        if not hit:
            continue
        path = hit.group("file")
        if any(mark in path for mark in _FOREIGN) or path.startswith("/"):
            foreign += 1
        else:
            mine.append((path, int(hit.group("line"))))
    return mine, foreign


def evidence_of(message: str) -> frozenset[str]:
    """Названные следы внутри сообщения исключения.

    Кадры сюда не попадают по построению: читается атрибут ``message``, а кадры
    живут в теле элемента. Иначе ребро графа ставил бы путь самого теста, и граф
    склеил бы всё, что упало в одном файле.
    """
    return frozenset(_EVIDENCE.findall(message or ""))


def _failure_from(classname: str, name: str, tag: str, message: str, text: str) -> Failure:
    mine, foreign = frames_of(text)
    return Failure(
        classname=classname, name=name, tag=tag,
        phase=phase_of(tag, message), message=message or "",
        kind=kind_of(message), skeleton=skeleton_of(message),
        coarse=skeleton_of(message, erase_literals=True),
        site=(f"{mine[-1][0]}:{mine[-1][1]}" if mine else None),
        frames=len(mine), foreign_frames=foreign,
        evidence=evidence_of(message),
    )


def census_from_path(path: Path, *, stream: Path | None = None) -> Census:
    """Перепись одной junit-записи. Файла нет ⇒ READ_ABSENT (это сам ответ)."""
    if not path.exists():
        return _unreadable(READ_ABSENT, f"junit-записи нет по пути {path}", str(path))
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        return _unreadable(READ_UNREADABLE, f"junit-запись не разобрана: {exc}", str(path))
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return _unreadable(READ_NO_SUITE, "в записи нет ни одного <testsuite>", str(path))
    collected = 0
    failures: list[Failure] = []
    for suite in suites:
        for case in suite.iter("testcase"):
            collected += 1
            for child in case:
                if child.tag not in ("failure", "error"):
                    continue
                failures.append(_failure_from(
                    case.attrib.get("classname", ""), case.attrib.get("name", ""),
                    child.tag, child.attrib.get("message", ""), child.text or "",
                ))
    if collected == 0:
        return _unreadable(READ_NO_CASES, "в записи нет ни одного <testcase>", str(path))
    agreed = disagreed = absent_for = 0
    stream_read: str | None = None
    if stream is not None:
        phases, stream_read = stream_phases(stream)
        for failure in failures:
            observed = phases.get(failure.nodeid)
            if observed is None:
                absent_for += 1
            elif observed == failure.phase:
                agreed += 1
            else:
                disagreed += 1
    return Census(read=READ_OK, reason="запись прочитана", path=str(path),
                  collected=collected, failures=tuple(failures),
                  stream_agreed=agreed, stream_disagreed=disagreed,
                  stream_absent_for=absent_for, stream_read=stream_read)


def stream_phases(path: Path) -> tuple[dict[str, str], str]:
    """Фаза провала из МАШИННОГО поля `w` потоковой записи, ключ — junit-имя.

    Имя потоковой записи (`путь/файл.py::Класс::тест`) приводится к паре
    junit (`пакет.файл.Класс`, `тест`): сверять надо одно и то же имя, иначе
    «в записи нет» получалось бы у каждого провала и сверка молча опустела бы.
    """
    if not path.exists():
        return {}, READ_ABSENT
    out: dict[str, str] = {}
    seen = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("e") != "fail":
                    continue
                seen += 1
                nodeid, phase = event.get("n"), event.get("w")
                if not isinstance(nodeid, str) or not isinstance(phase, str):
                    continue
                out[_junit_name(nodeid)] = phase
    except OSError as exc:
        return {}, f"{READ_UNREADABLE}: {exc}"
    return out, (READ_OK if seen else READ_NO_CASES)


def _junit_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    module = parts[0]
    if module.endswith(".py"):
        module = module[:-3]
    module = module.replace("/", ".")
    if len(parts) == 1:
        return module
    classname = ".".join([module, *parts[1:-1]])
    return f"{classname}::{parts[-1]}"


def fork_of(failures: Iterable[Failure]) -> Fork:
    """Вилка числа дефектов: компоненты графа … ключи «причина+место»."""
    items = list(failures)
    n = len(items)
    cause_groups = Counter(f.cause_key for f in items)
    upper = len({f.cause_site_key for f in items})

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[rb] = ra
        return True

    by_coarse: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, failure in enumerate(items):
        by_coarse[failure.coarse_key].append(i)
    for members in by_coarse.values():
        for other in members[1:]:
            union(members[0], other)

    by_token: dict[str, list[int]] = defaultdict(list)
    for i, failure in enumerate(items):
        for token in failure.evidence:
            by_token[token].append(i)
    merged = 0
    for members in by_token.values():
        for other in members[1:]:
            if union(members[0], other):
                merged += 1

    components: Counter = Counter(find(i) for i in range(n))
    return Fork(
        population=n, cause_groups=len(cause_groups), coarse_groups=len(by_coarse),
        lower=len(components), upper=upper, merged_by_evidence=merged,
        largest_component=(max(components.values()) if components else 0),
        groups=tuple(cause_groups.most_common()),
    )


def format_census(census: Census, *, shown: int = 12) -> str:
    if not census.measured:
        return (f"НЕ ИЗМЕРЕНО · {census.path}\n"
                f"   причина: {census.reason}\n"
                "   «провалов не найдено» здесь НЕ утверждается (инв. #17)")
    lines = [f"ИЗМЕРЕНО · {census.path}: случаев {census.collected}, "
             f"провалов {census.population}"]
    if census.population == 0:
        lines.append("   провалов НЕТ — измерено и равно нулю (не то же, что НЕ ИЗМЕРЕНО)")
        return "\n".join(lines)
    phase = census.by_phase()
    lines.append("   фазы (сумма = населению): " + " · ".join(
        f"{name} {phase.get(name, 0)}" for name in PHASES))
    cause = census.by_cause_class()
    lines.append("   опознание причины (сумма = населению): " + " · ".join(
        f"{name} {cause.get(name, 0)}" for name in CAUSE_CLASSES))
    site = census.by_site_class()
    lines.append("   опознание места (сумма = населению): " + " · ".join(
        f"{name} {site.get(name, 0)}" for name in SITE_CLASSES))
    lines.append(f"   тождества учёта: {'ДЕРЖАТСЯ' if census.identities_hold() else 'НЕ ДЕРЖАТСЯ'}")
    if census.stream_read is None:
        lines.append("   сверка фазы со второй записью: НЕ СПРОШЕНА (--stream не передан)")
    elif census.stream_read != READ_OK:
        lines.append(f"   сверка фазы со второй записью: НЕ ИЗМЕРЕНА — {census.stream_read}")
    else:
        lines.append(f"   сверка фазы со второй записью: согласие {census.stream_agreed} · "
                     f"расхождение {census.stream_disagreed} · "
                     f"в потоковой записи нет {census.stream_absent_for}")
    fork = fork_of(census.call)
    if fork.population == 0:
        lines.append("   фаза `call`: провалов нет — вилка не считается")
        return "\n".join(lines)
    call_cause = Counter(f.cause_class for f in census.call)
    lines.append("   из них опознание причины: " + " · ".join(
        f"{name} {call_cause.get(name, 0)}" for name in CAUSE_CLASSES))
    lines.append(f"   фаза `call`: провалов {fork.population} · ПРИЧИН (ключей) {fork.cause_groups}"
                 f" · грубых ключей {fork.coarse_groups}")
    lines.append(f"   ВИЛКА ДЕФЕКТОВ: НЕ МЕНЬШЕ {fork.lower} и НЕ БОЛЬШЕ {fork.upper}"
                 f" (склеено ребром следа {fork.merged_by_evidence} · "
                 f"крупнейший компонент {fork.largest_component})")
    for (kind, skel), count in fork.groups[:shown]:
        mark = "✖" if count > 1 else "·"
        lines.append(f"   {mark} {count:3d}  {kind}: {skel}")
    if fork.cause_groups > shown:
        lines.append(f"   … и ещё {fork.cause_groups - shown} причин(а) по одному провалу")
    return "\n".join(lines)


def as_json(census: Census) -> dict:
    payload = {
        "read": census.read, "reason": census.reason, "path": census.path,
        "collected": census.collected, "population": census.population,
        "by_phase": dict(census.by_phase()),
        "by_cause_class": dict(census.by_cause_class()),
        "by_site_class": dict(census.by_site_class()),
        "identities_hold": census.identities_hold(),
        "stream_read": census.stream_read,
        "stream_agreed": census.stream_agreed,
        "stream_disagreed": census.stream_disagreed,
        "stream_absent_for": census.stream_absent_for,
    }
    if census.measured:
        fork = fork_of(census.call)
        payload["call"] = {
            "population": fork.population, "cause_groups": fork.cause_groups,
            "coarse_groups": fork.coarse_groups,
            "defects_not_less_than": fork.lower, "defects_not_more_than": fork.upper,
            "merged_by_evidence": fork.merged_by_evidence,
            "largest_component": fork.largest_component,
            "groups": [{"kind": k, "skeleton": s, "failures": c}
                       for (k, s), c in fork.groups],
        }
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Причина провала фазы `call` по junit-записи (заказ G108 п. 1, ADR-675). "
                    "Только ЧИТАЕТ.",
    )
    parser.add_argument("record", nargs="+", type=Path, help="junit-XML прогона")
    parser.add_argument("--stream", type=Path, default=None,
                        help="потоковая запись того же прогона — вторая, МАШИННАЯ "
                             "дверь к фазе провала")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    measured = 0
    payloads = []
    for path in args.record:
        census = census_from_path(path, stream=args.stream)
        payloads.append(as_json(census))
        if not args.json:
            print(format_census(census, shown=args.top))
        if census.measured:
            measured += 1
    if args.json:
        print(json.dumps(payloads, ensure_ascii=False, indent=2))
    # Хотя бы одна запись не прочитана ⇒ 2: «часть измерена» не есть «измерено».
    return 0 if measured == len(args.record) else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
