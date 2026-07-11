"""Owner-only go-live blocker tracker  [Q1-9].

A deterministic, stdlib-only procurement tracker for the FOUR go-live gates the
*code cannot satisfy* — the owner must procure them out-of-band:

  1. ``custody``     — Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010).
  2. ``audit``       — external security audit of the execution path signed off.
  3. ``legal``       — entity + disclosure / no-guarantee framing reviewed by counsel.
  4. ``track_days``  — ≥30 evidenced honest paper-track days (the go-live gate).

Why this exists (vs. ``readiness_audit.py``): that module answers *"is the code
paper-safe?"* and lumps these into a flat ``live_blockers`` string list. This one
answers *"what must the OWNER go buy/sign/wait-for, and how far along is each?"* —
so procurement can run **in parallel** with the remaining track days rather than
starting only after day 30.

HONESTY INVARIANTS (hard):
  * The code NEVER marks ``custody`` / ``audit`` / ``legal`` **satisfied** on its
    own. Those flip to ``satisfied`` only when the OWNER asserts it — with evidence —
    in ``data/owner_blockers_evidence.json``. No evidence ⇒ ``open``. We never
    fabricate procurement progress.
  * ``track_days`` IS derivable honestly (from ``data/golive_status.json``), so the
    code auto-derives its status; it is the one gate that closes with time, not money.
  * ``custody`` is auto-derived only in the SAFE direction: a signer key present in
    env ⇒ still not "satisfied" here (that needs the Safe + owner assertion), but its
    absence is reported truthfully as ``open`` (paper-safe).
  * Deterministic, fail-closed, atomic writes only, no network, no keys, no LLM.

The owner drops progress into ``data/owner_blockers_evidence.json``, e.g.::

    {
      "audit": {"status": "in_progress", "note": "engaged Firm X 2026-07-08",
                "evidence_url": "https://..."},
      "legal": {"status": "open"}
    }

Only ``status`` values in {open, in_progress, satisfied} are honoured; anything
else is coerced to ``open`` (fail-closed). ``track_days`` and ``custody`` ignore
owner overrides for their auto-derived facts (you can't sign your way past the
track gate).

Run standalone::

    python3 -m spa_core.execution.owner_blockers          # human summary + writes JSON
    python3 -m spa_core.execution.owner_blockers --json    # machine-readable to stdout
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_save

# Reuse the SAME signer-env definition the safety audit uses — one source of truth.
from spa_core.execution.readiness_audit import SIGNER_KEY_ENVS

# ── Paths ────────────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[2]
_DATA = _REPO / "data"
_REPORT = "owner_blockers.json"
_EVIDENCE = "owner_blockers_evidence.json"

_VALID_STATUS = ("open", "in_progress", "satisfied")

# Canonical gate catalogue — stable documented facts (ADR-010 + the go-live gate),
# NOT fabricated numbers. AI holds no keys and is never a signer.
_GATES = (
    {
        "id": "custody",
        "what": "Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010) — "
                "AI holds no keys and is never a signer",
        "owner_action": "Deploy the multisig, provision the 3 signer keys off-host, "
                        "then assert in owner_blockers_evidence.json",
        "auto": "custody",          # auto-derived (safe direction only)
    },
    {
        "id": "audit",
        "what": "External security audit of the execution path signed off",
        "owner_action": "Engage an auditor; on sign-off record the report link in "
                        "owner_blockers_evidence.json",
        "auto": None,               # owner-asserted only
    },
    {
        "id": "legal",
        "what": "Entity + disclosure / no-guarantee framing reviewed by counsel "
                "before any external capital",
        "owner_action": "Counsel review of entity + disclosures; record sign-off in "
                        "owner_blockers_evidence.json",
        "auto": None,               # owner-asserted only
    },
    {
        "id": "track_days",
        "what": "≥30 evidenced honest paper-track days (the go-live gate; "
                "time-gated, nothing to fix in code)",
        "owner_action": "None — wait. The evidenced track accrues one honest day at a "
                        "time; no procurement closes this.",
        "auto": "track_days",       # fully auto-derived from golive_status.json
    },
)


def _read_json(name: str, default: Any = None) -> Any:
    try:
        return json.loads((_DATA / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — fail-closed: absent/corrupt ⇒ default
        return default


def _coerce_status(raw: Any) -> str:
    """Fail-closed status coercion: anything not in the whitelist ⇒ 'open'."""
    s = str(raw).strip().lower() if raw is not None else "open"
    return s if s in _VALID_STATUS else "open"


def _derive_custody(_golive: dict) -> tuple[str, str]:
    """Custody auto-derivation — SAFE direction only.

    A signer key in env means a key is *configured* (unsafe for paper), but never
    that custody is *satisfied* (that needs the deployed Safe + owner assertion).
    Absence ⇒ honestly ``open`` / paper-safe. Returns (auto_status, detail)."""
    signer_present = any(os.environ.get(k) for k in SIGNER_KEY_ENVS)
    if signer_present:
        return "open", "signer key present in env — custody still needs the Safe + owner sign-off"
    return "open", "no signer key in env (paper-safe) — custody not yet provisioned"


def _derive_track_days(golive: dict) -> tuple[str, str, dict]:
    """track_days auto-derivation from the canonical go-live gate. Honest & time-only."""
    needed = int(golive.get("min_track_days", 30) or 30)
    evidenced = golive.get("real_track_days")
    if evidenced is None:
        return "open", "evidenced track-day count unavailable (golive_status.json absent)", {
            "evidenced_days": None, "days_needed": needed, "days_remaining": needed,
        }
    evidenced = int(evidenced)
    remaining = max(0, needed - evidenced)
    if evidenced >= needed:
        status = "satisfied"
        detail = f"{evidenced}/{needed} evidenced track-days — gate met"
    elif evidenced > 0:
        status = "in_progress"
        detail = f"{evidenced}/{needed} evidenced track-days ({remaining} remaining)"
    else:
        status = "open"
        detail = f"0/{needed} evidenced track-days"
    return status, detail, {
        "evidenced_days": evidenced, "days_needed": needed, "days_remaining": remaining,
    }


def build(data_dir: str | os.PathLike | None = None) -> dict:
    """Deterministically assemble the owner-blocker report. Pure read → derive → dict."""
    global _DATA
    if data_dir is not None:
        _DATA = Path(data_dir)

    golive = _read_json("golive_status.json", {}) or {}
    evidence = _read_json(_EVIDENCE, {}) or {}
    if not isinstance(evidence, dict):
        evidence = {}

    gates: list[dict] = []
    for spec in _GATES:
        gid = spec["id"]
        ev = evidence.get(gid) if isinstance(evidence.get(gid), dict) else {}
        owner_status = _coerce_status(ev.get("status"))
        note = str(ev.get("note", "")).strip() or None
        evidence_url = str(ev.get("evidence_url", "")).strip() or None

        extra: dict = {}
        if spec["auto"] == "track_days":
            # Fully auto — owner cannot override the track gate.
            status, detail, extra = _derive_track_days(golive)
            source = "auto:golive_status.json"
        elif spec["auto"] == "custody":
            auto_status, detail = _derive_custody(golive)
            # Owner may assert 'satisfied'/'in_progress' (Safe deployed) ABOVE the auto
            # floor, but code never fabricates it. Take the more-advanced of the two,
            # and if owner asserts satisfied, keep their note as the evidence.
            status = owner_status if _VALID_STATUS.index(owner_status) > _VALID_STATUS.index(auto_status) else auto_status
            source = "owner-asserted" if status == owner_status and owner_status != auto_status else "auto:env"
        else:
            # Owner-asserted only (audit / legal). No evidence ⇒ open.
            status = owner_status
            detail = note or "awaiting owner procurement"
            source = "owner-asserted" if status != "open" else "open (no owner evidence)"

        gate = {
            "id": gid,
            "what": spec["what"],
            "owner_action": spec["owner_action"],
            "status": status,
            "detail": detail,
            "source": source,
        }
        if note:
            gate["note"] = note
        if evidence_url:
            gate["evidence_url"] = evidence_url
        gate.update(extra)
        gates.append(gate)

    open_count = sum(1 for g in gates if g["status"] != "satisfied")
    return {
        "report": "owner_only_blockers",
        "version": "v1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deterministic": True,
        "llm_forbidden": True,
        "note": "Owner-only go-live gates the CODE cannot satisfy. Code never fabricates "
                "procurement progress: audit/legal flip to satisfied only on owner-asserted "
                "evidence; track_days is time-derived; custody is reported in the safe direction.",
        "gates": gates,
        "open_count": open_count,
        "total": len(gates),
        "all_satisfied": open_count == 0,
        "evidence_file": f"data/{_EVIDENCE}",
    }


def write(data_dir: str | os.PathLike | None = None) -> dict:
    """Build + atomically persist to data/owner_blockers.json. Returns the report."""
    report = build(data_dir)
    atomic_save(report, str(_DATA / _REPORT))
    return report


def _print_human(report: dict) -> None:
    print("=" * 64)
    print("SPA OWNER-ONLY GO-LIVE BLOCKERS")
    print("=" * 64)
    print(f"generated_at : {report['generated_at']}")
    print(f"open / total : {report['open_count']} / {report['total']}")
    print("-" * 64)
    icon = {"open": "[  ]", "in_progress": "[~ ]", "satisfied": "[OK]"}
    for g in report["gates"]:
        print(f"  {icon.get(g['status'], '[  ]')} {g['id']}: {g['status']} — {g['detail']}")
    print("-" * 64)
    print("Owner drops progress into data/owner_blockers_evidence.json "
          "(audit/legal/custody). track_days is time-gated.")
    print("=" * 64)


def main(argv: list[str] | None = None) -> int:
    import sys
    args = sys.argv[1:] if argv is None else argv
    report = write()
    if "--json" in args:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
