"""Tests for the Q2-10 offline DD snapshot (scripts/build_dd_snapshot.py).

Verifies the snapshot freezes the clean proof surfaces with a pinned verifier head, the manifest is
self-consistent (sha256 per file, replay command references the pinned head), the unsound anchors surface
is documented as excluded, and — end-to-end — the standalone verifier re-derives the SAME head from the
frozen files OFFLINE and passes with the pinned --expect-head. Deterministic; no network.
"""
import importlib
import json

import pytest

bds = importlib.import_module("scripts.build_dd_snapshot")


def _build(tmp_path):
    return bds.build(out_dir=tmp_path)


def _build_or_skip(tmp_path):
    # The committed decision-log / proof surfaces live under data/ (gitignored, runtime-only), so a
    # clean checkout / CI has them absent → no head is reproduced. Skip the head-dependent assertions
    # there (this is a data-availability gap, not a logic regression; exercised locally where data exists).
    m = _build(tmp_path)
    if not m.get("expected_decision_head"):
        pytest.skip("committed decision-log data absent (clean checkout / CI) — no head to reproduce")
    return m


def test_snapshot_verifies_clean_with_pinned_head(tmp_path):
    m = _build_or_skip(tmp_path)
    # the frozen surfaces reproduce cleanly (anchors excluded → no index-0 break)
    assert m["verifier_ok"] is True
    assert m["verifier_errors"] == []
    assert m["expected_decision_head"]                     # a real head hash was reproduced
    assert m["expected_surfaces"]                          # non-empty


def test_manifest_files_have_hashes_and_exist(tmp_path):
    m = _build(tmp_path)
    for f in m["files"]:
        if f.get("absent"):
            continue
        assert f["sha256"]
        assert (tmp_path / f["arcname"]).exists()


def test_anchors_excluded_and_documented(tmp_path):
    m = _build(tmp_path)
    exc = {e["surface"] for e in m["excluded_surfaces"]}
    assert "C" in exc                                      # anchors surface excluded
    assert any("unsound" in e["reason"] for e in m["excluded_surfaces"])
    # anchors are NOT in the frozen surface set
    assert all(f["surface"] != "C" for f in m["files"])


def test_replay_command_references_pinned_head(tmp_path):
    m = _build_or_skip(tmp_path)
    assert m["expected_decision_head"] in m["replay_command"]
    for s in m["expected_surfaces"]:
        assert s in m["replay_command"]


def test_offline_replay_reproduces_the_head(tmp_path):
    """END-TO-END: the standalone verifier, run on the frozen snapshot, re-derives the SAME head."""
    from scripts import verify_spa
    m = _build_or_skip(tmp_path)
    frozen = [str(tmp_path / f["arcname"]) for f in m["files"] if f.get("sha256")]
    report = verify_spa.run(frozen, expect_head=m["expected_decision_head"])
    assert report["ok"] is True
    assert (report.get("decision_chain") or {}).get("head_hash") == m["expected_decision_head"]


def test_manifest_written_to_disk(tmp_path):
    _build(tmp_path)
    manifest = json.loads((tmp_path / "SNAPSHOT_MANIFEST.json").read_text())
    assert manifest["model"] == "spa_dd_snapshot_manifest"
    assert manifest["is_advisory"] is True
