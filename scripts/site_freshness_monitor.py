#!/usr/bin/env python3
"""site_freshness_monitor.py — Site Custodian block 2+3 (ADR-YL-011): the INDEPENDENT checker.

It does NOT trust the deploy pipeline. It fetches the live site + live API + the repo snapshot from the
OUTSIDE and asserts the triple agrees, is fresh, is available, and — critically — that the site never
OVERSTATES a metric vs the live API. On any FAIL it writes data/site_freshness_report.json and alerts
through SPA's Telegram channel. Kill-rule: OVERSTATED_METRIC, or staleness > 48h on TWO consecutive runs,
flips the snapshot to degraded:true (hero shows "live data temporarily unavailable" instead of a wrong
number — refusal-first: honest absence beats a false figure).

Design: `evaluate()` is PURE (all inputs injected) so tests mock every HTTP call — no network in CI.
`run()` wires real urllib fetches. stdlib-only, deterministic, fail-CLOSED. Runs every 6h via
.github/workflows/site_freshness.yml AND can run on the Mac.

FAIL categories (each a distinct, logged reason-code):
  STALE_SNAPSHOT      — snapshot as_of older than 30h
  STALE_API           — API last evidenced bar older than 30h
  SITE_BEHIND_SNAPSHOT— live site numbers != repo snapshot (deploy lag)
  SNAPSHOT_BEHIND_API — repo snapshot != live API (cycle ran, snapshot not regenerated)
  OVERSTATED_METRIC   — site shows an APY HIGHER than the live API (critical; never allowed)
  MISSING_ASOF        — live page has no as-of label, or it disagrees with the snapshot
  UNAVAILABLE         — a sitemap URL is not 200 / redirects unexpectedly
  VERIFIER_PIN_MISMATCH — live verify_spa.py SHA-256 != the published pin
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_SITEMAP = _ROOT / "landing" / "public" / "sitemap.xml"
_REPORT = _ROOT / "data" / "site_freshness_report.json"

SITE = "https://earn-defi.com"
API = "https://api.earn-defi.com"

APY_TOL_PP = 0.05          # allowed APY divergence in percentage points
STALE_HOURS = 30           # freshness bar
DEGRADE_STALE_HOURS = 48   # kill-rule staleness threshold


# ─────────────────────────────── helpers ───────────────────────────────
def _num(s):
    try:
        return float(str(s).replace(",", "").replace("$", "").replace("~", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _hours_since(date_str, now):
    """Hours from a YYYY-MM-DD (or ISO) date string to `now` (utc). None if unparseable."""
    if not date_str:
        return None
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return None
    delta = now - datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    return delta.total_seconds() / 3600.0


def parse_site_numbers(html):
    """Extract the public headline numbers from rendered HTML (P1-6 static ids). None if absent."""
    if not html:
        return {}
    def g(pat):
        m = re.search(pat, html)
        return m.group(1) if m else None
    return {
        "evidenced_days": _num(g(r'id="sl-day">\s*~?([\d,]+)') or g(r'id="tr-days-2">\s*([\d,]+)')),
        "paper_apy_pct": _num(g(r'id="sl-apy">\s*~?([\d.]+)%') or g(r'id="tr-apy">\s*~?([\d.]+)%')),
        "gates_passed": _num(g(r'id="sl-gates">\s*([\d]+)/')),
        "end_equity": _num(g(r'id="tr-equity">\s*\$?([\d,]+)')),
        "as_of": g(r'as of (\d{4}-\d{2}-\d{2})') or g(r'static snapshot as of (\d{4}-\d{2}-\d{2})'),
    }


def api_headline(golive, facts, equity_chain):
    """Best-effort authoritative headline from the live API (defensive field extraction)."""
    g = golive or {}
    f = facts or {}
    out = {
        "evidenced_days": _num(g.get("real_track_days") if g.get("real_track_days") is not None else g.get("track_days")),
        "gates_passed": _num(g.get("passed") if g.get("passed") is not None else g.get("risk_gates_passed")),
        "paper_apy_pct": _num(f.get("apy_today_pct") if f.get("apy_today_pct") is not None else g.get("apy_today_pct")),
        "end_equity": _num(f.get("current_equity") if f.get("current_equity") is not None else f.get("equity")),
        "last_bar": None,
    }
    # last evidenced bar date from the equity chain (freshness)
    rows = equity_chain if isinstance(equity_chain, list) else (equity_chain or {}).get("rows") or (equity_chain or {}).get("data")
    if isinstance(rows, list) and rows:
        last = rows[-1] if isinstance(rows[-1], dict) else {}
        out["last_bar"] = last.get("date") or last.get("ts")
    return out


# ─────────────────────────────── the pure evaluator ───────────────────────────────
def evaluate(*, snapshot, home_html, track_html, api, sitemap_statuses, verifier_sha, pin_sha,
             now, prev_report=None):
    """Pure Site-Custodian evaluation. Returns the report dict. No I/O."""
    fails = []          # list of {code, detail, severity}
    def fail(code, detail, severity="FAIL"):
        fails.append({"code": code, "detail": detail, "severity": severity})

    snap = snapshot or {}
    site_home = parse_site_numbers(home_html)
    site_track = parse_site_numbers(track_html)
    apih = api or {}

    # 1. snapshot freshness
    snap_age = _hours_since(snap.get("as_of"), now)
    if snap_age is None:
        fail("MISSING_ASOF", "snapshot has no parseable as_of")
    elif snap_age > STALE_HOURS:
        fail("STALE_SNAPSHOT", f"snapshot as_of {snap.get('as_of')} is {snap_age:.1f}h old (> {STALE_HOURS}h)")

    # 2. API last-bar freshness
    api_age = _hours_since(apih.get("last_bar"), now)
    if apih.get("last_bar") and api_age is not None and api_age > STALE_HOURS:
        fail("STALE_API", f"API last bar {apih.get('last_bar')} is {api_age:.1f}h old (> {STALE_HOURS}h)")

    # 3. site page carries an as-of label matching the snapshot
    for name, s in (("home", site_home), ("track", site_track)):
        if s.get("as_of") is None:
            fail("MISSING_ASOF", f"{name} page has no as-of label")
        elif snap.get("as_of") and s["as_of"] != snap["as_of"]:
            fail("SITE_BEHIND_SNAPSHOT", f"{name} as-of {s['as_of']} != snapshot as_of {snap['as_of']}")

    # 4. site == snapshot (deploy lag)
    def cmp_int(label, site_v, snap_v):
        if site_v is not None and snap_v is not None and abs(site_v - snap_v) >= 1:
            fail("SITE_BEHIND_SNAPSHOT", f"site {label}={site_v} != snapshot {label}={snap_v}")
    cmp_int("evidenced_days", site_home.get("evidenced_days"), _num(snap.get("real_track_days")))
    cmp_int("gates_passed", site_home.get("gates_passed"), _num(snap.get("gates_passed")))

    # 5. snapshot == API (snapshot regenerated after cycle?)
    if apih.get("evidenced_days") is not None and snap.get("real_track_days") is not None:
        if abs(apih["evidenced_days"] - _num(snap["real_track_days"])) >= 1:
            fail("SNAPSHOT_BEHIND_API", f"snapshot days={snap['real_track_days']} != API days={apih['evidenced_days']}")
    if apih.get("paper_apy_pct") is not None and snap.get("paper_apy_pct") is not None:
        if abs(apih["paper_apy_pct"] - _num(snap["paper_apy_pct"])) > APY_TOL_PP:
            fail("SNAPSHOT_BEHIND_API",
                 f"snapshot apy={snap['paper_apy_pct']} != API apy={apih['paper_apy_pct']} (>{APY_TOL_PP}pp)")

    # 6. OVERSTATED_METRIC — the site must NEVER show an APY higher than the live API (critical)
    api_apy = apih.get("paper_apy_pct")
    for name, s in (("home", site_home), ("track", site_track)):
        site_apy = s.get("paper_apy_pct")
        if site_apy is not None and api_apy is not None and site_apy > api_apy + APY_TOL_PP:
            fail("OVERSTATED_METRIC",
                 f"{name} shows APY {site_apy}% > live API {api_apy}% (+{APY_TOL_PP}pp tol)", severity="CRITICAL")

    # 7. availability — every sitemap URL 200, no unexpected redirect
    for url, code in (sitemap_statuses or {}).items():
        if code not in (200, 308):   # 308 = trailing-slash canonicalization, expected
            fail("UNAVAILABLE", f"{url} -> HTTP {code}")

    # 8. verifier pin
    if verifier_sha and pin_sha and verifier_sha != pin_sha:
        fail("VERIFIER_PIN_MISMATCH", f"live verify_spa.py {verifier_sha[:12]}… != pin {pin_sha[:12]}…")

    # ── kill-rule: OVERSTATED, or staleness>48h on TWO consecutive runs -> degrade ──
    overstated = any(f["code"] == "OVERSTATED_METRIC" for f in fails)
    stale_48 = (snap_age is not None and snap_age > DEGRADE_STALE_HOURS)
    prev_stale_48 = bool(prev_report and prev_report.get("stale_48h"))
    degrade = overstated or (stale_48 and prev_stale_48)

    return {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": not fails,
        "fails": fails,
        "n_fails": len(fails),
        "snapshot_age_h": round(snap_age, 2) if snap_age is not None else None,
        "api_age_h": round(api_age, 2) if api_age is not None else None,
        "stale_48h": stale_48,
        "degrade_triggered": degrade,
        "degrade_reason": ("OVERSTATED_METRIC" if overstated else
                           "STALE_48H_TWO_RUNS" if degrade else None),
        "site_home": site_home,
        "site_track": site_track,
        "snapshot": {k: snap.get(k) for k in ("as_of", "real_track_days", "paper_apy_pct", "gates_passed", "end_equity")},
        "api": apih,
    }


# ─────────────────────────────── I/O wrappers ───────────────────────────────
def _get(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SPA-SiteCustodian/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception:
        return None, None


def _get_json(url):
    _, body = _get(url)
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _sitemap_urls():
    if not _SITEMAP.exists():
        return []
    return re.findall(r"<loc>([^<]+)</loc>", _SITEMAP.read_text())


def _atomic_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    import os
    os.replace(tmp, path)


def _alert(report):
    """Alert via SPA's Telegram channel (token from Keychain — never in code). Best-effort."""
    if report.get("ok"):
        return
    lines = [f"🛡️ SITE CUSTODIAN — {report['n_fails']} FAIL(s) @ {report['ts']}"]
    for f in report["fails"][:8]:
        lines.append(f"  [{f['severity']}] {f['code']}: {f['detail']}")
    if report.get("degrade_triggered"):
        lines.append(f"  ⛔ KILL-RULE: site set to DEGRADED ({report['degrade_reason']})")
    msg = "\n".join(lines)
    # 1. SPA telegram_manager (dedup/cooldown-aware). Only treat as delivered if it RETURNS truthy —
    #    it returns False (not raises) when its cooldown/creds gate suppresses the send.
    try:
        from spa_core.alerts import telegram_manager
        if telegram_manager.send(msg, title="🛡️ Site Custodian", category="site_custodian"):
            return
    except Exception:
        pass
    # 2. Raw Telegram API — reliable fallback (telegram_manager can silently suppress). Creds from env
    #    (CI secrets) or macOS Keychain (Mac). Never hardcoded.
    import os
    tok = os.environ.get("TELEGRAM_BOT_TOKEN_SPA")
    chat = os.environ.get("TELEGRAM_CHAT_ID_SPA")
    if not (tok and chat):
        try:
            tok = tok or subprocess.run(["security", "find-generic-password", "-s", "TELEGRAM_BOT_TOKEN_SPA", "-w"],
                                        capture_output=True, text=True, timeout=5).stdout.strip()
            chat = chat or subprocess.run(["security", "find-generic-password", "-s", "TELEGRAM_CHAT_ID_SPA", "-w"],
                                          capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass
    if tok and chat:
        try:
            data = json.dumps({"chat_id": chat, "text": msg}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                         data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
            return
        except Exception as e:
            print(f"site_freshness_monitor: raw telegram alert failed ({e})", file=sys.stderr)
    print("site_freshness_monitor: no alert channel available; report written (CI failure = the alert)",
          file=sys.stderr)


def _apply_degrade():
    """Kill-rule: flip the snapshot to degraded:true + deploy it (refusal-first showcase)."""
    try:
        snap = json.loads(_SNAP.read_text())
        if snap.get("degraded") is True:
            return
        snap["degraded"] = True
        _atomic_write(_SNAP, snap)
        subprocess.run([sys.executable, str(_ROOT / "push_to_github_batch.py"), "--files", str(_SNAP),
                        "--message", "chore(site-custodian): KILL-RULE degrade site (stale/overstated metric)"],
                       timeout=180)
        print("site_freshness_monitor: DEGRADED flag set + pushed")
    except Exception as e:
        print(f"site_freshness_monitor: degrade apply failed ({e})", file=sys.stderr)


def _clear_degrade():
    """Recovery: all checks pass and the snapshot is degraded -> lift the plaque (set False + deploy)."""
    try:
        snap = json.loads(_SNAP.read_text())
        if snap.get("degraded") is not True:
            return
        snap["degraded"] = False
        _atomic_write(_SNAP, snap)
        subprocess.run([sys.executable, str(_ROOT / "push_to_github_batch.py"), "--files", str(_SNAP),
                        "--message", "chore(site-custodian): recover — checks pass, lift degraded plaque"],
                       timeout=180)
        print("site_freshness_monitor: recovered — degraded cleared + pushed")
    except Exception as e:
        print(f"site_freshness_monitor: clear-degrade failed ({e})", file=sys.stderr)


def run():
    now = datetime.datetime.now(datetime.timezone.utc)
    prev = None
    if _REPORT.exists():
        try:
            prev = json.loads(_REPORT.read_text())
        except ValueError:
            prev = None
    snapshot = json.loads(_SNAP.read_text()) if _SNAP.exists() else {}

    _, home_html = _get(SITE + "/")
    _, track_html = _get(SITE + "/track-record/")
    api = api_headline(
        _get_json(API + "/api/v1/golive"),
        _get_json(API + "/api/ssot/facts") or _get_json(API + "/api/live/portfolio"),
        _get_json(API + "/api/rates-desk/full-chain/equity_track"),
    )
    sitemap_statuses = {}
    for url in _sitemap_urls():
        code, _ = _get(url, timeout=12)
        sitemap_statuses[url] = code
    # verifier pin
    pin = None
    m = re.search(r"VERIFIER_SHA256\s*=\s*'([0-9a-f]{64})'",
                  (_ROOT / "landing" / "src" / "pages" / "verify.astro").read_text())
    pin = m.group(1) if m else None
    _, live_verifier = _get("https://raw.githubusercontent.com/yurii-spa/SPA/main/scripts/verify_spa.py")
    verifier_sha = hashlib.sha256(live_verifier.encode()).hexdigest() if live_verifier else None

    report = evaluate(snapshot=snapshot, home_html=home_html, track_html=track_html, api=api,
                      sitemap_statuses=sitemap_statuses, verifier_sha=verifier_sha, pin_sha=pin,
                      now=now, prev_report=prev)
    _atomic_write(_REPORT, report)
    print(json.dumps({k: report[k] for k in ("ok", "n_fails", "degrade_triggered", "snapshot_age_h")}, indent=2))
    if not report["ok"]:
        _alert(report)
    if report["degrade_triggered"]:
        _apply_degrade()
    elif report["ok"] and snapshot.get("degraded") is True:
        _clear_degrade()   # recovery: all checks pass again -> lift the plaque
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(run())
