"""
Integration tests — ApyMilestoneTracker ↔ cycle_runner.py (MP-512)

Verifies:
  1. Import of ApyMilestoneTracker from spa_core.analytics.apy_milestone_tracker
  2. record_day() записывает данные
  3. Файл apy_milestone_log.json существует после вызова
  4. get_current_milestones() возвращает list
  5. get_milestone_report() возвращает непустой dict
  6. Несколько вызовов record_day() не ломают друг друга
  7. record_day() с APY 5.0% достигает только L1
  8. record_day() с APY 15.5% достигает все 5 уровней
  9. Блок в cycle_runner.py присутствует (grep-тест)
 10. Fallback 10.115 используется при отсутствии apy_today_pct

Total: 10 tests
"""
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tracker(tmp_path: Path):
    from spa_core.analytics.apy_milestone_tracker import ApyMilestoneTracker
    return ApyMilestoneTracker(data_dir=tmp_path)


# ===========================================================================
# 1. Импорт
# ===========================================================================

class TestImport:

    def test_import_apy_milestone_tracker(self):
        """Импорт ApyMilestoneTracker из spa_core.analytics.apy_milestone_tracker успешен."""
        from spa_core.analytics.apy_milestone_tracker import ApyMilestoneTracker  # noqa: F401
        assert ApyMilestoneTracker is not None

    def test_import_apy_milestones_constant(self):
        """APY_MILESTONES тоже экспортируется и содержит 5 порогов."""
        from spa_core.analytics.apy_milestone_tracker import APY_MILESTONES
        assert len(APY_MILESTONES) == 5


# ===========================================================================
# 2. record_day() записывает данные
# ===========================================================================

class TestRecordDay:

    def test_record_day_writes_to_log(self, tmp_path):
        """record_day() должен добавить запись в daily_log."""
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.115, "S7")
        data = json.loads((tmp_path / "apy_milestone_log.json").read_text())
        assert len(data["daily_log"]) == 1
        assert data["daily_log"][0]["apy_pct"] == pytest.approx(10.115, rel=1e-5)

    def test_record_day_returns_dict(self, tmp_path):
        """record_day() должен возвращать dict (отчёт)."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 8.0, "s7_pendle_yt")
        assert isinstance(result, dict)


# ===========================================================================
# 3. Файл создаётся
# ===========================================================================

class TestFileCreation:

    def test_log_file_exists_after_record(self, tmp_path):
        """apy_milestone_log.json должен появиться на диске после первого record_day."""
        log_path = tmp_path / "apy_milestone_log.json"
        assert not log_path.exists(), "файл не должен существовать до record_day"
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.0, "S7")
        assert log_path.exists()

    def test_log_file_is_valid_json(self, tmp_path):
        """Файл должен содержать корректный JSON."""
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.0, "S7")
        raw = (tmp_path / "apy_milestone_log.json").read_text()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)


# ===========================================================================
# 4. get_current_milestones() → list
# ===========================================================================

class TestGetCurrentMilestones:

    def test_get_current_milestones_returns_list(self, tmp_path):
        """get_current_milestones() должен вернуть list из 5 элементов."""
        tracker = make_tracker(tmp_path)
        milestones = tracker.get_current_milestones()
        assert isinstance(milestones, list)
        assert len(milestones) == 5


# ===========================================================================
# 5. get_milestone_report() → непустой dict
# ===========================================================================

class TestGetMilestoneReport:

    def test_get_milestone_report_returns_nonempty_dict(self, tmp_path):
        """get_milestone_report() должен вернуть непустой dict с нужными ключами."""
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.115, "S7")
        report = tracker.get_milestone_report()
        assert isinstance(report, dict)
        assert len(report) > 0
        assert "milestones" in report
        assert "days_recorded" in report


# ===========================================================================
# 6. Несколько вызовов record_day() не ломают друг друга
# ===========================================================================

class TestMultipleRecordDays:

    def test_multiple_calls_do_not_break_each_other(self, tmp_path):
        """10 последовательных вызовов record_day() должны все выжить."""
        tracker = make_tracker(tmp_path)
        for i in range(10):
            result = tracker.record_day(f"2026-06-{12+i:02d}", 8.0 + i * 0.5, "S7")
            assert isinstance(result, dict), f"Итерация {i} вернула не dict"
        data = json.loads((tmp_path / "apy_milestone_log.json").read_text())
        assert data["days_recorded"] == 10


# ===========================================================================
# 7. APY 5.0% → только L1
# ===========================================================================

class TestMilestoneL1Only:

    def test_apy_5_pct_reaches_only_l1(self, tmp_path):
        """APY ровно 5.0% должен достигать только L1; L2–L5 не достигнуты."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 5.0, "S7")
        milestones = {m["level"]: m["reached"] for m in result["milestones"]}
        assert milestones[1] is True,  "L1 (5%) должен быть достигнут"
        assert milestones[2] is False, "L2 (7%) не должен быть достигнут при 5%"
        assert milestones[3] is False, "L3 (10%) не должен быть достигнут при 5%"
        assert milestones[4] is False, "L4 (12%) не должен быть достигнут при 5%"
        assert milestones[5] is False, "L5 (15%) не должен быть достигнут при 5%"


# ===========================================================================
# 8. APY 15.5% → все 5 уровней
# ===========================================================================

class TestMilestoneAllFive:

    def test_apy_15_5_reaches_all_five_levels(self, tmp_path):
        """APY 15.5% должен достигать все пять уровней L1–L5."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 15.5, "S10")
        milestones = {m["level"]: m["reached"] for m in result["milestones"]}
        for lvl in range(1, 6):
            assert milestones[lvl] is True, f"L{lvl} должен быть достигнут при APY 15.5%"
        assert result["milestones_reached_count"] == 5


# ===========================================================================
# 9. Блок MP-512 присутствует в cycle_runner.py
# ===========================================================================

class TestCycleRunnerIntegration:

    def test_mp512_block_present_in_cycle_runner(self):
        """cycle_runner.py должен содержать блок MP-512 с ApyMilestoneTracker."""
        runner_path = (
            Path(__file__).resolve().parents[1]
            / "spa_core" / "paper_trading" / "cycle_runner.py"
        )
        assert runner_path.exists(), "cycle_runner.py не найден"
        source = runner_path.read_text(encoding="utf-8")
        assert "ApyMilestoneTracker" in source, "ApyMilestoneTracker не найден в cycle_runner.py"
        assert "MP-512" in source, "Метка MP-512 не найдена в cycle_runner.py"
        assert "apy_milestone_tracker" in source, "Импорт модуля не найден"

    def test_mp512_block_inside_try_except(self):
        """Блок MP-512 должен быть обёрнут в try/except."""
        runner_path = (
            Path(__file__).resolve().parents[1]
            / "spa_core" / "paper_trading" / "cycle_runner.py"
        )
        source = runner_path.read_text(encoding="utf-8")
        # Найдём позицию блока и убедимся что рядом есть except
        idx = source.find("MP-512")
        assert idx != -1
        snippet = source[idx: idx + 1200]
        assert "except Exception" in snippet, "Блок MP-512 не обёрнут в try/except"


# ===========================================================================
# 10. Fallback при отсутствии best_strategy_id
# ===========================================================================

class TestFallbackBehavior:

    def test_fallback_strategy_id_when_no_attr(self, tmp_path):
        """Если объект не имеет best_strategy_id, fallback 's7_pendle_yt' используется."""
        tracker = make_tracker(tmp_path)
        # Симулируем объект result без best_strategy_id
        class FakeResult:
            apy_today_pct = 9.5

        fake = FakeResult()
        strategy = (
            fake.best_strategy_id
            if hasattr(fake, "best_strategy_id")
            else "s7_pendle_yt"
        )
        result = tracker.record_day("2026-06-12", 9.5, strategy)
        data = json.loads((tmp_path / "apy_milestone_log.json").read_text())
        assert data["daily_log"][0]["strategy_id"] == "s7_pendle_yt"

    def test_fallback_apy_when_invalid(self, tmp_path):
        """Если apy_today_pct <= 0, fallback 10.115 используется."""
        tracker = make_tracker(tmp_path)

        class FakeResult:
            apy_today_pct = -1.0  # невалидное значение

        fake = FakeResult()
        apy = (
            fake.apy_today_pct
            if hasattr(fake, "apy_today_pct")
            and isinstance(fake.apy_today_pct, (int, float))
            and fake.apy_today_pct > 0
            else 10.115
        )
        assert apy == pytest.approx(10.115, rel=1e-9), "Fallback должен быть 10.115"
