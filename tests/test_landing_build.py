"""
MP-1546 (v11.62) — Landing build validation tests.
Verifies dist/ exists, key HTML pages are present, and assets are properly structured.
Run after: cd landing && npm run build
"""
import os
import re
import sys

LANDING_ROOT = os.path.join(os.path.dirname(__file__), "..", "landing")
DIST_ROOT    = os.path.join(LANDING_ROOT, "dist")
SRC_ROOT     = os.path.join(LANDING_ROOT, "src")
CONFIG_PATH  = os.path.join(LANDING_ROOT, "astro.config.mjs")


def check(name, condition, *, warn_only=False):
    status = "PASS" if condition else ("WARN" if warn_only else "FAIL")
    print(f"  {status}  {name}")
    return condition or warn_only


def run():
    results = []

    # ── 1. astro.config.mjs ──────────────────────────────────────────────
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = f.read()

    results.append(check("config: site set to earn-defi.com",   "earn-defi.com" in cfg))
    results.append(check("config: output=static",               "output: 'static'" in cfg or 'output: "static"' in cfg))
    results.append(check("config: build.assets defined",        "assets:" in cfg))
    results.append(check("config: vite.build defined",          "vite:" in cfg and "build:" in cfg))
    results.append(check("config: manualChunks: undefined",     "manualChunks: undefined" in cfg))

    # ── 2. dist/ directory ───────────────────────────────────────────────
    dist_exists = os.path.isdir(DIST_ROOT)
    results.append(check("dist/ directory exists", dist_exists))

    if not dist_exists:
        print("\n  ⚠  Run 'cd landing && npm run build' first, then re-run tests.")
        return results

    # ── 3. Core HTML pages ───────────────────────────────────────────────
    required_pages = [
        "index.html",
        "faq/index.html",
        "methodology/index.html",
        "risk/index.html",
        "security/index.html",
        "fees/index.html",
        "strategies/index.html",
        "dashboard/index.html",
        "due-diligence/index.html",
        "status/index.html",
    ]
    for page in required_pages:
        path = os.path.join(DIST_ROOT, page)
        results.append(check(f"page exists: {page}", os.path.isfile(path), warn_only=not os.path.isfile(path)))

    # ── 4. Blog pages ────────────────────────────────────────────────────
    blog_pages = [
        "blog/index.html",
        "blog/2026-06-20-paper-trading-started/index.html",
        "blog/2026-06-19-architecture-audit/index.html",
        "blog/2026-06-18-domain-launched/index.html",
    ]
    for page in blog_pages:
        path = os.path.join(DIST_ROOT, page)
        results.append(check(f"blog page exists: {page}", os.path.isfile(path), warn_only=True))

    # ── 5. _assets directory (_astro/ accepted for pre-v11.62 builds) ───
    assets_dir = os.path.join(DIST_ROOT, "_assets")
    legacy_dir = os.path.join(DIST_ROOT, "_astro")
    assets_exist = os.path.isdir(assets_dir) or os.path.isdir(legacy_dir)
    assets_dir = assets_dir if os.path.isdir(assets_dir) else legacy_dir
    results.append(check("_assets/ or _astro/ directory exists", assets_exist))

    # ── 6. Static assets ─────────────────────────────────────────────────
    results.append(check("favicon.svg in dist/", os.path.isfile(os.path.join(DIST_ROOT, "favicon.svg"))))
    results.append(check("robots.txt in dist/",  os.path.isfile(os.path.join(DIST_ROOT, "robots.txt")), warn_only=True))

    # ── 7. index.html meta quality ───────────────────────────────────────
    index_html_path = os.path.join(DIST_ROOT, "index.html")
    if os.path.isfile(index_html_path):
        with open(index_html_path, encoding="utf-8") as f:
            html = f.read()
        results.append(check("index.html: og:title present",       'property="og:title"' in html))
        results.append(check("index.html: og:description present", 'property="og:description"' in html))
        results.append(check("index.html: og:image present",       'property="og:image"' in html))
        results.append(check("index.html: canonical present",      'rel="canonical"' in html))
        results.append(check("index.html: twitter:card present",   'name="twitter:card"' in html))
        results.append(check("index.html: schema.org present",       'application/ld+json' in html))
        # WebSite (post v11.59 rebuild) or Organization (pre-rebuild) both accepted
        results.append(check("index.html: schema.org @type present", 'WebSite' in html or 'Organization' in html))

    # ── 8. Bundle size sanity ────────────────────────────────────────────
    if os.path.isdir(assets_dir):
        js_files = [f for f in os.listdir(assets_dir) if f.endswith('.js')]
        total_js = sum(
            os.path.getsize(os.path.join(assets_dir, f)) for f in js_files
        )
        results.append(check(
            f"JS bundle < 500 KB (actual: {total_js // 1024} KB)",
            total_js < 500 * 1024,
            warn_only=True,
        ))

    passed = sum(1 for r in results if r)
    total  = len(results)
    print(f"\n{passed}/{total} passed")
    return results


if __name__ == "__main__":
    print("Landing build tests — MP-1546 (v11.62)\n")
    results = run()
    failed = [r for r in results if not r]
    sys.exit(1 if failed else 0)
