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


# The paper-track GOAL the narrative docs render as `n/30`. It is the denominator of the
# printed fraction, NOT a ceiling on the numerator: the track legitimately runs past its goal.
_TRACK_TARGET_DAYS = 30
_TRACK_DOC_LAG_DAYS = 7


def _track_band(track: int, *, lag_days: int = _TRACK_DOC_LAG_DAYS) -> tuple[int, int]:
    """Sane band `[lo, hi]` for the evidenced track-days number a narrative doc may state.

    `lo` tolerates a doc LAGGING the live counter by up to a week (TEST-2 decouple: the daily
    cycle advances `track` continuously, so a ±1 window flipped the suite red every ~2 days and
    could flip mid-run as the agent rewrote golive_status.json). `hi` forbids OVERSTATING the
    track; the `+1` covers the UTC-rollover moment. The real era guard is the evidenced ANCHOR,
    asserted separately — the number only needs a sanity band.

    `hi` used to carry a `min(_TRACK_TARGET_DAYS, track + 1)` cap, written while the track was
    still shorter than its goal. That cap is INERT below the goal — `min(30, track + 1)` equals
    `track + 1` for every `track <= 29`, so it never once bound there — and WRONG at or above it:
    on 2026-08-24, at `track = 62`, it produced `55 <= n <= 30`, an EMPTY band that NO document
    could satisfy, and the guard went red on every possible value instead of on drift. Dropping
    the cap therefore changes nothing below the goal (pinned by `test_track_band_*` below) and
    un-breaks the guard above it: a track that has passed its goal is a normal state, not drift.
    Same class as a literal date in a fixture (`.claude/rules/deployment.md`) — the assumption
    "the track is shorter than the goal" stopped being true on its own, with no edit to any code.
    """
    return max(0, track - lag_days), track + 1


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

    track_lo, track_hi = _track_band(track)

    # CLAUDE.md was deliberately condensed to lean instructions (env-setup-v3 Фаза 2, commit
    # e50a138c) and no longer carries the volatile live GoLive/track dashboard — those numbers now
    # live in CURRENT_STATE.md (auto-updated operational status) + README.md, which stay guarded here.
    # A condensed root instruction doc must not carry drift-prone live counters; the sibling test
    # `test_claude_md_no_stale_golive_or_app_ref` still forbids CLAUDE.md from showing a STALE count.
    for path in (_CURRENT_STATE_MD, _README_MD):
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
# 8b. The guard ABOVE has to be able to go green. These are its positive controls
#     — hermetic (no data/ needed), so they hold on a clean checkout too, where
#     the committed golive canon (track 13) keeps the live accident invisible.
# ---------------------------------------------------------------------------
def test_track_band_is_never_empty_past_the_goal():
    """Positive control replaying the 2026-08-24 failure: at `track = 62` the old
    `min(30, track + 1)` cap made the band `55 <= n <= 30` — empty, so the guard
    was red on EVERY value including the correct one. It must be satisfiable."""
    for track in (0, 1, 29, 30, 31, 37, 62, 365):
        lo, hi = _track_band(track)
        assert lo <= hi, f"empty band at track={track}: {lo} <= n <= {hi}"
        assert lo <= track <= hi, (
            f"the LIVE track {track} does not fit its own band {lo}..{hi} — the guard "
            f"cannot go green on the truth"
        )


def test_track_band_still_reds_a_wrong_era_number():
    """The other direction — the fix must not become an off-switch (invariant #16).
    At a live track of 62 both the pre-reset drift (`15/30`) and a stale
    goal-reached value (`30/30`) must stay OUT of the band."""
    lo, hi = _track_band(62)
    for wrong in (0, 7, 12, 15, 30, 54, 64, 100):
        assert not (lo <= wrong <= hi), (
            f"wrong-era track value {wrong} slipped into the band {lo}..{hi} at live track 62"
        )
    assert _doc_fraction("трек **62/30** evidenced", 30, lo=lo, hi=hi) == 62
    assert _doc_fraction("трек **12/30** evidenced", 30, lo=lo, hi=hi) is None
    assert _doc_fraction("трек **30/30** evidenced", 30, lo=lo, hi=hi) is None


def test_track_band_unchanged_below_the_goal():
    """Anti-weakening pin: dropping the `min(30, …)` cap must change NOTHING while the
    track is shorter than its goal — that cap never bound there. Byte-identical to the
    pre-fix formula for every such track, so this fix cannot be read as a loosening."""
    for track in range(0, _TRACK_TARGET_DAYS):
        assert _track_band(track) == (max(0, track - 7), min(_TRACK_TARGET_DAYS, track + 1)), (
            f"band changed below the goal at track={track} — that IS a loosening"
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
    """The PROOF_CHAIN_SPEC recipe must REPRODUCE. The published log is a re-based ring-buffer
    mirror, so the row at any fixed seq (and its prev_hash/entry_hash) legitimately drifts as the
    chain grows — pinning a literal in the doc rots every re-base. So the durable guarantee is
    NOT 'the doc cites today's hash' but: the live seq=111 row self-verifies, the spec publishes
    the exact recompute recipe, and the spec tells readers to recompute it themselves (its own
    'don't trust the literal' philosophy). No volatile hash literal is pinned to rot."""
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
    # The durable guarantee (stable across re-bases): the spec publishes the exact
    # recompute recipe and tells readers to recompute it themselves. A pinned literal
    # is NOT required (and must not be present) — the mirror re-chains, so any fixed-seq
    # literal rots. This matches the spec's own "don't trust the literal, recompute it".
    spec = _read(_PROOF_SPEC)
    assert "def recompute_entry_hash" in spec, (
        "PROOF_CHAIN_SPEC.md must publish the recompute recipe (the source of truth)."
    )
    assert _SPEC_EVENT_TYPE in spec, (
        f"PROOF_CHAIN_SPEC.md must state the fixed event_type '{_SPEC_EVENT_TYPE}'."
    )
    assert "recompute it yourself" in spec.lower(), (
        "PROOF_CHAIN_SPEC.md must tell readers to recompute the hash themselves — the "
        "ring-buffer mirror re-chains, so no pinned literal can be trusted (recipe is truth)."
    )
    # No volatile full seq=111 entry_hash literal may be pinned in the worked example —
    # a pinned literal rots every re-base. Guard the specific retired/forged hashes
    # (the pre-regeneration 90d939fd… and the drifted 431e7a76… literal) never reappear.
    for retired in (
        "90d939fdfc4b233fe0eaca2c10e39a1bd3aa5236214a4a54ec76b8cfcde6912e",
        "431e7a7608c6e449208d3e1ce8829acbee6c307f5d7c06d2822d20112d1c7366",
    ):
        assert retired not in spec, (
            f"PROOF_CHAIN_SPEC.md still pins a volatile seq=111 entry_hash literal ({retired[:8]}…) — "
            "remove it; the mirror re-chains so a fixed-seq literal rots. Recipe is the source of truth."
        )


# ---------------------------------------------------------------------------
# Sky/sUSDS: a LIFTED rule must not keep living in the docs as an ACTIVE ban.
#
# Invariant 10 held Sky/sUSDS at 0% allocation until an on-chain GSM Pause Delay
# ≥ 48h was confirmed. The condition WAS confirmed — 2026-08-05, DSPause.delay()
# = 172 800 s = 48.00 h, three independent RPC agreeing — and the owner promoted
# sky_susds WL → T1 (ADR-065, re-confirmed by ADR-126). CLAUDE.md and
# .claude/rules/adapters.md were updated the same day.
#
# The rest of docs/ was not, and the price of that remainder is MEASURED, not
# hypothetical: on 2026-08-16 a triage agent read the stale text as current and
# declared a live line of code a CRITICAL violation. A false critical born of
# prose, not of code.
#
# This guard answers exactly ONE question: **does any LIVING doc still state the
# 0%-until-GSM rule as if it were in force?**
#
# What it deliberately does NOT check (so a green run is not read as more than
# it is):
#   * whether the allocator actually holds sky_susds (that is the book's job);
#   * prose that merely names the gate without the zero ("blocker: GSM < 48h") —
#     it does not assert an allocation ban and reads as history either way;
#   * docs/decisions/** and docs/journal/** — a decision or a journal entry
#     records what was true when written and must never be rewritten.
#
# Two named exception classes, and neither is free:
#   * HISTORY snapshots — must carry a date or a SUPERSEDED marker in their head,
#     verified below. A doc parked here without a dated header FAILS.
#   * OWNER-GATED — the legal template states the rule as a contract term.
#     Changing a term in a legal template is the owner's call, not an agent's
#     doc edit, so it is NAMED here rather than silently swept in with history.
# Both lists SHRINK ONLY: if a listed file no longer states the rule, the test
# fails and tells you to delete the entry — an allowlist nobody prunes becomes
# decoration.
# ---------------------------------------------------------------------------
_SUSDS_SUBJECT = re.compile(r"sky[\s/_-]*susds|susds|\bsky\b", re.IGNORECASE)
_SUSDS_ZERO = re.compile(r"(?<![\d.])0\s*%|HOLD-AT-0|нулев|zero allocation", re.IGNORECASE)
_SUSDS_GATE = re.compile(r"\bGSM\b|pause[\s-]*delay", re.IGNORECASE)
# Any of these, on the line or within ±4 lines, means the text NAMES the lift —
# which is exactly what a correct doc does, so it must not be flagged.
_SUSDS_CURED = re.compile(
    r"ADR-065|lifted|снят|supersed|cured|выполнен|\bmet\b|2026-08-05|05\.08\.2026",
    re.IGNORECASE,
)

# History snapshots: legitimately describe the world on their own date.
_SUSDS_HISTORY_DOCS = {
    "docs/EXECUTION_SAFETY_AUDIT_20260619.md",
    "docs/REPORT_v2_dashboard.md",
    "docs/operator_runbook.md",
    "docs/protocol_research_2026_06.md",
    "docs/research/PROTOCOL_RESEARCH_v469.md",
}
# Owner-gated: a contract term, not a reference sentence. Named with its reason.
# EMPTY since 2026-08-25 (cycle #381): the single entry was the legal template, and
# the owner answered the card that held it (option 2, 10:23Z) — the term is now a
# general governance-precondition rule that names no protocol, so the exception had
# to go. The list stays here as a RATCHET on future entries, not as decoration: an
# empty allowlist makes the test below vacuous, so the teeth moved to
# test_susds_legal_template_is_scanned_like_any_living_doc — a re-add would fail it.
_SUSDS_OWNER_GATED_DOCS: dict[str, str] = {}
_SUSDS_SKIP_DIRS = ("docs/journal/", "docs/decisions/", "docs/ideas/", "docs/rules-draft/")
# A dated or explicitly-superseded header is what makes a history doc readable as
# history. Checked against the head of the file, not asserted by the list.
_DATED_HEADER = re.compile(
    r"20\d\d[-./]\d\d|SUPERSEDED|ИСТОРИЧЕСКИЙ|Retained for history", re.IGNORECASE
)


def _susds_scanned_docs() -> list[Path]:
    """Every doc a session might read as CURRENT guidance."""
    out = [_REPO_ROOT / "CLAUDE.md", _RULES_MD]
    out += sorted((_REPO_ROOT / ".claude" / "rules").glob("*.md"))
    out += sorted(_DOCS.rglob("*.md"))
    return [p for p in out if p.is_file()]


def _susds_active_ban_lines(path: Path) -> list[tuple[int, str]]:
    """Lines asserting the 0%-until-GSM rule with no mention of the lift nearby."""
    lines = _read(path).splitlines()
    found: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        window = "\n".join(lines[max(0, i - 4): i + 5])
        states_ban = bool(_SUSDS_ZERO.search(ln)) and bool(_SUSDS_GATE.search(ln))
        if not states_ban:
            # Same claim split across a sentence: subject + zero on the line, gate nearby.
            states_ban = (
                bool(_SUSDS_SUBJECT.search(ln))
                and bool(_SUSDS_ZERO.search(ln))
                and bool(_SUSDS_GATE.search("\n".join(lines[max(0, i - 3): i + 4])))
            )
        if not states_ban:
            continue
        if _SUSDS_CURED.search(window):
            continue
        found.append((i + 1, ln.strip()))
    return found


def test_susds_zero_rule_is_not_stated_as_active_in_living_docs():
    """No living reference doc may present the lifted Sky/sUSDS ban as in force."""
    offenders: list[str] = []
    for path in _susds_scanned_docs():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith(_SUSDS_SKIP_DIRS):
            continue
        if rel in _SUSDS_HISTORY_DOCS or rel in _SUSDS_OWNER_GATED_DOCS:
            continue
        for lineno, text in _susds_active_ban_lines(path):
            offenders.append(f"{rel}:{lineno}: {text[:160]}")
    assert not offenders, (
        "a LIVING doc still states «Sky/sUSDS = 0 % до GSM Pause Delay ≥ 48h» as an ACTIVE rule.\n"
        "The condition was MET on 2026-08-05 (48.00 h on-chain, 3 independent RPC) and the ban was\n"
        "lifted by ADR-065 — stale prose of exactly this class produced a FALSE CRITICAL finding\n"
        "on 2026-08-16 (a triage agent called a live line of code a violation because it read the\n"
        "doc as current). Fix: state that the condition was met and link ADR-065, as CLAUDE.md does.\n"
        "If the file is a dated snapshot, add it to _SUSDS_HISTORY_DOCS — it must carry a dated header.\n"
        "Offending lines:\n  " + "\n  ".join(offenders)
    )


def test_susds_history_docs_are_readable_as_history_and_still_needed():
    """Each history exception must (a) exist, (b) be dated, (c) still be needed."""
    for rel in sorted(_SUSDS_HISTORY_DOCS):
        path = _REPO_ROOT / rel
        assert path.is_file(), (
            f"{rel} is listed as a Sky/sUSDS history snapshot but does not exist — "
            "delete the entry (the list must shrink, never carry ghosts)."
        )
        head = "\n".join(_read(path).splitlines()[:14])
        assert _DATED_HEADER.search(head), (
            f"{rel} is exempted as a HISTORY snapshot, but its head carries no date and no\n"
            "SUPERSEDED marker — nothing tells a reader it describes a past state. Add the\n"
            "dated header, or fix the text instead of exempting it."
        )
        assert _susds_active_ban_lines(path), (
            f"{rel} no longer states the Sky/sUSDS ban — remove it from _SUSDS_HISTORY_DOCS.\n"
            "An exception nobody prunes turns the allowlist into decoration."
        )


def test_susds_owner_gated_exception_is_named_with_a_reason_and_still_needed():
    """The legal-template exception is a NAMED owner decision, not a quiet sweep."""
    for rel, reason in sorted(_SUSDS_OWNER_GATED_DOCS.items()):
        path = _REPO_ROOT / rel
        assert path.is_file(), f"{rel} listed as owner-gated but missing — delete the entry."
        assert reason.strip(), f"{rel} exempted without a reason — name it or fix it."
        assert _susds_active_ban_lines(path), (
            f"{rel} no longer states the Sky/sUSDS ban — remove it from _SUSDS_OWNER_GATED_DOCS."
        )


# --- cycle #381: the owner answered, so the exception is gone. These two carry the
# --- teeth the now-empty allowlist can no longer carry.
_LEGAL_TEMPLATE = "docs/legal/DOGOVIR_PROSTOGO_TOVARYSTVA_TEMPLATE.md"


def test_susds_legal_template_is_scanned_like_any_living_doc():
    """The template lost its exemption — it must now pass on its own merits.

    Owner decision 2026-08-25 (option 2): the contract term became a general
    governance-precondition rule naming no protocol. Two ways that could rot
    silently, and this test closes both: the file quietly re-enters an exception
    list, or the ban text comes back under the exemption nobody re-reads.
    """
    path = _REPO_ROOT / _LEGAL_TEMPLATE
    assert path.is_file(), f"{_LEGAL_TEMPLATE} vanished — the owner decision has no subject left"
    scanned = {p.relative_to(_REPO_ROOT).as_posix() for p in _susds_scanned_docs()}
    assert _LEGAL_TEMPLATE in scanned, (
        f"{_LEGAL_TEMPLATE} is no longer in the scanned corpus — it would be green by "
        "construction, exactly the blindness the owner-gated exception used to make VISIBLE"
    )
    assert _LEGAL_TEMPLATE not in _SUSDS_OWNER_GATED_DOCS, (
        f"{_LEGAL_TEMPLATE} was put back into _SUSDS_OWNER_GATED_DOCS. The owner ANSWERED that "
        "card on 2026-08-25 (option 2) — re-exempting it re-opens a decided question silently. "
        "If the contract term genuinely changed again, that is a NEW owner-decision card."
    )
    assert _LEGAL_TEMPLATE not in _SUSDS_HISTORY_DOCS, (
        f"{_LEGAL_TEMPLATE} is a LIVE contract template, not a dated snapshot — it must not be "
        "parked in the history allowlist"
    )
    offenders = _susds_active_ban_lines(path)
    assert not offenders, (
        f"{_LEGAL_TEMPLATE} states the lifted Sky/sUSDS ban as an ACTIVE contract term again: "
        f"{offenders}. This template goes to a real person; per the owner's decision the clause "
        "must be a general governance-precondition rule that names no protocol."
    )


def test_susds_detector_accepts_the_general_governance_rule(tmp_path):
    """Negative control on the EXACT replacement wording the owner chose.

    Without it, a detector tightened later could start flagging the very sentence
    the owner approved, and the next session would learn to disable the guard
    instead of fixing it.
    """
    probe = tmp_path / "dogovir.md"
    probe.write_text(
        "- APY нової позиції: 1%–30% (позиції поза діапазоном — заблоковані)\n"
        "- Протокол, безпека якого спирається на governance-передумову (затримка паузи, "
        "таймлок тощо),\n"
        "  допускається до портфеля **лише після підтвердження цієї передумови on-chain**; до\n"
        "  підтвердження його частка — 0%\n",
        encoding="utf-8",
    )
    assert not _susds_active_ban_lines(probe), (
        "the owner-approved general rule is flagged as an active Sky/sUSDS ban — the guard "
        "would nag forever on the wording the owner himself chose"
    )


# Verbatim pre-fix snippets from origin/main before cycle #380 — one per doc that
# had to be fixed. Kept as multi-line blocks because two of them state the ban
# across a sentence break, which is exactly the shape a line-only detector misses.
_SUSDS_PRE_FIX_SNIPPETS = {
    "SOURCE_INTEGRATION_GUIDE": "- **Sky/sUSDS stays at 0% allocation** until on-chain GSM Pause Delay ≥ 48h",
    "DATA_SOURCES_REGISTRY": "| `sky_susds` | Sky (MakerDAO) | sUSDS | 0% current | monitor only | GSM Pause Delay rule |",
    "RISK_MANAGEMENT_POLICY": (
        "## 6. Sky/sUSDS Special Rule\n\n"
        "Sky protocol (sUSDS) receives **0% allocation** until:\n\n"
        "- On-chain GSM Pause Delay is confirmed ≥ 48 hours\n"
    ),
    "44_research": (
        "- **Main risk.** Mechanism change; contract risk. Note the SPA invariant: "
        "**Sky/sUSDS = 0%** until GSM Pause Delay ≥ 48h confirmed on-chain.\n"
    ),
    "ARCH_EVOLUTION_ADR_018": (
        "### ADR-018: Sky/sUSDS at 0% Until On-Chain GSM Pause Delay ≥48h\n\n"
        "**Status:** Accepted\n\n"
        "**Decision:** Sky/sUSDS allocation remains 0% until on-chain confirmation of "
        "GSM (Governance Security Module) Pause Delay ≥48 hours.\n"
    ),
    # Cycle #381 (owner option 2, 2026-08-25): verbatim line 354 of the legal
    # template before the reformulation. It was the LAST owner-gated exception —
    # if the detector goes blind on it, emptying that allowlist means nothing.
    "DOGOVIR_TEMPLATE": "- Sky/sUSDS: **0% до підтвердження GSM Pause Delay ≥ 48h on-chain**",
    "protocol_research_ru": (
        "**Tier Decision: T1**\n"
        "Текущий статус: **0% аллокации** до подтверждения on-chain GSM Pause Delay ≥ 48h\n"
    ),
}


def test_susds_detector_fires_on_the_pre_fix_text(tmp_path):
    """Positive control: the REAL helper, on the REAL pre-fix text of each doc.

    Every snippet is verbatim from origin/main before cycle #380. The helper —
    not a re-implementation of its regexes — must flag each one; if it goes blind
    the green run above would mean nothing.
    """
    for name, snippet in _SUSDS_PRE_FIX_SNIPPETS.items():
        probe = tmp_path / f"{name}.md"
        probe.write_text(snippet, encoding="utf-8")
        assert _susds_active_ban_lines(probe), (
            f"detector went blind on the pre-fix text of {name} — it would no longer catch the "
            "stale-ban class that produced a FALSE CRITICAL on 2026-08-16:\n" + snippet
        )


def test_susds_detector_accepts_the_fixed_text(tmp_path):
    """Negative control: the text as it stands AFTER this fix must pass.

    Without this, a detector that flags everything would look just as green, and
    the guard would push docs to delete history instead of dating it.
    """
    fixed = (
        "- **Sky/sUSDS: the 0% rule is LIFTED** — the on-chain GSM Pause Delay ≥ 48h\n"
        "  precondition was met on 2026-08-05 (48.00 h, 3 independent RPC) and `sky_susds`\n"
        "  moved WL → T1; the share is decided by the allocator (ADR-065)\n"
    )
    probe = tmp_path / "fixed.md"
    probe.write_text(fixed, encoding="utf-8")
    assert not _susds_active_ban_lines(probe), (
        "the corrected wording is flagged as an active ban — the guard would nag forever "
        "and teach the next session to disable it"
    )


def test_susds_guard_scans_the_docs_it_claims_to_scan(tmp_path):
    """A scanner that reaches nothing is green by construction (audit lesson:
    a guard whose corpus is empty answers 'ok' about a world it never read)."""
    scanned = {p.relative_to(_REPO_ROOT).as_posix() for p in _susds_scanned_docs()}
    for must in ("CLAUDE.md", "docs/RISK_MANAGEMENT_POLICY.md", "docs/SOURCE_INTEGRATION_GUIDE.md"):
        assert must in scanned, f"{must} is not in the scanned corpus — the guard cannot see it"
    assert len(scanned) > 50, f"scanned corpus suspiciously small ({len(scanned)} docs)"


def test_susds_canonical_rule_docs_state_the_lift():
    """CLAUDE.md and the adapters rule are what every session reads first — they
    must carry the lift, not merely stop carrying the ban."""
    for rel in ("CLAUDE.md", ".claude/rules/adapters.md"):
        text = _read(_REPO_ROOT / rel)
        assert re.search(r"gsm|pause[\s-]*delay|DSPause", text, re.IGNORECASE), (
            f"{rel} no longer mentions the GSM condition at all — the lift is only honest if the "
            "condition it cleared is still named."
        )
        assert re.search(r"выполнено|снят|ADR-065|2026-08-05|05\.08\.2026", text), (
            f"{rel} names the GSM condition but never says it was MET (2026-08-05, ADR-065)."
        )
