#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.audit.book_commitments — commit-reveal of the daily BOOK ALLOCATION decision
(inbox «Целостность трека SPA», task 4; practice transferred from earn-defi
``earn_defi/commit_reveal.py``, 2026-09-08).

WHY
===
The main book had no forward commitment: a reviewer could verify that the equity curve was not
edited after the fact (equity chain, ADR-268 archive), but not that the ALLOCATION the cycle
decided on day D was fixed BEFORE the (virtual) execution and the day's yield were known. The
rates desk has anchors; the book had nothing. Commit-reveal closes that: at decision time only a
SHA-256 of the decision package is published; the package itself is revealed one cycle later, and
anyone recomputes the hash with the public ``scripts/verify_spa.py`` recipe.

WHAT
====
Package (private until the reveal)::

    {schema_version, cycle_date, snapshot_id, target_positions{pool: usd rounded 2}, action,
     decision_source, risk_policy_version, salt}

``commitment_hash = sha256(canonical_json(package))`` with the ONE canonical-JSON rule of
``docs/PROOF_CHAIN_SPEC.md`` §2 (``sort_keys=True, separators=(",", ":"), ensure_ascii=False``).
The salt (32 random bytes, hex) keeps the small target space from being brute-forced from the
hash alone — it also means this layer attests the engine and is NOT replayable by design
(``replay_equity`` ignores it).

Two files, both append-only, both rewritten atomically (tmp + ``os.replace``):

* ``data/book_commit_packages.jsonl`` — PRIVATE. One row per cycle date: the package + its hash.
  Never published before its reveal; not a product (``INTERNAL_WRITES`` of the cycle).
* ``data/book_commitments.jsonl`` — PUBLIC trail, hash-chained with the canonical
  ``compute_entry_hash`` of ``spa_core.audit.hash_chain`` (``seq, ts, event_type, payload,
  prev_hash``). Event types: ``book_commit`` (payload = date + hash, nothing else) and
  ``book_reveal`` (payload = date + hash + the package). Verified standalone by
  ``scripts/verify_spa.py`` (surface J).

Publication goes through the single sanctioned Telegram path — ``push_policy.enqueue_digest``
(the morning digest) — never a new poller and never a Tier-1 push. The digest section renders the
``event_key`` (older formatter) or the body (newer one), so the hash is carried in BOTH.

RULES
=====
Idempotent per cycle date (a re-run of the cycle does not re-commit and never re-salts); reveal
only when ``REVEAL_DELAY_DAYS`` have elapsed; never raises into the cycle (the caller wraps it);
stdlib only; no LLM; history is never rewritten.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.audit.hash_chain import compute_entry_hash

log = logging.getLogger("spa.audit.book_commitments")

PUBLIC_FILENAME = "book_commitments.jsonl"
PRIVATE_FILENAME = "book_commit_packages.jsonl"
EVENT_COMMIT = "book_commit"
EVENT_REVEAL = "book_reveal"
EVENT_TYPES = (EVENT_COMMIT, EVENT_REVEAL)
GENESIS = "0" * 64
SCHEMA_VERSION = "1.0"
RISK_POLICY_VERSION = "v1.0"
SALT_BYTES = 32

#: Reveal delay in CYCLE DAYS. The package for cycle date D is revealed by the first cycle whose
#: date is >= D + REVEAL_DELAY_DAYS (i.e. the next daily cycle). This is a publication cadence,
#: not a risk threshold: it exists so the hash is on record strictly BEFORE the day's yield and
#: the next day's decision are known. Changing it does not touch RiskPolicy or the kill-switch.
REVEAL_DELAY_DAYS = 1

#: After this many days without a reveal the monitor calls the commitment OVERDUE (advisory).
OVERDUE_AFTER_DAYS = 2

Publisher = Callable[[str, str, str, str], dict]


# ── canonical hashing (PROOF_CHAIN_SPEC §2 — reused, not re-invented) ───────────────────────────
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def commitment_hash(package: dict) -> str:
    return hashlib.sha256(canonical_json(package).encode("utf-8")).hexdigest()


def verify_package(package: dict, expected_hash: str) -> bool:
    try:
        return commitment_hash(package) == str(expected_hash)
    except (TypeError, ValueError):
        return False


def build_package(
    *,
    cycle_date: str,
    snapshot_id: Optional[str],
    target_positions: dict,
    decision_source: Any,
    action: str,
    risk_policy_version: str = RISK_POLICY_VERSION,
    salt: Optional[str] = None,
) -> dict:
    """The decision package. ``target_positions`` is the FINAL compliant book the cycle would
    adopt (pool → USD, rounded to cents); ``action`` is ``rebalance``/``hold`` — what the cycle
    decided to do with it BEFORE the virtual execution branch ran."""
    positions = {}
    for k, v in (target_positions or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            positions[str(k)] = round(float(v), 2)
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_date": str(cycle_date),
        "snapshot_id": (str(snapshot_id) if snapshot_id else None),
        "target_positions": positions,
        "action": str(action),
        "decision_source": (str(decision_source) if decision_source is not None else None),
        "risk_policy_version": str(risk_policy_version),
        "salt": salt or secrets.token_hex(SALT_BYTES),
    }


# ── files ─────────────────────────────────────────────────────────────────────────────────────
def public_path(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / PUBLIC_FILENAME


def private_path(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / PRIVATE_FILENAME


def _read_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            out.append({"_corrupt": line[:120]})
            continue
        out.append(row if isinstance(row, dict) else {"_corrupt": line[:120]})
    return out


def _atomic_write_lines(p: Path, lines: list[str], prefix: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_trail(data_dir: str | os.PathLike) -> list[dict]:
    """The PUBLIC chained trail (commit + reveal entries, seq order as stored)."""
    return _read_jsonl(public_path(data_dir))


def read_packages(data_dir: str | os.PathLike) -> list[dict]:
    """The PRIVATE packages ({cycle_date, package, commitment_hash, created_at})."""
    return _read_jsonl(private_path(data_dir))


def _append_private(data_dir: str | os.PathLike, row: dict) -> None:
    rows = [r for r in read_packages(data_dir) if "_corrupt" not in r]
    rows.append(row)
    _atomic_write_lines(private_path(data_dir),
                        [canonical_json(r) for r in rows], ".book_commit_packages.")


def _append_trail(data_dir: str | os.PathLike, event_type: str, payload: dict, ts: str) -> dict:
    """Append one chained entry to the public trail and return it (whole-file atomic rewrite —
    the file grows by ~2 rows/day)."""
    entries = read_trail(data_dir)
    good = [e for e in entries if "entry_hash" in e]
    seq = (int(good[-1]["seq"]) + 1) if good else 0
    prev = good[-1]["entry_hash"] if good else GENESIS
    entry = {"seq": seq, "ts": ts, "event_type": event_type, "payload": payload, "prev_hash": prev}
    entry["entry_hash"] = compute_entry_hash(seq, ts, event_type, payload, prev)
    lines = [canonical_json(e) for e in entries if "_corrupt" not in e]
    lines.append(canonical_json(entry))
    _atomic_write_lines(public_path(data_dir), lines, ".book_commitments.")
    return entry


def _commits_by_date(entries: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in entries:
        if e.get("event_type") == EVENT_COMMIT:
            d = str((e.get("payload") or {}).get("cycle_date"))
            out.setdefault(d, e)
    return out


def _reveals_by_date(entries: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in entries:
        if e.get("event_type") == EVENT_REVEAL:
            d = str((e.get("payload") or {}).get("cycle_date"))
            out.setdefault(d, e)
    return out


# ── publication (the ONE sanctioned path: the morning digest queue) ─────────────────────────────
def _digest_publisher(data_dir: str | os.PathLike) -> Publisher:
    """Enqueue into ``data/<data_dir>/telegram/digest_queue.json`` via ``push_policy.enqueue_digest``
    — folded into the morning report by ``spa_core.telegram.reports.daily``. Not a Tier-1 push;
    no poller; never raises (the policy module is fail-safe by contract)."""
    def _publish(kind: str, event_key: str, title: str, body: str) -> dict:
        try:
            from spa_core.telegram import push_policy
            push_policy.enqueue_digest(event_key, title, body, severity="INFO",
                                       reason="book_commit_reveal", data_dir=str(data_dir))
            return {"channel": "telegram-digest", "public": False, "queued": True}
        except Exception as exc:  # noqa: BLE001 — publication must never block the record
            return {"channel": "telegram-digest", "public": False, "queued": False,
                    "detail": f"{type(exc).__name__}: {exc}"}
    return _publish


def _commit_text(cycle_date: str, h: str) -> tuple[str, str, str]:
    key = f"book_commit:{cycle_date}:sha256={h}"
    title = f"SPA COMMIT книги {cycle_date}"
    body = (f"sha256 {h}\nраскрытие через {REVEAL_DELAY_DAYS} цикл; проверка: "
            f"python3 scripts/verify_spa.py data/{PUBLIC_FILENAME}")
    return key, title, body


def _reveal_text(cycle_date: str, h: str, package: dict, seq: int) -> tuple[str, str, str]:
    key = f"book_reveal:{cycle_date}:sha256={h}"
    title = f"SPA REVEAL книги {cycle_date}"
    pkg = canonical_json(package)
    # push_policy keeps the first 500 chars of a body; a package that does not fit is referenced
    # by its public seq instead of being truncated into something that cannot be re-hashed.
    head = f"sha256 {h}\n"
    if len(head) + len(pkg) <= 480:
        body = head + pkg
    else:
        body = head + (f"пакет не помещается в дайджест ({len(pkg)} симв.) — см. seq {seq} в "
                       f"data/{PUBLIC_FILENAME}")
    return key, title, body


# ── public API ─────────────────────────────────────────────────────────────────────────────────
def commit(
    data_dir: str | os.PathLike,
    *,
    cycle_date: str,
    snapshot_id: Optional[str],
    target_positions: dict,
    decision_source: Any,
    action: str,
    ts: str,
    salt: Optional[str] = None,
    publish: Optional[Publisher] = None,
) -> Optional[dict]:
    """Commit the decision for ``cycle_date`` if not committed yet. Returns the public commit
    entry, or None when the date is already committed (idempotent — a re-run never re-salts).

    Order: private package first (so a crash after it cannot lose the salt), then the
    publication, then the public entry carrying the publication result."""
    cycle_date = str(cycle_date)
    entries = read_trail(data_dir)
    if cycle_date in _commits_by_date(entries):
        return None
    stored = next((r for r in read_packages(data_dir) if r.get("cycle_date") == cycle_date), None)
    if stored is None:
        package = build_package(cycle_date=cycle_date, snapshot_id=snapshot_id,
                                target_positions=target_positions, decision_source=decision_source,
                                action=action, salt=salt)
        h = commitment_hash(package)
        _append_private(data_dir, {"cycle_date": cycle_date, "package": package,
                                   "commitment_hash": h, "created_at": ts})
    else:
        # package written, public entry lost (crash between the two writes): finish the commit
        # with the STORED package — never a fresh salt for an already-hashed decision.
        package = stored["package"]
        h = str(stored.get("commitment_hash") or commitment_hash(package))
    key, title, body = _commit_text(cycle_date, h)
    pub = (publish or _digest_publisher(data_dir))("commit", key, title, body)
    payload = {
        "cycle_date": cycle_date,
        "commitment_hash": h,
        "risk_policy_version": RISK_POLICY_VERSION,
        "reveal_delay_days": REVEAL_DELAY_DAYS,
        "published": pub,
    }
    return _append_trail(data_dir, EVENT_COMMIT, payload, ts)


def _days_between(later: str, earlier: str) -> Optional[int]:
    try:
        return (_dt.date.fromisoformat(str(later)[:10]) - _dt.date.fromisoformat(str(earlier)[:10])).days
    except ValueError:
        return None


def reveal_due(
    data_dir: str | os.PathLike,
    *,
    today: str,
    ts: str,
    delay_days: int = REVEAL_DELAY_DAYS,
    publish: Optional[Publisher] = None,
) -> list[dict]:
    """Reveal every committed package whose delay has elapsed as of ``today`` (the cycle date —
    time is an input, never read from the wall here). Returns the public reveal entries appended.
    A package with no commit entry on the trail is NOT revealed (nothing was committed to)."""
    entries = read_trail(data_dir)
    commits = _commits_by_date(entries)
    revealed = _reveals_by_date(entries)
    out: list[dict] = []
    for row in sorted((r for r in read_packages(data_dir) if "_corrupt" not in r),
                      key=lambda r: str(r.get("cycle_date"))):
        d = str(row.get("cycle_date"))
        if d in revealed or d not in commits:
            continue
        age = _days_between(today, d)
        if age is None or age < delay_days:
            continue
        package = row.get("package") or {}
        h = str(row.get("commitment_hash") or commitment_hash(package))
        commit_entry = commits[d]
        key, title, body = _reveal_text(d, h, package, int(commit_entry.get("seq", -1)))
        pub = (publish or _digest_publisher(data_dir))("reveal", key, title, body)
        payload = {
            "cycle_date": d,
            "commitment_hash": h,
            "commit_seq": commit_entry.get("seq"),
            "package": package,
            "published": pub,
        }
        entry = _append_trail(data_dir, EVENT_REVEAL, payload, ts)
        out.append(entry)
        commits = _commits_by_date(read_trail(data_dir))  # keep seq/prev fresh for the next append
    return out


def verify_trail(data_dir: str | os.PathLike) -> dict:
    """Recompute every entry hash in order AND check every reveal against its earlier commit.

    {ok, entries, broken_at, reason, commits, reveals, verified_reveals}. The same checks as
    ``scripts/verify_spa.py`` surface J, run in-process by the monitor; the public verifier is
    the one a reviewer runs — this one must never disagree with it."""
    entries = read_trail(data_dir)
    prev = GENESIS
    commits: dict[str, dict] = {}
    n_commits = n_reveals = n_verified = 0
    for i, e in enumerate(entries):
        if "_corrupt" in e:
            return _bad(i, len(entries), "corrupt line", n_commits, n_reveals, n_verified)
        if e.get("prev_hash") != prev or e.get("seq") != i:
            return _bad(i, len(entries), "chain broken (prev_hash/seq)", n_commits, n_reveals, n_verified)
        et = e.get("event_type")
        if et not in EVENT_TYPES:
            return _bad(i, len(entries), f"unknown event_type {et!r}", n_commits, n_reveals, n_verified)
        try:
            recomputed = compute_entry_hash(e["seq"], e["ts"], et, e["payload"], e["prev_hash"])
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return _bad(i, len(entries), "malformed row", n_commits, n_reveals, n_verified)
        if recomputed != e.get("entry_hash"):
            return _bad(i, len(entries), "entry_hash mismatch (payload altered)", n_commits, n_reveals, n_verified)
        p = e.get("payload") or {}
        d = str(p.get("cycle_date"))
        h = str(p.get("commitment_hash") or "")
        if et == EVENT_COMMIT:
            if d in commits:
                return _bad(i, len(entries), f"second commit for {d} (idempotency broken)", n_commits, n_reveals, n_verified)
            if len(h) != 64:
                return _bad(i, len(entries), "commit without a 64-hex commitment_hash", n_commits, n_reveals, n_verified)
            commits[d] = e
            n_commits += 1
        else:
            n_reveals += 1
            c = commits.get(d)
            if c is None:
                return _bad(i, len(entries), f"reveal for {d} without a prior commit", n_commits, n_reveals, n_verified)
            if str((c.get("payload") or {}).get("commitment_hash")) != h:
                return _bad(i, len(entries), f"reveal for {d} names a different hash than its commit", n_commits, n_reveals, n_verified)
            if not isinstance(p.get("package"), dict) or not verify_package(p["package"], h):
                return _bad(i, len(entries), f"package for {d} does not hash to its commitment", n_commits, n_reveals, n_verified)
            n_verified += 1
        prev = e["entry_hash"]
    return {"ok": True, "entries": len(entries), "broken_at": None, "reason": None,
            "commits": n_commits, "reveals": n_reveals, "verified_reveals": n_verified}


def _bad(i: int, n: int, reason: str, c: int, r: int, v: int) -> dict:
    return {"ok": False, "entries": n, "broken_at": i, "reason": reason,
            "commits": c, "reveals": r, "verified_reveals": v}


def status(data_dir: str | os.PathLike, *, today: str) -> dict:
    """What the monitor needs: last commit/reveal dates, pending reveals with ages, overdue ones,
    packages that never got a commit entry, and the chain verdict."""
    entries = read_trail(data_dir)
    commits = _commits_by_date(entries)
    reveals = _reveals_by_date(entries)
    pkg_dates = {str(r.get("cycle_date")) for r in read_packages(data_dir) if "_corrupt" not in r}
    pending = []
    for d in sorted(commits):
        if d in reveals:
            continue
        age = _days_between(today, d)
        pending.append({"cycle_date": d, "age_days": age})
    overdue = [p["cycle_date"] for p in pending
               if p["age_days"] is not None and p["age_days"] > OVERDUE_AFTER_DAYS]
    return {
        "exists": public_path(data_dir).is_file(),
        "entries": len(entries),
        "last_commit_date": max(commits) if commits else None,
        "last_reveal_date": max(reveals) if reveals else None,
        "pending": pending,
        "overdue": overdue,
        "uncommitted_packages": sorted(pkg_dates - set(commits)),
        "chain": verify_trail(data_dir),
    }
