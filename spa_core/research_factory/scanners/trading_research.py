"""spa_core/research_factory/scanners/trading_research.py — projected engine track (ADR-560 WP-S06).

``trading_research/status.json`` (ADR-525's own lifecycle/evidence engine, live, BTC-only) is
projected READ-ONLY into the factory: domain ``TRADING_RESEARCH``, every candidate
``engine:trading_research:<id>``. The ADR is explicit that this domain is ``PROJECT_ONLY``
(``contract.DOMAIN_DECISIONS``) and that every candidate here is ``admission_state=OBSERVE_ONLY``
— set by Package A from the declared ``domain``, never by this scanner (Appendix I: "A owns
them"). This module never re-runs, re-admits or re-scores the engine's own evidence; it reads
exactly what ``status.json`` already reports.

The status file carries only the CURRENT shortlist (the candidates presently in
``FORWARD_PAPER``) plus aggregate stage counts for the other 133 — it has no per-candidate
record for a REJECTED strategy, so this scanner cannot (and does not try to) project one. Payload
kept small per the Appendix-I interface: id, stage, and a verdict derived from the engine's own
``forward_net`` sign — never a re-derived score.

LLM_FORBIDDEN, stdlib only, no network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from spa_core.research_factory import contract, counterparty_registry
from spa_core.research_factory.scanners._common import (empty_result, full_candidate, not_applicable,
                                                          not_measured, read_json, sanitize_id_component)

SCANNER_NAME = "trading_research"
DOMAIN = "TRADING_RESEARCH"


def _verdict(forward_net) -> str:
    if not isinstance(forward_net, (int, float)):
        return "FORWARD_PAPER_UNVERIFIED"
    if forward_net > 0:
        return "FORWARD_PAPER_POSITIVE"
    if forward_net < 0:
        return "FORWARD_PAPER_NEGATIVE"
    return "FORWARD_PAPER_FLAT"


def scan(data_dir, now: datetime, *, rpc_client=None) -> dict:
    data_dir = Path(data_dir)
    as_of = now.isoformat()
    doc, err = read_json(data_dir / "trading_research" / "status.json")
    if not isinstance(doc, dict):
        return empty_result(SCANNER_NAME, DOMAIN, as_of, "UNAVAILABLE", err or "status.json malformed")

    total_candidates = doc.get("candidates")
    generated_ms = doc.get("generated_at_ms")
    # review H1: never default to the scan clock — status.json's OWN generated_at_ms is the
    # engine's true report time; absent that, doc_as_of is None and the realised_return cell
    # below becomes NOT_MEASURED rather than MEASURED-with-the-wrong-time.
    doc_as_of = (datetime.fromtimestamp(generated_ms / 1000.0, tz=timezone.utc).isoformat()
                if isinstance(generated_ms, (int, float)) else None)
    shortlist = doc.get("shortlist") if isinstance(doc.get("shortlist"), list) else []

    candidates, observations, counterparty = [], {}, {}
    for row in shortlist:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        raw_id = str(row["id"])
        engine_id = f"engine:trading_research:{sanitize_id_component(raw_id)}"
        forward_net = row.get("forward_net")
        verdict = _verdict(forward_net)

        cells = {
            "base_return": not_applicable("projected OBSERVE_ONLY engine candidate; not a yield-bearing position"),
            "incentive_return": not_applicable("no incentive leg for a directional trading strategy"),
            "quoted_return": not_applicable("internal research engine; nothing is advertised"),
            "realised_return": (contract.cell(contract.MEASURED, float(forward_net), unit="fraction",
                                              source_ref=f"data/trading_research/status.json#shortlist:{raw_id}",
                                              source_class=contract.PRIMARY_PROTOCOL,
                                              source_root="engine:trading_research", as_of=doc_as_of,
                                              recorded_at=now.isoformat(), now=now, window="since_admission",
                                              method=f"trading_research's own forward_net over "
                                                     f"{row.get('forward_bars')!r} forward bars; verdict={verdict}")
                                if isinstance(forward_net, (int, float)) and doc_as_of is not None else
                                not_measured("forward_net missing for this shortlist entry" if not
                                            isinstance(forward_net, (int, float)) else
                                            "status.json has no 'generated_at_ms' timestamp to pin this "
                                            "observation to")),
            "measured_return": not_measured("oos_sharpe/oos_max_drawdown are ratios, not return values — "
                                            "carried nowhere else; see source_ref for the raw figures"),
            "fees": not_measured("not exposed by trading_research/status.json"),
            "gas": not_applicable("spot/backtest strategy; no gas leg modelled here"),
            "hedging_cost": not_applicable("not a hedged position"),
            "funding": not_applicable("spot strategy per the engine's own shortlist ids (spot_long)"),
            "duration": not_measured("holding duration not exposed by status.json"),
            "liquidity": not_applicable("research engine; no paper capital deployed"),
            "time_to_exit": not_applicable("research engine; no paper capital deployed"),
            "capacity": not_applicable("research engine; no paper capital deployed"),
        }
        cells["net_expected_return"] = contract.net_expected_return(cells)

        cand = full_candidate(
            scanner=SCANNER_NAME, mechanism_id="DIRECTIONAL_TREND", domain=DOMAIN, network="offchain",
            instrument=raw_id, instrument_id=engine_id, venue_or_protocol="trading_research",
            underlying_root=engine_id, economic_driver_key=None, yield_source="FORWARD_PAPER",
            strategy_family="trading_research", return_window="since_admission", cells=cells, now=now,
        )
        candidates.append(cand)
        if cells["realised_return"]["state"] == contract.MEASURED:
            observations[cand["candidate_id"]] = {"observed_return": cells["realised_return"],
                                                   "realised_index": None, "period": now.date().isoformat()}
        counterparty[cand["candidate_id"]] = counterparty_registry.trading_research_default()

    status = "OK" if err is None else "PARTIAL"
    return {
        "scanner": SCANNER_NAME, "domain": DOMAIN, "as_of": as_of, "status": status, "reason": err,
        "denominators": {"scanned": total_candidates if isinstance(total_candidates, int) else None,
                         "discovered": len(candidates),
                         # the other stage-count entries (e.g. 133 REJECTED) exist in the engine's
                         # own lifecycle but status.json carries no per-candidate record for them —
                         # "truncated" names that gap honestly rather than pretending it is zero.
                         "truncated": (total_candidates - len(candidates))
                         if isinstance(total_candidates, int) else None},
        "candidates": candidates, "unresolved": [], "observations": observations,
        "counterparty": counterparty, "existing_book_roots": [],
    }
