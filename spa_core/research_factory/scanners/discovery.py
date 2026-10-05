"""spa_core/research_factory/scanners/discovery.py — DeFi discovery track (ADR-560 WP-S05).

Projects ``data/candidate_registry.json`` (``adapter_sdk/discovery.py`` via
``paper_trading/discovery_step.py``) into DISCOVERED candidates — the ADR's own words: "REUSE as
the DeFi intake; defects recorded (age gate never measured; Sky slug miss)". Both named defects
are carried through here, never silently repaired:

* **age gate never measured** — every row's ``age_days`` is ``null`` / ``gates_unknown`` includes
  ``"age"`` (``adapter_sdk/discovery.py:pool_age_days`` has no inception-date source); this
  scanner's ``duration`` cell says so explicitly rather than treating "unknown age" as "any age".
* **the "sky-lending" slug escapes the coverage check** — ``covered_protocol_slugs()`` matches by
  SUBSTRING against the live adapter-registry heads (``spark``, ``sdai`` …); "sky-lending" matches
  neither, so its SUSDS/SDAI pools are discovered as if new, even though their ``pool_id`` is
  EXACTLY the live book's ``spark_susds``/``sdai`` pool id (confirmed against
  ``data/adapter_status.json`` on the prod snapshot this was built against). This scanner gives
  those two instruments the SAME ``underlying_root`` the live-book adapters use
  (``cash_treasury.ROOT_SKY_SAVINGS``) so Package A's dedup recognises the collision — it does
  NOT drop or relabel the candidate itself (that would hide the defect, not fix it).

Mechanism inference is deliberately conservative: a handful of keyword rules
(lending/savings/credit/rwa/curator/vault/LP) classify what the DeFiLlama project name plainly
says; anything else goes to ``unresolved`` rather than a guess (per the ADR: "if unclear ⇒
unresolved"). The six "Midas RWA" USDC pools across four chains are six distinct candidates (six
distinct ``pool_id``s), never merged by symbol (review #2).

LLM_FORBIDDEN, stdlib only, no network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from spa_core.adapter_sdk.candidate_registry import read_candidate_registry
from spa_core.research_factory import contract, counterparty_registry
from spa_core.research_factory.scanners._common import (empty_result, full_candidate, not_applicable,
                                                          not_measured, read_json)
from spa_core.research_factory.scanners.cash_treasury import PROTOCOL_ROOT_MAP, ROOT_SKY_SAVINGS

SCANNER_NAME = "discovery"
DOMAIN = "DEFI_DISCOVERY"

#: (project, symbol) → (mechanism_id, underlying_root override|None, economic_driver_key|None) —
#: the one named collision the ADR calls out (review #2/#3): these pool_ids equal the live book's
#: own spark_susds/sdai pool_ids, so they share the Sky-savings root, not a fresh one.
_KNOWN_OVERRIDES = {
    ("sky-lending", "SUSDS"): ("STABLECOIN_SAVINGS", ROOT_SKY_SAVINGS, "SKY_SSR"),
    ("sky-lending", "SDAI"): ("STABLECOIN_SAVINGS", ROOT_SKY_SAVINGS, "MAKER_DSR"),
}


def _infer_mechanism(project: str, symbol: str) -> "str | None":
    """Conservative keyword inference from the DeFiLlama project id. Returns ``None`` (⇒
    unresolved) when nothing recognisable matches — never a default guess."""
    p = str(project or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    if (p, sym) in _KNOWN_OVERRIDES:
        return _KNOWN_OVERRIDES[(p, sym)][0]
    if "-" in sym and len([s for s in sym.split("-") if s]) >= 2:
        return "STABLE_LP"
    if "credit" in p:
        return "RWA_CREDIT"
    if "rwa" in p:
        return "RWA_CREDIT"
    if "lend" in p:
        return "LENDING"
    if "curator" in p or "vault" in p:
        return "VAULT_AGGREGATOR"
    return None


def _root_and_driver(project: str, symbol: str, instrument_id: str) -> "tuple[str, str | None]":
    override = _KNOWN_OVERRIDES.get((str(project or "").strip().lower(), str(symbol or "").strip().upper()))
    if override:
        return override[1], override[2]
    return instrument_id, None


def _existing_book_roots(data_dir: Path) -> list:
    roots = set()
    cur, _ = read_json(data_dir / "current_positions.json")
    if isinstance(cur, dict):
        for p in (cur.get("feed_coverage") or {}).get("live_adapters") or []:
            r = PROTOCOL_ROOT_MAP.get(str(p))
            if r:
                roots.add(r)
        for p in (cur.get("positions") or {}):
            r = PROTOCOL_ROOT_MAP.get(str(p))
            if r:
                roots.add(r)
    for fname in ("hy_paper_trading.json", "lp_paper_trading.json"):
        doc, _ = read_json(data_dir / fname)
        if isinstance(doc, dict):
            for pos in doc.get("positions") or []:
                if isinstance(pos, dict):
                    r = PROTOCOL_ROOT_MAP.get(str(pos.get("protocol")))
                    if r:
                        roots.add(r)
    return sorted(roots)


def scan(data_dir, now: datetime, *, rpc_client=None) -> dict:
    data_dir = Path(data_dir)
    as_of = now.isoformat()
    # the candidates and their measurement honesty come through the ONE canonical reader
    # (adapter_sdk.candidate_registry; test_candidate_registry_readers pins every module touching the
    # registry): an unread registry is `measured=False` with its reason — UNAVAILABLE, never zero rows.
    reg = read_candidate_registry(data_dir)
    existing_book_roots = _existing_book_roots(data_dir)
    if not reg["measured"]:
        res = empty_result(SCANNER_NAME, DOMAIN, as_of, "UNAVAILABLE", reg["reason"])
        res["existing_book_roots"] = existing_book_roots
        return res

    rows = reg["items"]
    # the same file's METADATA (generated_at / scanned_pools / gates) is not part of the canonical reader's
    # answer; read it alone — a missing/odd document only makes those cells NOT_MEASURED below
    doc, err = read_json(data_dir / "candidate_registry.json")
    if not isinstance(doc, dict):
        doc = {}
    # re-review L9: two reads of one file — if the writer replaced it in between, the metadata describes
    # different rows; say so (PARTIAL, metadata cells NOT_MEASURED) instead of mixing two versions
    if isinstance(doc.get("candidates"), list) and \
            [c for c in doc["candidates"] if isinstance(c, dict)] != rows:
        err = "candidate_registry.json changed between the canonical read and the metadata read"
        doc = {}
    scanned = doc.get("scanned_pools")
    gates = doc.get("gates") if isinstance(doc.get("gates"), dict) else {}
    max_candidates = gates.get("max_candidates")
    # review H1: never default to the scan clock — a missing 'generated_at' makes the dependent
    # cells below NOT_MEASURED (has_as_of=False), not MEASURED-with-the-wrong-time.
    generated_at = doc.get("generated_at") if isinstance(doc.get("generated_at"), str) else None
    has_as_of = generated_at is not None

    candidates, observations, counterparty, unresolved = [], {}, {}, []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pool_id, project, symbol, chain = row.get("pool_id"), row.get("protocol"), row.get("symbol"), row.get("chain")
        apy_pct, tvl_usd, age_days = row.get("apy_pct"), row.get("tvl_usd"), row.get("age_days")
        name = f"{project}:{symbol}@{chain}" if project and symbol else str(pool_id)
        if not isinstance(pool_id, str) or not pool_id:
            unresolved.append({"name": name, "reason": "candidate row has no pool_id"})
            continue
        instrument_id = f"llama:{pool_id.lower()}"
        network = contract.canonical_network(chain)
        if network is None:
            unresolved.append({"name": name, "reason": f"unknown chain alias {chain!r} — no canonical network"})
            continue
        mechanism_id = _infer_mechanism(project, symbol)
        if mechanism_id is None:
            unresolved.append({"name": name,
                               "reason": f"DeFiLlama project {project!r} does not match a recognisable "
                                         "mechanism keyword (lending/savings/credit/rwa/curator/vault/LP) — "
                                         "conservative inference leaves it unclassified rather than guessing"})
            continue

        root, driver = _root_and_driver(project, symbol, instrument_id)
        cells = {
            "base_return": (contract.cell(contract.MEASURED, float(apy_pct), unit="pct_apy",
                                          source_ref=f"data/candidate_registry.json#{pool_id}",
                                          source_class=contract.REPUTABLE_AGGREGATOR,
                                          source_root="defillama:yields", as_of=generated_at,
                                          recorded_at=now.isoformat(), now=now, window="spot")
                           if isinstance(apy_pct, (int, float)) and has_as_of else
                           not_measured("apy_pct missing for this pool" if not isinstance(apy_pct, (int, float))
                                       else "candidate_registry.json has no 'generated_at' timestamp to pin "
                                            "this rate to")),
            "incentive_return": not_measured("candidate_registry.json does not split apyBase/apyReward"),
            "quoted_return": not_applicable("freshly discovered pool; no issuer-advertised rate carried here"),
            "fees": not_measured("fee schedule not measured for a freshly discovered pool"),
            "gas": not_measured("gas cost not measured for a freshly discovered pool"),
            "hedging_cost": not_applicable("mechanism has no hedge leg") if mechanism_id not in
            ("SPOT_PERP_BASIS", "FUNDING_CAPTURE", "DELTA_NEUTRAL_CARRY") else
            not_measured("hedging cost not measured"),
            "funding": not_applicable("mechanism has no funding leg") if mechanism_id not in
            ("SPOT_PERP_BASIS", "FUNDING_CAPTURE", "DELTA_NEUTRAL_CARRY") else
            not_measured("funding leg not measured"),
            "duration": not_measured("age gate is never measured upstream (age_days="
                                      f"{age_days!r}, gates_unknown includes 'age') — "
                                      "adapter_sdk/discovery.py has no pool-inception-date source"),
            "liquidity": not_measured("exit liquidity not measured for a freshly discovered pool"),
            "time_to_exit": not_measured("exit timeline not measured for a freshly discovered pool"),
            "capacity": (contract.cell(contract.MEASURED, float(tvl_usd), unit="usd",
                                       source_ref=f"data/candidate_registry.json#{pool_id}",
                                       source_class=contract.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                       as_of=generated_at, recorded_at=now.isoformat(), now=now)
                        if isinstance(tvl_usd, (int, float)) and has_as_of else
                        not_measured("tvl_usd missing for this pool" if not isinstance(tvl_usd, (int, float))
                                    else "candidate_registry.json has no 'generated_at' timestamp to pin "
                                         "this value to")),
            "measured_return": not_applicable("pre-admission scan; no running paper account yet"),
            "realised_return": not_applicable("pre-admission scan; no running paper account yet"),
        }
        cells["net_expected_return"] = contract.net_expected_return(cells)

        cand = full_candidate(
            scanner=SCANNER_NAME, mechanism_id=mechanism_id, domain=DOMAIN, network=chain,
            instrument=str(symbol), instrument_id=instrument_id, venue_or_protocol=str(project),
            underlying_root=root, economic_driver_key=driver, yield_source="discovery",
            strategy_family="defi_discovery", return_window="spot", cells=cells, now=now,
        )
        candidates.append(cand)
        if cells["base_return"]["state"] == contract.MEASURED:
            observations[cand["candidate_id"]] = {"observed_return": cells["base_return"], "realised_index": None,
                                                   "period": now.date().isoformat()}
        counterparty[cand["candidate_id"]] = counterparty_registry.discovery_default(
            project, source_ref=f"data/candidate_registry.json#{pool_id}", mechanism_id=mechanism_id)

    truncated = max_candidates if isinstance(max_candidates, int) and len(rows) >= max_candidates else None
    status = "OK" if err is None else "PARTIAL"
    return {
        "scanner": SCANNER_NAME, "domain": DOMAIN, "as_of": as_of, "status": status, "reason": err,
        "denominators": {"scanned": scanned if isinstance(scanned, int) else None,
                         "discovered": len(candidates), "truncated": truncated},
        "candidates": candidates, "unresolved": unresolved, "observations": observations,
        "counterparty": counterparty, "existing_book_roots": existing_book_roots,
    }
