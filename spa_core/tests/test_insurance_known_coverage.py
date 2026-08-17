"""
Известное страховое покрытие НЕ выбрасывается — и модуль перестаёт быть слепым.

Карточка: ``agent-insurance-scorer-otbrasyvaet-izvestnoe-pokrytie.md``
(находка цикла #158; зеркало выдуманной казны ADR-070 п.15, закрытой отдельно
в ``test_insurance_treasury_unmeasured.py``).

Авария, которую воспроизводят эти тесты, настоящая — два подставленных литерала
подряд:

1. контекст-ветка ``protocol_insurance_scorer.score`` строила payload из
   структурного профиля и жёстко ставила ``has_insurance=False`` /
   ``insurance_coverage_pct=0.0``, хотя профиль НЕСЁТ измеренное покрытие
   (``systemic["insurance_pct_of_tvl"]``: aave_v3 = 1.5 %, maple = 1.0 %,
   morpho_blue = 0.5 %, pendle = 0.0 %);
2. ни один ключ результата не входил в ``_SCORE_KEYS`` агрегатора, поэтому
   коэрция падала в fallback «первый попавшийся ``*_score``» — по порядку
   вставки ``coverage_score``, а он после (1) был константным нулём у КАЖДОГО
   протокола. Замер до починки (все протоколы вселенной):
   ``risk_score = 0.0``, и модуль размечен ``blind_equal``.

Замер после починки (тот же прогон, ``_ModuleAdapter``):
aave_v3 = 67.7143 · pendle = 89.3734 · maple = 90.2306 ·
morpho_steakhouse = 89.0877 · compound_v3 = 68.2857; классификация
``scripts/audit_protocol_blindness.py::_audit_module`` — ``sensitive``
(было ``blind_equal``). ПОПРАВКА 17.08 (вечер): разметка ``_protocol_blindness.py`` С ТЕХ ПОР
ПЕРЕГЕНЕРИРОВАНА — записи про этот модуль там больше нет, он вернулся в composite.
Ниже — состояние на момент написания докстринга; оставлено как история, а не как факт.
Было: разметка ``_protocol_blindness.py`` НЕ перегенерирована
(это отдельное действие: полный Tier-B прогон переразмечает 479 модулей) —
пока она не обновлена, модуль остаётся исключённым из composite, и тесты ниже
охраняют именно поведение модуля, а не факт его возврата в composite.

Каждый тест, кроме помеченных «страж», — положительный контроль: на модуле до
починки он краснеет.

Read-only, stdlib, без сети, без записи на диск (``write_log=False`` везде).
"""

import unittest

from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics.protocol_insurance_scorer import ProtocolInsuranceScorer
from spa_core.analytics.signal_aggregator import _ModuleAdapter, _SCORE_KEYS

_HELD = ("aave_v3", "pendle", "maple", "morpho_steakhouse")
_TRIO = ("aave_v3", "maple", "pendle")          # аудиторская тройка


def _ctx(protocol):
    return {"cycle_ts": "2026-08-17T00:00:00Z", "protocol": protocol}


class _CapturingScorer(ProtocolInsuranceScorer):
    """Перехватывает payload, который контекст-ветка отдаёт своему же движку.

    Наружу уходит уже сведённый ``{"risk_score": ...}``, поэтому подстановка
    видна только здесь.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.captured = []

    def score(self, protocol_data, write_log=True):
        if isinstance(protocol_data, dict) and "tvl_usd" in protocol_data:
            self.captured.append(dict(protocol_data))
        return super().score(protocol_data, write_log=write_log)


class TestContextPathCarriesMeasuredCoverage(unittest.TestCase):
    """Сердцевина аварии: измеренное покрытие доходит до движка."""

    def test_payload_coverage_equals_structural_base(self):
        for proto in _HELD:
            with self.subTest(protocol=proto):
                sc = _CapturingScorer()
                sc.score(_ctx(proto), write_log=False)
                self.assertEqual(len(sc.captured), 1)
                profile = pf.generic_profile_for(proto)
                self.assertEqual(
                    sc.captured[0]["insurance_coverage_pct"],
                    float(profile["insurance_coverage_pct"]),
                    "покрытие обязано приходить из структурной базы, не из литерала",
                )

    def test_payload_coverage_matches_systemic_field(self):
        """Совпадение именно с ``systemic.insurance_pct_of_tvl`` базы."""
        for proto in _HELD:
            with self.subTest(protocol=proto):
                sc = _CapturingScorer()
                sc.score(_ctx(proto), write_log=False)
                facts = pf.facts_for(proto)
                self.assertEqual(
                    sc.captured[0]["insurance_coverage_pct"],
                    float(facts["systemic"]["insurance_pct_of_tvl"]),
                )

    def test_has_insurance_is_a_fact_not_a_literal(self):
        """``has_insurance`` = покрытие > 0. Обе стороны."""
        sc = _CapturingScorer()
        sc.score(_ctx("aave_v3"), write_log=False)      # покрытие 1.5 % > 0
        self.assertTrue(sc.captured[0]["has_insurance"])
        sc2 = _CapturingScorer()
        sc2.score(_ctx("pendle"), write_log=False)      # измеренный ноль
        self.assertFalse(sc2.captured[0]["has_insurance"])
        self.assertEqual(sc2.captured[0]["insurance_coverage_pct"], 0.0)

    def test_coverage_differs_between_protocols(self):
        """Литерал давал ОДИН ноль всем — теперь значения различаются."""
        seen = set()
        for proto in _HELD:
            sc = _CapturingScorer()
            sc.score(_ctx(proto), write_log=False)
            seen.add(sc.captured[0]["insurance_coverage_pct"])
        self.assertGreater(len(seen), 1)

    def test_coverage_score_no_longer_constant_zero(self):
        scores = set()
        for proto in _HELD:
            res = ProtocolInsuranceScorer().score(
                _legacy_from_profile(proto), write_log=False)
            scores.add(res["coverage_score"])
        self.assertGreater(len(scores), 1, "coverage_score снова константа")

    def test_provider_is_not_claimed(self):
        """Провайдера база не знает — «не названо», а не «провайдера нет»."""
        sc = _CapturingScorer()
        sc.score(_ctx("aave_v3"), write_log=False)
        self.assertEqual(sc.captured[0]["insurance_provider"], "")


def _legacy_from_profile(protocol, treasury_usd=None):
    """Тот же payload, который контекст-ветка строит из структурного профиля."""
    p = pf.generic_profile_for(protocol)
    assert p is not None, protocol
    cov = float(p["insurance_coverage_pct"])
    return {
        "protocol": p["name"],
        "has_insurance": cov > 0.0,
        "insurance_coverage_pct": cov,
        "insurance_provider": "",
        "treasury_usd": treasury_usd,
        "tvl_usd": p["tvl_usd"],
        "bug_bounty_usd": p["bug_bounty_usd"],
        "has_timelock": bool(p["has_timelock"]),
        "timelock_days": p["timelock_hours"] / 24.0,
    }


class TestExplicitScoreKeyAndPolarity(unittest.TestCase):
    """Явный ключ из ``_SCORE_KEYS`` с ОБЪЯВЛЕННОЙ полярностью."""

    FORTRESS = {
        "protocol": "Aave V3",
        "has_insurance": True,
        "insurance_coverage_pct": 80.0,
        "insurance_provider": "Nexus Mutual",
        "treasury_usd": 50_000_000,
        "tvl_usd": 400_000_000,
        "bug_bounty_usd": 1_000_000,
        "has_timelock": True,
        "timelock_days": 7,
    }

    def test_result_carries_a_known_score_key(self):
        res = ProtocolInsuranceScorer().score(dict(self.FORTRESS), write_log=False)
        self.assertIn("risk_score", res)
        self.assertIn("risk_score", _SCORE_KEYS,
                      "ключ обязан быть тем, который читает агрегатор")

    def test_risk_score_is_inverted_protection(self):
        res = ProtocolInsuranceScorer().score(dict(self.FORTRESS), write_log=False)
        self.assertAlmostEqual(
            res["risk_score"], 100.0 - res["total_insurance_score"], places=4)

    def test_polarity_higher_is_more_dangerous(self):
        """Шкала модуля «больше = защищённее» ⇄ шкала агрегатора «больше = опаснее»."""
        fortress = ProtocolInsuranceScorer().score(
            dict(self.FORTRESS), write_log=False)
        exposed = dict(self.FORTRESS)
        exposed.update({"has_insurance": False, "insurance_coverage_pct": 0.0,
                        "treasury_usd": 0.0, "bug_bounty_usd": 0.0,
                        "has_timelock": False, "timelock_days": 0})
        exposed_res = ProtocolInsuranceScorer().score(exposed, write_log=False)
        self.assertEqual(fortress["protection_tier"], "FORTRESS")
        self.assertEqual(exposed_res["protection_tier"], "EXPOSED")
        self.assertLess(fortress["risk_score"], exposed_res["risk_score"])
        self.assertAlmostEqual(exposed_res["risk_score"], 100.0, places=4)

    def test_coercion_no_longer_falls_back_to_coverage_score(self):
        """Именно тот fallback: «первый попавшийся ``*_score``» = coverage_score.

        Покрытие нулевое (честный измеренный ноль), поэтому на непочиненном
        модуле коэрция вернула бы 0.0 — здесь она обязана вернуть risk_score.
        """
        payload = dict(self.FORTRESS)
        payload.update({"has_insurance": False, "insurance_coverage_pct": 0.0})
        res = ProtocolInsuranceScorer().score(payload, write_log=False)
        self.assertEqual(res["coverage_score"], 0.0)
        coerced = _ModuleAdapter._coerce_score(res)
        self.assertAlmostEqual(coerced, res["risk_score"], places=4)
        self.assertGreater(coerced, 0.0)

    def test_risk_score_stays_in_band(self):
        for proto in _HELD:
            with self.subTest(protocol=proto):
                res = ProtocolInsuranceScorer().score(
                    _legacy_from_profile(proto), write_log=False)
                self.assertGreaterEqual(res["risk_score"], 0.0)
                self.assertLessEqual(res["risk_score"], 100.0)


class TestModuleIsNoLongerProtocolBlind(unittest.TestCase):
    """Слепота была следствием двух подстановок, а не природы задачи."""

    def _ctx_score(self, protocol):
        return ProtocolInsuranceScorer().score(_ctx(protocol), write_log=False)

    def test_context_scores_differ_across_audit_trio(self):
        scores = [self._ctx_score(p)["risk_score"] for p in _TRIO]
        self.assertEqual(len(set(scores)), len(scores),
                         f"score не различает протоколы: {scores}")

    def test_context_score_is_deterministic(self):
        """Повтор одного протокола — то же число (иначе nondeterministic)."""
        self.assertEqual(self._ctx_score("aave_v3"), self._ctx_score("aave_v3"))

    def test_control_protocol_is_dormant_none(self):
        """Страж: несуществующий протокол — dormant, не выдуманный score."""
        self.assertIsNone(
            ProtocolInsuranceScorer().score(
                _ctx("__nonexistent_control_protocol__"), write_log=False))

    def test_every_known_protocol_scores_and_universe_is_not_constant(self):
        scores = {}
        for proto in pf.known_protocols():
            res = self._ctx_score(proto)
            if res is None:
                continue
            scores[proto] = res["risk_score"]
        self.assertGreater(len(scores), 10)
        self.assertGreater(len(set(scores.values())), 3, scores)


class TestMeasuredDomainPathUnchanged(unittest.TestCase):
    """Страж в обратную сторону: полный доменный payload считается как считался.

    Числа — регрессионный якорь из ``test_insurance_treasury_unmeasured``
    (на непочиненном модуле зелёные): починка касается ТОЛЬКО контекст-ветки
    и добавленного ключа, а не арифметики компонент.
    """

    FULL = dict(TestExplicitScoreKeyAndPolarity.FORTRESS)

    def test_total_and_tier_unchanged(self):
        res = ProtocolInsuranceScorer().score(dict(self.FULL), write_log=False)
        self.assertEqual(res["total_insurance_score"], 80.0132)
        self.assertEqual(res["protection_tier"], "FORTRESS")
        self.assertEqual(res["treasury_tvl_ratio"], 0.125)
        self.assertEqual(res["unmeasured_components"], [])
        self.assertEqual(res["score_basis_max"], 100.0)

    def test_domain_payload_coverage_is_the_callers_number(self):
        """Доменный вход по-прежнему принимает СВОЁ покрытие (не из профиля)."""
        payload = dict(self.FULL)
        payload["insurance_coverage_pct"] = 12.5
        res = ProtocolInsuranceScorer().score(payload, write_log=False)
        self.assertEqual(res["insurance_coverage_pct"], 12.5)

    def test_missing_coverage_key_still_raises(self):
        payload = dict(self.FULL)
        payload.pop("insurance_coverage_pct")
        with self.assertRaises(ValueError):
            ProtocolInsuranceScorer().score(payload, write_log=False)

    def test_treasury_still_unmeasured_on_context_path(self):
        """Страж: починка покрытия не вернула выдуманную казну (ADR-070 п.15)."""
        sc = _CapturingScorer()
        sc.score(_ctx("aave_v3"), write_log=False)
        self.assertIsNone(sc.captured[0]["treasury_usd"])


if __name__ == "__main__":
    unittest.main()
