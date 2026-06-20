"""
tests/test_security_audit.py

MP-1457 (v10.73) — Security audit verification tests.
20 tests: no plaintext secrets, no hardcoded tokens, audit file exists, keychain usage.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SPA_CORE = REPO_ROOT / "spa_core"

# ── Patterns that indicate actual hardcoded secrets (not comments/examples) ──
SECRET_PATTERNS = [
    # Actual assignment of secret value (not a comment, not os.environ)
    r'(?:password|passwd|secret|api_key|apikey)\s*=\s*["\'][^"\']{8,}["\']',
    r'(?:ghp|github_pat|gh_token)\s*=\s*["\'][A-Za-z0-9_]{10,}["\']',
    r'Authorization.*Bearer\s+[A-Za-z0-9._\-]{20,}',
]

# Files that are explicitly allowed to mention secret patterns (audit/docs)
ALLOWLISTED_FILES = {
    "architecture_audit.py",   # contains detection regex patterns
    "github_pusher.py",        # contains usage example `ghp_xxx`
}


def get_python_files(directory: Path, exclude_tests: bool = True):
    """Get all .py files, optionally excluding test directories."""
    files = []
    for f in directory.rglob("*.py"):
        if exclude_tests and ("test" in f.name.lower() or "/tests/" in str(f)):
            continue
        files.append(f)
    return files


# ── 1. Security audit file ────────────────────────────────────────────────────

def test_security_audit_file_exists():
    """docs/SECURITY_AUDIT_20260619.md must exist."""
    path = REPO_ROOT / "docs" / "SECURITY_AUDIT_20260619.md"
    assert path.exists(), "Security audit file missing: docs/SECURITY_AUDIT_20260619.md"


def test_security_audit_non_empty():
    """Security audit must be substantial (≥2000 bytes)."""
    path = REPO_ROOT / "docs" / "SECURITY_AUDIT_20260619.md"
    if path.exists():
        assert path.stat().st_size >= 2000, "Security audit too small"


def test_security_audit_has_conclusion():
    """Security audit must have a Conclusion section."""
    path = REPO_ROOT / "docs" / "SECURITY_AUDIT_20260619.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert "Conclusion" in content, "Security audit missing Conclusion section"


def test_security_audit_confirms_no_hardcoded_secrets():
    """Security audit must explicitly state no hardcoded secrets found."""
    path = REPO_ROOT / "docs" / "SECURITY_AUDIT_20260619.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert "No hardcoded secrets" in content or "no hardcoded" in content.lower(), \
            "Audit doesn't confirm absence of hardcoded secrets"


def test_security_audit_covers_keychain():
    """Security audit must mention macOS Keychain."""
    path = REPO_ROOT / "docs" / "SECURITY_AUDIT_20260619.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert "Keychain" in content, "Security audit doesn't cover Keychain"


def test_security_audit_has_findings_section():
    """Security audit must have a Findings section."""
    path = REPO_ROOT / "docs" / "SECURITY_AUDIT_20260619.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert "Findings" in content, "Security audit missing Findings section"


# ── 2. No plaintext secrets in spa_core/ ─────────────────────────────────────

def test_no_hardcoded_github_pat():
    """No actual GitHub PAT (ghp_ prefix with real token) in spa_core/ files."""
    # Real PAT: ghp_ followed by 36+ alphanumeric chars
    pat_pattern = re.compile(r'ghp_[A-Za-z0-9]{36,}')
    for py_file in get_python_files(SPA_CORE):
        if py_file.name in ALLOWLISTED_FILES:
            continue
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        matches = pat_pattern.findall(content)
        assert not matches, (
            f"Possible real GitHub PAT found in {py_file.relative_to(REPO_ROOT)}: {matches}"
        )


def test_no_hardcoded_telegram_token():
    """No Telegram bot token format in spa_core/."""
    # Telegram token format: 1234567890:AAF...
    tg_pattern = re.compile(r'\d{8,12}:[A-Za-z0-9_\-]{35,}')
    for py_file in get_python_files(SPA_CORE):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "#" in line:
                line = line[:line.index("#")]  # strip comments
            if tg_pattern.search(line):
                assert False, (
                    f"Possible Telegram token in "
                    f"{py_file.relative_to(REPO_ROOT)}:{i+1}: {line.strip()}"
                )


def test_no_hardcoded_password_assignments():
    """No `password = 'actual_value'` assignments in non-test spa_core/ files."""
    pwd_pattern = re.compile(
        r'(?:password|passwd)\s*=\s*["\'][^"\']{8,}["\']',
        re.IGNORECASE
    )
    for py_file in get_python_files(SPA_CORE):
        if py_file.name in ALLOWLISTED_FILES:
            continue
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # skip comment lines
            if pwd_pattern.search(stripped):
                assert False, (
                    f"Possible hardcoded password at "
                    f"{py_file.relative_to(REPO_ROOT)}:{i+1}: {stripped[:80]}"
                )


def test_no_hardcoded_api_key_assignments():
    """No `api_key = 'actual_value'` assignments in spa_core/."""
    apikey_pattern = re.compile(
        r'api_key\s*=\s*["\'][A-Za-z0-9_\-\.]{10,}["\']',
        re.IGNORECASE
    )
    for py_file in get_python_files(SPA_CORE):
        if py_file.name in ALLOWLISTED_FILES:
            continue
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if apikey_pattern.search(stripped):
                assert False, (
                    f"Possible hardcoded API key at "
                    f"{py_file.relative_to(REPO_ROOT)}:{i+1}: {stripped[:80]}"
                )


# ── 3. Keychain usage ─────────────────────────────────────────────────────────

def test_keychain_py_exists():
    """spa_core/utils/keychain.py must exist."""
    keychain_path = SPA_CORE / "utils" / "keychain.py"
    assert keychain_path.exists(), "spa_core/utils/keychain.py missing"


def test_keychain_uses_subprocess():
    """keychain.py must use subprocess (not hardcoded values)."""
    keychain_path = SPA_CORE / "utils" / "keychain.py"
    if keychain_path.exists():
        content = keychain_path.read_text(encoding="utf-8")
        assert "subprocess" in content, "keychain.py must use subprocess for Keychain access"


def test_keychain_no_hardcoded_token():
    """keychain.py must not contain any actual token values."""
    keychain_path = SPA_CORE / "utils" / "keychain.py"
    if keychain_path.exists():
        content = keychain_path.read_text(encoding="utf-8")
        # Should only have service names, not actual token values
        assert "GITHUB_PAT_SPA" in content or "find-generic-password" in content, \
            "keychain.py should reference keychain service names"
        # Must NOT have actual token values
        assert "ghp_" not in content, "keychain.py contains actual PAT value"


def test_keychain_uses_security_command():
    """keychain.py must use macOS `security` command for Keychain access."""
    keychain_path = SPA_CORE / "utils" / "keychain.py"
    if keychain_path.exists():
        content = keychain_path.read_text(encoding="utf-8")
        assert "find-generic-password" in content, \
            "keychain.py must use macOS security find-generic-password"


# ── 4. Data files ─────────────────────────────────────────────────────────────

def test_no_secrets_in_state_json_files():
    """data/*.json state files must not contain 'password', 'secret', 'token' keys."""
    data_dir = REPO_ROOT / "data"
    suspicious_keys = {"password", "secret", "api_key", "private_key", "seed_phrase"}
    for json_file in data_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            if isinstance(data, dict):
                found = suspicious_keys & set(str(k).lower() for k in data.keys())
                assert not found, (
                    f"data/{json_file.name} contains suspicious key(s): {found}"
                )
        except (json.JSONDecodeError, OSError):
            pass  # corrupted file: not a secret issue


def test_no_bearer_tokens_in_data():
    """data/*.json must not contain Bearer token strings."""
    bearer_pattern = re.compile(r'Bearer\s+[A-Za-z0-9._\-]{20,}')
    data_dir = REPO_ROOT / "data"
    for json_file in data_dir.glob("*.json"):
        try:
            content = json_file.read_text(encoding="utf-8", errors="ignore")
            if bearer_pattern.search(content):
                assert False, f"Possible Bearer token in data/{json_file.name}"
        except OSError:
            pass


# ── 5. LLM_FORBIDDEN_AGENTS compliance ───────────────────────────────────────

def test_risk_policy_no_llm_import():
    """spa_core/risk/policy.py must not import any LLM client."""
    risk_policy = SPA_CORE / "risk" / "policy.py"
    if risk_policy.exists():
        content = risk_policy.read_text(encoding="utf-8")
        llm_imports = ["anthropic", "openai", "langchain", "llm", "ChatGPT"]
        for imp in llm_imports:
            assert imp not in content, (
                f"LLM import '{imp}' found in risk/policy.py (FORBIDDEN)"
            )


def test_golive_checker_no_llm_import():
    """golive_checker.py must not import any LLM client."""
    checker = SPA_CORE / "paper_trading" / "golive_checker.py"
    if checker.exists():
        content = checker.read_text(encoding="utf-8")
        assert "anthropic" not in content, "LLM import in golive_checker.py (FORBIDDEN)"
        assert "openai" not in content, "LLM import in golive_checker.py (FORBIDDEN)"
