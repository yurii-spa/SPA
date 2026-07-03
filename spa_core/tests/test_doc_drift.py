"""
test_doc_drift.py — DR / runbook doc-drift guard.

A disaster-recovery runbook that LIES is worse than none. The canonical DR doc
(``docs/DISASTER_RECOVERY.md``) was once stale to the point of dangerous: it
referenced RETIRED agents (whose revival re-triggers the Telegram-409 /
duplicate-flood regression), a DELETED install script, and wrong ports. This
test makes the canonical runbook unable to silently rot back into lying.

It enforces, on the CANONICAL doc only:
  1. No RETIRED agent label appears as a thing to run/revive. The retired set is
     SOURCED FROM ``agent_health_monitor.RETIRED_LABELS`` (never a hard-coded
     divergent list) so the guard widens automatically when an agent is retired.
  2. No reference to the deleted standalone ``install_agents.sh`` — the real
     installer is ``install_all_agents.sh`` (matched so the correct name passes).
  3. No wrong-port assignment (e.g. binding the apiserver's :8765 to httpserver,
     or claiming the dashboard/family-fund ports are something else).

And, on the SUPERSEDED docs (which legitimately still CONTAIN retired tokens as
history): each must carry a SUPERSEDED header pointing at the canonical doc — so
they can't be mistaken for current procedure.

stdlib only; deterministic; no network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "docs"
_DATA = _REPO_ROOT / "data"

CANONICAL = _DOCS / "DISASTER_RECOVERY.md"

# ---------------------------------------------------------------------------
# Narrative-doc state-number guard (audit finding #8).
#
# The narrative docs (CLAUDE.md / CURRENT_STATE.md / README.md / RULES.md) drift
# off the authoritative live state — go-live counts, evidenced track days, the
# evidenced anchor date, and the kill-switch thresholds get hand-edited and rot.
# These tests PIN the docs to the real source files so a future drift FAILS CI:
#   * data/golive_status.json      → passed/total, real_track_days, anchor
#   * spa_core/governance/kill_switch.py → SOFT 5% / HARD 10% thresholds
# Each doc is required to STATE the authoritative number (and, for the kill
# thresholds, to NOT assert the wrong "5% liquidates"/"15% kill" story).
# ---------------------------------------------------------------------------
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"
_CURRENT_STATE_MD = _REPO_ROOT / "CURRENT_STATE.md"
_README_MD = _REPO_ROOT / "README.md"
_RULES_MD = _REPO_ROOT / "RULES.md"
_DECISIONS_MD = _DOCS / "DECISIONS.md"

_GOLIVE_STATUS = _DATA / "golive_status.json"
_KILL_SWITCH_PY = _REPO_ROOT / "spa_core" / "governance" / "kill_switch.py"

# Docs that are intentionally STALE and kept only as history. They legitimately
# still contain retired tokens, so they are NOT scanned for those — instead each
# must carry a SUPERSEDED header pointing at the canonical doc.
SUPERSEDED_DOCS = [
    _DOCS / "DR_PROCEDURE_v1.md",
    _DOCS / "DR_PROCEDURE_v2.md",
    _DOCS / "RUNBOOK.md",
    _DOCS / "operator_runbook.md",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# A line REVIVES a retired agent when it loads/bootstraps/kickstarts/installs it.
# A line that BOOTS IT OUT, UNLOADS it, or merely says it is RETIRED is exactly
# what the runbook SHOULD say, so those are allowed.
_REVIVE_VERB = re.compile(
    r"launchctl\s+(load|bootstrap|kickstart)\b|\binstall_agent\b|bash\s+\S*install",
    re.IGNORECASE,
)
_ALLOWED_CONTEXT = re.compile(r"bootout|unload|retired|do not|never", re.IGNORECASE)


def _lines_reviving_retired(text: str) -> list[str]:
    """Return any line that presents a RETIRED label as something to load/revive.

    A prose mention ('com.spa.httpserver is RETIRED — do not revive') or an
    example bootout is fine; a `launchctl load …com.spa.httpserver` is the drift
    we must catch.
    """
    bad: list[str] = []
    for ln in text.splitlines():
        if not any(lbl in ln for lbl in RETIRED_LABELS):
            continue
        if _REVIVE_VERB.search(ln) and not _ALLOWED_CONTEXT.search(ln):
            bad.append(ln.strip())
    return bad


# ---------------------------------------------------------------------------
# 1. Canonical doc exists and is the one true DR doc.
# ---------------------------------------------------------------------------
def test_canonical_dr_doc_exists():
    assert CANONICAL.is_file(), f"canonical DR doc missing: {CANONICAL}"
    head = _read(CANONICAL)[:600]
    assert "CANONICAL" in head, "canonical DR doc must declare itself CANONICAL"


# ---------------------------------------------------------------------------
# 2. No RETIRED agent is presented as something to LOAD/REVIVE in the canonical
#    doc. Prose that names them as retired / boots them out is fine. The retired
#    set is sourced from RETIRED_LABELS so the guard can never diverge.
# ---------------------------------------------------------------------------
def test_canonical_doc_does_not_revive_retired_agents():
    assert RETIRED_LABELS, "RETIRED_LABELS unexpectedly empty — guard would be a no-op"
    offenders = _lines_reviving_retired(_read(CANONICAL))
    assert not offenders, (
        "canonical DR doc presents a RETIRED agent as something to load/revive "
        "(reviving re-triggers the Telegram-409 / duplicate-flood / EADDRINUSE "
        "regression):\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 3. No reference to the DELETED standalone install_agents.sh. The real
#    installer is install_all_agents.sh (which must therefore still pass).
# ---------------------------------------------------------------------------
def test_canonical_doc_uses_correct_installer():
    text = _read(CANONICAL)
    # A RUNNABLE invocation of the deleted standalone script (bash/sh … +
    # install_agents.sh not preceded by 'all_') is drift. Prose that merely warns
    # 'the standalone install_agents.sh no longer exists' is allowed.
    runnable_bad = [
        ln.strip() for ln in text.splitlines()
        if re.search(r"\b(bash|sh)\b[^\n]*(?<!all_)install_agents\.sh", ln)
    ]
    assert not runnable_bad, (
        "canonical DR doc invokes the DELETED standalone 'install_agents.sh'. "
        "The real installer is 'scripts/install_all_agents.sh':\n  "
        + "\n  ".join(runnable_bad)
    )
    assert "install_all_agents.sh" in text, (
        "canonical DR doc must point at the real installer install_all_agents.sh"
    )


# ---------------------------------------------------------------------------
# 4. Ports are assigned correctly. The classic drift is httpserver/dashboard/
#    familyfund being told to use the wrong port. Assert the canonical
#    port→owner facts and forbid the known-wrong assignments.
# ---------------------------------------------------------------------------
def test_canonical_doc_has_correct_ports():
    text = _read(CANONICAL).lower()
    # apiserver owns 8765
    assert "8765" in text and "apiserver" in text, "doc must state apiserver:8765"
    # the retired httpserver must NOT be presented as the :8765 owner
    assert not re.search(r"httpserver[^\n]{0,40}8765[^\n]{0,40}(run|load|start|bind)", text), (
        "doc assigns :8765 to the retired httpserver (it crash-loops on EADDRINUSE)"
    )
    # family fund = 8766, dashboard = 8767 (wrong-port drift guard)
    assert "8766" in text, "doc must mention the family-fund port 8766"
    assert "8767" in text, "doc must mention the dashboard port 8767"


# ---------------------------------------------------------------------------
# 5. The verify-fleet helper + pre-deploy gate are referenced (current reality).
# ---------------------------------------------------------------------------
def test_canonical_doc_references_current_reality_scripts():
    text = _read(CANONICAL)
    for needed in (
        "verify_fleet_after_reboot.sh",
        "check_agent_before_deploy.sh",
        "install_all_agents.sh",
    ):
        assert needed in text, f"canonical DR doc must reference {needed}"


# ---------------------------------------------------------------------------
# 6. Every superseded doc carries a SUPERSEDED header pointing at the canonical
#    doc — so its stale (retired-token-laden) content can't be mistaken for
#    current procedure.
# ---------------------------------------------------------------------------
def test_superseded_docs_point_at_canonical():
    for doc in SUPERSEDED_DOCS:
        if not doc.is_file():
            continue
        head = _read(doc)[:800]
        assert "SUPERSEDED" in head.upper(), (
            f"{doc.name} must carry a SUPERSEDED header (it is stale history)"
        )
        assert "DISASTER_RECOVERY.md" in head, (
            f"{doc.name}'s SUPERSEDED header must cross-link the canonical "
            "DISASTER_RECOVERY.md"
        )


# ===========================================================================
# WIDENED GUARD — narrative-doc state-number parity (audit finding #8).
#
# The DR guard above protects the runbooks. The narrative state docs drift the
# same way: their hand-edited go-live / track / anchor / kill-switch numbers rot
# off the authoritative source files. These tests PIN the docs to the source so
# a future drift FAILS, exactly like the runbook guard.
# ===========================================================================


def _require_golive_status():
    """WS4 hermeticity: these doc-drift pins read the LIVE go-live snapshot.
    On a clean checkout with an empty data/ the snapshot is absent — skip
    (this is an SSOT-consistency guard, not a hermetic unit test)."""
    if not _GOLIVE_STATUS.is_file():
        pytest.skip(f"live-data artifact absent (clean checkout): {_GOLIVE_STATUS}")


def _authoritative_golive() -> dict:
    """Read the live go-live snapshot — the single source of truth for the
    passed/total counts, evidenced track days, and the evidenced anchor date."""
    return json.loads(_GOLIVE_STATUS.read_text(encoding="utf-8"))


def _kill_switch_thresholds() -> tuple[float, float]:
    """Parse (SOFT, HARD) drawdown thresholds straight from kill_switch.py — the
    source of truth — so the doc assertions track the real constants."""
    src = _KILL_SWITCH_PY.read_text(encoding="utf-8")
    soft = re.search(r"^SOFT_DERISK_THRESHOLD_PCT\s*=\s*([\d.]+)", src, re.MULTILINE)
    hard = re.search(r"^DRAWDOWN_THRESHOLD_PCT\s*=\s*([\d.]+)", src, re.MULTILINE)
    assert soft and hard, "could not parse kill-switch thresholds from kill_switch.py"
    return float(soft.group(1)), float(hard.group(1))


def _pct(value: float) -> str:
    """Render a threshold like 5.0 → '5' / 10.0 → '10' (the form docs use)."""
    return str(int(value)) if float(value).is_integer() else str(value)


# ---------------------------------------------------------------------------
# 7. The authoritative source files we pin against actually exist and are sane.
# ---------------------------------------------------------------------------
def test_authoritative_sources_present():
    _require_golive_status()
    assert _GOLIVE_STATUS.is_file(), f"missing authoritative {_GOLIVE_STATUS}"
    assert _KILL_SWITCH_PY.is_file(), f"missing authoritative {_KILL_SWITCH_PY}"
    g = _authoritative_golive()
    assert isinstance(g.get("passed"), int) and isinstance(g.get("total"), int)
    assert isinstance(g.get("real_track_days"), int)
    assert isinstance(g.get("evidenced_anchor"), str) and g["evidenced_anchor"]
    soft, hard = _kill_switch_thresholds()
    assert 0 < soft < hard, f"kill thresholds out of order: SOFT={soft} HARD={hard}"


# ---------------------------------------------------------------------------
# 8. CLAUDE.md / CURRENT_STATE.md / README.md state-tables carry a SANE go-live
#    count, evidenced track days, and the evidenced anchor — not a drifted/
#    pre-reset story. PIN TO STABLE INVARIANTS, tolerate the known intra-day
#    transients.
#
#    Why a band, not an exact match: BOTH the go-live `passed` count and the
#    `real_track_days` counter LEGITIMATELY move during the day while the
#    narrative docs hold a stable snapshot value:
#      * go-live `passed` DIPS pre-dawn (e.g. 26/29) and recovers (27/29) once
#        the daily cycle + digest run flip the gap_monitor/telegram criteria;
#      * `real_track_days` TICKS UP once per UTC day (7 → 8 → …) while the doc
#        snapshot lags by ≤ a day.
#    Pinning static prose to a value that moves intra-day can never be stable, so
#    instead we assert the doc value sits in a tight, source-derived band around
#    the live value — which still FAILS on a genuinely-wrong number (old 15/30
#    drift, a wrong anchor) but PASSES across the known transient.
# ---------------------------------------------------------------------------
def _doc_fraction(text: str, denom: int, *, lo: int, hi: int) -> int | None:
    """Return the FIRST `n/denom` numerator in `text` whose n ∈ [lo, hi].

    Used to locate the doc's stated go-live / track value without demanding it
    equal a specific (drifting) live number — only that it sits in a sane band.
    """
    for m in re.finditer(rf"\b(\d+)\s*/\s*{denom}\b", text):
        n = int(m.group(1))
        if lo <= n <= hi:
            return n
    return None


def test_narrative_docs_match_golive_state():
    _require_golive_status()
    g = _authoritative_golive()
    passed, total = g["passed"], g["total"]
    track, anchor = g["real_track_days"], g["evidenced_anchor"]

    # GoLive band: docs must show some `n/total` with the STABLE total (29) and a
    # passed count that is at least the live value (so the stable 27 passes even
    # when golive momentarily dips to 26) and no higher than total, and never
    # more than 3 below total (catches a genuinely-wrong low number like 15).
    golive_lo = max(passed, total - 3)
    golive_hi = total

    # Track-days band (TEST-2 decouple): the daily cycle advances `track` continuously, so a ±1 window
    # coupled a static doc number to a live counter and flipped the suite red every ~2 days (and could
    # flip mid-run as the agent rewrote golive_status.json). The ANCHOR date (asserted below) is the real
    # drift guard; the number only needs a sanity band. So tolerate a LAGGING doc (up to ~a week behind)
    # while keeping the UPPER bound tight — a doc may never OVERSTATE the track, and a wrong-era/inflated
    # value (e.g. 30, or a pre-reset high) is still caught by `track_hi`.
    track_lo = max(0, track - 7)
    track_hi = min(30, track + 1)

    for path in (_CLAUDE_MD, _CURRENT_STATE_MD, _README_MD):
        text = _read(path)

        doc_passed = _doc_fraction(text, total, lo=golive_lo, hi=golive_hi)
        assert doc_passed is not None, (
            f"{path.name} drifted: no sane GoLive count 'n/{total}' with "
            f"{golive_lo} <= n <= {golive_hi} (live={passed}/{total}, "
            f"data/golive_status.json). A value outside this band is genuine "
            f"drift — the stable doc value should be {passed}/{total}."
        )

        doc_track = _doc_fraction(text, 30, lo=track_lo, hi=track_hi)
        assert doc_track is not None, (
            f"{path.name} drifted: no sane evidenced track-days 'n/30' with "
            f"{track_lo} <= n <= {track_hi} (live={track}/30, "
            f"data/golive_status.json)."
        )

        assert anchor in text, (
            f"{path.name} drifted: missing authoritative evidenced anchor "
            f"'{anchor}' from data/golive_status.json"
        )


# ---------------------------------------------------------------------------
# 9. CLAUDE.md must NOT re-introduce the self-contradictory transient pre-dawn
#    GoLive dip (e.g. 26/29) baked in WITHOUT a caveat alongside the
#    authoritative count, and must NOT reference a non-existent '/app' page.
# ---------------------------------------------------------------------------
def test_claude_md_no_stale_golive_or_app_ref():
    _require_golive_status()
    g = _authoritative_golive()
    text = _read(_CLAUDE_MD)
    # The transient dip value (total-1)/total must not appear as a bare state
    # number in the LIVE content (the canonical is passed/total). The dated
    # changelog footer may legitimately record it as history (e.g. "было 26/29").
    live_section = text.split("*Обновлено:")[0]
    stale_dip = f"{g['passed'] - 1}/{g['total']}"
    assert stale_dip not in live_section, (
        f"CLAUDE.md re-introduced the transient pre-dawn GoLive dip '{stale_dip}' "
        f"— canonical is '{g['passed']}/{g['total']}' (data/golive_status.json)"
    )
    # There is NO '/app' page — canonical app/dashboard route is '/dashboard'.
    # Forbid only an AFFIRMATIVE '/app' route claim ("на /app", "/app, EN") in
    # the live content; a NEGATED mention ("НЕ /app", "not /app") is the correct
    # corrective note and is allowed. The dated changelog footer (historical
    # record of past edits) is excluded entirely.
    live_section = text.split("*Обновлено:")[0]
    bad_app = [
        ln.strip()
        for ln in live_section.splitlines()
        if "/app" in ln
        and not re.search(r"(НЕ|не|not|no)\s*`?/app", ln, re.IGNORECASE)
    ]
    assert not bad_app, (
        "CLAUDE.md affirmatively references a non-existent '/app' page in its "
        "live content — the canonical dashboard route is '/dashboard':\n  "
        + "\n  ".join(bad_app)
    )


# ---------------------------------------------------------------------------
# 10. The kill-switch is the TWO-TIER ladder (ADR-034/048): SOFT de-risk (does
#     NOT liquidate) + HARD all-cash. RULES.md must state BOTH source-of-truth
#     thresholds and must NOT assert the old "5% liquidates" / "15% kill" story.
# ---------------------------------------------------------------------------
def test_rules_md_kill_switch_two_tier():
    soft, hard = _kill_switch_thresholds()
    soft_s, hard_s = _pct(soft), _pct(hard)
    text = _read(_RULES_MD)
    assert f"{soft_s}%" in text, (
        f"RULES.md missing the SOFT de-risk threshold '{soft_s}%' "
        f"(kill_switch.SOFT_DERISK_THRESHOLD_PCT)"
    )
    assert f"{hard_s}%" in text, (
        f"RULES.md missing the HARD kill threshold '{hard_s}%' "
        f"(kill_switch.DRAWDOWN_THRESHOLD_PCT) — two-tier ladder must be stated"
    )
    # The retired single-tier story: a 15% kill threshold no longer exists.
    assert "15%" not in text, (
        "RULES.md still references the retired 15% kill threshold "
        f"(now HARD {hard_s}%, ADR-048)"
    )


# ---------------------------------------------------------------------------
# 11. docs/DECISIONS.md P3-10 note (which still cites the old 15% HARD value as
#     history) must carry a SUPERSEDED cross-link to ADR-048 so a reader hitting
#     it first gets the correct current threshold.
# ---------------------------------------------------------------------------
def test_decisions_p3_10_superseded_crosslink():
    text = _read(_DECISIONS_MD)
    assert "P3-10" in text, "DECISIONS.md missing the P3-10 note"
    # Locate the P3-10 SECTION HEADER (not the earlier in-prose 'P3-10' refs that
    # live inside ADR-048) and require a SUPERSEDED→ADR-048 marker right under it.
    m = re.search(r"^#+ .*P3-10", text, re.MULTILINE)
    assert m, "DECISIONS.md missing the '## … (P3-10 …)' section header"
    section = text[m.start(): m.start() + 1500]
    assert "SUPERSEDED" in section.upper() and "ADR-048" in section, (
        "DECISIONS.md P3-10 note must carry a SUPERSEDED cross-link to ADR-048 "
        "(its 15% kill value is historical — live HARD threshold is now 10%)"
    )


# ---------------------------------------------------------------------------
# 12. PROOF_CHAIN_SPEC worked example must REPRODUCE against the LIVE chain
#     (audit finding #2). The §3 worked example pins a literal entry_hash for the
#     row at seq=111; the chain was regenerated, so a stale literal would mean a
#     skeptic following the spec literally gets a MISMATCH. This test recomputes
#     the live seq=111 entry_hash exactly per the spec and asserts the spec's
#     pinned literal equals it — so the published example can never silently rot.
# ---------------------------------------------------------------------------
_PROOF_SPEC = _DOCS / "PROOF_CHAIN_SPEC.md"
_DECISION_LOG = _DATA / "rates_desk" / "decision_log.jsonl"
_SPEC_ENVELOPE = ("seq", "ts", "entry_hash", "prev_hash")
_SPEC_EVENT_TYPE = "rates_desk_decision"


def _recompute_entry_hash(row: dict) -> str:
    import hashlib
    payload = {k: v for k, v in row.items() if k not in _SPEC_ENVELOPE}
    canonical = json.dumps(
        {"seq": row.get("seq"), "ts": row.get("ts"), "event_type": _SPEC_EVENT_TYPE,
         "payload": payload, "prev_hash": row.get("prev_hash")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_proof_chain_spec_worked_example_reproduces():
    """The PROOF_CHAIN_SPEC §3 worked-example entry_hash literal must equal the recomputed
    entry_hash of the LIVE row at seq=111 — a skeptic following the spec literally gets a MATCH."""
    import pytest
    if not (_PROOF_SPEC.exists() and _DECISION_LOG.exists()):
        pytest.skip("PROOF_CHAIN_SPEC.md or live decision_log.jsonl not present")
    rows = [json.loads(ln) for ln in _DECISION_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    if len(rows) <= 111:
        pytest.skip("live chain shorter than seq=111 (window evicted) — example not pinnable")
    row111 = rows[111]
    assert row111.get("seq") == 111, "row index 111 is not seq=111 (chain not contiguous)"
    live_hash = _recompute_entry_hash(row111)
    # the recompute must equal the row's own stored hash (the chain is internally valid)
    assert live_hash == row111.get("entry_hash"), "live seq=111 row does not self-verify"
    # and the SPEC's worked-example literal must equal that live hash (no stale example).
    spec = _read(_PROOF_SPEC)
    assert live_hash in spec, (
        f"PROOF_CHAIN_SPEC.md §3 worked example is STALE: it does not cite the live seq=111 "
        f"entry_hash {live_hash} — a skeptic following the spec literally would get a MISMATCH. "
        "Regenerate the worked example from the current chain."
    )
    # the retired/forged stale literal must be GONE from the spec.
    assert "90d939fdfc4b233fe0eaca2c10e39a1bd3aa5236214a4a54ec76b8cfcde6912e" not in spec, (
        "PROOF_CHAIN_SPEC.md still cites the pre-regeneration seq=111 hash (90d939fd…) — "
        "no row carries that hash anymore; remove the stale literal."
    )
