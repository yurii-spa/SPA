"""test_site_content_audit.py — Site Custodian block 4 (ADR-YL-011). No network: reads fixture pages."""
import datetime
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("site_content_audit", _ROOT / "scripts" / "site_content_audit.py")
aud = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(aud)

NOW = datetime.date(2026, 7, 3)


def _mk(tmp, name, body):
    p = tmp / f"{name}.astro"; p.write_text(body); return p


def test_stale_hardcoded_date(tmp_path):
    _mk(tmp_path, "a", "anchored 2026-04-01 (old) and 2026-07-01 (fresh)")
    stale = aud.find_stale_dates(tmp_path, NOW, max_age=60)
    dates = {s["date"] for s in stale}
    assert "2026-04-01" in dates and "2026-07-01" not in dates  # 93d old vs 2d


def test_metric_divergence_only_hardcoded(tmp_path):
    _mk(tmp_path, "index", "10 evidenced days shown")
    _mk(tmp_path, "track-record", "12 evidenced days shown")
    div = aud.check_metric_divergence(tmp_path)
    assert any(d["metric"] == "days" for d in div)  # 10 vs 12 hardcoded -> divergence


def test_metric_expressions_not_counted(tmp_path):
    # {snapDays} expressions must NOT be treated as hardcoded (no false divergence)
    _mk(tmp_path, "index", "{snapDays} evidenced days")
    _mk(tmp_path, "track-record", "{realDays} evidenced days")
    assert aud.check_metric_divergence(tmp_path) == []


def test_broken_link_and_anchor(tmp_path):
    _mk(tmp_path, "index", '<a href="/nonexistent-page">x</a> <a href="#missing">y</a>')
    broken = aud.check_internal_links(tmp_path)
    hrefs = {b["href"] for b in broken}
    assert "/nonexistent-page" in hrefs and "#missing" in hrefs


def test_valid_link_and_anchor_pass(tmp_path):
    _mk(tmp_path, "index", '<a href="/track-record">x</a> <a href="#sec">y</a><div id="sec"></div>')
    _mk(tmp_path, "track-record", "page")
    broken = aud.check_internal_links(tmp_path)
    assert broken == []


def test_sitemap_mismatch(tmp_path):
    _mk(tmp_path, "index", "x"); _mk(tmp_path, "orphan", "y")
    sm = tmp_path / "sitemap.xml"
    sm.write_text('<urlset><url><loc>https://earn-defi.com/</loc></url></urlset>')
    res = aud.check_sitemap_vs_pages(sm, tmp_path)
    assert "orphan" in res["missing_from_sitemap"]


def test_audit_clean_fixture(tmp_path):
    _mk(tmp_path, "index", "welcome {snapDays}")
    sm = tmp_path / "sitemap.xml"
    sm.write_text('<urlset><url><loc>https://earn-defi.com/</loc></url></urlset>')
    r = aud.audit(pages_dir=tmp_path, sitemap_path=sm, now=NOW)
    assert r["ok"] is True and r["n_fails"] == 0
