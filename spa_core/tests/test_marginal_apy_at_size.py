"""Сторож §12/§49 ТЗ CIO: влияет ли НАШ размер на ставку, по которой нас ранжируют.

Даты в файле отсутствуют намеренно: у модуля нет ни одного суждения о свежести,
а часы (`now`) — вход. Момент строится из эпохи, чтобы не заводить литеральную дату
там, где она ничего не значит (`.claude/rules/deployment.md`, «Время в тестах»).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import marginal_apy_at_size as M

_T0 = dt.datetime.fromtimestamp(0, dt.timezone.utc)


def _row(tvl=100_000_000.0, src="live", apy=8.0, base=8.0, reward=0.0):
    return {"tvl_usd": tvl, "tvl_source": src, "apy": apy,
            "apy_base": base, "apy_reward": reward}


class TestObjectiveIsActuallyLinear(unittest.TestCase):
    """Положительный контроль: дефект, ради которого сторож написан, ВОСПРОИЗВОДИТСЯ.

    Утверждение «оптимизатор не учитывает наш размер» — не цитата из докстринга,
    а свойство кода, и оно меряется здесь. Перестанет быть правдой (кто-то сделает
    ставку функцией веса) — этот тест покраснеет первым, и находка сторожа станет
    устаревшей ЯВНО, а не молча.
    """

    def test_weighted_apy_does_not_depend_on_position_size(self):
        from spa_core.tuner.allocation_tuner import AllocationTuner

        t = AllocationTuner()
        data = [{"id": "p", "apy": 8.0, "tvl_usd": 5_000_000.0, "tier": "T1"},
                {"id": "q", "apy": 4.0, "tvl_usd": 5_000_000.0, "tier": "T1"}]
        tiny = t._weighted_apy({"p": 0.001, "q": 0.999}, data)
        huge = t._weighted_apy({"p": 0.999, "q": 0.001}, data)
        # Ставка p одна и та же в обеих раскладках: вклад строго пропорционален
        # весу. Будь ставка функцией размера, отношение вкладов не совпало бы.
        self.assertAlmostEqual(tiny, 0.001 * 8.0 + 0.999 * 4.0, places=9)
        self.assertAlmostEqual(huge, 0.999 * 8.0 + 0.001 * 4.0, places=9)


class TestThirdOutcome(unittest.TestCase):
    def test_static_tvl_is_not_a_denominator(self):
        m = M.measure_pool("k", 40_000.0, _row(src="static"), 100_000.0)
        self.assertFalse(m.measured)
        self.assertIn("static", m.reason)
        self.assertIsNone(m.share_pct)
        self.assertIsNone(m.error_pp_modelled)

    def test_huge_static_tvl_is_still_refused(self):
        # Размер литерала не делает его наблюдением (ADR-053).
        m = M.measure_pool("k", 40_000.0, _row(tvl=12_000_000_000.0, src="static"),
                           100_000.0)
        self.assertFalse(m.measured)

    def test_unmeasured_composition_is_refused_with_a_reason(self):
        row = {"tvl_usd": 1e8, "tvl_source": "live", "apy": 8.0,
               "apy_base": None, "apy_reward": None}
        m = M.measure_pool("k", 40_000.0, row, 100_000.0)
        self.assertFalse(m.measured)
        self.assertIn("состав ставки", m.reason)

    def test_nonpositive_tvl_refused(self):
        m = M.measure_pool("k", 1_000.0, _row(tvl=0.0), 100_000.0)
        self.assertFalse(m.measured)

    def test_unchecked_outranks_critical_in_overall(self):
        rep = M.run(root=tempfile.gettempdir(), write=False, now=_T0,
                    reader=lambda p: (_ for _ in ()).throw(OSError("нет файла")))
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertTrue(rep["unchecked"])
        self.assertTrue(all("нет файла" in u for u in rep["unchecked"]))


class TestThreeNumbersAndOnlyOneIsFact(unittest.TestCase):
    def test_zero_reward_means_zero_definitional_error(self):
        """Главная гарантия честности: без награды ФАКТИЧЕСКАЯ ошибка ровно ноль."""
        m = M.measure_pool("k", 40_000.0, _row(base=8.0, reward=0.0), 100_000.0)
        self.assertTrue(m.measured)
        self.assertEqual(m.error_pp_definitional, 0.0)
        # …а модельная — уже НЕ ноль: она целиком из допущения об эластичности базы.
        self.assertGreater(m.error_pp_modelled, 0.0)

    def test_definitional_error_is_reward_times_share(self):
        tvl, dep, rew = 1_000_000.0, 250_000.0, 4.0
        m = M.measure_pool("k", dep, _row(tvl=tvl, base=4.0, reward=rew, apy=8.0),
                           1_000_000.0)
        expected = rew * (1.0 - tvl / (tvl + dep))
        self.assertAlmostEqual(m.error_pp_definitional, round(expected, 6), places=6)

    def test_bounds_are_ordered(self):
        m = M.measure_pool("k", 250_000.0,
                           _row(tvl=1_000_000.0, base=4.0, reward=4.0, apy=8.0),
                           1_000_000.0)
        self.assertLessEqual(m.error_pp_definitional, m.error_pp_modelled)
        self.assertLessEqual(m.error_pp_modelled, m.error_pp_full_elastic)

    def test_share_is_deposit_over_tvl_plus_deposit(self):
        m = M.measure_pool("k", 50_000.0, _row(tvl=950_000.0), 100_000.0)
        self.assertAlmostEqual(m.share_pct, 5.0, places=6)

    def test_bigger_position_dilutes_more(self):
        small = M.measure_pool("k", 10_000.0, _row(tvl=1e6), 1e6)
        big = M.measure_pool("k", 500_000.0, _row(tvl=1e6), 1e6)
        self.assertGreater(big.error_pp_modelled, small.error_pp_modelled)

    def test_blended_error_is_converted_to_capital_denominator(self):
        """min_gain_pp меряется в пп ОТ КАПИТАЛА — приведение обязано существовать."""
        m = M.measure_pool("k", 40_000.0, _row(tvl=1e6), 100_000.0)
        self.assertAlmostEqual(
            m.blended_error_pp_modelled,
            round(m.error_pp_modelled * (40_000.0 / 100_000.0), 6), places=6)
        # …и оно НЕ равно самой ошибке ставки: иначе приведения нет.
        self.assertNotAlmostEqual(m.blended_error_pp_modelled, m.error_pp_modelled)


class TestModelIsBorrowedNotCopied(unittest.TestCase):
    """Мутация ПРОВОДКИ: модель обязана приходить из MP-911, а не из своей копии."""

    def test_diluted_apy_comes_from_the_yield_dilution_analyzer(self):
        import spa_core.analytics.yield_dilution_analyzer as YDA

        real = YDA._diluted_apy
        baseline = M.measure_pool("k", 40_000.0, _row(tvl=1e6), 1e5).error_pp_modelled
        try:
            YDA._diluted_apy = lambda r, b, t, a: 0.0   # чужая модель сломана
            M_reloaded = _reload_module()
            mutated = M_reloaded.measure_pool(
                "k", 40_000.0, _row(tvl=1e6), 1e5).error_pp_modelled
        finally:
            YDA._diluted_apy = real
            _reload_module()
        self.assertNotAlmostEqual(baseline, mutated,
                                  msg="модель не берётся из MP-911 — есть своя копия")


def _reload_module():
    import importlib
    return importlib.reload(M)


class TestPolicyLimitsAreReadFromTheirHomes(unittest.TestCase):
    def test_floor_and_cap_come_from_tuner_constraints(self):
        from spa_core.tuner.allocation_tuner import TunerConstraints

        floor, cap, _mg, prov, refusals = M._policy_limits()
        c = TunerConstraints()
        self.assertEqual(floor, float(c.tvl_floor_usd))
        self.assertEqual(cap, float(max(c.per_protocol_t1_max, c.per_protocol_t2_max)))
        self.assertTrue(any("TunerConstraints" in x for x in prov))
        self.assertEqual(refusals, [])

    def test_min_gain_comes_from_the_damper_not_from_here(self):
        """Порог существенности — ЧУЖОЙ. Совпадать он обязан с живым путём.

        Живой путь (`rebalance_economics`, `churn_damper`) берёт колонку через
        `TriggerParams.for_mode()`, и колонка зависит от режима капитала. Сверяем
        с тем же вызовом, а не с литералом: литерал развалился бы в pilot-режиме,
        где `min_gain_pp` = 0.75 (ADR-060 §3).
        """
        from spa_core.allocator.rebalance_economics import TriggerParams

        _floor, _cap, min_gain, prov, refusals = M._policy_limits()
        self.assertEqual(min_gain, float(TriggerParams.for_mode().min_gain_pp))
        self.assertTrue(any("TriggerParams.for_mode" in x for x in prov))
        self.assertEqual(refusals, [])

    def test_unreadable_threshold_is_unchecked_not_a_literal(self):
        """Мутация ПРОВОДКИ: порог не прочитан ⇒ третий исход, а не тихое число."""
        import spa_core.allocator.rebalance_economics as RE

        real = RE.TriggerParams.for_mode
        try:
            RE.TriggerParams.for_mode = classmethod(
                lambda cls, mode=None: (_ for _ in ()).throw(RuntimeError("дом закрыт")))
            floor, cap, min_gain, _prov, refusals = M._policy_limits()
            self.assertIsNone(min_gain)
            self.assertTrue(any("дом закрыт" in r for r in refusals))
            with tempfile.TemporaryDirectory() as tmp:
                with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
                    json.dump({"adapters": {"b": _row()}}, fh)
                with open(os.path.join(tmp, "current_positions.json"), "w") as fh:
                    json.dump({"capital_usd": 1e5, "positions": {"b": 1e4}}, fh)
                rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            self.assertEqual(rep["overall"], "UNCHECKED")
        finally:
            RE.TriggerParams.for_mode = real


class TestPolicyBoundAndScaleCeiling(unittest.TestCase):
    def test_bound_uses_the_thinnest_fundable_pool(self):
        b = M.policy_bound(100_000.0, 5_000_000.0, 0.4)
        self.assertEqual(b["position_usd"], 40_000.0)
        self.assertAlmostEqual(b["worst_case_share_pct"],
                               40_000.0 / 5_040_000.0 * 100.0, places=4)

    def test_bound_grows_with_capital(self):
        small = M.policy_bound(1e5, 5e6, 0.4)["worst_case_error_pp_blended"]
        big = M.policy_bound(1e7, 5e6, 0.4)["worst_case_error_pp_blended"]
        self.assertGreater(big, small)

    def test_crossing_capital_actually_reaches_the_gain_band(self):
        sc = M.scale_ceiling(5_000_000.0, 0.4, 0.5)
        cap_at = sc["capital_usd_at_crossing"]
        self.assertIsNotNone(cap_at)
        at = M.policy_bound(cap_at, 5e6, 0.4)["worst_case_error_pp_blended"]
        self.assertGreaterEqual(at, 0.5 - 1e-6)
        # …и чуть ниже порога ещё НЕ догоняет — иначе это не точка пересечения.
        below = M.policy_bound(cap_at * 0.9, 5e6, 0.4)["worst_case_error_pp_blended"]
        self.assertLess(below, 0.5)

    def test_unreachable_crossing_is_named_not_invented(self):
        sc = M.scale_ceiling(5_000_000.0, 0.4, 10_000.0, max_capital_usd=1e6)
        self.assertIsNone(sc["capital_usd_at_crossing"])
        self.assertIsNotNone(sc["reason"])

    def test_scale_ceiling_is_deterministic(self):
        a = M.scale_ceiling(5e6, 0.4, 0.5)["capital_usd_at_crossing"]
        b = M.scale_ceiling(5e6, 0.4, 0.5)["capital_usd_at_crossing"]
        self.assertEqual(a, b)


class TestRunOnASnapshot(unittest.TestCase):
    def _snapshot(self, tmp, positions, adapters, capital=100_000.0):
        with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
            json.dump({"adapters": adapters}, fh)
        with open(os.path.join(tmp, "current_positions.json"), "w") as fh:
            json.dump({"capital_usd": capital, "positions": positions}, fh)

    def test_literal_denominator_is_reported_with_the_capital_at_stake(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp,
                           {"a": 40_000.0, "b": 10_000.0},
                           {"a": _row(src="static"), "b": _row()})
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            self.assertEqual(rep["unmeasured_capital_usd"], 40_000.0)
            self.assertAlmostEqual(rep["unmeasured_capital_pct"], 80.0, places=2)
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertIn("denominator_is_a_literal", kinds)

    def test_linearity_finding_is_present_regardless_of_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()})
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertIn("objective_is_linear_in_rate", kinds)

    def test_wrong_shape_is_unchecked_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
                json.dump({"adapters": []}, fh)      # список вместо словаря
            with open(os.path.join(tmp, "current_positions.json"), "w") as fh:
                json.dump({"capital_usd": 1e5, "positions": {}}, fh)
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            self.assertEqual(rep["overall"], "UNCHECKED")
            self.assertTrue(any("adapters" in u for u in rep["unchecked"]))

    def test_clock_is_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()})
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            self.assertEqual(rep["generated_at"], _T0.isoformat())

    def test_write_false_leaves_the_tree_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()})
            before = sorted(os.listdir(os.path.join(tmp, "data")))
            M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            self.assertEqual(sorted(os.listdir(os.path.join(tmp, "data"))), before)

    def test_write_true_produces_the_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()})
            M.run(root=tmp, data_dir=tmp, write=True, now=_T0)
            with open(os.path.join(tmp, M.REPORT_REL)) as fh:
                doc = json.load(fh)
            self.assertIn("policy_bound", doc)
            self.assertIn("scale_ceiling", doc)

    def test_critical_when_bound_eats_the_whole_gain_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Капитал выше потолка масштаба ⇒ линейность съедает требуемую выгоду.
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()},
                           capital=50_000_000.0)
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertIn("linearity_eats_the_gain_band", kinds)

    def test_no_critical_at_todays_capital(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()}, capital=100_000.0)
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertNotIn("linearity_eats_the_gain_band", kinds)


class TestNumberParsing(unittest.TestCase):
    def test_bool_is_not_a_number(self):
        self.assertIsNone(M._num(True))
        self.assertIsNone(M._num(False))

    def test_nan_and_inf_rejected(self):
        self.assertIsNone(M._num(float("nan")))
        self.assertIsNone(M._num(float("inf")))


class TestThresholdsFollowTheirHomesWhenTHOSEChange(unittest.TestCase):
    """Мутация «назначить литерал здесь» молчит, пока литерал совпадает с политикой.

    Замер цикла #502: подмена `min_gain_pp` на `0.50` и `tvl_floor` на `5_000_000.0`
    прямо в модуле не покраснила НИ ОДИН тест — ровно потому, что сегодня политика
    держит эти же значения (класс «сторож не проверен, пока умолчание делает его
    избыточным»). Проверять надо не совпадение с сегодняшним числом, а то, что
    число ДВИЖЕТСЯ ВСЛЕД за своим домом.
    """

    def test_min_gain_follows_the_damper(self):
        import spa_core.allocator.rebalance_economics as RE

        real = RE.TriggerParams.for_mode
        try:
            RE.TriggerParams.for_mode = classmethod(
                lambda cls, mode=None: cls(min_gain_pp=1.23))
            _f, _c, min_gain, prov, refusals = M._policy_limits()
        finally:
            RE.TriggerParams.for_mode = real
        self.assertEqual(min_gain, 1.23, "порог не следует за своим домом — он назначен здесь")
        self.assertEqual(refusals, [])
        self.assertTrue(any("1.23" in x for x in prov))

    def test_tvl_floor_and_cap_follow_the_tuner(self):
        import spa_core.tuner.allocation_tuner as AT

        real = AT.TunerConstraints
        try:
            AT.TunerConstraints = lambda: real(
                tvl_floor_usd=7_777_777.0, per_protocol_t1_max=0.33)
            floor, cap, _mg, _prov, refusals = M._policy_limits()
        finally:
            AT.TunerConstraints = real
        self.assertEqual(floor, 7_777_777.0,
                         "TVL-floor не следует за TunerConstraints — он назначен здесь")
        self.assertEqual(cap, 0.33,
                         "потолок концентрации не следует за TunerConstraints")
        self.assertEqual(refusals, [])


class TestArtifactHasBothHomes(unittest.TestCase):
    """Дом артефакта — ДВЕ записи манифеста, и парити-тест краснеет только на одной.

    `test_contract_manifest_parity` сверяет `PRODUCES` модулей с `produces[]` агента
    и НЕ смотрит в реестр артефактов (`"path": …`), где живут `slo_hours`,
    `producer` и `consumers`. Замер #502: удаление записи из реестра не покраснило
    ни один сторож. Артефакт без реестровой записи протухнет молча — SLO ему никто
    не назначит.
    """

    @staticmethod
    def _manifest():
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(M.__file__))))
        with open(os.path.join(root, "architecture", "manifest.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_registry_entry_exists_with_producer_and_consumer(self):
        man = self._manifest()
        rows = [a for a in (man.get("artifacts") or [])
                if a.get("path") == "data/marginal_apy_at_size.json"]
        self.assertEqual(len(rows), 1, "нет записи в реестре артефактов манифеста")
        row = rows[0]
        self.assertTrue(row.get("producer"), "у артефакта нет производителя")
        self.assertTrue(row.get("consumers"), "у артефакта нет потребителя")
        self.assertTrue(row.get("slo_hours"), "артефакту не назначен SLO")

    def test_producing_agent_declares_it(self):
        man = self._manifest()
        rows = [a for a in (man.get("artifacts") or [])
                if a.get("path") == "data/marginal_apy_at_size.json"]
        producer = rows[0]["producer"] if rows else None
        agents = [g for g in (man.get("agents") or []) if g.get("label") == producer]
        self.assertEqual(len(agents), 1, f"производитель {producer!r} не найден в манифесте")
        declared = {x.get("artifact") for x in (agents[0].get("produces") or [])}
        self.assertIn("data/marginal_apy_at_size.json", declared,
                      "агент-производитель не объявляет артефакт в produces[]")

    def test_module_declares_it_in_produces(self):
        from spa_core.monitoring import findings_bridge

        self.assertIn("data/marginal_apy_at_size.json", findings_bridge.PRODUCES)


class TestOfficeStepReadsIt(unittest.TestCase):
    """Потребитель обязан быть ИМЕНОВАННЫМ, иначе артефакт читает никто."""

    @staticmethod
    def _office_source():
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(M.__file__))))
        with open(os.path.join(root, "scripts", "consume_office_reports.py"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_office_step_has_a_named_branch(self):
        src = self._office_source()
        self.assertIn('elif name == "marginal_apy_at_size.json":', src,
                      "у шага 0-офис нет именной ветки — отчёт не будет прочитан")

    def test_office_step_knows_the_producer(self):
        src = self._office_source()
        self.assertIn('"marginal_apy_at_size.json": '
                      '"spa_core/monitoring/marginal_apy_at_size.py"', src)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
