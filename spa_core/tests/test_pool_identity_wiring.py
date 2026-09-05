"""ADR-233 — ПРОВОДКА личности пула: фид → адаптер → YieldInfo → снимок оркестратора.

Зачем отдельный файл
====================
Сторож `adapter_feed_divergence` умеет развести «один пул, два числа» и «два пула,
два числа» — но только если ОБЕ стороны личность назвали. Тесты самого сторожа
(`test_adapter_pool_identity_divergence.py`) кормят его фикстурами, поэтому снятие
поля из ПРОИЗВОДИТЕЛЯ не покрасило бы там ни одного теста: сторож продолжил бы
честно отвечать «unchecked» на выдуманные входы, а в проде замолчал бы навсегда.

Ровно этот класс назван в `.claude/rules/deployment.md` и в памяти проекта:
проверять надо ПРОВОДКУ, а не только детали. Здесь мутация «убрать
`pool_id` из записи оркестратора» или «перестать читать `resolved_pool_id`
в адаптере» обязана краснить.

Числа — из живого фида 2026-09-05 (замер цикла #492), см. соседний файл.
"""
# FROZEN-DATE-OK: даты — предмет замера 2026-09-05 (снимок 06:00Z).
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from spa_core.adapters.aave_v3 import AaveV3Adapter
from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.defillama_feed import DeFiLlamaFeed
from spa_core.orchestrator import adapter_orchestrator as orch

CORE_POOL = "aa70268e-4b52-42bf-a116-608b370f9501"
UMBRELLA_POOL = "6f00d46b-8735-49ae-9ced-2a0fccc56ad0"
PRIME_POOL = "effcb4a4-4dcb-45e5-935d-f15542c13e6b"

#: Четыре кандидата ключа `aave_v3` — ДОСЛОВНО из живого фида 05.09 (17 041 пул),
#: включая поле `underlyingTokens`, которым эти пулы и различаются.
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
UMBRELLA_TOKEN = "0xD4fa2D31b7968E448877f69A96DE69f5de8cD23E"

AAVE_POOLS = [
    {"pool": CORE_POOL, "project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
     "tvlUsd": 153_552_956, "apy": 3.58713, "apyBase": 3.58713, "apyReward": None,
     "poolMeta": None, "underlyingTokens": [USDC]},
    {"pool": UMBRELLA_POOL, "project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
     "tvlUsd": 58_619_173, "apy": 5.24713, "apyBase": 3.58713, "apyReward": 1.66,
     "poolMeta": "Umbrella", "underlyingTokens": [UMBRELLA_TOKEN]},
    {"pool": PRIME_POOL, "project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
     "tvlUsd": 1_529_813, "apy": 2.58038, "apyBase": 2.58038, "apyReward": None,
     "poolMeta": "Prime Instance", "underlyingTokens": [USDC]},
    {"pool": "27296bf9-617a-46e4-9d6d-eefc71e9e0b6", "project": "aave-v3",
     "symbol": "USDC", "chain": "Ethereum", "tvlUsd": 654_137, "apy": 4.372,
     "apyBase": 4.372, "apyReward": None, "poolMeta": "Aave Horizon Market",
     "underlyingTokens": [USDC]},
]


class FakeFeed(DeFiLlamaFeed):
    """Живой фид офлайн падает (`.claude/rules/adapters.md`) — подменяем снимок."""

    def __init__(self, pools):
        super().__init__()
        self._pools = pools

    def _fetch_pools(self):
        return self._pools


class TestFeedNamesTheResolvedPool(unittest.TestCase):

    def test_get_pool_id_returns_the_winner_of_the_same_selection(self):
        feed = FakeFeed(AAVE_POOLS)
        self.assertEqual(feed.get_pool_id("aave-v3", "USDC", "Ethereum"), CORE_POOL)
        # И это ТОТ ЖЕ пул, из которого взято число рядом — иначе личность
        # относилась бы к другому отбору, чем ставка.
        self.assertAlmostEqual(feed.get_apy("aave-v3", "USDC", "Ethereum"), 0.0358713)

    def test_when_the_core_market_drops_out_the_adapter_falls_to_Umbrella(self):
        """Воспроизведение снимка 06:00Z: без ядра путь адаптера берёт «Umbrella».

        Это и есть авария: `Umbrella` несёт ЧУЖОЙ underlying (не USDC) и 1.66 пп
        эмиссии, а точное совпадение символа про underlying не спрашивает.
        """
        feed = FakeFeed([p for p in AAVE_POOLS if p["pool"] != CORE_POOL])
        self.assertEqual(feed.get_pool_id("aave-v3", "USDC", "Ethereum"), UMBRELLA_POOL)
        self.assertAlmostEqual(feed.get_apy("aave-v3", "USDC", "Ethereum"), 0.0524713)

    def test_no_match_is_None_not_a_fabricated_identity(self):
        self.assertIsNone(FakeFeed([]).get_pool_id("aave-v3", "USDC", "Ethereum"))

    def test_a_pool_without_an_id_yields_no_identity(self):
        pools = [dict(AAVE_POOLS[0])]
        pools[0].pop("pool")
        self.assertIsNone(FakeFeed(pools).get_pool_id("aave-v3", "USDC", "Ethereum"))


class TestAFeedThatCannotNameAPoolDoesNotBreakFetch(unittest.TestCase):
    """Положительный контроль на дефект, допущенный в этой же правке (05.09).

    Первая редакция звала `safe_call(self.feed.get_pool_id, …)`. Обращение к
    атрибуту вычисляется ДО того, как `safe_call` получит управление, поэтому
    фид без этого метода поднимал `AttributeError` прямо из `fetch()` — а
    `fetch()` по контракту НЕ БРОСАЕТ никогда. Замер: так покраснели 23
    существующие проверки в четырёх файлах.

    Урок общий: обёртка «никогда не бросает» не покрывает вычисление СВОИХ
    аргументов. Фид, не умеющий назвать пул, обязан давать «личность НЕ
    ИЗМЕРЕНА», а не аварию.
    """

    class FeedWithoutTheMethod:
        """Двойник старого образца — ровно то, что живёт в чужих тестах."""

        def get_apy(self, *_a, **_k):
            return 0.0358713

        def get_tvl(self, *_a, **_k):
            return 153_552_956.0

    def test_fetch_survives_and_reports_no_identity(self):
        adapter = AaveV3Adapter(feed=self.FeedWithoutTheMethod())
        record = adapter.fetch()          # обязано НЕ бросить
        self.assertEqual(record["status"], "ok")
        self.assertIsNone(record["resolved_pool_id"])

    def test_yield_info_survives_and_keeps_the_live_number(self):
        info = AaveV3Adapter(feed=self.FeedWithoutTheMethod()).get_yield_info()
        self.assertIsNone(info.pool_id)
        self.assertAlmostEqual(info.apy, 0.0358713)

    def test_a_feed_whose_method_raises_is_also_not_an_outage(self):
        class Exploding(self.FeedWithoutTheMethod):
            def get_pool_id(self, *_a, **_k):
                raise RuntimeError("feed down")

        info = AaveV3Adapter(feed=Exploding()).get_yield_info()
        self.assertIsNone(info.pool_id)
        self.assertAlmostEqual(info.apy, 0.0358713)

    def test_a_blank_answer_is_NOT_an_identity(self):
        """Пустая строка — «личность не измерена», а не личность.

        Иначе два ключа с пустым ответом сравнились бы как РАВНЫЕ, и сверка
        тождества объявила бы «пул тот же» там, где не назван ни один.
        """
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=repr(blank)):
                class Blank(self.FeedWithoutTheMethod):
                    def get_pool_id(self, *_a, _b=blank, **_k):
                        return _b

                info = AaveV3Adapter(feed=Blank()).get_yield_info()
                self.assertIsNone(info.pool_id)

    def test_a_padded_identity_is_trimmed_not_rejected(self):
        class Padded(self.FeedWithoutTheMethod):
            def get_pool_id(self, *_a, **_k):
                return f"  {CORE_POOL}  "

        self.assertEqual(
            AaveV3Adapter(feed=Padded()).get_yield_info().pool_id, CORE_POOL)

    def test_a_non_string_answer_is_refused(self):
        class Numeric(self.FeedWithoutTheMethod):
            def get_pool_id(self, *_a, **_k):
                return 42

        self.assertIsNone(AaveV3Adapter(feed=Numeric()).get_yield_info().pool_id)


class TestAdapterCarriesIdentityIntoYieldInfo(unittest.TestCase):

    def test_yield_info_names_the_pool_the_number_came_from(self):
        info = AaveV3Adapter(feed=FakeFeed(AAVE_POOLS)).get_yield_info()
        self.assertEqual(info.pool_id, CORE_POOL)
        self.assertAlmostEqual(info.apy, 0.0358713)

    def test_identity_follows_the_number_when_the_winner_changes(self):
        feed = FakeFeed([p for p in AAVE_POOLS if p["pool"] != CORE_POOL])
        info = AaveV3Adapter(feed=feed).get_yield_info()
        self.assertEqual(info.pool_id, UMBRELLA_POOL)
        self.assertAlmostEqual(info.apy, 0.0524713)

    def test_dead_feed_declares_no_identity_rather_than_a_stale_one(self):
        info = AaveV3Adapter(feed=FakeFeed([])).get_yield_info()
        self.assertIsNone(info.apy)
        self.assertIsNone(info.pool_id)

    def test_the_hand_written_slug_is_NOT_used_as_identity(self):
        """`pool_id` класса — слаг-константа; личностью она быть не может.

        Слаг одинаков при ЛЮБОМ исходе отбора, поэтому подстановка его в
        `YieldInfo.pool_id` сделала бы сверку тождества вечно-зелёной.
        """
        info = AaveV3Adapter(feed=FakeFeed(AAVE_POOLS)).get_yield_info()
        self.assertEqual(AaveV3Adapter.pool_id, "aave-v3-usdc-ethereum")
        self.assertNotEqual(info.pool_id, AaveV3Adapter.pool_id)


def _fake_adapter(protocol: str, apy, pool_id):
    class _Fake:
        PROTOCOL = protocol

        def __init__(self, *_a, **_k):
            pass

        def get_yield_info(self):
            return YieldInfo(protocol=protocol, asset="USDC", apy=apy,
                             tvl_usd=1_000_000.0, tier="T1", risk_score=0.2,
                             tvl_source="live", pool_id=pool_id)

    _Fake.__name__ = f"Fake_{protocol}"
    return _Fake


class TestOrchestratorRecordsIdentity(unittest.TestCase):
    """Снимок оркестратора обязан НЕСТИ личность — иначе сверять нечего."""

    def _run(self, registry):
        return orch.run_orchestrator(
            registry=registry, write=False,
            now_fn=lambda: datetime(2026, 9, 5, 6, 0, 28, tzinfo=timezone.utc))

    def test_pool_id_reaches_the_snapshot_record(self):
        res = self._run([("aave_v3", "T1", _fake_adapter("aave_v3", 0.0358713, CORE_POOL))])
        record = next(a for a in res.adapters if a["protocol"] == "aave_v3")
        self.assertEqual(record["pool_id"], CORE_POOL)
        # Оркестратор округляет до 4 знаков (0.0358713 × 100 → 3.5871).
        self.assertEqual(record["apy_pct"], 3.5871)

    def test_an_adapter_that_cannot_name_a_pool_records_None_not_a_guess(self):
        res = self._run([("maple", "T2", _fake_adapter("maple", 0.05, None))])
        record = next(a for a in res.adapters if a["protocol"] == "maple")
        self.assertIsNone(record["pool_id"])
        # Поле обязано ПРИСУТСТВОВАТЬ: отсутствие ключа и «не измерено» —
        # разные вещи для читателя, а сторож различает их по значению.
        self.assertIn("pool_id", record)

    def test_the_field_is_present_even_when_the_adapter_blows_up(self):
        class _Boom:
            PROTOCOL = "euler_v2"

            def __init__(self, *_a, **_k):
                pass

            def get_yield_info(self):
                raise RuntimeError("feed down")

        res = self._run([("euler_v2", "T2", _Boom)])
        record = next(a for a in res.adapters if a["protocol"] == "euler_v2")
        self.assertIn("pool_id", record)
        self.assertIsNone(record["pool_id"])
        self.assertEqual(record["status"], "error")

    def test_identity_does_not_seize_the_protocol_key(self):
        """Личность — диагностика, а не имя. Ключ снимка остаётся реестровым."""
        res = self._run([("aave_v3", "T1", _fake_adapter("aave_v3", 0.03, CORE_POOL))])
        record = next(a for a in res.adapters if a["protocol"] == "aave_v3")
        self.assertEqual(record["protocol"], "aave_v3")
        self.assertEqual(record["pool_id"], CORE_POOL)


class TestBothFeedClassesCanNameAPool(unittest.TestCase):
    """Классов фида ДВА, и они не взаимозаменяемы — метод обязан быть у обоих.

    Замер 05.09: `aave_v3` и `morpho_steakhouse` берут
    `spa_core.adapters.defillama_feed.DeFiLlamaFeed`, а `morpho_blue`, `yearn_v3`,
    `euler_v2`, `maple` — `spa_core.feeds.defi_llama_feed.DefiLlamaFeed` (имена
    различаются одной буквой). Добавь метод только одному — и ЧЕТЫРЕ из семи
    опрашиваемых адаптеров личность не назовут никогда, а сверка тождества для
    них выродится в вечное «не измерено», то есть в украшение.

    Тот же класс, что три реестра с одним именем (`.claude/rules/adapters.md`).
    """

    def test_both_classes_expose_the_accessor(self):
        from spa_core.feeds.defi_llama_feed import DefiLlamaFeed as OtherFeed
        for cls in (DeFiLlamaFeed, OtherFeed):
            with self.subTest(cls=f"{cls.__module__}.{cls.__name__}"):
                self.assertTrue(callable(getattr(cls, "get_pool_id", None)))

    #: Замер 05.09: опрашиваемые адаптеры, резолвящие пул ЧЕРЕЗ фид. Остальные
    #: четыре (`aave_v3_base`, `morpho_blue_base`, `fluid_usdc`, `pendle`) фида не
    #: держат — их вердикт тождества честно `unchecked`, и это назван­ное состояние.
    FEED_BACKED = {"aave_v3", "compound_v3", "morpho_blue", "morpho_steakhouse",
                   "yearn_v3", "euler_v2", "maple"}

    def test_every_polled_adapter_that_uses_a_feed_can_name_its_pool(self):
        """Ни один опрашиваемый адаптер не должен молча выпасть из сверки."""
        missing, checked = [], set()
        for key, _tier, cls in orch.POLLED_ADAPTERS:
            # адаптер создаёт фид в __init__ — спрашиваем экземпляр
            try:
                inst = cls()
            except Exception:
                continue
            feed = getattr(inst, "feed", None)
            if feed is None:
                continue          # резолвит не через фид — вердикт честно unchecked
            checked.add(key)
            if not callable(getattr(feed, "get_pool_id", None)):
                missing.append(key)

        # Контроль на ВАКУУМНУЮ зелень: пустой цикл прошёл бы молча, и проверка
        # «ни один не выпал» была бы правдой ни о чём.
        self.assertEqual(
            checked, self.FEED_BACKED,
            "состав адаптеров с фидом изменился — пересмотри список, а не гаси проверку")
        self.assertEqual(
            missing, [],
            f"адаптеры с фидом, который не умеет назвать пул: {missing} — "
            f"для них сверка тождества вечно «не измерено»")


class TestEndToEndTheGuardSeesWhatTheOrchestratorWrote(unittest.TestCase):
    """Сквозной контроль: снимок оркестратора → сторож → верный род находки.

    Именно этот тест краснеет, если проводку снять: сторож получит запись без
    `pool_id`, вердикт личности выродится в `unchecked`, и `apy_identity_mismatch`
    станет недостижим из настоящего производителя.
    """

    def test_identity_mismatch_is_reachable_from_the_real_producer(self):
        from spa_core.monitoring import adapter_feed_divergence as afd
        import json, os, tempfile

        res = orch.run_orchestrator(
            registry=[("aave_v3", "T1", _fake_adapter("aave_v3", 0.0524713, UMBRELLA_POOL))],
            write=False,
            now_fn=lambda: datetime(2026, 9, 5, 6, 0, 28, tzinfo=timezone.utc))

        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            status = {
                "schema_version": 1,
                "generated_at": "2026-09-05T06:00:26.447071+00:00",
                "adapters": {"aave_v3": {
                    "apy": 2.58038, "live_apy": 2.58038, "live_apy_fresh": True,
                    "tvl_usd": 12_000_000_000.0, "tvl_source": "static", "tier": 1,
                    "pool_id": PRIME_POOL,
                }},
            }
            with open(os.path.join(data, "adapter_status.json"), "w") as fh:
                json.dump(status, fh)
            with open(os.path.join(data, "adapter_orchestrator_status.json"), "w") as fh:
                json.dump({"schema_version": 1,
                           "generated_at": "2026-09-05T06:00:28.610293+00:00",
                           "source": "adapter_orchestrator",
                           "adapters": res.adapters}, fh)
            report = afd.run(
                root=tmp, data_dir=data,
                now=datetime(2026, 9, 5, 6, 30, tzinfo=timezone.utc))

        kinds = [f["kind"] for f in report["findings"]]
        self.assertIn("apy_identity_mismatch", kinds)
        f = next(x for x in report["findings"] if x["kind"] == "apy_identity_mismatch")
        self.assertEqual(f["orchestrator_pool"], UMBRELLA_POOL)
        self.assertEqual(f["adapter_status_pool"], PRIME_POOL)
        self.assertEqual(f["identity"], "different")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
