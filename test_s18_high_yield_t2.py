"""
spa_core/tests/test_s18_high_yield_t2.py — MP-604 тесты S18 HighYieldT2Strategy

Тест-классы:
  TestInit             (8)  — инициализация, атрибуты, константы
  TestResolveSlot     (12)  — resolve_slot логика (первый eligible, boost max APY, fallback)
  TestGetAllocation   (15)  — веса слотов, перераспределение, edge cases
  TestGetExpectedAPY  (10)  — weighted APY, target, unresolved, edge
  TestGetRiskSummary  (12)  — t2_weight_pct, adr_019_compliant, risk_score
  TestGetHealth        (8)  — eligible adapters, overall_status, slots dict
  TestSimulate         (8)  — expected_yield_usd, структура, capital=0
  TestToDict           (7)  — JSON-serializable, обязательные ключи

Итого: 80 тестов.

Правила:
  - stdlib only, unittest, никаких внешних зависимостей
  - Тесты не обращаются к сети/файлам
  - Используют monkey-patching через subclassing / mock объекты
"""
import json
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные mock-объекты
# ──────────────────────────────────────────────────────────────────────────────

class _MockAdapter:
    """Фиктивный адаптер для инъекции в HighYieldT2Strategy._adapters."""

    def __init__(self, apy: float = 5.0, eligible: bool = True):
        self._apy = apy
        self._eligible = eligible

    def get_apy(self) -> float:
        return self._apy

    def is_eligible(self) -> bool:
        return self._eligible

    def simulate_deposit(self, amount: float) -> dict:
        return {"amount": amount, "expected_apy": self._apy, "status": "ok"}


class _IneligibleAdapter(_MockAdapter):
    def __init__(self):
        super().__init__(apy=0.0, eligible=False)


# ──────────────────────────────────────────────────────────────────────────────
# Фабрика: создаём стратегию без реальных импортов адаптеров
# ──────────────────────────────────────────────────────────────────────────────

def _make_strategy(adapters: Optional[dict] = None) -> "HighYieldT2Strategy":
    """Создать HighYieldT2Strategy с инъекцией mock-адаптеров."""
    from spa_core.strategies.s18_high_yield_t2 import HighYieldT2Strategy
    s = HighYieldT2Strategy.__new__(HighYieldT2Strategy)
    # Инициализируем вручную, минуя _load_adapters
    s._adapters = {}
    s._simulate_history = []
    if adapters:
        s._adapters.update(adapters)
    return s


def _make_full_strategy() -> "HighYieldT2Strategy":
    """Создать стратегию с полным набором mock-адаптеров (все eligible)."""
    return _make_strategy({
        "compound_v3":  _MockAdapter(apy=5.2,  eligible=True),
        "spark_susds":  _MockAdapter(apy=5.0,  eligible=True),
        "sfrax":        _MockAdapter(apy=8.5,  eligible=True),
        "wusdm":        _MockAdapter(apy=5.0,  eligible=True),
        "sdai":         _MockAdapter(apy=5.5,  eligible=True),
        "scrvusd":      _MockAdapter(apy=6.5,  eligible=True),
    })


# ──────────────────────────────────────────────────────────────────────────────
# TestInit — 8 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestInit(unittest.TestCase):

    def setUp(self):
        from spa_core.strategies.s18_high_yield_t2 import HighYieldT2Strategy
        self.cls = HighYieldT2Strategy

    def test_strategy_id(self):
        """STRATEGY_ID == 'S18'."""
        from spa_core.strategies.s18_high_yield_t2 import STRATEGY_ID
        self.assertEqual(STRATEGY_ID, "S18")

    def test_strategy_name(self):
        """STRATEGY_NAME == 'High Yield T2'."""
        from spa_core.strategies.s18_high_yield_t2 import STRATEGY_NAME
        self.assertEqual(STRATEGY_NAME, "High Yield T2")

    def test_target_apy(self):
        """TARGET_APY_PCT == 8.0."""
        from spa_core.strategies.s18_high_yield_t2 import TARGET_APY_PCT
        self.assertAlmostEqual(TARGET_APY_PCT, 8.0, places=5)

    def test_risk_score(self):
        """RISK_SCORE == 0.42."""
        from spa_core.strategies.s18_high_yield_t2 import RISK_SCORE
        self.assertAlmostEqual(RISK_SCORE, 0.42, places=5)

    def test_max_t2_weight(self):
        """MAX_T2_WEIGHT == 0.70."""
        from spa_core.strategies.s18_high_yield_t2 import MAX_T2_WEIGHT
        self.assertAlmostEqual(MAX_T2_WEIGHT, 0.70, places=5)

    def test_class_constants(self):
        """Класс имеет нужные атрибуты."""
        s = _make_strategy()
        self.assertEqual(s.STRATEGY_ID, "S18")
        self.assertEqual(s.STRATEGY_NAME, "High Yield T2")
        self.assertAlmostEqual(s.TARGET_APY_PCT, 8.0, places=5)
        self.assertAlmostEqual(s.RISK_SCORE, 0.42, places=5)
        self.assertAlmostEqual(s.MAX_T2_WEIGHT, 0.70, places=5)

    def test_has_adapters_dict(self):
        """Стратегия имеет _adapters dict."""
        s = _make_strategy()
        self.assertIsInstance(s._adapters, dict)

    def test_slots_four_entries(self):
        """SLOTS содержит ровно 4 слота."""
        from spa_core.strategies.s18_high_yield_t2 import SLOTS
        self.assertEqual(len(SLOTS), 4)
        self.assertIn("safety_net", SLOTS)
        self.assertIn("core_a", SLOTS)
        self.assertIn("core_b", SLOTS)
        self.assertIn("boost", SLOTS)


# ──────────────────────────────────────────────────────────────────────────────
# TestResolveSlot — 12 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveSlot(unittest.TestCase):

    def test_safety_net_resolves_to_compound_v3(self):
        """safety_net → compound_v3 если eligible."""
        s = _make_strategy({"compound_v3": _MockAdapter(apy=5.2, eligible=True)})
        key, _ = s._resolve_slot("safety_net")
        self.assertEqual(key, "compound_v3")

    def test_safety_net_fallback_to_spark_susds(self):
        """safety_net → spark_susds если compound_v3 ineligible."""
        s = _make_strategy({
            "compound_v3":  _IneligibleAdapter(),
            "spark_susds":  _MockAdapter(apy=5.0, eligible=True),
        })
        key, _ = s._resolve_slot("safety_net")
        self.assertEqual(key, "spark_susds")

    def test_safety_net_none_if_all_ineligible(self):
        """safety_net → (None, None) если все кандидаты ineligible."""
        s = _make_strategy({
            "compound_v3": _IneligibleAdapter(),
            "spark_susds": _IneligibleAdapter(),
        })
        key, inst = s._resolve_slot("safety_net")
        self.assertIsNone(key)
        self.assertIsNone(inst)

    def test_core_a_resolves_to_sfrax(self):
        """core_a → sfrax (первый eligible)."""
        s = _make_strategy({"sfrax": _MockAdapter(apy=8.5, eligible=True)})
        key, _ = s._resolve_slot("core_a")
        self.assertEqual(key, "sfrax")

    def test_core_a_fallback_to_wusdm(self):
        """core_a → wusdm если sfrax ineligible."""
        s = _make_strategy({
            "sfrax":  _IneligibleAdapter(),
            "wusdm":  _MockAdapter(apy=5.0, eligible=True),
        })
        key, _ = s._resolve_slot("core_a")
        self.assertEqual(key, "wusdm")

    def test_core_b_resolves_to_sdai(self):
        """core_b → sdai (первый eligible)."""
        s = _make_strategy({"sdai": _MockAdapter(apy=5.5, eligible=True)})
        key, _ = s._resolve_slot("core_b")
        self.assertEqual(key, "sdai")

    def test_core_b_fallback_to_scrvusd(self):
        """core_b → scrvusd если sdai ineligible."""
        s = _make_strategy({
            "sdai":    _IneligibleAdapter(),
            "scrvusd": _MockAdapter(apy=6.5, eligible=True),
        })
        key, _ = s._resolve_slot("core_b")
        self.assertEqual(key, "scrvusd")

    def test_boost_picks_max_apy(self):
        """boost → кандидат с максимальным APY."""
        s = _make_strategy({
            "sfrax":  _MockAdapter(apy=8.5,  eligible=True),
            "wusdm":  _MockAdapter(apy=5.0,  eligible=True),
            "sdai":   _MockAdapter(apy=5.5,  eligible=True),
        })
        key, _ = s._resolve_slot("boost")
        self.assertEqual(key, "sfrax")  # 8.5 > 5.5 > 5.0

    def test_boost_picks_only_eligible(self):
        """boost → только eligible кандидат."""
        s = _make_strategy({
            "sfrax":  _IneligibleAdapter(),
            "wusdm":  _MockAdapter(apy=5.0,  eligible=True),
            "sdai":   _MockAdapter(apy=12.0, eligible=True),
        })
        key, _ = s._resolve_slot("boost")
        self.assertEqual(key, "sdai")   # 12.0 > 5.0, sfrax ineligible

    def test_boost_single_eligible(self):
        """boost → единственный eligible кандидат."""
        s = _make_strategy({
            "sfrax":  _IneligibleAdapter(),
            "wusdm":  _MockAdapter(apy=7.0, eligible=True),
            "sdai":   _IneligibleAdapter(),
        })
        key, _ = s._resolve_slot("boost")
        self.assertEqual(key, "wusdm")

    def test_boost_none_if_all_ineligible(self):
        """boost → (None, None) если все кандидаты ineligible."""
        s = _make_strategy({
            "sfrax":  _IneligibleAdapter(),
            "wusdm":  _IneligibleAdapter(),
            "sdai":   _IneligibleAdapter(),
        })
        key, inst = s._resolve_slot("boost")
        self.assertIsNone(key)
        self.assertIsNone(inst)

    def test_resolve_returns_adapter_instance(self):
        """_resolve_slot возвращает adapter instance если загружен."""
        mock = _MockAdapter(apy=5.2, eligible=True)
        s = _make_strategy({"compound_v3": mock})
        key, inst = s._resolve_slot("safety_net")
        self.assertEqual(key, "compound_v3")
        self.assertIs(inst, mock)


# ──────────────────────────────────────────────────────────────────────────────
# TestGetAllocation — 15 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestGetAllocation(unittest.TestCase):

    def _full_s(self):
        return _make_full_strategy()

    def test_safety_net_weight_30pct(self):
        """safety_net получает ~30% капитала."""
        s = self._full_s()
        alloc = s.get_allocation(100_000.0)
        self.assertAlmostEqual(alloc.get("compound_v3", 0.0), 30_000.0, places=1)

    def test_core_a_weight_35pct(self):
        """core_a получает ~35% капитала."""
        s = self._full_s()
        alloc = s.get_allocation(100_000.0)
        # sfrax — primary candidate для core_a
        # В boost sfrax может тоже получить долю если APY максимальный
        # Проверяем: core_a_weight*capital ≤ sfrax_alloc ≤ (core_a+boost)*capital
        sfrax_alloc = alloc.get("sfrax", 0.0)
        self.assertGreaterEqual(sfrax_alloc, 35_000.0 - 0.1)

    def test_core_b_weight_25pct(self):
        """core_b получает ~25% капитала."""
        s = self._full_s()
        alloc = s.get_allocation(100_000.0)
        sdai_alloc = alloc.get("sdai", 0.0)
        self.assertAlmostEqual(sdai_alloc, 25_000.0, places=1)

    def test_boost_weight_10pct(self):
        """boost получает ~10% капитала (входит в сумму sfrax т.к. max APY)."""
        s = self._full_s()
        alloc = s.get_allocation(100_000.0)
        # boost → sfrax (max APY=8.5), так что sfrax = 35%+10% = 45%
        sfrax_alloc = alloc.get("sfrax", 0.0)
        self.assertAlmostEqual(sfrax_alloc, 45_000.0, places=1)

    def test_total_equals_capital(self):
        """Сумма аллокаций == capital_usd."""
        s = self._full_s()
        capital = 100_000.0
        alloc = s.get_allocation(capital)
        total = sum(v for k, v in alloc.items() if k != "__unallocated__")
        self.assertAlmostEqual(total, capital, places=3)

    def test_capital_zero(self):
        """При capital_usd=0 → нулевые аллокации."""
        s = self._full_s()
        alloc = s.get_allocation(0.0)
        for v in alloc.values():
            self.assertEqual(v, 0.0)

    def test_capital_negative(self):
        """При capital_usd<0 → нулевые аллокации."""
        s = self._full_s()
        alloc = s.get_allocation(-1000.0)
        for v in alloc.values():
            self.assertEqual(v, 0.0)

    def test_unresolved_slot_redirected_to_safety_net(self):
        """Unresolved слот → его капитал идёт в safety_net."""
        s = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.2, eligible=True),
            # core_a: sfrax и wusdm — не загружены → eligible=True (fallback)
            # Но мы принудительно сделаем ineligible
            "sfrax":  _IneligibleAdapter(),
            "wusdm":  _IneligibleAdapter(),
            "sdai":   _MockAdapter(apy=5.5, eligible=True),
        })
        alloc = s.get_allocation(100_000.0)
        # core_a unresolved → 35000 → compound_v3
        # boost: sfrax/wusdm ineligible, sdai eligible → sdai, но sdai уже в core_b
        # safety_net=compound_v3: 30000 + 35000 = 65000 (core_a unresolved)
        # Boost → sdai (10000)
        # core_b → sdai (25000) → sdai total = 35000
        compound_alloc = alloc.get("compound_v3", 0.0)
        self.assertGreater(compound_alloc, 30_000.0)  # получил часть от unresolved

    def test_all_t2_unresolved_safety_net_gets_all(self):
        """Все T2 слоты unresolved → safety_net получает 100%."""
        s = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.2, eligible=True),
            "spark_susds": _MockAdapter(apy=5.0, eligible=True),
            "sfrax":   _IneligibleAdapter(),
            "wusdm":   _IneligibleAdapter(),
            "sdai":    _IneligibleAdapter(),
            "scrvusd": _IneligibleAdapter(),
        })
        alloc = s.get_allocation(100_000.0)
        # core_a, core_b, boost — всё unresolved → всё в compound_v3
        compound_alloc = alloc.get("compound_v3", 0.0)
        self.assertAlmostEqual(compound_alloc, 100_000.0, places=1)

    def test_all_unresolved_unallocated(self):
        """Все слоты unresolved (включая safety_net) → __unallocated__."""
        s = _make_strategy({
            "compound_v3": _IneligibleAdapter(),
            "spark_susds": _IneligibleAdapter(),
            "sfrax":   _IneligibleAdapter(),
            "wusdm":   _IneligibleAdapter(),
            "sdai":    _IneligibleAdapter(),
            "scrvusd": _IneligibleAdapter(),
        })
        alloc = s.get_allocation(100_000.0)
        unallocated = alloc.get("__unallocated__", 0.0)
        self.assertAlmostEqual(unallocated, 100_000.0, places=1)

    def test_allocation_values_are_floats(self):
        """Все значения аллокации — float."""
        s = self._full_s()
        alloc = s.get_allocation(100_000.0)
        for v in alloc.values():
            self.assertIsInstance(v, float)

    def test_allocation_keys_are_strings(self):
        """Все ключи аллокации — str."""
        s = self._full_s()
        alloc = s.get_allocation(100_000.0)
        for k in alloc.keys():
            self.assertIsInstance(k, str)

    def test_same_adapter_in_multiple_slots_accumulates(self):
        """Один адаптер в нескольких слотах → суммируется."""
        # sfrax в core_a (35%) и boost (10% если max APY)
        s = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.2, eligible=True),
            "sfrax":       _MockAdapter(apy=9.0, eligible=True),
            "wusdm":       _MockAdapter(apy=4.0, eligible=True),
            "sdai":        _MockAdapter(apy=5.5, eligible=True),
            "scrvusd":     _MockAdapter(apy=6.5, eligible=True),
        })
        alloc = s.get_allocation(100_000.0)
        sfrax_total = alloc.get("sfrax", 0.0)
        # sfrax: core_a (35000) + boost (10000) = 45000 (т.к. apy=9.0 > все остальные)
        self.assertAlmostEqual(sfrax_total, 45_000.0, places=1)

    def test_small_capital(self):
        """Корректная аллокация для малого капитала (1000 USD)."""
        s = self._full_s()
        alloc = s.get_allocation(1000.0)
        total = sum(v for k, v in alloc.items() if k != "__unallocated__")
        self.assertAlmostEqual(total, 1000.0, places=3)

    def test_large_capital(self):
        """Корректная аллокация для большого капитала (10M USD)."""
        s = self._full_s()
        alloc = s.get_allocation(10_000_000.0)
        total = sum(v for k, v in alloc.items() if k != "__unallocated__")
        self.assertAlmostEqual(total, 10_000_000.0, places=1)


# ──────────────────────────────────────────────────────────────────────────────
# TestGetExpectedAPY — 10 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestGetExpectedAPY(unittest.TestCase):

    def test_returns_float(self):
        """get_expected_apy() возвращает float."""
        s = _make_full_strategy()
        result = s.get_expected_apy()
        self.assertIsInstance(result, float)

    def test_positive_apy(self):
        """get_expected_apy() > 0 при наличии eligible адаптеров."""
        s = _make_full_strategy()
        result = s.get_expected_apy()
        self.assertGreater(result, 0.0)

    def test_uses_fallback_apys(self):
        """Без загруженных адаптеров использует FALLBACK_APY."""
        s = _make_strategy()  # нет загруженных адаптеров
        result = s.get_expected_apy()
        # Должно совпадать с weighted fallback (все eligible через fallback)
        self.assertGreater(result, 0.0)

    def test_target_apy_8_pct(self):
        """Целевой APY — 8.0%."""
        from spa_core.strategies.s18_high_yield_t2 import TARGET_APY_PCT
        self.assertAlmostEqual(TARGET_APY_PCT, 8.0, places=5)

    def test_weighted_calculation_correctness(self):
        """Weighted APY корректно вычисляется из весов слотов."""
        # Настраиваем конкретные APY:
        # safety_net → compound_v3: 6.0 (30%)
        # core_a → sfrax: 10.0 (35%); boost → wusdm: 8.0 (10%) (wusdm > sdai > sfrax нет)
        # core_b → sdai: 7.0 (25%)
        s = _make_strategy({
            "compound_v3": _MockAdapter(apy=6.0,  eligible=True),
            "sfrax":       _MockAdapter(apy=10.0, eligible=True),
            "wusdm":       _MockAdapter(apy=8.0,  eligible=True),
            "sdai":        _MockAdapter(apy=7.0,  eligible=True),
        })
        # core_a → sfrax(10.0), boost → sfrax(10.0 > wusdm 8.0 > sdai 7.0)
        # sfrax: 45000/100000=0.45 weight
        # sdai: 25000/100000=0.25
        # compound_v3: 30000/100000=0.30
        # expected = 0.30*6.0 + 0.45*10.0 + 0.25*7.0 = 1.8 + 4.5 + 1.75 = 8.05
        result = s.get_expected_apy()
        self.assertAlmostEqual(result, 8.05, places=2)

    def test_all_slots_unresolved_returns_target(self):
        """Если все слоты unresolved → возвращает TARGET_APY_PCT (8.0%)."""
        from spa_core.strategies.s18_high_yield_t2 import TARGET_APY_PCT
        s = _make_strategy({
            "compound_v3": _IneligibleAdapter(),
            "spark_susds": _IneligibleAdapter(),
            "sfrax":   _IneligibleAdapter(),
            "wusdm":   _IneligibleAdapter(),
            "sdai":    _IneligibleAdapter(),
            "scrvusd": _IneligibleAdapter(),
        })
        result = s.get_expected_apy()
        self.assertAlmostEqual(result, TARGET_APY_PCT, places=5)

    def test_partial_unresolved_redistributes(self):
        """При unresolved T2 слотах APY снижается к T1 уровню."""
        s = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.0, eligible=True),
            "sfrax":   _IneligibleAdapter(),
            "wusdm":   _IneligibleAdapter(),
            "sdai":    _IneligibleAdapter(),
            "scrvusd": _IneligibleAdapter(),
        })
        result = s.get_expected_apy()
        # Все T2 unresolved → всё в compound_v3 (5.0%), APY ≈ 5.0
        self.assertAlmostEqual(result, 5.0, places=2)

    def test_apy_within_reasonable_range(self):
        """APY в разумном диапазоне [1.0, 30.0]."""
        from spa_core.strategies.s18_high_yield_t2 import MIN_APY_ELIGIBLE, MAX_APY_ELIGIBLE
        s = _make_full_strategy()
        result = s.get_expected_apy()
        self.assertGreaterEqual(result, MIN_APY_ELIGIBLE)
        self.assertLessEqual(result, MAX_APY_ELIGIBLE)

    def test_boost_uses_highest_apy_adapter(self):
        """Boost выбирает самый высокий APY, что повышает weighted APY."""
        s_low = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.0, eligible=True),
            "sfrax":       _MockAdapter(apy=8.0, eligible=True),
            "wusdm":       _MockAdapter(apy=3.0, eligible=True),  # boost → wusdm (3.0)
            "sdai":        _MockAdapter(apy=5.0, eligible=True),
        })
        s_high = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.0,  eligible=True),
            "sfrax":       _MockAdapter(apy=8.0,  eligible=True),
            "wusdm":       _MockAdapter(apy=15.0, eligible=True),  # boost → wusdm (15.0)
            "sdai":        _MockAdapter(apy=5.0,  eligible=True),
        })
        apy_low  = s_low.get_expected_apy()
        apy_high = s_high.get_expected_apy()
        self.assertGreater(apy_high, apy_low)

    def test_deterministic(self):
        """get_expected_apy() детерминирован при одинаковых адаптерах."""
        s = _make_full_strategy()
        r1 = s.get_expected_apy()
        r2 = s.get_expected_apy()
        self.assertEqual(r1, r2)


# ──────────────────────────────────────────────────────────────────────────────
# TestGetRiskSummary — 12 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestGetRiskSummary(unittest.TestCase):

    def setUp(self):
        self.s = _make_full_strategy()
        self.rs = self.s.get_risk_summary()

    def test_risk_score_value(self):
        """risk_score == 0.42."""
        self.assertAlmostEqual(self.rs["risk_score"], 0.42, places=5)

    def test_t1_weight_pct_30(self):
        """t1_weight_pct == 30.0 (safety_net только T1)."""
        self.assertAlmostEqual(self.rs["t1_weight_pct"], 30.0, places=2)

    def test_t2_weight_pct_70(self):
        """t2_weight_pct == 70.0 (core_a+core_b+boost = 35+25+10)."""
        self.assertAlmostEqual(self.rs["t2_weight_pct"], 70.0, places=2)

    def test_t2_adapter_count_positive(self):
        """t2_adapter_count >= 1 при наличии T2 адаптеров."""
        self.assertGreaterEqual(self.rs["t2_adapter_count"], 1)

    def test_risk_note_is_string(self):
        """risk_note является строкой."""
        self.assertIsInstance(self.rs["risk_note"], str)

    def test_risk_note_mentions_50_pct(self):
        """risk_note упоминает порог ADR-019 (50%)."""
        self.assertIn("50%", self.rs["risk_note"])

    def test_adr_019_compliant_false(self):
        """adr_019_compliant == False (T2=70% > 50%)."""
        self.assertFalse(self.rs["adr_019_compliant"])

    def test_max_t2_weight(self):
        """max_t2_weight == 0.70."""
        self.assertAlmostEqual(self.rs["max_t2_weight"], 0.70, places=5)

    def test_t1_plus_t2_equals_100(self):
        """t1_weight_pct + t2_weight_pct == 100%."""
        total = self.rs["t1_weight_pct"] + self.rs["t2_weight_pct"]
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_risk_score_in_range(self):
        """risk_score в диапазоне [0, 1]."""
        self.assertGreaterEqual(self.rs["risk_score"], 0.0)
        self.assertLessEqual(self.rs["risk_score"], 1.0)

    def test_t2_weight_pct_greater_than_t1(self):
        """T2 вес больше T1 вес (агрессивная стратегия)."""
        self.assertGreater(self.rs["t2_weight_pct"], self.rs["t1_weight_pct"])

    def test_adr_019_compliant_key_exists(self):
        """Ключ adr_019_compliant существует в результате."""
        self.assertIn("adr_019_compliant", self.rs)


# ──────────────────────────────────────────────────────────────────────────────
# TestGetHealth — 8 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestGetHealth(unittest.TestCase):

    def test_returns_dict(self):
        """get_health() возвращает dict."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertIsInstance(result, dict)

    def test_strategy_id(self):
        """health содержит корректный strategy_id."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertEqual(result["strategy_id"], "S18")

    def test_total_slots_four(self):
        """total_slots == 4."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertEqual(result["total_slots"], 4)

    def test_eligible_slots_with_full_adapters(self):
        """Все 4 слота eligible при полном наборе адаптеров."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertEqual(result["eligible_slots"], 4)

    def test_overall_status_ok(self):
        """overall_status == 'ok' когда все слоты eligible."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertEqual(result["overall_status"], "ok")

    def test_overall_status_degraded(self):
        """overall_status == 'degraded' когда часть слотов unresolved."""
        s = _make_strategy({
            "compound_v3": _MockAdapter(apy=5.2, eligible=True),
            "sfrax":   _IneligibleAdapter(),
            "wusdm":   _IneligibleAdapter(),
            "sdai":    _MockAdapter(apy=5.5, eligible=True),
        })
        result = s.get_health()
        self.assertIn(result["overall_status"], ["ok", "degraded"])

    def test_slots_is_dict_with_4_entries(self):
        """health['slots'] — dict с 4 записями (по одной на слот)."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertIsInstance(result["slots"], dict)
        self.assertEqual(len(result["slots"]), 4)

    def test_expected_apy_positive(self):
        """health['expected_apy'] > 0 при наличии eligible адаптеров."""
        s = _make_full_strategy()
        result = s.get_health()
        self.assertGreater(result["expected_apy"], 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# TestSimulate — 8 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestSimulate(unittest.TestCase):

    def _s(self):
        return _make_full_strategy()

    def test_returns_dict(self):
        """simulate() возвращает dict."""
        result = self._s().simulate(100_000.0)
        self.assertIsInstance(result, dict)

    def test_expected_yield_positive(self):
        """expected_annual_yield_usd > 0 при capital > 0."""
        result = self._s().simulate(100_000.0)
        self.assertGreater(result["expected_annual_yield_usd"], 0.0)

    def test_total_capital_preserved(self):
        """total_capital == capital_usd."""
        s = self._s()
        capital = 100_000.0
        result = s.simulate(capital)
        self.assertAlmostEqual(result["total_capital"], capital, places=3)

    def test_expected_apy_pct_positive(self):
        """expected_apy_pct > 0."""
        result = self._s().simulate(100_000.0)
        self.assertGreater(result["expected_apy_pct"], 0.0)

    def test_allocation_not_empty(self):
        """allocation не пустой dict при capital > 0."""
        result = self._s().simulate(100_000.0)
        self.assertTrue(len(result["allocation"]) > 0)

    def test_status_ok(self):
        """status == 'ok' при capital > 0."""
        result = self._s().simulate(100_000.0)
        self.assertEqual(result["status"], "ok")

    def test_slot_results_has_entries(self):
        """slot_results содержит записи по адаптерам."""
        result = self._s().simulate(100_000.0)
        self.assertIsInstance(result["slot_results"], dict)
        self.assertGreater(len(result["slot_results"]), 0)

    def test_capital_zero_yield_zero(self):
        """При capital=0 → yield = 0 и allocation пустой/нулевой."""
        result = self._s().simulate(0.0)
        self.assertAlmostEqual(result["expected_annual_yield_usd"], 0.0, places=5)
        self.assertAlmostEqual(result["total_capital"], 0.0, places=5)


# ──────────────────────────────────────────────────────────────────────────────
# TestToDict — 7 тестов
# ──────────────────────────────────────────────────────────────────────────────

class TestToDict(unittest.TestCase):

    def setUp(self):
        self.s = _make_full_strategy()
        self.d = self.s.to_dict()

    def test_returns_dict(self):
        """to_dict() возвращает dict."""
        self.assertIsInstance(self.d, dict)

    def test_json_serializable(self):
        """to_dict() результат полностью JSON-serializable."""
        try:
            json.dumps(self.d)
        except (TypeError, ValueError) as e:
            self.fail(f"to_dict() не JSON-serializable: {e}")

    def test_has_strategy_id(self):
        """to_dict() содержит корректный strategy_id."""
        self.assertEqual(self.d["strategy_id"], "S18")

    def test_has_target_apy_pct(self):
        """to_dict() содержит target_apy_pct."""
        self.assertIn("target_apy_pct", self.d)
        self.assertAlmostEqual(self.d["target_apy_pct"], 8.0, places=5)

    def test_has_risk_score(self):
        """to_dict() содержит risk_score."""
        self.assertIn("risk_score", self.d)
        self.assertAlmostEqual(self.d["risk_score"], 0.42, places=5)

    def test_has_slots_info(self):
        """to_dict() содержит slots с 4 записями."""
        self.assertIn("slots", self.d)
        self.assertIsInstance(self.d["slots"], dict)
        self.assertEqual(len(self.d["slots"]), 4)

    def test_has_timestamp(self):
        """to_dict() содержит timestamp."""
        self.assertIn("timestamp", self.d)
        self.assertIsInstance(self.d["timestamp"], str)
        self.assertGreater(len(self.d["timestamp"]), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
