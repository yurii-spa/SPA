"""The ingestion ALLOW-LIST — the only files memory may read — and the secret sanitizer.

Nothing outside these patterns is ingested: no data/ runtime state, no Keychain, no chat transcripts,
no personal files, no whole-disk crawl. Every chunk keeps (repo, path, layer, authority).

Roots are resolved at run time:
    spa       origin/main content — the full mirror clone ~/Documents/SPA_mirror (the production checkout
              is hundreds of commits behind for git-tracked files; only its data/ is live)
    bridge    ~/Documents/studio_bridge          (local repo, no remote)
    earndefi  ~/Documents/earn-defi              (local repo, no remote)
    company   ~/Documents/earn-defi-studio-memory (Company Memory, append-only)
    claude    ~/.claude/projects/-Users-yuriikulieshov-Documents-SPA-Claude/memory  (EPISODIC only)
    shadow    ~/studio-os-scratch/v03  (an off-origin worktree — EPISODIC, status UNKNOWN, never authority)
Any root can be overridden with SPA_MEMORY_ROOT_<NAME> (tests point them at tmp dirs).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

HOME = Path.home()
DEFAULT_ROOTS = {
    "spa": HOME / "Documents" / "SPA_mirror",
    "bridge": HOME / "Documents" / "studio_bridge",
    "earndefi": HOME / "Documents" / "earn-defi",
    "company": HOME / "Documents" / "earn-defi-studio-memory",
    "claude": HOME / ".claude" / "projects" / "-Users-yuriikulieshov-Documents-SPA-Claude" / "memory",
    "shadow": HOME / "studio-os-scratch" / "v03",
}


@dataclass(frozen=True)
class Rule:
    root: str
    pattern: str          # glob relative to the root
    layer: str            # CANONICAL / EPISODIC / SEMANTIC / DERIVED
    kind: str             # adr / rule / doc / roadmap / journal / idea / card / release / handoff / memory / agents
    authority: int        # 3 decides truth · 2 canonical context · 1 episodic evidence · 0 derived/stale


ALLOW: Tuple[Rule, ...] = (
    Rule("spa", "CLAUDE.md", "CANONICAL", "rule", 3),
    Rule("spa", ".claude/rules/*.md", "CANONICAL", "rule", 3),
    Rule("spa", "docs/decisions/ADR-*.md", "CANONICAL", "adr", 3),
    Rule("spa", "docs/ROADMAP.md", "CANONICAL", "roadmap", 3),
    Rule("spa", "docs/CAPITAL_ARCHITECTURE.md", "CANONICAL", "doc", 3),
    Rule("spa", "docs/MEMORY_ARCHITECTURE.md", "CANONICAL", "doc", 3),
    Rule("spa", "docs/TRADING_RESEARCH_ENGINE.md", "CANONICAL", "doc", 3),
    Rule("spa", "docs/GITHUB_CREDENTIALS.md", "CANONICAL", "doc", 3),
    Rule("spa", "docs/DEFI_ARCHITECTURE_GAP_AUDIT.md", "CANONICAL", "doc", 3),
    Rule("spa", "docs/THREE_TIER_YIELD_PRODUCT.md", "CANONICAL", "doc", 2),
    Rule("spa", "docs/STATE.md", "CANONICAL", "doc", 2),
    # The site-redesign execution specs (owner-commissioned brief, 2026-07-12): the ORIGIN of public
    # site features (calculator M3, comparison bar M2, tier cards, funnel events). Authority 1 — later
    # ADRs override them — but without them «why does this site feature exist?» had no source at all
    # (measured 2026-10-02: the assembler returned NOT covered for the homepage calculator; ADR-537).
    Rule("spa", "docs/SITE_REDESIGN_MASTER_BRIEF.md", "CANONICAL", "doc", 1),
    Rule("spa", "docs/redesign/*.md", "CANONICAL", "doc", 1),
    Rule("spa", "architecture/manifest.json", "CANONICAL", "agents", 3),
    Rule("spa", "architecture/memory_truth.json", "SEMANTIC", "truth", 3),
    Rule("spa", "docs/*ROADMAP*.md", "CANONICAL", "roadmap", 1),        # demoted by the truth registry
    Rule("spa", "docs/ideas/*.md", "EPISODIC", "idea", 1),
    Rule("spa", "docs/journal/2026-W*.md", "EPISODIC", "journal", 1),
    Rule("spa", "nimbalyst-local/tracker/*.md", "EPISODIC", "card", 1),
    Rule("bridge", "docs/adr/*.md", "CANONICAL", "adr", 3),
    Rule("bridge", "docs/releases/*.md", "CANONICAL", "release", 2),
    Rule("bridge", "docs/handoffs/CURRENT-HANDOFF.md", "EPISODIC", "handoff", 1),
    Rule("earndefi", "docs/DECISIONS.md", "CANONICAL", "adr", 3),
    Rule("earndefi", "docs/0*.md", "CANONICAL", "doc", 2),
    Rule("earndefi", "CLAUDE.md", "CANONICAL", "rule", 2),
    Rule("company", "decisions/**/*.md", "CANONICAL", "adr", 2),
    Rule("claude", "*.md", "EPISODIC", "memory", 1),
    # an off-origin feature worktree: readable evidence, NEVER authority (its ADR numbers collide with origin)
    Rule("shadow", "docs/decisions/ADR-47[1-5]-*.md", "EPISODIC", "shadow", 0),
    Rule("shadow", "docs/security/owner-admin-action*.md", "EPISODIC", "shadow", 0),
)

#: Never read, whatever a pattern says.
DENY = re.compile(r"(^|/)(\.git|data|node_modules|__pycache__|state|secrets|\.ssh)(/|$)|\.(db|sqlite|key|pem|p12)$"
                  r"|(^|/)_BOARD\.md$")   # _BOARD.md is a derived board of the cards — the cards themselves are indexed

#: Secret shapes. A matching line is DROPPED from the chunk (not masked) and counted.
SECRET_RES = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"), re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"gh[ousr]_[A-Za-z0-9]{20,}"), re.compile(r"(?<![A-Za-z0-9])sk-(ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"), re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(seed phrase|mnemonic)\b\s*[:=]"),
    re.compile(r"(?i)(password|passwd|api[_-]?key|secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


def roots() -> Dict[str, Path]:
    out = {}
    for name, default in DEFAULT_ROOTS.items():
        env = os.environ.get(f"SPA_MEMORY_ROOT_{name.upper()}")
        out[name] = Path(env) if env else default
    return out


def sanitize(text: str) -> Tuple[str, int]:
    """Drop every line that looks like a credential. Returns (clean text, dropped line count)."""
    kept, dropped = [], 0
    for line in text.splitlines():
        if any(r.search(line) for r in SECRET_RES):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept), dropped


def iter_files() -> Iterator[Tuple[Rule, Path, str]]:
    """(rule, absolute path, repo-relative path) for every allowed file, each once (first rule wins)."""
    seen = set()
    rs = roots()
    for rule in ALLOW:
        base = rs[rule.root]
        if not base.is_dir():
            continue
        for p in sorted(base.glob(rule.pattern)):
            rel = p.relative_to(base).as_posix()
            key = (rule.root, rel)
            if key in seen or not p.is_file() or DENY.search(rel):
                continue
            seen.add(key)
            yield rule, p, rel


def present_roots() -> List[str]:
    return [n for n, p in roots().items() if p.is_dir()]
