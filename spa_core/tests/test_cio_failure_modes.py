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

# FROZEN-DATE-OK: injected-clock — якорь _NOW уходит параметром now= в M.run().
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


class AGateWithoutATargetIsUNCHECKEDNotABlock(unittest.TestCase):
    """ADR-344 (инвариант #17): ноль свежего капитала — вердикт, а не подстановка.

    Пробы читали `(gate.get("target_usd") or {}).get(proto, 0.0)`. Если бы гейт
    вернул ответ без цели вовсе, подстановка дала бы ноль — то есть проба
    доложила бы УСПЕШНЫЙ блок по сломанному ответу. Направление ошибки худшее из
    возможных, поэтому отсутствие цели теперь третий исход с названной причиной.
    """

    def test_a_target_less_gate_is_not_a_move(self):
        self.assertFalse(M._gate_moves_capital({"target": {"a": 1.0}},
                                               {"approved": True, "error": None}))

    def test_the_reader_tells_absence_from_an_empty_target(self):
        self.assertIsNone(M._gate_target({"approved": True}))
        self.assertEqual(M._gate_target({"target_usd": {}}), {})

    def test_an_empty_target_still_reads_as_zero_fresh_capital(self):
        """Обратная сторона: гейт СКАЗАЛ «цели нет» — это ноль, и он измерен."""
        self.assertEqual(float(M._gate_target({"target_usd": {}}).get("pendle", 0.0)), 0.0)


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

    def test_an_unknown_tier_is_now_refused(self):
        """ИЗМЕНЕНО НАМЕРЕННО (ADR-359, инв. #16) — по прямому указанию автора теста.

        Здесь стояло обратное утверждение и текст: «незнакомый тир сегодня НЕ
        отказывает — если это починили, тест обязан покраснеть и вердикт модуля
        обязан стать REFUSES». Починили: решение владельца 12.09 (ADR-357 п. 3),
        `policy_tier` больше не подставляет T2 умолчанием. Утверждение поэтому
        перевёрнуто, а СЦЕНА оставлена дословно — меняется вердикт, не предмет.

        Проверяются ОБА носителя незнания: незнакомое слово и полностью
        отсутствующее поле. Проверять только первый значило бы оставить дыру,
        через которую эта же проба и падала (поле отсутствовало — капитал шёл).
        """
        ctx = _ctx()
        scene = ctx["gate_scene"]
        for label, mutate in (("незнакомое слово", lambda r: r.update(tier="T_UNKNOWN_TIER")),
                              ("поля тира нет вовсе", lambda r: r.pop("tier", None))):
            rows = [dict(r) for r in scene["adapters"]]
            for r in rows:
                if r["protocol"] == "pendle":
                    mutate(r)
            gate = M._call_gate(scene, rows)
            self.assertFalse(M._gate_moves_capital(scene, gate),
                             f"{label}: капитал всё ещё двигается — «не знаем» "
                             f"снова трактуется в пользу сделки")

        # Обратный контроль: со ЗНАКОМЫМ тиром сцена обязана двигать капитал,
        # иначе отказ был бы истинным по построению и ничего не доказывал.
        self.assertTrue(M._gate_moves_capital(scene, M._call_gate(scene, scene["adapters"])),
                        "здоровая сцена перестала двигать капитал — отказ выше "
                        "ничего не значит")

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


# ═══════════════ вторая ось (ADR-992): отказ гейта на пути к записи ═══════════════

def _fake_cycle(root: str, body: str) -> None:
    d = os.path.join(root, "spa_core", "paper_trading")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "cycle_runner.py"), "w", encoding="utf-8") as fh:
        fh.write(body)


_LIVE_LIKE_CYCLE = """
from spa_core.paper_trading.risk_gate import (
    _apply_risk_policy_gate,
    _compliant_target,
)
def run_cycle():
    gate = _apply_risk_policy_gate(target_usd, capital_usd, adapters)
    target_usd = apply_kill_switch_override(target_usd)
    target_usd = apply_soft_derisk_gate(target_usd)
    target_usd, _c = _compliant_target(target_usd, capital_usd, ddir, write)
    target_usd = apply_soft_derisk_gate(target_usd)
    target_usd = apply_rtmr_posture_gate(target_usd)
    from spa_core.paper_trading.pool_alias_gate import apply_pool_alias_gate
    target_usd = apply_pool_alias_gate(target_usd)
    from spa_core.paper_trading.admissible_trim import apply_admissible_trim
    target_usd, _t = apply_admissible_trim(target_usd)
    _cio_doc = write_shadow_rationale(data_dir=ddir, target_positions=target_usd)
    traded = ((not _safety_failed) and (not policy_blocked)
              and diff_usd > threshold_usd)
"""


class TestStageOrderAgainstTheLiveCycle(unittest.TestCase):
    """Объявленный порядок ступеней СВЕРЯЕТСЯ с исходником живого цикла."""

    def test_declared_order_matches_cycle_runner_on_this_tree(self):
        od = M.live_stage_order(M.REPO_ROOT)
        self.assertEqual(od["verdict"], "measured", od.get("reason"))
        self.assertEqual(od["live"], list(M.POST_GATE_STAGES))
        self.assertLess(od["gate_line"], od["record_line"])
        self.assertTrue(od["decision_requires_not_blocked"],
                        "Step 3 больше не требует «не заблокировано политикой» — "
                        "сцена С3 судит другой цикл")

    def test_the_live_like_fake_is_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_cycle(tmp, _LIVE_LIKE_CYCLE)
            od = M.live_stage_order(tmp)
        self.assertEqual(od["verdict"], "measured", od.get("reason"))
        self.assertTrue(od["decision_requires_not_blocked"])

    def test_a_swapped_order_is_diverged_and_names_both(self):
        swapped = _LIVE_LIKE_CYCLE.replace(
            "    target_usd = apply_rtmr_posture_gate(target_usd)\n", "").replace(
            "    target_usd = apply_kill_switch_override(target_usd)\n",
            "    target_usd = apply_kill_switch_override(target_usd)\n"
            "    target_usd = apply_rtmr_posture_gate(target_usd)\n")
        with tempfile.TemporaryDirectory() as tmp:
            _fake_cycle(tmp, swapped)
            od = M.live_stage_order(tmp)
        self.assertEqual(od["verdict"], "diverged")
        self.assertIn("apply_rtmr_posture_gate", od["reason"])
        self.assertEqual(od["live"][1], "apply_rtmr_posture_gate")

    def test_imports_and_defs_are_not_calls(self):
        """Ступени, названные ТОЛЬКО импортом/def в объявленном порядке, —
        не живая цепь: вердикт diverged, а не measured."""
        body = "\n".join(
            ["def run_cycle():",
             "    gate = _apply_risk_policy_gate(t)"]
            + [f"    from x import {n}" for n in M.POST_GATE_STAGES]
            + [f"def {n}(): pass" for n in dict.fromkeys(M.POST_GATE_STAGES)]
            + ["    _cio_doc = write_shadow_rationale(t)"]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            _fake_cycle(tmp, body)
            od = M.live_stage_order(tmp)
        self.assertEqual(od["verdict"], "diverged")
        self.assertEqual(od["live"], [])

    def test_unreadable_cycle_is_unmeasured_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            od = M.live_stage_order(tmp)
        self.assertEqual(od["verdict"], "unmeasured")
        self.assertTrue(od["reason"].strip())

    def test_missing_decision_line_is_false_not_absent(self):
        body = _LIVE_LIKE_CYCLE.split("    traded =")[0]
        with tempfile.TemporaryDirectory() as tmp:
            _fake_cycle(tmp, body)
            od = M.live_stage_order(tmp)
        self.assertEqual(od["verdict"], "measured")
        self.assertIs(od["decision_requires_not_blocked"], False)


def _gate(approved=True, target=None, frozen=(), error=None, trimmed=False):
    return {"approved": approved, "error": error, "trimmed": trimmed,
            "target_usd": dict(target or {}), "tvl_unverified": list(frozen),
            "violations": [] if approved else ["x"]}


def _identity(book, notes):
    return book, None


def _chain(gate, raw, held, stages):
    with tempfile.TemporaryDirectory() as tmp:
        return M.run_post_gate_chain(
            gate=gate, raw_target=raw, held=held, capital_usd=1_000.0, adapters=[],
            ddir=Path(tmp), now=_NOW, stages=stages)


class TestTheChainProbeDiscriminates(unittest.TestCase):
    """Каждая форма отмены ловится и приписывается СВОЕЙ ступени — на подделках."""

    HELD = {"a": 100.0, "b": 50.0}

    def test_identity_chain_survives_with_no_forms(self):
        g = _gate(target={"a": 100.0, "b": 50.0}, frozen=["b"])
        r = _chain(g, g["target_usd"], self.HELD, [("s", _identity)])
        self.assertEqual(r["outcome"], M.SURVIVES)
        self.assertEqual(r["forms"], [])
        self.assertFalse(r["record_divergence"])

    def test_fresh_capital_to_a_frozen_pool_is_named(self):
        g = _gate(target={"a": 100.0, "b": 50.0}, frozen=["b"])
        def give(book, notes):
            book = dict(book); book["b"] += 10.0; return book, None
        r = _chain(g, g["target_usd"], self.HELD, [("s0", _identity), ("giver", give)])
        self.assertEqual(r["outcome"], M.UNDONE)
        self.assertEqual(r["undone_by"], ["giver"])
        self.assertEqual(r["forms"], ["fresh_to_refused"])
        self.assertEqual(r["steps"][1]["fresh_to_refused_usd"], {"b": 10.0})

    def test_raising_above_both_judged_and_held_is_named(self):
        g = _gate(target={"a": 80.0, "b": 50.0}, frozen=["b"])
        def grow(book, notes):
            book = dict(book); book["a"] = 120.0; return book, None
        r = _chain(g, g["target_usd"], self.HELD, [("grower", grow)])
        self.assertEqual(r["undone_by"], ["grower"])
        self.assertEqual(r["forms"], ["raised_above_judged"])
        self.assertEqual(r["steps"][0]["raised_above_judged_usd"], {"a": 20.0})

    def test_a_rise_that_stays_under_held_is_not_fresh_capital(self):
        """Гейт одобрил продажу 100 → 80; ступень поставила 90: это МЕНЬШАЯ продажа,
        а не свежий капитал — потолок свежести = max(одобрено, удержано)."""
        g = _gate(target={"a": 80.0, "b": 50.0}, frozen=["b"])
        def soften(book, notes):
            book = dict(book); book["a"] = 90.0; return book, None
        r = _chain(g, g["target_usd"], self.HELD, [("softener", soften)])
        self.assertEqual(r["outcome"], M.SURVIVES)
        self.assertTrue(r["steps"][0]["changed"])

    def test_an_unjudged_protocol_is_blamed_on_the_stage_that_introduced_it(self):
        g = _gate(target={"a": 100.0, "b": 50.0}, frozen=["b"])
        def intro(book, notes):
            book = dict(book); book["c"] = 5.0; return book, None
        r = _chain(g, g["target_usd"], self.HELD,
                   [("intro", intro), ("carrier", _identity), ("carrier2", _identity)])
        self.assertEqual(r["undone_by"], ["intro"], "соседи ниже пронесли «c», не вводили его")
        self.assertEqual(r["forms"], ["introduced_unjudged"])
        self.assertEqual(r["steps"][1]["forms"], [])

    def test_dropping_an_approved_protocol_is_book_replaced(self):
        g = _gate(target={"a": 100.0, "b": 50.0}, frozen=["b"])
        def drop(book, notes):
            book = dict(book); book.pop("a"); return book, None
        r = _chain(g, g["target_usd"], self.HELD, [("dropper", drop)])
        self.assertEqual(r["undone_by"], ["dropper"])
        self.assertEqual(r["forms"], ["book_replaced"])
        self.assertEqual(r["steps"][0]["dropped_judged"], ["a"])

    def test_refused_gate_keeps_the_raw_carrier_and_judges_nothing(self):
        g = _gate(approved=False, target={"a": 300.0})
        r = _chain(g, {"a": 300.0}, self.HELD, [("s", _identity)])
        self.assertIn("сырая цель", r["carrier_source"])
        self.assertEqual(r["gate"]["judged_target"], {})
        self.assertEqual(r["outcome"], M.SURVIVES)
        self.assertTrue(r["record_divergence"], "300 > удержанных 100 — свежий капитал без одобрения")
        self.assertEqual(r["fresh_beyond_gate_usd"], {"a": 200.0})

    def test_refused_gate_with_a_book_under_held_has_no_divergence(self):
        g = _gate(approved=False, target={"a": 60.0})
        r = _chain(g, {"a": 60.0}, self.HELD, [("s", _identity)])
        self.assertFalse(r["record_divergence"])

    def test_frozen_or_trimmed_gate_hands_its_own_target_as_the_carrier(self):
        g = _gate(target={"a": 70.0, "b": 50.0}, frozen=["b"])
        r = _chain(g, {"a": 70.0, "b": 90.0}, self.HELD, [("s", _identity)])
        self.assertEqual(r["carrier_in"], {"a": 70.0, "b": 50.0})
        g2 = _gate(target={"a": 70.0, "b": 90.0})
        r2 = _chain(g2, {"a": 70.0, "b": 90.0}, self.HELD, [("s", _identity)])
        self.assertIn("сырая цель", r2["carrier_source"])

    def test_a_crashing_stage_is_unmeasured_and_named(self):
        g = _gate(target={"a": 100.0, "b": 50.0})
        def boom(book, notes):
            raise RuntimeError("дверь не ответила")
        r = _chain(g, g["target_usd"], self.HELD, [("ok", _identity), ("boom", boom)])
        self.assertEqual(r["outcome"], M.UNMEASURED)
        self.assertIn("boom", r["unmeasured_reason"])
        self.assertEqual(len(r["steps"]), 1)

    def test_turnover_is_one_sided_against_held(self):
        g = _gate(target={"a": 50.0, "b": 100.0}, frozen=[])
        r = _chain(g, g["target_usd"], self.HELD, [("s", _identity)])
        self.assertEqual(r["turnover_final_usd"], 50.0)


class TestTheSecondAxisOnTheLiveFunctions(unittest.TestCase):
    """Сцены второй оси над НАСТОЯЩИМИ ступенями цикла."""

    @classmethod
    def setUpClass(cls):
        cls.pg = M.run_post_gate_axis(_ctx(), root=M.REPO_ROOT, now=_NOW)
        cls.scenes = {s["scene"]: s for s in cls.pg["scenes"]}

    def test_control_passes_on_the_live_tree(self):
        self.assertTrue(self.pg["control"]["passed"], self.pg["control"]["reasons"])
        self.assertEqual(sorted(self.pg["control"]["checks"]),
                         ["k0_healthy_chain_is_identity", "k1_synthetic_return_is_named",
                          "order_matches_live_cycle"])
        self.assertEqual(self.pg["verdict"], "measured")

    def test_frozen_pool_survives_all_seven_stages(self):
        s = self.scenes["s1_frozen_pool_through_chain"]
        self.assertEqual(s["outcome"], M.SURVIVES, s.get("detail"))
        self.assertEqual(s["gate"]["frozen"], ["pendle"])
        self.assertEqual(len(s["steps"]), len(M.POST_GATE_STAGES))
        self.assertEqual(s["fresh_beyond_gate_usd"], {})

    def test_adr002_replaces_the_gated_book_when_the_snapshot_is_absent(self):
        s = self.scenes["s2_snapshot_absent_over_count_cap"]
        self.assertTrue(s["gate"]["approved"], "гейт обязан одобрить широкую книгу, иначе ADR-002 недостижим")
        self.assertEqual(s["gate"]["frozen"], ["pendle"])
        self.assertEqual(s["outcome"], M.UNDONE, s.get("detail"))
        self.assertEqual(s["undone_by"], ["_compliant_target"],
                         "виновник ровно один — ступень ADR-002; соседи ниже книгу не переписывали")
        adr002 = next(st for st in s["steps"] if st["stage"] == "_compliant_target")
        self.assertTrue(adr002["changed"])
        self.assertIn("СХЛОПНУТА", adr002["note"])
        self.assertTrue(set(s["forms"]) & {"raised_above_judged", "introduced_unjudged", "book_replaced"})

    def test_adr002_scene_turns_a_degradation_into_a_move(self):
        s = self.scenes["s2_snapshot_absent_over_count_cap"]
        self.assertGreater(s["turnover_final_usd"], 0.0,
                           "у записи оборот ноль — подмена книги ходом не стала, сцена потеряла предмет")

    def test_refused_book_reaches_the_record_trimmed_and_rejudged(self):
        s = self.scenes["s3_refused_book_reaches_record"]
        self.assertFalse(s["gate"]["approved"])
        self.assertIn("сырая цель", s["carrier_source"])
        self.assertEqual(s["trim_verdict"], "TRIMMED_TO_ADMISSIBLE", s.get("detail"))
        self.assertIs(s["rejudged_within_chain"], True)
        self.assertTrue(s["record_divergence"])
        self.assertEqual(s["outcome"], M.SURVIVES)
        self.assertTrue(self.pg["order"]["decision_requires_not_blocked"])

    def test_every_scene_outcome_is_in_the_vocabulary(self):
        for s in self.pg["scenes"]:
            self.assertIn(s["outcome"], (M.SURVIVES, M.UNDONE, M.UNMEASURED))
            if s["outcome"] == M.UNMEASURED:
                self.assertTrue(s["unmeasured_reason"].strip())
        self.assertEqual(sum(v for k, v in self.pg["tally"].items() if k != "total"),
                         self.pg["tally"]["total"])

    def test_host_doors_are_named(self):
        self.assertTrue(any("_compliant_target" in d for d in self.pg["host_doors"]))

    def test_order_block_names_the_live_lines(self):
        od = self.pg["order"]
        self.assertEqual(od["verdict"], "measured")
        self.assertEqual([s["stage"] for s in od["sites"]], list(M.POST_GATE_STAGES))


class TestTheSecondAxisInTheReport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc = M.run(root=M.REPO_ROOT, now=_NOW, write=False)

    def test_schema_is_v2_and_the_axis_is_in_the_artifact(self):
        self.assertEqual(self.doc["schema"], M.SCHEMA)
        self.assertIn("post_gate", self.doc)
        self.assertEqual(self.doc["post_gate"]["schema"], M.SCHEMA)

    def test_undone_is_critical_and_divergence_is_warn(self):
        codes = {f["code"]: f["severity"] for f in self.doc["findings"]}
        self.assertEqual(codes.get("refusal_undone:s2_snapshot_absent_over_count_cap"), "CRITICAL")
        self.assertEqual(codes.get("record_diverges:s3_refused_book_reaches_record"), "WARN")

    def test_the_ten_conditions_are_untouched_by_the_axis(self):
        self.assertEqual(self.doc["conditions_total"], len(M.OWNER_CONDITIONS))
        self.assertEqual(sum(self.doc["tally"].values()), len(M.OWNER_CONDITIONS))

    def test_unchecked_count_includes_the_axis(self):
        self.assertEqual(len(self.doc["unchecked"]), self.doc["counts"]["unchecked"])


class TestTheSecondAxisFailsClosed(unittest.TestCase):

    def test_a_broken_control_makes_the_axis_unmeasured_and_keeps_scene_findings(self):
        """Контроль сорван ⇒ вердикт оси «не измерено» с причиной; находки сцен при
        этом НЕ прячутся — ошибка в опасную сторону была бы молчанием."""
        real = M._call_chain
        def leaky(scene, adapters, target, now, stages=None):
            r = real(scene, adapters, target, now, stages=stages)
            if stages is None and scene is _ctx_cache["gate_scene"] and adapters is scene["adapters"]:
                r = dict(r, final=dict(r["final"], aave_v3=r["final"].get("aave_v3", 0.0) + 1.0))
            return r
        _ctx_cache = _ctx()
        M._call_chain = leaky
        try:
            pg = M.run_post_gate_axis(_ctx_cache, root=M.REPO_ROOT, now=_NOW)
        finally:
            M._call_chain = real
        self.assertEqual(pg["verdict"], "unmeasured")
        self.assertFalse(pg["control"]["checks"]["k0_healthy_chain_is_identity"])
        self.assertTrue(any("К0" in r for r in pg["control"]["reasons"]))
        findings, unchecked = M._post_gate_findings(pg)
        self.assertTrue(any(u.startswith("вторая ось") for u in unchecked))
        self.assertTrue(any(f["code"].startswith("refusal_undone:") for f in findings))

    def test_a_diverged_order_is_reported_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_cycle(tmp, _LIVE_LIKE_CYCLE.replace(
                "    target_usd = apply_pool_alias_gate(target_usd)\n", ""))
            pg = M.run_post_gate_axis(_ctx(), root=tmp, now=_NOW)
        self.assertEqual(pg["verdict"], "unmeasured")
        self.assertFalse(pg["control"]["checks"]["order_matches_live_cycle"])
        self.assertTrue(any("порядок ступеней" in r for r in pg["control"]["reasons"]))


class TestLiveStagesMirrorTheCycle(unittest.TestCase):

    def test_adr002_is_skipped_when_the_gate_refused_as_in_the_cycle(self):
        """`_compliant_target` в цикле стоит под `not policy_blocked`: на отказанной
        книге шире потолка числа протоколов ступень обязана быть ПРОПУЩЕНА, а не
        схлопывать книгу, которой гейт отказал."""
        from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate
        caps = M._policy_caps()
        sc = M._scene_over_count_cap(caps)
        cap = sc["capital_usd"]
        over = round((float(caps["t1_frac"]) + 0.10) * cap, 2)       # выше потолка T1
        rest = round((0.90 * cap - over) / (len(sc["target"]) - 1), 2)  # сумма под буфером кэша,
        wide = {p: rest for p in sc["target"]}                          # чтобы гейт не срезал долю
        wide["aave_v3"] = over
        with tempfile.TemporaryDirectory() as tmp:
            gate = _apply_risk_policy_gate(dict(wide), sc["capital_usd"], sc["adapters"],
                                           ddir=Path(tmp), current_positions=dict(sc["held"]))
            self.assertFalse(gate["approved"], gate["violations"][:2])
            r = M.run_post_gate_chain(gate=gate, raw_target=wide, held=sc["held"],
                                      capital_usd=sc["capital_usd"], adapters=sc["adapters"],
                                      ddir=Path(tmp), now=_NOW)
        st = next(s for s in r["steps"] if s["stage"] == "_compliant_target")
        self.assertIn("пропущена", st["note"])
        self.assertFalse(st["changed"])
