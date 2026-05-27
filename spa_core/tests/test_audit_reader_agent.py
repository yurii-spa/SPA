"""
Tests for spa_core/agents/audit_reader_agent.py (FEAT-INT-001).

Deterministic, fully offline test suite. Every network call is patched —
no real HTTP traffic ever leaves the test process. No mutation of the
production ``data/audit_findings.json`` file.

Coverage:
  1. _normalize_protocol_name — alias map + version coercion
  2. _classify_status — keyword-based mapping for Code4rena / Sherlock
  3. _coerce_severity — short-form and free-form severity strings
  4. BOOTSTRAP_AUDITS covers every SPA whitelist protocol (>=2 audits each)
  5. aggregate_by_protocol — returns 1 ProtocolAuditSummary per slug
  6. fixed/open critical/high invariants (sums never exceed totals)
  7. Offline mode does not call urllib.request.urlopen
  8. Network failure path falls back to bootstrap (fallback_used=True)
  9. Determinism — two consecutive aggregate runs are byte-equal
 10. export() round-trip via tmp_path
 11. export(dry_run=True) writes no file
 12. Curve Finance has an OPEN critical (Vyper 2023)
 13. Euler V2 has an ACKNOWLEDGED critical (Euler V1 hack 2023)
 14. Compound V3 contains a FIXED critical (Proposal 062, 2021)
 15. Every protocol has total_audits >= 2
 16. Snapshot schema sanity (top-level keys, summary block)
 17. AuditFinding dataclass is frozen (hashable)

These tests are designed to run with:

    pytest -q spa_core/tests/test_audit_reader_agent.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure spa_core is importable when pytest is run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.agents import audit_reader_agent as ara
from spa_core.agents.audit_reader_agent import (
    AGENT_VERSION,
    SPA_WHITELIST,
    SEVERITIES,
    STATUSES,
    AuditFinding,
    AuditReaderAgent,
    ProtocolAuditSummary,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def agent(tmp_path):
    """A fresh AuditReaderAgent writing into tmp_path (no prod data writes)."""
    out = tmp_path / "audit_findings.json"
    return AuditReaderAgent(output_file=out)


# ─── 1. _normalize_protocol_name ──────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("Aave Protocol V3", "aave-v3"),
    ("Aave V3",          "aave-v3"),
    ("aave",             "aave-v3"),
    ("Compound III",     "compound-v3"),
    ("Compound v3",      "compound-v3"),
    ("Curve Finance",    "curve-finance"),
    ("Curve",            "curve-finance"),
    ("Uniswap",          "uniswap-v3"),
    ("Uniswap V3",       "uniswap-v3"),
    ("Sky / sUSDS",      "sky"),
    ("MakerDAO",         "maker"),
    ("Morpho Blue",      "morpho"),
    ("Morpho Vaults",    "morpho"),
    ("Yearn V3",         "yearn-v3"),
    ("Pendle",           "pendle"),
    ("Pendle Finance",   "pendle"),
    ("Euler",            "euler-v2"),
    ("Euler V2",         "euler-v2"),
    ("",                 ""),
    (None,               ""),
])
def test_normalize_protocol_name(agent, inp, expected):
    assert agent._normalize_protocol_name(inp) == expected


# ─── 2. _classify_status ──────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("fixed",            "fixed"),
    ("Fixed",            "fixed"),
    ("FIXED",            "fixed"),
    ("Resolved",         "fixed"),
    ("patched in v2.1",  "fixed"),
    ("Acknowledged",     "acknowledged"),
    ("won't fix",        "acknowledged"),
    ("Wontfix",          "acknowledged"),
    ("Disputed",         "disputed"),
    ("invalid",          "disputed"),
    ("false positive",   "disputed"),
    ("OPEN",             "open"),
    ("pending review",   "open"),
    ("todo",             "open"),
    ("unresolved",       "open"),
    ("",                 "open"),   # conservative default
    (None,               "open"),
    ("something random", "open"),
])
def test_classify_status(agent, inp, expected):
    assert agent._classify_status(inp) == expected


# ─── 3. _coerce_severity ──────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("critical",      "critical"),
    ("Critical",      "critical"),
    ("C",             "critical"),
    ("high",          "high"),
    ("H",             "high"),
    ("HIGH severity", "high"),
    ("medium",        "medium"),
    ("M",             "medium"),
    ("low",           "low"),
    ("L",             "low"),
    ("info",          "info"),
    ("",              "info"),
    (None,            "info"),
    ("???",           "info"),
])
def test_coerce_severity(inp, expected):
    assert ara._coerce_severity(inp) == expected


# ─── 4. BOOTSTRAP covers whitelist ────────────────────────────────────────────

def test_bootstrap_covers_full_whitelist():
    """Every SPA whitelist slug must have at least one bootstrap audit."""
    slugs_in_bootstrap = {rec["protocol_slug"] for rec in ara.BOOTSTRAP_AUDITS}
    missing = set(SPA_WHITELIST) - slugs_in_bootstrap
    assert not missing, f"missing whitelist slugs in bootstrap: {missing}"


def test_bootstrap_has_minimum_two_audits_per_protocol():
    """Each protocol in the whitelist needs >= 2 distinct (auditor, contest)."""
    counts: dict[str, set] = {slug: set() for slug in SPA_WHITELIST}
    for rec in ara.BOOTSTRAP_AUDITS:
        slug = rec["protocol_slug"]
        if slug in counts:
            counts[slug].add((rec["auditor"], rec["contest_id"]))
    for slug, audits in counts.items():
        assert len(audits) >= 2, f"{slug} has only {len(audits)} bootstrap audits"


def test_bootstrap_severities_and_statuses_are_valid():
    """All bootstrap findings use canonical severity/status enums."""
    for rec in ara.BOOTSTRAP_AUDITS:
        for f in rec["findings"]:
            assert f["severity"] in SEVERITIES, f"{rec['contest_id']}: bad severity {f['severity']}"
            assert f["status"] in STATUSES, f"{rec['contest_id']}: bad status {f['status']}"


# ─── 5. aggregate_by_protocol returns one entry per slug ──────────────────────

def test_aggregate_returns_one_per_whitelist_slug(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    assert set(summaries.keys()) == set(SPA_WHITELIST)
    for slug, summary in summaries.items():
        assert isinstance(summary, ProtocolAuditSummary)
        assert summary.protocol_slug == slug


def test_aggregate_offline_does_not_call_urlopen(agent):
    with patch("urllib.request.urlopen") as mock_urlopen:
        agent.aggregate_by_protocol(offline=True)
    mock_urlopen.assert_not_called()


def test_export_offline_does_not_call_urlopen(agent):
    with patch("urllib.request.urlopen") as mock_urlopen:
        agent.export(offline=True, dry_run=True)
    mock_urlopen.assert_not_called()


# ─── 6. Invariants ────────────────────────────────────────────────────────────

def test_fixed_plus_open_le_total_critical(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    for slug, s in summaries.items():
        assert s.fixed_critical + s.open_critical <= s.total_critical, (
            f"{slug}: fixed_critical({s.fixed_critical}) + "
            f"open_critical({s.open_critical}) > total_critical({s.total_critical})"
        )


def test_fixed_plus_open_le_total_high(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    for slug, s in summaries.items():
        assert s.fixed_high + s.open_high <= s.total_high, (
            f"{slug}: fixed_high + open_high > total_high"
        )


def test_every_protocol_has_min_two_audits(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    for slug, s in summaries.items():
        assert s.total_audits >= 2, f"{slug}: only {s.total_audits} audits"


def test_every_protocol_has_findings(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    for slug, s in summaries.items():
        assert len(s.findings) >= 1, f"{slug}: no findings"


def test_every_protocol_has_at_least_one_auditor(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    for slug, s in summaries.items():
        assert len(s.auditors) >= 1, f"{slug}: no auditors"


# ─── 7. Known historical events ───────────────────────────────────────────────

def test_curve_has_open_critical_vyper_2023(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    curve = summaries["curve-finance"]
    assert curve.open_critical >= 1
    # The bootstrap entry's title must mention Vyper
    titles = " ".join(f.title for f in curve.findings if f.severity == "critical")
    assert "Vyper" in titles or "vyper" in titles


def test_euler_has_acknowledged_critical_v1_hack(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    euler = summaries["euler-v2"]
    # We expect at least one acknowledged critical (V1 hack)
    ack_crits = [f for f in euler.findings
                 if f.severity == "critical" and f.status == "acknowledged"]
    assert len(ack_crits) >= 1
    # And the title should reference Euler V1 / donation attack
    text = " ".join(f.title for f in ack_crits)
    assert "V1" in text or "donation" in text.lower()


def test_compound_has_fixed_critical_proposal_062(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    comp = summaries["compound-v3"]
    fixed_crits = [f for f in comp.findings
                   if f.severity == "critical" and f.status == "fixed"]
    assert len(fixed_crits) >= 1


# ─── 8. Determinism ───────────────────────────────────────────────────────────

def test_aggregate_is_deterministic(agent):
    a = agent.aggregate_by_protocol(offline=True)
    b = agent.aggregate_by_protocol(offline=True)

    # Convert to dicts (AuditFinding is frozen and hashable, but dicts give
    # readable diffs if they don't match)
    def normalise(summaries):
        return {
            slug: {
                "total_audits":    s.total_audits,
                "auditors":        s.auditors,
                "total_critical":  s.total_critical,
                "total_high":      s.total_high,
                "fixed_critical":  s.fixed_critical,
                "open_critical":   s.open_critical,
                "fixed_high":      s.fixed_high,
                "open_high":       s.open_high,
                "last_audit_date": s.last_audit_date,
                "findings": [
                    (f.severity, f.title, f.status, f.source, f.contest_id, f.url)
                    for f in s.findings
                ],
            }
            for slug, s in summaries.items()
        }

    assert normalise(a) == normalise(b)


def test_snapshot_protocols_keys_are_sorted(agent):
    snap = agent.export(offline=True, dry_run=True)
    keys = list(snap["protocols"].keys())
    assert keys == sorted(keys)


# ─── 9. Export round-trip ─────────────────────────────────────────────────────

def test_export_writes_file_and_round_trips(agent, tmp_path):
    out_path = agent.output_file
    assert not out_path.exists()
    snap = agent.export(offline=True, dry_run=False)
    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    # Ignore generated_at (timestamp drifts) — compare structural keys.
    assert on_disk["agent_version"] == AGENT_VERSION
    assert on_disk["summary"]["total_protocols"] == len(SPA_WHITELIST)
    assert set(on_disk["protocols"].keys()) == set(SPA_WHITELIST)
    assert on_disk["protocols"] == snap["protocols"]


def test_export_dry_run_does_not_write_file(agent):
    assert not agent.output_file.exists()
    snap = agent.export(offline=True, dry_run=True)
    assert not agent.output_file.exists()
    # But the snapshot is still returned in full.
    assert snap["summary"]["total_protocols"] == len(SPA_WHITELIST)


# ─── 10. Network failure fallback ─────────────────────────────────────────────

def test_aggregate_falls_back_when_network_fails(agent):
    """When both fetchers fail, aggregate must use bootstrap + fallback_used=True."""
    def boom(*a, **kw):
        raise urllib.error.URLError("simulated network down")

    with patch("urllib.request.urlopen", side_effect=boom):
        summaries = agent.aggregate_by_protocol(offline=False)

    assert agent._fallback_used is True
    # Still produced data for every whitelist slug.
    assert set(summaries.keys()) == set(SPA_WHITELIST)
    for s in summaries.values():
        assert s.total_audits >= 2


def test_aggregate_does_not_raise_on_garbage_payload(agent):
    """If Code4rena returns non-JSON, aggregate still succeeds."""
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    mock_resp.read.return_value = b"<html>not json</html>"
    with patch("urllib.request.urlopen", return_value=mock_resp):
        # Should not raise
        summaries = agent.aggregate_by_protocol(offline=False)
    assert len(summaries) == len(SPA_WHITELIST)


# ─── 11. Snapshot schema sanity ───────────────────────────────────────────────

def test_snapshot_top_level_keys(agent):
    snap = agent.export(offline=True, dry_run=True)
    for k in ("generated_at", "agent_version", "sources", "fallback_used",
              "protocols", "summary"):
        assert k in snap, f"missing key {k}"


def test_snapshot_summary_contents(agent):
    snap = agent.export(offline=True, dry_run=True)
    s = snap["summary"]
    assert s["total_protocols"] == len(SPA_WHITELIST)
    # Sum of per-protocol findings should equal summary.total_findings
    findings_count = sum(len(p["findings"]) for p in snap["protocols"].values())
    assert s["total_findings"] == findings_count
    # open_critical_count should match per-protocol roll-up
    open_crits = sum(p["open_critical"] for p in snap["protocols"].values())
    assert s["open_critical_count"] == open_crits


def test_snapshot_sources_list_includes_bootstrap(agent):
    snap = agent.export(offline=True, dry_run=True)
    assert "bootstrap" in snap["sources"]


def test_snapshot_fallback_used_true_when_offline(agent):
    snap = agent.export(offline=True, dry_run=True)
    assert snap["fallback_used"] is True


# ─── 12. AuditFinding dataclass ───────────────────────────────────────────────

def test_audit_finding_is_frozen_and_hashable():
    f = AuditFinding(
        severity="high", title="t", status="fixed",
        source="bootstrap", contest_id="c-1", url="https://x",
    )
    # Frozen — can be set-keyed
    s = {f}
    assert f in s
    # And read-only
    with pytest.raises(Exception):
        f.title = "mutated"  # type: ignore[misc]


# ─── 13. Severity ordering inside findings ────────────────────────────────────

def test_findings_sorted_by_severity_then_contest(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    for slug, s in summaries.items():
        order = [SEVERITIES.index(f.severity) if f.severity in SEVERITIES
                 else len(SEVERITIES) for f in s.findings]
        assert order == sorted(order), f"{slug} findings not sorted by severity"


# ─── 14. Whitelist filtering ──────────────────────────────────────────────────

def test_unknown_protocol_records_are_ignored(agent):
    """A record with an unrecognised slug must not pollute the summary set."""
    # Patch _bootstrap_records to inject a junk entry.
    real = agent._bootstrap_records()
    real.append({
        "protocol":      "Some Random Thing",
        "protocol_slug": "some-random-thing",
        "contest_id":    "junk-1",
        "auditor":       "Nobody",
        "date":          "",
        "url":           "",
        "findings":      [{"severity": "critical", "title": "x", "status": "open"}],
        "_bootstrap":    True,
    })
    with patch.object(agent, "_bootstrap_records", return_value=real):
        summaries = agent.aggregate_by_protocol(offline=True)
    # The injected slug must not appear.
    assert "some-random-thing" not in summaries
    assert set(summaries.keys()) == set(SPA_WHITELIST)


# ─── 15. last_audit_date is the maximum across audits ─────────────────────────

def test_last_audit_date_is_max(agent):
    summaries = agent.aggregate_by_protocol(offline=True)
    # Build per-slug expected max from bootstrap dates.
    expected: dict[str, str] = {}
    for rec in ara.BOOTSTRAP_AUDITS:
        slug = rec["protocol_slug"]
        date = rec.get("date") or ""
        if not date:
            continue
        if slug not in expected or date > expected[slug]:
            expected[slug] = date
    for slug, exp in expected.items():
        if slug in summaries:
            assert summaries[slug].last_audit_date == exp, (
                f"{slug}: last_audit_date {summaries[slug].last_audit_date} "
                f"!= expected {exp}"
            )


# ─── 16. AuditReaderAgent constructor defaults ────────────────────────────────

def test_default_output_path_is_data_audit_findings_json():
    a = AuditReaderAgent()
    assert a.output_file.name == "audit_findings.json"
    assert a.output_file.parent.name == "data"
