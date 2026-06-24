"""
spa_core/tests/test_run_manifest.py — tests for the Tier-1 run manifest / model registry.

Verifies: manifest_hash determinism (same state → same hash across calls), module_versions
returns a sha256 for each tier1 *.py, verify_reproducible detects a changed input, graceful
behaviour on missing files, and atomic write of data/tier1_run_manifest.json.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from spa_core.backtesting.tier1 import run_manifest as rm

_TIER1_DIR = Path(rm.__file__).resolve().parent


def _is_sha256(s) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def test_manifest_hash_deterministic():
    """Same code + same inputs → identical manifest_hash across two builds (no write)."""
    m1 = rm.build_manifest(write=False)
    m2 = rm.build_manifest(write=False)
    assert _is_sha256(m1["manifest_hash"])
    assert m1["manifest_hash"] == m2["manifest_hash"]
    # The hash core (excluding volatile generated_at) must also be identical.
    assert m1["module_hashes"] == m2["module_hashes"]
    assert m1["input_hashes"] == m2["input_hashes"]


def test_manifest_hash_matches_recomputation():
    """manifest_hash equals sha256 over canonical JSON of the three fingerprint maps."""
    m = rm.build_manifest(write=False)
    core = {
        "module_hashes": m["module_hashes"],
        "input_hashes": {k: v["sha256"] for k, v in m["input_hashes"].items()},
        "output_hashes": {k: v["sha256"] for k, v in m["output_hashes"].items()},
    }
    expected = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    assert m["manifest_hash"] == expected


def test_module_versions_covers_every_tier1_py():
    """module_versions() returns a valid sha256 for each spa_core/backtesting/tier1/*.py."""
    mv = rm.module_versions()
    on_disk = {p.name for p in _TIER1_DIR.glob("*.py")}
    assert set(mv.keys()) == on_disk
    assert "run_manifest.py" in mv
    for name, sha in mv.items():
        assert _is_sha256(sha), f"{name} -> {sha!r}"
    # sha must match a direct recomputation for a known file.
    target = _TIER1_DIR / "run_manifest.py"
    assert mv["run_manifest.py"] == hashlib.sha256(target.read_bytes()).hexdigest()
    # Sorted, deterministic ordering.
    assert list(mv.keys()) == sorted(mv.keys())


def test_verify_reproducible_clean():
    """A manifest verified against the unchanged current state is reproducible."""
    m = rm.build_manifest(write=False)
    res = rm.verify_reproducible(m)
    assert res["reproducible"] is True
    assert res["changed_modules"] == []
    assert res["changed_inputs"] == []
    assert res["changed_outputs"] == []
    assert res["manifest_hash_prev"] == res["manifest_hash_now"]


def test_verify_reproducible_detects_changed_input():
    """Altering a copy of a prior manifest's input fingerprint is flagged as non-reproducible."""
    m = rm.build_manifest(write=False)
    altered = copy.deepcopy(m)
    # Simulate that an input file's contents differed at a prior run.
    keys = list(altered["input_hashes"].keys())
    assert keys, "expected at least one tracked input"
    victim = keys[0]
    altered["input_hashes"][victim] = {
        "present": True,
        "sha256": "0" * 64,  # bogus fingerprint
        "bytes": 1,
    }
    altered["manifest_hash"] = "f" * 64  # force top-level hash mismatch too
    res = rm.verify_reproducible(altered)
    assert res["reproducible"] is False
    assert victim in res["changed_inputs"]


def test_verify_reproducible_detects_changed_module():
    """A divergent module fingerprint in the prior manifest is detected."""
    m = rm.build_manifest(write=False)
    altered = copy.deepcopy(m)
    name = next(iter(altered["module_hashes"]))
    altered["module_hashes"][name] = "1" * 64
    res = rm.verify_reproducible(altered)
    assert res["reproducible"] is False
    assert name in res["changed_modules"]


def test_graceful_on_missing_files(monkeypatch, tmp_path):
    """Missing inputs/outputs do not raise; inputs report present=False, outputs are skipped."""
    monkeypatch.setattr(rm, "_ROOT", tmp_path)
    monkeypatch.setattr(rm, "_DATA", tmp_path / "data")
    monkeypatch.setattr(rm, "_OUT", tmp_path / "data" / "tier1_run_manifest.json")
    m = rm.build_manifest(write=False)
    # No data dir exists → every input absent, no outputs.
    assert m["input_count"] == len(rm._INPUT_FILES)
    for rel, info in m["input_hashes"].items():
        assert info["present"] is False
        assert info["sha256"] is None
    assert m["output_count"] == 0
    assert m["output_hashes"] == {}
    # Module hashes still resolve (module dir is real).
    assert m["module_count"] >= 1
    assert _is_sha256(m["manifest_hash"])


def test_atomic_write(monkeypatch, tmp_path):
    """build_manifest(write=True) writes valid JSON atomically and leaves no temp files."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(rm, "_ROOT", tmp_path)
    monkeypatch.setattr(rm, "_DATA", data_dir)
    out = data_dir / "tier1_run_manifest.json"
    monkeypatch.setattr(rm, "_OUT", out)

    m = rm.build_manifest(write=True)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["manifest_hash"] == m["manifest_hash"]
    assert loaded["model"] == "tier1_run_manifest"
    assert loaded["llm_forbidden"] is True
    # No leftover temp artifacts from tempfile.mkstemp.
    leftovers = [p.name for p in data_dir.iterdir() if p.name.startswith(".tier1_manifest_")]
    assert leftovers == []


def test_input_fingerprint_matches_real_file_when_present():
    """When a real input exists, its recorded sha256 equals a direct file hash."""
    m = rm.build_manifest(write=False)
    for rel, info in m["input_hashes"].items():
        p = rm._ROOT / rel
        if info["present"]:
            assert info["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
            assert info["bytes"] == p.stat().st_size
