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
    # the SNAPSHOT itself is overstated (4.5% > API 3.3%) -> OVERSTATED_METRIC + immediate degrade
    r = mon.evaluate(snapshot=_snap(apy=4.5), home_html=_home(apy="4.5"), track_html=_track(apy="4.5"),
                     api=_api(apy=3.3), sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    codes = {f["code"] for f in r["fails"]}
    assert "OVERSTATED_METRIC" in codes
    assert any(f["severity"] == "CRITICAL" for f in r["fails"])
    assert r["degrade_triggered"] is True and r["degrade_reason"] == "SNAPSHOT_OVERSTATED"
    assert r["snapshot_overstated"] is True


def test_deploy_lag_no_degrade_when_snapshot_correct():
    # live site stale-overstated (4.9%) while the committed snapshot is CORRECT (3.3% == API) -> DEPLOY LAG:
    # must ALERT OVERSTATED but must NOT degrade the good snapshot (degrading it would show a plaque
    # instead of the right number once the deploy catches up).
    r = mon.evaluate(snapshot=_snap(apy=3.3), home_html=_home(apy="4.9"), track_html=_track(apy="4.9"),
                     api=_api(apy=3.3), sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW)
    codes = {f["code"] for f in r["fails"]}
    assert "OVERSTATED_METRIC" in codes
    assert r["site_overstated"] is True and r["snapshot_overstated"] is False
    assert r["degrade_triggered"] is False


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


# ── 2026-09-08 false plaque: the apy legs must be LIKE-FOR-LIKE (owner decision 2026-07-15, вариант «а») ──
# Replay of the real numbers that degraded the public site at 21:38Z: committed snapshot 5.3177 % (track-to-date),
# facts.apy_today_pct 5.0586 % (one day), evidenced chain anchor 2026-06-22 → 2026-09-08 over 77 real days.
_CHAIN_2026_09_08 = [
    {"seq": 0, "date": "2026-06-22", "close_equity": 100150.66, "equity": 100150.66, "evidenced": True, "source": "cycle"},
    {"seq": 40, "date": "2026-08-01", "close_equity": 100700.00, "equity": 100700.00, "evidenced": True, "source": "cycle"},
    {"seq": 76, "date": "2026-09-08", "close_equity": 101251.32, "equity": 101251.32, "evidenced": True, "source": "cycle"},
]
_GOLIVE_2026_09_08 = {"passed": 29, "total": 29, "real_track_days": 77, "evidenced_anchor": "2026-06-22"}
_FACTS_2026_09_08 = {"apy_today_pct": 5.0586, "current_equity": 101251.32, "real_track_days": 77}
NOW_2026_09_08 = datetime.datetime(2026, 9, 8, 21, 38, tzinfo=datetime.timezone.utc)


def test_api_headline_apy_is_the_track_apy_from_the_chain_not_apy_today():
    h = mon.api_headline(_GOLIVE_2026_09_08, _FACTS_2026_09_08, _CHAIN_2026_09_08)
    assert h["paper_apy_pct"] == 5.3177, h            # same formula as generate_track_snapshot.py
    assert h["apy_today_pct"] == 5.0586               # the volatile number is kept, but NOT under paper_apy_pct
    assert h["apy_source"] == "evidenced_chain"
    assert h["last_bar"] == "2026-09-08" and h["evidenced_days"] == 77 and h["gates_passed"] == 29


def test_snapshot_equal_to_the_chain_apy_is_not_overstated_and_not_degraded():
    """Positive control of the 2026-09-08 false plaque: with like-for-like numbers the custodian is quiet."""
    api = mon.api_headline(_GOLIVE_2026_09_08, _FACTS_2026_09_08, _CHAIN_2026_09_08)
    r = mon.evaluate(snapshot=_snap(days=77, apy=5.3177, gates=29, asof="2026-09-08", equity=101251.32),
                     home_html=_home(days=77, apy="5.3", gates="29", asof="2026-09-08"),
                     track_html=_track(equity="101,251", apy="5.3", asof="2026-09-08"),
                     api=api, sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW_2026_09_08)
    codes = {f["code"] for f in r["fails"]}
    assert "OVERSTATED_METRIC" not in codes, r["fails"]
    assert r["snapshot_overstated"] is False and r["degrade_triggered"] is False
    assert r["apy_leg"] == "measured" and r["api_apy_source"] == "evidenced_chain"


def test_snapshot_above_the_chain_apy_still_degrades():
    """The guard is not weakened: a snapshot that overstates the LIKE-FOR-LIKE track apy still kills."""
    api = mon.api_headline(_GOLIVE_2026_09_08, _FACTS_2026_09_08, _CHAIN_2026_09_08)
    r = mon.evaluate(snapshot=_snap(days=77, apy=6.1, gates=29, asof="2026-09-08", equity=101251.32),
                     home_html=_home(days=77, apy="6.1", gates="29", asof="2026-09-08"),
                     track_html=_track(equity="101,251", apy="6.1", asof="2026-09-08"),
                     api=api, sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW_2026_09_08)
    assert r["snapshot_overstated"] is True and r["degrade_triggered"] is True
    assert r["degrade_reason"] == "SNAPSHOT_OVERSTATED"


def test_missing_chain_makes_the_apy_legs_unmeasured_not_green():
    """Third outcome: no chain ⇒ no like-for-like apy ⇒ the legs are NAMED unmeasured; nothing degrades on apy,
    and the report does not pretend the comparison passed."""
    api = mon.api_headline(_GOLIVE_2026_09_08, _FACTS_2026_09_08, None)
    assert api["paper_apy_pct"] is None and api["apy_source"].startswith("unmeasured:")
    r = mon.evaluate(snapshot=_snap(days=77, apy=9.9, gates=29, asof="2026-09-08", equity=101251.32),
                     home_html=_home(days=77, apy="9.9", gates="29", asof="2026-09-08"),
                     track_html=_track(equity="101,251", apy="9.9", asof="2026-09-08"),
                     api=api, sitemap_statuses=_urls(), verifier_sha=PIN, pin_sha=PIN, now=NOW_2026_09_08)
    assert r["apy_leg"] == "unmeasured" and r["degrade_triggered"] is False
    assert not any(f["code"] == "OVERSTATED_METRIC" for f in r["fails"])


def test_jsonl_chain_is_parsed_and_bad_lines_are_skipped():
    body = "\n".join(['{"seq": 0, "date": "2026-06-22", "close_equity": 100150.66, "evidenced": true}',
                      "not json", "",
                      '{"seq": 1, "date": "2026-06-23", "close_equity": 100165.61, "evidenced": true}'])
    rows = mon._parse_jsonl(body)
    assert [r["seq"] for r in rows] == [0, 1]
    apy, src = mon.track_apy_from_chain(rows, "2026-06-22", 1)
    assert src == "evidenced_chain" and apy > 0


def test_pre_anchor_bars_are_excluded_from_the_track_apy():
    rows = [{"date": "2026-05-21", "close_equity": 100000.0, "evidenced": False}] + _CHAIN_2026_09_08
    apy, src = mon.track_apy_from_chain(rows, "2026-06-22", 77)
    assert (apy, src) == (5.3177, "evidenced_chain")
