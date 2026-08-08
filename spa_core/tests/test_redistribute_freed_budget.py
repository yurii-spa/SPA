"""Тесты ADR-072: срезанный гейтом бюджет не выбрасывается (мандат владельца 07.08).

Positive control — инцидент 2026-08-07: гейт срезал maple 20→10% и morpho 20→5%,
освобождённые ~20% капитала лежали в кэше под 0%, пока compound_v3 (T1, 3.3%,
live TVL) стоял с нулём. Обе стороны каждой границы:

  * срезанные/замороженные гейтом пулы НЕ дофинансируются (слово гейта свято);
  * кандидат без live-TVL или без положительного конечного APY — не кандидат
    (литерал ≠ наблюдение, ADR-061/063);
  * буфер min-cash неприкосновенен; потолки T1/T2/T2-total соблюдены;
  * ALLOC-002: новых имён сверх max_protocols не открываем;
  * мелочь (<0.5% капитала) не гоняем; мусорный вход не роняет цикл.
"""
from __future__ import annotations

import unittest

from spa_core.paper_trading.risk_gate import redistribute_freed_budget

CAP = 100_000.0


def adapter(p, tier="T1", apy=3.3, tvl_source="live"):
    return {"protocol": p, "tier": tier, "apy_pct": apy, "tvl_source": tvl_source,
            "tvl_usd": 50_000_000.0}


def incident():
    """Сегодняшний прод: оптимизатор просил 95%, гейт срезал до 75%."""
    pre = {"aave_v3": 40_000.0, "pendle": 15_000.0, "maple": 20_000.0,
           "morpho_steakhouse": 20_000.0}
    post = {"aave_v3": 40_000.0, "pendle": 15_000.0, "maple": 10_000.0,
            "morpho_steakhouse": 5_000.0}
    adapters = [adapter("aave_v3", "T1", 5.01), adapter("compound_v3", "T1", 3.30),
                adapter("yearn_v3", "T2", 3.27), adapter("euler_v2", "T2", 3.06),
                adapter("maple", "T2", 4.91), adapter("morpho_steakhouse", "T1", 3.40),
                adapter("pendle", "T2", 15.49)]
    gate = {"tvl_unverified": [], "approved": True}
    return pre, post, adapters, gate


class PositiveControl(unittest.TestCase):
    def test_freed_budget_goes_to_live_positive_candidates(self):
        pre, post, adapters, gate = incident()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        # ИЗМЕНЕНО ОСОЗНАННО 2026-08-08 (инв. 16, журнал W32): было 25k «всё
        # срезанное». Замер на проде показал, что гейт отвергает такую
        # перераздачу целиком («Chain concentration on ethereum 91% > 90%»),
        # т.е. прежнее ожидание описывало ЗАВЕДОМО ОТВЕРГАЕМОЕ предложение.
        # Проверка УСИЛЕНА: срезано по-прежнему 25k (freed_usd), но предлагается
        # ровно то, что лимит цепочки ПРОПУСТИТ: 90% × 100k − 70k(ethereum) = 20k.
        self.assertAlmostEqual(r["freed_usd"], 25_000.0, delta=1.0)
        self.assertAlmostEqual(sum(r["added"].values()), 20_000.0, delta=1.0)
        self.assertIn("compound_v3", r["added"])          # T1 3.3% > кэш 0%
        self.assertNotIn("maple", r["added"])             # срезан гейтом
        self.assertNotIn("morpho_steakhouse", r["added"])  # срезан гейтом
        self.assertLessEqual(sum(r["target_usd"].values()), CAP * 0.95 + 1e-6)
        self.assertTrue(all("ADR-072" in n for n in r["notes"]))  # именовано

    def test_chain_limit_caps_the_offer(self):
        """Лимит одной цепочки (90% капитала) режет предложение ДО гейта —
        иначе гейт отвергал бы перераздачу целиком (замер 08.08)."""
        pre, post, adapters, gate = incident()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        eth_after = sum(v for p, v in r["target_usd"].items())  # все на ethereum
        self.assertLessEqual(eth_after, CAP * 0.90 + 1e-6)
        # с более щедрым лимитом цепочки предложение больше — проверка живая
        r2 = redistribute_freed_budget(post, pre, CAP, adapters, gate,
                                       max_single_chain_pct=0.99)
        self.assertGreater(sum(r2["added"].values()), sum(r["added"].values()))

    def test_cap_bound_is_named_not_silent(self):
        """Размещать некуда ⇒ честное имя, а не молчание (ADR-055)."""
        pre = {"aave_v3": 40_000.0, "x": 55_000.0}
        post = {"aave_v3": 40_000.0}          # гейт срезал x целиком
        gate = {"tvl_unverified": ["x"], "approved": True}
        r = redistribute_freed_budget(post, pre, CAP, [adapter("x", "T1", 5.0)],
                                      gate)
        self.assertEqual(r["added"], {})
        self.assertTrue(r.get("cap_bound"))
        self.assertTrue(any("НЕКУДА" in n for n in r["notes"]))

    def test_gate_frozen_pool_never_refilled(self):
        pre, post, adapters, gate = incident()
        gate = dict(gate, tvl_unverified=["compound_v3"])
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertNotIn("compound_v3", r["added"])

    def test_non_live_tvl_and_bad_apy_are_not_candidates(self):
        pre, post, _, gate = incident()
        adapters = [adapter("static_pool", "T1", 9.9, tvl_source="static"),
                    adapter("none_apy", "T1", None),
                    adapter("zero_apy", "T1", 0.0),
                    adapter("nan_apy", "T1", float("nan"))]
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertEqual(r["added"], {})

    def test_min_cash_buffer_untouchable(self):
        pre, post, adapters, gate = incident()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate,
                                      min_cash_pct=0.25)
        self.assertLessEqual(sum(r["target_usd"].values()), CAP * 0.75 + 1e-6)

    def test_tier_caps_and_t2_total_respected(self):
        pre = {"aave_v3": 40_000.0}
        post = {"aave_v3": 20_000.0}  # гейт срезал aave на 20k — ровно они и перераздаются
        adapters = [adapter("t2a", "T2", 9.0), adapter("t2b", "T2", 8.0),
                    adapter("t2c", "T2", 7.0), adapter("aave_v3", "T1", 5.0)]
        gate = {"tvl_unverified": [], "approved": True}
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        t = r["target_usd"]
        self.assertNotIn("aave_v3", r["added"])  # срезан — не дофинансируем
        for p in ("t2a", "t2b", "t2c"):
            self.assertLessEqual(t.get(p, 0.0), CAP * 0.20 + 1e-6)
        t2_sum = t.get("t2a", 0) + t.get("t2b", 0) + t.get("t2c", 0)
        self.assertLessEqual(t2_sum, CAP * 0.35 + 1e-6)

    def test_alloc002_no_new_names_beyond_limit(self):
        pre = {f"h{i}": 9_000.0 for i in range(8)}   # 8 держимых (лимит)
        post = {f"h{i}": 8_000.0 for i in range(8)}  # гейт срезал всех по чуть
        adapters = ([adapter(f"h{i}", "T2", 4.0) for i in range(8)]
                    + [adapter("newcomer", "T1", 6.0)])
        gate = {"tvl_unverified": [], "approved": True}
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertNotIn("newcomer", r["added"])  # 9-е имя не открываем

    def test_model_underdeployment_is_not_our_business(self):
        """Аллокатор сам решил маленькую книгу (гейт ничего не резал) —
        перераздача НЕ трогает: спасаем срезанное, не отменяем модель."""
        small = {"aave_v3": 30_000.0}
        r = redistribute_freed_budget(small, dict(small), CAP,
                                      [adapter("compound_v3", "T1", 3.3)],
                                      {"tvl_unverified": []})
        self.assertEqual(r["added"], {})
        self.assertEqual(r["freed_usd"], 0.0)

    def test_tiny_freed_is_left_alone(self):
        pre = {"aave_v3": 40_000.0}
        post = {"aave_v3": 39_800.0}  # свободно $200 < 0.5% капитала... но 95k-39.8k
        # честный кейс: почти всё развёрнуто
        post_full = {"aave_v3": 40_000.0, "p": 54_800.0}
        r = redistribute_freed_budget(post_full, post_full, CAP,
                                      [adapter("x", "T1", 5.0)],
                                      {"tvl_unverified": []})
        self.assertEqual(r["added"], {})

    def test_garbage_never_raises(self):
        r = redistribute_freed_budget({}, {}, float("nan"), None,
                                      {"tvl_unverified": None})
        self.assertEqual(r["added"], {})
        r2 = redistribute_freed_budget({"a": "мусор"}, {}, CAP,
                                       [{"broken": True}, None], {})
        self.assertIsInstance(r2["target_usd"], dict)


if __name__ == "__main__":
    unittest.main()


# ═══════════════════════════════════════════════════════════════════════════
# ADR-073 · 2026-08-08, решение владельца (вариант 1 карточки
# `owner-decision-posle-strahovki-dengi-ostayutsya-sirotam`).
#
# Дополняет ADR-072.1 (лимит одной цепочки), приземлённый параллельной сессией
# в тот же день: суммарный L2, потолки из RiskConfig, ЧАСТИЧНЫЙ неразмещённый
# остаток, учёт тиров у заблокированных пулов и приёмка через настоящий гейт.
# ═══════════════════════════════════════════════════════════════════════════

class ChainLimitsFullSet(unittest.TestCase):

    def test_partial_unplaceable_remainder_is_named(self):
        """cap_bound ловит только «не разместили НИЧЕГО».

        Сегодняшний случай другой и он же самый частый: $20 000 ушли,
        $5 000 остались. Без этой проверки частичный остаток тонул молча —
        ровно то, что ADR-055 запрещает.
        """
        pre, post, adapters, gate = incident()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertTrue(r["added"], "часть обязана разместиться")
        self.assertAlmostEqual(r["unplaceable_usd"], 5_000.0, delta=1.0)
        self.assertTrue(any("разместить НЕ УДАЛОСЬ" in n for n in r["notes"]))

    def test_l2_total_cap_is_respected(self):
        """Суммарный L2 ≤ 50 % — второй потолок сети, который проверит гейт."""
        pre = {"aave_v3": 40_000.0, "maple": 55_000.0}
        post = {"aave_v3": 40_000.0, "maple": 0.0}
        adapters = [
            adapter("aave_v3", "T1", 5.01),
            {"protocol": "moonwell_base", "tier": "T2", "apy_pct": 9.9,
             "tvl_source": "live", "tvl_usd": 5e7, "chain": "base"},
            {"protocol": "silo_arbitrum", "tier": "T2", "apy_pct": 9.8,
             "tvl_source": "live", "tvl_usd": 5e7, "chain": "arbitrum"},
        ]
        gate = {"tvl_unverified": [], "approved": True}
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        l2 = sum(v for p, v in r["target_usd"].items()
                 if p in {"moonwell_base", "silo_arbitrum"})
        self.assertLessEqual(l2, CAP * 0.50 + 1.0)

    def test_blocked_pool_tier_is_not_defaulted_to_t2(self):
        """T1-позиция, срезанная гейтом, не смеет съедать суммарный лимит T2.

        Карты тира строились только по НЕзаблокированным адаптерам, поэтому
        ``tier_of.get(p, "T2")`` записывал morpho_steakhouse (T1, $5 000) в
        лимит T2 — и живой base-кандидат в освободившееся место не проходил.
        """
        pre, post, adapters, gate = incident()
        adapters = adapters + [
            {"protocol": "moonwell_base", "tier": "T2", "apy_pct": 6.6,
             "tvl_source": "live", "tvl_usd": 5e7, "chain": "base"},
        ]
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertIn("moonwell_base", r["added"])
        self.assertAlmostEqual(sum(r["added"].values()), 25_000.0, delta=1.0)
        self.assertEqual(r.get("unplaceable_usd", 0.0), 0.0)

    def test_caps_come_from_riskconfig_not_from_local_literals(self):
        """Потолок берётся из RiskConfig — иначе он однажды разъедется с гейтом."""
        from spa_core.risk.policy import RiskConfig

        cfg = RiskConfig()
        pre, post, adapters, gate = incident()
        auto = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        pinned = redistribute_freed_budget(
            post, pre, CAP, adapters, gate,
            max_single_chain_pct=float(cfg.max_single_chain_allocation),
            max_l2_total_pct=float(cfg.max_l2_total_allocation),
        )
        self.assertEqual(auto["added"], pinned["added"])

    def test_unknown_chain_counts_as_ethereum_not_a_free_bucket(self):
        """Fail-CLOSED: отсутствие поля chain не открывает обход лимита сети."""
        pre, post, adapters, gate = incident()
        adapters = adapters + [
            {"protocol": "protocol_bez_seti", "tier": "T2", "apy_pct": 99.0,
             "tvl_source": "live", "tvl_usd": 5e7},  # поля chain НЕТ
        ]
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertAlmostEqual(sum(r["added"].values()), 20_000.0, delta=1.0)


class SurvivesTheRealGate(unittest.TestCase):
    """Приёмка, которой не было: цель обязана ПРОЙТИ настоящий гейт.

    Прежние тесты проверяли, ЧТО ФУНКЦИЯ ВЕРНУЛА. Но в проде она возвращала
    прекрасную раскладку, которую гейт отвергал ЦЕЛИКОМ, — и все тесты
    оставались зелёными, пока деньги лежали в кэше. Класс «проверяй проводку,
    а не части» (цикл #144).
    """

    @staticmethod
    def _incident_with_chains():
        """Та же авария, но у адаптеров ЕСТЬ поле chain — как в проде.

        Без него гейт кладёт каждый протокол в собственную корзину
        ``unknown:<pool>``, лимит одной сети не срабатывает НИ НА ЧЁМ, и
        приёмка зеленеет даже на сломанном коде. Замерено: первая версия
        этого теста была именно такой и пропускала аварию.
        """
        pre, post, adapters, gate = incident()
        return pre, post, [dict(a, chain="ethereum") for a in adapters], gate

    def test_gate_really_rejects_a_chain_heavy_target(self):
        """Сначала докажем, что стенд ВООБЩЕ способен поймать нарушение."""
        from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate

        _pre, _post, adapters, _gate = self._incident_with_chains()
        chain_heavy = {"aave_v3": 40_000.0, "pendle": 20_000.0, "maple": 10_000.0,
                       "morpho_steakhouse": 5_000.0, "compound_v3": 20_000.0}
        g = _apply_risk_policy_gate(chain_heavy, CAP, adapters)
        self.assertTrue(
            [v for v in (g.get("violations") or []) if "Chain concentration" in v],
            "стенд не ловит нарушение лимита сети — тест ниже был бы пустышкой",
        )

    def test_redistributed_target_is_approved_by_the_gate(self):
        """Положительный контроль настоящей аварии прода 2026-08-08 09:50 UTC.

        На версии до починки краснеет сообщением БАЙТ-В-БАЙТ тем же, что
        записал прод: «Chain concentration on ethereum after trade 95.0%
        exceeds single-chain limit 90.0%».
        """
        from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate

        pre, post, adapters, gate = self._incident_with_chains()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertTrue(r["added"], "перераздача обязана что-то разместить")

        g2 = _apply_risk_policy_gate(r["target_usd"], CAP, adapters)
        chain_violations = [v for v in (g2.get("violations") or [])
                            if "Chain concentration" in v]
        self.assertEqual(
            chain_violations, [],
            f"снова предлагается непроходная по сети цель: {chain_violations}")
        self.assertTrue(g2.get("approved"), f"гейт не принял: {g2.get('violations')}")
