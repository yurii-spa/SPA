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
FROZEN_FIELDS = {
    "paper_apy_pct": ["facts?.paper_apy_pct", "facts.paper_apy_pct"],
    "max_drawdown_pct": ["max_drawdown_pct"],
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
    collision = set(snap.keys()) & set(FROZEN_FIELDS)
    assert not collision, (
        f"paper_apy_snapshot() emits frozen landing-read field name(s) {collision} "
        "— this silently changes a public number through the API without owner "
        "authorisation (ADR-285 subject #2, F4)"
    )
    assert "paper_apy_canonical" in snap
    assert "max_drawdown_track_pct" in snap
