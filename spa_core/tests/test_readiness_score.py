"""
Offline tests for SPA-V361 consolidated Go-Live readiness score
(spa_core/golive/readiness_score.py).

No network, no real state files. Component sources are monkeypatched so the
roll-up / worst-of / never-raise contract can be exercised deterministically.
"""
import json

import pytest

from spa_core.golive import readiness_score as rs


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _patch_components(monkeypatch, feed=None, mev=None, live=None):
    """Replace the three component helpers with controlled records."""
    if feed is not None:
        monkeypatch.setattr(rs, "_feed_health_component", lambda: dict(feed))
    if mev is not None:
        monkeypatch.setattr(rs, "_mev_coverage_component", lambda: dict(mev))
    if live is not None:
        monkeypatch.setattr(rs, "_live_apy_component", lambda: dict(live))


def _comp(key, score, status, **extra):
    rec = {"key": key, "label": key, "score": score, "status": status}
    rec.update(extra)
    return rec


# --------------------------------------------------------------------------
# document schema
# --------------------------------------------------------------------------

def test_document_top_level_keys_and_types():
    doc = rs.build_readiness_score_document()
    for key in (
        "schema_version",
        "generated_at",
        "overall_score",
        "overall_status",
        "components",
        "target_date",
    ):
        assert key in doc
    assert doc["schema_version"] == rs.SCHEMA_VERSION == 1
    assert isinstance(doc["generated_at"], str)
    assert doc["generated_at"].endswith("Z")
    assert isinstance(doc["overall_score"], float)
    assert doc["overall_status"] in rs._SEVERITY
    assert isinstance(doc["components"], list)
    assert doc["target_date"] == "2026-07-15"


def test_three_components_with_required_fields():
    doc = rs.build_readiness_score_document()
    assert len(doc["components"]) == 3
    keys = {c["key"] for c in doc["components"]}
    assert keys == {"feed_health", "mev_coverage", "live_apy"}
    for c in doc["components"]:
        assert "key" in c and "label" in c and "score" in c and "status" in c


def test_overall_score_within_bounds():
    doc = rs.build_readiness_score_document()
    assert 0.0 <= doc["overall_score"] <= 100.0


# --------------------------------------------------------------------------
# overall_score is the mean of component scores
# --------------------------------------------------------------------------

def test_overall_score_is_mean_of_components(monkeypatch):
    _patch_components(
        monkeypatch,
        feed=_comp("feed_health", 100, "ok"),
        mev=_comp("mev_coverage", 40, "degraded"),
        live=_comp("live_apy", 50, "warn"),
    )
    doc = rs.build_readiness_score_document()
    assert doc["overall_score"] == round((100 + 40 + 50) / 3, 1)


def test_overall_score_rounded_one_dp(monkeypatch):
    _patch_components(
        monkeypatch,
        feed=_comp("feed_health", 100, "ok"),
        mev=_comp("mev_coverage", 85.7, "ok"),
        live=_comp("live_apy", 50, "warn"),
    )
    doc = rs.build_readiness_score_document()
    assert doc["overall_score"] == round((100 + 85.7 + 50) / 3, 1)


# --------------------------------------------------------------------------
# worst-of overall_status logic
# --------------------------------------------------------------------------

def test_overall_status_all_ok(monkeypatch):
    _patch_components(
        monkeypatch,
        feed=_comp("feed_health", 100, "ok"),
        mev=_comp("mev_coverage", 100, "ok"),
        live=_comp("live_apy", 100, "ok"),
    )
    assert rs.build_readiness_score_document()["overall_status"] == "ok"


def test_overall_status_warn_when_any_warn(monkeypatch):
    _patch_components(
        monkeypatch,
        feed=_comp("feed_health", 100, "ok"),
        mev=_comp("mev_coverage", 100, "ok"),
        live=_comp("live_apy", 50, "warn"),
    )
    assert rs.build_readiness_score_document()["overall_status"] == "warn"


def test_overall_status_degraded_beats_warn(monkeypatch):
    _patch_components(
        monkeypatch,
        feed=_comp("feed_health", 0, "degraded"),
        mev=_comp("mev_coverage", 100, "ok"),
        live=_comp("live_apy", 50, "warn"),
    )
    assert rs.build_readiness_score_document()["overall_status"] == "degraded"


def test_overall_status_unknown_is_worst(monkeypatch):
    _patch_components(
        monkeypatch,
        feed=_comp("feed_health", 0, "degraded"),
        mev=_comp("mev_coverage", 0, "unknown"),
        live=_comp("live_apy", 50, "warn"),
    )
    assert rs.build_readiness_score_document()["overall_status"] == "unknown"


def test_worst_helper_empty_is_ok():
    assert rs._worst([]) == "ok"


# --------------------------------------------------------------------------
# component logic (real helpers, sources monkeypatched)
# --------------------------------------------------------------------------

def test_feed_health_maps_status_to_score(monkeypatch):
    import spa_core.alerts.feed_health_summary as fhs

    monkeypatch.setattr(
        fhs, "build_summary_document",
        lambda: {"overall_status": "warn", "counts": {"warn": 1}, "signal_count": 9},
    )
    rec = rs._feed_health_component()
    assert rec["status"] == "warn"
    assert rec["score"] == 60
    assert rec["counts"] == {"warn": 1}


def test_mev_coverage_status_thresholds(monkeypatch):
    import spa_core.execution.adapter_status as ast

    def _mk(pct):
        return lambda: {
            "mev_protection": {"coverage": {"coverage_pct": pct, "routed": 1, "total": 2}},
            "live_apy_enabled": False,
        }

    monkeypatch.setattr(ast, "build_status_document", _mk(90))
    assert rs._mev_coverage_component()["status"] == "ok"
    monkeypatch.setattr(ast, "build_status_document", _mk(60))
    assert rs._mev_coverage_component()["status"] == "warn"
    monkeypatch.setattr(ast, "build_status_document", _mk(10))
    assert rs._mev_coverage_component()["status"] == "degraded"


def test_live_apy_false_is_warn_50(monkeypatch):
    import spa_core.execution.adapter_status as ast

    monkeypatch.setattr(
        ast, "build_status_document",
        lambda: {"live_apy_enabled": False, "mev_protection": {"coverage": {}}},
    )
    rec = rs._live_apy_component()
    assert rec["status"] == "warn"
    assert rec["score"] == 50
    assert rec["live_apy_enabled"] is False


def test_live_apy_true_is_ok_100(monkeypatch):
    import spa_core.execution.adapter_status as ast

    monkeypatch.setattr(
        ast, "build_status_document",
        lambda: {"live_apy_enabled": True, "mev_protection": {"coverage": {}}},
    )
    rec = rs._live_apy_component()
    assert rec["status"] == "ok"
    assert rec["score"] == 100


# --------------------------------------------------------------------------
# never-raises
# --------------------------------------------------------------------------

def test_component_never_raises_on_source_failure(monkeypatch):
    import spa_core.alerts.feed_health_summary as fhs

    def _boom():
        raise RuntimeError("source exploded")

    monkeypatch.setattr(fhs, "build_summary_document", _boom)
    rec = rs._feed_health_component()
    assert rec["status"] == "unknown"
    assert rec["score"] == 0
    assert "error" in rec


def test_build_never_raises_when_all_sources_fail(monkeypatch):
    """Make every underlying source raise; the real helpers must swallow it and
    build must still return a valid document with all components unknown."""
    import spa_core.alerts.feed_health_summary as fhs
    import spa_core.execution.adapter_status as ast

    def _boom(*_a, **_k):
        raise RuntimeError("nope")

    monkeypatch.setattr(fhs, "build_summary_document", _boom)
    monkeypatch.setattr(ast, "build_status_document", _boom)
    doc = rs.build_readiness_score_document()
    assert doc["overall_status"] == "unknown"
    assert doc["overall_score"] == 0.0
    for c in doc["components"]:
        assert c["status"] == "unknown"
        assert c["score"] == 0
        assert "error" in c


# --------------------------------------------------------------------------
# JSON-serialisable
# --------------------------------------------------------------------------

def test_document_json_round_trips():
    doc = rs.build_readiness_score_document()
    s = json.dumps(doc)
    assert json.loads(s) == doc


def test_write_round_trips(tmp_path):
    out = tmp_path / "golive_readiness_score.json"
    doc = rs.write_readiness_score(str(out))
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == doc


# --------------------------------------------------------------------------
# SPA-V363 — persistent score history / trend (append_history)
# --------------------------------------------------------------------------

class TestAppendHistory:
    """append_history: compact append-only log, dedup, trim, never-raise."""

    def _doc(self, generated_at, score=72.5, status="warn"):
        return {
            "generated_at": generated_at,
            "overall_score": score,
            "overall_status": status,
            # extra keys that must NOT leak into the compact record:
            "components": [{"key": "feed_health"}],
            "schema_version": 1,
        }

    def test_first_call_creates_file_with_one_record(self, tmp_path):
        rs.append_history(self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        target = tmp_path / rs.HISTORY_FILENAME
        assert target.exists()
        history = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["overall_score"] == 72.5

    def test_second_distinct_timestamp_appends(self, tmp_path):
        rs.append_history(self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        rs.append_history(self._doc("2026-05-31T04:00:00Z", score=80.0),
                          data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / rs.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == 2
        assert history[-1]["overall_score"] == 80.0

    def test_same_timestamp_replaces_not_duplicates(self, tmp_path):
        rs.append_history(self._doc("2026-05-31T00:00:00Z", score=72.5),
                          data_dir=str(tmp_path))
        rs.append_history(self._doc("2026-05-31T00:00:00Z", score=99.9),
                          data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / rs.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == 1
        assert history[0]["overall_score"] == 99.9

    def test_trims_to_max_history_keeping_latest(self, tmp_path):
        n = rs.MAX_HISTORY + 25
        for i in range(n):
            rs.append_history(
                self._doc(f"2026-05-31T{i:05d}", score=float(i)),
                data_dir=str(tmp_path),
            )
        history = json.loads(
            (tmp_path / rs.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == rs.MAX_HISTORY
        # the most recent entry survives; the oldest were trimmed off the front
        assert history[-1]["overall_score"] == float(n - 1)
        assert history[0]["overall_score"] == float(n - rs.MAX_HISTORY)

    def test_never_raises_on_corrupt_existing_file(self, tmp_path):
        target = tmp_path / rs.HISTORY_FILENAME
        target.write_text("not json {{{", encoding="utf-8")
        # must not raise, and must overwrite with a valid single-record list
        rs.append_history(self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        history = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1

    def test_record_is_compact(self, tmp_path):
        rs.append_history(self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / rs.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert set(history[0].keys()) == {
            "generated_at", "overall_score", "overall_status"}

    def test_write_readiness_score_creates_main_and_history(self, tmp_path):
        out = tmp_path / "golive_readiness_score.json"
        doc = rs.write_readiness_score(str(out))
        assert out.exists()
        hist_file = tmp_path / rs.HISTORY_FILENAME
        assert hist_file.exists()
        history = json.loads(hist_file.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) >= 1
        assert history[-1]["overall_score"] == doc["overall_score"]
        assert history[-1]["generated_at"] == doc["generated_at"]


# --------------------------------------------------------------------------
# CLI smoke
# --------------------------------------------------------------------------

def test_cli_json_smoke(capsys):
    rc = rs._cli(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "overall_score" in parsed and "components" in parsed


def test_cli_write_smoke(tmp_path, capsys):
    out = tmp_path / "score.json"
    rc = rs._cli(["--write", str(out)])
    assert rc == 0
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == 1


# --------------------------------------------------------------------------
# SPA-V362 — wiring into the 4h export pipeline (export_data.py)
# Source-introspection (mirrors test_covariance_export.TestPipelineWiring):
# the readiness score must be regenerated each export cycle, registered in the
# files_written manifest, section-health tracked, and guarded by try/except.
# --------------------------------------------------------------------------

from pathlib import Path  # noqa: E402


def _pipeline_source() -> str:
    p = Path(__file__).resolve().parent.parent / "export_data.py"
    return p.read_text(encoding="utf-8")


def test_pipeline_imports_readiness_writer():
    src = _pipeline_source()
    assert "from golive.readiness_score import write_readiness_score" in src
    assert "write_readiness_score(" in src


def test_pipeline_writes_standard_path():
    src = _pipeline_source()
    assert "golive_readiness_score.json" in src


def test_pipeline_registers_in_manifest():
    src = _pipeline_source()
    assert '"golive_readiness_score.json"' in src


def test_pipeline_section_health_tracked():
    src = _pipeline_source()
    assert '_section_ok("golive_readiness_score")' in src
    assert '_section_fail("golive_readiness_score")' in src


def test_pipeline_call_is_guarded():
    """The readiness-score call sits inside a try/except (graceful section)."""
    src = _pipeline_source()
    idx = src.index("from golive.readiness_score import write_readiness_score")
    head = src[:idx]
    # A 'try:' must precede the import within the last few lines.
    assert any(line.strip() == "try:" for line in head.splitlines()[-4:])
    tail = src[idx:idx + 1200]
    assert "_section_fail(\"golive_readiness_score\")" in tail
