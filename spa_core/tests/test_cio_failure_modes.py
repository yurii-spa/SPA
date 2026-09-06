"""Тесты §47 ТЗ CIO — «отказывает ли путь решения на деградации входа».

Каждый тест ниже — положительный контроль на РЕАЛЬНОЕ поведение живых функций
(``_apply_risk_policy_gate`` и ``rebalance_economics.evaluate``), а не на
формулировки отчёта. Проверка, которая читала бы только свой же вывод, была бы
украшением: она осталась бы зелёной, даже если бы путь решения починили или
сломали.

FROZEN-DATE-OK: injected-clock — единственная отметка времени в отчёте
приходит параметром ``now=`` в :func:`run`; стенных часов тест не спрашивает.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import cio_failure_modes as M

_NOW = dt.datetime(2026, 9, 6, 12, 0, tzinfo=dt.timezone.utc)


def _ctx():
    from spa_core.allocator.rebalance_economics import TriggerParams
    caps = M._policy_caps()
    params = TriggerParams()
    return {
        "caps": caps,
        "params": params,
        "gate_scene": M._gate_scene(caps),
        "econ_scene_buy": M._econ_scene_buy(params),
        "econ_scene_exit": M._econ_scene_exit(params),
        "simulation_step": M._simulation_step_probe(M.REPO_ROOT),
    }


class TestScenesArePositiveControls(unittest.TestCase):
    """Без здорового вердикта любая проба доказывает ноль."""

    def test_gate_scene_moves_capital_when_everything_is_observed(self):
        ctx = _ctx()
        scene = ctx["gate_scene"]
        gate = M._call_gate(scene, scene["adapters"])
        self.assertTrue(
            M._gate_moves_capital(scene, gate),
            f"здоровая сцена гейта обязана двигать капитал, получено "
            f"approved={gate['approved']} err={gate['error']} "
            f"target={gate['target_usd']}")

    def test_buy_scene_is_ACT_when_everything_is_observed(self):
        ctx = _ctx()
        d = M._call_econ(ctx["econ_scene_buy"], ctx["params"])
        self.assertEqual(d.decision, "ACT", d.reasons)

    def test_exit_scene_is_HOLD_on_full_data(self):
        """Обратный контроль: без него «стало ACT» ничего не значило бы."""
        ctx = _ctx()
        d = M._call_econ(ctx["econ_scene_exit"], ctx["params"])
        self.assertEqual(d.decision, "HOLD", d.reasons)
        self.assertLess(d.gain_pp, float(ctx["params"].min_gain_pp))

    def test_scene_thresholds_are_borrowed_not_invented(self):
        """Доли сцены выведены из настоящих потолков, а не записаны числом."""
        caps = M._policy_caps()
        scene = M._gate_scene(caps)
        cap = scene["capital_usd"]
        self.assertLess(scene["target"]["aave_v3"] / cap, caps["t1_frac"] + 1e-9)
        self.assertLess(scene["target"]["pendle"] / cap, caps["t2_frac"] + 1e-9)
        for row in scene["adapters"]:
            self.assertGreater(row["tvl_usd"], caps["tvl_floor_usd"])


class TestTheDefectItself(unittest.TestCase):
    """Находка воспроизводится на ЖИВОЙ функции, а не на своём отчёте."""

    def test_losing_the_apy_of_an_exited_pool_TURNS_hold_into_act(self):
        ctx = _ctx()
        scene, params = ctx["econ_scene_exit"], ctx["params"]
        healthy = M._call_econ(scene, params)
        self.assertEqual(healthy.decision, "HOLD", healthy.reasons)
        apy = dict(scene["apy"])
        apy.pop(scene["degraded_protocol"])
        ev = set(scene["evidenced"]) - {scene["degraded_protocol"]}
        degraded = M._call_econ(scene, params, apy=apy, evidenced=ev)
        self.assertEqual(
            degraded.decision, "ACT",
            "пропажа ставки у покидаемого пула обязана быть воспроизводимой: "
            f"получено {degraded.decision} ({degraded.reasons})")
        self.assertGreater(degraded.gain_pp, healthy.gain_pp,
                           "деградация обязана УВЕЛИЧИВАТЬ выгоду хода")

    def test_unknown_tier_gets_a_cap_instead_of_a_refusal(self):
        ctx = _ctx()
        scene = ctx["gate_scene"]
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r["tier"] = "T_UNKNOWN_TIER"
        gate = M._call_gate(scene, rows)
        self.assertTrue(M._gate_moves_capital(scene, gate),
                        "замер §47: незнакомый тир сегодня НЕ отказывает — "
                        "если это починили, тест обязан покраснеть и вердикт "
                        "модуля обязан стать REFUSES")

    def test_two_rows_about_one_pool_are_decided_by_ORDER(self):
        ctx = _ctx()
        scene, floor = ctx["gate_scene"], ctx["caps"]["tvl_floor_usd"]
        head = [r for r in scene["adapters"] if r["protocol"] != "pendle"]
        live = M._row("pendle", 9.0, floor * 16.0, "T2")
        stat = M._row("pendle", 9.0, floor * 16.0, "T2", tvl_source="static")
        a = M._gate_moves_capital(scene, M._call_gate(scene, head + [stat, live]))
        b = M._gate_moves_capital(scene, M._call_gate(scene, head + [live, stat]))
        self.assertNotEqual(a, b, "спор двух источников сегодня решается порядком "
                                  "строк; если это починили — вердикт модуля "
                                  "обязан измениться вместе с тестом")

    def test_asset_field_is_never_asked(self):
        ctx = _ctx()
        scene = ctx["gate_scene"]
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r["asset"] = "ASSET_NOBODY_DECLARED"
        gate = M._call_gate(scene, rows)
        self.assertTrue(M._gate_moves_capital(scene, gate))


class TestDoorsThatDoWork(unittest.TestCase):
    """Три двери §47 держат — и это утверждение тоже обязано быть проверяемым."""

    def test_missing_liquidity_freezes_the_pool_at_held(self):
        ctx = _ctx()
        scene = ctx["gate_scene"]
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r["tvl_source"] = "static"
        gate = M._call_gate(scene, rows)
        self.assertIn("pendle", gate["tvl_unverified"])
        self.assertAlmostEqual(float(gate["target_usd"]["pendle"]),
                               float(scene["held"]["pendle"]), places=2)
        self.assertFalse(M._gate_moves_capital(scene, gate))

    def test_risk_service_unavailable_is_fail_closed(self):
        ctx = _ctx()
        scene = ctx["gate_scene"]
        saved = sys.modules.get("spa_core.risk.policy")
        sys.modules["spa_core.risk.policy"] = None
        try:
            gate = M._call_gate(scene, scene["adapters"])
        finally:
            if saved is None:
                sys.modules.pop("spa_core.risk.policy", None)
            else:
                sys.modules["spa_core.risk.policy"] = saved
        self.assertFalse(gate["approved"])
        self.assertIsNotNone(gate["error"])

    def test_non_finite_numbers_are_a_violation(self):
        ctx = _ctx()
        scene = ctx["gate_scene"]
        for field in ("apy_pct", "tvl_usd"):
            rows = [dict(r) for r in scene["adapters"]]
            for r in rows:
                if r["protocol"] == "pendle":
                    r[field] = float("nan")
            gate = M._call_gate(scene, rows)
            self.assertFalse(gate["approved"], field)


class TestReportShape(unittest.TestCase):

    def setUp(self):
        self.doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)

    def test_every_owner_condition_is_probed_exactly_once(self):
        got = [p["condition"] for p in self.doc["probes"]]
        self.assertEqual(got, [k for k, _ in M.OWNER_CONDITIONS])

    def test_owner_wording_is_reproduced_verbatim(self):
        for key, verbatim in M.OWNER_CONDITIONS:
            probe = next(p for p in self.doc["probes"] if p["condition"] == key)
            self.assertEqual(probe["owner_wording"], verbatim)

    def test_every_outcome_is_one_of_the_four(self):
        for p in self.doc["probes"]:
            self.assertIn(p["outcome"],
                          (M.REFUSES, M.PARTIAL, M.PROCEEDS, M.UNCHECKED))

    def test_unchecked_always_carries_a_named_reason(self):
        for p in self.doc["probes"]:
            if p["outcome"] == M.UNCHECKED:
                self.assertTrue(p["unchecked_reason"].strip(),
                                f"{p['condition']}: «не измерено» без причины — "
                                "это скип, а не третий исход")
        self.assertEqual(len(self.doc["unchecked"]),
                         self.doc["counts"]["unchecked"])

    def test_tally_sums_to_the_owners_ten(self):
        self.assertEqual(sum(self.doc["tally"].values()),
                         self.doc["conditions_total"])
        self.assertEqual(self.doc["conditions_total"], len(M.OWNER_CONDITIONS))

    def test_a_proceeds_outcome_is_CRITICAL_not_a_note(self):
        proceeds = [p for p in self.doc["probes"] if p["outcome"] == M.PROCEEDS]
        codes = {f["code"] for f in self.doc["findings"]
                 if f["severity"] == "CRITICAL"}
        for p in proceeds:
            self.assertIn(f"no_refusal:{p['condition']}", codes)

    def test_thresholds_name_their_owner(self):
        prov = self.doc["thresholds_provenance"]
        self.assertIn("RiskConfig", prov["concentration_caps_and_tvl_floor"])
        self.assertIn("TriggerParams", prov["gain_band_and_horizon"])

    def test_generated_at_comes_from_the_injected_clock(self):
        self.assertEqual(self.doc["generated_at"], _NOW.isoformat())

    def test_overall_is_critical_while_any_condition_proceeds(self):
        if self.doc["counts"]["critical"]:
            self.assertEqual(self.doc["overall"], "CRITICAL")

    def test_advisory_says_the_money_path_is_untouched(self):
        self.assertIn("money-path", self.doc["advisory"])


class TestHermeticity(unittest.TestCase):

    def test_run_writes_only_its_own_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
            M.run(root=tmp, now=_NOW, write=True)
            self.assertEqual(sorted(os.listdir(os.path.join(tmp, "data"))),
                             ["cio_failure_modes.json"])

    def test_probes_do_not_touch_the_live_state_directory(self):
        """Гейт читает реестр из ddir — проба обязана давать ему СВОЙ каталог."""
        live = Path(M.REPO_ROOT) / "data"
        before = {p.name: p.stat().st_mtime for p in live.glob("*.json")} \
            if live.exists() else {}
        M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        after = {p.name: p.stat().st_mtime for p in live.glob("*.json")} \
            if live.exists() else {}
        self.assertEqual(before, after, "проба тронула живое состояние")

    def test_artifact_is_json_serialisable(self):
        doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        json.loads(json.dumps(doc, ensure_ascii=False))


class TestPositiveControlCannotBeSkipped(unittest.TestCase):
    """Если положительный контроль сорван, исход обязан стать UNCHECKED."""

    def test_a_scene_that_does_not_move_capital_yields_unchecked(self):
        ctx = _ctx()
        # Ломаем сцену так, что здоровый вход УЖЕ не двигает капитал.
        ctx["gate_scene"] = dict(ctx["gate_scene"])
        ctx["gate_scene"]["target"] = {"aave_v3": 10 * M._SCENE_CAPITAL_USD}
        out = M._probe_unknown_tier(ctx)
        self.assertEqual(out["outcome"], M.UNCHECKED)
        self.assertIn("положительный контроль", out["unchecked_reason"])

    def test_a_failing_probe_becomes_unchecked_not_a_pass(self):
        saved = M._PROBES
        def boom(_ctx):
            raise RuntimeError("проба сломана")
        M._PROBES = (("unknown_asset", boom),)
        try:
            doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        finally:
            M._PROBES = saved
        self.assertEqual(doc["probes"][0]["outcome"], M.UNCHECKED)
        self.assertIn("проба сломана", doc["probes"][0]["unchecked_reason"])
        self.assertNotEqual(doc["overall"], "OK")


class TestVerdictAgreesWithTheLiveCode(unittest.TestCase):
    """Отчёт не имеет права расходиться с поведением живых функций.

    Без этих проверок модуль мог бы напечатать REFUSES на всех десяти
    условиях, ничего не измерив, — и остальные тесты остались бы зелёными.
    """

    def setUp(self):
        self.doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        self.ctx = _ctx()

    def _verdict(self, key):
        return next(p["outcome"] for p in self.doc["probes"]
                    if p["condition"] == key)

    def test_unknown_tier_verdict_matches_the_gate(self):
        scene = self.ctx["gate_scene"]
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r["tier"] = "T_UNKNOWN_TIER"
        moves = M._gate_moves_capital(scene, M._call_gate(scene, rows))
        self.assertEqual(self._verdict("unknown_tier"),
                         M.PROCEEDS if moves else M.REFUSES)

    def test_unknown_asset_verdict_matches_the_gate(self):
        scene = self.ctx["gate_scene"]
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r["asset"] = "ASSET_NOBODY_DECLARED"
        moves = M._gate_moves_capital(scene, M._call_gate(scene, rows))
        self.assertEqual(self._verdict("unknown_asset"),
                         M.PROCEEDS if moves else M.REFUSES)

    def test_missing_liquidity_verdict_matches_the_gate(self):
        scene = self.ctx["gate_scene"]
        rows = [dict(r) for r in scene["adapters"]]
        for r in rows:
            if r["protocol"] == "pendle":
                r["tvl_source"] = "static"
        moves = M._gate_moves_capital(scene, M._call_gate(scene, rows))
        self.assertEqual(self._verdict("missing_liquidity"),
                         M.PROCEEDS if moves else M.REFUSES)

    def test_price_uncertainty_verdict_matches_the_gate(self):
        scene = self.ctx["gate_scene"]
        moved = []
        for field in ("apy_pct", "tvl_usd"):
            rows = [dict(r) for r in scene["adapters"]]
            for r in rows:
                if r["protocol"] == "pendle":
                    r[field] = float("nan")
            moved.append(M._gate_moves_capital(scene, M._call_gate(scene, rows)))
        self.assertEqual(self._verdict("price_uncertainty"),
                         M.PROCEEDS if any(moved) else M.REFUSES)

    def test_missing_apy_verdict_matches_the_economics(self):
        params = self.ctx["params"]
        ex = self.ctx["econ_scene_exit"]
        apy = dict(ex["apy"]); apy.pop(ex["degraded_protocol"])
        ev = set(ex["evidenced"]) - {ex["degraded_protocol"]}
        flipped = M._call_econ(ex, params, apy=apy, evidenced=ev).decision == "ACT"
        if flipped:
            self.assertEqual(self._verdict("missing_apy"), M.PROCEEDS)
        else:
            self.assertIn(self._verdict("missing_apy"),
                          (M.REFUSES, M.PARTIAL, M.UNCHECKED))


class TestTheGuardNoticesAFix(unittest.TestCase):
    """Если дверь ПОСТРОЯТ, вердикт обязан измениться сам."""

    def test_a_gate_that_refuses_unknown_tiers_turns_the_verdict_to_refuses(self):
        import spa_core.paper_trading.risk_gate as RG
        real = RG._apply_risk_policy_gate
        known = {"T1", "T2", "T3"}

        def patched(target_usd, capital_usd, adapters, **kw):
            out = real(target_usd, capital_usd, adapters, **kw)
            for a in adapters:
                if isinstance(a, dict) and a.get("tier") not in known:
                    out = dict(out)
                    out["approved"] = False
                    out["violations"] = list(out.get("violations") or []) + [
                        f"{a.get('protocol')}: unknown tier {a.get('tier')!r}"]
                    break
            return out

        RG._apply_risk_policy_gate = patched
        try:
            doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        finally:
            RG._apply_risk_policy_gate = real
        outcome = next(p["outcome"] for p in doc["probes"]
                       if p["condition"] == "unknown_tier")
        self.assertEqual(outcome, M.REFUSES,
                         "починенная дверь обязана быть ЗАМЕЧЕНА замером, "
                         "иначе он мерит не поведение, а свой текст")


class TestHolesFoundByMutation(unittest.TestCase):
    """Четыре проверки, каждая закрывает мутацию, которая СНАЧАЛА молчала.

    Молчащая мутация — дыра теста, а не повод её править: ниже закрыты именно
    дыры, поведение субъекта не тронуто.
    """

    def test_the_probe_hands_the_gate_a_fresh_empty_directory(self):
        """M03. Гейт читает реестр из ``ddir`` — каталог обязан быть СВОИМ.

        Проверяется ФОРМА вызова, а не следствие: сверка времён файлов на этот
        вопрос не отвечала (живой ``data/`` гейт только читает), а сравнение
        двух прогонов — тем более, потому что при подмене оба читали бы ОДИН
        и тот же живой каталог и честно совпали бы.
        """
        import spa_core.paper_trading.risk_gate as RG
        real = RG._apply_risk_policy_gate
        seen: list[tuple] = []

        def spy(target_usd, capital_usd, adapters, **kw):
            ddir = Path(kw.get("ddir"))
            # Каталог живёт только внутри вызова — судить о нём надо ЗДЕСЬ.
            seen.append((ddir, sorted(x.name for x in ddir.iterdir())))
            return real(target_usd, capital_usd, adapters, **kw)

        RG._apply_risk_policy_gate = spy
        try:
            M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        finally:
            RG._apply_risk_policy_gate = real
        self.assertTrue(seen, "ни одна проба не позвала гейт")
        repo = Path(M.REPO_ROOT).resolve()
        for ddir, contents in seen:
            self.assertNotIn(repo, ddir.resolve().parents,
                             f"проба ходит в дерево репозитория: {ddir}")
            self.assertEqual(contents, [], f"каталог пробы не пуст: {ddir}")

    def test_moves_capital_treats_a_named_error_as_a_refusal(self):
        """M07. Ветка ``error`` избыточна на сегодняшнем субъекте — но она

        описывает контракт гейта («упал ⇒ не двигаемся»), и проверять её надо
        прямо, а не надеяться, что субъект заодно скажет ``approved=False``.
        """
        scene = _ctx()["gate_scene"]
        broken = {"approved": True, "error": "boom",
                  "target_usd": dict(scene["target"]), "tvl_unverified": []}
        self.assertFalse(M._gate_moves_capital(scene, broken))

    def test_buy_side_names_the_gates_that_closed(self):
        """M17. «Отказал» без имени двери не отличает одну дверь от другой."""
        doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)
        probe = next(p for p in doc["probes"] if p["condition"] == "missing_apy")
        ctx = _ctx()
        scene, params = ctx["econ_scene_buy"], ctx["params"]
        ev = set(scene["evidenced"]) - {scene["degraded_protocol"]}
        closed = sorted(k for k, v in
                        (M._call_econ(scene, params, evidenced=ev).gates or {}).items()
                        if not v)
        self.assertTrue(closed, "деградированный вход обязан закрыть хоть один гейт")
        self.assertIn("target_fully_evidenced", closed,
                      "ненаблюдаемая цель обязана закрывать СВОЙ гейт ADR-060, "
                      "а не только опускать выгоду")
        self.assertIn(str(closed), probe["detail"],
                      "отчёт обязан называть закрывшиеся гейты поимённо")

    def test_stale_source_alone_flips_the_exit_side(self):
        """M18. Значение НА МЕСТЕ, не живёт только источник — и ход возникает.

        Отличает правило «ненаблюдаемое = 0» от банального отсутствия числа:
        удалять ставку тут нельзя, иначе проба перестаёт различать причины.
        """
        ctx = _ctx()
        scene, params = ctx["econ_scene_exit"], ctx["params"]
        healthy = M._call_econ(scene, params)
        self.assertEqual(healthy.decision, "HOLD", healthy.reasons)
        ev = set(scene["evidenced"]) - {scene["degraded_protocol"]}
        degraded = M._call_econ(scene, params, evidenced=ev)
        self.assertIn(scene["degraded_protocol"], scene["apy"],
                      "значение ставки обязано остаться на месте")
        self.assertEqual(degraded.decision, "ACT",
                         "сегодня протухший источник у покидаемого пула СОЗДАЁТ "
                         f"ход; получено {degraded.decision} ({degraded.reasons})")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
