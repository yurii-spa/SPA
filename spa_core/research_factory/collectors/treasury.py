"""spa_core/research_factory/collectors/treasury.py — ADR-564 (RM-EVIDENCE-01) package E3.

NAV/oracle observation rows for the four Phase-0 tokenised-Treasury instruments (BUIDL, USYC,
OUSG, USDY), per ``instruments.INSTRUMENTS``. Three legs, each its own ``channel``:

* on-chain oracle (``onchain.chainlink_round`` / ``ondo_price_data`` / ``ondo_asset_price``) —
  ``channel=on_chain``, the TRUE upstream timestamp each reader already derives;
* USYC's official API (``usyc.hashnote.com/api/price`` and ``/api/price-reports``) —
  ``channel=official_api``, origin ``issuer:hashnote`` (the SAME group as the on-chain oracle —
  this is the circularity the ADR requires to be recorded, not hidden: one origin, two channels);
* the matching DeFiLlama pool APY, chain-and-contract joined via ``instruments.py`` — ALWAYS
  ``channel=aggregator`` (never promoted past WEAK on its own, per ``evidence_contract.HTTP_ALLOW``'s
  comment: "aggregator channel ONLY").

``collect(now, client, *, rpc_client=None, prior=None, pools=None)`` returns
``evidence_contract.OBS_ROW_FIELDS`` rows, append-only. ``prior`` carries the previous
``getAssetPrice`` reading per instrument (``{"OUSG": {"value": ..., "as_of": ...}}``) so
``onchain.ondo_asset_price``'s frozen-value tracking has something to compare against; a row is
``backfill=True`` whenever ``prior`` has no entry for that instrument (first collection).

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from spa_core.research_factory import contract, evidence_contract, instruments, onchain

CLAIM_NAV_ORACLE = "nav_oracle"
CLAIM_NAV_OFFICIAL_API = "nav_official_api"
CLAIM_NAV_AGGREGATOR_APY = "nav_aggregator_apy"

USYC_API_HOST = "usyc.hashnote.com"
DEFILLAMA_HOST = "yields.llama.fi"


def _sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _row(*, candidate_id: str, claim: str, state: str, value: Optional[Any] = None, unit: Optional[str] = None,
        upstream_ts: Optional[str] = None, fetched_at: str, origin: Optional[str], channel: str,
        ref: str, raw: Any = None, backfill: bool = False, revises: Optional[str] = None,
        reason: Optional[str] = None) -> dict:
    return {
        "schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": candidate_id, "claim": claim,
        "value": value, "unit": unit, "window": None, "upstream_ts": upstream_ts, "fetched_at": fetched_at,
        "origin": origin, "channel": channel, "ref": ref, "raw_sha256": _sha256(raw) if raw is not None else None,
        "backfill": backfill, "revises": revises, "state": state, "reason": reason,
    }


def _cell_to_row(cell: dict, *, candidate_id: str, claim: str, origin: Optional[str], channel: str,
                 ref: str, now: datetime, backfill: bool) -> dict:
    return _row(candidate_id=candidate_id, claim=claim, state=cell.get("state"), value=cell.get("value"),
               unit=cell.get("unit"), upstream_ts=cell.get("as_of"), fetched_at=now.isoformat(),
               origin=origin, channel=channel, ref=ref, backfill=backfill, reason=cell.get("reason"))


def _oracle_row(symbol: str, meta: dict, *, rpc_client, now: datetime, prior: dict) -> dict:
    oracle = meta["oracle"]
    kind = oracle.get("kind")
    candidate_id = instruments.candidate_id_for(symbol)
    backfill = symbol not in prior
    if kind == instruments.ORACLE_CHAINLINK_ROUND:
        cell = onchain.chainlink_round(oracle["address"], rpc_client=rpc_client, now=now,
                                       answer_decimals=oracle.get("answer_decimals", 18))
    elif kind == instruments.ORACLE_ONDO_PRICE_DATA:
        cell = onchain.ondo_price_data(oracle["address"], rpc_client=rpc_client, now=now,
                                       price_decimals=oracle.get("price_decimals", 18))
    elif kind == instruments.ORACLE_ONDO_ASSET_PRICE:
        # coordinator finding #1 (2026-10-04): the caller's `prior[symbol]` must carry the
        # PREVIOUS run's value AND its as_of AND (where available) its own fetch time, so
        # onchain.ondo_asset_price can tell "never observed" from "observed, unchanged" from
        # "observed, now confirmed changed" — three different as_of outcomes, never collapsed to
        # one. `prior[symbol].get("fetched_at")` is optional (today's loader — run.py's
        # `_treasury_prior_readings` — supplies only value/as_of); its absence degrades
        # gracefully inside onchain.py (falls back to prev_as_of as the anchor), never raises.
        p = prior.get(symbol) or {}
        cell = onchain.ondo_asset_price(oracle["address"], meta["address"], rpc_client=rpc_client, now=now,
                                        price_decimals=oracle.get("price_decimals", 18),
                                        prev_value=p.get("value"), prev_as_of=p.get("as_of"),
                                        prev_fetched_at=p.get("fetched_at"))
    else:
        cell = {"state": "NOT_MEASURED", "value": None, "unit": None, "as_of": None,
               "reason": oracle.get("reason") or f"{symbol}: no on-chain oracle reader configured"}
    ref = f"chain:{meta['chain_id']}:{(oracle.get('address') or meta['address']).lower()}:{kind}"
    return _cell_to_row(cell, candidate_id=candidate_id, claim=CLAIM_NAV_ORACLE,
                        origin=meta.get("oracle_origin"), channel=evidence_contract.CHANNEL_ON_CHAIN,
                        ref=ref, now=now, backfill=backfill)


def _usyc_api_rows(client, now: datetime, *, backfill: bool) -> list:
    candidate_id = instruments.candidate_id_for("USYC")
    rows = []
    for path, claim_suffix in (("/api/price", "price"), ("/api/price-reports", "price_reports")):
        try:
            doc = client.get(USYC_API_HOST, path, {}) if client is not None else None
        except Exception as exc:  # noqa: BLE001 — a client failure is NOT_MEASURED, never a crash
            rows.append(_row(candidate_id=candidate_id, claim=f"{CLAIM_NAV_OFFICIAL_API}:{claim_suffix}",
                             state="NOT_MEASURED", fetched_at=now.isoformat(), origin="issuer:hashnote",
                             channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{USYC_API_HOST}{path}",
                             backfill=backfill, reason=f"{type(exc).__name__}: {exc}"))
            continue
        price = doc.get("price") if isinstance(doc, dict) else None
        ts = doc.get("timestamp") or doc.get("as_of") if isinstance(doc, dict) else None
        if isinstance(price, (int, float)) and isinstance(ts, str) and contract.parse_ts(ts):
            rows.append(_row(candidate_id=candidate_id, claim=f"{CLAIM_NAV_OFFICIAL_API}:{claim_suffix}",
                             state="MEASURED", value=float(price), unit="usd_per_unit", upstream_ts=ts,
                             fetched_at=now.isoformat(), origin="issuer:hashnote",
                             channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{USYC_API_HOST}{path}",
                             raw=doc, backfill=backfill))
        else:
            rows.append(_row(candidate_id=candidate_id, claim=f"{CLAIM_NAV_OFFICIAL_API}:{claim_suffix}",
                             state="NOT_MEASURED", fetched_at=now.isoformat(), origin="issuer:hashnote",
                             channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{USYC_API_HOST}{path}",
                             backfill=backfill, raw=doc,
                             reason=f"{USYC_API_HOST}{path}: no usable (price, timestamp) pair in the response"))
    return rows


def _defillama_row(symbol: str, meta: dict, client, now: datetime, *, pools: Optional[list], backfill: bool) -> dict:
    candidate_id = instruments.candidate_id_for(symbol)
    if pools is None:
        try:
            doc = client.get(DEFILLAMA_HOST, "/pools", {}) if client is not None else None
            pools = doc.get("data") if isinstance(doc, dict) else None
        except Exception as exc:  # noqa: BLE001
            return _row(candidate_id=candidate_id, claim=CLAIM_NAV_AGGREGATOR_APY, state="NOT_MEASURED",
                       fetched_at=now.isoformat(), origin="aggregator:defillama",
                       channel=evidence_contract.CHANNEL_AGGREGATOR, ref=f"{DEFILLAMA_HOST}/pools",
                       backfill=backfill, reason=f"{type(exc).__name__}: {exc}")
    pool, reason = instruments.join_pool_by_chain_and_contract(symbol, pools or [])
    if pool is None:
        return _row(candidate_id=candidate_id, claim=CLAIM_NAV_AGGREGATOR_APY, state="NOT_MEASURED",
                   fetched_at=now.isoformat(), origin="aggregator:defillama",
                   channel=evidence_contract.CHANNEL_AGGREGATOR, ref=f"{DEFILLAMA_HOST}/pools",
                   backfill=backfill, reason=reason)
    apy = pool.get("apy")
    return _row(candidate_id=candidate_id, claim=CLAIM_NAV_AGGREGATOR_APY,
               state="MEASURED" if isinstance(apy, (int, float)) else "NOT_MEASURED",
               value=float(apy) if isinstance(apy, (int, float)) else None, unit="pct_apy",
               fetched_at=now.isoformat(), origin="aggregator:defillama",
               channel=evidence_contract.CHANNEL_AGGREGATOR, ref=f"{DEFILLAMA_HOST}/pools#{pool.get('pool')}",
               raw=pool, backfill=backfill,
               reason=None if isinstance(apy, (int, float)) else "joined pool has no numeric 'apy' field")


def collect(now: datetime, client, *, rpc_client=None, prior: Optional[dict] = None,
           pools: Optional[list] = None) -> list:
    """``prior``: ``{symbol: {"value": float, "as_of": iso_str}}`` — the last-recorded
    ``getAssetPrice`` reading (OUSG only needs this; harmless to pass for the others). ``pools``:
    inject a pre-fetched DeFiLlama pool list (tests); ``None`` fetches via ``client``."""
    prior = prior or {}
    rows = []
    for symbol, meta in instruments.INSTRUMENTS.items():
        backfill = symbol not in prior
        rows.append(_oracle_row(symbol, meta, rpc_client=rpc_client, now=now, prior=prior))
        if symbol == "USYC":
            rows.extend(_usyc_api_rows(client, now, backfill=backfill))
        rows.append(_defillama_row(symbol, meta, client, now, pools=pools, backfill=backfill))
    return rows
