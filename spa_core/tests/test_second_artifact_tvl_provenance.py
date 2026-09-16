"""ADR-398 — второй артефакт перестаёт описывать литералом то, что наблюдено рядом.

Почему этот файл существует
---------------------------
Про один и тот же профинансированный протокол в один и тот же цикл система держит ДВА
снимка. Замер `scripts/capital_observability_census.py` на живом каталоге 2026-09-16:

    aave_v3     ($5 000 книги)  поверхность решения $58 276 662 `live`
                                adapter_status.json $12 000 000 000 `static`   ×205.9
    compound_v3 ($40 000 книги) поверхность решения $35 527 960 `live`
                                adapter_status.json  $3 000 000 000 `static`   ×84.4

$45 000 — 47.4 % развёрнутого капитала — второй артефакт описывал литералом
`_TVL_ESTIMATES` там, где наблюдение лежало РЯДОМ, в тот же цикл. Гейт финансирования
этим не обманут: он судит по снимку оркестратора. Обманут отчёт владельцу и
советательные стратегии — второй файл читают шесть потребителей.

Причина была не в тождестве, а в ПРОВЕНАНСЕ. Оба ключа разрешались хинтом, и разрешались
ВЕРНО (`_CANONICAL_UNDERLYING` отсекает чужой актив) — но хинту по контракту
`test_tvl_pinned_provenance` запрещено штамповать TVL `live`, потому что «побеждает
больший TVL» есть тождество, способное молча уехать. Пин делает то же наблюдение
предъявимым: `tvl_pool_id` записан, аудитор может перекачать UUID и воспроизвести число.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* пин ⇒ `tvl_source="live"` + UUID в `tvl_pool_id`;
* **снять пин ⇒ вернуть литерал** — это положительный контроль, воспроизводящий
  измеренную аварию, а не украшение;
* ближний промах (USDE $548M @ 4.75 %, актив ДРУГОЙ, ставка ВЫШЕ) не побеждает;
* проба приёмки `second_artifact_tvl_agrees` зелена на целом контуре и красна на
  КАЖДОМ порванном звене — с названным звеном;
* протухший снимок ⇒ `unmeasured`, НИКОГДА не `not_satisfied`.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся и в
фикстуры, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается: фид
подменяется `FakeFeed`-фикстурой (`.claude/rules/adapters.md`).
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import adapter_status_generator as gen
from spa_core.monitoring import card_acceptance as ca
from spa_core.tests._freshness import now_utc

_FETCH = "spa_core.monitoring.adapter_status_generator._fetch_defillama"

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "second_artifact_tvl_agrees"

# ── Живой фид, запись 2026-09-16 (дословно; underlying — тот факт, что делает
#    тождество проверяемым) ────────────────────────────────────────────────────
_CIRCLE_USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

_AAVE_USDC = {
    "pool": "aa70268e-4b52-42bf-a116-608b370f9501",
    "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC",
    "tvlUsd": 190_403_740.0, "apy": 3.56705, "apyBase": 3.56705, "apyReward": None,
    "underlyingTokens": [_CIRCLE_USDC],
}
_COMPOUND_USDC = {
    "pool": "7da72d09-56ca-4ec5-a45f-59114353e487",
    "project": "compound-v3", "chain": "Ethereum", "symbol": "USDC",
    "tvlUsd": 38_729_092.0, "apy": 3.22644, "apyBase": 3.22644, "apyReward": 0,
    "underlyingTokens": [_CIRCLE_USDC],
}
#: Ближний промах aave-v3 на той же цепи: ставка ВЫШЕ пина (4.75 против 3.57), из неё
#: 4.09 пп — раздача токена, а актив ДРУГОЙ. Это соблазн, который «побеждает больший
#: TVL» однажды возьмёт: $548M против $190M у пина.
_AAVE_USDE = {
    "pool": "21e1ac8a-b3aa-4576-9506-0b40137721a0",
    "project": "aave-v3", "chain": "Ethereum", "symbol": "USDE",
    "tvlUsd": 548_217_678.0, "apy": 4.74782, "apyBase": 0.65949, "apyReward": 4.08833,
    "underlyingTokens": ["0x4c9edd5852cd905f086c759e8383e09bff1e68b3"],
}

_PINNED = {"aave_v3": _AAVE_USDC, "compound_v3": _COMPOUND_USDC}
_ALL_POOLS = [_AAVE_USDC, _COMPOUND_USDC, _AAVE_USDE]

_REGISTRY = {
    "adapters": {
        "aave_v3": {"protocol": "aave_v3", "tier": 1, "fallback_apy": 0.035,
                    "chain": "ethereum", "per_protocol_cap": 0.4, "status": "active"},
        "compound_v3": {"protocol": "compound_v3", "tier": 1, "fallback_apy": 0.052,
                        "chain": "ethereum", "per_protocol_cap": 0.4, "status": "active"},
    }
}


class TestPinsRegistered(unittest.TestCase):
    """Сами пины — проверка таблицы, фид не участвует."""

    def test_both_keys_pinned_to_the_scanned_uuids(self):
        for key, pool in _PINNED.items():
            with self.subTest(key=key):
                self.assertEqual(gen._POOL_ID_LOOKUP.get(key), pool["pool"])

    def test_each_pin_is_the_native_circle_usdc_pool(self):
        """Тождество проверяемо по активу, а не по имени символа."""
        for key, pool in _PINNED.items():
            with self.subTest(key=key):
                self.assertEqual([t.lower() for t in pool["underlyingTokens"]],
                                 [_CIRCLE_USDC])

    def test_no_two_keys_share_a_pool(self):
        """Два ключа на одном пуле — скрытая концентрация, которую cap не видит."""
        vals = list(gen._POOL_ID_LOOKUP.values())
        self.assertEqual(len(vals), len(set(vals)), "один пул закреплён за двумя ключами")

    def test_the_literal_the_pin_replaces_is_still_in_the_table(self):
        """Оценка НЕ удалена: она остаётся запасом на «фид не ответил».

        Смысл пина не в том, чтобы стереть литерал, а в том, чтобы литерал никогда
        не выходил под маркой наблюдения. Тест держит обе половины утверждения.
        """
        self.assertEqual(gen._TVL_ESTIMATES["aave_v3"], 12_000_000_000.0)
        self.assertEqual(gen._TVL_ESTIMATES["compound_v3"], 3_000_000_000.0)


class _GenBase(unittest.TestCase):
    """generate() на временном реестре — ни сети, ни `data/` репозитория."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.registry = self.data_dir / "adapter_registry.json"
        self.output = self.data_dir / "adapter_status.json"
        self.registry.write_text(json.dumps(_REGISTRY), encoding="utf-8")

    def _generate(self, pools=None):
        with patch(_FETCH, return_value=list(_ALL_POOLS if pools is None else pools)):
            return gen.generate(registry_path=self.registry, output_path=self.output)


class TestPinnedTvlIsObserved(_GenBase):

    def test_pinned_key_stamps_live_tvl_from_the_matched_pool(self):
        rows = self._generate()["adapters"]
        for key, pool in _PINNED.items():
            with self.subTest(key=key):
                self.assertEqual(rows[key]["pool_match"], "pinned")
                self.assertEqual(rows[key]["tvl_source"], "live")
                self.assertEqual(rows[key]["tvl_usd"], pool["tvlUsd"])
                self.assertEqual(rows[key]["tvl_pool_id"], pool["pool"])

    def test_the_observation_is_two_orders_below_the_literal_it_replaced(self):
        """Направление ошибки названо числом, а не словом «примерно»."""
        rows = self._generate()["adapters"]
        self.assertLess(rows["aave_v3"]["tvl_usd"],
                        gen._TVL_ESTIMATES["aave_v3"] / 50)
        self.assertLess(rows["compound_v3"]["tvl_usd"],
                        gen._TVL_ESTIMATES["compound_v3"] / 50)

    def test_the_higher_yield_foreign_asset_pool_does_not_win(self):
        """Положительный контроль тождества: USDE платит больше и НЕ выбирается."""
        rows = self._generate()["adapters"]
        self.assertNotEqual(rows["aave_v3"]["pool_id"], _AAVE_USDE["pool"])
        self.assertAlmostEqual(rows["aave_v3"]["live_apy"], _AAVE_USDC["apy"], places=3)

    def test_removing_the_pin_brings_the_literal_back(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: воспроизводит измеренную аварию 16.09.

        Снять пин — и хинт по-прежнему разрешает ТОТ ЖЕ пул (тождество не ломается),
        но TVL снова становится литералом под маркой `static`. Тест, который этого
        не показывает, не отличал бы починку от совпадения.
        """
        without = {k: v for k, v in gen._POOL_ID_LOOKUP.items() if k not in _PINNED}
        with patch.object(gen, "_POOL_ID_LOOKUP", without):
            rows = self._generate()["adapters"]
        for key in _PINNED:
            with self.subTest(key=key):
                self.assertEqual(rows[key]["pool_match"], "hint")
                self.assertEqual(rows[key]["tvl_source"], "static")
                self.assertEqual(rows[key]["tvl_usd"], gen._TVL_ESTIMATES[key])
                self.assertIsNone(rows[key]["tvl_pool_id"])

    def test_a_pin_that_the_feed_does_not_carry_never_becomes_live(self):
        """Фид не принёс закреплённый пул ⇒ литерал, честно помеченный `static`."""
        rows = self._generate(pools=[_AAVE_USDE])["adapters"]
        self.assertEqual(rows["compound_v3"]["tvl_source"], "static")
        self.assertIsNone(rows["compound_v3"]["tvl_pool_id"])


class TestFloorVerdictBecomesReachable(_GenBase):
    """Что ИМЕННО изменилось у потребителя, который судит о пороге.

    `status_reader.tvl_floor_verdict` трёхзначен и читает РОВНО `tvl_source == "live"`
    из этого файла. До пина оба ключа давали `None` («не измерено»), и ветка `False`
    была для них НЕДОСТИЖИМА по построению — та же форма, что у `moonwell_base` с его
    `TVL_USD = 500_000_000`: литерал в роли гейта не может ответить «нет» ни при каком
    входе.

    Оба ключа входят в аварийную книгу (`portfolio_rebalancer._SAFE_FALLBACK_POSITIONS`),
    поэтому эффект замерен, а не предположен: по ADR-108 (выбор владельца C) `None` —
    «оставить», `True` — «оставить», и СОСТАВ КНИГИ от этой правки не меняется. Меняется
    другое: гейт впервые СПОСОБЕН сказать «нет», если наблюдённый пул уйдёт под пол.
    """

    def _verdict(self, doc, floor=5_000_000.0):
        from spa_core.adapters.status_reader import tvl_floor_verdict
        out = Path(self._tmp.name) / "adapter_status.json"
        out.write_text(json.dumps(doc), encoding="utf-8")
        return {k: tvl_floor_verdict(k, Path(self._tmp.name), floor) for k in _PINNED}

    def test_before_the_pin_the_verdict_is_unmeasured(self):
        without = {k: v for k, v in gen._POOL_ID_LOOKUP.items() if k not in _PINNED}
        with patch.object(gen, "_POOL_ID_LOOKUP", without):
            doc = self._generate()
        self.assertEqual(self._verdict(doc), {"aave_v3": None, "compound_v3": None})

    def test_after_the_pin_the_verdict_is_a_measured_pass(self):
        self.assertEqual(self._verdict(self._generate()),
                         {"aave_v3": True, "compound_v3": True})

    def test_the_false_branch_is_now_reachable_for_these_keys(self):
        """Гейт, который не может ответить «нет», — литерал `True` в роли гейта.

        Пол поднимается выше наблюдённого размера: вердикт обязан стать `False`.
        До пина он остался бы `None` при ЛЮБОМ поле — это и проверяет соседний тест.
        """
        self.assertEqual(self._verdict(self._generate(), floor=1e12),
                         {"aave_v3": False, "compound_v3": False})

    def test_both_keys_are_in_the_emergency_book_so_the_effect_is_not_hypothetical(self):
        from spa_core.tuner import portfolio_rebalancer as pr
        for key in _PINNED:
            with self.subTest(key=key):
                self.assertIn(key, pr._SAFE_FALLBACK_POSITIONS)


# ── Проба приёмки карточки: контроль в ОБЕ стороны ───────────────────────────

class _ProbeBase(unittest.TestCase):
    """Песочница из двух артефактов. Часы — вход, якорь берётся ВНУТРИ теста."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        # Якорь считается здесь, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        self.book_stamp = (self.now - timedelta(hours=2)).isoformat()

    def _write(self, *, book: dict | None = None, status: dict | None = None):
        if book is not None:
            (self.data_dir / "current_positions.json").write_text(
                json.dumps(book), encoding="utf-8")
        if status is not None:
            (self.data_dir / "adapter_status.json").write_text(
                json.dumps(status), encoding="utf-8")

    def _book(self, *, tvl_sources: dict, stamp: str | None = None) -> dict:
        return {
            "generated_at": stamp or self.book_stamp,
            "positions": {"aave_v3": 5_000.0, "compound_v3": 40_000.0},
            "deployed_usd": 45_000.0,
            "feed_coverage": {
                "apy_sources": {"aave_v3": "live", "compound_v3": "live"},
                "tvl_sources": dict(tvl_sources),
                "tvl_usd": {"aave_v3": 58_276_662.0, "compound_v3": 35_527_960.0},
            },
        }

    def _status(self, rows: dict) -> dict:
        return {"generated_at": self.book_stamp, "adapters": rows}

    def _row(self, *, tvl_source: str | None, tvl_usd: float,
             live_apy: float | None = 3.5) -> dict:
        return {"live_apy": live_apy, "tvl_source": tvl_source, "tvl_usd": tvl_usd}

    def _healthy(self):
        self._write(
            book=self._book(tvl_sources={"aave_v3": "live", "compound_v3": "live"}),
            status=self._status({
                "aave_v3": self._row(tvl_source="live", tvl_usd=190_403_740.0),
                "compound_v3": self._row(tvl_source="live", tvl_usd=38_729_092.0),
            }))

    def _probe(self, **kw):
        return ca._probe_second_artifact_tvl_agrees(
            None, now=kw.pop("now", self.now), data_dir=str(self.data_dir), **kw)


class TestProbeGreenOnTheWholeContour(_ProbeBase):

    def test_intact_contour_is_satisfied(self):
        self._healthy()
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("спора по оси TVL нет", detail)


class TestProbeRedOnEachBrokenLink(_ProbeBase):
    """Каждое звено рвётся ОТДЕЛЬНО, и звено НАЗЫВАЕТСЯ в вердикте."""

    def test_second_artifact_back_on_a_literal_is_not_satisfied(self):
        """Ровно авария 16.09: поверхность наблюдает, второй файл — литерал."""
        self._healthy()
        self._write(status=self._status({
            "aave_v3": self._row(tvl_source="static", tvl_usd=12_000_000_000.0),
            "compound_v3": self._row(tvl_source="live", tvl_usd=38_729_092.0),
        }))
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("aave_v3", detail)
        self.assertNotIn("compound_v3", detail)
        self.assertIn("×205.9", detail)

    def test_protocol_absent_from_the_second_artifact_is_not_satisfied(self):
        """Молчание второго файла о профинансированных деньгах — не согласие."""
        self._healthy()
        self._write(status=self._status({
            "aave_v3": self._row(tvl_source="live", tvl_usd=190_403_740.0),
        }))
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("compound_v3", detail)
        self.assertIn("нет во втором артефакте", detail)

    def test_null_provenance_is_not_satisfied_either(self):
        """`null` честнее литерала, но спор со вторым артефактом НЕ снимает."""
        self._healthy()
        self._write(status=self._status({
            "aave_v3": self._row(tvl_source=None, tvl_usd=0.0),
            "compound_v3": self._row(tvl_source="live", tvl_usd=38_729_092.0),
        }))
        self.assertEqual(self._probe()[0], ca.NOT_SATISFIED)


class TestProbeRefusesInsteadOfLying(_ProbeBase):
    """Третий исход: «не измерено» никогда не выдаётся ни за одно из двух других."""

    def test_stale_book_is_unmeasured_not_not_satisfied(self):
        """Замороженный канон `data/` в worktree/CI судить о проде не вправе."""
        self._healthy()
        stale = (self.now - timedelta(hours=ca.CENSUS_MAX_AGE_H + 1)).isoformat()
        self._write(book=self._book(
            tvl_sources={"aave_v3": "static", "compound_v3": "static"}, stamp=stale))
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_fresh_book_at_the_window_edge_is_still_judged(self):
        """Контроль окна в обратную сторону: ровно на пределе проба ещё судит."""
        self._healthy()
        edge = (self.now - timedelta(hours=ca.CENSUS_MAX_AGE_H - 0.01)).isoformat()
        self._write(book=self._book(
            tvl_sources={"aave_v3": "live", "compound_v3": "live"}, stamp=edge))
        self.assertEqual(self._probe()[0], ca.SATISFIED)

    def test_unreadable_second_artifact_is_unmeasured(self):
        self._healthy()
        (self.data_dir / "adapter_status.json").write_text("{", encoding="utf-8")
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)

    def test_second_artifact_without_an_adapters_section_is_unmeasured(self):
        self._healthy()
        self._write(status={"generated_at": self.book_stamp})
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("НЕ СОСТОЯЛАСЬ", detail)

    def test_missing_data_dir_is_unmeasured(self):
        verdict, detail = ca._probe_second_artifact_tvl_agrees(
            None, now=self.now, data_dir=str(self.data_dir / "нет-такого"))
        self.assertEqual(verdict, ca.UNMEASURED, detail)


class TestProbeMeasuresItsOwnAxisOnly(_ProbeBase):
    """Границы карточки: соседний предмет не красит и не зеленит эту пробу."""

    def test_apy_axis_dispute_alone_stays_satisfied(self):
        """Перепись вернула бы код 1; у ЭТОЙ карточки предмет другой."""
        self._healthy()
        self._write(status=self._status({
            "aave_v3": self._row(tvl_source="live", tvl_usd=190_403_740.0,
                                 live_apy=None),
            "compound_v3": self._row(tvl_source="live", tvl_usd=38_729_092.0),
        }))
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_decision_surface_blind_on_tvl_is_also_a_dispute(self):
        """Спор считается в ОБЕ стороны: слепа поверхность — тоже находка."""
        self._healthy()
        self._write(book=self._book(
            tvl_sources={"aave_v3": "static", "compound_v3": "live"}))
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("aave_v3", detail)


class TestProbeIsWiredAndReadsTheRealCensus(_ProbeBase):

    def test_registered_under_its_exact_name(self):
        self.assertIs(ca.PROBES.get(PROBE_NAME), ca._probe_second_artifact_tvl_agrees)

    def test_declaration_validates(self):
        self.assertIsNone(ca.validate_spec(PROBE_NAME))

    def test_a_near_name_is_refused_not_matched_as_a_substring(self):
        """ADR-333: имя пробы — равенство, а не вхождение подстроки."""
        self.assertIsNotNone(ca.validate_spec(PROBE_NAME[:-1]))
        self.assertIsNotNone(ca.validate_spec(PROBE_NAME + "_x"))

    def test_the_probe_goes_through_the_census_module_not_a_private_copy(self):
        """Подменяем сам модуль переписи — вердикт обязан пойти за ним.

        Проба, несущая собственную копию логики переписи, этот контроль провалит:
        её вердикт не изменится. Так проверяется ПРОВОДКА, а не имя.
        """
        self._healthy()
        self.assertEqual(self._probe()[0], ca.SATISFIED)

        real = ca._census_module()

        class _Sabotaged:
            NotMeasured = real.NotMeasured

            @staticmethod
            def measure(_dir):
                raise real.NotMeasured("подменённая перепись отказалась")

        with patch.object(ca, "_census_module", lambda: _Sabotaged):
            verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("подменённая перепись отказалась", detail)


if __name__ == "__main__":
    unittest.main()
