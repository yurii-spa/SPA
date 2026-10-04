"""
test_no_live_credentials_in_runtime_config.py — ADR-556 / RM-LIVE-01 hardening.

Two independent claims, both about the gap between "nothing in this repo CAN
sign" and "nothing in the deployed runtime WOULD be told to try":

1. No launchd plist or agent wrapper script ships a live-signing credential
   or arming flag — ``SPA_PRIVATE_KEY`` / ``SPA_EXEC_ARMED`` /
   ``SPA_EXECUTION_MODE=live`` / a generic ``PRIVATE_KEY`` / ``MNEMONIC`` /
   ``SEED``. This is read-only: it only ever reads the real deployed
   ``~/Library/LaunchAgents/com.spa.*.plist`` (never writes it, never
   restarts an agent, never touches Keychain), per
   ``.claude/rules/deployment.md``.
2. No non-test Python caller anywhere under ``spa_core/`` or ``scripts/``
   constructs ``PaperTrader(..., live_execution=True)`` — the one flag that
   turns on the (already separately gated, ``SPA_EXECUTION_MODE=live``-only)
   live-execution leg of the paper engine (``spa_core/paper_trading/engine.py``,
   FEAT-004/005). Test files are the ONLY place this is expected to appear
   (``spa_core/tests/test_engine_bridge.py`` exercises it deliberately,
   deep in mocked RPC/account scaffolding) and are excluded by design.

Both claims carry a positive control: a synthetic offending file is built
(never executed — scanned with ``plistlib``/``ast`` only) and the checker
must catch it, proving the checker is not vacuously green.
"""
from __future__ import annotations

import ast
import plistlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHD_DIR = REPO_ROOT / "launchd"
SCRIPTS_DIR = REPO_ROOT / "scripts"
REAL_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

# ─────────────────────────────────────────────────────────────────────────────
# Shared vocabulary of what must never appear
# ─────────────────────────────────────────────────────────────────────────────

FORBIDDEN_VAR_NAMES = (
    "SPA_PRIVATE_KEY",
    "SPA_EXEC_ARMED",
    "PRIVATE_KEY",
    "MNEMONIC",
    "SEED",
)
# Special-cased separately because it is not the NAME that is forbidden
# (SPA_EXECUTION_MODE is a legitimate, widely-used var) but one specific VALUE.
LIVE_MODE_VAR = "SPA_EXECUTION_MODE"
LIVE_MODE_VALUE = "live"

_SEED_WORD_RE = re.compile(r"\bSEED\b")


def _name_is_forbidden(name: str) -> str | None:
    """Return the matched forbidden token, or None."""
    upper = name.upper()
    for token in FORBIDDEN_VAR_NAMES:
        if token == "SEED":
            if _SEED_WORD_RE.search(upper):
                return token
        elif token in upper:
            return token
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Plist scanning (EnvironmentVariables dict) — plistlib only, read-only
# ─────────────────────────────────────────────────────────────────────────────

def check_plist_bytes(data: bytes, *, label: str) -> list[str]:
    """Return a list of human-readable findings; empty means clean.

    Tries ``plistlib`` first (the correct way to read a plist); if that
    fails (e.g. a binary/corrupt plist outside this repo's control), falls
    back to a raw-text scan rather than silently reporting "clean" — a
    parse failure is not evidence of absence.
    """
    findings: list[str] = []
    try:
        doc = plistlib.loads(data)
    except Exception as exc:  # noqa: BLE001 — fall back to text scan below
        text = data.decode("utf-8", errors="replace")
        findings.extend(_scan_text_for_env_assignments(text, label=f"{label} [unparsed plist: {exc}]"))
        return findings

    env = doc.get("EnvironmentVariables") if isinstance(doc, dict) else None
    if not isinstance(env, dict):
        return findings
    for key, value in env.items():
        hit = _name_is_forbidden(str(key))
        if hit:
            findings.append(f"{label}: EnvironmentVariables key {key!r} matches forbidden token {hit!r}")
        if str(key).upper() == LIVE_MODE_VAR and str(value).strip().lower() == LIVE_MODE_VALUE:
            findings.append(f"{label}: EnvironmentVariables {LIVE_MODE_VAR}={value!r}")
        # Also check values in case a credential was stuffed into an unrelated key.
        val_hit = _name_is_forbidden(str(value)) if isinstance(value, str) else None
        if val_hit and val_hit != "SEED":  # 'SEED' in a path value is too noisy/irrelevant to check
            findings.append(f"{label}: EnvironmentVariables[{key!r}] value matches forbidden token {val_hit!r}")
    return findings


def _scan_text_for_env_assignments(text: str, *, label: str) -> list[str]:
    """Shell-style / plist-fragment fallback scan: `export NAME=value` or
    `NAME=value` lines, and `<key>NAME</key>` plist fragments."""
    findings: list[str] = []
    for line in text.splitlines():
        m = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
        if m:
            name, value = m.group(1), m.group(2).strip().strip('"\'')
            hit = _name_is_forbidden(name)
            if hit:
                findings.append(f"{label}: assignment {name}=... matches forbidden token {hit!r} ({line.strip()!r})")
            if name.upper() == LIVE_MODE_VAR and value.lower() == LIVE_MODE_VALUE:
                findings.append(f"{label}: {LIVE_MODE_VAR}=live ({line.strip()!r})")
            continue
        m2 = re.search(r"<key>([A-Za-z0-9_]+)</key>", line)
        if m2:
            hit = _name_is_forbidden(m2.group(1))
            if hit:
                findings.append(f"{label}: plist <key>{m2.group(1)}</key> matches forbidden token {hit!r}")
    return findings


def check_plist_file(path: Path) -> list[str]:
    return check_plist_bytes(path.read_bytes(), label=str(path))


def check_shell_script_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return _scan_text_for_env_assignments(text, label=str(path))


class TestPlistAndScriptPositiveControls:
    def test_catches_spa_private_key_in_plist_env(self, tmp_path):
        doc = {
            "Label": "com.spa.fake",
            "EnvironmentVariables": {"HOME": "/x", "SPA_PRIVATE_KEY": "deadbeef"},
        }
        data = plistlib.dumps(doc)
        findings = check_plist_bytes(data, label="synthetic")
        assert findings, "guard failed to catch SPA_PRIVATE_KEY in a plist EnvironmentVariables dict"

    def test_catches_exec_armed_in_plist_env(self, tmp_path):
        doc = {"EnvironmentVariables": {"SPA_EXEC_ARMED": "1"}}
        findings = check_plist_bytes(plistlib.dumps(doc), label="synthetic")
        assert findings

    def test_catches_execution_mode_live_in_plist_env(self, tmp_path):
        doc = {"EnvironmentVariables": {"SPA_EXECUTION_MODE": "live"}}
        findings = check_plist_bytes(plistlib.dumps(doc), label="synthetic")
        assert findings, "guard failed to catch SPA_EXECUTION_MODE=live"

    def test_execution_mode_paper_is_not_flagged(self, tmp_path):
        """Negative control: the non-live value must NOT trip the guard."""
        doc = {"EnvironmentVariables": {"SPA_EXECUTION_MODE": "paper"}}
        findings = check_plist_bytes(plistlib.dumps(doc), label="synthetic")
        assert findings == []

    def test_clean_plist_env_has_no_findings(self):
        doc = {"EnvironmentVariables": {"HOME": "/x", "PATH": "/usr/bin"}}
        assert check_plist_bytes(plistlib.dumps(doc), label="synthetic") == []

    def test_catches_mnemonic_and_seed_in_shell_export(self, tmp_path):
        script = tmp_path / "bad.sh"
        script.write_text(
            "#!/bin/bash\n"
            "export MNEMONIC=\"word1 word2 word3\"\n"
            "export SEED=abcdef\n",
            encoding="utf-8",
        )
        findings = check_shell_script_file(script)
        assert any("MNEMONIC" in f for f in findings)
        assert any("SEED" in f for f in findings)

    def test_catches_spa_execution_mode_live_export(self, tmp_path):
        script = tmp_path / "bad2.sh"
        script.write_text("export SPA_EXECUTION_MODE=live\n", encoding="utf-8")
        findings = check_shell_script_file(script)
        assert findings

    def test_clean_shell_script_has_no_findings(self, tmp_path):
        script = tmp_path / "ok.sh"
        script.write_text(
            "#!/bin/bash\nexport HOME=/x\nexec /bin/python3 -m spa_core.foo\n",
            encoding="utf-8",
        )
        assert check_shell_script_file(script) == []

    def test_seed_does_not_false_positive_on_unrelated_words(self, tmp_path):
        """'seed' as a word-fragment (e.g. a path component) must not trip
        the guard — only a standalone SEED-named assignment should."""
        script = tmp_path / "ok2.sh"
        script.write_text(
            "#!/bin/bash\nexport RESEEDED_CACHE_DIR=/tmp/reseeded\n",
            encoding="utf-8",
        )
        assert check_shell_script_file(script) == []


class TestRealLaunchdPlists:
    """Repo-tracked launchd/*.plist — these ARE git-tracked source, safe to
    read directly (no Keychain, no restart)."""

    @staticmethod
    def _files() -> list[Path]:
        if not LAUNCHD_DIR.is_dir():
            return []
        return sorted(LAUNCHD_DIR.glob("*.plist"))

    def test_launchd_dir_is_not_empty(self):
        assert self._files(), f"no .plist files found under {LAUNCHD_DIR}"

    @pytest.mark.parametrize("path", _files.__func__(), ids=lambda p: p.name)
    def test_repo_plist_has_no_live_credential(self, path):
        findings = check_plist_file(path)
        assert findings == [], f"{path.name}: {findings}"


class TestRealAgentWrapperScripts:
    """scripts/agent_*.sh — the launchd wrapper scripts (not the whole
    scripts/ directory's every tool; wrappers are what launchd actually
    execs with an inherited/declared environment)."""

    @staticmethod
    def _files() -> list[Path]:
        if not SCRIPTS_DIR.is_dir():
            return []
        return sorted(SCRIPTS_DIR.glob("agent_*.sh")) + sorted(SCRIPTS_DIR.glob("*agent_template*.sh"))

    def test_some_wrapper_scripts_exist(self):
        assert self._files(), f"no agent_*.sh wrappers found under {SCRIPTS_DIR}"

    @pytest.mark.parametrize("path", _files.__func__(), ids=lambda p: p.name)
    def test_wrapper_script_has_no_live_credential(self, path):
        findings = check_shell_script_file(path)
        assert findings == [], f"{path.name}: {findings}"

    def test_run_cloudflared_sh_has_no_live_credential(self):
        """Not an agent_*.sh wrapper by name, but still a deployed script
        that exports secrets — covered for completeness alongside the
        ADR-556 cloudflared hardening (test_cloudflared_token_not_on_argv.py)."""
        path = SCRIPTS_DIR / "run_cloudflared.sh"
        if not path.is_file():
            pytest.skip("run_cloudflared.sh not present")
        findings = check_shell_script_file(path)
        assert findings == [], findings


class TestRealDeployedLaunchAgents:
    """~/Library/LaunchAgents/com.spa.*.plist — the ACTUAL deployed agent
    definitions on this machine. Read-only: opened for reading only, never
    written, never used to restart/bootstrap anything (.claude/rules/
    deployment.md — a static probe must not touch a running agent)."""

    @staticmethod
    def _files() -> list[Path]:
        if not REAL_LAUNCH_AGENTS_DIR.is_dir():
            return []
        return sorted(REAL_LAUNCH_AGENTS_DIR.glob("com.spa.*.plist"))

    def test_deployed_agents_directory_reachable_or_skipped(self):
        """Not every environment running this suite (e.g. CI, a fresh clone)
        has a real ~/Library/LaunchAgents with SPA agents — that is a
        legitimate 'not applicable here', not a finding either way."""
        if not REAL_LAUNCH_AGENTS_DIR.is_dir():
            pytest.skip(f"{REAL_LAUNCH_AGENTS_DIR} does not exist on this host")
        if not self._files():
            pytest.skip("no com.spa.*.plist deployed on this host")
        assert self._files()

    @pytest.mark.parametrize("path", _files.__func__(), ids=lambda p: p.name)
    def test_deployed_plist_has_no_live_credential(self, path):
        findings = check_plist_file(path)
        assert findings == [], f"{path.name}: {findings}"


# ─────────────────────────────────────────────────────────────────────────────
# PaperTrader(live_execution=True) — non-test callers only
# ─────────────────────────────────────────────────────────────────────────────

def find_live_execution_true_calls(tree: ast.AST) -> list[int]:
    """Line numbers of any ``PaperTrader(..., live_execution=True, ...)`` call
    (keyword, or positional in the 5th slot — ``db_path, config, strategy_id,
    decision_logger, live_execution`` — per ``spa_core/paper_trading/engine.py``'s
    signature)."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if name != "PaperTrader":
            continue
        for kw in node.keywords:
            if kw.arg == "live_execution" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                hits.append(node.lineno)
        if len(node.args) >= 5:
            fifth = node.args[4]
            if isinstance(fifth, ast.Constant) and fifth.value is True:
                hits.append(node.lineno)
    return hits


def _is_test_path(path: Path) -> bool:
    if "tests" in path.parts:
        return True
    if path.name.startswith("test_"):
        return True
    return False


def _non_test_py_files(*bases: Path) -> list[Path]:
    out = []
    for base in bases:
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if _is_test_path(p):
                continue
            out.append(p)
    return sorted(out)


class TestPaperTraderLiveExecutionFlag:
    def test_positive_control_catches_keyword_true(self):
        src = "t = PaperTrader(db_path=p, live_execution=True)\n"
        hits = find_live_execution_true_calls(ast.parse(src))
        assert hits, "guard failed to catch live_execution=True as a keyword"

    def test_positive_control_catches_positional_true(self):
        src = "t = PaperTrader(p, None, 'sid', None, True)\n"
        hits = find_live_execution_true_calls(ast.parse(src))
        assert hits, "guard failed to catch live_execution=True passed positionally"

    def test_positive_control_does_not_flag_false(self):
        src = "t = PaperTrader(db_path=p, live_execution=False)\n"
        assert find_live_execution_true_calls(ast.parse(src)) == []

    def test_positive_control_does_not_flag_unrelated_call(self):
        src = "t = SomeOtherThing(live_execution=True)\n"
        assert find_live_execution_true_calls(ast.parse(src)) == []

    def test_positive_control_catches_module_qualified_call(self):
        src = "t = engine.PaperTrader(db_path=p, live_execution=True)\n"
        assert find_live_execution_true_calls(ast.parse(src))

    @pytest.mark.parametrize(
        "path",
        _non_test_py_files(REPO_ROOT / "spa_core", REPO_ROOT / "scripts"),
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_non_test_file_never_passes_live_execution_true(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = find_live_execution_true_calls(tree)
        assert hits == [], (
            f"{path.relative_to(REPO_ROOT)}: PaperTrader(live_execution=True) "
            f"at line(s) {hits} — outside tests, this flag must stay False"
        )

    def test_the_known_test_caller_is_excluded_by_the_scan(self):
        """Sanity: the one legitimate caller (test_engine_bridge.py) really
        does pass live_execution=True, and really IS excluded — otherwise
        this whole suite's exclusion logic is unverified."""
        known = REPO_ROOT / "spa_core" / "tests" / "test_engine_bridge.py"
        if not known.is_file():
            pytest.skip("test_engine_bridge.py not present")
        tree = ast.parse(known.read_text(encoding="utf-8"), filename=str(known))
        assert find_live_execution_true_calls(tree), (
            "expected test_engine_bridge.py to contain a live_execution=True "
            "call — if it no longer does, the exclusion-sanity premise changed"
        )
        assert _is_test_path(known), "test_engine_bridge.py must be classified as a test path"
