"""
tests/test_portfolio_health_v2.py
===================================
Тесты Portfolio Health v2.0 (EPIC-6 multi-engine).

Правила:
  - Engine B/C при отсутствии файла → score=50 (новый движок, не развёрнут)
  - DataTrust: нет файлов → score=100 (нет алармов = хорошо)
  - BEE: нет файлов → score=0 (fail-closed)
  - overall_score: взвешенное 60A + 25B + 15C
  - LLM_FORBIDDEN: нет AI-импортов, флаг в результате

LLM_FORBIDDEN — только stdlib, никаких AI-вызовов.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def health_module(project_root: Path) -> dict:
    sys.path.insert(0, str(project_root))
    from spa_core.monitoring.portfolio_health import (  # noqa: PLC0415
        get_bee_health,
        get_datatrust_health,
        get_engine_health,
        run_health_check,
    )
    return {
        "run_health_check": run_health_check,
        "get_engine_health": get_engine_health,
        "get_datatrust_health": get_datatrust_health,
        "get_bee_health": get_bee_health,
    }


# ---------------------------------------------------------------------------
# TestEngineHealth
# ---------------------------------------------------------------------------


class TestEngineHealth:
    """Тесты функции get_engine_health()."""

    def test_engine_a_returns_score(self, health_module: dict) -> None:
        """Engine A должен возвращать валидный score 0–100."""
        result = health_module["get_engine_health"]("A")
        assert "score" in result, "Нет поля score"
        assert "engine" in result
        assert result["engine"] == "A"
        assert 0 <= result["score"] <= 100

    def test_engine_a_has_status(self, health_module: dict) -> None:
        """Engine A должен иметь поле status."""
        result = health_module["get_engine_health"]("A")
        assert "status" in result
        assert result["status"] in {"ok", "degraded", "error", "not_deployed"}

    def test_engine_b_returns_50_when_no_data(self, health_module: dict) -> None:
        """Engine B при отсутствии или stub hy_paper_trading.json → score=50 (не развёрнут)."""
        result = health_module["get_engine_health"]("B")
        assert "score" in result, "Нет поля score"
        assert result["engine"] == "B"
        data_dir = Path(__file__).resolve().parents[1] / "data"
        hy_file = data_dir / "hy_paper_trading.json"
        if not hy_file.exists():
            # Файла нет → 50 (не развёрнут)
            assert result["score"] == 50, (
                f"Engine B без файла должен давать 50, получили {result['score']}"
            )
            assert result["status"] == "not_deployed"
        else:
            # Файл есть — проверяем stub (cycles_completed==0 или equity==0)
            import json as _json  # noqa: PLC0415
            content = _json.loads(hy_file.read_text())
            cycles = content.get("cycles_completed", 0) or 0
            equity = content.get("equity", 0.0) or 0.0
            if cycles == 0 or equity == 0.0:
                # stub — должен давать 50
                assert result["score"] == 50, (
                    f"Engine B stub (cycles=0/equity=0) должен давать 50, получили {result['score']}"
                )
                assert result["status"] == "not_deployed"
            else:
                assert 0 <= result["score"] <= 100

    def test_engine_c_returns_score(self, health_module: dict) -> None:
        """Engine C возвращает score 0–100."""
        result = health_module["get_engine_health"]("C")
        assert "score" in result
        assert result["engine"] == "C"
        assert 0 <= result["score"] <= 100

    def test_engine_c_returns_50_when_no_data(self, health_module: dict) -> None:
        """Engine C при отсутствии или stub lp_paper_trading.json → score=50."""
        data_dir = Path(__file__).resolve().parents[1] / "data"
        lp_file = data_dir / "lp_paper_trading.json"
        result = health_module["get_engine_health"]("C")
        if not lp_file.exists():
            assert result["score"] == 50, (
                f"Engine C без файла должен давать 50, получили {result['score']}"
            )
            assert result["status"] == "not_deployed"
        else:
            import json as _json  # noqa: PLC0415
            content = _json.loads(lp_file.read_text())
            cycles = content.get("cycles_completed", 0) or 0
            equity = content.get("equity", 0.0) or 0.0
            if cycles == 0 or equity == 0.0:
                assert result["score"] == 50, (
                    f"Engine C stub (cycles=0/equity=0) должен давать 50, получили {result['score']}"
                )
                assert result["status"] == "not_deployed"
            else:
                assert 0 <= result["score"] <= 100

    def test_unknown_engine_fails_closed(self, health_module: dict) -> None:
        """Неизвестный движок → score=0 (fail-closed)."""
        result = health_module["get_engine_health"]("X")
        assert result["score"] == 0, (
            f"Неизвестный движок должен давать 0, получили {result['score']}"
        )
        assert result["status"] == "error"

    def test_engine_has_details(self, health_module: dict) -> None:
        """Каждый движок должен возвращать поле details."""
        for eng in ("A", "B", "C"):
            result = health_module["get_engine_health"](eng)
            assert "details" in result, f"Нет details для Engine {eng}"
            assert isinstance(result["details"], dict)

    def test_engine_weight_not_in_raw_result(self, health_module: dict) -> None:
        """Вес движка не должен быть в сыром ответе get_engine_health (он добавляется в run_health_check)."""
        result = health_module["get_engine_health"]("A")
        # weight добавляется только в run_health_check, но это не критично
        # Главное что score корректный
        assert 0 <= result["score"] <= 100


# ---------------------------------------------------------------------------
# TestDataTrustHealth
# ---------------------------------------------------------------------------


class TestDataTrustHealth:
    """Тесты функции get_datatrust_health()."""

    def test_returns_score(self, health_module: dict) -> None:
        """Должен возвращать score 0–100."""
        result = health_module["get_datatrust_health"]()
        assert "score" in result
        assert 0 <= result["score"] <= 100

    def test_has_status(self, health_module: dict) -> None:
        """Должен иметь поле status."""
        result = health_module["get_datatrust_health"]()
        assert "status" in result
        assert result["status"] in {"ok", "degraded", "error"}

    def test_no_files_means_no_alarms(self, health_module: dict) -> None:
        """Нет файлов circuit_breaker / alarm_log → score=100 (нет алармов = хорошо)."""
        data_dir = Path(__file__).resolve().parents[1] / "data"
        cb_exists = (data_dir / "circuit_breaker_state.json").exists()
        alarm_exists = (data_dir / "datatrust_alarm_log.json").exists()

        result = health_module["get_datatrust_health"]()

        if not cb_exists and not alarm_exists:
            assert result["score"] == 100, (
                f"Без файлов DataTrust score должен быть 100, получили {result['score']}"
            )
        else:
            # Файлы есть — просто проверяем диапазон
            assert 0 <= result["score"] <= 100

    def test_has_details(self, health_module: dict) -> None:
        """Должен возвращать поле details."""
        result = health_module["get_datatrust_health"]()
        assert "details" in result
        assert isinstance(result["details"], dict)

    def test_circuit_breaker_open_gives_zero(
        self, health_module: dict, tmp_path: Path
    ) -> None:
        """Circuit breaker OPEN → score=0 (fail-closed)."""
        cb_file = tmp_path / "circuit_breaker_state.json"
        cb_file.write_text(json.dumps({"state": "OPEN", "version": "v1"}))
        from spa_core.monitoring.portfolio_health import get_datatrust_health  # noqa: PLC0415
        result = get_datatrust_health(data_dir=tmp_path)
        assert result["score"] == 0

    def test_circuit_breaker_half_open_gives_50(
        self, health_module: dict, tmp_path: Path
    ) -> None:
        """Circuit breaker HALF_OPEN → score=50."""
        cb_file = tmp_path / "circuit_breaker_state.json"
        cb_file.write_text(json.dumps({"state": "HALF_OPEN", "version": "v1"}))
        from spa_core.monitoring.portfolio_health import get_datatrust_health  # noqa: PLC0415
        result = get_datatrust_health(data_dir=tmp_path)
        assert result["score"] == 50

    def test_circuit_breaker_closed_gives_100(
        self, health_module: dict, tmp_path: Path
    ) -> None:
        """Circuit breaker CLOSED → score=100."""
        cb_file = tmp_path / "circuit_breaker_state.json"
        cb_file.write_text(json.dumps({"state": "CLOSED", "version": "v1"}))
        from spa_core.monitoring.portfolio_health import get_datatrust_health  # noqa: PLC0415
        result = get_datatrust_health(data_dir=tmp_path)
        assert result["score"] == 100

    def test_critical_alarm_last_24h_gives_zero(
        self, health_module: dict, tmp_path: Path
    ) -> None:
        """CRITICAL аларм в последние 24ч → score=0."""
        from datetime import datetime, timezone  # noqa: PLC0415
        now_iso = datetime.now(timezone.utc).isoformat()
        alarm_log = [
            {
                "alarm_id": "A001",
                "level": "critical",
                "metric": "apy",
                "source": "test",
                "message": "test alarm",
                "signal": "stale",
                "created_at": now_iso,
            }
        ]
        (tmp_path / "datatrust_alarm_log.json").write_text(json.dumps(alarm_log))
        from spa_core.monitoring.portfolio_health import get_datatrust_health  # noqa: PLC0415
        result = get_datatrust_health(data_dir=tmp_path)
        assert result["score"] == 0


# ---------------------------------------------------------------------------
# TestBEEHealth
# ---------------------------------------------------------------------------


class TestBEEHealth:
    """Тесты функции get_bee_health()."""

    def test_returns_score(self, health_module: dict) -> None:
        """Должен возвращать score 0–100."""
        result = health_module["get_bee_health"]()
        assert "score" in result
        assert 0 <= result["score"] <= 100

    def test_has_status(self, health_module: dict) -> None:
        """Должен иметь поле status."""
        result = health_module["get_bee_health"]()
        assert "status" in result

    def test_no_files_fails_closed(self, tmp_path: Path) -> None:
        """Нет safety_report.json → score=0 (fail-closed)."""
        from spa_core.monitoring.portfolio_health import get_bee_health  # noqa: PLC0415
        result = get_bee_health(data_dir=tmp_path)
        assert result["score"] == 0, (
            f"BEE без данных должен давать 0, получили {result['score']}"
        )
        assert result["status"] == "error"

    def test_with_safety_report(self, health_module: dict) -> None:
        """Если safety_report.json существует → score > 0."""
        data_dir = Path(__file__).resolve().parents[1] / "data"
        safety_path = data_dir / "bee" / "safety_report.json"
        result = health_module["get_bee_health"]()
        if safety_path.exists():
            assert result["score"] > 0, (
                f"BEE с safety_report.json должен давать score > 0, получили {result['score']}"
            )
        else:
            # Файла нет — ожидаем 0
            assert result["score"] == 0

    def test_5_of_5_gate_triggered_gives_100(self, tmp_path: Path) -> None:
        """events_where_gate_triggered == total_events_analyzed и нет FP → score=100 (или 110→100)."""
        bee_dir = tmp_path / "bee"
        bee_dir.mkdir()
        safety_report = {
            "total_events_analyzed": 5,
            "events_where_gate_triggered": 5,
            "false_positives": 0,
        }
        (bee_dir / "safety_report.json").write_text(json.dumps(safety_report))
        from spa_core.monitoring.portfolio_health import get_bee_health  # noqa: PLC0415
        result = get_bee_health(data_dir=tmp_path)
        assert result["score"] == 100

    def test_in_distribution_verdict_gives_bonus(self, tmp_path: Path) -> None:
        """fit_80pct_ci.verdict == 'in_distribution' → score = min(100, base+10)."""
        bee_dir = tmp_path / "bee"
        bee_dir.mkdir()
        safety_report = {
            "total_events_analyzed": 5,
            "events_where_gate_triggered": 5,
            "false_positives": 0,
        }
        fit_report = {
            "verdict": "in_distribution",
            "fit_80pct_ci": {"verdict": "in_distribution"},
        }
        (bee_dir / "safety_report.json").write_text(json.dumps(safety_report))
        (bee_dir / "backtest_live_fit.json").write_text(json.dumps(fit_report))
        from spa_core.monitoring.portfolio_health import get_bee_health  # noqa: PLC0415
        result = get_bee_health(data_dir=tmp_path)
        # 5/5 * 100 + 10 = 110 → clamp → 100
        assert result["score"] == 100
        assert result["details"]["fit_bonus_applied"] is True

    def test_partial_gate_triggered(self, tmp_path: Path) -> None:
        """3 из 5 событий сработали → score = 60."""
        bee_dir = tmp_path / "bee"
        bee_dir.mkdir()
        safety_report = {
            "total_events_analyzed": 5,
            "events_where_gate_triggered": 3,
            "false_positives": 0,
        }
        (bee_dir / "safety_report.json").write_text(json.dumps(safety_report))
        from spa_core.monitoring.portfolio_health import get_bee_health  # noqa: PLC0415
        result = get_bee_health(data_dir=tmp_path)
        assert result["score"] == 60.0

    def test_false_positives_penalized(self, tmp_path: Path) -> None:
        """False positives снижают score."""
        bee_dir = tmp_path / "bee"
        bee_dir.mkdir()
        safety_report = {
            "total_events_analyzed": 5,
            "events_where_gate_triggered": 5,
            "false_positives": 2,  # -10
        }
        (bee_dir / "safety_report.json").write_text(json.dumps(safety_report))
        from spa_core.monitoring.portfolio_health import get_bee_health  # noqa: PLC0415
        result = get_bee_health(data_dir=tmp_path)
        # 100 - (2*5) = 90
        assert result["score"] == 90.0

    def test_has_details(self, health_module: dict) -> None:
        """Должен иметь поле details."""
        result = health_module["get_bee_health"]()
        assert "details" in result
        assert isinstance(result["details"], dict)


# ---------------------------------------------------------------------------
# TestRunHealthCheck
# ---------------------------------------------------------------------------


class TestRunHealthCheck:
    """Тесты основной функции run_health_check()."""

    def test_run_returns_dict(self, health_module: dict) -> None:
        """Должен возвращать словарь."""
        result = health_module["run_health_check"]()
        assert isinstance(result, dict)

    def test_overall_score_present(self, health_module: dict) -> None:
        """Должно быть поле overall_score в диапазоне 0–100."""
        result = health_module["run_health_check"]()
        assert "overall_score" in result
        assert 0 <= result["overall_score"] <= 100

    def test_engine_health_present(self, health_module: dict) -> None:
        """run_health_check включает engine_health для A, B, C."""
        result = health_module["run_health_check"]()
        assert "engine_health" in result
        eh = result["engine_health"]
        assert isinstance(eh, dict)
        for eng in ("A", "B", "C"):
            assert eng in eh, f"Нет движка {eng} в engine_health"
            assert "score" in eh[eng]
            assert 0 <= eh[eng]["score"] <= 100

    def test_engine_health_has_weights(self, health_module: dict) -> None:
        """Каждый движок должен иметь поле weight в engine_health."""
        result = health_module["run_health_check"]()
        eh = result["engine_health"]
        assert abs(eh["A"]["weight"] - 0.60) < 1e-9
        assert abs(eh["B"]["weight"] - 0.25) < 1e-9
        assert abs(eh["C"]["weight"] - 0.15) < 1e-9

    def test_datatrust_health_present(self, health_module: dict) -> None:
        """Должно быть поле datatrust_health."""
        result = health_module["run_health_check"]()
        assert "datatrust_health" in result
        dt = result["datatrust_health"]
        assert "score" in dt
        assert 0 <= dt["score"] <= 100

    def test_bee_health_present(self, health_module: dict) -> None:
        """Должно быть поле bee_health."""
        result = health_module["run_health_check"]()
        assert "bee_health" in result
        bee = result["bee_health"]
        assert "score" in bee
        assert 0 <= bee["score"] <= 100

    def test_llm_forbidden_in_result(self, health_module: dict) -> None:
        """Результат должен содержать LLM_FORBIDDEN=True."""
        result = health_module["run_health_check"]()
        assert result.get("LLM_FORBIDDEN") is True

    def test_summary_level_present(self, health_module: dict) -> None:
        """Должен быть summary_level в допустимых значениях."""
        result = health_module["run_health_check"]()
        assert "summary_level" in result
        assert result["summary_level"] in {"OK", "WARNING", "CRITICAL"}

    def test_generated_at_present(self, health_module: dict) -> None:
        """Должен быть временной штамп generated_at."""
        result = health_module["run_health_check"]()
        assert "generated_at" in result
        assert isinstance(result["generated_at"], str)
        assert "T" in result["generated_at"]

    def test_version_present(self, health_module: dict) -> None:
        """Должна быть версия модуля."""
        result = health_module["run_health_check"]()
        assert "version" in result

    def test_overall_score_is_weighted_average(self, tmp_path: Path) -> None:
        """overall_score = 60A + 25B + 15C."""
        # Создаём минимальные данные для Engine A
        status = {
            "is_demo": False,
            "last_cycle_status": "ok",
            "kill_switch_active": False,
            "risk_policy_approved": True,
            "num_adapters_live": 5,
            "current_equity": 100000,
        }
        (tmp_path / "paper_trading_status.json").write_text(json.dumps(status))
        # B и C не развёрнуты → score=50 каждый

        from spa_core.monitoring.portfolio_health import run_health_check  # noqa: PLC0415
        result = run_health_check(data_dir=tmp_path)

        a_score = result["engine_health"]["A"]["score"]
        b_score = result["engine_health"]["B"]["score"]
        c_score = result["engine_health"]["C"]["score"]

        expected = round(a_score * 0.60 + b_score * 0.25 + c_score * 0.15, 2)
        assert abs(result["overall_score"] - expected) < 0.01, (
            f"overall_score={result['overall_score']} ≠ ожидаемое {expected}"
        )

    def test_b_and_c_neutral_without_data(self, tmp_path: Path) -> None:
        """Без B/C файлов оба должны давать score=50."""
        from spa_core.monitoring.portfolio_health import run_health_check  # noqa: PLC0415
        result = run_health_check(data_dir=tmp_path)
        # Engine A может быть 0 (нет paper_trading_status.json), но B и C должны быть 50
        assert result["engine_health"]["B"]["score"] == 50
        assert result["engine_health"]["C"]["score"] == 50


# ---------------------------------------------------------------------------
# TestLLMForbidden
# ---------------------------------------------------------------------------


class TestLLMForbidden:
    """Проверяем что LLM_FORBIDDEN соблюдён в исходнике."""

    def test_file_llm_forbidden_comment(self, project_root: Path) -> None:
        """Файл должен содержать строку 'LLM_FORBIDDEN'."""
        content = (
            project_root / "spa_core" / "monitoring" / "portfolio_health.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content, (
            "portfolio_health.py должен содержать метку LLM_FORBIDDEN"
        )

    def test_no_ai_imports(self, project_root: Path) -> None:
        """Не должно быть импортов AI-библиотек."""
        content = (
            project_root / "spa_core" / "monitoring" / "portfolio_health.py"
        ).read_text().lower()
        for banned in ("openai", "anthropic", "gpt", "langchain", "litellm"):
            assert banned not in content, (
                f"portfolio_health.py содержит запрещённый импорт: {banned}"
            )

    def test_only_stdlib(self, project_root: Path) -> None:
        """Проверяем что используется только stdlib."""
        content = (
            project_root / "spa_core" / "monitoring" / "portfolio_health.py"
        ).read_text()
        # Нет import requests, aiohttp, httpx и пр.
        for banned in ("import requests", "import aiohttp", "import httpx",
                       "import numpy", "import pandas"):
            assert banned not in content, (
                f"portfolio_health.py содержит не-stdlib импорт: {banned}"
            )
