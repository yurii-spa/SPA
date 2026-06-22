"""
Тесты EPIC-2 S2.2 — GoLiveChecker-LP Engine C (golive_checker_lp.py).

Покрытие:
  - CHECK-LP-001: 14 дней → PASS, 5 дней → PENDING, 0 дней → PENDING
  - CHECK-LP-002: нет IL нарушений → PASS, IL < -12% → FAIL
  - CHECK-LP-003: policy_lp импортируется и работает → PASS
  - CHECK-LP-004: UniswapV3LPAdapter.read_state() работает → PASS
  - CHECK-LP-005: файл существует с корректными полями → PASS
  - CHECK-LP-006: нет позиций → PASS, non-neutral → FAIL
  - overall_status: все PASS → READY, PENDING → PENDING, FAIL → NOT_READY
  - LPGoLiveReport: поля, LLM_FORBIDDEN
  - run_golive_check_lp: write_report=False не пишет файл
  - LLM_FORBIDDEN в файле и результатах

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
    Изолируем пути golive_checker_lp модуля через monkeypatch.
    """
    import spa_core.monitoring.golive_checker_lp as gm
    monkeypatch.setattr(gm, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")
    monkeypatch.setattr(gm, "_GOLIVE_LP_REPORT_PATH", tmp_path / "golive_lp_report.json")


@pytest.fixture
def gm():
    import spa_core.monitoring.golive_checker_lp as mod
    return mod


@pytest.fixture
def lp_state_14days():
    """State с 14 днями трека — для PASS тестов."""
    return {
        "sleeve": "C",
        "engine": "LP/Liquidity",
        "start_date": "2026-06-01",
        "equity": 0.0,
        "peak_equity": 0.0,
        "il_drawdown_pct": 0.0,
        "positions": [],
        "daily_history": [{"date": f"2026-06-{1 + i:02d}", "il_drawdown_pct": 0.0} for i in range(14)],
        "cycles_completed": 14,
        "LLM_FORBIDDEN": True,
    }


@pytest.fixture
def lp_state_5days():
    """State с 5 днями трека — для PENDING тестов."""
    return {
        "sleeve": "C",
        "engine": "LP/Liquidity",
        "start_date": "2026-06-22",
        "equity": 0.0,
        "peak_equity": 0.0,
        "il_drawdown_pct": 0.0,
        "positions": [],
        "daily_history": [{"date": f"2026-06-{22 + i:02d}", "il_drawdown_pct": 0.0} for i in range(5)],
        "cycles_completed": 5,
        "LLM_FORBIDDEN": True,
    }


# ── 1. CHECK-LP-001: track days ──────────────────────────────────────────────

class TestCheckLP001TrackDays:
    def test_14_days_pass(self, gm, lp_state_14days):
        """14 дней трека → CHECK-LP-001 PASS"""
        check = gm._check_lp_001_track_days(lp_state_14days)
        assert check.check_id == "CHECK-LP-001"
        assert check.status == "PASS"

    def test_5_days_pending(self, gm, lp_state_5days):
        """5 дней трека → CHECK-LP-001 PENDING"""
        check = gm._check_lp_001_track_days(lp_state_5days)
        assert check.check_id == "CHECK-LP-001"
        assert check.status == "PENDING"
        assert "5" in check.detail

    def test_0_days_pending(self, gm):
        """0 дней трека → CHECK-LP-001 PENDING"""
        empty_state = {"daily_history": []}
        check = gm._check_lp_001_track_days(empty_state)
        assert check.status == "PENDING"

    def test_15_days_pass(self, gm):
        """15+ дней трека → CHECK-LP-001 PASS"""
        state = {
            "daily_history": [{"date": f"2026-06-{1 + i:02d}"} for i in range(15)]
        }
        check = gm._check_lp_001_track_days(state)
        assert check.status == "PASS"


# ── 2. CHECK-LP-002: IL drawdown ─────────────────────────────────────────────

class TestCheckLP002ILDrawdown:
    def test_no_il_violations_pass(self, gm, lp_state_14days):
        """Нет IL нарушений → CHECK-LP-002 PASS"""
        check = gm._check_lp_002_max_il_drawdown(lp_state_14days)
        assert check.check_id == "CHECK-LP-002"
        assert check.status == "PASS"

    def test_il_exceeded_in_history_fail(self, gm):
        """IL < -12% в historical записи → CHECK-LP-002 FAIL"""
        state_with_breach = {
            "il_drawdown_pct": 0.0,
            "daily_history": [
                {"date": "2026-06-01", "il_drawdown_pct": -0.15},  # нарушение
                {"date": "2026-06-02", "il_drawdown_pct": 0.0},
            ],
        }
        check = gm._check_lp_002_max_il_drawdown(state_with_breach)
        assert check.status == "FAIL"
        assert "-15.00%" in check.detail or "-0.15" in check.detail or "−15" in check.detail or "-15" in check.detail

    def test_current_il_exceeded_fail(self, gm):
        """Текущий il_drawdown_pct < -12% → CHECK-LP-002 FAIL"""
        state_bad = {
            "il_drawdown_pct": -0.13,
            "daily_history": [],
        }
        check = gm._check_lp_002_max_il_drawdown(state_bad)
        assert check.status == "FAIL"

    def test_exactly_minus_12pct_pass(self, gm):
        """IL drawdown ровно -12% → PASS (порог строго <)"""
        state = {
            "il_drawdown_pct": -0.12,
            "daily_history": [{"date": "2026-06-01", "il_drawdown_pct": -0.12}],
        }
        check = gm._check_lp_002_max_il_drawdown(state)
        assert check.status == "PASS"

    def test_empty_state_pass(self, gm):
        """Пустой state → PASS (нет нарушений)"""
        check = gm._check_lp_002_max_il_drawdown({})
        assert check.status == "PASS"


# ── 3. CHECK-LP-003: policy_lp ───────────────────────────────────────────────

class TestCheckLP003PolicyLP:
    def test_policy_lp_works_pass(self, gm):
        """policy_lp импортируется и корректно оценивает хорошую позицию → PASS"""
        check = gm._check_lp_003_policy_lp()
        assert check.check_id == "CHECK-LP-003"
        assert check.status == "PASS"
        assert "approved=True" in check.detail


# ── 4. CHECK-LP-004: UniswapV3LPAdapter ──────────────────────────────────────

class TestCheckLP004UniswapAdapter:
    def test_adapter_read_state_pass(self, gm):
        """UniswapV3LPAdapter.read_state() возвращает корректные данные → PASS"""
        check = gm._check_lp_004_uniswap_adapter()
        assert check.check_id == "CHECK-LP-004"
        assert check.status == "PASS"
        assert "fee_apy_24h" in check.detail or "tvl" in check.detail.lower()


# ── 5. CHECK-LP-005: data file exists ────────────────────────────────────────

class TestCheckLP005DataFile:
    def test_file_exists_with_correct_fields_pass(self, gm, monkeypatch, tmp_path):
        """Файл с корректными полями → CHECK-LP-005 PASS"""
        lp_path = tmp_path / "lp_paper_trading.json"
        lp_path.write_text(json.dumps({
            "sleeve": "C",
            "engine": "LP/Liquidity",
            "start_date": "2026-06-22",
            "equity": 0.0,
            "LLM_FORBIDDEN": True,
        }))
        monkeypatch.setattr(gm, "_LP_DATA_PATH", lp_path)

        check = gm._check_lp_005_data_file_exists()
        assert check.status == "PASS"

    def test_file_missing_fail(self, gm, monkeypatch, tmp_path):
        """Файл отсутствует → CHECK-LP-005 FAIL"""
        monkeypatch.setattr(gm, "_LP_DATA_PATH", tmp_path / "nonexistent.json")

        check = gm._check_lp_005_data_file_exists()
        assert check.status == "FAIL"

    def test_wrong_sleeve_fail(self, gm, monkeypatch, tmp_path):
        """sleeve != 'C' → CHECK-LP-005 FAIL"""
        lp_path = tmp_path / "lp_paper_trading.json"
        lp_path.write_text(json.dumps({
            "sleeve": "B",  # неправильный sleeve
            "engine": "HY/Carry",
            "start_date": "2026-06-22",
            "equity": 0.0,
            "LLM_FORBIDDEN": True,
        }))
        monkeypatch.setattr(gm, "_LP_DATA_PATH", lp_path)

        check = gm._check_lp_005_data_file_exists()
        assert check.status == "FAIL"

    def test_missing_required_key_fail(self, gm, monkeypatch, tmp_path):
        """Отсутствует обязательное поле → CHECK-LP-005 FAIL"""
        lp_path = tmp_path / "lp_paper_trading.json"
        lp_path.write_text(json.dumps({
            "sleeve": "C",
            # missing: engine, start_date, equity, LLM_FORBIDDEN
        }))
        monkeypatch.setattr(gm, "_LP_DATA_PATH", lp_path)

        check = gm._check_lp_005_data_file_exists()
        assert check.status == "FAIL"


# ── 6. CHECK-LP-006: delta-neutral ───────────────────────────────────────────

class TestCheckLP006DeltaNeutral:
    def test_no_positions_pass(self, gm):
        """Нет позиций → CHECK-LP-006 PASS"""
        check = gm._check_lp_006_delta_neutral({"positions": []})
        assert check.check_id == "CHECK-LP-006"
        assert check.status == "PASS"
        assert "Нет открытых" in check.detail

    def test_all_neutral_pass(self, gm):
        """Все позиции delta-neutral → PASS"""
        state = {
            "positions": [
                {"pool_id": "USDC_USDT_001", "is_delta_neutral": True},
                {"pool_id": "USDC_USDT_BASE_001", "is_delta_neutral": True},
            ]
        }
        check = gm._check_lp_006_delta_neutral(state)
        assert check.status == "PASS"

    def test_non_neutral_position_fail(self, gm):
        """Одна non-neutral позиция → CHECK-LP-006 FAIL"""
        state = {
            "positions": [
                {"pool_id": "WETH_USDC", "is_delta_neutral": False},
            ]
        }
        check = gm._check_lp_006_delta_neutral(state)
        assert check.status == "FAIL"
        assert "WETH_USDC" in check.detail

    def test_empty_state_pass(self, gm):
        """Нет ключа positions → PASS (fail-closed: нет позиций)"""
        check = gm._check_lp_006_delta_neutral({})
        assert check.status == "PASS"


# ── 7. run_golive_check_lp: overall logic ────────────────────────────────────

class TestRunGoLiveCheckLP:
    def test_all_pending_overall_pending(self, gm, monkeypatch):
        """14 CHECK-LP-001 PENDING (мало дней) при остальных PASS → overall PENDING"""
        # Монкейпатчим CHECK-LP-001 на PENDING
        def _lp001_pending(state):
            return gm.LPCheck(
                check_id="CHECK-LP-001",
                description="≥14 дней",
                status="PENDING",
                detail="3/14 дней",
                blocking=True,
            )

        monkeypatch.setattr(gm, "_check_lp_001_track_days", _lp001_pending)
        # Остальные проверки — PASS
        def _pass_check(check_id):
            def _check(*args, **kwargs):
                return gm.LPCheck(
                    check_id=check_id,
                    description="mock",
                    status="PASS",
                    detail="ok",
                    blocking=True,
                )
            return _check

        monkeypatch.setattr(gm, "_check_lp_002_max_il_drawdown", _pass_check("CHECK-LP-002"))
        monkeypatch.setattr(gm, "_check_lp_003_policy_lp", lambda: gm.LPCheck("CHECK-LP-003", "mock", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_004_uniswap_adapter", lambda: gm.LPCheck("CHECK-LP-004", "mock", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_005_data_file_exists", lambda: gm.LPCheck("CHECK-LP-005", "mock", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_006_delta_neutral", _pass_check("CHECK-LP-006"))

        report = gm.run_golive_check_lp(write_report=False)

        assert report.overall_status == "PENDING"

    def test_blocking_fail_overall_not_ready(self, gm, monkeypatch):
        """Блокирующий FAIL → overall NOT_READY"""
        def _fail_check_001(state):
            return gm.LPCheck("CHECK-LP-001", "mock", "FAIL", "blocked", blocking=True)

        monkeypatch.setattr(gm, "_check_lp_001_track_days", _fail_check_001)
        monkeypatch.setattr(gm, "_check_lp_002_max_il_drawdown", lambda s: gm.LPCheck("CHECK-LP-002", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_003_policy_lp", lambda: gm.LPCheck("CHECK-LP-003", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_004_uniswap_adapter", lambda: gm.LPCheck("CHECK-LP-004", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_005_data_file_exists", lambda: gm.LPCheck("CHECK-LP-005", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_006_delta_neutral", lambda s: gm.LPCheck("CHECK-LP-006", "m", "PASS", "ok"))

        report = gm.run_golive_check_lp(write_report=False)

        assert report.overall_status == "NOT_READY"

    def test_write_report_false_no_file(self, gm, monkeypatch, tmp_path):
        """write_report=False → файл golive_lp_report.json НЕ создаётся"""
        report_path = tmp_path / "golive_lp_report.json"
        monkeypatch.setattr(gm, "_GOLIVE_LP_REPORT_PATH", report_path)

        gm.run_golive_check_lp(write_report=False)

        assert not report_path.exists()

    def test_write_report_true_creates_file(self, gm, monkeypatch, tmp_path):
        """write_report=True → файл golive_lp_report.json создаётся"""
        lp_path = tmp_path / "lp_paper_trading.json"
        lp_path.write_text(json.dumps({
            "sleeve": "C",
            "engine": "LP/Liquidity",
            "start_date": "2026-06-22",
            "equity": 0.0,
            "LLM_FORBIDDEN": True,
            "positions": [],
            "daily_history": [],
        }))
        report_path = tmp_path / "golive_lp_report.json"
        monkeypatch.setattr(gm, "_LP_DATA_PATH", lp_path)
        monkeypatch.setattr(gm, "_GOLIVE_LP_REPORT_PATH", report_path)

        gm.run_golive_check_lp(write_report=True)

        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert "overall_status" in data
        assert data.get("LLM_FORBIDDEN") is True

    def test_report_has_6_checks(self, gm):
        """run_golive_check_lp возвращает ровно 6 проверок"""
        report = gm.run_golive_check_lp(write_report=False)
        assert report.total == 6
        assert len(report.checks) == 6

    def test_report_check_ids_present(self, gm):
        """Все 6 check_id присутствуют в отчёте"""
        report = gm.run_golive_check_lp(write_report=False)
        check_ids = {c.check_id for c in report.checks}
        expected = {
            "CHECK-LP-001", "CHECK-LP-002", "CHECK-LP-003",
            "CHECK-LP-004", "CHECK-LP-005", "CHECK-LP-006",
        }
        assert check_ids == expected


# ── 8. LPGoLiveReport dataclass ──────────────────────────────────────────────

class TestLPGoLiveReport:
    def test_report_llm_forbidden_true(self, gm):
        """LPGoLiveReport.LLM_FORBIDDEN = True"""
        report = gm.run_golive_check_lp(write_report=False)
        assert report.LLM_FORBIDDEN is True

    def test_report_has_generated_at(self, gm):
        """LPGoLiveReport.generated_at не пустой"""
        report = gm.run_golive_check_lp(write_report=False)
        assert report.generated_at
        assert "Z" in report.generated_at or "+" in report.generated_at

    def test_report_version(self, gm):
        """LPGoLiveReport.version содержит 'golive_lp'"""
        report = gm.run_golive_check_lp(write_report=False)
        assert "golive_lp" in report.version

    def test_passed_count_matches(self, gm, monkeypatch):
        """passed count совпадает с реальным количеством PASS"""
        # Монкейпатчим все проверки на PASS
        def _pass(check_id):
            def _fn(*args, **kwargs):
                return gm.LPCheck(check_id, "mock", "PASS", "ok")
            return _fn

        monkeypatch.setattr(gm, "_check_lp_001_track_days", _pass("CHECK-LP-001"))
        monkeypatch.setattr(gm, "_check_lp_002_max_il_drawdown", _pass("CHECK-LP-002"))
        monkeypatch.setattr(gm, "_check_lp_003_policy_lp", lambda: gm.LPCheck("CHECK-LP-003", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_004_uniswap_adapter", lambda: gm.LPCheck("CHECK-LP-004", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_005_data_file_exists", lambda: gm.LPCheck("CHECK-LP-005", "m", "PASS", "ok"))
        monkeypatch.setattr(gm, "_check_lp_006_delta_neutral", _pass("CHECK-LP-006"))

        report = gm.run_golive_check_lp(write_report=False)

        assert report.passed == 6
        assert report.overall_status == "READY"


# ── 9. LLM_FORBIDDEN в файле ─────────────────────────────────────────────────

class TestGoLiveLPLLMForbidden:
    def test_llm_forbidden_in_source_file(self):
        """Файл golive_checker_lp.py содержит 'LLM_FORBIDDEN'"""
        src = (
            _PROJECT_ROOT / "spa_core" / "monitoring" / "golive_checker_lp.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in src

    def test_llm_forbidden_early_in_docstring(self):
        """LLM_FORBIDDEN упоминается в начале файла"""
        src = (
            _PROJECT_ROOT / "spa_core" / "monitoring" / "golive_checker_lp.py"
        ).read_text()
        assert src.index("LLM_FORBIDDEN") < 1000

    def test_golive_version_constant_defined(self, gm):
        """GOLIVE_LP_VERSION определён"""
        assert hasattr(gm, "GOLIVE_LP_VERSION")
        assert "golive_lp" in gm.GOLIVE_LP_VERSION
