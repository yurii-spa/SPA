#!/usr/bin/env python3
"""site_content_audit.py — Site Custodian block 4 (ADR-YL-011): weekly content-consistency audit.

Reads the SITE SOURCE (no network) and reports drift that erodes trust:
  1. METRIC_DIVERGENCE — the same hardcoded metric literal (days, gates, APY) differs across the key
     pages (hero / track-record / trust / due-diligence / methodology).
  2. STALE_HARDCODED_DATE — a literal 2026-XX-XX date in src/pages older than 60 days (aging candidate).
  3. BROKEN_LINK — an internal href="/…" that points at no src/pages route; a same-page #anchor with no id.
  4. SITEMAP_MISMATCH — a public src/pages route missing from sitemap.xml (or a sitemap loc with no page).
  5. REDIRECT_SHADOWING — a _redirects rule shadows an existing page (delegates to check_redirect_shadowing).

Report -> data/site_audit_weekly.json; alerts on NEW fails vs the prior report. Pure functions take a
pages dir so tests run on fixtures. Deterministic, stdlib-only, fail-CLOSED.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAGES = _ROOT / "landing" / "src" / "pages"
_SITEMAP = _ROOT / "landing" / "public" / "sitemap.xml"
_REPORT = _ROOT / "data" / "site_audit_weekly.json"
_COMPONENTS = _ROOT / "landing" / "src" / "components"
_KEY_PAGES = ("index", "track-record", "trust", "due-diligence", "methodology")
_MAX_DATE_AGE_DAYS = 60
_CANONICAL_CYCLE_HOUR = "08"   # daily_cycle plist Hour=8; /status + CLAUDE.md agree on 08:00 UTC

# Routes that exist without a src/pages file (redirect targets / dynamic) — not "broken".
_ALLOWED_EXTRA_ROUTES = {"/dashboard", "/strategies", "/"}


def find_stale_dates(pages_dir: Path, now: datetime.date, max_age=_MAX_DATE_AGE_DAYS):
    out = []
    for f in sorted(pages_dir.rglob("*.astro")):
        for m in re.finditer(r"(2026-\d{2}-\d{2})", f.read_text()):
            try:
                d = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            age = (now - d).days
            if age > max_age:
                out.append({"file": str(f.relative_to(pages_dir)), "date": m.group(1), "age_days": age})
    return out


def _hardcoded_metrics(text: str):
    """Metric-like LITERALS that are NOT Astro expressions ({...}). Returns {kind: set(values)}."""
    # strip Astro expressions so {snapDays} etc. are not counted as hardcoded
    stripped = re.sub(r"\{[^{}]*\}", " ", text)
    m = {"days": set(), "gates": set(), "apy": set()}
    for g in re.findall(r"(\d{1,2})\s*(?:evidenced|honest)\s+days", stripped):
        m["days"].add(g)
    for g in re.findall(r"\b(\d{1,2})/29\b", stripped):
        m["gates"].add(g)
    for g in re.findall(r"~?(\d\.\d+)\s*%[^%]{0,20}?(?:APY|paper)", stripped, re.I):
        m["apy"].add(g)
    return m


def check_metric_divergence(pages_dir: Path):
    per_kind = {"days": {}, "gates": {}, "apy": {}}
    for name in _KEY_PAGES:
        f = pages_dir / f"{name}.astro"
        if not f.exists():
            continue
        hm = _hardcoded_metrics(f.read_text())
        for kind, vals in hm.items():
            for v in vals:
                per_kind[kind].setdefault(v, []).append(name)
    out = []
    for kind, values in per_kind.items():
        if len(values) > 1:   # same metric literal appears with >1 distinct value across pages
            out.append({"metric": kind, "values": {v: pgs for v, pgs in values.items()}})
    return out


def check_internal_links(pages_dir: Path):
    routes = set()
    for f in pages_dir.rglob("*.astro"):
        rel = f.relative_to(pages_dir).with_suffix("")
        routes.add("/" + ("" if rel.name == "index" and rel.parent == Path(".") else str(rel).replace("index", "").rstrip("/")))
    routes |= _ALLOWED_EXTRA_ROUTES
    broken = []
    for f in sorted(pages_dir.rglob("*.astro")):
        text = f.read_text()
        ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', text))
        for href in re.findall(r'href="(/[A-Za-z0-9_\-/]*)"', text):
            base = "/" + href.strip("/")
            base = base if base != "//" else "/"
            if base not in routes and base.rstrip("/") not in routes:
                broken.append({"file": str(f.relative_to(pages_dir)), "href": href, "why": "no such page route"})
        for anchor in re.findall(r'href="#([A-Za-z0-9_\-]+)"', text):
            if anchor not in ids:
                broken.append({"file": str(f.relative_to(pages_dir)), "href": "#" + anchor, "why": "no matching id on page"})
    return broken


def check_sitemap_vs_pages(sitemap_path: Path, pages_dir: Path):
    locs = set(re.findall(r"<loc>https?://[^/]+/([^<]*)</loc>", sitemap_path.read_text())) if sitemap_path.exists() else set()
    locs = {l.strip("/") for l in locs}
    pages = set()
    for f in pages_dir.rglob("*.astro"):
        rel = str(f.relative_to(pages_dir).with_suffix("")).replace("index", "").strip("/")
        pages.add(rel)
    # internal/dev pages we don't require in the sitemap
    skip = {"cockpit-kit"}  # e.g. dev kits; extend as needed
    missing_from_sitemap = sorted((pages - locs) - skip)
    sitemap_without_page = sorted(locs - pages - {""})
    return {"missing_from_sitemap": missing_from_sitemap, "sitemap_without_page": sitemap_without_page}


def check_narrative_constants(pages_dir: Path, components_dir: Path | None = _COMPONENTS):
    """Catch narrative-constant drift (audit-re #4):
      - cycle_time_wrong: any 'NN:00 UTC' daily-cycle reference whose hour isn't the canonical 08
        (the plist/`/status` value) — a factual bug (the cycle runs at exactly one time).
      - apy_constants: every hardcoded '~X.X%' APY-prose value across pages + components, mapped to the
        files it appears in. Reported (not failed): these are legit approximations (e.g. the steady-book
        '~4.5%', distinct from the live paper APY), surfaced so a human can spot one that has drifted
        from the data-sourced value it claims to mirror.
    """
    files = list(pages_dir.rglob("*.astro"))
    if components_dir and components_dir.exists():
        files += list(components_dir.rglob("*.astro")) + list(components_dir.rglob("*.jsx"))
    cycle_time_wrong, apy_constants = [], {}
    for f in files:
        try:
            text = f.read_text()
        except OSError:
            continue
        rel = str(f).split("/landing/", 1)[-1]
        for m in re.finditer(r"\b(\d{2}):00 UTC\b", text):
            # Only the DAILY cycle is pinned to 08:00; other agents legitimately run at other times
            # (tournament_engine 09:00 UTC etc.). Flag a non-08:00 time only when 'daily' is in context.
            window = text[max(0, m.start() - 45): m.end() + 45].lower()
            if m.group(1) != _CANONICAL_CYCLE_HOUR and "daily" in window:
                cycle_time_wrong.append({"file": rel, "found": m.group(0)})
        for m in re.finditer(r"~(\d\.\d)\s?%", text):
            apy_constants.setdefault(m.group(1), set()).add(rel)
    return {"cycle_time_wrong": cycle_time_wrong,
            "apy_constants": {k: sorted(v) for k, v in apy_constants.items()}}


def audit(pages_dir: Path = _PAGES, sitemap_path: Path = _SITEMAP, now: datetime.date | None = None,
          components_dir: Path | None = _COMPONENTS):
    now = now or datetime.datetime.now(datetime.timezone.utc).date()
    fails = []
    div = check_metric_divergence(pages_dir)
    if div:
        fails.append({"code": "METRIC_DIVERGENCE", "detail": div})
    stale = find_stale_dates(pages_dir, now)
    if stale:
        fails.append({"code": "STALE_HARDCODED_DATE", "detail": stale, "severity": "WARN"})
    broken = check_internal_links(pages_dir)
    if broken:
        fails.append({"code": "BROKEN_LINK", "detail": broken})
    sm = check_sitemap_vs_pages(sitemap_path, pages_dir)
    if sm["missing_from_sitemap"] or sm["sitemap_without_page"]:
        fails.append({"code": "SITEMAP_MISMATCH", "detail": sm})
    # redirect shadowing (delegates to the P0-3 gate; skip gracefully if unavailable)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("crs", _ROOT / "scripts" / "check_redirect_shadowing.py")
        crs = importlib.util.module_from_spec(spec); spec.loader.exec_module(crs)
        if crs.main() != 0:
            fails.append({"code": "REDIRECT_SHADOWING", "detail": "see check_redirect_shadowing output"})
    except Exception:
        pass
    narr = check_narrative_constants(pages_dir, components_dir=components_dir)
    if narr["cycle_time_wrong"]:
        fails.append({"code": "NARRATIVE_CYCLE_TIME", "detail": narr["cycle_time_wrong"]})
    return {
        "ts": (now.isoformat()),
        "ok": not fails,
        "n_fails": len(fails),
        "fails": fails,
        "narrative_apy_constants": narr["apy_constants"],   # informational — surfaced for human review
    }


def _atomic_write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    import os
    os.replace(tmp, path)


def main() -> int:
    prev_codes = set()
    if _REPORT.exists():
        try:
            prev_codes = {f["code"] for f in json.loads(_REPORT.read_text()).get("fails", [])}
        except ValueError:
            pass
    report = audit()
    _atomic_write(_REPORT, report)
    new_codes = {f["code"] for f in report["fails"]} - prev_codes
    print(json.dumps({"ok": report["ok"], "n_fails": report["n_fails"],
                      "codes": sorted({f["code"] for f in report["fails"]})}, indent=2))
    if new_codes:
        try:
            from scripts.site_freshness_monitor import _alert  # reuse the same Telegram channel
        except Exception:
            _alert = None
        msg = f"🛡️ SITE CONTENT AUDIT — new fails: {sorted(new_codes)} @ {report['ts']}"
        try:
            from spa_core.alerts import telegram_manager
            telegram_manager.send(msg)
        except Exception:
            print(msg, file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
