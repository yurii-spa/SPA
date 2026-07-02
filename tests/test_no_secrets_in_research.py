"""SECURITY-002 — no real secrets leaked into research-layer files.

Scans docs/, prompts/, data/{strategy,protocol,stablecoin}_cards/, and
research/ for real-looking PATs / API keys / private keys / mnemonics.

This is a SECURITY GUARD — it must not be weakened to pass. It DOES, however,
distinguish a real leaked secret from documentation that *discusses* the
pattern (placeholder strings like `ghp_xxxx...`, `ghp_SECRETVALUE`, the word
"mnemonic" used in prose). Those are not secrets; a real 36+ char high-entropy
GitHub PAT, an `sk-...` key, or a PEM private-key block are.

Research-layer only: no spa_core import, no data mutation, no cycle run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SCAN_DIRS = [
    REPO_ROOT / "docs",
    REPO_ROOT / "prompts",
    REPO_ROOT / "research",
    REPO_ROOT / "data" / "strategy_cards",
    REPO_ROOT / "data" / "protocol_cards",
    REPO_ROOT / "data" / "stablecoin_cards",
]

TEXT_SUFFIXES = {".md", ".txt", ".json", ".py", ".yml", ".yaml", ".command", ".sh"}

# Obvious placeholders that appear in security docs / examples and are NOT secrets.
PLACEHOLDER_MARKERS = (
    "xxxx",
    "XXXX",
    "SECRETVALUE",
    "your_",
    "YOUR_",
    "example",
    "EXAMPLE",
    "placeholder",
    "PLACEHOLDER",
    "<",  # angle-bracket templated value like <token>
)

# --- Real-secret patterns (deliberately strict to avoid matching prose) -----
SECRET_PATTERNS = {
    # GitHub PAT: ghp_ / github_pat_ followed by a long real token body.
    "github_pat": re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),
    "github_pat_fine": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    # OpenAI-style key.
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    # AWS access key id.
    "aws_akid": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Slack token.
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    # PEM private key block.
    "pem_private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    # Raw hex private key (0x + 64 hex) — an actual key, not prose.
    "hex_private_key": re.compile(r"\b0x[a-fA-F0-9]{64}\b"),
}


def _iter_files():
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
                yield p


def _line_is_placeholder(line: str) -> bool:
    return any(mark in line for mark in PLACEHOLDER_MARKERS)


ALL_FILES = sorted(_iter_files())


def test_files_discovered():
    assert ALL_FILES, "no research-layer text files discovered to scan"


def test_no_real_secrets_in_research_layer():
    findings = []
    for path in ALL_FILES:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for name, rx in SECRET_PATTERNS.items():
                m = rx.search(line)
                if not m:
                    continue
                # PEM header is a secret regardless of placeholders on the line.
                if name != "pem_private_key" and _line_is_placeholder(line):
                    continue
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}:{i} [{name}] {m.group(0)[:12]}..."
                )
    assert not findings, "possible leaked secret(s) in research layer:\n" + "\n".join(findings)
