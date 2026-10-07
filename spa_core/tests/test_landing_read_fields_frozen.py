"""spa_core/tests/test_landing_read_fields_frozen.py — guard (integration review F4,
2026-10-05): a field any live `landing/` page reads off `/api/ssot/facts` or
`/api/health-public` must keep its OLD value semantics until the owner explicitly
authorises a switch (ADR-285 subject #2 — public yield/drawdown numbers).

The regression this guards: `spa_core.governance.ssot.paper_apy_snapshot()` (new,
RM-TRUTH-01 W5) returned its canonical rate/drawdown under the SAME bare names two
landing pages already read (`paper_apy_pct` via `/api/ssot/facts` →
`DashboardSPAApp.jsx:288`'s `facts.paper_apy_pct ?? facts.apy_today_pct`; and
`max_drawdown_pct` via `/api/health-public` → `index.astro`'s `#m-dd` and
`track-record.astro`'s `#tr-dd`). Merging that dict into either endpoint's response
silently swapped what those public numbers render — a visible change made through
the API, without the owner's authorisation.

This is a SCAN, not a hand-maintained list: it reads the literal field names out of
the live `landing/` source tree, so a future landing edit that starts reading a new
field by one of these exact bare names is caught automatically, rather than relying
on someone remembering to update a list here.
"""
from __future__ import annotations

import re
from pathlib import Path

from spa_core.governance.ssot import paper_apy_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
LANDING_SRC = REPO_ROOT / "landing" / "src"

#: Bare field names this review found landing pages reading off the two endpoints
#: `paper_apy_snapshot()` feeds. Each is checked both ways: (a) a landing file still
#: reads it today (so the freeze is still meaningful) and (b) the producer's dict
#: never emits it under this exact name.
FROZEN_FIELDS = {}

#: PRODUCT-TRUTH-02 (2026-10-07, owner-gated publication candidate): `/dashboard` no longer reads
#: `facts.paper_apy_pct` — that read was the fallback chain `paper_apy_pct ?? apy_today_pct`, which
#: showed a one-day OBSERVED rate as «Paper APY» (ADR-580 C2). The page now reads the typed
#: `paper_apy_canonical`. The bare name is RETIRED, not forgotten: the producer must still never
#: emit it (test below), and landing must never read it again (a re-introduced fallback is red).
RETIRED_READ_FIELDS = {
    "paper_apy_pct": ["facts?.paper_apy_pct", "facts.paper_apy_pct"],
    # PRODUCT-TRUTH-02: `#m-dd` (index) and `#tr-dd` (track-record) no longer overwrite the published
    # drawdown with `/api/health-public`'s `d.max_drawdown_pct`; the bare name is retired the same way.
    "max_drawdown_pct": ["d.max_drawdown_pct"],
}


def _landing_text():
    if not LANDING_SRC.is_dir():
        return None
    parts = []
    for ext in ("*.astro", "*.jsx", "*.js"):
        for p in LANDING_SRC.rglob(ext):
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(parts)


def test_landing_still_reads_each_frozen_field_by_this_exact_name():
    """Sanity check on the guard itself: if landing/ stopped reading a name here,
    the freeze on that name is stale and the test below would be vacuous."""
    text = _landing_text()
    if text is None:
        import pytest
        pytest.skip("landing/src not present in this checkout — cannot measure")
    if not FROZEN_FIELDS:
        # Nothing is frozen any more — but that must be an explicit, measured state, not a silent pass:
        # both formerly frozen names are retired (and checked below never to be read again).
        assert set(RETIRED_READ_FIELDS) >= {"paper_apy_pct", "max_drawdown_pct"}, (
            "FROZEN_FIELDS is empty but the retired set is incomplete — re-measure the guard's premise")
        return
    for field, needles in FROZEN_FIELDS.items():
        assert any(n in text for n in needles), (
            f"landing/ no longer reads {field!r} by any known pattern — this "
            "guard's premise needs re-measuring, not silently trusting"
        )


def test_paper_apy_snapshot_never_emits_a_frozen_bare_name():
    """The canonical producer must expose its value ONLY under its new, distinct
    names (`paper_apy_canonical`, `max_drawdown_track_pct`) — never under a bare
    name a landing page already reads off the SAME endpoints it feeds
    (`/api/ssot/facts` via `key_facts()`, `/api/health-public` via `**snap`)."""
    snap = paper_apy_snapshot(REPO_ROOT / "data")
    collision = set(snap.keys()) & (set(FROZEN_FIELDS) | set(RETIRED_READ_FIELDS))
    assert not collision, (
        f"paper_apy_snapshot() emits frozen landing-read field name(s) {collision} "
        "— this silently changes a public number through the API without owner "
        "authorisation (ADR-285 subject #2, F4)"
    )
    assert "paper_apy_canonical" in snap
    assert "max_drawdown_track_pct" in snap


def _retired_access_pattern(field):
    """Any property access to the bare name: `<identifier>.<field>`, `<identifier>?.<field>`,
    `["<field>"]` / `['<field>']` — not only the one spelling that existed when it was retired."""
    import re as _re
    return _re.compile(r"(?:[A-Za-z_$][\w$]*\s*\??\.\s*" + _re.escape(field) + r"\b)"
                       r"|(?:\[\s*['\"]" + _re.escape(field) + r"['\"]\s*\])")


#: Landing files that fetch the two endpoints `paper_apy_snapshot()` feeds.
_GUARDED_ENDPOINTS = ("/api/health-public", "/api/ssot/facts")

#: Receivers in those files whose `.max_drawdown_pct` is NOT a read of the guarded endpoints (the name is
#: generic: many payloads carry it). Each is declared with what it IS; any other receiver is a finding.
NON_ENDPOINT_RECEIVERS = {
    "snap": "landing/src/lib/snapshot_view.js — the published weekly shelf, the intended source",
    "s": "DashboardLive sleeve rows (/api/sleeves), a per-sleeve drawdown",
    "r": "DashboardLive backtest/tournament rows, a per-strategy BACKTEST drawdown",
    "mm": "DashboardLive annual-contrast metrics (BACKTEST aggressive side)",
}


def _guarded_files():
    out = []
    for ext in ("*.astro", "*.jsx", "*.js"):
        for p in LANDING_SRC.rglob(ext):
            t = p.read_text(encoding="utf-8", errors="ignore")
            if any(e in t for e in _GUARDED_ENDPOINTS):
                out.append((p, t))
    return out


def test_landing_never_reads_a_retired_field_again():
    """PRODUCT-TRUTH-02: a retired bare read (one-day-rate fallback, API drawdown overwrite) must not come back.
    Scope: every file that fetches a guarded endpoint; every access spelling; only declared non-endpoint
    receivers are exempt, so a new `d.`/`facts.`/`x["…"]` read is red."""
    if not LANDING_SRC.is_dir():
        import pytest
        pytest.skip("landing/src not present in this checkout — cannot measure")
    files = _guarded_files()
    assert files, "no landing file fetches the guarded endpoints — the guard's premise needs re-measuring"
    import re as _re
    findings = []
    for p, t in files:
        for field in RETIRED_READ_FIELDS:
            for m in _retired_access_pattern(field).finditer(t):
                recv = _re.match(r"([A-Za-z_$][\w$]*)", m.group(0))
                if recv and recv.group(1) in NON_ENDPOINT_RECEIVERS and not m.group(0).startswith("["):
                    continue
                findings.append(f"{p.relative_to(REPO_ROOT)}: {m.group(0)}")
    assert not findings, f"landing/ reads a retired field off a guarded endpoint again: {findings}"


def test_retired_access_pattern_catches_every_spelling():
    """Positive and negative control for the matcher itself."""
    pat = _retired_access_pattern("max_drawdown_pct")
    for bad in ("d.max_drawdown_pct", "facts?.max_drawdown_pct", "s . max_drawdown_pct",
                "x['max_drawdown_pct']", 'x["max_drawdown_pct"]'):
        assert pat.search(bad), bad
    for ok in ("max_drawdown_track_pct", "realized_max_drawdown_pct", "const max_drawdown_pct_note = 1",
               "max_drawdown_pct_as_of"):
        assert not pat.search(ok), ok
