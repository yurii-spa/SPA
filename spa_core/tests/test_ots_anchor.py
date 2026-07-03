"""
test_ots_anchor.py — external-anchoring layer (ADR-YL-010).

No network, no real `ots` client: subprocess is injected via `_run`/`ots_bin`. Asserts digest-file
creation, append-only ledger, idempotency, graceful degradation, upgrade-event append, and the
no-keys / no-mutation invariants.
"""
# LLM_FORBIDDEN
import json
import types

import pytest

from spa_core.audit import ots_anchor


HEAD = "3a467bedbeb3b1e3b562dd95c418113ecd79e23ab4207d7b5e3909b5b0839a0e"


def _fake_run_success(ots_dir):
    """A fake subprocess.run that 'produces' a .ots file, like a real `ots stamp` would."""
    def _run(cmd, **kw):
        # cmd = [ots_bin, "stamp", <digest_file>]
        if len(cmd) >= 3 and cmd[1] == "stamp":
            open(cmd[2] + ".ots", "wb").write(b"\x00OpenTimestamps\x00fake-proof")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    return _run


def test_stamp_creates_digest_and_ledger(tmp_path):
    d = tmp_path / "ots"
    ledger = d / "ots_anchors.jsonl"
    entry = ots_anchor.stamp_head(
        HEAD, 580, source="rates_desk",
        ots_dir=d, ledger_path=ledger, ots_bin="/fake/ots", _run=_fake_run_success(d),
    )
    assert entry["status"] == "pending"
    assert entry["head_hash"] == HEAD
    # digest file content is EXACTLY the head hash (re-creatable by a verifier)
    digest = d / f"{HEAD}.head"
    assert digest.read_text().strip() == HEAD
    assert (d / f"{HEAD}.head.ots").exists()
    # ledger has exactly one append-only line
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    assert len(rows) == 1 and rows[0]["event"] == "ots_stamp"


def test_idempotent_per_head(tmp_path):
    d = tmp_path / "ots"
    ledger = d / "ots_anchors.jsonl"
    run = _fake_run_success(d)
    ots_anchor.stamp_head(HEAD, 580, ots_dir=d, ledger_path=ledger, ots_bin="/fake/ots", _run=run)
    second = ots_anchor.stamp_head(HEAD, 580, ots_dir=d, ledger_path=ledger, ots_bin="/fake/ots", _run=run)
    assert second.get("idempotent_noop") is True
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    assert len(rows) == 1  # no duplicate stamp appended


def test_graceful_degradation_no_client(tmp_path):
    d = tmp_path / "ots"
    ledger = d / "ots_anchors.jsonl"
    # ots_bin=None simulates the client being unavailable
    entry = ots_anchor.stamp_head(HEAD, 580, ots_dir=d, ledger_path=ledger, ots_bin=None)
    assert entry["status"] == "client_unavailable"
    # digest file STILL written (head existence recorded append-only for later stamping)
    assert (d / f"{HEAD}.head").read_text().strip() == HEAD
    assert entry["ots_file"] is None


def test_upgrade_appends_event_never_mutates(tmp_path):
    d = tmp_path / "ots"
    ledger = d / "ots_anchors.jsonl"
    ots_anchor.stamp_head(HEAD, 580, ots_dir=d, ledger_path=ledger,
                          ots_bin="/fake/ots", _run=_fake_run_success(d))
    before = ledger.read_text()

    def _run_upgrade(cmd, **kw):
        return types.SimpleNamespace(returncode=0, stdout="Success! Bitcoin block 900000", stderr="")

    summary = ots_anchor.upgrade_pending(
        ots_dir=d, ledger_path=ledger, ots_bin="/fake/ots", _run=_run_upgrade,
    )
    assert summary["upgraded"] == 1
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    # the original stamp line is UNCHANGED (append-only); a new upgrade event was appended
    assert ledger.read_text().startswith(before)
    assert any(r["event"] == "ots_upgrade" and r["status"] == "confirmed" for r in rows)


def test_bad_head_rejected(tmp_path):
    with pytest.raises(ValueError):
        ots_anchor.stamp_head("short", 1, ots_dir=tmp_path, ledger_path=tmp_path / "l.jsonl")


def test_no_private_keys_or_signing_in_source():
    """Invariant: the module never touches keys/signing/fund movement."""
    import inspect
    src = inspect.getsource(ots_anchor).lower()
    for bad in ("private_key", "seed_phrase", "sign(", "sendtoaddress", "wallet", "sk_"):
        assert bad not in src, f"forbidden token in ots_anchor: {bad}"
