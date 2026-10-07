#!/usr/bin/env python3
"""verify_publication.py — the fail-closed gate between BUILD and PUBLISH (PRODUCT-TRUTH-02, ADR-630).

Answers ONE question about a candidate shelf (`landing/src/data/site_numbers.json`): «may this artifact
go to the public as it is?». It never publishes, never writes, never fixes. Three outcomes (inv. #17):

  0  PASS          — every check measured and clean
  1  FAIL          — at least one named finding (each one alone is a reason to refuse)
  2  NOT MEASURED  — an input could not be read; «could not check» is never «clean»

Checks (each a named finding): schema/provenance present · source files exist and hash to the recorded
values · the artifact equals a rebuild from its own inputs · every return is typed (TARGET / OBSERVED /
REALIZED_PAPER / MODELLED / BACKTEST) and the type agrees with its kind and maturity · a backtest tail is
labelled BACKTEST · a short history is never a reportable result · the product mapping has no conflict ·
the measurement date is not stale · the declared next publication follows the one cadence rule · the
candidate is not older than the shelf already published · every changed public financial value carries
an approval (standing approval only for a re-measured value of the same field and type, ADR-357 weekly
cadence; anything else needs an explicit owner approval reference) · pages do not read deprecated
untyped fields.

stdlib, deterministic, LLM_FORBIDDEN.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from spa_core.publication import cadence  # noqa: E402
from spa_core.publication import metric_types as mt  # noqa: E402
from spa_core.publication import product_map  # noqa: E402
from spa_core.defi_engine.package_status import REPORTABLE_AFTER  # noqa: E402

PASS, FAIL, NOT_MEASURED = 0, 1, 2
#: a weekly shelf may carry a measurement at most this many days older than its publication date
MAX_MEASUREMENT_LAG_DAYS = 3
#: a measurement older than one cadence plus the lag is never published, however approved
MAX_MEASUREMENT_AGE_DAYS = 10
#: the standing approval for routine re-measurement of an already-published field (owner, weekly cadence)
STANDING_APPROVAL = "ADR-357 п. 5 (weekly re-publication of measured values)"
#: page code reading these as a published/paper rate is a defect (audit 2026-10-07): a 1-day observation
#: or a fallback chain onto it shown under a «Paper APY» label.
DEPRECATED_READS = (
    (re.compile(r"(\?\?|\|\|)\s*[\w.?\[\]'\"]*apy_today_pct\w*"),
     "a rate falls back to the 1-day apy_today_pct (shown under the mature label)"),
    (re.compile(r"\bytd_apy_pct\b"), "ytd_apy_pct (1-day observation) read by a page"),
)


def _load_bsn():
    spec = importlib.util.spec_from_file_location("_bsn_verify", ROOT / "scripts" / "build_site_numbers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _figures(doc, path="shelf"):
    if isinstance(doc, dict):
        if "value" in doc and "unit" in doc and "kind" in doc:
            yield path, doc
            return
        for k, v in doc.items():
            if not str(k).startswith("_"):
                yield from _figures(v, f"{path}.{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from _figures(v, f"{path}[{i}]")


def check_types(doc: dict, bsn) -> list[str]:
    out: list[str] = []
    for path, f in _figures(doc):
        kind, mtype = f.get("kind"), f.get("metric_type")
        if kind not in bsn.KINDS:
            out.append(f"{path}: unknown kind {kind!r}")
        if f.get("annualised"):
            if mtype not in mt.RETURN_TYPES:
                out.append(f"{path}: return without a known metric_type ({mtype!r})")
                continue
            if kind == bsn.BACKTEST and mtype != mt.BACKTEST_RETURN:
                out.append(f"{path}: BACKTEST source exposed as {mtype}")
            if kind == bsn.TARGET and mtype != mt.TARGET_RETURN:
                out.append(f"{path}: TARGET exposed as {mtype} (a target is never a result)")
            if mtype == mt.TARGET_RETURN and kind != bsn.TARGET:
                out.append(f"{path}: TARGET_RETURN carried by kind {kind!r}")
            if mtype == mt.BACKTEST_RETURN and kind != bsn.BACKTEST:
                out.append(f"{path}: BACKTEST_RETURN carried by kind {kind!r} (backtest exposed as paper)")
            if kind == bsn.MEASUREMENT and mtype not in (mt.REALIZED_PAPER_RETURN, mt.OBSERVED_RETURN):
                out.append(f"{path}: measurement typed {mtype}")
            if mtype == mt.REALIZED_PAPER_RETURN:
                w = f.get("window_days")
                if f.get("reportable") is not True:
                    out.append(f"{path}: REALIZED_PAPER_RETURN not marked reportable")
                if not isinstance(w, (int, float)) or w < REPORTABLE_AFTER:
                    out.append(f"{path}: REALIZED_PAPER_RETURN on a {w!r}-day window (< {REPORTABLE_AFTER}) — "
                               "short history annualised as a mature result")
            if mtype == mt.OBSERVED_RETURN and f.get("reportable") is True:
                out.append(f"{path}: OBSERVED_RETURN marked reportable")
        elif mtype is not None:
            out.append(f"{path}: metric_type {mtype!r} on a non-annualised figure")
        if path.endswith(".drawdown") and f.get("value") is not None:
            want = mt.BACKTEST if kind == bsn.BACKTEST else mt.PAPER
            if f.get("basis") != want:
                out.append(f"{path}: drawdown basis {f.get('basis')!r}, expected {want} (backtest tail must say BACKTEST)")
    out += [f"validate_shelf: {p}" for p in bsn.validate_shelf(doc)]
    return out


def _flat_values(doc: dict) -> dict:
    return {p: (f.get("value"), f.get("kind"), f.get("metric_type")) for p, f in _figures(doc)}


APPROVAL_LINE = "publication-approves:"
SHELF_REL = "landing/src/data/site_numbers.json"


def approval_line(doc: dict, shelf_sha: str) -> str:
    """The exact line an owner approval record must carry: it names THIS shelf by its publication date and
    content hash, so an approval of one candidate can never be reused for another."""
    return f"{APPROVAL_LINE} {SHELF_REL} {doc.get('published_at')} sha256:{shelf_sha}"


APPROVAL_ONLY_MARKERS = ("missing owner approval", "first publication of a shelf needs",
                         "approval record not found", "is not closed by the owner", "does not name this shelf")


def approval_only(res: dict) -> bool:
    """True when the ONLY thing between this shelf and the public is the owner's approval."""
    f = res.get("findings") or []
    return res.get("outcome") == FAIL and bool(f) and all(any(m in x for m in APPROVAL_ONLY_MARKERS) for x in f)


def card_status(text: str) -> Optional[str]:
    """The card's status from its YAML FRONTMATTER only (the queue's own parser) — a body line that
    happens to read `status: owner-done` approves nothing."""
    from spa_core.owner_queue.queue import _parse_frontmatter, _split_frontmatter
    fm_lines, _ = _split_frontmatter(text)
    st = _parse_frontmatter(fm_lines).get("status") if fm_lines else None
    return str(st).strip() if st is not None else None


OWNER_CLOSED = ("owner-done", "owner-accepted")


def find_approval(doc: dict, shelf_sha: str, tracker_dir: "Path | str | None" = None) -> Optional[str]:
    """The owner-closed card that names THIS shelf (exact `publication-approves:` line), or None.
    Scans the tracker files directly — one rule for safe_site_push, both pushers and the publisher."""
    import os
    if tracker_dir is None:
        tracker_dir = os.environ.get("SPA_TRACKER_DIR") or None
    if tracker_dir is None:
        try:
            from spa_core.owner_queue.queue import TRACKER_DIR as tracker_dir  # type: ignore
        except Exception:  # noqa: BLE001
            return None
    line = approval_line(doc, shelf_sha)
    for p in sorted(Path(tracker_dir).glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if line in text and card_status(text) in OWNER_CLOSED:
            return str(p)
    return None


def needs_approval(doc: dict, published: dict, bsn) -> list[str]:
    """What a standing approval does NOT cover. Standing (ADR-357 weekly cadence) covers ONE thing: a
    re-measured value of a field that was already public with the same kind and type. Everything else —
    a new schema, a new field with a value, null→value, a changed type, a changed decision/target/backtest
    value — needs an explicit owner approval of this shelf."""
    out = []
    ps = (published.get("_provenance") or {}).get("schema_version") if isinstance(published.get("_provenance"), dict) else None
    cs = (doc.get("_provenance") or {}).get("schema_version") if isinstance(doc.get("_provenance"), dict) else None
    if ps != cs:
        out.append(f"first publication of shelf schema {cs!r} (public today: {ps!r})")
    old, new = _flat_values(published), _flat_values(doc)
    for p, (v, k, t) in new.items():
        if v is None:
            continue
        if p not in old:
            out.append(f"{p}: new public value {v!r}")
            continue
        ov, ok, ot = old[p]
        if ov is None:
            out.append(f"{p}: null → {v!r} (a value appears for the first time)")
        elif (k, t) != (ok, ot):
            out.append(f"{p}: type changed {ok}/{ot} → {k}/{t}")
        elif v != ov and k != bsn.MEASUREMENT:
            out.append(f"{p}: {k} value changed {ov!r} → {v!r}")
    return out


def check_approval(doc: dict, published: Optional[dict], approval: Optional[str], bsn,
                   shelf_sha: str) -> list[str]:
    # the record is checked FIRST, whatever the diff says: a bad reference is a finding on its own
    if approval:
        ap = Path(approval)
        if not ap.is_file():
            return [f"owner approval record not found: {approval}"]
        text = ap.read_text(encoding="utf-8", errors="replace")
        if card_status(text) not in OWNER_CLOSED:
            return [f"owner approval {approval} is not closed by the owner (status owner-done/owner-accepted)"]
        if approval_line(doc, shelf_sha) not in text:
            return [f"owner approval {approval} does not name this shelf "
                    f"(expected line: {approval_line(doc, shelf_sha)})"]
    if published is None:
        return [] if approval else ["first publication of a shelf needs an explicit owner approval"]
    needs = needs_approval(doc, published, bsn)
    if needs and not approval:
        return ["missing owner approval for: " + "; ".join(needs[:12]) +
                (f" (+{len(needs) - 12} more)" if len(needs) > 12 else "")]
    return []


def scan_pages(pages_dir: Path) -> list[str]:
    """Every OCCURRENCE (file + normalised line text), so a second offender in a listed file is new."""
    out: list[str] = []
    root = pages_dir.parent.parent
    for p in sorted(pages_dir.rglob("*")):
        if p.suffix not in (".astro", ".js", ".jsx", ".ts", ".tsx") or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        rel = p.relative_to(root) if root in p.parents else p
        for rx, what in DEPRECATED_READS:
            for m in rx.finditer(text):
                ln = text.count("\n", 0, m.start())
                snippet = " ".join(lines[ln].split())[:160] if ln < len(lines) else ""
                key = f"{rel} :: {snippet} ({what})"
                if key not in out:
                    out.append(key)
    return out


def verify(*, shelf: Path, published: Optional[Path], today: str, approval: Optional[str] = None,
           pages: Optional[Path] = None, bsn=None) -> dict:
    bsn = bsn or _load_bsn()
    doc = _read(shelf)
    if doc is None:
        return {"outcome": NOT_MEASURED, "reason": f"candidate shelf not readable: {shelf}", "findings": []}
    findings: list[str] = []
    prov = doc.get("_provenance")
    if not isinstance(prov, dict) or prov.get("schema_version") != bsn.SCHEMA_VERSION:
        findings.append(f"stale artifact: schema {(prov or {}).get('schema_version') if isinstance(prov, dict) else None!r} "
                        f"≠ {bsn.SCHEMA_VERSION} (rebuild with scripts/build_site_numbers.py)")
        prov = prov if isinstance(prov, dict) else {}
    # sources: judged against the shelf's OWN recorded inputs (review 07.10, deadlock B). A shelf approved
    # days after its build must still verify: its inputs are found by hash — today's file if unchanged,
    # else the content-addressed copy the builder preserved at write time (`bsn.INPUTS_STORE`).
    recovered: dict = {}
    for rel, want in (prov.get("source_hashes") or {}).items():
        cur = {"landing/src/data/track_snapshot.json": bsn.SNAPSHOT,
               "landing/src/lib/constitution.json": bsn.CONSTITUTION}.get(rel, ROOT / rel)
        kept = [Path(bsn.inputs_store_for(Path(shelf))) / f"{want}.json", Path(bsn.INPUTS_STORE) / f"{want}.json"]
        hit = next((c for c in (Path(cur), *kept) if c.is_file() and bsn._sha256(c) == want), None)
        if hit is not None:
            recovered[rel] = hit
        elif not Path(cur).is_file():
            return {"outcome": NOT_MEASURED, "reason": f"missing source {rel}", "findings": findings}
        else:
            findings.append(f"source hash mismatch: {rel} changed since the artifact was built and the "
                            f"recorded input sha256:{want[:12]} is not preserved")
    # rebuild equality — from the RECORDED inputs, not today's files
    swap = (bsn.SNAPSHOT, bsn.CONSTITUTION)
    try:
        bsn.SNAPSHOT = recovered.get("landing/src/data/track_snapshot.json", bsn.SNAPSHOT)
        bsn.CONSTITUTION = recovered.get("landing/src/lib/constitution.json", bsn.CONSTITUTION)
        rebuilt = bsn.build(published_at=doc.get("published_at"), source_commit=prov.get("source_commit"))
    except bsn.NotMeasured as exc:
        return {"outcome": NOT_MEASURED, "reason": f"rebuild not possible: {exc}", "findings": findings}
    except bsn.SequencingViolation as exc:
        findings.append(f"rebuild refused: {exc}")
        rebuilt = None
    finally:
        bsn.SNAPSHOT, bsn.CONSTITUTION = swap
    if rebuilt is not None and json.dumps(rebuilt, sort_keys=True) != json.dumps(doc, sort_keys=True):
        diff = sorted(k for k in set(rebuilt) | set(doc) if rebuilt.get(k) != doc.get(k))
        findings.append(f"site_numbers ≠ rebuild from canonical inputs (fields: {diff})")
    findings += check_types(doc, bsn)
    # mapping
    rows = doc.get("profiles")
    if not isinstance(rows, list) or not rows:
        findings.append("product mapping missing from the artifact")
    else:
        findings += [f"mapping: {c}" for c in product_map.conflicts(rows)]
    # dates and cadence
    try:
        meas, pub, now = (date.fromisoformat(str(doc.get("measured_at"))),
                          date.fromisoformat(str(doc.get("published_at"))), date.fromisoformat(today))
    except ValueError:
        return {"outcome": NOT_MEASURED, "reason": "measured_at/published_at not parseable", "findings": findings}
    if (now - meas).days > MAX_MEASUREMENT_AGE_DAYS:
        findings.append(f"stale measurement: measured {meas}, {(now - meas).days} d ago (> {MAX_MEASUREMENT_AGE_DAYS} d)")
    if (pub - meas).days > MAX_MEASUREMENT_LAG_DAYS:
        findings.append(f"stale measurement date: measured {meas} for publication {pub} (> {MAX_MEASUREMENT_LAG_DAYS} d)")
    if (now - pub).days >= cadence.CADENCE_DAYS:
        findings.append(f"stale publication artifact: published_at {pub} is {(now - pub).days} d old (cadence {cadence.CADENCE_DAYS} d)")
    want_next = cadence.next_publication(pub.isoformat())
    if doc.get("next_publication") != want_next:
        findings.append(f"cadence conflict: next_publication {doc.get('next_publication')!r} ≠ rule {want_next!r}")
    if published is None:
        return {"outcome": NOT_MEASURED, "reason": "published shelf location unknown (no mirror, no "
                "$SPA_PUBLISHED_SHELF, no --published) — cannot judge cadence, age or approval",
                "findings": findings}
    pub_doc = _read(published)
    if pub_doc is None:
        return {"outcome": NOT_MEASURED, "reason": f"published shelf not readable: {published}", "findings": findings}
    live_pub = cadence.published_at(pub_doc)
    if live_pub and pub.isoformat() < live_pub:
        findings.append(f"candidate older than the live publication ({pub} < {live_pub})")
    findings += check_approval(doc, pub_doc, approval, bsn, bsn._sha256(Path(shelf)))
    if pages is not None:
        findings += [f"page reads a deprecated field: {x}" for x in scan_pages(pages)]
    return {"outcome": FAIL if findings else PASS, "reason": None, "findings": findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fail-closed gate between BUILD and PUBLISH (ADR-630)")
    ap.add_argument("--shelf", default=str(ROOT / "landing" / "src" / "data" / "site_numbers.json"))
    ap.add_argument("--published", default=None,
                    help="the PUBLISHED shelf (default: $SPA_PUBLISHED_SHELF or the origin mirror)")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--approval", default=None, help="owner card closing the publication gate")
    ap.add_argument("--find-approval", action="store_true",
                    help="look up the owner-closed card naming this shelf in the tracker")
    ap.add_argument("--pages", default=str(ROOT / "landing" / "src"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    pub = cadence.published_shelf_path(a.published)
    approval = a.approval
    if approval is None and a.find_approval:
        d = _read(Path(a.shelf))
        approval = find_approval(d, _load_bsn()._sha256(Path(a.shelf))) if d else None
    res = verify(shelf=Path(a.shelf), published=pub, today=a.today, approval=approval,
                 pages=Path(a.pages) if a.pages else None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        head = {PASS: "PASS", FAIL: "FAIL", NOT_MEASURED: "NOT MEASURED"}[res["outcome"]]
        print(f"{head}" + (f" — {res['reason']}" if res.get("reason") else ""))
        for f in res["findings"]:
            print(f"  - {f}")
    return res["outcome"]


if __name__ == "__main__":
    raise SystemExit(main())
