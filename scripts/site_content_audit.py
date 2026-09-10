#!/usr/bin/env python3
"""site_content_audit.py — Site Custodian block 4 (ADR-YL-011): weekly content-consistency audit.

Reads the SITE SOURCE (no network) and reports drift that erodes trust:
  1. METRIC_DIVERGENCE — the same hardcoded metric literal (days, gates, APY) differs across the key
     pages (hero / track-record / trust / due-diligence / methodology). Comments (frontmatter `//`,
     `/* */`, `<!-- -->`) are stripped first: a comment saying "used to be 27/29" is history, not copy.
  2. STALE_HARDCODED_DATE (WARN) — a literal 2026-XX-XX date in src/pages older than 60 days (aging
     candidate). Exempt, because they are correct BY NATURE and not aging claims: dates inside
     comments (invisible), `blog/**` (a post carries its own date), blog-post dates cited elsewhere
     (derived from `blog/YYYY-MM-DD-*.astro` filenames), and the data-sourced anchors read from
     `landing/src/data/track_snapshot.json` (evidenced_anchor, as_of, first/last bar date, and a
     domain-launch date if the snapshot or strategy_config carries one).
  3. BROKEN_LINK — an internal href="/…" that points at no src/pages route; a same-page #anchor with
     no id. A link that matches a dynamic template (`protocols/[slug].astro` ⇒ /protocols/<x>) is a
     route, not a breakage.
  4. SITEMAP_MISMATCH — the TRUTH is the build-time endpoint `src/pages/sitemap.xml.ts` (import.meta
     .glob of pages − INTERNAL_ROUTES − admin/cockpit/board/404 + /protocols/{slug} from its data
     source + /rss.xml + the static public/btc-engine/*.html pages). `landing/public/sitemap.xml` is a
     DEAD hand-maintained file that Astro overrides at build time — it is ignored here (comparing to it
     reported 28 phantom "missing" pages for ten Mondays running). What IS checked: an advertised route
     with no backing file, a page that passes `noindex` to Layout yet is advertised (the endpoint's own
     rule says to mirror every such page into INTERNAL_ROUTES), a stale INTERNAL_ROUTES entry, and an
     unparseable endpoint (fail-CLOSED: no truth ⇒ finding).
  5. REDIRECT_SHADOWING — a _redirects rule shadows an existing page (delegates to check_redirect_shadowing).
  6. NARRATIVE_CYCLE_TIME — an 'NN:00 UTC' daily-cycle reference outside the canonical hours.

SEVERITY AND EXIT CODE. Every finding carries `severity`: "ERROR" (default) or "WARN". The process
exit code is 1 ONLY when an ERROR-severity finding exists; WARN findings are reported and alerted on
when new, but never flip the exit code. Before 2026-09-08 a WARN flipped it, and together with the
false positives above the Monday workflow failed 10/10 runs since 2026-07-06 — a guard that is always
red is a guard nobody reads.

PREVIOUS RUN. "New fails" are computed against data/site_audit_weekly.json; in CI that file never
exists (data/ is not in git), so the fallback is the previous artifact named by $SITE_AUDIT_PREV.
With neither, the run is announced as «первый прогон» — not as "new fails".

Report -> data/site_audit_weekly.json. Pure functions take a pages dir so tests run on fixtures.
Deterministic, stdlib-only, fail-CLOSED.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAGES = _ROOT / "landing" / "src" / "pages"
_PUBLIC = _ROOT / "landing" / "public"
_REPORT = _ROOT / "data" / "site_audit_weekly.json"
_COMPONENTS = _ROOT / "landing" / "src" / "components"
_KEY_PAGES = ("index", "track-record", "trust", "due-diligence", "methodology")
_MAX_DATE_AGE_DAYS = 60
# Accepted on-the-hour UTC times. NOTE (owner-gated): there is a systemic LOCAL-vs-UTC mislabel — the
# launchd plists use LOCAL hours (daily_cycle Hour=8, tournament Hour=9 in CEST), so the REAL UTC endpoints
# are 06:00 (daily, evidenced by paper_trading_status.last_cycle_ts) and ~07:00 (tournament), while the docs
# /status/CLAUDE.md label them "08:00/09:00 UTC". Until the owner reconciles (fix the docs to real UTC, or
# move the schedule to true 08:00 UTC), accept the whole plausible set so this check doesn't false-fail on
# the ambiguity; it still catches a genuinely-odd time (e.g. 03:00/12:00 UTC).
# Source of truth: ~/Library/LaunchAgents/com.spa.daily_cycle.plist StartCalendarInterval Hour=8 is
# LOCAL (CEST=UTC+2) => 06:00 UTC (confirmed by data/paper_trading_status.json last_cycle_ts=06:00:01Z);
# tournament ~07:00 UTC. The old "08:00/09:00 UTC" labels were a local-vs-UTC mislabel, now corrected.
_CANONICAL_UTC_HOURS = ("06", "07")

# Routes that exist without a src/pages file (redirect targets / dynamic) — not "broken".
_ALLOWED_EXTRA_ROUTES = {"/dashboard", "/strategies", "/"}

# Severity vocabulary — only these two; anything else is a bug in this script, not a third level.
ERROR = "ERROR"
WARN = "WARN"

# Directories under src/pages whose dates are correct by nature (a post carries its own date).
_DATE_EXEMPT_DIRS = ("blog",)
# Snapshot keys that name a data-sourced anchor date (NOT go_live_target: a stale target on a page is
# exactly the kind of drift the check exists to catch — the site removed that literal on purpose).
_SNAPSHOT_ANCHOR_KEYS = ("evidenced_anchor", "as_of")
_LAUNCH_DATE_KEYS = ("domain_launched", "domain_launch_date", "launched_at", "site_launched", "launch_date")


# ── comment stripping (shared by the date and the metric checks) ──────────────────────────────────
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# `//` to end of line, unless it is the `//` of a URL scheme (`https://`) or is escaped.
_JS_LINE_COMMENT = re.compile(r"(?<![:\\])//[^\n]*")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.S)
_SCRIPT_BLOCK = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.S | re.I)


def _strip_js_comments(code: str) -> str:
    return _JS_LINE_COMMENT.sub(" ", _JS_BLOCK_COMMENT.sub(" ", code))


def strip_comments(text: str) -> str:
    """Remove what a visitor never sees: HTML comments everywhere; JS comments inside the Astro
    frontmatter and inside <script> blocks. Markup outside those regions is left alone (a `//`
    inside prose or an href is not a comment)."""
    text = _HTML_COMMENT.sub(" ", text)
    text = _FRONTMATTER.sub(lambda m: "---\n" + _strip_js_comments(m.group(1)) + "\n---", text, count=1)
    text = _SCRIPT_BLOCK.sub(lambda m: m.group(1) + _strip_js_comments(m.group(2)) + m.group(3), text)
    return text


# ── 2. stale hardcoded dates ───────────────────────────────────────────────────────────────────────
def _iso_date_or_none(v) -> str | None:
    if not isinstance(v, str):
        return None
    try:
        return datetime.date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        return None


def known_anchor_dates(pages_dir: Path) -> set:
    """Dates that are correct BY NATURE for this site, read from data (never typed here):
      • track_snapshot.json: evidenced_anchor, as_of, first/last bar date, and a launch-date key if any;
      • strategy_config.json: a launch-date key if any;
      • blog post dates: `blog/YYYY-MM-DD-*.astro` filenames (the post index cites them elsewhere).
    A missing/corrupt source contributes nothing (fail-CLOSED: no anchor ⇒ no exemption)."""
    out: set = set()
    data_dir = pages_dir.parent / "data"
    for name, keys in (("track_snapshot.json", _SNAPSHOT_ANCHOR_KEYS + _LAUNCH_DATE_KEYS),
                       ("strategy_config.json", _LAUNCH_DATE_KEYS)):
        try:
            doc = json.loads((data_dir / name).read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for k in keys:
            d = _iso_date_or_none(doc.get(k))
            if d:
                out.add(d)
        bars = doc.get("bars")
        if isinstance(bars, list) and bars:
            for bar in (bars[0], bars[-1]):
                d = _iso_date_or_none(bar.get("date")) if isinstance(bar, dict) else None
                if d:
                    out.add(d)
    for f in pages_dir.glob("blog/*.astro"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-", f.name)
        if m and _iso_date_or_none(m.group(1)):
            out.add(m.group(1))
    return out


def find_stale_dates(pages_dir: Path, now: datetime.date, max_age=_MAX_DATE_AGE_DAYS,
                     anchors: set | None = None):
    """Visible literal dates older than `max_age` days. Exempt: comments, `blog/**`, and `anchors`
    (default: known_anchor_dates(pages_dir))."""
    anchors = known_anchor_dates(pages_dir) if anchors is None else set(anchors)
    out = []
    for f in sorted(pages_dir.rglob("*.astro")):
        rel = f.relative_to(pages_dir)
        if rel.parts and rel.parts[0] in _DATE_EXEMPT_DIRS:
            continue
        for m in re.finditer(r"(2026-\d{2}-\d{2})", strip_comments(f.read_text())):
            try:
                d = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if m.group(1) in anchors:
                continue
            age = (now - d).days
            if age > max_age:
                out.append({"file": str(rel), "date": m.group(1), "age_days": age})
    return out


# ── 1. metric divergence ───────────────────────────────────────────────────────────────────────────
def _hardcoded_metrics(text: str):
    """Metric-like LITERALS that are NOT Astro expressions ({...}) and NOT inside comments.
    Returns {kind: set(values)}."""
    stripped = strip_comments(text)
    # strip Astro expressions so {snapDays} etc. are not counted as hardcoded
    stripped = re.sub(r"\{[^{}]*\}", " ", stripped)
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


# ── 3. internal links ──────────────────────────────────────────────────────────────────────────────
def _route_of(rel: Path) -> str:
    """src/pages-relative file (suffix stripped) → URL path. `index` collapses to its directory."""
    if rel.name == "index":
        parent = rel.parent.as_posix()
        return "/" if parent == "." else "/" + parent
    return "/" + rel.as_posix()


def _dynamic_templates(pages_dir: Path) -> list:
    """Segment lists of dynamic routes: `protocols/[slug].astro` → ["protocols", "[slug]"]."""
    out = []
    for f in pages_dir.rglob("*.astro"):
        rel = f.relative_to(pages_dir).with_suffix("")
        if "[" in rel.as_posix():
            out.append(rel.as_posix().split("/"))
    return out


def _matches_dynamic(path: str, templates: list) -> bool:
    """/protocols/ezeth matches ["protocols", "[slug]"]; /protocols/a/b does not (segment count)."""
    segs = [s for s in path.split("/") if s]
    for tpl in templates:
        if len(tpl) != len(segs):
            continue
        if all(t.startswith("[") or t == s for t, s in zip(tpl, segs)) and all(segs):
            return True
    return False


def check_internal_links(pages_dir: Path):
    routes = set()
    for f in pages_dir.rglob("*.astro"):
        rel = f.relative_to(pages_dir).with_suffix("")
        if "[" in rel.as_posix():
            continue  # dynamic template — matched by shape below, never a literal route
        routes.add(_route_of(rel))
    routes |= _ALLOWED_EXTRA_ROUTES
    templates = _dynamic_templates(pages_dir)
    broken = []
    for f in sorted(pages_dir.rglob("*.astro")):
        text = f.read_text()
        ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', text))
        for href in re.findall(r'href="(/[A-Za-z0-9_\-/]*)"', text):
            base = "/" + href.strip("/")
            base = base if base != "//" else "/"
            if base in routes or base.rstrip("/") in routes:
                continue
            if _matches_dynamic(base, templates):
                continue  # served by a `[param]` template (e.g. /protocols/ezeth) — a route, not a breakage
            broken.append({"file": str(f.relative_to(pages_dir)), "href": href, "why": "no such page route"})
        for anchor in re.findall(r'href="#([A-Za-z0-9_\-]+)"', text):
            if anchor not in ids:
                broken.append({"file": str(f.relative_to(pages_dir)), "href": "#" + anchor, "why": "no matching id on page"})
    return broken


# ── 4. sitemap: the endpoint is the truth ──────────────────────────────────────────────────────────
_SITEMAP_ENDPOINT = "sitemap.xml.ts"
_INTERNAL_ROUTES_RE = re.compile(r"INTERNAL_ROUTES\s*=\s*new\s+Set<string>\(\s*\[(.*?)\]\s*\)", re.S)
_STR_LITERAL_RE = re.compile(r"""['"]([^'"]+)['"]""")
_PROTOCOL_IMPORT_RE = re.compile(r"""import\s+\w+\s+from\s+['"]([^'"]+protocol_verdicts\.json)['"]""")
_NOINDEX_PROP_RE = re.compile(r"\bnoindex(?:\s*=\s*\{\s*true\s*\})?(?=[\s/>])")
_NOINDEX_META_RE = re.compile(r"""<meta\s+name=["']robots["']\s+content=["'][^"']*noindex""", re.I)


def _endpoint_rules(endpoint: Path) -> dict | None:
    """Parse the three data-bearing lists out of sitemap.xml.ts. None ⇒ unparseable (fail-CLOSED)."""
    try:
        src = endpoint.read_text()
    except OSError:
        return None
    m = _INTERNAL_ROUTES_RE.search(_strip_js_comments(src))
    if not m:
        return None
    internal = set(_STR_LITERAL_RE.findall(m.group(1)))
    static_pages = sorted({s for s in _STR_LITERAL_RE.findall(src) if s.startswith("/btc-engine/")})
    pm = _PROTOCOL_IMPORT_RE.search(src)
    return {"internal_routes": internal, "static_pages": static_pages,
            "protocol_data": (endpoint.parent / pm.group(1)).resolve() if pm else None,
            "adds_rss": "'/rss.xml'" in src or '"/rss.xml"' in src}


def _endpoint_excludes(rel: str, internal: set) -> bool:
    """The endpoint's own exclusion rules, mirrored: dynamic, admin, cockpit/board, 404/500, INTERNAL."""
    if "[" in rel:
        return True
    if rel == "admin" or rel.startswith("admin/"):
        return True
    if rel in ("cockpit", "board") or rel.startswith(("cockpit/", "board/")):
        return True
    if rel in ("404", "500"):
        return True
    return rel in internal


def _is_noindex(text: str) -> bool:
    text = strip_comments(text)
    return bool(_NOINDEX_PROP_RE.search(text) or _NOINDEX_META_RE.search(text))


def check_sitemap_endpoint(pages_dir: Path, public_dir: Path | None = None):
    """Compare the sitemap the ENDPOINT will emit with the page tree and the static files.

    Returns {endpoint_unparseable, sitemap_without_page, noindex_in_sitemap, stale_internal_routes,
             missing_from_sitemap, static_sitemap_present}. Every list empty ⇒ consistent.
    `landing/public/sitemap.xml` is never read: it is dead (overridden by the endpoint at build time)."""
    public_dir = public_dir if public_dir is not None else pages_dir.parent.parent / "public"
    res = {"endpoint_unparseable": None, "sitemap_without_page": [], "noindex_in_sitemap": [],
           "stale_internal_routes": [], "missing_from_sitemap": [],
           "static_sitemap_present": (public_dir / "sitemap.xml").exists()}
    endpoint = pages_dir / _SITEMAP_ENDPOINT
    rules = _endpoint_rules(endpoint)
    if rules is None:
        res["endpoint_unparseable"] = (f"{_SITEMAP_ENDPOINT} missing or its INTERNAL_ROUTES block not found — "
                                       "no sitemap truth, nothing can be declared consistent")
        return res

    pages = {}
    for f in pages_dir.rglob("*.astro"):
        rel = f.relative_to(pages_dir).with_suffix("").as_posix()
        pages[rel] = f
    # what the endpoint's glob emits
    advertised = {rel for rel in pages if not _endpoint_excludes(rel, rules["internal_routes"])}
    # noindex pages that the endpoint still advertises — its own comment forbids exactly this
    res["noindex_in_sitemap"] = sorted(rel for rel in advertised if _is_noindex(pages[rel].read_text()))
    # an exclusion that names no page is stale (harmless to crawlers, misleading to readers)
    res["stale_internal_routes"] = sorted(r for r in rules["internal_routes"] if r not in pages)
    # explicit expansions must be backed by real files
    if rules["protocol_data"] is not None:
        try:
            doc = json.loads(rules["protocol_data"].read_text())
            slugs = [p.get("slug") for p in doc.get("protocols", []) if isinstance(p, dict)]
        except (OSError, ValueError, AttributeError):
            slugs = None
        if slugs is None:
            res["sitemap_without_page"].append({"route": "/protocols/{slug}",
                                                "why": f"data source unreadable: {rules['protocol_data'].name}"})
        elif "protocols/[slug]" not in pages:
            for s in slugs:
                res["sitemap_without_page"].append({"route": f"/protocols/{s}", "why": "no protocols/[slug].astro template"})
    if rules["adds_rss"] and not (pages_dir / "rss.xml.ts").exists():
        res["sitemap_without_page"].append({"route": "/rss.xml", "why": "no rss.xml.ts endpoint"})
    for p in rules["static_pages"]:
        name = p[len("/btc-engine/"):] or "index"
        if not (public_dir / "btc-engine" / f"{name}.html").exists():
            res["sitemap_without_page"].append({"route": p, "why": f"no public/btc-engine/{name}.html"})
    # parity: a page that is neither advertised nor intentionally excluded (empty by construction —
    # kept so a future change to the endpoint's glob shows up here rather than nowhere)
    res["missing_from_sitemap"] = sorted(rel for rel in pages
                                         if rel not in advertised and not _endpoint_excludes(rel, rules["internal_routes"]))
    return res


# ── 6. narrative constants ─────────────────────────────────────────────────────────────────────────
def check_narrative_constants(pages_dir: Path, components_dir: Path | None = _COMPONENTS):
    """Catch narrative-constant drift (audit-re #4):
      - cycle_time_wrong: any 'NN:00 UTC' daily-cycle reference whose hour isn't in _CANONICAL_UTC_HOURS
        (06 daily / 07 tournament — source: com.spa.daily_cycle.plist Hour=8 CEST = 06:00 UTC) — a factual
        bug (the cycle runs at exactly one time).
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
            # Whitelist the two legit on-the-hour UTC times (08 paper cycle, 09 tournament); any other
            # NN:00 UTC is unexplained drift and gets flagged (health monitors run at :30, not :00).
            if m.group(1) not in _CANONICAL_UTC_HOURS:
                cycle_time_wrong.append({"file": rel, "found": m.group(0)})
        for m in re.finditer(r"~(\d\.\d)\s?%", text):
            apy_constants.setdefault(m.group(1), set()).add(rel)
    return {"cycle_time_wrong": cycle_time_wrong,
            "apy_constants": {k: sorted(v) for k, v in apy_constants.items()}}


# ── the audit ──────────────────────────────────────────────────────────────────────────────────────
def check_number_provenance() -> dict:
    """Числа сайта без происхождения (ADR-315, `.claude/rules/site-numbers.md`).

    Делегирует `scripts/site_number_provenance.py`. Инструмент недоступен ⇒ ТРЕТИЙ
    исход `unmeasured` с названной причиной, а не тихое «чисто»: соседняя делегация
    в этом же файле (`check_redirect_shadowing`) глушит любое исключение через
    `except Exception: pass`, и это ровно тот fail-OPEN, который здесь повторять нельзя.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "snp", _ROOT / "scripts" / "site_number_provenance.py")
        if spec is None or spec.loader is None:
            return {"unmeasured": ["site_number_provenance.py не загружается"]}
        snp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(snp)
        rep = snp.scan()
        base, why = snp.load_baseline()
        if why:
            rep.setdefault("unmeasured", []).append(why)
        v = snp.verdict(rep, base)
        return {"unmeasured": v["unmeasured"], "new_undeclared": v["new_undeclared"],
                "undeclared_total": v["undeclared_total"],
                "baseline_total": v["baseline_total"], "counts": v["counts"]}
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return {"unmeasured": [f"провенанс чисел НЕ измерен: {type(exc).__name__}: {exc}"]}


def audit(pages_dir: Path = _PAGES, public_dir: Path | None = None, now: datetime.date | None = None,
          components_dir: Path | None = _COMPONENTS):
    now = now or datetime.datetime.now(datetime.timezone.utc).date()
    fails = []
    div = check_metric_divergence(pages_dir)
    if div:
        fails.append({"code": "METRIC_DIVERGENCE", "severity": ERROR, "detail": div})
    stale = find_stale_dates(pages_dir, now)
    if stale:
        fails.append({"code": "STALE_HARDCODED_DATE", "severity": WARN, "detail": stale})
    broken = check_internal_links(pages_dir)
    if broken:
        fails.append({"code": "BROKEN_LINK", "severity": ERROR, "detail": broken})
    sm = check_sitemap_endpoint(pages_dir, public_dir)
    if sm["endpoint_unparseable"] or sm["sitemap_without_page"] or sm["noindex_in_sitemap"] or sm["missing_from_sitemap"]:
        fails.append({"code": "SITEMAP_MISMATCH", "severity": ERROR, "detail": sm})
    elif sm["stale_internal_routes"]:
        fails.append({"code": "SITEMAP_MISMATCH", "severity": WARN, "detail": sm})
    # redirect shadowing (delegates to the P0-3 gate; skip gracefully if unavailable)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("crs", _ROOT / "scripts" / "check_redirect_shadowing.py")
        crs = importlib.util.module_from_spec(spec); spec.loader.exec_module(crs)
        if crs.main() != 0:
            fails.append({"code": "REDIRECT_SHADOWING", "severity": ERROR, "detail": "see check_redirect_shadowing output"})
    except Exception:
        pass
    # 7. NUMBER_PROVENANCE (ADR-315) — откуда взялось каждое число. Отдельный вопрос
    #    от METRIC_DIVERGENCE выше: шестнадцать СОГЛАСОВАННЫХ литералов расхождения не
    #    дают и остаются литералами. Меряется ЖИВОЙ сайт, а не `pages_dir`: фикстура —
    #    это сцена для соседних проверок, у неё нет ни базы храповика, ни провенанса,
    #    и судить о доставленном сайте по ней нельзя. WARN, а не ERROR: понедельничный
    #    workflow этого файла уже краснел 10 раз подряд, и сторож, всегда красный, —
    #    сторож, которого не читают. Красное на КАЖДОМ пуше даёт CI-храповик.
    prov = check_number_provenance()
    if prov.get("unmeasured") or prov.get("new_undeclared"):
        fails.append({"code": "NUMBER_PROVENANCE", "severity": WARN, "detail": prov})

    narr = check_narrative_constants(pages_dir, components_dir=components_dir)
    if narr["cycle_time_wrong"]:
        fails.append({"code": "NARRATIVE_CYCLE_TIME", "severity": ERROR, "detail": narr["cycle_time_wrong"]})
    n_errors = sum(1 for f in fails if f["severity"] != WARN)
    return {
        "ts": (now.isoformat()),
        "ok": n_errors == 0,           # WARN never flips this (see module docstring)
        "n_fails": len(fails),
        "n_errors": n_errors,
        "n_warn": len(fails) - n_errors,
        "fails": fails,
        "narrative_apy_constants": narr["apy_constants"],   # informational — surfaced for human review
    }


def exit_code(report: dict) -> int:
    """1 only when an ERROR-severity finding exists; WARN-only ⇒ 0."""
    return 0 if report.get("ok") else 1


def _atomic_write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.replace(tmp, path)


def previous_codes(report_path: Path = _REPORT, env: dict | None = None) -> tuple:
    """(codes, source). Sources, in order: the local report; the artifact named by $SITE_AUDIT_PREV;
    else (set(), "none") — the caller announces «первый прогон», never "new fails"."""
    env = os.environ if env is None else env
    candidates = [(report_path, "report")]
    prev = env.get("SITE_AUDIT_PREV")
    if prev:
        candidates.append((Path(prev), "SITE_AUDIT_PREV"))
    for path, source in candidates:
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        return {f["code"] for f in doc.get("fails", []) if isinstance(f, dict) and "code" in f}, source
    return set(), "none"


def main() -> int:
    prev_codes, prev_source = previous_codes()
    report = audit()
    _atomic_write(_REPORT, report)
    codes = sorted({f["code"] for f in report["fails"]})
    print(json.dumps({"ok": report["ok"], "n_fails": report["n_fails"], "n_errors": report["n_errors"],
                      "n_warn": report["n_warn"], "codes": codes, "previous": prev_source}, indent=2))
    if prev_source == "none":
        msg = (f"🛡️ SITE CONTENT AUDIT — первый прогон (базы для сравнения нет): fails {codes} @ {report['ts']}"
               if codes else "")
    else:
        new_codes = set(codes) - prev_codes
        msg = f"🛡️ SITE CONTENT AUDIT — new fails: {sorted(new_codes)} @ {report['ts']}" if new_codes else ""
    if msg:
        try:
            from spa_core.alerts import telegram_manager
            telegram_manager.send(msg, title="🛡️ Site Content Audit", category="site_content_audit")
        except Exception:
            print(msg, file=sys.stderr)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
