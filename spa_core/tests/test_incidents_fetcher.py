"""
Tests for spa_core/data_pipeline/incidents_fetcher.py (FEAT-RISK-002).

These tests are deterministic and fully offline: every network call is
patched. The test set covers:

1. ``normalise_protocol_name`` — slug generation edge cases.
2. ``classify_type`` — DefiLlama enum mapping.
3. ``_safe_amount`` / ``_safe_date`` — numeric & date normalisation.
4. ``_match_spa_protocol`` — substring matching against SPA whitelist.
5. ``normalise_incident`` — full record normalisation.
6. ``_dedupe_and_sort`` — de-duplication semantics.
7. ``build_summary`` — per-protocol roll-up.
8. ``fetch_defillama_hacks`` — happy path and error tolerance.
9. ``build_incidents_snapshot`` — offline mode (bootstrap only) + full mode.
10. ``write_snapshot`` / ``load_snapshot`` — round-trip on disk.

No data/ directory mutation occurs — all writes are to ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from data_pipeline import incidents_fetcher as inc


# ─── 1. normalise_protocol_name ───────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("Aave V3", "aave-v3"),
    ("Compound v3", "compound-v3"),
    ("Curve Finance", "curve-finance"),
    ("  Euler  ", "euler"),
    ("Yearn  V3 / vaults", "yearn-v3-vaults"),
    ("Sky_sUSDS", "sky-susds"),
    ("", ""),
    (None, ""),
])
def test_normalise_protocol_name(inp, expected):
    assert inc.normalise_protocol_name(inp) == expected


# ─── 2. classify_type ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("rugpull",                 "rugpull"),
    ("Exit scam",               "rugpull"),
    ("depeg",                   "depeg"),
    ("Stablecoin Depeg",        "depeg"),
    ("smart contract exploit",  "exploit"),
    ("logic bug",               "exploit"),
    ("hack",                    "hack"),
    ("Phishing",                "hack"),
    ("private key compromise",  "hack"),
    ("",                        "unknown"),
    (None,                      "unknown"),
    ("something weird",         "exploit"),    # default heuristic
])
def test_classify_type(inp, expected):
    assert inc.classify_type(inp) == expected


# ─── 3. _safe_amount / _safe_date ─────────────────────────────────────────────

class TestSafeAmount:
    def test_none_returns_zero(self):
        assert inc._safe_amount(None) == 0.0

    def test_invalid_string_returns_zero(self):
        assert inc._safe_amount("not a number") == 0.0

    def test_plain_usd_value(self):
        # Already in USD (millions threshold exceeded) — returned as-is
        assert inc._safe_amount(73_500_000) == 73_500_000.0

    def test_millions_units_converted(self):
        # DefiLlama serves "amount" in millions in some endpoints — converted
        assert inc._safe_amount(73.5) == 73_500_000.0

    def test_zero_passes_through(self):
        # 0 means "amount not disclosed" — must NOT be inflated by ×1e6
        assert inc._safe_amount(0) == 0.0
        assert inc._safe_amount("0") == 0.0


class TestSafeDate:
    def test_iso_string(self):
        assert inc._safe_date("2023-07-30") == "2023-07-30"

    def test_iso_with_time(self):
        assert inc._safe_date("2023-07-30T12:00:00Z") == "2023-07-30"

    def test_unix_seconds(self):
        # 2023-07-30 in seconds
        assert inc._safe_date(1690675200) == "2023-07-30"

    def test_unix_ms(self):
        # Same date in ms
        assert inc._safe_date(1690675200_000) == "2023-07-30"

    def test_dd_mm_yyyy(self):
        assert inc._safe_date("30/07/2023") == "2023-07-30"

    def test_invalid_returns_empty(self):
        assert inc._safe_date("not-a-date") == ""
        assert inc._safe_date("") == ""
        assert inc._safe_date(None) == ""


# ─── 4. _match_spa_protocol ───────────────────────────────────────────────────

class TestMatchSpaProtocol:
    def test_aave_v3_matches_aave_family(self):
        out = inc._match_spa_protocol("Aave V3")
        assert "aave" in out
        assert "aave-v3" in out

    def test_compound_matches(self):
        assert "compound" in inc._match_spa_protocol("Compound")

    def test_unrelated_protocol_no_match(self):
        # Wormhole was never on SPA whitelist
        assert inc._match_spa_protocol("Wormhole Bridge") == []

    def test_partial_substring_curve(self):
        out = inc._match_spa_protocol("Curve Finance")
        assert "curve" in out

    def test_empty_returns_empty(self):
        assert inc._match_spa_protocol("") == []
        assert inc._match_spa_protocol(None) == []


# ─── 5. normalise_incident ────────────────────────────────────────────────────

class TestNormaliseIncident:
    def test_defillama_shape(self):
        raw = {
            "id":              1234,
            "name":            "Curve Finance",
            "date":            "2023-07-30",
            "amount":          73.5,          # millions
            "classification":  "Smart contract exploit",
            "chain":           "Ethereum",
            "technique":       "Reentrancy",
            "source":          "https://example.com",
        }
        norm = inc.normalise_incident(raw)
        assert norm["id"] == "1234"
        assert norm["protocol"] == "Curve Finance"
        assert norm["protocol_slug"] == "curve-finance"
        assert norm["date"] == "2023-07-30"
        assert norm["amount_lost_usd"] == 73_500_000.0
        assert norm["type"] == "exploit"
        assert norm["chain"] == "ethereum"
        assert norm["source_url"] == "https://example.com"
        assert norm["status"] == "unknown"
        assert "curve" in norm["spa_protocols_affected"]

    def test_chain_as_list(self):
        raw = {"name": "Multichain", "chain": ["ethereum", "bsc"]}
        norm = inc.normalise_incident(raw)
        assert norm["chain"] == "ethereum,bsc"

    def test_bootstrap_record_round_trip(self):
        # Every bootstrap record must normalise cleanly
        for raw in inc.BOOTSTRAP_INCIDENTS:
            norm = inc.normalise_incident(raw, source="bootstrap")
            assert norm["protocol"]
            assert norm["protocol_slug"]
            assert norm["date"] != ""
            assert norm["amount_lost_usd"] >= 0
            assert norm["type"] in {"hack", "exploit", "rugpull", "depeg", "unknown"}

    def test_missing_fields_default_safely(self):
        # An almost-empty dict must not raise
        norm = inc.normalise_incident({})
        assert norm["protocol"] == "unknown"
        assert norm["type"] == "unknown"
        assert norm["chain"] == ""
        assert norm["spa_protocols_affected"] == []


# ─── 6. _dedupe_and_sort ──────────────────────────────────────────────────────

class TestDedupeAndSort:
    def _mk(self, slug="x", date="2024-01-01", amount=1.0, source=""):
        return {
            "id": f"{slug}-{date}",
            "protocol": slug,
            "protocol_slug": slug,
            "date": date,
            "amount_lost_usd": amount,
            "type": "exploit",
            "technique": "tech",
            "chain": "ethereum",
            "source_url": source,
            "status": "unknown",
            "spa_protocols_affected": [],
        }

    def test_duplicate_collapsed(self):
        a = self._mk(amount=10)
        b = self._mk(amount=10)
        out = inc._dedupe_and_sort([a, b])
        assert len(out) == 1

    def test_higher_amount_wins(self):
        a = self._mk(amount=10, source="")
        b = self._mk(amount=20, source="")
        out = inc._dedupe_and_sort([a, b])
        assert len(out) == 1
        assert out[0]["amount_lost_usd"] == 20

    def test_non_empty_source_wins(self):
        a = self._mk(amount=10, source="")
        b = self._mk(amount=10, source="https://example.com")
        out = inc._dedupe_and_sort([a, b])
        assert len(out) == 1
        assert out[0]["source_url"] == "https://example.com"

    def test_sort_by_date_desc(self):
        a = self._mk(slug="aave", date="2023-01-01")
        b = self._mk(slug="curve", date="2024-01-01")
        c = self._mk(slug="euler", date="2025-01-01")
        out = inc._dedupe_and_sort([a, b, c])
        assert [i["date"] for i in out] == ["2025-01-01", "2024-01-01", "2023-01-01"]


# ─── 7. build_summary ─────────────────────────────────────────────────────────

class TestBuildSummary:
    def test_empty_input_initialises_all_slugs(self):
        s = inc.build_summary([])
        for slug in inc.SPA_PROTOCOL_SLUGS:
            assert slug in s
            assert s[slug] == {"incidents": 0, "total_lost_usd": 0.0, "last_incident": None}

    def test_increments_per_protocol(self):
        norm = inc.normalise_incident({
            "name": "Aave V3", "date": "2024-01-01",
            "amount": 5.0, "classification": "exploit",
        })
        s = inc.build_summary([norm])
        # Aave V3 should populate both 'aave' and 'aave-v3'
        assert s["aave"]["incidents"] == 1
        assert s["aave-v3"]["incidents"] == 1
        assert s["aave"]["total_lost_usd"] == 5_000_000.0
        assert s["aave"]["last_incident"] == "2024-01-01"

    def test_latest_date_kept(self):
        a = inc.normalise_incident({"name": "Aave", "date": "2023-01-01", "amount": 1.0})
        b = inc.normalise_incident({"name": "Aave", "date": "2025-01-01", "amount": 2.0})
        s = inc.build_summary([a, b])
        assert s["aave"]["last_incident"] == "2025-01-01"


# ─── 8. fetch_defillama_hacks ─────────────────────────────────────────────────

class TestFetchDefillama:
    def _mock_resp(self, body_dict):
        body = json.dumps(body_dict).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_list_payload_returned_as_is(self):
        resp = self._mock_resp([{"name": "x", "date": "2024-01-01"}])
        with patch("urllib.request.urlopen", return_value=resp):
            out = inc.fetch_defillama_hacks(timeout=1)
        assert out == [{"name": "x", "date": "2024-01-01"}]

    def test_dict_payload_with_hacks_key(self):
        resp = self._mock_resp({"hacks": [{"name": "y"}]})
        with patch("urllib.request.urlopen", return_value=resp):
            out = inc.fetch_defillama_hacks(timeout=1)
        assert out == [{"name": "y"}]

    def test_network_error_returns_empty(self):
        with patch("urllib.request.urlopen", side_effect=OSError("no network")):
            with patch("time.sleep"):  # avoid 6s sleep in tests
                out = inc.fetch_defillama_hacks(timeout=1)
        assert out == []

    def test_invalid_json_returns_empty(self):
        bad = MagicMock()
        bad.read.return_value = b"not-json"
        bad.__enter__ = lambda s: s
        bad.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=bad):
            with patch("time.sleep"):
                out = inc.fetch_defillama_hacks(timeout=1)
        assert out == []


# ─── 9. build_incidents_snapshot ──────────────────────────────────────────────

class TestBuildSnapshot:
    def test_offline_uses_bootstrap_only(self):
        snap = inc.build_incidents_snapshot(offline=True)
        assert snap["fetched_from_api"] is False
        assert snap["total_incidents"] == len(inc.BOOTSTRAP_INCIDENTS)
        assert snap["total_amount_lost_usd"] > 0

    def test_offline_summary_is_complete(self):
        snap = inc.build_incidents_snapshot(offline=True)
        # Every SPA slug must be present
        for slug in inc.SPA_PROTOCOL_SLUGS:
            assert slug in snap["by_protocol_summary"]

    def test_online_merges_api_with_bootstrap(self):
        api_payload = [
            {
                "id": "999", "name": "Test Protocol",
                "date": "2026-01-01", "amount": 10.0,
                "classification": "exploit", "chain": "ethereum",
                "source": "https://t.example",
            },
        ]
        resp = MagicMock()
        resp.read.return_value = json.dumps(api_payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            snap = inc.build_incidents_snapshot(offline=False, timeout=1)
        assert snap["fetched_from_api"] is True
        # Should include both API and bootstrap entries
        assert snap["total_incidents"] >= len(inc.BOOTSTRAP_INCIDENTS) + 1

    def test_snapshot_shape_is_stable(self):
        snap = inc.build_incidents_snapshot(offline=True)
        required = {
            "updated_at", "source", "fetched_from_api",
            "total_incidents", "total_amount_lost_usd",
            "incidents", "by_protocol_summary",
        }
        assert set(snap.keys()) == required


# ─── 10. write_snapshot / load_snapshot ───────────────────────────────────────

class TestWriteLoadRoundTrip:
    def test_round_trip(self, tmp_path: Path):
        snap = inc.build_incidents_snapshot(offline=True)
        out = tmp_path / "incidents.json"
        written = inc.write_snapshot(snap, output_path=out)
        assert written == out
        assert out.exists()

        loaded = inc.load_snapshot(path=out)
        assert loaded is not None
        assert loaded["total_incidents"] == snap["total_incidents"]
        assert loaded["fetched_from_api"] is False

    def test_load_nonexistent_returns_none(self, tmp_path: Path):
        out = tmp_path / "missing.json"
        assert inc.load_snapshot(path=out) is None

    def test_load_invalid_json_returns_none(self, tmp_path: Path):
        out = tmp_path / "bad.json"
        out.write_text("not json")
        assert inc.load_snapshot(path=out) is None
