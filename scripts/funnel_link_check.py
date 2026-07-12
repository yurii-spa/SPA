#!/usr/bin/env python3
"""Funnel / cross-repo link-integrity check (UX-13 durable guard).

A broken link ANYWHERE in the conversion path (entry → snapshot/checkup → packages → pilot) silently
kills conversion — the page still returns 200, the CTA just 404s. This script crawls the funnel-critical
pages on BOTH domains (earn-defi.com landing + checkup.earn-defi.com), resolves every internal and
cross-domain href they emit, and fails if any lands on a non-2xx/3xx.

  * stdlib-only (urllib), deterministic, advisory/read-only — hits live URLs, mutates nothing.
  * Exit 0 ⇔ every funnel link resolves; exit 1 ⇔ a real broken link (named). Network/timeout errors
    are reported SEPARATELY (exit 2) so a flaky run is never mistaken for a broken funnel.
  * CI-usable: wire as an advisory step; a hard 404 in the conversion path should page someone.

    python3 scripts/funnel_link_check.py            # human summary
    python3 scripts/funnel_link_check.py --json      # machine output

Honest scope: this checks REACHABILITY (does the URL resolve), not content correctness. It is a
regression tripwire for the funnel, not a substitute for the honesty/number guards.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import urllib.error

LANDING = "https://earn-defi.com"
CHECKUP = "https://checkup.earn-defi.com"

# The conversion-critical pages whose outbound links must never 404. Kept small + explicit so the
# check is fast and its intent is legible (this IS the funnel).
FUNNEL_PAGES = [
    f"{LANDING}/",
    f"{LANDING}/snapshot/",
    f"{LANDING}/how-we-think/",
    f"{LANDING}/packages/",
    f"{LANDING}/pilot/",
    f"{LANDING}/fundability/",
    f"{LANDING}/protocols/steth/",
    f"{CHECKUP}/",
]

# Terminal routes that MUST exist even if a page fails to parse — the conversion dead-ends.
CRITICAL_ROUTES = [
    f"{LANDING}/snapshot/",
    f"{LANDING}/packages/",
    f"{LANDING}/pilot/",
    f"{CHECKUP}/check",
]

_UA = "spa-funnel-link-check/1.0 (advisory)"
_HREF = re.compile(r'href="(/[a-zA-Z0-9\-/]*|https://(?:checkup\.)?earn-defi\.com/[a-zA-Z0-9\-/?=_.]*)"')
_TITLE = re.compile(r"<title>([^<]*)</title>", re.I)
# The landing homepage's <title>. CF Pages historically served the homepage with HTTP 200 for unmatched
# routes (a soft-404) — so a status check alone can miss a broken internal link. If a NON-home URL comes
# back carrying the homepage title, treat it as a soft-404 (broken) even on a 200.
_HOME_TITLE_MARK = "systematic onchain stablecoin yield"


def _title_of(html: str) -> str:
    m = _TITLE.search(html)
    return (m.group(1) if m else "").strip()


def _fetch(url: str, timeout: int = 15) -> tuple[int | None, str]:
    """Return (status_code, body). status_code None ⇒ network error (not a 404)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""  # DNS/timeout/reset — a transient, NOT a broken link


def _norm(href: str, base: str = LANDING) -> str:
    # Relative hrefs resolve against the ORIGIN of the page they were found on (a `/check` link on the
    # checkup page is a checkup route, NOT an earn-defi route) — otherwise cross-domain relative links
    # are falsely flagged as broken.
    full = href if href.startswith("http") else base + href
    full = full.split("#")[0].split("?")[0]
    if not full.rstrip("/").split("/")[-1].count("."):  # no file extension → dir route, add slash
        full = full.rstrip("/") + "/"
    return full


def run() -> dict:
    broken: list[dict] = []
    network_errors: list[dict] = []
    checked: set[str] = set()

    def probe(url: str, source: str) -> None:
        if url in checked:
            return
        checked.add(url)
        code, body = _fetch(url)
        if code is None:
            network_errors.append({"url": url, "from": source})
        elif code >= 400:
            broken.append({"url": url, "from": source, "code": code})
        else:
            # soft-404 guard: a non-home URL that returns the homepage title is a masked broken link.
            is_home = url.rstrip("/") in (LANDING, CHECKUP)
            if not is_home and _HOME_TITLE_MARK in _title_of(body).lower():
                broken.append({"url": url, "from": source, "code": code, "soft_404": True})

    # 1) crawl each funnel page's outbound links
    unreachable_pages = []
    for page in FUNNEL_PAGES:
        code, html = _fetch(page)
        if code is None:
            unreachable_pages.append(page)
            continue
        if code >= 400:
            broken.append({"url": page, "from": "FUNNEL_PAGE", "code": code})
            continue
        page_origin = CHECKUP if page.startswith(CHECKUP) else LANDING
        for h in set(_HREF.findall(html)):
            if h in ("/", "#") or h.startswith("/#"):
                continue
            probe(_norm(h, page_origin), page)

    # 2) the terminal routes must exist regardless
    for route in CRITICAL_ROUTES:
        probe(route, "CRITICAL_ROUTE")

    ok = not broken and not unreachable_pages
    return {
        "check": "funnel_link_integrity",
        "pages_crawled": len(FUNNEL_PAGES),
        "links_checked": len(checked),
        "broken": broken,
        "unreachable_pages": unreachable_pages,
        "network_errors": network_errors,
        "all_resolve": ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the conversion funnel has no broken links")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    res = run()
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"[funnel_link_check] crawled {res['pages_crawled']} funnel pages, "
              f"checked {res['links_checked']} unique links")
        if res["broken"]:
            print("  BROKEN (conversion-path 404s):")
            for b in res["broken"]:
                print(f"    [{b['code']}] {b['url']}  (from {b['from']})")
        if res["unreachable_pages"]:
            print(f"  UNREACHABLE funnel pages (network?): {res['unreachable_pages']}")
        if res["network_errors"]:
            print(f"  network errors on {len(res['network_errors'])} links (transient, not counted "
                  f"as broken)")
        if res["all_resolve"]:
            print("  ✓ every funnel link resolves — conversion path intact")

    if res["broken"]:
        return 1  # a real broken link in the funnel
    if res["unreachable_pages"]:
        return 2  # could not verify (network) — distinct from a broken link
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
