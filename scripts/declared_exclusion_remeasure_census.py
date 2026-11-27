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
}


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

def census(root: pathlib.Path) -> tuple[list[Verdict], list[str]]:
    """Вердикты по обоим носителям + перечень НЕ ИЗМЕРЕННОГО с причинами."""
    verdicts: list[Verdict] = []
    unmeasured: list[str] = []

    guards, guards_unparsed = guard_literals(root)
    if not guards:
        return [], ["охват сторожей ПУСТ: ни один файл не разобрался — "
                    "ось B спросить нечем"]
    for rel in guards_unparsed:
        unmeasured.append(f"сторож не разобран, его ответ об оси B неизвестен: {rel}")

    # — носитель JSON —
    try:
        files = sorted(p for p in root.rglob("*baseline*.json")
                       if ".git" not in p.parts)
    except OSError as exc:
        return [], [f"поверхность JSON не прочитана: {type(exc).__name__}: {exc}"]
    for path in files:
        rel = str(path.relative_to(root))
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
        if not keys and nameless:
            unmeasured.append(
                f"{rel}: причина — безымянное ЗНАЧЕНИЕ ({nameless} набор(а/ов) формы "
                f"`путь → причина строкой`); вопрос «читает ли её сторож» строковыми "
                f"литералами НЕ РАЗРЕШАЕТСЯ — это граница меры, а не находка")
            continue
        if not readers:
            verdicts.append(Verdict(rel, "json", "subject", rows,
                                    f"{detail}; причинных ключей {len(keys)}, "
                                    f"а читателя-сторожа в охвате НЕТ ни одного"))
            continue
        partial = (f"; ЧАСТИЧНО: ещё {nameless} набор(а/ов) с причиной-ЗНАЧЕНИЕМ "
                   f"этой меркой не судятся" if nameless else "")
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

    return verdicts, unmeasured


def check_known_members(verdicts: list[Verdict]) -> list[str]:
    """Контроль ДО чисел: каждый известный член обязан лечь в ожидаемое ведро."""
    got = {v.key: v.bucket for v in verdicts}
    broken: list[str] = []
    for key, expected in KNOWN_MEMBERS.items():
        actual = got.get(key)
        if actual is None:
            broken.append(f"{key}: известный член ПОТЕРЯН поверхностью "
                          f"(ожидалось ведро `{expected}`)")
        elif actual != expected:
            broken.append(f"{key}: ведро `{actual}`, ожидалось `{expected}`")
    return broken


def render(root: pathlib.Path) -> tuple[str, int]:
    verdicts, unmeasured = census(root)
    lines = [f"перепись «исключение объявлено СЛОВОМ, а не замером» (схема {SCHEMA})",
             f"дерево: {root}"]

    broken = check_known_members(verdicts)
    if broken:
        lines.append("")
        lines.append("🚨 НЕ ИЗМЕРЕНО: контроль ИЗВЕСТНЫХ ЧЛЕНОВ не сошёлся — "
                     "ни одного числа о классе не выдаётся")
        for row in broken:
            lines.append(f"   ✗ {row}")
        lines.append("   Форма, потерявшая известного члена, класс не сужает, "
                     "а ПОДМЕНЯЕТ (урок ADR-1074).")
        return "\n".join(lines), 2
    lines.append(f"контроль известных членов: {len(KNOWN_MEMBERS)} из "
                 f"{len(KNOWN_MEMBERS)} в ожидаемых ведрах (обе стороны)")

    buckets: dict[str, list[Verdict]] = {}
    for v in verdicts:
        buckets.setdefault(v.bucket, []).append(v)
    subject = buckets.get("subject", [])
    absent = buckets.get("reason_absent", [])
    mixed_remeasured = buckets.get("remeasured", [])
    norows = buckets.get("no_rows", [])
    notbase = buckets.get("not_an_exclusion_base", [])

    lines.append("")
    lines.append(f"носителей в поверхности: {len(verdicts)} "
                 f"(json {sum(1 for v in verdicts if v.carrier == 'json')} · "
                 f"python {sum(1 for v in verdicts if v.carrier == 'python')})")
    lines.append(f"  ПРЕДМЕТ (причина у строки ЕСТЬ, перемерять не берётся никто): "
                 f"{len(subject)}")
    lines.append(f"  причина ПЕРЕМЕРЯЕТСЯ: {len(mixed_remeasured)}")
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
                 f"{len(subject) + len(unmeasured)} — неразобранное нулём не считается")
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
        verdicts, unmeasured = census(root)
        broken = check_known_members(verdicts)
        payload = {"schema": SCHEMA, "root": str(root),
                   "known_member_control_broken": broken,
                   "verdicts": [v.as_dict() for v in verdicts],
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
