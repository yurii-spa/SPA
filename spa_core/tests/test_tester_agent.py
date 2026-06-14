"""
Tests for TesterAgent (v2.5 — BL-003).

All tests are deterministic and offline: no real pytest invocations,
no network, no real DB. subprocess.run is monkeypatched everywhere.
The MessageBus is mocked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Make spa_core importable
_SPA_CORE = Path(__file__).parent.parent
if str(_SPA_CORE) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE))

from agents.tester_agent import TesterAgent  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Fake repo root with both tests dirs so _resolve_dirs is happy."""
    (tmp_path / "spa_core" / "tests").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "data").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def bus() -> MagicMock:
    b = MagicMock()
    b.publish = MagicMock(return_value="msg-id-456")
    return b


@pytest.fixture
def agent(bus: MagicMock, repo_root: Path) -> TesterAgent:
    return TesterAgent(bus=bus, repo_root=repo_root)


# ── parse_pytest_output tests ────────────────────────────────────────────────


def test_parse_summary_all_passed(agent: TesterAgent):
    stdout = (
        "============================= test session starts ==============================\n"
        "collected 200 items\n"
        "\n"
        "tests/test_foo.py ....................                                  [100%]\n"
        "\n"
        "============================== 200 passed in 8.91s =============================\n"
    )
    parsed = agent.parse_pytest_output(stdout)
    assert parsed["totals"]["passed"] == 200
    assert parsed["totals"]["failed"] == 0
    assert parsed["totals"].get("errors", 0) == 0
    assert parsed["totals"]["collected"] == 200
    assert parsed["duration_s"] == pytest.approx(8.91)
    assert parsed["failures"] == []


def test_parse_summary_with_failures(agent: TesterAgent):
    stdout = (
        "collected 200 items\n"
        "tests/test_foo.py F....\n"
        "FAILED tests/test_foo.py::test_thing - AssertionError: nope\n"
        "===================== 1 failed, 199 passed in 12.34s ======================\n"
    )
    parsed = agent.parse_pytest_output(stdout)
    assert parsed["totals"]["failed"] == 1
    assert parsed["totals"]["passed"] == 199
    assert parsed["duration_s"] == pytest.approx(12.34)
    # one failure captured
    assert len(parsed["failures"]) == 1
    assert parsed["failures"][0]["kind"] == "FAILED"
    assert parsed["failures"][0]["name"] == "tests/test_foo.py::test_thing"


def test_parse_summary_with_errors(agent: TesterAgent):
    stdout = (
        "collected 200 items\n"
        "ERROR tests/test_bad.py::test_setup\n"
        "===================== 1 error, 199 passed in 5.00s ======================\n"
    )
    parsed = agent.parse_pytest_output(stdout)
    assert parsed["totals"].get("errors", 0) == 1
    assert parsed["totals"]["passed"] == 199
    assert parsed["duration_s"] == pytest.approx(5.0)
    assert len(parsed["failures"]) == 1
    assert parsed["failures"][0]["kind"] == "ERROR"
    assert parsed["failures"][0]["name"] == "tests/test_bad.py::test_setup"


def test_parse_summary_empty_or_garbage(agent: TesterAgent):
    # Empty stdout → all zeros, no failures, no duration.
    parsed_empty = agent.parse_pytest_output("")
    assert parsed_empty["totals"]["passed"] == 0
    assert parsed_empty["totals"]["failed"] == 0
    assert parsed_empty["totals"]["collected"] == 0
    assert parsed_empty["failures"] == []
    assert parsed_empty["duration_s"] is None
    assert parsed_empty["summary_line"] is None

    # Garbage that doesn't match anything → also zeros.
    parsed_junk = agent.parse_pytest_output(
        "this is\nnot pytest\noutput at all 12345\n"
    )
    assert parsed_junk["totals"]["passed"] == 0
    assert parsed_junk["totals"]["failed"] == 0
    assert parsed_junk["failures"] == []
    assert parsed_junk["duration_s"] is None


def test_parse_pytest_output_extracts_failure_names(agent: TesterAgent):
    stdout = (
        "collected 5 items\n"
        "tests/test_a.py F.\n"
        "tests/test_b.py F.\n"
        "ERROR tests/test_c.py::TestThing::test_setup_method\n"
        "FAILED tests/test_a.py::test_one - AssertionError: boom\n"
        "FAILED tests/test_b.py::test_two - ValueError: nope\n"
        "============== 2 failed, 1 error, 2 passed in 1.23s ===============\n"
    )
    parsed = agent.parse_pytest_output(stdout)
    names = [f["name"] for f in parsed["failures"]]
    assert "tests/test_a.py::test_one" in names
    assert "tests/test_b.py::test_two" in names
    assert "tests/test_c.py::TestThing::test_setup_method" in names
    kinds = {f["kind"] for f in parsed["failures"]}
    assert kinds == {"FAILED", "ERROR"}
    assert parsed["totals"]["failed"] == 2
    assert parsed["totals"].get("errors", 0) == 1
    assert parsed["totals"]["passed"] == 2


# ── discover_tests / run_tests subprocess tests ──────────────────────────────


def test_discover_tests_uses_subprocess(agent: TesterAgent, monkeypatch):
    captured: dict = {}

    fake_stdout = (
        "spa_core/tests/test_foo.py::test_one\n"
        "spa_core/tests/test_foo.py::test_two\n"
        "tests/test_bar.py::TestClass::test_method\n"
        "\n"
        "3 tests collected in 0.05s\n"
    )

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout=fake_stdout, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    discovered = agent.discover_tests()
    # subprocess actually invoked
    assert "cmd" in captured
    # pytest --collect-only -q is the command shape
    assert "pytest" in captured["cmd"]
    assert "--collect-only" in captured["cmd"]
    assert "-q" in captured["cmd"]
    # 3 collected lines parsed
    assert len(discovered) == 3
    nodeids = [d["nodeid"] for d in discovered]
    assert "spa_core/tests/test_foo.py::test_one" in nodeids
    assert "tests/test_bar.py::TestClass::test_method" in nodeids
    # each entry has file + nodeid
    for d in discovered:
        assert d["file"].endswith(".py")
        assert "::" in d["nodeid"]


def test_run_tests_returns_dict_with_required_keys(
    agent: TesterAgent, monkeypatch
):
    fake_stdout = (
        "collected 3 items\n"
        "tests/test_x.py ...\n"
        "================== 3 passed in 0.42s ==================\n"
    )

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout=fake_stdout, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = agent.run_tests()
    for key in (
        "exit_code", "totals", "failures", "duration_s",
        "stdout_tail", "dirs", "cmd",
    ):
        assert key in result, f"missing key: {key}"
    assert result["exit_code"] == 0
    assert result["totals"]["passed"] == 3
    assert result["failures"] == []
    assert result["duration_s"] == pytest.approx(0.42)
    assert isinstance(result["dirs"], list)
    assert isinstance(result["cmd"], list)


# ── dump_report ──────────────────────────────────────────────────────────────


def test_dump_report_writes_valid_json(
    agent: TesterAgent, monkeypatch, tmp_path: Path
):
    fake_stdout = (
        "collected 1 items\n"
        "tests/test_y.py .\n"
        "================== 1 passed in 0.10s ==================\n"
    )

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout=fake_stdout, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    out_file = tmp_path / "tester_report.json"
    written = agent.dump_report(out_path=out_file)
    assert written == out_file
    assert out_file.exists()

    data = json.loads(out_file.read_text())
    assert "generated_at" in data
    assert data["agent"] == "tester_agent"
    assert "report" in data

    report = data["report"]
    for key in ("exit_code", "totals", "failures", "duration_s",
                "stdout_tail", "dirs", "cmd"):
        assert key in report


# ── run() publishes to bus ───────────────────────────────────────────────────


def test_run_publishes_to_bus(agent: TesterAgent, monkeypatch):
    fake_stdout = (
        "collected 2 items\n"
        "tests/test_z.py ..\n"
        "================== 2 passed in 0.20s ==================\n"
    )

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout=fake_stdout, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    msg_ids = agent.run()
    assert msg_ids == ["msg-id-456"]
    agent.bus.publish.assert_called_once()

    args, kwargs = agent.bus.publish.call_args
    topic = args[0] if args else kwargs.get("topic")
    sender = args[1] if len(args) > 1 else kwargs.get("sender")
    payload = args[2] if len(args) > 2 else kwargs.get("payload")

    assert topic == "tester.report"
    assert sender == "tester_agent"
    assert "report" in payload
    assert payload["report"]["totals"]["passed"] == 2
    assert payload["report"]["exit_code"] == 0
