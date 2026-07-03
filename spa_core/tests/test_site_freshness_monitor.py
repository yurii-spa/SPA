"""test_site_freshness_monitor.py — Site Custodian block 2/3 (ADR-YL-011). No network: evaluate() is pure."""
import datetime
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("site_freshness_monitor", _ROOT / "scripts" / "site_freshness_monitor.py")
mon = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(mon)

NOW = datetime.datetime(2026, 7, 3, 12, 0, tzinfo=datetime.timezone.utc)


def _home(days=12, apy="3.3", gates="27", asof="2026-07-03"):
    return (f'<span class="num" id="sl-day">{days}</span>'
            f'<span class="num" id="sl-apy">~{apy}%</span>'
            f'<span class="num" id="sl-gates">{gates}/29</span>'
            f'<span id="sl-asof">as of {asof}</span>')


def _track(equity="100,265", apy="3.3", asof="2026-07-03"):
    return (f'<p id="tr-equity">${equity}</p><p id="tr-apy">~{apy}%</p>'
            f'<p id="tr-asof">static snapshot as of {asof}</p>')


def _snap(days=12, apy=3.3, gates=27, asof="2026-07-03", equity=100265.0):
    return {"as_of": asof, "real_track_days": days, "paper_apy_pct": apy, "gates_passed": gates, "end_equity": equity}


def _api(days=12, apy=3.3, equity=100265.0, last="2026-07-03"):
    return {"evidenced_days": days, "paper_apy_pct": apy, "gates_passed": 27, "end_equity": equity, "last_bar": last}


def _urls(ok=True):
    return {"https://earn-defi.com/": 200 if ok else 404, "https://earn-defi.com/verify/": 200}

PIN = "a" * 64


def test_all_green():
    r = mon.evaluate(snapshot=_snap(), home_html=_home(), track_html=_track(), api=_api(),
                     sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    assert r["ok"] is True and r["n_fails"] == 0 and r["degrade_triggered"] is False


def test_overstated_metric_is_critical_and_degrades():
    # site shows 4.5% while API says 3.3% -> OVERSTATED_METRIC + immediate degrade
    r = mon.evaluate(snapshot=_snap(apy=4.5), home_html=_home(apy="4.5"), track_html=_track(apy="4.5"),
                     api=_api(apy=3.3), sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    codes = {f["code"] for f in r["fails"]}
    assert "OVERSTATED_METRIC" in codes
    assert any(f["severity"] == "CRITICAL" for f in r["fails"])
    assert r["degrade_triggered"] is True and r["degrade_reason"] == "OVERSTATED_METRIC"


def test_stale_snapshot():
    r = mon.evaluate(snapshot=_snap(asof="2026-06-25"), home_html=_home(asof="2026-06-25"),
                     track_html=_track(asof="2026-06-25"), api=_api(last="2026-06-25"),
                     sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    codes = {f["code"] for f in r["fails"]}
    assert "STALE_SNAPSHOT" in codes and "STALE_API" in codes and r["ok"] is False


def test_site_behind_snapshot():
    # site still shows 10 days / old as-of while snapshot is 12 / new -> deploy lag
    r = mon.evaluate(snapshot=_snap(days=12, asof="2026-07-03"),
                     home_html=_home(days=10, asof="2026-07-01"), track_html=_track(asof="2026-07-01"),
                     api=_api(days=12), sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    assert any(f["code"] == "SITE_BEHIND_SNAPSHOT" for f in r["fails"])


def test_snapshot_behind_api():
    r = mon.evaluate(snapshot=_snap(days=11, apy=3.6), home_html=_home(days=11, apy="3.6"),
                     track_html=_track(apy="3.6"), api=_api(days=12, apy=3.3),
                     sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    assert any(f["code"] == "SNAPSHOT_BEHIND_API" for f in r["fails"])


def test_kill_rule_two_consecutive_stale_runs():
    stale = _snap(asof="2026-06-25")  # 8 days old > 48h
    prev = {"stale_48h": True}
    r = mon.evaluate(snapshot=stale, home_html=_home(asof="2026-06-25"), track_html=_track(asof="2026-06-25"),
                     api=_api(last="2026-06-25"), sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN,
                     now=NOW, prev_report=prev)
    assert r["stale_48h"] is True and r["degrade_triggered"] is True and r["degrade_reason"] == "STALE_48H_TWO_RUNS"
    # single stale run (no prev) does NOT degrade
    r1 = mon.evaluate(snapshot=stale, home_html=_home(asof="2026-06-25"), track_html=_track(asof="2026-06-25"),
                      api=_api(last="2026-06-25"), sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN,
                      now=NOW, prev_report=None)
    assert r1["degrade_triggered"] is False


def test_unavailable_and_pin_mismatch():
    r = mon.evaluate(snapshot=_snap(), home_html=_home(), track_html=_track(), api=_api(),
                     sitemap_statuses=_urls(ok=False), verifier_sha="b" * 64, pin_sha=PIN, now=NOW)
    codes = {f["code"] for f in r["fails"]}
    assert "UNAVAILABLE" in codes and "VERIFIER_PIN_MISMATCH" in codes


def test_308_redirect_is_allowed():
    r = mon.evaluate(snapshot=_snap(), home_html=_home(), track_html=_track(), api=_api(),
                     sitemap_statuses={"https://earn-defi.com/status": 308}, verifier_sha=PIN, pin_sha=PIN, now=NOW)
    assert not any(f["code"] == "UNAVAILABLE" for f in r["fails"])


def test_parse_site_numbers():
    p = mon.parse_site_numbers(_home(days=12, apy="3.3", gates="27", asof="2026-07-03"))
    assert p["evidenced_days"] == 12 and p["paper_apy_pct"] == 3.3 and p["gates_passed"] == 27
    assert p["as_of"] == "2026-07-03"
