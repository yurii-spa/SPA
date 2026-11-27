#!/usr/bin/env python3
"""Перепись класса «исключение объявлено СЛОВОМ, а не замером» (заказ G1092 п. 5).

ADR-1117 закрыл ОДНУ базу: 61 путь переходника снимка получил причину, которую
ПЕРЕМЕРЯЕТ прибор, а не повторяет проза. Заказ назвал остаток честно: «население
класса за пределами этого сторожа НЕ ИЗМЕРЕНО. Закрыта ОДНА база.» Нулём это не
считается, и мерить его генератором ПО СЛОВАМ запрещено (урок ADR-1074/1114: слово
мерой не является) — спрашивать надо у КАЖДОЙ базы, объявлена ли ось её причины в
приборе.

Вопрос прибора — ДВУХОСНЫЙ, и оси отвечают на разное:

* **ось A — несёт ли СТРОКА причину.** Чисто структурная, из байтов самой базы:
  строка-строка (`"test_foo.py"`) причины не несёт — её «причина» это файловый
  `_comment`, один на все 275 строк. Строка-объект и отображение `путь → причина`
  причину несут.
* **ось B — ПЕРЕМЕРЯЕТСЯ ли причина, и спрашивается это у ДЕРЕВА.** Первая
  редакция прибора спрашивала СВОЙ ЖЕ перечень объявленных адресов, и перечень
  был пуст — поэтому «мерки не объявлено» выходило у ВСЕХ 22 носителей с
  причиной. Это не замер, а тавтология: она отвечает «записал ли я это у себя»,
  а не «есть ли мерка в дереве». Проверка на известном члене опровергла её сразу
  — `ci_only_red_class_baseline.json` свой построчный контракт ПЕРЕМЕРЯЕТ
  (`required_member_fields` и `determinism_axis` сверяются со сторожем), и первая
  редакция обвинила его ложно. Теперь ось спрашивает дерево: читает ли
  КАКОЙ-НИБУДЬ сторож хоть один ПРИЧИННЫЙ КЛЮЧ строк этой базы (разбором, по
  строковым литералам, а не подстрокой — упоминание в докстринге зовом не
  является, дословный урок ADR-1116).

**Ключ НАБОРА причинным не является.** `known`, `plateaus`, `members` — это то,
ЧЕМ добираются до строк, а не то, ЧЕМ строка себя объясняет. Считать их причиной
значило бы зачесть «сторож открыл базу» за «сторож перемерил причину».

**У причины-ЗНАЧЕНИЯ имени нет, и это третий исход.** В форме
`{путь: "причина строкой"}` причина не имеет ключа вовсе, поэтому вопрос «читает
ли её сторож» строковыми литералами НЕ РАЗРЕШАЕТСЯ. Такой носитель уходит в
`unmeasured` с названной причиной, а не в предмет: обвинить его значило бы выдать
границу меры за находку.

**Предмет класса** — база, чья строка причину НЕСЁТ, а перемерять её не берётся
никто: это и есть «слово вместо замера». База без причины у строки — РОД ДРУГОЙ
(причина файловая, одна на всех), и считать её предметом значило бы подменить
класс; она называется отдельным ведром.

**Чего прибор НЕ меряет, и нулём это не считается.** Население носителя-PYTHON
(объявление живёт модульным словарём, как `NOT_IN_VIEW` у ADR-1117) перечислением
НЕ добывается: «модульный словарь, который читает сторож как список освобождённых»
от любого другого словаря структурно не отличается. Поэтому Python-носители
объявлены ПОИМЁННО в `PYTHON_CARRIERS`, каждый ПРОВЕРЯЕТСЯ разбором, а полнота
этого перечня — названный долг, а не ноль. Форма `*baseline*.json` известного
положительного члена НЕ СОДЕРЖИТ (он Python), и форма, теряющая известного члена,
класс не сужает, а ПОДМЕНЯЕТ — отсюда два носителя, а не один.

Коды возврата: 0 — предмет пуст · 1 — предмет назван (находки) · 2 — НЕ ИЗМЕРЕНО
(поверхность не прочитана, объявленный адрес не разобран, контроль известных
членов не сошёлся).
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

SCHEMA = "declared-exclusion-remeasure/1"

#: Служебные ключи базы: они несут ЗАМЕР и ПРАВИЛО, а не строки исключений.
#: Перечень взят ЗАМЕРОМ по 49 базам дерева, а не из головы: ключ попадает сюда
#: только если он скаляр-описание во ВСЕХ базах, где встречается.
META_KEYS = frozenset({
    "schema", "schema_version", "snapshot", "count", "note", "notes", "rule",
    "adr", "order", "instrument", "tree", "sha", "base_sha", "scope", "cycle",
    "measured", "measured_at", "measured_by", "measured_in", "measured_on",
    "measured_on_sha", "measured_on_commit", "upper_bound", "tolerance_usd",
})

#: Вердикты оси C (дорога ЗНАЧЕНИЯ) — объявлены здесь, потому что их называет
#: контроль известных членов ВЫШЕ самой оси.
#: Предел различаемых положений на одно имя. Перебор ⇒ НЕ ИЗМЕРЕНО с причиной,
#: а не усечённый ответ: усечение молча превратило бы «не досчитали» в «не читает».
_POSITION_CAP = 256

ROAD_VALUE = "value"
ROAD_KEYS = "keys"
ROAD_NONE = "no_reader"
ROAD_UNMEASURED = "unmeasured"

REASON_ABSENT = "ПРИЧИНЫ У СТРОКИ НЕТ"
REASON_PRESENT = "причина у строки есть"
MEASURE_ABSENT = "МЕРКИ НЕТ"

#: Базы, которые объявлением исключений НЕ являются: это СОСТОЯНИЕ и КОНФИГ,
#: попавшие в поверхность по ИМЕНИ файла. Исключение объявляется здесь с причиной
#: и ПРОВЕРЯЕТСЯ (`_carrier_is_not_an_exclusion_base`): база обязана не иметь ни
#: одного читателя-сторожа. Слово «не нужно» причиной не является.
NOT_AN_EXCLUSION_BASE: dict[str, str] = {
    "data/strategies/s0_baseline.json":
        "снимок СОСТОЯНИЯ бумажной стратегии (cash/positions/equity_curve), никого "
        "не освобождает от сторожа",
    "spa_core/strategies/strategy_configs_baseline.json":
        "КОНФИГ стратегий (schema_version + strategies), никого не освобождает",
}

#: Носитель-PYTHON: объявление исключений живёт модульным именем, а не JSON-файлом.
#: Здесь лежит ИЗВЕСТНЫЙ ПОЛОЖИТЕЛЬНЫЙ член класса (ADR-1117) — он и есть контроль
#: оси B в сторону «перемеряется». Полнота перечня — НАЗВАННЫЙ ДОЛГ (см. докстринг).
PYTHON_CARRIERS: dict[str, tuple[str, str]] = {
    "spa_core/tests/test_site_snapshot_view_shape.py::NOT_IN_VIEW": (
        "spa_core/tests/test_site_snapshot_view_shape.py",
        "ADR-1117: у каждого исключения причина, и причина ПЕРЕМЕРЯЕТСЯ прибором "
        "`scripts/snapshot_view_field_demand.py` — поле, которое снова читают, "
        "краснит сторожа",
    ),
}

#: Где живут сторожа, которых спрашивает ось B. Каталоги — ВХОД меры, а не
#: умолчание: охват печатается, и он есть ГРАНИЦА, а не замер пустоты остальных.
#:
#: **ПОМОЩНИКИ (`_*.py`) входят в охват, и это не удобство, а починка.** Первая
#: редакция спрашивала только `test_*.py` и выдала ОДНУ находку —
#: `absent_observation_baseline.json`, «читателя-сторожа НЕТ ни одного». Находка
#: оказалась ЛОЖНОЙ: храповик инв. #17 базу читает, но ЧЕРЕЗ ПОМОЩНИКА
#: `spa_core/tests/_absent_observation.py` (`ao.load_baseline()`), а имени базы в
#: самом тесте не стоит. Это ровно та граница ОДНОГО ХОПА, о которую спотыкается
#: сторож притязания `injected-clock`, и форма, теряющая известного читателя,
#: класс не сужает, а ПОДМЕНЯЕТ (урок ADR-1074).
GUARD_GLOBS = ("spa_core/tests/test_*.py", "scripts/tests/test_*.py",
               "spa_core/tests/_*.py", "scripts/tests/_*.py")

#: Контроль формы ДО чисел: известные члены класса и ожидаемое ведро каждого.
#: Не сошёлся ⇒ код 2 и НИ ОДНОГО числа (урок ADR-1110: контроль ДО чисел).
#: Направления ОБА: причина ПЕРЕМЕРЯЕТСЯ (два носителя, json и python — форма,
#: теряющая любого, ПОДМЕНЯЕТ класс) и причины у строки НЕТ ВОВСЕ. Ведро каждого
#: члена проверено ЧТЕНИЕМ кода, а не выведено из прозы.
KNOWN_MEMBERS: dict[str, str] = {
    # Python-носитель, ADR-1117: причина перемеряется прибором спроса.
    "spa_core/tests/test_site_snapshot_view_shape.py::NOT_IN_VIEW": "remeasured",
    # JSON-носитель: `test_ci_only_red_class_ratchet.py` сверяет построчный
    # контракт объявления со сторожем — прочитано, а не предположено.
    "spa_core/tests/ci_only_red_class_baseline.json": "remeasured",
    # Голые строки: причина одна файловая на все 275/45/458 строк.
    "spa_core/tests/frozen_date_baseline.json": "reason_absent",
    "spa_core/tests/design_status_baseline.json": "reason_absent",
    "scripts/inbox_acceptance_baseline.json": "reason_absent",
    # Читается ЧЕРЕЗ ПОМОЩНИКА: имени базы в самом храповике инв. #17 нет вовсе.
    # Член держит охват помощников — сузь `GUARD_GLOBS` до `test_*.py`, и этот
    # член вернётся ложной находкой (так и случилось в первой редакции).
    "spa_core/tests/absent_observation_baseline.json": "remeasured",
    # ── ось C (ADR-1121), ведро читано В КОДЕ, а не выведено из прозы ──
    # `revealed.items()` в `test_unwired_scripts_ratchet.py`, причина
    # используется (`reason.strip()`, `assertIn(".py", reason)`).
    "spa_core/tests/unwired_scripts_baseline.json": "value_read",
    # Прибор `scripts/python_git_ref_provenance.py` берёт причину
    # `for _key, _why in (_b.get(_sect) or {}).items()`. Член держит ДВЕ двери
    # сразу: опознание по СХЕМЕ (имени файла в приборе нет вовсе) и раскрытие
    # ВЫЧИСЛЕННОГО ключа по литеральному кортежу.
    "scripts/python_git_ref_provenance_baseline.json": "value_read",
    # ДВЕРЬ 4 (возврат функции файла), и член держит её В ОБЕ стороны.
    # Прочитано В КОДЕ, а не выведено из прозы: `lint_forbidden_imports.py`
    # опознаёт носителя литералом `BASELINE_REL`, набор выбирает ВНУТРИ
    # помощника (`load_baseline` → `return doc.get("known", {})`), а причину
    # читает в `main()` — `print(f"ИЗВЕСТНОЕ  {f} — {baseline[f.key]}")`
    # (строка 269). Сними дверь 4 — и носитель станет `subject`, то есть
    # вернётся ЛОЖНАЯ находка первой редакции оси C (замер #1266 объявил его
    # единственным предметом класса; #1267 опроверг чтением кода).
    "scripts/forbidden_import_baseline.json": "value_read",
    # РОД ДРУГОЙ: безымянное значение — ЧИСЛО (`operand` = {carries: 3}).
    # Обвинить его значило бы выдать счётчик за «слово вместо замера».
    "spa_core/tests/caller_record_baseline.json": "nameless_not_a_reason",
    # ОТВЕТ О ДРУГОМ НАБОРЕ: причину-строку несёт блок замера `измерено_на`, а
    # `.items()` читают у счётчика `файлы` (`scripts/adapter_status_writer_census.py`).
    # Член держит ограничение дороги значения НЕСУЩИМ набором: снимешь его —
    # носитель молча станет «значение читают», то есть ответом о другом наборе.
    "scripts/adapter_status_caller_supplied_baseline.json": "value_read_elsewhere",
}

#: Контроль САМОЙ оси C, в ОБЕ стороны и отдельно от ведра: ведро решается
#: РОДОМ значения, а дорога — чтением дерева, и совпадение одного не
#: доказывает другого. `office_undeclared_read_baseline.json` держит здесь
#: случай «род другой, а дорога значения ЕСТЬ» (`BASELINE["undeclared_top"].items()`):
#: без него ось C зеленела бы, ни разу не ответив «читает» на носителе не-предмете.
KNOWN_VALUE_ROAD: dict[str, str] = {
    "spa_core/tests/unwired_scripts_baseline.json": ROAD_VALUE,
    "scripts/python_git_ref_provenance_baseline.json": ROAD_VALUE,
    "spa_core/tests/office_undeclared_read_baseline.json": ROAD_VALUE,
    # Дверь 4: причина читается ЗА ВОЗВРАТОМ функции того же файла.
    "scripts/forbidden_import_baseline.json": ROAD_VALUE,
}

#: ⚠️ Сторону `keys` (предмет класса) В ДЕРЕВЕ сегодня не держит НИ ОДИН
#: носитель — после двери 4 предмет ПУСТ, и это замер, а не удобство. Поэтому
#: контроль этой стороны живёт СЦЕНОЙ сторожа
#: (`test_declared_exclusion_remeasure_census.py`, одноразовый файл-читатель,
#: берущий из набора только `in`), а не строкой этой таблицы: вписать сюда
#: носителя, которого мера в это ведро не кладёт, значило бы объявить
#: контролем собственное ожидание. Появится настоящий предмет — его место здесь.


class Verdict:
    """Вердикт об ОДНОМ носителе объявленных исключений."""

    __slots__ = ("key", "carrier", "bucket", "rows", "detail")

    def __init__(self, key: str, carrier: str, bucket: str, rows: int,
                 detail: str) -> None:
        self.key = key
        self.carrier = carrier
        self.bucket = bucket
        self.rows = rows
        self.detail = detail

    def as_dict(self) -> dict:
        return {"key": self.key, "carrier": self.carrier, "bucket": self.bucket,
                "rows": self.rows, "detail": self.detail}


# ───────────────────────────── ось A: несёт ли строка причину ─────────────────

def row_sets(doc: object) -> dict[str, tuple[str, int]]:
    """Наборы строк базы: ключ → (форма, число строк).

    Строки бывают СПИСКОМ и ОТОБРАЖЕНИЕМ, и это существенно: отображение
    `путь → причина` причину НЕСЁТ. Первая редакция прибора брала только список
    и отправила ДЕСЯТЬ носителей в ведро «строк нет» — ошибка в сторону «чисто»,
    то есть в опасную.
    """
    out: dict[str, tuple[str, int]] = {}
    if not isinstance(doc, dict):
        return out
    for key, value in doc.items():
        if key.startswith("_") or key in META_KEYS:
            continue
        if isinstance(value, list) and value:
            out[key] = ("list", len(value))
        elif isinstance(value, dict) and value:
            out[key] = ("mapping", len(value))
    return out


def reason_axis(doc: object) -> tuple[str, int, str]:
    """Ось A: `reason_absent` · `reason_present` · `mixed` · `no_rows`."""
    sets = row_sets(doc)
    if not sets:
        return "no_rows", 0, "ни одного набора строк под неслужебным ключом"
    kinds: set[str] = set()
    total = 0
    assert isinstance(doc, dict)
    for key, (form, size) in sets.items():
        total += size
        if form == "mapping":
            kinds.add("present")
            continue
        for item in doc[key]:
            kinds.add("present" if isinstance(item, dict) else "absent")
    if kinds == {"absent"}:
        return "reason_absent", total, f"{total} строк(и) — голые значения"
    if kinds == {"present"}:
        return "reason_present", total, f"{total} строк(и) несут причину"
    return "mixed", total, f"{total} строк(и): часть с причиной, часть без"


# ───────────────────────────── ось B: перемеряется ли причина ────────────────

def reason_keys(doc: object) -> tuple[set[str], int]:
    """Причинные ключи строк + число наборов, где причина — безымянное ЗНАЧЕНИЕ.

    Причинным является ПОЛЕ СТРОКИ, а не ключ набора: `known` / `plateaus` —
    это то, ЧЕМ добираются до строк. Зачесть их значило бы принять «сторож
    открыл базу» за «сторож перемерил причину».
    """
    keys: set[str] = set()
    nameless = 0
    if not isinstance(doc, dict):
        return keys, nameless
    for key, value in doc.items():
        if key.startswith("_") or key in META_KEYS:
            continue
        if isinstance(value, dict) and value:
            inner = [v for v in value.values() if isinstance(v, dict)]
            if inner:
                for item in inner:
                    keys.update(k for k in item if isinstance(k, str))
            else:
                nameless += 1          # {путь: "причина строкой"} — имени нет
        elif isinstance(value, list) and value:
            objs = [v for v in value if isinstance(v, dict)]
            for item in objs:
                keys.update(k for k in item if isinstance(k, str))
    return keys, nameless


def string_literals(path: pathlib.Path) -> set[str] | None:
    """Строковые литералы файла по AST. Не разобрался ⇒ None (третий исход)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def guard_literals(root: pathlib.Path) -> tuple[dict[str, set[str]], list[str]]:
    """Литералы КАЖДОГО сторожа охвата + поимённый перечень неразобранных."""
    table: dict[str, set[str]] = {}
    unparsed: list[str] = []
    for pattern in GUARD_GLOBS:
        for path in sorted(root.glob(pattern)):
            rel = str(path.relative_to(root))
            lits = string_literals(path)
            if lits is None:
                unparsed.append(rel)
            else:
                table[rel] = lits
    return table, unparsed


def remeasure_axis(base_rel: str, keys: set[str],
                   guards: dict[str, set[str]]) -> tuple[list[tuple[str, int]], int]:
    """Кто из сторожей ЧИТАЕТ базу, и сколько её причинных ключей он называет."""
    needle = pathlib.PurePath(base_rel).name
    readers: list[tuple[str, int]] = []
    for rel, lits in guards.items():
        if not any(needle in s for s in lits):
            continue
        readers.append((rel, len(keys & lits)))
    return readers, sum(1 for _, hit in readers if hit)


def measure_names_the_base(root: pathlib.Path, measure_rel: str,
                           needle: str) -> tuple[bool, str]:
    """Называет ли мерка базу — РАЗБОРОМ, а не подстрокой.

    Подстрока зачла бы за зов упоминание в докстринге (дословный урок ADR-1116).
    Для JSON-носителя базу называет СТРОКОВЫЙ литерал её имени; для
    Python-носителя — ИМЯ или атрибут.
    """
    path = root / measure_rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return False, f"адрес мерки не разобран: {type(exc).__name__}: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == needle:
            return True, "база названа именем"
        if isinstance(node, ast.Attribute) and node.attr == needle:
            return True, "база названа атрибутом"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if needle in node.value:
                return True, "база названа строковым литералом"
    return False, f"адрес есть, а `{needle}` в нём не названо разбором"


def python_carrier_declares_rows(root: pathlib.Path, rel: str,
                                 name: str) -> tuple[int, str]:
    """Сколько строк объявляет Python-носитель. Не разобрано ⇒ (-1, причина)."""
    path = root / rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return -1, f"носитель не разобран: {type(exc).__name__}: {exc}"
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            return len(value.keys), "объявлен словарём"
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return len(value.elts), "объявлен перечнем"
        return -1, f"имя `{name}` есть, а его значение не перечень и не словарь"
    return -1, f"имени `{name}` в носителе не объявлено"


# ───────────────────────────── ось C: дорога ЗНАЧЕНИЯ ────────────────────────
#
# Заказ G1093 п. 3 назвал границу прежней меры честно: у формы
# `{путь: "причина строкой"}` причины НЕТ ИМЕНИ, поэтому вопрос «читает ли её
# сторож» строковыми литералами НЕ РАЗРЕШАЕТСЯ, и девять носителей уходили в
# `unmeasured`. Закрыть его можно только дорогой ЗНАЧЕНИЯ: кто пробегает
# `.items()` / `.values()` набора — или читает поле ИЗ его строки — и
# ИСПОЛЬЗУЕТ полученное. Это граф, а не литералы.
#
# Ось отвечает на ПРИСУТСТВИЕ чтения, а НЕ на его осмысленность (п. 6 заказа):
# сторож, прочитавший причину и ничего ею не решивший, через меру пройдёт. Это
# следующий вопрос, и мерить его нечем, кроме независимого читателя.

#: Зовы, не меняющие состав перебираемого: `sorted(x.items())` прячет дорогу
#: значения ровно так же, как `x.items()` её показывает. `set(...)` / `dict(...)`
#: проходными НЕ объявлены намеренно — они меняют ВОПРОС (дают КЛЮЧИ).
PASSTHROUGH = frozenset({"sorted", "list", "tuple", "reversed", "iter"})

VALUE_METHODS = frozenset({"items", "values"})
_CHAIN_METHODS = VALUE_METHODS | {"keys"}

#: Индекс НЕ строкой (`rows[0]`, срез) — это шаг ВНУТРЬ содержимого, а не ключ
#: набора. Отдельный знак нужен, чтобы такой шаг не выдавался за «ключ не
#: разобран»: глубина — и есть ответ.
_DEEP = "\x00deep"

#: Имя ВОЗВРАТА функции того же файла (дверь 4). Отдельное пространство имён
#: нужно затем, чтобы переменная и функция с одним именем не путались.
_RET = "\x00ret:"



def nameless_sets(doc: object) -> dict[str, str]:
    """Наборы с БЕЗЫМЯННОЙ причиной → РОД их значений (из байтов базы).

    Род решает ТИП значений, а не слово о наборе:

    * `reason_string` — значения строки: та самая форма `путь → причина строкой`,
      которую назвал заказ;
    * `tally` — значения числа / `bool` / `None`: это ЗАМЕР, освобождать им
      некого, и причиной он не является. Считать такой набор предметом значило
      бы выдать счётчик за «слово вместо замера»;
    * `listing` — значения списки: СОДЕРЖИМОЕ замера, тоже не причина;
    * `mixed` — вперемешку; причину несёт, если хоть одно значение строка.

    Разделение существенно: замер #1266 нашёл среди девяти «неизмеренных»
    ШЕСТЬ носителей, у которых безымянное значение — ЧИСЛО
    (`operand`={carries: 3}, `counts_at_measure`, `door_sites`, `axis_*`), то
    есть обвинить их значило бы ошибиться в сторону НАХОДКИ.
    """
    out: dict[str, str] = {}
    if not isinstance(doc, dict):
        return out
    for key, value in doc.items():
        if key.startswith("_") or key in META_KEYS:
            continue
        if not isinstance(value, dict) or not value:
            continue
        if any(isinstance(v, dict) for v in value.values()):
            continue                      # причина ИМЕНОВАНА — это ось B
        kinds = set()
        for item in value.values():
            if isinstance(item, str):
                kinds.add("reason_string")
            elif isinstance(item, (list, tuple, dict)):
                kinds.add("listing")
            else:
                kinds.add("tally")
        out[key] = (kinds.pop() if len(kinds) == 1
                    else "mixed:" + "+".join(sorted(kinds)))
    return out


def carrier_anchors(rel: str, doc: object) -> set[str]:
    """Чем файл дерева ОПОЗНАЁТ носителя: имя файла и объявленная схема.

    Схема нужна не для красоты: известный член
    `scripts/python_git_ref_provenance_baseline.json` читается ПРИБОРОМ, который
    имени файла не называет вовсе (путь приходит в `--baseline`), а документ
    опознаёт литералом `BASELINE_SCHEMA`. Форма, теряющая известного читателя,
    класс не сужает, а ПОДМЕНЯЕТ (урок ADR-1074).
    """
    out = {pathlib.PurePath(rel).name}
    if isinstance(doc, dict):
        schema = doc.get("schema")
        if isinstance(schema, str) and schema.strip():
            out.add(schema)
    return out


def _prose_ids(tree: ast.AST) -> set[int]:
    """Константы-ПРОЗА: докстринг и голое строковое выражение.

    Упоминание носителя в прозе читателем не делает — дословный урок ADR-1116.
    Замер: `spa_core/monitoring/card_acceptance.py` называет
    `scripts/forbidden_import_baseline.json` в докстринге, и без этого отсева
    он попал бы в читателей базы, которую не открывает ни одной строкой.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            out.add(id(node.value))
    return out


def _contains_anchor(node: ast.AST, anchors: set[str], prose: set[int]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                and id(sub) not in prose:
            if any(a in sub.value for a in anchors):
                return True
    return False


def names_the_carrier(tree: ast.AST, anchors: set[str]) -> bool:
    """Называет ли файл носителя В КОДЕ (а не в прозе)."""
    return _contains_anchor(tree, anchors, _prose_ids(tree))


def loop_literal_vars(tree: ast.AST) -> dict[str, set[str]]:
    """Переменная цикла → её ЛИТЕРАЛЬНЫЕ строковые значения.

    Вычисляемый ключ без такого перечня остаётся НЕ РАЗОБРАННЫМ (третий исход,
    инв. #17), а известный член класса читается РОВНО так:
    `for _sect in ("admitted_after_migration", "unresolved"):`.
    """
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            continue
        source = node.iter
        while isinstance(source, ast.Call) and isinstance(source.func, ast.Name) \
                and source.func.id in PASSTHROUGH and len(source.args) == 1:
            source = source.args[0]
        if not isinstance(source, (ast.Tuple, ast.List, ast.Set)):
            continue
        values = {e.value for e in source.elts
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if values and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, set()).update(values)
    return out


def _keys_of(node: ast.AST, loopvars: dict[str, set[str]]) -> set[str] | None:
    """Ключ шага: литерал · раскрытая переменная цикла · шаг ВГЛУБЬ · НЕ РАЗОБРАН."""
    inner = getattr(node, "value", None)
    if type(node).__name__ == "Index" and inner is not None:
        node = inner
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else {_DEEP}
    if isinstance(node, ast.Slice):
        return {_DEEP}
    if isinstance(node, ast.Name) and node.id in loopvars:
        return set(loopvars[node.id])
    return None


def _positions(node: ast.AST, derived: dict[str, set[tuple]],
               loopvars: dict[str, set[str]], depth: int = 0,
               fields: frozenset[str] = frozenset()) -> tuple[set[tuple], bool]:
    """Положения внутри документа носителя, которые может держать выражение."""
    if depth > 8:
        return set(), True
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in PASSTHROUGH and len(node.args) == 1:
        node = node.args[0]
    if isinstance(node, ast.Name):
        return set(derived.get(node.id, ())), False
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and _RET + node.func.id in derived:
        # ДВЕРЬ 4: значение пришло ВОЗВРАТОМ функции того же файла.
        return set(derived[_RET + node.func.id]), False
    if isinstance(node, ast.Attribute) and node.attr in fields:
        return {()}, False                 # дверь 3: ИМЯ ПОЛЯ объявлено литералом
    if isinstance(node, ast.BoolOp):
        # `or` отдаёт ЛЕВОЕ при истине и правое иначе ⇒ носителем может быть
        # любой операнд; `and` отдаёт ПОСЛЕДНЕЕ. Путать их — измеренный дефект
        # (шесть ложных «читают» в соседней мерке), поэтому выбор назван.
        operands = node.values if isinstance(node.op, ast.Or) else node.values[-1:]
        out, bad = set(), False
        for operand in operands:
            got, flag = _positions(operand, derived, loopvars, depth + 1, fields)
            out |= got
            bad = bad or flag
        return out, bad
    inner: ast.AST | None = None
    key_node: ast.AST | None = None
    if isinstance(node, ast.Subscript):
        inner, key_node = node.value, node.slice
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        inner, key_node = node.func.value, node.args[0]
    if inner is None or key_node is None:
        return set(), False
    base, bad = _positions(inner, derived, loopvars, depth + 1, fields)
    if not base:
        return set(), bad
    keys = _keys_of(key_node, loopvars)
    # Глубже ВТОРОГО шага положения не различаются намеренно: вопрос оси C —
    # «ключ набора тот ли и зашли ли ВНУТРЬ строки», а не полный адрес поля.
    # Прежняя редакция копила адреса до третьего шага, и на
    # `spa_core/monitoring/card_acceptance.py` (24 348 строк, циклы по
    # литеральным кортежам) набор положений рос произведением — замер #1266:
    # 7 ГиБ памяти и ни одного ответа. Цена меры — часть меры.
    out: set[tuple] = set()
    for base_place in base:
        if len(base_place) >= 2:
            out.add(base_place)
        elif keys is None and len(base_place) == 1:
            # ДВЕРЬ 4б: шаг ВНУТРЬ УЖЕ ОПОЗНАННОГО набора. Какой бы ключ ни
            # стоял, полученное есть ЗНАЧЕНИЕ строки ЭТОГО набора — выдать это
            # за «не разобрано» значило бы объявить предметом файл, который
            # причину читает (замер #1267: `baseline[f.key]` в
            # `scripts/lint_forbidden_imports.py:269` ПЕЧАТАЕТ причину).
            out.add(base_place + (_DEEP,))
        elif keys is None:
            # Положение — ВЕСЬ документ: какой это набор, НЕ ИЗВЕСТНО, и
            # третий исход здесь остаётся третьим исходом (инв. #17).
            bad = True
        else:
            out.update(base_place + (k,) for k in keys)
        if len(out) > _POSITION_CAP:
            # Предел достигнут ⇒ ТРЕТИЙ исход, а не усечённый ответ.
            return set(), True
    return out, bad


def _names_a_field(node: ast.AST, fields: frozenset[str]) -> bool:
    """Упоминает ли выражение ПОЛЕ, объявленное литералом носителя (дверь 3)."""
    if not fields:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in fields:
            return True
    return False


def _peel(node: ast.AST, derived: dict[str, set[tuple]],
          loopvars: dict[str, set[str]],
          fields: frozenset[str] = frozenset()) -> tuple[set[tuple], str | None, bool]:
    """Снять обёртки и метод-хвост: (положения, метод, НЕ РАЗОБРАНО)."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in PASSTHROUGH and len(node.args) == 1:
        node = node.args[0]
    method = None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in _CHAIN_METHODS:
        method = node.func.attr
        node = node.func.value
    pos, bad = _positions(node, derived, loopvars, 0, fields)
    return pos, method, bad


def _value_positions(node: ast.AST, derived: dict[str, set[tuple]],
                     loopvars: dict[str, set[str]], anchors: set[str],
                     prose: set[int], depth: int = 0,
                     fields: frozenset[str] = frozenset()) -> set[tuple]:
    """Какое положение документа получает ПРАВАЯ ЧАСТЬ присваивания."""
    if depth > 12:
        return set()
    chain, _bad = _positions(node, derived, loopvars, 0, fields)
    if chain:
        return chain
    if _contains_anchor(node, anchors, prose):
        return {()}                        # путь к носителю либо сам документ
    out: set[tuple] = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.expr_context, ast.operator, ast.boolop,
                              ast.cmpop, ast.unaryop)):
            continue
        out |= _value_positions(child, derived, loopvars, anchors, prose,
                                depth + 1, fields)
    return out


def _own_returns(fn: ast.AST) -> list[ast.AST]:
    """Выражения `return` САМОЙ функции — без вложенных определений.

    Вложенная функция возвращает СВОЁ, и приписать её возврат внешней значило бы
    расширить дорогу значения туда, где её нет.
    """
    out: list[ast.AST] = []
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            out.append(node.value)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _return_pairs(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """ВОЗВРАТ функции того же файла → псевдоимя `_RET + имя` (дверь 4).

    Без этой двери дорога значения рвётся на границе ФУНКЦИИ, а не помощника, и
    мера врёт в сторону НАХОДКИ. Замер #1267 на известном члене:
    ``scripts/lint_forbidden_imports.py`` опознаёт носителя литералом
    ``BASELINE_REL``, набор выбирает ВНУТРИ помощника
    (``load_baseline`` → ``return doc.get("known", {})``), а причину читает
    в ``main()`` — ``print(f"ИЗВЕСТНОЕ  {f} — {baseline[f.key]}")``. Два
    действия в ОДНОМ файле, между ними один `return`, и первая редакция оси C
    объявила носителя ПРЕДМЕТОМ класса, то есть выдала границу своей меры за
    находку о мире (дословно урок ADR-1074/ADR-1116).

    Зов по АТРИБУТУ (``mod.load_baseline()``) здесь намеренно НЕ разрешается:
    это уже второй хоп, и население за ним НЕ ИЗМЕРЕНО (см. «Чего это не
    закрывает» в ADR-1121).
    """
    pairs: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pairs.extend((_RET + node.name, value) for value in _own_returns(node))
    return pairs


def _mentions(pairs: list[tuple[str, ast.AST]]) -> list[set[str]]:
    """Имена, упомянутые правой частью — включая псевдоимена ВОЗВРАТОВ.

    Неподвижная точка пересматривает правую часть, когда `derived` пополнилось
    упомянутым ею именем. Зов ``load_baseline(root)`` упоминает `load_baseline`,
    а положение приходит под именем ``_RET + "load_baseline"`` — не добавь его
    сюда, и дверь 4 существовала бы, не доезжая до зова НИ РАЗУ (ровно тот
    дефект затравки, что ADR-1121 назвал у двери 3).
    """
    out: list[set[str]] = []
    for _name, value in pairs:
        names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
        out.append(names | {_RET + n for n in names})
    return out


def _assign_pairs(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """Все присваивания имени — ОДНИМ обходом дерева.

    Обход здесь один намеренно: прежняя редакция ходила по дереву двенадцать раз
    (по разу на круг неподвижной точки) и на `card_acceptance.py` не укладывалась
    в предел шага цикла вовсе. Цена меры — часть меры: прибор, который не
    доживает до ответа, отвечает «НЕ ИЗМЕРЕНО» на вопрос, который умел.
    """
    pairs: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    pairs.append((target.id, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                pairs.append((node.target.id, node.value))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            if isinstance(node.optional_vars, ast.Name):
                pairs.append((node.optional_vars.id, node.context_expr))
    pairs.extend(_return_pairs(tree))      # дверь 4: возврат функции файла
    return pairs


def derived_positions(tree: ast.AST, anchors: set[str],
                      loopvars: dict[str, set[str]],
                      facts: tuple | None = None,
                      fields: frozenset[str] = frozenset()) -> dict[str, set[tuple]]:
    """Имена файла, чьё значение происходит от носителя, → их положения.

    Две двери опознания, и обе ИЗМЕРЕНЫ на известных членах:

    1. **происхождение от литерала** — `_BASELINE = Path(...) / "<имя>.json"`,
       затем `d = json.loads(_BASELINE.read_text(...))`; перенос через обёртки
       (`json.loads`, `open`, `Path`) обязателен, иначе дорога рвётся на первом
       же зове;
    2. **правило СХЕМЫ** — `_b.get("schema") != BASELINE_SCHEMA` опознаёт
       документ там, где путь пришёл аргументом и литерала имени в файле нет
       ВОВСЕ. Без него известный член (прибор провенанса) выпал бы из читателей.

    Неподвижная точка считается РАБОЧИМ СПИСКОМ: правая часть пересматривается
    только когда `derived` пополнилось именем, которое она упоминает.
    """
    if facts is None:
        prose = _prose_ids(tree)
        pairs = _assign_pairs(tree)
        mentions = _mentions(pairs)
        candidates = _schema_compare_sites(tree)
    else:
        prose, pairs, mentions, _lv, candidates = facts
    # Затравка обязана включать и дверь 3: правая часть может не нести литерала
    # вовсе и открывать документ ЧУЖИМ полем (`census.DECLARATION_REL`). Первая
    # редакция сеяла только по литералу, и известный читатель в работу не
    # попадал ВООБЩЕ — ложная находка оставалась.
    anchored = [_contains_anchor(value, anchors, prose)
                or _names_a_field(value, fields) for _name, value in pairs]
    derived: dict[str, set[tuple]] = {}
    # Затравка — ТОЛЬКО правые части, где литерал носителя стоит сам: всё
    # остальное попадает в работу лишь когда `derived` пополнилось именем,
    # которое эта правая часть упоминает.
    pending = {i for i, flag in enumerate(anchored) if flag}
    for _round in range(16):
        changed = False
        fresh: set[int] = set()
        for i in sorted(pending):
            name, value = pairs[i]
            got = _value_positions(value, derived, loopvars, anchors, prose,
                                   0, fields)
            if got and not got <= derived.get(name, set()):
                derived.setdefault(name, set()).update(got)
                changed = True
                fresh |= {j for j, names in enumerate(mentions) if name in names}
        for name, comparators in candidates:
            if () in derived.get(name, set()):
                continue
            if any(_contains_anchor(c, anchors, prose)
                   or _value_positions(c, derived, loopvars, anchors, prose,
                                       0, fields) == {()}
                   for c in comparators):
                derived.setdefault(name, set()).add(())
                changed = True
                fresh |= {j for j, names in enumerate(mentions) if name in names}
        if not changed:
            break
        pending = fresh
    return derived


def _schema_compare_sites(tree: ast.AST) -> list[tuple[str, list[ast.AST]]]:
    """Места сверки `X.get("schema") <op> …` — собраны ОДНИМ обходом.

    Само решение «опознан ли документ» принимается на круге неподвижной точки,
    а обход дерева к нему не привязан: это та же цена меры, что у
    :func:`_assign_pairs`.
    """
    out: list[tuple[str, list[ast.AST]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Call):
            continue
        call = node.left
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == "get"
                and call.args and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "schema"
                and isinstance(call.func.value, ast.Name)):
            continue
        out.append((call.func.value.id, list(node.comparators)))
    return out


def value_road_in_file(tree: ast.AST, derived: dict[str, set[tuple]],
                       loopvars: dict[str, set[str]], keys: set[str],
                       fields: frozenset[str] = frozenset(),
                       ) -> tuple[dict[str, list[str]], set[str], list[str]]:
    """Что файл делает с СОДЕРЖИМЫМ безымянных наборов носителя.

    Возврат: (ключ → как прочитано ЗНАЧЕНИЕ, ключи, прочитанные только по
    КЛЮЧАМ, перечень НЕ РАЗОБРАННОГО). Три исхода различимы (инв. #17).
    """
    value: dict[str, list[str]] = {}
    only_keys: set[str] = set()
    unresolved: list[str] = []
    loads = {n.id for n in ast.walk(tree)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}

    def record(pos: set[tuple], method: str | None, where: str,
               value_target: str | None, bad: bool) -> None:
        if bad:
            unresolved.append(f"{where}: ключ вычислен и НЕ РАСКРЫТ")
        for place in pos:
            if not place or place[0] not in keys:
                continue
            key = place[0]
            if len(place) > 1:
                step = ("шаг ВНУТРЬ, ключ вычислен" if place[1] == _DEEP
                        else f"шаг `{place[1]}`")
                value.setdefault(key, []).append(f"{where}: чтение ИЗ строки "
                                                 f"({step})")
            elif method in VALUE_METHODS:
                if method == "items" and value_target is not None \
                        and value_target not in loads:
                    unresolved.append(f"{where}: `.items()`, а ЗНАЧЕНИЕ "
                                      f"`{value_target}` нигде не читается")
                else:
                    value.setdefault(key, []).append(f"{where}: `.{method}()`")
            else:
                only_keys.add(key)

    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            continue
        seen.add(id(node.iter))
        pos, method, bad = _peel(node.iter, derived, loopvars, fields)
        target = node.target
        second = None
        if method == "items" and isinstance(target, ast.Tuple) \
                and len(target.elts) == 2 and isinstance(target.elts[1], ast.Name):
            second = target.elts[1].id
        # У `ast.comprehension` строки нет вовсе — печатать `0` значило бы
        # выдать отсутствие наблюдения за номер строки (инв. #17).
        line = getattr(node, "lineno", None)
        where = f"цикл@{line}" if line else "включение (строка не объявлена)"
        record(pos, method, where, second, bad)
    for node in ast.walk(tree):
        if id(node) in seen or not isinstance(node, (ast.Call, ast.Subscript)):
            continue
        pos, method, bad = _peel(node, derived, loopvars, fields)
        if not pos and not bad:
            continue
        # `not pos` при `bad` — НЕ «нечего записать»: это ровно третий исход,
        # и прежняя редакция теряла его молча (сцена с вычисленным ключом,
        # пришедшим параметром, выходила «только КЛЮЧИ»).
        line = getattr(node, "lineno", None)
        record(pos, method,
               f"выражение@{line}" if line else "выражение (строка не объявлена)",
               None, bad)
    return value, only_keys, unresolved

def anchor_index(root: pathlib.Path,
                 anchors: set[str]) -> tuple[dict[str, set[str]], list[str]]:
    """Какие `*.py` дерева называют хоть один опознавательный знак носителей.

    Это ПРЕДФИЛЬТР по байтам: он только сужает, кого разбирать, а утверждение о
    чтении делает уже AST. Нечитаемый файл уходит в третий исход ПОИМЁННО — его
    молчание неотличимо от «не называет», и подменять одно другим запрещено.
    """
    hits: dict[str, set[str]] = {}
    unreadable: list[str] = []
    cheap = tuple(sorted({a for a in anchors if "baseline" not in a}))
    for path in sorted(root.rglob("*.py")):
        if ".git" in path.parts:
            continue
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        if "baseline" not in text and not any(c in text for c in cheap):
            continue
        found = {a for a in anchors if a in text}
        if found:
            hits[rel] = found
    return hits, unreadable


#: Кеши ЧИТАТЕЛЯ: разбор, проза, присваивания и переменные циклов от носителя
#: не зависят, а один файл называет много носителей. Без них прибор ходил по
#: дереву `card_acceptance.py` по разу на КАЖДЫЙ носитель и до ответа не доживал.
_TREE_CACHE: dict[str, ast.AST | None] = {}
_READER_FACTS: dict[str, tuple] = {}


def _reader_tree(root: pathlib.Path, rel: str) -> ast.AST | None:
    """Разобранный читатель с КЕШЕМ: один файл называет много носителей."""
    key = str(root / rel)
    if key not in _TREE_CACHE:
        try:
            _TREE_CACHE[key] = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            _TREE_CACHE[key] = None
    return _TREE_CACHE[key]


def reader_facts(rel: str, tree: ast.AST) -> tuple:
    """Проза · присваивания · упоминания имён · переменные циклов · сверки схемы."""
    if rel not in _READER_FACTS:
        prose = _prose_ids(tree)
        pairs = _assign_pairs(tree)
        mentions = _mentions(pairs)
        _READER_FACTS[rel] = (prose, pairs, mentions, loop_literal_vars(tree),
                              _schema_compare_sites(tree))
    return _READER_FACTS[rel]


def attr_anchors(pairs: list[tuple[str, ast.AST]], anchors: set[str],
                 prose: set[int]) -> set[str]:
    """Имена ПОЛЕЙ, объявленных в этом файле литералом носителя.

    Третья дверь опознания, и без неё мера даёт ЛОЖНУЮ НАХОДКУ. Замер #1266:
    `spa_core/tests/test_unfinished_work_probe.py` объявляет
    `DECLARATION_REL = "spa_core/tests/unfinished_work_class_baseline.json"`
    (заглушкой модуля), а документ открывает ЧУЖИМ полем —
    `json.loads((Path(census.PROJECT_ROOT) / census.DECLARATION_REL).read_text(...))`.
    Имя у поля ОДНО, контракт один, и первая редакция оси C объявила этот
    носитель предметом, хотя его `axis_one.rows` читают построчно. Ошибка в
    сторону НАХОДКИ — та же, что ADR-1074 назвал подменой класса.
    """
    return {name for name, value in pairs
            if _contains_anchor(value, anchors, prose)}



def value_road(root: pathlib.Path, rel: str, doc: object, sets: dict[str, str],
               index: dict[str, set[str]],
               ) -> tuple[str, list[str], list[str], set[str]]:
    """Ось C об ОДНОМ носителе: (вердикт, доказательства, НЕ РАЗОБРАННОЕ, наборы).

    Четвёртое возвращаемое — ключи наборов, у которых дорога значения НАЙДЕНА.
    Без него вердикт отвечал бы о ДРУГОМ наборе: у
    `scripts/adapter_status_caller_supplied_baseline.json` причину-строку несёт
    блок ЗАМЕРА `измерено_на`, а `.items()` читают у счётчика `файлы` — и первая
    редакция объявила носителя «значение читают», ни разу не спросив о причине
    (дословно класс ADR-1072: «ответ о ДРУГОМ носителе, выданный за ответ о моём»).

    Вердикт: `value` — значение набора кто-то читает · `keys` — читатели есть, а
    берут только КЛЮЧИ · `no_reader` — носителя не называет в КОДЕ ни один файл
    дерева · `unmeasured` — дорога есть, но разобрать её не удалось.
    """
    anchors = carrier_anchors(rel, doc)
    keys = set(sets)
    proofs: list[str] = []
    key_only: set[str] = set()
    unresolved: list[str] = []
    value_keys: set[str] = set()
    readers = [r for r, found in index.items() if found & anchors]
    if not readers:
        return ROAD_NONE, [], [], value_keys
    code_readers = 0
    for reader in sorted(readers):
        tree = _reader_tree(root, reader)
        if tree is None:
            unresolved.append(f"{reader}: не разобран")
            continue
        facts = reader_facts(str(root / reader), tree)
        if not _contains_anchor(tree, anchors, facts[0]):
            continue                      # назвал только в ПРОЗЕ — не читатель
        code_readers += 1
        loopvars = facts[3]
        fields = frozenset(attr_anchors(facts[1], anchors, facts[0]))
        derived = derived_positions(tree, anchors, loopvars, facts, fields)
        if not derived and not fields:
            continue
        got, only, bad = value_road_in_file(tree, derived, loopvars, keys, fields)
        for key, how in got.items():
            proofs.append(f"{reader} → `{key}`: {how[0]}")
            value_keys.add(key)
        key_only |= only
        # Причины СВОРАЧИВАЮТСЯ по роду: у одного читателя их бывают тысячи
        # (по узлу выражения), и перечислять их поштучно значило бы утопить
        # счётчик «НЕ ИЗМЕРЕНО» — замер первой редакции дал 5017 строк.
        if bad:
            kinds: dict[str, int] = {}
            for row in bad:
                kind = row.split(": ", 1)[-1]
                kinds[kind] = kinds.get(kind, 0) + 1
            unresolved.append(f"{reader}: " + " · ".join(
                f"{kind} ×{count}" for kind, count in sorted(kinds.items())))
    if proofs:
        return ROAD_VALUE, proofs, unresolved, value_keys
    if unresolved:
        return ROAD_UNMEASURED, [], unresolved, value_keys
    if not code_readers:
        # Байтовый предфильтр нашёл имя, а В КОДЕ его не называет никто:
        # «назвал в прозе» читателем не делает, и выдать это за «читатели
        # есть, но берут КЛЮЧИ» значило бы ответить о другом носителе.
        return ROAD_NONE, [], [], value_keys
    if key_only:
        return ROAD_KEYS, [f"читатели берут только КЛЮЧИ наборов "
                           f"{sorted(key_only)}"], [], value_keys
    return (ROAD_KEYS, ["ни один читатель не добирается до содержимого наборов"],
            [], value_keys)


# ───────────────────────────── контроль формы ДО чисел ───────────────────────

def _carrier_is_not_an_exclusion_base(root: pathlib.Path,
                                      rel: str) -> tuple[bool, str]:
    """Проверить объявленное исключение из поверхности: читателя-сторожа быть НЕ должно.

    Слово «не нужно» причиной не является — у исключения обязан быть замер.
    """
    needle = pathlib.PurePath(rel).name
    readers: list[str] = []
    for pattern in ("spa_core/tests/test_*.py", "scripts/tests/test_*.py"):
        for path in root.glob(pattern):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if needle in text:
                readers.append(str(path.relative_to(root)))
    if readers:
        return False, f"читателей-сторожей {len(readers)}: {readers[:3]}"
    return True, "ни одного читателя-сторожа не нашлось"


# ───────────────────────────── перепись ──────────────────────────────────────

def census(root: pathlib.Path) -> tuple[list[Verdict], list[str], dict[str, str]]:
    """Вердикты по обоим носителям · НЕ ИЗМЕРЕННОЕ с причинами · ответы оси C."""
    verdicts: list[Verdict] = []
    unmeasured: list[str] = []
    road_table: dict[str, str] = {}

    guards, guards_unparsed = guard_literals(root)
    if not guards:
        return [], ["охват сторожей ПУСТ: ни один файл не разобрался — "
                    "ось B спросить нечем"], {}
    for rel in guards_unparsed:
        unmeasured.append(f"сторож не разобран, его ответ об оси B неизвестен: {rel}")

    # — носитель JSON —
    try:
        files = sorted(p for p in root.rglob("*baseline*.json")
                       if ".git" not in p.parts)
    except OSError as exc:
        return [], [f"поверхность JSON не прочитана: {type(exc).__name__}: {exc}"], {}

    # Опознавательные знаки ВСЕХ носителей собираются ЗАРАНЕЕ: индекс читателей
    # строится ОДНИМ проходом по дереву, а не по разу на носителя.
    docs: dict[str, object] = {}
    all_anchors: set[str] = set()
    for path in files:
        rel = str(path.relative_to(root))
        if rel in NOT_AN_EXCLUSION_BASE:
            continue
        try:
            docs[rel] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue                       # о причине скажет основной проход
        all_anchors |= carrier_anchors(rel, docs[rel])
    index, index_unreadable = anchor_index(root, all_anchors)
    for row in index_unreadable:
        unmeasured.append(f"файл дерева не прочитан, его ответ об оси C неизвестен: {row}")

    for number, path in enumerate(files, 1):
        rel = str(path.relative_to(root))
        if number == 1 or number % 5 == 0 or number == len(files):
            # Долгий прогон обязан быть ВИДЕН (`.claude/rules/deployment.md`
            # § «ОКНО МУТАЦИОННОГО ПРИБОРА» п. 8), но строка на КАЖДОГО носителя
            # тонет в логе прогона набора — отсюда шаг в пять.
            print(f"[перепись] {number}/{len(files)} {rel}",
                  file=sys.stderr, flush=True)
        if rel in NOT_AN_EXCLUSION_BASE:
            ok, detail = _carrier_is_not_an_exclusion_base(root, rel)
            if ok:
                verdicts.append(Verdict(rel, "json", "not_an_exclusion_base", 0,
                                        NOT_AN_EXCLUSION_BASE[rel]))
            else:
                unmeasured.append(
                    f"{rel}: объявлено «не база исключений», а замер спорит — {detail}")
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            unmeasured.append(f"{rel}: не прочитана — {type(exc).__name__}: {exc}")
            continue
        axis, rows, detail = reason_axis(doc)
        if axis == "no_rows":
            verdicts.append(Verdict(rel, "json", "no_rows", 0, detail))
            continue
        if axis == "reason_absent":
            verdicts.append(Verdict(rel, "json", "reason_absent", rows, detail))
            continue
        # причина у строки ЕСТЬ (целиком или частью) ⇒ спросить ДЕРЕВО
        keys, nameless = reason_keys(doc)
        readers, reading = remeasure_axis(rel, keys, guards)

        # ── ось C: дорога ЗНАЧЕНИЯ у безымянной причины (ADR-1121) ──
        sets = nameless_sets(doc)
        road, proofs, road_bad, road_keys = ROAD_NONE, [], [], set()
        if sets:
            road, proofs, road_bad, road_keys = value_road(
                root, rel, doc, sets, index)
            road_table[rel] = road
            unmeasured.extend(f"{rel} · ось C: {row}" for row in road_bad)
        bearing = sorted(k for k, kind in sets.items() if "reason_string" in kind)
        # Дорога значения зачитывается ТОЛЬКО у набора, который причину НЕСЁТ.
        bearing_road = sorted(road_keys & set(bearing))

        if not keys and nameless:
            kinds = ", ".join(f"`{k}`={sets[k]}" for k in sorted(sets))
            if not bearing:
                verdicts.append(Verdict(
                    rel, "json", "nameless_not_a_reason", rows,
                    f"{detail}; безымянные наборы несут не причину, а "
                    f"ЗАМЕР/СОДЕРЖИМОЕ ({kinds}); дорога значения: {road}"))
            elif road == ROAD_VALUE and bearing_road:
                shown = next(p for p in proofs
                             if any(f"`{k}`" in p for k in bearing_road))
                verdicts.append(Verdict(
                    rel, "json", "value_read", rows,
                    f"{detail}; причина безымянна ({kinds}), и ЗНАЧЕНИЕ читают — "
                    f"{shown}" + (f" (+{len(proofs) - 1} ещё)"
                                  if len(proofs) > 1 else "")))
            elif road == ROAD_VALUE:
                verdicts.append(Verdict(
                    rel, "json", "value_read_elsewhere", rows,
                    f"{detail}; причина безымянна ({kinds}); ЗНАЧЕНИЕ читают, но "
                    f"у ДРУГИХ наборов {sorted(road_keys)} — у несущих причину "
                    f"{bearing} дороги значения не нашлось: {proofs[0]}"))
            elif road == ROAD_NONE:
                verdicts.append(Verdict(
                    rel, "json", "nameless_no_reader", rows,
                    f"{detail}; причина безымянна ({kinds}), а носителя не "
                    f"называет В КОДЕ ни один `*.py` дерева — это вопрос о "
                    f"СИРОТЕ, а не «слово вместо замера»"))
            elif road == ROAD_UNMEASURED:
                unmeasured.append(
                    f"{rel}: дорога значения НЕ РАЗОБРАНА у всех читателей")
            else:
                verdicts.append(Verdict(
                    rel, "json", "subject", rows,
                    f"{detail}; причина безымянна ({kinds}) и ЗНАЧЕНИЕ не читает "
                    f"никто: {proofs[0] if proofs else 'читатели берут только КЛЮЧИ'}"))
            continue
        if not readers:
            verdicts.append(Verdict(rel, "json", "subject", rows,
                                    f"{detail}; причинных ключей {len(keys)}, "
                                    f"а читателя-сторожа в охвате НЕТ ни одного"))
            continue
        if nameless:
            partial = (f"; безымянных наборов ещё {nameless}, дорога значения у "
                       f"них: {road}")
        else:
            partial = ""
        if reading:
            best = max(readers, key=lambda r: r[1])
            verdicts.append(Verdict(
                rel, "json", "remeasured", rows,
                f"{detail}; {best[0]} называет {best[1]} из {len(keys)} причинных "
                f"ключ(а/ей) (читателей {len(readers)}){partial}"))
        else:
            verdicts.append(Verdict(
                rel, "json", "subject", rows,
                f"{detail}; читателей {len(readers)}, но ни один не называет ни "
                f"одного из {len(keys)} причинных ключей — причина есть СЛОВО"))

    # — носитель PYTHON (перечень объявлен; полнота — НАЗВАННЫЙ долг) —
    for key, (measure_rel, why) in PYTHON_CARRIERS.items():
        rel, name = key.split("::", 1)
        rows, how = python_carrier_declares_rows(root, rel, name)
        if rows < 0:
            unmeasured.append(f"{key}: {how}")
            continue
        if measure_rel == MEASURE_ABSENT:
            verdicts.append(Verdict(key, "python", "subject", rows,
                                    f"{how}; МЕРКИ НЕТ: {why}"))
            continue
        named, detail = measure_names_the_base(root, measure_rel, name)
        if named:
            verdicts.append(Verdict(key, "python", "remeasured", rows,
                                    f"{how}; мерка {measure_rel} ({detail})"))
        else:
            unmeasured.append(
                f"{key}: объявленный адрес мерки перечня не называет — {detail}")

    return verdicts, unmeasured, road_table


def check_known_members(verdicts: list[Verdict],
                        roads: dict[str, str] | None = None) -> list[str]:
    """Контроль ДО чисел: каждый известный член обязан лечь в ожидаемое ведро.

    Осей контроля ДВЕ, и они независимы: ВЕДРО решается родом значения, ДОРОГА —
    чтением дерева. Сойдись только одна — числа всё равно не выдаются: мера,
    у которой известный член попал не в своё ведро, отвечает о ДРУГОМ классе.
    """
    got = {v.key: v.bucket for v in verdicts}
    broken: list[str] = []
    for key, expected in KNOWN_MEMBERS.items():
        actual = got.get(key)
        if actual is None:
            broken.append(f"{key}: известный член ПОТЕРЯН поверхностью "
                          f"(ожидалось ведро `{expected}`)")
        elif actual != expected:
            broken.append(f"{key}: ведро `{actual}`, ожидалось `{expected}`")
    if roads is not None:
        for key, expected in KNOWN_VALUE_ROAD.items():
            actual = roads.get(key)
            if actual is None:
                broken.append(f"{key}: ось C известного члена НЕ СПРОШЕНА "
                              f"(ожидалось `{expected}`)")
            elif actual != expected:
                broken.append(f"{key}: дорога значения `{actual}`, "
                              f"ожидалось `{expected}`")
    return broken


def control_line(known: dict[str, str], roads: dict[str, str]) -> str:
    """Строка о контроле — ЗАМЕР состава таблицы, а не слово «обе стороны».

    После двери 4 (ADR-1121, поправка #1267) предмет класса ПУСТ, и носителя на
    сторону `keys` в дереве не осталось ни одного. Печатать «обе стороны»
    значило бы утверждать о контроле, которого в таблице НЕТ; отсутствующая
    сторона НАЗЫВАЕТСЯ, и названо, где её контроль живёт.
    """
    sides = sorted(set(roads.values()))
    tail = ("" if ROAD_KEYS in sides else
            f" — сторону `{ROAD_KEYS}` в дереве не держит НИ ОДИН носитель "
            f"(предмет пуст), её контроль живёт СЦЕНОЙ сторожа")
    return (f"контроль известных членов: {len(known)} из {len(known)} "
            f"в ожидаемых ведрах · ось C: {len(roads)} из {len(roads)}, "
            f"стороны в таблице: {', '.join(sides) or '—'}{tail}")


def render(root: pathlib.Path) -> tuple[str, int]:
    verdicts, unmeasured, roads = census(root)
    lines = [f"перепись «исключение объявлено СЛОВОМ, а не замером» (схема {SCHEMA})",
             f"дерево: {root}"]

    broken = check_known_members(verdicts, roads)
    if broken:
        lines.append("")
        lines.append("🚨 НЕ ИЗМЕРЕНО: контроль ИЗВЕСТНЫХ ЧЛЕНОВ не сошёлся — "
                     "ни одного числа о классе не выдаётся")
        for row in broken:
            lines.append(f"   ✗ {row}")
        lines.append("   Форма, потерявшая известного члена, класс не сужает, "
                     "а ПОДМЕНЯЕТ (урок ADR-1074).")
        return "\n".join(lines), 2
    lines.append(control_line(KNOWN_MEMBERS, KNOWN_VALUE_ROAD))

    buckets: dict[str, list[Verdict]] = {}
    for v in verdicts:
        buckets.setdefault(v.bucket, []).append(v)
    subject = buckets.get("subject", [])
    absent = buckets.get("reason_absent", [])
    mixed_remeasured = buckets.get("remeasured", [])
    norows = buckets.get("no_rows", [])
    notbase = buckets.get("not_an_exclusion_base", [])
    value_read = buckets.get("value_read", [])
    not_a_reason = buckets.get("nameless_not_a_reason", [])
    no_reader = buckets.get("nameless_no_reader", [])
    elsewhere = buckets.get("value_read_elsewhere", [])

    lines.append("")
    lines.append(f"носителей в поверхности: {len(verdicts)} "
                 f"(json {sum(1 for v in verdicts if v.carrier == 'json')} · "
                 f"python {sum(1 for v in verdicts if v.carrier == 'python')})")
    lines.append(f"  ПРЕДМЕТ (причина у строки ЕСТЬ, перемерять не берётся никто): "
                 f"{len(subject)}")
    lines.append(f"  причина ПЕРЕМЕРЯЕТСЯ (ось B, причина ИМЕНОВАНА): "
                 f"{len(mixed_remeasured)}")
    lines.append(f"  причина БЕЗЫМЯННА, но ЗНАЧЕНИЕ читают (ось C): "
                 f"{len(value_read)}")
    lines.append(f"  безымянное значение — ЗАМЕР/СОДЕРЖИМОЕ, причиной не "
                 f"является: {len(not_a_reason)}")
    lines.append(f"  ЗНАЧЕНИЕ читают у ДРУГОГО набора, не у несущего причину: "
                 f"{len(elsewhere)}")
    lines.append(f"  причина безымянна, а носителя не называет НИ ОДИН `*.py` "
                 f"(вопрос о СИРОТЕ): {len(no_reader)}")
    lines.append(f"  РОД ДРУГОЙ — причины у строки нет вовсе (она файловая): "
                 f"{len(absent)}")
    lines.append(f"  строк исключений нет (порог/замер, освобождать некого): {len(norows)}")
    lines.append(f"  объявлено «не база исключений» и ЗАМЕР согласен: {len(notbase)}")
    lines.append(f"  НЕ ИЗМЕРЕНО: {len(unmeasured)} — это НЕ ноль")

    if subject:
        lines.append("")
        lines.append("ПРЕДМЕТ ПОИМЁННО:")
        for v in sorted(subject, key=lambda x: -x.rows):
            lines.append(f"  🚨 {v.key} ({v.rows} строк) — {v.detail}")
    if mixed_remeasured:
        lines.append("")
        lines.append("ПРИЧИНА ПЕРЕМЕРЯЕТСЯ (контроль оси B в сторону «да»):")
        for v in mixed_remeasured:
            lines.append(f"  ✅ {v.key} ({v.rows} строк) — {v.detail}")
    if value_read:
        lines.append("")
        lines.append("ОСЬ C — ЗНАЧЕНИЕ безымянной причины ЧИТАЮТ "
                     "(присутствие чтения, НЕ его осмысленность):")
        for v in value_read:
            lines.append(f"  ✅ {v.key} ({v.rows} строк) — {v.detail}")
    if elsewhere:
        lines.append("")
        lines.append("ОТВЕТ О ДРУГОМ НАБОРЕ — дорога значения есть, но не у того, "
                     "кто несёт причину (класс ADR-1072, в предмет НЕ идёт):")
        for v in elsewhere:
            lines.append(f"  ? {v.key} ({v.rows} строк) — {v.detail}")
    if not_a_reason:
        lines.append("")
        lines.append("РОД ДРУГОЙ — безымянное значение есть ЗАМЕР или "
                     "СОДЕРЖИМОЕ (обвинять ЗАПРЕЩЕНО: это счётчик, не слово):")
        for v in not_a_reason:
            lines.append(f"  • {v.key} — {v.detail}")
    if no_reader:
        lines.append("")
        lines.append("ВОПРОС О СИРОТЕ — причина безымянна, носителя не называет "
                     "в КОДЕ ни один `*.py` дерева (другой класс, не предмет):")
        for v in no_reader:
            lines.append(f"  ? {v.key} — {v.detail}")
    if absent:
        lines.append("")
        lines.append("РОД ДРУГОЙ — причина ФАЙЛОВАЯ, одна на все строки "
                     "(предметом НЕ является, подменять класс нельзя):")
        for v in sorted(absent, key=lambda x: -x.rows):
            lines.append(f"  • {v.key} ({v.rows} строк)")
    if unmeasured:
        lines.append("")
        lines.append("НЕ ИЗМЕРЕНО ПОИМЁННО (причина названа у каждого):")
        for row in unmeasured:
            lines.append(f"  ? {row}")

    lines.append("")
    lines.append(f"ВИЛКА населения предмета: {len(subject)} … "
                 f"{len(subject) + len(unmeasured) + len(no_reader) + len(elsewhere)}"
                 f" — неразобранное, СИРОТЫ и «ответ о другом наборе» нулём не "
                 f"считаются")
    lines.append("ДОЛГ НАЗВАН: полнота перечня Python-носителей НЕ ИЗМЕРЕНА — "
                 "«модульный словарь освобождённых» структурно неотличим от любого "
                 "другого словаря, перечислением не добывается.")
    lines.append("Прибор только ЧИТАЕТ: ни одной базы, ни одного сторожа не правит.")
    code = 1 if (subject or unmeasured) else 0
    return "\n".join(lines), code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=None,
                    help="дерево замера; умолчание ПЕЧАТАЕТСЯ (ADR-933)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    if args.repo_root is None:
        root = pathlib.Path(__file__).resolve().parent.parent
        print(f"[дерево НЕ НАЗВАНО — умолчание {root}]", file=sys.stderr)
    else:
        root = pathlib.Path(args.repo_root).resolve()
        if not root.is_dir():
            print(f"НЕ ИЗМЕРЕНО: названное дерево не читается: {root}", file=sys.stderr)
            return 2

    if args.json:
        verdicts, unmeasured, roads = census(root)
        broken = check_known_members(verdicts, roads)
        payload = {"schema": SCHEMA, "root": str(root),
                   "known_member_control_broken": broken,
                   "verdicts": [v.as_dict() for v in verdicts],
                   "value_road": roads,
                   "unmeasured": unmeasured}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if broken:
            return 2
        subject = [v for v in verdicts if v.bucket == "subject"]
        return 1 if (subject or unmeasured) else 0

    text, code = render(root)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
