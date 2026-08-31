"""Срез по СЕТИ — не приговор протоколу (решение владельца 31.08, вариант 1).

Авария 30.08, числа из логов и снимка того цикла. Аллокатор просил ethereum на 95 %,
потолок сети 90 % — сработал ADR-136 и срезал ethereum-протоколы. Затем гейт снял
`fluid_fusdc` (TVL не подтверждён), у сети появился запас.

И тут прежнее правило ADR-160 («не возвращать капитал тому, кого потолок только что
срезал») исключило из получателей ЛУЧШИХ на этой сети — `compound_v3` (7.87 %) и
`fluid_usdc`, — потому что их срезал СЕТЕВОЙ потолок. Капитал достался единственному
не исключённому ethereum-адресу: `aave_v3` под 3.26 %, худшему из десяти при медиане
4.93 %. Так и родилось нарушение ECON-10, о котором аудитор писал каждое утро.

Правило ADR-160 верно, пока срез — суждение о САМОМ пуле. Срез по совокупному признаку
говорит «здесь суммарно много», а не «этот протокол плох».

Потолок сети при этом остаётся железным — это проверяет отдельный тест ниже.
"""
import unittest

from spa_core.paper_trading.risk_gate import redistribute_freed_budget

CAP = 100_000.0


def _a(p, tier, apy, chain):
    return {"protocol": p, "tier": tier, "apy_pct": apy, "tvl_source": "live",
            "tvl_usd": 100_000_000.0, "chain": chain}


def _incident_30_08():
    """Книга до хода и цель, которую гейт уже обработал."""
    post = {"compound_v3": 37_894.74, "maple": 18_947.37, "fluid_usdc": 9_473.68}
    pre = dict(post)
    pre["fluid_fusdc"] = 18_947.37            # снят гейтом: TVL не подтверждён
    adapters = [
        _a("compound_v3", "T1", 7.87, "ethereum"),
        _a("maple", "T2", 5.03, "ethereum"),
        _a("fluid_usdc", "T2", 4.93, "ethereum"),
        _a("morpho_blue_base", "T2", 4.45, "base"),
        _a("aave_v3", "T1", 3.26, "ethereum"),   # ХУДШИЙ из набора
    ]
    gate = {"tvl_unverified": ["fluid_fusdc"], "approved": True}
    # сетевой потолок срезал ethereum-протоколы (доли капитала)
    chain_trims = {"compound_v3": 0.02, "maple": 0.01, "fluid_usdc": 0.01}
    return post, pre, adapters, gate, chain_trims


class TestChainTrimIsNotAVerdict(unittest.TestCase):

    def test_the_worst_protocol_no_longer_gets_the_money_by_default(self):
        post, pre, adapters, gate, chain_trims = _incident_30_08()
        r = redistribute_freed_budget(
            post, pre, CAP, adapters, gate,
            allocator_trims_by_protocol=chain_trims,
            chain_trims_by_protocol=chain_trims)
        added = r.get("added") or {}
        self.assertTrue(added, f"ничего не размещено: {r.get('notes')}")
        best = max(added, key=lambda p: added[p])
        self.assertNotEqual(
            best, "aave_v3",
            "основная сумма снова ушла в худший протокол набора (3.26 % при медиане 4.93 %)")
        self.assertIn(
            "compound_v3", added,
            f"самый доходный кандидат по-прежнему исключён сетевым срезом: {sorted(added)}")

    def test_old_behaviour_reproduces_the_incident(self):
        """Контроль посылки: БЕЗ разделения деньги идут в худший."""
        post, pre, adapters, gate, chain_trims = _incident_30_08()
        r = redistribute_freed_budget(
            post, pre, CAP, adapters, gate,
            allocator_trims_by_protocol=chain_trims)   # сетевые НЕ выделены
        added = r.get("added") or {}
        self.assertNotIn(
            "compound_v3", added,
            "фикстура не воспроизводит аварию: лучший кандидат и так не был исключён")
        if added:
            self.assertIn("aave_v3", added,
                          f"ожидался уход капитала в худший протокол, получено: {sorted(added)}")

    def test_a_by_substance_trim_still_blocks(self):
        """Обратный контроль: срез ПО СУЩЕСТВУ по-прежнему лишает получения."""
        post, pre, adapters, gate, chain_trims = _incident_30_08()
        substance = dict(chain_trims)
        substance["compound_v3"] = 0.02      # срезан по существу, а не сетью
        r = redistribute_freed_budget(
            post, pre, CAP, adapters, gate,
            allocator_trims_by_protocol=substance,
            chain_trims_by_protocol={"maple": 0.01, "fluid_usdc": 0.01})
        self.assertNotIn(
            "compound_v3", r.get("added") or {},
            "протокол, срезанный по существу, всё-таки получил капитал — "
            "перераздача отменила слово защиты")

    def test_chain_ceiling_is_still_hard(self):
        """Потолок сети не ослаблен: ethereum не превышает 90 % капитала."""
        post, pre, adapters, gate, chain_trims = _incident_30_08()
        r = redistribute_freed_budget(
            post, pre, CAP, adapters, gate,
            allocator_trims_by_protocol=chain_trims,
            chain_trims_by_protocol=chain_trims)
        eth = {a["protocol"] for a in adapters if a["chain"] == "ethereum"}
        share = sum(v for p, v in r["target_usd"].items() if p in eth) / CAP
        self.assertLessEqual(share, 0.90 + 1e-9,
                             f"сеть ethereum вышла за потолок 90 %: {share:.1%}")


if __name__ == "__main__":
    unittest.main()
