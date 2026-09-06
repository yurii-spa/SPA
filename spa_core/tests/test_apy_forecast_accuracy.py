"""Сторож §49 ТЗ «Portfolio CIO» → «Forecast accuracy».

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на замер 2026-09-06 по живой истории
ADR-060: проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`). Воспроизводятся ровно те три факта, ради
которых модуль написан: (1) прогноз бывает ПРОТИВОПОЛОЖЕН факту по знаку,
(2) худшее завышение почти равно зазору, которым решается гейт, (3) полностью
сверен ОДИН день из 32 — популяция, на которой «точность» не утверждается.

FROZEN-DATE-OK: injected-clock — `run(..., now=_NOW)`: единственная дверь модуля
к часам это параметр `now`, он же попадает в `generated_at` (закреплено
`test_run_ITSELF_uses_the_injected_clock_not_the_wall`). Строки `cycle_date`
здесь — ЯРЛЫКИ вердиктов, а не отметки свежести: сверка идёт по ПОРЯДКУ записей
в истории, календарь в ней не участвует ни одним сравнением
(`test_scoring_never_consults_the_calendar`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from spa_core.monitoring import apy_forecast_accuracy as A

# FROZEN-DATE-OK: injected-clock — единственная дверь модуля к часам это параметр
# `now`; якорь `_NOW` ниже передаётся в `A.run(..., now=_NOW)` и он же попадает в
# `generated_at` (закреплено `test_run_ITSELF_uses_the_injected_clock_not_the_wall`).
# Строки `cycle_date` в фикстурах — ЯРЛЫКИ вердиктов, а не отметки свежести:
# сверка идёт по ПОРЯДКУ записей истории, календарь в ней не участвует ни одним
# сравнением — это отдельный контроль `test_scoring_never_consults_the_calendar`,
# который сдвигает те же ярлыки на десять лет и требует того же вердикта.
_NOW = dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=dt.timezone.utc)


# ── Фикстуры: форма записи взята с живой истории, числа — из замера ───────────

def _rec(date: str, *, gain_pp: float, cur: dict, tgt: dict,
         capital: float = 100_000.0, band: float = 0.5,
         apy: dict | None = None, verdict: str = "HOLD") -> dict:
    return {
        "cycle_date": date,
        "verdict": verdict,
        "gain_pp": gain_pp,
        "capital_usd": capital,
        "required_gain_pp": band,
        "current_positions": dict(cur),
        "target_positions": dict(tgt),
        "apy_evidenced_pct": dict(apy or {}),
    }


def _deltas_of(rec: dict) -> dict:
    cur, tgt = rec.get("current_positions") or {}, rec.get("target_positions") or {}
    out = {}
    for p in set(cur) | set(tgt):
        d = float(tgt.get(p, 0.0) or 0.0) - float(cur.get(p, 0.0) or 0.0)
        if abs(d) > 0.005:
            out[p] = d
    return out


def _day_gain(deltas: dict, apy_map: dict):
    missing = sorted(p for p in deltas if apy_map.get(p) is None)
    if missing:
        return None, missing
    return sum(d * float(apy_map[p]) / 100.0 / 365.0 for p, d in deltas.items()), []


def _score(records, horizon_days=7):
    return A.score_window(records, horizon_days=horizon_days,
                          day_gain=_day_gain, deltas_of=_deltas_of)


class TestDirection(unittest.TestCase):
    """Ошибка НАПРАВЛЕНИЯ — не то же, что ошибка величины."""

    def _incident_2026_08_06(self):
        """Дословный повтор аварии: $35k из morpho_steakhouse в aave_v3.

        Прогноз обещал +0.523 пп; наблюдённые ставки следующих дней показали
        morpho_steakhouse ЛУЧШЕ — перекладка теряла деньги.
        """
        head = _rec("d0", gain_pp=0.52332,
                    cur={"aave_v3": 5_000.0, "morpho_steakhouse": 40_000.0},
                    tgt={"aave_v3": 40_000.0, "morpho_steakhouse": 5_000.0})
        fwd = [_rec(f"d{i}", gain_pp=0.0, cur={}, tgt={},
                    apy={"aave_v3": a, "morpho_steakhouse": m})
               for i, (a, m) in enumerate(
                   [(3.3118, 3.4028), (3.3068, 3.3196)], start=1)]
        return [head] + fwd

    def test_sign_disagreement_is_detected(self):
        s = _score(self._incident_2026_08_06())[0]
        self.assertTrue(s["scored"])
        self.assertGreater(s["claimed_usd_per_day"], 0.0)
        self.assertLess(s["realised_usd_per_day"], 0.0)
        self.assertTrue(s["sign_disagrees"])

    def test_direction_lists_the_incident(self):
        signs = A.direction(_score(self._incident_2026_08_06()))
        self.assertEqual(len(signs), 1)
        self.assertEqual(signs[0]["cycle_date"], "d0")

    def test_a_forecast_that_came_true_is_NOT_a_sign_disagreement(self):
        """Обратный контроль: сторож обязан молчать на верном прогнозе."""
        head = _rec("d0", gain_pp=0.52332,
                    cur={"aave_v3": 5_000.0, "morpho_steakhouse": 40_000.0},
                    tgt={"aave_v3": 40_000.0, "morpho_steakhouse": 5_000.0})
        fwd = [_rec("d1", gain_pp=0.0, cur={}, tgt={},
                    apy={"aave_v3": 5.0, "morpho_steakhouse": 3.0})]
        s = _score([head] + fwd)[0]
        self.assertFalse(s["sign_disagrees"])
        self.assertEqual(A.direction([s]), [])


class TestMagnitude(unittest.TestCase):
    """Величина: «обещано / вышло» и КОГО в неё пускают."""

    @staticmethod
    def _pair(gain_pp, realised_apy, band=0.5):
        """Одна нога: $10k из a в b, где b даёт `realised_apy`, a — 0 %."""
        head = _rec("d0", gain_pp=gain_pp, band=band,
                    cur={"a": 10_000.0, "b": 0.0}, tgt={"a": 0.0, "b": 10_000.0})
        fwd = [_rec("d1", gain_pp=0.0, cur={}, tgt={},
                    apy={"a": 0.0, "b": realised_apy})]
        return [head] + fwd

    def test_ratio_is_claim_over_realised(self):
        # Обещано 1.0 пп на $100k = 2.7397 $/дн.; вышло 10 % на $10k = 2.7397 $/дн.
        s = _score(self._pair(1.0, 10.0))[0]
        self.assertAlmostEqual(s["ratio_claimed_over_realised"], 1.0, places=3)

    def test_only_band_material_days_enter_the_calibration(self):
        """Дни ниже полосы ГЕЙТА в калибровку не идут — там точность ни на что
        не влияет, и разбавлять ею ответ значило бы прятать существенные дни."""
        below = _score(self._pair(0.1, 10.0, band=0.5))[0]
        above = _score(self._pair(1.0, 10.0, band=0.5))[0]
        self.assertFalse(below["band_material"])
        self.assertTrue(above["band_material"])
        self.assertEqual(A.magnitude([below])["n"], 0)
        self.assertEqual(A.magnitude([above])["n"], 1)

    def test_materiality_follows_the_RECORDED_band_not_a_local_literal(self):
        """Полоса читается из САМОЙ записи: сдвинули полосу — сдвинулся состав."""
        wide = _score(self._pair(1.0, 10.0, band=2.0))[0]
        narrow = _score(self._pair(1.0, 10.0, band=0.5))[0]
        self.assertFalse(wide["band_material"])
        self.assertTrue(narrow["band_material"])

    def test_empty_calibration_says_WHY_not_zero(self):
        """Пустая популяция — причина, а не число: ноль читался бы как замер."""
        m = A.magnitude([])
        self.assertEqual(m["n"], 0)
        self.assertIn("reason", m)


class TestPopulationHonesty(unittest.TestCase):
    """Чего мы сказать НЕ можем — обязано быть сказано вслух."""

    def test_unpriced_leg_makes_the_day_UNCHECKED_never_interpolated(self):
        head = _rec("d0", gain_pp=1.0, cur={"a": 10_000.0, "b": 0.0},
                    tgt={"a": 0.0, "b": 10_000.0})
        fwd = [_rec("d1", gain_pp=0.0, cur={}, tgt={}, apy={"a": 0.0})]  # b нет
        s = _score([head] + fwd)[0]
        self.assertFalse(s["scored"])
        self.assertEqual(s["reason"], "no_evidenced_apy_for_moved_legs")
        self.assertIn("b", s["unpriced_protocols"])

    def test_fully_checked_requires_the_WHOLE_horizon(self):
        head = _rec("d0", gain_pp=1.0, cur={"a": 10_000.0, "b": 0.0},
                    tgt={"a": 0.0, "b": 10_000.0})
        fwd = [_rec(f"d{i}", gain_pp=0.0, cur={}, tgt={},
                    apy={"a": 0.0, "b": 10.0}) for i in range(1, 4)]
        partial = _score([head] + fwd, horizon_days=7)[0]
        full = _score([head] + fwd, horizon_days=3)[0]
        self.assertTrue(partial["scored"])
        self.assertFalse(partial["fully_checked"])
        self.assertTrue(full["fully_checked"])

    def test_nothing_proposed_is_not_scored(self):
        head = _rec("d0", gain_pp=0.0, cur={"a": 10_000.0}, tgt={"a": 10_000.0})
        s = _score([head, _rec("d1", gain_pp=0.0, cur={}, tgt={})])[0]
        self.assertFalse(s["scored"])
        self.assertEqual(s["reason"], "nothing_proposed")

    def test_a_verdict_without_its_own_capital_is_NOT_scored(self):
        """Знаменатель берётся из САМОЙ записи; подставить книгу из другого
        места значило бы сверить обещание одного дня со ставкой другого."""
        head = _rec("d0", gain_pp=1.0, cur={"a": 10_000.0, "b": 0.0},
                    tgt={"a": 0.0, "b": 10_000.0})
        head.pop("capital_usd")
        s = _score([head, _rec("d1", gain_pp=0.0, cur={}, tgt={},
                               apy={"a": 0.0, "b": 10.0})])[0]
        self.assertFalse(s["scored"])
        self.assertEqual(s["reason"], "no_capital")

    def test_scoring_never_consults_the_calendar(self):
        """Ярлыки дат сдвинуты на десять лет — вердикт обязан не измениться.

        Это и есть основание пометки FROZEN-DATE-OK наверху файла: календарь в
        сверке не участвует, порядок задают сами записи.
        """
        head = _rec("d0", gain_pp=1.0, cur={"a": 10_000.0, "b": 0.0},
                    tgt={"a": 0.0, "b": 10_000.0})
        fwd = [_rec("d1", gain_pp=0.0, cur={}, tgt={}, apy={"a": 0.0, "b": 10.0})]
        base = _score([head] + fwd)[0]
        shifted = [dict(head, cycle_date="2036-01-01"),
                   dict(fwd[0], cycle_date="2036-01-02")]
        self.assertEqual(base["ratio_claimed_over_realised"],
                         _score(shifted)[0]["ratio_claimed_over_realised"])


class TestGateRelation(unittest.TestCase):
    """Смысл ошибки — не её величина, а отношение к ЗАЗОРУ гейта (ADR-243)."""

    @staticmethod
    def _shadow(payback=23.11, gain_pp=1.91706, band=0.75):
        return {"payback_days": payback, "gain_pp": gain_pp,
                "required_gain_pp": band}

    def test_the_finding_threshold_MOVES_with_the_gate_margin(self):
        """Порог — САМ зазор, а не подобранное число: одна и та же ошибка при
        РАЗНЫХ зазорах обязана давать разные ответы. Константа в этом месте на
        такую пару не отреагирует."""
        err = 1.2953  # худшее наблюдённое завышение, замер 06.09
        narrow = A.gate_relation(err, self._shadow(payback=23.11), 30.0)
        wide = A.gate_relation(err, self._shadow(payback=4.0), 30.0)
        self.assertFalse(narrow["error_exceeds_margin"])   # ×1.2981 — едва выше
        self.assertAlmostEqual(narrow["payback_margin"], 1.2981, places=3)
        self.assertTrue(wide["payback_margin"] > err)
        self.assertFalse(wide["error_exceeds_margin"])
        # Зазор УЖЕ ошибки ⇒ гейт переворачивается.
        tight = A.gate_relation(err, self._shadow(payback=29.0), 30.0)
        self.assertTrue(tight["error_exceeds_margin"])

    def test_margin_consumption_is_reported_even_when_not_crossed(self):
        """«Не пересекло» — не весь ответ: 99.8 % и 3 % обязаны читаться по-разному."""
        g = A.gate_relation(1.2953, self._shadow(), 30.0)
        self.assertFalse(g["error_exceeds_margin"])
        self.assertAlmostEqual(g["margin_consumed_pct"], 99.78, places=1)

    def test_the_TIGHTEST_of_the_two_gates_decides(self):
        """Гейта два; решает тот, у кого запас меньше."""
        g = A.gate_relation(1.0, self._shadow(), 30.0)
        self.assertAlmostEqual(g["gain_band_margin"], 2.5561, places=3)
        self.assertEqual(g["tightest_gate_margin"], g["payback_margin"])

    def test_horizon_comes_from_its_home_not_from_a_local_literal(self):
        """Сдвинули горизонт — сдвинулся зазор. Литерал 30.0 на это не ответит."""
        a = A.gate_relation(1.0, self._shadow(), 30.0)["payback_margin"]
        b = A.gate_relation(1.0, self._shadow(), 99.0)["payback_margin"]
        self.assertNotEqual(a, b)

    def test_no_recorded_verdict_means_the_margin_is_NOT_invented(self):
        g = A.gate_relation(1.3, None, 30.0)
        self.assertNotIn("payback_margin", g)
        self.assertIn("reason", g)


class TestThirdOutcome(unittest.TestCase):
    """«Не измерено» — самостоятельный исход, не ноль и не скип.

    `test_a_history_that_scores_NOTHING_is_UNCHECKED_not_OK` добавлен по находке
    мутации цикла #504: подмена `overall = _UNCHECKED` на `"OK"` в конце `run`
    МОЛЧАЛА, потому что оба прежних теста уходили в РАННИЙ возврат «истории
    нет» и до мутируемой строки не доходили никогда. Класс известный —
    «сторож не проверен, потому что при текущем умолчании он избыточен»:
    пустой каталог отвечал на СВОЙ вопрос, а не на нужный.
    """

    @staticmethod
    def _root_with_history(records) -> str:
        import tempfile
        root = tempfile.mkdtemp(prefix="afa_hist_")
        os.makedirs(os.path.join(root, "data"), exist_ok=True)
        with open(os.path.join(root, "data",
                               "allocation_rationale_history.jsonl"),
                  "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return root

    def test_a_history_that_scores_NOTHING_is_UNCHECKED_not_OK(self):
        """История ЕСТЬ, сверять в ней нечего — отчёт не смеет выглядеть чистым.

        Это не то же, что «истории нет»: сюда доходит полный путь `run`, и
        именно здесь вердикт назначается в последний раз.
        """
        root = self._root_with_history([
            _rec("d0", gain_pp=0.0, cur={"a": 10_000.0}, tgt={"a": 10_000.0}),
            _rec("d1", gain_pp=0.0, cur={"a": 10_000.0}, tgt={"a": 10_000.0}),
        ])
        doc = A.run(root=root, now=_NOW, write=False)
        self.assertEqual(doc["population"]["days_observed"], 2,
                         "история обязана быть ПРОЧИТАНА, иначе тест мерит не то")
        self.assertEqual(doc["population"]["scoreable"], 0)
        self.assertEqual(doc["overall"], "UNCHECKED")
        self.assertGreater(doc["counts"]["unchecked"], 0)

    def test_a_history_that_DOES_score_is_not_UNCHECKED(self):
        """Обратный контроль той же строки: сверяемая история даёт вердикт."""
        root = self._root_with_history([
            _rec("d0", gain_pp=1.0, cur={"a": 10_000.0, "b": 0.0},
                 tgt={"a": 0.0, "b": 10_000.0}),
            _rec("d1", gain_pp=0.0, cur={}, tgt={}, apy={"a": 0.0, "b": 10.0}),
        ])
        doc = A.run(root=root, now=_NOW, write=False)
        self.assertEqual(doc["population"]["scoreable"], 1)
        self.assertNotEqual(doc["overall"], "UNCHECKED")

    def test_empty_history_is_UNCHECKED_not_OK(self):
        doc = A.run(root=_tmp_root(), now=_NOW, write=False)
        self.assertEqual(doc["overall"], "UNCHECKED")
        self.assertTrue(doc["unchecked"])

    def test_UNCHECKED_is_not_silently_a_clean_pass(self):
        doc = A.run(root=_tmp_root(), now=_NOW, write=False)
        self.assertNotEqual(doc["overall"], "OK")
        self.assertEqual(doc["counts"]["critical"], 0)
        self.assertGreater(doc["counts"]["unchecked"], 0)


class TestClock(unittest.TestCase):
    def test_run_ITSELF_uses_the_injected_clock_not_the_wall(self):
        """Инъекция обязана доходить до `run`. «Половина инъекции» — та же бомба."""
        doc = A.run(root=_tmp_root(), now=_NOW, write=False)
        self.assertEqual(doc["generated_at"], _NOW.isoformat())
        other = _NOW + dt.timedelta(days=365)
        self.assertEqual(A.run(root=_tmp_root(), now=other,
                               write=False)["generated_at"], other.isoformat())


class TestReuse(unittest.TestCase):
    """Формула выгоды ПЕРЕИСПОЛЬЗУЕТСЯ, а не написана здесь заново (§3 ТЗ)."""

    def test_run_takes_the_formula_from_the_forecasts_own_producer(self):
        from spa_core.paper_trading import shadow_trigger_eval as ste
        doc = A.run(root=_tmp_root(), now=_NOW, write=False)
        self.assertIn("shadow_trigger_eval", doc["provenance"]["formula"])
        # Имя объявлено — и оно существует у производителя.
        for attr in ("_day_gain_usd", "_deltas", "DEFAULT_HORIZON_DAYS"):
            self.assertTrue(hasattr(ste, attr), f"{attr} исчез у производителя")

    def test_module_holds_no_second_copy_of_the_gain_formula(self):
        """Вторая копия формулы разошлась бы молча — её здесь быть не должно."""
        with open(A.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("/ 100.0 / 365.0", src,
                         "похоже, дневная выгода пересчитана здесь заново")


class TestWiring(unittest.TestCase):
    """У артефакта обязан быть ДОМ (ДВЕ записи манифеста) и ПОТРЕБИТЕЛЬ.

    Удаление ЛЮБОЙ из двух записей манифеста не красит ни один существующий
    сторож (замер #502) — поэтому обе проверяются здесь поимённо.
    """

    @staticmethod
    def _manifest():
        with open(os.path.join(A.REPO_ROOT, "architecture", "manifest.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_artifact_has_a_top_level_manifest_entry(self):
        entry = [a for a in self._manifest()["artifacts"]
                 if a.get("path") == A.REPORT_REL]
        self.assertEqual(len(entry), 1, f"нет записи artifacts[{A.REPORT_REL}]")
        self.assertEqual(entry[0]["producer"], "com.spa.decision_loop")
        self.assertIn("orchestrator_protocol", entry[0]["consumers"])

    def test_artifact_is_in_the_producers_passport(self):
        agent = [a for a in self._manifest()["agents"]
                 if a.get("label") == "com.spa.decision_loop"]
        self.assertEqual(len(agent), 1)
        self.assertIn(A.REPORT_REL, {p["artifact"] for p in agent[0]["produces"]},
                      "артефакт не объявлен в produces паспорта производителя")

    def test_producer_declares_the_artifact(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(A.REPORT_REL, findings_bridge.PRODUCES)

    def test_the_producer_actually_CALLS_the_module(self):
        """`PRODUCES` — обещание; без строки вызова артефакта не будет вовсе."""
        from spa_core.monitoring import findings_bridge
        with open(findings_bridge.__file__.replace(".pyc", ".py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("from spa_core.monitoring import apy_forecast_accuracy", src)
        self.assertIn("apy_forecast_accuracy.run(", src,
                      "мост объявляет артефакт, но не зовёт его производителя")

    def test_the_consumer_branch_exists_by_name(self):
        """Проверяется ВЕТКА, а не упоминание имени: имя есть и в таблице полей,
        поэтому поиск подстрокой зеленел бы и на снятой ветке (замер #503)."""
        path = os.path.join(A.REPO_ROOT, "scripts", "consume_office_reports.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('elif name == "apy_forecast_accuracy.json":', src,
                      "у отчёта нет ИМЕННОЙ печатающей ветки шага 0-офис")

    def test_the_consumer_declares_the_producer_so_the_schema_is_checkable(self):
        """Без записи в `_PRODUCER` схема отчёта остаётся несверяемой (#503)."""
        path = os.path.join(A.REPO_ROOT, "scripts", "consume_office_reports.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('"apy_forecast_accuracy.json": '
                      '"spa_core/monitoring/apy_forecast_accuracy.py"', src)


class TestAdvisory(unittest.TestCase):
    """Модуль НАЗЫВАЕТ, но не чинит: money-path — решение владельца."""

    def test_report_says_so_out_loud(self):
        doc = A.run(root=_tmp_root(), now=_NOW, write=False)
        self.assertIn("money-path", doc["advisory"])

    def test_module_never_imports_execution(self):
        with open(A.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("spa_core.execution", src)


def _tmp_root() -> str:
    """Пустой корень: истории нет ⇒ сверять нечего (третий исход)."""
    import tempfile
    root = tempfile.mkdtemp(prefix="afa_")
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    return root


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
