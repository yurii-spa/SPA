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
        # ПРАВКА ЦИКЛА #731, НАМЕРЕННАЯ И ОБОСНОВАННАЯ (инв. #16): прежде здесь
        # стояло `all("нет файла" in u)`. С непрочитанной книгой капитала нет, а
        # размеры сцены замера задаются потолком политики ОТ КАПИТАЛА — значит и
        # целевую функцию спросить не у чего, и это ВТОРАЯ, самостоятельная
        # причина «не измерено». Требование «все причины — одна и та же»
        # запрещало бы прибору называть вторую; требование ниже строже: названа
        # обязана быть КАЖДАЯ, и обе поимённо.
        rep = M.run(root=tempfile.gettempdir(), write=False, now=_T0,
                    reader=lambda p: (_ for _ in ()).throw(OSError("нет файла")))
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertTrue(rep["unchecked"])
        self.assertTrue(any("нет файла" in u for u in rep["unchecked"]))
        self.assertTrue(any("НЕ СПРОСИЛИ" in u for u in rep["unchecked"]))
        self.assertTrue(all(u.strip() for u in rep["unchecked"]),
                        "причина без текста — это «не измерено» без причины")


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

    def test_linearity_finding_now_comes_from_a_measurement(self):
        """Та же находка, что и раньше, — но теперь она ИЗМЕРЕНА, а не напечатана.

        ЗАМЕНА ТЕСТА НАМЕРЕННА И ОБОСНОВАНА (инв. #16, цикл #731, ADR-514).
        Прежний тест назывался `…_is_present_regardless_of_the_snapshot` и
        требовал, чтобы находка присутствовала ВСЕГДА. Он верно описывал то, что
        код делал, — и ровно этим закреплял дефект: находка была безусловной
        строкой, то есть претензией, способной пережить свой предмет молча.
        Требование «присутствует всегда» сделало бы невозможным единственный
        честный исход «целевую функцию спросили, и она реагирует».

        Новое требование СТРОЖЕ прежнего: находка обязана быть, И при ней обязан
        стоять состоявшийся замер с двумя разными размерами.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()})
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertIn("objective_is_linear_in_rate", kinds)
            sens = rep["objective_size_sensitivity"]
            self.assertTrue(sens["measured"], sens["reason"])
            self.assertFalse(sens["size_aware"])
            self.assertNotEqual(sens["small_usd"], sens["large_usd"])
            self.assertEqual(sens["rate_at_small_pp"], sens["rate_at_large_pp"])
            # Порог «функция вернула другое число» ЧИСЛЕННЫЙ, и что он на
            # порядки ниже настоящего эффекта — замер, а не вкус.
            self.assertGreater(sens["reference_dilution_pp"],
                               M.NUMERICAL_EPS_PP * 1e6)

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


# ── цикл #731: претензия о линейности стала ЗАМЕРОМ, и у замера контроль ─────


class _FakeObjectiveModule:
    """Подставная целевая функция. Ставку роняет ПО РАЗМЕРУ — и замер обязан это увидеть.

    Нужна затем, что иначе контроль был бы односторонним: сегодня живая функция
    линейна, и тест, умеющий только это, не отличил бы работающий замер от
    константы, возвращающей «линейна» при любом входе.
    """

    def __init__(self, drop_per_unit_weight: float = 1.0):
        self._drop = drop_per_unit_weight
        outer = self

        class AllocationTuner:
            def _weighted_apy(self, weights, adapter_data):
                rates = {a["id"]: float(a.get("apy") or 0.0) for a in adapter_data}
                # Ставка ПАДАЕТ с весом: ровно то, чего ТЗ §12 и требует.
                return sum(w * (rates.get(pid, 0.0) - outer._drop * w)
                           for pid, w in weights.items())

        self.AllocationTuner = AllocationTuner


class _BrokenObjectiveModule:
    """Целевая функция, у которой доходностный член унесли или переименовали."""

    class AllocationTuner:
        pass


class _RaisingObjectiveModule:
    class AllocationTuner:
        def _weighted_apy(self, weights, adapter_data):
            raise RuntimeError("сцена не принята")


class _MuteObjectiveModule:
    class AllocationTuner:
        def _weighted_apy(self, weights, adapter_data):
            return None


def _keeping_real_constraints(module):
    """Перенести в подставной модуль НАСТОЯЩИЕ `TunerConstraints`.

    Целевая функция и потолки политики живут в одном модуле; подменив его
    целиком, мы поменяли бы разом две вещи, и «функцию спросить нечем» стало бы
    неотличимо от «пороги не прочитаны».
    """
    from spa_core.tuner.allocation_tuner import TunerConstraints

    module.TunerConstraints = TunerConstraints
    return module


class _swap_objective:
    """Подменить модуль целевой функции в `sys.modules` на время теста."""

    def __init__(self, module):
        self._module = module
        self._saved = None
        self._had = False

    def __enter__(self):
        import sys
        self._had = M.OBJECTIVE_MODULE in sys.modules
        self._saved = sys.modules.get(M.OBJECTIVE_MODULE)
        sys.modules[M.OBJECTIVE_MODULE] = self._module
        return self._module

    def __exit__(self, *exc):
        import sys
        if self._had:
            sys.modules[M.OBJECTIVE_MODULE] = self._saved
        else:
            sys.modules.pop(M.OBJECTIVE_MODULE, None)
        return False


class TestObjectiveSizeSensitivityIsMeasuredNotAsserted(unittest.TestCase):
    """Положительный контроль ЗАМЕРА — в ОБЕ стороны, и по каждому порванному звену.

    Дефект, который воспроизводится: до цикла #731 ответ на главный вопрос
    владельца был напечатанной строкой. Проверка «строка есть» зелена и на
    системе, где ранжирующее число давно стало функцией размера, — то есть
    отвечает на свой вопрос, а не на нужный.
    """

    def test_live_objective_is_measured_size_blind(self):
        s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertTrue(s["measured"], s["reason"])
        self.assertFalse(s["size_aware"])
        self.assertEqual(s["rate_at_small_pp"], s["rate_at_large_pp"])
        self.assertEqual(s["large_usd"], 40_000.0)
        self.assertLess(s["small_usd"], s["large_usd"])

    def test_a_size_aware_objective_flips_the_measurement(self):
        with _swap_objective(_FakeObjectiveModule()):
            s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertTrue(s["measured"], s["reason"])
        self.assertTrue(s["size_aware"])
        self.assertGreater(s["rate_at_small_pp"], s["rate_at_large_pp"])

    def test_the_probe_reads_the_live_objective_not_its_own_copy(self):
        """Подмена ДОХОДИТ до замера — иначе он мерил бы собственное убеждение."""
        base = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        with _swap_objective(_FakeObjectiveModule()):
            swapped = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertNotEqual(base["size_aware"], swapped["size_aware"])

    def test_missing_yield_term_is_a_named_third_outcome(self):
        with _swap_objective(_BrokenObjectiveModule()):
            s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertFalse(s["measured"])
        self.assertIn(M.OBJECTIVE_YIELD_TERM, s["reason"])
        self.assertIsNone(s["size_aware"])

    def test_raising_objective_is_a_named_third_outcome(self):
        with _swap_objective(_RaisingObjectiveModule()):
            s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertFalse(s["measured"])
        self.assertIn("RuntimeError", s["reason"])

    def test_unusable_return_is_a_named_third_outcome(self):
        with _swap_objective(_MuteObjectiveModule()):
            s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertFalse(s["measured"])
        self.assertIn("НЕ ИЗМЕРЕНА", s["reason"])

    def test_missing_tuner_class_is_a_named_third_outcome(self):
        class _NoTuner:
            pass

        with _swap_objective(_NoTuner()):
            s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4)
        self.assertFalse(s["measured"])
        self.assertIn("AllocationTuner", s["reason"])

    def test_unimportable_objective_is_a_named_third_outcome(self):
        def _boom(name):
            raise ImportError(f"нет модуля {name}")

        s = M.objective_size_sensitivity(100_000.0, 5_000_000.0, 0.4,
                                         importer=_boom)
        self.assertFalse(s["measured"])
        self.assertIn("ImportError", s["reason"])

    def test_unread_policy_is_not_replaced_by_a_literal(self):
        for floor, cap in ((None, 0.4), (5_000_000.0, None)):
            with self.subTest(floor=floor, cap=cap):
                s = M.objective_size_sensitivity(100_000.0, floor, cap)
                self.assertFalse(s["measured"])
                self.assertIn("TunerConstraints", s["reason"])
                self.assertIsNone(s["size_aware"])

    def test_unread_capital_is_not_replaced_by_a_zero(self):
        s = M.objective_size_sensitivity(0.0, 5_000_000.0, 0.4)
        self.assertFalse(s["measured"])
        self.assertIn("капитал", s["reason"])
        self.assertIsNone(s["rate_at_small_pp"])

    def test_unaskable_objective_makes_the_run_unchecked_not_linear(self):
        """Порванное звено НЕ возвращает прежнее умолчание «функция линейна»."""
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp, {"b": 10_000.0}, {"b": _row()})
            # Подменяется РОВНО доходностный член: потолки политики живут в том
            # же модуле и переносятся настоящими, иначе замер отвечал бы «пороги
            # не прочитаны», а не «функцию спросить нечем».
            with _swap_objective(_keeping_real_constraints(_BrokenObjectiveModule())):
                rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertNotIn("objective_is_linear_in_rate", kinds)
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertTrue(any("НЕ СПРОСИЛИ" in u for u in rep["unchecked"]))

    def _snapshot(self, tmp, positions, adapters, capital=100_000.0):
        with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
            json.dump({"adapters": adapters}, fh)
        with open(os.path.join(tmp, "current_positions.json"), "w") as fh:
            json.dump({"capital_usd": capital, "positions": positions}, fh)


class TestCriterionBlock(unittest.TestCase):
    """Вердикт критерия §49 — по ОСИ находки, и НЕ есть `overall`."""

    _MEASURED = {"measured": True, "size_aware": True, "rate_at_small_pp": 8.0,
                 "rate_at_large_pp": 7.0, "small_usd": 40.0, "large_usd": 40_000.0,
                 "reference_dilution_pp": 0.03, "delta_pp": 1.0, "reason": None}

    def test_found_axis_gives_not_satisfied(self):
        block = M._criterion_block(
            [{"kind": "objective_is_linear_in_rate", "severity": "INFO"}],
            [], self._MEASURED, deployed_usd=95_000.0)
        self.assertEqual(block["status"], M.CRITERION_NOT_SATISFIED)
        self.assertEqual(block["found"], ["objective_is_linear_in_rate"])

    def test_found_axis_survives_incompleteness_beside_it(self):
        """Утверждение СУЩЕСТВОВАНИЯ не отменяется непрочитанным рядом.

        Ровно здесь перенос `overall` соврал бы: у прибора третий исход стои́т
        выше `CRITICAL`, и измеренное красное владельца стало бы «не измерено».
        """
        block = M._criterion_block(
            [{"kind": "objective_is_linear_in_rate", "severity": "INFO"},
             {"kind": "denominator_is_a_literal", "severity": "WARN"}],
            ["снимок адаптеров не прочитан"], self._MEASURED, deployed_usd=95_000.0)
        self.assertEqual(block["status"], M.CRITERION_NOT_SATISFIED)

    def test_unobserved_axis_alone_gives_the_third_outcome(self):
        block = M._criterion_block(
            [{"kind": "denominator_is_a_literal", "severity": "WARN"}],
            [], self._MEASURED, deployed_usd=95_000.0)
        self.assertEqual(block["status"], M.CRITERION_UNMEASURED)
        self.assertIn("denominator_is_a_literal", block["reason"])

    def test_unchecked_alone_gives_the_third_outcome(self):
        block = M._criterion_block([], ["целевую функцию НЕ СПРОСИЛИ: …"],
                                   {"measured": False, "reason": "…",
                                    "size_aware": None},
                                   deployed_usd=95_000.0)
        self.assertEqual(block["status"], M.CRITERION_UNMEASURED)

    def test_unknown_finding_kind_breaks_the_verdict_by_name(self):
        block = M._criterion_block([{"kind": "brand_new_thing", "severity": "INFO"}],
                                   [], self._MEASURED, deployed_usd=95_000.0)
        self.assertEqual(block["status"], M.CRITERION_UNMEASURED)
        self.assertIn("brand_new_thing", block["reason"])

    def test_empty_book_is_not_a_green_verdict(self):
        block = M._criterion_block(
            [{"kind": "objective_reacts_to_our_size", "severity": "INFO"}],
            [], self._MEASURED, deployed_usd=0.0)
        self.assertEqual(block["status"], M.CRITERION_UNMEASURED)
        self.assertIn("мёртвого дерева", block["reason"])

    def test_green_path_needs_a_size_aware_objective_and_a_live_book(self):
        block = M._criterion_block(
            [{"kind": "objective_reacts_to_our_size", "severity": "INFO"}],
            [], self._MEASURED, deployed_usd=95_000.0)
        self.assertEqual(block["status"], M.CRITERION_SATISFIED)

    def test_every_emitted_kind_has_a_declared_axis(self):
        """Перечень осей ЗАКРЫТ, и он обязан покрывать всё, что прибор рождает.

        Вид, который прибор печатает, но осью не объявил, обрывал бы вердикт
        третьим исходом на живом дереве — то есть сторож замолчал бы от
        собственной неполноты.
        """
        import re
        with open(M.__file__, encoding="utf-8") as fh:
            body = fh.read()
        emitted = set(re.findall(r'"kind":\s*"([a-z_]+)"', body))
        self.assertTrue(emitted, "виды находок в теле прибора не найдены вовсе")
        self.assertEqual(emitted - set(M.FINDING_AXIS), set())

    def test_criterion_verdict_is_not_the_overall_ladder(self):
        """`overall` и вердикт критерия РАСХОДЯТСЯ — и это цель, а не побочность."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
                json.dump({"adapters": {"b": _row()}}, fh)
            with open(os.path.join(tmp, "current_positions.json"), "w") as fh:
                json.dump({"capital_usd": 100_000.0,
                           "positions": {"b": 10_000.0}}, fh)
            rep = M.run(root=tmp, data_dir=tmp, write=False, now=_T0)
        self.assertEqual(rep["overall"], "INFO")
        self.assertEqual(rep["criterion"]["status"], M.CRITERION_NOT_SATISFIED)


class TestCriterionDeclaration(unittest.TestCase):
    def test_instrument_declares_the_criterion_by_anchor(self):
        self.assertTrue(M.CRITERION.startswith("§49 Marginal return"))

    def test_manifest_binds_this_artifact_in_the_canonical_form(self):
        """Привязка читается из ЖИВОЙ конституции, а не из фикстуры (урок #730)."""
        from spa_core.monitoring import s49_criterion_price as price

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(M.__file__))))
        bindings = price.parse_bindings(price.read_manifest(root))["bindings"]
        rows = bindings.get("Marginal return")
        self.assertIsNotNone(rows, "конституция не объявляет меру `Marginal return`")
        self.assertEqual([r["path"] for r in rows], [M.REPORT_REL])
        self.assertEqual(rows[0]["form"], price.CANONICAL_FORM)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
