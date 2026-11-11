"""testing_scenario_census.py — §37 ТЗ «Portfolio CIO»: «Testing scenarios».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §37::

    Testing scenarios
    Необходимо реализовать automated tests и scenario tests.
    Test 1 — очевидно плохая текущая аллокация … Expected: REBALANCE, но не обязательно
    перемещение всех 40%.
    Test 2 — transient spike … Expected: KEEP / DEFER
    … (пятнадцать сцен поимённо) …
    Test 15 — same snapshot determinism … Expected: идентичный calculation output.

Сцен владельца **ПЯТНАДЦАТЬ**, у каждой — вход и ожидание. Число объявлено константой
(:data:`OWNER_SCENES_DECLARED`), названия и ожидания — дословно (:data:`OWNER_SCENES`),
и расхождение с карточкой краснеет тестом, а не живёт в чьей-то памяти (``parity``).

Предмет — не «есть ли тесты в репозитории»
==========================================
Заказ G970 п. 1 назвал предмет точно: «у КАЖДОЙ названной владельцем сцены есть тест,
который на ней проходит, и он красен на ПОРВАННОЙ сцене». Тестов со словом «spike» в
дереве 82 файла, «churn» — 60, «gas» — 168; ни одно из этих чисел на вопрос владельца
не отвечает. Поэтому осей ЧЕТЫРЕ, и каждая отвечает на свой вопрос:

ось A — ДВЕРЬ (:data:`DOOR_KINDS`)
    Существует ли на ДЕНЕЖНОМ ПУТИ дверь, принимающая входы сцены владельца. ``present``
    — все названные входы принимаются; ``partial`` — дверь есть, но хотя бы один вход
    владельца у неё ОТСУТСТВУЕТ (и он назван поимённо: ``missing_inputs``); ``absent`` —
    двери нет. Advisory-модули дверью не считаются (инвариант «advisory никогда не
    гейтит»): корреляция `investment_cio/correlation.py` — не ограничение.
ось B — СЦЕНА ВЛАДЕЛЬЦА (:data:`SCENE_KINDS`)
    Сцена строится из ЛИТЕРАЛОВ владельца и прогоняется через живую дверь; токены двери
    печатаются ДОСЛОВНО (``ACT``/``HOLD``, ``ALLOW``/``BLOCK``, ``approved``…), а
    ожидание владельца читается ПРЕДИКАТОМ о поведении (``reading`` — наше прочтение,
    напечатанное рядом). Перевод ``ACT ↔ REBALANCE`` утверждением об эквивалентности НЕ
    является (ADR-967, §24): читатель видит и токен, и прочтение.
ось C — ПОРВАННАЯ СЦЕНА (:data:`TEAR_KINDS`)
    Та же дверь на сцене, где ожидание владельца обязано СМЕНИТЬСЯ. Если предикат на
    порванной сцене даёт тот же ответ — проверка ничего не различает, и «проходит»
    верно случайно (``indiscriminate``). Это и есть «красен на порванной сцене».
ось D — ТЕСТ В РЕПОЗИТОРИИ (:data:`TEST_KINDS`)
    Объявленный реестр ``SCENE_TESTS`` (путь::функция) сверяется с деревом разбором AST:
    функция существует — ``present``; названа, но не найдена — ``stale``; у сцены не
    названо ни одного теста — ``absent``. Реестр без сверки был бы списком из головы.

🪤 Что считать «денежным путём»
==============================
Двери, через которые проходит цель книги в ``cycle_runner``: дверь ЦЕНЫ
(``allocator.rebalance_economics.evaluate`` — ``ACT``/``HOLD``), ограничитель
(``governance.churn_damper.decide`` — ``ALLOW``/``BLOCK``), гейт политики
(``paper_trading.risk_gate._apply_risk_policy_gate`` — ``approved`` + книга, ADR-053),
потолки аллокатора (``StrategyAllocator._apply_caps``), ёмкость (``risk.capacity_limits``,
применяется в ``allocate()``), гейт Tier-A (``cycle_gates.apply_analytics_blocking_gate``),
газовый стоп-кран Base (``cycle_gates.apply_base_gas_kill_switch`` +
``monitoring.base_gas_monitor``). Колонка порогов — **paper** (``TriggerParams()``),
передаётся ЯВНО: сцена не должна зависеть от ``SPA_CAPITAL_MODE`` хоста.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): живой ``data/`` не читается и не пишется — все сцены
из литералов, часы и журнал ходов инъектируются, газовый монитор и гейт Tier-A работают в
одноразовом каталоге, сигнал Tier-A подменяется ТОЛЬКО на время сцены (вопрос сцены 14 —
«чтит ли гейт BLOCK», а не «умеет ли Tier-A увидеть взлом»; второе измерено отдельно
по реестру модулей и напечатано как недостающий вход). Ни один порог не правится.
Карточку владельцу не заводит: сцены — работа агента, пороги — ADR.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import inspect
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/testing_scenario_census.json"
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "37. Testing scenarios"
NEXT_SECTION_HEAD = "38. Historical replay"
OWNER_REQUIREMENT_LINE = "Необходимо реализовать automated tests и scenario tests."
EXPECTED_LEAD = "Expected:"
SCENE_HEAD_RE = re.compile(r"^Test (\d+) — (.+?)\s*$")

#: Пятнадцать сцен владельца: номер → (название дословно, строки «Expected» дословно).
OWNER_SCENES: Tuple[Tuple[int, str, Tuple[str, ...]], ...] = (
    (1, "очевидно плохая текущая аллокация", ("REBALANCE", "но не обязательно перемещение всех 40%.")),
    (2, "transient spike", ("KEEP / DEFER",)),
    (3, "expensive transaction", ("KEEP",)),
    (4, "Candidate 20%", ("не обходить Tier/Risk Policy.",)),
    (5, "marginal yield collapse", ("уменьшить position size или отказаться.",)),
    (6, "correlation", ("применять concentration/correlation constraints.",)),
    (7, "stale data", ("NO EXECUTION",)),
    (8, "high gas", ("DEFER",)),
    (9, "gas falls", ("новый расчет может перейти:", "DEFER → REBALANCE")),
    (10, "new capital", ("использовать новый capital для приближения к Target, не делать лишний Aave withdrawal.",)),
    (11, "APY disappears before execution", ("pre-trade validation отменяет execution.",)),
    (12, "oscillating APYs", ("никакого churn.",)),
    (13, "concentration limit", ("25% max",)),
    (14, "emergency", ("Risk action имеет приоритет над normal yield optimization.",)),
    (15, "same snapshot determinism", ("идентичный calculation output.",)),
)
OWNER_SCENES_DECLARED = 15

#: Заказ G970 п. 1 назвал предмет и границы (`sed -n '1040,1110p'`, вторая граница — §38),
#: привёл ОДНУ сцену примером («Test 1 — … Aave 40 % / 3 %, Morpho 10 % / 6 %») и числа
#: сцен не называл — сдвиг не применим, и это печатается отдельно от «назвал верно».
ORDER_G970_NAMED: Dict[str, Any] = {"scenes": None, "example_named": "Test 1", "tail_read": True}

DOOR_KINDS: Tuple[str, ...] = ("present", "partial", "absent", UNMEASURED)
SCENE_KINDS: Tuple[str, ...] = ("as_expected", "contrary", "unreachable", UNMEASURED)
TEAR_KINDS: Tuple[str, ...] = ("discriminates", "indiscriminate", "not_built", UNMEASURED)
TEST_KINDS: Tuple[str, ...] = ("present", "stale", "absent", UNMEASURED)

#: Капитал сцены и имена ног. Литералы сцены, не пороги системы.
CAPITAL = 100_000.0
AAVE, MORPHO, COMPOUND = "aave_v3", "morpho_blue", "compound_v3"
CANDIDATE, BASE_VAULT, OTHER = "candidate_vault", "morpho_blue_base", "other_vault"
#: Якорь сцены газового монитора — литерал есть ПРЕДМЕТ (сцена воспроизводима на любом
#: хосте); монитору день передаётся входом ``today=``, стенных часов сцена не знает.
# FROZEN-DATE-OK: injected-clock — день передаётся входом `today=` в
# BaseGasMonitor.record_reading через подкласс сцены; стенные часы не спрашиваются.
SCENE_DAY = dt.date(2026, 11, 9)
DETERMINISM_RUNS = 100

#: Ось D — объявленный реестр тестов на сцену (путь::функция). Сверяется с деревом AST.
_BATTERY = "spa_core/tests/test_testing_scenario_census.py"
SCENE_TESTS: Dict[int, Tuple[str, ...]] = {
    1: (f"{_BATTERY}::test_scene_01_owner_numbers_cannot_reach_the_paper_gain_band",
        f"{_BATTERY}::test_scene_01_torn_a_wider_spread_acts"),
    2: (f"{_BATTERY}::test_scene_02_the_price_door_acts_on_a_captured_spike",
        f"{_BATTERY}::test_scene_02_torn_the_rate_back_holds"),
    3: (f"{_BATTERY}::test_scene_03_two_points_hold_for_the_gain_band_not_persistence",
        f"{_BATTERY}::test_scene_03_torn_a_six_point_spread_acts",
        "spa_core/tests/test_rebalance_economics.py::test_gain_that_cannot_repay_within_the_horizon_holds"),
    4: (f"{_BATTERY}::test_scene_04_a_t3_candidate_at_twenty_percent_is_refused",
        f"{_BATTERY}::test_scene_04_torn_the_same_candidate_as_t1_passes"),
    5: (f"{_BATTERY}::test_scene_05_capacity_cap_shrinks_the_position",
        f"{_BATTERY}::test_scene_05_torn_a_deep_pool_is_not_capped",
        "spa_core/tests/test_capacity_limits.py::test_exactly_at_limit"),
    6: (f"{_BATTERY}::test_scene_06_shared_chain_dependency_is_capped",
        f"{_BATTERY}::test_scene_06_torn_split_chains_pass"),
    7: (f"{_BATTERY}::test_scene_07_stale_liquidity_gets_no_fresh_capital",
        f"{_BATTERY}::test_scene_07_torn_live_liquidity_is_funded",
        "spa_core/tests/test_tvl_floor_verdict.py::test_a_literal_can_never_pass_the_floor",
        "spa_core/tests/test_risk_policy_gate.py::test_low_tvl_blocks"),
    8: (f"{_BATTERY}::test_scene_08_three_high_gas_days_zero_the_base_leg",
        f"{_BATTERY}::test_scene_08_torn_low_gas_leaves_the_leg",
        "spa_core/tests/test_cycle_runner_characterization.py::test_base_gas_kill_switch_disabled_is_noop"),
    9: (f"{_BATTERY}::test_scene_09_gas_falling_releases_the_leg",
        f"{_BATTERY}::test_scene_09_torn_gas_staying_high_keeps_it_zeroed"),
    10: (f"{_BATTERY}::test_scene_10_new_cash_funds_the_gap_without_an_aave_leg",
         f"{_BATTERY}::test_scene_10_torn_selling_aave_while_cash_idles_is_named"),
    11: (f"{_BATTERY}::test_scene_11_recomputation_on_the_vanished_rate_holds",
         f"{_BATTERY}::test_scene_11_torn_a_rate_that_stays_acts"),
    12: (f"{_BATTERY}::test_scene_12_oscillation_never_moves_capital",
         f"{_BATTERY}::test_scene_12_torn_a_wide_swing_acts_on_step_one",
         "spa_core/tests/test_rebalance_economics.py::test_reversing_a_recent_move_must_clear_a_higher_bar",
         "spa_core/tests/test_churn_damper.py::test_min_hold_blocks_a_fresh_reshuffle"),
    13: (f"{_BATTERY}::test_scene_13_the_cap_binds_the_optimum",
         f"{_BATTERY}::test_scene_13_torn_a_target_under_the_cap_is_untouched",
         "spa_core/tests/test_allocator_properties.py::test_inv_per_protocol_tier_cap"),
    14: (f"{_BATTERY}::test_scene_14_a_block_signal_zeroes_the_best_yield",
         f"{_BATTERY}::test_scene_14_torn_an_ok_signal_leaves_the_target"),
    15: (f"{_BATTERY}::test_scene_15_hundred_runs_are_byte_identical",
         f"{_BATTERY}::test_scene_15_torn_the_comparator_sees_one_changed_run",
         "spa_core/tests/test_cycle_nav_determinism.py::test_determinism_byte_identical_output"),
}


# ───────────────────────────── чтение карточки / паритет ──────────────────────

def _read_text(path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница {NEXT_SECTION_HEAD!r} — "
                      f"перечень не ограничен, и счёт по нему был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def parse_scenes(body: List[str]) -> List[Dict[str, Any]]:
    """Сцены раздела: ``Test N — название`` + строки после ``Expected:`` до «⸻»/следующей сцены.

    HTML-комментарии источника (`<!-- источник: … -->`) и пустые строки — не содержание.
    """
    scenes: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    in_expected = False
    for raw in body:
        s = raw.strip()
        if s.startswith("<!--"):
            continue
        m = SCENE_HEAD_RE.match(s)
        if m:
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(), "expected": [], "inputs": []}
            scenes.append(cur)
            in_expected = False
            continue
        if cur is None:
            continue
        if s == "⸻":
            in_expected = False
            continue
        if s == EXPECTED_LEAD:
            in_expected = True
            continue
        if not s:
            continue
        (cur["expected"] if in_expected else cur["inputs"]).append(s)
    return scenes


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = _read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    return {"measured": True, "requirement_line_present": OWNER_REQUIREMENT_LINE in stripped,
            "scenes": parse_scenes(body)}


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None, "order_tail_read": ORDER_G970_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    scenes = parsed["scenes"]
    if not parsed["requirement_line_present"]:
        mism.append(f"строка {OWNER_REQUIREMENT_LINE!r} не найдена")
    if len(scenes) != OWNER_SCENES_DECLARED:
        mism.append(f"сцен в карточке {len(scenes)} ≠ объявлено {OWNER_SCENES_DECLARED}")
    got = [(s["n"], s["title"], tuple(s["expected"])) for s in scenes]
    for want in OWNER_SCENES:
        have = next((g for g in got if g[0] == want[0]), None)
        if have is None:
            mism.append(f"Test {want[0]} в карточке не найден")
        elif have[1] != want[1]:
            mism.append(f"Test {want[0]}: название {have[1]!r} ≠ константе {want[1]!r}")
        elif have[2] != want[2]:
            mism.append(f"Test {want[0]}: ожидание {list(have[2])} ≠ константе {list(want[2])}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    out["order_undercount"] = (None if ORDER_G970_NAMED["scenes"] is None
                               else len(scenes) - int(ORDER_G970_NAMED["scenes"]))
    return out


# ───────────────────────────── двери сцен ─────────────────────────────────────

@contextlib.contextmanager
def _quiet():
    """Глушит ПОПУТНЫЙ лог дверей на время сцены (``logging``, не stdout — ADR-967)."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _paper_params() -> Any:
    from spa_core.allocator.rebalance_economics import TriggerParams
    return TriggerParams()


def econ(current: Dict[str, float], target: Dict[str, float], apy: Dict[str, float],
         capital: float = CAPITAL, **over: Any) -> Any:
    """Вердикт двери ЦЕНЫ (полный объект решения), колонка paper передана явно."""
    from spa_core.allocator.rebalance_economics import evaluate
    protos = sorted(set(current) | set(target) | set(apy))
    scene: Dict[str, Any] = dict(
        current_positions=dict(current), target_positions=dict(target), apy_pct=dict(apy),
        evidenced=set(protos), chains={p: "ethereum" for p in protos}, capital_usd=capital,
        params=_paper_params(), days_since_last_act=99.0,
        position_age_days={p: 99.0 for p in protos}, turnover_last_week_usd=0.0,
        turnover_today_usd=0.0, tvl_evidenced=set(protos),
    )
    scene.update(over)
    with _quiet():
        return evaluate(**scene)


def econ_view(d: Any) -> Dict[str, Any]:
    return {"token": str(d.decision), "reasons": list(d.reasons),
            "legs": {str(l["protocol"]): round(float(l["delta_usd"]), 2) for l in (d.legs or [])},
            "gain_pp": d.gain_pp, "required_gain_pp": d.required_gain_pp,
            "payback_days": d.payback_days, "cost_usd": d.cost_usd}


def damper(current: Dict[str, float], target: Dict[str, float], trades: List[dict],
           capital: float = CAPITAL, now: Optional[dt.datetime] = None) -> Any:
    from spa_core.governance import churn_damper
    anchor = now or dt.datetime.combine(SCENE_DAY, dt.time(12, 0), tzinfo=dt.timezone.utc)
    with _quiet():
        return churn_damper.decide(dict(current), dict(target), list(trades), capital,
                                   now=anchor, params=_paper_params())


def trade(days_ago: float, usd: float) -> dict:
    anchor = dt.datetime.combine(SCENE_DAY, dt.time(12, 0), tzinfo=dt.timezone.utc)
    return {"ts": (anchor - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delta_abs": float(usd)}


def adapter(protocol: str, apy: float, *, tier: str = "T1", chain: str = "ethereum",
            tvl: Optional[float] = None, tvl_source: str = "live") -> dict:
    """Строка снимка оркестратора для гейта. TVL живой и с запасом над полом, если не
    сказано иное — иначе вердикт решала бы ADR-053-заморозка, а не измеряемое ограничение."""
    from spa_core.risk.policy import RiskConfig
    floor = float(RiskConfig().min_tvl_usd)
    return {"protocol": protocol, "apy_pct": apy, "tvl_usd": floor * 20.0 if tvl is None else tvl,
            "tier": tier, "chain": chain, "asset": "USDC", "pool_id": protocol,
            "apy_source": "live", "tvl_source": tvl_source}


def gate(target: Dict[str, float], adapters: List[dict], held: Optional[Dict[str, float]] = None,
         capital: float = CAPITAL) -> Dict[str, Any]:
    """Гейт политики (ADR-053) на литеральном снимке; ``ddir=None`` — реестр не читается."""
    from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate
    with _quiet():
        res = _apply_risk_policy_gate(dict(target), capital, adapters, ddir=None,
                                      current_positions=dict(held or {}))
    # Ключи гейт объявляет ВСЕГДА (``out`` инициализирован до try) — читаем индексом, без
    # подстановки пустого значения: «ключа нет» обязан быть KeyError, а не пустой список (инв. #17).
    return {"approved": bool(res["approved"]), "violations": list(res["violations"]),
            "warnings": list(res["warnings"]), "target_usd": dict(res["target_usd"]),
            "tvl_unverified": list(res["tvl_unverified"]), "error": res["error"]}


def allocator_caps(weights: Dict[str, float], tiers: Dict[str, str], tmp: str) -> Tuple[Dict[str, float], bool, float]:
    """Потолки аллокатора на весах; экземпляр изолирован от живого дерева (как в
    ``test_allocator_properties``)."""
    from spa_core.allocator.allocator import StrategyAllocator
    a = StrategyAllocator(status_path=os.path.join(tmp, "status.json"),
                          registry_path=os.path.join(tmp, "_no_registry.json"),
                          strategy_loop_enabled=False, live_apy_provider={})
    with _quiet():
        capped, was = a._apply_caps(dict(weights), dict(tiers))
    return {k: round(float(v), 6) for k, v in capped.items()}, bool(was), float(StrategyAllocator.T1_CAP)


def capacity_cap(allocation: Dict[str, float], tvl: Dict[str, float]) -> Dict[str, float]:
    from spa_core.risk.capacity_limits import apply_capacity_caps
    with _quiet():
        return {k: round(float(v), 2) for k, v in apply_capacity_caps(dict(allocation), dict(tvl)).items()}


def gas_monitor_class(gwei: float, day: dt.date) -> type:
    """Подкласс монитора для сцены: гейт зовёт ``record_reading()`` без аргументов, и
    без подкласса монитор пошёл бы в СЕТЬ и к СТЕННЫМ часам."""
    from spa_core.monitoring.base_gas_monitor import BaseGasMonitor

    class _SceneGas(BaseGasMonitor):
        def record_reading(self, g: Optional[float] = None, *, today: Optional[dt.date] = None):  # type: ignore[override]
            return super().record_reading(gwei if g is None else g, today=today or day)

    return _SceneGas


def gas_gate(target: Dict[str, float], history_gwei: Sequence[float], today_gwei: float) -> Dict[str, Any]:
    """Газовый стоп-кран Base: история из ``history_gwei`` (по суткам до ``SCENE_DAY``),
    затем гейт на чтении ``today_gwei`` в день сцены. Всё — в одноразовом каталоге."""
    from spa_core.monitoring import base_gas_monitor as bgm
    from spa_core.paper_trading.cycle_gates import apply_base_gas_kill_switch
    out = dict(target)
    notes: List[str] = []
    with tempfile.TemporaryDirectory(prefix="tsc_gas_") as tmp:
        mon = bgm.BaseGasMonitor(data_dir=tmp)
        n = len(history_gwei)
        with _quiet():
            for i, g in enumerate(history_gwei):
                mon.record_reading(float(g), today=SCENE_DAY - dt.timedelta(days=n - i))
            apply_base_gas_kill_switch(out, ddir=Path(tmp),
                                       base_gas_monitor_class=gas_monitor_class(float(today_gwei), SCENE_DAY),
                                       base_chain_monitoring=True, notes=notes)
            status = bgm.BaseGasMonitor(data_dir=tmp).get_status()
    return {"target_usd": out, "notes": notes, "kill_switch_active": bool(status.get("kill_switch_active")),
            "consecutive_above": status.get("consecutive_above"),
            "threshold_gwei": float(bgm.BASE_GAS_THRESHOLD_GWEI), "kill_days": int(bgm.BASE_GAS_KILL_DAYS)}


def tier_a_gate(target: Dict[str, float], signals: Dict[str, str]) -> Dict[str, Any]:
    """Гейт Tier-A на ПОДМЕНЁННОМ сигнале: вопрос сцены — чтит ли гейт BLOCK, а не умеют
    ли модули Tier-A увидеть взлом (это ось «детектор», ниже)."""
    from unittest import mock
    from spa_core.analytics import signal_aggregator
    from spa_core.paper_trading.cycle_gates import apply_analytics_blocking_gate
    out = dict(target)
    notes: List[str] = []

    def _fake(protocols, *_args, **_kw):   # сигнатура run_tier_a(protocols, context=, data_dir=)
        return {"protocols": {p: {"signal": signals.get(p, "OK"), "reason": "scene", "score": 0.0}
                              for p in protocols}}

    with tempfile.TemporaryDirectory(prefix="tsc_tier_a_") as tmp, _quiet(), \
            mock.patch.object(signal_aggregator, "run_tier_a", _fake):
        apply_analytics_blocking_gate(out, ddir=Path(tmp), run_ts="scene", today=SCENE_DAY.isoformat(),
                                      correlation_id="scene", write=False, notes=notes)
    return {"target_usd": {k: round(float(v), 2) for k, v in out.items()}, "notes": notes}


def security_detector_tiers() -> Dict[str, Any]:
    """В каком тире реестра Tier-A/B/C живут детекторы безопасности (ось «детектор» сцены 14)."""
    from spa_core.analytics import _module_registry as reg
    out: Dict[str, Any] = {"tier_a_total": len(reg.TIER_A_MODULES), "by_tier": {}}
    for tier in ("A", "B", "C"):
        mods = getattr(reg, f"TIER_{tier}_MODULES")
        out["by_tier"][tier] = [{"module": m["module"], "weight": m.get("weight")} for m in mods
                                if any(w in m["module"] for w in ("secur", "incident", "exploit", "hack"))]
    return out


def _fingerprint(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)


# ───────────────────────────── сцены владельца ────────────────────────────────
#
# Каждая сцена возвращает словарь: door (ось A), owner/torn (ось B/C — токены дословно и
# `holds` предиката), reading (наше прочтение ожидания владельца словами двери).

def _door(kind: str, symbols: Sequence[str], missing: Sequence[str] = (), note: str = "") -> Dict[str, Any]:
    return {"kind": kind, "symbols": list(symbols), "missing_inputs": list(missing), "note": note}


def scene_01() -> Dict[str, Any]:
    """Aave 40 % @ 3 % · Morpho 10 % @ 6 %; ожидание — REBALANCE, но не обязательно все 40 %."""
    p = _paper_params()
    cur = {AAVE: 0.40 * CAPITAL, MORPHO: 0.10 * CAPITAL}
    apy = {AAVE: 3.0, MORPHO: 6.0}
    move = p.max_turnover_per_move * CAPITAL
    full = econ(cur, {AAVE: 0.0, MORPHO: 0.50 * CAPITAL}, apy)
    bounded = econ(cur, {AAVE: cur[AAVE] - move, MORPHO: cur[MORPHO] + move}, apy)

    def _holds(f: Any, b: Any) -> bool:
        return "ACT" in (str(f.decision), str(b.decision))

    torn_apy = {AAVE: 3.0, MORPHO: 9.0}
    t_full = econ(cur, {AAVE: 0.0, MORPHO: 0.50 * CAPITAL}, torn_apy)
    t_bounded = econ(cur, {AAVE: cur[AAVE] - move, MORPHO: cur[MORPHO] + move}, torn_apy)
    reachable = round(p.max_turnover_per_move * (apy[MORPHO] - apy[AAVE]), 6)
    return {
        "door": _door("present", ["spa_core.allocator.rebalance_economics.evaluate"]),
        "owner": {"full_move": econ_view(full), "bounded_move": econ_view(bounded), "holds": _holds(full, bounded),
                  "largest_gain_one_move_pp": reachable, "required_gain_pp": p.min_gain_pp},
        "torn": {"full_move": econ_view(t_full), "bounded_move": econ_view(t_bounded), "holds": _holds(t_full, t_bounded),
                 "what_changed": "ставка Morpho 6 % → 9 %"},
        "reading": ("REBALANCE читается как: хотя бы одна из двух целей (весь ход · ход в пределах потолка "
                    f"{p.max_turnover_per_move:.0%}) даёт ACT; «не обязательно все 40 %» — цель в пределах потолка"),
    }


def scene_02() -> Dict[str, Any]:
    """Ставка цели 3 % → 12 % на минуты; ожидание — KEEP / DEFER."""
    p = _paper_params()
    cur = {AAVE: 0.40 * CAPITAL, MORPHO: 0.10 * CAPITAL}
    move = p.max_turnover_per_move * CAPITAL
    tgt = {AAVE: cur[AAVE] - move, MORPHO: cur[MORPHO] + move}
    spiked = econ(cur, tgt, {AAVE: 3.0, MORPHO: 12.0})
    back = econ(cur, tgt, {AAVE: 3.0, MORPHO: 3.0})
    return {
        "door": _door("partial", ["spa_core.allocator.rebalance_economics.evaluate"],
                      ["стойкость/длительность ставки (persistence): дверь цены принимает ОДНУ ставку без истории; "
                       "окно свежести снимка (ADR-976, 36 ч) старит наблюдение, но не спрашивает, сколько оно держалось"],
                      "полоса здравости живого APY (_LIVE_APY_MAX_DECIMAL = 200 %) всплеск 12 % не ловит"),
        "owner": {"spike_captured": econ_view(spiked), "holds": str(spiked.decision) == "HOLD"},
        "torn": {"rate_back": econ_view(back), "holds": str(back.decision) == "HOLD",
                 "what_changed": "ставка цели вернулась к 3 %"},
        "reading": "KEEP / DEFER читается как: дверь цены на снимке со всплеском выдаёт HOLD",
    }


def scene_03() -> Dict[str, Any]:
    """+2 пп, окупаемость 20 дн., ожидаемая стойкость 5 дн.; ожидание — KEEP."""
    p = _paper_params()
    cur = {AAVE: 0.50 * CAPITAL}
    move = p.max_turnover_per_move * CAPITAL
    tgt = {AAVE: cur[AAVE] - move, MORPHO: move}
    two = econ(cur, tgt, {AAVE: 3.0, MORPHO: 5.0})
    six = econ(cur, tgt, {AAVE: 3.0, MORPHO: 9.0})
    return {
        "door": _door("partial", ["spa_core.allocator.rebalance_economics.evaluate"],
                      ["ожидаемая стойкость (expected persistence) — входа нет",
                       "окупаемость (break-even) — не вход, а ВЫВОД из констант газа/проскальзывания (cost_model)"],
                      f"горизонт окупаемости колонки paper — {p.max_payback_days:.0f} дн."),
        "owner": {"two_points": econ_view(two), "holds": str(two.decision) == "HOLD"},
        "torn": {"six_points": econ_view(six), "holds": str(six.decision) == "HOLD",
                 "what_changed": "разница ставок 2 пп → 6 пп"},
        "reading": ("KEEP читается как HOLD; причина двери — полоса выигрыша (gain_below_band), а не "
                    "«стойкость короче окупаемости», как у владельца: ответ совпал, основание — нет"),
    }


def scene_04() -> Dict[str, Any]:
    """Кандидат показывает 20 % APY; ожидание — не обходить Tier/Risk Policy."""
    tgt = {CANDIDATE: 0.20 * CAPITAL, AAVE: 0.40 * CAPITAL}
    t3 = gate(tgt, [adapter(CANDIDATE, 20.0, tier="T3"), adapter(AAVE, 3.0)])
    t1 = gate(tgt, [adapter(CANDIDATE, 20.0, tier="T1"), adapter(AAVE, 3.0)])

    def _refused(g: Dict[str, Any]) -> bool:
        return (not g["approved"]) or float(g["target_usd"].get(CANDIDATE, 0.0)) <= 0.0

    return {
        "door": _door("present", ["spa_core.paper_trading.risk_gate._apply_risk_policy_gate",
                                  "spa_core.risk.policy.RiskPolicy.check_new_position"]),
        "owner": {"t3_candidate": t3, "holds": _refused(t3)},
        "torn": {"t1_candidate": t1, "holds": _refused(t1), "what_changed": "тир кандидата T3 → T1 при той же ставке"},
        "reading": ("«не обходить Tier/Risk Policy» читается как: кандидат тира T3 на 20 % капитала НЕ одобрен "
                    "(потолок T3), хотя его ставка внутри полосы APY политики"),
    }


def scene_05() -> Dict[str, Any]:
    """Показано 8 %, после нашего депозита 3,5 %; ожидание — уменьшить размер или отказаться."""
    shallow = capacity_cap({CANDIDATE: 0.20 * CAPITAL}, {CANDIDATE: 500_000.0})
    deep = capacity_cap({CANDIDATE: 0.20 * CAPITAL}, {CANDIDATE: 50_000_000.0})
    from spa_core.risk.capacity_limits import MAX_CAPACITY_PCT
    return {
        "door": _door("partial", ["spa_core.risk.capacity_limits.apply_capacity_caps",
                                  "spa_core.allocator.allocator.StrategyAllocator.allocate (MP-209)"],
                      ["ставка ПОСЛЕ нашего депозита (marginal APY) — входа нет ни у одной двери; размер режется долей "
                       f"от TVL пула ({MAX_CAPACITY_PCT:.0%}), а не по падению ставки"],
                      "в RiskPolicy.check_new_position та же ёмкость — warn-only (ADR-009)"),
        "owner": {"shallow_pool": shallow, "proposed_usd": 0.20 * CAPITAL,
                  "holds": float(shallow[CANDIDATE]) < 0.20 * CAPITAL},
        "torn": {"deep_pool": deep, "holds": float(deep[CANDIDATE]) < 0.20 * CAPITAL,
                 "what_changed": "TVL пула $500 тыс. → $50 млн"},
        "reading": "«уменьшить position size» читается как: сумма после ёмкостного потолка меньше предложенной",
    }


def scene_06() -> Dict[str, Any]:
    """Несколько vault на одних критических зависимостях; ожидание — concentration/correlation constraints."""
    tgt = {CANDIDATE: 0.30 * CAPITAL, OTHER: 0.30 * CAPITAL}
    same = gate(tgt, [adapter(CANDIDATE, 6.0, chain="base"), adapter(OTHER, 6.0, chain="base")])
    split = gate(tgt, [adapter(CANDIDATE, 6.0, chain="base"), adapter(OTHER, 6.0, chain="ethereum")])
    return {
        "door": _door("partial", ["spa_core.paper_trading.risk_gate._apply_risk_policy_gate",
                                  "spa_core.risk.policy.RiskConfig.max_l2_total_allocation / max_single_chain_allocation"],
                      ["общие критические зависимости vault (оракул, куратор, базовый актив, мост) — входа нет; "
                       "единственная зависимость, которую знает денежный путь, — СЕТЬ"],
                      "корреляция investment_cio/correlation.py — advisory-коэффициент начислений, не ограничение"),
        "owner": {"same_chain": same, "holds": not same["approved"]},
        "torn": {"split_chains": split, "holds": not split["approved"], "what_changed": "второй vault на другой сети"},
        "reading": "«constraints» читается как: два vault на одной L2-сети сверх потолка L2 НЕ одобрены",
    }


def scene_07() -> Dict[str, Any]:
    """APY свежий, ликвидность stale; ожидание — NO EXECUTION."""
    tgt = {MORPHO: 0.20 * CAPITAL}
    stale = gate(tgt, [adapter(MORPHO, 6.0, tvl_source="stale")])
    live = gate(tgt, [adapter(MORPHO, 6.0, tvl_source="live")])

    def _no_fresh(g: Dict[str, Any]) -> bool:
        return float(g["target_usd"].get(MORPHO, 0.0)) <= 0.0

    return {
        "door": _door("present", ["spa_core.paper_trading.risk_gate._apply_risk_policy_gate (ADR-053)"]),
        "owner": {"stale_liquidity": stale, "holds": _no_fresh(stale) and MORPHO in stale["tvl_unverified"]},
        "torn": {"live_liquidity": live, "holds": _no_fresh(live), "what_changed": "tvl_source stale → live"},
        "reading": "NO EXECUTION читается как: пул без живого TVL не получает свежего капитала (ADR-053)",
    }


def scene_08() -> Dict[str, Any]:
    """Экономика хорошая, газ временно делает сделку плохой; ожидание — DEFER."""
    tgt = {BASE_VAULT: 0.20 * CAPITAL, AAVE: 0.30 * CAPITAL}
    high = gas_gate(tgt, [50.0, 50.0], 50.0)
    low = gas_gate(tgt, [1.0, 1.0], 1.0)

    def _deferred(g: Dict[str, Any]) -> bool:
        return float(g["target_usd"][BASE_VAULT]) == 0.0 and float(g["target_usd"][AAVE]) == tgt[AAVE]

    return {
        "door": _door("partial", ["spa_core.paper_trading.cycle_gates.apply_base_gas_kill_switch",
                                  "spa_core.monitoring.base_gas_monitor.BaseGasMonitor"],
                      ["газ Ethereum как НАБЛЮДЕНИЕ — у двери цены газ есть литерал модуля "
                       "(backtesting.tier1.cost_model.GAS_USD_PER_POSITION_CHANGE), не вход",
                       f"«временно» в часах/минутах — порог монитора {high['kill_days']} суточных чтения"],
                      f"порог {high['threshold_gwei']} gwei, только сеть Base"),
        "owner": {"high_gas": high, "holds": _deferred(high)},
        "torn": {"low_gas": low, "holds": _deferred(low), "what_changed": "чтения 50 gwei → 1 gwei"},
        "reading": "DEFER читается как: нога Base обнулена стоп-краном при неизменной ноге Ethereum",
    }


def scene_09() -> Dict[str, Any]:
    """Та же возможность, газ падает; ожидание — DEFER → REBALANCE."""
    tgt = {BASE_VAULT: 0.20 * CAPITAL, AAVE: 0.30 * CAPITAL}
    falls = gas_gate(tgt, [50.0, 50.0, 50.0], 1.0)
    stays = gas_gate(tgt, [50.0, 50.0, 50.0], 50.0)

    def _released(g: Dict[str, Any]) -> bool:
        return float(g["target_usd"][BASE_VAULT]) == tgt[BASE_VAULT]

    return {
        "door": _door("partial", ["spa_core.paper_trading.cycle_gates.apply_base_gas_kill_switch",
                                  "spa_core.monitoring.base_gas_monitor.BaseGasMonitor"],
                      ["тот же недостающий вход, что у сцены 8: газ Ethereum не наблюдается"],
                      "сброс стоп-крана — одним чтением ниже порога (KILL_SWITCH_RESET)"),
        "owner": {"gas_falls": falls, "holds": _released(falls)},
        "torn": {"gas_stays": stays, "holds": _released(stays), "what_changed": "четвёртое чтение 1 gwei → 50 gwei"},
        "reading": "DEFER → REBALANCE читается как: после чтения ниже порога нога Base возвращается в цель",
    }


def scene_10() -> Dict[str, Any]:
    """+$10k нового кэша, Morpho недовложен; ожидание — новым капиталом к цели, без лишнего вывода из Aave."""
    cur = {AAVE: 0.40 * CAPITAL, MORPHO: 0.10 * CAPITAL, COMPOUND: 0.40 * CAPITAL}   # кэш 10 % — новый
    apy = {AAVE: 3.0, MORPHO: 6.0, COMPOUND: 3.5}
    good = {AAVE: 0.40 * CAPITAL, MORPHO: 0.20 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
    bad = {AAVE: 0.30 * CAPITAL, MORPHO: 0.20 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
    e_good, d_good = econ(cur, good, apy), damper(cur, good, [])
    e_bad, d_bad = econ(cur, bad, apy), damper(cur, bad, [])
    from spa_core.allocator.allocator import StrategyAllocator
    alloc_params = list(inspect.signature(StrategyAllocator.allocate).parameters)

    def _holds(e: Any, d: Any) -> bool:
        legs = {str(l["protocol"]): float(l["delta_usd"]) for l in (e.legs or [])}
        return legs.get(AAVE, 0.0) >= 0.0 and str(e.decision) == "ACT" and bool(d.allowed)

    return {
        "door": _door("partial", ["spa_core.allocator.rebalance_economics.evaluate",
                                  "spa_core.governance.churn_damper.decide"],
                      ["ЦЕЛЬ строится аллокатором без знания текущих позиций: сигнатура "
                       f"StrategyAllocator.allocate{tuple(alloc_params)} текущей книги не принимает — "
                       "«не делать лишний вывод из Aave» судят двери НАД готовой целью, а не её построение"]),
        "owner": {"economics": econ_view(e_good), "damper": {"token": str(d_good.decision), "reason": str(d_good.reason)},
                  "holds": _holds(e_good, d_good)},
        "torn": {"economics": econ_view(e_bad), "damper": {"token": str(d_bad.decision), "reason": str(d_bad.reason)},
                 "holds": _holds(e_bad, d_bad), "what_changed": "цель продаёт $10k Aave при простаивающем кэше"},
        "reading": ("ожидание читается как: ноги хода не содержат уменьшения Aave, дверь цены — ACT, "
                    "ограничитель — ALLOW"),
    }


def scene_11() -> Dict[str, Any]:
    """Рекомендация создана, до исполнения ставка упала; ожидание — pre-trade validation отменяет."""
    cur = {AAVE: 0.40 * CAPITAL, MORPHO: 0.10 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
    tgt = {AAVE: 0.30 * CAPITAL, MORPHO: 0.20 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
    at_rec = econ(cur, tgt, {AAVE: 3.0, MORPHO: 9.0, COMPOUND: 3.5})
    vanished = econ(cur, tgt, {AAVE: 3.0, MORPHO: 3.0, COMPOUND: 3.5})
    stays = econ(cur, tgt, {AAVE: 3.0, MORPHO: 9.0, COMPOUND: 3.5})
    p = _paper_params()
    return {
        "door": _door("partial", ["spa_core.allocator.rebalance_economics.evaluate (пересчёт)"],
                      ["дверь ОТМЕНЫ записанной рекомендации перед исполнением: ручки input_freshness_tolerance_s="
                       f"{p.input_freshness_tolerance_s:.0f} с / decision_ttl_s={p.decision_ttl_s:.0f} с ОПИСЫВАЮТ допуск, "
                       "ворот принуждения у двери исполнения нет (ADR-971 ось E, ADR-972); на бумаге решение и "
                       "исполнение — один процесс (ADR-970 § 2)"]),
        "owner": {"at_recommendation": econ_view(at_rec), "re_evaluated": econ_view(vanished),
                  "holds": str(at_rec.decision) == "ACT" and str(vanished.decision) == "HOLD"},
        "torn": {"at_recommendation": econ_view(at_rec), "re_evaluated": econ_view(stays),
                 "holds": str(at_rec.decision) == "ACT" and str(stays.decision) == "HOLD",
                 "what_changed": "ставка цели к моменту исполнения не упала"},
        "reading": ("«pre-trade validation отменяет» читается как: ПЕРЕСЧЁТ на исчезнувшей ставке даёт HOLD; "
                    "самой двери отмены в денежном пути нет — это названо недостающим входом"),
    }


def scene_12() -> Dict[str, Any]:
    """A/B колеблются 5,0/5,3 ↔ 5,4/5,1; ожидание — никакого churn."""
    p = _paper_params()
    a = {AAVE: 0.50 * CAPITAL, MORPHO: 0.50 * CAPITAL}
    move = p.max_turnover_per_move * CAPITAL
    b = {AAVE: a[AAVE] - move, MORPHO: a[MORPHO] + move}

    def _swing(r1: Dict[str, float], r2: Dict[str, float]) -> Dict[str, Any]:
        s1 = econ(a, b, r1)
        s2 = econ(b, a, r2, last_move_legs={AAVE: -move, MORPHO: move}, days_since_last_move=1.0,
                  days_since_last_act=1.0)
        d2 = damper(b, a, [trade(1.0, move)])
        holds = str(s1.decision) == "HOLD" and str(s2.decision) == "HOLD" and not d2.allowed
        return {"step_1": econ_view(s1), "step_2": econ_view(s2),
                "damper_step_2": {"token": str(d2.decision), "reason": str(d2.reason)}, "holds": holds}

    owner = _swing({AAVE: 5.0, MORPHO: 5.3}, {AAVE: 5.4, MORPHO: 5.1})
    torn = _swing({AAVE: 5.0, MORPHO: 9.0}, {AAVE: 9.0, MORPHO: 5.0})
    torn["what_changed"] = "размах качелей 0,3 пп → 4 пп"
    return {
        "door": _door("present", ["spa_core.allocator.rebalance_economics.evaluate",
                                  "spa_core.governance.churn_damper.decide"]),
        "owner": owner, "torn": torn,
        "reading": ("«никакого churn» читается как: оба шага качелей — HOLD у двери цены, обратный шаг — "
                    "BLOCK у ограничителя"),
    }


def scene_13() -> Dict[str, Any]:
    """Оптимум 70 %, потолок политики; ожидание — потолок."""
    with tempfile.TemporaryDirectory(prefix="tsc_caps_") as tmp:
        capped, was, t1_cap = allocator_caps({CANDIDATE: 0.70, OTHER: 0.30}, {CANDIDATE: "T1", OTHER: "T1"}, tmp)
        under, was_u, _ = allocator_caps({CANDIDATE: 0.30, OTHER: 0.30}, {CANDIDATE: "T1", OTHER: "T1"}, tmp)
    g_over = gate({CANDIDATE: 0.70 * CAPITAL, OTHER: 0.20 * CAPITAL},
                  [adapter(CANDIDATE, 8.0), adapter(OTHER, 3.0)])
    g_under = gate({CANDIDATE: 0.30 * CAPITAL, OTHER: 0.30 * CAPITAL},
                   [adapter(CANDIDATE, 8.0), adapter(OTHER, 3.0)])
    return {
        "door": _door("present", ["spa_core.allocator.allocator.StrategyAllocator._apply_caps",
                                  "spa_core.paper_trading.risk_gate._apply_risk_policy_gate"],
                      note=(f"потолок владельца в сцене — 25 % (пример), потолок политики T1 — {t1_cap:.0%} "
                            "(RiskConfig.max_concentration_t1); числа РАЗНЫЕ и не сравниваются")),
        "owner": {"allocator_capped": capped, "was_capped": was, "t1_cap": t1_cap, "gate_on_optimum": g_over,
                  "holds": was and float(capped[CANDIDATE]) <= t1_cap + 1e-9 and not g_over["approved"]},
        "torn": {"allocator_capped": under, "was_capped": was_u, "gate_under_cap": g_under,
                 "holds": was_u and not g_under["approved"], "what_changed": "оптимум 70 % → 30 % (под потолком)"},
        "reading": ("«25 % max» читается как: аллокатор режет вес до потолка T1, а гейт НЕ одобряет цель, "
                    "превышающую потолок"),
    }


def scene_14() -> Dict[str, Any]:
    """Текущий протокол получает critical security alert; ожидание — risk action выше yield."""
    tgt = {AAVE: 0.50 * CAPITAL, MORPHO: 0.40 * CAPITAL}
    blocked = tier_a_gate(tgt, {AAVE: "BLOCK"})
    ok = tier_a_gate(tgt, {AAVE: "OK"})
    det = security_detector_tiers()
    tier_a_sec = [m["module"] for m in det["by_tier"]["A"]]
    incident = [m for t in ("B", "C") for m in det["by_tier"][t] if "incident" in m["module"]]

    def _risk_first(g: Dict[str, Any]) -> bool:
        return float(g["target_usd"][AAVE]) == 0.0 and abs(sum(g["target_usd"].values()) - sum(tgt.values())) < 0.01

    return {
        "door": _door("partial", ["spa_core.paper_trading.cycle_gates.apply_analytics_blocking_gate",
                                  "spa_core.analytics.signal_aggregator.run_tier_a"],
                      [("детектор «critical security alert» в Tier A: трекер инцидентов "
                        f"{[m['module'] for m in incident]} живёт в тире C с весом "
                        f"{[m['weight'] for m in incident]} и до BLOCK не дотягивается по построению; "
                        f"в Tier A по безопасности — только {tier_a_sec} (категория bridge)")],
                      f"модулей Tier A — {det['tier_a_total']}"),
        "owner": {"block_signal": blocked, "holds": _risk_first(blocked), "detectors": det},
        "torn": {"ok_signal": ok, "holds": _risk_first(ok), "what_changed": "сигнал Tier-A BLOCK → OK"},
        "reading": ("«risk action выше yield» читается как: протокол с лучшей ставкой при BLOCK обнулён, "
                    "высвобожденное перераспределено"),
    }


def scene_15() -> Dict[str, Any]:
    """100 запусков на одном снимке; ожидание — идентичный расчёт."""
    cur = {AAVE: 0.40 * CAPITAL, MORPHO: 0.10 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
    tgt = {AAVE: 0.40 * CAPITAL, MORPHO: 0.20 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
    apy = {AAVE: 3.0, MORPHO: 6.0, COMPOUND: 3.5}
    adapters = [adapter(CANDIDATE, 8.0), adapter(OTHER, 3.0)]
    g_tgt = {CANDIDATE: 0.30 * CAPITAL, OTHER: 0.30 * CAPITAL}
    econ_prints = {_fingerprint(econ_view(econ(cur, tgt, apy))) for _ in range(DETERMINISM_RUNS)}
    gate_prints = {_fingerprint(gate(g_tgt, adapters)) for _ in range(DETERMINISM_RUNS)}
    # контроль сравнителя: 99 одинаковых прогонов + один на ДРУГОМ снимке
    control = {_fingerprint(econ_view(econ(cur, tgt, apy))) for _ in range(DETERMINISM_RUNS - 1)}
    control.add(_fingerprint(econ_view(econ(cur, tgt, {**apy, MORPHO: 6.5}))))
    return {
        "door": _door("present", ["spa_core.allocator.rebalance_economics.evaluate",
                                  "spa_core.paper_trading.risk_gate._apply_risk_policy_gate"]),
        "owner": {"runs": DETERMINISM_RUNS, "distinct_economics": len(econ_prints), "distinct_gate": len(gate_prints),
                  "holds": len(econ_prints) == 1 and len(gate_prints) == 1},
        "torn": {"runs": DETERMINISM_RUNS, "distinct_economics": len(control), "holds": len(control) == 1,
                 "what_changed": "один прогон из ста — на другом снимке (контроль сравнителя)"},
        "reading": "«идентичный output» читается как: отпечатков результата за 100 прогонов ровно один",
    }


SCENES: Dict[int, Callable[[], Dict[str, Any]]] = {
    1: scene_01, 2: scene_02, 3: scene_03, 4: scene_04, 5: scene_05, 6: scene_06, 7: scene_07,
    8: scene_08, 9: scene_09, 10: scene_10, 11: scene_11, 12: scene_12, 13: scene_13, 14: scene_14, 15: scene_15,
}


# ───────────────────────────── ось D: тест в репозитории ──────────────────────

def test_presence(root: str, refs: Sequence[str]) -> Dict[str, Any]:
    """Каждая ссылка ``путь::функция`` сверяется с деревом разбором AST."""
    rows: List[Dict[str, Any]] = []
    for ref in refs:
        path, _, func = ref.partition("::")
        full = os.path.join(root, path)
        text, why = _read_text(full)
        if text is None:
            rows.append({"ref": ref, "kind": UNMEASURED, "reason": f"файл не прочитан: {why}"})
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            rows.append({"ref": ref, "kind": UNMEASURED, "reason": f"файл не разобран: {exc}"})
            continue
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        rows.append({"ref": ref, "kind": "present" if func in names else "stale",
                     "reason": None if func in names else f"функция {func!r} в {path} не найдена"})
    if not rows:
        kind = "absent"
    elif any(r["kind"] == UNMEASURED for r in rows):
        kind = UNMEASURED
    elif any(r["kind"] == "stale" for r in rows):
        kind = "stale"
    else:
        kind = "present"
    return {"kind": kind, "refs": rows}


# ───────────────────────────── контроль и замер ───────────────────────────────

def control() -> Tuple[bool, str, Dict[str, Any]]:
    """Условие ВСЕГО отчёта: здоровая сцена проходит обе главные двери.

    Без него «дверь отказала» и «сцена сломана» неотличимы, а «ожидание не исполнено»
    произносилось бы и в мире, где не работает сама сцена.
    """
    try:
        cur = {AAVE: 0.40 * CAPITAL, MORPHO: 0.10 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
        tgt = {AAVE: 0.30 * CAPITAL, MORPHO: 0.20 * CAPITAL, COMPOUND: 0.40 * CAPITAL}
        e = econ(cur, tgt, {AAVE: 3.0, MORPHO: 9.0, COMPOUND: 3.5})
        g = gate({CANDIDATE: 0.30 * CAPITAL, OTHER: 0.30 * CAPITAL}, [adapter(CANDIDATE, 6.0), adapter(OTHER, 3.0)])
    except Exception as exc:  # noqa: BLE001
        return False, f"здоровая сцена не построена: {type(exc).__name__}: {exc}", {}
    base = {"economics": str(e.decision), "gate_approved": g["approved"], "gate_error": g["error"]}
    if str(e.decision) != "ACT":
        return False, f"здоровая сцена не даёт ACT у двери цены ({e.decision}: {'; '.join(e.reasons)})", base
    if not g["approved"]:
        return False, f"здоровая цель не одобрена гейтом ({g['violations']}; error={g['error']})", base
    return True, "", base


def measure_scene(n: int, root: str) -> Dict[str, Any]:
    spec = next(s for s in OWNER_SCENES if s[0] == n)
    row: Dict[str, Any] = {"n": n, "title": spec[1], "expected": list(spec[2]),
                           "tests": test_presence(root, SCENE_TESTS.get(n, ()))}
    try:
        got = SCENES[n]()
    except Exception as exc:  # noqa: BLE001
        row.update({"door": _door(UNMEASURED, [], note=f"{type(exc).__name__}: {exc}"),
                    "scene_kind": UNMEASURED, "tear_kind": UNMEASURED,
                    "reason": f"сцена не построена: {type(exc).__name__}: {exc}"})
        return row
    row.update(got)
    door_kind = got["door"]["kind"]
    owner_holds = bool(got["owner"].get("holds"))
    torn_holds = bool(got["torn"].get("holds"))
    if door_kind == "absent":
        row["scene_kind"] = "unreachable"
        row["tear_kind"] = "not_built"
    else:
        row["scene_kind"] = "as_expected" if owner_holds else "contrary"
        row["tear_kind"] = "discriminates" if owner_holds != torn_holds else "indiscriminate"
    return row


def _tally(rows: Dict[int, Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out = {"door": {k: 0 for k in DOOR_KINDS}, "scene": {k: 0 for k in SCENE_KINDS},
           "tear": {k: 0 for k in TEAR_KINDS}, "tests": {k: 0 for k in TEST_KINDS}}
    for r in rows.values():
        out["door"][r["door"]["kind"]] += 1
        out["scene"][r["scene_kind"]] += 1
        out["tear"][r["tear_kind"]] += 1
        out["tests"][r["tests"]["kind"]] += 1
    return out


def _findings(parity_r: Dict[str, Any], ctl_ok: bool, ctl_why: str,
              rows: Dict[int, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []
    if not parity_r["parsed"].get("measured"):
        unmeasured.append(f"паритет с карточкой НЕ ИЗМЕРЕН: {parity_r['parsed'].get('reason')}")
    elif parity_r["agrees"] is False:
        findings.append({"severity": "CRITICAL", "code": "parity_mismatch",
                         "detail": "константы прибора расходятся с карточкой: " + "; ".join(parity_r["mismatches"])})
    if not ctl_ok:
        unmeasured.append(f"контрольная сцена сломана — счёт по сценам НЕ читать: {ctl_why}")
        return findings, unmeasured
    for n in sorted(rows):
        r = rows[n]
        tag = f"Test {n} ({r['title']})"
        if r["scene_kind"] == UNMEASURED:
            unmeasured.append(f"{tag}: {r.get('reason')}")
            continue
        dk = r["door"]["kind"]
        if dk == "absent":
            findings.append({"severity": "CRITICAL", "code": "door_absent", "scene": n,
                             "detail": f"{tag}: двери на денежном пути нет — {r['door']['note']}"})
        elif dk == "partial":
            findings.append({"severity": "WARN", "code": "door_partial", "scene": n,
                             "detail": f"{tag}: дверь без входа владельца — " + "; ".join(r["door"]["missing_inputs"])})
        if r["scene_kind"] == "contrary":
            findings.append({"severity": "CRITICAL", "code": "scene_contrary", "scene": n,
                             "detail": f"{tag}: живая дверь НЕ даёт ожидаемого владельцем ({' · '.join(r['expected'])}); "
                                       f"прочтение: {r['reading']}"})
        if r["tear_kind"] == "indiscriminate":
            findings.append({"severity": "CRITICAL", "code": "scene_indiscriminate", "scene": n,
                             "detail": f"{tag}: порванная сцена ({r['torn'].get('what_changed')}) даёт тот же ответ — "
                                       "проверка ничего не различает"})
        tk = r["tests"]["kind"]
        if tk == "absent":
            findings.append({"severity": "WARN", "code": "test_absent", "scene": n,
                             "detail": f"{tag}: в реестре нет ни одного теста"})
        elif tk == "stale":
            stale = [x["reason"] for x in r["tests"]["refs"] if x["kind"] == "stale"]
            findings.append({"severity": "WARN", "code": "test_stale", "scene": n,
                             "detail": f"{tag}: реестр называет тест, которого нет — " + "; ".join(stale)})
        elif tk == UNMEASURED:
            unmeasured.append(f"{tag}: тесты не сверены — " + "; ".join(
                x["reason"] for x in r["tests"]["refs"] if x["kind"] == UNMEASURED))
    return findings, unmeasured


def run(root: str = REPO_ROOT, card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None, scenes: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """Полный замер §37. Только ЧИТАЕТ; ``applied=False``. ``scenes`` — подмножество номеров
    (вход для батареи; по умолчанию — все пятнадцать)."""
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    parity_r = parity(card_path)
    ctl_ok, ctl_why, ctl_base = control()
    wanted = list(scenes) if scenes is not None else [s[0] for s in OWNER_SCENES]
    rows = {n: measure_scene(n, root) for n in wanted} if ctl_ok else {}
    findings, unmeasured = _findings(parity_r, ctl_ok, ctl_why, rows)
    counts = {"critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
              "warn": sum(1 for f in findings if f["severity"] == "WARN"),
              "info": 0, "unmeasured": len(unmeasured)}
    overall = ("CRITICAL" if counts["critical"] else "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "testing_scenario_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §37 ТЗ «Portfolio CIO» (Testing scenarios): у каждой из пятнадцати "
                     "сцен владельца — дверь на денежном пути (A), поведение живой двери на сцене владельца (B), "
                     "на порванной сцене (C) и тест в репозитории (D). Живой data/ не читается и не пишется; "
                     "токены дверей печатаются дословно, ожидание владельца читается ПРЕДИКАТОМ (reading), "
                     "а не переводом токенов (ADR-967). Ни один порог не правится; карточка владельцу не заводится."),
        "overall": overall,
        "counts": counts,
        "declared": {"scenes": [{"n": s[0], "title": s[1], "expected": list(s[2])} for s in OWNER_SCENES],
                     "scenes_declared": OWNER_SCENES_DECLARED, "requirement_line": OWNER_REQUIREMENT_LINE,
                     "order_g970_named": dict(ORDER_G970_NAMED),
                     "door_kinds": list(DOOR_KINDS), "scene_kinds": list(SCENE_KINDS),
                     "tear_kinds": list(TEAR_KINDS), "test_kinds": list(TEST_KINDS),
                     "capital_usd": CAPITAL, "params_column": "paper (TriggerParams(), передана явно)",
                     "determinism_runs": DETERMINISM_RUNS},
        "parity": parity_r,
        "control": {"ok": ctl_ok, "reason": ctl_why, "base": ctl_base},
        "scenes": {str(n): rows[n] for n in sorted(rows)},
        "tally": _tally(rows) if rows else None,
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§37 ТЗ «Portfolio CIO» (Testing scenarios): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (сцен {OWNER_SCENES_DECLARED}; заказ G970 чисел не называл — "
              f"сдвиг не применим, пример назван: {ORDER_G970_NAMED['example_named']})")
    elif p.get("agrees") is False:
        print("   паритет с карточкой: РАСХОЖДЕНИЕ — " + "; ".join(p["mismatches"]))
    else:
        print(f"   паритет с карточкой: НЕ ИЗМЕРЕН — {p['parsed'].get('reason')}")
    ctl = doc["control"]
    print(f"   контроль: {'OK' if ctl['ok'] else 'СЛОМАН — ' + ctl['reason']} {ctl['base']}")
    t = doc.get("tally")
    if t:
        print(f"   двери: {t['door']} · сцены: {t['scene']} · порванные: {t['tear']} · тесты: {t['tests']}")
    for n, r in doc["scenes"].items():
        d = r["door"]["kind"]
        print(f"   Test {n:>2} {r['title']!s:<36} дверь={d:<8} сцена={r['scene_kind']:<12} "
              f"порванная={r['tear_kind']:<14} тесты={r['tests']['kind']}")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['code']}: {f['detail']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, "--now пуст — момент замера не назван"
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        return None, f"--now не разобран ({exc})"
    return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)), None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§37 ТЗ «Portfolio CIO»: у каждой сцены владельца — дверь, сцена, порванная сцена и тест")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, card_path=ns.card, write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
