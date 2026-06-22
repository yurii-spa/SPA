"""
Тесты EPIC-1 S1.3 — Engine B HY/Carry paper trading cycle (hy_cycle.py).

Покрытие:
  - fail-closed: EXIT режим → cycle_skipped=True
  - WATCH режим → cycle_skipped=True (не ENTER)
  - UNKNOWN/невалидный режим → cycle_skipped=True
  - kill_switch при drawdown > -8%
  - kill_switch НЕ срабатывает при малой просадке (-3%)
  - compute_drawdown: peak, drawdown, zero-peak safe
  - load_hy_state: default при отсутствии файла
  - save/load roundtrip: атомарная запись + загрузка
  - get_hy_summary: обязательные поля, LLM_FORBIDDEN, golive_days_remaining
  - LLM_FORBIDDEN в файле и результатах
  - run_hy_cycle dry_run не пишет файл
  - kill_switch обновляет regime → EXIT в state
  - ENTER режим: цикл не скипается
  - HY_CYCLE_VERSION определён
"""
import pytest
import json
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _isolate_module(monkeypatch, tmp_path):
    """
    Изолируем пути hy_cycle модуля через monkeypatch на уровне всей сессии теста.
    Каждый тест получает собственный tmp_path для hy_data_path.
    """
    import spa_core.paper_trading.hy_cycle as m
    monkeypatch.setattr(m, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", tmp_path / "hy_regime_log.json")


@pytest.fixture
def m():
    import spa_core.paper_trading.hy_cycle as mod
    return mod


# ── 1. fail-closed: EXIT / WATCH / UNKNOWN режимы ───────────────────────────

class TestFailClosed:
    def test_exit_regime_skips_cycle(self, m, monkeypatch):
        """EXIT режим → cycle_skipped=True (fail-closed)"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "EXIT")

        result = m.run_hy_cycle(dry_run=True)

        assert result.get("cycle_skipped") is True
        assert "EXIT" in result.get("reason", "")
        assert result.get("LLM_FORBIDDEN") is True

    def test_watch_regime_skips_cycle(self, m, monkeypatch):
        """WATCH режим → cycle_skipped=True (не ENTER)"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "WATCH")

        result = m.run_hy_cycle(dry_run=True)

        assert result.get("cycle_skipped") is True
        assert "WATCH" in result.get("reason", "")

    def test_unknown_regime_skips_cycle(self, m, monkeypatch):
        """UNKNOWN / невалидный режим → cycle_skipped=True"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "FOOBAR")

        result = m.run_hy_cycle(dry_run=True)

        assert result.get("cycle_skipped") is True

    def test_enter_regime_does_not_skip(self, m, monkeypatch):
        """ENTER режим → цикл выполняется (cycle_skipped=False или отсутствует kill_switch)"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
        normal_state = {
            "equity": 1000.0,
            "peak_equity": 1000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: dict(normal_state))

        result = m.run_hy_cycle(dry_run=True)

        assert result.get("cycle_skipped") is not True
        assert result.get("kill_switch") is not True


# ── 2. Kill switch ──────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_kill_switch_triggered_at_9pct_drawdown(self, m, monkeypatch):
        """drawdown -9% (< -8% threshold) → kill_switch=True"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
        bad_state = {
            "equity": 9100.0,   # -9.9% от пика 10100
            "peak_equity": 10100.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: dict(bad_state))

        result = m.run_hy_cycle(dry_run=True)

        assert result.get("kill_switch") is True
        assert result.get("regime") == "EXIT"

    def test_kill_switch_not_triggered_at_3pct_drawdown(self, m, monkeypatch):
        """drawdown -3% → kill switch НЕ срабатывает"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
        ok_state = {
            "equity": 9700.0,   # -3% от пика 10000
            "peak_equity": 10000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: dict(ok_state))

        result = m.run_hy_cycle(dry_run=True)

        assert not result.get("kill_switch")
        assert result.get("cycle_skipped") is not True

    def test_kill_switch_exactly_8pct_not_triggered(self, m, monkeypatch):
        """drawdown ровно -8% → НЕ срабатывает (threshold строго <)"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
        edge_state = {
            "equity": 9200.0,   # ровно -8% от пика 10000
            "peak_equity": 10000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: dict(edge_state))

        result = m.run_hy_cycle(dry_run=True)

        assert not result.get("kill_switch")

    def test_kill_switch_forces_exit_regime_in_state(self, m, monkeypatch, tmp_path):
        """kill_switch записывает regime=EXIT в state (dry_run=False)"""
        import spa_core.paper_trading.hy_cycle as mod
        monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
        bad_state = {
            "equity": 8000.0,
            "peak_equity": 10000.0,  # -20%
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }

        saved = {}

        def _mock_save(s):
            saved.update(s)

        monkeypatch.setattr(m, "load_hy_state", lambda: dict(bad_state))
        monkeypatch.setattr(m, "save_hy_state", _mock_save)

        result = m.run_hy_cycle(dry_run=False)

        assert result.get("kill_switch") is True
        assert saved.get("regime") == "EXIT"


# ── 3. compute_drawdown ─────────────────────────────────────────────────────

class TestComputeDrawdown:
    def test_zero_drawdown_at_peak(self, m):
        """equity == peak → drawdown = 0.0"""
        dd = m.compute_drawdown(10000.0, 10000.0)
        assert dd == pytest.approx(0.0)

    def test_ten_percent_drawdown(self, m):
        """equity 9000, peak 10000 → drawdown = -0.10"""
        dd = m.compute_drawdown(9000.0, 10000.0)
        assert dd == pytest.approx(-0.10)

    def test_zero_peak_returns_zero_safely(self, m):
        """peak = 0 → нет деления на ноль, возвращает 0.0"""
        dd = m.compute_drawdown(0.0, 0.0)
        assert dd == 0.0

    def test_positive_return_no_drawdown(self, m):
        """equity > peak (позитивный возврат) → положительное число"""
        dd = m.compute_drawdown(11000.0, 10000.0)
        assert dd == pytest.approx(0.10)


# ── 4. State persistence ────────────────────────────────────────────────────

class TestStatePersistence:
    def test_load_default_when_file_missing(self, m, monkeypatch, tmp_path):
        """Нет файла → default state без краша"""
        monkeypatch.setattr(m, "_HY_DATA_PATH", tmp_path / "nonexistent.json")

        state = m.load_hy_state()

        assert state.get("sleeve") == "B"
        assert state.get("equity") == 0.0
        assert state.get("regime") == "EXIT"
        assert state.get("LLM_FORBIDDEN") is True

    def test_load_default_on_corrupted_json(self, m, monkeypatch, tmp_path):
        """Битый JSON → default state (fail-closed)"""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json{{")
        monkeypatch.setattr(m, "_HY_DATA_PATH", bad_file)

        state = m.load_hy_state()

        assert state.get("sleeve") == "B"
        assert state.get("equity") == 0.0

    def test_save_load_roundtrip(self, m, monkeypatch, tmp_path):
        """save_hy_state → load_hy_state: данные совпадают"""
        test_path = tmp_path / "hy_paper_trading.json"
        monkeypatch.setattr(m, "_HY_DATA_PATH", test_path)

        original = {"sleeve": "B", "equity": 5000.0, "regime": "EXIT", "LLM_FORBIDDEN": True}
        m.save_hy_state(original)

        loaded = m.load_hy_state()

        assert loaded.get("equity") == 5000.0
        assert loaded.get("regime") == "EXIT"
        assert loaded.get("LLM_FORBIDDEN") is True

    def test_dry_run_does_not_write_file(self, m, monkeypatch, tmp_path):
        """dry_run=True → файл не создаётся"""
        test_path = tmp_path / "should_not_exist.json"
        monkeypatch.setattr(m, "_HY_DATA_PATH", test_path)
        monkeypatch.setattr(m, "get_hy_regime", lambda: "EXIT")

        m.run_hy_cycle(dry_run=True)

        assert not test_path.exists()

    def test_save_is_atomic_tmp_removed(self, m, monkeypatch, tmp_path):
        """После save_hy_state tmp-файл не остаётся"""
        test_path = tmp_path / "hy.json"
        monkeypatch.setattr(m, "_HY_DATA_PATH", test_path)

        m.save_hy_state({"sleeve": "B", "equity": 100.0})

        tmp_file = test_path.with_suffix(".tmp")
        assert not tmp_file.exists()
        assert test_path.exists()


# ── 5. get_hy_summary ────────────────────────────────────────────────────────

class TestGetHYSummary:
    def test_summary_has_required_fields(self, m):
        summary = m.get_hy_summary()
        required = [
            "sleeve", "engine", "start_date", "equity", "drawdown_pct",
            "regime", "days_tracked", "cycles_completed",
            "golive_days_needed", "golive_days_remaining", "golive_ready",
            "LLM_FORBIDDEN",
        ]
        for field in required:
            assert field in summary, f"Missing field: {field}"

    def test_summary_llm_forbidden_true(self, m):
        summary = m.get_hy_summary()
        assert summary["LLM_FORBIDDEN"] is True

    def test_golive_days_remaining_5days(self, m, monkeypatch):
        """5 дней трека → days_remaining = 9, golive_ready = False"""
        state_5days = {
            "sleeve": "B",
            "start_date": "2026-06-17",
            "equity": 0.0,
            "peak_equity": 0.0,
            "drawdown_pct": 0.0,
            "regime": "EXIT",
            "cycles_completed": 10,
            "daily_history": [{"date": f"2026-06-{17 + i:02d}"} for i in range(5)],
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: state_5days)

        summary = m.get_hy_summary()

        assert summary["days_tracked"] == 5
        assert summary["golive_days_remaining"] == 9
        assert summary["golive_ready"] is False

    def test_golive_ready_at_14days(self, m, monkeypatch):
        """14 дней трека → golive_ready=True, remaining=0"""
        state_14 = {
            "sleeve": "B",
            "start_date": "2026-06-08",
            "equity": 0.0,
            "peak_equity": 0.0,
            "drawdown_pct": 0.0,
            "regime": "EXIT",
            "cycles_completed": 14,
            "daily_history": [{"date": f"2026-06-{8 + i:02d}"} for i in range(14)],
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: state_14)

        summary = m.get_hy_summary()

        assert summary["days_tracked"] == 14
        assert summary["golive_days_remaining"] == 0
        assert summary["golive_ready"] is True

    def test_summary_sleeve_is_b(self, m):
        summary = m.get_hy_summary()
        assert summary["sleeve"] == "B"


# ── 6. LLM_FORBIDDEN ────────────────────────────────────────────────────────

class TestLLMForbidden:
    def test_llm_forbidden_in_source_file(self):
        """Файл hy_cycle.py содержит 'LLM_FORBIDDEN'"""
        src = (_PROJECT_ROOT / "spa_core" / "paper_trading" / "hy_cycle.py").read_text()
        assert "LLM_FORBIDDEN" in src

    def test_llm_forbidden_in_module_comment(self):
        """Docstring модуля содержит LLM_FORBIDDEN"""
        src = (_PROJECT_ROOT / "spa_core" / "paper_trading" / "hy_cycle.py").read_text()
        # Проверяем что LLM_FORBIDDEN упоминается в начале файла (docstring)
        assert src.index("LLM_FORBIDDEN") < 500

    def test_run_cycle_exit_result_llm_forbidden(self, m, monkeypatch):
        """Результат run_hy_cycle (EXIT режим) содержит LLM_FORBIDDEN=True"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "EXIT")
        result = m.run_hy_cycle(dry_run=True)
        assert result.get("LLM_FORBIDDEN") is True

    def test_run_cycle_enter_result_llm_forbidden(self, m, monkeypatch):
        """Результат run_hy_cycle (ENTER режим) содержит LLM_FORBIDDEN=True"""
        monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
        normal_state = {
            "equity": 1000.0,
            "peak_equity": 1000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_hy_state", lambda: dict(normal_state))
        result = m.run_hy_cycle(dry_run=True)
        assert result.get("LLM_FORBIDDEN") is True

    def test_hy_data_json_llm_forbidden(self, m, monkeypatch, tmp_path):
        """data/hy_paper_trading.json содержит LLM_FORBIDDEN=true при записи"""
        test_path = tmp_path / "hy_paper_trading.json"
        monkeypatch.setattr(m, "_HY_DATA_PATH", test_path)
        monkeypatch.setattr(m, "get_hy_regime", lambda: "EXIT")

        m.run_hy_cycle(dry_run=False)

        data = json.loads(test_path.read_text())
        assert data.get("LLM_FORBIDDEN") is True


# ── 7. Версия и константы ────────────────────────────────────────────────────

class TestVersionAndConstants:
    def test_hy_cycle_version_defined(self, m):
        """HY_CYCLE_VERSION определён"""
        assert hasattr(m, "HY_CYCLE_VERSION")
        assert isinstance(m.HY_CYCLE_VERSION, str)
        assert len(m.HY_CYCLE_VERSION) > 0

    def test_kill_threshold_is_minus_8pct(self, m):
        """Kill threshold = -0.08"""
        assert m._KILL_DRAWDOWN_THRESHOLD == pytest.approx(-0.08)

    def test_golive_min_days_is_14(self, m):
        """GoLive minimum = 14 дней"""
        assert m._GOLIVE_MIN_DAYS == 14


# ── 8. get_hy_regime ────────────────────────────────────────────────────────

class TestGetHYRegime:
    def test_returns_exit_when_no_file(self, m, monkeypatch, tmp_path):
        """Нет файла hy_regime_log.json → EXIT (fail-closed)"""
        monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", tmp_path / "nonexistent.json")
        assert m.get_hy_regime() == "EXIT"

    def test_reads_current_state_from_file(self, m, monkeypatch, tmp_path):
        """Читает current_state из hy_regime_log.json"""
        log_path = tmp_path / "hy_regime_log.json"
        log_path.write_text(json.dumps({"current_state": "ENTER"}))
        monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", log_path)

        assert m.get_hy_regime() == "ENTER"

    def test_invalid_state_returns_exit(self, m, monkeypatch, tmp_path):
        """Невалидное current_state → EXIT (fail-closed)"""
        log_path = tmp_path / "hy_regime_log.json"
        log_path.write_text(json.dumps({"current_state": "INVALID_STATE_XYZ"}))
        monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", log_path)

        assert m.get_hy_regime() == "EXIT"

    def test_corrupted_json_returns_exit(self, m, monkeypatch, tmp_path):
        """Битый JSON → EXIT (fail-closed)"""
        log_path = tmp_path / "hy_regime_log.json"
        log_path.write_text("{{bad json")
        monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", log_path)

        assert m.get_hy_regime() == "EXIT"
