#!/usr/bin/env python3
"""Sitemap hygiene guard (WARN-ONLY by default) — UX-05 invariant.

sitemap.xml.ts advertises the public URL set to crawlers. Any page that passes ``noindex``
to Layout (dev showcases, tier redirect-stubs like /strategies/preserve) MUST also be listed
in the sitemap's INTERNAL_ROUTES exclusion set — otherwise the sitemap points crawlers at a
page we've told them not to index (or at a redirect stub instead of its canonical target).

This guard mirrors that invariant: every ``noindex`` landing page (outside /admin, which the
sitemap excludes wholesale) must appear in INTERNAL_ROUTES. It catches the regression where a
new noindex page — or a resurrected redirect-stub — silently re-enters the public sitemap.

WARN-ONLY by design (per the CF-prebuild-freshness lesson: a hard exit-1 in the CF prebuild
froze the whole site for days). Exit 0 always, UNLESS STRICT_SITEMAP_HYGIENE=1 (then exit 1 on
any drift). Deterministic, stdlib-only.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "landing" / "src" / "pages"
SITEMAP = PAGES / "sitemap.xml.ts"


def _route_of(astro: Path) -> str:
    """Map a .astro file under pages/ to its public route (mirrors sitemap.xml.ts logic)."""
    rel = astro.relative_to(PAGES).as_posix()[: -len(".astro")]
    if rel.endswith("/index"):
        rel = rel[: -len("/index")]
    return rel or "index"


def _noindex_pages() -> list[str]:
    """Routes of pages that pass noindex to Layout (excluding sitemap.xml.ts's own comment)."""
    out = []
    for f in PAGES.rglob("*.astro"):
        rel = f.relative_to(PAGES).as_posix()
        if rel.startswith("admin/"):
            continue  # sitemap excludes /admin wholesale
        txt = f.read_text(encoding="utf-8")
        # a page opts out via a noindex prop/attr on Layout — a bare word match is enough here
        if re.search(r"\bnoindex\b", txt):
            out.append(_route_of(f))
    return sorted(set(out))


def _internal_routes() -> set[str]:
    """Parse the INTERNAL_ROUTES set literal out of sitemap.xml.ts."""
    if not SITEMAP.exists():
        return set()
    txt = SITEMAP.read_text(encoding="utf-8")
    m = re.search(r"INTERNAL_ROUTES\s*=\s*new Set<string>\(\s*\[(.*?)\]\s*\)", txt, re.S)
    if not m:
        # single-arg form: new Set<string>(['a'])
        m = re.search(r"INTERNAL_ROUTES\s*=\s*new Set<string>\(\s*(\[.*?\])\s*\)", txt, re.S)
        if not m:
            return set()
    body = m.group(1)
    return set(re.findall(r"['\"]([^'\"]+)['\"]", body))


def main() -> int:
    strict = os.environ.get("STRICT_SITEMAP_HYGIENE") == "1"
    if not SITEMAP.exists():
        print(f"[sitemap-hygiene] WARN: sitemap source missing: {SITEMAP.relative_to(ROOT)}")
        return 0
    excluded = _internal_routes()
    leaks = [r for r in _noindex_pages() if r not in excluded]
    if not leaks:
        print("[sitemap-hygiene] OK — every noindex page is excluded from the sitemap")
        return 0
    print(
        f"[sitemap-hygiene] {'FAIL' if strict else 'WARN'}: {len(leaks)} noindex page(s) NOT in "
        "sitemap.xml.ts INTERNAL_ROUTES (crawlers would be pointed at a noindex/redirect page — "
        "add the route to INTERNAL_ROUTES):"
    )
    for r in leaks:
        print(f"    {r}")
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
