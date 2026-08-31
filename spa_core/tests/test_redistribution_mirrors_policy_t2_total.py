"""Перераздача не имеет собственного потолка — она зеркалит политику (ADR-144).

Замер 31.08, утренний цикл. Гейт срезал сеть ethereum до её потолка 90 %
(`ADR-136: сеть ethereum: 95.00% → 90.00%`), поэтому единственной сетью со
свободой осталась base. Добавка туда упёрлась в суммарный T2 — книга стояла на
**ровно 35.00 %**, то есть на СОБСТВЕННОМ умолчании перераздачи
(`t2_total_cap_pct = 0.35`), при том что `RiskConfig.max_total_t2_allocation`
разрешает **0.50**.

Итог: `$17 368 разместить НЕ УДАЛОСЬ`, 17.4 % капитала простояли под 0 % при живых
кандидатах 4.2–5.2 % годовых.

ADR-144 (решение владельца 26.08) закрыл ровно этот класс — «два источника лимитов
в одной системе не двойная страховка, а гарантированный разъезд» — и назвал ровно
это число 0.35. Тогда зеркало навели у тюнера и ребалансера; сюда оно не дошло.

Граница риска не здесь: после перераздачи цикл ПОВТОРНО прогоняет RiskPolicy и
принимает результат только APPROVED без нарушений (инвариант #1).
"""
import unittest

from spa_core.paper_trading.risk_gate import redistribute_freed_budget

CAP = 100_000.0


def _a(p, tier, apy, chain):
    return {"protocol": p, "tier": tier, "apy_pct": apy, "tvl_source": "live",
            "tvl_usd": 100_000_000.0, "chain": chain}


def _incident_31_08():
    """Книга и снимок утра 31.08 — числа из data/, не выдуманные."""
    book = {"compound_v3": 37_894.74, "maple": 18_947.37, "fluid_usdc": 9_473.68,
            "morpho_blue_base": 6_578.95, "aave_v3": 4_736.84}
    # Гейт срезал СЕТЬ ethereum с 95 % до потолка 90 % (ADR-136), поэтому каждый
    # ethereum-протокол оказался «только что срезан гейтом» и по ADR-160 капитал
    # получать не вправе — перераздача не отменяет слово гейта. Свободной осталась
    # только сеть base. БЕЗ этого условия авария не воспроизводится: проверено —
    # на фикстуре, где ethereum не срезан, деньги уходят в compound_v3/aave_v3 и
    # литерал 35 % ничего не блокирует.
    pre = dict(book)
    for _p in ("compound_v3", "maple", "fluid_usdc", "aave_v3"):
        pre[_p] = book[_p] * 1.06
    pre["fluid_fusdc"] = 18_947.37          # снят гейтом (tvl не подтверждён)
    adapters = [
        _a("compound_v3", "T1", 8.54, "ethereum"),
        _a("fluid_usdc", "T2", 5.24, "ethereum"),
        _a("maple", "T2", 5.03, "ethereum"),
        _a("aave_v3", "T1", 4.98, "ethereum"),
        _a("morpho_blue_base", "T2", 4.45, "base"),
        _a("aave_v3_base", "T2", 3.39, "base"),
    ]
    gate = {"tvl_unverified": ["fluid_fusdc"], "approved": True}
    return book, pre, adapters, gate


class TestRedistributionMirrorsPolicy(unittest.TestCase):

    def _t2_share(self, target, adapters):
        t2 = {a["protocol"] for a in adapters if a["tier"] != "T1"}
        return sum(v for p, v in target.items() if p in t2) / CAP

    def test_base_capacity_above_35pct_is_used(self):
        """Ключ аварии: T2 стоял ровно на 35 % и потому «ёмкости не осталось»."""
        book, pre, adapters, gate = _incident_31_08()
        self.assertAlmostEqual(self._t2_share(book, adapters), 0.35, places=4,
                               msg="фикстура не воспроизводит аварию: T2 не на 35 %")
        r = redistribute_freed_budget(book, pre, CAP, adapters, gate)
        added = r.get("added") or {}
        self.assertTrue(
            added,
            "перераздача снова ничего не разместила — собственный потолок 35 % "
            f"вернулся: {r.get('notes')}")
        # Воспроизведение прода: с литералом 0.35 не размещается НИЧЕГО и остаётся
        # ровно $17 368.42 — то же число, что в логе цикла 31.08.
        blocked = redistribute_freed_budget(book, pre, CAP, adapters, gate,
                                            t2_total_cap_pct=0.35)
        self.assertEqual(blocked.get("added") or {}, {})
        self.assertAlmostEqual(blocked.get("unplaceable_usd"), 17_368.42, places=2)
        self.assertGreater(
            self._t2_share(r["target_usd"], adapters), 0.35,
            "суммарный T2 остался под собственным умолчанием, а не под политикой")

    def test_it_never_exceeds_the_policy_ceiling(self):
        """Обратный контроль: зеркало не смеет пустить выше самой политики."""
        from spa_core.risk.policy import RiskConfig
        ceiling = float(RiskConfig().max_total_t2_allocation)
        book, pre, adapters, gate = _incident_31_08()
        r = redistribute_freed_budget(book, pre, CAP, adapters, gate)
        self.assertLessEqual(
            self._t2_share(r["target_usd"], adapters), ceiling + 1e-9,
            "перераздача вышла за потолок САМОЙ политики — это уже не зеркало")

    def test_an_explicit_cap_still_wins(self):
        """Явно переданный потолок обязан побеждать зеркало: ужесточение возможно."""
        book, pre, adapters, gate = _incident_31_08()
        r = redistribute_freed_budget(book, pre, CAP, adapters, gate,
                                      t2_total_cap_pct=0.35)
        self.assertEqual(
            r.get("added") or {}, {},
            "явный потолок 35 % проигнорирован — параметр перестал работать")


if __name__ == "__main__":
    unittest.main()
