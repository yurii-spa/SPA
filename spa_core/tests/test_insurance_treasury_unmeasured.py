"""
Казна протокола НЕ ИЗМЕРЕНА — отказ, а не выдумка (ADR-070 п.15).

Авария, которую воспроизводят эти тесты, настоящая: на контекст-пути
``protocol_insurance_scorer`` подставлял казну = ``tvl_usd * 0.02`` — число,
которого нет ни в одном источнике. Оно давало каждому протоколу 4.13 балла из
30 «за резервы», и давало РОВНО ОДИНАКОВЫЕ 4.13 всем — постоянное отношение
0.02 было одной из причин разметки модуля как ``blind_equal``.

Замер положительного контроля: на модуле с origin краснеют **9 из 16** тестов этого файла
(15 из 24 исходов в отчёте pytest — два теста идут по четырём протоколам субтестами).

Каждый тест ниже, кроме явно помеченных «страж», — положительный контроль:
на неисправленном модуле он краснеет (подстановка возвращается / ``float(None)``
роняет TypeError). Тесты-стражи краснели бы на будущей регрессии, а не на
прошлой аварии — это сказано вслух, чтобы набор не выглядел сильнее, чем он есть.
"""

import unittest

from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics.protocol_insurance_scorer import (
    ProtocolInsuranceScorer,
    _bug_bounty_score,
    _coverage_score,
    _timelock_score,
    _treasury_score,
)
from spa_core.analytics.signal_aggregator import _ModuleAdapter

_HELD = ("aave_v3", "pendle", "maple", "morpho_steakhouse")


def _legacy_from_profile(protocol, treasury_usd):
    """Тот же payload, который модуль строит из структурного профиля.

    НАМЕРЕННОЕ ИЗМЕНЕНИЕ ФИКСТУРЫ (инв. 16, 2026-08-17, карточка
    ``agent-insurance-scorer-otbrasyvaet-izvestnoe-pokrytie``): покрытие и
    ``has_insurance`` берутся из профиля, потому что контекст-ветка модуля
    перестала подставлять литералы ``False`` / ``0.0``. Ни одна проверка этого
    файла не ослаблена — они все о КАЗНЕ и сформулированы относительно
    компонент (``score_basis_max``, сумма earned, равенство тиров), поэтому
    остаются в силе; фиксировать здесь старые литералы означало бы проверять
    payload, которого модуль больше не строит. Обоснование в журнале:
    ``docs/journal/2026-W34.md``.
    """
    p = pf.generic_profile_for(protocol)
    assert p is not None, protocol
    _cov = float(p["insurance_coverage_pct"])
    return {
        "protocol": p["name"],
        "has_insurance": _cov > 0.0,
        "insurance_coverage_pct": _cov,
        "insurance_provider": "",
        "treasury_usd": treasury_usd,
        "tvl_usd": p["tvl_usd"],
        "bug_bounty_usd": p["bug_bounty_usd"],
        "has_timelock": bool(p["has_timelock"]),
        "timelock_days": p["timelock_hours"] / 24.0,
    }


class _CapturingScorer(ProtocolInsuranceScorer):
    """Перехватывает payload, который контекст-ветка отдаёт своему же движку.

    Контекст-ветка вызывает ``self.score(_legacy, ...)`` — единственная точка,
    где выдуманная казна была бы видна снаружи (наружу уходит уже сведённый
    ``{"risk_score": ...}``).
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.captured = []

    def score(self, protocol_data, write_log=True):
        if isinstance(protocol_data, dict) and "tvl_usd" in protocol_data:
            self.captured.append(dict(protocol_data))
        return super().score(protocol_data, write_log=write_log)


class TestContextPathDoesNotFabricateTreasury(unittest.TestCase):
    """Положительный контроль: сердцевина аварии."""

    def test_context_payload_carries_no_invented_treasury(self):
        for proto in _HELD:
            with self.subTest(protocol=proto):
                sc = _CapturingScorer()
                sc.score({"cycle_ts": "x", "protocol": proto}, write_log=False)
                self.assertEqual(len(sc.captured), 1)
                self.assertIsNone(
                    sc.captured[0]["treasury_usd"],
                    "казна не измерена — в payload'е должен быть отказ (None)",
                )

    def test_no_protocol_gets_treasury_proportional_to_tvl(self):
        """Именно та формула: 2% TVL. Проверяем ОТСУТСТВИЕ пропорции."""
        for proto in _HELD:
            with self.subTest(protocol=proto):
                sc = _CapturingScorer()
                sc.score({"cycle_ts": "x", "protocol": proto}, write_log=False)
                payload = sc.captured[0]
                self.assertNotEqual(payload["treasury_usd"],
                                    payload["tvl_usd"] * 0.02)

    def test_result_names_treasury_as_unmeasured(self):
        sc = ProtocolInsuranceScorer()
        res = sc.score(_legacy_from_profile("aave_v3", None), write_log=False)
        self.assertEqual(res["unmeasured_components"], ["treasury"])
        self.assertIsNone(res["treasury_score"])
        self.assertIsNone(res["treasury_usd"])
        self.assertIsNone(res["treasury_tvl_ratio"])


class TestUnmeasuredIsNotZero(unittest.TestCase):
    """«Не измерено» ≠ «казны нет». Ноль — тоже утверждение о протоколе."""

    def test_none_treasury_returns_none_not_zero(self):
        self.assertIsNone(_treasury_score(None, 1_000_000_000.0))

    def test_measured_empty_treasury_still_scores_zero(self):
        """Обратная сторона: измеренный ноль остаётся честным нулём."""
        self.assertEqual(_treasury_score(0.0, 1_000_000_000.0), 0.0)

    def test_unmeasured_leaves_both_numerator_and_denominator(self):
        sc = ProtocolInsuranceScorer()
        res = sc.score(_legacy_from_profile("aave_v3", None), write_log=False)
        self.assertEqual(res["score_basis_max"], 70.0)
        self.assertEqual(
            res["earned_points"],
            round(res["coverage_score"] + res["bug_bounty_score"]
                  + res["timelock_score"], 4),
        )
        self.assertAlmostEqual(
            res["total_insurance_score"],
            round(res["earned_points"] / 70.0 * 100.0, 4), places=4)

    def test_refusal_does_not_downgrade_the_tier(self):
        """ADR-070 п.15: UNCHECKED не наказывает протокол.

        Отказ от 4.13 выдуманных баллов не имеет права уронить тир: и с
        выдумкой, и без неё aave_v3 — EXPOSED, потому что доля от ИЗМЕРИМОГО
        максимума считается на той же шкале, на которой калиброваны пороги.
        """
        sc = ProtocolInsuranceScorer()
        fabricated = _legacy_from_profile("aave_v3", None)
        fabricated["treasury_usd"] = fabricated["tvl_usd"] * 0.02
        honest = _legacy_from_profile("aave_v3", None)
        self.assertEqual(
            sc.score(honest, write_log=False)["protection_tier"],
            sc.score(fabricated, write_log=False)["protection_tier"],
        )


class TestHoleIsStillARefusalToRun(unittest.TestCase):
    """Дырка в payload'е ≠ «не измерено»: отсутствующий ключ по-прежнему ValueError.

    Страж (не положительный контроль): на неисправленном модуле тоже зелёный.
    Стоит здесь потому, что новый допуск ``None`` — ровно тот тип послабления,
    которым дырка могла бы снова начать проползать молча.
    """

    def test_missing_treasury_key_raises(self):
        payload = _legacy_from_profile("aave_v3", None)
        payload.pop("treasury_usd")
        with self.assertRaises(ValueError):
            ProtocolInsuranceScorer().score(payload, write_log=False)

    def test_negative_treasury_still_raises(self):
        payload = _legacy_from_profile("aave_v3", -1.0)
        with self.assertRaises(ValueError):
            ProtocolInsuranceScorer().score(payload, write_log=False)


class TestNothingMeasuredIsDormant(unittest.TestCase):
    """Если однажды не измерена НИ ОДНА компонента — dormant, а не ноль.

    Ноль баллов из ноля возможных объявил бы протокол беззащитным на пустом
    месте. Сегодня отказываться умеет только казна, поэтому состояние
    достигается подменой трёх остальных компонент — ветка защиты обязана быть
    исполнена хотя бы одним тестом, иначе она украшение.
    """

    def test_all_components_unmeasured_returns_none(self):
        import spa_core.analytics.protocol_insurance_scorer as mod
        originals = (mod._coverage_score, mod._bug_bounty_score,
                     mod._timelock_score)
        mod._coverage_score = lambda *a, **k: None
        mod._bug_bounty_score = lambda *a, **k: None
        mod._timelock_score = lambda *a, **k: None
        try:
            res = mod.ProtocolInsuranceScorer().score(
                _legacy_from_profile("aave_v3", None), write_log=False)
        finally:
            (mod._coverage_score, mod._bug_bounty_score,
             mod._timelock_score) = originals
        self.assertIsNone(res)


class TestMeasuredPathUnchanged(unittest.TestCase):
    """Страж в обратную сторону: полный payload считается как считался.

    Два теста с числами — регрессионный якорь (на неисправленном модуле
    зелёные; числа получены прогоном модуля с origin, плюс отдельно сверены
    500 случайных полных payload'ов — расхождений 0). Третий краснеет на старом
    модуле лишь потому, что поля базы там ещё нет.
    """

    FULL = {
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

    def test_full_payload_scores_and_tiers_exactly_as_before(self):
        res = ProtocolInsuranceScorer().score(dict(self.FULL), write_log=False)
        self.assertEqual(res["total_insurance_score"], 80.0132)
        self.assertEqual(res["protection_tier"], "FORTRESS")
        self.assertEqual(res["treasury_tvl_ratio"], 0.125)

    def test_measured_payload_declares_full_basis(self):
        res = ProtocolInsuranceScorer().score(dict(self.FULL), write_log=False)
        self.assertEqual(res["unmeasured_components"], [])
        self.assertEqual(res["score_basis_max"], 100.0)

    def test_total_equals_plain_sum_when_everything_measured(self):
        """Нормализация обязана быть тождеством при полной базе."""
        f = self.FULL
        res = ProtocolInsuranceScorer().score(dict(f), write_log=False)
        plain = round(
            _coverage_score(f["has_insurance"], f["insurance_coverage_pct"])
            + _treasury_score(f["treasury_usd"], f["tvl_usd"])
            + _bug_bounty_score(f["bug_bounty_usd"])
            + _timelock_score(f["has_timelock"], f["timelock_days"]), 4)
        self.assertEqual(res["total_insurance_score"], plain)


class TestUncheckedBlocksNobody(unittest.TestCase):
    """Вторая половина решения владельца: отказ не смеет никого блокировать.

    Замер того, что видит агрегатор.

    НАМЕРЕННОЕ ИЗМЕНЕНИЕ ДВУХ ТЕСТОВ (инв. 16, 2026-08-17, карточка
    ``agent-insurance-scorer-otbrasyvaet-izvestnoe-pokrytie``; обоснование —
    ``docs/journal/2026-W34.md``). Оба теста закрепляли величину ``0.0``,
    которую агрегатор видел ПОТОМУ ЧТО модуль был слеп: ``_coerce_score`` не
    находил ни одного ключа из ``_SCORE_KEYS`` и падал в fallback «первый
    попавшийся ``*_score``» — ``coverage_score``, а он был константным нулём
    из-за выброшенного покрытия. Это ровно тот дефект, который закрыт
    отдельной карточкой: у результата появился явный ``risk_score``
    (= 100 − защищённость), и величина стала протокол-специфичной
    (aave_v3 67.7143 · pendle 89.3734 · maple 90.2306 · morpho 89.0877).
    Проверки НЕ ослаблены, а переписаны на то, что решение владельца
    действительно гарантирует: известный протокол не глохнет, отказ от
    выдуманной казны не двигает ТИР (``test_refusal_does_not_downgrade_the_tier``
    выше), а число агрегатора — честная арифметика модуля, а не константа.
    Старое равенство ``0.0 == 0.0`` держалось тождественно и не проверяло
    ничего.
    """

    def test_known_protocols_get_their_own_aggregator_score(self):
        sc = ProtocolInsuranceScorer()
        seen = {}
        for proto in _HELD:
            with self.subTest(protocol=proto):
                out = sc.score({"cycle_ts": "x", "protocol": proto},
                               write_log=False)
                self.assertIsNotNone(out, "известный протокол не должен глохнуть")
                self.assertIsInstance(out["risk_score"], float)
                self.assertGreaterEqual(out["risk_score"], 0.0)
                self.assertLessEqual(out["risk_score"], 100.0)
                seen[proto] = out["risk_score"]
        self.assertGreater(len(set(seen.values())), 1,
                           f"score снова одинаков у всех протоколов: {seen}")

    def test_unknown_protocol_stays_dormant(self):
        out = ProtocolInsuranceScorer().score(
            {"cycle_ts": "x", "protocol": "__nonexistent_control__"},
            write_log=False)
        self.assertIsNone(out)

    def test_refusal_does_not_penalise_via_the_aggregator_number(self):
        """Отказ от казны не двигает тир и остаётся ЧЕСТНОЙ арифметикой.

        Раньше здесь стояло равенство коэрцированных величин — оно держалось
        только потому, что обе были константным нулём слепого модуля. Теперь
        проверяется то, что действительно обещано ADR-070 п.15: тир не падает,
        а число агрегатора равно ``100 − total_insurance_score`` в обоих
        случаях (никакой отдельной шкалы для «не измерено»).
        """
        sc = ProtocolInsuranceScorer()
        fabricated = _legacy_from_profile("pendle", None)
        fabricated["treasury_usd"] = fabricated["tvl_usd"] * 0.02
        honest = _legacy_from_profile("pendle", None)
        res_honest = sc.score(honest, write_log=False)
        res_fab = sc.score(fabricated, write_log=False)
        self.assertEqual(res_honest["protection_tier"], res_fab["protection_tier"])
        for res in (res_honest, res_fab):
            self.assertAlmostEqual(
                _ModuleAdapter._coerce_score(res),
                100.0 - res["total_insurance_score"], places=4)


if __name__ == "__main__":
    unittest.main()
