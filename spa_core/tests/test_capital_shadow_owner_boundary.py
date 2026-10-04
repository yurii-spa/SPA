# FROZEN-DATE-OK: injected-clock — every freshness judgement gets now=NOW (fixed 2026-10-04T12:00Z) and fixture stamps are pinned relative to that same anchor
"""Owner-boundary regression tests for RM-LIVE-01 capital_shadow (ADR-556 binding architecture
review, 2026-10-04, + the second independent re-review's N1/N3/N4/N7/N8) — CRITICAL finding #1,
HIGH findings #2/#6, MEDIUM finding #11, and N1/N3/N4/N7/N8.

Only ``verify.py``, ``runbook.py``, ``ledger.py`` and ``incidents.py`` are exercised here (the four
modules this pass is scoped to). Every test below is a REGRESSION for a named finding: each one
would fail against the code as it stood before this pass. Fakes stand in for ``simulate``/the RPC
client (interface only); nothing here touches a real network.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.capital_shadow import abi, contract, incidents, intent as intent_mod, keccak, ledger, machine, \
    runbook, simulate, tokens, verify
from spa_core.utils.atomic import atomic_save

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# shared fixtures / helpers
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_common(data_dir: Path, *, now: datetime = NOW) -> None:
    """All three risk-input files, fresh (``generated_at`` = ``now`` - 1h, well inside the 26h
    freshness window) and clean (kill CLEAR, RiskPolicy PASS)."""
    fresh = _iso(now - timedelta(hours=1))
    atomic_save({"generated_at": fresh, "triggered": False, "state": "CLEAR"},
               str(data_dir / "kill_switch_status.json"))
    atomic_save({"policy_compliant": True, "policy_version": "v1.0", "generated_at": fresh},
               str(data_dir / "current_positions.json"))
    atomic_save({"active": False, "generated_at": fresh}, str(data_dir / "derisk_status.json"))
    atomic_save([{"trade_id": "T001", "ts": "2026-10-01T00:00:00Z", "from_allocation": {"aave_v3": 0.0},
                 "to_allocation": {"aave_v3": 1000.0}}], str(data_dir / "trades.json"))


def _pin() -> dict:
    return {"state": "PASS", "number": 100, "hash": "0x" + "cd" * 32, "operators": ["Allnodes", "dRPC"]}


def _write_owner_safe(data_dir: Path, address: str) -> None:
    sub = data_dir / contract.DATA_SUBDIR
    sub.mkdir(parents=True, exist_ok=True)
    atomic_save({"address": address}, str(sub / "owner_safe.json"))


def _write_owner_confirmation(data_dir: Path, incident_id: str, nonce: str) -> None:
    """Simulates the OWNER's own out-of-band act (review N4-ii) — this runtime never does this."""
    sub = data_dir / contract.DATA_SUBDIR / incidents.CONFIRMATIONS_SUBDIR
    sub.mkdir(parents=True, exist_ok=True)
    atomic_save({"nonce": nonce}, str(sub / f"{incident_id}.json"))


def _blank_risk_snapshot() -> dict:
    return {k: {"state": contract.NOT_MEASURED, "value": None, "as_of": None, "digest": None, "reason": "fixture"}
           for k in ("kill_switch", "derisk", "riskpolicy_verdict", "riskpolicy_version", "cio_recommendation_id",
                     "cio_stance", "book_state_digest", "depeg")}


def _supply_intent(*, now: datetime = NOW, ttl_s: int = contract.INTENT_TTL_SHADOW_S, tag: str = "",
                   risk_snapshot: dict | None = None) -> dict:
    return intent_mod._base_fields(
        now=now, pin=_pin(), sleeve_id="defi_conservative", strategy_id=f"defi_conservative:supply{tag}",
        action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", instrument="aave_v3",
        from_asset="USDC", to_asset="USDC", notional=1000.0, notional_unit="USDC",
        source_recommendation_id=None, source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=None,
        risk_snapshot=risk_snapshot if risk_snapshot is not None else _blank_risk_snapshot(), unknowns=[],
        reason=f"fixture{tag}", scenario=contract.SCENARIO_CURRENT, ttl_s=ttl_s)


def _correct_supply_payload(owner_safe: str) -> str:
    usdc_addr = tokens.TOKENS[1]["USDC"]["address"]
    return abi.function_call("supply(address,uint256,address,uint16)",
                             [usdc_addr, 1000 * 10 ** 6, owner_safe, 0])


def _advance_to_manual_pilot_ready(data_dir: Path, an_intent: dict, now: datetime) -> None:
    for state in (contract.S_VALIDATED, contract.S_SIMULATED, contract.S_SHADOW_READY,
                 contract.S_SHADOW_EXECUTED, contract.S_RECONCILED, contract.S_MANUAL_PILOT_READY):
        machine.advance(data_dir, an_intent, state, {}, now)


def _open_owner_action_for(data_dir: Path, an_intent: dict, now: datetime) -> None:
    ledger.open_owner_action_if_none_outstanding(
        data_dir, sleeve_id=an_intent["sleeve_id"], intent_id=an_intent["intent_id"], block=100,
        expires_at=_iso(now + timedelta(hours=1)), now=now)


def _ready_fixture(tmp_path: Path, monkeypatch, *, tag: str = "ready", now: datetime = NOW) -> dict:
    """The full "owner could verify and PASS" baseline: fresh/clean risk files, a configured
    owner Safe, depeg MEASURED and in-band, an intent cleared all the way to MANUAL_PILOT_READY
    with a still-open owner_action, and a payload that matches it field for field. Every N1 ABORT
    test below takes this and deviates exactly ONE thing."""
    _seed_common(tmp_path, now=now)
    monkeypatch.setattr(intent_mod, "read_depeg_state", lambda data_dir: {
        "state": contract.MEASURED, "value": 1.0, "as_of": _iso(now - timedelta(hours=1)), "digest": "d",
        "reason": None})
    owner_safe = "0x" + "aa" * 20
    _write_owner_safe(tmp_path, owner_safe)

    book_digest, book_as_of, _ = intent_mod.book_digest_and_asof(tmp_path, "trades.json")
    risk_snapshot = intent_mod.build_risk_snapshot(tmp_path, now, book_digest=book_digest, book_as_of=book_as_of)
    an_intent = _supply_intent(now=now, tag=tag, risk_snapshot=risk_snapshot)
    machine.record_intent(tmp_path, an_intent, now)
    _advance_to_manual_pilot_ready(tmp_path, an_intent, now)
    _open_owner_action_for(tmp_path, an_intent, now)

    def fake_simulate_intent(intent_arg, *, client=None, now=None, sender=None):
        assert sender == owner_safe, "re-simulation must run from the owner's Safe, never the synthetic sender"
        return {"result": contract.SIM_PASS}
    monkeypatch.setattr(simulate, "simulate_intent", fake_simulate_intent)

    return {
        "intent": an_intent, "owner_safe": owner_safe, "to_address": tokens.VENUES["aave_v3"]["address"],
        "payload_hex": _correct_supply_payload(owner_safe), "value": 0, "operation": 0, "chain_id": 1,
    }


def _verify(tmp_path, fx, *, now=NOW, **overrides):
    kwargs = {"to_address": fx["to_address"], "value": fx["value"], "operation": fx["operation"],
             "chain_id": fx["chain_id"], "data_dir": tmp_path, "now": now}
    kwargs.update(overrides)
    payload_hex = kwargs.pop("payload_hex", fx["payload_hex"])
    return verify.verify(fx["intent"]["intent_id"], payload_hex, **kwargs)


class _NullDispatcher:
    def create_alert(self, level, title, message, adapter_id=None):
        return object()

    def dispatch(self, alert):
        return {"channels_succeeded": []}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# CRITICAL finding #1 + N1 — verify.py
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_verify_passes_on_the_full_clean_baseline(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch)
    result = _verify(tmp_path, fx)
    assert result["verdict"] == "PASS", result["mismatches"]


def test_reproduced_attack_forged_transfer_expired_and_hard_kill_aborts(tmp_path):
    """The EXACT reproduction from the review: a payload for a completely different method (a
    plain ERC-20 ``transfer`` to an attacker) against an intent 30+ days expired, under HARD_KILL.
    The old ``decode_call(payload_hex, [intent.get("instrument")])`` passed a VENUE NAME where a
    signature belonged, always decoded to None, and a None decode added NO mismatch — so none of
    this was ever checked and the old code PASSed. The fixed verify() must ABORT and must name
    the decode failure, the expiry, AND the kill switch."""
    _seed_common(tmp_path)
    atomic_save({"generated_at": "2026-10-04T11:00:00Z", "triggered": True, "state": "HARD_KILL"},
               str(tmp_path / "kill_switch_status.json"))
    owner_safe = "0x" + "aa" * 20
    _write_owner_safe(tmp_path, owner_safe)

    built_at = NOW - timedelta(days=31)
    an_intent = _supply_intent(now=built_at, ttl_s=3600, tag="attack")
    machine.record_intent(tmp_path, an_intent, built_at)

    attacker = "0x" + "ff" * 20
    forged_payload = abi.function_call("transfer(address,uint256)", [attacker, int(1e12)])
    venue_addr = tokens.VENUES["aave_v3"]["address"]

    result = verify.verify(an_intent["intent_id"], forged_payload, to_address=venue_addr, value=0, operation=0,
                           chain_id=1, data_dir=tmp_path, now=NOW)
    assert result["verdict"] == "ABORT"
    assert any("did not decode" in m for m in result["mismatches"]), result["mismatches"]
    assert any("expired" in m for m in result["mismatches"]), result["mismatches"]
    assert any("kill switch" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_on_wrong_target(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="target")
    wrong_target = "0x" + "99" * 20
    result = _verify(tmp_path, fx, to_address=wrong_target)
    assert result["verdict"] == "ABORT"
    assert any("to_address mismatch" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_when_expired(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="exp")
    later = NOW + timedelta(seconds=contract.INTENT_TTL_SHADOW_S + 1)
    result = _verify(tmp_path, fx, now=later)
    assert result["verdict"] == "ABORT"
    assert any("expired" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_under_hard_kill(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="kill")
    atomic_save({"generated_at": "2026-10-04T11:00:00Z", "triggered": True, "state": "HARD_KILL"},
               str(tmp_path / "kill_switch_status.json"))
    result = _verify(tmp_path, fx)
    assert result["verdict"] == "ABORT"
    assert any("kill switch" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_when_resimulation_sender_override_unsupported(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="nosender")

    def fake_simulate_intent_no_sender(intent_arg, *, client=None, now=None):
        return {"result": contract.SIM_PASS}
    monkeypatch.setattr(simulate, "simulate_intent", fake_simulate_intent_no_sender)

    result = _verify(tmp_path, fx)
    assert result["verdict"] == "ABORT"
    assert any("sender" in m and "unsupported" in m for m in result["mismatches"]), result["mismatches"]


# ── N1a — intent must have reached MANUAL_PILOT_READY/OWNER_GATE with an open, matching owner_action

def test_verify_aborts_without_reaching_manual_pilot_ready(tmp_path, monkeypatch):
    """Same clean world, but the intent was never advanced past DRAFT and no runbook/owner_action
    was ever issued for it — verify must refuse to treat a payload as something the owner was
    ever asked to sign."""
    _seed_common(tmp_path)
    monkeypatch.setattr(intent_mod, "read_depeg_state", lambda data_dir: {
        "state": contract.MEASURED, "value": 1.0, "as_of": None, "digest": "d", "reason": None})
    owner_safe = "0x" + "aa" * 20
    _write_owner_safe(tmp_path, owner_safe)
    an_intent = _supply_intent(tag="nostate")
    machine.record_intent(tmp_path, an_intent, NOW)

    result = verify.verify(an_intent["intent_id"], _correct_supply_payload(owner_safe),
                           to_address=tokens.VENUES["aave_v3"]["address"], value=0, operation=0, chain_id=1,
                           data_dir=tmp_path, now=NOW)
    assert result["verdict"] == "ABORT"
    assert any("not MANUAL_PILOT_READY" in m for m in result["mismatches"]), result["mismatches"]
    assert any("no recorded, still-open owner_action" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_when_owner_action_was_issued_for_a_different_intent(tmp_path, monkeypatch):
    """The sleeve HAS an open, current owner_action — but for a DIFFERENT intent than the one this
    payload claims to verify. Must still ABORT: a runbook for intent A is never license to sign
    for intent B."""
    fx = _ready_fixture(tmp_path, monkeypatch, tag="other")
    other_intent = _supply_intent(tag="other-second")
    machine.record_intent(tmp_path, other_intent, NOW)
    _advance_to_manual_pilot_ready(tmp_path, other_intent, NOW)

    result = verify.verify(other_intent["intent_id"], _correct_supply_payload(fx["owner_safe"]),
                           to_address=fx["to_address"], value=0, operation=0, chain_id=1, data_dir=tmp_path,
                           now=NOW)
    assert result["verdict"] == "ABORT"
    assert any("no recorded, still-open owner_action" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_for_a_test_scenario_intent(tmp_path):
    _seed_common(tmp_path)
    scenario_intent = intent_mod.build_scenario_intents(NOW, _pin(), "verify-scenario")[0]
    machine.record_intent(tmp_path, scenario_intent, NOW)
    result = verify.verify(scenario_intent["intent_id"], "0x" + "00" * 4,
                           to_address="0x" + "11" * 20, value=0, operation=0, chain_id=1, data_dir=tmp_path,
                           now=NOW)
    assert result["verdict"] == "ABORT"
    assert any("not CURRENT_STATE" in m for m in result["mismatches"]), result["mismatches"]


# ── N1b — freshness of the risk input files

def test_freshness_check_unit(tmp_path):
    atomic_save({"generated_at": _iso(NOW - timedelta(hours=1))}, str(tmp_path / "x.json"))
    fresh = verify.freshness_check(tmp_path, "x.json", NOW)
    assert fresh["fresh"] is True

    atomic_save({"generated_at": _iso(NOW - timedelta(hours=27))}, str(tmp_path / "stale.json"))
    stale = verify.freshness_check(tmp_path, "stale.json", NOW)
    assert stale["fresh"] is False
    assert "27.0h old" in stale["reason"] or "h old" in stale["reason"]

    missing = verify.freshness_check(tmp_path, "nope.json", NOW)
    assert missing["fresh"] is False
    assert "unavailable" in missing["reason"]


def test_verify_aborts_on_stale_risk_input_file(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="stale")
    atomic_save({"policy_compliant": True, "policy_version": "v1.0",
               "generated_at": _iso(NOW - timedelta(hours=30))}, str(tmp_path / "current_positions.json"))
    result = _verify(tmp_path, fx)
    assert result["verdict"] == "ABORT"
    assert any("current_positions.json is not fresh" in m for m in result["mismatches"]), result["mismatches"]


# ── N1c — strict calldata decode (unit tests against verify.strict_decode_call directly)

def test_strict_decode_rejects_trailing_bytes(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="trailing")
    padded_payload = fx["payload_hex"] + "00" * 32  # one extra, bogus trailing word
    result = _verify(tmp_path, fx, payload_hex=padded_payload)
    assert result["verdict"] == "ABORT"
    assert any("calldata length" in m for m in result["mismatches"]), result["mismatches"]

    decoded, reason = verify.strict_decode_call(padded_payload, "supply(address,uint256,address,uint16)")
    assert decoded is None
    assert "calldata length" in reason


def test_strict_decode_rejects_truncated_payload():
    full = abi.function_call("supply(address,uint256,address,uint16)",
                             ["0x" + "11" * 20, 1000, "0x" + "22" * 20, 0])
    truncated = full[:-10]
    decoded, reason = verify.strict_decode_call(truncated, "supply(address,uint256,address,uint16)")
    assert decoded is None
    assert "calldata length" in reason


def test_strict_decode_rejects_noncanonical_address_upper_bytes():
    sig = "approve(address,uint256)"
    sel = keccak.selector(sig)
    dirty_upper = bytes([1]) + bytes(11) + bytes(20)  # non-zero upper byte, never a canonical address word
    amount_word = (1000).to_bytes(32, "big")
    payload = sel + dirty_upper.hex() + amount_word.hex()
    decoded, reason = verify.strict_decode_call(payload, sig)
    assert decoded is None
    assert "non-canonical" in reason


def test_strict_decode_rejects_noncanonical_bool():
    sig = "foo(bool)"
    sel = keccak.selector(sig)
    bad_bool_word = (2).to_bytes(32, "big")  # neither 0 nor 1
    payload = sel + bad_bool_word.hex()
    decoded, reason = verify.strict_decode_call(payload, sig)
    assert decoded is None
    assert "canonical" in reason


def test_strict_decode_accepts_canonical_payload():
    sig = "supply(address,uint256,address,uint16)"
    addr = "0x" + "11" * 20
    payload = abi.function_call(sig, [addr, 1000, "0x" + "22" * 20, 0])
    decoded, reason = verify.strict_decode_call(payload, sig)
    assert reason is None
    assert decoded["args"][0] == addr


# ── N1d — depeg must be MEASURED and within band

def test_verify_aborts_when_depeg_outside_band(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="depeg")
    monkeypatch.setattr(intent_mod, "read_depeg_state", lambda data_dir: {
        "state": contract.MEASURED, "value": 0.97, "as_of": None, "digest": "d", "reason": None})
    result = _verify(tmp_path, fx)
    assert result["verdict"] == "ABORT"
    assert any("outside band" in m for m in result["mismatches"]), result["mismatches"]


# ── N1e — value / operation / chain_id are REQUIRED wallet fields

def test_verify_aborts_on_nonzero_native_value(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="value")
    result = _verify(tmp_path, fx, value=1)
    assert result["verdict"] == "ABORT"
    assert any("tx value" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_on_delegatecall_operation(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="delegatecall")
    result = _verify(tmp_path, fx, operation=1)
    assert result["verdict"] == "ABORT"
    assert any("DELEGATECALL" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_aborts_on_wrong_chain_id(tmp_path, monkeypatch):
    fx = _ready_fixture(tmp_path, monkeypatch, tag="chain")
    result = _verify(tmp_path, fx, chain_id=8453)
    assert result["verdict"] == "ABORT"
    assert any("chain_id mismatch" in m for m in result["mismatches"]), result["mismatches"]


def test_verify_cli_requires_value_operation_chain_id(tmp_path, monkeypatch, capsys):
    _seed_common(tmp_path)
    # no owner Safe configured in this scene -> guaranteed ABORT regardless of chain/venue, so
    # this is purely a smoke test of the CLI's required-argument wiring.
    an_intent = _supply_intent(tag="cli-n1e")
    machine.record_intent(tmp_path, an_intent, NOW)
    with pytest.raises(SystemExit):
        verify.main(["--intent", an_intent["intent_id"], "--payload", "0x1234", "--to-address",
                    "0x" + "33" * 20, "--data-dir", str(tmp_path)])  # missing --value/--operation/--chain-id

    rc = verify.main(["--intent", an_intent["intent_id"], "--payload", "0x1234", "--to-address",
                      "0x" + "33" * 20, "--value", "0", "--operation", "0", "--chain-id", "1",
                      "--data-dir", str(tmp_path)])
    assert rc == contract.EXIT_FAIL
    out = capsys.readouterr().out
    assert "ABORT" in out


# ══════════════════════════════════════════════════════════════════════════════════════════════
# HIGH finding #2 — runbook.py (never the simulation's own call; asserts replaced with refusals)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_runbook_builds_args_from_pinned_registry_never_simulation(tmp_path):
    # two INDEPENDENT data dirs on purpose: generating two runbooks for the same sleeve in the
    # same store is HIGH finding #6's own territory (single outstanding owner action), covered
    # separately below — this test is only about WHERE the displayed arguments come from.
    scene1, scene2 = tmp_path / "scene1", tmp_path / "scene2"
    _seed_common(scene1)
    _seed_common(scene2)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    an_intent = _supply_intent(tag="registry")
    synthetic_sender = "0x" + "11" * 20
    fake_sim = {"call": {"signature": "supply(address,uint256,address,uint16)", "selector": "0xdeadbeef",
               "args_readable": f"asset=0xbad, amount=999999, onBehalfOf={synthetic_sender}, referralCode=0"},
               "block": {"number": 100, "hash": "0x" + "ab" * 32, "operators": ["Allnodes", "dRPC"]}}
    text = runbook.generate(report, an_intent, fake_sim, data_dir=scene1, now=NOW)
    assert synthetic_sender not in text
    assert "999999" not in text
    assert "0xbad" not in text
    assert tokens.VENUES["aave_v3"]["address"] in text
    assert "OWNER_DECISION_REQUIRED" in text
    assert "OWNER_SAFE (NOT CONFIGURED)" in text  # no owner_safe.json seeded in this scene

    owner_safe = "0x" + "aa" * 20
    _write_owner_safe(scene2, owner_safe)
    text2 = runbook.generate(report, _supply_intent(tag="registry2"), fake_sim, data_dir=scene2, now=NOW)
    assert owner_safe in text2
    assert f"OWNER_SAFE (configured address: {owner_safe})" in text2


def test_runbook_refuses_when_a_field_would_leak_hex(tmp_path, monkeypatch):
    """Replaces the old bare ``assert`` (silently stripped under ``python -O``): any field that
    would print a raw hex literal outside the explicitly-allowed lines is an explicit refusal."""
    _seed_common(tmp_path)
    monkeypatch.setattr(tokens, "registry_digest", lambda: "0x" + "ab" * 40)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    an_intent = _supply_intent(tag="leak")
    with pytest.raises(runbook.RunbookRefused):
        runbook.generate(report, an_intent, None, data_dir=tmp_path, now=NOW)


def test_runbook_leak_guard_survives_python_dash_O(tmp_path):
    """The exact HIGH #2 hazard: a guard implemented as a bare ``assert`` disappears under
    ``python -O``. This runs the SAME leak scenario as the test above in a real ``-O`` subprocess
    and proves the refusal still fires — there is no assert left to strip."""
    script = (
        "import sys; sys.path.insert(0, " + repr(str(REPO_ROOT)) + ")\n"
        "from spa_core.capital_shadow import contract, runbook, tokens\n"
        "tokens.registry_digest = lambda: '0x' + 'ab' * 40\n"
        "report = {'readiness_state': contract.R_MANUAL_PILOT_READY, 'candidate_sleeve': 'defi_conservative'}\n"
        "import datetime as _dt\n"
        "an_intent = {'scenario': contract.SCENARIO_CURRENT, 'intent_id': 'leak-O',\n"
        "            'action_type': contract.ACTION_SUPPLY, 'network_or_venue': 'aave_v3',\n"
        "            'from_asset': 'USDC', 'notional': 1000.0, 'sleeve_id': 'defi_conservative',\n"
        "            'expires_at': (_dt.datetime.now(_dt.timezone.utc) + "
        "_dt.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        "try:\n"
        "    runbook.generate(report, an_intent, None, data_dir=" + repr(str(tmp_path)) + ", now=None)\n"
        "    print('NO_REFUSAL')\n"
        "except runbook.RunbookRefused:\n"
        "    print('REFUSED')\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", script], capture_output=True, text=True, timeout=30)
    assert "REFUSED" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_runbook_has_no_bare_assert():
    """Static regression for HIGH #2: the previous implementation's ONLY guard against leaking the
    simulation's synthetic sender was a bare ``assert`` (stripped under ``-O``). Zero ``assert``
    statements must remain in this module."""
    import ast
    tree = ast.parse(Path(REPO_ROOT / "spa_core" / "capital_shadow" / "runbook.py").read_text())
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert asserts == [], f"runbook.py still has {len(asserts)} bare assert(s) at line(s) " \
                          f"{[n.lineno for n in asserts]}"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# HIGH finding #6 / review N3 — single outstanding owner action + single-use approval
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_runbook_refuses_second_runbook_while_sleeve_action_open(tmp_path):
    _seed_common(tmp_path)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    intent_a = _supply_intent(tag="a")
    intent_b = _supply_intent(tag="b")

    text = runbook.generate(report, intent_a, None, data_dir=tmp_path, now=NOW)
    assert text is not None

    with pytest.raises(runbook.RunbookRefused):
        runbook.generate(report, intent_b, None, data_dir=tmp_path, now=NOW)

    # re-generating for the SAME intent is allowed (its own new audit row), never a refusal.
    text_again = runbook.generate(report, intent_a, None, data_dir=tmp_path, now=NOW)
    assert text_again is not None


def test_runbook_each_issuance_gets_its_own_ledger_row(tmp_path):
    """Review N3: re-issuing for the SAME intent creates a NEW row (own ``issued_at``), never
    collapses into the first one — each issuance is its own audit entry."""
    _seed_common(tmp_path)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    an_intent = _supply_intent(tag="issuances")
    runbook.generate(report, an_intent, None, data_dir=tmp_path, now=NOW)
    later = NOW + timedelta(seconds=1)
    runbook.generate(report, an_intent, None, data_dir=tmp_path, now=later)
    rows = [e for e in ledger.read_all(tmp_path) if e.get("kind") == "owner_action"]
    assert len(rows) == 2
    assert rows[0]["key"] != rows[1]["key"]


def test_runbook_allows_new_runbook_after_owner_action_expires_by_now(tmp_path):
    """"Open" is computed from ``now`` every call (TOCTOU-safe) — nobody has to remember to write
    an EXPIRED row for a new runbook to become possible again once the old one's own
    ``expires_at`` has passed."""
    _seed_common(tmp_path)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    intent_a = _supply_intent(tag="exp-a")
    intent_b = _supply_intent(tag="exp-b")

    runbook.generate(report, intent_a, None, data_dir=tmp_path, now=NOW)
    much_later = NOW + timedelta(seconds=contract.INTENT_TTL_PILOT_S + 1)
    text = runbook.generate(report, intent_b, None, data_dir=tmp_path, now=much_later)
    assert text is not None


def test_runbook_allows_new_runbook_after_owner_action_explicitly_closed(tmp_path):
    _seed_common(tmp_path)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    intent_a = _supply_intent(tag="close-a")
    intent_b = _supply_intent(tag="close-b")

    runbook.generate(report, intent_a, None, data_dir=tmp_path, now=NOW)
    ledger.close_owner_action(tmp_path, sleeve_id="defi_conservative", intent_id=intent_a["intent_id"],
                              status="CANCELLED", now=NOW, detail="owner cancelled")
    assert ledger.outstanding_owner_action(tmp_path, "defi_conservative", NOW) is None
    text = runbook.generate(report, intent_b, None, data_dir=tmp_path, now=NOW)
    assert text is not None


def test_runbook_refuses_cross_sleeve_mismatch(tmp_path):
    _seed_common(tmp_path)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_balanced"}
    an_intent = _supply_intent(tag="crosssleeve")  # sleeve_id="defi_conservative"
    with pytest.raises(runbook.RunbookRefused, match="cross-sleeve"):
        runbook.generate(report, an_intent, None, data_dir=tmp_path, now=NOW)


def test_runbook_refuses_an_expired_intent(tmp_path):
    _seed_common(tmp_path)
    report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    an_intent = _supply_intent(tag="expired-runbook", ttl_s=10)
    later = NOW + timedelta(seconds=20)
    with pytest.raises(runbook.RunbookRefused, match="expired"):
        runbook.generate(report, an_intent, None, data_dir=tmp_path, now=later)


def test_owner_action_check_and_append_are_atomic_under_one_lock(tmp_path, monkeypatch):
    """Review N3: the previous code read ``outstanding_owner_action`` and wrote
    ``open_owner_action`` as two SEPARATE, unlocked-between-them calls. This proves the fused
    primitive (`open_owner_action_if_none_outstanding`) holds ONE lock across both — if it
    didn't, a second call racing in between the check and the write (simulated here by patching
    ``outstanding_owner_action`` to flip its answer mid-call) could observe a stale "none open"."""
    calls = {"n": 0}
    real_check = ledger.outstanding_owner_action

    def flipping_check(data_dir, sleeve_id, now):
        calls["n"] += 1
        return real_check(data_dir, sleeve_id, now)
    monkeypatch.setattr(ledger, "outstanding_owner_action", flipping_check)

    entry1, created1 = ledger.open_owner_action_if_none_outstanding(
        tmp_path, sleeve_id="defi_conservative", intent_id="intent-1", block=1, expires_at=_iso(NOW + timedelta(hours=1)),
        now=NOW)
    assert created1 is True
    with pytest.raises(ledger.OwnerActionAlreadyOpen):
        ledger.open_owner_action_if_none_outstanding(
            tmp_path, sleeve_id="defi_conservative", intent_id="intent-2", block=1,
            expires_at=_iso(NOW + timedelta(hours=1)), now=NOW)
    assert calls["n"] == 2


def test_record_and_consume_owner_approval_single_use(tmp_path):
    entry = ledger.record_owner_approval(tmp_path, "intent-x", 100, _iso(NOW + timedelta(hours=1)), now=NOW)
    assert entry["payload"]["used"] is False

    consumed = ledger.consume_owner_approval(tmp_path, "intent-x", 100, _iso(NOW + timedelta(hours=1)), now=NOW)
    assert consumed["payload"]["used"] is True

    with pytest.raises(ledger.ApprovalAlreadyUsed):
        ledger.consume_owner_approval(tmp_path, "intent-x", 100, _iso(NOW + timedelta(hours=1)), now=NOW)


def test_consume_owner_approval_without_record_is_refused(tmp_path):
    with pytest.raises(ledger.LedgerError):
        ledger.consume_owner_approval(tmp_path, "never-recorded", 1, _iso(NOW + timedelta(hours=1)), now=NOW)


def test_consume_owner_approval_refuses_when_expired(tmp_path):
    """Review N8: an approval past its own ``expires_at`` may never be consumed, even on its
    FIRST use."""
    expires_at = _iso(NOW + timedelta(minutes=5))
    ledger.record_owner_approval(tmp_path, "intent-y", 100, expires_at, now=NOW)
    later = NOW + timedelta(minutes=10)
    with pytest.raises(ledger.ApprovalExpired):
        ledger.consume_owner_approval(tmp_path, "intent-y", 100, expires_at, now=later)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# MEDIUM finding #11 / N4 — ledger/incident integrity
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_incidents_hash_chained_with_sibling_anchor(tmp_path):
    row = incidents.raise_incident(tmp_path, "forbidden_method", "test", now=NOW, dispatcher=_NullDispatcher())
    assert row["prev_hash"] == incidents.GENESIS
    assert isinstance(row["entry_hash"], str) and row["entry_hash"]
    anchors = incidents._read_anchors(tmp_path)
    assert len(anchors) == 1
    assert anchors[0]["entry_hash"] == row["entry_hash"]
    assert incidents.verify_chain(tmp_path)["ok"] is True

    row2 = incidents.raise_incident(tmp_path, "quorum_disagreement", "test2", now=NOW, dispatcher=_NullDispatcher())
    assert row2["prev_hash"] == row["entry_hash"]
    assert incidents.verify_chain(tmp_path)["ok"] is True


def test_incidents_torn_line_is_broken_not_silently_skipped(tmp_path):
    incidents.raise_incident(tmp_path, "forbidden_method", "test", now=NOW, dispatcher=_NullDispatcher())
    path = tmp_path / contract.DATA_SUBDIR / contract.INCIDENTS
    with open(path, "a") as f:
        f.write("{not valid json\n")

    verdict = incidents.verify_chain(tmp_path)
    assert verdict["ok"] is False
    assert verdict["reason"] == "torn_line"
    with pytest.raises(incidents.IncidentStoreBroken):
        incidents.read_all(tmp_path)
    with pytest.raises(incidents.IncidentStoreBroken):
        incidents.open_incidents(tmp_path)
    assert incidents.store_state(tmp_path) == {"state": "BROKEN", "reason": "torn_line (break_at=2, entries=1)"}


def test_incidents_file_deleted_while_anchors_exist_is_broken(tmp_path):
    incidents.raise_incident(tmp_path, "forbidden_method", "test", now=NOW, dispatcher=_NullDispatcher())
    path = tmp_path / contract.DATA_SUBDIR / contract.INCIDENTS
    path.unlink()

    verdict = incidents.verify_chain(tmp_path)
    assert verdict["ok"] is False
    assert verdict["reason"] == "file_deleted_with_anchors"
    with pytest.raises(incidents.IncidentStoreBroken):
        incidents.read_all(tmp_path)
    assert incidents.store_state(tmp_path)["state"] == "BROKEN"


def test_store_state_ok_on_clean_store(tmp_path):
    incidents.raise_incident(tmp_path, "forbidden_method", "test", now=NOW, dispatcher=_NullDispatcher())
    assert incidents.store_state(tmp_path) == {"state": "OK", "reason": None}


# ── N4-ii: owner confirmation must be a VERIFIED, file-based, out-of-band act ───────────────────

def test_clear_incident_requires_owner_confirmation_file_with_the_right_nonce(tmp_path):
    row = incidents.raise_incident(tmp_path, "ledger_broken", "x", now=NOW, dispatcher=_NullDispatcher())
    nonce = row["confirmation_nonce"]
    assert nonce

    # no file at all -> refused
    with pytest.raises(ValueError):
        incidents.clear_incident(tmp_path, row["incident_id"], "repaired, verified")

    # a file exists but with an ARBITRARY (wrong) string -> still refused, never "non-empty is enough"
    _write_owner_confirmation(tmp_path, row["incident_id"], "some-arbitrary-string")
    with pytest.raises(ValueError):
        incidents.clear_incident(tmp_path, row["incident_id"], "repaired, verified")

    # the REAL nonce, placed by the (simulated) owner -> clears
    _write_owner_confirmation(tmp_path, row["incident_id"], nonce)
    cleared = incidents.clear_incident(tmp_path, row["incident_id"], "repaired, verified")
    assert cleared["status"] == "CLEARED"
    assert cleared["confirmation_token"] == nonce


@pytest.mark.parametrize("kind", sorted(incidents.OWNER_CONFIRMATION_REQUIRED_KINDS))
def test_clear_incident_requires_confirmation_for_every_sensitive_kind(tmp_path, kind):
    row = incidents.raise_incident(tmp_path, kind, "x", now=NOW, dispatcher=_NullDispatcher())
    with pytest.raises(ValueError):
        incidents.clear_incident(tmp_path, row["incident_id"], "repaired")
    _write_owner_confirmation(tmp_path, row["incident_id"], row["confirmation_nonce"])
    cleared = incidents.clear_incident(tmp_path, row["incident_id"], "repaired")
    assert cleared["status"] == "CLEARED"


def test_clear_incident_allows_non_sensitive_kind_without_confirmation_file(tmp_path):
    row = incidents.raise_incident(tmp_path, "forbidden_method", "x", now=NOW, dispatcher=_NullDispatcher())
    cleared = incidents.clear_incident(tmp_path, row["incident_id"], "repaired")
    assert cleared["status"] == "CLEARED"


def test_ledger_repaired_is_an_owner_confirmation_required_kind():
    assert "ledger_repaired" in incidents.OWNER_CONFIRMATION_REQUIRED_KINDS


# ── N4-iv: mid-chain tamper refuses outright; auto-reanchor is gone ─────────────────────────────

def test_ledger_repair_refuses_mid_chain_tamper(tmp_path):
    an_intent_1 = _supply_intent(tag="tamper1")
    machine.record_intent(tmp_path, an_intent_1, NOW)
    an_intent_2 = _supply_intent(tag="tamper2")
    machine.record_intent(tmp_path, an_intent_2, NOW)

    ledger_path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    lines = ledger_path.read_text().splitlines()
    assert len(lines) == 2
    lines[0] = "{not valid json, but something follows me"
    ledger_path.write_text("\n".join(lines) + "\n")

    result = ledger.repair(tmp_path, dispatcher=_NullDispatcher())
    assert result["repaired"] is False
    assert result["fixable"] is False
    assert "tampered" in result["reason"]
    # nothing moved aside, nothing silently discarded
    assert ledger_path.read_text().splitlines() == "{not valid json, but something follows me".splitlines() + \
          [lines[1]]
    incs = incidents.open_incidents(tmp_path)
    assert any(i["kind"] == "ledger_tampered" for i in incs), incs


def test_ledger_repair_still_moves_aside_a_torn_last_line(tmp_path):
    an_intent = _supply_intent(tag="tornlast")
    machine.record_intent(tmp_path, an_intent, NOW)
    ledger_path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    with open(ledger_path, "a") as f:
        f.write('{"seq": 2, "incomplete')  # a crash mid-write of the NEXT (last) line

    result = ledger.repair(tmp_path, dispatcher=_NullDispatcher())
    assert result["repaired"] is True
    assert result["moved_lines"] == 1
    after = ledger.verify_chain(tmp_path)
    assert after["ok"] is True


def test_ledger_repair_no_longer_auto_reanchors_requires_owner_confirmation(tmp_path):
    an_intent = _supply_intent(tag="noauto")
    machine.record_intent(tmp_path, an_intent, NOW)

    anchors_path = tmp_path / contract.ANCHORS_SUBDIR / "anchors.jsonl"
    assert len(anchors_path.read_text().splitlines()) == 1
    anchors_path.write_text("")  # simulate a crash between the ledger write and the anchor write

    before = ledger.verify_chain(tmp_path)
    assert before["ok"] is False and before["reason"] == "anchor_missing"

    result = ledger.repair(tmp_path, dispatcher=_NullDispatcher())
    assert result["repaired"] is False, "N4-iv: automatic re-anchoring must no longer happen at all"
    assert result["fixable"] is True
    incident_id = result["incident_id"]
    assert incident_id

    still_broken = ledger.verify_chain(tmp_path)
    assert still_broken["ok"] is False

    # the owner's out-of-band act: copy the nonce the incident carries into the confirmation file.
    incident_row = next(i for i in incidents.open_incidents(tmp_path) if i["incident_id"] == incident_id)
    assert incident_row["kind"] == "anchor_broken"
    _write_owner_confirmation(tmp_path, incident_id, incident_row["confirmation_nonce"])

    reanchor_result = ledger.reanchor_with_owner_confirmation(tmp_path, incident_id, now=NOW)
    assert reanchor_result["repaired"] is True
    after = ledger.verify_chain(tmp_path)
    assert after["ok"] is True
    assert all(i["incident_id"] != incident_id for i in incidents.open_incidents(tmp_path))
    assert any(i["kind"] == "ledger_repaired" for i in incidents.open_incidents(tmp_path))


def test_reanchor_with_owner_confirmation_refuses_wrong_nonce(tmp_path):
    an_intent = _supply_intent(tag="wrongnonce")
    machine.record_intent(tmp_path, an_intent, NOW)
    anchors_path = tmp_path / contract.ANCHORS_SUBDIR / "anchors.jsonl"
    anchors_path.write_text("")
    result = ledger.repair(tmp_path, dispatcher=_NullDispatcher())
    incident_id = result["incident_id"]
    _write_owner_confirmation(tmp_path, incident_id, "totally-made-up-nonce")
    with pytest.raises(ledger.LedgerError):
        ledger.reanchor_with_owner_confirmation(tmp_path, incident_id, now=NOW)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# N7 — raise_incident(dispatcher=None) must never touch the real repo-global alert state
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_raise_incident_default_dispatcher_never_touches_real_repo_data(tmp_path):
    real_dedup = REPO_ROOT / "data" / "alert_dispatcher_dedup.json"
    before = real_dedup.read_bytes() if real_dedup.exists() else None

    incidents.raise_incident(tmp_path, "forbidden_method", "scratch-run test", now=NOW)  # dispatcher=None

    after = real_dedup.read_bytes() if real_dedup.exists() else None
    assert before == after, "a scratch data_dir incident must never mutate the repo's own live alert state"

    outbox = tmp_path / contract.DATA_SUBDIR / incidents.ALERTS_OUTBOX_FILE
    assert outbox.exists()
    assert "capital_shadow INCIDENT: forbidden_method" in outbox.read_text()


def test_default_dispatcher_is_outbox_for_non_production_dir(tmp_path):
    assert isinstance(incidents._default_dispatcher(tmp_path), incidents._OutboxDispatcher)


def test_default_dispatcher_is_real_only_for_the_actual_production_dir(monkeypatch, tmp_path):
    from spa_core.utils import live_paths
    monkeypatch.setattr(live_paths, "live_data_dir", lambda *a, **k: tmp_path)
    dispatcher = incidents._default_dispatcher(tmp_path)
    assert not isinstance(dispatcher, incidents._OutboxDispatcher)
