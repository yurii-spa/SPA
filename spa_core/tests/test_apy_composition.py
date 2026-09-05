"""Состав ставки адаптера (ADR-230) — сторож `apy_composition`.

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на замер 2026-09-05 (цикл #489): живой
фид DeFiLlama, 17 057 пулов, 23 разрешённых ключа. Единственный ключ, платящий
эмиссией, — `spark_susds`: `apyBase: null`, `apyReward: 4.06595`, poolMeta
"SPK Farming Pool", rewardTokens [SPK]. В тот же день инвест-офис предлагал этот
ключ как возможность 4.0694 % и снял с цели $4 737, а отказ состоялся по
ПОСТОРОННЕЙ причине (`tvl_unverified_policy_gate`). Проверка, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md`), поэтому фикстуры
ниже — те самые записи, а не выдуманный пример.

Второй предмет — тождество, решённое сегодняшним TVL. Замер того же дня разводит
род на порядок: `morpho_blue` 61 соперник при разрыве 0.0145 пп (подмена
победителя не меняет НИЧЕГО) против `euler_v2` 24.0391 пп и `spark_susds`
1.7475 пп. Тест на `morpho_blue` — контроль на ТИШИНУ: сторож, кричащий о
безразличном, учит себя не читать.

Время — ВХОД (`now=`) И отметки фикстур закреплены: обе стороны зафиксированы,
тест не может протухнуть от сдвига календаря.
"""
# FROZEN-DATE-OK: даты фикстур — сам предмет теста (воспроизводится замер
# 2026-09-05, где предметом является возраст снимка относительно потолка 26 ч).
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import apy_composition as ac

#: Отметка живого снимка 05.09 и момент прогона сторожа рядом с ним.
TS = "2026-09-05T07:21:22.922513+00:00"
NOW = dt.datetime(2026, 9, 5, 7, 30, 0, tzinfo=dt.timezone.utc)

#: `spark_susds` ДОСЛОВНО из снимка 05.09 07:21Z — 100 % ставки раздачей SPK.
SPARK = {
    "display_name": "Spark sUSDS", "apy": 4.0659, "live_apy": 4.0659,
    "live_apy_as_of": TS, "live_apy_fresh": True, "fallback_apy": 5.5,
    "tvl_usd": 500000000.0, "tvl_source": "static", "tvl_pool_id": None,
    "pool_match": "hint", "pool_id": "54e9b138-3146-4c1f-8dce-1cb948f5ef96",
    "apy_base": 0.0, "apy_reward": 4.0659, "apy_reward_share": 1.0,
    "apy_composition_unmeasured": None,
    "reward_tokens": ["0xc20059e0317de91738d13af027dfc4a50781b066"],
    "hint_rivals": {"count": 1,
                    "runner_up_pool": "0ed981dc-b49d-426d-ade5-6014728b1ef9",
                    "runner_up_apy": 2.3184, "runner_up_tvl_usd": 260194395.0,
                    "runner_up_pool_meta": None, "apy_spread_pp": 1.7475},
    "pool_match_refused": None, "tier": 1, "chain": "ethereum",
    "per_protocol_cap": 0.4, "active": True, "last_updated": TS,
}

#: `aave_arbitrum` — чистая база, пин, соперников нет. Контроль на тишину.
AAVE_ARB = {
    "display_name": "Aave V3 Arbitrum", "apy": 2.7731, "live_apy": 2.7731,
    "live_apy_as_of": TS, "live_apy_fresh": True, "fallback_apy": 4.1,
    "tvl_usd": 28415259.0, "tvl_source": "live",
    "tvl_pool_id": "d9fa8e14-0447-4207-9ae8-7810199dfa1f", "pool_match": "pinned",
    "pool_id": "d9fa8e14-0447-4207-9ae8-7810199dfa1f",
    "apy_base": 2.7731, "apy_reward": 0.0, "apy_reward_share": 0.0,
    "apy_composition_unmeasured": None, "reward_tokens": None, "hint_rivals": None,
    "pool_match_refused": None, "tier": 1, "chain": "arbitrum",
    "per_protocol_cap": 0.4, "active": True, "last_updated": TS,
}

#: `morpho_blue` — 61 соперник при разрыве 0.0145 пп. Контроль на ТИШИНУ рода.
MORPHO = {
    "display_name": "Morpho Blue", "apy": 4.1019, "live_apy": 4.1019,
    "live_apy_as_of": TS, "live_apy_fresh": True, "fallback_apy": 4.1,
    "tvl_usd": 2000000000.0, "tvl_source": "static", "tvl_pool_id": None,
    "pool_match": "hint", "pool_id": "931ea9be-5f4d-428e-beaf-205fc5b4e2b5",
    "apy_base": 4.1019, "apy_reward": 0.0, "apy_reward_share": 0.0,
    "apy_composition_unmeasured": None, "reward_tokens": None,
    "hint_rivals": {"count": 61,
                    "runner_up_pool": "71b34441-5a46-431b-a9b3-8c081cd0d74c",
                    "runner_up_apy": 4.1164, "runner_up_tvl_usd": 87339609.0,
                    "runner_up_pool_meta": None, "apy_spread_pp": 0.0145},
    "pool_match_refused": None, "tier": 2, "chain": "ethereum",
    "per_protocol_cap": 0.2, "active": True, "last_updated": TS,
}

#: `euler_v2` — 18 соперников при разрыве 24.0391 пп.
EULER = {
    "display_name": "Euler V2", "apy": 3.1795, "live_apy": 3.1795,
    "live_apy_as_of": TS, "live_apy_fresh": True, "fallback_apy": 2.75,
    "tvl_usd": 150000000.0, "tvl_source": "static", "tvl_pool_id": None,
    "pool_match": "hint", "pool_id": "31a0cd94-b781-4e0d-a9f1-1702bc2c238f",
    "apy_base": 3.1795, "apy_reward": 0.0, "apy_reward_share": 0.0,
    "apy_composition_unmeasured": None, "reward_tokens": None,
    "hint_rivals": {"count": 18,
                    "runner_up_pool": "ea1a5fae-2b37-57fa-9477-152a684766c5",
                    "runner_up_apy": 27.2186, "runner_up_tvl_usd": 1242478.0,
                    "runner_up_pool_meta": "EVK Vault eUSDC-132",
                    "apy_spread_pp": 24.0391},
    "pool_match_refused": None, "tier": 2, "chain": "ethereum",
    "per_protocol_cap": 0.2, "active": True, "last_updated": TS,
}

#: `pendle` — литерал реестра, наблюдения этого прогона НЕТ. Не предмет сторожа.
PENDLE = {
    "display_name": "Pendle Finance (PT markets)", "apy": 8.0, "live_apy": None,
    "live_apy_as_of": None, "live_apy_fresh": False, "fallback_apy": 8.0,
    "tvl_usd": 500000000.0, "tvl_source": "static", "tvl_pool_id": None,
    "pool_match": None, "pool_id": None, "apy_base": None, "apy_reward": None,
    "apy_reward_share": None,
    "apy_composition_unmeasured": "пул этого прогона не разрешён — состав ставки измерять не на чем",
    "reward_tokens": None, "hint_rivals": None, "pool_match_refused": None,
    "tier": 2, "chain": "ethereum", "per_protocol_cap": 0.2, "active": True,
    "last_updated": TS,
}


def _doc(adapters: dict, ts: str = TS) -> dict:
    return {"schema_version": 2, "generated_at": ts, "adapters": adapters}


def _kinds(report: dict) -> list[str]:
    return [f"{f['adapter']}/{f['kind']}" for f in report["findings"]]


class TestEmissionDominated(unittest.TestCase):
    """Род «ставка держится на раздаче токена» — замер spark_susds 05.09."""

    def test_spark_susds_named_as_emission_not_yield(self):
        r = ac.measure(_doc({"spark_susds": SPARK}))
        self.assertIn("spark_susds/emission_dominated", _kinds(r))
        f = next(x for x in r["findings"] if x["kind"] == "emission_dominated")
        self.assertEqual(f["reward_share"], 1.0)
        self.assertEqual(f["apy_reward"], 4.0659)
        self.assertEqual(f["apy_base"], 0.0)
        self.assertIn("0xc20059e0317de91738d13af027dfc4a50781b066", f["message"])

    def test_unfunded_key_is_warn_not_critical(self):
        """Ключа в книге нет ⇒ WARN: назвать надо, но денег на нём пока нет."""
        r = ac.measure(_doc({"spark_susds": SPARK}), book={"aave_v3": 5000.0})
        f = next(x for x in r["findings"] if x["kind"] == "emission_dominated")
        self.assertEqual(f["severity"], ac.WARN)
        self.assertEqual(f["usd_held"], 0.0)
        self.assertEqual(ac.exit_code(r | {"counts": r["counts"]}), 1)

    def test_funded_key_is_critical(self):
        """Деньги УЖЕ стоят на числе, которое платится чужим токеном ⇒ CRITICAL."""
        r = ac.measure(_doc({"spark_susds": SPARK}), book={"spark_susds": 4737.0})
        f = next(x for x in r["findings"] if x["kind"] == "emission_dominated")
        self.assertEqual(f["severity"], ac.CRITICAL)
        self.assertEqual(f["usd_held"], 4737.0)
        self.assertEqual(r["overall"], ac.CRITICAL)

    def test_unread_book_does_not_silently_mean_unfunded(self):
        """Книги нет ⇒ находка остаётся, но НЕ повышается, и это СКАЗАНО.

        Молчаливое «книги нет ⇒ считаем ноль» понизило бы CRITICAL до WARN на
        любом хосте, где `data/` отсутствует по построению (worktree).
        """
        r = ac.measure(_doc({"spark_susds": SPARK}), book=None,
                       book_reason="книги нет на диске")
        f = next(x for x in r["findings"] if x["kind"] == "emission_dominated")
        self.assertEqual(f["severity"], ac.WARN)
        self.assertIsNone(f["usd_held"])
        self.assertIn("НЕ ИЗМЕРЕНО", f["message"])
        self.assertEqual(r["book_note"], "книги нет на диске")

    def test_pure_base_yield_says_nothing(self):
        r = ac.measure(_doc({"aave_arbitrum": AAVE_ARB}))
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["overall"], ac.OK)

    def test_threshold_is_the_half_not_the_measured_case(self):
        """Порог ловит и менее крайние случаи, а не подогнан под share == 1.0."""
        half = dict(SPARK, apy_reward_share=0.5, apy_base=2.03, apy_reward=2.03)
        self.assertIn("spark_susds/emission_dominated",
                      _kinds(ac.measure(_doc({"spark_susds": half}))))
        below = dict(SPARK, apy_reward_share=0.49)
        self.assertNotIn("spark_susds/emission_dominated",
                         _kinds(ac.measure(_doc({"spark_susds": below}))))


class TestIdentityByTvlOnly(unittest.TestCase):
    """Род «пул выбран сегодняшним порядком TVL» — мера это РАЗРЫВ, не число."""

    def test_spark_rivals_named(self):
        r = ac.measure(_doc({"spark_susds": SPARK}))
        f = next(x for x in r["findings"] if x["kind"] == "identity_by_tvl_only")
        self.assertEqual(f["apy_spread_pp"], 1.7475)
        self.assertEqual(f["runner_up_pool"], "0ed981dc-b49d-426d-ade5-6014728b1ef9")

    def test_euler_wide_spread_named(self):
        r = ac.measure(_doc({"euler_v2": EULER}))
        f = next(x for x in r["findings"] if x["kind"] == "identity_by_tvl_only")
        self.assertEqual(f["apy_spread_pp"], 24.0391)
        self.assertEqual(f["rivals"], 18)

    def test_sixty_one_rivals_at_a_hundredth_of_a_point_stay_silent(self):
        """61 соперник при 0.0145 пп — НЕ находка: подмена не меняет ничего.

        Это контроль на тишину. Считай мы соперников, а не разрыв, сторож кричал
        бы о `morpho_blue` каждый цикл и научил бы себя не читать.
        """
        r = ac.measure(_doc({"morpho_blue": MORPHO}))
        self.assertEqual(_kinds(r), [])
        self.assertEqual(r["overall"], ac.OK)

    def test_pinned_key_has_no_identity_finding(self):
        r = ac.measure(_doc({"aave_arbitrum": AAVE_ARB}))
        self.assertNotIn("aave_arbitrum/identity_by_tvl_only", _kinds(r))


class TestThirdOutcome(unittest.TestCase):
    """«Не измерено» — самостоятельный исход, а не ноль и не зачёт."""

    def test_observed_key_without_composition_is_unchecked_not_zero(self):
        broken = dict(SPARK, apy_reward_share=None,
                      apy_composition_unmeasured="фид не сообщил ни apyBase, ни apyReward")
        r = ac.measure(_doc({"spark_susds": broken}))
        self.assertEqual(r["overall"], ac.UNCHECKED)
        self.assertEqual(r["counts"]["unchecked"], 1)
        self.assertIn("НЕ ИЗМЕРЕН", r["unchecked"][0])
        self.assertEqual(ac.exit_code(r), 2)

    def test_literal_key_is_not_counted_as_blindness(self):
        """Ключ без наблюдения этого прогона — предмет adapter_feed_divergence.

        Считай мы его слепотой, сторож жил бы в вечном UNCHECKED (13 из 34 ключей
        на 05.09 стоят на литерале) — то есть был бы выключен.
        """
        r = ac.measure(_doc({"pendle": PENDLE, "aave_arbitrum": AAVE_ARB}))
        self.assertEqual(r["unchecked"], [])
        self.assertEqual(r["observed_adapters"], ["aave_arbitrum"])
        self.assertEqual(r["overall"], ac.OK)

    def test_nothing_to_parse_is_not_a_clean_pass(self):
        r = ac.measure(_doc({"pendle": PENDLE}))
        self.assertEqual(r["overall"], ac.UNCHECKED)
        self.assertIn("НЕ чистый зачёт", r["unchecked"][0])

    def test_missing_adapters_section_is_unchecked(self):
        r = ac.measure({"generated_at": TS})
        self.assertEqual(r["overall"], ac.UNCHECKED)
        self.assertEqual(ac.exit_code(r), 2)

    def test_exit_code_without_counts_is_two(self):
        """Отчёта без счётчиков быть не должно ⇒ это не ноль находок, а отказ."""
        self.assertEqual(ac.exit_code({}), 2)
        self.assertEqual(ac.exit_code({"counts": None}), 2)


class TestRunOnDisk(unittest.TestCase):
    """Возраст входа и fail-CLOSED — на настоящем каталоге, с инъекцией часов."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="apycomp_")

    def _write(self, name: str, doc) -> None:
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)

    def test_absent_input_is_unchecked(self):
        r = ac.run(data_dir=self.tmp, now=NOW)
        self.assertEqual(r["overall"], ac.UNCHECKED)
        self.assertEqual(ac.exit_code(r), 2)

    def test_stale_snapshot_refuses_to_judge(self):
        """27 ч при потолке 26 ч: сторож не говорит в настоящем времени о вчера."""
        old = (NOW - dt.timedelta(hours=27)).isoformat()
        self._write("adapter_status.json", _doc({"spark_susds": SPARK}, ts=old))
        r = ac.run(data_dir=self.tmp, now=NOW)
        self.assertEqual(r["overall"], ac.UNCHECKED)
        self.assertIn("stale_input", r["unchecked"][0])

    def test_fresh_snapshot_is_judged(self):
        self._write("adapter_status.json", _doc({"spark_susds": SPARK}))
        r = ac.run(data_dir=self.tmp, now=NOW)
        self.assertEqual(r["overall"], ac.WARN)
        self.assertIn("spark_susds/emission_dominated", _kinds(r))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "apy_composition.json")))

    def test_book_is_read_and_raises_severity(self):
        self._write("adapter_status.json", _doc({"spark_susds": SPARK}))
        self._write("current_positions.json", {"positions": {"spark_susds": 4737.0}})
        r = ac.run(data_dir=self.tmp, now=NOW)
        self.assertEqual(r["overall"], ac.CRITICAL)
        self.assertEqual(ac.exit_code(r), 2)


class TestJournalMemory(unittest.TestCase):
    """Память отвечает «менялся ли победитель» ЧИСЛОМ, а не пересказом."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="apycomp_log_")

    def _run_snapshot(self, entry: dict, ts: str, now: dt.datetime):
        with open(os.path.join(self.tmp, "adapter_status.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(_doc({"spark_susds": entry}, ts=ts), fh, ensure_ascii=False)
        return ac.run(data_dir=self.tmp, now=now)

    def test_same_snapshot_twice_is_one_record(self):
        """Сторожа зовут часто, вход пишет дневной цикл — единица счёта СНИМОК."""
        self._run_snapshot(SPARK, TS, NOW)
        second = self._run_snapshot(SPARK, TS, NOW + dt.timedelta(hours=1))
        self.assertEqual(second["history_appended"], 0)
        self.assertEqual(second["history"]["by_adapter"]["spark_susds"]["snapshots"], 1)

    def test_winner_change_is_counted(self):
        ts2 = (NOW + dt.timedelta(hours=24)).isoformat()
        self._run_snapshot(SPARK, TS, NOW)
        flipped = dict(SPARK, pool_id="0ed981dc-b49d-426d-ade5-6014728b1ef9",
                       apy=2.3184, apy_base=2.3184, apy_reward=0.0,
                       apy_reward_share=0.0)
        r = self._run_snapshot(flipped, ts2, NOW + dt.timedelta(hours=24, minutes=5))
        row = r["history"]["by_adapter"]["spark_susds"]
        self.assertEqual(row["winner_changes"], 1)
        self.assertEqual(row["distinct_pools"], 2)
        self.assertEqual((row["apy_min"], row["apy_max"]), (2.3184, 4.0659))

    def test_history_without_journal_is_unchecked(self):
        h = ac.history(self.tmp, now=NOW)
        self.assertEqual(h["status"], ac.UNCHECKED)
        self.assertIn("памяти", h["reason"])

    def test_window_truncation_is_said_aloud(self):
        """«0 смен за 7 суток» на однодневном журнале — ненаблюдение, не новость."""
        self._run_snapshot(SPARK, TS, NOW)
        h = ac.history(self.tmp, days=7.0, now=NOW)
        self.assertTrue(h["window_truncated"])
        self.assertLess(h["covered_days"], 7.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
