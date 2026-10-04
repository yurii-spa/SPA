"""spa_core/research_factory/scanners/_common.py — shared helpers for the five Package-B scanners.

Not part of the frozen B→A scanner interface (``contract.py`` / Appendix I) — a private module
inside the ``scanners`` package so the five scanner modules do not each hand-roll the same
"read a JSON file without raising" / "every candidate carries every field" plumbing. Imported by
absolute submodule path (``from spa_core.research_factory.scanners._common import ...``) so it
never depends on ``scanners/__init__.py`` having finished running.

LLM_FORBIDDEN, stdlib only, no network, never writes a file (scanners are read-only by contract).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from spa_core.research_factory import contract

#: a candidate dict missing one of these is a scanner bug, not a possible real-world state —
#: every candidate this package emits is built through :func:`full_candidate`, which fills all of
#: them, so this is only a defensive assertion surface for the tests.
_REQUIRED_FIELDS = contract.CANDIDATE_FIELDS


def read_json(path: Path) -> "tuple[Optional[Any], Optional[str]]":
    """Load one JSON file. Never raises: ``(doc, None)`` on success, ``(None, reason)`` on any
    failure (missing file, unreadable, malformed JSON) — a scanner turns ``reason`` into its own
    ``status``/``reason``, it never crashes on a producer's bad day."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, f"{path.name} absent"
    except Exception as exc:  # noqa: BLE001 — malformed input is a named outcome, never a crash
        return None, f"{path.name} unreadable: {type(exc).__name__}: {exc}"


def empty_result(scanner: str, domain: str, as_of: str, status: str, reason: Optional[str],
                  denominators: Optional[dict] = None) -> dict:
    """A scanner result with nothing found — used for UNAVAILABLE and for a clean, empty OK/PARTIAL
    run. Every key the Appendix-I scanner interface promises is present, even when empty."""
    return {
        "scanner": scanner, "domain": domain, "as_of": as_of, "status": status, "reason": reason,
        "denominators": denominators or {"scanned": None, "discovered": 0, "truncated": None},
        "candidates": [], "unresolved": [], "observations": {}, "counterparty": {},
        "existing_book_roots": [],
    }


def not_measured(reason: str) -> dict:
    return contract.cell(contract.NOT_MEASURED, reason=reason)


def not_applicable(reason: str) -> dict:
    return contract.cell(contract.NOT_APPLICABLE, reason=reason)


#: the 10 risk dimensions are a future-work scoring layer (advisory, built elsewhere per the
#: ADR) — no Package-B scanner computes any of them; every candidate says so explicitly rather
#: than silently omitting the field (invariant #17: absence is a named value, never a 0 or a gap).
_RISK_REASON = "risk scoring is not performed by the Package-B scanners (ADR-560 WP-B)"


def full_candidate(*, scanner: str, mechanism_id: str, domain: str, network: str,
                    instrument: str, instrument_id: str, venue_or_protocol: str,
                    underlying_root: Optional[str], economic_driver_key: Optional[str],
                    yield_source: str, exposure: Optional[str] = None,
                    underlying_assets: Optional[list] = None, collateral: Optional[list] = None,
                    strategy_family: Optional[str] = None, return_window: Optional[str] = None,
                    correlation_features: Optional[list] = None, regime_dependency: Optional[str] = None,
                    cells: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """Every ``contract.CANDIDATE_FIELDS`` key, filled. ``exposure`` is
    ``contract.exposure_key(mechanism_id, instrument_id, network)`` — computed here so every
    scanner builds it the same way; raises exactly as :func:`contract.exposure_key` does (the
    caller is expected to have already validated the id/network and route a failure to
    ``unresolved`` BEFORE calling this, per the Appendix-I contract: "unresolvable ⇒ a scanner
    records the candidate in unresolved").

    ``cells`` overrides the per-candidate value cells (``contract.CELL_FIELDS``); any cell not
    supplied defaults to NOT_MEASURED, naming the scanner that did not populate it — never a 0,
    never silently absent (invariant #17)."""
    mech = contract.MECHANISMS[mechanism_id]
    key = exposure if exposure is not None else contract.exposure_key(mechanism_id, instrument_id, network)
    cid = contract.candidate_id(key)
    canon_network = contract.canonical_network(network) or network
    cells = dict(cells or {})
    out_cells: dict = {}
    for f in contract.CELL_FIELDS:
        if f in cells:
            out_cells[f] = cells[f]
        elif f in ("leverage", "liquidation_distance") and not mech["leverage_required"]:
            out_cells[f] = not_applicable(f"{mechanism_id} does not require leverage")
        else:
            out_cells[f] = not_measured(f"{f} not populated by the {scanner} scanner")
    risk = {f: not_measured(_RISK_REASON) for f in contract.RISK_FIELDS}
    identity = {
        "candidate_id": cid, "exposure_key": key, "exposure_key_version": contract.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": mech["asset_class"], "domain": domain,
        "strategy_family": strategy_family, "network": canon_network, "venue_or_protocol": venue_or_protocol,
        "instrument": instrument, "instrument_id": instrument_id, "underlying_assets": underlying_assets,
        "underlying_root": underlying_root, "economic_driver_key": economic_driver_key,
        "yield_source": yield_source, "return_window": return_window, "collateral": collateral,
        "correlation_features": correlation_features, "regime_dependency": regime_dependency,
        "superseded_by": None,
    }
    state = {
        "source_quality": None, "data_freshness": None, "evidence_maturity": None, "unknowns": None,
        "source_refs": None,
        # A owns these three (Appendix I: "admission_state/paper_status/evidence_maturity left
        # None — A owns them"); Package B never sets them, including for an OBSERVE_ONLY /
        # projected candidate — A decides that from the scanner's declared ``domain``.
        "paper_status": None, "admission_state": None,
    }
    cand = {**identity, **out_cells, **risk, **state}
    if now is not None:
        derive_state_fields(cand, now)
    missing = [f for f in _REQUIRED_FIELDS if f not in cand]
    if missing:  # pragma: no cover — defensive; _REQUIRED_FIELDS mirrors the dict built above
        raise AssertionError(f"full_candidate: missing fields {missing}")
    return cand


def derive_state_fields(cand: dict, now: datetime) -> None:
    """Fills ``source_quality`` / ``data_freshness`` / ``unknowns`` / ``source_refs`` IN PLACE
    from whatever cells the scanner actually set on ``cand`` — computed once, generically, so the
    answer to "what did we actually learn about this candidate" cannot drift between scanners.

    ``source_refs`` is the list of the candidate's own VALUED cells (not a list of bare strings):
    Package A's ``admission.py:_source_provenance_acceptable`` reads ``source_class``/
    ``source_root``/``value`` directly off each entry (PRIMARY-root / aggregator+independent-root
    provenance check, review #4) — a plain ``source_ref`` string would not carry that."""
    unknowns, refs, classes, freshness = [], [], set(), {}
    for f in contract.CELL_FIELDS + contract.RISK_FIELDS:
        c = cand.get(f)
        if not isinstance(c, dict):
            continue
        if c.get("state") not in contract.VALUED_STATES:
            unknowns.append(f)
            continue
        refs.append(c)
        if c.get("source_class"):
            classes.add(c["source_class"])
        fresh = contract.is_fresh(c, now)
        if fresh is not None:
            freshness[f] = fresh
    cand["unknowns"] = unknowns
    cand["source_refs"] = refs
    cand["source_quality"] = sorted(classes) if classes else None
    cand["data_freshness"] = freshness or None


def sanitize_id_component(raw: str) -> str:
    """A free-form internal id (may contain ``@``, ``:``, spaces …) squeezed into the charset
    ``contract.INSTRUMENT_ID_RE`` allows for an ``engine:<engine>:<id>`` instrument id
    (``[A-Za-z0-9_\\-]+``). Deterministic, lossy-but-legible — never a hash standing in for a
    readable id when the readable id can simply be reshaped."""
    out = []
    for ch in str(raw):
        out.append(ch if ch.isalnum() or ch in "_-" else "-")
    squeezed = "".join(out)
    while "--" in squeezed:
        squeezed = squeezed.replace("--", "-")
    return squeezed.strip("-") or "unknown"
