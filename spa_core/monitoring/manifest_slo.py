# LLM_FORBIDDEN
"""
ONE reader of the fleet constitution's freshness SLOs — one number, one place.

WHY THIS MODULE EXISTS (#342, 2026-08-22). The expiry of `data/investment_os/chief_investment.json`
was written down THREE times: `architecture/manifest.json` (`slo_hours`, the constitution),
`investment_os.health` (literal `30 * 3600`) and `monitoring.artifact_freshness` (literal `30.0`).
Both literals carried the comment "MEASURED, not guessed" — and both were snapshots copied by hand
from a schedule, so neither could follow it. When owner decision ADR-104 changed the chief's cadence
(`86400s → 300s`) and its SLO (`26h → 1h`), the constitution moved and the two copies did not:

    architecture_conformance (B2)  — WARN, "возраст 18.8ч > SLO 1ч"   (reads the constitution)
    investment_os.health           — "house view FRESH, 12.4h of 30h" (read its own literal)

Three guards, one file, verdicts 30x apart — and the one that testified FOR health is the one the
orchestrator reads FIRST every cycle. The fix is not a better literal; it is removing the literal's
AUTHORITY. Hence a single reader, imported by every guard that judges freshness, and a `source`
that travels with the number so a reader can always tell a budget that was READ from one that was
fallen back to.

Deterministic · stdlib · read-only · ADVISORY. Gates nothing; moves no capital.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The constitution of the fleet — the ONE place a cadence/SLO is decided
#: (`CLAUDE.md` inv. 13: only files in git are the source of truth).
MANIFEST_PATH: Path = _REPO_ROOT / "architecture" / "manifest.json"


def slo_hours_by_path(manifest_path: Optional[Path] = None) -> tuple[dict[str, float], str]:
    """Read `{repo-relative artifact path: slo_hours}` for every ACTIVE artifact.

    Returns ``(mapping, why)``. ``why`` is empty when the constitution was read; otherwise it
    NAMES what went wrong, so a caller can say "not measured" out loud instead of silently
    presenting a fallback as if it had been measured.

    fail-SAFE (never raises — guards that import this must not crash on a bad file) and
    fail-CLOSED in what it CLAIMS: an unreadable manifest yields an EMPTY mapping plus a reason,
    never a plausible-looking number.

    An artifact whose ``status`` is not ``active`` is skipped on purpose: a retired artifact's
    SLO is not in force, and letting it bind a live guard would be the same class of defect this
    module exists to close.
    """
    p = Path(manifest_path) if manifest_path is not None else MANIFEST_PATH
    out: dict[str, float] = {}
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError, TypeError) as e:
        return {}, f"{p.name} not read ({type(e).__name__}) — SLO NOT measured"
    try:
        for art in doc.get("artifacts", []) or []:
            if art.get("status") != "active":
                continue
            path = str(art.get("path") or "")
            hours = art.get("slo_hours")
            if not path or not hours:
                continue
            out[path] = float(hours)
    except (AttributeError, TypeError, ValueError) as e:
        return {}, f"{p.name} unreadable shape ({type(e).__name__}) — SLO NOT measured"
    return out, ""
