"""ADR-070 пп.17–18 — храповик исполнения решения владельца (2026-08-07).

Решение владельца, дословно:

    17. `frax`: дубль удалить из реестра (единственный инструмент закреплён за `sfrax`).
    18. `notional_v3`: признать неподдерживаемым (не ERC-4626) и вывести до отдельного разбора.

«Удалить» и «вывести» — РАЗНЫЕ действия, и файл держит их порознь:

* **удалить** (`frax`) — ключа нет в каноническом ``spa_core.adapters.ADAPTER_REGISTRY``,
  класс не экспортируется, статической TVL-константы не осталось;
* **вывести** (`notional_v3`) — запись ОСТАЁТСЯ видимой в
  ``spa_core.adapters.registry.ADAPTER_METADATA`` (иначе причина исчезнет вместе с
  ключом), но помечена ``withdrawn`` с ADR и причиной, не инстанцируется и не
  попадает в ``list_eligible()``.

ПОЧЕМУ ХРАПОВИК, А НЕ ОДНА ПРАВКА. Ключ в реестре — это состав набора
рассматриваемых протоколов, то есть money-path. Правка без сторожа откатывается
следующим, кто «вернёт как было»: у обоих ключей на диске лежат живые модули
(``frax_adapter.py``, ``notional_v3_adapter.py``), и одна строка возвращает их в
оборот.

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (правило `.claude/rules/deployment.md`): у проверки два
края, и каждый обязан краснеть на мутацию —

* ``TestRemovedKeyStaysOut`` краснеет, если удалённый ключ ВЕРНЁТСЯ;
* ``TestNeighboursSurvived`` краснеет, если удаление ЗАДЕЛО СОСЕДА
  (`sfrax`, `fluid_usdc`, `fluid_usdt` и остальной канон).

Оба края проверены на себе в ``TestTheRatchetItselfBites``: тесты гоняются на
подменённых наборах, воспроизводящих обе аварии, и там они обязаны падать.

Только stdlib.
"""
from __future__ import annotations

import unittest

from spa_core.adapters import ADAPTER_REGISTRY
from spa_core.adapters.registry import (
    ADAPTER_METADATA,
    WithdrawnAdapterError,
    get_adapter,
    is_withdrawn,
    list_eligible,
    list_withdrawn,
)

# Ключи из решения владельца.
_DELETED = "frax"        # ADR-070 п.17 — удалить
_WITHDRAWN = "notional_v3"  # ADR-070 п.18 — вывести


def _registry_keys(registry=None) -> list[str]:
    """Канон — список кортежей ``(ключ, тир, класс)``; берём первый элемент.

    Авария #206 случилась ровно на том, что кто-то прочитал этот список как
    dict и получил буквы имён вместо ключей — поэтому распаковка явная.
    """
    reg = ADAPTER_REGISTRY if registry is None else registry
    return [entry[0] for entry in reg]


class TestRemovedKeyStaysOut(unittest.TestCase):
    """Край 1: удалённый ключ не появляется в кандидатах. Краснеет на возврат."""

    def test_frax_is_absent_from_the_canonical_registry(self):
        self.assertNotIn(
            _DELETED, _registry_keys(),
            "ADR-070 п.17: ключ `frax` удалён из ADAPTER_REGISTRY. Возврат — "
            "только новым ADR: у него нет собственного пула в фиде, а SFRAX уже "
            "занят ключом `sfrax` (два ключа на один пул = скрытая концентрация).")

    def test_frax_is_not_re_exported_by_the_package(self):
        import spa_core.adapters as pkg
        self.assertFalse(
            hasattr(pkg, "FraxAdapter"),
            "класс FraxAdapter снова экспортируется пакетом — ключ вернётся следом")
        self.assertNotIn("FraxAdapter", pkg.__all__)

    def test_no_static_tvl_constant_survives_for_frax(self):
        """Литерал $100M ВЫШЕ порога $5M — он прошёл бы floor тавтологически.

        ADR-053: «live» ставится на наблюдение, никогда на константу. У снятого
        ключа константы быть не должно вовсе.
        """
        from spa_core.monitoring import adapter_status_generator as gen
        self.assertNotIn(_DELETED, gen._TVL_ESTIMATES)

    def test_frax_is_not_in_the_metadata_set_either(self):
        """Сосед-набор мог бы стать чёрным ходом для того же ключа."""
        self.assertNotIn(_DELETED, ADAPTER_METADATA)


class TestWithdrawnKeyIsNamedNotDeleted(unittest.TestCase):
    """`notional_v3` ВЫВЕДЕН — это другое действие, и оно отличимо."""

    def test_the_entry_is_still_visible(self):
        self.assertIn(
            _WITHDRAWN, ADAPTER_METADATA,
            "«вывести» ≠ «удалить»: запись остаётся, иначе причина вывода "
            "исчезает вместе с ключом")

    def test_the_withdrawal_is_marked_with_adr_and_reason(self):
        meta = ADAPTER_METADATA[_WITHDRAWN]
        self.assertIs(meta.get("withdrawn"), True)
        self.assertIn("ADR-070", str(meta.get("withdrawn_adr", "")))
        self.assertTrue(str(meta.get("withdrawn_reason", "")).strip(),
                        "вывод без записанной причины — это молчаливое удаление")

    def test_it_is_not_eligible(self):
        self.assertTrue(is_withdrawn(_WITHDRAWN))
        self.assertIn(_WITHDRAWN, list_withdrawn())
        self.assertNotIn(_WITHDRAWN, list_eligible())

    def test_instantiating_it_refuses_by_name(self):
        """Fail-CLOSED и ИМЕНОВАННО: «нет ключа» и «выведен» — разные факты."""
        with self.assertRaises(WithdrawnAdapterError) as ctx:
            get_adapter(_WITHDRAWN)
        self.assertIn("ADR-070", str(ctx.exception))

    def test_a_missing_key_still_raises_the_other_error(self):
        with self.assertRaises(KeyError):
            get_adapter("no_such_adapter_key_at_all")

    def test_no_static_tvl_constant_survives_for_notional(self):
        from spa_core.monitoring import adapter_status_generator as gen
        self.assertNotIn(_WITHDRAWN, gen._TVL_ESTIMATES)

    def test_withdrawal_did_not_leak_into_the_canonical_registry(self):
        self.assertNotIn(_WITHDRAWN, _registry_keys())


class TestNeighboursSurvived(unittest.TestCase):
    """Край 2: удаление не задело соседей. Краснеет, если задело."""

    #: Ключи, которые ОБЯЗАНЫ остаться в каноне. `sfrax` — тот самый инструмент,
    #: ради которого дубль и снимали; остальные — представители соседних классов
    #: (T1-якорь, L2, T3), чтобы «случайно вырезали блок» стало видно.
    _MUST_STAY = ("sfrax", "aave_v3", "spark_susds", "sdai", "scrvusd",
                  "stusd", "wusdm", "susde", "pendle", "maple")

    def test_the_neighbours_are_all_still_registered(self):
        keys = set(_registry_keys())
        missing = [k for k in self._MUST_STAY if k not in keys]
        self.assertEqual(missing, [], f"удаление задело соседей: {missing}")

    def test_sfrax_keeps_its_own_pool_pin(self):
        """Инструмент, за которым закреплён SFRAX-пул, не должен был пострадать."""
        from spa_core.monitoring import adapter_status_generator as gen
        self.assertIn("sfrax", gen._POOL_ID_LOOKUP)

    def test_metadata_neighbours_of_the_withdrawn_key_are_untouched(self):
        for key in ("fluid_usdc", "fluid_usdt"):
            with self.subTest(adapter=key):
                self.assertIn(key, ADAPTER_METADATA)
                self.assertFalse(is_withdrawn(key),
                                 f"{key} выведен заодно — этого решения не было")

    def test_only_the_decided_key_is_withdrawn(self):
        self.assertEqual(sorted(list_withdrawn()), [_WITHDRAWN])

    def test_the_canonical_registry_did_not_collapse(self):
        """Пустой/куцый реестр сделал бы оба края тождественно истинными."""
        self.assertGreaterEqual(len(ADAPTER_REGISTRY), 30)

    def test_keys_are_unique(self):
        keys = _registry_keys()
        self.assertEqual(len(keys), len(set(keys)), "дубль ключа в реестре")


class TestTheRatchetItselfBites(unittest.TestCase):
    """Проверка сторожа: воспроизводим обе аварии — обе обязаны краснеть.

    Проверка, никогда не видевшая настоящей поломки, — украшение
    (`.claude/rules/deployment.md`).
    """

    def test_a_returned_frax_key_would_be_caught(self):
        mutated = list(ADAPTER_REGISTRY) + [("frax", "T2", object)]
        self.assertIn("frax", _registry_keys(mutated))  # авария воспроизведена
        with self.assertRaises(AssertionError):
            self.assertNotIn("frax", _registry_keys(mutated), "sentinel")

    def test_a_dropped_neighbour_would_be_caught(self):
        mutated = [e for e in ADAPTER_REGISTRY if e[0] != "sfrax"]
        keys = set(_registry_keys(mutated))
        missing = [k for k in TestNeighboursSurvived._MUST_STAY if k not in keys]
        self.assertEqual(missing, ["sfrax"])  # авария воспроизведена
        with self.assertRaises(AssertionError):
            self.assertEqual(missing, [], "sentinel")

    def test_an_unmarked_withdrawal_would_be_caught(self):
        """Если бы `notional_v3` просто вычеркнули, край «вывести» покраснел бы."""
        stripped = {k: v for k, v in ADAPTER_METADATA.items() if k != _WITHDRAWN}
        with self.assertRaises(AssertionError):
            self.assertIn(_WITHDRAWN, stripped, "sentinel")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
