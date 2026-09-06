"""ADR-239 — крест двух пространств имён личности: рынок Pendle ↔ пул DeFiLlama.

Что здесь проверяется и почему именно так
=========================================
Приказ владельца (CIO, остаток G1) требовал ответить: **«один ли это рынок»** у
ключей ``pendle`` и ``pendle_pt_susde``. Ответить было нечем — ``pendle`` берёт
число из Pendle V2 REST и в пространстве имён DeFiLlama UUID не имеет. Сторож
тождества сравнивает UUID, поэтому про ``pendle`` он говорил не «коллизии нет»,
а «сравнивать нечем».

Каждый тест ниже — положительный контроль на ЗАМЕРЕННОЕ 2026-09-06 состояние
живых источников (Pendle REST + выгрузка DeFiLlama, 17 176 пулов, 90 строк
``pendle-v2``/Ethereum), а не на выдуманную форму:

* у рынка APYUSD в фиде ДВЕ ноги с БАЙТ В БАЙТ одинаковым TVL $21 447 313 —
  PT ``9fe33fd6…`` (14.018 пп целиком ``apyBase``) и LP ``8dc83a62…``
  (13.732 пп, из них 0.344 пп эмиссия). Это РАЗНЫЕ инструменты;
* общий отбор ``DeFiLlamaFeed.get_pool_id('pendle-v2','APYUSD')`` — «побеждает
  больший TVL» — на живых данных отдаёт ногу **LP**. Это не гипотеза о
  возможной ошибке, это ответ живого кода, и он здесь воспроизведён;
* ``PT-strUSD-26NOV2026`` и ``PT-sUSDe-26NOV2026`` гасятся В ОДИН ДЕНЬ ⇒ срок
  сам по себе инструмент не называет; у одного актива живёт несколько выпусков
  ⇒ актив сам по себе тоже.

Даты здесь — ДАТЫ ПОГАШЕНИЯ инструментов, то есть сам предмет сверки: ими
инструмент и определён. Часов в проверяемом коде нет ни одних — ``resolve_pool_identity``
не спрашивает «сегодня» ни разу, поэтому сдвиг календаря не может изменить ни
один вердикт этого файла.
"""
# FROZEN-DATE-OK: даты — предмет сверки (срок погашения = часть личности
# инструмента), а не отметка свежести: в проверяемом коде часов нет вовсе.
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.defillama_feed import DeFiLlamaFeed
from spa_core.adapters.pendle_adapter import PendleAdapter
from spa_core.adapters.pendle_pool_identity import (
    CORROBORATED,
    CORROBORATION_TOLERANCE_PP,
    DIVERGENT,
    UNMEASURED,
    parse_pt_leg,
    resolve_pool_identity,
)
from spa_core.adapters.pendle_pt import PendleMarketData
from spa_core.monitoring.adapter_status_generator import _lookup_pendle_pt
from spa_core.orchestrator import adapter_orchestrator as orch

# ── UUID из живой выгрузки 2026-09-06 ────────────────────────────────────────
APYUSD_PT = "9fe33fd6-d3f3-4dbe-9187-7bff012e79f5"
APYUSD_LP = "8dc83a62-a160-4bcf-ac7f-a1f812a317dc"
SUSDE_PT = "fc9a73bc-8ccc-5701-9007-1aeb68ff6a51"
SUSDE_LP = "afdef3b3-9d5c-4e39-8f0f-8a3f2f6b6d21"
STRUSD_PT = "576837c2-16a2-4b56-9c1a-6f3a1cbe0d0e"
USD3_PT = "b6490fe9-3f0c-4a6a-a1a1-8dc3f0d5f0a3"

#: Строки фида ДОСЛОВНОЙ формы (поля, которыми пользуется крест). TVL у ног
#: одного рынка одинаков намеренно — так он и приходит.
PENDLE_POOLS = [
    {"pool": APYUSD_LP, "project": "pendle-v2", "chain": "Ethereum",
     "symbol": "APYUSD", "tvlUsd": 21_447_313, "apy": 13.73208,
     "apyBase": 13.38794, "apyReward": 0.34414,
     "poolMeta": "For LP | Maturity 05NOV2026"},
    {"pool": APYUSD_PT, "project": "pendle-v2", "chain": "Ethereum",
     "symbol": "APYUSD", "tvlUsd": 21_447_313, "apy": 14.01831,
     "apyBase": 14.01831, "apyReward": None,
     "poolMeta": "For buying PT-apyUSD-05NOV2026"},
    {"pool": SUSDE_LP, "project": "pendle-v2", "chain": "Ethereum",
     "symbol": "SUSDE", "tvlUsd": 3_668_597, "apy": 5.39176,
     "apyBase": 5.39176, "apyReward": None,
     "poolMeta": "For LP | Maturity 26NOV2026"},
    {"pool": SUSDE_PT, "project": "pendle-v2", "chain": "Ethereum",
     "symbol": "SUSDE", "tvlUsd": 3_668_597, "apy": 4.90572,
     "apyBase": 4.90572, "apyReward": None,
     "poolMeta": "For buying PT-sUSDe-26NOV2026"},
    {"pool": STRUSD_PT, "project": "pendle-v2", "chain": "Ethereum",
     "symbol": "STRUSD", "tvlUsd": 7_133_706, "apy": 11.7844,
     "apyBase": 11.7844, "apyReward": None,
     "poolMeta": "For buying PT-strUSD-26NOV2026"},
    {"pool": USD3_PT, "project": "pendle-v2", "chain": "Ethereum",
     "symbol": "USD3", "tvlUsd": 6_681_052, "apy": 13.94251,
     "apyBase": 13.94251, "apyReward": None,
     "poolMeta": "For buying PT-USD3-17DEC2026"},
]

#: Рынок, который живой ``PendleAdapter`` выбрал 06.09 (единственный, прошедший
#: собственный тир-порог $20M).
APYUSD_MARKET = dict(
    underlying_asset="apyUSD",
    maturity_date="2026-11-05",
    implied_apy_pct=14.0147,
)


class FakeFeed(DeFiLlamaFeed):
    """Живой фид офлайн падает (`.claude/rules/adapters.md`) — подменяем снимок."""

    def __init__(self, pools):
        super().__init__(enabled=False)
        self._pools = pools

    def _fetch_pools(self):
        return self._pools


def _market(**over) -> PendleMarketData:
    """Рынок Pendle формы живого ответа REST."""
    data = dict(
        market_address="0xc5f938a8ef5f3bf9e72f5aa094baf5e03f4727d3",
        name="PT-apyUSD-5NOV2026",
        underlying_asset="apyUSD",
        pt_apy=14.0147,
        underlying_apy=13.0735,
        maturity_date="2026-11-05",
        days_to_maturity=60,
        tvl_usd=21_371_652.0,
        is_expired=False,
        liquidity_usd=21_371_652.0,
        implied_apy=14.0147,
    )
    data.update(over)
    return PendleMarketData(**data)


def _adapter(markets, pools) -> PendleAdapter:
    pt = MagicMock()
    pt.get_top_markets.return_value = markets
    return PendleAdapter(_pendle_pt_adapter=pt, _defillama_feed=FakeFeed(pools))


# ── 1. Ключ креста — ИНСТРУМЕНТ, а не размер и не цена ───────────────────────

class TestInstrumentIsTheKey(unittest.TestCase):

    def test_pt_leg_wins_over_lp_leg_with_byte_identical_tvl(self):
        got = resolve_pool_identity(pools=PENDLE_POOLS, **APYUSD_MARKET)
        self.assertEqual(got.pool_id, APYUSD_PT)
        self.assertEqual(got.candidates, 1)

    def test_generic_largest_tvl_rule_picks_the_WRONG_leg(self):
        # Замер 06.09 на живом фиде: общий отбор отдаёт ногу LP — другой
        # инструмент (13.73 пп, из них 0.344 пп эмиссия) вместо PT (14.02 пп
        # целиком apyBase). Ради этого крест и написан отдельно; если тест
        # когда-нибудь позеленеет «сам», значит фид сменил форму, а не мы.
        generic = FakeFeed(PENDLE_POOLS).get_pool_id("pendle-v2", "APYUSD")
        self.assertEqual(generic, APYUSD_LP)
        self.assertNotEqual(
            generic, resolve_pool_identity(pools=PENDLE_POOLS, **APYUSD_MARKET).pool_id
        )

    def test_same_maturity_other_asset_is_a_different_instrument(self):
        # strUSD и sUSDe гасятся В ОДИН ДЕНЬ — срок сам по себе не опознаёт.
        got = resolve_pool_identity(
            underlying_asset="sUSDe", maturity_date="2026-11-26",
            implied_apy_pct=4.90572, pools=PENDLE_POOLS,
        )
        self.assertEqual(got.pool_id, SUSDE_PT)
        self.assertNotEqual(got.pool_id, STRUSD_PT)

    def test_same_asset_other_maturity_is_a_different_instrument(self):
        got = resolve_pool_identity(
            underlying_asset="apyUSD", maturity_date="2026-12-05",
            implied_apy_pct=14.0147, pools=PENDLE_POOLS,
        )
        self.assertIsNone(got.pool_id)
        self.assertIn("нет ноги PT", got.reason)

    def test_asset_case_does_not_decide(self):
        # REST зовёт актив "apyUSD", фид пишет "PT-apyUSD-…", symbol "APYUSD".
        got = resolve_pool_identity(
            underlying_asset="APYUSD", maturity_date="2026-11-05",
            implied_apy_pct=14.0147, pools=PENDLE_POOLS,
        )
        self.assertEqual(got.pool_id, APYUSD_PT)

    def test_lp_leg_alone_is_not_an_instrument(self):
        only_lp = [p for p in PENDLE_POOLS if p["pool"] == APYUSD_LP]
        got = resolve_pool_identity(pools=only_lp, **APYUSD_MARKET)
        self.assertIsNone(got.pool_id)
        self.assertTrue(got.reason.strip())


# ── 2. Fail-CLOSED и ТРЕТИЙ ИСХОД: причина записана всегда ───────────────────

class TestRefusalIsNamed(unittest.TestCase):

    def test_no_pools_refuses_with_a_reason(self):
        got = resolve_pool_identity(pools=None, **APYUSD_MARKET)
        self.assertIsNone(got.pool_id)
        self.assertIn("недоступен", got.reason)

    def test_two_pools_for_one_instrument_refuse_rather_than_pick(self):
        twin = dict(PENDLE_POOLS[1])
        twin["pool"] = "00000000-0000-0000-0000-000000000000"
        got = resolve_pool_identity(pools=PENDLE_POOLS + [twin], **APYUSD_MARKET)
        self.assertIsNone(got.pool_id)
        self.assertEqual(got.candidates, 2)
        self.assertIn("монеткой", got.reason)

    def test_unreadable_maturity_is_not_matched(self):
        broken = dict(PENDLE_POOLS[1])
        broken["poolMeta"] = "For buying PT-apyUSD-NOVEMBER"
        got = resolve_pool_identity(
            pools=[broken, PENDLE_POOLS[0]], **APYUSD_MARKET
        )
        self.assertIsNone(got.pool_id)

    def test_row_without_uuid_is_not_an_answer(self):
        anon = dict(PENDLE_POOLS[1])
        anon["pool"] = ""
        got = resolve_pool_identity(pools=[anon], **APYUSD_MARKET)
        self.assertIsNone(got.pool_id)

    def test_other_chain_does_not_match(self):
        got = resolve_pool_identity(
            pools=PENDLE_POOLS, chain="Arbitrum", **APYUSD_MARKET
        )
        self.assertIsNone(got.pool_id)

    def test_other_project_does_not_match(self):
        foreign = dict(PENDLE_POOLS[1])
        foreign["project"] = "pendle"          # старое поколение, другой проект
        got = resolve_pool_identity(pools=[foreign], **APYUSD_MARKET)
        self.assertIsNone(got.pool_id)

    def test_market_without_asset_or_maturity_is_refused(self):
        got = resolve_pool_identity(
            underlying_asset="", maturity_date="", pools=PENDLE_POOLS,
        )
        self.assertIsNone(got.pool_id)
        self.assertIn("опознавать нечем", got.reason)

    def test_parse_pt_leg_reads_the_instrument(self):
        self.assertEqual(
            parse_pt_leg(PENDLE_POOLS[1]), ("apyusd", date(2026, 11, 5))
        )
        self.assertIsNone(parse_pt_leg(PENDLE_POOLS[0]))   # нога LP
        self.assertIsNone(parse_pt_leg({"poolMeta": None}))


# ── 3. Подтверждение ценой — ОТДЕЛЬНЫЙ вопрос со своей ценой ошибки ──────────

class TestCorroborationIsNotIdentity(unittest.TestCase):

    def test_price_within_tolerance_is_corroborated(self):
        got = resolve_pool_identity(pools=PENDLE_POOLS, **APYUSD_MARKET)
        self.assertEqual(got.corroboration, CORROBORATED)
        # Живой разброс двух источников 06.09: 14.01831 против 14.0147.
        self.assertLess(got.apy_delta_pp, 0.01)

    def test_price_disagreement_does_NOT_unname_the_instrument(self):
        # Два источника опрашиваются в разные моменты; расхождение цены —
        # предмет `adapter_feed_divergence`, а не вердикт о личности.
        got = resolve_pool_identity(
            underlying_asset="apyUSD", maturity_date="2026-11-05",
            implied_apy_pct=8.0, pools=PENDLE_POOLS,
        )
        self.assertEqual(got.pool_id, APYUSD_PT)
        self.assertEqual(got.corroboration, DIVERGENT)
        self.assertGreater(got.apy_delta_pp, CORROBORATION_TOLERANCE_PP)

    def test_no_price_means_unmeasured_not_corroborated(self):
        got = resolve_pool_identity(
            underlying_asset="apyUSD", maturity_date="2026-11-05",
            implied_apy_pct=None, pools=PENDLE_POOLS,
        )
        self.assertEqual(got.pool_id, APYUSD_PT)
        self.assertEqual(got.corroboration, UNMEASURED)
        self.assertIsNone(got.apy_delta_pp)


# ── 4. ПРОВОДКА: адаптер → YieldInfo → запись оркестратора ───────────────────

class TestWiring(unittest.TestCase):

    def test_adapter_names_the_pt_pool_in_yield_info(self):
        info = _adapter([_market()], PENDLE_POOLS).get_yield_info()
        self.assertEqual(info.pool_id, APYUSD_PT)
        self.assertIsNone(info.pool_id_refused)

    def test_feed_outage_never_suppresses_the_apy(self):
        info = _adapter([_market()], None).get_yield_info()
        self.assertAlmostEqual(info.apy, 0.140147, places=6)
        self.assertIsNone(info.pool_id)
        self.assertTrue(info.pool_id_refused)

    def test_unknown_chain_refuses_by_construction(self):
        pt = MagicMock()
        pt.get_top_markets.return_value = [_market()]
        a = PendleAdapter(
            chain_id=8453, _pendle_pt_adapter=pt, _defillama_feed=FakeFeed(PENDLE_POOLS)
        )
        info = a.get_yield_info()
        self.assertIsNone(info.pool_id)
        self.assertTrue(info.pool_id_refused)

    def test_refused_market_carries_no_identity_at_all(self):
        # Ниже собственного тир-порога адаптер отказывает от числа — личности
        # там тоже быть не должно (иначе снимок назвал бы пул, из которого
        # ничего не наблюдалось).
        info = _adapter([_market(tvl_usd=6_000_000.0)], PENDLE_POOLS).get_yield_info()
        self.assertIsNone(info.apy)
        self.assertIsNone(info.pool_id)

    def _record(self, info: YieldInfo) -> dict:
        class _Fake:
            PROTOCOL = "pendle"

            def get_yield_info(self_inner):
                return info

        return orch._run_one_adapter(
            "pendle", "T3", _Fake, "2026-09-06T06:00:00+00:00",
            datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc),
        )

    def test_snapshot_carries_the_named_pool(self):
        rec = self._record(YieldInfo(
            protocol="pendle", asset="USDC", apy=0.140147, tvl_usd=21_371_652.0,
            tier="T3", risk_score=0.45, tvl_source="live", pool_id=APYUSD_PT,
        ))
        self.assertEqual(rec["pool_id"], APYUSD_PT)
        self.assertIsNone(rec["pool_id_refused"])

    def test_snapshot_carries_the_REASON_when_identity_is_unmeasured(self):
        # Мутация «перестать возить причину в снимок» краснит именно здесь:
        # без причины пустой `pool_id` неотличим от адаптера, который про пулы
        # не умеет вовсе, — а это разные состояния с разной починкой.
        rec = self._record(YieldInfo(
            protocol="pendle", asset="USDC", apy=0.140147, tvl_usd=21_371_652.0,
            tier="T3", risk_score=0.45, tvl_source="live",
            pool_id=None, pool_id_refused="в фиде нет ноги PT для apyusd/2026-11-05",
        ))
        self.assertIsNone(rec["pool_id"])
        self.assertIn("нет ноги PT", rec["pool_id_refused"])

    def test_reason_is_dropped_when_identity_IS_named(self):
        rec = self._record(YieldInfo(
            protocol="pendle", asset="USDC", apy=0.140147, tvl_usd=21_371_652.0,
            tier="T3", risk_score=0.45, tvl_source="live",
            pool_id=APYUSD_PT, pool_id_refused="остаточная причина",
        ))
        self.assertIsNone(rec["pool_id_refused"])


# ── 5. Ответ на вопрос приказа: «ОДИН ЛИ ЭТО РЫНОК» ──────────────────────────

class TestTheQuestionTheOrderAsked(unittest.TestCase):
    """`pendle` и `pendle_pt_susde` — один инструмент или два.

    До ADR-239 ответа не существовало: у одного ключа личности не было вовсе,
    и сторож тождества честно говорил «сравнивать нечем». Теперь обе стороны
    называют UUID ОДНОГО пространства имён, и вопрос стал разрешимым — вот его
    измеренный ответ на данных 06.09.
    """

    def test_the_two_keys_resolve_to_different_pools(self):
        ours = resolve_pool_identity(pools=PENDLE_POOLS, **APYUSD_MARKET).pool_id
        theirs = _lookup_pendle_pt(
            "pendle_pt_susde", PENDLE_POOLS, today=date(2026, 9, 6)
        )
        self.assertEqual(ours, APYUSD_PT)
        self.assertEqual(theirs["pool"], SUSDE_PT)
        self.assertNotEqual(ours, theirs["pool"])

    def test_a_collision_would_now_be_visible(self):
        # Ключевое: ценность креста не в сегодняшнем «нет», а в том, что «да»
        # СТАЛО ВЫРАЗИМЫМ. Рынок sUSDe однажды может пройти собственный
        # тир-порог `pendle` — тогда оба ключа назовут ОДИН UUID, и сторож
        # тождества увидит пару, которой до сих пор не видел по построению.
        as_if = resolve_pool_identity(
            underlying_asset="sUSDe", maturity_date="2026-11-26",
            implied_apy_pct=4.90572, pools=PENDLE_POOLS,
        ).pool_id
        theirs = _lookup_pendle_pt(
            "pendle_pt_susde", PENDLE_POOLS, today=date(2026, 9, 6)
        )
        self.assertEqual(as_if, theirs["pool"])


class TestTheGuardCanNowSeeIt(unittest.TestCase):
    """ДО КОНЦА ПРОВОДА: дойдёт ли подпись до сторожа тождества (урок ADR-238).

    Юнит-проверки выше говорят о функциях. Вопрос, дойдёт ли ответ до
    ПОТРЕБИТЕЛЯ, — отдельный, и задаётся он отдельно: ADR-238 нашёл ровно
    обратный случай, когда производитель подпись писал, а сторож её выбрасывал.

    Замер того же дифференциала на ЖИВЫХ артефактах (06.09, песочница, живое
    `data/` не тронуто): с подписью сторож даёт пару `pendle + pendle_pt_susde`
    (warn 5), без неё — молчание (warn 4) на том же снимке.
    """

    ORCH_ROW = {
        "protocol": "pendle", "status": "ok", "live_data": True,
        "tvl_source": "live", "tvl_usd": 3_668_597.0, "apy_pct": 4.90572,
    }
    STATUS_DOC = {
        "adapters": {
            "pendle_pt_susde": {
                "tvl_source": "live", "tvl_usd": 3_668_597.0,
                "live_apy": 4.90572, "tvl_pool_id": SUSDE_PT,
            }
        }
    }

    def _pairs(self, pool_id):
        from spa_core.monitoring import pool_identity_collision as guard

        orch = {"adapters": [dict(self.ORCH_ROW, pool_id=pool_id)]}
        obs, _unchecked = guard._observations(orch, self.STATUS_DOC)
        pairs, _named = guard._declared_pairs(obs, {}, guard._identities(self.STATUS_DOC))
        return pairs

    def test_named_identity_makes_the_pair_visible(self):
        self.assertEqual(
            self._pairs(SUSDE_PT).get(SUSDE_PT), ["pendle", "pendle_pt_susde"]
        )

    def test_without_identity_the_same_collision_is_invisible(self):
        # Контроль: тот же такт, те же числа — но подписи нет, и пары нет.
        # Это и есть цена молчания, которую ADR-239 закрывает.
        self.assertNotIn(SUSDE_PT, self._pairs(None))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
