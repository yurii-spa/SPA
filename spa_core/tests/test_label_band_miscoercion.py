"""Потерянная коэрцией слепота: ярлык не имеет права съедать измерение.

Авария (замер цикла #143, карточка
``inbox-slepota-mozhet-byt-poteryannoi-koerciei``).

``collateral_health_monitor`` и ``defi_collateral_health_monitor`` ИЗМЕРИЛИ
разницу между протоколами — buffer_pct 56.25 у заёмных против 100.0 у
беззаёмных, health_factor 2.29 против inf. Оба сказали про всех "SAFE", а
ветка ``label_map`` в ``_ModuleAdapter._coerce_score`` вернула якорь ярлыка —
10.0 на все восемь протоколов. Снаружи это неотличимо от протокол-слепого
модуля: первый уехал в разметку слепоты и перестал исполняться вовсе, второй
в разметку НЕ попал и каждый час нёс константу в advisory-composite Tier-B,
называя её измерением.

Механизм — НЕ тот, что у страхового скорера (там коэрция падала в fallback
«первый ``*_score``» и давала константный ноль). Здесь score вычислялся
ветвью ярлыка, а ярлык грубый.

Положительный контроль — ``test_accident_label_only_result_is_constant``:
воспроизводит доfix-форму результата (различающийся ``detail`` под одинаковым
``risk_label``, БЕЗ ``risk_score``) и показывает, что она схлопывается в
константу. Тесты реальных модулей ниже краснеют на сегодняшнем (доfix)
``_coerce_score``: до правки оба возвращали 10.0 для всех протоколов.

Приёмка ДВУСТОРОННЯЯ (урок #136 — первая версия похожей правки погасила
рабочий Tier-A модуль): модуль, у которого различающегося числа НЕТ, обязан
ОСТАТЬСЯ на ярлыке, а не начать выдумывать. Это
``test_module_without_own_measurement_stays_on_label``.

Времени в тестах нет: ни стенных часов, ни фиксированных дат — предмет
проверки от календаря не зависит.
"""
import math
import unittest

from spa_core.analytics import collateral_health_monitor as chm
from spa_core.analytics import defi_collateral_health_monitor as dchm
from spa_core.analytics import defi_cross_chain_yield_comparator as dccyc
from spa_core.analytics._label_band import band_score
from spa_core.analytics.signal_aggregator import (
    LABEL_SCORE_MAP, _ModuleAdapter,
)

# Протоколы двух разных форм: заёмная позиция (LTV>0) против беззаёмной.
# Именно на этой паре модули различаются, а ярлык у обеих — "SAFE".
LEVERAGED = "aave_v3"
UNLEVERAGED = "yearn_v3"

# Полоса ярлыка "SAFE" в лестнице ("SAFE","WARNING","SEVERE","CRITICAL"):
# безопасный край — сам якорь (соседа-снизу нет), опасный — середина до
# якоря "WARNING".
SAFE_ANCHOR = LABEL_SCORE_MAP["SAFE"]                      # 10.0
SAFE_RISK_EDGE = (LABEL_SCORE_MAP["SAFE"] + LABEL_SCORE_MAP["WARNING"]) / 2.0


def ctx(protocol):
    return {"source": "test", "protocol": protocol}


class AccidentReproduction(unittest.TestCase):
    """Положительный контроль: форма «ярлык без числа» — это константа."""

    def test_accident_label_only_result_is_constant(self):
        # Ровно то, что модули отдавали ДО правки: detail различается,
        # risk_label одинаков, числа нет.
        before_leveraged = {
            "risk_label": "SAFE",
            "detail": {"buffer_pct": 56.25, "current_ltv": 0.35,
                       "liquidation_ltv": 0.8, "status": "SAFE"},
        }
        before_unleveraged = {
            "risk_label": "SAFE",
            "detail": {"buffer_pct": 100.0, "current_ltv": 0.0,
                       "liquidation_ltv": 1.0, "status": "SAFE"},
        }
        self.assertNotEqual(before_leveraged["detail"],
                            before_unleveraged["detail"],
                            "предпосылка аварии: модуль различил протоколы")
        a = _ModuleAdapter._coerce_score(before_leveraged)
        b = _ModuleAdapter._coerce_score(before_unleveraged)
        self.assertEqual(a, b,
                         "авария: разные измерения дают ОДИН score")
        self.assertEqual(a, LABEL_SCORE_MAP["SAFE"],
                         "и этот score — якорь ярлыка, а не измерение")

    def test_nested_descent_would_not_have_helped(self):
        """Числа под ``detail`` НЕТ — спуск в контейнеры аварию не лечит.

        Замер #143: ни одно из различающихся полей (`buffer_pct`,
        `current_ltv`, …) не является ключом score. Тест держит этот факт,
        чтобы починку не пытались повторить обходом вложенных контейнеров:
        он ничего бы не нашёл.
        """
        detail = {"buffer_pct": 56.25, "current_ltv": 0.35,
                  "liquidation_ltv": 0.8, "status": "SAFE"}
        self.assertIsNone(_ModuleAdapter._coerce_score(detail))


class ModulesRecoverTheirMeasurement(unittest.TestCase):
    """Краснеет на доfix-коде: там оба модуля давали 10.0 везде."""

    def test_collateral_health_monitor_differentiates(self):
        a = _ModuleAdapter._coerce_score(chm.analyze(ctx(LEVERAGED)))
        b = _ModuleAdapter._coerce_score(chm.analyze(ctx(UNLEVERAGED)))
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b,
                            "измеренная разница buffer_pct обязана дожить "
                            "до агрегатора")

    def test_defi_collateral_health_monitor_differentiates(self):
        a = _ModuleAdapter._coerce_score(dchm.analyze(ctx(LEVERAGED)))
        b = _ModuleAdapter._coerce_score(dchm.analyze(ctx(UNLEVERAGED)))
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)

    def test_score_never_contradicts_the_label(self):
        """Число обязано лежать ВНУТРИ полосы объявленного ярлыка."""
        for mod in (chm, dchm):
            for proto in (LEVERAGED, UNLEVERAGED):
                res = mod.analyze(ctx(proto))
                self.assertEqual(res["risk_label"], "SAFE",
                                 "предпосылка: вердикт модуля не изменился")
                score = _ModuleAdapter._coerce_score(res)
                self.assertGreaterEqual(score, SAFE_ANCHOR)
                self.assertLessEqual(
                    score, SAFE_RISK_EDGE,
                    "%s: score вышел из полосы SAFE — он противоречит "
                    "собственному вердикту модуля" % mod.__name__)

    def test_leveraged_position_is_scored_riskier(self):
        """Направление не перевёрнуто: меньше запаса — опаснее."""
        for mod in (chm, dchm):
            lev = _ModuleAdapter._coerce_score(mod.analyze(ctx(LEVERAGED)))
            unlev = _ModuleAdapter._coerce_score(mod.analyze(ctx(UNLEVERAGED)))
            self.assertGreater(
                lev, unlev,
                "%s: заёмная позиция обязана быть НЕ безопаснее "
                "беззаёмной" % mod.__name__)


class TwoSidedAcceptance(unittest.TestCase):
    """Урок #136: правка не смеет заставить выдумывать того, кто не мерил."""

    def test_module_without_own_measurement_stays_on_label(self):
        """``defi_cross_chain_yield_comparator`` числа не получает.

        Его собственный предмет — эффективность цепочки (net/gross). В
        профиле мост и газ равны нулю у ВСЕХ протоколов, поэтому
        эффективность честно константа (=1.0, "EXCELLENT"). Различаются у
        него только ПРОНЕСЁННЫЕ насквозь APY профиля — то самое «различие из
        побочных полей», против которого в агрегаторе стоит разметка
        `unsourced`. Собрать из них риск-score значило бы выдумать.
        """
        res = dccyc.analyze(ctx(LEVERAGED))
        self.assertNotIn("risk_score", res,
                         "модуль без собственного измерения обязан остаться "
                         "на ярлыке")
        self.assertEqual(_ModuleAdapter._coerce_score(res),
                         LABEL_SCORE_MAP["EXCELLENT"])

    def test_plain_label_coercion_unchanged(self):
        """Ветка label_map для остальных модулей не сдвинулась."""
        self.assertEqual(
            _ModuleAdapter._coerce_score({"risk_label": "HIGH"}), 78.0)
        self.assertEqual(
            _ModuleAdapter._coerce_score({"label": "CRITICAL"}), 95.0)

    def test_label_map_has_single_owner(self):
        """У словаря ярлыков одно имя: ветка коэрции читает ИМЕННО его."""
        for label, anchor in LABEL_SCORE_MAP.items():
            self.assertEqual(
                _ModuleAdapter._coerce_score({"risk_label": label}), anchor,
                "ярлык %s разошёлся с LABEL_SCORE_MAP" % label)


class BandScoreContract(unittest.TestCase):

    LADDER = ("SAFE", "WARNING", "SEVERE", "CRITICAL")

    def test_edges_of_the_band(self):
        self.assertEqual(band_score("SAFE", 0.0, self.LADDER), SAFE_ANCHOR)
        self.assertEqual(band_score("SAFE", 1.0, self.LADDER), SAFE_RISK_EDGE)

    def test_position_is_monotone(self):
        prev = band_score("WARNING", 0.0, self.LADDER)
        for step in range(1, 11):
            cur = band_score("WARNING", step / 10.0, self.LADDER)
            self.assertGreater(cur, prev)
            prev = cur

    def test_band_never_crosses_neighbours(self):
        """Полосы соседних ярлыков не перекрываются — вердикт не ломается."""
        safe_hi = band_score("SAFE", 1.0, self.LADDER)
        warn_lo = band_score("WARNING", 0.0, self.LADDER)
        self.assertLessEqual(safe_hi, warn_lo)

    def test_position_is_clamped_not_extrapolated(self):
        self.assertEqual(band_score("SAFE", -5.0, self.LADDER),
                         band_score("SAFE", 0.0, self.LADDER))
        self.assertEqual(band_score("SAFE", 99.0, self.LADDER),
                         band_score("SAFE", 1.0, self.LADDER))

    def test_fail_closed_returns_none_not_zero(self):
        """«Не измерено» обязано отличаться от «измерен ноль»."""
        for bad in (
            band_score("НЕ_ЯРЛЫК", 0.5, self.LADDER),
            band_score("SAFE", 0.5, ("SAFE", "НЕ_ЯРЛЫК")),
            band_score("SAFE", 0.5, ()),
            band_score("SAFE", float("nan"), self.LADDER),
            band_score("SAFE", "не число", self.LADDER),
            # немонотонная лестница: якоря обязаны возрастать
            band_score("SAFE", 0.5, ("WARNING", "SAFE")),
        ):
            self.assertIsNone(bad)

    def test_single_label_ladder_collapses_to_anchor(self):
        for pos in (0.0, 0.5, 1.0):
            self.assertEqual(band_score("SAFE", pos, ("SAFE",)),
                             LABEL_SCORE_MAP["SAFE"])

    def test_score_stays_in_0_100(self):
        for label in self.LADDER:
            for pos in (0.0, 0.5, 1.0):
                s = band_score(label, pos, self.LADDER)
                self.assertFalse(math.isnan(s))
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 100.0)


if __name__ == "__main__":
    unittest.main()
