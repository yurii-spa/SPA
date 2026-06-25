"""
Тесты EPIC-5 S5.4 — DataTrust Gate v1.0.

Покрытие:
  - fail-closed: CB OPEN → allowed=False
  - fail-closed: CB HALF_OPEN (strict) → allowed=False
  - fail-closed: exception в check_circuit_breaker → allowed=False
  - fail-closed: exception в run_datatrust_gate → allowed=False
  - CB CLOSED → allowed=True
  - stale-файлы ниже порога → allowed=True (предупреждение)
  - stale-файлы >= 3 → allowed=False
  - Нет файлов → нет stale
  - LLM_FORBIDDEN — нет AI-импортов
  - GateResult поля + версия
  - Логирование (ring-buffer, атомарность)

LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
import json
import time
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _import_gate(project_root):
    """Добавляем корень проекта в sys.path один раз."""
    import sys
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


@pytest.fixture
def gate_module():
    from spa_core.data_trust import datatrust_gate as m
    return m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_cb(monkeypatch, gate_module, allowed: bool, reason: str):
    """Патчит check_circuit_breaker напрямую в gate_module."""
    monkeypatch.setattr(gate_module, "check_circuit_breaker", lambda: (allowed, reason))


def _patch_freshness(monkeypatch, gate_module, fresh: bool, stale: list):
    monkeypatch.setattr(gate_module, "check_data_freshness", lambda: (fresh, stale))


# ---------------------------------------------------------------------------
# 1. Circuit Breaker: fail-closed
# ---------------------------------------------------------------------------

class TestCircuitBreakerFailClosed:

    def test_cb_open_blocks(self, gate_module, monkeypatch):
        """CB OPEN → run_datatrust_gate возвращает allowed=False (fail-closed)."""
        _patch_cb(monkeypatch, gate_module, False, "circuit_breaker=OPEN")

        result = gate_module.run_datatrust_gate()

        assert result.allowed is False, "CB OPEN должен блокировать цикл"
        assert "OPEN" in result.reason
        assert result.circuit_state == "OPEN"
        assert result.LLM_FORBIDDEN is True

    def test_cb_half_open_strict_blocks(self, gate_module, monkeypatch):
        """CB HALF_OPEN (strict) → allowed=False."""
        _patch_cb(monkeypatch, gate_module, False, "circuit_breaker=HALF_OPEN (strict)")

        result = gate_module.run_datatrust_gate()

        assert result.allowed is False
        assert "HALF_OPEN" in result.reason

    def test_cb_error_fails_closed(self, gate_module, monkeypatch):
        """Ошибка в check_circuit_breaker → allowed=False (fail-closed)."""
        def _raise():
            raise RuntimeError("network error")
        monkeypatch.setattr(gate_module, "check_circuit_breaker", _raise)

        result = gate_module.run_datatrust_gate()

        assert result.allowed is False
        assert "exception" in result.reason.lower() or "error" in result.reason.lower()

    def test_run_exception_fails_closed(self, gate_module, monkeypatch):
        """Необработанное исключение в run_datatrust_gate → allowed=False."""
        def _raise():
            raise ValueError("unexpected crash")
        monkeypatch.setattr(gate_module, "check_circuit_breaker", _raise)

        result = gate_module.run_datatrust_gate()

        assert result.allowed is False, "Исключение должно давать fail-closed"
        assert result.LLM_FORBIDDEN is True


# ---------------------------------------------------------------------------
# 2. Circuit Breaker: happy path
# ---------------------------------------------------------------------------

class TestCircuitBreakerHappyPath:

    def test_cb_closed_allows(self, gate_module, monkeypatch):
        """CB CLOSED + нет stale → allowed=True."""
        _patch_cb(monkeypatch, gate_module, True, "circuit_breaker=CLOSED")
        _patch_freshness(monkeypatch, gate_module, True, [])

        result = gate_module.run_datatrust_gate()

        assert result.allowed is True
        assert result.circuit_state == "CLOSED"
        assert result.LLM_FORBIDDEN is True

    def test_cb_closed_with_few_stale_allows(self, gate_module, monkeypatch):
        """CB CLOSED + 1–2 stale (ниже порога) → allowed=True."""
        _patch_cb(monkeypatch, gate_module, True, "circuit_breaker=CLOSED")
        _patch_freshness(monkeypatch, gate_module, False, ["data/file1.json (age=5.0h > max=2h)"])

        result = gate_module.run_datatrust_gate()

        assert result.allowed is True
        assert len(result.stale_files) == 1


# ---------------------------------------------------------------------------
# 3. Data freshness
# ---------------------------------------------------------------------------

class TestDataFreshness:

    def test_no_files_no_stale(self, gate_module, monkeypatch, tmp_path):
        """Нет файлов → нет stale (новый проект)."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()

        fresh_ok, stale = gate_module.check_data_freshness()

        assert stale == []
        assert fresh_ok is True

    def test_fresh_file_is_ok(self, gate_module, monkeypatch, tmp_path):
        """Свежий файл → нет stale."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Создаём свежий файл
        f = data_dir / "paper_trading_status.json"
        f.write_text("{}")

        monkeypatch.setitem(
            gate_module.CRITICAL_DATA_FRESHNESS,
            "data/paper_trading_status.json",
            7200,
        )

        fresh_ok, stale = gate_module.check_data_freshness()
        assert stale == []

    def test_stale_file_detected(self, gate_module, monkeypatch, tmp_path):
        """Устаревший файл (mtime в далёком прошлом) → в stale."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            gate_module,
            "CRITICAL_DATA_FRESHNESS",
            {"data/paper_trading_status.json": 1},  # 1 секунда max
        )
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        f = data_dir / "paper_trading_status.json"
        f.write_text("{}")
        # Устанавливаем mtime в прошлое
        old_ts = time.time() - 100
        import os
        os.utime(f, (old_ts, old_ts))

        fresh_ok, stale = gate_module.check_data_freshness()
        assert len(stale) == 1
        assert "paper_trading_status.json" in stale[0]

    def test_three_stale_blocks_cycle(self, gate_module, monkeypatch):
        """3+ stale файла → allowed=False."""
        _patch_cb(monkeypatch, gate_module, True, "circuit_breaker=CLOSED")
        _patch_freshness(
            monkeypatch, gate_module, False,
            ["f1 (age=5.0h > max=2h)", "f2 (age=6.0h > max=4h)", "f3 (age=30.0h > max=24h)"],
        )

        result = gate_module.run_datatrust_gate()

        assert result.allowed is False
        assert "stale" in result.reason
        assert len(result.stale_files) == 3

    def test_two_stale_allows(self, gate_module, monkeypatch):
        """2 stale (< порога 3) → allowed=True."""
        _patch_cb(monkeypatch, gate_module, True, "circuit_breaker=CLOSED")
        _patch_freshness(
            monkeypatch, gate_module, False,
            ["f1 (age=5.0h > max=2h)", "f2 (age=6.0h > max=4h)"],
        )

        result = gate_module.run_datatrust_gate()

        assert result.allowed is True


# ---------------------------------------------------------------------------
# 4. GateResult structure
# ---------------------------------------------------------------------------

class TestGateResult:

    def test_gate_result_fields(self, gate_module, monkeypatch):
        """GateResult содержит все обязательные поля."""
        _patch_cb(monkeypatch, gate_module, True, "circuit_breaker=CLOSED")
        _patch_freshness(monkeypatch, gate_module, True, [])

        result = gate_module.run_datatrust_gate()

        assert hasattr(result, "allowed")
        assert hasattr(result, "reason")
        assert hasattr(result, "circuit_state")
        assert hasattr(result, "stale_files")
        assert hasattr(result, "checked_at")
        assert hasattr(result, "LLM_FORBIDDEN")

    def test_llm_forbidden_flag(self, gate_module, monkeypatch):
        """LLM_FORBIDDEN всегда True в GateResult."""
        _patch_cb(monkeypatch, gate_module, False, "circuit_breaker=OPEN")

        result = gate_module.run_datatrust_gate()
        assert result.LLM_FORBIDDEN is True

    def test_checked_at_is_iso(self, gate_module, monkeypatch):
        """checked_at имеет ISO-формат."""
        _patch_cb(monkeypatch, gate_module, True, "circuit_breaker=CLOSED")
        _patch_freshness(monkeypatch, gate_module, True, [])

        result = gate_module.run_datatrust_gate()

        # Должен быть парсинг без ошибок
        from datetime import datetime
        dt = datetime.strptime(result.checked_at, "%Y-%m-%dT%H:%M:%SZ")
        assert dt.year >= 2026

    def test_version_constant(self, gate_module):
        """DATATRUST_GATE_VERSION определена."""
        assert gate_module.DATATRUST_GATE_VERSION == "datatrust_gate_v1.0"


# ---------------------------------------------------------------------------
# 5. Logging
# ---------------------------------------------------------------------------

class TestLogging:

    def test_log_gate_result_no_crash(self, gate_module, monkeypatch, tmp_path):
        """log_gate_result не кидает исключение."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()

        gate_result = gate_module.GateResult(
            allowed=True,
            reason="test",
            circuit_state="CLOSED",
            stale_files=[],
            checked_at="2026-06-22T10:00:00Z",
        )
        gate_module.log_gate_result(gate_result)  # не должно кидать

    def test_log_creates_file(self, gate_module, monkeypatch, tmp_path):
        """После log_gate_result файл datatrust_gate_log.json создаётся."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()

        gate_result = gate_module.GateResult(
            allowed=False,
            reason="circuit_breaker=OPEN",
            circuit_state="OPEN",
            stale_files=[],
            checked_at="2026-06-22T10:00:00Z",
        )
        gate_module.log_gate_result(gate_result)

        log_path = tmp_path / "data" / "datatrust_gate_log.json"
        assert log_path.exists()
        data = json.loads(log_path.read_text())
        assert "entries" in data
        assert len(data["entries"]) == 1
        assert data["entries"][0]["allowed"] is False

    def test_log_ring_buffer(self, gate_module, monkeypatch, tmp_path):
        """Ring-buffer: после 200+ записей остаётся ровно 200."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()

        gate_result = gate_module.GateResult(
            allowed=True,
            reason="ok",
            circuit_state="CLOSED",
            stale_files=[],
            checked_at="2026-06-22T10:00:00Z",
        )
        for _ in range(205):
            gate_module.log_gate_result(gate_result)

        log_path = tmp_path / "data" / "datatrust_gate_log.json"
        data = json.loads(log_path.read_text())
        assert len(data["entries"]) == 200

    def test_run_gate_writes_log(self, gate_module, monkeypatch, tmp_path):
        """run_datatrust_gate автоматически пишет лог."""
        monkeypatch.setattr(gate_module, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()
        _patch_cb(monkeypatch, gate_module, False, "circuit_breaker=OPEN")

        gate_module.run_datatrust_gate()

        log_path = tmp_path / "data" / "datatrust_gate_log.json"
        assert log_path.exists()
        data = json.loads(log_path.read_text())
        assert data["last_result"]["allowed"] is False


# ---------------------------------------------------------------------------
# 6. LLM_FORBIDDEN — статический анализ файла
# ---------------------------------------------------------------------------

class TestLLMForbidden:

    def test_file_has_llm_forbidden_marker(self, project_root):
        """Файл datatrust_gate.py содержит маркер LLM_FORBIDDEN."""
        content = (
            project_root / "spa_core" / "data_trust" / "datatrust_gate.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_library_imports(self, project_root):
        """Нет импортов AI-библиотек."""
        content = (
            project_root / "spa_core" / "data_trust" / "datatrust_gate.py"
        ).read_text().lower()
        forbidden = ["openai", "anthropic", "gpt", "langchain", "transformers"]
        for term in forbidden:
            assert term not in content, f"Найден запрещённый импорт: {term}"

    def test_no_requests_or_http(self, project_root):
        """Нет внешних HTTP-библиотек (только stdlib)."""
        content = (
            project_root / "spa_core" / "data_trust" / "datatrust_gate.py"
        ).read_text()
        for lib in ["import requests", "import httpx", "import aiohttp", "import urllib3"]:
            assert lib not in content, f"Найдена внешняя зависимость: {lib}"


# ---------------------------------------------------------------------------
# 7. Integration: реальный circuit_breaker (CLOSED в нормальном режиме)
# ---------------------------------------------------------------------------

class TestRealCircuitBreaker:

    def test_real_cb_check_circuit_breaker(self, gate_module):
        """check_circuit_breaker работает с реальным circuit_breaker (CB в CLOSED)."""
        allowed, reason = gate_module.check_circuit_breaker()
        # В нормальном режиме CB должен быть CLOSED → allowed=True
        # Если CB OPEN — тест всё равно проверяет корректность возвращаемых типов
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)
        assert "circuit_breaker" in reason

    def test_real_run_datatrust_gate_returns_gate_result(self, gate_module):
        """run_datatrust_gate с реальным CB возвращает GateResult."""
        result = gate_module.run_datatrust_gate()
        assert isinstance(result, gate_module.GateResult)
        assert result.LLM_FORBIDDEN is True
        assert isinstance(result.stale_files, list)
