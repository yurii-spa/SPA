"""
Волна 2 (задача A2, audit 2026-08-05): позитивные контроли разбора
протокол-слепых Tier-B модулей.

Каждый тест воспроизводит реальный класс слепоты, найденный дифференциальным
аудитом, и краснеет на не-починенном коде:
  * fee-gap семейство (51 модуль, общий движок _fee_gap_core) возвращало
    константу INSUFFICIENT (score 0.0) для ЛЮБОГО протокола — теперь vault с
    performance fee и протокол без него обязаны РАЗЛИЧАТЬСЯ, а неизвестная
    эрозия при fee>0 обязана давать None (не фабрикацию);
  * контекст-ветки фазы 2 читали слишком бедный срез профиля — обогащение
    generic_profile_for обязано отдавать РАЗЛИЧАЮЩИЕСЯ oracle/admin/exit-поля;
  * «нужны ряды»-модули обязаны питаться реальным рядом _apy_series и давать
    громкий None при недоборе истории (fail-closed, не выдумка);
  * полярность: движки «выше = лучше» инвертируются в risk_score.

Часы не читаются напрямую: фикстуры рядов строятся ОТНОСИТЕЛЬНО сегодняшней
даты (date.today), литеральных дат нет.
"""
import importlib.util
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics._fee_gap_core import (
    _erosion_pct,
    build_context_position,
    maybe_context_result,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _mk_series_dir(tmp: str, stem_points: dict) -> str:
    """Создать data_dir с historical_apy/<stem>.json из относительных дат.

    stem_points: {stem: [(days_ago, apy), ...]}
    """
    hist = Path(tmp) / "historical_apy"
    hist.mkdir(parents=True, exist_ok=True)
    today = date.today()
    for stem, points in stem_points.items():
        rows = [{"date": (today - timedelta(days=d)).isoformat(), "apy": v}
                for d, v in points]
        (hist / f"{stem}.json").write_text(json.dumps(rows), encoding="utf-8")
    return tmp


class TestFeeGapContextBranch(unittest.TestCase):
    """Fee-gap семейство: слепая константа → протокол-специфичный сигнал."""

    def _mgmt_analyzer(self):
        from spa_core.analytics import (
            defi_protocol_vault_performance_fee_gross_of_management_fee_base_gap_analyzer as m,  # noqa: E501
        )
        return m.DeFiProtocolVaultPerformanceFeeGrossOfManagementFeeBaseGapAnalyzer()  # noqa: E501

    def _keeper_analyzer(self):
        from spa_core.analytics import (
            defi_protocol_vault_performance_fee_gross_of_keeper_fee_base_gap_analyzer as m,  # noqa: E501
        )
        return m.DeFiProtocolVaultPerformanceFeeGrossOfKeeperFeeBaseGapAnalyzer()  # noqa: E501

    def test_vault_and_lending_differ(self):
        """Контроль слепоты: до фикса yearn и aave давали одну константу."""
        with TemporaryDirectory() as tmp:  # пустой data_dir → структурный apy
            a = self._mgmt_analyzer()
            r_vault = a.analyze({"protocol": "yearn_v3", "cycle_ts": 1,
                                 "data_dir": tmp})
            r_lend = a.analyze({"protocol": "aave_v3", "cycle_ts": 1,
                                "data_dir": tmp})
        self.assertIsInstance(r_vault, dict)
        self.assertIsInstance(r_lend, dict)
        # у lending нет performance fee → gap тривиально 0 → риск 0
        self.assertEqual(r_lend["risk_score"], 0.0)
        # vault: fee 10% на gross при mgmt-эрозии 1% → риск строго > 0
        self.assertGreater(r_vault["risk_score"], 0.0)
        self.assertLess(r_vault["risk_score"], 50.0)
        self.assertNotEqual(r_vault["risk_score"], r_lend["risk_score"])

    def test_polarity_inverted(self):
        """Движок отдаёт score «выше=честнее» — risk обязан быть 100-score."""
        with TemporaryDirectory() as tmp:
            r = self._mgmt_analyzer().analyze(
                {"protocol": "yearn_v3", "cycle_ts": 1, "data_dir": tmp})
        self.assertAlmostEqual(
            r["risk_score"], 100.0 - r["engine_score_higher_better"], places=2)

    def test_unmeasured_erosion_dormant_not_fabricated(self):
        """fee>0 + эрозия kind не измерена → None (dormant), не константа."""
        with TemporaryDirectory() as tmp:
            a = self._keeper_analyzer()
            self.assertIsNone(a.analyze({"protocol": "yearn_v3", "cycle_ts": 1,
                                         "data_dir": tmp}))
            # без fee keeper-эрозия не важна → честный «чисто» (риск 0)
            r = a.analyze({"protocol": "aave_v3", "cycle_ts": 1,
                           "data_dir": tmp})
            self.assertEqual(r["risk_score"], 0.0)

    def test_unknown_protocol_none(self):
        self.assertIsNone(self._mgmt_analyzer().analyze(
            {"protocol": "__nonexistent__", "cycle_ts": 1}))

    def test_legacy_path_untouched(self):
        """Легаси-вызов с доменными ключами идёт в старый движок как раньше."""
        r = self._mgmt_analyzer().analyze({
            "vault": "X", "gross_yield_pct": 10.0,
            "performance_fee_pct": 10.0,
            "net_of_management_fee_yield_pct": 9.0,
        })
        self.assertIn("score", r)
        self.assertNotIn("risk_score", r)

    def test_erosion_mapping_real_fields_only(self):
        prof = pf.generic_profile_for("yearn_v3")
        self.assertEqual(_erosion_pct("net_of_management_fee_yield_pct", prof),
                         prof["management_fee_pct"])
        self.assertEqual(_erosion_pct("net_of_deposit_fee_yield_pct", prof), 0.0)
        self.assertIsNone(_erosion_pct("net_of_keeper_fee_yield_pct", prof))
        # нет долга → borrow-cost эрозия 0 (реальный факт cascade)
        self.assertEqual(_erosion_pct("net_of_borrow_cost_yield_pct", prof), 0.0)

    def test_build_context_position_series_wins(self):
        """gross берётся из РЕАЛЬНОГО ряда, когда он есть."""
        with TemporaryDirectory() as tmp:
            _mk_series_dir(tmp, {"yearn_v3_usdc": [(0, 7.77)]})
            pos = build_context_position(
                "yearn_v3", "gross_yield_pct",
                "net_of_management_fee_yield_pct", data_dir=tmp)
        self.assertEqual(pos["gross_yield_pct"], 7.77)

    def test_maybe_context_result_passthrough_for_legacy(self):
        handled, _res = maybe_context_result(
            lambda p: {}, {"vault": "x", "gross_yield_pct": 1.0},
            "gross_yield_pct", "net_of_management_fee_yield_pct")
        self.assertFalse(handled)


class TestProfileEnrichmentWave2(unittest.TestCase):
    """Обогащение generic_profile_for: богатый срез РАЗЛИЧАЕТСЯ и честен."""

    def test_oracle_admin_exit_fields_differ_across_protocols(self):
        a = pf.generic_profile_for("aave_v3")
        p = pf.generic_profile_for("pendle")
        m = pf.generic_profile_for("maple")
        self.assertNotEqual(a["oracle_count"], p["oracle_count"])
        self.assertNotEqual(a["timelock_days"], m["timelock_days"])
        self.assertNotEqual(a["cooldown_days"], m["cooldown_days"])
        self.assertNotEqual(a["pause_controller_type"],
                            m["pause_controller_type"])

    def test_derivations_match_facts(self):
        """Каждое новое поле — прямая производная facts, не выдумка."""
        prof = pf.generic_profile_for("aave_v3")
        facts = pf.facts_for("aave_v3")
        self.assertEqual(prof["oracle_count"],
                         facts["oracle"]["num_price_sources"])
        self.assertEqual(prof["timelock_days"],
                         facts["admin"]["timelock_hours"] / 24.0)
        self.assertEqual(prof["insurance_fund_usd"],
                         facts["systemic"]["insurance_pct_of_tvl"]
                         * facts["tvl_usd"] / 100.0)
        self.assertEqual(prof["kind"], facts["kind"])

    def test_unknown_protocol_still_none(self):
        self.assertIsNone(pf.generic_profile_for("__nope__"))


class TestSeriesContextBranches(unittest.TestCase):
    """Линия «нужны ряды»: реальный ряд → сигнал; недобор → громкий None."""

    def _staleness(self):
        from spa_core.analytics import (
            defi_protocol_vault_apr_quote_staleness_analyzer as m,
        )
        return m.DeFiProtocolVaultAPRQuoteStalenessAnalyzer()

    def test_fresh_vs_stale_series(self):
        a = self._staleness()
        with TemporaryDirectory() as tmp:
            _mk_series_dir(tmp, {"aave_v3_usdc":
                                 [(2, 3.1), (1, 3.2), (0, 3.3)]})
            fresh = a.analyze({"protocol": "aave_v3", "cycle_ts": 1,
                               "data_dir": tmp})
        with TemporaryDirectory() as tmp:
            _mk_series_dir(tmp, {"aave_v3_usdc":
                                 [(12, 3.1), (11, 3.2), (10, 3.3)]})
            stale = a.analyze({"protocol": "aave_v3", "cycle_ts": 1,
                               "data_dir": tmp})
        self.assertIsInstance(fresh, dict)
        self.assertIsInstance(stale, dict)
        # котировка 10-дневной давности обязана быть рискованнее свежей
        self.assertGreater(stale["risk_score"], fresh["risk_score"])

    def test_insufficient_history_is_none(self):
        a = self._staleness()
        with TemporaryDirectory() as tmp:  # пустой data_dir — нет ряда
            self.assertIsNone(a.analyze({"protocol": "aave_v3", "cycle_ts": 1,
                                         "data_dir": tmp}))
        with TemporaryDirectory() as tmp:  # 2 точки < min_days=3
            _mk_series_dir(tmp, {"aave_v3_usdc": [(1, 3.2), (0, 3.3)]})
            self.assertIsNone(a.analyze({"protocol": "aave_v3", "cycle_ts": 1,
                                         "data_dir": tmp}))

    def test_no_data_files_written_on_context_path(self):
        """Контекст-путь модулей с write-prone движками не пишет в data/."""
        from spa_core.analytics import protocol_defi_yield_smoothing_analyzer as sm
        log = REPO_ROOT / "data" / "yield_smoothing_log.json"
        before = log.read_bytes() if log.exists() else None
        with TemporaryDirectory() as tmp:
            _mk_series_dir(tmp, {"yearn_v3_usdc":
                                 [(d, 5.0 + d * 0.01) for d in range(6)]})
            r = sm.analyze({"protocol": "yearn_v3", "cycle_ts": 1,
                            "data_dir": tmp})
        self.assertIsInstance(r, dict)
        self.assertIn("risk_score", r)
        after = log.read_bytes() if log.exists() else None
        self.assertEqual(before, after,
                         "контекст-путь не имеет права трогать data/-лог")


class TestAuditWideReclassification(unittest.TestCase):
    """Аудит-скрипт: wide_ok не попадает в PROTOCOL_BLIND_MODULES."""

    @classmethod
    def _load_script(cls):
        spec = importlib.util.spec_from_file_location(
            "audit_protocol_blindness_under_test",
            REPO_ROOT / "scripts" / "audit_protocol_blindness.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_emit_markup_separates_wide_ok(self):
        mod = self._load_script()
        report = {
            "generated_at": "T",
            "results": [
                {"module": "m_blind", "classification": "blind_constant"},
                {"module": "m_wide", "classification": "blind_equal_wide_ok"},
                {"module": "m_sens", "classification": "sensitive"},
            ],
        }
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "_pb.py"
            mod.emit_markup(report, out)
            ns: dict = {}
            exec(out.read_text(encoding="utf-8"), ns)  # noqa: S102 — тест
        self.assertIn("m_blind", ns["PROTOCOL_BLIND_MODULES"])
        self.assertNotIn("m_wide", ns["PROTOCOL_BLIND_MODULES"])
        self.assertNotIn("m_sens", ns["PROTOCOL_BLIND_MODULES"])
        self.assertIn("m_wide", ns["WIDE_OK_MODULES"])

    def test_wide_ok_not_blind_equivalent(self):
        mod = self._load_script()
        self.assertNotIn("blind_equal_wide_ok", mod.BLIND_EQUIVALENT)

    def test_aggregator_runs_wide_ok_modules(self):
        """Честный coarse-модуль НЕ исключается из Tier-B исполнения."""
        from spa_core.analytics._protocol_blindness import (
            PROTOCOL_BLIND_MODULES,
            WIDE_OK_MODULES,
        )
        self.assertFalse(PROTOCOL_BLIND_MODULES & WIDE_OK_MODULES)


if __name__ == "__main__":
    unittest.main()
