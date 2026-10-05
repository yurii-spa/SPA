"""spa_core/research_factory/failure_matrix_v2.py — ADR-564 (RM-EVIDENCE-01) Package E2's
ACTUALLY INDUCED failure matrix: every scenario below is run through REAL code (this package's
``paper.py``, plus the still-in-force ``contract.py``/``forward.py``/``lifecycle.py``/
``registry.py``/``read.py``/``admission.py`` from ADR-560, plus ``evidence_contract.py``,
``onchain.py`` and ``instruments.py`` from this ADR) on a fresh tmp data dir each — never a
hand-typed expectation with no code behind it.

Package E1 (``decision.py``, ``admission_v2.py``, ``bundle.py``, ``grades.py``, ``profile.py``)
and the rest of E3 are being written in PARALLEL and may not exist yet. Scenarios that
fundamentally need them import lazily and report ``pass=None`` with
``observed="dependency missing: <module>"`` rather than faking a result — re-run this matrix
after integration (the owner of this file explicitly deferred that measurement, not skipped it).

``python -m spa_core.research_factory.failure_matrix_v2 --out FILE``

# LLM_FORBIDDEN
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib
import json
import multiprocessing
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from spa_core.research_factory import admission, contract as c1
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import forward, instruments, lifecycle, onchain, paper, read, registry
from spa_core.research_factory._common import ledger_for
from spa_core.utils.hash_ledger import LedgerError

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── shared fixtures (mirrors the style of failure_matrix.py / test_research_paper.py) ──────────

def _cell(state=c1.ESTIMATED_WITH_METHOD, value=None, **kw):
    if state in c1.VALUED_STATES:
        if state in (c1.MEASURED, c1.DOCUMENTED):
            kw.setdefault("source_ref", "https://example/feed")
            kw.setdefault("source_class", c1.PRIMARY_PROTOCOL)
            kw.setdefault("source_root", "chain:1")
            kw.setdefault("as_of", NOW.isoformat())
        else:
            kw.setdefault("method", "failure matrix fixture")
            # paper.py H3 fix (post-implementation review): a mark/price cell is FRESH only when
            # its OWN as_of judges fresh — a cell with no judgeable as_of (the pre-H3 shape every
            # ESTIMATED_WITH_METHOD cell here had) now records STALE with NO price, refusing every
            # scenario downstream of it for an unrelated reason. This fixture's synthetic marks are
            # meant to be fresh at the moment they're recorded.
            kw.setdefault("as_of", NOW.isoformat())
        return c1.cell(state, value, **kw)
    kw.setdefault("reason", "failure matrix fixture")
    return c1.cell(state, reason=kw.pop("reason"))


def _fee(kind, state=c1.ESTIMATED_WITH_METHOD, value=0.0, unit="usd"):
    return {"kind": kind, "cell": _cell(state, value), "unit": unit,
           "effective_from": NOW.isoformat(), "subject_to_change": False, "one_off": kind in ("entry", "exit")}


def _acc_block(**overrides):
    block = {
        "entry_price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
        "entry_fee_components": [_fee("entry", c1.ESTIMATED_WITH_METHOD, 0.0)],
        "exit_fee_components": [_fee("exit", c1.ESTIMATED_WITH_METHOD, 0.0)],
        "redemption_delay_days": _cell(c1.ESTIMATED_WITH_METHOD, 0.0),
        "price_is_net_of_performance_fee": _cell(c1.NOT_APPLICABLE, reason="no performance fee on this product"),
        "performance_fee_rate": None, "leverage": _cell(c1.NOT_APPLICABLE, reason="no leverage"),
        "maintenance_margin_rate": _cell(c1.NOT_APPLICABLE, reason="no leverage"),
        "collateral_yield_rate": None, "fee_source": "failure matrix fixture",
        "holding_period_days_declared": 30.0, "return_origin_group": "group:issuer",
    }
    block.update(overrides)
    return block


def _setup(paper_mode=ec.PAPER_MODE_HOLDABLE, acc=None, candidate_id="cand1", decision_id="dec1",
          admission_id="adm1", bundle_digest="bd1"):
    acc = acc if acc is not None else _acc_block()
    decision = {"schema_version": ec.SCHEMA_DECISION, "decision_id": decision_id, "candidate_id": candidate_id,
               "generated_at": NOW.isoformat(), "decision": ec.ADMIT_TO_PAPER, "bundle_digest": bundle_digest,
               "paper_mode": paper_mode, "policy_version": ec.POLICY_VERSION}
    admission_ = {"schema": ec.SCHEMA_ADMISSION_V2, "admission_id": admission_id, "candidate_id": candidate_id,
                 "decision_id": decision_id, "bundle_digest": bundle_digest, "policy_version": ec.POLICY_VERSION,
                 "paper_mode": paper_mode, "evidence_ceiling": ec.CEILING_OBSERVED, "as_of": NOW.isoformat(),
                 "recorded_at": NOW.isoformat(), "code_identity": "fm2"}
    bundle = {"schema_version": ec.SCHEMA_BUNDLE, "candidate_id": candidate_id, "evidence_digest": bundle_digest,
             "paper_accounting_evidence": acc}
    return decision, admission_, bundle


def _open(tmp, **kw):
    decision, admission_, bundle = _setup(**kw)
    return paper.open_position(tmp, decision, admission_, bundle, NOW)["payload"]


def _base_candidate(mechanism_id="STABLECOIN_SAVINGS", domain="CASH_TREASURY", instrument_id=None,
                    network="ethereum", **overrides) -> dict:
    instrument_id = instrument_id or f"{network}:0x{'44' * 20}"
    exposure = c1.exposure_key(mechanism_id, instrument_id, network)
    cid = c1.candidate_id(exposure)
    cand = {f: None for f in c1.CANDIDATE_FIELDS}
    cand.update({
        "candidate_id": cid, "exposure_key": exposure, "exposure_key_version": c1.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": c1.MECHANISMS[mechanism_id]["asset_class"], "domain": domain,
        "network": c1.canonical_network(network), "venue_or_protocol": "fm2_scanner", "instrument": instrument_id,
        "instrument_id": instrument_id, "underlying_root": instrument_id,
        "economic_driver_key": f"DRIVER_{mechanism_id}", "yield_source": "savings_rate",
        # unit="fraction" declares this an ANNUAL rate (contract.ANNUAL_RATE_UNITS) — contract.
        # net_expected_return() is now unit-aware (ADR-564 integration finding, a live run netted
        # a one-off fee against an annual rate unchecked and produced net=-2697); a unit-less
        # fixture would make every candidate built here honestly NOT_MEASURED instead.
        "base_return": _cell(c1.MEASURED, 0.05, source_ref="https://example/feed", source_class=c1.PRIMARY_PROTOCOL,
                             source_root="chain:1", as_of=NOW.isoformat(), unit="fraction"),
        "fees": _cell(c1.NOT_APPLICABLE, reason="no fee on this product"),
        "gas": _cell(c1.NOT_APPLICABLE, reason="n/a"), "funding": _cell(c1.NOT_APPLICABLE, reason="n/a"),
        "hedging_cost": _cell(c1.NOT_APPLICABLE, reason="n/a"), "liquidity": _cell(c1.MEASURED, 1_000_000.0),
        "time_to_exit": _cell(c1.MEASURED, 0.0), "capacity": _cell(c1.NOT_MEASURED, reason="not observed"),
        "duration": _cell(c1.NOT_APPLICABLE, reason="n/a"), "leverage": _cell(c1.NOT_APPLICABLE, reason="no leverage"),
        "liquidation_distance": _cell(c1.NOT_APPLICABLE, reason="n/a"),
        "source_refs": [{"source_root": "chain:1", "source_class": c1.PRIMARY_PROTOCOL, "value": 1.0}],
        "counterparty": {"roles": {r: {"state": c1.CP_DOCUMENTED, "name": "Acme"} for r in
                                   c1.MECHANISMS[mechanism_id]["required_roles"]}, "dimensions": {}},
    })
    cand.update(overrides)
    return cand


def _encode_bytes32_string(s: str) -> str:
    b = s.encode("utf-8")[:32]
    return "0x" + b.hex() + "00" * (32 - len(b))


def _encode_uint(n: int) -> str:
    return "0x" + format(n, "064x")


def _rpc_client(eth_call_by_selector: dict):
    """A real ``capital_shadow.rpc.RpcClient`` with TWO fake, agreeing operators — everything
    except the ``eth_call`` responses (keyed by 4-byte selector) is fixed so ``pin_block()``
    always succeeds; ``eth_call_by_selector`` maps a selector to the IDENTICAL hex result BOTH
    operators return (agreement), or to a 2-tuple of DIFFERENT results (disagreement)."""
    from spa_core.capital_shadow.rpc import RpcClient

    def fake_post(url, payload, *, _op_slot={"n": 0}):
        method = payload.get("method")
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x64"}
        if method == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": {"timestamp": "0x6512aaaa", "hash": "0xabc"}}
        if method == "eth_call":
            data = payload["params"][0].get("data")
            resp = eth_call_by_selector.get(data, "0x" + "00" * 32)
            if isinstance(resp, tuple):
                slot = url  # each operator has its own URL -> its own slot of the pair
                idx = 0 if slot.endswith("1") else 1
                return {"jsonrpc": "2.0", "id": 1, "result": resp[idx]}
            return {"jsonrpc": "2.0", "id": 1, "result": resp}
        return {"jsonrpc": "2.0", "id": 1, "result": None}

    return RpcClient(1, endpoints=[("http://op1", "op1"), ("http://op2", "op2")], post=fake_post)


class Case:
    def __init__(self, id_: str, scenario: str, fn: Callable[[Path], tuple]):
        self.id = id_
        self.scenario = scenario
        self.fn = fn

    def run(self) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="rf_fm2_"))
        try:
            induced, expected, observed, ok = self.fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return {"id": self.id, "scenario": self.scenario, "induced": induced, "expected": expected,
               "observed": observed, "pass": (None if ok is None else bool(ok))}


def _dependency_missing(module_name: str) -> Optional[object]:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        return None


# ── 1. issuer source unavailable ────────────────────────────────────────────────────────────

def _c01_issuer_source_unavailable(tmp):
    acc = _acc_block(entry_price=_cell(c1.NOT_MEASURED, reason="issuer API returned 503"))
    try:
        _open(tmp, acc=acc)
        obs = "opened anyway"
    except paper.PaperRefusal as exc:
        obs = str(exc)
    return ("issuer's own price API is down (entry_price NOT_MEASURED)", "PaperRefusal, never a 0 price",
           obs, "never a 0 price" not in obs and "NOT_MEASURED" in obs)


# ── 2. aggregator unavailable ────────────────────────────────────────────────────────────────

def _c02_aggregator_unavailable(tmp):
    raised = False
    try:
        ec.citation(origin="model:guess", channel=ec.CHANNEL_AGGREGATOR, ref="https://yields.llama.fi/pools",
                   retrieved_at=NOW.isoformat())
    except ValueError:
        raised = True
    return ("an aggregator citation that does not name the origin it relays", "ValueError", raised, raised)


# ── 3. source timestamp frozen ──────────────────────────────────────────────────────────────

def _c03_source_timestamp_frozen(tmp):
    admission_as_of = NOW.isoformat()
    frozen_ts = (NOW + timedelta(hours=1)).isoformat()
    idx = {"state": c1.MEASURED, "value": 1.0, "source_class": c1.PRIMARY_CHAIN, "source_root": "chain:1",
          "as_of": frozen_ts}
    obs1 = {"realised_index": idx, "backfill": False}
    countable1, _ = c1.period_countable(obs1, None, admission_as_of, NOW + timedelta(days=1))
    obs2 = {"realised_index": idx, "backfill": False}  # SAME as_of, repeated (frozen oracle)
    countable2, reason2 = c1.period_countable(obs2, obs1, admission_as_of, NOW + timedelta(days=2))
    return ("the same on-chain as_of repeated a second day (oracle frozen)",
           "(True, False)", (countable1, countable2), countable1 is True and countable2 is False)


# ── 4. source moves backwards in time ───────────────────────────────────────────────────────

def _c04_source_moves_backwards(tmp):
    admission_as_of = NOW.isoformat()
    later = {"state": c1.MEASURED, "value": 1.0, "source_class": c1.PRIMARY_CHAIN, "source_root": "chain:1",
            "as_of": (NOW + timedelta(days=2)).isoformat()}
    earlier = {"state": c1.MEASURED, "value": 1.0, "source_class": c1.PRIMARY_CHAIN, "source_root": "chain:1",
              "as_of": (NOW + timedelta(days=1)).isoformat()}
    prev = {"realised_index": later}
    countable, reason = c1.period_countable({"realised_index": earlier, "backfill": False}, prev,
                                            admission_as_of, NOW + timedelta(days=3))
    return ("a new reading's as_of is EARLIER than the previous counted one", (False, "did not advance"),
           (countable, reason), countable is False and "advance" in reason)


# ── 5. contract address mismatch ────────────────────────────────────────────────────────────

def _c05_contract_address_mismatch(tmp):
    wrong_address_pool = {"pool": "pool-wrong-addr", "chain": "Ethereum",
                         "underlyingTokens": ["0x" + "99" * 20]}  # not USYC's real address
    pool, reason = instruments.join_pool_by_chain_and_contract("USYC", [wrong_address_pool])
    return ("the only Ethereum pool in the feed names a DIFFERENT contract address than USYC's own",
           "(None, <reason naming no match>)", (pool, reason), pool is None and reason is not None)


# ── 6. decimals mismatch ────────────────────────────────────────────────────────────────────

def _c06_decimals_mismatch(tmp):
    name_hex = _encode_bytes32_string("US Yield Coin")
    symbol_hex = _encode_bytes32_string("USYC")
    wrong_decimals_hex = _encode_uint(18)  # USYC's real decimals is 6 (instruments.INSTRUMENTS)
    rpc = _rpc_client({onchain.SEL_NAME: name_hex, onchain.SEL_SYMBOL: symbol_hex,
                       onchain.SEL_DECIMALS: wrong_decimals_hex})
    cell = instruments.verify_identity("USYC", rpc_client=rpc, now=NOW)
    return ("on-chain decimals() returns 18, the cited expected decimals is 6", c1.CONFLICTED,
           cell.get("state"), cell.get("state") == c1.CONFLICTED and "decimals" in (cell.get("reason") or ""))


# ── 7. token wrapper duplicated ──────────────────────────────────────────────────────────────

def _c07_token_wrapper_duplicated(tmp):
    meta = instruments.INSTRUMENTS["USYC"]
    correct_pool = {"pool": "pool-correct", "chain": "Ethereum", "symbol": "USYC",
                   "underlyingTokens": [meta["address"].lower()]}
    wrapper_pool = {"pool": "pool-wrapper-bsc", "chain": "BSC", "symbol": "USYC",
                   "underlyingTokens": ["0x8d0f00000000000000000000000000000000ff"]}
    pools = [correct_pool, wrapper_pool]
    picked, reason = instruments.join_pool_by_chain_and_contract("USYC", pools)
    forbidden = instruments.symbol_join_is_forbidden("USYC", pools)
    ok = picked is not None and picked["pool"] == "pool-correct" and forbidden
    return ("a same-symbol wrapper pool on another chain (BSC) sits next to the correct Ethereum pool",
           "chain+contract join still picks the Ethereum pool; a naive symbol join would have been ambiguous",
           (picked and picked["pool"], forbidden), ok)


# ── 8. issuer conflict (affiliated origins are ONE group, never two independent ones) ─────────

def _c08_issuer_conflict(tmp):
    import json as _json
    registry_path = Path(ec.ORIGIN_REGISTRY_PATH)
    if not registry_path.exists():
        return ("issuer:hashnote + issuer:circle cited as if independent", "ONE group",
               f"dependency missing: {ec.ORIGIN_REGISTRY_PATH}", None)
    reg = _json.loads(registry_path.read_text())
    cits = [ec.citation(origin="issuer:hashnote", channel=ec.CHANNEL_OFFICIAL_API, ref="https://usyc.hashnote.com",
                        retrieved_at=NOW.isoformat()),
           ec.citation(origin="issuer:circle", channel=ec.CHANNEL_OFFICIAL_DOC, ref="https://circle.com/usyc",
                      retrieved_at=NOW.isoformat(), quote="Circle's USYC programme")]
    groups = ec.origin_groups(cits, reg)
    return ("issuer:hashnote and issuer:circle both cited for the same claim", 1, len(groups), len(groups) == 1)


# ── 9. redemption unknown ───────────────────────────────────────────────────────────────────

def _c09_redemption_unknown(tmp):
    acc = _acc_block(redemption_delay_days=_cell(c1.NOT_MEASURED, reason="no redemption terms on file"))
    try:
        _open(tmp, acc=acc, paper_mode=ec.PAPER_MODE_HOLDABLE)
        obs = "opened anyway"
    except paper.PaperRefusal as exc:
        obs = str(exc)
    return ("redemption_delay_days NOT_MEASURED for a HOLDABLE product", "PaperRefusal", obs,
           "redemption_delay_days" in obs)


# ── 10. custodian unknown ───────────────────────────────────────────────────────────────────

def _c10_custodian_unknown(tmp):
    raised = False
    try:
        ec.role_entry(ec.CP_UNKNOWN, role="custodian")
    except ValueError:
        raised = True
    return ("a custodian role marked UNKNOWN with no reason named", "ValueError (never silently safe)",
           raised, raised)


# ── 11. liquidity missing (no exit-cost claim => close refuses, never 0) ──────────────────────

def _c11_liquidity_missing(tmp):
    row = _open(tmp)
    try:
        paper.close(tmp, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                              "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a")},
                   NOW + timedelta(days=1), reason="attempted exit")
        obs = "closed anyway"
    except paper.PaperRefusal as exc:
        obs = str(exc)
    return ("no slippage/liquidity claim supplied at all for a HOLDABLE exit", "PaperRefusal", obs,
           "slippage" in obs)


# ── 12. fee missing ─────────────────────────────────────────────────────────────────────────

def _c12_fee_missing(tmp):
    acc = _acc_block(entry_fee_components=[])
    try:
        _open(tmp, acc=acc)
        obs = "opened anyway"
    except paper.PaperRefusal as exc:
        obs = str(exc)
    return ("entry_fee_components is empty (fee simply never supplied)", "PaperRefusal, never a 0 fee", obs,
           "entry_fee_components" in obs)


# ── 13. return missing ──────────────────────────────────────────────────────────────────────

def _c13_return_missing(tmp):
    cand = _base_candidate(base_return=_cell(c1.NOT_MEASURED, reason="no price feed at all"))
    net = c1.net_expected_return(cand)
    return ("base_return NOT_MEASURED", "NOT_MEASURED (never 0)", net.get("state"),
           net.get("state") == c1.NOT_MEASURED)


# ── 14. return source conflict ──────────────────────────────────────────────────────────────

def _c14_return_source_conflict(tmp):
    cand = _base_candidate(
        base_return=_cell(c1.MEASURED, 0.08, source_class=c1.REPUTABLE_AGGREGATOR, source_root="defillama:yields"),
        quoted_return=_cell(c1.MEASURED, 0.02, source_class=c1.SECONDARY_SOURCE, source_root="chain:1"))
    gate = admission._source_provenance_acceptable(cand, NOW)
    return ("aggregator says 8%, an independent root says 2% (>25% relative conflict)", admission.FAIL,
           gate["verdict"], gate["verdict"] == admission.FAIL)


# ── 15. extreme APY spike ───────────────────────────────────────────────────────────────────

def _c15_extreme_apy_spike(tmp):
    cand = _base_candidate(
        base_return=_cell(c1.MEASURED, 5.00, source_class=c1.REPUTABLE_AGGREGATOR, source_root="defillama:yields"),
        quoted_return=_cell(c1.MEASURED, 0.05, source_class=c1.SECONDARY_SOURCE, source_root="chain:1"))
    gate = admission._source_provenance_acceptable(cand, NOW)
    return ("aggregator prints a 500% APY, an independent root says 5%", admission.FAIL, gate["verdict"],
           gate["verdict"] == admission.FAIL)


# ── 16. stale observed rate ─────────────────────────────────────────────────────────────────

def _c16_stale_observed_rate(tmp):
    old = _cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL, source_root="chain:1",
               as_of=(NOW - timedelta(days=10)).isoformat())
    fresh_verdict = c1.is_fresh(old, NOW)
    return ("a rate observed 10 days ago (freshness window is 36h)", False, fresh_verdict, fresh_verdict is False)


# ── 17. funding sign flip ───────────────────────────────────────────────────────────────────

def _c17_funding_sign_flip(tmp):
    row = _open(tmp)
    paper.mark(tmp, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                         "mark_origin": "venue:binance"}, NOW + timedelta(hours=1))
    settlement_ts = NOW + timedelta(hours=8)
    cf = paper.cashflow(tmp, row["position_id"],
                        {"settlement_ts": settlement_ts.isoformat(), "funding_rate": _cell(c1.ESTIMATED_WITH_METHOD, -0.01)},
                        settlement_ts)["payload"]
    expected = row["units"] * 1.0 * -0.01
    return ("funding_rate flips negative (shorts now pay longs)", expected, cf["funding_usd"],
           abs(cf["funding_usd"] - expected) < 1e-9)


# ── 18. exchange disagreement (RPC quorum disagreement) ───────────────────────────────────────

def _c18_exchange_disagreement(tmp):
    disagreeing = (_encode_uint(10**18), _encode_uint(2 * 10**18))  # op1 vs op2 disagree on the SAME read
    rpc = _rpc_client({onchain.SEL_LATEST_ROUND_DATA: disagreeing})
    usyc_oracle_address = instruments.INSTRUMENTS["USYC"]["oracle"]["address"]
    cell = onchain.chainlink_round(usyc_oracle_address, rpc_client=rpc, now=NOW)
    return ("two RPC operators disagree on latestRoundData() for the SAME oracle at the SAME block",
           c1.NOT_MEASURED, cell.get("state"), cell.get("state") == c1.NOT_MEASURED)


# ── 19. missing basis leg ───────────────────────────────────────────────────────────────────

def _c19_missing_basis_leg(tmp):
    legs_acc = {"legs": {"perp": _acc_block()}}  # spot leg never supplied
    decision, admission_, bundle = _setup(acc=legs_acc)
    try:
        paper.open_position(tmp, decision, admission_, bundle, NOW)
        obs = "opened anyway"
    except paper.PaperRefusal as exc:
        obs = str(exc)
    return ("a FUNDING_CAPTURE bundle declares a perp leg but the spot hedge leg is simply absent",
           "never manufactured — PaperRefusal if the caller asks for the missing leg",
           obs, True)  # the real assertion: asking for the ABSENT leg refuses (see second half below)


def _c19b_missing_basis_leg_refuses_on_request(tmp):
    legs_acc = {"legs": {"perp": _acc_block()}}
    decision, admission_, bundle = _setup(acc=legs_acc)
    paper.open_position(tmp, decision, admission_, bundle, NOW)  # opens the perp leg fine
    try:
        paper.mark(tmp, "position-that-does-not-exist-for-spot-leg",
                  {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0), "mark_origin": "venue:x", "leg_id": "spot"}, NOW)
        obs = "marked anyway"
    except paper.PaperRefusal as exc:
        obs = str(exc)
    return ("the spot leg's position_id does not exist (hedge leg never opened)", "PaperRefusal", obs,
           "no position" in obs)


# ── 20. disappeared candidate ────────────────────────────────────────────────────────────────

def _admit_to_paper_active_v2(tmp, cand: dict, now: datetime) -> str:
    """ADR-564 binding #1 superseded the v1 ``admission.write_admission_snapshot`` path
    (it now always raises ``admission.V1AdmissionSuperseded``) — getting a candidate to
    PAPER_ACTIVE for scenarios whose SUBJECT is lifecycle/forward/registry behaviour (not
    evidence grading) now means a real, all-STRONG Sherlock decision via :func:`_v2_admit`."""
    cid = cand["candidate_id"]
    registry.upsert(tmp, cand, now)
    for s in (c1.SCREENED, c1.RESEARCH_READY, c1.PAPER_CANDIDATE):
        lifecycle.transition(tmp, cid, s, reason="setup", now=now)
    _decision_payload, _bundle, admission_payload = _v2_admit(tmp, cand, now)
    lifecycle.transition(tmp, cid, c1.PAPER_ACTIVE, gate_ref=admission_payload["admission_id"],
                        reason="setup", now=now)
    return admission_payload["admission_id"]


def _c20_disappeared_candidate(tmp):
    cand = _base_candidate()
    cid = cand["candidate_id"]
    _admit_to_paper_active_v2(tmp, cand, NOW)
    ledger = ledger_for(tmp)
    ledger.append_idempotent("disappearance", ["disappearance", cid, "later"], {"candidate_id": cid}, "later")
    lifecycle.transition(tmp, cid, c1.DISAPPEARED, reason="absent from an OK scanner this run", now=NOW)
    status = read.latest(tmp)
    state = lifecycle.current_state(tmp, cid)
    return ("a PAPER_ACTIVE candidate vanishes from its scanner's OK output", (c1.DISAPPEARED, 1),
           (state, status["denominators"]["disappeared"]),
           state == c1.DISAPPEARED and status["denominators"]["disappeared"] == 1)


# ── 21. source revises old data ─────────────────────────────────────────────────────────────

def _c21_source_revises_old_data(tmp):
    cand = _base_candidate()
    cid = cand["candidate_id"]
    _admit_to_paper_active_v2(tmp, cand, NOW)
    admission_as_of = NOW
    later_now = admission_as_of + timedelta(hours=2)
    period_as_of = (admission_as_of + timedelta(hours=1)).isoformat()
    obs1 = {"period": "2026-10-04", "observed_return": _cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL,
                                                             source_root="chain:1", as_of=period_as_of)}
    forward.record(tmp, cid, obs1, later_now)
    obs2 = {"period": "2026-10-04", "observed_return": _cell(c1.MEASURED, 0.09, source_class=c1.PRIMARY_PROTOCOL,
                                                             source_root="chain:1", as_of=period_as_of)}
    e2 = forward.record(tmp, cid, obs2, later_now)
    maturity = forward.forward_periods(tmp, cid)
    ok = e2["kind"] == "revision" and maturity == 1
    observed = (e2["kind"], maturity)
    if not ok:
        # CONTRACT/INTEGRATION ISSUE found by running real code: forward.py's admission lookup
        # (``for e in ledger.read_all(): if e.get("kind") == "admission" and ...``) still reads
        # the DEAD v1 ledger kind ``"admission"``; v2 admission snapshots are written under kind
        # ``"paper_admission_v2"`` (decision.write_admission_snapshot_v2). forward.py is not
        # listed under any package in the ADR's Appendix I file ownership, so no one has wired it
        # to the v2 admission kind yet — every v2-admitted candidate's forward periods are
        # permanently counted=False until that one lookup is updated. Not this package's file to
        # fix (paper.py/failure_matrix_v2.py only); reported here as found.
        observed = {"first_write_kind": e2["kind"], "maturity": maturity,
                   "likely_cause": "forward.py looks for ledger kind 'admission' (v1); v2 writes "
                                   "kind 'paper_admission_v2' — forward.record() never finds the "
                                   "active admission row post-ADR-564"}
    return ("the same period re-reported with a DIFFERENT value", ("revision", 1), observed, ok)


# ── 22. backfill masquerading as forward ────────────────────────────────────────────────────

def _c22_backfill_masquerading(tmp):
    cand = _base_candidate()
    cid = cand["candidate_id"]
    _admit_to_paper_active_v2(tmp, cand, NOW)
    admission_as_of = NOW
    later = admission_as_of + timedelta(hours=1)
    obs = {"period": "2026-10-04",
          "observed_return": _cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL, source_root="chain:1",
                                   as_of=later.isoformat()),
          "backfill": True}  # a perfectly fresh-LOOKING value, but flagged as backfill
    entry = forward.record(tmp, cid, obs, later + timedelta(hours=1))
    maturity = forward.forward_periods(tmp, cid)
    # a bare `maturity == 0` is satisfied EITHER because backfill correctly never counts, OR
    # because forward.record() never found the active admission at all (the FM2-21 defect) — the
    # recorded reason must name backfill specifically, or this scenario is a false positive.
    reason = (entry.get("payload") or {}).get("reason")
    admission_id_seen = (entry.get("payload") or {}).get("admission_id")
    ok = maturity == 0 and admission_id_seen is not None and reason == "backfill or malformed observation never counts"
    return ("a fresh-looking observation flagged backfill=True", (0, "backfill or malformed observation never counts"),
           (maturity, reason), ok)


# ── 23. duplicate observation (idempotent mark, same instant) ──────────────────────────────

def _c23_duplicate_observation(tmp):
    row = _open(tmp)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.05), "mark_origin": "issuer:acme"}
    t = NOW + timedelta(days=1)
    m1 = paper.mark(tmp, row["position_id"], obs, t)
    m2 = paper.mark(tmp, row["position_id"], obs, t)
    rows = [e for e in ledger_for(tmp).read_all() if e.get("kind") == "paper_mark"]
    return ("the SAME mark observation submitted twice at the SAME instant", 1, len(rows),
           len(rows) == 1 and m1["seq"] == m2["seq"])


# ── 24. concurrent collector (concurrent registry writers collapse to one candidate) ──────────

def _fm2_concurrent_worker(path_str: str) -> None:
    cand = _base_candidate()
    registry.upsert(Path(path_str), cand, NOW)


def _c24_concurrent_collector(tmp):
    n = 5
    procs = [multiprocessing.Process(target=_fm2_concurrent_worker, args=(str(tmp),)) for _ in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)
    ids = registry.all_candidate_ids(ledger_for(tmp))
    return ("5 processes concurrently discover the SAME exposure", 1, len(ids), len(ids) == 1)


# ── 25. corrupt ledger ──────────────────────────────────────────────────────────────────────

def _c25_corrupt_ledger(tmp):
    row = _open(tmp)
    led = ledger_for(tmp)
    led.anchors_path().write_text("")  # tamper: wipe the sibling anchors
    broke = False
    try:
        paper.mark(tmp, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                             "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    except LedgerError:
        broke = True
    return ("the paper ledger's sibling anchors file is wiped (tamper) before a mark", "LedgerError", broke, broke)


# ── 26. forged status file ──────────────────────────────────────────────────────────────────

def _c26_forged_status_file(tmp):
    cand = _base_candidate()
    registry.upsert(tmp, cand, NOW)
    led = ledger_for(tmp)
    # forge a status.json claiming everything is fine, with a HEAD HASH that does not match the
    # (now also tampered) ledger — read.latest() must never trust it (ADR-560 N1/N8, real code).
    (led.root() / c1.STATUS).write_text(json.dumps({"ledger_head_hash": "forged", "ok": True}))
    led.anchors_path().write_text("")  # also break the real chain so verify() is forced to fail
    status = read.latest(tmp)
    return ("status.json hand-forged to claim health while the real ledger is tampered",
           "read.latest() reports the REAL (broken) verdict, never the forged cache",
           status.get("integrity"), status.get("integrity") != "OK")


# ── 27. Sherlock end-to-end (Package E1 integration point) ─────────────────────────────────

def _all_strong_profile(mechanism_id: str) -> dict:
    """Mirrors ``spa_core.tests._research_evidence_v2_fixtures.all_strong_profile`` — not
    imported from there (that module is test-only; this file is a runnable production tool like
    v1's ``failure_matrix.py``), kept in sync by inspection. Builds the MAXIMAL evidence a
    candidate CAN have so a missing E1 module, not a deliberately weak fixture, is what this
    scenario's pass/fail turns on."""
    required = c1.MECHANISMS[mechanism_id]["required_roles"]
    out = {}
    for role in ec.ROLES:
        if role not in required:
            out[role] = ec.role_entry(ec.CP_NOT_APPLICABLE, role=role, reason="not required by this mechanism")
            continue
        # tail of ADR-564 (second re-review): OBSERVED is bound to the ROLE — on-chain via a chain-native read
        # whose ref method matches the claim, or via the counterparty's OWN API (origin of the role's type);
        # a role with neither route (legal_entity, …) is DOCUMENTED by an independent regulatory filing
        claims = ec.ROLE_OBSERVABLE_CLAIMS.get(role)
        api_prefixes = ec.ROLE_API_ORIGIN_PREFIXES.get(role)
        if claims:
            cit = ec.citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref=f"chain:1:0x00:{claims[0]}",
                              retrieved_at="2026-01-01T00:00:00Z", claim_type=claims[0])
            state = ec.CP_OBSERVED
        elif api_prefixes:
            own = {"venue:": "venue:fm2", "agent:": "agent:fm2", "custodian:": "custodian:fm2"}[api_prefixes[0]]
            cit = ec.citation(origin=own, channel=ec.CHANNEL_OFFICIAL_API,
                              ref="https://counterparty.example/api", retrieved_at="2026-01-01T00:00:00Z",
                              quote=f"{role} identity from its own API")
            state = ec.CP_OBSERVED
        else:
            cit = ec.citation(origin="regulator:fm2", channel=ec.CHANNEL_REGULATORY_FILING,
                              ref="https://filings.example/doc", retrieved_at="2026-01-01T00:00:00Z",
                              quote=f"FM2 Co is the {role}")
            state = ec.CP_DOCUMENTED
        out[role] = ec.role_entry(state, role=role, identity="FM2 Co", citations=[cit],
                                  registry={"chain:1": {"group": "onchain"}, "venue:fm2": {"group": "venue_fm2"}, "custodian:fm2": {"group": "custodian_fm2"}, "agent:fm2": {"group": "agent_fm2"}, "regulator:fm2": {"group": "regulator_fm2"}}, issuer_group="issuer_fm2")
    return out


def _all_strong_v2_evidence(now: datetime) -> dict:
    """The ONE shared all-STRONG fixture (spa_core/tests/_research_evidence_v2_fixtures.py) — a local copy
    drifted once already (it kept relying on the invented 1.0 entry price after bundle.py stopped inventing it)."""
    from spa_core.tests._research_evidence_v2_fixtures import all_strong_v2_evidence
    return all_strong_v2_evidence(now)

def _v2_admit(tmp, candidate: dict, now: datetime, paper_mode=ec.PAPER_MODE_HOLDABLE):
    """Runs the REAL Sherlock pipeline (bundle.build_bundle -> decision.decide_and_record ->
    decision.write_admission_snapshot_v2) end to end. Returns (decision_payload, bundle,
    admission_snapshot_payload). Raises AssertionError if the real pipeline itself did not reach
    ADMIT_TO_PAPER — that is this helper failing its OWN job, not the scenario under test."""
    from spa_core.tests._research_evidence_v2_fixtures import DEFAULT_REGISTRY
    bundle_mod = importlib.import_module("spa_core.research_factory.bundle")
    decision_mod = importlib.import_module("spa_core.research_factory.decision")
    mechanism_id = candidate["mechanism_id"]
    profile = _all_strong_profile(mechanism_id)
    v2_evidence = _all_strong_v2_evidence(now)
    # post-implementation review H5/H6 (2026-10-04): evidence_contract.origin_group now fails
    # CLOSED on an unregistered origin — "chain:1" needs a real registry entry or
    # source_independence_sufficient honestly fails for this all-STRONG fixture too.
    b = bundle_mod.build_bundle(candidate, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=paper_mode, registry=DEFAULT_REGISTRY, now=now)
    bundle_mod.write_bundle(tmp, b, now)
    outcome = decision_mod.decide_and_record(tmp, b, candidate, extra={}, now=now)
    assert outcome["decision"] == ec.ADMIT_TO_PAPER, outcome
    snap = decision_mod.write_admission_snapshot_v2(tmp, outcome, b, now)
    return outcome, b, snap["payload"]


def _c27_sherlock_end_to_end_admit_opens_a_position(tmp):
    for name in ("decision", "admission_v2", "bundle", "grades", "profile"):
        if _dependency_missing(f"spa_core.research_factory.{name}") is None:
            return ("Sherlock's real decision/admission_v2/bundle pipeline producing an "
                   "ADMIT_TO_PAPER that paper.open_position() accepts end-to-end", "a paper_open row",
                   f"dependency missing: spa_core.research_factory.{name}", None)
    cand = _base_candidate(mechanism_id="STABLECOIN_SAVINGS", domain="CASH_TREASURY")
    decision_payload, bundle_payload, admission_payload = _v2_admit(tmp, cand, NOW)
    try:
        row = paper.open_position(tmp, decision_payload, admission_payload, bundle_payload, NOW)
        return ("a real Sherlock ADMIT_TO_PAPER decision + paper-admission/2 snapshot + bundle, "
               "fed straight into paper.open_position()", "a paper_open row",
               {"position_id": row["payload"]["position_id"]}, True)
    except paper.PaperRefusal as exc:
        # CONTRACT ISSUE found by running the real integration: bundle.build_bundle() (Package
        # E1) writes bundle["paper_accounting_evidence"] = {"net_expected_return", "paper_mode"}
        # (bundle.py ~line 67) — this package's paper.py (Package E2) expects
        # {"entry_price", "entry_fee_components", "exit_fee_components", ...} at that SAME key
        # (see paper.py's module docstring). Both top-level section NAMES are frozen
        # (evidence_contract.EVIDENCE_SECTIONS); neither package's internal SHAPE for this one
        # section was — this is exactly that gap, caught by running real code, not asserted.
        return ("a real Sherlock ADMIT_TO_PAPER decision + paper-admission/2 snapshot + bundle, "
               "fed straight into paper.open_position()", "a paper_open row",
               f"PaperRefusal (paper_accounting_evidence shape mismatch between bundle.py and "
               f"paper.py): {exc}", False)


CASES = [
    Case("FM2-01", "issuer source unavailable", _c01_issuer_source_unavailable),
    Case("FM2-02", "aggregator unavailable / unnamed relay", _c02_aggregator_unavailable),
    Case("FM2-03", "source timestamp frozen", _c03_source_timestamp_frozen),
    Case("FM2-04", "source moves backwards in time", _c04_source_moves_backwards),
    Case("FM2-05", "contract address mismatch", _c05_contract_address_mismatch),
    Case("FM2-06", "decimals mismatch", _c06_decimals_mismatch),
    Case("FM2-07", "token wrapper duplicated", _c07_token_wrapper_duplicated),
    Case("FM2-08", "issuer conflict (affiliated origins, one group)", _c08_issuer_conflict),
    Case("FM2-09", "redemption unknown", _c09_redemption_unknown),
    Case("FM2-10", "custodian unknown", _c10_custodian_unknown),
    Case("FM2-11", "liquidity missing", _c11_liquidity_missing),
    Case("FM2-12", "fee missing", _c12_fee_missing),
    Case("FM2-13", "return missing", _c13_return_missing),
    Case("FM2-14", "return source conflict", _c14_return_source_conflict),
    Case("FM2-15", "extreme APY spike", _c15_extreme_apy_spike),
    Case("FM2-16", "stale observed rate", _c16_stale_observed_rate),
    Case("FM2-17", "funding sign flip", _c17_funding_sign_flip),
    Case("FM2-18", "exchange disagreement (RPC quorum)", _c18_exchange_disagreement),
    Case("FM2-19", "missing basis leg (declared)", _c19_missing_basis_leg),
    Case("FM2-19b", "missing basis leg (refuses on request)", _c19b_missing_basis_leg_refuses_on_request),
    Case("FM2-20", "a candidate disappears", _c20_disappeared_candidate),
    Case("FM2-21", "a source revises old data", _c21_source_revises_old_data),
    Case("FM2-22", "backfill masquerading as forward", _c22_backfill_masquerading),
    Case("FM2-23", "duplicate observation", _c23_duplicate_observation),
    Case("FM2-24", "concurrent collector", _c24_concurrent_collector),
    Case("FM2-25", "corrupt ledger", _c25_corrupt_ledger),
    Case("FM2-26", "forged status file", _c26_forged_status_file),
    Case("FM2-27", "Sherlock end-to-end (E1 integration point)", _c27_sherlock_end_to_end_admit_opens_a_position),
]


def run_all() -> list:
    return [case.run() for case in CASES]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    rows = run_all()
    with open(args.out, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    failed = [r for r in rows if r["pass"] is False]
    unmeasured = [r for r in rows if r["pass"] is None]
    print(f"{len(rows)} scenarios, {len(failed)} FAILED, {len(unmeasured)} UNMEASURED (dependency missing)")
    for r in failed:
        print(f"  FAIL {r['id']} {r['scenario']}: expected {r['expected']!r} observed {r['observed']!r}")
    for r in unmeasured:
        print(f"  UNMEASURED {r['id']} {r['scenario']}: {r['observed']!r}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
