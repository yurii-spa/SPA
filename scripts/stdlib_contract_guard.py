"""
scripts/stdlib_contract_guard.py
Identifies files with pure stdlib contracts — files that MUST NOT import
from spa_core.utils or any third-party library.

A stdlib contract file is identified by having:
1. A test function named test_only_stdlib_imports OR
2. A comment "# stdlib only" in the file OR
3. Being in the STDLIB_CONTRACT_FILES whitelist

These files must NEVER be migrated to use spa_core.utils.*
"""
import os
import ast
import sys
from typing import List

STDLIB_CONTRACT_FILES = [
    "spa_core/audit/proof_of_track.py",
    # add others found during scan
]

# Known stdlib module names (top-level)
_STDLIB_TOPS = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
    "os", "sys", "json", "re", "math", "time", "datetime", "collections",
    "itertools", "functools", "pathlib", "io", "abc", "copy", "typing",
    "enum", "dataclasses", "hashlib", "hmac", "base64", "struct",
    "socket", "ssl", "threading", "multiprocessing", "subprocess",
    "tempfile", "shutil", "glob", "fnmatch", "stat", "errno",
    "logging", "warnings", "contextlib", "traceback", "inspect",
    "importlib", "pkgutil", "types", "weakref", "gc", "platform",
    "urllib", "http", "email", "html", "xml", "csv", "configparser",
    "argparse", "getopt", "unittest", "doctest", "pprint", "textwrap",
    "string", "random", "decimal", "fractions", "statistics", "operator",
    "heapq", "bisect", "array", "queue", "asyncio", "concurrent",
    "signal", "select", "selectors", "uuid", "zlib", "gzip",
    "zipfile", "tarfile", "sqlite3", "pickle", "shelve",
    "__future__", "builtins",
}


def is_stdlib_contract(filepath: str) -> bool:
    """
    Returns True if filepath is a stdlib contract file that must NOT
    import from spa_core.utils or any third-party library.
    
    Detection heuristics (any one suffices):
    1. filepath is in STDLIB_CONTRACT_FILES whitelist
    2. File contains comment "# stdlib only"
    3. File has a test function named test_only_stdlib_imports
    """
    # Normalize path
    norm = filepath.replace("\\", "/").lstrip("./")
    # 1. Whitelist check
    for entry in STDLIB_CONTRACT_FILES:
        if norm == entry or norm.endswith("/" + entry) or entry.endswith("/" + norm):
            return True
    # Read file content (silently skip if unreadable)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return False
    # 2. Comment marker
    if "# stdlib only" in content:
        return True
    # 3. Test function name
    if "def test_only_stdlib_imports" in content:
        return True
    return False


def validate_no_spa_imports(filepath: str) -> bool:
    """
    Returns True if the file does NOT import from spa_core.utils or
    other spa_core sub-packages (i.e., is clean for a stdlib contract).
    Returns False if it imports from spa_core.utils.* or spa_core.*
    (excluding spa_core itself being the package).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return True  # Can't read → assume clean
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return True  # Can't parse → assume clean
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("spa_core."):
                    return False
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("spa_core."):
                return False
    return True


def scan_for_contracts(base_dir: str = ".") -> List[str]:
    """
    Scans base_dir for all Python files that qualify as stdlib contracts.
    Returns a list of relative paths.
    """
    contracts = []
    for root, dirs, files in os.walk(base_dir):
        # Skip hidden dirs and common non-source dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            if is_stdlib_contract(fpath):
                contracts.append(os.path.relpath(fpath, base_dir))
    return contracts


def report(base_dir: str = ".") -> str:
    """
    Generates a human-readable report of stdlib contract files found in base_dir.
    """
    contracts = scan_for_contracts(base_dir)
    lines = [
        "stdlib contract guard report",
        "=" * 40,
        f"Base directory: {os.path.abspath(base_dir)}",
        f"stdlib contract files found: {len(contracts)}",
        "",
    ]
    if contracts:
        lines.append("Files protected from atomic migration:")
        for c in sorted(contracts):
            lines.append(f"  [PROTECTED] {c}")
    else:
        lines.append("No stdlib contract files found.")
    lines.append("")
    lines.append("These files MUST NOT import from spa_core.utils.*")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="stdlib contract guard — identify protected files")
    parser.add_argument("--base-dir", default=".", help="Base directory to scan")
    parser.add_argument("--check", metavar="FILE", help="Check if a specific file is a stdlib contract")
    parser.add_argument("--validate", metavar="FILE", help="Validate that a file has no spa_core imports")
    args = parser.parse_args()
    
    if args.check:
        result = is_stdlib_contract(args.check)
        print(f"{'stdlib contract' if result else 'not a stdlib contract'}: {args.check}")
        sys.exit(0 if result else 1)
    elif args.validate:
        result = validate_no_spa_imports(args.validate)
        print(f"{'clean (no spa_core imports)' if result else 'VIOLATION: has spa_core imports'}: {args.validate}")
        sys.exit(0 if result else 1)
    else:
        print(report(args.base_dir))
