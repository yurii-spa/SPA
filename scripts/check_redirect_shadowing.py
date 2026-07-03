#!/usr/bin/env python3
"""check_redirect_shadowing.py — no _redirects rule may shadow a real page, and no internal link
may point at a redirecting URL (P0-3 audit fix).

Cloudflare Pages applies `_redirects` BEFORE serving a static page, so a redirect whose source path
also exists as a real `src/pages/<path>.astro` silently hijacks that page. The external audit found
`/status` and `/tournament` (both real pages, both linked in nav/footer) were being 301/302'd to the
dashboard. This gate fails CI on any such shadowing and on any internal link to a redirecting URL.

Exit 0 = clean; exit 1 = violations printed.
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_REDIRECTS = _ROOT / "landing" / "public" / "_redirects"
_PAGES = _ROOT / "landing" / "src" / "pages"
_SCAN_DIRS = [_ROOT / "landing" / "src"]


def _redirect_sources():
    """(source_path, is_rewrite) for each rule; skips comments + full-URL host rules."""
    out = []
    for line in _REDIRECTS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        src = parts[0]
        if src.startswith("http") or "*" in src:   # host-level / splat rule, not a page path
            continue
        status = parts[-1] if parts[-1].isdigit() else "301"
        out.append((src, status == "200"))
    return out


def _page_exists(path: str) -> bool:
    clean = path.strip("/")
    if not clean:
        return False
    return (_PAGES / f"{clean}.astro").exists() or (_PAGES / clean / "index.astro").exists()


def main() -> int:
    violations = []
    sources = _redirect_sources()
    redirecting = set()

    # 1. a redirect (not a 200-rewrite) whose source is also a real page = shadowing
    for src, is_rewrite in sources:
        if is_rewrite:
            continue
        redirecting.add(src.rstrip("/"))
        if _page_exists(src):
            violations.append(f"SHADOWING: _redirects rule '{src}' hijacks the real page src/pages{src}.astro")

    # 2. internal links pointing at a redirecting URL
    link_re = re.compile(r'href=["\'](/[A-Za-z0-9_\-/]*)["\']')
    for base in _SCAN_DIRS:
        for f in base.rglob("*.astro"):
            for m in link_re.finditer(f.read_text()):
                target = m.group(1).rstrip("/")
                if target in redirecting:
                    violations.append(f"DEAD-LINK: {f.relative_to(_ROOT)} links to redirecting URL '{target}'")

    if violations:
        print("redirect-shadowing check FAILED:")
        for v in sorted(set(violations)):
            print("  " + v)
        return 1
    print(f"redirect-shadowing check OK — {len(sources)} rules, no page shadowed, no dead internal links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
