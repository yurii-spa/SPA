"""
Тесты BEE (Backtest Evidence Engine) — EPIC-9 / ADR-043
=========================================================

Тестовые группы:
  1. TestEventCatalog      — структура и содержимое каталога событий
  2. TestCounterfactual    — Ядро A: реакция гейта, honest-framing, no-APY-promise
  3. TestBacktestLiveFit   — Ядро B: классификация режима, fit, verdict
  4. TestPin               — Пиннинг, воспроизводимость, хэширование
  5. TestLLMForbidden      — Проверка отсутствия LLM-вызовов во всех модулях
"""
import json
import sys
import pytest
from pathlib import Path

# Добавляем корень репо в sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


# =====================================================================
#  Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def project_root():
    return _PROJECT_ROOT


@pytest.fixture(scope="module")
def counterfactual_mod():
    from spa_core.bee.counterfactual import (
        load_event_catalog,
        simulate_gate_reaction,
        run_counterfactual_for_all_events,
        get_event,
    )
    return {
        "load_event_catalog": load_event_catalog,
        "simulate_gate_reaction": simulate_gate_reaction,
        "run_counterfactual_for_all_events": run_counterfactual_for_all_events,
        "get_event": get_event,
    }


@pytest.fixture(scope="module")
def fit_mod():
    from spa_core.bee.backtest_live_fit import (
        classify_regime,
        compute_backtest_distribution,
        check_live_vs_backtest,
        run_backtest_live_fit,
    )
    return {
        "classify_regime": classify_regime,
        "compute_backtest_distribution": compute_backtest_distribution,
        "check_live_vs_backtest": check_live_vs_backtest,
        "run_backtest_live_fit": run_backtest_live_fit,
    }


@pytest.fixture(scope="module")
def pin_mod():
    from spa_core.bee import pin as pin_module
    from spa_core.bee.pin import pin_data, verify_pin, hash_result
    return {
        "pin_data": pin_data,
        "verify_pin": verify_pin,
        "hash_result": hash_result,
        "_module": pin_module,
    }


# =====================================================================
#  1. TestEventCatalog
# =====================================================================

class TestEventCatalog:
    """Тесты каталога кризисных событий."""

    def test_catalog_loads(self, counterfactual_mod):
        events = counterfactual_mod["load_event_catalog"]()
        assert len(events) >= 4, "Каталог должен содержать минимум 4 события"

    def test_required_event_fields(self, counterfactual_mod):
        events = counterfactual_mod["load_event_catalog"]()
        required = {
            "event_id", "name", "window_start", "window_end",
            "affected_assets", "stress_type", "expected_gate_reaction", "severity",
        }
        for event in events:
            missing = required - set(event.keys())
            assert not missing, (
                f"Событие {event.get('event_id')} пропускает поля: {missing}"
            )

    def test_usdc_svb_event_exists(self, counterfactual_mod):
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        assert event is not None, "USDC_SVB_2023 должно быть в каталоге"
        assert event["window_start"] == "2023-03-10"

    def test_ust_luna_event_exists(self, counterfactual_mod):
        event = counterfactual_mod["get_event"]("UST_LUNA_2022")
        assert event is not None, "UST_LUNA_2022 должно быть в каталоге"

    def test_ftx_contagion_event_exists(self, counterfactual_mod):
        event = counterfactual_mod["get_event"]("FTX_CONTAGION_2022")
        assert event is not None, "FTX_CONTAGION_2022 должно быть в каталоге"

    def test_event_windows_valid_dates(self, counterfactual_mod):
        from datetime import datetime
        events = counterfactual_mod["load_event_catalog"]()
        for e in events:
            start = datetime.strptime(e["window_start"], "%Y-%m-%d")
            end = datetime.strptime(e["window_end"], "%Y-%m-%d")
            assert start <= end, f"Событие {e['event_id']}: start > end"

    def test_stress_types_known(self, counterfactual_mod):
        known = {
            "algo_stablecoin_collapse",
            "blue_chip_stablecoin_depeg",
            "systemic_risk_vol_spike",
            "wrapper_depeg_liquidity",
            "funding_flip_wrapper_depeg",
        }
        events = counterfactual_mod["load_event_catalog"]()
        for e in events:
            assert e["stress_type"] in known, (
                f"Неизвестный stress_type: {e['stress_type']}"
            )

    def test_get_event_returns_none_for_unknown(self, counterfactual_mod):
        result = counterfactual_mod["get_event"]("NONEXISTENT_EVENT_XYZ")
        assert result is None


# =====================================================================
#  2. TestCounterfactual (Ядро A)
# =====================================================================

class TestCounterfactual:
    """Тесты Core A: реакция гейта, no-look-ahead, honest-framing."""

    def test_simulate_gate_reaction_usdc_svb(self, counterfactual_mod):
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)

        assert result["gate_reaction"]["exit_triggered"] is True
        # Должен выйти в течение 12 часов
        assert result["gate_reaction"]["hours_after_depeg_start"] <= 12.0, (
            "Гейт должен сработать не позже 12ч после начала депега"
        )
        # SPA просадка должна быть лучше (менее отрицательной) чем наивный холд
        cf = result["counterfactual_metrics"]
        assert cf["spa_drawdown_pct"] > cf["naive_drawdown_pct"], (
            "SPA просадка должна быть меньше наивного холда"
        )

    def test_simulate_gate_reaction_ust_luna(self, counterfactual_mod):
        event = counterfactual_mod["get_event"]("UST_LUNA_2022")
        result = counterfactual_mod["simulate_gate_reaction"](event)

        assert result["gate_reaction"]["exit_triggered"] is True
        cf = result["counterfactual_metrics"]
        assert cf["drawdown_saved_pct"] > 0, "Гейт должен сохранить капитал при UST коллапсе"

    def test_simulate_gate_reaction_ftx(self, counterfactual_mod):
        event = counterfactual_mod["get_event"]("FTX_CONTAGION_2022")
        result = counterfactual_mod["simulate_gate_reaction"](event)

        assert result["gate_reaction"]["exit_triggered"] is True
        cf = result["counterfactual_metrics"]
        assert cf["spa_drawdown_pct"] > cf["naive_drawdown_pct"]

    def test_counterfactual_result_structure(self, counterfactual_mod):
        """Обязательные поля в каждом результате."""
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)

        required = {
            "event_id", "event_name", "stress_type", "severity",
            "window_start", "window_end", "affected_assets",
            "gate_reaction", "counterfactual_metrics",
            "false_positive", "data_source", "caveat",
            "computed_at", "policy_version",
        }
        missing = required - set(result.keys())
        assert not missing, f"Пропущены обязательные поля: {missing}"

    def test_counterfactual_includes_caveat(self, counterfactual_mod):
        """Honest-framing: caveat не должен быть пустым."""
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)

        caveat = result.get("caveat", "")
        assert len(caveat) > 20, "Caveat должен быть содержательным"

    def test_no_apy_promise_in_counterfactual(self, counterfactual_mod):
        """Честность: нет обещаний X% годовых."""
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)
        result_str = json.dumps(result, ensure_ascii=False).lower()

        forbidden = ["guaranteed", "will earn", "гарантированно", "гарантия доходности"]
        for term in forbidden:
            assert term not in result_str, f"Запрещённый термин в counterfactual: '{term}'"

    def test_caveat_no_guarantee(self, counterfactual_mod):
        """Caveat не должен обещать гарантий."""
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)
        caveat_lower = result["caveat"].lower()
        # Нет слова "гарантирует" без отрицания перед ним
        assert "не гарантирует" in caveat_lower or "guarantee" not in caveat_lower

    def test_data_source_tag_present(self, counterfactual_mod):
        """Каждый результат должен иметь data_source тег."""
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)

        assert "data_source" in result
        assert result["data_source"] in ("real-data", "modeled")

    def test_policy_version_present(self, counterfactual_mod):
        """Версия политики должна быть в результате."""
        event = counterfactual_mod["get_event"]("USDC_SVB_2023")
        result = counterfactual_mod["simulate_gate_reaction"](event)
        assert "policy_version" in result

    def test_run_all_events_no_error(self, counterfactual_mod, tmp_path):
        """Прогон всех событий без ошибок."""
        safety_report = counterfactual_mod["run_counterfactual_for_all_events"](
            output_dir=tmp_path
        )

        assert "events" in safety_report
        assert len(safety_report["events"]) >= 4
        assert "generated_at" in safety_report
        assert "total_events_analyzed" in safety_report

    def test_safety_report_false_positives(self, counterfactual_mod, tmp_path):
        """False-positive rate должен быть ≤ 50%."""
        safety_report = counterfactual_mod["run_counterfactual_for_all_events"](
            output_dir=tmp_path
        )

        total = safety_report["total_events_analyzed"]
        fp = safety_report["false_positives"]
        fp_rate = fp / total if total > 0 else 0

        assert fp_rate <= 0.50, (
            f"Слишком много false positives: {fp}/{total} = {fp_rate:.0%}"
        )

    def test_safety_report_has_caveat(self, counterfactual_mod, tmp_path):
        """Safety report должен содержать caveat."""
        safety_report = counterfactual_mod["run_counterfactual_for_all_events"](
            output_dir=tmp_path
        )

        caveat = safety_report.get("caveat", "")
        assert len(caveat) > 20
        # Нет голых обещаний
        assert "guarantee" not in caveat.lower()

    def test_all_events_have_narrative(self, counterfactual_mod, tmp_path):
        """Все события должны иметь честную нарратив-строку."""
        safety_report = counterfactual_mod["run_counterfactual_for_all_events"](
            output_dir=tmp_path
        )

        for event in safety_report["events"]:
            assert "narrative" in event, f"Событие {event['event_id']} без narrative"
            narrative = event["narrative"].lower()
            assert "will earn" not in narrative
            assert "guaranteed" not in narrative

    def test_gate_triggered_on_all_stress_types(self, counterfactual_mod, tmp_path):
        """Гейт должен срабатывать на всех типах стрессовых событий."""
        safety_report = counterfactual_mod["run_counterfactual_for_all_events"](
            output_dir=tmp_path
        )

        triggered = safety_report["events_where_gate_triggered"]
        total = safety_report["total_events_analyzed"]
        assert triggered == total, (
            f"Гейт должен срабатывать на всех событиях: {triggered}/{total}"
        )

    def test_counterfactual_files_created_atomically(self, counterfactual_mod, tmp_path):
        """Атомарные записи: per-event файлы должны существовать."""
        counterfactual_mod["run_counterfactual_for_all_events"](output_dir=tmp_path)

        json_files = list(tmp_path.glob("counterfactual_*.json"))
        assert len(json_files) >= 4, "Должны быть созданы per-event файлы"

        # Нет .tmp файлов (атомарность)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Остались .tmp файлы: {tmp_files}"


# =====================================================================
#  3. TestBacktestLiveFit (Ядро B)
# =====================================================================

class TestBacktestLiveFit:
    """Тесты Core B: classify_regime, distribution, check_live_vs_backtest."""

    def test_classify_regime_normal(self, fit_mod):
        assert fit_mod["classify_regime"](0.054) == "normal"

    def test_classify_regime_high(self, fit_mod):
        assert fit_mod["classify_regime"](0.085) == "high_demand"

    def test_classify_regime_low(self, fit_mod):
        assert fit_mod["classify_regime"](0.025) == "low_rate"

    def test_classify_regime_stress(self, fit_mod):
        assert fit_mod["classify_regime"](0.005) == "stress"

    def test_classify_regime_boundary_7pct(self, fit_mod):
        # 7% — граница normal/high
        assert fit_mod["classify_regime"](0.070) == "high_demand"

    def test_classify_regime_boundary_4pct(self, fit_mod):
        # 4% — граница low/normal
        assert fit_mod["classify_regime"](0.040) == "normal"

    def test_distribution_has_band(self, fit_mod):
        dist = fit_mod["compute_backtest_distribution"]("normal")
        assert "expected_apy_band_80" in dist
        lo, hi = dist["expected_apy_band_80"]
        assert lo < hi, "Band должен быть валидным диапазоном"
        assert lo >= 0.0, "Нижняя граница не должна быть отрицательной для Core"

    def test_distribution_has_data_source(self, fit_mod):
        dist = fit_mod["compute_backtest_distribution"]("normal")
        assert dist.get("data_source") in ("modeled", "real-data")

    def test_distribution_all_regimes(self, fit_mod):
        for regime in ("normal", "high_demand", "low_rate", "stress"):
            dist = fit_mod["compute_backtest_distribution"](regime)
            assert "expected_apy_band_80" in dist, f"Нет band для режима {regime}"

    def test_check_live_no_history(self, fit_mod):
        """Пустая история → insufficient_data."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        result = fit_mod["check_live_vs_backtest"]([], dist)
        assert result["verdict"] == "insufficient_data"

    def test_check_live_in_distribution(self, fit_mod):
        """Live в диапазоне → in_distribution."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        # band normal: [0.035, 0.065] — APY 5% в полосе
        history = [
            {"current_apy": 0.050, "date": f"2026-06-{10 + i:02d}"}
            for i in range(10)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        assert result["verdict"] == "in_distribution"
        assert result["pct_live_days_in_band"] >= 0.70

    def test_check_live_drifting(self, fit_mod):
        """APY 9% > band normal [3.5%, 6.5%] → drifting или broken."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        history = [
            {"current_apy": 0.090, "date": f"2026-06-{10 + i:02d}"}
            for i in range(10)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        assert result["verdict"] in ("drifting", "broken")

    def test_check_live_broken(self, fit_mod):
        """APY 0.1% << band → broken."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        history = [
            {"current_apy": 0.001, "date": f"2026-06-{10 + i:02d}"}
            for i in range(10)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        assert result["verdict"] in ("drifting", "broken")

    def test_check_live_drift_bps_sign_positive(self, fit_mod):
        """live > центр бэктеста → drift_bps > 0."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        # band [0.035, 0.065], center = 0.050; live 0.08 > center
        history = [
            {"current_apy": 0.080, "date": f"2026-06-{10 + i:02d}"}
            for i in range(5)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        assert result["drift_bps"] > 0

    def test_check_live_drift_bps_sign_negative(self, fit_mod):
        """live < центр бэктеста → drift_bps < 0."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        # center = 0.050; live 0.02 < center
        history = [
            {"current_apy": 0.020, "date": f"2026-06-{10 + i:02d}"}
            for i in range(5)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        assert result["drift_bps"] < 0

    def test_verdict_has_alert_when_drifting(self, fit_mod):
        """Алерт активен при drifting/broken."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        history = [
            {"current_apy": 0.001, "date": f"2026-06-{10 + i:02d}"}
            for i in range(10)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        if result["verdict"] in ("drifting", "broken"):
            assert result["needs_alert"] is True
            assert result["alert_message"] is not None

    def test_verdict_no_alert_when_in_distribution(self, fit_mod):
        """Нет алерта при in_distribution."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        history = [
            {"current_apy": 0.050, "date": f"2026-06-{10 + i:02d}"}
            for i in range(10)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        if result["verdict"] == "in_distribution":
            assert result["needs_alert"] is False
            assert result["alert_message"] is None

    def test_apy_in_percentage_format(self, fit_mod):
        """APY в процентах (5.0) должен быть конвертирован в доли (0.05)."""
        dist = fit_mod["compute_backtest_distribution"]("normal")
        history = [
            {"current_apy": 5.0, "date": f"2026-06-{10 + i:02d}"}  # 5.0% как процент
            for i in range(10)
        ]
        result = fit_mod["check_live_vs_backtest"](history, dist)
        # 5.0% / 100 = 0.05 — в полосе normal [3.5%, 6.5%]
        assert result["verdict"] == "in_distribution"

    def test_run_backtest_live_fit_end_to_end(self, fit_mod, tmp_path):
        """End-to-end прогон → backtest_live_fit.json."""
        output_path = tmp_path / "backtest_live_fit.json"
        result = fit_mod["run_backtest_live_fit"](output_path=output_path)

        assert "verdict" in result
        assert result["verdict"] in (
            "in_distribution", "drifting", "broken", "insufficient_data"
        )
        assert "regime_label" in result
        assert "expected_apy_band" in result
        assert output_path.exists()

    def test_no_apy_promise_in_fit_result(self, fit_mod, tmp_path):
        """Honest-framing: нет APY-обещаний в результате fit."""
        output_path = tmp_path / "backtest_live_fit.json"
        result = fit_mod["run_backtest_live_fit"](output_path=output_path)
        result_str = json.dumps(result, ensure_ascii=False).lower()

        forbidden = ["guaranteed", "will earn", "гарантированно"]
        for term in forbidden:
            assert term not in result_str, f"Запрещённый термин: '{term}'"

    def test_fit_result_atomic_write(self, fit_mod, tmp_path):
        """Атомарная запись: нет .tmp файлов после завершения."""
        output_path = tmp_path / "backtest_live_fit.json"
        fit_mod["run_backtest_live_fit"](output_path=output_path)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Остались .tmp файлы: {tmp_files}"

    def test_fit_result_has_data_note(self, fit_mod, tmp_path):
        """Результат fit должен содержать data_note с предупреждением."""
        output_path = tmp_path / "backtest_live_fit.json"
        result = fit_mod["run_backtest_live_fit"](output_path=output_path)
        assert "data_note" in result
        assert len(result["data_note"]) > 20


# =====================================================================
#  4. TestPin
# =====================================================================

class TestPin:
    """Тесты пиннинга и воспроизводимости."""

    def _patch_dirs(self, pin_mod, tmp_path):
        """Патчим директории pin-модуля на tmp_path."""
        mod = pin_mod["_module"]
        original = (mod._PINNED_DIR, mod._HASHES_DIR)
        mod._PINNED_DIR = tmp_path / "pinned"
        mod._HASHES_DIR = tmp_path / "hashes"
        return original

    def _restore_dirs(self, pin_mod, original):
        mod = pin_mod["_module"]
        mod._PINNED_DIR, mod._HASHES_DIR = original

    def test_pin_and_verify_ok(self, pin_mod, tmp_path):
        """Пиннинг → верификация → OK."""
        original = self._patch_dirs(pin_mod, tmp_path)
        try:
            manifest = pin_mod["pin_data"](
                "test_data", {"values": [1, 2, 3]}, seed=42
            )
            assert "content_hash" in manifest
            assert len(manifest["content_hash"]) == 64  # SHA256 hex = 64 chars
            assert manifest["seed"] == 42

            verification = pin_mod["verify_pin"]("test_data")
            assert verification["ok"] is True
        finally:
            self._restore_dirs(pin_mod, original)

    def test_pin_manifest_fields(self, pin_mod, tmp_path):
        """Манифест содержит обязательные поля."""
        original = self._patch_dirs(pin_mod, tmp_path)
        try:
            manifest = pin_mod["pin_data"](
                "manifest_test", {"x": 1}, seed=99
            )
            required = {"name", "seed", "content_hash", "pinned_at", "canonical_bytes"}
            missing = required - set(manifest.keys())
            assert not missing, f"Пропущены поля манифеста: {missing}"
        finally:
            self._restore_dirs(pin_mod, original)

    def test_verify_missing_pin(self, pin_mod, tmp_path):
        """Верификация несуществующего пина → ok=False."""
        original = self._patch_dirs(pin_mod, tmp_path)
        try:
            result = pin_mod["verify_pin"]("nonexistent_xyz")
            assert result["ok"] is False
        finally:
            self._restore_dirs(pin_mod, original)

    def test_hash_result_deterministic(self, pin_mod, tmp_path):
        """Одинаковый result → одинаковый SHA256."""
        original = self._patch_dirs(pin_mod, tmp_path)
        try:
            result = {"verdict": "in_distribution", "apy": 0.054}
            h1 = pin_mod["hash_result"](result, "test_r1")
            h2 = pin_mod["hash_result"](result, "test_r2")
            assert h1 == h2, "Одинаковый result должен давать одинаковый хэш"
            assert len(h1) == 64
        finally:
            self._restore_dirs(pin_mod, original)

    def test_hash_result_different_data(self, pin_mod, tmp_path):
        """Разные данные → разные хэши."""
        original = self._patch_dirs(pin_mod, tmp_path)
        try:
            h1 = pin_mod["hash_result"]({"verdict": "in_distribution"}, "r1")
            h2 = pin_mod["hash_result"]({"verdict": "broken"}, "r2")
            assert h1 != h2
        finally:
            self._restore_dirs(pin_mod, original)

    def test_atomic_write_no_tmp_residue(self, pin_mod, tmp_path):
        """Атомарная запись: нет .tmp файлов."""
        original = self._patch_dirs(pin_mod, tmp_path)
        try:
            pin_mod["pin_data"]("atomic_test", {"x": 42}, seed=42)
            tmp_files = list(tmp_path.rglob("*.tmp"))
            assert len(tmp_files) == 0, f"Остались .tmp: {tmp_files}"
        finally:
            self._restore_dirs(pin_mod, original)


# =====================================================================
#  5. TestLLMForbidden
# =====================================================================

class TestLLMForbidden:
    """Проверяем отсутствие LLM-вызовов во всех BEE модулях."""

    _FORBIDDEN_CALLS = [
        "openai.", "anthropic.", "claude.", "gpt.", "llm.",
        "requests.post", "urllib.request.urlopen",
    ]

    def _check_file(self, path: Path) -> None:
        content = path.read_text()
        content_lower = content.lower()

        assert "LLM_FORBIDDEN" in content, (
            f"{path.name} должен содержать маркер LLM_FORBIDDEN"
        )
        for call in self._FORBIDDEN_CALLS:
            assert call.lower() not in content_lower, (
                f"Запрещённый вызов '{call}' в {path.name}"
            )

    def test_counterfactual_llm_forbidden(self, project_root):
        self._check_file(project_root / "spa_core" / "bee" / "counterfactual.py")

    def test_backtest_live_fit_llm_forbidden(self, project_root):
        self._check_file(project_root / "spa_core" / "bee" / "backtest_live_fit.py")

    def test_pin_llm_forbidden(self, project_root):
        self._check_file(project_root / "spa_core" / "bee" / "pin.py")

    def test_no_external_imports_in_counterfactual(self, project_root):
        """Только stdlib — никаких внешних зависимостей."""
        content = (project_root / "spa_core" / "bee" / "counterfactual.py").read_text()
        forbidden_imports = ["import requests", "import aiohttp", "import httpx"]
        for imp in forbidden_imports:
            assert imp not in content, f"Внешний импорт '{imp}' в counterfactual.py"

    def test_no_external_imports_in_fit(self, project_root):
        content = (project_root / "spa_core" / "bee" / "backtest_live_fit.py").read_text()
        forbidden_imports = ["import requests", "import aiohttp", "import httpx"]
        for imp in forbidden_imports:
            assert imp not in content, f"Внешний импорт '{imp}' в backtest_live_fit.py"

    def test_no_external_imports_in_pin(self, project_root):
        content = (project_root / "spa_core" / "bee" / "pin.py").read_text()
        forbidden_imports = ["import requests", "import aiohttp", "import httpx"]
        for imp in forbidden_imports:
            assert imp not in content, f"Внешний импорт '{imp}' в pin.py"
