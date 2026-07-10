#!/usr/bin/env python3
"""6mo-M1 #11 — tier-band consistency guard (WARN-ONLY by default).

After #7 unified the tier APY/drawdown band strings into landing/src/lib/tier_bands.json, this guard
keeps them unified: it flags any NEW hardcoded band-shaped string (e.g. "6–8% net APY", "≤10% drawdown",
"Capital protection first (10–12%)") that appears in a landing source file OTHER than the canonical
tier_bands.json — i.e. someone re-hardcoding a band instead of importing the single source.

WARN-ONLY by design (per the CF-prebuild-freshness lesson: a hard exit-1 in the CF prebuild froze the
whole site for days). Exit 0 always, UNLESS STRICT_TIER_BANDS=1 is set (then exit 1 on any drift) — so
it can run as an advisory CF-prebuild step without ever blocking a deploy, and as a strict CI gate when
wanted. Deterministic, stdlib-only.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANDING_SRC = ROOT / "landing" / "src"
CANONICAL = LANDING_SRC / "lib" / "tier_bands.json"

# band-SHAPED literals: an APY/drawdown range next to "net APY"/"drawdown", or a nav "(...%)" band.
_BAND_PATTERNS = [
    re.compile(r"\d+[–-]\d+%\s*net APY"),                       # "6–12% net APY"
    re.compile(r"≤\s*\d+%\s*drawdown"),                          # "≤10% drawdown"
    re.compile(r"(?:protection first|controlled risk|active monitoring)\s*\([^)]*%\)"),  # nav band copy
]


def scan() -> list:
    """Return [(relpath, lineno, snippet)] for band-shaped literals outside the canonical file."""
    hits = []
    for path in sorted(LANDING_SRC.rglob("*.astro")):
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path  # LANDING_SRC redirected outside the repo (tests) → show the raw path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in _BAND_PATTERNS:
                if pat.search(line):
                    hits.append((str(rel), i, line.strip()[:110]))
                    break
    return hits


def main() -> int:
    strict = os.environ.get("STRICT_TIER_BANDS") == "1"
    if not CANONICAL.exists():
        print(f"[tier-band-guard] WARN: canonical source missing: {CANONICAL.relative_to(ROOT)}")
        return 1 if strict else 0
    hits = scan()
    if not hits:
        print("[tier-band-guard] OK — no hardcoded tier band strings outside tier_bands.json")
        return 0
    print(f"[tier-band-guard] {'FAIL' if strict else 'WARN'}: "
          f"{len(hits)} hardcoded band-shaped string(s) outside the canonical tier_bands.json "
          "(import from ../lib/tier_bands.json instead so bands can't diverge):")
    for rel, ln, snip in hits:
        print(f"  {rel}:{ln}  {snip}")
    return 1 if strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
