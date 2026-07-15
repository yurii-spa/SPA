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
    assert doc["target_date"] == "2026-07-21"


def test_components_with_required_fields():
    # SPA-V364: four components now (three operational + informational schedule).
    doc = rs.build_readiness_score_document()
    assert len(doc["components"]) == 4
    keys = {c["key"] for c in doc["components"]}
    assert keys == {"feed_health", "mev_coverage", "live_apy", "schedule"}
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
    def _mk(pct):
        return lambda: {
            "mev_protection": {"coverage": {"coverage_pct": pct, "routed": 1, "total": 2}},
            "live_apy_enabled": False,
        }

    monkeypatch.setattr(rs, "_read_adapter_status_json", _mk(90))
    assert rs._mev_coverage_component()["status"] == "ok"
    monkeypatch.setattr(rs, "_read_adapter_status_json", _mk(60))
    assert rs._mev_coverage_component()["status"] == "warn"
    monkeypatch.setattr(rs, "_read_adapter_status_json", _mk(10))
    assert rs._mev_coverage_component()["status"] == "degraded"


def test_live_apy_false_is_warn_50(monkeypatch):
    monkeypatch.setattr(
        rs, "_read_adapter_status_json",
        lambda: {"live_apy_enabled": False, "mev_protection": {"coverage": {}}},
    )
    rec = rs._live_apy_component()
    assert rec["status"] == "warn"
    assert rec["score"] == 50
    assert rec["live_apy_enabled"] is False


def test_live_apy_true_is_ok_100(monkeypatch):
    monkeypatch.setattr(
        rs, "_read_adapter_status_json",
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

    def _boom(*_a, **_k):
        raise RuntimeError("nope")

    monkeypatch.setattr(fhs, "build_summary_document", _boom)
    monkeypatch.setattr(rs, "_read_adapter_status_json", _boom)
    doc = rs.build_readiness_score_document()
    assert doc["overall_status"] == "unknown"
    assert doc["overall_score"] == 0.0
    # overall_* are computed over the contributing operational components only;
    # all three sources blew up, so each must be unknown/0 with an error note.
    # The informational schedule component still computes fine and is excluded.
    for c in doc["components"]:
        if not c.get("contributes_to_overall"):
            continue
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
# SPA-V368 — persistent combined-gate history (append_combined_history)
# --------------------------------------------------------------------------

class TestAppendCombinedHistory:
    """append_combined_history: compact gate log, dedup, trim, never-raise."""

    def _doc(self, generated_at, gate="NO_GO",
             operational_status="warn", checklist_verdict="NOT_READY"):
        return {
            "generated_at": generated_at,
            "gate": gate,
            "operational_status": operational_status,
            "checklist_verdict": checklist_verdict,
            # extra keys that must NOT leak into the compact record:
            "blocking": ["checklist not_ready"],
            "schema_version": 1,
        }

    def test_first_call_creates_file_with_one_record(self, tmp_path):
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        target = tmp_path / rs.COMBINED_HISTORY_FILENAME
        assert target.exists()
        history = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1
        assert set(history[0].keys()) == {
            "generated_at", "gate", "operational_status", "checklist_verdict"}
        assert history[0]["gate"] == "NO_GO"

    def test_second_distinct_timestamp_appends(self, tmp_path):
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        rs.append_combined_history(
            self._doc("2026-05-31T04:00:00Z", gate="GO"), data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / rs.COMBINED_HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == 2
        assert history[-1]["gate"] == "GO"

    def test_same_timestamp_replaces_not_duplicates(self, tmp_path):
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z", gate="NO_GO"),
            data_dir=str(tmp_path))
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z", gate="GO"),
            data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / rs.COMBINED_HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == 1
        assert history[0]["gate"] == "GO"

    def test_trims_to_max_history_keeping_latest(self, tmp_path):
        n = rs.MAX_HISTORY + 25
        for i in range(n):
            rs.append_combined_history(
                self._doc(f"2026-05-31T{i:05d}",
                          gate=("GO" if i % 2 == 0 else "NO_GO")),
                data_dir=str(tmp_path),
            )
        history = json.loads(
            (tmp_path / rs.COMBINED_HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == rs.MAX_HISTORY
        assert history[-1]["generated_at"] == f"2026-05-31T{n - 1:05d}"
        assert history[0]["generated_at"] == f"2026-05-31T{n - rs.MAX_HISTORY:05d}"

    def test_never_raises_on_corrupt_existing_file(self, tmp_path):
        target = tmp_path / rs.COMBINED_HISTORY_FILENAME
        target.write_text("not json {{{", encoding="utf-8")
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        history = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1

    def test_missing_file_starts_empty(self, tmp_path):
        # no pre-existing file -> starts from empty list, single record written
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z"), data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / rs.COMBINED_HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert history == [{
            "generated_at": "2026-05-31T00:00:00Z",
            "gate": "NO_GO",
            "operational_status": "warn",
            "checklist_verdict": "NOT_READY",
        }]

    def test_never_raises_on_impossible_data_dir(self, tmp_path):
        # a data_dir whose parent is an existing FILE makes mkdir impossible;
        # the append must swallow it and never raise.
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        bad_dir = str(blocker / "subdir")  # blocker is a file, not a dir
        rs.append_combined_history(
            self._doc("2026-05-31T00:00:00Z"), data_dir=bad_dir)
        # nothing written, no exception
        assert not (blocker / "subdir").exists()

    def test_write_combined_gate_creates_main_and_history(self, tmp_path):
        out = tmp_path / rs.COMBINED_VERDICT_FILENAME
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        assert out.exists()
        hist_file = tmp_path / rs.COMBINED_HISTORY_FILENAME
        assert hist_file.exists()
        history = json.loads(hist_file.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) >= 1
        assert history[-1]["gate"] == doc["gate"]
        assert history[-1]["generated_at"] == doc["generated_at"]


# --------------------------------------------------------------------------
# SPA-V364 — informational schedule / countdown component
# --------------------------------------------------------------------------

class TestScheduleComponent:
    """schedule day-counter: informational, NOT part of the operational mean."""

    def test_record_shape_and_keys(self):
        rec = rs._schedule_component()
        for key in (
            "key", "label", "target_date", "days_to_golive",
            "contributes_to_overall", "scored", "status", "score",
        ):
            assert key in rec
        assert rec["key"] == "schedule"
        assert rec["label"] == "Days to go-live"
        assert rec["target_date"] == rs.TARGET_DATE == "2026-07-21"
        assert rec["contributes_to_overall"] is False
        assert rec["scored"] is False

    def test_days_to_golive_is_int_and_signed_per_formula(self):
        from datetime import datetime, timezone
        rec = rs._schedule_component()
        assert isinstance(rec["days_to_golive"], int)
        # The value must equal the signed formula (target - today). This is the real,
        # time-INVARIANT regression guard. It is deliberately NOT asserted to be > 0:
        # days_to_golive is a countdown that legitimately reaches 0 on the target day
        # and goes negative once the project clock passes a stale/hit TARGET_DATE. The
        # sign behaviour across future/today/overdue is fully covered by the monkeypatch
        # tests below (far_out / final_stretch / boundary_today / overdue). A hardcoded
        # `> 0` here was a time-bomb: it fired the day the clock reached TARGET_DATE
        # (2026-07-15), reddening CI for a countdown correctly hitting zero — not a
        # regression. (If the go-live target has genuinely moved, bump rs.TARGET_DATE.)
        target = datetime.strptime(rs.TARGET_DATE, "%Y-%m-%d").date()
        expected = (target - datetime.now(timezone.utc).date()).days
        assert rec["days_to_golive"] == expected

    def test_status_ok_when_far_out(self, monkeypatch):
        monkeypatch.setattr(rs, "TARGET_DATE", "2099-01-01")
        rec = rs._schedule_component()
        assert rec["days_to_golive"] > 14
        assert rec["status"] == "ok"
        assert rec["score"] == 100

    def test_status_warn_in_final_stretch(self, monkeypatch):
        from datetime import datetime, timezone, timedelta
        soon = (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()
        monkeypatch.setattr(rs, "TARGET_DATE", soon)
        rec = rs._schedule_component()
        assert 0 <= rec["days_to_golive"] <= 14
        assert rec["status"] == "warn"
        assert rec["score"] == 60

    def test_status_warn_at_boundary_today(self, monkeypatch):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        monkeypatch.setattr(rs, "TARGET_DATE", today)
        rec = rs._schedule_component()
        assert rec["days_to_golive"] == 0
        assert rec["status"] == "warn"

    def test_status_degraded_when_overdue(self, monkeypatch):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
        monkeypatch.setattr(rs, "TARGET_DATE", past)
        rec = rs._schedule_component()
        assert rec["days_to_golive"] < 0
        assert rec["status"] == "degraded"
        assert rec["score"] == 0

    def test_never_raises_on_broken_target_date(self, monkeypatch):
        monkeypatch.setattr(rs, "TARGET_DATE", "not-a-date")
        rec = rs._schedule_component()
        assert rec["status"] == "unknown"
        assert rec["score"] == 0
        assert rec["days_to_golive"] is None
        assert "error" in rec

    # ---- document-level integration ---------------------------------------

    def test_document_has_four_components_schedule_last(self):
        doc = rs.build_readiness_score_document()
        assert len(doc["components"]) == 4
        keys = [c["key"] for c in doc["components"]]
        assert keys[-1] == "schedule"
        assert set(keys) == {
            "feed_health", "mev_coverage", "live_apy", "schedule"}

    def test_exactly_three_contribute_to_overall(self):
        doc = rs.build_readiness_score_document()
        contributing = [c for c in doc["components"]
                        if c.get("contributes_to_overall")]
        assert len(contributing) == 3
        assert {c["key"] for c in contributing} == {
            "feed_health", "mev_coverage", "live_apy"}
        sched = next(c for c in doc["components"] if c["key"] == "schedule")
        assert sched["contributes_to_overall"] is False

    def test_schedule_does_not_shift_overall_score(self, monkeypatch):
        """overall_score is the mean of the 3 operational scores only — adding
        the schedule component (whatever its score) must not change it."""
        _patch_components(
            monkeypatch,
            feed=_comp("feed_health", 100, "ok"),
            mev=_comp("mev_coverage", 40, "degraded"),
            live=_comp("live_apy", 50, "warn"),
        )
        # schedule scores 100 (far-out date) — would drag mean upward if counted.
        monkeypatch.setattr(rs, "TARGET_DATE", "2099-01-01")
        doc = rs.build_readiness_score_document()
        assert doc["overall_score"] == round((100 + 40 + 50) / 3, 1)
        # explicitly NOT the mean of all four:
        assert doc["overall_score"] != round((100 + 40 + 50 + 100) / 4, 1)

    def test_overall_status_ignores_schedule(self, monkeypatch):
        """A degraded (overdue) schedule must not worsen overall_status when the
        three operational components are all ok."""
        _patch_components(
            monkeypatch,
            feed=_comp("feed_health", 100, "ok"),
            mev=_comp("mev_coverage", 100, "ok"),
            live=_comp("live_apy", 100, "ok"),
        )
        monkeypatch.setattr(rs, "TARGET_DATE", "2000-01-01")  # overdue -> degraded
        doc = rs.build_readiness_score_document()
        assert doc["overall_status"] == "ok"

    def test_top_level_days_to_golive_present(self):
        doc = rs.build_readiness_score_document()
        assert "days_to_golive" in doc
        sched = next(c for c in doc["components"] if c["key"] == "schedule")
        assert doc["days_to_golive"] == sched["days_to_golive"]

    def test_top_level_days_to_golive_none_when_schedule_breaks(self, monkeypatch):
        monkeypatch.setattr(rs, "TARGET_DATE", "garbage")
        doc = rs.build_readiness_score_document()
        # build must not raise and days_to_golive falls back to None.
        assert doc["days_to_golive"] is None


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
    # P3-8/P5-9: the former nested `_section_ok`/`_section_fail` helpers were
    # promoted to ExportContext methods (`ctx.section_ok`/`ctx.section_fail`).
    # Behaviour is identical — each export section's health is still recorded
    # under its section name; only the call spelling changed.
    assert 'ctx.section_ok("golive_readiness_score")' in src
    assert 'ctx.section_fail("golive_readiness_score")' in src


def test_pipeline_call_is_guarded():
    """The readiness-score call sits inside a try/except (graceful section)."""
    src = _pipeline_source()
    idx = src.index("from golive.readiness_score import write_readiness_score")
    head = src[:idx]
    # A 'try:' must precede the import within the last few lines.
    assert any(line.strip() == "try:" for line in head.splitlines()[-4:])
    tail = src[idx:idx + 1200]
    assert 'ctx.section_fail("golive_readiness_score")' in tail


# ─── SPA-V366: combined go/no-go gate (operational readiness + checklist) ─────
class TestCombinedGoLiveGate:
    """build_combined_golive_gate fuses the two independent go-live axes into one
    GO / NO_GO gate. Pure presentation-layer; never raises; does not mutate
    either source document."""

    def _score(self, status="ok", score=90.0):
        return {"overall_status": status, "overall_score": score}

    def _checklist(self, verdict="READY", passes=12, total=12):
        criteria = [
            {"name": "c%d" % i, "status": ("PASS" if i < passes else "FAIL")}
            for i in range(total)
        ]
        return {"verdict": verdict, "criteria": criteria}

    def test_go_only_when_operational_ok_and_checklist_ready(self):
        gate = rs.build_combined_golive_gate(
            self._score("ok"), self._checklist("READY", 12, 12)
        )
        assert gate["gate"] == "GO"
        assert gate["blocking"] == []
        assert gate["operational_status"] == "ok"
        assert gate["checklist_verdict"] == "READY"
        assert gate["criteria_passed"] == 12
        assert gate["criteria_total"] == 12

    def test_no_go_when_operational_not_ok(self):
        gate = rs.build_combined_golive_gate(
            self._score("warn"), self._checklist("READY", 12, 12)
        )
        assert gate["gate"] == "NO_GO"
        assert any("operational readiness warn" in b for b in gate["blocking"])
        assert not any("checklist" in b for b in gate["blocking"])

    def test_no_go_when_checklist_not_ready(self):
        gate = rs.build_combined_golive_gate(
            self._score("ok"), self._checklist("NOT_READY", 6, 12)
        )
        assert gate["gate"] == "NO_GO"
        assert gate["criteria_passed"] == 6
        assert any("checklist not_ready" in b for b in gate["blocking"])
        assert not any("operational" in b for b in gate["blocking"])

    def test_no_go_lists_both_axes_when_both_block(self):
        gate = rs.build_combined_golive_gate(
            self._score("degraded"), self._checklist("NOT_READY", 3, 12)
        )
        assert gate["gate"] == "NO_GO"
        assert len(gate["blocking"]) == 2

    def test_unknown_operational_status_is_not_go(self):
        gate = rs.build_combined_golive_gate(
            {"overall_status": "weird", "overall_score": 50},
            self._checklist("READY", 12, 12),
        )
        assert gate["operational_status"] == "unknown"
        assert gate["gate"] == "NO_GO"

    def test_both_none_is_safe_no_go(self):
        gate = rs.build_combined_golive_gate(None, None)
        assert gate["gate"] == "NO_GO"
        assert gate["operational_status"] == "unknown"
        assert gate["checklist_verdict"] is None
        # both axes are blocking (operational unknown + checklist unknown)
        assert len(gate["blocking"]) == 2

    def test_missing_criteria_list_keeps_counts_none(self):
        gate = rs.build_combined_golive_gate(
            self._score("ok"), {"verdict": "READY"}
        )
        assert gate["criteria_passed"] is None
        assert gate["criteria_total"] is None
        # verdict READY + operational ok -> GO even without criteria detail
        assert gate["gate"] == "GO"

    def test_does_not_mutate_inputs(self):
        score = self._score("ok")
        checklist = self._checklist("READY", 12, 12)
        score_copy = json.loads(json.dumps(score))
        checklist_copy = json.loads(json.dumps(checklist))
        rs.build_combined_golive_gate(score, checklist)
        assert score == score_copy
        assert checklist == checklist_copy

    def test_result_json_serialisable(self):
        gate = rs.build_combined_golive_gate(
            self._score("ok"), self._checklist("READY", 12, 12)
        )
        assert json.loads(json.dumps(gate))["gate"] == "GO"

    def test_verdict_case_insensitive(self):
        gate = rs.build_combined_golive_gate(
            self._score("ok"), {"verdict": "ready", "criteria": []}
        )
        assert gate["checklist_verdict"] == "READY"
        assert gate["gate"] == "GO"

    def test_in_all_exports(self):
        assert "build_combined_golive_gate" in rs.__all__


# ─── SPA-V367: persisted combined go/no-go gate (write_combined_golive_gate) ──
class TestWriteCombinedGoLiveGate:
    """write_combined_golive_gate reads the two already-emitted source documents
    from data_dir, runs build_combined_golive_gate over them and persists the
    result to golive_combined_verdict.json. Mirrors the SPA-V362 wiring of
    write_readiness_score. Missing/corrupt sources degrade to a safe NO_GO."""

    def _write_sources(self, d, op_status="warn", op_score=78.6,
                       verdict="NOT_READY", passes=6, total=12):
        score = {"overall_status": op_status, "overall_score": op_score}
        criteria = [
            {"name": "c%d" % i, "status": ("PASS" if i < passes else "FAIL")}
            for i in range(total)
        ]
        checklist = {"verdict": verdict, "criteria": criteria}
        (d / rs._SCORE_FILENAME).write_text(json.dumps(score), encoding="utf-8")
        (d / rs._CHECKLIST_FILENAME).write_text(
            json.dumps(checklist), encoding="utf-8"
        )

    def test_writes_file_and_returns_doc(self, tmp_path):
        self._write_sources(tmp_path)
        out = tmp_path / "golive_combined_verdict.json"
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        assert out.exists()
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk == doc

    def test_doc_carries_schema_and_timestamp(self, tmp_path):
        self._write_sources(tmp_path)
        out = tmp_path / "golive_combined_verdict.json"
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        assert doc["schema_version"] == rs.SCHEMA_VERSION
        assert isinstance(doc["generated_at"], str) and doc["generated_at"]
        # carries the gate fields through
        assert doc["gate"] in ("GO", "NO_GO")
        assert "blocking" in doc and "operational_status" in doc

    def test_gate_no_go_from_warn_plus_not_ready(self, tmp_path):
        self._write_sources(tmp_path, op_status="warn", verdict="NOT_READY",
                            passes=6, total=12)
        out = tmp_path / "golive_combined_verdict.json"
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        assert doc["gate"] == "NO_GO"
        assert doc["criteria_passed"] == 6
        assert doc["criteria_total"] == 12
        assert len(doc["blocking"]) == 2

    def test_gate_go_from_ok_plus_ready(self, tmp_path):
        self._write_sources(tmp_path, op_status="ok", verdict="READY",
                            passes=12, total=12)
        out = tmp_path / "golive_combined_verdict.json"
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        assert doc["gate"] == "GO"
        assert doc["blocking"] == []

    def test_missing_sources_safe_no_go(self, tmp_path):
        # no source files written at all
        out = tmp_path / "golive_combined_verdict.json"
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        assert out.exists()
        assert doc["gate"] == "NO_GO"
        assert doc["operational_status"] == "unknown"
        assert doc["checklist_verdict"] is None

    def test_corrupt_source_degrades_not_raises(self, tmp_path):
        (tmp_path / rs._SCORE_FILENAME).write_text("{not json", encoding="utf-8")
        (tmp_path / rs._CHECKLIST_FILENAME).write_text("[]", encoding="utf-8")
        out = tmp_path / "golive_combined_verdict.json"
        doc = rs.write_combined_golive_gate(str(out), data_dir=str(tmp_path))
        # corrupt score -> None -> unknown; list (non-dict) checklist -> None
        assert doc["gate"] == "NO_GO"
        assert doc["operational_status"] == "unknown"

    def test_default_out_path_uses_data_dir(self, tmp_path):
        self._write_sources(tmp_path)
        # out_path omitted -> <data_dir>/COMBINED_VERDICT_FILENAME
        doc = rs.write_combined_golive_gate(data_dir=str(tmp_path))
        target = tmp_path / rs.COMBINED_VERDICT_FILENAME
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == doc

    def test_does_not_mutate_source_files(self, tmp_path):
        self._write_sources(tmp_path)
        before_score = (tmp_path / rs._SCORE_FILENAME).read_text(encoding="utf-8")
        before_chk = (tmp_path / rs._CHECKLIST_FILENAME).read_text(encoding="utf-8")
        rs.write_combined_golive_gate(
            str(tmp_path / "golive_combined_verdict.json"), data_dir=str(tmp_path)
        )
        assert (tmp_path / rs._SCORE_FILENAME).read_text(encoding="utf-8") == before_score
        assert (tmp_path / rs._CHECKLIST_FILENAME).read_text(encoding="utf-8") == before_chk

    def test_in_all_exports(self):
        assert "write_combined_golive_gate" in rs.__all__
        assert "COMBINED_VERDICT_FILENAME" in rs.__all__


# ─── SPA-V367: export pipeline wiring of write_combined_golive_gate ───────────
def test_pipeline_imports_combined_gate_writer():
    src = _pipeline_source()
    assert "from golive.readiness_score import write_combined_golive_gate" in src
    assert "write_combined_golive_gate(" in src


def test_pipeline_writes_combined_verdict_path():
    src = _pipeline_source()
    assert "golive_combined_verdict.json" in src


def test_pipeline_registers_combined_in_manifest():
    src = _pipeline_source()
    assert '"golive_combined_verdict.json"' in src


def test_pipeline_combined_section_health_tracked():
    src = _pipeline_source()
    # P3-8/P5-9: nested `_section_ok`/`_section_fail` -> ExportContext methods
    # (`ctx.section_ok`/`ctx.section_fail`). Same section-health tracking,
    # different call spelling.
    assert 'ctx.section_ok("golive_combined_verdict")' in src
    assert 'ctx.section_fail("golive_combined_verdict")' in src


def test_pipeline_combined_call_is_guarded():
    src = _pipeline_source()
    idx = src.index(
        "from golive.readiness_score import write_combined_golive_gate"
    )
    head = src[:idx]
    assert any(line.strip() == "try:" for line in head.splitlines()[-4:])
    tail = src[idx:idx + 1200]
    assert 'ctx.section_fail("golive_combined_verdict")' in tail


def test_pipeline_combined_runs_after_readiness_score():
    """The combined gate consumes golive_readiness_score.json, so its writer
    must be wired AFTER the readiness-score writer in the export pipeline."""
    src = _pipeline_source()
    i_score = src.index("write_readiness_score(")
    i_gate = src.index("write_combined_golive_gate(")
    assert i_score < i_gate
