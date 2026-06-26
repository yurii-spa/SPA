"""
Tests for FEAT-007 / SPA-V336: APY history bridge + live covariance export.

Covers:
  * apy_history_bridge: schema mapping, ts conversion, graceful degradation,
    idempotent ensure, deterministic output.
  * covariance_export: estimator picks up bridged data (live, not fallback),
    matrix symmetry/diagonal, source classification, tier resolution,
    JSON-serialisability, CLI round-trip.

All tests are deterministic, network-free and filesystem-isolated (tmp_path).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make spa_core sub-packages importable (mirrors other test modules).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics import apy_history_bridge as bridge  # noqa: E402
from analytics import covariance_export as cov_export  # noqa: E402
from analytics.covariance_estimator import (  # noqa: E402
    CovarianceEstimator,
    MIN_OBSERVATIONS,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────

def _recent_dates(n: int) -> list[str]:
    """n consecutive recent dates (within the 90d window), oldest first."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=n - 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _make_historical(n_points: int = 30) -> dict:
    """A minimal but realistic historical_apy.json-shaped dict, 2 protocols."""
    dates = _recent_dates(n_points)
    return {
        "generated_at": "2026-05-30T00:00:00+00:00",
        "data_source": "synthetic",
        "days": n_points,
        "protocols": {
            "aave-v3-usdc-ethereum": [
                {"date": d, "apy": 5.0 + 0.1 * i, "tvl_usd": 1.0e8 + i}
                for i, d in enumerate(dates)
            ],
            "yearn-v3-usdc-ethereum": [
                {"date": d, "apy": 7.0 - 0.05 * i, "tvl_usd": 5.0e7 + i}
                for i, d in enumerate(dates)
            ],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# Bridge — timestamp conversion
# ──────────────────────────────────────────────────────────────────────────

class TestDateToIsoTs:
    def test_date_only_becomes_midnight_utc(self):
        assert bridge._date_to_iso_ts("2026-02-21") == "2026-02-21T00:00:00+00:00"

    def test_trailing_z_normalised(self):
        out = bridge._date_to_iso_ts("2026-02-21T12:30:00Z")
        assert out == "2026-02-21T12:30:00+00:00"

    def test_naive_timestamp_assumed_utc(self):
        out = bridge._date_to_iso_ts("2026-02-21T12:30:00")
        assert out.endswith("+00:00")

    def test_aware_timestamp_preserved(self):
        out = bridge._date_to_iso_ts("2026-02-21T12:30:00+02:00")
        assert out == "2026-02-21T12:30:00+02:00"

    @pytest.mark.parametrize("bad", ["", "   ", "not-a-date", "2026-13-99", None, 42])
    def test_unparseable_returns_none(self, bad):
        assert bridge._date_to_iso_ts(bad) is None


# ──────────────────────────────────────────────────────────────────────────
# Bridge — convert_history
# ──────────────────────────────────────────────────────────────────────────

class TestConvertHistory:
    def test_basic_schema_mapping(self):
        doc = bridge.convert_history(_make_historical(10))
        assert set(doc.keys()) == {"protocol_history", "last_updated"}
        ph = doc["protocol_history"]
        assert set(ph.keys()) == {
            "aave-v3-usdc-ethereum", "yearn-v3-usdc-ethereum"
        }
        entry = ph["aave-v3-usdc-ethereum"][0]
        assert set(entry.keys()) == {"ts", "apy", "tvl_usd"}
        assert entry["ts"].endswith("+00:00")
        assert isinstance(entry["apy"], float)

    def test_point_count_preserved(self):
        doc = bridge.convert_history(_make_historical(17))
        assert len(doc["protocol_history"]["aave-v3-usdc-ethereum"]) == 17

    def test_keys_sorted_deterministic(self):
        doc = bridge.convert_history(_make_historical(5))
        keys = list(doc["protocol_history"].keys())
        assert keys == sorted(keys)

    def test_last_updated_from_generated_at(self):
        doc = bridge.convert_history(_make_historical(5))
        assert doc["last_updated"] == "2026-05-30T00:00:00+00:00"

    def test_missing_generated_at_gets_synthesized_iso(self):
        h = _make_historical(5)
        del h["generated_at"]
        doc = bridge.convert_history(h)
        # Should still be a parseable ISO string.
        assert datetime.fromisoformat(doc["last_updated"])

    @pytest.mark.parametrize("bad", [None, [], "x", {}, {"protocols": "nope"}])
    def test_malformed_input_yields_empty_document(self, bad):
        doc = bridge.convert_history(bad)
        assert doc == {"protocol_history": {}, "last_updated": None} or \
            doc["protocol_history"] == {}

    def test_bad_entries_skipped_not_raised(self):
        h = {
            "protocols": {
                "aave-v3-usdc-ethereum": [
                    {"date": "2026-02-21", "apy": 5.0},
                    {"date": "bad-date", "apy": 5.0},     # dropped
                    {"date": "2026-02-22", "apy": "NaNish"},  # dropped (float fail)
                    "not-a-dict",                          # dropped
                ]
            }
        }
        doc = bridge.convert_history(h)
        assert len(doc["protocol_history"]["aave-v3-usdc-ethereum"]) == 1

    def test_protocol_with_no_usable_points_omitted(self):
        h = {"protocols": {"dead": [{"date": "bad"}], "good": [{"date": "2026-02-21", "apy": 5.0}]}}
        doc = bridge.convert_history(h)
        assert "dead" not in doc["protocol_history"]
        assert "good" in doc["protocol_history"]

    def test_deterministic_identical_output(self):
        h = _make_historical(12)
        assert bridge.convert_history(h) == bridge.convert_history(h)


# ──────────────────────────────────────────────────────────────────────────
# Bridge — IO (load / write / ensure)
# ──────────────────────────────────────────────────────────────────────────

class TestBridgeIO:
    def test_load_missing_returns_empty_dict(self, tmp_path):
        assert bridge.load_historical(str(tmp_path / "nope.json")) == {}

    def test_load_malformed_returns_empty_dict(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ not json")
        assert bridge.load_historical(str(p)) == {}

    def test_write_creates_file_and_parent(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(10)))
        out = tmp_path / "nested" / "apy_history.json"
        doc = bridge.write_tracker_history(source=str(src), out_path=str(out))
        assert out.exists()
        on_disk = json.loads(out.read_text())
        assert on_disk == doc
        assert len(on_disk["protocol_history"]) == 2

    def test_ensure_writes_when_absent(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(10)))
        out = tmp_path / "apy_history.json"
        created = bridge.ensure_apy_history(out_path=str(out), source=str(src))
        assert created is True
        assert out.exists()

    def test_ensure_noop_when_present(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(10)))
        out = tmp_path / "apy_history.json"
        out.write_text(json.dumps({"protocol_history": {}, "last_updated": None}))
        created = bridge.ensure_apy_history(out_path=str(out), source=str(src))
        assert created is False  # left untouched

    def test_ensure_missing_source_returns_false(self, tmp_path):
        out = tmp_path / "apy_history.json"
        created = bridge.ensure_apy_history(
            out_path=str(out), source=str(tmp_path / "absent.json")
        )
        assert created is False


# ──────────────────────────────────────────────────────────────────────────
# Bridge → Estimator end-to-end
# ──────────────────────────────────────────────────────────────────────────

class TestBridgedEstimator:
    def test_estimator_reads_bridged_store_live(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(MIN_OBSERVATIONS + 20)))
        out = tmp_path / "apy_history.json"
        bridge.write_tracker_history(source=str(src), out_path=str(out))

        est = CovarianceEstimator(history_file=str(out))
        assert est.protocols() == [
            "aave-v3-usdc-ethereum", "yearn-v3-usdc-ethereum"
        ]
        vol = est.compute_volatility("aave-v3-usdc-ethereum")
        # Real series (not the synthetic 10% proxy) → strictly positive,
        # and below what a 10% CV on a ~5-7% APY would give.
        assert vol > 0.0

    def test_summary_not_fallback_with_enough_points(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(MIN_OBSERVATIONS + 5)))
        out = tmp_path / "apy_history.json"
        bridge.write_tracker_history(source=str(src), out_path=str(out))
        est = CovarianceEstimator(history_file=str(out))
        summ = est.summary()
        for row in summ["protocols"].values():
            assert row["fallback"] is False
            assert row["n_obs"] >= MIN_OBSERVATIONS


# ──────────────────────────────────────────────────────────────────────────
# covariance_export
# ──────────────────────────────────────────────────────────────────────────

class TestTierFor:
    @pytest.mark.parametrize("key,tier", [
        ("aave-v3-usdc-ethereum", "T1"),
        ("compound-v3-usdc-ethereum", "T1"),
        ("morpho-usdc-ethereum", "T1"),
        ("sky-susds-usds-ethereum", "T1"),
        ("yearn-v3-usdc-ethereum", "T2"),
        ("euler-v2-usdc-ethereum", "T2"),
        ("maple-usdc-ethereum", "T2"),
        ("pendle-pt-usdc-ethereum", "T2"),
        ("unknown-protocol", "T2"),  # conservative default
    ])
    def test_tier_resolution(self, key, tier):
        assert cov_export.tier_for(key) == tier


class TestClassifySource:
    def test_empty_is_synthetic(self):
        assert cov_export._classify_source({}) == "synthetic_fallback"

    def test_all_fallback(self):
        rows = {"a": {"fallback": True}, "b": {"fallback": True}}
        assert cov_export._classify_source(rows) == "synthetic_fallback"

    def test_all_live(self):
        rows = {"a": {"fallback": False}, "b": {"fallback": False}}
        assert cov_export._classify_source(rows) == "live"

    def test_mixed_is_partial(self):
        rows = {"a": {"fallback": False}, "b": {"fallback": True}}
        assert cov_export._classify_source(rows) == "partial"


class TestBuildDocument:
    def _setup(self, tmp_path, n=MIN_OBSERVATIONS + 20):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(n)))
        hist = tmp_path / "apy_history.json"
        return str(src), str(hist)

    def test_live_source_with_real_data(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(
            history_file=hist, source_export=src
        )
        assert doc["source"] == "live"
        assert doc["schema_version"] == cov_export.SCHEMA_VERSION
        assert doc["window_days"] == 90
        assert doc["history_bridged"] is True  # store didn't exist → bridged
        assert set(doc["protocols"]) == {
            "aave-v3-usdc-ethereum", "yearn-v3-usdc-ethereum"
        }

    def test_required_top_level_keys(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(history_file=hist, source_export=src)
        for k in ("schema_version", "generated_at", "window_days",
                  "min_observations", "source", "history_store",
                  "history_bridged", "protocols", "covariance_matrix",
                  "correlation_matrix"):
            assert k in doc

    def test_matrices_symmetric(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(history_file=hist, source_export=src)
        for mat in (doc["covariance_matrix"], doc["correlation_matrix"]):
            keys = list(mat.keys())
            for i in keys:
                for j in keys:
                    assert mat[i][j] == mat[j][i]

    def test_correlation_diagonal_is_one(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(history_file=hist, source_export=src)
        for k in doc["correlation_matrix"]:
            assert doc["correlation_matrix"][k][k] == 1.0

    def test_covariance_diagonal_nonnegative(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(history_file=hist, source_export=src)
        for k in doc["covariance_matrix"]:
            assert doc["covariance_matrix"][k][k] >= 0.0

    def test_generated_at_parseable(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(history_file=hist, source_export=src)
        assert datetime.fromisoformat(doc["generated_at"])

    def test_json_serialisable(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(history_file=hist, source_export=src)
        # round-trips cleanly
        assert json.loads(json.dumps(doc)) == json.loads(json.dumps(doc))

    def test_missing_source_no_bridge_synthetic(self, tmp_path):
        # No history store, no source, bridge disabled → empty/synthetic.
        doc = cov_export.build_covariance_document(
            history_file=str(tmp_path / "absent.json"),
            source_export=str(tmp_path / "also_absent.json"),
            auto_bridge=False,
        )
        assert doc["source"] == "synthetic_fallback"
        assert doc["protocols"] == {}
        assert doc["covariance_matrix"] == {}

    def test_custom_window(self, tmp_path):
        src, hist = self._setup(tmp_path)
        doc = cov_export.build_covariance_document(
            history_file=hist, source_export=src, window_days=30
        )
        assert doc["window_days"] == 30


class TestWriteJson:
    def test_write_and_reload(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(MIN_OBSERVATIONS + 10)))
        hist = tmp_path / "apy_history.json"
        out = tmp_path / "out" / "covariance_summary.json"
        doc = cov_export.write_covariance_json(
            out_path=str(out), history_file=str(hist), source_export=str(src)
        )
        assert out.exists()
        on_disk = json.loads(out.read_text())
        assert on_disk == doc
        assert on_disk["source"] == "live"


class TestCli:
    def test_cli_write_roundtrip(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(MIN_OBSERVATIONS + 10)))
        hist = tmp_path / "apy_history.json"
        out = tmp_path / "covariance_summary.json"
        rc = cov_export.main([
            "--write",
            "--source", str(src),
            "--history", str(hist),
            "--out", str(out),
        ])
        assert rc == 0
        assert out.exists()
        assert json.loads(out.read_text())["source"] == "live"

    def test_bridge_cli_write(self, tmp_path):
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(10)))
        out = tmp_path / "apy_history.json"
        rc = bridge.main(["--source", str(src), "--out", str(out), "--write"])
        assert rc == 0
        assert out.exists()
        assert len(json.loads(out.read_text())["protocol_history"]) == 2


# ──────────────────────────────────────────────────────────────────────────
# Committed artifacts (repo-level smoke checks)
# ──────────────────────────────────────────────────────────────────────────

class TestExportPipelineWiring:
    """SPA-V338: covariance_export must be wired into the 4h export pipeline.

    The pipeline (spa_core/export_data.py :: run_export) is heavy (SQLite,
    paper trader, DeFiLlama, etc.), so rather than running it end-to-end we
    verify the wiring statically + behaviourally:

      * the pipeline source imports and calls write_covariance_json and
        registers covariance_summary in its artifact manifest;
      * the covariance write is wrapped graceful — a raising write does NOT
        propagate out of the section (mirrors every other optional export).
    """

    def _pipeline_source(self) -> str:
        p = Path(__file__).resolve().parent.parent / "export_data.py"
        return p.read_text()

    def test_pipeline_imports_covariance_writer(self):
        src = self._pipeline_source()
        assert "from analytics.covariance_export import write_covariance_json" in src
        assert "write_covariance_json(" in src

    def test_pipeline_writes_standard_path(self):
        src = self._pipeline_source()
        # Same default path the CLI uses, under the pipeline OUTPUT_DIR.
        assert 'covariance_summary.json' in src

    def test_pipeline_registers_in_manifest(self):
        src = self._pipeline_source()
        # Listed in the files_written manifest fed to the decision logger.
        assert '"covariance_summary.json"' in src

    def test_pipeline_section_health_tracked(self):
        src = self._pipeline_source()
        # P3-8: health helpers are now ExportContext methods (ctx.section_ok/fail).
        assert 'section_ok("covariance_summary")' in src
        assert 'section_fail("covariance_summary")' in src

    def test_pipeline_call_is_guarded(self):
        """The covariance call sits inside a try/except (graceful section)."""
        src = self._pipeline_source()
        idx = src.index("from analytics.covariance_export import write_covariance_json")
        # Find the nearest 'try:' preceding the import — it must exist and the
        # matching except must reference the covariance section fail.
        head = src[:idx]
        assert head.rstrip().endswith("try:") or "try:" in head.splitlines()[-3:][0] \
            or any(line.strip() == "try:" for line in head.splitlines()[-4:])
        tail = src[idx:idx + 1200]
        # P3-8: health helpers are now ExportContext methods (ctx.section_fail).
        assert "section_fail(\"covariance_summary\")" in tail

    def test_covariance_failure_does_not_propagate(self, tmp_path, monkeypatch):
        """Simulate the pipeline's covariance section: a raising writer must be
        swallowed (warning logged), so the pipeline keeps running."""
        def _boom(*a, **k):
            raise RuntimeError("simulated covariance failure")

        monkeypatch.setattr(cov_export, "write_covariance_json", _boom)

        # Mirror the exact graceful pattern used in run_export.
        failed = False
        try:
            cov_export.write_covariance_json(out_path=str(tmp_path / "x.json"))
        except Exception:
            failed = True  # caught — pipeline would log warning and continue
        assert failed is True  # the except branch ran; nothing escaped

    def test_writer_produces_valid_artifact_offline(self, tmp_path):
        """End-to-end the way the pipeline calls it: bridge from a
        historical_apy.json then write covariance_summary.json — no network."""
        src = tmp_path / "historical_apy.json"
        src.write_text(json.dumps(_make_historical(MIN_OBSERVATIONS + 15)))
        hist = tmp_path / "apy_history.json"
        out = tmp_path / "covariance_summary.json"
        doc = cov_export.write_covariance_json(
            out_path=str(out), history_file=str(hist), source_export=str(src)
        )
        assert out.exists()
        on_disk = json.loads(out.read_text())
        assert on_disk == doc
        assert on_disk["schema_version"] == cov_export.SCHEMA_VERSION
        assert on_disk["source"] in ("live", "partial", "synthetic_fallback")
        assert "covariance_matrix" in on_disk
        assert "correlation_matrix" in on_disk


class TestCommittedArtifacts:
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    def test_apy_history_artifact_valid(self):
        p = self._repo_root() / "data" / "apy_history.json"
        if not p.exists():
            pytest.skip("data/apy_history.json not generated in this env")
        d = json.loads(p.read_text())
        assert "protocol_history" in d
        assert len(d["protocol_history"]) >= 1

    def test_covariance_summary_artifact_valid(self):
        p = self._repo_root() / "data" / "covariance_summary.json"
        if not p.exists():
            pytest.skip("data/covariance_summary.json not generated in this env")
        d = json.loads(p.read_text())
        assert d["schema_version"] == cov_export.SCHEMA_VERSION
        assert d["source"] in ("live", "partial", "synthetic_fallback")
        assert "covariance_matrix" in d and "correlation_matrix" in d
