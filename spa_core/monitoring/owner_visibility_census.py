"""Перепись §49 `Owner visibility` приказа владельца «Portfolio CIO» (ADR-488).

Критерий владельца дословно:

    **Owner visibility.** Owner видит current/optimal APY, Yield Gap и
    recommendation.

Четыре предмета, и слово в критерии — **видит**. Поэтому вопрос переписи не
«посчитано ли число» и не «есть ли модуль отображения», а **доходит ли число до
поверхности, которую владелец открывает**. Это тот же класс «производитель без
читателя», но нацеленный не на модуль, а на ОТДЕЛЬНОЕ ЧИСЛО: слой отображения
может быть жив, иметь читателя и зелёные тесты — и при этом терять ровно те три
числа, которые владелец назвал.

Замер 2026-09-27, ради которого прибор и написан. Журнал решений
(``allocation_rationale_history*.jsonl``) несёт ВСЕ ЧЕТЫРЕ предмета, каждый
своим полем: ``book_apy_pp`` (4.62636), ``target_apy_pp`` (4.856832),
``gain_pp`` (0.230472), ``verdict`` (``HOLD``). Слой отображения
(``spa_core.paper_trading.cio_brief``) читает ИМЕННО ЭТУ запись, у него есть
настоящий читатель (``spa_core/api/routers/live.py`` → ``/api/live/books/brief``
→ ``landing/src/pages/admin/portfolio-summary.astro``) — и в выдаче он оставляет
``verdict``, а все три ЧИСЛА роняет. До владельца доходит один предмет из
четырёх, причём материал лежал в одном поле от читателя.

## Почему «есть модуль» и «есть читатель» на этот вопрос не отвечают

Рядом уже работают два сторожа, и оба честно отвечают каждый на свой вопрос:

===========================  =========================================  ======================================
вопрос                       кто отвечает                               чего НЕ проверяет
===========================  =========================================  ======================================
состав объяснительной фразы  ``cio_explainability`` (§44)               какие ЧИСЛА в ней есть
есть ли у слоя читатель      ``cio_explainability._brief_consumers``    что именно слой отдаёт читателю
**доходит ли ЧИСЛО**         этот прибор                                всё остальное
===========================  =========================================  ======================================

## Три исхода у каждого предмета, и они не склеиваются

``field``
    выдача несёт предмет СВОИМ полем, и значение равно записанному. Только это
    и есть «владелец видит»: поле можно подписать, отформатировать и сверить.
``prose_only``
    числа как поля нет, но его напечатанная форма найдена ВНУТРИ строки прозы
    (у нас так живёт Yield Gap: он попадает в ``why`` кодом причины
    ``gain_below_band:0.230pp<0.500pp`` — и только когда этот гейт НЕ пройден;
    у книг без материальных ног он исчезает вовсе). Это НЕ зачёт: число,
    существующее лишь как подстрока в объяснении, нельзя ни подписать, ни
    сверить, и оно пропадает при смене причины.
``absent``
    выдача предмета не несёт ни полем, ни прозой.

Четвёртый исход — ``unmeasured`` с названной причиной — обязателен там, где
журнал или выдача не прочитаны (инвариант #17). «Не измерено» никогда не
выдаётся за «доходит».

## ADR-333: проба не проходит подстрокой — и здесь это устроено намеренно

Подстрока в этом приборе НЕ является критерием зачёта: она отделяет ``absent``
от ``prose_only``, то есть работает на УЖЕСТОЧЕНИЕ, а зачёт (``field``) меряется
равенством ЗНАЧЕНИЙ. Ось поверхностей по той же причине не считает читателем
упоминание пути в комментарии: у ``portfolio-summary.astro`` путь эндпоинта
встречается ДВА раза — один раз в комментарии-шапке и один раз настоящим
аргументом ``jget(...)``. Упоминания считаются и НАЗЫВАЮТСЯ отдельно, читателем
не признаются. Сам этот файл из населения оси исключён: прибор, находящий себя,
и есть запрет ADR-333.

## Чего прибор НЕ утверждает

* Он не судит о ПРАВИЛЬНОСТИ чисел — только об их доставке. ``gain_pp`` может
  быть посчитан неверно, и перепись этого не заметит: у неё другой предмет.
* Он не утверждает, что на поверхности владельца нет НИКАКОЙ ставки. Ставка там
  есть — ``annualized_apy_pct``, реализованная доходность книги (1.42 % на день
  замера). Это ДРУГОЕ число, и прибор докладывает такие соседние имена
  отдельной осью: пустое место владелец заметит, а занятое похожим именем —
  нет. Ось докладывает ИМЕНА, а не равенство смысла.
* Он ничего не чинит. Ни RiskPolicy, ни стоп-кран, ни аллокатор, ни
  ``TriggerParams``, ни живой трек, ни ``landing/`` он не трогает — только
  читает.

Только stdlib. LLM запрещён. Атомарная запись артефакта (инвариант #5).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.observation import observed

ARTIFACT_NAME = "owner_visibility_census.json"
SCHEMA = "owner-visibility-census-v2"
CRITERION = ("§49 Owner visibility приказа владельца «Portfolio CIO»: "
             "«Owner видит current/optimal APY, Yield Gap и recommendation»")

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Исходы доставки одного предмета. Порядок — от зачёта к отсутствию.
DELIVERY_FIELD = "field"
DELIVERY_PROSE = "prose_only"
DELIVERY_ABSENT = "absent"
DELIVERY_UNMEASURED = "unmeasured"

#: Четыре предмета критерия — и ключ журнала, которым каждый записан.
#: Ключ здесь НЕ догадка: он взят из настоящей записи ``shadow-hist-v2``.
#: Имена журнала и слова владельца расходятся (`book_apy_pp` против «current
#: APY»), и это само по себе часть находки: прибор обязан называть оба, иначе
#: читатель не поймёт, ЧТО именно не доехало.
SUBJECTS: Tuple[Tuple[str, str, str, str], ...] = (
    ("current_apy", "book_apy_pp", "current APY", "number"),
    ("optimal_apy", "target_apy_pp", "optimal APY", "number"),
    ("yield_gap", "gain_pp", "Yield Gap", "number"),
    ("recommendation", "verdict", "recommendation", "text"),
)

#: Поверхность владельца: эндпоинт, который отдаёт выдачу слоя отображения.
BRIEF_ENDPOINT = "/api/live/books/brief"

#: Каталоги, где живут поверхности владельца. Тесты в население оси не входят —
#: тест читателем владельца не является (урок `cio_explainability`).
SURFACE_DIRS = ("landing/src", "spa_core/telegram", "scripts", "docs")

#: Из них КОДОВЫЕ — те, где вызов эндпоинта вообще возможен. `docs/` в перечень
#: не входит намеренно: документ читателем выдачи быть не может, он способен
#: только упомянуть путь. Различие нужно для третьего исхода: «в дереве нет
#: поверхностей» и «поверхность есть и выдачу не зовёт» — разные ответы, а
#: упоминания в `docs/` есть в ЛЮБОМ дереве и склеивали их (замер #710:
#: прод-дерево без `landing/src/pages/admin/portfolio-summary.astro` давало
#: «читателей 0» рядом с двумя упоминаниями в `docs/` и выглядело находкой).
CODE_SURFACE_DIRS = ("landing/src", "spa_core/telegram", "scripts")

#: Прибор не может найти СЕБЯ, потому что живёт ВНЕ населения оси: ни
#: `spa_core/monitoring/`, ни `spa_core/tests/` в `SURFACE_DIRS` не входят.
#: Здесь стоял перечень-исключение из двух своих путей, и приёмка этого же
#: цикла показала мутацией, что он ВЫРОЖДЕН: снять его нельзя было заметить —
#: обоих файлов в населении нет и так. Мёртвый сторож хуже отсутствующего, он
#: читается как защита. Настоящую защиту меряет
#: `test_the_probe_lives_outside_the_scanned_population`: добавит кто-нибудь
#: `spa_core/monitoring` в `SURFACE_DIRS` — тест покраснеет (ADR-333).

HISTORY_PREFIX = "allocation_rationale_history"
BOOKS = ("conservative", "balanced", "aggressive")


# ───────────────────────────── чтение журнала ────────────────────────────────

def read_latest_records(data_dir: Path) -> Dict[str, Any]:
    """Свежайшая запись журнала по каждой книге.

    Читается ТЕМ ЖЕ загрузчиком, которым читает слой отображения
    (``shadow_trigger_eval.load_history``): своя копия правила «какая строка
    дня главная» была бы вторым ответом на один вопрос (ADR-395).
    """
    try:
        from spa_core.paper_trading.shadow_trigger_eval import load_history
    except Exception as exc:  # noqa: BLE001 — импорт загрузчика есть предпосылка
        return {"measured": False,
                "reason": (f"загрузчик журнала решений не импортируется "
                           f"({type(exc).__name__}: {exc}) — предмет замера не "
                           f"прочитан, и это НЕ «владелец всё видит»")}
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return {"measured": False,
                "reason": f"каталога данных нет: {data_dir}"}
    records: Dict[str, Any] = {}
    unreadable: Dict[str, str] = {}
    for book in BOOKS:
        try:
            rows, _dropped_lines = load_history(data_dir, book_id=book)
        except Exception as exc:  # noqa: BLE001
            unreadable[book] = f"{type(exc).__name__}: {exc}"
            continue
        if not rows:
            unreadable[book] = "журнал решений книги пуст"
            continue
        records[book] = rows[-1]
    if not records:
        return {"measured": False,
                "reason": ("ни по одной книге журнал решений не прочитан: "
                           + "; ".join(f"{b}: {r}"
                                       for b, r in sorted(unreadable.items()))),
                "unreadable": unreadable}
    return {"measured": True, "reason": None, "records": records,
            "unreadable": unreadable}


def read_brief_payload(data_dir: Path) -> Dict[str, Any]:
    """Выдача слоя отображения — ровно та, что уезжает читателю.

    Зовётся НАСТОЯЩИЙ ``build_books_brief``, а не его пересказ: предмет замера —
    что слой ОТДАЁТ, и пересказ отвечал бы на вопрос о пересказе.
    """
    try:
        from spa_core.paper_trading.cio_brief import build_books_brief
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": (f"слой отображения не импортируется "
                           f"({type(exc).__name__}: {exc}) — что доходит до "
                           f"владельца, НЕ измерено")}
    try:
        payload = build_books_brief(Path(data_dir))
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": (f"слой отображения упал на живых данных "
                           f"({type(exc).__name__}: {exc})")}
    if not isinstance(payload, dict):
        return {"measured": False,
                "reason": (f"слой отображения вернул {type(payload).__name__}, "
                           f"а не словарь книг")}
    return {"measured": True, "reason": None, "payload": payload}


# ──────────────────────────── доставка предмета ──────────────────────────────

#: Наименьшая точность, при которой напечатанное число ОПОЗНАВАЕМО как это
#: число. Первая редакция брала и ноль знаков, и приёмка нашла на этом
#: настоящую поломку: ``4.62636`` округлялось до ``"5"``, односимвольная
#: подстрока находилась в ЛЮБОЙ прозе, и предмет, до владельца НЕ доходящий,
#: объявлялся дошедшим «прозой». Ошибка была в сторону оправдания — то есть
#: ровно та, которой прибор существовать не должен.
_MIN_PROSE_DIGITS = 2
_MAX_PROSE_DIGITS = 4


def _renderings(value: float) -> List[str]:
    """Как число могло быть напечатано внутри прозы — с опознаваемой точностью.

    Перечень щедр по ФОРМАТУ (2…4 знака, плюс собственное представление), но не
    по точности: форма короче двух знаков после запятой опознаёт не число, а
    случайную цифру.
    """
    out: List[str] = []
    for digits in range(_MIN_PROSE_DIGITS, _MAX_PROSE_DIGITS + 1):
        out.append(f"{value:.{digits}f}")
    out.append(repr(round(value, 6)))
    return [s for s in dict.fromkeys(out) if s]


def _found_in_prose(form: str, haystack: str) -> bool:
    """Форма найдена как ЧИСЛО, а не как обрывок другого числа.

    ``"0.230"`` внутри ``"10.2304"`` — не то число: цифра вплотную слева или
    справа означает, что напечатано было другое значение.
    """
    start = 0
    while True:
        idx = haystack.find(form, start)
        if idx < 0:
            return False
        before = haystack[idx - 1] if idx > 0 else ""
        after_idx = idx + len(form)
        after = haystack[after_idx] if after_idx < len(haystack) else ""
        if not before.isdigit() and not after.isdigit():
            return True
        start = idx + 1


def _numbers_equal(left: Any, right: Any) -> bool:
    """Равенство ЗНАЧЕНИЙ — зачёт меряется им, а не подстрокой (ADR-333)."""
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return abs(float(left) - float(right)) <= 1e-9


def _strings_of(payload: Any) -> List[str]:
    """Все строки выдачи — материал оси прозы."""
    out: List[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            out.extend(_strings_of(value))
    elif isinstance(payload, list):
        for value in payload:
            out.extend(_strings_of(value))
    elif isinstance(payload, str):
        out.append(payload)
    return out


def _fields_of(payload: Any) -> List[Tuple[str, Any]]:
    """Пары «поле → значение» выдачи, включая вложенные."""
    out: List[Tuple[str, Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            out.append((str(key), value))
            out.extend(_fields_of(value))
    elif isinstance(payload, list):
        for value in payload:
            out.extend(_fields_of(value))
    return out


def score_subject(subject: str, journal_key: str, owner_words: str, kind: str,
                  record: Any, delivered: Any) -> Dict[str, Any]:
    """Один предмет одной книги: записан ли, и доходит ли до владельца."""
    row: Dict[str, Any] = {"subject": subject, "journal_key": journal_key,
                           "owner_words": owner_words}
    expected = observed(record, journal_key,
                        kind=(int, float) if kind == "number" else str)
    if expected is None:
        #: Предмет НЕ записан. Это не «доходит» и не «не доходит» — это
        #: отсутствие предмета замера, и сказать так обязан прибор.
        row.update(recorded=False, delivery=DELIVERY_UNMEASURED,
                   reason=(f"журнал решений не несёт `{journal_key}` — "
                           f"доставка предмета «{owner_words}» НЕ измерена, и "
                           f"это НЕ «владелец его видит»"),
                   expected=None)
        return row
    row.update(recorded=True, expected=expected, reason=None)
    if not isinstance(delivered, dict):
        row.update(delivery=DELIVERY_UNMEASURED,
                   reason=(f"выдача слоя отображения по книге не словарь "
                           f"({type(delivered).__name__}) — доставка предмета "
                           f"НЕ измерена"))
        return row
    if delivered.get("available") is False:
        row.update(delivery=DELIVERY_UNMEASURED,
                   reason=(f"слой отображения объявил книгу недоступной "
                           f"({delivered.get('reason')}) — доставка предмета "
                           f"НЕ измерена"))
        return row

    for name, value in _fields_of(delivered):
        hit = (_numbers_equal(value, expected) if kind == "number"
               else isinstance(value, str) and value == expected)
        if hit:
            row.update(delivery=DELIVERY_FIELD, delivered_as=name)
            return row

    haystack = "\n".join(_strings_of(delivered))
    forms = (_renderings(float(expected)) if kind == "number"
             else [str(expected)])
    for form in forms:
        if form and _found_in_prose(form, haystack):
            row.update(delivery=DELIVERY_PROSE, prose_form=form)
            return row
    row.update(delivery=DELIVERY_ABSENT)
    return row


# ──────────────────────────── ось поверхностей ───────────────────────────────

def _call_argument_pattern(endpoint: str) -> "re.Pattern[str]":
    """Путь эндпоинта как АРГУМЕНТ вызова, а не просто как текст в файле."""
    return re.compile(r"""[A-Za-z_$][\w$.]*\s*\(\s*['"]"""
                      + re.escape(endpoint) + r"""['"]""")


def measure_surfaces(repo_root: Optional[Path],
                     endpoint: str = BRIEF_ENDPOINT) -> Dict[str, Any]:
    """Кто из поверхностей владельца ЗОВЁТ эндпоинт выдачи.

    Читателем признаётся только путь, стоящий АРГУМЕНТОМ вызова. Упоминание в
    комментарии считается и называется отдельно: у настоящей поверхности
    (``portfolio-summary.astro``) путь встречается дважды, и один из двух —
    комментарий-шапка. Признать его читателем значило бы объявить доставку
    налаженной по факту того, что о ней написали.
    """
    if repo_root is None:
        return {"measured": False,
                "reason": "корень дерева не передан — ось поверхностей не измерена"}
    repo_root = Path(repo_root)
    if not repo_root.is_dir():
        return {"measured": False,
                "reason": f"корня дерева нет: {repo_root}"}
    pattern = _call_argument_pattern(endpoint)
    callers: List[str] = []
    mentions: List[str] = []
    code_population: List[str] = []
    unread: Dict[str, str] = {}
    for rel_dir in SURFACE_DIRS:
        base = repo_root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if "/tests/" in rel or rel.startswith("tests/"):
                continue
            if path.suffix.lower() not in (".astro", ".js", ".ts", ".jsx",
                                           ".tsx", ".py", ".html", ".svelte",
                                           ".vue", ".md"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except Exception as exc:  # noqa: BLE001
                unread[rel] = f"{type(exc).__name__}: {exc}"
                continue
            if endpoint not in text:
                continue
            if rel_dir in CODE_SURFACE_DIRS:
                code_population.append(rel)
            if pattern.search(text):
                callers.append(rel)
            else:
                mentions.append(rel)
    if not code_population:
        #: Населения у оси НЕТ ВОВСЕ: ни один файл поверхностных каталогов даже не
        #: упоминает эндпоинт. Это НЕ «страница перестала звать выдачу» — это
        #: дерево без страницы, и два исхода обязаны быть различимы (инв. #17).
        #: Так отвечает прод-дерево: `landing/` туда не синхронизируется
        #: (`.claude/rules/deployment.md`, ADR-152), поэтому мерить ось надо из
        #: дерева, которое поверхность несёт.
        return {"measured": False,
                "reason": (f"ни один файл кодовых каталогов "
                           f"{', '.join(CODE_SURFACE_DIRS)} даже не упоминает "
                           f"{endpoint} — населения у оси нет вовсе: в ЭТОМ дереве "
                           f"поверхностей владельца нет, и это НЕ «страница "
                           f"перестала звать выдачу». Мерить надо из дерева, "
                           f"которое поверхность несёт: `landing/` в прод-дерево не "
                           f"синхронизируется (ADR-152)"),
                "endpoint": endpoint, "callers": [], "mentions_only": mentions,
                "code_population": [], "files_unread": unread}
    return {"measured": True, "reason": None, "endpoint": endpoint,
            "callers": callers, "mentions_only": mentions,
            "code_population": code_population, "files_unread": unread}


def _field_read_pattern(name: str) -> "re.Pattern[str]":
    """Имя поля, прочитанное КАК ПОЛЕ, а не встреченное как текст.

    Та же разница, что у оси поверхностей между вызовом и упоминанием пути:
    ``br.current_apy_pp`` и ``br['current_apy_pp']`` — чтение, а слово внутри
    фразы — нет. Зачёт по простому вхождению подстроки был бы ровно тем
    дефектом, который запрещает ADR-333: выдача, переставшая нести поле, но
    сохранившая его имя в шапке-комментарии, объявлялась бы дошедшей.
    """
    esc = re.escape(name)
    #: Третья форма — деструктуризация/сокращённый ключ (`{current_apy_pp}`,
    #: `{a, current_apy_pp}`, `{current_apy_pp: x}`). Граница у неё УЗКАЯ
    #: намеренно: первая редакция принимала «имя где угодно внутри однострочных
    #: фигурных скобок», и такая мера ошибается в сторону ОПРАВДАНИЯ — фраза
    #: `{ // когда-то читали current_apy_pp }` объявлялась чтением. Ошибаться
    #: эта ось обязана в сторону находки, поэтому имя обязано стоять сразу за
    #: `{` или `,` и сразу перед `}`, `,` или `:`.
    return re.compile(r"""(?:\.\s*""" + esc + r"""\b)"""
                      r"""|(?:\[\s*['"]""" + esc + r"""['"]\s*\])"""
                      r"""|(?:[{,]\s*""" + esc + r"""\s*[},:])""")


def measure_surface_fields(repo_root: Optional[Path], callers: List[str],
                           field_names: List[str]) -> Dict[str, Any]:
    """Читает ли поверхность-читатель то ПОЛЕ, которым предмет доставлен.

    Зачем ось нужна отдельно от `measure_surfaces`. Та отвечает «кто зовёт
    эндпоинт», и ответ «зовёт один» был бы зелёным даже если бы страница
    брала из выдачи одну прозу. Замер 2026-09-28 (цикл #710) ровно такой и
    оказался: после доставки трёх чисел в выдачу `portfolio-summary.astro`
    звал эндпоинт и не читал НИ ОДНОГО из четырёх полей — включая `verdict`,
    который прежний замер числил дошедшим. «Дошло до выдачи» и «дошло до
    владельца» разделяет последний шаг, и до этой оси его не мерил никто.

    Чего ось НЕ утверждает — и это принципиально: она меряет ФОРМУ чтения, а
    не достижимость кода. Выражение `br.current_apy_pp`, стоящее в
    комментарии, она признает чтением, а поле, собранное из куска имени, — не
    признает. Ошибаться такая мера обязана в сторону находки, а не оправдания:
    ложная тревога стоит перечитывания файла, ложное «дошло» — трёх месяцев.
    """
    if repo_root is None:
        return {"measured": False,
                "reason": "корень дерева не передан — ось чтения полей не измерена"}
    if not callers:
        return {"measured": False,
                "reason": ("поверхностей-читателей не найдено — читать поля "
                           "выдачи некому, и это НЕ «поля дошли»")}
    if not field_names:
        return {"measured": False,
                "reason": ("ни один предмет не доставлен полем — проверять "
                           "чтение поля нечего")}
    repo_root = Path(repo_root)
    patterns = {name: _field_read_pattern(name) for name in sorted(set(field_names))}
    read_by: Dict[str, List[str]] = {name: [] for name in patterns}
    mentions: Dict[str, List[str]] = {name: [] for name in patterns}
    unread: Dict[str, str] = {}
    for rel in callers:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception as exc:  # noqa: BLE001
            unread[rel] = f"{type(exc).__name__}: {exc}"
            continue
        for name, pattern in patterns.items():
            if pattern.search(text):
                read_by[name].append(rel)
            elif name in text:
                mentions[name].append(rel)
    if unread and not any(read_by.values()):
        return {"measured": False,
                "reason": ("ни одна поверхность-читатель не прочитана: "
                           + "; ".join(f"{r}: {w}" for r, w in sorted(unread.items()))),
                "files_unread": unread}
    return {"measured": True, "reason": None,
            "read_by": {k: v for k, v in read_by.items() if v},
            "not_read": sorted(k for k, v in read_by.items() if not v),
            "mentions_only": {k: v for k, v in mentions.items() if v and not read_by[k]},
            "files_unread": unread}


#: Имя поля со ставкой, которое поверхность владельца печатает. Ось докладывает
#: ИМЕНА: занятое похожим именем место владелец не заметит, а пустое — заметит.
_APY_FIELD = re.compile(r"[\w$]*(?:apy|APY)[\w$]*")


def measure_neighbour_rates(repo_root: Optional[Path],
                            surfaces: List[str]) -> Dict[str, Any]:
    """Какие ставки поверхность владельца печатает ВМЕСТО названных им."""
    if repo_root is None:
        return {"measured": False,
                "reason": "корень дерева не передан — ось соседних ставок не измерена"}
    if not surfaces:
        return {"measured": False,
                "reason": ("поверхностей-читателей не найдено — печатать имена "
                           "ставок не у кого")}
    repo_root = Path(repo_root)
    found: Dict[str, List[str]] = {}
    unread: Dict[str, str] = {}
    for rel in surfaces:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception as exc:  # noqa: BLE001
            unread[rel] = f"{type(exc).__name__}: {exc}"
            continue
        names = sorted({m.group(0) for m in _APY_FIELD.finditer(text)
                        if m.group(0).lower() != "apy"})
        if names:
            found[rel] = names
    return {"measured": True, "reason": None, "by_surface": found,
            "files_unread": unread}


# ─────────────────────────────── перепись ────────────────────────────────────

def run_census(data_dir: Path, now: Optional[datetime] = None,
               repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Доходят ли до владельца четыре предмета, названные им в §49."""
    now = now or datetime.now(timezone.utc)
    journal = read_latest_records(Path(data_dir))
    if not journal["measured"]:
        return _unmeasured(journal["reason"], now)
    brief = read_brief_payload(Path(data_dir))
    if not brief["measured"]:
        return _unmeasured(brief["reason"], now,
                           books_in_journal=sorted(journal["records"]))

    payload = brief["payload"]
    books: Dict[str, Any] = {}
    for book, record in sorted(journal["records"].items()):
        delivered = payload.get(book)
        rows = [score_subject(subject, key, words, kind, record, delivered)
                for subject, key, words, kind in SUBJECTS]
        books[book] = {
            "cycle_date": record.get("cycle_date"),
            "generated_at": record.get("generated_at"),
            "subjects": rows,
            "delivered_as_field": [r["subject"] for r in rows
                                   if r["delivery"] == DELIVERY_FIELD],
            "prose_only": [r["subject"] for r in rows
                           if r["delivery"] == DELIVERY_PROSE],
            "absent": [r["subject"] for r in rows
                       if r["delivery"] == DELIVERY_ABSENT],
            "unmeasured": [r["subject"] for r in rows
                           if r["delivery"] == DELIVERY_UNMEASURED],
        }

    surfaces = measure_surfaces(repo_root)
    callers = list(surfaces.get("callers") or []) if surfaces.get("measured") else []
    neighbours = measure_neighbour_rates(repo_root, callers)
    #: Имена полей, которыми предметы РЕАЛЬНО доставлены — вход третьей оси.
    #: Перечень берётся из замера, а не из таблицы SUBJECTS: спрашивать надо про
    #: то поле, которое выдача несёт сегодня, иначе ось мерила бы ожидание.
    delivered_field_names = sorted({
        str(row["delivered_as"]) for book in books.values()
        for row in book["subjects"]
        if row["delivery"] == DELIVERY_FIELD and row.get("delivered_as")})
    surface_fields = measure_surface_fields(repo_root, callers,
                                           delivered_field_names)

    totals = {kind: 0 for kind in (DELIVERY_FIELD, DELIVERY_PROSE,
                                   DELIVERY_ABSENT, DELIVERY_UNMEASURED)}
    for book in books.values():
        for row in book["subjects"]:
            totals[row["delivery"]] += 1

    #: Вердикт судит НАСТОЯЩЕЕ — свежайшую запись каждой книги. История тут не
    #: при чём: сторож, красный навсегда, учит себя игнорировать. Красным этот
    #: гасится доставкой полей, а не изменением порога.
    recorded_but_lost = sum(
        1 for book in books.values() for row in book["subjects"]
        if row.get("recorded") and row["delivery"] in (DELIVERY_ABSENT,
                                                       DELIVERY_PROSE))
    #: Предмет, дошедший до ВЫДАЧИ полем, но не прочитанный ни одной
    #: поверхностью владельца. До оси #710 этот исход был неотличим от «дошло»:
    #: выдачу читал реальный читатель, а конкретное поле он не брал.
    not_rendered = sorted(surface_fields.get("not_read") or []) \
        if surface_fields.get("measured") else []
    delivered_but_not_rendered = len(not_rendered)
    if not surfaces.get("measured") or not surface_fields.get("measured"):
        status = STATUS_UNMEASURED
    elif recorded_but_lost or delivered_but_not_rendered:
        status = STATUS_CRITICAL
    elif totals[DELIVERY_UNMEASURED]:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "schema": SCHEMA, "measured": True, "status": status,
        "criterion": CRITERION, "generated_at": now.isoformat(),
        "books": books, "books_unreadable": journal.get("unreadable") or {},
        "subjects_total": sum(len(b["subjects"]) for b in books.values()),
        "delivered_as_field": totals[DELIVERY_FIELD],
        "prose_only": totals[DELIVERY_PROSE],
        "absent": totals[DELIVERY_ABSENT],
        "subjects_unmeasured": totals[DELIVERY_UNMEASURED],
        "recorded_but_not_delivered": recorded_but_lost,
        "delivered_but_not_rendered": delivered_but_not_rendered,
        "fields_not_rendered": not_rendered,
        "surfaces": surfaces, "surface_fields": surface_fields,
        "neighbour_rates": neighbours,
        "reason": None,
    }


def _unmeasured(reason: str, now: datetime, **extra: Any) -> Dict[str, Any]:
    """Третий исход: названная причина, а не ноль и не «чисто» (инв. #17)."""
    doc: Dict[str, Any] = {
        "schema": SCHEMA, "measured": False, "status": STATUS_UNMEASURED,
        "criterion": CRITERION, "generated_at": now.isoformat(),
        "reason": reason, "books": {}, "subjects_total": 0,
        "delivered_as_field": 0, "prose_only": 0, "absent": 0,
        "subjects_unmeasured": 0, "recorded_but_not_delivered": 0,
        "delivered_but_not_rendered": 0, "fields_not_rendered": [],
        "surfaces": {"measured": False,
                     "reason": "предмет замера не прочитан — ось не мерилась"},
        "surface_fields": {"measured": False,
                           "reason": "предмет замера не прочитан — ось не мерилась"},
        "neighbour_rates": {"measured": False,
                            "reason": "предмет замера не прочитан"},
    }
    doc.update(extra)
    return doc


# ──────────────────────────────── отчёт ──────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    head = "видимость для владельца (§49 Owner visibility)"
    if not report.get("measured"):
        return f"{head}: НЕ ИЗМЕРЕНО — {report.get('reason')}"
    return (f"{head}: {report['status']} · предметов "
            f"{report['subjects_total']} · ДОХОДИТ полем "
            f"{report['delivered_as_field']} · только прозой "
            f"{report['prose_only']} · НЕ ДОХОДИТ {report['absent']} · "
            f"НЕ ИЗМЕРЕНО {report['subjects_unmeasured']} · записано, но не "
            f"доставлено {report['recorded_but_not_delivered']} · доставлено "
            f"полем, но НЕ ЧИТАЕТСЯ поверхностью "
            f"{report.get('delivered_but_not_rendered', 0)}")


def format_report(report: Dict[str, Any], limit: int = 12) -> List[str]:
    """Отчёт для шага 0-офис."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        lines.append(f"[ПРЕДМЕТ] {report.get('criterion')}")
        return lines
    books = observed(report, "books", kind=dict) or {}
    shown = 0
    for book, data in sorted(books.items()):
        for row in data.get("subjects", []):
            if row["delivery"] == DELIVERY_FIELD:
                continue
            if shown >= limit:
                break
            mark = {DELIVERY_ABSENT: "НЕ ДОХОДИТ",
                    DELIVERY_PROSE: "ТОЛЬКО ПРОЗОЙ",
                    DELIVERY_UNMEASURED: "НЕ ИЗМЕРЕНО"}[row["delivery"]]
            detail = ""
            if row["delivery"] == DELIVERY_PROSE:
                detail = (f" — найдено подстрокой «{row.get('prose_form')}» "
                          f"внутри прозы: подписать и сверить такое число "
                          f"нельзя, при смене причины оно исчезнет")
            elif row["delivery"] == DELIVERY_UNMEASURED:
                detail = f" — {row.get('reason')}"
            lines.append(f"[{mark}] {book} · «{row['owner_words']}» "
                         f"(журнал: `{row['journal_key']}` = "
                         f"{row.get('expected')}){detail}")
            shown += 1
    for book, data in sorted(books.items()):
        if data["delivered_as_field"]:
            lines.append(f"[ДОХОДИТ] {book}: "
                         + ", ".join(sorted(data["delivered_as_field"])))
    surfaces = observed(report, "surfaces", kind=dict) or {}
    if not surfaces.get("measured"):
        lines.append(f"[ПОВЕРХНОСТИ] НЕ ИЗМЕРЕНО — {surfaces.get('reason')}")
    else:
        callers = surfaces.get("callers") or []
        mentions = surfaces.get("mentions_only") or []
        lines.append(f"[ПОВЕРХНОСТИ] эндпоинт {surfaces.get('endpoint')}: "
                     f"зовут {len(callers)} · упоминают, не зовя "
                     f"{len(mentions)}"
                     + (f" — {', '.join(callers)}" if callers else ""))
        if mentions:
            lines.append("   упоминание пути НЕ читатель: "
                         + ", ".join(mentions))
    sfields = observed(report, "surface_fields", kind=dict) or {}
    if not sfields.get("measured"):
        lines.append(f"[ЧТЕНИЕ ПОЛЯ] НЕ ИЗМЕРЕНО — {sfields.get('reason')}")
    else:
        for name, rels in sorted((sfields.get("read_by") or {}).items()):
            lines.append(f"[ЧТЕНИЕ ПОЛЯ] `{name}` читают: " + ", ".join(rels))
        for name in sfields.get("not_read") or []:
            seen = (sfields.get("mentions_only") or {}).get(name) or []
            lines.append(
                f"[НЕ ЧИТАЕТСЯ] поле `{name}` есть в выдаче, но ни одна "
                f"поверхность владельца его не берёт"
                + (f" (имя встречается, но не как чтение: {', '.join(seen)})"
                   if seen else "")
                + " — до выдачи предмет дошёл, до владельца нет")
    neighbours = observed(report, "neighbour_rates", kind=dict) or {}
    if neighbours.get("measured"):
        for rel, names in sorted((neighbours.get("by_surface") or {}).items()):
            lines.append(f"[СОСЕДНЯЯ СТАВКА] {rel} печатает "
                         + ", ".join(names)
                         + " — это ДРУГИЕ числа; место, занятое похожим именем, "
                           "владелец не заметит пустым")
    lines.append("НЕ ДОКЛАДЫВАЕТ: верность самих чисел (предмет — доставка, не "
                 "счёт); прочитал ли владелец страницу; равенство СМЫСЛА "
                 "соседних ставок — ось называет только их ИМЕНА; достижимость "
                 "кода, читающего поле — ось чтения меряет ФОРМУ чтения")
    return lines


# ──────────────────────────── артефакт и ступень ─────────────────────────────

def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь): обратный `atomic_save` отвергает
    # fail-CLOSED, артефакт не появляется вовсе, а ступень докладывает
    # `measured=True` — отказ записи становится неотличим от успеха у всех,
    # кто смотрит на вывод, а не на диск (настоящая поломка #701, ADR-480).
    atomic_save(report, str(path))
    return path


def run(root: str = ".", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ступень моста находок (`findings_bridge`): померить и оставить артефакт.

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с
    названной причиной обязано доехать до читателя, иначе шаг 0-офис увидит
    отсутствие файла и не сможет отличить его от «ступень не запускалась».
    """
    data_dir = Path(root) / "data"
    report = run_census(data_dir, now=now, repo_root=Path(root))
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None,
                    help="каталог данных (по умолчанию — data/ репозитория)")
    ap.add_argument("--repo-root", default=None,
                    help="корень дерева для оси поверхностей (по умолчанию — свой)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт целиком")
    ap.add_argument("--save", action="store_true",
                    help=f"записать {ARTIFACT_NAME} в каталог данных")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else \
        Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else (repo_root / "data")
    report = run_census(data_dir, repo_root=repo_root)
    if args.save:
        save_artifact(report, data_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    if not report.get("measured"):
        return 2
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
