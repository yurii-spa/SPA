"""Тождество, объявленное КЛАССОМ ключа (ADR-237) — каждый тест воспроизводит замер.

Класс, который здесь закрывается
================================
Ключ, чей путь к фиду не разрешился (ни пина, ни хинта), ранжируется литералом
``fallback_apy`` — и до 2026-09-06 читался как «тождества нет». Замер 06.09 по
живому фиду DeFiLlama (17 099 пулов) и живому ``data/adapter_status.json``:
таких ключей **12 из 34**, и на них стои́т $200 778 советательного капитала.

Тождество у них ЕСТЬ, и оно объявлено — константами класса адаптера, которых
таблица ``_DEFILLAMA_HINTS`` не читала никогда (она ПАРАЛЛЕЛЬНОЕ объявление того
же факта, набираемое руками):

    EthenaSusdeAdapter.DEFILLAMA_PROJECT = "ethena-usde"
    EthenaSusdeAdapter.DEFILLAMA_SYMBOL  = "SUSDE"
    EthenaSusdeAdapter.CHAIN             = "ethereum"
        → в фиде 06.09 РОВНО ОДИН пул: 66985a81-… ($1.41 млрд @ 4.53 %)
        → и это ТОТ ЖЕ UUID, что ``_POOL_ID_LOOKUP["susde"]``

То есть ``ethena_susde`` и ``susde`` — один контракт (Ethena sUSDe), два ключа,
два потолка концентрации (20 % + 10 %) и две цены: ``susde`` наблюдает 4.53 пп,
``ethena_susde`` предъявляет литерал 12.0 пп. Сторож ``pool_identity_collision``
этой пары не видел ПО ПОСТРОЕНИЮ — его популяция была «ключи, которые
РЕЗОЛВЯТСЯ в пул».

``alpha_agent`` назвал эту задачу дословно ещё 17.08: ложная пара
``pendle_pt_susde ↔ susde`` «по ФОРМЕ ИМЕНИ неотличима от верной
``ethena_susde ↔ susde``… разделяет только личность пула (UUID) — это отдельная
задача». Тест ``test_the_false_pair_stays_invisible`` — она и есть.

Положительные контроли, а не украшение
======================================
``test_identity_never_moves_a_number_that_ranks_capital`` падает, если ветка
тождества когда-нибудь тронет ``apy``/``live_apy``/``tvl_usd``/``tvl_source``/
``pool_match`` — то есть если «назвать» превратится в «профинансировать».
``test_pair_is_invisible_without_the_declared_identity`` воспроизводит состояние
ДО правки и требует, чтобы находка тогда ОТСУТСТВОВАЛА: находка, которая была бы
видна и без нового кода, ничего не закрывает.

Время — ВХОД (``now=``), сеть не задействована ни одним тестом: фид передаётся
списком-фикстурой.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import adapter_status_generator as gen
from spa_core.monitoring import pool_identity_collision as pic
from spa_core.tests._freshness import now_utc, ts

# Наблюдения живого фида 2026-09-06, сверенные в тот же заход.
ETHENA_POOL = "66985a81-9c51-46ca-9977-42b4fe7bc6df"
ETHENA_TVL, ETHENA_APY = 1_406_754_377.0, 4.52506
# Ложная пара по форме имени: PT-токен Pendle на sUSDE — ДРУГОЙ пул.
PT_POOL = "fc9a73bc-8ccc-5701-9007-1aeb68ff6a51"


def _pool(pool_id, project, chain, symbol, tvl, apy, **kw):
    row = {"pool": pool_id, "project": project, "chain": chain, "symbol": symbol,
           "tvlUsd": tvl, "apy": apy, "apyBase": apy, "apyReward": None,
           "rewardTokens": None}
    row.update(kw)
    return row


ETHENA_FEED_ROW = _pool(ETHENA_POOL, "ethena-usde", "Ethereum", "SUSDE",
                        ETHENA_TVL, ETHENA_APY)


class TestDeclaredSearch(unittest.TestCase):
    """Объявление ЧИТАЕТСЯ у класса, а не копируется в таблицу рядом."""

    def test_reader_returns_exactly_what_the_class_declares(self):
        """Дрейф-сторож: копия объявления разошлась бы молча, чтение — не может."""
        from spa_core.adapters.ethena_susde_adapter import EthenaSusdeAdapter

        search, why = gen._declared_search("ethena_susde")
        self.assertIsNone(why)
        self.assertEqual(search, (EthenaSusdeAdapter.DEFILLAMA_PROJECT,
                                  EthenaSusdeAdapter.DEFILLAMA_SYMBOL,
                                  EthenaSusdeAdapter.CHAIN))

    def test_class_declaring_no_search_is_refused_with_the_missing_name(self):
        """Замер 06.09: пять классов из двенадцати не объявляют ``DEFILLAMA_PROJECT``.

        Достроить за них «наверное, project == имя ключа» было бы догадкой —
        ровно тем, против чего написан ADR-230. Отказ обязан НАЗВАТЬ, чего нет.
        """
        search, why = gen._declared_search("sfrax")
        self.assertIsNone(search)
        self.assertIn("DEFILLAMA_PROJECT", why)

    def test_key_outside_the_adapter_registry_is_refused_not_guessed(self):
        """``aerodrome_usdc_lp`` держит $25 087 книги и класса в реестре НЕ имеет."""
        search, why = gen._declared_search("aerodrome_usdc_lp")
        self.assertIsNone(search)
        self.assertIn("ADAPTER_REGISTRY", why)


class TestIdentityResolution(unittest.TestCase):
    """Правило «РОВНО ОДИН кандидат» и третий исход."""

    def _by_pcs(self, rows):
        return gen._build_pool_indexes(rows)[1]

    def test_single_candidate_resolves_to_the_uuid_the_class_declares(self):
        pid, declared_by, why = gen._identity_pool(
            "ethena_susde", self._by_pcs([ETHENA_FEED_ROW]))
        self.assertEqual(pid, ETHENA_POOL)
        self.assertIsNone(why)
        self.assertIn("ethena-usde", declared_by)

    def test_two_candidates_refuse_rather_than_take_the_largest(self):
        """ADR-230: победителя выбрал бы порядок TVL, а не объявление.

        Живой пример этого исхода — ``fluid_usdc``: объявленному поиску
        ("fluid-lending", "USDC", ethereum) 06.09 отвечали ЧЕТЫРЕ пула одного
        актива. Пара ``fluid_usdc + fluid_fusdc`` при этом не теряется — её
        по-прежнему держит род ``observed`` того же сторожа.
        """
        rows = [ETHENA_FEED_ROW,
                _pool("aaaaaaaa-0000-0000-0000-000000000000", "ethena-usde",
                      "Ethereum", "SUSDE-EXTRA", 1.0, 9.9)]
        pid, _declared_by, why = gen._identity_pool("ethena_susde", self._by_pcs(rows))
        self.assertIsNone(pid)
        self.assertIn("2", why)

    def test_no_candidate_says_so_and_does_not_return_a_silent_none(self):
        pid, _declared_by, why = gen._identity_pool("ethena_susde", self._by_pcs([]))
        self.assertIsNone(pid)
        self.assertIn("ни один пул", why)


class _GeneratorCase(unittest.TestCase):
    """Прогон настоящего ``generate()`` — фид фикстурой, живое ``data/`` не тронуто."""

    REGISTRY = {
        "ethena_susde": {"tier": 3, "protocol": "Ethena sUSDe (advisory)",
                         "chain": "ethereum", "fallback_apy": 0.12,
                         "per_protocol_cap": 0.2, "status": "active"},
        "susde": {"tier": 3, "protocol": "Ethena sUSDe", "chain": "ethereum",
                  "fallback_apy": 0.12, "per_protocol_cap": 0.1, "status": "active"},
    }

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.dir / "adapter_registry.json").write_text(
            json.dumps({"adapters": self.REGISTRY}), encoding="utf-8")
        self._orig_reg, self._orig_status = gen._REGISTRY_FILE, gen._STATUS_FILE
        self._orig_fetch = gen._fetch_defillama
        gen._REGISTRY_FILE = self.dir / "adapter_registry.json"
        gen._STATUS_FILE = self.dir / "adapter_status.json"

    def tearDown(self):
        gen._REGISTRY_FILE, gen._STATUS_FILE = self._orig_reg, self._orig_status
        gen._fetch_defillama = self._orig_fetch

    def generate(self, feed):
        gen._fetch_defillama = lambda timeout=5: feed
        return gen.generate()["adapters"]


class TestGeneratorRecordsIdentityWithoutFunding(_GeneratorCase):

    def test_unresolved_key_gets_the_identity_its_class_declares(self):
        ad = self.generate([ETHENA_FEED_ROW])
        row = ad["ethena_susde"]
        self.assertIsNone(row["pool_match"], "ключ по-прежнему НЕ резолвится сам")
        self.assertEqual(row["identity_pool_id"], ETHENA_POOL)

    def test_identity_never_moves_a_number_that_ranks_capital(self):
        """Главный контроль: «назвать» не имеет права стать «профинансировать».

        Сравниваются два прогона, различающиеся РОВНО тем, есть ли в фиде пул,
        который объявление ключа находит. Ни одно поле денежного пути не смеет
        отличаться: тождество записывается рядом, а не вместо.
        """
        money = ("apy", "live_apy", "tvl_usd", "tvl_source", "pool_match",
                 "pool_id", "tvl_pool_id", "per_protocol_cap", "active")
        # Пул-пустышка чужого проекта: фид в обеих руках ЖИВОЙ (иначе разошёлся
        # бы feed_reachable, и сравнивались бы два разных мира).
        filler = _pool("bbbbbbbb-0000-0000-0000-000000000000", "some-other",
                       "Ethereum", "XYZ", 1_000.0, 1.0)
        without = self.generate([filler])["ethena_susde"]
        with_pool = self.generate([filler, ETHENA_FEED_ROW])["ethena_susde"]
        for field in money:
            self.assertEqual(without[field], with_pool[field],
                             f"поле денежного пути {field!r} сдвинулось от тождества")
        self.assertIsNone(without["identity_pool_id"])
        self.assertEqual(with_pool["identity_pool_id"], ETHENA_POOL)

    def test_literal_key_keeps_ranking_by_its_literal(self):
        """$75 301 советательного капитала стоят на 12.0 пп и после правки тоже.

        Двинуть их — решение владельца (карточка
        ``owner-decision-dve-treti-kapitala-stoyat-na-chislah-kot``), а не
        следствие того, что сторож научился называть тождество.
        """
        row = self.generate([ETHENA_FEED_ROW])["ethena_susde"]
        self.assertEqual(row["apy"], 12.0)
        self.assertEqual(row["tvl_source"], "static")

    def test_resolved_key_says_WHERE_its_identity_is_instead_of_a_null(self):
        """У запинённого ключа поле пусто — но причина названа, а не подразумевается."""
        row = self.generate([ETHENA_FEED_ROW])["susde"]
        self.assertEqual(row["pool_match"], "pinned")
        self.assertIsNone(row["identity_pool_id"])
        self.assertIn("pool_id", row["identity_refused"])

    def test_silent_feed_is_unmeasured_with_a_reason_never_a_null(self):
        """Третий исход. Авария 05.09 17:44Z: фид отдал 8 байт с кодом 200."""
        row = self.generate(None)["ethena_susde"]
        self.assertIsNone(row["identity_pool_id"])
        self.assertIn("НЕ ИЗМЕРЕНО", row["identity_refused"])


class _CollisionCase(unittest.TestCase):
    """Сторож тождества: фикстуры одного такта, пины — НАСТОЯЩИЕ (``_POOL_ID_LOOKUP``)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, status_rows, orch_rows=None, positions=None):
        (self.dir / "adapter_orchestrator_status.json").write_text(json.dumps(
            {"generated_at": ts(1.0), "adapters": orch_rows or []}), encoding="utf-8")
        (self.dir / "adapter_status.json").write_text(json.dumps(
            {"generated_at": ts(1.0), "adapters": status_rows}), encoding="utf-8")
        (self.dir / "adapter_registry.json").write_text(json.dumps(
            {"adapters": {}}), encoding="utf-8")
        (self.dir / "current_positions.json").write_text(json.dumps(
            {"generated_at": ts(1.0), "positions": positions or {}}), encoding="utf-8")

    def run_guard(self):
        return pic.run(root=str(self.dir), data_dir=str(self.dir), write=False,
                       now=now_utc())

    @staticmethod
    def live(apy, tvl, pool_id):
        return {"apy": apy, "live_apy": apy, "tvl_usd": tvl, "tvl_source": "live",
                "tvl_pool_id": pool_id}

    @staticmethod
    def literal(apy, identity=None, refused=None):
        return {"apy": apy, "live_apy": None, "tvl_usd": 0.0, "tvl_source": "static",
                "tvl_pool_id": None, "pool_match": None, "pool_match_refused": None,
                "identity_pool_id": identity, "identity_refused": refused}

    def _base_rows(self):
        """Два живых наблюдения — иначе сторож честно откажется судить (их < 2)."""
        return {
            "susde": self.live(ETHENA_APY, ETHENA_TVL, ETHENA_POOL),
            "pendle_pt_susde": self.live(4.9068, 3_636_113.0, PT_POOL),
        }

    def collisions_with(self, keys):
        rows = self._base_rows()
        rows.update(keys)
        self.write(rows)
        rep = self.run_guard()
        return [c for c in rep["collisions"] if "ethena_susde" in c["keys"]], rep


class TestHiddenPairBecomesVisible(_CollisionCase):

    def test_class_declared_identity_makes_the_ethena_pair_visible(self):
        """Положительный контроль: пара, которой сторож не видел ПО ПОСТРОЕНИЮ."""
        found, _rep = self.collisions_with(
            {"ethena_susde": self.literal(12.0, identity=ETHENA_POOL)})
        self.assertEqual(len(found), 1, "пара ethena_susde + susde не найдена")
        row = found[0]
        self.assertEqual(row["keys"], ["ethena_susde", "susde"])
        self.assertEqual(row["pool_id"], ETHENA_POOL)
        self.assertEqual(row["named_by"]["ethena_susde"], pic.NAMED_BY_CLASS)
        self.assertEqual(row["named_by"]["susde"], pic.NAMED_BY_PIN)

    def test_pair_is_invisible_without_the_declared_identity(self):
        """Состояние ДО правки. Находка, видимая и без нового кода, ничего не закрывает."""
        found, _rep = self.collisions_with(
            {"ethena_susde": self.literal(12.0, refused="класс не объявляет поиск")})
        self.assertEqual(found, [], "пара нашлась БЕЗ объявленного тождества")

    def test_the_false_pair_stays_invisible(self):
        """``pendle_pt_susde`` ⊃ ``susde`` по ФОРМЕ ИМЕНИ, но UUID другой.

        Ровно та задача, которую ``alpha_agent`` 17.08 назвал неразрешимой
        синтаксисом: «разделяет только личность пула (UUID)».
        """
        _found, rep = self.collisions_with(
            {"ethena_susde": self.literal(12.0, identity=ETHENA_POOL)})
        for c in rep["collisions"]:
            self.assertNotEqual(sorted(c["keys"]), ["pendle_pt_susde", "susde"])

    def test_message_says_the_literal_key_does_not_RANK_on_that_pool(self):
        """Оговорка обязательна: ``ethena_susde`` пулом ЯВЛЯЕТСЯ, а не ранжируется им."""
        found, _rep = self.collisions_with(
            {"ethena_susde": self.literal(12.0, identity=ETHENA_POOL)})
        self.assertIn("НЕ", found[0]["message"])
        self.assertIn("ОБЪЯВЛЯЕТ", found[0]["message"])

    def test_unfunded_pair_is_WARN_not_CRITICAL(self):
        """Тяжесть держится на книге. В conservative-книге ``ethena_susde`` нет."""
        found, _rep = self.collisions_with(
            {"ethena_susde": self.literal(12.0, identity=ETHENA_POOL)})
        self.assertEqual(found[0]["severity"], pic.WARN)

    def test_funded_pair_is_CRITICAL(self):
        """Обратная сторона той же меры: деньги внутри ⇒ находка тяжелее."""
        rows = self._base_rows()
        rows["ethena_susde"] = self.literal(12.0, identity=ETHENA_POOL)
        self.write(rows, positions={"ethena_susde": 25_087.0})
        rep = self.run_guard()
        found = [c for c in rep["collisions"] if "ethena_susde" in c["keys"]]
        self.assertEqual(found[0]["severity"], pic.CRITICAL)
        self.assertIn("25,087", found[0]["message"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
