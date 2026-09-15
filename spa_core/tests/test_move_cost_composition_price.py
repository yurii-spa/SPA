"""Приёмка прибора «цена СОСТАВА хода» (заказ #608/G21, ADR-389).

Каждый тест здесь — либо ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (сцена, на которой прибор обязан
сказать «да», рядом со сценой, на которой он обязан сказать «нет»), либо сторож
притязания, которое прибор произносит о себе вслух. Притязание без сторожа уже
однажды оказалось ложным ([ADR-387]: «этот прибор только читает» не краснело ни
на одном тесте, а судья писал в каталог, который прибор обещал не трогать).

Отдельный класс сторожей — ТРЕТИЙ ИСХОД. Прибор обязан различать «состав измерен»,
«состав измерен и разошёлся» и «состав НЕ измерен», и последнее не имеет права
складываться ни с первым, ни со вторым (инв. #17). Обе причины третьего исхода
(ног не записали · сеть ноги неизвестна) проверяются на сценах, где оценщик
МОЛЧА выдал бы число, — иначе сторож проверял бы отсутствие соблазна.

Часы инъектируются. FROZEN-DATE-OK: injected-clock — все даты происходят от
_NOW/_ANCHOR и подаются в measure(now=)/run(now=); стенных часов в файле нет.
"""
# FROZEN-DATE-OK: injected-clock — `_NOW` и производный от него `_ANCHOR`
# подаются в `measure(now=...)`; обе стороны закреплены одним якорем,
# стенных часов в файле нет (ADR-395).

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import move_cost_composition_price as M
from spa_core.monitoring import criterion_sign_price as C
from spa_core.paper_trading import shadow_trigger_eval as ste
from spa_core.allocator.rebalance_economics import _move_cost_usd
from spa_core.backtesting.tier1.cost_model import (
    GAS_USD_PER_POSITION_CHANGE, SLIPPAGE_BPS_STABLE, BRIDGE_BPS)

_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
_ANCHOR = _NOW - timedelta(days=60)

_GATES = sorted(g for g in ste._ALL_GATES if g != "has_legs")
_REASON_OF = {gate: reason for reason, gate in ste.GATE_BY_REASON_PREFIX.items()}

#: Карта сетей сцены. Две сети нужны обе: мост заряжается ТОЛЬКО когда их больше
#: одной, и сцена с одной сетью проверяла бы половину правила.
_CHAINS = {"a": "ethereum", "b": "base", "c": "ethereum"}


def _day(offset: int) -> str:
    return (_ANCHOR + timedelta(days=offset)).date().isoformat()


def _legs_of(current: dict, target: dict) -> list:
    out = []
    for p in sorted(set(current) | set(target)):
        d = float(target.get(p, 0.0)) - float(current.get(p, 0.0))
        if abs(d) > 0.005:
            out.append({"protocol": p, "delta_usd": round(d, 2),
                        "direction": "increase" if d > 0 else "decrease"})
    return out


def _turnover_of(legs: list) -> float:
    ups = sum(l["delta_usd"] for l in legs if l["delta_usd"] > 0)
    downs = sum(-l["delta_usd"] for l in legs if l["delta_usd"] < 0)
    return max(ups, downs)


def _record(offset: int, *, refused=(), current=None, target=None, apy=None,
            cost_usd=None, with_legs=True, verdict="HOLD",
            capital=100_000.0) -> dict:
    """Строка журнала решений в той форме, в какой её читает судья.

    Цена по умолчанию — ТА, которую записал бы сам оценщик: сцена, где запись
    и модель расходятся, обязана расходиться НАМЕРЕННО, а не из-за фикстуры.
    """
    current = dict(current or {})
    target = dict(target or {})
    legs = _legs_of(current, target)
    turnover = _turnover_of(legs)
    rec = {
        "schema": "shadow-hist-v2",
        "cycle_date": _day(offset),
        "generated_at": (_ANCHOR + timedelta(days=offset)).isoformat(),
        "verdict": verdict,
        "capital_usd": capital,
        "current_positions": current,
        "target_positions": target,
        "apy_evidenced_pct": dict(apy or {}),
        "reasons": [_REASON_OF[g] for g in refused],
    }
    if legs:
        rec["turnover_usd"] = round(turnover, 2)
        if with_legs:
            rec["legs"] = legs
        rec["cost_usd"] = (round(_move_cost_usd(legs, turnover, _CHAINS), 2)
                           if cost_usd is None else cost_usd)
    return rec


class _Scene:
    """Одноразовый каталог данных: живое `data/` этими тестами не касается."""

    def __init__(self, records, *, chains=None):
        self.dir = Path(tempfile.mkdtemp(prefix="mccp_test_"))
        (self.dir / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8")
        reg = {"adapters": {p: {"chain": ch}
                            for p, ch in (chains if chains is not None
                                          else _CHAINS).items()}}
        (self.dir / "adapter_registry.json").write_text(
            json.dumps(reg), encoding="utf-8")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def fingerprint(self) -> dict:
        """Содержимое каталога пофайлово — для сторожа «на запись не открываем»."""
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.dir.iterdir()) if p.is_file()}


def _scene(*, moves, chains=None, with_legs=True):
    """Сцена из ходов a→b: за днём хода идут семь дней-носителей ставки.

    ``moves`` — список ``(refused_gates, delta_usd, apy_at_decision,
    apy_forward, cost_usd)``. Полный горизонт нужен, иначе сцена мерила бы
    пробелы вперёд вместо того, ради чего написана.
    """
    records = []
    offset = 0
    for refused, delta, apy_now, apy_fwd, cost in moves:
        records.append(_record(
            offset, refused=refused,
            current={"a": 50_000.0, "b": 0.0},
            target={"a": 50_000.0 - delta, "b": delta},
            apy=dict(apy_now), cost_usd=cost, with_legs=with_legs))
        for k in range(1, 8):
            records.append(_record(offset + k, apy=dict(apy_fwd)))
        offset += 8
    return _Scene(records, chains=chains)


def _days_of(scene: _Scene):
    days, ctx = C.scorable_days(scene.dir)
    rows, order = M.journal_by_date(scene.dir)
    return days, ctx, rows, order


# ─────────────────────────── (а) состав и воспроизведение ──────────────────────
class CostComposition(unittest.TestCase):

    def setUp(self):
        self.scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0}, {"a": 4.0, "b": 9.0}, None),
            (("gain_above_band",), 5_000.0, {"a": 4.0, "b": 9.0}, {"a": 4.0, "b": 9.0}, None),
        ])
        self.addCleanup(self.scene.close)
        self.days, self.ctx, self.rows, self.order = _days_of(self.scene)
        self.chains, _src = M.chain_map(self.scene.dir)

    def test_the_scene_actually_produced_scorable_days(self):
        """Предпосылка сцены — измерена, а не предположена."""
        self.assertEqual(len(self.days), 2, self.ctx)

    def test_a_cost_written_by_the_estimator_is_reproduced_to_the_cent(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: запись и модель совпадают ⇒ так и сказано."""
        out = M.compose(self.days, self.rows, self.chains)
        self.assertEqual(out["days_reproduced"], 2)
        self.assertEqual(out["days_divergent"], 0)
        self.assertEqual(out["days_unmeasured"], 0)
        self.assertTrue(out["recorded_cost_is_the_estimator"])
        self.assertLessEqual(out["max_abs_diff_usd"], M.CENT)

    def test_a_cost_that_diverges_is_named_and_not_absorbed(self):
        """ОБРАТНАЯ СЦЕНА: цена сдвинута на доллар — согласие обязано пропасть."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, 777.0)])
        self.addCleanup(scene.close)
        days, _ctx, rows, _order = _days_of(scene)
        chains, _ = M.chain_map(scene.dir)
        out = M.compose(days, rows, chains)
        self.assertEqual(out["days_divergent"], 1)
        self.assertEqual(out["days_reproduced"], 0)
        self.assertFalse(out["recorded_cost_is_the_estimator"])
        keys = {f["key"] for f in M._findings(out, {"measured": False, "reason": "x"},
                                              {}, SLIPPAGE_BPS_STABLE)}
        self.assertIn("recorded_cost_diverges_from_the_estimator", keys)
        self.assertNotIn("recorded_cost_is_not_an_observation", keys)

    def test_a_day_without_legs_is_a_third_outcome_not_an_agreement(self):
        """Ног не записали ⇒ НЕ ИЗМЕРЕНО: ни в согласие, ни в расхождение."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)], with_legs=False)
        self.addCleanup(scene.close)
        days, _ctx, rows, _order = _days_of(scene)
        chains, _ = M.chain_map(scene.dir)
        out = M.compose(days, rows, chains)
        self.assertEqual(out["days_unmeasured"], 1)
        self.assertEqual(out["days_reproduced"], 0)
        self.assertEqual(out["days_divergent"], 0)
        self.assertFalse(out["recorded_cost_is_the_estimator"])
        row = out["per_day"][0]
        self.assertEqual(row["reason"], "legs_not_recorded")
        # Газ и мост порознь НЕ НАЗЫВАЮТСЯ, а их сумма — измеренная величина.
        self.assertIsNone(row["gas_usd"])
        self.assertIsNone(row["bridge_usd"])
        self.assertIsNotNone(row["gas_plus_bridge_usd"])

    def test_an_unknown_chain_is_a_third_outcome_although_the_estimator_would_answer(self):
        """Сеть ноги неизвестна ⇒ НЕ ИЗМЕРЕНО, хотя оценщик молча дал бы число.

        Контроль соблазна: сперва показываем, что `_move_cost_usd` на пустой
        карте ОТВЕЧАЕТ (подставляя `blended`), и только потом требуем от прибора
        третьего исхода. Без первой половины сторож проверял бы, что соблазна нет.
        """
        legs = [{"protocol": "a", "delta_usd": 1000.0, "direction": "increase"}]
        silent = _move_cost_usd(legs, 1000.0, {})
        self.assertGreater(silent, 0.0)

        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)], chains={"a": "ethereum"})
        self.addCleanup(scene.close)
        days, _ctx, rows, _order = _days_of(scene)
        chains, _ = M.chain_map(scene.dir)
        out = M.compose(days, rows, chains)
        self.assertEqual(out["days_unmeasured"], 1)
        self.assertEqual(out["per_day"][0]["reason"], "chain_unknown:b")
        self.assertIsNone(out["per_day"][0]["cost_usd_recomputed"])

    def test_an_unreadable_chain_map_names_its_reason(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        (scene.dir / "adapter_registry.json").unlink()
        chains, source = M.chain_map(scene.dir)
        self.assertEqual(chains, {})
        self.assertIn("НЕ ПРОЧИТАНА", source)

    def test_slippage_does_not_vary_in_bps_and_gas_does(self):
        """Утверждение шапки — замером: разброс цены держат газ и мост."""
        out = M.compose(self.days, self.rows, self.chains)
        comp = out["component_bps_of_turnover"]
        self.assertEqual(comp["slippage_usd"]["spread"], 0.0)
        self.assertFalse(out["slippage_bps_varies"])
        self.assertGreater(comp["gas_usd"]["spread"], 0.0)
        self.assertEqual(out["widest_bps_component"], "gas_usd")
        self.assertEqual(comp["slippage_usd"]["median"],
                         round(SLIPPAGE_BPS_STABLE, 3))

    def test_component_shares_sum_to_one_and_totals_match_the_recorded_cost(self):
        out = M.compose(self.days, self.rows, self.chains)
        self.assertAlmostEqual(sum(out["component_shares"].values()), 1.0, places=3)
        totals = sum(out["component_totals_usd"].values())
        recorded = sum(r["cost_usd_recorded"] for r in out["per_day"]
                       if r["status"] == "reproduced")
        self.assertAlmostEqual(totals, recorded, places=2)

    def test_bridge_is_charged_only_when_more_than_one_chain_is_touched(self):
        """Обе стороны условия: одна сеть ⇒ моста нет, две ⇒ ровно 5 bps."""
        two = M.compose(self.days, self.rows, self.chains)["per_day"][0]
        self.assertGreater(two["bridge_usd"], 0.0)
        self.assertAlmostEqual(
            two["bridge_usd"],
            round(two["turnover_usd"] * BRIDGE_BPS / 10_000.0, 2), places=2)

        one_chain = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "c": 9.0},
             {"a": 4.0, "c": 9.0}, None)])
        self.addCleanup(one_chain.close)
        recs = []
        for line in (one_chain.dir / "allocation_rationale_history.jsonl") \
                .read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("target_positions", {}).get("b") is not None:
                rec["target_positions"]["c"] = rec["target_positions"].pop("b")
            if rec.get("current_positions", {}).get("b") is not None:
                rec["current_positions"]["c"] = rec["current_positions"].pop("b")
            if rec.get("legs"):
                for leg in rec["legs"]:
                    if leg["protocol"] == "b":
                        leg["protocol"] = "c"
                rec["cost_usd"] = round(
                    _move_cost_usd(rec["legs"], rec["turnover_usd"], _CHAINS), 2)
            recs.append(rec)
        (one_chain.dir / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
            encoding="utf-8")
        days, _ctx, rows, _order = _days_of(one_chain)
        chains, _ = M.chain_map(one_chain.dir)
        row = M.compose(days, rows, chains)["per_day"][0]
        self.assertEqual(row["chains_touched"], ["ethereum"])
        self.assertEqual(row["bridge_usd"], 0.0)
        self.assertEqual(row["status"], "reproduced")

    def test_gas_is_per_leg_and_priced_by_the_owners_table(self):
        row = M.compose(self.days, self.rows, self.chains)["per_day"][0]
        expected = (GAS_USD_PER_POSITION_CHANGE["ethereum"]
                    + GAS_USD_PER_POSITION_CHANGE["base"])
        self.assertEqual(row["legs_recorded"], 2)
        self.assertAlmostEqual(row["gas_usd"], expected, places=2)


class LumpSeparability(unittest.TestCase):
    """Утверждение «газ и мост неразделимы» — ИЗМЕРЕНО, а не заявлено."""

    GAS = {"eth": 12.0, "base": 0.15, "cheap": 0.05}

    def _ask(self, lump, turnover, **kw):
        return M.lump_explanations(lump, turnover, gas_table=self.GAS,
                                   bridge_bps=BRIDGE_BPS, **kw)

    def test_a_lump_with_two_explanations_is_reported_inseparable(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: 24.00 — это И 12+12 на одной сети,
        И 0.15+0.05 на двух плюс мост 23.80 с оборота 47 600 $. Ровно та форма,
        что встречается на живых днях без записанных ног."""
        turnover = 47_600.0
        self.assertAlmostEqual(turnover * BRIDGE_BPS / 10_000.0, 23.8, places=6)
        out = self._ask(24.0, turnover)
        self.assertGreater(out["explanations"], 1)
        self.assertFalse(out["separable"])
        self.assertTrue(any(e["multichain"] for e in out["examples"]))
        self.assertTrue(any(not e["multichain"] for e in out["examples"]))

    def test_a_lump_with_one_explanation_says_so_and_names_the_bound(self):
        """ОБРАТНАЯ СЦЕНА: решение ровно одно — и «единственно» ограничено пределом."""
        out = self._ask(12.0, 0.0, max_legs=1)
        self.assertEqual(out["explanations"], 1)
        self.assertTrue(out["separable"])
        self.assertEqual(out["search_max_legs"], 1)

    def test_a_lump_nothing_explains_is_zero_not_separable(self):
        """Ноль решений — третий исход: «неразделимо» из него НЕ следует."""
        out = self._ask(7.77, 0.0)
        self.assertEqual(out["explanations"], 0)
        self.assertFalse(out["separable"])
        self.assertEqual(out["examples"], [])

    def test_the_bridge_is_offered_only_to_multi_unit_sets(self):
        """Мост не заряжается на одной сети — иначе перебор считал бы решения,
        которых оценщик выдать не может."""
        turnover = 20_000.0
        bridge = turnover * BRIDGE_BPS / 10_000.0
        out = self._ask(12.15 + bridge, turnover)
        self.assertTrue(all(e["multichain"] for e in out["examples"]))
        self.assertTrue(all(len(set(e["gas_units"])) > 1 for e in out["examples"]))

    def test_compose_reports_the_lump_census_for_legless_days(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)], with_legs=False)
        self.addCleanup(scene.close)
        days, _ctx, rows, _order = _days_of(scene)
        chains, _ = M.chain_map(scene.dir)
        out = M.compose(days, rows, chains)
        self.assertEqual(out["lump_search_max_legs"], M.LUMP_SEARCH_MAX_LEGS)
        self.assertEqual(out["lump_ambiguous_days"]
                         + out["lump_single_solution_days"]
                         + out["lump_unexplained_days"], 1)
        self.assertIn("lump", out["per_day"][0])


# ──────────────────── (б) снос ставки против дефекта аллокатора ────────────────
class BenefitBasis(unittest.TestCase):

    def _drift(self, scene):
        days, ctx, rows, order = _days_of(scene)
        return M.benefit_drift(days, rows, order,
                               horizon_days=int(ctx["horizon_days"])), days

    def test_a_move_right_ex_ante_that_the_forward_rate_broke_is_named_drift(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: вера была верна, ставка ушла ⇒ снос, и нога названа."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0,
             {"a": 4.0, "b": 9.0},        # в день решения b много лучше a
             {"a": 4.0, "b": 0.10},       # вперёд b обвалилась
             None)])
        self.addCleanup(scene.close)
        out, _days = self._drift(scene)
        self.assertTrue(out["measured"], out.get("reason"))
        row = out["per_day"][0]
        self.assertLess(row["benefit_usd_observed"], 0.0)
        self.assertGreater(row["benefit_usd_ex_ante"], 0.0)
        self.assertEqual(row["basis"], "forward_rate_drift")
        self.assertEqual(row["worst_drift_leg"], "b")
        self.assertEqual(out["negative_days_by_basis"]["forward_rate_drift"],
                         [row["date"]])

    def test_a_book_already_worse_at_decision_time_is_named_a_defect(self):
        """ОБРАТНАЯ СЦЕНА: по ставкам САМОГО дня цель хуже ⇒ дефект, не снос."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0,
             {"a": 9.0, "b": 1.0},        # уже в день решения b ХУЖЕ a
             {"a": 9.0, "b": 1.0},
             None)])
        self.addCleanup(scene.close)
        out, _days = self._drift(scene)
        self.assertTrue(out["measured"], out.get("reason"))
        row = out["per_day"][0]
        self.assertLess(row["benefit_usd_ex_ante"], 0.0)
        self.assertEqual(row["basis"], "allocator_proposed_a_worse_book")
        keys = {f["key"] for f in M._findings(
            {"recorded_cost_is_the_estimator": False, "days_divergent": 0,
             "days_unmeasured": 0, "days_reproduced": 0, "days_total": 1,
             "cost_usd_recorded_total": 1.0}, out, {}, SLIPPAGE_BPS_STABLE)}
        self.assertIn("allocator_proposed_a_worse_book", keys)

    def test_a_profitable_day_gets_no_basis_at_all(self):
        """Основание не выдумывается там, где объяснять нечего."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        out, _days = self._drift(scene)
        row = out["per_day"][0]
        self.assertGreater(row["benefit_usd_observed"], 0.0)
        self.assertIsNone(row["basis"])
        self.assertEqual(out["negative_benefit_days"], [])

    def test_a_reconstruction_that_disagrees_with_the_judge_refuses(self):
        """Сторож собственного восстановления: расхождение ⇒ секция снята.

        Без него прибор печатал бы слагаемые ЧУЖОГО числа как его разложение.
        """
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        days, ctx, rows, order = _days_of(scene)
        days[0] = dict(days[0], benefit_usd=float(days[0]["benefit_usd"]) + 10.0)
        out = M.benefit_drift(days, rows, order,
                              horizon_days=int(ctx["horizon_days"]))
        self.assertFalse(out["measured"])
        self.assertIn(days[0]["date"], out["reason"])
        self.assertGreater(out["max_abs_diff_usd"], 0.02)

    def test_drift_is_the_difference_between_observed_and_ex_ante(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 6.0}, None)])
        self.addCleanup(scene.close)
        out, _days = self._drift(scene)
        row = out["per_day"][0]
        self.assertAlmostEqual(
            row["drift_usd"],
            round(row["benefit_usd_reconstructed"] - row["benefit_usd_ex_ante"], 2),
            places=2)
        self.assertLess(row["drift_usd"], 0.0)


# ──────────────────────────── (в) сметание уровней цены ───────────────────────
class CostLevelSweep(unittest.TestCase):

    def test_a_cheap_level_returns_act_days_and_the_recorded_one_does_not(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: уровень доходит до судьи и меняет ответ."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 6.0},
             {"a": 4.0, "b": 6.0}, None)])
        self.addCleanup(scene.close)
        _days, ctx, _rows, _order = _days_of(scene)
        out = M.cost_level_sweep(scene.dir, horizon_days=int(ctx["horizon_days"]),
                                 gates=_GATES, median_bps=17.0,
                                 slippage_bps=SLIPPAGE_BPS_STABLE)
        self.assertEqual(out["named"]["as_is"], 0)
        self.assertGreater(out["max_act_days"], 0)
        self.assertTrue(out["sensitivity_control"]["holds"])
        self.assertTrue(out["sensitivity_control"]["binding"])
        flip = out["flip_level_bps"]
        self.assertTrue(flip["measured"], flip.get("reason"))
        self.assertGreater(flip["flip_bps"], M.BPS_BISECT_BRACKET[0])
        self.assertLess(flip["flip_bps"], M.BPS_BISECT_BRACKET[1])
        self.assertEqual(flip["monotonicity_control"]["disagreed"], [])

    def test_the_flip_is_withheld_when_no_level_in_the_bracket_closes(self):
        """ОБРАТНАЯ СЦЕНА: выгода отрицательна при ЛЮБОЙ цене ⇒ перелома нет.

        Край скобки не подставляется: «не найден» печатается словом.
        """
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 9.0, "b": 1.0},
             {"a": 9.0, "b": 1.0}, None)])
        self.addCleanup(scene.close)
        _days, ctx, _rows, _order = _days_of(scene)
        out = M.cost_level_sweep(scene.dir, horizon_days=int(ctx["horizon_days"]),
                                 gates=_GATES, median_bps=None,
                                 slippage_bps=SLIPPAGE_BPS_STABLE)
        flip = out["flip_level_bps"]
        self.assertFalse(flip["measured"])
        self.assertIsNone(flip["flip_bps"])
        self.assertIn("перелом не найден", flip["reason"])

    def test_the_named_levels_include_the_median_only_when_it_exists(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 6.0},
             {"a": 4.0, "b": 6.0}, None)])
        self.addCleanup(scene.close)
        _days, ctx, _rows, _order = _days_of(scene)
        with_median = M.cost_level_sweep(
            scene.dir, horizon_days=int(ctx["horizon_days"]), gates=_GATES,
            median_bps=17.0, slippage_bps=SLIPPAGE_BPS_STABLE)
        self.assertIn("median", with_median["named"])
        without = M.cost_level_sweep(
            scene.dir, horizon_days=int(ctx["horizon_days"]), gates=_GATES,
            median_bps=None, slippage_bps=SLIPPAGE_BPS_STABLE)
        self.assertNotIn("median", without["named"])
        self.assertIn("slippage_only", without["named"])

    def test_a_level_that_never_reaches_the_judge_makes_the_measure_unmeasured(self):
        """Контроль чувствительности связывает: неподключённый рычаг ⇒ НЕ ИЗМЕРЕНО."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 6.0},
             {"a": 4.0, "b": 6.0}, None)])
        self.addCleanup(scene.close)
        original = M._set_bps
        M._set_bps = lambda level: (lambda rec: None)      # рычаг оборван
        try:
            doc = M.measure(scene.dir, now=_NOW)
        finally:
            M._set_bps = original
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
        self.assertIn("не доходит", doc["unmeasured_reason"])


# ───────────────────────── притязания прибора о самом себе ────────────────────
class InstrumentClaims(unittest.TestCase):

    def test_the_data_dir_is_never_opened_for_writing(self):
        """Притязание шапки — сторожем, а не словом ([ADR-387])."""
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        before = scene.fingerprint()
        M.measure(scene.dir, now=_NOW)
        self.assertEqual(scene.fingerprint(), before)

    def test_an_empty_journal_is_unmeasured_not_ok(self):
        scene = _Scene([])
        self.addCleanup(scene.close)
        doc = M.measure(scene.dir, now=_NOW)
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", doc["headline"])

    def test_unmeasured_is_printed_on_the_first_line(self):
        scene = _Scene([])
        self.addCleanup(scene.close)
        lines = M.format_report(M.measure(scene.dir, now=_NOW))
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])

    def test_main_returns_two_on_unmeasured_and_one_on_critical(self):
        empty = _Scene([])
        self.addCleanup(empty.close)
        self.assertEqual(
            M.main(["--data-dir", str(empty.dir), "--no-write"]), 2)

        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        doc = M.measure(scene.dir, now=_NOW)
        self.assertEqual(doc["status"], M.STATUS_CRITICAL, doc["headline"])
        self.assertEqual(
            M.main(["--data-dir", str(scene.dir), "--no-write"]), 1)

    def test_no_write_really_writes_nothing(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        M.main(["--data-dir", str(scene.dir), "--no-write"])
        self.assertFalse((scene.dir / M.OUTPUT_FILENAME).exists())

    def test_writing_is_atomic_and_lands_in_the_named_file(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        M.main(["--data-dir", str(scene.dir)])
        doc = json.loads((scene.dir / M.OUTPUT_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(doc["version"], M.VERSION)
        self.assertIn("G21", doc["order"])

    def test_the_report_names_the_chain_map_as_todays(self):
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        doc = M.measure(scene.dir, now=_NOW)
        self.assertIn("СЕГОДНЯШНЯЯ", doc["chains_source"])
        self.assertTrue(any("СЕГОДНЯШНЯЯ" in line
                            for line in M.format_report(doc)))

    def test_the_constants_are_imported_not_relitteralised(self):
        """Второй копии констант стоимости в приборе нет.

        Проверяется ИСХОДОМ: подменив таблицу газа у её владельца, состав обязан
        измениться. Сравнение с литералом в тексте прибора эту подмену пережило бы.
        """
        scene = _scene(moves=[
            (("cooldown_ok",), 20_000.0, {"a": 4.0, "b": 9.0},
             {"a": 4.0, "b": 9.0}, None)])
        self.addCleanup(scene.close)
        days, _ctx, rows, _order = _days_of(scene)
        chains, _ = M.chain_map(scene.dir)
        base = M.compose(days, rows, chains)["component_totals_usd"]["gas_usd"]

        import spa_core.backtesting.tier1.cost_model as cm
        original = cm.GAS_USD_PER_POSITION_CHANGE
        cm.GAS_USD_PER_POSITION_CHANGE = {k: v * 10.0 for k, v in original.items()}
        try:
            moved = M.compose(days, rows, chains)["component_totals_usd"]["gas_usd"]
        finally:
            cm.GAS_USD_PER_POSITION_CHANGE = original
        self.assertAlmostEqual(moved, base * 10.0, places=2)


if __name__ == "__main__":
    unittest.main()
