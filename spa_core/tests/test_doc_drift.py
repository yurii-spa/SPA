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

import re
from pathlib import Path

from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "docs"

CANONICAL = _DOCS / "DISASTER_RECOVERY.md"

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
