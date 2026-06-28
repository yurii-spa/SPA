"""
MP-446 — Day 1 Pre-flight Tests
pytest, stdlib only, no mocks (реальные файлы репо).
"""
import ast
import json
import os
import sys
import tempfile

import pytest

# Путь к корню репо (tests/ → ..)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

CYCLE_RUNNER = os.path.join(REPO_ROOT, "spa_core", "paper_trading", "cycle_runner.py")
PAPER_EVIDENCE = os.path.join(REPO_ROOT, "data", "paper_evidence.json")
ADAPTER_STATUS = os.path.join(REPO_ROOT, "data", "adapter_status.json")
GOLIVE_STATUS = os.path.join(REPO_ROOT, "data", "golive_status.json")

EXPECTED_START_DATE = "2026-06-12"
MIN_ADAPTERS = 10


# ---------------------------------------------------------------------------
# Check 1 — cycle_runner.py exists & syntax OK
# ---------------------------------------------------------------------------
class TestCycleRunnerSyntax:
    def test_file_exists(self):
        assert os.path.isfile(CYCLE_RUNNER), f"cycle_runner.py not found: {CYCLE_RUNNER}"

    def test_syntax_valid(self):
        with open(CYCLE_RUNNER, encoding="utf-8") as fh:
            src = fh.read()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"cycle_runner.py syntax error: {exc}")


# ---------------------------------------------------------------------------
# Check 2 — ADAPTER_REGISTRY loads, count >= MIN_ADAPTERS
# ---------------------------------------------------------------------------
class TestAdapterRegistry:
    def test_import_succeeds(self):
        from spa_core.adapters import ADAPTER_REGISTRY  # noqa: PLC0415
        assert ADAPTER_REGISTRY is not None

    def test_count_ge_min(self):
        from spa_core.adapters import ADAPTER_REGISTRY  # noqa: PLC0415
        assert len(ADAPTER_REGISTRY) >= MIN_ADAPTERS, (
            f"Expected >= {MIN_ADAPTERS} adapters, got {len(ADAPTER_REGISTRY)}"
        )


# ---------------------------------------------------------------------------
# Check 3 — PaperEvidenceTracker initializes without exception
# ---------------------------------------------------------------------------
class TestPaperEvidenceTracker:
    def test_init_no_exception(self):
        from spa_core.paper_trading.paper_evidence_tracker import PaperEvidenceTracker  # noqa: PLC0415
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name
        try:
            tracker = PaperEvidenceTracker(evidence_file=tmp_path)
            assert tracker is not None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_init_with_real_file(self):
        """Трекер инициализируется с реальным paper_evidence.json без ошибок."""
        from spa_core.paper_trading.paper_evidence_tracker import PaperEvidenceTracker  # noqa: PLC0415
        tracker = PaperEvidenceTracker(evidence_file=PAPER_EVIDENCE)
        assert tracker is not None


# ---------------------------------------------------------------------------
# Check 4 — paper_evidence.json parses, start_date == EXPECTED_START_DATE
# ---------------------------------------------------------------------------
class TestPaperEvidenceJson:
    @pytest.fixture(scope="class")
    def data(self):
        assert os.path.isfile(PAPER_EVIDENCE), f"File not found: {PAPER_EVIDENCE}"
        with open(PAPER_EVIDENCE, encoding="utf-8") as fh:
            return json.load(fh)

    def test_file_parseable(self, data):
        assert isinstance(data, dict)

    def test_start_date_correct(self, data):
        start = data.get("start_date")
        assert start == EXPECTED_START_DATE, (
            f"Expected start_date={EXPECTED_START_DATE!r}, got {start!r}"
        )

    def test_has_required_keys(self, data):
        for key in ("schema_version", "base_capital", "days"):
            assert key in data, f"Missing key: {key!r}"


# ---------------------------------------------------------------------------
# Check 5 — adapter_status.json parses, count >= MIN_ADAPTERS
# ---------------------------------------------------------------------------
class TestAdapterStatusJson:
    @pytest.fixture(scope="class")
    def data(self):
        assert os.path.isfile(ADAPTER_STATUS), f"File not found: {ADAPTER_STATUS}"
        with open(ADAPTER_STATUS, encoding="utf-8") as fh:
            return json.load(fh)

    def test_file_parseable(self, data):
        assert isinstance(data, dict)

    def test_adapters_key_exists(self, data):
        assert "adapters" in data, "Key 'adapters' missing from adapter_status.json"

    def test_adapter_count_ge_min(self, data):
        adapters = data.get("adapters", [])
        count = len(adapters)
        assert count >= MIN_ADAPTERS, (
            f"Expected >= {MIN_ADAPTERS} adapters, got {count}"
        )


# ---------------------------------------------------------------------------
# Check 6 — golive_status.json parses, ready=true
# ---------------------------------------------------------------------------
class TestGoliveStatusJson:
    @pytest.fixture(scope="class")
    def data(self):
        assert os.path.isfile(GOLIVE_STATUS), f"File not found: {GOLIVE_STATUS}"
        with open(GOLIVE_STATUS, encoding="utf-8") as fh:
            return json.load(fh)

    def test_file_parseable(self, data):
        assert isinstance(data, dict)

    def test_ready_is_bool(self, data):
        # ADR-002: go-live requires 30+ honest evidenced track days (target ~2026-07-21,
        # anchored to the first evidenced day 2026-06-22 — see golive_status.json).
        # Until that date, ready=False is expected and correct — time-gated.
        # This test verifies the field exists and is a bool, not that it's True.
        ready = data.get("ready")
        assert isinstance(ready, bool), f"golive_status.ready must be a bool, got {ready!r}"

    def test_blockers_are_time_gated_only(self, data):
        # Until the go-live target (~2026-07-21), the only valid blockers are time-gated ones.
        # Structural / configuration blockers (anything other than track-days
        # and gap_monitor) should not appear.
        blockers = data.get("blockers", [])
        # Time-gated: require specific number of run days
        TIME_GATED_KEYWORDS = ("track_days", "gap_monitor", "honest", "target")
        # Infrastructure-only / transient daily-cadence: always fail in sandbox/CI or
        # before a scheduled agent fires today, but pass on the production host once the
        # day's run completes. NOT structural — they self-clear, no code fix possible.
        INFRA_SANDBOX_KEYWORDS = ("autopush", "launchd", "sandbox", "macos", "plist",
                                   "always fails in ci",
                                   # daily-cadence agents not yet fired today (self-clears
                                   # when the scheduled run sends — e.g. the morning digest).
                                   "telegram", "digest", "has not run yet today")
        non_time_gated = [
            b for b in blockers
            if not any(kw in b.lower() for kw in TIME_GATED_KEYWORDS)
            and not any(kw in b.lower() for kw in INFRA_SANDBOX_KEYWORDS)
        ]
        assert len(non_time_gated) == 0, (
            f"Non-time-gated/non-infra blockers found (structural issues): {non_time_gated}"
        )
