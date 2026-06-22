"""
Тесты EPIC-5 DataTrust S5.2: alarm.py + circuit_breaker.py

Покрытие:
  - Alarm создаётся при signal != "ok"
  - Circuit breaker CLOSED → OPEN после N consecutive alarms
  - fail-closed: OPEN → trading not allowed
  - HALF_OPEN → strict/non-strict
  - reset возвращает CLOSED
  - ring-buffer лога (100 записей)
  - LLM_FORBIDDEN маркеры в исходниках
  - Нет AI-зависимостей
"""
import pytest
import json
from pathlib import Path
from datetime import datetime


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def alarm_module(project_root, tmp_path):
    import sys
    sys.path.insert(0, str(project_root))
    import spa_core.data_trust.alarm as alarm_mod
    original = alarm_mod._ALARM_LOG
    alarm_mod._ALARM_LOG = tmp_path / "alarm_log.json"
    yield alarm_mod
    alarm_mod._ALARM_LOG = original


@pytest.fixture
def cb_module(project_root, tmp_path):
    import sys
    sys.path.insert(0, str(project_root))
    import spa_core.data_trust.circuit_breaker as cb_mod
    original = cb_mod._CB_STATE_FILE
    cb_mod._CB_STATE_FILE = tmp_path / "cb_state.json"
    yield cb_mod
    cb_mod._CB_STATE_FILE = original


# ──────────────────────────────────────────────────────────────────────────────
# alarm.py — тесты
# ──────────────────────────────────────────────────────────────────────────────

class TestAlarm:

    def test_no_alarm_on_ok(self, alarm_module):
        """signal="ok" → None"""
        result = alarm_module.process_validation_result("apy", "ok", "all good", send_telegram=False)
        assert result is None

    def test_alarm_on_stale(self, alarm_module):
        """signal="stale" → WARN alarm"""
        alarm = alarm_module.process_validation_result("apy", "stale", "data stale", send_telegram=False)
        assert alarm is not None
        assert alarm.signal == "stale"
        assert alarm.metric == "apy"
        assert alarm.level == alarm_module.AlarmLevel.WARN

    def test_alarm_on_missing(self, alarm_module):
        """signal="missing" → CRITICAL alarm"""
        alarm = alarm_module.process_validation_result("tvl_usd", "missing", "no data", send_telegram=False)
        assert alarm is not None
        assert alarm.level == alarm_module.AlarmLevel.CRITICAL
        assert alarm.signal == "missing"

    def test_alarm_on_divergent(self, alarm_module):
        """signal="divergent" → WARN alarm"""
        alarm = alarm_module.process_validation_result("apy", "divergent", "sources disagree", send_telegram=False)
        assert alarm is not None
        assert alarm.level == alarm_module.AlarmLevel.WARN

    def test_alarm_on_out_of_range(self, alarm_module):
        """signal="out_of_range" → CRITICAL alarm"""
        alarm = alarm_module.process_validation_result("apy", "out_of_range", "apy=999", send_telegram=False)
        assert alarm is not None
        assert alarm.level == alarm_module.AlarmLevel.CRITICAL

    def test_alarm_on_exit_signal(self, alarm_module):
        """signal="exit" (validator общий сигнал) → CRITICAL alarm"""
        alarm = alarm_module.process_validation_result("price", "exit", "fail-closed exit", send_telegram=False)
        assert alarm is not None
        assert alarm.level == alarm_module.AlarmLevel.CRITICAL

    def test_alarm_on_fail_closed(self, alarm_module):
        """signal="fail_closed" → CRITICAL alarm"""
        alarm = alarm_module.process_validation_result("apy", "fail_closed", "fail closed", send_telegram=False)
        assert alarm is not None
        assert alarm.level == alarm_module.AlarmLevel.CRITICAL

    def test_alarm_on_alarm_signal(self, alarm_module):
        """signal="alarm" (от validator) → WARN alarm"""
        alarm = alarm_module.process_validation_result("apy", "alarm", "divergence alarm", send_telegram=False)
        assert alarm is not None
        assert alarm.level == alarm_module.AlarmLevel.WARN

    def test_alarm_logged_to_file(self, alarm_module):
        """alarm пишется в log-файл"""
        alarm_module.process_validation_result("apy", "stale", "stale data", send_telegram=False)
        assert alarm_module._ALARM_LOG.exists()
        log = json.loads(alarm_module._ALARM_LOG.read_text())
        assert len(log["alarms"]) >= 1

    def test_alarm_has_id(self, alarm_module):
        """alarm_id начинается с DT-"""
        alarm = alarm_module.process_validation_result("apy", "stale", "stale", send_telegram=False)
        assert alarm.alarm_id.startswith("DT-")

    def test_alarm_has_created_at(self, alarm_module):
        """created_at — ISO timestamp"""
        alarm = alarm_module.process_validation_result("apy", "stale", "stale", send_telegram=False)
        assert "Z" in alarm.created_at or "T" in alarm.created_at

    def test_create_alarm_direct(self, alarm_module):
        """create_alarm() напрямую"""
        alarm = alarm_module.create_alarm("tvl_usd", "missing", "no data")
        assert alarm.metric == "tvl_usd"
        assert alarm.signal == "missing"
        assert alarm.source == "datatrust"

    def test_create_alarm_custom_level(self, alarm_module):
        """create_alarm() с явным уровнем"""
        alarm = alarm_module.create_alarm("apy", "info", "just fyi", level=alarm_module.AlarmLevel.INFO)
        assert alarm.level == alarm_module.AlarmLevel.INFO

    def test_log_has_version(self, alarm_module):
        """Лог содержит version"""
        alarm_module.create_alarm("apy", "stale", "test")
        log = json.loads(alarm_module._ALARM_LOG.read_text())
        assert log.get("version") == alarm_module.ALARM_VERSION

    def test_log_ring_buffer(self, alarm_module):
        """ring-buffer: не превышает 100 записей"""
        for i in range(110):
            alarm_module.create_alarm("apy", "stale", f"stale {i}")
        log = json.loads(alarm_module._ALARM_LOG.read_text())
        assert len(log["alarms"]) <= alarm_module._RING_BUFFER_SIZE

    def test_get_active_alarms_empty(self, alarm_module):
        """get_active_alarms() без алармов → пустой список"""
        alarms = alarm_module.get_active_alarms()
        assert isinstance(alarms, list)

    def test_get_active_alarms_after_create(self, alarm_module):
        """get_active_alarms() видит только что созданный alarm"""
        alarm_module.create_alarm("apy", "stale", "stale data")
        alarms = alarm_module.get_active_alarms(lookback_hours=1)
        assert len(alarms) >= 1

    def test_get_active_alarms_returns_dataalarmalarms(self, alarm_module):
        """get_active_alarms() возвращает DataAlarm объекты"""
        alarm_module.create_alarm("apy", "stale", "stale")
        alarms = alarm_module.get_active_alarms(lookback_hours=1)
        assert all(isinstance(a, alarm_module.DataAlarm) for a in alarms)

    def test_message_truncated_at_200(self, alarm_module):
        """Длинное сообщение обрезается до 200 символов"""
        long_msg = "x" * 300
        alarm = alarm_module.process_validation_result("apy", "stale", long_msg, send_telegram=False)
        assert len(alarm.message) <= 200

    def test_log_total_count(self, alarm_module):
        """total_count накапливается"""
        alarm_module.create_alarm("apy", "stale", "a")
        alarm_module.create_alarm("apy", "stale", "b")
        log = json.loads(alarm_module._ALARM_LOG.read_text())
        assert log.get("total_count", 0) >= 2


# ──────────────────────────────────────────────────────────────────────────────
# circuit_breaker.py — тесты
# ──────────────────────────────────────────────────────────────────────────────

class TestCircuitBreaker:

    def test_starts_closed(self, cb_module):
        """Без файла состояния — CLOSED (нормальная работа)"""
        status = cb_module.is_trading_allowed()
        assert status["allowed"] is True
        assert status["state"] == "CLOSED"

    def test_open_after_n_alarms(self, cb_module):
        """N consecutive alarms → OPEN → trading blocked"""
        n = cb_module.CONSECUTIVE_ALARMS_TO_OPEN
        for _ in range(n):
            cb_module.record_alarm("apy")

        status = cb_module.is_trading_allowed()
        assert status["allowed"] is False
        assert status["state"] == "OPEN"

    def test_less_than_n_alarms_stays_closed(self, cb_module):
        """N-1 alarm → остаётся CLOSED"""
        n = cb_module.CONSECUTIVE_ALARMS_TO_OPEN
        for _ in range(n - 1):
            cb_module.record_alarm("apy")

        status = cb_module.is_trading_allowed()
        assert status["allowed"] is True
        assert status["state"] == "CLOSED"

    def test_fail_closed_open_blocks(self, cb_module):
        """OPEN → trading NOT allowed (fail-closed)"""
        state = cb_module.load_state()
        state["state"] = "OPEN"
        state["consecutive_alarms"] = 3
        state["opened_at"] = datetime.utcnow().isoformat() + "Z"
        cb_module.save_state(state)

        result = cb_module.is_trading_allowed()
        assert result["allowed"] is False

    def test_fail_closed_unknown_state_blocks(self, cb_module):
        """Неизвестное состояние → FAIL_CLOSED → blocked"""
        state = cb_module.load_state()
        state["state"] = "UNKNOWN_STATE_XYZ"
        cb_module.save_state(state)

        result = cb_module.is_trading_allowed()
        assert result["allowed"] is False

    def test_reset_restores_closed(self, cb_module):
        """reset_circuit() → CLOSED → торговля разрешена"""
        for _ in range(cb_module.CONSECUTIVE_ALARMS_TO_OPEN):
            cb_module.record_alarm("apy")
        assert cb_module.is_trading_allowed()["allowed"] is False

        cb_module.reset_circuit()
        assert cb_module.is_trading_allowed()["allowed"] is True
        assert cb_module.is_trading_allowed()["state"] == "CLOSED"

    def test_llm_forbidden_in_state(self, cb_module):
        """is_trading_allowed() возвращает LLM_FORBIDDEN=True"""
        status = cb_module.is_trading_allowed()
        assert status.get("LLM_FORBIDDEN") is True

    def test_success_resets_counter_when_closed(self, cb_module):
        """record_success() при CLOSED → сбрасывает consecutive_alarms"""
        cb_module.record_alarm("apy")  # 1 alarm, не открывает
        state = cb_module.load_state()
        assert state["consecutive_alarms"] > 0

        # record_success при CLOSED → сброс
        cb_module.record_success()
        state2 = cb_module.load_state()
        assert state2["consecutive_alarms"] == 0

    def test_state_file_created(self, cb_module):
        """record_alarm() создаёт state файл"""
        cb_module.record_alarm("tvl_usd")
        assert cb_module._CB_STATE_FILE.exists()

    def test_state_file_is_valid_json(self, cb_module):
        """state файл — валидный JSON"""
        cb_module.record_alarm("apy")
        content = cb_module._CB_STATE_FILE.read_text()
        state = json.loads(content)
        assert "state" in state
        assert "consecutive_alarms" in state

    def test_state_has_version(self, cb_module):
        """state файл содержит version"""
        cb_module.record_alarm("apy")
        state = cb_module.load_state()
        assert state.get("version") == cb_module.CB_VERSION

    def test_half_open_strict_blocks(self, cb_module):
        """HALF_OPEN + strict=True → blocked"""
        state = cb_module.load_state()
        state["state"] = "HALF_OPEN"
        state["half_open_at"] = datetime.utcnow().isoformat() + "Z"
        cb_module.save_state(state)

        result = cb_module.is_trading_allowed(strict=True)
        assert result["allowed"] is False
        assert result["state"] == "HALF_OPEN"

    def test_half_open_non_strict_allows(self, cb_module):
        """HALF_OPEN + strict=False → allowed"""
        state = cb_module.load_state()
        state["state"] = "HALF_OPEN"
        state["half_open_at"] = datetime.utcnow().isoformat() + "Z"
        cb_module.save_state(state)

        result = cb_module.is_trading_allowed(strict=False)
        assert result["allowed"] is True
        assert result["state"] == "HALF_OPEN"

    def test_record_alarm_tracks_metric(self, cb_module):
        """record_alarm() сохраняет имя метрики"""
        cb_module.record_alarm("my_metric")
        state = cb_module.load_state()
        assert state.get("last_alarm_metric") == "my_metric"

    def test_get_status_returns_config(self, cb_module):
        """get_status() содержит конфигурацию"""
        status = cb_module.get_status()
        assert "config" in status
        cfg = status["config"]
        assert cfg["consecutive_alarms_to_open"] == cb_module.CONSECUTIVE_ALARMS_TO_OPEN
        assert cfg["recovery_hours"] == cb_module.RECOVERY_HOURS
        assert cfg["auto_close_hours"] == cb_module.AUTO_CLOSE_HOURS

    def test_get_status_llm_forbidden(self, cb_module):
        """get_status() содержит LLM_FORBIDDEN"""
        status = cb_module.get_status()
        assert status.get("LLM_FORBIDDEN") is True

    def test_reset_clears_alarm_count(self, cb_module):
        """После reset consecutive_alarms=0"""
        for _ in range(cb_module.CONSECUTIVE_ALARMS_TO_OPEN):
            cb_module.record_alarm("apy")

        cb_module.reset_circuit()
        state = cb_module.load_state()
        assert state["consecutive_alarms"] == 0

    def test_half_open_alarm_reopens(self, cb_module):
        """alarm в HALF_OPEN → откат в OPEN"""
        state = cb_module.load_state()
        state["state"] = "HALF_OPEN"
        state["consecutive_alarms"] = 2
        state["half_open_at"] = datetime.utcnow().isoformat() + "Z"
        cb_module.save_state(state)

        # Новый alarm в HALF_OPEN → OPEN
        cb_module.record_alarm("apy")
        result = cb_module.is_trading_allowed()
        assert result["allowed"] is False


# ──────────────────────────────────────────────────────────────────────────────
# LLM_FORBIDDEN — проверки исходников
# ──────────────────────────────────────────────────────────────────────────────

class TestLLMForbidden:

    def test_alarm_llm_forbidden_marker(self, project_root):
        """alarm.py содержит LLM_FORBIDDEN"""
        content = (project_root / "spa_core" / "data_trust" / "alarm.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_circuit_breaker_llm_forbidden_marker(self, project_root):
        """circuit_breaker.py содержит LLM_FORBIDDEN"""
        content = (project_root / "spa_core" / "data_trust" / "circuit_breaker.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_openai_in_alarm(self, project_root):
        """alarm.py не импортирует AI-библиотеки"""
        content = (project_root / "spa_core" / "data_trust" / "alarm.py").read_text().lower()
        for term in ("openai", "anthropic", "gpt", "langchain", "claude"):
            assert term not in content, f"AI term '{term}' found in alarm.py"

    def test_no_openai_in_circuit_breaker(self, project_root):
        """circuit_breaker.py не импортирует AI-библиотеки"""
        content = (project_root / "spa_core" / "data_trust" / "circuit_breaker.py").read_text().lower()
        for term in ("openai", "anthropic", "gpt", "langchain", "claude"):
            assert term not in content, f"AI term '{term}' found in circuit_breaker.py"

    def test_no_external_deps_in_alarm(self, project_root):
        """alarm.py использует только stdlib"""
        content = (project_root / "spa_core" / "data_trust" / "alarm.py").read_text()
        # Только allowed imports: stdlib + spa_core.alerts.telegram_client
        for banned in ("requests", "httpx", "aiohttp", "boto3", "pandas", "numpy"):
            assert banned not in content, f"External dep '{banned}' found in alarm.py"

    def test_no_external_deps_in_circuit_breaker(self, project_root):
        """circuit_breaker.py использует только stdlib"""
        content = (project_root / "spa_core" / "data_trust" / "circuit_breaker.py").read_text()
        for banned in ("requests", "httpx", "aiohttp", "boto3", "pandas", "numpy"):
            assert banned not in content, f"External dep '{banned}' found in circuit_breaker.py"

    def test_atomic_write_in_alarm(self, project_root):
        """alarm.py использует атомарную запись"""
        content = (project_root / "spa_core" / "data_trust" / "alarm.py").read_text()
        assert "os.replace" in content, "alarm.py должен использовать атомарную запись (os.replace)"

    def test_atomic_write_in_circuit_breaker(self, project_root):
        """circuit_breaker.py использует атомарную запись"""
        content = (project_root / "spa_core" / "data_trust" / "circuit_breaker.py").read_text()
        assert "os.replace" in content, "circuit_breaker.py должен использовать атомарную запись (os.replace)"
