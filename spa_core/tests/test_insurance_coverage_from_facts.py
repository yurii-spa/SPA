"""
Страховое покрытие ИЗМЕРЕНО базой — выбрасывать его нельзя (карточка
``agent-insurance-scorer-otbrasyvaet-izvestnoe-pokrytie``, цикл #366).

Авария настоящая и зеркальна починенной казне: там ВЫДУМЫВАЛИ число, которого
нет, здесь ВЫБРАСЫВАЛИ число, которое есть. На контекст-пути
``protocol_insurance_scorer`` жёстко проставлял ``has_insurance=False`` и
``insurance_coverage_pct=0.0``, хотя ``_protocol_facts`` знает покрытие
(``systemic.insurance_pct_of_tvl`` → ``insurance_coverage_pct`` профиля) и оно
РАЗЛИЧАЕТСЯ между протоколами.

Последствие было не косметическим. ``_ModuleAdapter._coerce_score`` не находил в
результате НИ ОДНОГО ключа из ``_SCORE_KEYS`` и падал в fallback «первый
попавшийся ``*_score``» — по порядку вставки это ``coverage_score``, равный 0.0
у КАЖДОГО протокола. Отсюда разметка ``blind_equal`` и исключение модуля из
composite и из confidence: модуль был слеп не по природе задачи, а из-за двух
подстановок подряд.

Замер цикла #366 на 35 протоколах базы:
  ДО:    risk_score = 0.0 у всех 35 (1 различное значение);
  ПОСЛЕ: 10 различных значений, 67.71 (aave_v3, лучше всех защищён) …
         90.80 (aerodrome/usual/velodrome/wusdm).
Влияние на composite (Tier-B, sandbox, тройка аудита):
  aave_v3 35.71 → 35.87 · maple 40.72 → 41.03 · pendle 40.18 → 40.49;
  modules_ok 92→93 / 76→77 — модуль вернулся в composite и в confidence.
Слой advisory: Risk Scoring v2 НИКОГДА не гейтит исполнение (инвариант #1).

Положительный контроль: на модуле с ``origin/main`` (49c279d5a) краснеют все
тесты этого файла, кроме помеченных «страж» — они про будущую регрессию, и это
сказано вслух, чтобы набор не выглядел сильнее, чем он есть.
"""

import unittest

from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics._protocol_blindness import PROTOCOL_BLIND_DETAIL
from spa_core.analytics.protocol_insurance_scorer import ProtocolInsuranceScorer
from spa_core.analytics.signal_aggregator import _ModuleAdapter


def _ctx(protocol):
    """Чистый протокол-контекст (без доменных ключей) — путь профиля."""
    return {"cycle_ts": "2026-08-24T00:00:00Z", "protocol": protocol}


class TestCoverageComesFromFactsBase(unittest.TestCase):
    """Покрытие в результате = покрытие базы, протокол за протоколом."""

    def setUp(self):
        self.scorer = ProtocolInsuranceScorer()
        self.protocols = sorted(pf.known_protocols())

    def test_base_actually_knows_coverage(self):
        """Страж-предпосылка: если база перестанет различать покрытие, все
        остальные тесты файла станут украшением — это должно быть видно."""
        vals = {float(pf.facts_for(p)["systemic"]["insurance_pct_of_tvl"])
                for p in self.protocols}
        self.assertGreater(len(vals), 1,
                           f"база больше не различает покрытие: {vals}")

    def test_legacy_payload_carries_measured_coverage(self):
        """Контекст-ветка кладёт в payload ИЗМЕРЕННОЕ покрытие профиля."""
        for proto in self.protocols:
            with self.subTest(protocol=proto):
                expected = float(
                    pf.facts_for(proto)["systemic"]["insurance_pct_of_tvl"])
                res = self.scorer.score(_ctx(proto), write_log=False)
                self.assertIsNotNone(res, f"{proto}: dormant там, где база знает протокол")
                self.assertEqual(self.scorer.get_score_breakdown()["protocol"],
                                 pf.facts_for(proto)["name"])
                inner = self.scorer._last_result
                self.assertAlmostEqual(
                    float(inner["insurance_coverage_pct"]), expected, places=6,
                    msg=f"{proto}: покрытие базы {expected} выброшено")

    def test_has_insurance_follows_measured_coverage(self):
        """``has_insurance`` — ФАКТ (покрытие > 0), а не литерал False."""
        for proto in self.protocols:
            with self.subTest(protocol=proto):
                expected = float(
                    pf.facts_for(proto)["systemic"]["insurance_pct_of_tvl"]) > 0.0
                self.scorer.score(_ctx(proto), write_log=False)
                self.assertEqual(bool(self.scorer._last_result["has_insurance"]),
                                 expected)

    def test_coverage_score_differs_between_protocols(self):
        """Компонента покрытия перестала быть константой 0.0 у всех."""
        seen = set()
        for proto in self.protocols:
            self.scorer.score(_ctx(proto), write_log=False)
            seen.add(self.scorer._last_result["coverage_score"])
        self.assertGreater(len(seen), 1, f"coverage_score всё ещё константа: {seen}")

    def test_zero_coverage_stays_an_honest_zero(self):
        """Страж: измеренный НОЛЬ остаётся нулём — починка не подставляет
        покрытие там, где база честно говорит 0 (обратный контроль)."""
        zeros = [p for p in self.protocols
                 if float(pf.facts_for(p)["systemic"]["insurance_pct_of_tvl"]) == 0.0]
        self.assertTrue(zeros, "в базе не осталось протоколов без покрытия — тест ослеп")
        for proto in zeros:
            with self.subTest(protocol=proto):
                self.scorer.score(_ctx(proto), write_log=False)
                inner = self.scorer._last_result
                self.assertEqual(float(inner["insurance_coverage_pct"]), 0.0)
                self.assertFalse(inner["has_insurance"])
                self.assertEqual(inner["coverage_score"], 0.0)

    def test_provider_is_not_fabricated(self):
        """Имя страховщика база не знает ⇒ пустая строка, а не выдуманное имя."""
        self.scorer.score(_ctx("aave_v3"), write_log=False)
        self.assertEqual(self.scorer._last_result["insurance_provider"], "")


class TestContextScoreIsNoLongerProtocolBlind(unittest.TestCase):
    """То, ради чего починка: агрегатор получает РАЗНЫЕ числа."""

    def setUp(self):
        self.scorer = ProtocolInsuranceScorer()
        self.protocols = sorted(pf.known_protocols())

    def _scores(self):
        out = {}
        for proto in self.protocols:
            res = self.scorer.score(_ctx(proto), write_log=False)
            self.assertIsNotNone(res, f"{proto}: dormant")
            out[proto] = res["risk_score"]
        return out

    def test_scores_differ_across_universe(self):
        scores = self._scores()
        self.assertGreater(
            len(set(scores.values())), 1,
            "risk_score одинаков у всех протоколов — модуль по-прежнему слеп")

    def test_audit_trio_is_not_equal(self):
        """Аудит слепоты судит по тройке aave_v3/maple/pendle — на ней и
        должно различаться, иначе разметка вернёт модуль в слепые."""
        trio = {p: self.scorer.score(_ctx(p), write_log=False)["risk_score"]
                for p in ("aave_v3", "maple", "pendle")}
        self.assertEqual(len(set(trio.values())), 3, trio)

    def test_nonexistent_protocol_still_dormant(self):
        """Страж: контрольный несуществующий протокол → None, не фабрикация."""
        self.assertIsNone(
            self.scorer.score(_ctx("__nonexistent_control__"), write_log=False))

    def test_polarity_more_protection_means_less_risk(self):
        """Шкала модуля: больше = ЛУЧШЕ защищён. Агрегатор ждёт обратного."""
        for proto in ("aave_v3", "maple", "pendle", "yearn_v3"):
            with self.subTest(protocol=proto):
                res = self.scorer.score(_ctx(proto), write_log=False)
                total = float(self.scorer._last_result["total_insurance_score"])
                self.assertAlmostEqual(res["risk_score"], 100.0 - total, places=3)

    def test_best_protected_gets_lowest_risk(self):
        scores = self._scores()
        best = min(scores, key=lambda p: scores[p])
        self.scorer.score(_ctx(best), write_log=False)
        best_total = float(self.scorer._last_result["total_insurance_score"])
        for proto, val in scores.items():
            if proto == best:
                continue
            self.scorer.score(_ctx(proto), write_log=False)
            self.assertLessEqual(
                float(self.scorer._last_result["total_insurance_score"]),
                best_total + 1e-9,
                f"{proto} защищён лучше {best}, но получил больший риск")

    def test_coerce_reads_risk_score_not_coverage_score(self):
        """Именно тот механизм: без явного ключа коэрция брала первый
        попавшийся ``*_score`` — ``coverage_score``, равный 0.0 у всех."""
        for proto in ("aave_v3", "maple", "pendle"):
            with self.subTest(protocol=proto):
                inner = dict(self.scorer.score(_ctx(proto), write_log=False) or {})
                full = dict(self.scorer._last_result)
                coerced = _ModuleAdapter._coerce_score(full)
                self.assertAlmostEqual(
                    coerced, 100.0 - float(full["total_insurance_score"]), places=3)
                self.assertNotEqual(coerced, full["coverage_score"])
                self.assertAlmostEqual(inner["risk_score"], coerced, places=3)


class TestLegacyPathUntouched(unittest.TestCase):
    """Публичный контракт модуля не изменён — переворот знака живёт ТОЛЬКО
    на контекст-пути (это забота адаптера, а не шкалы модуля)."""

    FULL = {
        "protocol": "test_protocol",
        "has_insurance": True,
        "insurance_coverage_pct": 80.0,
        "insurance_provider": "nexus_mutual",
        "treasury_usd": 50_000_000.0,
        "tvl_usd": 1_000_000_000.0,
        "bug_bounty_usd": 1_000_000.0,
        "has_timelock": True,
        "timelock_days": 7,
    }

    def test_direct_payload_has_no_injected_risk_score(self):
        res = ProtocolInsuranceScorer().score(dict(self.FULL), write_log=False)
        self.assertNotIn("risk_score", res)
        self.assertEqual(res["insurance_coverage_pct"], 80.0)
        self.assertTrue(res["has_insurance"])


class TestBlindnessMarkupRegenerated(unittest.TestCase):
    def test_module_no_longer_marked_blind(self):
        """Разметка перегенерирована аудитом (не руками): модуль ушёл из
        слепых и вернулся в composite."""
        self.assertNotIn("protocol_insurance_scorer", PROTOCOL_BLIND_DETAIL)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
