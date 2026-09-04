#!/usr/bin/env python3
"""Измеритель претензии ``FROZEN-DATE-OK: injected-clock`` — по AST, не подстрокой.

Зачем
------------------------------------------------------------------------------
Храповик литеральных дат (:mod:`spa_core.tests.test_frozen_date_ratchet`) — единственный
сторож класса «фикстура с литеральной датой рядом с понятием свежести». У класса есть
законный выход: пометка ``FROZEN-DATE-OK: injected-clock — <как>`` (решётка перед меткой
в этом файле опущена НАМЕРЕННО: дословная строка выписала бы освобождение самому
измерителю — несчастный случай, уже случившийся с храповиком), означающая приём
№1 правила ``.claude/rules/deployment.md`` — часы приходят ВХОДОМ, обе стороны
закреплены, тест бессмертен.

Замер 04.09 (цикл #477): пометку с этой причиной несут **51** файл набора (карточка
#468 называла ровно это число). Храповик проверяет ровно две вещи: что пометка ЕСТЬ и
что у неё ЕСТЬ причина. **Саму причину не сверял с кодом никто.** Файл, который напишет
``injected-clock`` и при этом возьмёт время у окружающих часов, выходил из класса
молча — ровно та бомба, против которой храповик написан, только с запиской.

Почему AST, а не регулярка
------------------------------------------------------------------------------
Цикл #468 попробовал подстрокой (``\\b(now|as_of|…)\\s*=\\s*[A-Za-z_]``) и назвал 8 файлов
из 51 «неподтверждёнными». Ручная сверка ТРЁХ из восьми показала, что ошибался
ИНСТРУМЕНТ: ``as_of="2026-08-08"`` и ``now_iso=`` — настоящие инъекции со значением-
ЛИТЕРАЛОМ, под шаблон не попавшие. Число 8 было отозвано, а правильным исходом того
замера назван «НЕ ИЗМЕРЕНО с причиной», а не список обвиняемых.

Вопрос, на который отвечает этот модуль, поэтому поставлен иначе: не «есть ли в файле
буквы ``now=``», а **«получает ли какой-нибудь вызов ЯКОРЬ (тот самый литерал) или
производное от него значение в качестве аргумента»**. Это разбор дерева.

Что такое якорь, привязка и инъекция
------------------------------------------------------------------------------
* **Якорь** — литерал времени: строка с ISO-датой (``"2026-08-08"``) либо конструктор
  ``datetime(20xx, …)`` / ``date(20xx, …)`` (в любом написании: ``dt.datetime(…)``).
* **Привязка** — имя, ЗНАЧЕНИЕ которого происходит от якоря: ``NOW = datetime(2030,…)``,
  ``LATER = NOW + timedelta(hours=3)``, ``STAMP = NOW.isoformat()``. Привязка ищется до
  неподвижной точки, поэтому порядок строк в файле роли не играет.
* **Инъекция** — вызов, которому якорь или привязка переданы АРГУМЕНТОМ:
  ``refresh(…, now=NOW)``, ``_write(tmp, (NOW - td).isoformat())``, ``f(as_of="2026-08-08")``.

Намеренно НЕ считаются инъекцией:

* конструирование самого якоря (``datetime(2030, 1, 1, tzinfo=timezone.utc)``) — иначе
  каждый якорь доказывал бы сам себя;
* разбор литерала в дату (``datetime.fromisoformat("2026-08-08")``) — это тоже
  построение якоря, а не передача его коду;
* производная ОТ якоря (``NOW.isoformat()``) — она делает значение, а не отдаёт его.

**Контейнер не является привязкой** — и это главный водораздел. Авария 2026-08-04 имеет
вид ``doc = {"generated_at": "2026-08-02T15:01:33+00:00"}`` с последующим
``age_hours(doc)``: литерал лежит ВНУТРИ словаря, сравнивается со стенными часами, и
никакого часового входа у ``age_hours`` нет. Считай мы «RHS содержит якорь» привязкой —
бомба доказывала бы претензию, которой не имеет, то есть сторож стал бы fail-OPEN.

Граница претензии, названная вслух
------------------------------------------------------------------------------
Модуль проверяет, что претензия ``injected-clock`` **не выдумана**: инъекция в файле
ЕСТЬ. Он НЕ утверждает, что закреплена каждая дата файла — смешанный файл (честная
инъекция рядом с настоящей бомбой) он назовёт подтверждённым. Это ровно та граница, о
которой предупреждает ``test_a_now_kwarg_alone_is_not_accepted_as_proof`` в самом
храповике: инъекция где-то в файле не есть доказательство про весь файл. Разница в том,
что там на этом основании отказались РАСШИРЯТЬ детектор (автоматически освобождать), а
здесь проверяется УЖЕ ВЫПИСАННАЯ человеком пометка — и «претензия не выдумана» строго
сильнее прежнего «претензию не читает никто».

Третий исход
------------------------------------------------------------------------------
Файл может не разобраться (синтаксис, кодировка). Тогда вердикт — :data:`UNMEASURED` с
названной причиной, и это САМОСТОЯТЕЛЬНЫЙ исход, а не число и не тихий пропуск: «не
измерено», выданное за «прошло», — тот же дефект, что ведётся уроком #465.

Только stdlib. LLM здесь запрещён — это измерение, не суждение.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Пометка-освобождение и её причина — та же форма, что читает храповик. Второй
#: реализации разбора пометки здесь нет: обе стороны обязаны видеть ОДНУ строку.
MARKER_RE = re.compile(r"#\s*FROZEN-DATE-OK\s*:\s*(\S.*)", re.IGNORECASE)

#: Претензия, которую этот модуль умеет проверять. Остальные причины освобождения
#: (``detector-samples``, историческая дата и пр.) он не трогает: они обещают другое.
CLAIM = "injected-clock"

#: Литерал даты в строке. Тот же литерал, что видит храповик (`_ISO_DATE_RE`), —
#: намеренно: сторож и измеритель претензии обязаны говорить об одном и том же.
#: Кавычку храповика здесь заменяет строение AST (мы и так смотрим только на
#: `Constant[str]`), а закрывающей границы `\b` тут БЫТЬ НЕ ДОЛЖНО: в
#: `"2026-08-02T15:01:33+00:00"` после дня стоит `T`, границы слова нет, и якорь
#: аварии 2026-08-04 — самый частый вид отметки в наборе — оказался бы невидим.
_ISO_RE = re.compile(r"\b20\d\d-\d\d-\d\d")

#: Имена, чей вызов С ЛИТЕРАЛЬНЫМ ГОДОМ первым аргументом и есть якорь.
_CTOR_NAMES = frozenset({"datetime", "date"})

#: Вызовы, которые СТРОЯТ якорь из литерала. Передача литерала сюда — не инъекция:
#: это второе написание того же якоря.
_ANCHOR_FACTORIES = frozenset({
    "datetime", "date", "fromisoformat", "fromtimestamp", "utcfromtimestamp",
    "strptime", "combine",
})

PROVEN = "proven"          #: инъекция найдена — претензия подтверждена кодом
UNPROVEN = "unproven"      #: файл разобран, инъекции нет — претензия не подтверждена
UNMEASURED = "unmeasured"  #: разобрать не вышло; НЕ «прошло» и НЕ «находка»


@dataclass(frozen=True)
class Injection:
    """Одно место, где якорь (или производное от него) уходит аргументом в вызов."""
    line: int
    callee: str
    keyword: str | None = None

    def __str__(self) -> str:  # pragma: no cover - форма отчёта
        where = f"{self.callee}(…{self.keyword}=…)" if self.keyword else f"{self.callee}(…)"
        return f"строка {self.line}: {where}"


@dataclass(frozen=True)
class Verdict:
    """Вердикт о ФАЙЛЕ: подтверждена ли его пометка ``injected-clock``."""
    path: Path
    verdict: str
    reason: str = ""
    anchors: int = 0
    bound: tuple[str, ...] = ()
    injections: tuple[Injection, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.verdict == PROVEN


def claims_injected_clock(src: str) -> bool:
    """Файл выписал себе освобождение с причиной ``injected-clock``?"""
    return any(CLAIM in m.group(1).lower() for m in MARKER_RE.finditer(src))


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def is_anchor(node: ast.AST) -> bool:
    """Узел — ЛИТЕРАЛ времени: ISO-строка либо ``datetime``/``date`` с годом-литералом."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(_ISO_RE.search(node.value))
    if isinstance(node, ast.Call) and _callee_name(node) in _CTOR_NAMES:
        args = node.args
        return bool(args and isinstance(args[0], ast.Constant)
                    and isinstance(args[0].value, int) and 2000 <= args[0].value <= 2099)
    return False


def is_rooted(node: ast.AST | None, bound: set[str]) -> bool:
    """Значение выражения ПРОИСХОДИТ от литерального якоря.

    Обход намеренно узкий: происхождение тянется через арифметику, обращение к
    атрибуту, метод объекта и f-строку — но НЕ через контейнер. Список и словарь,
    внутри которых лежит литерал, значением-от-якоря не являются: именно так выглядит
    авария 2026-08-04, и считать её происхождением значило бы оправдать бомбу.
    """
    if node is None:
        return False
    if is_anchor(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in bound
    if isinstance(node, ast.BinOp):
        return is_rooted(node.left, bound) or is_rooted(node.right, bound)
    if isinstance(node, ast.UnaryOp):
        return is_rooted(node.operand, bound)
    if isinstance(node, ast.Attribute):
        return is_rooted(node.value, bound)
    if isinstance(node, ast.JoinedStr):
        return any(is_rooted(v.value, bound) for v in node.values
                   if isinstance(v, ast.FormattedValue))
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and is_rooted(func.value, bound):
            return True                       # NOW.isoformat() — производная от якоря
        if _callee_name(node) in _ANCHOR_FACTORIES:
            return any(is_rooted(a, bound) for a in node.args)
        return False
    return False


def _bound_names(tree: ast.AST) -> set[str]:
    """Имена, чьи значения происходят от якоря. До неподвижной точки, а не по порядку.

    ``LATER = NOW + timedelta(1)`` может стоять выше ``NOW = datetime(…)`` (константы
    модуля, фикстуры), и однопроходный обход назвал бы такой файл неподтверждённым по
    причине, не имеющей отношения к делу.
    """
    pairs: list[tuple[ast.AST, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            pairs.extend((t, node.value) for t in node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pairs.append((node.target, node.value))
        elif isinstance(node, ast.NamedExpr):
            pairs.append((node.target, node.value))

    bound: set[str] = set()
    changed = True
    while changed:
        changed = False
        for target, value in pairs:
            # Только простое имя. Распаковка кортежа пометила бы связанными ВСЕ имена
            # слева, а это расширение освобождения на угад — та самая сторона, куда
            # ошибаться нельзя.
            if isinstance(target, ast.Name) and target.id not in bound:
                if is_rooted(value, bound):
                    bound.add(target.id)
                    changed = True
    return bound


def _injections(tree: ast.AST, bound: set[str]) -> list[Injection]:
    """Вызовы, которым якорь или производное от него передано аргументом."""
    out: list[Injection] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or is_anchor(node):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and is_rooted(func.value, bound):
            continue                                  # NOW.replace(...) — не передача
        callee = _callee_name(node)
        if callee in _ANCHOR_FACTORIES:
            continue                                  # разбор литерала — не передача
        for arg in node.args:
            if is_rooted(arg, bound):
                out.append(Injection(line=node.lineno, callee=callee))
        for kw in node.keywords:
            if is_rooted(kw.value, bound):
                out.append(Injection(line=node.lineno, callee=callee, keyword=kw.arg))
    return out


def measure_source(src: str, path: Path | str = "<source>") -> Verdict:
    """Вердикт по ТЕКСТУ файла. Не разобралось ⇒ :data:`UNMEASURED` с причиной."""
    p = Path(path)
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return Verdict(path=p, verdict=UNMEASURED,
                       reason=f"файл не разбирается в AST: {exc}")
    bound = _bound_names(tree)
    anchors = sum(1 for n in ast.walk(tree) if is_anchor(n))
    found = _injections(tree, bound)
    if found:
        return Verdict(path=p, verdict=PROVEN, anchors=anchors,
                       bound=tuple(sorted(bound)), injections=tuple(found))
    if not anchors:
        return Verdict(path=p, verdict=UNPROVEN, anchors=0,
                       reason="в файле нет ни одного литерального якоря времени — "
                              "освобождать нечего, а пометка утверждает обратное")
    return Verdict(path=p, verdict=UNPROVEN, anchors=anchors,
                   bound=tuple(sorted(bound)),
                   reason=f"якорей найдено {anchors}, но ни один из них (и ничего "
                          f"производного от них) не передан аргументом ни в один "
                          f"вызов — часы здесь не ВХОД, и пометка это не описывает")


def measure_file(path: Path | str) -> Verdict:
    """Вердикт по ФАЙЛУ. Нечитаем ⇒ :data:`UNMEASURED`, а не пропуск."""
    p = Path(path)
    try:
        src = p.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — нечитаемость это исход, а не авария
        return Verdict(path=p, verdict=UNMEASURED, reason=f"файл не прочитан: {exc}")
    return measure_source(src, p)


def claiming_files(tests_dir: Path | str) -> list[Path]:
    """Файлы каталога, выписавшие себе освобождение по причине ``injected-clock``."""
    out: list[Path] = []
    for f in sorted(Path(tests_dir).glob("test_*.py")):
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 — нечитаемый файл претензии не заявлял
            continue
        if claims_injected_clock(src):
            out.append(f)
    return out
