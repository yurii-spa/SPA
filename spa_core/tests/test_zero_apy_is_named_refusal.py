"""Нулевой APY — это ОТКАЗ С НАЗВАННОЙ ПРИЧИНОЙ, а не доходность 0.00 %.

Почему этот файл существует
---------------------------
Карточка владельца `inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu` (решение
08.08) сообщала: у `morpho_blue_base` и `silo_arbitrum` «аномальный APY 0.00 %».
Разбор показал, что 0.00 % никогда не было ВЫХОДОМ адаптера — это строка его
собственного лога о пуле, который он отверг. Наружу же уходил голый ``None``,
неотличимый от «фид не ответил». Отказ БЫЛ, но НЕ БЫЛ ОБЪЯВЛЕН, и поэтому три
недели никто не пошёл смотреть — карточка ушла владельцу с диагнозом «неверный
UUID», которого в этих двух адаптерах нет вовсе (они резолвят пул подсказкой).

Тот же класс на уровне генератора статуса: пин (личность гейт-класса, ADR-064),
который НЕ разрешился — потому что UUID исчез из фида или потому что пул отдаёт
``apy: 0`` — молча падал на нечёткую подсказку. Строка отчёта выглядела
здоровой: ``pool_match: "hint"``, ``pool_match_refused: null``. Для семи
закреплённых ключей БЕЗ подсказки (`sky_susds`, `ondo_usdy`, `susde`, `sfrax`,
`sdai`, `scrvusd`, `extra_finance_base`) отказ не оставлял вообще ничего.

И тот же класс на money-path: аллокатор читал ``float(a.get("apy_pct", 0.0))``
и клеймил результат ``apy_source: "live"`` — ноль, выданный за наблюдение.

Проверки идут В ОБЕ СТОРОНЫ. Тест, который проверяет только «отказ назван»,
пройдёт и на производителе, который отказывает ВСЕГДА — а это и есть вторая
половина того же дефекта. Поэтому у каждого отказа рядом стоит положительный
контроль: здоровый пул по-прежнему наблюдается.

Сети здесь нет: фид инжектируется. Литеральных дат рядом со свежестью нет.
Только stdlib.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.adapters.morpho_blue_base_adapter import MorphoBlueBaseAdapter
from spa_core.adapters.pool_selection import SelectionTally, pool_apy_pct
from spa_core.adapters.silo_arbitrum_usdc_adapter import SiloArbitrumUSDCAdapter
from spa_core.allocator.allocator import StrategyAllocator
from spa_core.monitoring import adapter_status_generator as gen

_FETCH = "spa_core.monitoring.adapter_status_generator._fetch_defillama"

# Настоящая форма UUID — чтобы тест не смог пройти совпадением с "".
_MORPHO_BASE_PIN = "ba68527f-8ec2-4c55-827a-8f4673ae047c"
_USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


# ─────────────────────────────────────────────────────────────────────────────
# Помощники: фальшивый фид (FakeFeed), сети нет
# ─────────────────────────────────────────────────────────────────────────────

def _patch_pools(module_path: str, pools: list[dict]):
    """Патчит urlopen адаптера, отдавая ``pools`` как ответ DeFiLlama."""

    class _Resp:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    payload = json.dumps({"status": "success", "data": pools}).encode("utf-8")
    return patch(
        f"{module_path}.urllib.request.urlopen",
        return_value=_Resp(payload),
    )


def _morpho_pool(apy, tvl: float = 587_300_000.0, pool_id: str = _MORPHO_BASE_PIN) -> dict:
    pool = {
        "pool": pool_id,
        "chain": "Base",
        "project": "morpho-blue",
        "symbol": "STEAKUSDC",
        "tvlUsd": tvl,
        "underlyingTokens": [_USDC_BASE],
    }
    if apy is not _MISSING:
        pool["apy"] = apy
    return pool


def _silo_pool(apy, tvl: float = 50_000.0) -> dict:
    pool = {
        "pool": "11111111-2222-3333-4444-555555555555",
        "chain": "Arbitrum",
        "project": "silo-v2",
        "symbol": "USDC",
        "tvlUsd": tvl,
    }
    if apy is not _MISSING:
        pool["apy"] = apy
    return pool


class _Missing:
    """Часовой «поля apy нет вовсе» — отличается от ``apy: None``."""


_MISSING = _Missing()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Чистая функция: отсутствующее наблюдение — не ноль
# ─────────────────────────────────────────────────────────────────────────────

class TestPoolApyPct(unittest.TestCase):
    def test_missing_field_is_none_not_zero(self):
        """``pool.get("apy", 0.0)`` — ровно тот дефект, ради которого модуль."""
        self.assertIsNone(pool_apy_pct({"pool": "x"}))

    def test_null_field_is_none(self):
        self.assertIsNone(pool_apy_pct({"apy": None}))

    def test_bool_is_not_a_yield(self):
        """``True`` — это ``isinstance(int)``; без явной проверки стал бы 1.0 %."""
        self.assertIsNone(pool_apy_pct({"apy": True}))

    def test_nan_is_not_an_observation(self):
        self.assertIsNone(pool_apy_pct({"apy": float("nan")}))

    def test_real_zero_is_reported_as_zero_not_hidden(self):
        """Обратная сторона: настоящий ноль — настоящее наблюдение.

        Судить «ноль ниже санитарной границы» — работа вызывающего, и он обязан
        это ОБЪЯВИТЬ. Функция не имеет права прятать наблюдение под ``None``,
        иначе «пул платит ноль» и «поля нет» снова станут неразличимы.
        """
        self.assertEqual(pool_apy_pct({"apy": 0.0}), 0.0)

    def test_positive_control_normal_value_passes(self):
        self.assertAlmostEqual(pool_apy_pct({"apy": 4.32}), 4.32)


class TestSelectionTally(unittest.TestCase):
    def test_reason_names_the_zero_apy_that_started_this(self):
        tally = SelectionTally()
        tally.scanned = 9
        tally.matched = 1
        tally.reject_anomalous_apy(0.0)
        reason = tally.reason("что искали")
        self.assertIn("0.00%", reason)
        self.assertIn("не ноль", reason)

    def test_reason_distinguishes_no_match_from_rejected_match(self):
        empty = SelectionTally()
        empty.scanned = 9
        self.assertIn("не совпал", empty.reason("что искали"))
        rejected = SelectionTally()
        rejected.scanned = 9
        rejected.matched = 2
        rejected.thin_tvl = 2
        self.assertIn("отвергнуты", rejected.reason("что искали"))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Адаптеры, названные в карточке
# ─────────────────────────────────────────────────────────────────────────────

class _AdapterContract:
    """Общий контракт обоих адаптеров — в обе стороны."""

    module_path: str = ""
    adapter_cls: type = object
    zero_pool: staticmethod = None  # type: ignore[assignment]
    good_pool: staticmethod = None  # type: ignore[assignment]

    def _adapter(self):
        return self.adapter_cls()

    # ── отказ ────────────────────────────────────────────────────────────
    def test_zero_apy_pool_yields_none_not_zero(self):
        a = self._adapter()
        with _patch_pools(self.module_path, [self.zero_pool(0.0)]):
            self.assertIsNone(
                a.get_apy(),
                "нулевой APY уехал наружу числом — это утверждение о доходности",
            )

    def test_zero_apy_refusal_is_named_in_words(self):
        a = self._adapter()
        with _patch_pools(self.module_path, [self.zero_pool(0.0)]):
            a.get_apy()
            reason = a.get_write_state()["refusal_reason"] or ""
        self.assertIn("0.00%", reason, "причина отказа не называет само число")
        self.assertIn("не ноль", reason)

    def test_missing_apy_field_is_refusal_not_zero(self):
        a = self._adapter()
        with _patch_pools(self.module_path, [self.zero_pool(_MISSING)]):
            self.assertIsNone(a.get_apy())
            self.assertTrue(a.get_write_state()["refusal_reason"])

    def test_unreachable_feed_says_so_distinctly(self):
        """«Фид не ответил» и «пул отвергнут» — разные факты, разные строки."""
        a = self._adapter()
        with patch(
            f"{self.module_path}.urllib.request.urlopen",
            side_effect=OSError("no route to host"),
        ):
            self.assertIsNone(a.get_apy())
            reason = a.get_write_state()["refusal_reason"] or ""
        self.assertIn("не ответил", reason)

    def test_yield_info_never_stamps_live_on_the_constant(self):
        a = self._adapter()
        with _patch_pools(self.module_path, [self.zero_pool(0.0)]):
            info = a.get_yield_info()
        self.assertIsNone(info.apy)
        self.assertEqual(info.tvl_source, "static")

    # ── положительный контроль ───────────────────────────────────────────
    def test_healthy_pool_is_still_observed(self):
        a = self._adapter()
        with _patch_pools(self.module_path, [self.good_pool(4.32)]):
            apy = a.get_apy()
            info = a.get_yield_info()
            refusal = a.get_write_state()["refusal_reason"]
        self.assertAlmostEqual(apy, 4.32)
        self.assertAlmostEqual(info.apy, 0.0432)
        self.assertEqual(info.tvl_source, "live")
        self.assertIsNone(refusal)


class TestMorphoBlueBase(_AdapterContract, unittest.TestCase):
    module_path = "spa_core.adapters.morpho_blue_base_adapter"
    adapter_cls = MorphoBlueBaseAdapter
    zero_pool = staticmethod(_morpho_pool)
    good_pool = staticmethod(_morpho_pool)

    def test_validate_is_false_when_nothing_was_observed(self):
        """``validate()`` раньше падало на ``None > 0`` и ловило это в except —
        верный ответ по случайной причине. Теперь отсутствие наблюдения
        отвергается явно."""
        a = self._adapter()
        with _patch_pools(self.module_path, [self.zero_pool(0.0)]):
            self.assertFalse(a.validate())

    def test_validate_positive_control(self):
        a = self._adapter()
        with _patch_pools(self.module_path, [self.good_pool(4.32)]):
            self.assertTrue(a.validate())


class TestSiloArbitrum(_AdapterContract, unittest.TestCase):
    module_path = "spa_core.adapters.silo_arbitrum_usdc_adapter"
    adapter_cls = SiloArbitrumUSDCAdapter
    zero_pool = staticmethod(_silo_pool)
    good_pool = staticmethod(_silo_pool)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Генератор статуса: пин, который не разрешился, обязан сказать это словами
# ─────────────────────────────────────────────────────────────────────────────

_REGISTRY = {
    "adapters": {
        "morpho_blue_base": {
            "tier": 2, "protocol": "Morpho Blue Base", "chain": "base",
            "fallback_apy": 0.062, "per_protocol_cap": 0.2, "status": "active",
        },
        # Закреплённый ключ БЕЗ подсказки — тот случай, где промах пина
        # не оставлял вообще никакого следа.
        "sfrax": {
            "tier": 2, "protocol": "Frax sFRAX", "chain": "ethereum",
            "fallback_apy": 0.0125, "per_protocol_cap": 0.2, "status": "active",
        },
    }
}


class TestPinRefusalIsNamed(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        self.registry = d / "adapter_registry.json"
        self.output = d / "adapter_status.json"
        self.registry.write_text(json.dumps(_REGISTRY), encoding="utf-8")

    def _generate(self, pools):
        with patch(_FETCH, return_value=pools):
            return gen.generate(registry_path=self.registry, output_path=self.output)

    def test_pinned_pool_with_zero_apy_is_refused_and_named(self):
        """Пул на месте, но платит 0.00 % — это НЕ наблюдение доходности."""
        doc = self._generate([_morpho_pool(0.0)])
        row = doc["adapters"]["morpho_blue_base"]
        self.assertIsNone(row["live_apy"])
        reason = row["pool_match_refused"] or ""
        self.assertIn(_MORPHO_BASE_PIN, reason)
        self.assertIn("never read as 0.00%", reason)

    def test_absent_pin_is_named_even_when_a_hint_resolves(self):
        """Главный молчаливый случай: пин исчез, подсказка «спасла» строку.

        Число при этом принадлежит ДРУГОМУ хранилищу, а отчёт до правки выглядел
        совершенно здоровым.
        """
        other = _morpho_pool(3.22, tvl=172_500_000.0,
                             pool_id="99999999-8888-7777-6666-555555555555")
        doc = self._generate([other])
        row = doc["adapters"]["morpho_blue_base"]
        self.assertEqual(row["pool_match"], "hint")
        self.assertIsNotNone(row["live_apy"])
        reason = row["pool_match_refused"] or ""
        self.assertIn(_MORPHO_BASE_PIN, reason)
        self.assertIn("ABSENT", reason)

    def test_pin_only_key_no_longer_refuses_in_total_silence(self):
        """``sfrax`` закреплён и подсказки не имеет — раньше отказ был пустым."""
        doc = self._generate([_morpho_pool(4.32)])  # sfrax-пула в фиде нет
        row = doc["adapters"]["sfrax"]
        self.assertIsNone(row["live_apy"])
        self.assertTrue(
            row["pool_match_refused"],
            "закреплённый ключ отказал, не оставив ни строчки причины",
        )

    def test_positive_control_healthy_pin_says_nothing(self):
        """Обратная сторона: здоровый пин НЕ обязан ничего объяснять.

        Без этого теста «называть причину всегда» прошло бы на производителе,
        который жалуется и на исправные строки — шум, в котором тонет сигнал.
        """
        doc = self._generate([_morpho_pool(4.32)])
        row = doc["adapters"]["morpho_blue_base"]
        self.assertEqual(row["pool_match"], "pinned")
        self.assertIsNone(row["pool_match_refused"])
        self.assertEqual(row["tvl_source"], "live")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Money-path: аллокатор не имеет права ранжировать ноль как наблюдение
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot(apy_pct, status: str = "partial") -> dict:
    """Снимок оркестратора с одной строкой. ``apy_pct`` подаётся как есть."""
    return {
        "generated_at": "n/a",
        "adapters": [
            {
                "protocol": "morpho_blue_base",
                "tier": "T2",
                "status": status,
                "apy_pct": None if apy_pct is _MISSING else apy_pct,
                "tvl_usd": 587_300_000.0,
                "tvl_source": "live",
                "last_updated": "n/a",
            }
        ],
    }


class TestAllocatorRefusesUnobservedApy(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)
        (self.d / "adapter_registry.json").write_text(
            json.dumps({"adapters": {}}), encoding="utf-8"
        )
        (self.d / "adapter_status.json").write_text(
            json.dumps({"adapters": {}}), encoding="utf-8"
        )

    def _load(self, apy_pct, status: str = "partial"):
        status_path = self.d / "adapter_orchestrator_status.json"
        doc = _snapshot(apy_pct, status)
        if apy_pct is _MISSING:
            doc["adapters"][0].pop("apy_pct")
        status_path.write_text(json.dumps(doc), encoding="utf-8")
        alloc = StrategyAllocator(
            status_path=status_path,
            registry_path=self.d / "adapter_registry.json",
            adapter_status_path=self.d / "adapter_status.json",
        )
        rows = alloc._load_adapters()
        return alloc, {r["protocol"] for r in rows}

    def test_null_apy_row_does_not_crash_the_money_path(self):
        """``float(None)`` бросало TypeError прямо в загрузке аллокатора.

        Оркестратор пишет ``apy_pct: null`` КАЖДЫЙ раз, когда адаптер отказал, —
        то есть отсутствующее наблюдение и было единственным входом этой ветки.
        """
        alloc, names = self._load(None)
        self.assertNotIn("morpho_blue_base", names)
        self.assertEqual(alloc._blocked.get("morpho_blue_base"), "apy_not_observed")

    def test_missing_apy_key_is_refused_not_read_as_zero(self):
        alloc, names = self._load(_MISSING)
        self.assertNotIn("morpho_blue_base", names)
        self.assertEqual(alloc._blocked.get("morpho_blue_base"), "apy_not_observed")

    def test_non_numeric_apy_is_refused(self):
        """Строка вместо числа — тоже отсутствие наблюдения, а не ноль."""
        alloc, names = self._load("n/a")
        self.assertNotIn("morpho_blue_base", names)
        self.assertEqual(alloc._blocked.get("morpho_blue_base"), "apy_not_observed")

    def test_nan_is_closed_at_the_adapter_not_at_the_allocator(self):
        """Где именно закрыт NaN — решение, и оно закреплено с обеих сторон.

        В аллокаторе NaN НЕ отвергается намеренно: ``test_allocator_properties``
        контрактует выживание при NaN/inf, а его карта тиров строится по СЫРОМУ
        снимку — выбросив NaN-строку, мы заставили бы дублирующееся имя
        протокола разрешиться в другой тир и получили бы «нарушение потолка»,
        которого не было (замер: случай 128). Источник закрыт там, где он
        возникает: адаптер физически не может выдать NaN.
        """
        self.assertIsNone(pool_apy_pct({"apy": float("nan")}))
        _alloc, names = self._load(float("nan"))
        self.assertIn("morpho_blue_base", names)

    def test_observed_zero_stays_a_measurement_not_a_refusal(self):
        """Обратная сторона, и она важнее первой.

        Числовой ноль в снимке оркестратора — это НАБЛЮДЕНИЕ («пул платит
        ноль», status ``partial``), а не пропуск. Выбрасывать его здесь значило
        бы чинить симптом чужой правкой: отказ финансировать низкую доходность —
        работа RiskPolicy (MIN_APY 1 %), а не загрузчика. Без этого теста первая
        версия правки молча удалила бы кандидатов из модели ``equal_weight``.
        """
        _alloc, names = self._load(0.0)
        self.assertIn("morpho_blue_base", names)

    def test_positive_control_observed_apy_is_ranked(self):
        _alloc, names = self._load(4.32, status="ok")
        self.assertIn("morpho_blue_base", names)


if __name__ == "__main__":
    unittest.main()
