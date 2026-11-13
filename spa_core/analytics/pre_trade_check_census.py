"""pre_trade_check_census.py — §27 ТЗ «Portfolio CIO»: Pre-trade check.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §27 «Pre-trade check»::

    Между recommendation и execution обязательно выполнить повторную проверку.
    Проверить:
    fresh APY
    fresh gas
    fresh liquidity
    fresh slippage
    withdraw simulation
    deposit simulation
    position impact
    policy
    expected economics
    Если opportunity исчезла:
    CANCEL / DEFER
    а не исполнять устаревшее решение.

🪤 ЧИСЛО ПРОВЕРОК СНЯТО ПРИБОРОМ, И ЗАКАЗ ОШИБСЯ ВТРОЕ
======================================================
Заказ G958 п. 1 считал «по первым строкам» и назвал ТРИ проверки (`fresh APY` ·
`fresh gas` · `fresh liquidity`), честно оговорив, что хвост раздела не читал.
Разбор карточки даёт **ДЕВЯТЬ** (:data:`OWNER_CHECKS_DECLARED`) и ДВА исхода
(:data:`OWNER_OUTCOMES_DECLARED`: ``CANCEL`` / ``DEFER``). Обе границы раздела
названы константами (:data:`SECTION_HEAD`, :data:`NEXT_SECTION_HEAD`), и каждое
число живёт ДВАЖДЫ — константой и разбором карточки (:func:`owner_section_from_card`);
расхождение краснеет тестом, нечитаемая карточка — ТРЕТИЙ исход, а не возврат к
константе (урок ADR-913/ADR-919). Число заказа хранится рядом
(:data:`ORDER_G958_NAMED`), чтобы «заказ недосчитал» было ИЗМЕРЕНО отчётом, а не
замечено один раз и забыто (та же форма, что ``ORDER_G955_NAMED`` в §24).

Второго прибора на один предмет НЕ заводится
============================================
У §27 УЖЕ есть прибор: :mod:`spa_core.monitoring.pre_trade_recheck_census`
(ADR-487, цикл #708) меряет ПРИЗНАК повторной проверки ИСХОДОМ — было ли у
исполненного хода ВТОРОЕ наблюдение входов (ярлык наблюдения ``snapshot_id``
исполнения отличается от ярлыка предложения). Его вердикт здесь **ВВОЗИТСЯ**
(ось B), а не перемеряется: две копии одного замера разошлись бы, и «тот же
ответ» утверждалось бы про разные вопросы — тот же порядок, которым §26 ввозил
§49 ``decision_reproducibility``.

Тот же прибор САМ объявляет, чего НЕ докладывает: «покрытие каждого из девяти
предметов §27 по отдельности» — и объясняет почему: делить ОДИН ноль второго
наблюдения по девяти графам значило бы выдать разбор за замер. Этот модуль
добавляет ровно те оси, которых у соседа нет, и ни одной из его.

Оси
===
* **A — род второго события.** §27 — про ВРЕМЯ МЕЖДУ двумя событиями, поэтому
  ось «есть ли проверка» отвечает мимо: сначала надо измерить, существует ли
  вообще момент, в котором проверка могла бы стоять. Реального (он-чейн)
  исполнения у системы НЕТ ПО ПОСТРОЕНИЮ — инвариант #6 запрещает бумажному коду
  импортировать ``spa_core/execution/``, и ось МЕРИТ это по AST денежного пути,
  а не утверждает. Бумажное исполнение ЕСТЬ: событие ``trade_executed`` пишется
  тем же процессом, что и предложение, через доли секунды. Третий исход
  «второго события не существует» — находка о СТАДИИ, а не о пропущенной проверке
  (та же оговорка стои́т в §44 — `[НЕ ИЗМЕРЕНО] simulation failure`).
* **B — признак повторной проверки** (ввоз ADR-487): статус, число исполнений
  без второго наблюдения, окно в секундах, судима ли свежесть.
* **C — наблюдатель КАЖДОЙ из девяти проверок на денежном пути.** «Fresh X»
  требует, чтобы X вообще наблюдалось хотя бы ОДНАЖДЫ; у величины, которая
  входит на денежный путь константой дерева, свежести нет по построению, а у
  величины без единого наблюдателя нечего и перепроверять. Род объявлен
  (:data:`OBSERVER_MAP`) и ПРОВЕРЕН по коду (идентификаторы без комментариев и
  докстрок, единственная дверь ``_code_identifiers`` из §26): претензия о
  присутствии требует, чтобы названные имена БЫЛИ в названном модуле; претензия
  об отсутствии — чтобы ни одного слова-свидетеля НЕ было в коде поверхности
  зовущих. Поверхность денежного пути ВВОЗИТСЯ (``MONEY_PATH_PREFIXES`` сторожа
  дрейфа) и расширена ПОИМЁННО теми шагами цикла, которые ``cycle_runner``
  ввозит лениво внутри шага; каждое расширение проверяется по его импортам.
* **D — «fresh» есть функция `now`.** Это ТОТ ЖЕ предмет, что пятый вход
  ADR-969: свежесть спрашивается ДВАЖДЫ (на рекомендации и на исполнении), то
  есть §27 по построению требует, чтобы ``now`` был ВХОДОМ у обоих событий. Ось
  ВВОЗИТ ответ §26 о субъектах и добавляет одну дверь, которой там не было —
  вход цикла ``run_cycle``: у него ``now`` ЕСТЬ, но до гейта годности он не
  доезжает (G958 п. 4 назвал это и не измерил; здесь измерено подписью).
* **E — словарь исхода.** §27 называет ``CANCEL`` и ``DEFER``; словарь §24
  (``OWNER_DECISION_TYPES``) знает ``DEFER`` и НЕ знает ``CANCEL`` — два раздела
  одного ТЗ расходятся словарём, и это находка о ТЕКСТЕ владельца, не о коде.
  Присутствие ``DEFER`` на дверях решения ВВОЗИТСЯ из §24; ``CANCEL`` меряется
  по тем же дверям ТОЙ ЖЕ дверью кода.

🪤 ПРЕДПОСЫЛКА ЗАКАЗА ПРОВЕРЕНА ДО ТОГО, КАК ПЕЧАТАТЬ НОЛЬ
=========================================================
G958 п. 1 (в): «`fresh gas` не имеет в дереве ни одного наблюдателя на денежном
пути — проверить, прежде чем печатать ноль». Проверено, и предпосылка
ОПРОВЕРГНУТА: ``cycle_gates.py`` (Step 2d, ADR-025) читает ЖИВОЙ gwei Base через
``BaseGasMonitor._fetch_gas_gwei`` (``urllib`` к RPC) — наблюдатель есть, но он
один, про одну сеть и как стоп-кран; в МОДЕЛЬ СТОИМОСТИ хода газ входит константой
``GAS_USD_PER_POSITION_CHANGE``. Поэтому у `gas` ДВА рода сразу, и прибор печатает
оба, а не выбирает удобный.

Что модуль НЕ делает
====================
Не двигает капитал, не правит политику, гейт, окно свежести и ни одну проверку.
Не чинит `pre_trade_recheck_census` и не меняет его схему. **Только называет.**
ADVISORY (``applied=False``).
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── ВВЕЗЁННЫЕ СЛОВАРИ И ДВЕРИ. Своя копия мерки = «прибор отвечает о себе» ────
# §13 (ADR-956) — третий исход.
from spa_core.analytics.transaction_economics import UNMEASURED
# §26 (ADR-969): единственная дверь к идентификаторам кода и ось пятого входа.
from spa_core.analytics.determinism_census import (
    FIFTH_INPUT,
    PIN_KINDS,
    _code_identifiers,
    measure_pinnability,
)
# §24 (ADR-967): словарь типов решения владельца и ЖИВАЯ перепись дверей.
from spa_core.analytics import decision_type_census as _s24
# §49 / ADR-487: признак повторной проверки — ввозится ВЕРДИКТ, не перемер.
from spa_core.monitoring import pre_trade_recheck_census as _s49
# Сторож дрейфа: ОБЪЯВЛЕННАЯ поверхность денежного пути.
from spa_core.monitoring.deployment_drift_monitor import MONEY_PATH_PREFIXES
# Честная форма чтения наблюдения (инв. #17).
from spa_core.utils.observation import observed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/pre_trade_check_census.json"

#: Границы раздела §27 в карточке приказа. ОБЕ названы (ловушка §25: без второй
#: границы в перечень попадает сам заголовок следующего раздела).
SECTION_HEAD = "27. Pre-trade check"
NEXT_SECTION_HEAD = "28. Decision expiry"

#: Карточка приказа владельца — производитель чисел ниже.
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

#: Якоря подразделов §27 — УТВЕРЖДЕНИЕ о форме, проверяемое разбором.
_REQUIREMENT_LINE = ("Между recommendation и execution обязательно выполнить "
                     "повторную проверку.")
_CHECKS_LEAD = "Проверить:"
_OUTCOMES_LEAD = "Если opportunity исчезла:"
_PROHIBITION_LINE = "а не исполнять устаревшее решение."

OWNER_CHECKS_DECLARED = 9
OWNER_OUTCOMES_DECLARED = 2
#: Сколько проверок назвал заказ G958 п. 1 («по первым строкам»). Хранится,
#: чтобы недосчёт заказа был ИЗМЕРЕН отчётом (форма §24 `ORDER_G955_NAMED`).
ORDER_G958_NAMED = 3

#: Девять проверок §27 ДОСЛОВНО, в порядке карточки.
CHECKS_27: Tuple[str, ...] = (
    "fresh APY",
    "fresh gas",
    "fresh liquidity",
    "fresh slippage",
    "withdraw simulation",
    "deposit simulation",
    "position impact",
    "policy",
    "expected economics",
)

#: Два исхода §27 при исчезновении opportunity, дословно.
OUTCOMES_27: Tuple[str, ...] = ("CANCEL", "DEFER")

# ── ось A: род второго события ───────────────────────────────────────────────

#: Роды второго события («execution» §27). ``none`` — самостоятельное значение:
#: события, которого нет, не «проверенное» и не «непроверенное».
SECOND_EVENT_KINDS: Tuple[str, ...] = (
    "present",      # событие записывается на этом дереве
    "none",         # события нет ПО ПОСТРОЕНИЮ (измерено, не предположено)
    UNMEASURED,
)

#: Пакет реального исполнения; импорт его с денежного пути запрещён инв. #6.
EXECUTION_PACKAGE = "spa_core.execution"

# ── ось C: наблюдатель каждой проверки ───────────────────────────────────────

#: Как величина проверки §27 ВХОДИТ на денежный путь сегодня.
OBSERVER_KINDS: Tuple[str, ...] = (
    "live_observation",     # читается у живого источника каждый цикл
    "computed_on_path",     # вычисляется из входов на самом пути
    "proxy_observation",    # наблюдается ЗАМЕСТИТЕЛЬ, а не величина владельца
    "tree_constant",        # входит константой дерева — свежести нет по построению
    "door_without_caller",  # метод есть (в адаптерах), зовущего на пути нет
    "absent",               # ни одного слова-свидетеля в коде поверхности
    UNMEASURED,
)

#: Роды, у которых «fresh» ИМЕЕТ смысл: есть что перенаблюдать.
FRESHNESS_CAPABLE: Tuple[str, ...] = ("live_observation", "computed_on_path",
                                      "proxy_observation")

#: Поверхность зовущих — модули, где стоя́т ШАГИ цикла и его гейты. Претензия
#: ``door_without_caller``/``absent`` доказывается ОТСУТСТВИЕМ слова именно здесь.
#: Поверхность ВВЕЗЕНА (сторож дрейфа) и расширена ПОИМЁННО; каждое расширение
#: проверяется по импортам ``cycle_runner`` (:func:`measure_surface`).
MONEY_PATH_EXTENSION: Tuple[Tuple[str, str], ...] = (
    ("spa_core/paper_trading/allocation_rationale.py",
     "ADR-060 тень: экономика хода считается здесь каждый цикл"),
    ("spa_core/paper_trading/admissible_trim.py",
     "ADR-850: урезание хода до допустимого размера — шаг цикла"),
    ("spa_core/monitoring/base_gas_monitor.py",
     "ADR-025: единственный живой наблюдатель газа, его зовёт cycle_gates"),
)

#: ОБЪЯВЛЕНИЕ, проверяемое кодом: для каждой проверки §27 — род, модули и
#: идентификаторы, которые ОБЯЗАНЫ существовать в коде названного модуля
#: (не в комментарии и не в докстроке), и причина. Для `absent`/
#: `door_without_caller` вторая половина — слова-свидетели, которых НЕ ДОЛЖНО
#: быть в коде поверхности зовущих (:data:`CALLER_SURFACE`).
OBSERVER_MAP: Dict[str, Dict[str, Any]] = {
    "fresh APY": {
        "kind": "live_observation",
        "evidence": {
            "spa_core/allocator/allocator.py": ("live_apy", "_apy_sources"),
            "spa_core/risk/policy.py": ("current_apy",),
        },
        "why": "ставка читается у живого фида каждый цикл; у неё есть `as_of`",
    },
    "fresh gas": {
        "kind": "live_observation",
        "evidence": {
            "spa_core/paper_trading/cycle_gates.py": ("_gas_status", "gwei"),
            "spa_core/monitoring/base_gas_monitor.py": ("_fetch_gas_gwei",),
        },
        "also": {
            "kind": "tree_constant",
            "evidence": {"spa_core/allocator/rebalance_economics.py":
                         ("GAS_USD_PER_POSITION_CHANGE",)},
        },
        "why": ("ЖИВОЙ gwei читается ТОЛЬКО для Base и ТОЛЬКО как стоп-кран "
                "(Step 2d, ADR-025); в модель СТОИМОСТИ хода газ входит "
                "константой — предпосылка заказа G958 «наблюдателя нет» "
                "опровергнута, но наблюдатель один и не про цену хода"),
    },
    "fresh liquidity": {
        "kind": "proxy_observation",
        "evidence": {
            "spa_core/allocator/allocator.py": ("_load_evidenced_tvl",
                                                "_filter_by_tvl"),
            "spa_core/risk/policy.py": ("min_tvl_usd", "tvl_map"),
        },
        "why": ("наблюдается TVL как заместитель; сам аллокатор пишет об этом "
                "словами «допущение ранжирования, не наблюдение ликвидности»; "
                "глубина выхода (`liquidity_depth_analyzer`) на пути не стоит"),
    },
    "fresh slippage": {
        "kind": "tree_constant",
        "evidence": {"spa_core/allocator/rebalance_economics.py":
                     ("SLIPPAGE_BPS_STABLE",)},
        "why": "проскальзывание — константа дерева; свежести у константы нет",
    },
    "withdraw simulation": {
        "kind": "door_without_caller",
        "evidence": {"spa_core/adapters/aave_v3_optimism_adapter.py":
                     ("simulate_withdraw",)},
        "absent_from_callers": ("simulate_withdraw",),
        "why": ("метод есть у адаптеров, зовущего на поверхности шагов цикла "
                "нет — ход ни разу не симулируется перед записью"),
    },
    "deposit simulation": {
        "kind": "door_without_caller",
        "evidence": {"spa_core/adapters/compound_v3_adapter.py":
                     ("simulate_deposit",)},
        "absent_from_callers": ("simulate_deposit",),
        "why": "та же форма, что у вывода: дверь есть, зовущего нет",
    },
    "position impact": {
        "kind": "proxy_observation",
        "evidence": {
            "spa_core/allocator/allocator.py": ("apply_capacity_caps",),
            "spa_core/risk/policy.py": ("check_capacity",),
            "spa_core/paper_trading/cycle_runner.py": ("apply_admissible_trim",),
        },
        "why": ("измеряется ДОЛЯ позиции в TVL (потолок 1 %, MP-209) и "
                "допустимый размер хода (ADR-850) — не влияние размера на "
                "ставку, которое назвал владелец"),
    },
    "policy": {
        "kind": "computed_on_path",
        "evidence": {
            "spa_core/paper_trading/cycle_runner.py": ("_apply_risk_policy_gate",
                                                       "policy_approved"),
            # `RiskPolicy` здесь — ОПРЕДЕЛЕНИЕ класса, и дверь определений
            # (`_defined_names`) отличает его от упоминания в строке.
            "spa_core/risk/policy.py": ("RiskPolicy",),
        },
        "why": "вердикт RiskPolicy v1.0 считается на пути каждый цикл",
    },
    "expected economics": {
        "kind": "computed_on_path",
        "evidence": {
            "spa_core/paper_trading/cycle_runner.py": ("_move_cost_usd",),
            "spa_core/allocator/rebalance_economics.py": ("payback_days",),
            "spa_core/paper_trading/allocation_rationale.py": ("gain_pp",),
        },
        "why": "выигрыш, издержка и окупаемость считаются на пути (ADR-060/298)",
    },
}

#: Поверхность ЗОВУЩИХ для претензий об отсутствии. Это не весь денежный путь
#: (адаптеры в него входят, а претензия именно о том, что адаптерную дверь
#: никто не зовёт), а те модули, из которых идут шаги цикла.
CALLER_SURFACE: Tuple[str, ...] = (
    "spa_core/paper_trading/cycle_runner.py",
    "spa_core/paper_trading/cycle_gates.py",
    "spa_core/allocator/allocator.py",
    "spa_core/allocator/rebalance_economics.py",
    "spa_core/tuner/allocation_tuner.py",
    "spa_core/tuner/portfolio_rebalancer.py",
    "spa_core/paper_trading/allocation_rationale.py",
    "spa_core/paper_trading/admissible_trim.py",
    "spa_core/risk/policy.py",
)

# ── ось D: часы у входа цикла ────────────────────────────────────────────────

#: Имена, которыми вход цикла назвал бы момент. ``now`` — первое и каноническое.
CLOCK_PARAM_NAMES: Tuple[str, ...] = ("now", "run_ts", "as_of")


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _read_card(card_path: str) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        with open(card_path, encoding="utf-8") as fh:
            return fh.read().splitlines(), None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except UnicodeDecodeError as exc:  # pragma: no cover
        return None, f"UnicodeDecodeError: {exc}"


def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    """Строки РОВНО раздела §27: от его заголовка до заголовка §28."""
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
                  f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по "
                  f"нему был бы счётом неизвестно чего")


def _items_between(body: List[str], lead: str,
                   stops: Tuple[str, ...]) -> List[str]:
    out: List[str] = []
    seen = False
    for ln in body:
        s = ln.strip()
        if not seen:
            if s == lead:
                seen = True
            continue
        if not s or s == "⸻":
            continue
        if s in stops:
            break
        out.append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    """РАЗБОР карточки — производитель чисел §27. Третий исход при любом сбое."""
    lines, why = _read_card(card_path)
    if lines is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(lines)
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    for anchor in (_REQUIREMENT_LINE, _CHECKS_LEAD, _OUTCOMES_LEAD,
                   _PROHIBITION_LINE):
        if anchor not in stripped:
            return {"measured": False,
                    "reason": f"в §27 не найден якорь {anchor!r} — форма раздела "
                              f"не та, на которую написан разбор"}
    checks = _items_between(body, _CHECKS_LEAD, (_OUTCOMES_LEAD,))
    outcome_lines = _items_between(body, _OUTCOMES_LEAD, (_PROHIBITION_LINE,))
    outcomes = [tok.strip() for ln in outcome_lines for tok in ln.split("/")
                if tok.strip()]
    return {"measured": True, "reason": None, "checks": checks,
            "outcomes": outcomes, "requirement": _REQUIREMENT_LINE,
            "prohibition": _PROHIBITION_LINE}


def parity(card_path: str) -> Dict[str, Any]:
    """Константы прибора ↔ разбор карточки. Расхождение НАЗЫВАЕТСЯ, не прячется."""
    parsed = owner_section_from_card(card_path)
    if not parsed["measured"]:
        return {"agrees": None, "parsed": parsed, "mismatches": [],
                "order_g958_named": ORDER_G958_NAMED,
                "order_undercount": None}
    mism: List[str] = []
    if parsed["checks"] != list(CHECKS_27):
        mism.append(f"проверки: карточка {parsed['checks']} ≠ прибор {list(CHECKS_27)}")
    if len(parsed["checks"]) != OWNER_CHECKS_DECLARED:
        mism.append(f"число проверок: карточка {len(parsed['checks'])} ≠ "
                    f"объявлено {OWNER_CHECKS_DECLARED}")
    if parsed["outcomes"] != list(OUTCOMES_27):
        mism.append(f"исходы: карточка {parsed['outcomes']} ≠ прибор {list(OUTCOMES_27)}")
    if len(parsed["outcomes"]) != OWNER_OUTCOMES_DECLARED:
        mism.append(f"число исходов: карточка {len(parsed['outcomes'])} ≠ "
                    f"объявлено {OWNER_OUTCOMES_DECLARED}")
    return {"agrees": not mism, "parsed": parsed, "mismatches": mism,
            "order_g958_named": ORDER_G958_NAMED,
            "order_undercount": len(parsed["checks"]) - ORDER_G958_NAMED}


# ───────────────────────────── ось A: второе событие ─────────────────────────

def _imports_package(path: Path, package: str) -> Optional[bool]:
    """Импортирует ли модуль пакет (любой формой). ``None`` — не разобран."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == package or node.module.startswith(package + "."):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == package or alias.name.startswith(package + "."):
                    return True
    return False


def money_path_files(root: str) -> Tuple[List[str], List[str]]:
    """Файлы объявленной поверхности денежного пути (ввоз сторожа дрейфа)
    плюс поимённое расширение. Возвращает (файлы, отсутствующие пути)."""
    files: List[str] = []
    missing: List[str] = []
    for prefix in MONEY_PATH_PREFIXES:
        p = Path(root) / prefix
        if prefix.endswith(".py"):
            (files if p.is_file() else missing).append(prefix)
            continue
        if not p.is_dir():
            missing.append(prefix)
            continue
        for path in sorted(p.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in rel or path.name.startswith("test_"):
                continue
            files.append(rel)
    for rel, _ in MONEY_PATH_EXTENSION:
        (files if (Path(root) / rel).is_file() else missing).append(rel)
    return files, missing


def measure_surface(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Расширение поверхности — ПРЕТЕНЗИЯ, и она проверяется: каждый модуль
    расширения обязан импортироваться `cycle_runner` или `cycle_gates`."""
    runner = Path(root) / "spa_core/paper_trading/cycle_runner.py"
    gates = Path(root) / "spa_core/paper_trading/cycle_gates.py"
    rows: Dict[str, Dict[str, Any]] = {}
    for rel, why in MONEY_PATH_EXTENSION:
        dotted = rel[:-3].replace("/", ".")
        verdicts = [_imports_package(p, dotted) for p in (runner, gates)
                    if p.is_file()]
        if not verdicts or any(v is None for v in verdicts):
            rows[rel] = {"kind": UNMEASURED, "why": why,
                         "reason": "cycle_runner/cycle_gates не разобраны"}
        elif any(verdicts):
            rows[rel] = {"kind": "imported_by_cycle", "why": why}
        else:
            rows[rel] = {"kind": "not_imported_by_cycle", "why": why,
                         "reason": "ни cycle_runner, ни cycle_gates его не "
                                   "ввозят — расширение поверхности не доказано"}
    files, missing = money_path_files(root)
    return {"measured": True, "prefixes": list(MONEY_PATH_PREFIXES),
            "extension": rows, "files_n": len(files), "missing": missing}


def measure_second_event(data_dir: str, root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось A: какие ВТОРЫЕ события существуют — реальное и бумажное."""
    out: Dict[str, Any] = {"measured": True, "real_onchain": {}, "paper_virtual": {}}
    # Реальное исполнение: ищется ИМПОРТ пакета исполнения с денежного пути.
    files, missing = money_path_files(root)
    importers: List[str] = []
    unparsed: List[str] = []
    for rel in files:
        v = _imports_package(Path(root) / rel, EXECUTION_PACKAGE)
        if v is None:
            unparsed.append(rel)
        elif v:
            importers.append(rel)
    if not files:
        out["real_onchain"] = {"kind": UNMEASURED,
                               "reason": "поверхность денежного пути пуста: "
                                         + ", ".join(missing)}
    elif unparsed:
        out["real_onchain"] = {"kind": UNMEASURED, "importers": importers,
                               "reason": f"не разобраны {len(unparsed)} файл(а/ов) "
                                         f"поверхности: {unparsed[:3]}"}
    elif importers:
        out["real_onchain"] = {"kind": "present", "importers": importers,
                               "why": "денежный путь ВВОЗИТ пакет исполнения — "
                                      "инвариант #6 нарушен"}
    else:
        out["real_onchain"] = {"kind": "none", "importers": [],
                               "files_scanned": len(files),
                               "why": ("ни один из модулей денежного пути не "
                                       "ввозит `spa_core.execution` (инв. #6) — "
                                       "реального второго события нет ПО "
                                       "ПОСТРОЕНИЮ; это стадия, не пропуск")}
    # Бумажное исполнение: событие `trade_executed` в цепочке аудита.
    chain = _s49.read_chain(Path(data_dir) / _s49.CHAIN_FILENAME)
    if not chain.get("ok"):
        out["paper_virtual"] = {"kind": UNMEASURED, "reason": chain.get("reason")}
    else:
        execs = [r for r in chain["rows"]
                 if r.get("event_type") == _s49.EVENT_EXECUTED]
        props = [r for r in chain["rows"]
                 if r.get("event_type") == _s49.EVENT_PROPOSAL]
        out["paper_virtual"] = {
            "kind": "present" if execs else "none",
            "executions": len(execs), "proposals": len(props),
            "why": ("бумажное исполнение записывается ТЕМ ЖЕ процессом, что и "
                    "предложение (`cycle_runner`, `execution_mode` = "
                    "read_only_simulation)" if execs else
                    "в цепочке нет ни одного `trade_executed`")}
    return out


# ───────────────────────────── ось B: признак повторной проверки ─────────────

def import_recheck_verdict(data_dir: str, root: str = REPO_ROOT,
                           now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Ввоз вердикта ADR-487. Перемера НЕТ: берётся ровно его отчёт."""
    try:
        rep = _s49.run_census(Path(data_dir), now=now, repo_root=Path(root))
    except Exception as exc:  # noqa: BLE001 — причина обязана быть названа
        return {"measured": False,
                "reason": f"перепись ADR-487 упала: {type(exc).__name__}: {exc}"}
    if not rep.get("measured"):
        return {"measured": False,
                "reason": f"перепись ADR-487 отказалась мерить: {rep.get('reason')}"}
    keep = ("status", "executions", "executions_measurable", "no_recheck",
            "recheck_present", "stale_beyond_tolerance", "ttl_declared_count",
            "window_s_min", "window_s_median", "window_s_max",
            "freshness_judgeable", "freshness_unjudgeable_reason")
    out = {k: rep.get(k) for k in keep}
    out["measured"] = True
    out["source"] = "spa_core.monitoring.pre_trade_recheck_census (ADR-487)"
    out["does_not_report"] = rep.get("does_not_report")
    return out


# ───────────────────────────── ось C: наблюдатели ────────────────────────────

def _defined_names(path: str) -> Tuple[Optional[set], Optional[str]]:
    """Имена ОПРЕДЕЛЕНИЙ модуля (функции, классы) — вторая дверь к коду.

    Дверь §26 (``_code_identifiers``) собирает имена, которыми код ПОЛЬЗУЕТСЯ
    (`Name`/`Attribute`/`arg`/строки), и этого достаточно для претензии «модуль
    это читает». Претензия «дверь ЗДЕСЬ ОПРЕДЕЛЕНА» (``def simulate_deposit``)
    — другой вопрос: определение в первую дверь не попадает, и наивный
    «не найдено» опроверг бы верную претензию. Замер #1088: ровно так четыре
    объявления из девяти вышли «разошедшимися с кодом» на первом прогоне.
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef))}, None


def _identifiers_of(root: str, rel: str,
                    cache: Dict[str, Tuple[Optional[set], Optional[str]]]
                    ) -> Tuple[Optional[set], Optional[str]]:
    """Имена кода модуля ОБЕИМИ дверями (использование ∪ определение)."""
    if rel not in cache:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            cache[rel] = (None, "файла нет в дереве")
        else:
            used, why_u = _code_identifiers(path)
            defined, why_d = _defined_names(path)
            if used is None or defined is None:
                cache[rel] = (None, why_u or why_d)
            else:
                cache[rel] = (used | defined, None)
    return cache[rel]


def _check_evidence(root: str, evidence: Dict[str, Tuple[str, ...]],
                    cache: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
    """Все названные имена есть в КОДЕ названных модулей? Третий исход при
    нечитаемом модуле."""
    problems: List[str] = []
    unmeasured = False
    for rel, names in evidence.items():
        ids, why = _identifiers_of(root, rel, cache)
        if ids is None:
            problems.append(f"{rel}: НЕ ИЗМЕРЕНО — {why}")
            unmeasured = True
            continue
        for n in names:
            if n not in ids:
                problems.append(f"{rel}: в коде нет имени {n!r}")
    if unmeasured:
        return None, problems
    return (not problems), problems


def _callers_mention(root: str, words: Tuple[str, ...],
                     cache: Dict[str, Any], *, exact: bool = False
                     ) -> Tuple[Optional[List[str]], List[str]]:
    """Где на поверхности зовущих встречается хоть одно слово-свидетель.

    ``exact=False`` — по ОСНОВЕ (`simulate_withdraw` ловит и
    `simulate_withdraw_usd`): так доказывается отсутствие ЗОВУЩЕГО.
    ``exact=True`` — ТОКЕН целиком: так спрашивается, выдаёт ли дверь слово
    `CANCEL`; по основе «DEFER» нашёлся бы внутри «DEFERRED» и в любой фразе
    журнала (на этом покраснел первый прогон батареи #1088).
    """
    hits: List[str] = []
    unmeasured: List[str] = []
    for rel in CALLER_SURFACE:
        ids, why = _identifiers_of(root, rel, cache)
        if ids is None:
            unmeasured.append(f"{rel}: {why}")
            continue
        for w in words:
            if (w in ids) if exact else any(w in i for i in ids):
                hits.append(f"{rel}:{w}")
                break
    if unmeasured:
        return None, unmeasured
    return hits, []


def measure_observers(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось C: род наблюдателя каждой из девяти проверок, ПРОВЕРЕННЫЙ кодом."""
    cache: Dict[str, Any] = {}
    rows: Dict[str, Dict[str, Any]] = {}
    for check in CHECKS_27:
        decl = OBSERVER_MAP.get(check)
        if decl is None:
            rows[check] = {"kind": UNMEASURED,
                           "reason": "проверка не объявлена в OBSERVER_MAP"}
            continue
        kind = decl["kind"]
        ok, problems = _check_evidence(root, decl["evidence"], cache)
        row: Dict[str, Any] = {"declared": kind, "why": decl["why"],
                               "evidence": {k: list(v) for k, v in
                                            decl["evidence"].items()}}
        if ok is None:
            row.update(kind=UNMEASURED, reason="; ".join(problems))
            rows[check] = row
            continue
        if not ok:
            row.update(kind=UNMEASURED,
                       reason="объявление разошлось с кодом: " + "; ".join(problems))
            rows[check] = row
            continue
        if kind in ("door_without_caller", "absent"):
            words = tuple(decl.get("absent_from_callers") or ())
            hits, unm = _callers_mention(root, words, cache)
            if hits is None:
                row.update(kind=UNMEASURED,
                           reason="поверхность зовущих не прочитана: " + "; ".join(unm))
                rows[check] = row
                continue
            if hits:
                row.update(kind=UNMEASURED,
                           reason=f"претензия «зовущего нет» ОПРОВЕРГНУТА кодом: {hits}")
                rows[check] = row
                continue
        row["kind"] = kind
        row["freshness_capable"] = kind in FRESHNESS_CAPABLE
        also = decl.get("also")
        if also:
            ok2, pr2 = _check_evidence(root, also["evidence"], cache)
            row["also"] = {"kind": also["kind"] if ok2 else UNMEASURED,
                           "evidence": {k: list(v) for k, v in
                                        also["evidence"].items()},
                           "reason": None if ok2 else "; ".join(pr2)}
        rows[check] = row
    tally = {k: sum(1 for r in rows.values() if r["kind"] == k)
             for k in OBSERVER_KINDS}
    return {"measured": True, "checks": rows, "tally": tally,
            "caller_surface": list(CALLER_SURFACE)}


# ───────────────────────────── ось D: fresh = f(now) ─────────────────────────

def measure_clock_at_both_events(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось D: ввоз оси A ADR-969 (субъекты) плюс вход цикла `run_cycle`."""
    out: Dict[str, Any] = {"measured": True, "fifth_input": FIFTH_INPUT}
    pin = measure_pinnability(root)
    if not pin.get("measured"):
        out["subjects"] = {"kind": UNMEASURED, "reason": pin.get("reason")}
    else:
        out["subjects"] = {s: r["kind"] for s, r in
                           (pin.get("fifth_input") or {}).get("subjects", {}).items()}
    if root not in __import__("sys").path:
        __import__("sys").path.insert(0, root)
    try:
        import inspect
        from spa_core.paper_trading.cycle_runner import run_cycle
        params = set(inspect.signature(run_cycle).parameters)
    except Exception as exc:  # noqa: BLE001
        out["cycle_entry"] = {"kind": UNMEASURED,
                              "reason": f"run_cycle не импортирован: "
                                        f"{type(exc).__name__}: {exc}"}
        return out
    named = [n for n in CLOCK_PARAM_NAMES if n in params]
    out["cycle_entry"] = {
        "kind": "pinnable_named" if named else "unpinnable_ambient",
        "params": named,
        "why": ("у входа цикла момент ЕСТЬ аргументом — но к гейту годности "
                "(`_fundable`) он не доезжает: субъекты выше его не принимают"
                if named else "у входа цикла нет аргумента момента"),
    }
    # Род ответа — из словаря §26, а не свой: PIN_KINDS ввезён ради этой проверки.
    assert out["cycle_entry"]["kind"] in PIN_KINDS
    return out


# ───────────────────────────── ось E: словарь исхода ─────────────────────────

def measure_outcome_vocabulary(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось E: CANCEL/DEFER против словаря §24 и дверей решения."""
    out: Dict[str, Any] = {"measured": True, "outcomes": {}}
    s24_reason: Optional[str] = None
    try:
        s24 = _s24.census(Path(root))
    except Exception as exc:  # noqa: BLE001
        s24 = None
        s24_reason = f"перепись §24 упала: {type(exc).__name__}: {exc}"
    rows24 = {r.get("type"): r for r in (s24 or {}).get("types", [])}
    cache: Dict[str, Any] = {}
    for token in OUTCOMES_27:
        in_vocab = token in _s24.OWNER_DECISION_TYPES
        row: Dict[str, Any] = {"in_section_24_vocabulary": in_vocab}
        if in_vocab:
            # Слово из словаря §24 спрашивается ТОЛЬКО у §24. Упавшая перепись
            # соседа — третий исход, а не повод спросить код самим: подстановка
            # своего замера вместо отказа соседа — ровно класс «подстановка
            # вместо отказа» из шага 0-офис.
            row["presence_source"] = "§24 decision_type_census (ввоз)"
            if token in rows24:
                pres = observed(rows24[token], "presence", kind=dict)
                row["presence_on_doors"] = (pres.get("kind") if pres else UNMEASURED)
            else:
                row["presence_on_doors"] = UNMEASURED
                row["presence_reason"] = (s24_reason or
                                          "перепись §24 не отдала строку этого типа")
        else:
            # Слова нет в словаре §24 — дверей решения спрашиваем дверью кода,
            # ТОКЕНОМ целиком.
            hits, unm = _callers_mention(root, (token,), cache, exact=True)
            if hits is None:
                row["presence_on_doors"] = UNMEASURED
                row["presence_reason"] = "; ".join(unm)
            else:
                row["presence_on_doors"] = ("emitted_only" if hits
                                            else "absent_from_every_door")
                row["presence_hits"] = hits
            row["presence_source"] = "AST поверхности зовущих"
        out["outcomes"][token] = row
    return out


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], second: Dict[str, Any],
              recheck: Dict[str, Any], observers: Dict[str, Any],
              clock: Dict[str, Any], vocab: Dict[str, Any],
              surface: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[str]]:
    findings: List[Dict[str, str]] = []
    unmeasured: List[str] = []

    if parity_r.get("agrees") is None:
        unmeasured.append("паритет с карточкой: " + str(parity_r["parsed"].get("reason")))
    elif not parity_r["agrees"]:
        findings.append({"severity": "CRITICAL", "code": "owner_text_drifted",
                         "message": "разбор карточки разошёлся с константами: "
                                    + "; ".join(parity_r["mismatches"])})
    # `or 0` здесь поймал храповик инв. #17 на первом прогоне (#1088): он делал
    # «недосчёт НЕ ИЗМЕРЕН» неотличимым от «недосчёта нет». Третий исход читается явно.
    elif (parity_r.get("order_undercount") is not None
          and parity_r["order_undercount"] > 0):
        findings.append({"severity": "INFO", "code": "order_undercounted_checks",
                         "message": (f"заказ G958 п. 1 назвал {ORDER_G958_NAMED} "
                                     f"проверки, карточка несёт "
                                     f"{OWNER_CHECKS_DECLARED}; число снято "
                                     f"разбором, не глазами")})

    for rel, row in surface.get("extension", {}).items():
        if row["kind"] != "imported_by_cycle":
            unmeasured.append(f"поверхность: расширение {rel} — {row.get('reason')}")

    real = second.get("real_onchain", {})
    paper = second.get("paper_virtual", {})
    if real.get("kind") == UNMEASURED:
        unmeasured.append("ось A (реальное исполнение): " + str(real.get("reason")))
    elif real.get("kind") == "present":
        findings.append({"severity": "CRITICAL", "code": "money_path_imports_execution",
                         "message": f"денежный путь ввозит {EXECUTION_PACKAGE}: "
                                    f"{real.get('importers')} — инвариант #6"})
    if paper.get("kind") == UNMEASURED:
        unmeasured.append("ось A (бумажное исполнение): " + str(paper.get("reason")))
    elif real.get("kind") == "none" and paper.get("kind") == "present":
        w = recheck.get("window_s_max") if recheck.get("measured") else None
        findings.append({
            "severity": "INFO", "code": "second_event_is_paper_within_one_process",
            "message": (f"единственное второе событие §27 — бумажная запись "
                        f"`trade_executed` ({paper.get('executions')} шт.) тем же "
                        f"процессом, что и предложение; окно между событиями "
                        f"≤ {w} с. Реального исполнения нет по инв. #6 — это "
                        f"находка о СТАДИИ, не о пропущенной проверке")})
    elif real.get("kind") == "none" and paper.get("kind") == "none":
        findings.append({"severity": "INFO", "code": "no_second_event_at_all",
                         "message": "ни реального, ни бумажного исполнения — "
                                    "окна §27 не существует"})

    if not recheck.get("measured"):
        unmeasured.append("ось B (признак повторной проверки, ADR-487): "
                          + str(recheck.get("reason")))
    else:
        if recheck.get("status") == _s49.STATUS_CRITICAL:
            findings.append({"severity": "CRITICAL", "code": "stale_beyond_owner_tolerance",
                             "message": f"ADR-487: {recheck.get('stale_beyond_tolerance')} "
                                        f"исполнений старее допуска владельца"})
        elif recheck.get("status") == _s49.STATUS_WARNING:
            findings.append({
                "severity": "WARN", "code": "no_second_observation_between_events",
                "message": (f"ADR-487 (ввоз): у {recheck.get('no_recheck')} из "
                            f"{recheck.get('executions_measurable')} исполнений "
                            f"второго наблюдения входов НЕ БЫЛО — ярлык снимка "
                            f"исполнения равен ярлыку предложения; «opportunity "
                            f"исчезла» заметить нечему")})
        if recheck.get("freshness_judgeable") is False:
            unmeasured.append("ось B: чрезмерная старость входа НЕ СУДИМА — "
                              + str(recheck.get("freshness_unjudgeable_reason")))

    if not observers.get("measured"):
        unmeasured.append("ось C: " + str(observers.get("reason")))
    else:
        for check, row in observers["checks"].items():
            k = row["kind"]
            if k == UNMEASURED:
                unmeasured.append(f"ось C «{check}»: {row.get('reason')}")
            elif k in ("door_without_caller", "absent"):
                findings.append({
                    "severity": "CRITICAL", "code": "check_never_observed_on_money_path",
                    "message": (f"«{check}»: {row['why']} — перепроверять "
                                f"величину, которой путь не наблюдал ни разу, "
                                f"нечем; §27 требует второго взгляда там, где "
                                f"не было первого")})
            elif k == "tree_constant":
                findings.append({
                    "severity": "WARN", "code": "check_enters_as_tree_constant",
                    "message": (f"«{check}»: {row['why']} — у константы "
                                f"свежести нет по построению, слово «fresh» к "
                                f"ней неприменимо")})
            elif k == "proxy_observation":
                findings.append({
                    "severity": "INFO", "code": "owner_word_observed_by_proxy",
                    "message": f"«{check}»: {row['why']}"})
            also = row.get("also")
            if also and also.get("kind") == "tree_constant":
                findings.append({
                    "severity": "WARN", "code": "check_split_between_two_kinds",
                    "message": (f"«{check}»: наблюдается живьём для одной сети "
                                f"как стоп-кран, а в цену хода входит константой "
                                f"{list(also['evidence'].values())[0]} — «fresh» "
                                f"верно про стоп-кран и неверно про цену")})

    if not clock.get("measured"):
        unmeasured.append("ось D: " + str(clock.get("reason")))
    else:
        subj = clock.get("subjects") or {}
        if isinstance(subj, dict) and subj.get("kind") == UNMEASURED:
            unmeasured.append("ось D (субъекты ADR-969): " + str(subj.get("reason")))
        else:
            ambient = sorted(s for s, k in subj.items() if k == "unpinnable_ambient")
            entry = clock.get("cycle_entry") or {}
            if entry.get("kind") == UNMEASURED:
                unmeasured.append("ось D (вход цикла): " + str(entry.get("reason")))
            elif ambient:
                findings.append({
                    "severity": "WARN", "code": "fresh_needs_now_as_input_and_it_is_not",
                    "message": (f"«fresh» спрашивается ДВАЖДЫ, и оба раза это "
                                f"функция `now`; у входа цикла `run_cycle` момент "
                                f"{'ЕСТЬ (' + ', '.join(entry.get('params') or []) + ')' if entry.get('kind') == 'pinnable_named' else 'НЕТ'}, "
                                f"а у субъектов {', '.join(ambient)} — нет "
                                f"(ADR-969 ось A): закрепить одну и ту же "
                                f"свежесть на обоих событиях вызывающий не может")})

    if not vocab.get("measured"):
        unmeasured.append("ось E: " + str(vocab.get("reason")))
    else:
        for token, row in vocab["outcomes"].items():
            if not row.get("in_section_24_vocabulary"):
                findings.append({
                    "severity": "INFO", "code": "outcome_absent_from_section_24_vocabulary",
                    "message": (f"§27 называет исход «{token}», которого нет в "
                                f"словаре типов решения §24 "
                                f"{list(_s24.OWNER_DECISION_TYPES)} — два раздела "
                                f"одного ТЗ расходятся словарём; находка о "
                                f"тексте владельца, не о коде")})
            pres = row.get("presence_on_doors")
            if pres == UNMEASURED:
                unmeasured.append(f"ось E «{token}»: присутствие на дверях — "
                                  + str(row.get("presence_reason")))
            elif pres == "absent_from_every_door":
                findings.append({
                    "severity": "WARN", "code": "outcome_token_absent_from_every_door",
                    "message": (f"исход §27 «{token}» не объявляет и не выдаёт "
                                f"ни одна дверь решения ({row.get('presence_source')}) "
                                f"— «CANCEL / DEFER, а не исполнять устаревшее» "
                                f"произнести сегодня нечем")})
    return findings, unmeasured


def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §27. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    surface = measure_surface(root)
    second = measure_second_event(data_dir, root)
    recheck = import_recheck_verdict(data_dir, root, now=now)
    observers = measure_observers(root)
    clock = measure_clock_at_both_events(root)
    vocab = measure_outcome_vocabulary(root)

    findings, unmeasured = _findings(parity_r, second, recheck, observers,
                                     clock, vocab, surface)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "pre_trade_check_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §27 ТЗ «Portfolio CIO» (Pre-trade "
                     "check). Политику, гейт, окно свежести, прибор ADR-487 и "
                     "живой трек НЕ трогает — только читает"),
        "overall": overall,
        "counts": counts,
        "declared": {"checks": list(CHECKS_27), "checks_n": OWNER_CHECKS_DECLARED,
                     "outcomes": list(OUTCOMES_27),
                     "outcomes_n": OWNER_OUTCOMES_DECLARED,
                     "order_g958_named": ORDER_G958_NAMED,
                     "observer_kinds": list(OBSERVER_KINDS),
                     "second_event_kinds": list(SECOND_EVENT_KINDS)},
        "parity": parity_r,
        "surface": surface,
        "axis_a_second_event": second,
        "axis_b_recheck_sign": recheck,
        "axis_c_observers": observers,
        "axis_d_clock": clock,
        "axis_e_outcome_vocabulary": vocab,
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — (data, path). Сосед §26 на первом прогоне #1088
        # оказался с переставленными аргументами: его `--data-dir` прогон без
        # `--no-write` падал в самом конце, и артефакта §26 не было ни разу.
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§27 ТЗ «Portfolio CIO» (Pre-trade check): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (проверок {OWNER_CHECKS_DECLARED}, "
              f"исходов {OWNER_OUTCOMES_DECLARED}; заказ G958 назвал "
              f"{ORDER_G958_NAMED})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    a = doc["axis_a_second_event"]
    print(f"   [ось A] реальное исполнение = {a.get('real_onchain', {}).get('kind')} · "
          f"бумажное = {a.get('paper_virtual', {}).get('kind')} "
          f"({a.get('paper_virtual', {}).get('executions')} исполнений)")
    b = doc["axis_b_recheck_sign"]
    if b.get("measured"):
        print(f"   [ось B] ADR-487: {b['status']} · без второго наблюдения "
              f"{b['no_recheck']}/{b['executions_measurable']} · окно "
              f"{b['window_s_min']}…{b['window_s_max']} с · свежесть судима = "
              f"{b['freshness_judgeable']}")
    else:
        print(f"   [ось B] НЕ ИЗМЕРЕНО: {b.get('reason')}")
    o = doc["axis_c_observers"]
    if o.get("measured"):
        for check, row in o["checks"].items():
            extra = f" (+{row['also']['kind']})" if row.get("also") else ""
            print(f"   [ось C] {check}: {row['kind']}{extra}")
    d = doc["axis_d_clock"]
    print(f"   [ось D] субъекты: {d.get('subjects')} · вход цикла: "
          f"{(d.get('cycle_entry') or {}).get('kind')} {(d.get('cycle_entry') or {}).get('params')}")
    e = doc["axis_e_outcome_vocabulary"]
    for token, row in (e.get("outcomes") or {}).items():
        print(f"   [ось E] {token}: в словаре §24 = {row.get('in_section_24_vocabulary')} · "
              f"на дверях = {row.get('presence_on_doors')}")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['code']}: {f['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§27 ТЗ «Portfolio CIO»: Pre-trade check — девять проверок "
                    "между двумя событиями")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по "
                         "построению — передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(argv)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(ns.data_dir if ns.data_dir else ns.root, who="pre_trade_check_census")
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card,
              write=not ns.no_write)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
