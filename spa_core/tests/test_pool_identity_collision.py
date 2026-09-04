"""Сторож тождества пулов: каждый тест — воспроизведение ИЗМЕРЕННОГО состояния.

Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`). Обе коллизии ниже сверены с ЖИВЫМ фидом
DeFiLlama 2026-09-04, и числа в фикстурах — наблюдения того дня, а не выдумка:

* ``fluid_usdc`` + ``fluid_fusdc`` → пул ``4438dabc-…`` (Ethereum/fluid-lending/USDC).
  В `fluid-lending`/Ethereum/USDC живут ЧЕТЫРЕ пула ($150.1M, $4.0M, $336k, $12k);
  «best TVL wins» отдаёт первый — ровно тот, что запинен за ``fluid_fusdc``.
  В книге в тот день: ``fluid_usdc`` $20 000.
* ``morpho_blue`` + ``morpho_steakhouse`` → пул ``931ea9be-…`` (STEAKUSDC).
  ``MorphoBlueAdapter`` ищет символ в режиме "contains" и берёт лучший по TVL
  USDC-волт: STEAKUSDC $94.67M против GTUSDCP $88.72M — разрыв 6.7 %, то есть
  завтра победитель может смениться, и НИ ОДИН артефакт этого не запишет.

Время — ВХОД (``now=``), отметки относительные: обе стороны закреплены, тест не
может протухнуть от движения календаря.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import pool_identity_collision as pic
from spa_core.tests._freshness import now_utc, ts

# Наблюдения 2026-09-04, сверенные с живым фидом.
_FLUID_POOL = "4438dabc-7f0c-430b-8136-2722711ae663"
_FLUID_TVL, _FLUID_APY = 151_093_142.0, 4.47
_STEAK_POOL = "931ea9be-5f4d-428e-beaf-205fc5b4e2b5"
_STEAK_TVL, _STEAK_APY = 94_831_801.0, 4.1934


def _orch_row(protocol, apy, tvl, **kw):
    row = {"protocol": protocol, "apy_pct": apy, "tvl_usd": tvl, "status": "ok",
           "live_data": True, "tvl_source": "live", "tier": "T2"}
    row.update(kw)
    return row


def _status_row(apy, tvl, pool_id=None, tvl_source="live"):
    return {"live_apy": apy, "tvl_usd": tvl, "tvl_source": tvl_source,
            "tvl_pool_id": pool_id, "apy": apy}


class _Base(unittest.TestCase):
    """Каждый тест пишет свой каталог данных — живое ``data/`` не задействовано."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, orch_rows, status_rows, registry=None, positions=None,
              orch_age=1.0, status_age=1.0, book_age=1.0):
        (self.dir / "adapter_orchestrator_status.json").write_text(json.dumps(
            {"generated_at": ts(orch_age), "adapters": orch_rows}), encoding="utf-8")
        (self.dir / "adapter_status.json").write_text(json.dumps(
            {"generated_at": ts(status_age), "adapters": status_rows}), encoding="utf-8")
        (self.dir / "adapter_registry.json").write_text(json.dumps(
            {"adapters": registry or {}}), encoding="utf-8")
        if positions is not None:
            (self.dir / "current_positions.json").write_text(json.dumps(
                {"generated_at": ts(book_age), "positions": positions}), encoding="utf-8")

    def run_guard(self, **kw):
        return pic.run(root=str(self.dir), data_dir=str(self.dir), write=False,
                       now=now_utc(), **kw)

    def kinds(self, report, kind):
        return [f for f in report["findings"] if f["kind"] == kind]


class TestObservedCollision(_Base):
    """Род ``observed`` — то, чего существующий тест пинов не видит ПО ПОСТРОЕНИЮ."""

    def test_fluid_pair_funded_is_critical(self):
        """Авария 2026-09-04: два ключа, один пул, $20 000 книги внутри.

        Пара живёт в РАЗНЫХ артефактах (fluid_usdc только у оркестратора,
        fluid_fusdc только в adapter_status) — сторож, читающий один файл, её
        не увидит.
        """
        self.write(
            [_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL),
             _orch_row("maple", 5.0322, 2_736_934_669.0)],
            {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)},
            positions={"fluid_usdc": 20_000.0},
        )
        r = self.run_guard()
        cols = self.kinds(r, "pool_collision")
        self.assertEqual(len(cols), 1, r["findings"])
        self.assertEqual(cols[0]["severity"], pic.CRITICAL)
        self.assertEqual(sorted(cols[0]["keys"]), ["fluid_fusdc", "fluid_usdc"])
        self.assertEqual(r["collisions"][0]["funded_total_usd"], 20_000.0)
        self.assertEqual(r["collisions"][0]["pool_id"], _FLUID_POOL)
        self.assertEqual(pic.exit_code(r), 2)

    def test_morpho_pair_unfunded_is_warn_not_silence(self):
        """Ноль в книге не означает «не подвержены»: оба ключа активны и T2 по 20 %."""
        self.write(
            [_orch_row("morpho_blue", _STEAK_APY, _STEAK_TVL),
             _orch_row("morpho_steakhouse", _STEAK_APY, _STEAK_TVL)],
            {"morpho_steakhouse": _status_row(_STEAK_APY, _STEAK_TVL, _STEAK_POOL)},
            positions={"compound_v3": 40_000.0},
        )
        r = self.run_guard()
        cols = self.kinds(r, "pool_collision")
        self.assertEqual(len(cols), 1, r["findings"])
        self.assertEqual(cols[0]["severity"], pic.WARN)
        self.assertEqual(r["collisions"][0]["funded_total_usd"], 0.0)
        self.assertEqual(pic.exit_code(r), 1)

    def test_distinct_pools_do_not_collide(self):
        """Контроль на ЛОЖНОЕ срабатывание: разные пулы обязаны остаться разными.

        Замер 04.09: из 20 различимых живых тождеств сторож назвал 2, и обе
        подтверждены живым фидом — ложных ноль.
        """
        self.write(
            [_orch_row("aave_v3", 3.5257, 171_498_406.0),
             _orch_row("compound_v3", 4.2041, 36_026_599.0),
             _orch_row("maple", 5.0322, 2_736_934_669.0)],
            {},
            positions={"aave_v3": 5_000.0},
        )
        r = self.run_guard()
        self.assertEqual(self.kinds(r, "pool_collision"), [])
        self.assertEqual(r["overall"], "OK")
        self.assertEqual(pic.exit_code(r), 0)

    def test_same_tvl_but_different_apy_is_not_a_collision(self):
        """Совпасть обязаны ОБА числа — иначе это не один пул, а совпадение размера."""
        self.write(
            [_orch_row("a_one", 4.0, 100_000_000.0),
             _orch_row("b_two", 7.5, 100_000_000.0)],
            {},
        )
        self.assertEqual(self.kinds(self.run_guard(), "pool_collision"), [])

    def test_tvl_tolerance_stays_negligible(self):
        """Допуск — про округление записи, а не про «примерно похожий размер».

        Соседний по величине волт Morpho отстоит на $6M; допуск обязан быть на
        много порядков меньше, иначе сторож склеит РАЗНЫЕ пулы.
        """
        self.write(
            [_orch_row("a_one", 4.0, 100_000_000.0),
             _orch_row("b_two", 4.0, 100_100_000.0)],  # +0.1 % — уже другой пул
            {},
        )
        self.assertEqual(self.kinds(self.run_guard(), "pool_collision"), [])


class TestDeclaredCollision(_Base):
    """Род ``declared`` — два ключа НАЗЫВАЮТ один UUID."""

    def test_two_keys_naming_one_pool_id(self):
        self.write(
            [_orch_row("k_one", 4.0, 10_000_000.0),
             _orch_row("k_two", 9.0, 50_000_000.0)],
            {"k_one": _status_row(4.0, 10_000_000.0, "pool-aaa"),
             "k_two": _status_row(9.0, 50_000_000.0, "pool-aaa")},
        )
        cols = self.kinds(self.run_guard(), "pool_collision")
        self.assertEqual(len(cols), 1)
        self.assertIn("declared", self.run_guard()["collisions"][0]["kind"])

    def test_kind_says_when_both_detectors_agree(self):
        """Совпали и подпись, и наблюдение — род обязан сказать это, а не выбрать один."""
        self.write(
            [_orch_row("k_one", 4.0, 10_000_000.0)],
            {"k_one": _status_row(4.0, 10_000_000.0, "pool-aaa"),
             "k_two": _status_row(4.0, 10_000_000.0, "pool-aaa")},
        )
        self.assertEqual(self.run_guard()["collisions"][0]["kind"], "declared+observed")


class TestUnreachableRefusal(_Base):
    """Отказ реестра, до которого не доходит гейт фондирования."""

    _REG_REFUSES = {"fluid_usdc": {"research_only": True, "status": "research",
                                   "per_protocol_cap": 0.0}}

    def test_polled_key_with_registry_refusal_and_money_is_critical(self):
        """Замер 04.09: research_only + status=research + cap 0.0 — и $20 000 в книге."""
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)], {},
                   registry=self._REG_REFUSES, positions={"fluid_usdc": 20_000.0})
        rows = self.kinds(self.run_guard(), "unreachable_refusal")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], pic.CRITICAL)
        self.assertIn("Отказ недостижим", rows[0]["message"])

    def test_unpolled_key_is_info_not_critical(self):
        """Ключ вне опроса: ветка реестра ДОСТИЖИМА, отказ состоится — вреда нет.

        Различать это обязательно. Замер 04.09: расхождений объявлений 9, и
        только ОДНО из них опрашивается. Сторож, кричащий обо всех девяти,
        учит себя игнорировать.
        """
        self.write([_orch_row("other", 4.0, 10_000_000.0)], {},
                   registry={"ethena_susde": {"research_only": True, "status": "active"}})
        r = self.run_guard()
        rows = self.kinds(r, "unreachable_refusal")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], pic.INFO)
        # Признак достижимости живёт в подробной секции — именно он отличает
        # безвредное расхождение от отказа, до которого не доходит управление.
        self.assertTrue(r["unreachable_refusals"][0]["registry_branch_reachable"])

    def test_class_declaring_the_same_refusal_is_not_a_finding(self):
        """Второе объявление говорит то же ⇒ отказ состоится ⇒ находки нет."""
        class _Advisory:
            IS_ADVISORY = True

        real = pic._unreachable_refusals
        self.write([_orch_row("susde", 4.0, 10_000_000.0)], {},
                   registry={"susde": {"research_only": True, "status": "active"}})
        # Класс объявляет отказ — подменяем таблицу классов тем, что видит гейт.
        import spa_core.adapters as adapters_mod
        orig = adapters_mod.ADAPTER_REGISTRY
        adapters_mod.ADAPTER_REGISTRY = [("susde", "T2", _Advisory)]
        try:
            rows = self.kinds(self.run_guard(), "unreachable_refusal")
        finally:
            adapters_mod.ADAPTER_REGISTRY = orig
        self.assertEqual(rows, [], "класс отказывает — сторожу говорить не о чем")
        self.assertIs(pic._unreachable_refusals, real)

    def test_active_key_without_refusal_is_silent(self):
        self.write([_orch_row("maple", 5.0, 2_000_000_000.0)], {},
                   registry={"maple": {"research_only": False, "status": "active"}})
        self.assertEqual(self.kinds(self.run_guard(), "unreachable_refusal"), [])


class TestThirdOutcome(_Base):
    """«Не измерено» обязано отличаться от «сравнили и коллизий нет»."""

    def test_nothing_to_compare_is_unchecked_not_a_clean_pass(self):
        """Один наблюдаемый ключ — сравнивать не с чем. Это НЕ «коллизий нет»."""
        self.write([_orch_row("only_one", 4.0, 10_000_000.0)], {})
        r = self.run_guard()
        self.assertEqual(r["overall"], pic.UNCHECKED)
        self.assertTrue(any("сравнивать" in u for u in r["unchecked"]), r["unchecked"])
        self.assertEqual(pic.exit_code(r), 2)

    def test_missing_input_is_unchecked(self):
        r = pic.run(root=str(self.dir), data_dir=str(self.dir), write=False, now=now_utc())
        self.assertEqual(r["overall"], pic.UNCHECKED)
        self.assertEqual(pic.exit_code(r), 2)

    def test_broken_json_is_named_not_swallowed(self):
        self.write([], {})
        (self.dir / "adapter_status.json").write_text("{not json", encoding="utf-8")
        r = self.run_guard()
        self.assertEqual(r["overall"], pic.UNCHECKED)
        self.assertTrue(any("не читается" in u for u in r["unchecked"]))

    def test_stale_input_refuses_to_judge(self):
        """Сторож не говорит в настоящем времени о вчерашнем снимке."""
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)],
                   {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)},
                   orch_age=40.0, status_age=40.0)
        r = self.run_guard()
        self.assertEqual(r["overall"], pic.UNCHECKED)
        self.assertTrue(any("stale_input" in u for u in r["unchecked"]))
        self.assertEqual(self.kinds(r, "pool_collision"), [])

    def test_snapshot_skew_refuses_to_judge(self):
        """Далеко разнесённые отметки — это два МОМЕНТА, а не два тождества."""
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)],
                   {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)},
                   orch_age=1.0, status_age=6.0)
        r = self.run_guard()
        self.assertEqual(r["overall"], pic.UNCHECKED)
        self.assertTrue(any("snapshot_skew" in u for u in r["unchecked"]))

    def test_stale_book_lowers_severity_instead_of_claiming_money(self):
        """Тяжесть держится на «в книге есть деньги» — значит книгу надо ИЗМЕРИТЬ.

        Протухший снимок позиций не даёт права ни поднять тревогу до CRITICAL,
        ни промолчать: коллизия остаётся WARN, а причина называется вслух.
        """
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)],
                   {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)},
                   positions={"fluid_usdc": 20_000.0}, book_age=72.0)
        r = self.run_guard()
        cols = self.kinds(r, "pool_collision")
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["severity"], pic.WARN,
                         "деньги из протухшей книги не поднимают тревогу до CRITICAL")
        self.assertTrue(any("current_positions" in u for u in r["unchecked"]), r["unchecked"])

    def test_missing_book_is_named_not_read_as_empty(self):
        """«Книги нет» и «книга пуста» — разные факты."""
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)],
                   {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)})
        r = self.run_guard()
        self.assertTrue(any("current_positions" in u for u in r["unchecked"]), r["unchecked"])

    def test_unparsable_stamp_is_said_not_assumed_fresh(self):
        (self.dir / "adapter_orchestrator_status.json").write_text(json.dumps(
            {"generated_at": "не дата", "adapters": []}), encoding="utf-8")
        (self.dir / "adapter_status.json").write_text(json.dumps(
            {"generated_at": "не дата", "adapters": {}}), encoding="utf-8")
        (self.dir / "adapter_registry.json").write_text(json.dumps(
            {"adapters": {}}), encoding="utf-8")
        r = self.run_guard()
        self.assertEqual(r["overall"], pic.UNCHECKED)
        self.assertTrue(any("возраст" in u for u in r["unchecked"]))


class TestProvenance(_Base):
    """Литерал наблюдением не является — иначе сторож склеит две КОНСТАНТЫ."""

    def test_static_rows_are_not_compared(self):
        """Два ключа с одинаковым ЛИТЕРАЛОМ TVL — не улика, а два раза выдумано."""
        self.write(
            [_orch_row("a_one", 8.0, 500_000_000.0, tvl_source="static", live_data=False),
             _orch_row("b_two", 8.0, 500_000_000.0, tvl_source="static", live_data=False)],
            {"c_three": _status_row(8.0, 500_000_000.0, None, tvl_source="static")},
        )
        r = self.run_guard()
        self.assertEqual(self.kinds(r, "pool_collision"), [])
        self.assertEqual(r["keys_compared"], [])

    def test_errored_row_is_not_an_observation(self):
        self.write(
            [_orch_row("a_one", 4.0, 10_000_000.0, status="error"),
             _orch_row("b_two", 4.0, 10_000_000.0)],
            {},
        )
        self.assertNotIn("a_one", self.run_guard()["keys_compared"])

    def test_bool_is_not_a_number(self):
        """``True`` иначе стало бы TVL 1.0 и попало в сверку."""
        self.assertIsNone(pic._num(True))
        self.assertIsNone(pic._num(False))
        self.assertEqual(pic._num(1.5), 1.5)


class TestClockIsAnInput(_Base):
    """Время — ВХОД. Тест обязан уметь состарить снимок, не трогая часы машины."""

    def test_same_fixture_flips_verdict_with_injected_now(self):
        from datetime import timedelta
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)],
                   {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)},
                   positions={"fluid_usdc": 20_000.0})
        fresh = pic.run(root=str(self.dir), data_dir=str(self.dir), write=False,
                        now=now_utc())
        self.assertEqual(fresh["overall"], pic.CRITICAL)
        aged = pic.run(root=str(self.dir), data_dir=str(self.dir), write=False,
                       now=now_utc() + timedelta(hours=48))
        self.assertEqual(aged["overall"], pic.UNCHECKED)


class TestArtifactAndCli(_Base):
    def test_report_is_written_atomically_to_the_data_dir(self):
        self.write([_orch_row("fluid_usdc", _FLUID_APY, _FLUID_TVL)],
                   {"fluid_fusdc": _status_row(_FLUID_APY, _FLUID_TVL, _FLUID_POOL)},
                   positions={"fluid_usdc": 20_000.0})
        pic.run(root=str(self.dir), data_dir=str(self.dir), write=True, now=now_utc())
        out = json.loads((self.dir / "pool_identity_collision.json").read_text())
        self.assertEqual(out["overall"], pic.CRITICAL)
        self.assertEqual(out["generated_by"],
                         "spa_core.monitoring.pool_identity_collision")

    def test_cli_exit_code_matches_the_report(self):
        self.write([_orch_row("morpho_blue", _STEAK_APY, _STEAK_TVL),
                    _orch_row("morpho_steakhouse", _STEAK_APY, _STEAK_TVL)], {},
                   positions={"compound_v3": 40_000.0})
        code = pic.main(["--root", str(self.dir), "--data-dir", str(self.dir),
                         "--no-write"], now=now_utc())
        self.assertEqual(code, 1)

    def test_module_forbids_llm(self):
        src = Path(pic.__file__).read_text(encoding="utf-8")
        self.assertIn("LLM_FORBIDDEN", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
