"""Tests for the FUNDABILITY one-pager generator.

Contract verified:
- runs deterministically (same sources -> same bytes);
- every section is present;
- numbers are SOURCED from the data files (mock the data -> the output reflects
  the mocks, not hardcoded constants);
- a missing source -> "data unavailable" / "unavailable", never fabricated;
- the forward track is honestly labeled "N/30 accruing".
"""

import importlib.util
import json
import os

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
    "generate_fundability_onepager.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("fundability_gen", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load_module()


# --------------------------------------------------------------------------- #
# Fixtures — a fully populated fake repo and an empty one.
# --------------------------------------------------------------------------- #

def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


@pytest.fixture
def full_repo(tmp_path):
    """A repo with every data source populated with distinctive sentinel numbers."""
    root = tmp_path
    d = root / "data"
    rd = d / "rates_desk"

    _write(str(d / "golive_status.json"), {
        "passed": 17, "total": 23, "real_track_days": 9,
        "evidenced_anchor": "2026-01-01", "target_date": "2026-12-31",
    })
    _write(str(rd / "rates_desk_promotion.json"), {
        "rwa_floor_pct": 3.4,
        "sleeves": [
            {"shape": "fixed_carry", "stage": "PAPER_CANDIDATE",
             "net_apy_pct": 7.7777, "beats_floor": True, "max_drawdown_pct": 0.0,
             "refusals_count": 1234, "kills": 5},
            {"shape": "basis_hedge", "stage": "BLOCKED-NO-HEDGE",
             "net_apy_pct": 3.4, "beats_floor": False, "max_drawdown_pct": 0.0,
             "refusals_count": 0, "kills": 0},
        ],
    })
    _write_jsonl(str(rd / "decision_log.jsonl"), [
        {"kind": "REFUSAL", "reason": "tail_veto", "underlying": "ezeth"},
        {"kind": "REFUSAL", "reason": "tail_veto", "underlying": "rseth"},
        {"kind": "REFUSAL", "reason": "size_floor", "underlying": "susde"},
        {"kind": "ENTRY", "reason": "none", "underlying": "susde"},
    ])
    _write(str(d / "rwa_safety_board.json"), {
        "n_assets": 11, "n_not_cash_like": 11,
        "verdict_counts": {"LIQUID": 0, "THIN": 1, "REDEMPTION_ONLY": 9, "UNSAFE": 1},
        "onchain_nav_coverage": {"max_abs_nav_divergence_pct": 8.1672},
    })
    _write(str(d / "forward_track_integrity.json"), {
        "all_ok": True, "n_tracks": 8, "n_failing": 0,
    })
    _write(str(d / "golive_dry_run.json"), {
        "moves_capital": False,
        "all_gates_reached": True, "ordering_ok": True,
        "would_proceed": False, "live_trading_gate_active": False,
        "gates": [{"name": "nav_reconciliation", "verdict": "PASS"}],
    })
    return str(root)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_deterministic(full_repo):
    a = GEN.generate(root=full_repo, now_iso="FIXED")
    b = GEN.generate(root=full_repo, now_iso="FIXED")
    assert a == b


def test_all_sections_present(full_repo):
    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    assert "## 1. The thesis" in doc
    assert "## 2. The validated edge" in doc
    assert "## 3. The forward track-to-date" in doc
    assert "## 4. The safety architecture" in doc
    assert "## 5. The off-code gates" in doc
    # footer
    assert "Regenerated FIXED" in doc
    assert "All numbers live from" in doc


def test_numbers_sourced_not_hardcoded(full_repo):
    """The output must reflect the MOCK data, proving nothing is hardcoded."""
    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    # rates-desk sleeve numbers from the mock
    assert "7.7777%" in doc
    assert "1234" in doc
    assert "fixed_carry" in doc
    assert "basis_hedge" in doc
    # decision-log proof chain counts derived from the mock (4 total, 3 refusals,
    # 2 tail-vetoes, 1 entry)
    assert "**4** logged decisions" in doc
    assert "**3 refusals**" in doc
    assert "**2** structural tail-vetoes" in doc
    assert "**1 entries**" in doc
    # RWA board from the mock
    assert "**11/11**" in doc
    assert "8.17%" in doc
    # go-live pass/total from the mock
    assert "**17/23 pass**" in doc
    # forward-track integrity from the mock
    assert "8 forward tracks" in doc


def test_forward_track_honest_n_of_30(full_repo):
    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    assert "**9/30 evidenced days — accruing, not yet 30**" in doc
    assert "**9/30 accruing**" in doc  # in the safety section too
    assert "2026-12-31" in doc  # target date sourced


def test_missing_sources_report_unavailable_not_fabricated(tmp_path):
    """An empty repo (no data/) must degrade to honest 'unavailable', never invent."""
    root = str(tmp_path)
    doc = GEN.generate(root=root, now_iso="FIXED")
    # all five sections still present
    for sec in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5."):
        assert sec in doc
    # honest unavailability surfaced for each missing source
    assert "data unavailable" in doc
    assert "golive_status.json missing" in doc
    assert "rates_desk_promotion.json missing" in doc
    assert "decision_log.jsonl missing" in doc
    assert "rwa_safety_board.json missing" in doc
    assert "forward_track_integrity.json missing" in doc
    assert "golive_dry_run.json missing" in doc
    # and CRUCIALLY no fabricated numbers leaked from the real repo
    assert "6.0901%" not in doc
    assert "246 logged" not in doc


def test_partial_source_only_that_field_unavailable(tmp_path):
    """A present-but-incomplete source yields UNAVAILABLE only for the missing field."""
    root = tmp_path
    d = root / "data"
    rd = d / "rates_desk"
    # golive present but missing real_track_days
    _write(str(d / "golive_status.json"), {"passed": 5, "total": 29})
    # promotion present but with a sleeve missing net_apy_pct
    _write(str(rd / "rates_desk_promotion.json"), {
        "rwa_floor_pct": 3.4,
        "sleeves": [{"shape": "fixed_carry", "stage": "PAPER_CANDIDATE",
                     "net_apy_pct": None, "beats_floor": True,
                     "max_drawdown_pct": 0.0, "refusals_count": 10, "kills": 1}],
    })
    doc = GEN.generate(root=str(root), now_iso="FIXED")
    # pass/total still rendered honestly
    assert "**5/29 pass**" in doc
    # the missing track-days field -> unavailable, not a guessed integer
    assert "Evidenced days: " in doc and "data unavailable" in doc
    # the present pass/total proves it's not blanket-unavailable
    assert "fixed_carry" in doc


def test_atomic_write_produces_file(full_repo, monkeypatch):
    """--md path writes the doc atomically to docs/FUNDABILITY.md."""
    out = os.path.join(full_repo, "docs", "FUNDABILITY.md")
    monkeypatch.setattr(GEN, "_repo_root", lambda: full_repo)
    rc = GEN.main(["--md"])
    assert rc == 0
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as fh:
        content = fh.read()
    assert "## 1. The thesis" in content
    # no stray temp files left behind
    leftovers = [f for f in os.listdir(os.path.join(full_repo, "docs"))
                 if f.startswith(".fundability_")]
    assert leftovers == []
