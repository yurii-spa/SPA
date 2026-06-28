#!/usr/bin/env python3
"""
scripts/drill_restore.py — INERT restore drill (R7 resilience sprint).

WHY: SPA writes backups (data/backups/spa_state_*.tar.gz via the backup agents) but
had NEVER proven that a restore actually works. A backup you cannot restore is theater.
This drill EXTRACTS the newest backup to a TEMP sandbox and VALIDATES the critical state
files a real recovery must produce — without ever writing into the live data/ tree.

DESIGN (fail-CLOSED, stdlib-only, deterministic):
  1. Find the NEWEST backup archive in data/backups/ (by mtime). Fail-closed if none.
  2. Extract it to a fresh tempfile.mkdtemp() sandbox — NEVER under the live data/.
     A hard guard asserts the extract dir is OUTSIDE the repo data/ before any write,
     and tar members are path-sanitised (no absolute paths / .. traversal).
  3. Validate the critical recovered files:
       - golive_status.json          → JSON parses + has top-level passed/total;
                                        real_track_days is an int >= 0.
       - equity_curve_daily.json     → JSON parses + non-empty 'daily' list;
                                        last date <= today (UTC).
       - paper_evidence_history.json → JSON parses + dict with expected keys.
       - current_positions.json      → JSON parses.
       - track.db (sqlite)           → opens via sqlite3 + a sanity query (list tables,
                                        count a known table) without corruption.
         track.db is now carried INSIDE the converged state tar (both the dr_backup and
         daily_backup producers add a consistent sqlite copy), so it is validated from the
         in-archive member. For LEGACY archives produced before convergence (no track.db
         member) the drill falls back to the newest bare data/backups/spa_*.db snapshot. If
         no usable source exists, track.db is reported FAIL (fail-closed).
  4. Print a clear PASS/FAIL report and write data/restore_drill_status.json (atomic).
  5. Exit 0 iff EVERY critical file was restored + valid. Otherwise non-zero.

The temp sandbox is removed on exit by default (--keep leaves it + prints the path).

Usage:
  python3 scripts/drill_restore.py                 # drill the newest archive
  python3 scripts/drill_restore.py --archive PATH  # drill a specific archive
  python3 scripts/drill_restore.py --keep          # keep the temp sandbox
  python3 scripts/drill_restore.py --quiet         # only the final verdict line
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Make `import spa_core` resolvable when run directly (the WS-8 extended validators load
# spa_core.audit.day30_artifact); launchd hands a minimal PYTHONPATH so be explicit.
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_DATA = os.path.realpath(os.path.join(_REPO_ROOT, "data"))
_BACKUPS = os.path.join(_DATA, "backups")
_STATUS_PATH = os.path.join(_DATA, "restore_drill_status.json")

ARCHIVE_GLOB = os.path.join(_BACKUPS, "spa_state_*.tar.gz")
DB_GLOB = os.path.join(_BACKUPS, "spa_*.db")

# Critical files a restore MUST recover. Each is validated below.
CRITICAL_JSON = (
    "golive_status.json",
    "equity_curve_daily.json",
    "paper_evidence_history.json",
    "current_positions.json",
)
CRITICAL_DB = "track.db"

# ── WS-8: the EXTENDED critical state a restore must also byte-verifiably recover ──
# These are the published PROOF CHAINS, the CAPTURED BOOK, and the DAY-30 artifact. They
# are HASH-ANCHORED, so "byte-verifiable recovery" means more than "the JSON parses": the
# restored copy must REPRODUCE its published hashes (verify_spa.py for the chains, the
# embedded proof_hash for the day-30 artifact). A backup that restored a TORN/edited proof
# chain would be caught here, never silently passed.
#
# Each entry is validated ONLY IF it is present in the archive (a legacy archive produced
# before WS-8 has none of these → reported as not-in-archive, which is a soft note, not a
# hard fail — the core CRITICAL_JSON + track.db set is what gates the drill). For a CURRENT
# archive (post-WS-8 daily_backup / dr_backup) they ARE present and MUST verify.
PROOF_CHAIN_DIR = "rates_desk"            # verify_spa.py covers A/B/C/D + paper/ (captured book)
PROOF_BREADTH_DIRS = ("tournament", "rwa_backstop")  # E / F — also covered by verify_spa.py
CAPTURED_BOOK = "rates_desk/paper/rates_desk_fixed_carry_series.json"
CAPTURED_BOOK_PROOF = "rates_desk/paper/rates_desk_fixed_carry_series_proof.jsonl"
DAY30_ARTIFACT = "day30_artifact.json"


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def find_newest_archive() -> str:
    """Newest spa_state_*.tar.gz by mtime. Fail-CLOSED (raise) if none."""
    archives = [p for p in glob.glob(ARCHIVE_GLOB) if os.path.isfile(p)]
    if not archives:
        raise FileNotFoundError(f"no backup archives match {ARCHIVE_GLOB}")
    return max(archives, key=lambda p: (os.path.getmtime(p), p))


def find_newest_db() -> str:
    """Newest non-empty bare spa_*.db snapshot, or '' if none usable."""
    dbs = [p for p in glob.glob(DB_GLOB)
           if os.path.isfile(p) and os.path.getsize(p) > 0]
    if not dbs:
        return ""
    return max(dbs, key=lambda p: (os.path.getmtime(p), p))


# --------------------------------------------------------------------------- #
# safe extraction
# --------------------------------------------------------------------------- #
def _assert_sandbox_outside_data(sandbox: str) -> None:
    """HARD guard: the extract dir must be a real dir OUTSIDE the live data/ tree."""
    real = os.path.realpath(sandbox)
    if not os.path.isdir(real):
        raise RuntimeError(f"sandbox is not a directory: {real}")
    data = _DATA + os.sep
    if real == _DATA or real.startswith(data):
        raise RuntimeError(
            f"REFUSING to extract: sandbox {real} is under live data/ {_DATA}"
        )


def _is_within(directory: str, target: str) -> bool:
    directory = os.path.realpath(directory)
    target = os.path.realpath(target)
    return target == directory or target.startswith(directory + os.sep)


def safe_extract(archive: str, sandbox: str) -> list:
    """Extract every member into the sandbox, rejecting absolute / traversal paths.

    Returns the list of member names extracted. Never follows members outside sandbox.
    """
    _assert_sandbox_outside_data(sandbox)
    extracted = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or os.path.isabs(name) or ".." in name.split("/"):
                raise RuntimeError(f"unsafe tar member path rejected: {name!r}")
            dest = os.path.join(sandbox, name)
            if not _is_within(sandbox, dest):
                raise RuntimeError(f"tar member escapes sandbox: {name!r}")
            if member.islnk() or member.issym():
                raise RuntimeError(f"link member rejected: {name!r}")
            # 'data' filter (py3.12+) strips perms/abs-paths; fall back if unsupported.
            try:
                tar.extract(member, sandbox, filter="data")
            except TypeError:
                tar.extract(member, sandbox)  # older Python: members sanitised above
            extracted.append(name)
    # final paranoia: nothing landed in live data/
    _assert_sandbox_outside_data(sandbox)
    return extracted


# --------------------------------------------------------------------------- #
# validators (each returns (ok: bool, detail: str))
# --------------------------------------------------------------------------- #
def _today_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _validate_golive(path: str) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        return False, "not a JSON object"
    for k in ("passed", "total"):
        if k not in d:
            return False, f"missing top-level key {k!r}"
    if not isinstance(d["passed"], int) or not isinstance(d["total"], int):
        return False, "passed/total not ints"
    rtd = d.get("real_track_days")
    if not isinstance(rtd, int) or rtd < 0:
        return False, f"real_track_days not a non-negative int: {rtd!r}"
    return True, f"passed={d['passed']}/{d['total']} real_track_days={rtd}"


def _validate_equity(path: str) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    daily = d.get("daily") if isinstance(d, dict) else (d if isinstance(d, list) else None)
    if not isinstance(daily, list) or not daily:
        return False, "no non-empty 'daily' list"
    last = daily[-1]
    last_date = last.get("date") if isinstance(last, dict) else None
    if not isinstance(last_date, str) or not last_date:
        return False, "last point has no date"
    if last_date > _today_utc():
        return False, f"last date {last_date} is in the future (> {_today_utc()})"
    return True, f"{len(daily)} points, last={last_date}"


def _validate_evidence(path: str) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        return False, "not a JSON object"
    # tolerant: accept any of the known shapes for the evidence ledger
    if not any(k in d for k in ("days", "history", "schema_version")):
        return False, "missing expected evidence keys"
    n = len(d.get("days", d.get("history", [])) or [])
    return True, f"evidence dict ok ({n} entries)"


def _validate_positions(path: str) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, (dict, list)):
        return False, "not a JSON object/array"
    return True, "positions JSON parses"


_JSON_VALIDATORS = {
    "golive_status.json": _validate_golive,
    "equity_curve_daily.json": _validate_equity,
    "paper_evidence_history.json": _validate_evidence,
    "current_positions.json": _validate_positions,
}


def _validate_sqlite(path: str) -> tuple:
    """Open via sqlite3, list tables, count a known table — detects corruption."""
    if not path or not os.path.isfile(path):
        return False, "no usable track.db snapshot found"
    con = None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = con.cursor()
        ic = cur.execute("PRAGMA integrity_check").fetchone()
        if not ic or ic[0] != "ok":
            return False, f"integrity_check={ic}"
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        # sanity query: count a known table if present, else just confirm we can query
        known = next((t for t in tables
                      if t in ("evidence_records", "paper_trading_records",
                               "system_events", "adapter_apy_history")), None)
        if known:
            n = cur.execute(f"SELECT COUNT(*) FROM {known}").fetchone()[0]
            return True, f"sqlite ok, {len(tables)} tables, {known}={n} rows"
        return True, f"sqlite ok, {len(tables)} tables (no known table to count)"
    except sqlite3.DatabaseError as exc:
        return False, f"sqlite error: {exc}"
    finally:
        if con is not None:
            con.close()


# --------------------------------------------------------------------------- #
# WS-8 extended validators — the proof chains / captured book / day-30 artifact
# must be recovered BYTE-VERIFIABLY (reproduce their published hashes), not merely
# parse. These run against the restored copies in the sandbox.
# --------------------------------------------------------------------------- #
_REPO_ROOT_FOR_VERIFY = _REPO_ROOT  # the live repo (for loading verify_spa.py / day30 module)


def _load_verify_spa():
    """Import scripts/verify_spa.py as a module (it is a script, not a package)."""
    import importlib.util
    path = os.path.join(_REPO_ROOT_FOR_VERIFY, "scripts", "verify_spa.py")
    spec = importlib.util.spec_from_file_location("verify_spa_for_drill", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _validate_proof_chains(sandbox: str, archive_members: set) -> tuple:
    """BYTE-VERIFIABLE recovery of every published proof chain present in the archive.

    Runs the STANDALONE verify_spa.py (the same zero-dependency tool a third party uses) over
    the restored proof tree in the sandbox. verify_spa re-derives EVERY published hash (decision
    chain, exit-NAV, anchors, equity track, tournament, RWA-NAV, sleeve/captured-book proofs); a
    single restored byte that differs from what produced the published hash → exit non-zero here.

    Returns (ok, detail). If NO proof surface is present in the archive (legacy pre-WS-8 backup),
    returns (True, 'no proof chains in archive (legacy)') — a soft pass for the core drill.
    """
    has_any = any(
        m.startswith(PROOF_CHAIN_DIR + "/") or any(m.startswith(d + "/") for d in PROOF_BREADTH_DIRS)
        for m in archive_members
    )
    if not has_any:
        return True, "no proof chains in archive (legacy pre-WS-8 backup)"
    try:
        ver = _load_verify_spa()
    except Exception as exc:  # noqa: BLE001
        return False, f"could not load verify_spa.py: {exc}"
    # Point verify_spa at the restored sandbox copy of data/ (it auto-discovers all surfaces).
    targets = []
    for d in (PROOF_CHAIN_DIR, *PROOF_BREADTH_DIRS):
        p = os.path.join(sandbox, d)
        if os.path.isdir(p):
            targets.append(p)
    if not targets:
        return False, "proof members present in archive but no proof dir restored"
    try:
        report = ver.run(targets)
    except Exception as exc:  # noqa: BLE001
        return False, f"verify_spa raised: {exc}"
    if report.get("ok"):
        surfaces = [k for k in ("decision_chain", "exit_nav", "anchors", "equity_track",
                                "tournament", "nav_proof", "sleeves")
                    if report.get(k)]
        return True, f"verify_spa OK — reproduced surfaces: {','.join(surfaces) or 'none'}"
    return False, f"verify_spa FAILED: {report.get('errors')}"


def _validate_captured_book(sandbox: str, archive_members: set) -> tuple:
    """The CAPTURED BOOK (rates-desk FixedCarry forward series) + its hash-anchored proof must be
    recovered and the proof must re-derive (covered by verify_spa over rates_desk/paper/). Here we
    additionally assert both the series AND its proof are physically present + parse, so a dropped
    captured book is caught explicitly (not only via the aggregate proof run)."""
    if CAPTURED_BOOK not in archive_members:
        return True, "captured book not in archive (legacy pre-WS-8 backup)"
    series_p = os.path.join(sandbox, CAPTURED_BOOK)
    proof_p = os.path.join(sandbox, CAPTURED_BOOK_PROOF)
    if not os.path.isfile(series_p):
        return False, "captured book series in manifest but not restored"
    try:
        with open(series_p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        n = len(doc.get("series", [])) if isinstance(doc, dict) else 0
    except Exception as exc:  # noqa: BLE001
        return False, f"captured book series unparseable: {exc}"
    if CAPTURED_BOOK_PROOF not in archive_members or not os.path.isfile(proof_p):
        return False, f"captured book series restored ({n} pts) but its hash-anchored proof is MISSING"
    return True, f"captured book restored: {n} forward point(s) + proof present"


def _validate_day30(sandbox: str, archive_members: set) -> tuple:
    """The DAY-30 readiness artifact must be recovered and its embedded proof_hash must re-derive
    (byte-verifiable: any edited content field breaks the hash). Uses the SAME compute_proof_hash
    the producer uses."""
    if DAY30_ARTIFACT not in archive_members:
        return True, "day30 artifact not in archive (not yet produced / legacy backup)"
    p = os.path.join(sandbox, DAY30_ARTIFACT)
    if not os.path.isfile(p):
        return False, "day30 artifact in manifest but not restored"
    try:
        with open(p, "r", encoding="utf-8") as f:
            art = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return False, f"day30 artifact unparseable: {exc}"
    try:
        import importlib
        d30 = importlib.import_module("spa_core.audit.day30_artifact")
        res = d30.verify_artifact(art)
    except Exception as exc:  # noqa: BLE001
        return False, f"day30 verify raised: {exc}"
    if res.get("valid"):
        return True, f"day30 proof_hash re-derives (verdict={art.get('verdict')})"
    return False, ("day30 proof_hash MISMATCH — restored artifact does not reproduce its hash "
                   f"(stored={str(res.get('stored_hash'))[:16]}…)")


# --------------------------------------------------------------------------- #
# atomic status write
# --------------------------------------------------------------------------- #
def _atomic_write_json(path: str, obj: dict) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
        shutil.move(tmp, path)  # cross-device-safe atomic replace (project convention)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# drill
# --------------------------------------------------------------------------- #
def run_drill(archive: str = "", keep: bool = False, quiet: bool = False) -> dict:
    """Run the inert restore drill. Returns the report dict (also written to status JSON)."""
    archive = archive or find_newest_archive()
    archive = os.path.abspath(archive)
    if not os.path.isfile(archive):
        raise FileNotFoundError(f"archive not found: {archive}")

    sandbox = tempfile.mkdtemp(prefix="spa_restore_drill_")
    _assert_sandbox_outside_data(sandbox)  # guard BEFORE any extraction

    files_validated = []
    all_ok = True
    db_snapshot = ""
    db_source_label = None
    try:
        members = safe_extract(archive, sandbox)
        member_set = set(members)

        # 1) JSON critical files (must be present in the archive — fail-CLOSED if not)
        for name in CRITICAL_JSON:
            entry = {"file": name, "ok": False, "detail": ""}
            if name not in member_set:
                entry["detail"] = "MISSING from archive"
            else:
                try:
                    ok, detail = _JSON_VALIDATORS[name](os.path.join(sandbox, name))
                    entry["ok"], entry["detail"] = ok, detail
                except Exception as exc:  # parse error etc.
                    entry["detail"] = f"validation error: {exc}"
            all_ok = all_ok and entry["ok"]
            files_validated.append(entry)

        # 2) track.db — PREFER the copy now carried INSIDE the converged archive (every
        #    backup ships the full critical set). Fall back to the newest bare .db snapshot
        #    only for legacy archives produced before convergence (backward compat).
        db_source_label = None
        if CRITICAL_DB in member_set:
            db_path = os.path.join(sandbox, CRITICAL_DB)
            ok, detail = _validate_sqlite(db_path)
            db_source_label = f"in-archive:{os.path.basename(archive)}"
            db_snapshot = ""  # in-tar, not a bare snapshot
        else:
            db_snapshot = find_newest_db()
            ok, detail = _validate_sqlite(db_snapshot)
            db_source_label = os.path.basename(db_snapshot) if db_snapshot else None
        files_validated.append({
            "file": CRITICAL_DB,
            "ok": ok,
            "detail": detail,
            "source": db_source_label,
        })
        all_ok = all_ok and ok

        # 3) WS-8 EXTENDED critical state — byte-verifiable recovery of the proof chains,
        #    the captured book, and the day-30 artifact (each reproduces its published hash).
        #    Present-and-valid → PASS; present-and-torn → FAIL; absent (legacy archive) → soft PASS.
        for label, fn in (("proof_chains", _validate_proof_chains),
                          ("captured_book", _validate_captured_book),
                          ("day30_artifact", _validate_day30)):
            try:
                ok2, detail2 = fn(sandbox, member_set)
            except Exception as exc:  # noqa: BLE001 — a validator crash is a fail-closed FAIL
                ok2, detail2 = False, f"validator error: {exc}"
            files_validated.append({"file": label, "ok": ok2, "detail": detail2})
            all_ok = all_ok and ok2
    finally:
        if keep:
            sandbox_note = sandbox
        else:
            shutil.rmtree(sandbox, ignore_errors=True)
            sandbox_note = None

    report = {
        "schema": "spa_restore_drill/v1",
        "llm_forbidden": True,
        "last_drill_ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "archive": os.path.basename(archive),
        "archive_path": archive,
        "db_snapshot": db_source_label,
        "sandbox": sandbox_note,
        "files_validated": files_validated,
        "all_ok": all_ok,
    }
    _atomic_write_json(_STATUS_PATH, report)

    if not quiet:
        _print_report(report)
    return report


def _print_report(report: dict) -> None:
    print("=" * 64)
    print("SPA RESTORE DRILL (inert — extracted to temp sandbox, live data/ untouched)")
    print("=" * 64)
    print(f"archive     : {report['archive']}")
    print(f"track.db src: {report['db_snapshot']}")
    if report["sandbox"]:
        print(f"sandbox     : {report['sandbox']} (kept)")
    print("-" * 64)
    for e in report["files_validated"]:
        mark = "PASS" if e["ok"] else "FAIL"
        print(f"  [{mark}] {e['file']:<28} {e['detail']}")
    print("-" * 64)
    verdict = "ALL CRITICAL FILES RESTORED + VALID" if report["all_ok"] \
        else "RESTORE DRILL FAILED (fail-closed)"
    print(f"VERDICT: {verdict}  (all_ok={report['all_ok']})")
    print(f"status  : {_STATUS_PATH}")


def main() -> int:
    ap = argparse.ArgumentParser(description="SPA inert restore drill")
    ap.add_argument("--archive", default="", help="drill a specific archive (default: newest)")
    ap.add_argument("--keep", action="store_true", help="keep the temp sandbox")
    ap.add_argument("--quiet", action="store_true", help="only print the verdict line")
    args = ap.parse_args()

    try:
        report = run_drill(archive=args.archive, keep=args.keep, quiet=args.quiet)
    except Exception as exc:
        # fail-CLOSED: any failure to even run the drill is a non-zero exit
        print(f"[FAIL] restore drill could not run: {exc}", file=sys.stderr)
        try:
            _atomic_write_json(_STATUS_PATH, {
                "schema": "spa_restore_drill/v1",
                "last_drill_ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "archive": None,
                "files_validated": [],
                "all_ok": False,
                "error": str(exc),
            })
        except Exception:
            pass
        return 2

    if args.quiet:
        print(f"all_ok={report['all_ok']} archive={report['archive']}")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
