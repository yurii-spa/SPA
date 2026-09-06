"""cio_failure_modes.py — §47 ТЗ «Portfolio CIO»: отказывает ли путь решения на
деградации входа.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §47 «Failure modes»::

    Система должна fail-safe. При: missing APY · stale data · conflicting
    sources · missing liquidity · simulation failure · risk service unavailable
    · unknown Tier · unknown protocol · unknown asset · price uncertainty —
    НЕ выполнять automatic rebalance. Использовать DEFER или соответствующее
    safe состояние.

Десять условий названы ВЛАДЕЛЬЦЕМ, а не нами; порядок и формулировки — его.

Ответ на «мерил ли кто-нибудь» — НЕТ
====================================
Отдельные двери проверены поимённо (ADR-053 морозит пул без живого TVL,
FIX-P0 закрывает упавший гейт, `target_fully_evidenced` не пускает
ненаблюдаемую цель), и у каждой есть свой тест. Но вопрос §47 поставлен НЕ про
дверь, а про ПОКРЫТИЕ: на скольких из десяти названных деградаций путь решения
отказывает. Такого замера не делал никто, и ответ на него нельзя получить
чтением — только опытом над настоящими функциями.

Что именно считается «путём решения»
====================================
Ровно те две функции, которыми живой дневной цикл решает о перекладке:

``spa_core.paper_trading.risk_gate._apply_risk_policy_gate``
    допустимость цели (RiskPolicy v1.0 + заморозка ADR-053). Отказ = либо
    ``approved=False``, либо ``error`` (упавший гейт), либо снятие свежего
    капитала с пула (``tvl_unverified`` / выпадение из цели).

``spa_core.allocator.rebalance_economics.evaluate``
    экономический вердикт ADR-060: ``ACT`` (перекладываем) или ``HOLD``.

Обе вызываются НАСТОЯЩИЕ. Ни один порог здесь не назначен: потолки
концентрации и пол TVL — у :class:`spa_core.risk.policy.RiskConfig`, полоса
выгоды и горизонт окупаемости — у
:class:`spa_core.allocator.rebalance_economics.TriggerParams`. Модуль
СПРАШИВАЕТ у них, а не повторяет их числа.

Положительный контроль — часть КАЖДОГО замера, а не украшение
==============================================================
«После деградации система не перекладывает» ничего не значит, если она не
перекладывала и до неё. Поэтому каждая проба сначала обязана получить на
ЗДОРОВОМ входе вердикт «капитал бы двинулся» (``approved=True`` и полная цель
у гейта; ``ACT`` у экономики), и только потом портит РОВНО ОДИН вход. Не
удалось установить здоровый вердикт ⇒ исход пробы ``UNCHECKED`` с названной
причиной, а НЕ «отказывает». Это ровно тот дефект, из-за которого сторож
бывает зелёным на сломанном коде: проверка, которой нечего было ломать.

Четыре исхода, и третий — самостоятельный
==========================================
``REFUSES``
    здоровый вход двигает капитал, деградированный — нет. §47 выполнен.
``PARTIAL``
    отказ есть, но не на всей поверхности условия (например, только когда
    деградирован ПОКУПАЕМЫЙ пул, но не удерживаемый). Называется вслух, потому
    что «частично» в отчёте о fail-safe читается как «есть» — и это ошибка.
``PROCEEDS``
    деградированный вход капитал ДВИГАЕТ. Прямое расхождение с §47.
``UNCHECKED``
    условие не представимо входом этого пути (шага симуляции в paper-контуре
    нет вовсе) либо положительный контроль не установлен. Не ноль и не скип:
    «не измерено» — отдельный исход с причиной, иначе оно неотличимо от
    «прошло».

Направление ошибки важнее её наличия
=====================================
У «missing APY» есть две стороны, и они не симметричны. Ненаблюдаемый пул
получает вклад 0 — правило ADR-060, записанное НАМЕРЕННО («что мы не можем
доказать, того мы не заработали»): иначе непрозрачный пул защищался бы своим
литералом от перекладки в наблюдаемый. На стороне ПОКУПКИ это работает как
задумано — цель с ненаблюдаемым пулом получает отказ. На стороне УДЕРЖАНИЯ то
же правило действует наоборот: потеря наблюдения за пулом, который мы держим,
удешевляет расставание с ним и ДОБАВЛЯЕТ выгоды предложенному ходу. Замер
показывает переход ``HOLD → ACT`` от одной пропавшей ставки. Замысел ADR-060
при этом не оспаривается — он назван; расходится с §47 не замысел, а
поведение: пробел в данных не обязан порождать перекладку.

ADVISORY. Ни одна дверь этим модулем не строится и не двигается: добавить
отказ в путь решения — значит изменить путь, по которому двигается капитал,
то есть money-path и решение владельца.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_failure_modes.json"

REFUSES = "REFUSES"
PARTIAL = "PARTIAL"
PROCEEDS = "PROCEEDS"
UNCHECKED = "UNCHECKED"

#: Десять условий §47 в порядке ТЗ. Ключ → дословная формулировка владельца.
OWNER_CONDITIONS: tuple[tuple[str, str], ...] = (
    ("missing_apy", "missing APY"),
    ("stale_data", "stale data"),
    ("conflicting_sources", "conflicting sources"),
    ("missing_liquidity", "missing liquidity"),
    ("simulation_failure", "simulation failure"),
    ("risk_service_unavailable", "risk service unavailable"),
    ("unknown_tier", "unknown Tier"),
    ("unknown_protocol", "unknown protocol"),
    ("unknown_asset", "unknown asset"),
    ("price_uncertainty", "price uncertainty"),
)

#: Капитал сцены. Не порог и ничего не решает: доли к нему приводятся ниже из
#: настоящих потолков RiskConfig, поэтому число можно менять, не трогая смысл.
_SCENE_CAPITAL_USD = 100_000.0


# ─────────────────────────── сцена для гейта допустимости ───────────────────

def _gate_scene(policy_caps: dict) -> dict:
    """Здоровая сцена гейта: доли ПОД настоящими потолками RiskConfig.

    Ни одна доля здесь не выдумана — каждая берётся как половина потолка
    соответствующего тира, поэтому изменение потолка владельцем сцену не
    ломает и не превращает положительный контроль в ложный.
    """
    cap = _SCENE_CAPITAL_USD
    t1 = float(policy_caps["t1_frac"]) * cap * 0.75
    t2 = float(policy_caps["t2_frac"]) * cap * 0.75
    floor = float(policy_caps["tvl_floor_usd"])
    return {
        "capital_usd": cap,
        "target": {"aave_v3": round(t1, 2), "pendle": round(t2, 2)},
        # Держим МЕНЬШЕ, чем целимся: свежий капитал в pendle обязателен,
        # иначе «заморозка на удержанном» была бы неотличима от разрешения.
        "held": {"aave_v3": round(t1 + 0.10 * cap, 2), "pendle": round(t2 * 0.5, 2)},
        "adapters": [
            _row("aave_v3", 2.7, floor * 180.0, "T1"),
            _row("pendle", 9.0, floor * 16.0, "T2"),
        ],
    }


def _row(proto: str, apy_pct: float, tvl_usd: float, tier: str, **over: Any) -> dict:
    row = {
        "protocol": proto,
        "apy_pct": apy_pct,
        "tvl_usd": tvl_usd,
        "tier": tier,
        "apy_source": "live",
        "tvl_source": "live",
    }
    row.update(over)
    return row


def _policy_caps() -> dict:
    """Потолки берутся у RiskConfig — модуль их не повторяет."""
    from spa_core.risk.policy import RiskConfig

    cfg = RiskConfig()
    return {
        "t1_frac": float(cfg.max_concentration_t1),
        "t2_frac": float(cfg.max_concentration_t2),
        "tvl_floor_usd": float(cfg.min_tvl_usd),
        "source": "spa_core.risk.policy.RiskConfig",
    }


def _call_gate(scene: dict, adapters: list[dict], target: dict | None = None) -> dict:
    """Настоящий гейт допустимости, в СВОЁМ временном каталоге состояния.

    Каталог пуст намеренно: живой ``data/`` не читается и не пишется — иначе
    вердикт пробы зависел бы от хоста, а не от подставленного входа.
    """
    from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate

    with tempfile.TemporaryDirectory(prefix="cio_fm_") as tmp:
        return _apply_risk_policy_gate(
            dict(target if target is not None else scene["target"]),
            scene["capital_usd"],
            adapters,
            ddir=Path(tmp),
            current_positions=dict(scene["held"]),
        )


def _gate_moves_capital(scene: dict, gate: dict) -> bool:
    """«Капитал бы двинулся» = гейт одобрил И не срезал ни одной ноги цели."""
    if not gate.get("approved") or gate.get("error") is not None:
        return False
    got = gate.get("target_usd") or {}
    for proto, want in scene["target"].items():
        if abs(float(got.get(proto, 0.0)) - float(want)) > 0.01:
            return False
    return True


# ────────────────────────── сцена для экономического вердикта ───────────────

def _econ_scene_buy(params) -> dict:
    """Сцена ПОКУПКИ: свежий капитал заходит в пул, которого в книге ещё нет.

    Здесь деградация касается ТОЛЬКО покупаемой стороны — пул не удерживается,
    поэтому его наблюдаемость не может подействовать на книгу «до хода».
    Полоса выгоды берётся у ``TriggerParams``, а не назначается: цель строится
    как «полоса с двойным запасом», что бы полоса ни значила.
    """
    cap = _SCENE_CAPITAL_USD
    band = float(params.min_gain_pp)
    move_frac = 0.12                      # под потолком хода TriggerParams
    move = move_frac * cap
    dst_apy = (2.0 * band) / move_frac    # выгода = 2 полосы: пул покупается из кэша
    return {
        "kind": "buy",
        "capital_usd": cap,
        "current": {"aave_v3": 0.40 * cap, "cash": 0.60 * cap},
        "target": {"aave_v3": 0.40 * cap, "morpho_blue": move,
                   "cash": 0.60 * cap - move},
        "apy": {"aave_v3": 2.7, "morpho_blue": round(dst_apy, 6), "cash": 0.0},
        "evidenced": {"aave_v3", "morpho_blue", "cash"},
        "chains": {"aave_v3": "ethereum", "morpho_blue": "ethereum",
                   "cash": "ethereum"},
        "degraded_protocol": "morpho_blue",
        "band_pp": band,
    }


def _econ_scene_exit(params) -> dict:
    """Сцена ВЫХОДА: книга целиком покидает пул, и его наблюдаемость пропадает.

    Выгода здоровой сцены НАМЕРЕННО ниже полосы — иначе «после деградации
    ACT» ничего не доказывало бы: надо видеть именно ПЕРЕХОД. Обе величины
    выведены из полосы ``TriggerParams``, литералов решения тут нет.
    """
    cap = _SCENE_CAPITAL_USD
    band = float(params.min_gain_pp)
    move_frac = 0.12
    move = move_frac * cap
    src_apy = 2.7
    healthy_gain = 0.6 * band             # заведомо НИЖЕ полосы
    dst_apy = src_apy + healthy_gain / move_frac
    return {
        "kind": "exit",
        "capital_usd": cap,
        "current": {"aave_v3": move, "cash": cap - move},
        "target": {"morpho_blue": move, "cash": cap - move},
        "apy": {"aave_v3": src_apy, "morpho_blue": round(dst_apy, 6), "cash": 0.0},
        "evidenced": {"aave_v3", "morpho_blue", "cash"},
        "chains": {"aave_v3": "ethereum", "morpho_blue": "ethereum",
                   "cash": "ethereum"},
        "degraded_protocol": "aave_v3",
        "band_pp": band,
    }


def _call_econ(scene: dict, params, *, apy: dict | None = None,
               evidenced: set | None = None, tvl_evidenced: set | None = None):
    from spa_core.allocator.rebalance_economics import evaluate

    return evaluate(
        current_positions=dict(scene["current"]),
        target_positions=dict(scene["target"]),
        apy_pct=dict(scene["apy"] if apy is None else apy),
        evidenced=set(scene["evidenced"] if evidenced is None else evidenced),
        chains=dict(scene["chains"]),
        capital_usd=scene["capital_usd"],
        params=params,
        tvl_evidenced=set(scene["evidenced"]) if tvl_evidenced is None else tvl_evidenced,
    )


# ─────────────────────────────────── пробы ──────────────────────────────────

def _probe(key: str, verbatim: str, door: str, outcome: str, *,
           healthy: str = "", degraded: str = "", detail: str = "",
           reason: str = "") -> dict:
    return {
        "condition": key,
        "owner_wording": verbatim,
        "door": door,
        "outcome": outcome,
        "healthy_verdict": healthy,
        "degraded_verdict": degraded,
        "detail": detail,
        "unchecked_reason": reason,
    }


def _probe_missing_apy(ctx: dict) -> dict:
    """Пропала ставка. Две стороны, и они НЕ симметричны."""
    params = ctx["params"]
    buy_scene, exit_scene = ctx["econ_scene_buy"], ctx["econ_scene_exit"]

    # ── сторона ПОКУПКИ: положительный контроль — здоровый вход даёт ACT ──
    buy_healthy = _call_econ(buy_scene, params)
    if buy_healthy.decision != "ACT":
        return _probe("missing_apy", "missing APY", _DOOR_ECON, UNCHECKED,
                      reason=("положительный контроль стороны покупки не "
                              f"установлен: здоровая сцена дала "
                              f"{buy_healthy.decision} "
                              f"({'; '.join(buy_healthy.reasons)})"))
    buy_ev = set(buy_scene["evidenced"]) - {buy_scene["degraded_protocol"]}
    buy = _call_econ(buy_scene, params, evidenced=buy_ev)

    # ── сторона УДЕРЖАНИЯ: контроль ОБРАТНЫЙ — здоровый вход обязан быть HOLD ──
    exit_healthy = _call_econ(exit_scene, params)
    exit_probe_ok = exit_healthy.decision == "HOLD"
    exit_dec = None
    if exit_probe_ok:
        ex_apy = dict(exit_scene["apy"])
        ex_apy.pop(exit_scene["degraded_protocol"])
        ex_ev = set(exit_scene["evidenced"]) - {exit_scene["degraded_protocol"]}
        exit_dec = _call_econ(exit_scene, params, apy=ex_apy, evidenced=ex_ev)

    buy_closed = sorted(k for k, v in (buy.gates or {}).items() if not v)
    detail = (f"покупаемый пул без ставки: {buy_healthy.decision} → "
              f"{buy.decision} (выгода {buy_healthy.gain_pp:+.3f} → "
              f"{buy.gain_pp:+.3f} пп; закрылись гейты {buy_closed})")
    if exit_dec is not None:
        detail += (f"; покидаемый пул без ставки: {exit_healthy.decision} → "
                   f"{exit_dec.decision} (выгода {exit_healthy.gain_pp:+.3f} → "
                   f"{exit_dec.gain_pp:+.3f} пп)")
    else:
        detail += ("; сторона удержания НЕ измерена: обратный контроль требует "
                   f"здорового HOLD, получен {exit_healthy.decision}")

    if buy.decision == "ACT":
        return _probe("missing_apy", "missing APY", _DOOR_ECON, PROCEEDS,
                      healthy="ACT", degraded="ACT", detail=detail)
    if exit_dec is not None and exit_dec.decision == "ACT":
        return _probe(
            "missing_apy", "missing APY", _DOOR_ECON, PROCEEDS,
            healthy=f"покупка ACT / удержание {exit_healthy.decision}",
            degraded=f"покупка {buy.decision} / удержание ACT",
            detail=detail + " — пропажа ставки у ПОКИДАЕМОГО пула сама СОЗДАЁТ "
                            "перекладку: ход, который на полных данных не "
                            "проходит полосу выгоды, на пробеле в данных её "
                            "проходит")
    if exit_dec is None:
        return _probe("missing_apy", "missing APY", _DOOR_ECON, PARTIAL,
                      healthy="ACT", degraded=buy.decision, detail=detail)
    return _probe("missing_apy", "missing APY", _DOOR_ECON, REFUSES,
                  healthy="ACT", degraded=buy.decision, detail=detail)


def _probe_stale_data(ctx: dict) -> dict:
    """Ставка ЕСТЬ, но она вчерашняя (``apy_source='fallback_stale'``).

    Отличие от «пропала ставка» существенно: ЗНАЧЕНИЕ на месте, не живёт
    только его ИСТОЧНИК. Живой вывод один и тот же — ``evidenced`` строится в
    ``allocation_rationale.write_shadow_rationale`` из ``apy_sources ==
    "live"``, — поэтому деградируется ровно та величина, которую строит цикл,
    и значение НЕ удаляется. Так проба отличает правило «ненаблюдаемое = 0»
    от простого отсутствия числа.
    """
    params = ctx["params"]
    buy_scene, exit_scene = ctx["econ_scene_buy"], ctx["econ_scene_exit"]

    buy_healthy = _call_econ(buy_scene, params)
    if buy_healthy.decision != "ACT":
        return _probe("stale_data", "stale data", _DOOR_ECON, UNCHECKED,
                      reason=f"положительный контроль не установлен: "
                             f"{buy_healthy.decision}")
    stale_ev = set(buy_scene["evidenced"]) - {buy_scene["degraded_protocol"]}
    buy = _call_econ(buy_scene, params, evidenced=stale_ev)

    # Сторона ВЫХОДА: значение остаётся, живым перестаёт быть только источник.
    exit_healthy = _call_econ(exit_scene, params)
    exit_dec = None
    if exit_healthy.decision == "HOLD":
        ex_ev = set(exit_scene["evidenced"]) - {exit_scene["degraded_protocol"]}
        exit_dec = _call_econ(exit_scene, params, evidenced=ex_ev)

    # А видит ли протухший источник гейт допустимости?
    g_scene = ctx["gate_scene"]
    stale_rows = [dict(r) for r in g_scene["adapters"]]
    for r in stale_rows:
        if r["protocol"] == "pendle":
            r["apy_source"] = "fallback_stale"
    gate_moves = _gate_moves_capital(g_scene, _call_gate(g_scene, stale_rows))

    detail = (f"покупаемый пул с протухшим источником: {buy.decision}; "
              f"гейт допустимости: "
              f"{'ПРОПУСКАЕТ' if gate_moves else 'отказывает'} — поле "
              f"apy_source им не читается вовсе")
    if exit_dec is not None:
        detail += (f"; покидаемый пул с протухшим источником (значение НА "
                   f"МЕСТЕ): {exit_healthy.decision} → {exit_dec.decision} "
                   f"(выгода {exit_healthy.gain_pp:+.3f} → "
                   f"{exit_dec.gain_pp:+.3f} пп)")
    else:
        detail += ("; сторона выхода НЕ измерена: обратный контроль требует "
                   f"здорового HOLD, получен {exit_healthy.decision}")

    if buy.decision == "ACT":
        return _probe("stale_data", "stale data", _DOOR_ECON, PROCEEDS,
                      healthy="ACT", degraded="ACT", detail=detail)
    if exit_dec is not None and exit_dec.decision == "ACT":
        return _probe(
            "stale_data", "stale data", _DOOR_ECON, PROCEEDS,
            healthy=f"покупка ACT / выход {exit_healthy.decision}",
            degraded=f"покупка {buy.decision} / выход ACT",
            detail=detail + " — протухший источник у ПОКИДАЕМОГО пула сам "
                            "СОЗДАЁТ перекладку: правило «ненаблюдаемое = 0» "
                            "действует и тогда, когда число на месте")
    outcome = PARTIAL if (gate_moves or exit_dec is None) else REFUSES
    return _probe("stale_data", "stale data", _DOOR_ECON, outcome,
                  healthy="ACT", degraded=buy.decision, detail=detail)


def _probe_conflicting_sources(ctx: dict) -> dict:
    """Два источника об ОДНОМ пуле спорят. Кто победил — решает порядок строк."""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("conflicting_sources", "conflicting sources", _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен: здоровая сцена "
                             "не двигает капитал")
    live = _row("pendle", 9.0, ctx["caps"]["tvl_floor_usd"] * 16.0, "T2")
    stat = _row("pendle", 9.0, ctx["caps"]["tvl_floor_usd"] * 16.0, "T2",
                tvl_source="static")
    head = [r for r in scene["adapters"] if r["protocol"] != "pendle"]
    live_last = _call_gate(scene, head + [stat, live])
    stat_last = _call_gate(scene, head + [live, stat])
    a, b = _gate_moves_capital(scene, live_last), _gate_moves_capital(scene, stat_last)
    detail = (f"живая строка последней: капитал двигается={a} "
              f"(заморожено {live_last.get('tvl_unverified')}); "
              f"статическая последней: капитал двигается={b} "
              f"(заморожено {stat_last.get('tvl_unverified')})")
    if a != b:
        return _probe("conflicting_sources", "conflicting sources", _DOOR_GATE, PROCEEDS,
                      healthy="капитал двигается", degraded="решает ПОРЯДОК строк",
                      detail=detail + " — спор двух источников не отказ, а "
                                      "молчаливая победа последней записи")
    if a:
        return _probe("conflicting_sources", "conflicting sources", _DOOR_GATE, PROCEEDS,
                      healthy="капитал двигается", degraded="капитал двигается",
                      detail=detail)
    return _probe("conflicting_sources", "conflicting sources", _DOOR_GATE, REFUSES,
                  healthy="капитал двигается", degraded="отказ", detail=detail)


def _probe_missing_liquidity(ctx: dict) -> dict:
    """TVL пула не наблюдён — пол ликвидности проверить нечем (ADR-053)."""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("missing_liquidity", "missing liquidity", _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен")
    rows = [dict(r) for r in scene["adapters"]]
    for r in rows:
        if r["protocol"] == "pendle":
            r["tvl_source"] = "static"
    gate = _call_gate(scene, rows)
    moved = _gate_moves_capital(scene, gate)
    got = float((gate.get("target_usd") or {}).get("pendle", 0.0))
    detail = (f"свежий капитал снят: цель ${scene['target']['pendle']:,.0f} → "
              f"${got:,.0f} (удержано ${scene['held']['pendle']:,.0f}); "
              f"заморожено {gate.get('tvl_unverified')}")
    if moved:
        return _probe("missing_liquidity", "missing liquidity", _DOOR_GATE, PROCEEDS,
                      healthy="капитал двигается", degraded="капитал двигается",
                      detail=detail)
    return _probe("missing_liquidity", "missing liquidity", _DOOR_GATE, REFUSES,
                  healthy="капитал двигается",
                  degraded="заморозка на удержанном (hold+reduce)", detail=detail)


def _probe_simulation_failure(ctx: dict) -> dict:
    """Шага симуляции в paper-контуре НЕТ — деградировать нечего."""
    probe = ctx["simulation_step"]
    if probe.get("present"):
        return _probe("simulation_failure", "simulation failure",
                      probe.get("door", ""), UNCHECKED,
                      reason="шаг симуляции найден, но проба над ним не построена")
    return _probe(
        "simulation_failure", "simulation failure", "—", UNCHECKED,
        reason=("в paper-контуре шага симуляции сделки нет вовсе: путь решения "
                "read-only и не импортирует spa_core/execution (инвариант #6), "
                f"{probe.get('reason', '')}. Дверь появится вместе со Stage 2 "
                "ТЗ §40 — это решение владельца, а не пропущенная проверка"))


def _probe_risk_service_unavailable(ctx: dict) -> dict:
    """Сам RiskPolicy недоступен. Диверсия над импортом, а не над данными."""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("risk_service_unavailable", "risk service unavailable",
                      _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен")
    saved = sys.modules.get("spa_core.risk.policy")
    sys.modules["spa_core.risk.policy"] = None   # импорт останавливается
    try:
        gate = _call_gate(scene, scene["adapters"])
    finally:
        if saved is None:
            sys.modules.pop("spa_core.risk.policy", None)
        else:
            sys.modules["spa_core.risk.policy"] = saved
    moved = _gate_moves_capital(scene, gate)
    detail = (f"approved={gate.get('approved')} · error={gate.get('error')!r}")
    if moved:
        return _probe("risk_service_unavailable", "risk service unavailable",
                      _DOOR_GATE, PROCEEDS, healthy="капитал двигается",
                      degraded="капитал двигается", detail=detail)
    return _probe("risk_service_unavailable", "risk service unavailable",
                  _DOOR_GATE, REFUSES, healthy="капитал двигается",
                  degraded="fail-closed: approved=False + названный error",
                  detail=detail)


def _probe_unknown_tier(ctx: dict) -> dict:
    """Тир пула — не T1/T2/T3, а неизвестное слово (или его нет вовсе)."""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("unknown_tier", "unknown Tier", _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен")
    weird = [dict(r) for r in scene["adapters"]]
    for r in weird:
        if r["protocol"] == "pendle":
            r["tier"] = "T_UNKNOWN_TIER"
    absent = [dict(r) for r in scene["adapters"]]
    for r in absent:
        if r["protocol"] == "pendle":
            r.pop("tier", None)
    g1, g2 = _call_gate(scene, weird), _call_gate(scene, absent)
    m1, m2 = _gate_moves_capital(scene, g1), _gate_moves_capital(scene, g2)
    detail = (f"незнакомое слово в поле тира: капитал двигается={m1}; "
              f"поля тира нет вовсе: капитал двигается={m2}")
    if m1 or m2:
        return _probe("unknown_tier", "unknown Tier", _DOOR_GATE, PROCEEDS,
                      healthy="капитал двигается", degraded="капитал двигается",
                      detail=detail + " — незнакомый тир молча получает потолок T2 "
                                      "вместо отказа")
    return _probe("unknown_tier", "unknown Tier", _DOOR_GATE, REFUSES,
                  healthy="капитал двигается", degraded="отказ", detail=detail)


def _probe_unknown_protocol(ctx: dict) -> dict:
    """Протокол, которого путь решения не знает."""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("unknown_protocol", "unknown protocol", _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен")
    # (а) имени нет в снимке адаптеров вовсе
    ghost_target = dict(scene["target"])
    ghost_target.pop("pendle")
    ghost_target["protocol_nobody_declared"] = scene["target"]["pendle"]
    absent = _call_gate(scene, scene["adapters"], target=ghost_target)
    got_ghost = float((absent.get("target_usd") or {}).get(
        "protocol_nobody_declared", 0.0))
    # (б) имя В снимке есть и TVL живой — но никакого другого признака знания нет
    known_row = [dict(r) for r in scene["adapters"]]
    known_row.append(_row("protocol_nobody_declared", 9.0,
                          ctx["caps"]["tvl_floor_usd"] * 16.0, "T2"))
    present = _call_gate(scene, known_row, target=ghost_target)
    got_present = float((present.get("target_usd") or {}).get(
        "protocol_nobody_declared", 0.0))
    detail = (f"имени нет в снимке: свежий капитал ${got_ghost:,.0f} "
              f"(заморожено {absent.get('tvl_unverified')}); "
              f"имя в снимке с живым TVL: свежий капитал ${got_present:,.0f}")
    if got_ghost <= 0.01 and got_present <= 0.01:
        return _probe("unknown_protocol", "unknown protocol", _DOOR_GATE, REFUSES,
                      healthy="капитал двигается", degraded="отказ", detail=detail)
    if got_ghost <= 0.01:
        return _probe(
            "unknown_protocol", "unknown protocol", _DOOR_GATE, PARTIAL,
            healthy="капитал двигается", degraded="отказ только по отсутствию TVL",
            detail=detail + " — отказывает не «незнакомое имя», а отсутствие "
                            "живого TVL; имя в снимке финансируется без вопроса "
                            "о том, знает ли его реестр")
    return _probe("unknown_protocol", "unknown protocol", _DOOR_GATE, PROCEEDS,
                  healthy="капитал двигается", degraded="капитал двигается",
                  detail=detail)


def _probe_unknown_asset(ctx: dict) -> dict:
    """Актив пула неизвестен — путь решения о нём вообще не спрашивает?"""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("unknown_asset", "unknown asset", _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен")
    rows = [dict(r) for r in scene["adapters"]]
    for r in rows:
        if r["protocol"] == "pendle":
            r["asset"] = "ASSET_NOBODY_DECLARED"
    gate = _call_gate(scene, rows)
    moved = _gate_moves_capital(scene, gate)
    detail = (f"поле актива подменено на незнакомое: капитал двигается={moved}; "
              f"нарушений {len(gate.get('violations') or [])}, "
              f"предупреждений {len(gate.get('warnings') or [])}")
    if moved:
        return _probe("unknown_asset", "unknown asset", _DOOR_GATE, PROCEEDS,
                      healthy="капитал двигается", degraded="капитал двигается",
                      detail=detail + " — актив пула гейтом не спрашивается ни "
                                      "разу: подменить его нечем, потому что "
                                      "двери нет")
    return _probe("unknown_asset", "unknown asset", _DOOR_GATE, REFUSES,
                  healthy="капитал двигается", degraded="отказ", detail=detail)


def _probe_price_uncertainty(ctx: dict) -> dict:
    """Число пришло, но оно не число: NaN в ставке и в TVL."""
    scene = ctx["gate_scene"]
    healthy = _call_gate(scene, scene["adapters"])
    if not _gate_moves_capital(scene, healthy):
        return _probe("price_uncertainty", "price uncertainty", _DOOR_GATE, UNCHECKED,
                      reason="положительный контроль не установлен")
    results = {}
    for field in ("apy_pct", "tvl_usd"):
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r[field] = float("nan")
        g = _call_gate(scene, rows)
        results[field] = _gate_moves_capital(scene, g)
    detail = "; ".join(f"{k}=NaN: капитал двигается={v}" for k, v in results.items())
    if any(results.values()):
        return _probe("price_uncertainty", "price uncertainty", _DOOR_GATE, PROCEEDS,
                      healthy="капитал двигается", degraded="капитал двигается",
                      detail=detail)
    return _probe("price_uncertainty", "price uncertainty", _DOOR_GATE, REFUSES,
                  healthy="капитал двигается",
                  degraded="нарушение «non-finite» → approved=False", detail=detail)


_DOOR_GATE = "spa_core.paper_trading.risk_gate._apply_risk_policy_gate"
_DOOR_ECON = "spa_core.allocator.rebalance_economics.evaluate"

_PROBES: tuple[tuple[str, Callable[[dict], dict]], ...] = (
    ("missing_apy", _probe_missing_apy),
    ("stale_data", _probe_stale_data),
    ("conflicting_sources", _probe_conflicting_sources),
    ("missing_liquidity", _probe_missing_liquidity),
    ("simulation_failure", _probe_simulation_failure),
    ("risk_service_unavailable", _probe_risk_service_unavailable),
    ("unknown_tier", _probe_unknown_tier),
    ("unknown_protocol", _probe_unknown_protocol),
    ("unknown_asset", _probe_unknown_asset),
    ("price_uncertainty", _probe_price_uncertainty),
)


def _simulation_step_probe(root: str) -> dict:
    """Есть ли в paper-пути решения шаг симуляции сделки.

    Вопрос отдельный: «нет двери» и «дверь есть, но проба над ней не
    построена» — разные ответы, и второй нельзя выдавать за первый.
    """
    target = os.path.join(root, "spa_core", "paper_trading", "cycle_runner.py")
    try:
        with open(target, "r", encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        return {"present": None, "reason": f"цикл не прочитан ({exc})"}
    imports_execution = "spa_core.execution" in src
    return {
        "present": bool(imports_execution),
        "door": "spa_core.execution" if imports_execution else "",
        "reason": ("живой цикл не импортирует spa_core/execution"
                   if not imports_execution
                   else "живой цикл ссылается на spa_core/execution"),
    }


def run(*, root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True) -> dict:
    """Прогнать десять проб §47 и записать отчёт."""
    now = now or dt.datetime.now(dt.timezone.utc)
    from spa_core.allocator.rebalance_economics import TriggerParams

    caps = _policy_caps()
    params = TriggerParams()          # paper-колонка ADR-060; порог не наш
    ctx = {
        "caps": caps,
        "params": params,
        "gate_scene": _gate_scene(caps),
        "econ_scene_buy": _econ_scene_buy(params),
        "econ_scene_exit": _econ_scene_exit(params),
        "simulation_step": _simulation_step_probe(root),
    }

    probes: list[dict] = []
    for key, fn in _PROBES:
        verbatim = dict(OWNER_CONDITIONS)[key]
        try:
            probes.append(fn(ctx))
        except Exception as exc:  # noqa: BLE001 — упавшая проба это UNCHECKED
            door = _DOOR_ECON if key in ("missing_apy", "stale_data") else _DOOR_GATE
            probes.append(_probe(key, verbatim, door, UNCHECKED,
                                 reason=f"проба не выполнена: {type(exc).__name__}: {exc}"))

    findings, unchecked = _findings(probes)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    overall = ("CRITICAL" if counts["critical"]
               else "WARN" if counts["warn"]
               else "UNCHECKED" if counts["unchecked"]
               else "OK")
    tally = {o: sum(1 for p in probes if p["outcome"] == o)
             for o in (REFUSES, PARTIAL, PROCEEDS, UNCHECKED)}
    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "owner_criterion": ("§47 ТЗ «Portfolio CIO»: при перечисленных деградациях "
                            "НЕ выполнять automatic rebalance — DEFER или "
                            "соответствующее safe состояние"),
        "conditions_total": len(OWNER_CONDITIONS),
        "tally": tally,
        "thresholds_provenance": {
            "concentration_caps_and_tvl_floor": caps["source"],
            "gain_band_and_horizon": ("spa_core.allocator.rebalance_economics."
                                      f"TriggerParams (mode={params.mode}, "
                                      f"version={params.version})"),
        },
        "probes": probes,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: ни одна дверь не строится и не двигается этим "
                     "модулем — добавить отказ в путь решения значит изменить "
                     "путь, по которому двигается капитал, это money-path и "
                     "решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _findings(probes: list[dict]) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []
    proceeds = [p for p in probes if p["outcome"] == PROCEEDS]
    partial = [p for p in probes if p["outcome"] == PARTIAL]
    refuses = [p for p in probes if p["outcome"] == REFUSES]

    for p in proceeds:
        findings.append({
            "severity": "CRITICAL",
            "code": f"no_refusal:{p['condition']}",
            "message": (f"условие владельца «{p['owner_wording']}» НЕ отказывает: "
                        f"на здоровом входе {p['healthy_verdict']}, после одной "
                        f"деградации {p['degraded_verdict']}. {p['detail']}"),
        })
    for p in partial:
        findings.append({
            "severity": "WARN",
            "code": f"partial_refusal:{p['condition']}",
            "message": (f"условие владельца «{p['owner_wording']}» отказывает НЕ на "
                        f"всей поверхности: {p['detail']}"),
        })
    for p in probes:
        if p["outcome"] == UNCHECKED:
            unchecked.append(f"{p['owner_wording']}: {p['unchecked_reason']}")

    if proceeds or partial:
        findings.append({
            "severity": "CRITICAL" if proceeds else "WARN",
            "code": "coverage",
            "message": (f"из {len(OWNER_CONDITIONS)} названных владельцем деградаций "
                        f"путь решения отказывает на {len(refuses)}; частично — на "
                        f"{len(partial)}; НЕ отказывает на {len(proceeds)}; "
                        f"не измерено — {len(unchecked)}"),
        })
    if refuses:
        findings.append({
            "severity": "INFO",
            "code": "refusals_that_work",
            "message": ("отказывают как требует §47: "
                        + ", ".join(f"«{p['owner_wording']}»" for p in refuses)),
        })
    return findings, unchecked


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    c = doc["counts"]
    print(f"cio_failure_modes: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    for p in doc["probes"]:
        print(f"  {p['outcome']:9s} «{p['owner_wording']}» — "
              f"{p['detail'] or p['unchecked_reason']}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
