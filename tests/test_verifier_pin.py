"""test_verifier_pin.py — the published verifier pin must match the shipped script (P0-1 audit fix).

CI turns RED if scripts/verify_spa.py changes without re-pinning BOTH docs/VERIFIER_RELEASE.md and
landing/src/pages/verify.astro. This prevents the exact regression the external audit found: the pin
(0f8c270c…) had drifted from the actual script (bbc4853a…) and the tag was never pushed.
"""
import hashlib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VERIFIER = _ROOT / "scripts" / "verify_spa.py"
_RELEASE = _ROOT / "docs" / "VERIFIER_RELEASE.md"
_ASTRO = _ROOT / "landing" / "src" / "pages" / "verify.astro"


def _actual_sha() -> str:
    return hashlib.sha256(_VERIFIER.read_bytes()).hexdigest()


def test_release_manifest_pins_the_actual_verifier():
    sha = _actual_sha()
    text = _RELEASE.read_text()
    assert sha in text, (
        f"docs/VERIFIER_RELEASE.md does not pin the actual verify_spa.py SHA-256 {sha}. "
        "Re-pin the manifest (Current release + the shasum blocks) and bump the version tag."
    )


def test_verify_astro_pins_the_actual_verifier():
    sha = _actual_sha()
    text = _ASTRO.read_text()
    m = re.search(r"VERIFIER_SHA256\s*=\s*'([0-9a-f]{64})'", text)
    assert m, "verify.astro: VERIFIER_SHA256 constant not found"
    assert m.group(1) == sha, (
        f"verify.astro pins {m.group(1)} but verify_spa.py hashes to {sha} — re-pin on any script change."
    )


def test_release_and_astro_agree_on_version_tag():
    rel = _RELEASE.read_text()
    ast = _ASTRO.read_text()
    m_ast = re.search(r"VERIFIER_VERSION\s*=\s*'(verifier-v[0-9.]+)'", ast)
    assert m_ast, "verify.astro: VERIFIER_VERSION not found"
    tag = m_ast.group(1)
    assert tag in rel, f"docs/VERIFIER_RELEASE.md must reference the same version tag {tag} as verify.astro"
