"""
Тесты EPIC-1 S1.5 — GoLiveChecker-HY (Engine B).

Покрытие:
  - Нет данных → FAIL / PENDING
  - 14 дней paper trading → CHECK-HY-001 PASS
  - 7 дней ENTER → CHECK-HY-002 PASS
  - Drawdown OK/FAIL → CHECK-HY-003
  - policy_hy check → CHECK-HY-004 PASS или FAIL (зависит от наличия policy_hy)
  - PendlePTAdapter check → CHECK-HY-005 PASS или FAIL (зависит от адаптера)
  - data file check → CHECK-HY-006
  - run_golive_check_hy() возвращает HYGoLiveReport с 6 чеками
  - Атомарная запись data/golive_hy_report.json
  - LLM_FORBIDDEN: нет AI-импортов

LLM_FORBIDDEN
"""
import json
import sys
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def golive_module(project_root):
    """Импортирует все публичные символы из golive_checker_hy."""
    sys.path.insert(0, str(project_root))
    from spa_core.monitoring.golive_checker_hy import (
        run_golive_check_hy,
        _check_paper_days,
        _check_enter_days,
        _check_drawdown,
        _check_policy_hy,
        _check_pendle_adapter,
        _check_data_file,
        GOLIVE_HY_VERSION,
        MIN_PAPER_DAYS,
        MIN_ENTER_DAYS,
        MAX_DRAWDOWN_PCT,
    )
    return {
        "run_golive_check_hy": run_golive_check_hy,
        "_check_paper_days": _check_paper_days,
        "_check_enter_days": _check_enter_days,
        "_check_drawdown": _check_drawdown,
        "_check_policy_hy": _check_policy_hy,
        "_check_pendle_adapter": _check_pendle_adapter,
        "_check_data_file": _check_data_file,
        "GOLIVE_HY_VERSION": GOLIVE_HY_VERSION,
        "MIN_PAPER_DAYS": MIN_PAPER_DAYS,
        "MIN_ENTER_DAYS": MIN_ENTER_DAYS,
        "MAX_DRAWDOWN_PCT": MAX_DRAWDOWN_PCT,
    }


def _make_history(days: int, regime: str = "EXIT") -> list:
    """Вспомогательный: создаёт daily_history с заданным числом записей."""
    return [
        {"date": f"2026-06-{i+1:02d}", "regime": regime, "drawdown_pct": 0.0}
        for i in range(days)
    ]


# ---------------------------------------------------------------------------
# CHECK-HY-001: Paper trading days
# ---------------------------------------------------------------------------

class TestCheckPaperDays:
    def test_no_history_fail(self, golive_module):
        """Пустая история → FAIL (0 дней)."""
        result = golive_module["_check_paper_days"]({"daily_history": []})
        assert result.check_id == "CHECK-HY-001"
        assert result.status == "FAIL"
        assert result.value == 0

    def test_missing_key_fail(self, golive_module):
        """Нет ключа daily_history → FAIL (fail-closed)."""
        result = golive_module["_check_paper_days"]({})
        assert result.status == "FAIL"

    def test_7_days_pending(self, golive_module):
        """7 дней < 14 → PENDING."""
        result = golive_module["_check_paper_days"]({"daily_history": _make_history(7)})
        assert result.status == "PENDING"
        assert result.value == 7

    def test_13_days_pending(self, golive_module):
        """13 дней < 14 → PENDING."""
        result = golive_module["_check_paper_days"]({"daily_history": _make_history(13)})
        assert result.status == "PENDING"

    def test_14_days_pass(self, golive_module):
        """14 дней == MIN_PAPER_DAYS → PASS."""
        result = golive_module["_check_paper_days"]({"daily_history": _make_history(14)})
        assert result.status == "PASS"
        assert result.value == 14

    def test_20_days_pass(self, golive_module):
        """20 дней > MIN_PAPER_DAYS → PASS."""
        result = golive_module["_check_paper_days"]({"daily_history": _make_history(20)})
        assert result.status == "PASS"

    def test_note_contains_remaining(self, golive_module):
        """Note содержит количество оставшихся дней."""
        result = golive_module["_check_paper_days"]({"daily_history": _make_history(5)})
        assert "9 remaining" in result.note  # 14 - 5 = 9


# ---------------------------------------------------------------------------
# CHECK-HY-002: ENTER regime days
# ---------------------------------------------------------------------------

class TestCheckEnterDays:
    def test_no_history_fail(self, golive_module):
        """Пустая история → FAIL."""
        result = golive_module["_check_enter_days"]({"daily_history": []})
        assert result.check_id == "CHECK-HY-002"
        assert result.status == "FAIL"
        assert result.value == 0

    def test_all_exit_pending(self, golive_module):
        """Есть история, но все EXIT → PENDING."""
        history = _make_history(14, regime="EXIT")
        result = golive_module["_check_enter_days"]({"daily_history": history})
        assert result.status == "PENDING"
        assert result.value == 0

    def test_6_enter_days_pending(self, golive_module):
        """6 ENTER дней < 7 → PENDING."""
        history = [{"regime": "ENTER", "drawdown_pct": 0.0} for _ in range(6)]
        history += [{"regime": "EXIT", "drawdown_pct": 0.0} for _ in range(8)]
        result = golive_module["_check_enter_days"]({"daily_history": history})
        assert result.status == "PENDING"
        assert result.value == 6

    def test_7_enter_days_pass(self, golive_module):
        """7 ENTER дней == MIN_ENTER_DAYS → PASS."""
        history = [{"regime": "ENTER", "drawdown_pct": 0.0} for _ in range(7)]
        history += [{"regime": "EXIT", "drawdown_pct": 0.0} for _ in range(7)]
        result = golive_module["_check_enter_days"]({"daily_history": history})
        assert result.status == "PASS"
        assert result.value == 7

    def test_14_enter_days_pass(self, golive_module):
        """Все 14 дней ENTER → PASS."""
        history = _make_history(14, regime="ENTER")
        result = golive_module["_check_enter_days"]({"daily_history": history})
        assert result.status == "PASS"
        assert result.value == 14

    def test_mixed_regimes_counts_only_enter(self, golive_module):
        """Смешанные режимы — считаем только ENTER."""
        history = [
            {"regime": "ENTER"},
            {"regime": "EXIT"},
            {"regime": "ENTER"},
            {"regime": "UNKNOWN"},
            {"regime": "ENTER"},
        ]
        result = golive_module["_check_enter_days"]({"daily_history": history})
        assert result.value == 3


# ---------------------------------------------------------------------------
# CHECK-HY-003: Drawdown threshold
# ---------------------------------------------------------------------------

class TestCheckDrawdown:
    def test_zero_drawdown_pass(self, golive_module):
        """Нулевой drawdown → PASS."""
        state = {"drawdown_pct": 0.0, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.check_id == "CHECK-HY-003"
        assert result.status == "PASS"

    def test_small_drawdown_pass(self, golive_module):
        """Drawdown -3% (лучше -8%) → PASS."""
        state = {"drawdown_pct": -0.03, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.status == "PASS"

    def test_exactly_at_threshold_pass(self, golive_module):
        """Drawdown ровно -8% → PASS (граница включительно)."""
        state = {"drawdown_pct": -0.08, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.status == "PASS"

    def test_just_over_threshold_fail(self, golive_module):
        """Drawdown -8.01% → FAIL."""
        state = {"drawdown_pct": -0.0801, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.status == "FAIL"

    def test_large_drawdown_fail(self, golive_module):
        """Drawdown -15% → FAIL."""
        state = {"drawdown_pct": -0.15, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.status == "FAIL"

    def test_history_drawdown_checked(self, golive_module):
        """Нарушение drawdown в истории → FAIL, даже если текущий OK."""
        state = {
            "drawdown_pct": 0.0,
            "daily_history": [
                {"drawdown_pct": -0.09, "date": "2026-06-01"},
                {"drawdown_pct": -0.02, "date": "2026-06-02"},
            ],
        }
        result = golive_module["_check_drawdown"](state)
        assert result.status == "FAIL"

    def test_no_history_uses_current(self, golive_module):
        """Без истории — смотрим только текущий drawdown."""
        state = {"drawdown_pct": -0.05, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.status == "PASS"

    def test_missing_drawdown_pct_zero(self, golive_module):
        """Нет поля drawdown_pct → считаем 0 (PASS)."""
        state = {"daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert result.status == "PASS"

    def test_note_contains_worst(self, golive_module):
        """Note содержит значение наихудшего drawdown."""
        state = {"drawdown_pct": -0.05, "daily_history": []}
        result = golive_module["_check_drawdown"](state)
        assert "-5.00%" in result.note or "-0.05" in result.note or "5%" in result.note


# ---------------------------------------------------------------------------
# CHECK-HY-004: policy_hy
# ---------------------------------------------------------------------------

class TestCheckPolicyHY:
    def test_returns_check_hy_004(self, golive_module):
        result = golive_module["_check_policy_hy"]()
        assert result.check_id == "CHECK-HY-004"

    def test_status_pass_or_fail(self, golive_module):
        """Допустимы только PASS или FAIL (не PENDING)."""
        result = golive_module["_check_policy_hy"]()
        assert result.status in ("PASS", "FAIL")

    def test_policy_hy_pass(self, golive_module):
        """Если policy_hy установлен — должен быть PASS."""
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from spa_core.risk.policy_hy import evaluate_protocol  # noqa: F401
            result = golive_module["_check_policy_hy"]()
            assert result.status == "PASS", f"policy_hy есть, но CHECK-HY-004 FAIL: {result.note}"
        except ImportError:
            pytest.skip("policy_hy не установлен — пропускаем")


# ---------------------------------------------------------------------------
# CHECK-HY-005: PendlePTAdapter
# ---------------------------------------------------------------------------

class TestCheckPendleAdapter:
    def test_returns_check_hy_005(self, golive_module):
        result = golive_module["_check_pendle_adapter"]()
        assert result.check_id == "CHECK-HY-005"

    def test_status_pass_or_fail(self, golive_module):
        """PASS или FAIL (не PENDING)."""
        result = golive_module["_check_pendle_adapter"]()
        assert result.status in ("PASS", "FAIL")

    def test_pendle_adapter_pass(self, golive_module, project_root):
        """Если adapters/pendle_pt.py существует — должен быть PASS."""
        adapter_path = project_root / "adapters" / "pendle_pt.py"
        if not adapter_path.exists():
            pytest.skip("adapters/pendle_pt.py не найден — пропускаем")
        result = golive_module["_check_pendle_adapter"]()
        assert result.status == "PASS", f"Адаптер есть, но FAIL: {result.note}"


# ---------------------------------------------------------------------------
# CHECK-HY-006: Data file
# ---------------------------------------------------------------------------

class TestCheckDataFile:
    def test_returns_check_hy_006(self, golive_module):
        result = golive_module["_check_data_file"]()
        assert result.check_id == "CHECK-HY-006"

    def test_file_exists_pass(self, golive_module, project_root):
        """Если hy_paper_trading.json существует → PASS."""
        hy_path = project_root / "data" / "hy_paper_trading.json"
        if not hy_path.exists():
            pytest.skip("hy_paper_trading.json не существует — пропускаем")
        result = golive_module["_check_data_file"]()
        assert result.status == "PASS"

    def test_file_missing_fail(self, golive_module, project_root, tmp_path, monkeypatch):
        """Если файл не существует → FAIL."""
        import spa_core.monitoring.golive_checker_hy as checker_mod
        monkeypatch.setattr(checker_mod, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()
        result = checker_mod._check_data_file()
        assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# run_golive_check_hy() — интеграционный
# ---------------------------------------------------------------------------

class TestRunGoLiveCheckHY:
    def test_returns_report(self, golive_module):
        """run_golive_check_hy() возвращает HYGoLiveReport."""
        report = golive_module["run_golive_check_hy"]()
        assert report is not None
        assert report.total == 6

    def test_overall_status_valid(self, golive_module):
        """overall_status один из PASS / FAIL / PENDING."""
        report = golive_module["run_golive_check_hy"]()
        assert report.overall_status in ("PASS", "FAIL", "PENDING")

    def test_llm_forbidden_true(self, golive_module):
        """LLM_FORBIDDEN обязательно True."""
        report = golive_module["run_golive_check_hy"]()
        assert report.LLM_FORBIDDEN is True

    def test_all_6_check_ids_present(self, golive_module):
        """Все 6 check_id обязательно присутствуют."""
        report = golive_module["run_golive_check_hy"]()
        check_ids = {c.check_id for c in report.checks}
        for expected in ["CHECK-HY-001", "CHECK-HY-002", "CHECK-HY-003",
                         "CHECK-HY-004", "CHECK-HY-005", "CHECK-HY-006"]:
            assert expected in check_ids, f"{expected} отсутствует в report.checks"

    def test_passed_plus_failed_plus_pending_equals_total(self, golive_module):
        """passed + failed + pending == total."""
        report = golive_module["run_golive_check_hy"]()
        assert report.passed + report.failed + report.pending == report.total

    def test_blockers_are_failed_checks(self, golive_module):
        """Все blocker_ids — это FAIL чеки."""
        report = golive_module["run_golive_check_hy"]()
        failed_ids = {c.check_id for c in report.checks if c.status == "FAIL"}
        assert set(report.blocker_ids) == failed_ids

    def test_report_file_created(self, golive_module, project_root):
        """Файл data/golive_hy_report.json создан после запуска."""
        golive_module["run_golive_check_hy"]()
        report_path = project_root / "data" / "golive_hy_report.json"
        assert report_path.exists(), "golive_hy_report.json не создан"

    def test_report_file_valid_json(self, golive_module, project_root):
        """Файл golive_hy_report.json содержит валидный JSON."""
        golive_module["run_golive_check_hy"]()
        report_path = project_root / "data" / "golive_hy_report.json"
        data = json.loads(report_path.read_text())
        assert "overall_status" in data
        assert "checks" in data
        assert "LLM_FORBIDDEN" in data

    def test_report_file_llm_forbidden(self, golive_module, project_root):
        """Поле LLM_FORBIDDEN=True в JSON-файле."""
        golive_module["run_golive_check_hy"]()
        report_path = project_root / "data" / "golive_hy_report.json"
        data = json.loads(report_path.read_text())
        assert data["LLM_FORBIDDEN"] is True

    def test_report_file_has_6_checks(self, golive_module, project_root):
        """JSON-файл содержит ровно 6 проверок."""
        golive_module["run_golive_check_hy"]()
        report_path = project_root / "data" / "golive_hy_report.json"
        data = json.loads(report_path.read_text())
        assert len(data["checks"]) == 6

    def test_ready_for_golive_false_without_data(self, golive_module):
        """Без 14 дней трека ready_for_golive = False."""
        report = golive_module["run_golive_check_hy"]()
        # hy_paper_trading.json существует, но daily_history пустой → PENDING/FAIL
        assert report.ready_for_golive is False

    def test_fail_dominates_pending(self, golive_module):
        """Если есть FAIL и PENDING — overall_status = FAIL."""
        report = golive_module["run_golive_check_hy"]()
        if report.failed > 0 and report.pending > 0:
            assert report.overall_status == "FAIL"


# ---------------------------------------------------------------------------
# LLM_FORBIDDEN guards
# ---------------------------------------------------------------------------

class TestLLMForbidden:
    def test_file_contains_llm_forbidden_marker(self, project_root):
        """Файл содержит маркер LLM_FORBIDDEN."""
        content = (
            project_root / "spa_core" / "monitoring" / "golive_checker_hy.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_library_imports(self, project_root):
        """Нет импортов AI-библиотек (openai, anthropic, langchain, gpt)."""
        content = (
            project_root / "spa_core" / "monitoring" / "golive_checker_hy.py"
        ).read_text().lower()
        for forbidden in ("openai", "anthropic", "gpt", "langchain", "llm"):
            # "llm" разрешён только как часть комментария LLM_FORBIDDEN
            if forbidden == "llm":
                # Проверяем, что нет import llm или from llm
                assert "import llm" not in content
            else:
                assert forbidden not in content, f"Forbidden import: {forbidden}"

    def test_no_requests_or_httpx(self, project_root):
        """Только stdlib — нет requests/httpx/aiohttp."""
        content = (
            project_root / "spa_core" / "monitoring" / "golive_checker_hy.py"
        ).read_text()
        for lib in ("import requests", "import httpx", "import aiohttp"):
            assert lib not in content, f"Нарушение stdlib-only: {lib}"

    def test_atomic_write_pattern(self, project_root):
        """Используется атомарная запись (tempfile + os.replace)."""
        content = (
            project_root / "spa_core" / "monitoring" / "golive_checker_hy.py"
        ).read_text()
        assert "os.replace" in content, "Нет атомарной записи os.replace"
        assert "tempfile" in content, "Нет tempfile для атомарной записи"

    def test_check_functions_llm_forbidden(self, project_root):
        """Каждая _check_* функция содержит # LLM_FORBIDDEN."""
        content = (
            project_root / "spa_core" / "monitoring" / "golive_checker_hy.py"
        ).read_text()
        # Минимум 6 вхождений LLM_FORBIDDEN (по одному на каждую проверку + верхний уровень)
        count = content.count("LLM_FORBIDDEN")
        assert count >= 6, f"LLM_FORBIDDEN встречается только {count} раз (ожидалось >= 6)"
