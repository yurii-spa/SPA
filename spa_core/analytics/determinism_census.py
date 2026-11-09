"""determinism_census.py — §26 ТЗ «Portfolio CIO»: Determinism.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §26 «Determinism»::

    При одинаковых:
    market snapshot
    portfolio state
    risk policy
    configuration
    Portfolio Optimizer должен выдавать одинаковый результат.
    LLM может:
    объяснять;
    summarise;
    формировать owner-facing recommendation.
    LLM не должен определять:
    арифметику;
    allocation constraints;
    финансовые расчеты;
    policy pass/fail.

§26 формулирован короче всех предыдущих разделов и ровно поэтому опаснее: одна
строка «одинаковый результат» читается как уже проверенное свойство, а проверять
в ней надо ПАРУ «вход → выход», причём вход назван ЧЕТЫРЬМЯ словами, и ни одно из
них не есть имя аргумента в коде.

🪤 ЧИСЛО ВХОДОВ СНЯТО ПРИБОРОМ, А НЕ ГЛАЗАМИ
============================================
Как и в §25, перечень кончается строкой ПЕРЕД заголовком следующего раздела, и
обе границы названы константами (:data:`SECTION_HEAD`, :data:`NEXT_SECTION_HEAD`).
Поэтому каждое число живёт ДВАЖДЫ и обязано совпасть:

* :data:`OWNER_INPUTS_DECLARED` (4) · :data:`OWNER_PERMITTED_DECLARED` (3) ·
  :data:`OWNER_FORBIDDEN_DECLARED` (4) — константы;
* :func:`owner_section_from_card` — РАЗБОР карточки приказа, то есть
  ПРОИЗВОДИТЕЛЬ числа.

Расхождение краснеет тестом. Карточка нечитаема ⇒ ТРЕТИЙ ИСХОД (``unmeasured`` с
названной причиной), а не молчаливый возврат к константе (урок ADR-913/ADR-919:
сторож, сравнивающий свои константы САМ С СОБОЙ, не мерит ничего).

§26 несёт ДВА требования, и они нарушаются порознь
==================================================
Половина первая — ПАРА «вход → выход» (оси A, B, C ниже). Половина вторая — РОЛЬ
LLM: три разрешённых занятия и ЧЕТЫРЕ запрещённых определения (ось D). Склеить их
в один вердикт значило бы выдать ответ о детерминизме арифметики за ответ о том,
кто эту арифметику определяет.

Главная находка: ВХОДОВ ПЯТЬ, А НЕ ЧЕТЫРЕ (ось C)
=================================================
Детерминизм есть свойство ПАРЫ, поэтому вопрос «одинаковый ли результат» имеет
смысл только вместе с вопросом «одинаковый ли ВХОД», а список входов владельца
НЕПОЛОН: у ``StrategyAllocator`` результат зависит ещё и от того, КОГДА его
позвали. Гейт годности протокола (``_fundable`` → ``unevidenced``) стои́т на
окне свежести ``_EVIDENCE_MAX_AGE_H = 36.0`` ч, а окно сравнивает отметку
НАБЛЮДЕНИЯ со стенными часами.

Замер 2026-11-09 (цикл #1087), живой снимок, байты входа НЕ менялись ни на один —
двигался РОВНО ``now``::

    now+0h   : APY-evidenced 22 · TVL-evidenced 19
    now+12h  : APY-evidenced 22 · TVL-evidenced 19
    now+24h  : APY-evidenced 10 · TVL-evidenced  0      ← сменился набор
    now+1год : APY-evidenced 10 · TVL-evidenced  0

То есть при ОДИНАКОВЫХ четырёх входах владельца результат РАЗНЫЙ, и §26 как
написан неисполним не потому, что расчёт случаен, а потому, что в нём не назван
пятый вход. Пятый вход при этом **не пришпиливается на входе субъекта**:
``allocate()`` не принимает ``now`` вовсе (ось A), а инъекция ``now=`` живёт
только у внутренних ``_load_evidenced_apy`` / ``_load_evidenced_tvl``.

🪤 ПОЧЕМУ ЭТОГО НЕ ВИДИТ ЗЕЛЁНЫЙ ОТВЕТ §49 `Determinism`
=======================================================
Сосед :mod:`spa_core.monitoring.decision_reproducibility` (ADR-513/ADR-515)
отвечает на §49 «Calculations reproducible» и отвечает ВЕРНО: 100 прогонов из 100
дали один хеш. Его прогоны идут в пределах СЕКУНД друг от друга, поэтому окно
свежести между ними не пересекает ни одной границы — **дверь пятого входа закрыта
у него ПО ПОСТРОЕНИЮ, а не по замеру**. Он же объявляет часы субъекта полем
``clock_fields=("timestamp",)``, то есть числит клок ШТАМПОМ производителя; у
аллокатора клок ещё и АРИФМЕТИЧЕСКИЙ вход, и эти два рода здесь различены.

Это не упрёк соседу: зелёный ответ на свой вопрос никогда не есть ответ на
нужный. Ось B поэтому НЕ перемеряет то, что он уже измерил, а ВВОЗИТ его вердикт
и добавляет дверь, которой у него нет (свободная соль хеша).

🪤 ЧТО ВЫЧТЕНО ИЗ ПРЕДМЕТА ЯВНО
===============================
§25 измерил (ADR-968), что ``decision_id`` тени ADR-060 — детерминированная метка
``adr060-shadow-<дата>``, а ``generated_at`` — нет: два прогона одного дня дают
разные ЗАПИСИ по построению. §26 — про РЕЗУЛЬТАТ оптимизатора, а не про отметку
прогона, поэтому объявленные штампы (:data:`RUN_IDENTITY_FIELDS`) снимаются до
сравнения ЕДИНСТВЕННОЙ дверью :func:`spa_core.monitoring.decision_reproducibility.strip_clock`
(своя копия правила означала бы, что прибор глушит по имени то, что ему удобно).

🪤 ДВЕ РАЗНЫЕ ДВЕРИ, КОТОРЫЕ ЛЕГКО СЧЕСТЬ ОДНОЙ
===============================================
Порядок обхода ``set`` и порядок ключей ``dict`` — РАЗНЫЕ двери. Соль хеша
(``PYTHONHASHSEED``) фиксирует первую; порядок вставки в ``dict`` гарантирован
языком с 3.7 и от соли не зависит вовсе. Поэтому ось B спрашивает соль ТРЕМЯ
состояниями, а не двумя: фиксированная одна · фиксированные разные · **СВОБОДНАЯ**
(переменная не выставлена, интерпретатор солит сам). Сосед по §49 всегда ставит
``PYTHONHASHSEED`` явно, то есть отвечает про НАСТРОЙКУ, а живой дневной цикл её
не пришпиливает.

Что модуль НЕ делает
====================
Не двигает капитал, не правит политику и не трогает ни один гейт. **Только
называет.** Заказ G957 п. 1 говорит это прямо: «Политику и гейт НЕ ТРОГАТЬ».
Окно свежести, гейт ``_fundable`` и ``_EVIDENCE_MAX_AGE_H`` не меняются здесь ни
на символ: их правка — money-path и предмет №1 владельца.

ADVISORY (``applied=False``).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

# ── ВВЕЗЁННЫЕ СЛОВАРИ. Своя копия мерки означала бы «прибор отвечает о себе» ──
# §13 (ADR-956) — третий исход. Ровно то значение, которое получит читатель.
from spa_core.analytics.transaction_economics import UNMEASURED
# Честная форма чтения наблюдения — ЕДИНСТВЕННАЯ дверь (CLAUDE.md, инв. #17).
from spa_core.utils.observation import observed
# §49-сосед: ЕДИНСТВЕННАЯ дверь снятия штампов и объявление субъектов.
from spa_core.monitoring.decision_reproducibility import (
    SUBJECTS as REPRO_SUBJECTS,
    strip_clock,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/determinism_census.json"

#: Границы раздела §26 в карточке приказа. ОБЕ названы: перечень кончается
#: строкой ПЕРЕД заголовком следующего раздела, иначе в него попадает сам
#: заголовок (ловушка, на которой наивный счёт §25 дал 29 вместо 28).
SECTION_HEAD = "26. Determinism"
NEXT_SECTION_HEAD = "27. Pre-trade check"

#: Карточка приказа владельца — производитель всех трёх чисел ниже.
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

#: Якоря подразделов внутри §26. Это УТВЕРЖДЕНИЕ о форме раздела, и оно
#: проверяется разбором: не нашлось ⇒ ``unmeasured``, а не пустой список.
_INPUTS_LEAD = "При одинаковых:"
_RESULT_LINE = "Portfolio Optimizer должен выдавать одинаковый результат."
_PERMITTED_LEAD = "LLM может:"
_FORBIDDEN_LEAD = "LLM не должен определять:"

OWNER_INPUTS_DECLARED = 4
OWNER_PERMITTED_DECLARED = 3
OWNER_FORBIDDEN_DECLARED = 4

#: Четыре входа §26 ДОСЛОВНО. Порядок — как в карточке.
INPUTS_26: Tuple[str, ...] = (
    "market snapshot",
    "portfolio state",
    "risk policy",
    "configuration",
)

PERMITTED_26: Tuple[str, ...] = (
    "объяснять",
    "summarise",
    "формировать owner-facing recommendation",
)

FORBIDDEN_26: Tuple[str, ...] = (
    "арифметику",
    "allocation constraints",
    "финансовые расчеты",
    "policy pass/fail",
)

#: ПЯТЫЙ вход — находка оси C, а не пункт владельца. Назван отдельно именно
#: поэтому: подмешать его в :data:`INPUTS_26` значило бы приписать владельцу
#: слово, которого он не писал.
FIFTH_INPUT = "wall clock (now)"

#: Штампы прогона, ВЫЧТЕННЫЕ из предмета §26 явно (см. докстринг модуля).
RUN_IDENTITY_FIELDS: Tuple[str, ...] = ("timestamp", "generated_at")

# ── ось A: род пришпиливаемости ──────────────────────────────────────────────

#: Род ответа оси A. ``not_an_input`` — самостоятельное значение: вход, который
#: субъект не читает ВОВСЕ, не «пришпилен» и не «не пришпилен», и считать его
#: одним из двух значило бы соврать в обе стороны.
PIN_KINDS: Tuple[str, ...] = (
    "pinnable_named",        # у точки входа есть аргумент, и он СУЩЕСТВУЕТ
    "not_an_input",          # субъект этого входа не читает вовсе
    "unpinnable_import",     # связан на импорте (модульная константа/синглтон)
    "unpinnable_ambient",    # берётся у окружения (стенные часы, env)
    UNMEASURED,              # разобрать не вышло — причина названа
)

#: ОБЪЯВЛЕНИЕ, а не угадывание: для каждого субъекта и каждого входа §26 —
#: чем он пришпиливается у точки входа. Пустой кортеж = претензия
#: ``not_an_input``; она проверяется ОТДЕЛЬНО (:data:`NOT_AN_INPUT_PROOF`), иначе
#: «я не нашёл аргумента» было бы неотличимо от «субъект это не читает».
INPUT_MAP: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "allocator": {
        "market snapshot": ("status_path", "adapter_status_path",
                            "live_apy_provider"),
        "portfolio state": (),
        "risk policy": (),
        "configuration": ("allocation_model", "objective", "registry_path",
                          "strategies_dir", "comparison_path"),
    },
    "tuner": {
        "market snapshot": ("adapter_data", "data_dir"),
        "portfolio state": ("current_weights", "data_dir"),
        "risk policy": ("constraints",),
        "configuration": ("constraints", "data_dir"),
    },
}

#: Почему вход объявлен НЕ пришпиливаемым — с АДРЕСОМ, который проверяется.
#: Адрес есть у каждой претензии: «не нашёл» причиной не является.
UNPINNABLE_REASONS: Dict[Tuple[str, str], Tuple[str, str, str]] = {
    ("allocator", "portfolio state"): (
        "not_an_input",
        "spa_core/allocator/allocator.py",
        "слово «portfolio» встречается в модуле РОВНО один раз и в комментарии; "
        "книгу аллокатор не читает ни одним путём — он предлагает ЦЕЛЬ, а "
        "сравнение цели с книгой живёт у тюнера и у триггера ребаланса",
    ),
    ("allocator", "risk policy"): (
        "unpinnable_import",
        "spa_core/allocator/allocator.py:35-37 (_POLICY_CONFIG = _RiskConfig())",
        "пороги политики связываются на ИМПОРТЕ модуля в синглтон "
        "`_POLICY_CONFIG`; у точки входа аргумента для них нет, поэтому "
        "«одинаковая risk policy» обеспечивается одинаковым ДЕРЕВОМ, а не "
        "одинаковым вызовом",
    ),
}

#: Претензия ``not_an_input`` доказывается замером, а не отсутствием аргумента:
#: имя → (модуль, слова, которых в нём НЕ ДОЛЖНО быть вне комментариев).
NOT_AN_INPUT_PROOF: Dict[Tuple[str, str], Tuple[str, Tuple[str, ...]]] = {
    ("allocator", "portfolio state"): (
        "spa_core/allocator/allocator.py",
        # Слово ВЛАДЕЛЬЦА («portfolio») плюс три конкретных имени, которыми
        # книга зовётся в коде. Первое стои́т здесь не для красоты: в
        # аллокаторе оно встречается РОВНО в комментарии, поэтому именно оно
        # разводит честное свидетельство (AST без докстрок и комментариев) от
        # наивного `grep`, который опроверг бы ВЕРНУЮ претензию. Мутация,
        # подменяющая разбор на `grep`, убивается этим словом и только им
        # (замер #1087: без него мутация ВЫЖИВАЛА).
        ("portfolio", "current_positions", "current_weights", "book_usd"),
    ),
}

# ── ось D: кто отвечает за каждое запрещённое определение ────────────────────

#: Для каждого из ЧЕТЫРЁХ запрещённых §26 определений — чем он измерен сегодня.
#: Это карта ЧИТАТЕЛЕЙ, а не повторный замер: §15 (ADR-958) и §45 уже мерили
#: свои половины, и перемерить их здесь значило бы завести второй прибор на
#: один предмет (запрет заказа G957 п. 1 и общий порядок дома).
LLM_ANSWERED_BY: Dict[str, Tuple[str, str]] = {
    "арифметику": (
        "spa_core/analytics/objective_penalties.py",
        "§15 (ADR-958): «LLM не должен быть источником финансовой математики» — "
        "замер шести слагаемых целевой функции на живой двери",
    ),
    "allocation constraints": (
        "spa_core/analytics/risk_constraint_census.py",
        "§12/§14: ограничения раскладки объявлены данными и измерены отдельно",
    ),
    "финансовые расчеты": (
        "scripts/lint_llm_forbidden.py",
        "инвариант #3: ДВЕ двери — импорт SDK (run_lint) и запуск бинаря "
        "claude подпроцессом (run_launch_lint, ADR-958)",
    ),
    "policy pass/fail": (
        "spa_core/monitoring/cio_architecture_constraints.py",
        "§45: достижимость двери LLM с денежного пути + слепота сторожа "
        "инварианта #3 (обе двери спрошены с ADR-969)",
    ),
}


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _read_card(card_path: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Строки карточки приказа, либо названная причина «не прочитана»."""
    try:
        with open(card_path, encoding="utf-8") as fh:
            return fh.read().splitlines(), None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except UnicodeDecodeError as exc:  # pragma: no cover — защита от битых байт
        return None, f"UnicodeDecodeError: {exc}"


def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    """Строки РОВНО раздела §26: от его заголовка до заголовка §27.

    Обе границы названы. Нижняя граница — заголовок СЛЕДУЮЩЕГО раздела, и это
    не придирка: без неё в перечень попадает сам заголовок (ровно ловушка §25).
    """
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == SECTION_HEAD:
            start = i
            break
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == NEXT_SECTION_HEAD:
            return lines[start + 1:j], None
    return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                  f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, "
                  f"и счёт по нему был бы счётом неизвестно чего")


def _items_between(body: List[str], lead: str,
                   stops: Tuple[str, ...]) -> List[str]:
    """Непустые строки после ``lead`` до первой из ``stops``."""
    out: List[str] = []
    seen = False
    for ln in body:
        s = ln.strip()
        if not seen:
            if s == lead:
                seen = True
            continue
        if s in stops or s.startswith("⸻"):
            break
        if s:
            # Концевая пунктуация перечня (`;` у средних пунктов, `.` у
            # последнего) — разделитель, а не часть пункта. Снимается ОБА
            # рода: иначе паритет краснел бы на точке, и первый же прогон
            # ADR-969 именно на ней и покраснел.
            out.append(s.rstrip(";."))
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    """ПРОИЗВОДИТЕЛЬ трёх чисел §26 — разбор карточки приказа.

    Возвращает ``{"measured": bool, "reason": str|None, "inputs": [...],
    "permitted": [...], "forbidden": [...]}``. Нечитаемая карточка и
    ненайденная граница — ТРЕТИЙ ИСХОД с названной причиной, а не тихий
    возврат к константам: сверять константу с собой же нельзя.
    """
    lines, reason = _read_card(card_path)
    if lines is None:
        return {"measured": False, "reason": f"карточка не прочитана: {reason}"}
    body, reason = _section_lines(lines)
    if body is None:
        return {"measured": False, "reason": reason}

    inputs = _items_between(body, _INPUTS_LEAD, (_RESULT_LINE,))
    permitted = _items_between(body, _PERMITTED_LEAD, (_FORBIDDEN_LEAD,))
    forbidden = _items_between(body, _FORBIDDEN_LEAD, ())
    if not inputs or not permitted or not forbidden:
        return {"measured": False,
                "reason": ("в разделе §26 не найден один из якорей подразделов "
                           f"({_INPUTS_LEAD!r} / {_PERMITTED_LEAD!r} / "
                           f"{_FORBIDDEN_LEAD!r}) — форма раздела изменилась, "
                           "и счёт по ней был бы счётом неизвестно чего")}
    return {"measured": True, "reason": None, "inputs": inputs,
            "permitted": permitted, "forbidden": forbidden}


def parity(card_path: str) -> Dict[str, Any]:
    """Сверка КОНСТАНТ с РАЗБОРОМ карточки. Расхождение — находка."""
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": []}
    if not parsed.get("measured"):
        out["agrees"] = None
        return out
    pairs = (
        ("inputs", OWNER_INPUTS_DECLARED, INPUTS_26, parsed["inputs"]),
        ("permitted", OWNER_PERMITTED_DECLARED, PERMITTED_26, parsed["permitted"]),
        ("forbidden", OWNER_FORBIDDEN_DECLARED, FORBIDDEN_26, parsed["forbidden"]),
    )
    for name, declared_n, declared_items, found in pairs:
        if len(found) != declared_n:
            out["mismatches"].append(
                f"{name}: константа объявляет {declared_n}, карточка даёт "
                f"{len(found)} ({found})")
        elif list(declared_items) != list(found):
            out["mismatches"].append(
                f"{name}: число совпало ({declared_n}), а СОСТАВ нет — "
                f"константа {list(declared_items)}, карточка {found}")
    out["agrees"] = not out["mismatches"]
    return out


# ──────────────────── ось A: пришпиливаем ли мы четыре входа ─────────────────

def _entry_params(root: str) -> Tuple[Dict[str, set], Optional[str]]:
    """Имена аргументов точек входа ОБОИХ субъектов, спрошенные у кода.

    Спрашивается ЖИВАЯ подпись (``inspect.signature``), а не список в приборе:
    объявление :data:`INPUT_MAP` — претензия, и мерить её собственной копией
    значило бы отвечать о себе (ADR-913/ADR-919).
    """
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import inspect
        from spa_core.allocator.allocator import StrategyAllocator
        from spa_core.tuner.allocation_tuner import run_allocation_tuner
    except Exception as exc:  # noqa: BLE001
        return {}, f"субъекты не импортируются: {type(exc).__name__}: {exc}"
    alloc = set(inspect.signature(StrategyAllocator.__init__).parameters)
    alloc |= set(inspect.signature(StrategyAllocator.allocate).parameters)
    alloc -= {"self"}
    tuner = set(inspect.signature(run_allocation_tuner).parameters)
    return {"allocator": alloc, "tuner": tuner}, None


def _code_identifiers(path: str) -> Tuple[Optional[set], Optional[str]]:
    """Имена и строковые литералы КОДА модуля — без докстрок и комментариев.

    Комментарии в AST не попадают вовсе, докстроки отбрасываются явно. Это
    важно именно здесь: претензия ``not_an_input`` доказывается ОТСУТСТВИЕМ
    слова, а слово «portfolio» в аллокаторе живёт РОВНО в комментарии, и
    наивный ``grep`` опроверг бы верную претензию.
    """
    import ast
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    docs: set = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            body = getattr(n, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))
    out: set = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
              and id(n) not in docs):
            out.add(n.value)
    return out, None


def measure_pinnability(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось A: род каждого из ЧЕТЫРЁХ входов §26 у каждого субъекта.

    Отвечает на вопрос, без которого §26 не мерится вовсе: **способен ли
    вызывающий держать вход одинаковым?** «Одинаковый вход» — предпосылка
    владельца, и если её нельзя обеспечить у точки входа, то «одинаковый
    результат» нечем и проверить.
    """
    params, reason = _entry_params(root)
    out: Dict[str, Any] = {"measured": not reason, "reason": reason,
                           "subjects": {}}
    if reason:
        return out
    for subject, per_input in INPUT_MAP.items():
        rows: Dict[str, Any] = {}
        known = params.get(subject, set())
        for owner_input in INPUTS_26:
            declared = per_input.get(owner_input, ())
            if declared:
                missing = [p for p in declared if p not in known]
                if missing:
                    rows[owner_input] = {
                        "kind": UNMEASURED,
                        "reason": (f"объявленные аргументы {missing} у точки "
                                   f"входа НЕ НАЙДЕНЫ — объявление прибора "
                                   f"разошлось с подписью субъекта"),
                        "params": list(declared)}
                else:
                    rows[owner_input] = {"kind": "pinnable_named",
                                         "reason": None,
                                         "params": list(declared)}
                continue
            # Пустой кортеж — претензия «не пришпиливается». ПОЧЕМУ именно,
            # берётся из объявления, а не выводится из пустоты.
            claim = UNPINNABLE_REASONS.get((subject, owner_input))
            if claim is None:
                rows[owner_input] = {
                    "kind": UNMEASURED,
                    "reason": ("аргумента нет и причина НЕ ОБЪЯВЛЕНА — "
                               "«я не нашёл» причиной не является"),
                    "params": []}
                continue
            kind, address, why = claim
            row: Dict[str, Any] = {"kind": kind, "reason": why,
                                   "address": address, "params": []}
            # Адрес претензии проверяется: файла нет ⇒ третий исход.
            addr_file = address.split(":")[0]
            if not os.path.isfile(os.path.join(root, addr_file)):
                row["kind"] = UNMEASURED
                row["reason"] = (f"адрес претензии не существует в дереве: "
                                 f"{addr_file}")
                rows[owner_input] = row
                continue
            proof = NOT_AN_INPUT_PROOF.get((subject, owner_input))
            if proof is not None:
                mod_rel, forbidden_words = proof
                ids, why_not = _code_identifiers(os.path.join(root, mod_rel))
                if ids is None:
                    row["kind"] = UNMEASURED
                    row["reason"] = (f"модуль претензии не разобран "
                                     f"({mod_rel}): {why_not}")
                else:
                    hits = sorted(w for w in forbidden_words
                                  if any(w in i for i in ids))
                    row["proof"] = {"module": mod_rel,
                                    "words_absent_from_code": not hits,
                                    "hits": hits}
                    if hits:
                        row["kind"] = UNMEASURED
                        row["reason"] = (
                            f"претензия «не читает книгу» ОПРОВЕРГНУТА замером: "
                            f"в коде {mod_rel} найдены {hits}")
            rows[owner_input] = row
        out["subjects"][subject] = rows

    # Пятый вход спрашивается у ТЕХ ЖЕ подписей и отдельной строкой.
    fifth: Dict[str, Any] = {}
    for subject in INPUT_MAP:
        known = params.get(subject, set())
        fifth[subject] = {
            "kind": "pinnable_named" if "now" in known else "unpinnable_ambient",
            "reason": (None if "now" in known else
                       "у точки входа аргумента `now` НЕТ: вызывающий не может "
                       "держать пятый вход одинаковым, даже зная о нём"),
            "params": ["now"] if "now" in known else []}
    out["fifth_input"] = {"name": FIFTH_INPUT, "subjects": fifth}
    return out


# ───────────── ось C: пятый вход — дифференциально, байты не менялись ─────────

#: Сдвиги часов, на которых спрашивается набор годных протоколов. Ноль —
#: опорный; остальные растут через границу окна свежести (36 ч), и последний
#: заведомо далеко за ней. Числа — ВХОД прибора, не политика.
CLOCK_OFFSETS_H: Tuple[float, ...] = (0.0, 1.0, 12.0, 24.0, 36.0, 48.0, 168.0,
                                      8760.0)


def measure_fifth_input(data_dir: str,
                        offsets_h: Tuple[float, ...] = CLOCK_OFFSETS_H,
                        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Ось C: меняется ли набор годных протоколов от ОДНИХ ЧАСОВ.

    Байты входа НЕ копируются и НЕ правятся — читается один и тот же снимок,
    двигается РОВНО ``now``. Поэтому «вход одинаков» здесь не допущение, а
    свойство замера: другого входа у функции просто нет.

    Третий исход обязателен: снимок не прочитан / дверь инъекции исчезла ⇒
    ``unmeasured`` с названной причиной, а НЕ «наборы совпали». «Одинаково» на
    сцене, где ничего не считалось, — ровно тот ложный зелёный, против которого
    §26 и мерится (контрапункт (а) заказа G957 п. 1).
    """
    # `depends_on_clock` объявлен ЗДЕСЬ и равен None до замера: отсутствующий
    # ключ отдавал бы через `.get()` тот же None, что настоящее «не зависит»,
    # то есть «не измерено» было бы неотличимо от ответа (инв. #17). Найдено
    # собственным контролем `test_axis_c_missing_snapshot_is_unmeasured_…`.
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "offsets_h": list(offsets_h), "rows": [],
                           "changed_at_offsets": [], "never_aging": {},
                           "depends_on_clock": None}
    try:
        from pathlib import Path
        from spa_core.allocator import allocator as A
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"аллокатор не импортируется: {type(exc).__name__}: {exc}"
        return out
    for door in ("_load_evidenced_apy", "_load_evidenced_tvl",
                 "_EVIDENCE_MAX_AGE_H"):
        if not hasattr(A, door):
            out["reason"] = (f"дверь инъекции часов исчезла: у аллокатора нет "
                             f"`{door}` — ось C НЕ ИЗМЕРЕНА")
            return out
    orch = os.path.join(data_dir, "adapter_orchestrator_status.json")
    ast_p = os.path.join(data_dir, "adapter_status.json")
    for p in (orch, ast_p):
        if not os.path.isfile(p):
            out["reason"] = f"снимок не прочитан: нет файла {p}"
            return out

    base = now or dt.datetime.now(dt.timezone.utc)
    out["now_anchor"] = base.isoformat()
    out["max_age_h"] = float(getattr(A, "_EVIDENCE_MAX_AGE_H"))
    rows: List[Dict[str, Any]] = []
    for dh in offsets_h:
        ref = base + dt.timedelta(hours=dh)
        try:
            apy = A._load_evidenced_apy(Path(orch), Path(ast_p), now=ref)
            tvl = A._load_evidenced_tvl(Path(ast_p), now=ref)
        except Exception as exc:  # noqa: BLE001
            out["reason"] = (f"замер на сдвиге {dh}ч упал: "
                             f"{type(exc).__name__}: {exc}")
            return out
        by_source: Dict[str, int] = {}
        for _v, src in apy.values():
            by_source[str(src)] = by_source.get(str(src), 0) + 1
        rows.append({"offset_h": dh,
                     "apy_evidenced": sorted(apy),
                     "tvl_evidenced": sorted(tvl),
                     "apy_by_source": by_source})
    out["rows"] = rows
    out["measured"] = True

    ref0 = (rows[0]["apy_evidenced"], rows[0]["tvl_evidenced"])
    out["changed_at_offsets"] = [r["offset_h"] for r in rows
                                 if (r["apy_evidenced"], r["tvl_evidenced"]) != ref0]
    out["depends_on_clock"] = bool(out["changed_at_offsets"])
    # Источник, который НЕ СТАРЕЕТ: присутствует и на самом дальнем сдвиге.
    far = rows[-1]
    out["never_aging"] = {"offset_h": far["offset_h"],
                          "apy_by_source": far["apy_by_source"],
                          "apy_evidenced": far["apy_evidenced"]}
    out["counts"] = {"apy_at_zero": len(rows[0]["apy_evidenced"]),
                     "apy_at_far": len(far["apy_evidenced"]),
                     "tvl_at_zero": len(rows[0]["tvl_evidenced"]),
                     "tvl_at_far": len(far["tvl_evidenced"])}
    return out


# ───────── ось B: соль хеша ТРЕМЯ состояниями, в том числе СВОБОДНЫМ ─────────

#: Состояния соли. Третье — СВОБОДНОЕ: переменная не выставлена вовсе, и
#: интерпретатор солит сам. Сосед по §49 всегда ставит её явно, то есть
#: отвечает про НАСТРОЙКУ; живой дневной цикл её не пришпиливает (требование
#: (б) заказа G957 п. 1).
SEED_STATES: Tuple[Tuple[str, Optional[str]], ...] = (
    ("fixed_0", "0"),
    ("fixed_1", "1"),
    ("free", None),
    ("free_again", None),
)

#: 🪤 СВИДЕТЕЛЬ НЕПУСТОТЫ СЦЕНЫ — обязателен (контрапункт (а) заказа G957 п. 1).
#: Детерминизм есть свойство ПАРЫ «вход → выход», и «ответы совпали» верно
#: СЛУЧАЙНО на сцене, где оптимизатор ничего не считал: четыре пустых ответа
#: тоже дают один хеш. Поэтому у сцены спрашивается, РАНЖИРОВАЛ ли субъект
#: хоть что-нибудь, и пустая сцена — ТРЕТИЙ ИСХОД, а не «одинаково».
#: Поле → предикат, объявлены вместе с причиной, почему именно это поле.
SCENE_WITNESS: Tuple[Tuple[str, str], ...] = (
    ("apy_used", "ставка, по которой субъект РАНЖИРОВАЛ: пустое отображение "
                 "значит, что ранжировать было нечем"),
    ("allocated_pct", "доля размещённого капитала: ноль значит, что раскладки "
                      "субъект не построил"),
)


def _scene_is_vacuous(doc: Dict[str, Any]) -> Optional[str]:
    """``None`` — сцена непуста; иначе названная причина пустоты.

    Отсутствие самого поля-свидетеля — тоже пустота, и это НЕ придирка: поле
    могло переехать, и тогда прибор обязан сказать «не измерено», а не выдать
    совпадение четырёх ответов, которых никто не считал.
    """
    for field, why in SCENE_WITNESS:
        if field not in doc:
            return (f"в ответе субъекта нет поля-свидетеля `{field}` ({why}) — "
                    f"непустота сцены НЕ ПОДТВЕРЖДЕНА")
        value = doc[field]
        if isinstance(value, dict) and not value:
            return f"`{field}` пусто ({why})"
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and float(value) == 0.0:
            return f"`{field}` равно нулю ({why})"
    return None


def _run_subject(code: str, sandbox: str, root: str, seed: Optional[str],
                 timeout: float) -> Tuple[int, str, str]:
    """Один прогон субъекта в ОТДЕЛЬНОМ процессе на пришпиленной песочнице.

    ``seed is None`` — соль НЕ выставляется (свободное состояние). Остальное
    окружение повторяет соседа по §49 дословно, включая ``SPA_LIVE_ROOT`` в
    песочницу: иначе ``live_root()`` субъекта увёл бы прогон в прод-дерево.
    """
    env = dict(os.environ)
    if seed is None:
        env.pop("PYTHONHASHSEED", None)
    else:
        env["PYTHONHASHSEED"] = seed
    env["SPA_DATA_DIR"] = sandbox
    env["SPA_SANDBOX"] = "1"
    env["SPA_LIVE_ROOT"] = sandbox
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def measure_seed_door(data_dir: str, root: str = REPO_ROOT,
                      subject_key: str = "allocator",
                      timeout: float = 180.0) -> Dict[str, Any]:
    """Ось B: та же сцена при РАЗНЫХ состояниях соли хеша.

    Субъект ВВЕЗЁН из :data:`REPRO_SUBJECTS` — своего кода сцены у этого
    прибора нет намеренно: две копии сцены разошлись бы, и тогда «тот же
    ответ» утверждалось бы про разные вопросы.

    Штампы прогона снимаются ЕДИНСТВЕННОЙ дверью :func:`strip_clock` по
    объявлению :data:`RUN_IDENTITY_FIELDS` — §26 про РЕЗУЛЬТАТ, а не про
    отметку (вычитание названо явно, требование (г) заказа).

    Третий исход: песочница не собрана / прогон не завершился / разбор ответа
    не вышел ⇒ ``unmeasured`` с причиной. «Сцену построить нечем» НИКОГДА не
    выдаётся за «ответы совпали».
    """
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "subject": subject_key, "runs": [],
                           "distinct_outputs": None,
                           "stamps_removed": [], "states": [s for s, _ in SEED_STATES]}
    subject = next((s for s in REPRO_SUBJECTS if s.key == subject_key), None)
    if subject is None:
        out["reason"] = (f"субъект {subject_key!r} не объявлен у соседа по §49 — "
                         f"сцену строить нечем")
        return out
    try:
        from spa_core.monitoring.decision_reproducibility import _build_sandbox
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"песочница соседа недоступна: {type(exc).__name__}: {exc}"
        return out

    tmp = tempfile.mkdtemp(prefix="spa_det26_")
    try:
        canon: List[str] = []
        for state, seed in SEED_STATES:
            sandbox = os.path.join(tmp, state)
            try:
                n_files = _build_sandbox(data_dir, sandbox)
            except OSError as exc:
                out["reason"] = f"песочница не собрана ({state}): {exc}"
                return out
            if not n_files:
                out["reason"] = (f"снимок пуст: в {data_dir} нет ни одного "
                                 f"верхнеуровневого *.json — сравнивать нечего")
                return out
            try:
                rc, stdout, stderr = _run_subject(subject.code, sandbox, root,
                                                  seed, timeout)
            except subprocess.TimeoutExpired:
                out["reason"] = f"прогон {state} не завершился за {timeout}с"
                return out
            if rc != 0:
                out["reason"] = (f"прогон {state} вышел кодом {rc}: "
                                 f"{(stderr or '').strip()[-300:]}")
                return out
            try:
                doc = json.loads(stdout)
            except json.JSONDecodeError as exc:
                out["reason"] = f"ответ {state} не разобран: {exc}"
                return out
            if not isinstance(doc, dict):
                out["reason"] = (f"ответ {state} не отображение "
                                 f"({type(doc).__name__}) — сравнивать нечего")
                return out
            vacuous = _scene_is_vacuous(doc)
            if vacuous is not None:
                out["reason"] = (
                    f"сцену построить нечем ({state}): {vacuous}. «Ответы "
                    f"совпали» на такой сцене верно СЛУЧАЙНО — пустые ответы "
                    f"тоже совпадают, поэтому вердикт НЕ ВЫДАЁТСЯ")
                out["scene_vacuous"] = True
                return out
            stripped, removed = strip_clock(doc, RUN_IDENTITY_FIELDS)
            canon.append(json.dumps(stripped, sort_keys=True,
                                    ensure_ascii=False, default=str))
            out["runs"].append({"state": state,
                                "seed": seed,
                                "stamps_removed": sorted(removed)})
            out["stamps_removed"] = sorted(set(out["stamps_removed"])
                                           | set(removed))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    out["measured"] = True
    out["scene_vacuous"] = False
    out["witness_fields"] = [f for f, _ in SCENE_WITNESS]
    out["distinct_outputs"] = len(set(canon))
    out["same_under_every_seed_state"] = out["distinct_outputs"] == 1
    if out["distinct_outputs"] > 1:
        groups: Dict[str, List[str]] = {}
        for (state, _s), c in zip(SEED_STATES, canon):
            groups.setdefault(c, []).append(state)
        out["groups"] = [sorted(v) for v in groups.values()]
    return out


# ──────────────── ось D: вторая половина §26 — роль LLM ──────────────────────

def measure_llm_half(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось D: четыре ЗАПРЕЩЁННЫХ §26 определения — чем измерено каждое.

    Это карта ЧИТАТЕЛЕЙ, а не второй замер: §15 (ADR-958) и §45 уже мерят свои
    половины, и завести здесь третий прибор на тот же предмет значило бы
    получить два ответа на один вопрос без правила, какой из них верен.

    Замеряется ОДНО своё: жив ли адрес каждого ответчика в дереве, и что
    сегодня говорит сторож инварианта #3 про ОБЕ свои двери (с ADR-969 проба
    §45 спрашивает их обе; до него она звала только ``run_lint`` и отвечала о
    стороже ответом ОДНОЙ его двери).
    """
    out: Dict[str, Any] = {"measured": True, "reason": None, "forbidden": {},
                           "permitted": list(PERMITTED_26), "guard": None}
    for item in FORBIDDEN_26:
        answered = LLM_ANSWERED_BY.get(item)
        if answered is None:
            out["forbidden"][item] = {"kind": UNMEASURED,
                                      "reason": "ответчик НЕ ОБЪЯВЛЕН"}
            continue
        address, why = answered
        exists = os.path.isfile(os.path.join(root, address))
        out["forbidden"][item] = {
            "kind": "answered_elsewhere" if exists else UNMEASURED,
            "address": address,
            "reason": why if exists else
                      f"объявленный ответчик отсутствует в дереве: {address}"}
    try:
        from spa_core.monitoring.cio_architecture_constraints import lint_blindness
        out["guard"] = lint_blindness(root)
    except Exception as exc:  # noqa: BLE001
        out["guard"] = {"measured": False,
                        "reason": f"{type(exc).__name__}: {exc}"}
    return out


# ───────────────────────────── сборка отчёта ─────────────────────────────────

def _findings(parity_r: Dict[str, Any], pin: Dict[str, Any],
              seed: Dict[str, Any], fifth: Dict[str, Any],
              llm: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[str]]:
    """Находки и список «НЕ ИЗМЕРЕНО». Третий исход НИКОГДА не находка."""
    findings: List[Dict[str, str]] = []
    unmeasured: List[str] = []

    if parity_r.get("agrees") is None:
        unmeasured.append("паритет с карточкой: "
                          + str(parity_r["parsed"].get("reason")))
    elif not parity_r["agrees"]:
        findings.append({"severity": "CRITICAL", "code": "owner_text_drifted",
                         "message": ("разбор карточки разошёлся с константами "
                                     "прибора: " + "; ".join(parity_r["mismatches"]))})

    if not pin.get("measured"):
        unmeasured.append(f"ось A (пришпиливаемость): {pin.get('reason')}")
    else:
        for subject, rows in pin["subjects"].items():
            for owner_input, row in rows.items():
                if row["kind"] == UNMEASURED:
                    unmeasured.append(
                        f"ось A {subject}/{owner_input}: {row.get('reason')}")
        # Вход, который НЕ ЧИТАЕТ ни один субъект, — находка о §26, а не о коде.
        for owner_input in INPUTS_26:
            kinds = {s: pin["subjects"][s][owner_input]["kind"]
                     for s in pin["subjects"]}
            if all(k == "not_an_input" for k in kinds.values()):
                findings.append({
                    "severity": "WARN", "code": "owner_input_read_by_nobody",
                    "message": (f"вход §26 «{owner_input}» не читает НИ ОДИН "
                                f"субъект — «при одинаковых» про него "
                                f"бессодержательно")})
        fifth_pin = pin.get("fifth_input", {}).get("subjects", {})
        ambient = sorted(s for s, r in fifth_pin.items()
                         if r["kind"] == "unpinnable_ambient")
        if ambient:
            findings.append({
                "severity": "WARN", "code": "fifth_input_unpinnable",
                "message": (f"пятый вход «{FIFTH_INPUT}» не пришпиливается у "
                            f"точки входа субъект(а/ов) {', '.join(ambient)}: "
                            f"аргумента `now` нет, значит обеспечить предпосылку "
                            f"§26 «при одинаковых» вызывающий НЕ МОЖЕТ")})

    if not fifth.get("measured"):
        unmeasured.append(f"ось C (пятый вход): {fifth.get('reason')}")
    elif fifth.get("depends_on_clock"):
        c = fifth["counts"]
        findings.append({
            "severity": "CRITICAL", "code": "result_depends_on_the_clock",
            "message": (
                f"при ОДИНАКОВЫХ четырёх входах §26 (байты снимка не менялись "
                f"ни на один) набор годных протоколов МЕНЯЕТСЯ от одних часов: "
                f"APY-evidenced {c['apy_at_zero']} → {c['apy_at_far']}, "
                f"TVL-evidenced {c['tvl_at_zero']} → {c['tvl_at_far']}; "
                f"сменилось на сдвигах {fifth['changed_at_offsets']} ч при окне "
                f"свежести {fifth['max_age_h']} ч. Это НЕ случайность расчёта — "
                f"это ПЯТЫЙ вход, не названный в §26")})
        # 🪤 `or {}` здесь был НОВЫМ членом класса «отсутствие наблюдения =
        # благополучие» (инв. #17), и поймал его собственный храповик
        # `test_absent_observation_ratchet` на первом же прогоне: подстановка
        # пустого словаря делала «не измерено» неотличимым от «источников,
        # которые не стареют, НЕТ», и находка молча не печаталась бы.
        # Честная форма короче подстановки: три исхода различимы.
        far_block = observed(fifth, "never_aging", kind=dict)
        far_src = (observed(far_block, "apy_by_source", kind=dict)
                   if far_block is not None else None)
        if far_src is None:
            unmeasured.append(
                "ось C: состав источников на дальнем сдвиге НЕ ИЗМЕРЕН "
                "(`never_aging.apy_by_source` отсутствует либо не отображение) "
                "— о нестареющем источнике не сказано НИЧЕГО, и это не ноль")
        elif far_src:
            findings.append({
                "severity": "CRITICAL", "code": "evidence_that_never_ages",
                "message": (
                    f"источник доказательности, который НЕ СТАРЕЕТ ВОВСЕ: на "
                    f"сдвиге {fifth['never_aging']['offset_h']} ч годными "
                    f"остаются {sum(far_src.values())} протокол(а/ов) "
                    f"{far_src} — ветка снимка оркестратора в "
                    f"`_load_evidenced_apy` окна свежести не применяет, поэтому "
                    f"гейт `_fundable` на них НИКОГДА не скажет `unevidenced`. "
                    f"Утверждение CLAUDE.md «stale-фид → unevidenced» верно про "
                    f"ВТОРОЙ источник (adapter_status) и НЕ верно про этот")})

    if not seed.get("measured"):
        unmeasured.append(f"ось B (соль хеша): {seed.get('reason')}")
    elif not seed.get("same_under_every_seed_state"):
        findings.append({
            "severity": "CRITICAL", "code": "result_depends_on_hash_seed",
            "message": (f"та же сцена дала {seed['distinct_outputs']} РАЗНЫХ "
                        f"ответа при разных состояниях соли хеша; группы: "
                        f"{seed.get('groups')}")})

    guard = (llm.get("guard") or {})
    if not guard.get("measured"):
        unmeasured.append(f"ось D (сторож инв. #3): {guard.get('reason')}")
    elif guard.get("blind_to_subprocess") is None:
        unmeasured.append("ось D: слепота сторожа инв. #3 НЕ ИЗМЕРЕНА — "
                          + str(guard.get("blind_unmeasured_reason")))
    elif guard.get("blind_to_subprocess"):
        findings.append({
            "severity": "CRITICAL", "code": "guard_blind_to_real_door",
            "message": ("сторож инварианта #3 не ловит дверь-subprocess НИ "
                        "ОДНОЙ из своих двух дверей — запрет §26 «LLM не "
                        "должен определять policy pass/fail» держится не "
                        "сторожем")})
    for item, row in llm.get("forbidden", {}).items():
        if row["kind"] == UNMEASURED:
            unmeasured.append(f"ось D «{item}»: {row.get('reason')}")
    return findings, unmeasured


def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        with_seed_axis: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §26. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    pin = measure_pinnability(root)
    fifth = measure_fifth_input(data_dir, now=now)
    llm = measure_llm_half(root)
    if with_seed_axis:
        seed = measure_seed_door(data_dir, root)
    else:
        seed = {"measured": False,
                "reason": "ось B не запрашивалась (--no-seed-axis)"}

    findings, unmeasured = _findings(parity_r, pin, seed, fifth, llm)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "determinism_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §26 ТЗ «Portfolio CIO» "
                     "(Determinism). Политику, гейт `_fundable`, окно "
                     "свежести и живой трек НЕ трогает — только читает"),
        "overall": overall,
        "counts": counts,
        "declared": {"inputs": list(INPUTS_26),
                     "inputs_n": OWNER_INPUTS_DECLARED,
                     "permitted": list(PERMITTED_26),
                     "permitted_n": OWNER_PERMITTED_DECLARED,
                     "forbidden": list(FORBIDDEN_26),
                     "forbidden_n": OWNER_FORBIDDEN_DECLARED,
                     "fifth_input": FIFTH_INPUT,
                     "run_identity_fields": list(RUN_IDENTITY_FIELDS)},
        "parity": parity_r,
        "axis_a_pinnability": pin,
        "axis_b_seed_door": seed,
        "axis_c_fifth_input": fifth,
        "axis_d_llm_half": llm,
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # (data, path) — не наоборот. До #1088 аргументы стояли переставленными,
        # и `run(write=True)` (умолчание CLI) падал ValueError в самом конце:
        # артефакт §26 не был записан ни разу, а батарея проверяла только
        # `write=False`. Найдено прибором §27 на том же вызове.
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    print(f"§26 ТЗ «Portfolio CIO» (Determinism): {doc['overall']} "
          f"(critical={doc['counts']['critical']} "
          f"warn={doc['counts']['warn']} "
          f"не измерено={doc['counts']['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ "
              f"(входов {OWNER_INPUTS_DECLARED}, разрешено "
              f"{OWNER_PERMITTED_DECLARED}, запрещено {OWNER_FORBIDDEN_DECLARED})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    pin = doc["axis_a_pinnability"]
    if pin.get("measured"):
        for subject, rows in pin["subjects"].items():
            kinds = ", ".join(f"{k}={v['kind']}" for k, v in rows.items())
            print(f"   [ось A] {subject}: {kinds}")
        for subject, row in pin["fifth_input"]["subjects"].items():
            print(f"   [ось A] {subject}: пятый вход ({FIFTH_INPUT}) "
                  f"= {row['kind']}")
    c = doc["axis_c_fifth_input"]
    if c.get("measured"):
        cc = c["counts"]
        print(f"   [ось C] окно свежести {c['max_age_h']}ч · APY-evidenced "
              f"{cc['apy_at_zero']}→{cc['apy_at_far']} · TVL-evidenced "
              f"{cc['tvl_at_zero']}→{cc['tvl_at_far']} · сменилось на "
              f"{c['changed_at_offsets']}ч")
    else:
        print(f"   [ось C] НЕ ИЗМЕРЕНО: {c.get('reason')}")
    b = doc["axis_b_seed_door"]
    if b.get("measured"):
        print(f"   [ось B] состояний соли {len(b['states'])}, разных ответов "
              f"{b['distinct_outputs']} (штампы снятые: {b['stamps_removed']}; "
              f"сцена НЕПУСТА по свидетелям {b.get('witness_fields')})")
    else:
        print(f"   [ось B] НЕ ИЗМЕРЕНО: {b.get('reason')}")
    g = (doc["axis_d_llm_half"].get("guard") or {})
    print(f"   [ось D] запрещённых определений {OWNER_FORBIDDEN_DECLARED}, "
          f"слепота сторожа инв. #3 = {g.get('blind_to_subprocess')}")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['code']}: {f['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§26 ТЗ «Portfolio CIO»: Determinism — замер пары вход→выход")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по "
                         "построению — передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--no-seed-axis", action="store_true",
                    help="не поднимать подпроцессы оси B (быстрый прогон)")
    ns = ap.parse_args(argv)
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card,
              write=not ns.no_write, with_seed_axis=not ns.no_seed_axis)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
