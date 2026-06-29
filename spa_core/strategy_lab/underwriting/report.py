# LLM_FORBIDDEN
"""spa_core.strategy_lab.underwriting.report — the hash-anchored, publicly-verifiable
UNDERWRITING REPORT (Lane C, Layer-3 moat productized as underwriting-grade risk infra).

WHAT THIS IS
============
The report is the artifact the desk SELLS: not deployed capital, but the MEASUREMENT + the
PROOF. It composes three already-produced verdicts into ONE tamper-evident document:

  1. per-market REFUSAL verdicts   (READ from data/refusal_status.json — the desk's discipline)
  2. depth-at-size                 (READ from Lane B's data/rates_desk/depth_at_size.json)
  3. the realized-at-size VERDICT  (READ from Lane B's data/rates_desk/realized_at_size.json —
                                    SURVIVES_AT / DOES_NOT_SURVIVE_PAST / INSUFFICIENT_DATA,
                                    survives_at_aum_usd, floor_plus_bps_at_5M)

Every SECTION of the report carries its own ``proof_hash`` (SHA-256 over the section's canonical
JSON), and each section is ALSO chained into ``report_proof.jsonl`` (a single-genesis, contiguous,
prev-linked hash chain — PROOF_CHAIN_SPEC §5 shape, ``event_type = "underwriting_report_section"``).
A skeptical third party re-derives every section proof_hash AND walks the chain with
``scripts/verify_spa.py`` (surface H) — NO ``spa_core`` import. Tamper → precise broken_at.

THE HONESTY RULE (anti-happy-laundering — the whole point of Lane C)
===================================================================
Lane C reads Lane B's killer verdict VERBATIM. It NEVER recomputes ``survives_at_aum_usd`` or any
other realized number — it copies B's value into the report byte-for-byte. ``read_realized_verbatim``
is the ONLY path to the realized verdict, and it is a pure passthrough. A guard test
(``test_underwriting_passthrough.py``) asserts the published ``survives_at_aum_usd`` equals the raw
JSON value byte-for-byte; a recompute path would diverge and the test fails loudly. There is, by
construction, no arithmetic in this module that touches the realized verdict.

REFUSAL-CONSISTENCY (red-team property)
=======================================
A market that the refusal layer REFUSED can NEVER appear as underwritten-capacity. ``build_report``
fail-CLOSED REFUSES to list a market in the realized/capacity section if that market's refusal
verdict is REFUSE — and a smoke test asserts the property holds even under an adversarially edited
input.

OWNER-GATED PUBLICATION
=======================
``SPA_UNDERWRITING_PUBLISH`` (default OFF). The report is ALWAYS generated and written to ``data/``
(so the proof chain grows and is verifiable), but it is NOT surfaced publicly (no API/landing
exposure) until the owner flips the flag — commercial sale of the underwriting report is owner-gated.
When OFF the written report carries ``"published": false`` and ``"publish_gate": "owner"``.

SAFETY
======
stdlib-only · deterministic (an explicit ``as_of``/``generated_at`` may be supplied for tests) ·
fail-CLOSED · atomic (tmp + os.replace, same-dir) · IS_ADVISORY=True (moves no capital, touches no
risk/execution, no go-live track) · NO ``spa_core.execution`` import.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── advisory / safety contract ───────────────────────────────────────────────────────────────────
IS_ADVISORY = True            # this report moves no capital; it is a measurement/proof artifact
RESEARCH_ONLY = True

# ── published invariants (MUST agree with scripts/verify_spa.py surface H) ─────────────────────────
UNDERWRITING_EVENT_TYPE = "underwriting_report_section"
GENESIS_PREV = "0" * 64
REPORT_SCHEMA_VERSION = "1.0"

# the owner flag — default OFF (commercial publication is owner-gated).
PUBLISH_FLAG_ENV = "SPA_UNDERWRITING_PUBLISH"

# the canonical verdict vocabulary copied VERBATIM from Lane B (never re-derived here).
_KILLER_VERDICTS = ("SURVIVES_AT", "DOES_NOT_SURVIVE_PAST", "INSUFFICIENT_DATA")
# refusal verdict vocabulary (read from the refusal layer; a REFUSE market cannot be underwritten).
_REFUSE_VERDICT = "REFUSE"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REALIZED = _REPO_ROOT / "data" / "rates_desk" / "realized_at_size.json"
_DEFAULT_DEPTH = _REPO_ROOT / "data" / "rates_desk" / "depth_at_size.json"
_DEFAULT_REFUSAL = _REPO_ROOT / "data" / "refusal_status.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "underwriting" / "underwriting_report.json"
_DEFAULT_PROOF = _REPO_ROOT / "data" / "underwriting" / "report_proof.jsonl"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# canonical JSON + the section hash recipe (inlined per PROOF_CHAIN_SPEC §2/§3 — no shared lib so the
# standalone verifier can reproduce it with zero spa_core import)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _canonical(obj: Any) -> str:
    """The ONE canonical-JSON rule (PROOF_CHAIN_SPEC §2): sort_keys recursive, compact, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def section_proof_hash(section_body: Dict[str, Any]) -> str:
    """The per-section proof_hash: SHA-256 over the canonical JSON of the section body alone (the
    section MINUS its own ``proof_hash``/envelope). Independent of chain position — a third party
    recomputes it from the published section content. Deterministic / PURE."""
    body = {k: v for k, v in section_body.items()
            if k not in ("proof_hash", "seq", "prev_hash", "entry_hash")}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def chain_entry_hash(seq: int, section_id: str, payload: Dict[str, Any], prev_hash: str) -> str:
    """The §3 chain entry_hash over canonical({seq, section_id, event_type, payload, prev_hash}).

    ``payload`` is the section body (which already carries its own ``proof_hash``), so the chain
    binds the section proof into the prev-linked chain. ``event_type`` is the fixed constant. This is
    the recipe the standalone verifier reproduces (surface H)."""
    canonical = _canonical({
        "seq": seq,
        "section_id": section_id,
        "event_type": UNDERWRITING_EVENT_TYPE,
        "payload": payload,
        "prev_hash": prev_hash,
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# VERBATIM passthrough readers (the anti-happy-laundering core — NO recompute, EVER)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"unreadable: {e}"
    except json.JSONDecodeError as e:
        return None, f"corrupt JSON: {e}"


def read_realized_verbatim(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """Read Lane B's killer verdict (``realized_at_size.json``) and return its fields VERBATIM.

    THIS IS THE ONLY PATH TO THE REALIZED VERDICT. It performs NO arithmetic, NO re-derivation, NO
    "fix-up" of B's numbers — it copies the bytes B published. The returned dict preserves B's exact
    ``verdict`` / ``survives_at_aum_usd`` / ``floor_plus_bps_at_5M`` values (whatever their JSON type:
    a number stays a number, a string a string, null null). fail-CLOSED: a missing/corrupt file, or a
    verdict outside B's vocabulary, → (None, error).

    The honesty guarantee: ``report.survives_at_aum_usd`` is THIS value, byte-for-byte. A guard test
    asserts equality against the raw JSON; there is no code path here that could launder a happier
    number."""
    doc, err = _read_json(path)
    if err is not None:
        return None, f"realized_at_size: {err}"
    if not isinstance(doc, dict):
        return None, "realized_at_size: not a JSON object"
    verdict = doc.get("verdict")
    if verdict not in _KILLER_VERDICTS:
        return None, (f"realized_at_size: verdict {verdict!r} not in Lane B's vocabulary "
                      f"{_KILLER_VERDICTS} (fail-CLOSED — refuse to publish an unknown verdict)")
    # copy the load-bearing fields VERBATIM — whatever type/value B published, unchanged.
    return {
        "verdict": verdict,                                       # B's killer verdict, verbatim
        "survives_at_aum_usd": doc.get("survives_at_aum_usd"),    # VERBATIM — never recomputed
        "floor_plus_bps_at_5M": doc.get("floor_plus_bps_at_5M"),  # VERBATIM
        "as_of": doc.get("as_of"),
        "data_source": doc.get("data_source"),
        "markets": _verbatim_market_list(doc.get("markets")),
    }, None


def _verbatim_market_list(markets: Any) -> List[dict]:
    """Pass Lane B's per-market realized rows through verbatim (drop non-dict junk; preserve values).
    No number is touched."""
    if not isinstance(markets, list):
        return []
    out: List[dict] = []
    for m in markets:
        if isinstance(m, dict):
            out.append(dict(m))  # shallow copy, values unchanged
    return out


def read_depth_verbatim(path: Path) -> Tuple[dict, Optional[str]]:
    """Read Lane B's depth-at-size (``depth_at_size.json``) verbatim. Returns ({} , err) on a
    missing/corrupt file — the depth section is then marked unavailable but the report still builds
    (the realized verdict + refusals are the load-bearing sections). PURE passthrough; no recompute."""
    doc, err = _read_json(path)
    if err is not None:
        return {}, f"depth_at_size: {err}"
    return (doc if isinstance(doc, dict) else {}), None


def read_refusals_verbatim(path: Path) -> Tuple[List[dict], Optional[str]]:
    """Read the per-market refusal verdicts from ``refusal_status.json`` verbatim. Returns the list of
    {symbol, group, verdict, tail_score, reason} rows (values unchanged). fail-CLOSED on a corrupt
    file. An absent file → ([], None) (no refusal section, report still builds)."""
    doc, err = _read_json(path)
    if err is not None:
        return [], f"refusal_status: {err}"
    if not isinstance(doc, dict):
        return [], "refusal_status: not a JSON object"
    rows = doc.get("underlyings")
    out: List[dict] = []
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append({
                "symbol": r.get("symbol"),
                "group": r.get("group"),
                "verdict": r.get("verdict"),       # SAFE / WATCH / REFUSE / UNKNOWN — verbatim
                "tail_score": r.get("tail_score"),
                "reason": r.get("reason"),
            })
    return out, None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# report assembly (deterministic; every section gets a proof_hash; sections chained)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _refused_symbols(refusals: List[dict]) -> set:
    """The set of market symbols the refusal layer REFUSED (verdict == REFUSE). A refused market can
    NEVER appear as underwritten-capacity (refusal-consistency)."""
    return {r.get("symbol") for r in refusals
            if isinstance(r, dict) and r.get("verdict") == _REFUSE_VERDICT}


def _capacity_markets(realized: dict, refused: set) -> Tuple[List[dict], List[str]]:
    """Split Lane B's realized per-market rows into the underwritten-capacity list, fail-CLOSED
    EXCLUDING any market the refusal layer REFUSED. Returns (capacity_markets, excluded_symbols).
    The excluded list is published so the exclusion is auditable (refusal-consistency, red-team #3)."""
    capacity: List[dict] = []
    excluded: List[str] = []
    for m in realized.get("markets", []):
        sym = m.get("symbol") or m.get("market_id") or m.get("underlying")
        if sym in refused:
            excluded.append(sym)
            continue
        capacity.append(m)
    return capacity, sorted(x for x in excluded if x is not None)


def build_report(
    *,
    realized_path: Optional[Path] = None,
    depth_path: Optional[Path] = None,
    refusal_path: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    """Assemble the hash-anchored underwriting report. Returns (report, None) or (None, error).

    The report is a dict with a single-genesis chain of SECTIONS; each section carries its own
    ``proof_hash`` (over the section body) AND chain envelope (``seq``/``prev_hash``/``entry_hash``)
    so the same content is verifiable two ways: per-section AND as a contiguous chain (surface H).

    Sections (in chain order):
      0. ``meta``      — schema/version/advisory flags/publish gate
      1. ``refusals``  — the per-market refusal verdicts (the discipline)  [VERBATIM]
      2. ``depth``     — depth-at-size                                     [VERBATIM, Lane B]
      3. ``realized``  — the killer verdict + survives_at_aum_usd          [VERBATIM, Lane B]
      4. ``capacity``  — underwritten-capacity markets, REFUSE markets EXCLUDED (refusal-consistency)

    fail-CLOSED: a missing/corrupt/unknown-verdict realized file → (None, error). The depth/refusal
    sections degrade to ``available: false`` rather than failing the whole report (the realized
    verdict + refusals are load-bearing; depth is supporting).

    Deterministic: same inputs + same ``generated_at`` → byte-identical report (incl. all hashes)."""
    realized, rerr = read_realized_verbatim(realized_path or _DEFAULT_REALIZED)
    if rerr is not None:
        return None, rerr  # fail-CLOSED: no realized verdict → no report

    depth, derr = read_depth_verbatim(depth_path or _DEFAULT_DEPTH)
    refusals, ferr = read_refusals_verbatim(refusal_path or _DEFAULT_REFUSAL)
    if ferr is not None:
        # a CORRUPT refusal file is fail-CLOSED (we cannot prove refusal-consistency without it).
        return None, ferr

    refused = _refused_symbols(refusals)
    capacity_markets, excluded = _capacity_markets(realized, refused)

    published = is_publish_enabled()

    # ── the ordered section BODIES (each gets its own proof_hash; then chained) ──
    section_bodies: List[Tuple[str, dict]] = []

    section_bodies.append(("meta", {
        "section_id": "meta",
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_kind": "underwriting_report",
        "is_advisory": IS_ADVISORY,
        "llm_forbidden": True,
        "deterministic": True,
        "published": bool(published),                 # owner gate (default False)
        "publish_gate": "owner",
        "publish_flag_env": PUBLISH_FLAG_ENV,
        "generated_at": generated_at,
        "honesty_rule": ("realized verdict (survives_at_aum_usd / floor_plus_bps_at_5M) is copied "
                         "VERBATIM from Lane B's realized_at_size.json — never recomputed here"),
    }))

    section_bodies.append(("refusals", {
        "section_id": "refusals",
        "available": bool(refusals),
        "n_markets": len(refusals),
        "n_refused": len(refused),
        "verdicts": refusals,                          # VERBATIM per-market refusal verdicts
        "data_source": "data/refusal_status.json",
    }))

    section_bodies.append(("depth", {
        "section_id": "depth",
        "available": bool(depth),
        "depth_at_size": depth,                        # VERBATIM, Lane B (or {} if unavailable)
        "data_source": "data/rates_desk/depth_at_size.json",
    }))

    section_bodies.append(("realized", {
        "section_id": "realized",
        # ── THE LOAD-BEARING VERBATIM FIELDS — copied byte-for-byte from Lane B, NEVER recomputed ──
        "verdict": realized["verdict"],
        "survives_at_aum_usd": realized["survives_at_aum_usd"],
        "floor_plus_bps_at_5M": realized["floor_plus_bps_at_5M"],
        "as_of": realized.get("as_of"),
        "data_source": "data/rates_desk/realized_at_size.json",
        "passthrough": "VERBATIM_FROM_LANE_B",
    }))

    section_bodies.append(("capacity", {
        "section_id": "capacity",
        "n_capacity_markets": len(capacity_markets),
        "capacity_markets": capacity_markets,          # REFUSE markets are EXCLUDED below
        "excluded_refused_markets": excluded,          # auditable refusal-consistency record
        "refusal_consistency": ("a market REFUSED by the refusal layer is EXCLUDED from "
                                "underwritten capacity — fail-CLOSED"),
    }))

    # ── seal each section: its own proof_hash, then chain them (single genesis) ──
    sections: List[dict] = []
    prev = GENESIS_PREV
    for seq, (section_id, body) in enumerate(section_bodies):
        body = dict(body)
        body["proof_hash"] = section_proof_hash(body)   # per-section anchor (over the body)
        entry_hash = chain_entry_hash(seq, section_id, body, prev)
        sections.append({"seq": seq, "section_id": section_id, "prev_hash": prev,
                         "entry_hash": entry_hash, **body})
        prev = entry_hash

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_kind": "underwriting_report",
        "generated_at": generated_at,
        "published": bool(published),
        "publish_gate": "owner",
        "publish_flag_env": PUBLISH_FLAG_ENV,
        "is_advisory": IS_ADVISORY,
        "llm_forbidden": True,
        "deterministic": True,
        "event_type": UNDERWRITING_EVENT_TYPE,
        "head_hash": prev,                              # last section's entry_hash (chain head)
        "n_sections": len(sections),
        "sections": sections,
    }
    return report, None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# owner flag (C1.4)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def is_publish_enabled() -> bool:
    """The owner gate. Default OFF. ON only when SPA_UNDERWRITING_PUBLISH is an explicit truthy value
    ('1'/'true'/'yes'/'on', case-insensitive). Any other value (incl. unset, '', '0', 'false') → OFF.
    fail-CLOSED toward NOT publishing — commercial sale of the report is owner-gated."""
    raw = os.environ.get(PUBLISH_FLAG_ENV, "")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# verification helpers (the same recipe the standalone verifier uses — shared for the in-repo test)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_SECTION_ENVELOPE = ("seq", "prev_hash", "entry_hash")


def verify_report_chain(sections: List[dict]) -> dict:
    """Verify the report's section chain (PROOF_CHAIN_SPEC §5 shape): walk in seq order; at each
    section require (1) seq == idx, (2) prev_hash == previous entry_hash (genesis '0'*64),
    (3) the per-section proof_hash recomputes over the body, (4) the chain entry_hash recomputes.
    Returns {valid, length, broken_at, head_hash}. fail-CLOSED. Empty is vacuously valid."""
    expected_prev = GENESIS_PREV
    head_hash: Optional[str] = None
    n = len(sections)
    for idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if sec.get("seq") != idx:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if sec.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        # body = the section minus the chain envelope (it still carries its own proof_hash).
        body = {k: v for k, v in sec.items() if k not in _SECTION_ENVELOPE}
        # (3) per-section proof_hash recompute
        if section_proof_hash(body) != sec.get("proof_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        # (4) chain entry_hash recompute (over the full body incl. its proof_hash)
        try:
            recomputed = chain_entry_hash(sec.get("seq"), sec.get("section_id"), body,
                                          sec.get("prev_hash"))
        except Exception:  # noqa: BLE001 — malformed section → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != sec.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = sec["entry_hash"]
        head_hash = sec["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# atomic writers (tmp + os.replace, same dir → no cross-device EXDEV)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _atomic_write_text(text: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(dst))


def write_report(
    *,
    realized_path: Optional[Path] = None,
    depth_path: Optional[Path] = None,
    refusal_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    proof_path: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Build the report and atomically write BOTH artifacts:
      • ``underwriting_report.json`` — the full document (the report itself), and
      • ``report_proof.jsonl``       — the section chain as JSONL (surface H verifies THIS file).

    OWNER GATE (C1.4): the report is ALWAYS written to ``data/`` (the proof chain must grow + be
    verifiable), but ``published`` is False unless ``SPA_UNDERWRITING_PUBLISH`` is set. Nothing here
    surfaces the report to the API/landing — that wiring stays behind the flag, off-code this week.

    Returns a small report dict; fail-CLOSED raises nothing for a missing realized file — it returns
    {"ok": False, "error": ...} and writes NOTHING (no partial/forged artifact)."""
    report, err = build_report(realized_path=realized_path, depth_path=depth_path,
                               refusal_path=refusal_path, generated_at=generated_at)
    if err is not None or report is None:
        return {"ok": False, "error": err, "wrote": []}

    out = Path(out_path) if out_path is not None else _DEFAULT_OUT
    proof = Path(proof_path) if proof_path is not None else _DEFAULT_PROOF

    # the report document (pretty, sorted → stable diffs)
    _atomic_write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", out)

    # the proof JSONL: one line per section (the standalone verifier surface H walks THIS chain)
    lines = [json.dumps(sec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
             for sec in report["sections"]]
    _atomic_write_text(("\n".join(lines) + "\n") if lines else "", proof)

    return {
        "ok": True,
        "published": report["published"],
        "head_hash": report["head_hash"],
        "n_sections": report["n_sections"],
        "wrote": [str(out), str(proof)],
        "chain_valid": verify_report_chain(report["sections"])["valid"],
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.strategy_lab.underwriting.report",
        description="Build the hash-anchored, publicly-verifiable underwriting report (Lane C). "
                    "Reads Lane B's verdict VERBATIM. Owner-gated publication "
                    f"({PUBLISH_FLAG_ENV}, default OFF).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true",
                      help="build + atomically write underwriting_report.json + report_proof.jsonl")
    mode.add_argument("--check", action="store_true",
                      help="build in-memory, print the head hash + chain validity, write NOTHING")
    ap.add_argument("--realized", default=None, help="path to Lane B realized_at_size.json")
    ap.add_argument("--depth", default=None, help="path to Lane B depth_at_size.json")
    ap.add_argument("--refusal", default=None, help="path to refusal_status.json")
    ap.add_argument("--out", default=None, help="output report JSON path")
    ap.add_argument("--proof", default=None, help="output proof JSONL path")
    ap.add_argument("--generated-at", default=None, help="explicit ISO timestamp (determinism)")
    args = ap.parse_args(argv)

    def _p(v):
        return Path(v) if v else None

    if args.build:
        rep = write_report(realized_path=_p(args.realized), depth_path=_p(args.depth),
                           refusal_path=_p(args.refusal), out_path=_p(args.out),
                           proof_path=_p(args.proof), generated_at=args.generated_at)
        if not rep["ok"]:
            print(f"underwriting: FAILED (fail-CLOSED) — {rep['error']}", file=sys.stderr)
            return 1
        print(f"underwriting: wrote {rep['n_sections']} sections → {', '.join(rep['wrote'])}")
        print(f"underwriting: head_hash={rep['head_hash']}  chain_valid={rep['chain_valid']}  "
              f"published={rep['published']} (owner gate: {PUBLISH_FLAG_ENV})")
        return 0
    else:
        report, err = build_report(realized_path=_p(args.realized), depth_path=_p(args.depth),
                                   refusal_path=_p(args.refusal), generated_at=args.generated_at)
        if err is not None or report is None:
            print(f"underwriting: FAILED (fail-CLOSED) — {err}", file=sys.stderr)
            return 1
        res = verify_report_chain(report["sections"])
        print(f"underwriting: {report['n_sections']} sections (read-only, nothing written)")
        print(f"underwriting: head_hash={report['head_hash']}  chain_valid={res['valid']}  "
              f"published={report['published']}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
