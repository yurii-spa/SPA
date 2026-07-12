#!/usr/bin/env python3
"""Conversion-instrumentation guard (WARN-ONLY by default) — Q1-7 invariant.

Q1-7 instrumented every conversion CTA with a ``data-track`` attribute so the global
analytics handler in Layout.astro logs the click. The funnel is only measurable if that
coverage stays complete: a new ``<a href="/packages">`` (or /pilot, /fundability, …)
WITHOUT data-track is a blind spot — the click happens but analytics never sees it.

This guard flags any anchor pointing at a conversion target that lacks data-track, so the
funnel can't silently go blind again as pages are edited.

WARN-ONLY by design (per the CF-prebuild-freshness lesson: a hard exit-1 in the CF prebuild
froze the whole site for days). Exit 0 always, UNLESS STRICT_CONVERSION_TRACKING=1 (then exit 1
on any blind CTA). Deterministic, stdlib-only.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "landing" / "src" / "pages"

# Conversion targets whose CTAs must be measured (mirror the Q1-7 sweep).
_TARGETS = (
    "/packages", "/pilot", "/fundability", "/due-diligence", "/strategies",
    "/track-record", "/verify", "/refusals", "/exit-nav", "/competitive-position",
    "/annual-contrast",
)


def _is_conversion(href: str) -> bool:
    base = href.split("#")[0].split("?")[0].rstrip("/") or "/"
    return any(base == t.rstrip("/") or base.startswith(t.rstrip("/") + "/") for t in _TARGETS)


def scan() -> list[tuple[str, str]]:
    """Return [(relpath, href)] for conversion anchors missing data-track."""
    blind: list[tuple[str, str]] = []
    for f in PAGES.rglob("*.astro"):
        rel = f.relative_to(PAGES).as_posix()
        if rel.startswith("admin/") or rel.startswith("cockpit") or rel.startswith("board"):
            continue  # operator surfaces — not public conversion funnel
        txt = f.read_text(encoding="utf-8")
        for m in re.finditer(r'<a\s[^>]*href=["\'](/[^"\']*)["\'][^>]*>', txt):
            if _is_conversion(m.group(1)) and "data-track" not in m.group(0):
                blind.append((rel, m.group(1)))
    return blind


def main() -> int:
    strict = os.environ.get("STRICT_CONVERSION_TRACKING") == "1"
    if not PAGES.exists():
        print(f"[conversion-tracking] WARN: pages dir missing: {PAGES.relative_to(ROOT)}")
        return 0
    blind = scan()
    if not blind:
        print("[conversion-tracking] OK — every conversion CTA carries data-track (funnel fully measurable)")
        return 0
    print(
        f"[conversion-tracking] {'FAIL' if strict else 'WARN'}: {len(blind)} conversion CTA(s) missing "
        "data-track (the funnel is blind at these clicks — add data-track=\"{page}_to_{dest}\"):"
    )
    for rel, href in blind:
        print(f"    {rel}  →  {href}")
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
