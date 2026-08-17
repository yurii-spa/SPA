"""Один ключ — один инструмент: ``spark_susds`` против ``sky_susds``.

**Дефект.** Адаптер ``spark_susds`` объявляет ``VAULT_ADDRESS = 0xa393…7fbD`` —
это токен sUSDS, сберегательное хранилище Sky. Ровно тот же инструмент уже
закреплён по UUID под ДРУГИМ ключом реестра, ``sky_susds`` (пул d8c4eff5…,
Ethereum / sky-lending / SUSDS). А подсказка ``spark_susds`` = (spark, USDS,
Ethereum) резолвится в **третий** продукт — кредитный рынок SparkLend USDS
(пул 54e9b138…, $543M @ 3.11 %), у которого свои заёмщики, свой риск ликвидации
и своя доходность.

То есть ключ одновременно (а) дублировал инструмент соседа и (б) публиковал как
свой показатель чужого рынка. Оба факта money-path: ``live_apy`` читают
ранжирование, house_view, отчёты и yield-improvement-триггер ADR-060, а кэп на
протокол считает два ключа независимыми позициями и потому не видит удвоенной
экспозиции на один контракт.

**Почему существующие сторожа молчали.** ``_CANONICAL_UNDERLYING``
(``test_feed_hint_asset_identity.py``) сверяет БАЗОВЫЙ АКТИВ — и честно
пропускает подмену: базовый актив кредитного рынка USDS это и есть USDS,
который подсказка объявляет. ``test_no_two_keys_share_a_pool``
(``test_tvl_pinned_provenance.py``) сверяет ПИНЫ — и тоже молчит, потому что
``spark_susds`` не закреплён вовсе. Различает эти два продукта не актив и не
пин, а заявленный ИНСТРУМЕНТ, и его до сих пор нигде не сводили.

**Разрешение — асимметричное, по ADR-064.** Закрепление по UUID это личность
гейт-класса, нечёткая подсказка — нет. Поэтому при споре наблюдение остаётся у
закреплённого ключа, а остальные гаснут с НАЗВАННОЙ причиной; если закреплённых
ноль или больше одного — гаснут все (инвариант 2, fail-CLOSED). Что делать с
самим дублем в реестре — вопрос владельца (состав реестра money-path), карточка
``own-2026-08-17-spark-susds-dublikat.md``.

**Положительный контроль.** ``TestDefectReproduces`` восстанавливает состояние
ДО правки (пустая таблица личностей) и показывает на живых записях фида, что
``spark_susds`` действительно забирал 3.11 % кредитного рынка SparkLend. Без
этого теста проверка ни разу не видела настоящей поломки.

Только FakeFeed, ни один тест не ходит в сеть (``.claude/rules/adapters.md``);
стенные часы на уровне модуля не читаются.
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import adapter_status_generator as gen

_FETCH = "spa_core.monitoring.adapter_status_generator._fetch_defillama"

_SUSDS_TOKEN = "0xa3931d71877c0e7a3148cb7eb4463524fec27fbd"

# ── Записи живого фида (форма дословная, числа округлены) ────────────────────
# Кредитный рынок SparkLend USDS — то, во что резолвилась подсказка spark_susds.
_SPARKLEND_USDS_MARKET = {
    "pool": "54e9b138-3146-4c1f-8dce-1cb948f5ef96",
    "project": "sparklend", "chain": "Ethereum", "symbol": "USDS",
    "tvlUsd": 543_078_478.0, "apy": 3.11143,
    "underlyingTokens": ["0xdC035D45d973E3EC169d2276DDab16f1e407384F"],
}
# Хранилище sUSDS — то, что адаптер spark_susds на самом деле моделирует;
# закреплено под ключом sky_susds.
_SKY_SUSDS_VAULT = {
    "pool": "d8c4eff5-c8a9-46fc-a888-057c4c668e72",
    "project": "sky-lending", "chain": "Ethereum", "symbol": "SUSDS",
    "tvlUsd": 4_750_000_000.0, "apy": 3.52,
    "underlyingTokens": ["0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"],
}

_REGISTRY = {
    "adapters": {
        "spark_susds": {"protocol": "spark_susds", "tier": 1, "fallback_apy": 0.055,
                        "chain": "ethereum", "per_protocol_cap": 0.3, "status": "active"},
        "sky_susds":   {"protocol": "sky_susds", "tier": 1, "fallback_apy": 0.035,
                        "chain": "ethereum", "per_protocol_cap": 0.3, "status": "active"},
    }
}


class _GenBase(unittest.TestCase):
    """``generate()`` против временного реестра — ни сети, ни репозиторного data/."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.registry = self.data_dir / "adapter_registry.json"
        self.output = self.data_dir / "adapter_status.json"
        self.registry.write_text(json.dumps(_REGISTRY), encoding="utf-8")

    def _generate(self, pools):
        with patch(_FETCH, return_value=pools):
            return gen.generate(registry_path=self.registry, output_path=self.output)


class TestDefectReproduces(_GenBase):
    """Положительный контроль: без слоя личности дефект живой и воспроизводимый."""

    def test_without_the_identity_layer_spark_takes_a_foreign_market(self):
        """Пустая таблица личностей = состояние до правки.

        Ключ, моделирующий сберегательное хранилище под 3.52 %, публикует
        3.11 % кредитного рынка — и по всем прочим признакам выглядит исправным:
        подсказка совпала, базовый актив USDS «правильный», отказа нет.
        """
        with patch.object(gen, "_MODELED_INSTRUMENT", {}):
            doc = self._generate([_SPARKLEND_USDS_MARKET, _SKY_SUSDS_VAULT])
        row = doc["adapters"]["spark_susds"]
        self.assertEqual(row["pool_match"], "hint")
        self.assertAlmostEqual(row["live_apy"], 3.1114, places=3)
        self.assertIsNone(row["pool_match_refused"])

    def test_the_foreign_market_is_a_different_product_not_a_variant(self):
        """Разница не косметическая: разные проекты и разные базовые активы."""
        self.assertNotEqual(
            _SPARKLEND_USDS_MARKET["project"], _SKY_SUSDS_VAULT["project"])
        self.assertNotEqual(
            [t.lower() for t in _SPARKLEND_USDS_MARKET["underlyingTokens"]],
            [t.lower() for t in _SKY_SUSDS_VAULT["underlyingTokens"]])


class TestSparkIsRefused(_GenBase):
    """С поставленной таблицей ключ гаснет — и говорит, почему."""

    def test_spark_susds_publishes_no_number(self):
        doc = self._generate([_SPARKLEND_USDS_MARKET, _SKY_SUSDS_VAULT])
        row = doc["adapters"]["spark_susds"]
        self.assertIsNone(row["live_apy"], "число чужого рынка ушло потребителям")
        self.assertIsNone(row["pool_match"])
        self.assertIsNone(row["tvl_pool_id"])
        self.assertEqual(row["tvl_source"], "static")

    def test_the_refusal_is_named_not_silent(self):
        """Пустой ``live_apy`` неотличим от «фид не ответил» — нужна причина."""
        doc = self._generate([_SPARKLEND_USDS_MARKET, _SKY_SUSDS_VAULT])
        reason = doc["adapters"]["spark_susds"]["pool_match_refused"] or ""
        self.assertIn("identity disputed", reason)
        self.assertIn("sky_susds", reason)
        self.assertIn(_SUSDS_TOKEN, reason.lower())

    def test_refusal_holds_even_if_someone_pins_spark_susds(self):
        """Пин не лечит спор личности — иначе обойти проверку тривиально.

        Закрепить ``spark_susds`` на пуле sUSDS означало бы два ключа на одном
        пуле (запрещено ``test_no_two_keys_share_a_pool``), а на любом другом —
        снова чужой продукт. Поэтому спор гасит ключ раньше сопоставления.
        """
        pins = dict(gen._POOL_ID_LOOKUP)
        pins["spark_susds"] = _SPARKLEND_USDS_MARKET["pool"]
        with patch.object(gen, "_POOL_ID_LOOKUP", pins):
            doc = self._generate([_SPARKLEND_USDS_MARKET, _SKY_SUSDS_VAULT])
        row = doc["adapters"]["spark_susds"]
        self.assertIsNone(row["live_apy"])
        self.assertIsNone(row["pool_match"])

    def test_spark_susds_is_not_pinned_today(self):
        """Пин обязан оставаться у одного владельца инструмента."""
        self.assertNotIn("spark_susds", gen._POOL_ID_LOOKUP)
        self.assertEqual(
            gen._POOL_ID_LOOKUP["sky_susds"], _SKY_SUSDS_VAULT["pool"])


class TestNoCollateralDamage(_GenBase):
    """Ужесточение не имеет права глушить честные ключи."""

    def test_sky_susds_keeps_its_pinned_observation(self):
        doc = self._generate([_SPARKLEND_USDS_MARKET, _SKY_SUSDS_VAULT])
        row = doc["adapters"]["sky_susds"]
        self.assertEqual(row["pool_match"], "pinned")
        self.assertAlmostEqual(row["live_apy"], 3.52, places=3)
        self.assertEqual(row["tvl_source"], "live")
        self.assertEqual(row["tvl_pool_id"], _SKY_SUSDS_VAULT["pool"])
        self.assertIsNone(row["pool_match_refused"])

    def test_only_one_key_is_disputed_in_the_shipped_table(self):
        """Спор ровно один — правка не гасит половину реестра заодно."""
        disputed = sorted(
            k for k in gen._MODELED_INSTRUMENT if gen._disputed_identity(k))
        self.assertEqual(disputed, ["spark_susds"])

    def test_same_address_on_three_chains_is_three_instruments(self):
        """Aave V3 Pool имеет ОДИН адрес на Arbitrum / OP / Polygon.

        Сравнение по одному адресу объявило бы три живых ключа дубликатами и
        погасило их все — сеть входит в личность именно поэтому.
        """
        aave = {k: v for k, v in gen._MODELED_INSTRUMENT.items()
                if k in ("aave_arbitrum", "aave_v3_optimism", "aave_v3_polygon")}
        self.assertEqual(len(aave), 3)
        self.assertEqual(len({a for _c, a in aave.values()}), 1)
        for key in aave:
            self.assertIsNone(gen._disputed_identity(key))


class TestCollisionRule(unittest.TestCase):
    """Само правило разрешения спора — обе стороны закреплены."""

    _IDENT = ("ethereum", "0x1111111111111111111111111111111111111111")

    def test_one_pinned_claimant_keeps_the_observation(self):
        table = {"alpha": self._IDENT, "beta": self._IDENT}
        pins = {"alpha": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
        self.assertIsNone(gen._disputed_identity("alpha", table, pins))
        self.assertIn("identity disputed",
                      gen._disputed_identity("beta", table, pins) or "")

    def test_no_pinned_claimant_darkens_everyone(self):
        """Никто не закреплён ⇒ система не знает, чей инструмент, и не гадает."""
        table = {"alpha": self._IDENT, "beta": self._IDENT}
        for key in table:
            reason = gen._disputed_identity(key, table, {})
            self.assertIn("no single key pins it by UUID", reason or "")

    def test_two_pinned_claimants_darken_everyone(self):
        """Два пина на один инструмент — спор, а не разрешение."""
        table = {"alpha": self._IDENT, "beta": self._IDENT}
        pins = {"alpha": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "beta": "ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee"}
        for key in table:
            self.assertIn("fail-CLOSED", gen._disputed_identity(key, table, pins) or "")

    def test_a_lone_key_is_never_disputed(self):
        table = {"alpha": self._IDENT}
        self.assertIsNone(gen._disputed_identity("alpha", table, {}))
        self.assertEqual(gen._instrument_collisions(table), {})

    def test_case_and_chain_are_normalised_before_comparison(self):
        """Фид и адаптеры пишут адреса в разном регистре — сравнение не должно
        зависеть от этого, иначе дубликат «MiXeD vs lower» пройдёт незамеченным."""
        table = {"alpha": ("Ethereum", self._IDENT[1].upper()),
                 "beta": self._IDENT}
        self.assertEqual(len(gen._instrument_collisions(table)), 1)


class TestDeclarationRatchet(unittest.TestCase):
    """Таблица не может отстать от адаптеров — иначе следующий дубль невидим."""

    _ADAPTERS = Path(gen.__file__).resolve().parents[1] / "adapters"

    @staticmethod
    def _module_constants(tree: ast.Module) -> dict[str, str]:
        out: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        out[tgt.id] = node.value.value
        return out

    def _declared_addresses(self) -> dict[str, str]:
        """``PROTOCOL`` → адрес, объявленный в классе адаптера.

        Разбор через ``ast``: константа может быть записана и литералом
        (``VAULT_ADDRESS = "0x…"``), и через модульное имя
        (``POOL_ADDRESS = _POOL_ADDRESS`` у трёх Aave-адаптеров). Регулярка по
        литералу пропустила бы вторую форму — и это ровно тот случай, где ключей
        три, а адрес один.
        """
        found: dict[str, str] = {}
        for path in sorted(self._ADAPTERS.glob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover — не наш предмет
                continue
            consts = self._module_constants(tree)
            for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
                protocol, address = None, None
                for stmt in cls.body:
                    if not isinstance(stmt, ast.Assign):
                        continue
                    names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                    if not names:
                        continue
                    if "PROTOCOL" in names and isinstance(stmt.value, ast.Constant) \
                            and isinstance(stmt.value.value, str):
                        protocol = stmt.value.value
                    if {"VAULT_ADDRESS", "POOL_ADDRESS"} & set(names):
                        if isinstance(stmt.value, ast.Constant) \
                                and isinstance(stmt.value.value, str):
                            address = stmt.value.value
                        elif isinstance(stmt.value, ast.Name):
                            address = consts.get(stmt.value.id)
                if protocol and address and re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
                    found[protocol] = address.lower()
        return found

    def test_the_scan_actually_finds_adapters(self):
        """Пустой скан сделал бы следующий тест тождественно истинным."""
        found = self._declared_addresses()
        self.assertGreaterEqual(len(found), 10, f"скан нашёл лишь {found}")
        self.assertEqual(found.get("spark_susds"), _SUSDS_TOKEN)

    def test_the_scan_resolves_the_indirect_form(self):
        """Три Aave-адаптера пишут ``POOL_ADDRESS = _POOL_ADDRESS``."""
        found = self._declared_addresses()
        for key in ("aave_arbitrum", "aave_v3_optimism", "aave_v3_polygon"):
            self.assertIn(key, found, f"{key}: не разобрана косвенная форма")

    def test_every_adapter_address_is_declared_with_the_same_value(self):
        """Новый адаптер с адресной константой НАСЛЕДУЕТ проверку.

        Opt-in-таблица — форма fail-OPEN: следующий добавленный ключ оказался бы
        молча незащищённым, а именно так и появился нынешний дубль.
        """
        for key, address in self._declared_addresses().items():
            with self.subTest(key=key):
                self.assertIn(
                    key, gen._MODELED_INSTRUMENT,
                    f"{key} объявляет адрес {address}, но не заведён в "
                    f"_MODELED_INSTRUMENT — дубликат такого ключа будет невидим")
                self.assertEqual(gen._MODELED_INSTRUMENT[key][1], address)

    def test_declared_addresses_are_stored_lower_case(self):
        for key, (chain, address) in gen._MODELED_INSTRUMENT.items():
            with self.subTest(key=key):
                self.assertEqual(address, address.lower())
                self.assertEqual(chain, chain.lower())
                self.assertRegex(address, r"^0x[0-9a-f]{40}$")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
