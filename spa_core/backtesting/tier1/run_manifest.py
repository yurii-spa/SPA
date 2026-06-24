"""
spa_core/backtesting/tier1/run_manifest.py — deterministic run manifest / model registry.

PARALLEL MODEL — reads only; never edits the tournament, RiskPolicy, or any canonical
module. Tier-1 reproducibility requires that every result be traceable to the exact code
that produced it and the exact input data it consumed. This module fingerprints a Tier-1
run end-to-end:

  1. CODE VERSION    — sha256 of the source of every spa_core/backtesting/tier1/*.py file.
  2. DATA FINGERPRINT — sha256 of the contents of each input the pipeline consumes
                        (data/bee/defillama_apy_history.json, data/mass_tournament_results.json).
  3. OUTPUT STAMP    — generated_at + sha256 of each Tier-1 output JSON that exists.
  4. MANIFEST HASH   — sha256 over the canonical JSON of
                        {module_hashes, input_hashes, output_hashes}. Same code + same
                        inputs → same manifest_hash. That equality IS the reproducibility
                        proof: a divergent hash means the code or the data changed.

Output: data/tier1_run_manifest.json (atomic). Deterministic, stdlib only, LLM-forbidden.
Integration note: run this LAST in the Tier-1 pipeline so it stamps a complete run
(after verdict/gate/packages/etc. have been written).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path

_THIS = Path(__file__).resolve()
_TIER1_DIR = _THIS.parent
_ROOT = _THIS.parents[3]
_DATA = _ROOT / "data"
_OUT = _DATA / "tier1_run_manifest.json"

# Inputs the Tier-1 pipeline consumes (data fingerprints). Paths relative to repo root.
_INPUT_FILES = (
    "data/bee/defillama_apy_history.json",
    "data/mass_tournament_results.json",
)

# Tier-1 outputs whose presence + content we stamp (record only the ones that exist).
_OUTPUT_FILES = (
    "data/tier1_verdict.json",
    "data/tier1_gate.json",
    "data/tier1_packages.json",
    "data/tier1_status.json",
    "data/tier1_correlation.json",
    "data/tier1_data_integrity.json",
    "data/tier1_monte_carlo.json",
    "data/tier1_nav_proof.json",
    "data/tier1_regime.json",
    "data/tier1_var.json",
)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: Path) -> str:
    """sha256 of a file's raw bytes, streamed (handles large inputs). Caller guards existence."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj) -> str:
    """Canonical JSON: sorted keys, no whitespace — stable byte representation."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def module_versions() -> dict:
    """{filename: sha256} for every spa_core/backtesting/tier1/*.py source file.

    Keyed by bare filename (deterministic, location-independent) and sorted, so the same
    set of sources always produces the same mapping regardless of iteration order."""
    out = {}
    for p in sorted(_TIER1_DIR.glob("*.py"), key=lambda x: x.name):
        out[p.name] = _sha256_file(p)
    return dict(sorted(out.items()))


def _input_hashes() -> dict:
    """{relpath: {present, sha256, bytes}} for each pipeline input. Graceful on missing."""
    out = {}
    for rel in _INPUT_FILES:
        p = _ROOT / rel
        if p.exists() and p.is_file():
            out[rel] = {"present": True, "sha256": _sha256_file(p), "bytes": p.stat().st_size}
        else:
            out[rel] = {"present": False, "sha256": None, "bytes": 0}
    return dict(sorted(out.items()))


def _output_hashes() -> dict:
    """{relpath: {present, sha256, generated_at, bytes}} for each existing Tier-1 output.

    generated_at is read from the output JSON when available (the pipeline stamps it),
    otherwise falls back to the file mtime (UTC ISO)."""
    out = {}
    for rel in _OUTPUT_FILES:
        p = _ROOT / rel
        if not (p.exists() and p.is_file()):
            continue
        generated_at = None
        try:
            doc = json.loads(p.read_text())
            if isinstance(doc, dict):
                generated_at = doc.get("generated_at")
        except Exception:
            generated_at = None
        if not generated_at:
            generated_at = datetime.datetime.fromtimestamp(
                p.stat().st_mtime, datetime.timezone.utc
            ).isoformat()
        out[rel] = {
            "present": True,
            "sha256": _sha256_file(p),
            "generated_at": generated_at,
            "bytes": p.stat().st_size,
        }
    return dict(sorted(out.items()))


def build_manifest(write: bool = True) -> dict:
    """Build the full Tier-1 run manifest and (by default) atomically write it.

    manifest_hash = sha256 over canonical JSON of {module_hashes, input_hashes,
    output_hashes}, so identical code + identical inputs + identical outputs reproduce
    the same hash — the reproducibility proof."""
    module_hashes = module_versions()
    input_hashes = _input_hashes()
    output_hashes = _output_hashes()

    # The hash core deliberately EXCLUDES generated_at / volatile metadata: only the
    # content fingerprints (code + data) determine reproducibility.
    core = {
        "module_hashes": module_hashes,
        "input_hashes": {k: v["sha256"] for k, v in input_hashes.items()},
        "output_hashes": {k: v["sha256"] for k, v in output_hashes.items()},
    }
    manifest_hash = _sha256_bytes(_canonical(core).encode("ascii"))

    manifest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_run_manifest",
        "llm_forbidden": True,
        "manifest_hash": manifest_hash,
        "module_count": len(module_hashes),
        "module_hashes": module_hashes,
        "input_count": len(input_hashes),
        "input_hashes": input_hashes,
        "output_count": len(output_hashes),
        "output_hashes": output_hashes,
        "reproducibility_note": (
            "manifest_hash is sha256 over canonical JSON of {module_hashes, input_hashes, "
            "output_hashes} (sort_keys, compact). Same code + same inputs + same outputs → "
            "same manifest_hash. A divergent hash proves code or data changed; use "
            "verify_reproducible() to see exactly what."
        ),
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1_manifest_")
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, _OUT)
    return manifest


def verify_reproducible(prev_manifest: dict) -> dict:
    """Compare a prior manifest to the CURRENT state and report what changed.

    Returns {reproducible, manifest_hash_prev, manifest_hash_now, changed_modules,
    changed_inputs, changed_outputs}. reproducible is True iff the manifest_hash matches
    AND no individual module/input/output fingerprint diverged."""
    now = build_manifest(write=False)

    def _diff(prev_map: dict, now_map: dict, key: str) -> list:
        prev = prev_map or {}
        cur = now_map or {}

        def _sha(d):
            return d.get("sha256") if isinstance(d, dict) else d

        changed = []
        for name in sorted(set(prev) | set(cur)):
            if _sha(prev.get(name)) != _sha(cur.get(name)):
                changed.append(name)
        return changed

    changed_modules = _diff(prev_manifest.get("module_hashes"), now["module_hashes"], "module")
    changed_inputs = _diff(prev_manifest.get("input_hashes"), now["input_hashes"], "input")
    changed_outputs = _diff(prev_manifest.get("output_hashes"), now["output_hashes"], "output")

    prev_hash = prev_manifest.get("manifest_hash")
    now_hash = now["manifest_hash"]
    reproducible = (
        prev_hash == now_hash
        and not changed_modules
        and not changed_inputs
        and not changed_outputs
    )
    return {
        "reproducible": reproducible,
        "manifest_hash_prev": prev_hash,
        "manifest_hash_now": now_hash,
        "changed_modules": changed_modules,
        "changed_inputs": changed_inputs,
        "changed_outputs": changed_outputs,
    }


if __name__ == "__main__":
    m = build_manifest()
    print(json.dumps({
        "manifest_hash": m["manifest_hash"],
        "module_count": m["module_count"],
        "input_fingerprints": {
            k: (v["sha256"][:16] + "..." if v["sha256"] else None)
            for k, v in m["input_hashes"].items()
        },
        "input_present": {k: v["present"] for k, v in m["input_hashes"].items()},
        "output_count": m["output_count"],
    }, indent=2))
