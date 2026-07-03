"""
spa_core/audit/ots_anchor.py — EXTERNAL timestamp anchoring (OpenTimestamps / Bitcoin).

THE PROVENANCE GAP this closes (ADR-YL-010): the SPA proof chain (`decision_log.jsonl` +
`anchors.jsonl`) is SELF-HOSTED. Every hash and every anchor is written by a single operator,
so an external skeptic can object: "you could regenerate the whole chain backdated." Internal
hashes prove INTEGRITY (nothing was silently rewritten *relative to a recorded checkpoint*) but
NOT EXISTENCE-IN-TIME (that the data existed at a claimed date), because the checkpoints are ours.

THE FIX — an APPEND-ONLY layer ON TOP of the existing chain (the chain is NEVER mutated): at each
daily head-checkpoint, submit the chain's `head_hash` to the OpenTimestamps calendar network, which
aggregates it into a Bitcoin transaction. The resulting `.ots` proof lets ANYONE independently prove
(with their own `ots verify`, no SPA code, no trust in us) that the head_hash existed no later than a
specific Bitcoin block's time. Bitcoin's timestamp is the external clock we do not control.

WHY NO PRIVATE KEYS (confirmed — see ADR-YL-010): OpenTimestamps is a *proof of existence*, not a
signature. It commits the digest into a public Merkle tree that the calendars aggregate into an
on-chain Bitcoin transaction; verification walks the Merkle path to the block header. There is NO
signing, NO key, NO fund movement anywhere in this module — it only reads a hash and writes proof
files. This preserves the SPA invariant "no private keys / seed phrases / signing".

DESIGN (offline-first, stdlib-only codebase):
  • We do NOT import any third-party library. We shell out to the reference `ots`
    (opentimestamps-client) binary — an EXTERNAL system tool, like `git` or `curl`. Resolve it via
    $SPA_OTS_BIN or PATH. If it is absent, we DEGRADE GRACEFULLY: the head digest file and the ledger
    entry are still written (status "client_unavailable"), so the head's existence is at least
    recorded append-only and can be OTS-stamped later — and the digest file, committed to the PUBLIC
    GitHub repo by the normal push, already gives a weaker independent timestamp (GitHub's commit
    clock on a public repo). The Bitcoin-grade proof is filled in once the client is installed.
  • APPEND-ONLY: `proofs/ots/ots_anchors.jsonl` is a monotonic ledger; each stamp appends one line
    (atomic tmp-rewrite + os.replace). Idempotent per head_hash: stamping an already-stamped head is a
    no-op. Upgrades (pending→Bitcoin-confirmed) append a NEW `ots_upgrade` event — we never rewrite a
    prior ledger line.
  • The stamped file is `proofs/ots/<head_hash>.head` whose content is EXACTLY the head_hash (64 hex
    + newline). So a verifier recreates it trivially and runs `ots verify <head_hash>.head.ots`.

HONEST SCOPE: OTS proofs begin at the ADOPTION date — history BEFORE first stamp is not
Bitcoin-anchored. But the immediate retro-anchor of today's head proves "everything in the chain that
exists today existed no later than today" (a forward-only guarantee from here on).

PURE provenance plumbing; stdlib only; LLM-FORBIDDEN; no keys; no fund movement; never mutates the
existing proof chain.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parents[2]
_OTS_DIR = _ROOT / "proofs" / "ots"
_OTS_LEDGER = _OTS_DIR / "ots_anchors.jsonl"

STAMP_EVENT = "ots_stamp"
UPGRADE_EVENT = "ots_upgrade"

# Adoption date recorded so the /verify caveat + tests can assert the honest scope boundary.
ADOPTION_DATE = "2026-07-03"


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _relpath(p: Path) -> str:
    """Path relative to the repo root when under it, else the plain string (test tmp dirs)."""
    try:
        return str(p.relative_to(_ROOT))
    except ValueError:
        return str(p)


def resolve_ots_bin() -> Optional[str]:
    """The external `ots` (opentimestamps-client) binary, or None if unavailable.

    Resolution: $SPA_OTS_BIN (absolute path, e.g. an isolated venv), then PATH. We NEVER import
    opentimestamps into this codebase (stdlib-only invariant) — the client is an external tool.
    """
    env = os.environ.get("SPA_OTS_BIN")
    if env and Path(env).exists() and os.access(env, os.X_OK):
        return env
    return shutil.which("ots")


def _ots_version(ots_bin: str) -> Optional[str]:
    try:
        out = subprocess.run(
            [ots_bin, "--version"], capture_output=True, text=True, timeout=30
        )
        return (out.stdout or out.stderr or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _read_ledger(path: Path = _OTS_LEDGER) -> List[dict]:
    """Append-only ledger; [] if absent. fail-CLOSED: skip corrupt lines (never crash a stamp)."""
    if not path.exists():
        return []
    out: List[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, TypeError):
            continue
    return out


def _atomic_append_line(path: Path, line: str) -> None:
    """Append one line via tmp-rewrite + os.replace (same-dir tmp → no EXDEV; crash never tears a line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(existing + line + "\n")
    os.replace(tmp, path)


def already_stamped(head_hash: str, ledger_path: Path = _OTS_LEDGER) -> bool:
    """True if a STAMP event for this head_hash already exists (idempotency guard)."""
    return any(
        e.get("event") == STAMP_EVENT and e.get("head_hash") == head_hash
        for e in _read_ledger(ledger_path)
    )


def _write_digest_file(head_hash: str, ots_dir: Path) -> Path:
    """Write `<head_hash>.head` whose content is EXACTLY the head_hash (deterministic, re-creatable)."""
    ots_dir.mkdir(parents=True, exist_ok=True)
    digest_file = ots_dir / f"{head_hash}.head"
    # Content is exactly the head hex + newline — a verifier reproduces it trivially.
    digest_file.write_text(head_hash + "\n")
    return digest_file


def stamp_head(
    head_hash: str,
    chain_length: Optional[int] = None,
    source: str = "rates_desk",
    *,
    ots_dir: Path = _OTS_DIR,
    ledger_path: Path = _OTS_LEDGER,
    ots_bin: Optional[str] = None,
    _run=subprocess.run,
) -> dict:
    """Create (or record-pending) an OpenTimestamps proof for a chain head_hash.

    Idempotent per head_hash. Writes the digest file + one append-only ledger line. Runs `ots stamp`
    if the client is available (status "pending", proof lands in Bitcoin over ~hours); otherwise records
    status "client_unavailable" (digest file still written → owner stamps later; public-repo commit of
    the digest already gives a weaker external timestamp). Returns the ledger entry.

    `_run` and `ots_bin` are injectable for tests (no network in the suite).
    """
    if not head_hash or len(head_hash) < 32:
        raise ValueError("head_hash must be a non-trivial hex digest")

    if already_stamped(head_hash, ledger_path):
        # Idempotent: return the existing entry, do nothing.
        for e in _read_ledger(ledger_path):
            if e.get("event") == STAMP_EVENT and e.get("head_hash") == head_hash:
                return {**e, "idempotent_noop": True}

    digest_file = _write_digest_file(head_hash, ots_dir)
    ots_bin = ots_bin if ots_bin is not None else resolve_ots_bin()

    status = "client_unavailable"
    ots_file = None
    client = None
    if ots_bin:
        client = _ots_version(ots_bin) or os.path.basename(ots_bin)
        try:
            proc = _run(
                [ots_bin, "stamp", str(digest_file)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            candidate = Path(str(digest_file) + ".ots")
            if getattr(proc, "returncode", 1) == 0 and candidate.exists():
                status = "pending"
                ots_file = _relpath(candidate)
            else:
                status = "stamp_failed"
        except (OSError, subprocess.SubprocessError):
            status = "stamp_failed"

    entry = {
        "event": STAMP_EVENT,
        "ts": _utcnow_iso(),
        "head_hash": head_hash,
        "chain_length": chain_length,
        "source": source,
        "digest_file": _relpath(digest_file),
        "ots_file": ots_file,
        "status": status,
        "ots_client": client,
        "adoption_date": ADOPTION_DATE,
    }
    _atomic_append_line(ledger_path, json.dumps(entry, sort_keys=True))
    return entry


def upgrade_pending(
    *,
    ots_dir: Path = _OTS_DIR,
    ledger_path: Path = _OTS_LEDGER,
    ots_bin: Optional[str] = None,
    _run=subprocess.run,
) -> dict:
    """Run `ots upgrade` on pending proofs; append an `ots_upgrade` event when one confirms.

    Never mutates prior ledger lines (append-only). The `.ots` file itself is updated in place by the
    client (expected OTS behaviour — it is an external artifact, not our hash chain). Returns a summary.
    """
    ots_bin = ots_bin if ots_bin is not None else resolve_ots_bin()
    ledger = _read_ledger(ledger_path)
    # Heads currently pending, minus those already recorded confirmed.
    confirmed = {e.get("head_hash") for e in ledger if e.get("event") == UPGRADE_EVENT}
    pending = [
        e for e in ledger
        if e.get("event") == STAMP_EVENT and e.get("status") == "pending"
        and e.get("head_hash") not in confirmed and e.get("ots_file")
    ]
    upgraded = 0
    checked = 0
    if ots_bin:
        for e in pending:
            ots_path = _ROOT / e["ots_file"]
            if not ots_path.exists():
                continue
            checked += 1
            try:
                proc = _run(
                    [ots_bin, "--no-cache", "upgrade", str(ots_path)],
                    capture_output=True, text=True, timeout=120,
                )
                blob = ((getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")).lower()
                # ots prints "Success! Bitcoin block ..." (or "already ... complete") once confirmed.
                if "bitcoin block" in blob or "success" in blob or "complete" in blob:
                    _atomic_append_line(ledger_path, json.dumps({
                        "event": UPGRADE_EVENT,
                        "ts": _utcnow_iso(),
                        "head_hash": e["head_hash"],
                        "ots_file": e["ots_file"],
                        "status": "confirmed",
                        "detail": blob.strip()[:200],
                    }, sort_keys=True))
                    upgraded += 1
            except (OSError, subprocess.SubprocessError):
                continue
    return {"pending_checked": checked, "upgraded": upgraded, "ots_client": bool(ots_bin)}


def latest_head() -> tuple[Optional[str], Optional[int]]:
    """Current public rates-desk chain head (head_hash, chain_length), re-derived as a third party would.

    Reuses the SAME verifier the anchors ledger uses (no divergent head logic).
    """
    try:
        from spa_core.strategy_lab.rates_desk import anchors as _a
        return _a._decision_log_head()
    except Exception:
        return None, None


def stamp_latest_head(source: str = "rates_desk") -> dict:
    """Convenience: resolve the current chain head and stamp it (the daily-agent entrypoint)."""
    head_hash, chain_length = latest_head()
    if not head_hash:
        return {"status": "no_head", "head_hash": None}
    return stamp_head(head_hash, chain_length, source=source)
