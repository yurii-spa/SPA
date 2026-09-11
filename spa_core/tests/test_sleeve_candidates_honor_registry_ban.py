"""ADR-330: объявленный запрет реестра действует и в кандидатах книг-рукавов.

Замер 11.09: `ondo_usdy` под запретом реестра стоял среди кандидатов Balanced/Aggressive —
запрет исполнял только консервативный аллокатор (ADR-303). Урок ADR-061/303 «одна
проверка на оба пути» до книг-рукавов не дошёл.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.paper_trading import sleeve_book as sb


def _row(name, apy=5.0):
    return {"protocol": name, "tier": "T2", "apy_pct": apy, "apy_source": "live",
            "observed_apy_pct": apy, "tvl_usd": 50_000_000.0, "tvl_source": "live"}


ROWS = [_row("ondo_usdy", 3.57), _row("maple", 4.97), _row("pendle_pt_susde", 4.9)]


class TheBanReachesTheSleeveBooks(unittest.TestCase):
    def test_a_research_only_protocol_is_not_a_candidate(self):
        """СЦЕНА ЗАМЕРА: ondo_usdy под запретом реестра."""
        reg = {"ondo_usdy": {"research_only": True}, "maple": {"research_only": False}}
        names = [c["protocol"] for c in sb._dedup_best(ROWS, registry=reg)]
        self.assertNotIn("ondo_usdy", names)
        self.assertIn("maple", names)

    def test_a_zero_cap_is_a_ban_too(self):
        reg = {"pendle_pt_susde": {"per_protocol_cap": 0.0}}
        names = [c["protocol"] for c in sb._dedup_best(ROWS, registry=reg)]
        self.assertNotIn("pendle_pt_susde", names)

    def test_a_protocol_without_a_registry_entry_is_not_banned(self):
        """Отсутствие объявления не есть запрет — иначе новый адаптер забанен по построению."""
        names = [c["protocol"] for c in sb._dedup_best(ROWS, registry={})]
        self.assertEqual(sorted(names), ["maple", "ondo_usdy", "pendle_pt_susde"])

    def test_an_unreadable_registry_names_itself_and_bans_nothing(self):
        with TemporaryDirectory() as td:
            reg, why = sb.load_registry_declarations(Path(td) / "нет.json")
        self.assertEqual(reg, {})
        self.assertIn("не прочитан", why)

    def test_the_rule_is_the_allocators_function_not_a_copy(self):
        """Второе определение запрета однажды разошлось бы с первым молча."""
        import inspect
        src = inspect.getsource(sb._dedup_best)
        self.assertIn("from spa_core.allocator.allocator import declared_ban", src)
        self.assertNotIn('"registry_research_only"', src, "правило скопировано в sleeve_book")


if __name__ == "__main__":
    unittest.main()
