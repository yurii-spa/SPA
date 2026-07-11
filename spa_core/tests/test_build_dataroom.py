"""Tests for the Q2-9 self-verifying data-room bundle (scripts/build_dataroom.py).

Verifies the bundle is self-verifying (every file's stored sha256 matches its bytes), a MANIFEST + README
are present, absent sources are recorded (never fabricated), and the manifest counts are consistent.
Deterministic; no network.
"""
import hashlib
import importlib
import json
import zipfile
from datetime import datetime, timezone

bd = importlib.import_module("scripts.build_dataroom")


def _open(tmp_path):
    path = bd.build(out_dir=tmp_path, now=datetime(2026, 7, 11, 0, 0, 0, tzinfo=timezone.utc))
    return path, zipfile.ZipFile(path)


def test_bundle_has_manifest_readme_and_verifier(tmp_path):
    _, z = _open(tmp_path)
    names = z.namelist()
    assert "MANIFEST.json" in names
    assert "README.md" in names
    assert "verifier/verify_spa.py" in names          # the standalone verifier is always bundled


def test_manifest_hashes_are_self_verifying(tmp_path):
    _, z = _open(tmp_path)
    manifest = json.loads(z.read("MANIFEST.json"))
    for f in manifest["files"]:
        if f["sha256"] is None:
            continue                                   # absent source — nothing to hash
        actual = hashlib.sha256(z.read(f["arcname"])).hexdigest()
        assert actual == f["sha256"], f"hash mismatch for {f['arcname']}"


def test_manifest_counts_consistent(tmp_path):
    _, z = _open(tmp_path)
    m = json.loads(z.read("MANIFEST.json"))
    present = [f for f in m["files"] if f["sha256"]]
    absent = [f for f in m["files"] if not f["sha256"]]
    assert m["n_files"] == len(present)
    assert m["n_absent"] == len(absent)
    assert m["is_advisory"] is True


def test_absent_source_recorded_not_fabricated(tmp_path, monkeypatch):
    # inject a non-existent artifact → it must appear with sha256 None, not crash or invent bytes
    monkeypatch.setattr(bd, "ARTIFACTS", bd.ARTIFACTS + [
        ("does/not/exist.md", "proof/ghost.md", "a file that isn't there")])
    _, z = _open(tmp_path)
    m = json.loads(z.read("MANIFEST.json"))
    ghost = next(f for f in m["files"] if f["arcname"] == "proof/ghost.md")
    assert ghost["sha256"] is None and ghost["bytes"] == 0
    assert "proof/ghost.md" not in z.namelist()        # absent → not written into the zip


def test_readme_has_reproduce_commands(tmp_path):
    _, z = _open(tmp_path)
    readme = z.read("README.md").decode()
    assert "verify_spa.py" in readme
    assert "full-chain" in readme
    assert "sha256" in readme
