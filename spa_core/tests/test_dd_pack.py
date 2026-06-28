"""Tests for the DD pack generator (scripts/generate_dd_pack.py).

The headline contract is the **no-unsourced-number guard** (the hostile-LP self-check):
every numeric token in the rendered DD_PACK.md must be resolvable to a live data/ source or a
hashed decision row. A hardcoded number that drifts from data/ fails the build.

Also verified:
- determinism (same inputs -> byte-stable);
- the worked refused-vs-approved example cites REAL adjacent hashed rows (proof_hashes present,
  chain-adjacent: the ENTRY's prev_hash == the REFUSAL's entry_hash);
- missing sources degrade to honest "data unavailable", never fabricated numbers;
- the re-derived chain head matches the standalone verifier's head.
"""

import hashlib
import importlib.util
import json
import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_ROOT, "scripts", "generate_dd_pack.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("dd_pack_gen", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load_module()


# --------------------------------------------------------------------------- #
# Fixtures
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


def _chain_jsonl(rows):
    """Take rows lacking chain envelope fields and produce a valid single-genesis chain
    (seq, prev_hash, entry_hash) exactly per the verify_spa recipe, so the DD-pack can
    re-derive the head and cite real worked rows. NOTE: proof_hash is part of the hashed
    payload (it is NOT an envelope key), so it must be set BEFORE entry_hash is computed —
    exactly as the real producer does it — or the chain won't re-derive."""
    out = []
    prev = "0" * 64
    for i, r in enumerate(rows):
        row = dict(r)
        row["seq"] = i
        row["prev_hash"] = prev
        row.setdefault("ts", "2026-06-25T22:04:33.534555+00:00")
        # proof_hash is in the hashed payload → set it FIRST (stable placeholder).
        row.setdefault("proof_hash", hashlib.sha256((str(i) + row["prev_hash"]).encode()).hexdigest())
        # compute entry_hash via the generator's own recompute (the public recipe)
        eh = GEN._recompute_entry_hash(row)
        row["entry_hash"] = eh
        out.append(row)
        prev = eh
    return out


@pytest.fixture
def full_repo(tmp_path):
    """A repo with every data source populated with distinctive sentinel numbers + a valid chain
    carrying a real ezeth-REFUSAL -> susde-ENTRY adjacent pair."""
    root = tmp_path
    d = root / "data"
    rd = d / "rates_desk"

    _write(str(d / "golive_status.json"), {
        "passed": 17, "total": 23, "real_track_days": 9,
        "evidenced_anchor": "2026-01-01", "target_date": "2026-12-31",
    })
    _write(str(rd / "rates_desk_promotion.json"), {"rwa_floor_pct": 3.4, "sleeves": []})

    chain = _chain_jsonl([
        {"kind": "REFUSAL", "reason": "tail_veto", "underlying": "wsteth",
         "approved_size_usd": "0", "as_of": "2024-08-01", "shape": "fixed_carry",
         "net_edge": "-0.30",
         "decomposition": {"baseline": "0.02", "peg_haircut": "0.05",
                           "liquidity_haircut": "0.06", "protocol_haircut": "0.02",
                           "oracle_haircut": "0.005", "funding_flip_haircut": "0",
                           "total_haircut": "0.155", "fair_yield": "-0.135"},
         "detail": {"note": "tail-comp veto", "max_total_haircut": "0.12"}},
        # the adjacent worked pair: ezeth REFUSAL then susde ENTRY
        {"kind": "REFUSAL", "reason": "tail_veto", "underlying": "ezeth",
         "approved_size_usd": "0", "as_of": "2024-09-01", "shape": "fixed_carry",
         "net_edge": "-0.4242",
         "decomposition": {"baseline": "0.029", "peg_haircut": "0.064",
                           "liquidity_haircut": "0.06", "protocol_haircut": "0.026",
                           "oracle_haircut": "0.0066", "funding_flip_haircut": "0",
                           "total_haircut": "0.1566", "fair_yield": "-0.1276"},
         "detail": {"note": "tail-comp veto", "max_total_haircut": "0.12"}},
        {"kind": "ENTRY", "reason": "none", "underlying": "susde",
         "approved_size_usd": "4062.5", "as_of": "2024-09-01", "shape": "fixed_carry",
         "net_edge": "0.1803",
         "decomposition": {"baseline": "0.01", "peg_haircut": "0.0",
                           "liquidity_haircut": "0.06", "protocol_haircut": "0.012",
                           "oracle_haircut": "0.0033", "funding_flip_haircut": "0",
                           "total_haircut": "0.0753", "fair_yield": "-0.0653"},
         "detail": {"quoted_rate": "0.12", "exit_cap": "4062.5"}},
        {"kind": "REFUSAL", "reason": "size_floor", "underlying": "susds",
         "approved_size_usd": "0", "as_of": "2024-10-01", "shape": "fixed_carry",
         "net_edge": "0.01",
         "decomposition": {"baseline": "0.01", "peg_haircut": "0.0",
                           "liquidity_haircut": "0.06", "protocol_haircut": "0.012",
                           "oracle_haircut": "0.0033", "funding_flip_haircut": "0",
                           "total_haircut": "0.0753", "fair_yield": "-0.0653"},
         "detail": {}},
    ])
    _write_jsonl(str(rd / "decision_log.jsonl"), chain)

    # one anchor checkpointing the chain head
    head = chain[-1]["entry_hash"]
    _write_jsonl(str(rd / "anchors.jsonl"), [
        {"seq": 0, "ts": "2026-06-28T00:00:00+00:00", "head_hash": head,
         "chain_length": len(chain), "event_type": "rates_desk_anchor"},
    ])

    _write(str(rd / "portfolio_capacity.json"), {
        "n_fundable_books": 22, "n_harvestable_markets": 25,
        "total_deployable_usd": 330314.6, "aggregate_net_apy_pct": 22.9289,
        "rwa_floor_pct": 3.4, "dollars_above_floor_per_yr": 64779.43,
        "pct_of_10m_target": 0.6478, "gap_to_10m_usd": 9935220.57,
    })
    _write(str(d / "rwa_safety_board.json"), {
        "n_assets": 11, "n_not_cash_like": 11,
        "verdict_counts": {"LIQUID": 0, "THIN": 1, "REDEMPTION_ONLY": 9, "UNSAFE": 1},
        "onchain_nav_coverage": {"max_abs_nav_divergence_pct": 8.1672},
    })
    _write(str(d / "forward_track_integrity.json"), {
        "all_ok": True, "n_tracks": 8, "n_failing": 0,
    })
    _write(str(d / "golive_dry_run.json"), {
        "moves_capital": False, "all_gates_reached": True, "ordering_ok": True,
        "would_proceed": False, "live_trading_gate_active": False,
        "gates": [{"name": "nav_reconciliation", "verdict": "PASS"}],
    })
    return str(root)


# --------------------------------------------------------------------------- #
# The no-unsourced-number guard — the headline contract
# --------------------------------------------------------------------------- #

# Structural numbers that legitimately appear in PROSE / scaffolding and are NOT data claims:
# section numbers, the §9 rule reference, the "$10M/yr" GOAL (a stated target, not a measured
# claim), the "5-10x" qualitative ratio, the "$1.00" marketing-NAV reference unit, $0 real capital,
# the "/30" target horizon, "4626" (ERC-4626 standard name), "$100k" virtual book base.
_ALLOWED_STRUCTURAL = {
    # markdown section headers 1..8
    "1", "2", "3", "4", "5", "6", "7", "8", "10",
    "2a", "2b", "5a", "5b",
    "9",            # §9 exit-capacity rule
    "10m", "10M",   # the $10M/yr GOAL (target, not a claim)
    "5-10x", "5", "10x",  # qualitative "below the bar" ratio
    "4626",         # ERC-4626 (a standard's name)
    "256",          # SHA-256 (algorithm name)
    "1.00",         # marketing-NAV reference unit ($1.00)
    "0",            # $0 real capital / generic zero
}


def _atoms(s):
    """Atomic numeric sub-tokens of a string ('2026-07-21'->2026,07,21; '17/23'->17,23)."""
    out = set()
    for m in re.findall(r"[0-9]+(?:\.[0-9]+)?%?", s):
        out.add(m)
        out.add(m.rstrip("%"))
    return out


def _numeric_tokens_in(text):
    """Tokenize the doc the way the guard must: composite digit-runs (with . , % x / + -), their
    atomic sub-numbers, plus section-header tokens like '2a'. Hex hashes are handled separately."""
    toks = set()
    for m in re.findall(r"[0-9][0-9.,%x/+-]*[0-9%x]|[0-9]", text):
        toks.add(m)
    toks |= _atoms(text)
    for m in re.findall(r"\b[0-9][a-z]\b", text):
        toks.add(m)
    return toks


def _hash_tokens_in(text):
    """All 64-hex strings (hashes) — registered as sourced, excluded from the numeric guard."""
    return set(re.findall(r"\b[0-9a-f]{64}\b", text))


def test_no_unsourced_numbers(full_repo):
    """HOSTILE-LP GUARD: every numeric token in the rendered doc is either (a) a sourced number,
    (b) a registered hash, or (c) a whitelisted structural/goal token. Anything else FAILS."""
    doc = GEN.generate_doc(root=full_repo, now_iso="2026-01-01 00:00 UTC")
    text = doc.render()
    sourced = set(doc.sourced_map().keys())
    # also allow numeric sub-tokens of every sourced value (e.g. '3.4%' -> '3.4','4')
    for s in list(sourced):
        sourced |= _atoms(str(s))
        for t in re.findall(r"[0-9][0-9.,%x/+-]*[0-9%x]|[0-9]", str(s)):
            sourced.add(t)

    hashes = _hash_tokens_in(text)
    # strip the footer timestamp line (we pinned now_iso, but the date contains digits) and
    # code-block verifier commands (they echo sourced hashes/paths already covered).
    found = _numeric_tokens_in(text)

    # build the full allow-set
    allow = set()
    allow |= sourced
    allow |= _ALLOWED_STRUCTURAL
    # the pinned now_iso tokens are allowed (deterministic header/footer timestamp)
    for t in _numeric_tokens_in("2026-01-01 00:00 UTC"):
        allow.add(t)
    # hash tokens are allowed (each is registered/sourced)
    allow |= hashes
    # also allow numeric fragments inside hashes (defensive — the tokenizer won't split hashes,
    # but module paths / ERC-4626 already covered above)

    # A token passes if it is directly allowed, OR every one of its atomic sub-numbers is allowed
    # (so a composite like '17/23' passes when both '17' and '23' are sourced).
    def _ok(tok):
        if tok in allow:
            return True
        atoms = _atoms(tok)
        return bool(atoms) and all(a in allow for a in atoms)

    unsourced = sorted(t for t in found if not _ok(t))
    assert not unsourced, (
        "UNSOURCED numeric tokens in DD_PACK.md (every number must trace to data/ or a hashed "
        "row, or be whitelisted structural):\n  " + "\n  ".join(unsourced)
    )


def test_deterministic(full_repo):
    a = GEN.generate(root=full_repo, now_iso="FIXED")
    b = GEN.generate(root=full_repo, now_iso="FIXED")
    assert a == b


def test_all_sections_present(full_repo):
    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    for sec in ("## 1. Executive verdicts", "## 2. The validated GO",
                "## 3. The decision record", "## 4. Honest capacity",
                "## 5. The other two theses", "## 6. The off-code gates",
                "## 7. The track status", "## 8. How a hostile LP checks"):
        assert sec in doc, sec
    assert "Regenerated FIXED" in doc


def test_worked_example_cites_real_adjacent_hashed_rows(full_repo):
    """The §2 worked example must cite the REAL ezeth REFUSAL + the susde ENTRY, with their real
    proof_hashes, and they must be chain-adjacent (ENTRY.prev_hash == REFUSAL.entry_hash)."""
    rd = os.path.join(full_repo, "data", "rates_desk", "decision_log.jsonl")
    rows = [json.loads(l) for l in open(rd) if l.strip()]
    ref = next(r for r in rows if r["underlying"] == "ezeth" and r["kind"] == "REFUSAL")
    ent = next(r for r in rows if r["underlying"] == "susde" and r["kind"] == "ENTRY")
    # adjacency is what makes the worked example provable
    assert ent["prev_hash"] == ref["entry_hash"]

    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    # both underlyings + both verdicts named
    assert "REFUSAL — `ezeth`" in doc
    assert "ENTRY — `susde`" in doc
    # the real hashes are present
    assert ref["proof_hash"] in doc
    assert ref["entry_hash"] in doc
    assert ent["proof_hash"] in doc
    # the haircut breakdown is rendered (peg/total)
    assert "peg haircut" in doc
    assert "total haircut" in doc
    # adjacency is claimed in prose
    assert "provably adjacent" in doc


def test_head_matches_verifier(full_repo):
    """The chain head the DD pack cites equals the head re-derived by the standalone verifier recipe."""
    rd = os.path.join(full_repo, "data", "rates_desk", "decision_log.jsonl")
    rows = [json.loads(l) for l in open(rd) if l.strip()]
    head = rows[-1]["entry_hash"]
    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    assert head in doc
    assert f"--expect-head {head}" in doc


def test_capacity_numbers_sourced(full_repo):
    doc = GEN.generate(root=full_repo, now_iso="FIXED")
    assert "22" in doc and "25" in doc        # fundable books / harvestable markets
    assert "$330,315" in doc                  # total deployable
    assert "$64,779/yr" in doc                # carry above floor
    assert "0.65%" in doc                     # pct of 10M target


def test_missing_sources_report_unavailable_not_fabricated(tmp_path):
    """An empty repo (no data/) degrades to honest 'data unavailable', never invents numbers."""
    doc = GEN.generate(root=str(tmp_path), now_iso="FIXED")
    # sections still present
    for sec in ("## 1.", "## 2.", "## 4.", "## 5.", "## 7."):
        assert sec in doc
    assert "data unavailable" in doc
    # crucially no real-repo numbers leaked
    assert "394" not in doc
    assert "$330,315" not in doc
    # the no-unsourced guard still holds on the empty doc
    d = GEN.generate_doc(root=str(tmp_path), now_iso="2026-01-01 00:00 UTC")
    text = d.render()
    sourced = set(d.sourced_map().keys())
    for s in list(sourced):
        sourced |= _atoms(str(s))
        for t in re.findall(r"[0-9][0-9.,%x/+-]*[0-9%x]|[0-9]", str(s)):
            sourced.add(t)
    allow = sourced | _ALLOWED_STRUCTURAL | _hash_tokens_in(text)
    for t in _numeric_tokens_in("2026-01-01 00:00 UTC"):
        allow.add(t)

    def _ok(tok):
        if tok in allow:
            return True
        atoms = _atoms(tok)
        return bool(atoms) and all(a in allow for a in atoms)

    unsourced = sorted(t for t in _numeric_tokens_in(text) if not _ok(t))
    assert not unsourced, "unsourced numbers even in the empty-repo doc: " + ", ".join(unsourced)


def test_liquidator_nogo_sourced_to_doc(full_repo):
    """The Liquidator NO-GO figures are cited from the published de-risk doc, registered as sourced."""
    doc_obj = GEN.generate_doc(root=full_repo, now_iso="FIXED")
    text = doc_obj.render()
    assert "$3.8M/yr" in text
    assert "$2.2M/yr" in text
    assert "$20M/yr" in text
    assert "docs/LIQUIDATOR_DERISK.md" in text
    # those M-figures are registered as sourced from the doc
    smap = doc_obj.sourced_map()
    assert any("LIQUIDATOR_DERISK" in v for v in smap.values())


def test_atomic_write(full_repo, monkeypatch):
    out = os.path.join(full_repo, "docs", "DD_PACK.md")
    monkeypatch.setattr(GEN, "_repo_root", lambda: full_repo)
    rc = GEN.main([])
    assert rc == 0
    assert os.path.exists(out)
    leftovers = [f for f in os.listdir(os.path.join(full_repo, "docs"))
                 if f.startswith(".dd_pack_")]
    assert leftovers == []
