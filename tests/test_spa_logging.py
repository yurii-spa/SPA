"""
tests/test_spa_logging.py
25 unit tests for spa_core/utils/logging.py (MP-1531 v11.47)
"""
import io
import json
import logging
import os
import tempfile

import pytest

# Reset module-level logger state between tests
@pytest.fixture(autouse=True)
def reset_logging():
    """Clear all spa.* loggers before each test."""
    for name in list(logging.Logger.manager.loggerDict.keys()):
        if name.startswith("spa."):
            lgr = logging.getLogger(name)
            lgr.handlers.clear()
            lgr.propagate = False
    yield


from spa_core.utils.logging import SPALogger, get_logger


# ── helpers ────────────────────────────────────────────────────────────────

def capture_logger(component: str) -> tuple:
    """Returns (SPALogger, stream) where stream captures stderr JSON lines."""
    buf = io.StringIO()
    logger = SPALogger.__new__(SPALogger)
    logger.component = component
    logger.log_file = None
    logger._logger = logging.getLogger(f"spa.{component}.cap")
    logger._logger.handlers.clear()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger._logger.addHandler(handler)
    logger._logger.setLevel(logging.DEBUG)
    return logger, buf


def last_entry(buf: io.StringIO) -> dict:
    """Parse the last JSON line from buf."""
    buf.seek(0)
    lines = [l.strip() for l in buf.read().splitlines() if l.strip()]
    return json.loads(lines[-1])


# ── test 1: basic info ─────────────────────────────────────────────────────

def test_info_level_field():
    lg, buf = capture_logger("t1")
    lg.info("hello")
    entry = last_entry(buf)
    assert entry["level"] == "INFO"


# ── test 2: info message ───────────────────────────────────────────────────

def test_info_message_field():
    lg, buf = capture_logger("t2")
    lg.info("test message")
    entry = last_entry(buf)
    assert entry["message"] == "test message"


# ── test 3: component field ────────────────────────────────────────────────

def test_component_field():
    lg, buf = capture_logger("cycle_runner")
    lg.info("running")
    entry = last_entry(buf)
    assert entry["component"] == "cycle_runner"


# ── test 4: timestamp present ─────────────────────────────────────────────

def test_timestamp_present():
    lg, buf = capture_logger("t4")
    lg.info("ping")
    entry = last_entry(buf)
    assert "timestamp" in entry
    assert "T" in entry["timestamp"]  # ISO format


# ── test 5: timestamp is UTC ISO ──────────────────────────────────────────

def test_timestamp_utc_iso_format():
    import datetime
    lg, buf = capture_logger("t5")
    lg.info("ping")
    entry = last_entry(buf)
    ts = entry["timestamp"]
    # Must be parseable
    parsed = datetime.datetime.fromisoformat(ts)
    assert parsed is not None


# ── test 6: warning level ─────────────────────────────────────────────────

def test_warning_level_field():
    lg, buf = capture_logger("t6")
    lg.warning("bad thing")
    entry = last_entry(buf)
    assert entry["level"] == "WARNING"


# ── test 7: error level ───────────────────────────────────────────────────

def test_error_level_field():
    lg, buf = capture_logger("t7")
    lg.error("error!")
    entry = last_entry(buf)
    assert entry["level"] == "ERROR"


# ── test 8: critical level ────────────────────────────────────────────────

def test_critical_level_field():
    lg, buf = capture_logger("t8")
    lg.critical("critical!")
    entry = last_entry(buf)
    assert entry["level"] == "CRITICAL"


# ── test 9: debug level ───────────────────────────────────────────────────

def test_debug_level_field():
    lg, buf = capture_logger("t9")
    lg.debug("debug msg")
    entry = last_entry(buf)
    assert entry["level"] == "DEBUG"


# ── test 10: extra kwargs included ────────────────────────────────────────

def test_extra_kwargs_in_entry():
    lg, buf = capture_logger("t10")
    lg.info("cycle done", cycle_id=42, protocol="aave")
    entry = last_entry(buf)
    assert entry["cycle_id"] == 42
    assert entry["protocol"] == "aave"


# ── test 11: None kwargs filtered ─────────────────────────────────────────

def test_none_kwargs_filtered():
    lg, buf = capture_logger("t11")
    lg.info("msg", value=None, count=5)
    entry = last_entry(buf)
    assert "value" not in entry
    assert entry["count"] == 5


# ── test 12: output is valid JSON ─────────────────────────────────────────

def test_output_is_valid_json():
    lg, buf = capture_logger("t12")
    lg.info("test", data={"nested": [1, 2, 3]})
    buf.seek(0)
    raw = buf.read().strip()
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)


# ── test 13: audit method sets audit=True ────────────────────────────────

def test_audit_sets_audit_true():
    lg, buf = capture_logger("t13")
    lg.audit("REBALANCE", actor="cycle_runner")
    entry = last_entry(buf)
    assert entry["audit"] is True


# ── test 14: audit message prefixed with AUDIT: ──────────────────────────

def test_audit_message_prefix():
    lg, buf = capture_logger("t14")
    lg.audit("POSITION_CLOSED")
    entry = last_entry(buf)
    assert entry["message"].startswith("AUDIT: ")
    assert "POSITION_CLOSED" in entry["message"]


# ── test 15: audit actor field ───────────────────────────────────────────

def test_audit_actor_field():
    lg, buf = capture_logger("t15")
    lg.audit("GATE_CHECK", actor="risk_policy")
    entry = last_entry(buf)
    assert entry["actor"] == "risk_policy"


# ── test 16: audit default actor is system ───────────────────────────────

def test_audit_default_actor():
    lg, buf = capture_logger("t16")
    lg.audit("CYCLE_START")
    entry = last_entry(buf)
    assert entry["actor"] == "system"


# ── test 17: audit level is INFO ─────────────────────────────────────────

def test_audit_level_is_info():
    lg, buf = capture_logger("t17")
    lg.audit("SOMETHING")
    entry = last_entry(buf)
    assert entry["level"] == "INFO"


# ── test 18: audit extra kwargs ──────────────────────────────────────────

def test_audit_extra_kwargs():
    lg, buf = capture_logger("t18")
    lg.audit("TRADE", amount=1000.0, protocol="compound")
    entry = last_entry(buf)
    assert entry["amount"] == 1000.0
    assert entry["protocol"] == "compound"


# ── test 19: multiple messages produce multiple JSON lines ───────────────

def test_multiple_messages():
    lg, buf = capture_logger("t19")
    lg.info("first")
    lg.info("second")
    buf.seek(0)
    lines = [l.strip() for l in buf.read().splitlines() if l.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "first"
    assert json.loads(lines[1])["message"] == "second"


# ── test 20: get_logger factory ──────────────────────────────────────────

def test_get_logger_returns_spalogger():
    lg = get_logger("factory_test")
    assert isinstance(lg, SPALogger)
    assert lg.component == "factory_test"


# ── test 21: get_logger sets component ───────────────────────────────────

def test_get_logger_component():
    lg = get_logger("allocator")
    assert lg.component == "allocator"


# ── test 22: file logging ─────────────────────────────────────────────────

def test_file_logging():
    with tempfile.NamedTemporaryFile(mode='r', suffix='.log', delete=False) as f:
        fname = f.name
    try:
        lg = get_logger("file_test", log_file=fname)
        lg.info("written to file", run_id="abc")
        # Read back
        with open(fname) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert entry["message"] == "written to file"
        assert entry["run_id"] == "abc"
    finally:
        os.unlink(fname)


# ── test 23: two loggers different components ────────────────────────────

def test_two_loggers_different_components():
    lg1, buf1 = capture_logger("comp_a")
    lg2, buf2 = capture_logger("comp_b")
    lg1.info("from a")
    lg2.info("from b")
    e1 = last_entry(buf1)
    e2 = last_entry(buf2)
    assert e1["component"] == "comp_a"
    assert e2["component"] == "comp_b"


# ── test 24: required keys always present ────────────────────────────────

def test_required_keys_always_present():
    lg, buf = capture_logger("t24")
    for method in [lg.info, lg.warning, lg.error, lg.critical]:
        method("test")
    buf.seek(0)
    for line in buf.read().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        for key in ("timestamp", "level", "component", "message"):
            assert key in entry, f"Missing key {key} in {entry}"


# ── test 25: structured kwargs with list values ──────────────────────────

def test_structured_kwargs_list_values():
    lg, buf = capture_logger("t25")
    lg.info("positions update", protocols=["aave", "compound"], values=[50000, 30000])
    entry = last_entry(buf)
    assert entry["protocols"] == ["aave", "compound"]
    assert entry["values"] == [50000, 30000]
