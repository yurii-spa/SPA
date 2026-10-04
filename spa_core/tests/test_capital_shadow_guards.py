"""
test_capital_shadow_guards.py — ADR-556 / RM-LIVE-01 static guards.

``spa_core/capital_shadow/`` sits between an investment recommendation and
any future real-capital action. By contract (``contract.py``'s module
docstring, and ADR-556's WP-A03 / binding-review point 13) it "never holds a
key, never signs, never broadcasts, never submits an order, never moves
funds." These guards check that boundary STATICALLY (AST + plain text scans
over source — no import of anything live, no network, no execution of any
package code) rather than trusting discipline alone — "the client's
allow-list makes [a send] impossible by construction, not by discipline"
(``rpc.py``'s own docstring), and this suite proves the construction.

The guards are written GENERICALLY over whatever ``*.py`` files exist in the
package directory at test time, because several modules were still being
written concurrently by other sessions when this file was created
(``rpc.py``, ``abi.py``, ``tokens.py``, ``simulate.py``, ``exchange_sim.py``,
``intent.py``, ``machine.py``, ``ledger.py``, ``reconcile.py``,
``readiness.py``, ``runbook.py``, ``verify.py``, ``incidents.py``, ``run.py``,
``read.py``, ``failure_matrix.py``). Nothing here hardcodes that list — a
new module dropped into the directory is picked up automatically and must
pass the same guards.

Every guard below has a POSITIVE CONTROL: the same checker function is run
over a synthetic offending snippet (written to a tmp file, never imported —
only ``ast.parse``d) and must catch it. A checker that only ever sees clean
code is unverified; these prove each one actually fires on the violation it
claims to catch.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "spa_core" / "capital_shadow"
PKG_DOTTED = "spa_core.capital_shadow"


def _package_files() -> list[Path]:
    """Every *.py file directly in the package (no recursion needed — flat package)."""
    if not PKG_DIR.is_dir():
        return []
    return sorted(p for p in PKG_DIR.glob("*.py") if p.is_file())


def _parse_file(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _parse_source(source: str) -> ast.AST:
    return ast.parse(source, filename="<synthetic>")


# A guard that found zero real package files would pass every assertion
# vacuously — that is a measurement failure, not a clean bill of health.
# Every parametrized-over-files test below either lists at least one file or
# is explicitly marked to tolerate an empty package (there are none of the
# latter: by the time this suite runs, the package is non-empty — contract.py
# and keccak.py exist from the start of the epic).
_FILES = _package_files()


def test_package_directory_is_not_empty():
    assert PKG_DIR.is_dir(), f"package directory missing: {PKG_DIR}"
    assert _FILES, "spa_core/capital_shadow/ has no .py files — nothing was measured"


# ─────────────────────────────────────────────────────────────────────────────
# Shared AST helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_relative_module(level: int, module: str | None,
                              package_dotted: str = PKG_DOTTED) -> str:
    """Resolve a relative ``from .[...]x import y`` to its absolute dotted path.

    ``level=1`` means "from the current package" (here, ``spa_core.capital_shadow``
    itself, since every file in this directory is a plain module, not a
    sub-package); ``level=2`` means one package up (``spa_core``), etc.
    """
    parts = package_dotted.split(".")
    drop = max(level - 1, 0)
    base_parts = parts[: len(parts) - drop] if drop < len(parts) else []
    base = ".".join(base_parts)
    return ".".join(p for p in (base, module) if p)


def collect_import_targets(tree: ast.AST) -> list[tuple[str, int]]:
    """Every dotted name bound by an import statement, relative imports resolved.

    For ``from a.b import c`` this yields BOTH ``a.b`` and ``a.b.c`` (lineno of
    the import statement), so a prefix check against either the module or the
    specific imported name works without the caller re-deriving anything.
    """
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                module = _resolve_relative_module(node.level, node.module)
            else:
                module = node.module or ""
            if module:
                out.append((module, node.lineno))
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                out.append((full, node.lineno))
    return out


def _matches_prefix(dotted: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if dotted == prefix or dotted.startswith(prefix + "."):
            return prefix
    return None


# ─────────────────────────────────────────────────────────────────────────────
# (a) no import of the money-path / exchange-SDK / signing-library surface
# ─────────────────────────────────────────────────────────────────────────────

FORBIDDEN_IMPORT_PREFIXES = (
    "spa_core.execution",
    "spa_core.paper_trading.engine",
    "spa_core.allocator",
    "spa_core.governance",
    "eth_account",
    "web3",
    "eth_keys",
    "eth_keyfile",
    # "any exchange SDK" (ADR-556 WP-A03) — non-exhaustive by construction, but
    # names every CEX SDK this codebase's requirements.txt / adjacent research
    # layers (strategy_lab) are known to reference.
    "ccxt",
    "binance",
    "python_binance",
    "krakenex",
    "coinbase",
    "pybit",
)


def find_forbidden_imports(tree: ast.AST) -> list[tuple[str, int]]:
    hits = []
    for dotted, lineno in collect_import_targets(tree):
        hit = _matches_prefix(dotted, FORBIDDEN_IMPORT_PREFIXES)
        if hit:
            hits.append((dotted, lineno))
    return hits


class TestNoMoneyPathImports:
    def test_positive_control_catches_execution_import(self):
        src = "from spa_core.execution import eth_signer\n"
        hits = find_forbidden_imports(_parse_source(src))
        assert hits, "guard failed to catch `from spa_core.execution import ...`"

    def test_positive_control_catches_relative_execution_import(self):
        # `from ...execution import x` written from inside capital_shadow/foo.py
        # (3 dots: foo.py's own module, up to capital_shadow, up to spa_core).
        src = "from ..execution import eth_signer\n"
        hits = find_forbidden_imports(_parse_source(src))
        assert hits, "guard failed to catch a RELATIVE import of spa_core.execution"

    def test_positive_control_catches_eth_account(self):
        src = "import eth_account\n"
        assert find_forbidden_imports(_parse_source(src))

    def test_positive_control_catches_web3(self):
        src = "from web3 import Web3\n"
        assert find_forbidden_imports(_parse_source(src))

    def test_positive_control_catches_ccxt(self):
        src = "import ccxt\n"
        assert find_forbidden_imports(_parse_source(src))

    def test_positive_control_catches_governance(self):
        src = "from spa_core.governance import kill_switch\n"
        assert find_forbidden_imports(_parse_source(src))

    def test_positive_control_catches_allocator(self):
        src = "from spa_core import allocator\n"
        assert find_forbidden_imports(_parse_source(src))

    def test_positive_control_does_not_flag_clean_import(self):
        src = "from spa_core.capital_shadow import contract\n"
        assert find_forbidden_imports(_parse_source(src)) == []

    @pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
    def test_real_file_has_no_forbidden_import(self, path):
        hits = find_forbidden_imports(_parse_file(path))
        assert hits == [], f"{path.name}: forbidden import(s) {hits}"


# ─────────────────────────────────────────────────────────────────────────────
# (b) only rpc.py may import urllib / http / socket / ssl / requests
# ─────────────────────────────────────────────────────────────────────────────

NETWORK_MODULES = ("urllib", "http", "socket", "ssl", "requests")


def find_network_imports(tree: ast.AST) -> list[tuple[str, int]]:
    hits = []
    for dotted, lineno in collect_import_targets(tree):
        top = dotted.split(".")[0]
        if top in NETWORK_MODULES:
            hits.append((dotted, lineno))
    return hits


class TestOnlyRpcImportsNetwork:
    def test_positive_control_catches_urllib_outside_rpc(self):
        src = "import urllib.request\n"
        assert find_network_imports(_parse_source(src))

    def test_positive_control_catches_socket(self):
        src = "import socket\n"
        assert find_network_imports(_parse_source(src))

    def test_positive_control_catches_requests(self):
        src = "import requests\n"
        assert find_network_imports(_parse_source(src))

    def test_positive_control_does_not_flag_unrelated_import(self):
        src = "import json\nfrom pathlib import Path\n"
        assert find_network_imports(_parse_source(src)) == []

    @pytest.mark.parametrize(
        "path", [p for p in _FILES if p.name != "rpc.py"], ids=lambda p: p.name,
    )
    def test_non_rpc_file_imports_no_network_module(self, path):
        hits = find_network_imports(_parse_file(path))
        assert hits == [], f"{path.name}: only rpc.py may import a network module, found {hits}"

    def test_rpc_py_exists_and_is_the_one_network_importer(self):
        """Sanity: rpc.py is actually present and actually the one doing the
        network import — otherwise the exemption above is untested air."""
        rpc_path = PKG_DIR / "rpc.py"
        if not rpc_path.is_file():
            pytest.skip("rpc.py not yet landed")
        assert find_network_imports(_parse_file(rpc_path)), (
            "rpc.py has no network import — either it changed transport, or "
            "the exemption in this guard is no longer meaningful"
        )


# ─────────────────────────────────────────────────────────────────────────────
# (c) no importlib / __import__ / exec / eval / compile / subprocess /
#     os.system / os.popen / pty anywhere in the package
# ─────────────────────────────────────────────────────────────────────────────

_DANGEROUS_IMPORT_TOPS = ("importlib", "subprocess", "pty")
_DANGEROUS_BUILTIN_CALLS = ("exec", "eval", "compile", "__import__")


def find_dynamic_execution(tree: ast.AST) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _DANGEROUS_IMPORT_TOPS:
                    hits.append((f"import {alias.name}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".")[0] in _DANGEROUS_IMPORT_TOPS:
                hits.append((f"from {mod} import ...", node.lineno))
        elif isinstance(node, ast.Name) and node.id == "__import__":
            hits.append(("__import__", node.lineno))
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _DANGEROUS_BUILTIN_CALLS:
                hits.append((fn.id, node.lineno))
            elif (
                isinstance(fn, ast.Attribute)
                and fn.attr in ("system", "popen")
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "os"
            ):
                hits.append((f"os.{fn.attr}", node.lineno))
    return hits


class TestNoDynamicExecution:
    # NOTE: every "dangerous" snippet below (exec/eval/os.system/subprocess/...)
    # is a plain Python string that is only ever fed to `ast.parse` (never
    # executed, never `exec`'d, no shell involved) — it is TEST DATA for the
    # static checker, not a live code path. That is the whole point of this
    # suite: the guard is proven against the exact hazard it claims to catch.
    @pytest.mark.parametrize(
        "snippet,label",
        [
            ("import subprocess\n", "import subprocess"),
            ("import importlib\n", "import importlib"),
            ("import pty\n", "import pty"),
            ("from subprocess import run\n", "from subprocess import run"),
            ("x = __import__('os')\n", "__import__ call"),
            ("exec('1+1')\n", "exec(...)"),
            ("eval('1+1')\n", "eval(...)"),
            ("compile('1+1', '<s>', 'eval')\n", "compile(...)"),
            ("import os\nos.system('echo hi')\n", "os.system(...)"),
            ("import os\nos.popen('echo hi')\n", "os.popen(...)"),
        ],
    )
    def test_positive_control_catches_each_form(self, snippet, label):
        hits = find_dynamic_execution(_parse_source(snippet))
        assert hits, f"guard failed to catch: {label}"

    def test_positive_control_does_not_flag_clean_code(self):
        src = (
            "import json\n"
            "import time\n"
            "from pathlib import Path\n"
            "def f(x):\n"
            "    return json.dumps({'a': x, 't': time.time()})\n"
        )
        assert find_dynamic_execution(_parse_source(src)) == []

    @pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
    def test_real_file_has_no_dynamic_execution(self, path):
        hits = find_dynamic_execution(_parse_file(path))
        assert hits == [], f"{path.name}: dynamic-execution primitive(s) found: {hits}"


# ─────────────────────────────────────────────────────────────────────────────
# (d) no string literal naming a send/sign JSON-RPC method, outside rpc.py
# ─────────────────────────────────────────────────────────────────────────────

SEND_SIGN_METHODS_EXACT = frozenset({
    "eth_sendRawTransaction",
    "eth_sendTransaction",
    "eth_sign",
    "personal_sign",
    "eth_signTransaction",
    "eth_signTypedData",
    "eth_signTypedData_v1",
    "eth_signTypedData_v3",
    "eth_signTypedData_v4",
})


def find_send_sign_literals(tree: ast.AST) -> list[tuple[str, int]]:
    """Exact-value match only — a prose sentence that MENTIONS a method name
    (e.g. an incident message "eth_sendRawTransaction attempted and refused")
    is not the same hazard as a literal used to BUILD a call, and flagging
    prose would make this guard impossible to keep green in a module whose
    whole job is to talk about refused methods (failure_matrix.py, incidents.py).
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in SEND_SIGN_METHODS_EXACT:
                hits.append((node.value, node.lineno))
    return hits


class TestNoSendSignLiteralsOutsideRpc:
    def test_positive_control_catches_exact_method_name(self):
        src = 'METHOD = "eth_sendRawTransaction"\n'
        assert find_send_sign_literals(_parse_source(src))

    def test_positive_control_catches_in_dict_literal(self):
        src = 'payload = {"method": "personal_sign", "params": []}\n'
        assert find_send_sign_literals(_parse_source(src))

    @pytest.mark.parametrize(
        "method",
        sorted(SEND_SIGN_METHODS_EXACT),
    )
    def test_positive_control_catches_every_listed_method(self, method):
        src = f'M = "{method}"\n'
        assert find_send_sign_literals(_parse_source(src)), method

    def test_does_not_flag_prose_mentioning_a_method_name(self):
        """The guard's whole point: a sentence CONTAINING the method name is
        not an exact match and must NOT be flagged — otherwise a module that
        documents its own refusals (failure_matrix.py, rpc.py's docstring)
        could never be clean."""
        src = (
            'MSG = "eth_sendRawTransaction attempted and refused — '
            'see incident log"\n'
        )
        assert find_send_sign_literals(_parse_source(src)) == []

    @pytest.mark.parametrize(
        "path", [p for p in _FILES if p.name != "rpc.py"], ids=lambda p: p.name,
    )
    def test_non_rpc_file_names_no_send_sign_method_exactly(self, path):
        hits = find_send_sign_literals(_parse_file(path))
        assert hits == [], (
            f"{path.name}: string literal exactly naming a send/sign RPC "
            f"method (outside rpc.py): {hits}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# (e) the package's RPC allow-list equals contract.RPC_ALLOWED_METHODS and
#     contains no send/sign method
# ─────────────────────────────────────────────────────────────────────────────

def _forbidden_allowlist_entries(methods) -> list[str]:
    bad = []
    for m in methods:
        if not isinstance(m, str):
            bad.append(repr(m))
            continue
        if m.startswith("eth_send") or m.startswith("eth_sign") or m.startswith("personal_"):
            bad.append(m)
    return bad


class TestRpcAllowList:
    def test_positive_control_flags_a_bad_entry(self):
        assert _forbidden_allowlist_entries(
            {"eth_call", "eth_sendRawTransaction"}
        ) == ["eth_sendRawTransaction"]

    def test_positive_control_flags_personal_prefix(self):
        assert _forbidden_allowlist_entries({"personal_sign"}) == ["personal_sign"]

    def test_positive_control_clean_set_is_untouched(self):
        assert _forbidden_allowlist_entries({"eth_call", "eth_chainId"}) == []

    def test_contract_allow_list_exists_and_is_nonempty(self):
        from spa_core.capital_shadow import contract
        assert hasattr(contract, "RPC_ALLOWED_METHODS")
        methods = contract.RPC_ALLOWED_METHODS
        assert isinstance(methods, (set, frozenset)), type(methods)
        assert methods, "RPC_ALLOWED_METHODS is empty"

    def test_contract_allow_list_contains_no_send_or_sign_method(self):
        from spa_core.capital_shadow import contract
        bad = _forbidden_allowlist_entries(contract.RPC_ALLOWED_METHODS)
        assert bad == [], f"RPC_ALLOWED_METHODS contains a send/sign method: {bad}"

    def test_rpc_py_does_not_shadow_the_allow_list_with_its_own_constant(self):
        """Single source of truth (CLAUDE.md adapters.md 'one name — one
        object' lesson): rpc.py must not define its OWN top-level
        RPC_ALLOWED_METHODS that could silently diverge from contract.py's."""
        rpc_path = PKG_DIR / "rpc.py"
        if not rpc_path.is_file():
            pytest.skip("rpc.py not yet landed")
        tree = _parse_file(rpc_path)
        shadowed = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id == "RPC_ALLOWED_METHODS"
        ]
        assert shadowed == [], (
            f"rpc.py defines its own RPC_ALLOWED_METHODS at line(s) {shadowed} "
            "— it must use contract.RPC_ALLOWED_METHODS, not a local copy"
        )

    def test_rpc_py_actually_uses_contracts_allow_list(self):
        rpc_path = PKG_DIR / "rpc.py"
        if not rpc_path.is_file():
            pytest.skip("rpc.py not yet landed")
        text = rpc_path.read_text(encoding="utf-8")
        assert "contract.RPC_ALLOWED_METHODS" in text or "RPC_ALLOWED_METHODS" in text, (
            "rpc.py never references RPC_ALLOWED_METHODS at all — nothing "
            "would enforce the allow-list"
        )


# ─────────────────────────────────────────────────────────────────────────────
# (f) no module defines or accepts a parameter named like a key/seed/secret
# ─────────────────────────────────────────────────────────────────────────────

KEY_LIKE_IDENTIFIER_RE = re.compile(
    r"(private_?key|privkey|\bseed\b|mnemonic|secret)", re.IGNORECASE,
)


def find_key_like_identifiers(tree: ast.AST) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            all_args = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
            if args.vararg:
                all_args.append(args.vararg)
            if args.kwarg:
                all_args.append(args.kwarg)
            for a in all_args:
                if a.arg == "self" or a.arg == "cls":
                    continue
                if KEY_LIKE_IDENTIFIER_RE.search(a.arg):
                    hits.append((f"{node.name}(..., {a.arg}, ...)", node.lineno))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if KEY_LIKE_IDENTIFIER_RE.search(node.id):
                hits.append((node.id, node.lineno))
    return hits


class TestNoKeyLikeIdentifiers:
    def test_positive_control_catches_private_key_param(self):
        src = "def sign(private_key, tx):\n    pass\n"
        assert find_key_like_identifiers(_parse_source(src))

    def test_positive_control_catches_privkey_param(self):
        src = "def f(privkey):\n    pass\n"
        assert find_key_like_identifiers(_parse_source(src))

    def test_positive_control_catches_seed_param(self):
        src = "def f(seed):\n    pass\n"
        assert find_key_like_identifiers(_parse_source(src))

    def test_positive_control_catches_mnemonic_param(self):
        src = "def f(mnemonic):\n    pass\n"
        assert find_key_like_identifiers(_parse_source(src))

    def test_positive_control_catches_secret_variable(self):
        src = "def f():\n    secret = read_it()\n    return secret\n"
        assert find_key_like_identifiers(_parse_source(src))

    def test_positive_control_does_not_flag_unrelated_names(self):
        src = (
            "def f(self, intent_id, block_number, security_events):\n"
            "    seedling = 1\n"  # contains 'seed' only as a prefix of a longer word... see note
            "    return intent_id\n"
        )
        hits = find_key_like_identifiers(_parse_source(src))
        # 'seedling' legitimately contains 'seed' — this is why real-file
        # assertions below report the exact names (reviewable), rather than
        # asserting blindly; this control instead proves 'security_events'
        # and 'self' are NOT flagged (neither contains the pattern /
        # is explicitly excluded).
        flagged_names = {h[0] for h in hits}
        assert "security_events" not in flagged_names
        assert not any(n == "self" for n in flagged_names)

    @pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
    def test_real_file_defines_no_key_like_identifier(self, path):
        hits = find_key_like_identifiers(_parse_file(path))
        assert hits == [], f"{path.name}: key/seed/secret-like identifier(s): {hits}"


# ─────────────────────────────────────────────────────────────────────────────
# (g) REVERSE — nothing in the money-path / risk / governance tree imports
#     capital_shadow or even names it
# ─────────────────────────────────────────────────────────────────────────────

REVERSE_PROTECTED_DIRS = (
    "spa_core/execution",
    "spa_core/paper_trading",
    "spa_core/risk",
    "spa_core/governance",
    "spa_core/allocator",
)


def find_capital_shadow_references(base_dir: Path) -> list[str]:
    hits = []
    if not base_dir.is_dir():
        return hits
    for path in sorted(base_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "capital_shadow" in text:
            try:
                hits.append(str(path.relative_to(REPO_ROOT)))
            except ValueError:
                hits.append(str(path))  # outside REPO_ROOT (e.g. a tmp_path control)
    return hits


class TestReverseNoCapitalShadowReferences:
    def test_positive_control_catches_a_reference(self, tmp_path):
        d = tmp_path / "fake_execution"
        d.mkdir()
        (d / "bad.py").write_text(
            "from spa_core.capital_shadow import contract\n", encoding="utf-8",
        )
        hits = find_capital_shadow_references(d)
        assert hits, "guard failed to catch a reference to capital_shadow"

    def test_positive_control_clean_dir_has_no_hits(self, tmp_path):
        d = tmp_path / "fake_clean"
        d.mkdir()
        (d / "ok.py").write_text("import json\n", encoding="utf-8")
        assert find_capital_shadow_references(d) == []

    @pytest.mark.parametrize("rel_dir", REVERSE_PROTECTED_DIRS)
    def test_protected_dir_has_no_capital_shadow_reference(self, rel_dir):
        base = REPO_ROOT / rel_dir
        hits = find_capital_shadow_references(base)
        assert hits == [], f"{rel_dir}: references capital_shadow: {hits}"
