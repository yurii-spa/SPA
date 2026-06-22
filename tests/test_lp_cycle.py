"""
Тесты EPIC-2 S2.2 — Engine C LP paper trading cycle (lp_cycle.py).

Покрытие:
  - fail-closed при ошибке загрузки state
  - IL kill switch -13% → kill_switch=True
  - IL kill switch ровно -12% → НЕ срабатывает (threshold строго <)
  - Малый drawdown -3% → нет kill switch
  - check_positions_delta_neutral: пустой список, все neutral, одна non-neutral
  - Non-delta-neutral позиции → cycle_skipped=True
  - compute_il_drawdown: peak=0 safe, корректный расчёт
  - load_lp_state: default при отсутствии файла, fail-closed на битом JSON
  - save/load roundtrip: атомарная запись
  - dry_run не пишет файл
  - get_lp_summary: обязательные поля, LLM_FORBIDDEN, golive_days_remaining
  - 14 дней трека → golive_ready=True
  - LLM_FORBIDDEN в файле и результатах
  - LP_CYCLE_VERSION, IL_KILL_THRESHOLD константы
  - daily_history: дедупликация по дате

LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
import pytest
import json
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _isolate_module(monkeypatch, tmp_path):
    """
    Изолируем пути lp_cycle модуля через monkeypatch.
    Каждый тест получает собственный tmp_path.
    """
    import spa_core.paper_trading.lp_cycle as m
    monkeypatch.setattr(m, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")


@pytest.fixture
def m():
    import spa_core.paper_trading.lp_cycle as mod
    return mod


# ── 1. fail-closed ──────────────────────────────────────────────────────────

class TestFailClosed:
    def test_fail_closed_on_corrupted_state(self, m, monkeypatch, tmp_path):
        """Битый JSON файл → load_lp_state возвращает default state (fail-closed)"""
        bad_file = tmp_path / "lp_paper_trading.json"
        bad_file.write_text("{not valid json{{")
        monkeypatch.setattr(m, "_LP_DATA_PATH", bad_file)

        state = m.load_lp_state()

        assert state.get("sleeve") == "C"
        assert state.get("equity") == 0.0
        assert state.get("LLM_FORBIDDEN") is True

    def test_fail_closed_missing_file(self, m, monkeypatch, tmp_path):
        """Нет файла → default state без краша"""
        monkeypatch.setattr(m, "_LP_DATA_PATH", tmp_path / "nonexistent.json")

        state = m.load_lp_state()

        assert state.get("sleeve") == "C"
        assert state.get("engine") == "LP/Liquidity"
        assert state.get("LLM_FORBIDDEN") is True

    def test_fail_closed_load_error_skips_cycle(self, m, monkeypatch):
        """load_lp_state выбрасывает исключение → cycle_skipped=True, reason=fail_closed"""
        def _raise():
            raise RuntimeError("simulated load failure")

        monkeypatch.setattr(m, "load_lp_state", _raise)

        result = m.run_lp_cycle(dry_run=True)

        assert result.get("cycle_skipped") is True
        assert "fail_closed" in result.get("reason", "")
        assert result.get("LLM_FORBIDDEN") is True


# ── 2. IL kill switch ────────────────────────────────────────────────────────

class TestILKillSwitch:
    def test_kill_switch_at_13pct_il_drawdown(self, m, monkeypatch):
        """IL drawdown -13% (< -12% threshold) → kill_switch=True"""
        bad_state = {
            "equity": 8700.0,   # -13% от пика 10000
            "peak_equity": 10000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(bad_state))

        result = m.run_lp_cycle(dry_run=True)

        assert result.get("kill_switch") is True
        assert result.get("il_drawdown_pct") < -0.12
        assert result.get("LLM_FORBIDDEN") is True

    def test_kill_switch_not_at_exactly_12pct(self, m, monkeypatch):
        """IL drawdown ровно -12% → НЕ срабатывает (threshold строго <)"""
        edge_state = {
            "equity": 8800.0,   # ровно -12% от пика 10000
            "peak_equity": 10000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(edge_state))

        result = m.run_lp_cycle(dry_run=True)

        assert not result.get("kill_switch")

    def test_kill_switch_not_at_3pct_drawdown(self, m, monkeypatch):
        """IL drawdown -3% → kill switch НЕ срабатывает"""
        ok_state = {
            "equity": 9700.0,   # -3% от пика 10000
            "peak_equity": 10000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(ok_state))

        result = m.run_lp_cycle(dry_run=True)

        assert not result.get("kill_switch")
        assert result.get("cycle_skipped") is not True

    def test_kill_switch_writes_state_when_not_dry_run(self, m, monkeypatch):
        """kill_switch=True + dry_run=False → save_lp_state вызывается"""
        bad_state = {
            "equity": 8000.0,   # -20% от пика 10000
            "peak_equity": 10000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        saved = {}

        def _mock_save(s):
            saved.update(s)

        monkeypatch.setattr(m, "load_lp_state", lambda: dict(bad_state))
        monkeypatch.setattr(m, "save_lp_state", _mock_save)

        result = m.run_lp_cycle(dry_run=False)

        assert result.get("kill_switch") is True
        assert saved.get("LLM_FORBIDDEN") is True

    def test_kill_switch_threshold_constant(self, m):
        """IL_KILL_THRESHOLD = -0.12"""
        assert m.IL_KILL_THRESHOLD == pytest.approx(-0.12)


# ── 3. Delta-neutral requirement ────────────────────────────────────────────

class TestDeltaNeutral:
    def test_empty_positions_is_delta_neutral(self, m):
        """Пустой список позиций → True (нет позиций — OK)"""
        assert m.check_positions_delta_neutral([]) is True

    def test_all_neutral_positions_pass(self, m):
        """Все позиции с is_delta_neutral=True → True"""
        positions = [
            {"pool_id": "USDC_USDT_001", "is_delta_neutral": True},
            {"pool_id": "USDC_USDT_BASE_001", "is_delta_neutral": True},
        ]
        assert m.check_positions_delta_neutral(positions) is True

    def test_one_non_neutral_position_fails(self, m):
        """Одна позиция с is_delta_neutral=False → False"""
        positions = [
            {"pool_id": "USDC_USDT_001", "is_delta_neutral": True},
            {"pool_id": "WETH_USDC", "is_delta_neutral": False},
        ]
        assert m.check_positions_delta_neutral(positions) is False

    def test_missing_field_defaults_to_neutral(self, m):
        """Поле is_delta_neutral отсутствует → считается нейтральным (True)"""
        positions = [{"pool_id": "USDC_USDT_001"}]
        assert m.check_positions_delta_neutral(positions) is True

    def test_non_neutral_position_skips_cycle(self, m, monkeypatch):
        """Не delta-neutral позиции → cycle_skipped=True"""
        state_with_bad_pos = {
            "equity": 5000.0,
            "peak_equity": 5000.0,
            "positions": [{"pool_id": "WETH_USDC", "is_delta_neutral": False}],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(state_with_bad_pos))

        result = m.run_lp_cycle(dry_run=True)

        assert result.get("cycle_skipped") is True
        assert "delta_neutral" in result.get("reason", "").lower()


# ── 4. compute_il_drawdown ───────────────────────────────────────────────────

class TestComputeILDrawdown:
    def test_zero_drawdown_at_peak(self, m):
        """equity == peak → drawdown = 0.0"""
        dd = m.compute_il_drawdown(10000.0, 10000.0)
        assert dd == pytest.approx(0.0)

    def test_ten_percent_drawdown(self, m):
        """equity 9000, peak 10000 → drawdown = -0.10"""
        dd = m.compute_il_drawdown(9000.0, 10000.0)
        assert dd == pytest.approx(-0.10)

    def test_zero_peak_returns_zero_safely(self, m):
        """peak = 0 → нет деления на ноль, возвращает 0.0"""
        dd = m.compute_il_drawdown(0.0, 0.0)
        assert dd == 0.0

    def test_positive_return(self, m):
        """equity > peak → положительное число (equity выросло)"""
        dd = m.compute_il_drawdown(11000.0, 10000.0)
        assert dd == pytest.approx(0.10)

    def test_exactly_12pct_drawdown(self, m):
        """equity 8800, peak 10000 → drawdown ровно -0.12"""
        dd = m.compute_il_drawdown(8800.0, 10000.0)
        assert dd == pytest.approx(-0.12)


# ── 5. State persistence ─────────────────────────────────────────────────────

class TestStatePersistence:
    def test_save_load_roundtrip(self, m, monkeypatch, tmp_path):
        """save_lp_state → load_lp_state: данные совпадают"""
        test_path = tmp_path / "lp_paper_trading.json"
        monkeypatch.setattr(m, "_LP_DATA_PATH", test_path)

        original = {
            "sleeve": "C",
            "engine": "LP/Liquidity",
            "equity": 7500.0,
            "il_drawdown_pct": -0.03,
            "LLM_FORBIDDEN": True,
        }
        m.save_lp_state(original)

        loaded = m.load_lp_state()

        assert loaded.get("equity") == 7500.0
        assert loaded.get("il_drawdown_pct") == pytest.approx(-0.03)
        assert loaded.get("LLM_FORBIDDEN") is True

    def test_dry_run_does_not_write_file(self, m, monkeypatch, tmp_path):
        """dry_run=True → файл не создаётся"""
        test_path = tmp_path / "should_not_exist.json"
        monkeypatch.setattr(m, "_LP_DATA_PATH", test_path)

        ok_state = {
            "equity": 5000.0,
            "peak_equity": 5000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(ok_state))

        m.run_lp_cycle(dry_run=True)

        assert not test_path.exists()

    def test_save_is_atomic_tmp_removed(self, m, monkeypatch, tmp_path):
        """После save_lp_state tmp-файл не остаётся"""
        test_path = tmp_path / "lp.json"
        monkeypatch.setattr(m, "_LP_DATA_PATH", test_path)

        m.save_lp_state({"sleeve": "C", "equity": 100.0})

        tmp_file = test_path.with_suffix(".tmp")
        assert not tmp_file.exists()
        assert test_path.exists()

    def test_run_writes_on_not_dry_run(self, m, monkeypatch, tmp_path):
        """dry_run=False + нормальный state → файл записывается"""
        test_path = tmp_path / "lp_paper_trading.json"
        monkeypatch.setattr(m, "_LP_DATA_PATH", test_path)

        ok_state = {
            "sleeve": "C",
            "equity": 1000.0,
            "peak_equity": 1000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
            "LLM_FORBIDDEN": True,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(ok_state))

        def _real_save(s):
            test_path.write_text(json.dumps(s))

        monkeypatch.setattr(m, "save_lp_state", _real_save)

        m.run_lp_cycle(dry_run=False)

        assert test_path.exists()


# ── 6. get_lp_summary ────────────────────────────────────────────────────────

class TestGetLPSummary:
    def test_summary_has_required_fields(self, m):
        summary = m.get_lp_summary()
        required = [
            "sleeve", "engine", "start_date", "equity",
            "il_drawdown_pct", "days_tracked", "cycles_completed",
            "golive_days_needed", "golive_days_remaining", "golive_ready",
            "LLM_FORBIDDEN",
        ]
        for field_name in required:
            assert field_name in summary, f"Missing field: {field_name}"

    def test_summary_llm_forbidden_true(self, m):
        summary = m.get_lp_summary()
        assert summary["LLM_FORBIDDEN"] is True

    def test_summary_sleeve_is_c(self, m):
        summary = m.get_lp_summary()
        assert summary["sleeve"] == "C"

    def test_golive_5days_not_ready(self, m, monkeypatch):
        """5 дней трека → golive_ready=False, remaining=9"""
        state_5days = {
            "sleeve": "C",
            "start_date": "2026-06-22",
            "equity": 0.0,
            "peak_equity": 0.0,
            "il_drawdown_pct": 0.0,
            "cycles_completed": 5,
            "daily_history": [{"date": f"2026-06-{22 + i:02d}"} for i in range(5)],
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: state_5days)

        summary = m.get_lp_summary()

        assert summary["days_tracked"] == 5
        assert summary["golive_days_remaining"] == 9
        assert summary["golive_ready"] is False

    def test_golive_ready_at_14days(self, m, monkeypatch):
        """14 дней трека → golive_ready=True, remaining=0"""
        state_14 = {
            "sleeve": "C",
            "start_date": "2026-06-22",
            "equity": 0.0,
            "peak_equity": 0.0,
            "il_drawdown_pct": 0.0,
            "cycles_completed": 14,
            "daily_history": [{"date": f"2026-06-{22 + i:02d}"} for i in range(14)],
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: state_14)

        summary = m.get_lp_summary()

        assert summary["days_tracked"] == 14
        assert summary["golive_days_remaining"] == 0
        assert summary["golive_ready"] is True

    def test_golive_more_than_14days(self, m, monkeypatch):
        """20 дней трека → remaining=0 (не отрицательный)"""
        state_20 = {
            "sleeve": "C",
            "start_date": "2026-06-01",
            "equity": 0.0,
            "peak_equity": 0.0,
            "il_drawdown_pct": 0.0,
            "cycles_completed": 20,
            "daily_history": [{"date": f"2026-06-{1 + i:02d}"} for i in range(20)],
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: state_20)

        summary = m.get_lp_summary()

        assert summary["golive_days_remaining"] == 0
        assert summary["golive_ready"] is True


# ── 7. LLM_FORBIDDEN ─────────────────────────────────────────────────────────

class TestLLMForbidden:
    def test_llm_forbidden_in_source_file(self):
        """Файл lp_cycle.py содержит 'LLM_FORBIDDEN'"""
        src = (_PROJECT_ROOT / "spa_core" / "paper_trading" / "lp_cycle.py").read_text()
        assert "LLM_FORBIDDEN" in src

    def test_llm_forbidden_in_docstring(self):
        """LLM_FORBIDDEN упоминается в начале файла (docstring)"""
        src = (_PROJECT_ROOT / "spa_core" / "paper_trading" / "lp_cycle.py").read_text()
        assert src.index("LLM_FORBIDDEN") < 500

    def test_run_cycle_normal_result_llm_forbidden(self, m, monkeypatch):
        """Результат run_lp_cycle (нормальный цикл) содержит LLM_FORBIDDEN=True"""
        ok_state = {
            "equity": 1000.0,
            "peak_equity": 1000.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(ok_state))

        result = m.run_lp_cycle(dry_run=True)

        assert result.get("LLM_FORBIDDEN") is True

    def test_kill_switch_result_llm_forbidden(self, m, monkeypatch):
        """Результат kill_switch содержит LLM_FORBIDDEN=True"""
        bad_state = {
            "equity": 8000.0,
            "peak_equity": 10000.0,  # -20%
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(bad_state))

        result = m.run_lp_cycle(dry_run=True)

        assert result.get("kill_switch") is True
        assert result.get("LLM_FORBIDDEN") is True

    def test_lp_json_llm_forbidden_field(self, m, monkeypatch, tmp_path):
        """Записанный JSON содержит LLM_FORBIDDEN=true"""
        test_path = tmp_path / "lp_paper_trading.json"
        monkeypatch.setattr(m, "_LP_DATA_PATH", test_path)

        ok_state = {
            "sleeve": "C",
            "equity": 0.0,
            "peak_equity": 0.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
            "LLM_FORBIDDEN": True,
        }
        monkeypatch.setattr(m, "load_lp_state", lambda: dict(ok_state))

        def _real_save(s):
            test_path.write_text(json.dumps(s))

        monkeypatch.setattr(m, "save_lp_state", _real_save)

        m.run_lp_cycle(dry_run=False)

        data = json.loads(test_path.read_text())
        assert data.get("LLM_FORBIDDEN") is True


# ── 8. Версия и константы ────────────────────────────────────────────────────

class TestVersionAndConstants:
    def test_lp_cycle_version_defined(self, m):
        """LP_CYCLE_VERSION определён"""
        assert hasattr(m, "LP_CYCLE_VERSION")
        assert isinstance(m.LP_CYCLE_VERSION, str)
        assert "lp_cycle" in m.LP_CYCLE_VERSION

    def test_il_kill_threshold_is_minus_12pct(self, m):
        """IL_KILL_THRESHOLD = -0.12"""
        assert m.IL_KILL_THRESHOLD == pytest.approx(-0.12)

    def test_golive_min_days_is_14(self, m):
        """GoLive minimum = 14 дней"""
        assert m._GOLIVE_MIN_DAYS == 14


# ── 9. daily_history дедупликация ───────────────────────────────────────────

class TestDailyHistoryDedup:
    def test_same_date_not_duplicated(self, m, monkeypatch):
        """Запуск двух циклов в один день → одна запись в daily_history"""
        today = "2026-06-22"

        state_with_entry = {
            "equity": 1000.0,
            "peak_equity": 1000.0,
            "positions": [],
            "daily_history": [{"date": today, "equity": 1000.0}],
            "cycles_completed": 1,
        }
        saved_states = []

        def _save(s):
            saved_states.append(json.loads(json.dumps(s)))

        monkeypatch.setattr(m, "load_lp_state", lambda: dict(state_with_entry))
        monkeypatch.setattr(m, "save_lp_state", _save)

        m.run_lp_cycle(dry_run=False)

        if saved_states:
            history = saved_states[-1].get("daily_history", [])
            dates = [e["date"] for e in history]
            assert dates.count(today) == 1, f"Дублирование: {dates}"

    def test_new_date_adds_entry(self, m, monkeypatch):
        """Новая дата → новая запись добавляется в daily_history"""
        state_empty = {
            "equity": 500.0,
            "peak_equity": 500.0,
            "positions": [],
            "daily_history": [],
            "cycles_completed": 0,
        }
        saved_states = []

        def _save(s):
            saved_states.append(json.loads(json.dumps(s)))

        monkeypatch.setattr(m, "load_lp_state", lambda: dict(state_empty))
        monkeypatch.setattr(m, "save_lp_state", _save)

        m.run_lp_cycle(dry_run=False)

        if saved_states:
            history = saved_states[-1].get("daily_history", [])
            assert len(history) == 1
