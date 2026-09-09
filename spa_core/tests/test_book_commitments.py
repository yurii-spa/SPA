# FROZEN-DATE-OK: injected-clock — every clock is an explicit argument: commit(ts=TS_D1), reveal_due(today=D2, ts=TS_D2), check_book_commitments(now=NOW_D2); the wall clock is never read by the subject under test
"""test_book_commitments.py — task 4 of inbox «Целостность трека SPA»: commit-reveal of the daily
BOOK decision (practice transferred from earn-defi ``commit_reveal.py``).

Positive controls, each one a way the attestation could lie:
  • the public trail HIDES the package — a commit row carries the hash and nothing else;
  • a reveal re-hashes to its earlier commit; a tampered package / salt does not;
  • the salt makes two identical decisions hash differently (and the same salt → the same hash);
  • a tampered trail row breaks the chain at that row;
  • a reveal never happens before the delay; a date is committed exactly once (a re-run never re-salts);
  • the publisher sees the hash at commit time and the package only at reveal time; the default
    publisher lands in the digest QUEUE file (never a live Telegram call);
  • the cycle_runner hooks have the form of a CALL: commit sits AFTER the risk_verdict audit event and
    BEFORE the trade is written; reveal sits at cycle start; both are wrapped so they cannot crash
    the cycle; the artifact is declared in PRODUCES;
  • the STANDALONE verifier (loaded by path, no spa_core) verifies a synthetic trail and reports the
    precise broken_at on tamper, on a reveal without a commit, and on a hash mismatch;
  • the monitor's third outcome: no trail ⇒ UNCHECKED (never HEALTHY); commit on the last decision
    ⇒ HEALTHY; a missed cycle / an overdue reveal ⇒ WARNING; the signal is advisory.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.audit import book_commitments as bc  # noqa: E402
from spa_core.monitoring import cycle_health_monitor as chm  # noqa: E402

D1 = "2026-09-08"
D2 = "2026-09-09"
D3 = "2026-09-10"
TS_D1 = D1 + "T06:00:00+00:00"
TS_D2 = D2 + "T06:00:00+00:00"
TS_D3 = D3 + "T06:00:00+00:00"
NOW_D2 = datetime.fromisoformat(TS_D2)
NOW_D3 = datetime.fromisoformat(TS_D3)
NOW_LATE = datetime.fromisoformat("2026-09-13T06:00:00+00:00")

TARGET = {"aave_v3": 40000.004, "compound_v3": 35000.0, "sky_susds": 20000.5}


class _Capture:
    """A publisher double: records what would have gone to the digest, returns a delivery dict."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def __call__(self, kind: str, key: str, title: str, body: str) -> dict:
        self.calls.append((kind, key, title, body))
        return {"channel": "test", "queued": True}


def _commit(tmp: Path, date: str = D1, ts: str = TS_D1, publish=None, **kw):
    return bc.commit(tmp, cycle_date=date, snapshot_id=f"{date}:abc123", target_positions=TARGET,
                     decision_source="risk_adjusted_yield", action="rebalance", ts=ts,
                     publish=publish or _Capture(), **kw)


def _rows(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_rows(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(bc.canonical_json(r) + "\n" for r in rows), encoding="utf-8")


def _load_verifier():
    """scripts/verify_spa.py by FILE PATH with a private module name — exactly how a stranger runs it."""
    spec = importlib.util.spec_from_file_location("_verify_spa_book_under_test",
                                                  _PROJECT_ROOT / "scripts" / "verify_spa.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── the commitment itself ─────────────────────────────────────────────────────────────────────────
class TestCommitHidesAndRevealShows:
    def test_commit_publishes_only_the_hash(self, tmp_path):
        pub = _Capture()
        entry = _commit(tmp_path, publish=pub)
        assert entry["event_type"] == bc.EVENT_COMMIT and entry["seq"] == 0
        payload = entry["payload"]
        h = payload["commitment_hash"]
        assert len(h) == 64 and set(payload) == {"cycle_date", "commitment_hash", "risk_policy_version",
                                                  "reveal_delay_days", "published"}
        public_text = bc.public_path(tmp_path).read_text(encoding="utf-8")
        for secret in ("aave_v3", "40000", "salt", "snapshot_id", "abc123", "risk_adjusted_yield"):
            assert secret not in public_text, f"public trail leaks {secret!r}"
        # the package IS on disk — privately — and hashes to the published digest
        pkg_rows = bc.read_packages(tmp_path)
        assert len(pkg_rows) == 1 and bc.verify_package(pkg_rows[0]["package"], h)
        assert pkg_rows[0]["package"]["target_positions"] == {"aave_v3": 40000.0, "compound_v3": 35000.0,
                                                              "sky_susds": 20000.5}
        # the publisher saw the hash and nothing from the package
        kind, key, title, body = pub.calls[0]
        assert kind == "commit" and h in key and h in body
        assert "aave_v3" not in body and "salt" not in body

    def test_reveal_verifies_against_the_commit(self, tmp_path):
        pub = _Capture()
        entry = _commit(tmp_path, publish=pub)
        h = entry["payload"]["commitment_hash"]
        out = bc.reveal_due(tmp_path, today=D2, ts=TS_D2, publish=pub)
        assert len(out) == 1 and out[0]["event_type"] == bc.EVENT_REVEAL and out[0]["seq"] == 1
        pkg = out[0]["payload"]["package"]
        assert out[0]["payload"]["commitment_hash"] == h and out[0]["payload"]["commit_seq"] == 0
        assert bc.verify_package(pkg, h) and pkg["cycle_date"] == D1 and pkg["action"] == "rebalance"
        assert pkg["risk_policy_version"] == "v1.0" and len(pkg["salt"]) == 64
        # the reveal publication carries the package (it fits the digest body)
        kind, key, title, body = pub.calls[1]
        assert kind == "reveal" and h in key and '"aave_v3":40000.0' in body
        v = bc.verify_trail(tmp_path)
        assert v["ok"] and v["commits"] == 1 and v["reveals"] == 1 and v["verified_reveals"] == 1

    def test_tampered_package_fails_verification(self, tmp_path):
        h = _commit(tmp_path)["payload"]["commitment_hash"]
        pkg = bc.reveal_due(tmp_path, today=D2, ts=TS_D2, publish=_Capture())[0]["payload"]["package"]
        assert bc.verify_package(pkg, h)
        bad = dict(pkg, target_positions=dict(pkg["target_positions"], aave_v3=90000.0))
        assert not bc.verify_package(bad, h)
        bad = dict(pkg, salt="00" * 32)
        assert not bc.verify_package(bad, h)
        bad = dict(pkg, action="hold")
        assert not bc.verify_package(bad, h)
        # and the same forgery inside the public file is named by the in-process verifier
        p = bc.public_path(tmp_path)
        rows = _rows(p)
        rows[1]["payload"]["package"]["target_positions"]["aave_v3"] = 90000.0
        rows[1]["entry_hash"] = bc.compute_entry_hash(rows[1]["seq"], rows[1]["ts"], rows[1]["event_type"],
                                                      rows[1]["payload"], rows[1]["prev_hash"])
        _write_rows(p, rows)
        v = bc.verify_trail(tmp_path)
        assert not v["ok"] and v["broken_at"] == 1 and "does not hash" in v["reason"]

    def test_salt_makes_identical_decisions_hash_differently(self):
        kw = dict(cycle_date=D1, snapshot_id="s", target_positions=TARGET,
                  decision_source="x", action="hold")
        a = bc.commitment_hash(bc.build_package(**kw))
        b = bc.commitment_hash(bc.build_package(**kw))
        assert a != b
        fixed = "ab" * 32
        assert bc.commitment_hash(bc.build_package(salt=fixed, **kw)) == bc.commitment_hash(bc.build_package(salt=fixed, **kw))

    def test_chain_tamper_is_detected_at_the_row(self, tmp_path):
        _commit(tmp_path)
        _commit(tmp_path, date=D2, ts=TS_D2)
        p = bc.public_path(tmp_path)
        rows = _rows(p)
        rows[0]["payload"]["commitment_hash"] = "f" * 64  # rewrite history: a different commitment
        _write_rows(p, rows)
        v = bc.verify_trail(tmp_path)
        assert not v["ok"] and v["broken_at"] == 0 and "entry_hash mismatch" in v["reason"]

    def test_reveal_not_before_the_delay(self, tmp_path):
        _commit(tmp_path)
        assert bc.reveal_due(tmp_path, today=D1, ts=TS_D1, publish=_Capture()) == []  # same cycle day: too early
        assert bc.REVEAL_DELAY_DAYS == 1
        assert len(bc.reveal_due(tmp_path, today=D2, ts=TS_D2, publish=_Capture())) == 1
        assert bc.reveal_due(tmp_path, today=D3, ts=TS_D3, publish=_Capture()) == []  # already revealed

    def test_commit_is_idempotent_per_date_and_never_resalts(self, tmp_path):
        first = _commit(tmp_path)
        assert _commit(tmp_path, ts=TS_D1.replace("06:00", "07:00")) is None  # re-run of the same day
        rows = bc.read_trail(tmp_path)
        assert [r["event_type"] for r in rows] == [bc.EVENT_COMMIT]
        assert len(bc.read_packages(tmp_path)) == 1
        # a crash between the private write and the public append is finished with the STORED salt
        bc.public_path(tmp_path).unlink()
        again = _commit(tmp_path)
        assert again is not None and again["payload"]["commitment_hash"] == first["payload"]["commitment_hash"]

    def test_reveal_without_a_commit_entry_is_not_performed(self, tmp_path):
        _commit(tmp_path)
        bc.public_path(tmp_path).unlink()  # package on disk, nothing committed publicly
        assert bc.reveal_due(tmp_path, today=D3, ts=TS_D3, publish=_Capture()) == []
        st = bc.status(tmp_path, today=D3)
        assert st["uncommitted_packages"] == [D1]

    def test_default_publisher_lands_in_the_digest_queue_file(self, tmp_path):
        """No live Telegram: the sanctioned path is push_policy.enqueue_digest → digest_queue.json,
        folded into the morning report. The hash is in the event_key AND the body (both renderers)."""
        entry = bc.commit(tmp_path, cycle_date=D1, snapshot_id=None, target_positions=TARGET,
                          decision_source="x", action="hold", ts=TS_D1)
        h = entry["payload"]["commitment_hash"]
        assert entry["payload"]["published"] == {"channel": "telegram-digest", "public": False, "queued": True}
        q = json.loads((tmp_path / "telegram" / "digest_queue.json").read_text(encoding="utf-8"))
        item = q["items"][-1]
        assert h in item["event_key"] and h in item["body"] and item["reason"] == "book_commit_reveal"
        assert "aave_v3" not in item["body"]


# ── the cycle_runner hooks: form of a CALL, placed where the design says, wrapped ────────────────
class TestCycleRunnerHooks:
    SRC = (_PROJECT_ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")

    @classmethod
    def _calls(cls) -> list[tuple[int, str]]:
        """(lineno, marker) for the calls that order the decision path inside run_cycle."""
        tree = ast.parse(cls.SRC)
        out: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == "run_cycle"):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                f = sub.func
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                if name == "commit" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "_bc":
                    out.append((sub.lineno, "book_commit"))
                elif name == "reveal_due":
                    out.append((sub.lineno, "book_reveal"))
                elif name == "_audit_record":
                    tag = next((a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str)), None)
                    if tag in ("risk_verdict", "trade_executed", "allocation_proposal"):
                        out.append((sub.lineno, tag))
                elif name == "append" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "trades":
                    out.append((sub.lineno, "trades.append"))
        return sorted(out)

    def test_commit_is_a_call_after_the_risk_verdict_and_before_the_trade(self):
        seq = self._calls()
        marks = [m for _, m in seq]
        assert "book_commit" in marks, "commit hook missing"
        assert marks.index("book_commit") > marks.index("risk_verdict")
        assert marks.index("book_commit") > marks.index("allocation_proposal")
        assert marks.index("book_commit") < marks.index("trades.append")
        assert marks.index("book_commit") < marks.index("trade_executed")

    def test_reveal_is_a_call_at_cycle_start(self):
        seq = self._calls()
        marks = [m for _, m in seq]
        assert "book_reveal" in marks, "reveal hook missing"
        assert marks.index("book_reveal") < marks.index("allocation_proposal")

    def test_hooks_are_wrapped_so_they_cannot_crash_the_cycle(self):
        i = self.SRC.index("_bc.commit(")
        block = self.SRC[self.SRC.rfind("try:", 0, i):i + 1200]
        assert "except Exception as _bc_exc2" in block and "cycle continues" in block
        j = self.SRC.index("_bc.reveal_due(")
        block = self.SRC[self.SRC.rfind("try:", 0, j):j + 900]
        assert "except Exception as _bc_exc" in block and "cycle continues" in block

    def test_hooks_are_gated_on_write_so_a_dry_run_leaves_no_public_trace(self):
        for marker in ("_bc.commit(", "_bc.reveal_due("):
            i = self.SRC.index(marker)
            head = self.SRC[self.SRC.rfind("\n    if write:", 0, i):i]
            assert "\n    if write:" in head and "def " not in head

    def test_artifacts_are_declared(self):
        from spa_core.paper_trading import cycle_runner
        assert "data/book_commitments.jsonl" in cycle_runner.PRODUCES
        assert "data/book_commit_packages.jsonl" in cycle_runner.INTERNAL_WRITES
        assert "data/book_commit_packages.jsonl" not in cycle_runner.PRODUCES  # private state, not a product

    def test_cycle_runner_commit_survives_a_broken_attestation_layer(self, monkeypatch):
        """Mutation of the wiring: a commit() that raises must become a NOTE, not a crashed cycle.
        Exercised through the exact hook text by executing it with the cycle's locals stubbed."""
        i = self.SRC.index("    # ── Commit-reveal of the book decision, part 2")
        j = self.SRC.index("    if _safety_failed:", i)
        hook = "\n".join(ln[4:] for ln in self.SRC[i:j].splitlines())
        monkeypatch.setattr(bc, "commit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
        notes: list[str] = []
        env = {"write": True, "ddir": Path("."), "today": D1, "run_ts": TS_D1, "target_usd": TARGET,
               "model_used": "x", "traded": True, "notes": notes, "log": chm.__dict__.get("log") or _NullLog()}
        exec(compile(hook, "cycle_runner_hook", "exec"), env)
        assert notes == ["book_commit_error: RuntimeError"]


class _NullLog:
    def warning(self, *a, **k):
        pass


# ── the standalone verifier (surface J) ─────────────────────────────────────────────────────────
class TestStandaloneVerifier:
    def _trail(self, tmp_path: Path) -> Path:
        _commit(tmp_path)
        _commit(tmp_path, date=D2, ts=TS_D2)
        bc.reveal_due(tmp_path, today=D2, ts=TS_D2, publish=_Capture())  # reveals D1 only
        return bc.public_path(tmp_path)

    def test_verifier_reproduces_a_synthetic_trail_from_a_directory(self, tmp_path):
        p = self._trail(tmp_path)
        V = _load_verifier()
        rep = V.run([str(tmp_path)])
        assert rep["ok"], rep["errors"]
        j = rep["book_commitments"]
        assert j["valid"] and j["length"] == 3 and j["n_commits"] == 2 and j["n_verified_reveals"] == 1
        assert j["n_pending"] == 1 and j["first_date"] == D1 and j["last_date"] == D1
        assert rep["files"]["book_commitments"] == str(p)
        # the in-process verifier and the public one agree on the head
        assert bc.verify_trail(tmp_path)["ok"] and j["head_hash"] == _rows(p)[-1]["entry_hash"]
        assert V.main([str(p), "--expect-surfaces", "J"]) == 0

    def test_verifier_reports_broken_at_on_a_forged_package(self, tmp_path):
        p = self._trail(tmp_path)
        rows = _rows(p)
        rows[2]["payload"]["package"]["target_positions"]["aave_v3"] = 90000.0
        # re-seal the row so ONLY the commitment check can catch it (an edited row alone would fail the chain)
        rows[2]["entry_hash"] = bc.compute_entry_hash(rows[2]["seq"], rows[2]["ts"], rows[2]["event_type"],
                                                      rows[2]["payload"], rows[2]["prev_hash"])
        _write_rows(p, rows)
        V = _load_verifier()
        rep = V.run([str(p)])
        assert not rep["ok"]
        assert rep["book_commitments"]["broken_at"] == 2 and "does not hash" in rep["book_commitments"]["reason"]
        assert any("book_commitments: chain broken at row 2" in e for e in rep["errors"])
        assert V.main([str(p)]) == 1

    def test_verifier_rejects_a_reveal_without_an_earlier_commit_and_a_hash_mismatch(self, tmp_path):
        p = self._trail(tmp_path)
        V = _load_verifier()
        # (a) drop the commit the reveal points at: the reveal has no EARLIER commit
        rows = _rows(p)
        without = [rows[1], rows[2]]
        chained = []
        prev = "0" * 64
        for k, r in enumerate(without):
            r = dict(r, seq=k, prev_hash=prev)
            r["entry_hash"] = bc.compute_entry_hash(k, r["ts"], r["event_type"], r["payload"], prev)
            prev = r["entry_hash"]
            chained.append(r)
        _write_rows(p, chained)
        rep = V.run([str(p)])
        assert rep["book_commitments"]["broken_at"] == 1 and "no EARLIER commit" in rep["book_commitments"]["reason"]
        # (b) a reveal that names a different hash than its commit
        rows = _rows(self._trail(tmp_path / "b"))
        rows[2]["payload"]["commitment_hash"] = "0" * 64
        rows[2]["entry_hash"] = bc.compute_entry_hash(2, rows[2]["ts"], rows[2]["event_type"], rows[2]["payload"], rows[2]["prev_hash"])
        _write_rows(p, rows)
        rep = V.run([str(p)])
        assert rep["book_commitments"]["broken_at"] == 2 and "different commitment_hash" in rep["book_commitments"]["reason"]

    def test_verifier_classifies_by_content_and_rejects_a_second_commit_for_one_date(self, tmp_path):
        p = self._trail(tmp_path)
        V = _load_verifier()
        renamed = tmp_path / "whatever.jsonl"
        renamed.write_bytes(p.read_bytes())
        p.unlink()
        assert V._sniff_jsonl_kind(renamed) == "book_commitments"
        rep = V.run([str(renamed)])
        assert rep["ok"] and rep["book_commitments"]["valid"]
        # a second commit for D1 appended honestly to the chain is still a broken invariant
        rows = _rows(renamed)
        dup = {"seq": 3, "ts": TS_D3, "event_type": "book_commit", "prev_hash": rows[-1]["entry_hash"],
               "payload": {"cycle_date": D1, "commitment_hash": "e" * 64, "risk_policy_version": "v1.0",
                           "reveal_delay_days": 1, "published": {}}}
        dup["entry_hash"] = bc.compute_entry_hash(3, TS_D3, "book_commit", dup["payload"], dup["prev_hash"])
        _write_rows(renamed, rows + [dup])
        rep = V.run([str(renamed)])
        assert rep["book_commitments"]["broken_at"] == 3 and "second commit" in rep["book_commitments"]["reason"]

    def test_verifier_has_no_spa_core_import(self):
        src = (_PROJECT_ROOT / "scripts" / "verify_spa.py").read_text(encoding="utf-8")
        assert "import spa_core" not in src and "from spa_core" not in src
        assert '"J": "book_commitments"' in src


# ── the monitor line: third outcome, advisory ───────────────────────────────────────────────────
def _curve(tmp: Path, dates: list[str]) -> None:
    bars = [{"date": d, "open_equity": 100000.0, "close_equity": 100010.0} for d in dates]
    (tmp / "equity_curve_daily.json").write_text(json.dumps({"daily": bars}), encoding="utf-8")


class TestMonitorAndBriefing:
    def test_no_trail_is_unchecked_never_healthy(self, tmp_path):
        m = chm.CycleHealthMonitor()
        _curve(tmp_path, [D1])
        chk = m.check_book_commitments(str(tmp_path), now=NOW_D2)
        assert chk["status"] == chm.UNCHECKED and chk["advisory"] is True and "не начат" in chk["detail"]

    def test_commit_on_the_last_decision_is_healthy(self, tmp_path):
        m = chm.CycleHealthMonitor()
        _curve(tmp_path, [D1, D2])
        _commit(tmp_path)
        _commit(tmp_path, date=D2, ts=TS_D2)
        bc.reveal_due(tmp_path, today=D2, ts=TS_D2, publish=_Capture())
        chk = m.check_book_commitments(str(tmp_path), now=NOW_D2)
        assert chk["status"] == "HEALTHY", chk
        assert chk["commits"] == 2 and chk["verified_reveals"] == 1 and chk["pending"] == 1 and chk["chain_ok"]
        assert chk["last_commit_date"] == D2 and chk["last_decision_date"] == D2

    def test_missed_cycle_overdue_reveal_and_broken_chain_are_warnings(self, tmp_path):
        m = chm.CycleHealthMonitor()
        _curve(tmp_path, [D1, D2])
        _commit(tmp_path)  # D2 decided (bar exists) but never committed
        chk = m.check_book_commitments(str(tmp_path), now=NOW_D2)
        assert chk["status"] == "WARNING" and "без коммита" in chk["detail"]
        _commit(tmp_path, date=D2, ts=TS_D2)
        chk = m.check_book_commitments(str(tmp_path), now=NOW_LATE)  # nobody revealed for days
        assert chk["status"] == "WARNING" and "просрочено" in chk["detail"] and chk["overdue"] == [D1, D2]
        bc.reveal_due(tmp_path, today=NOW_LATE.strftime("%Y-%m-%d"), ts=NOW_LATE.isoformat(), publish=_Capture())
        assert m.check_book_commitments(str(tmp_path), now=NOW_LATE)["status"] == "HEALTHY"
        p = bc.public_path(tmp_path)
        rows = _rows(p)
        rows[0]["ts"] = TS_D3  # back-date/forward-date a commit
        _write_rows(p, rows)
        chk = m.check_book_commitments(str(tmp_path), now=NOW_LATE)
        assert chk["status"] == "WARNING" and "порвана" in chk["detail"] and chk["chain_ok"] is False

    def test_no_curve_is_unchecked_with_the_reason_named(self, tmp_path):
        m = chm.CycleHealthMonitor()
        _commit(tmp_path)
        chk = m.check_book_commitments(str(tmp_path), now=NOW_D2)
        assert chk["status"] == chm.UNCHECKED and "не измерена" in chk["detail"] and chk["chain_ok"]

    def test_signal_is_advisory_in_run_all_checks(self, tmp_path):
        m = chm.CycleHealthMonitor()
        rep = m.run_all_checks(data_dir=str(tmp_path))
        assert "book_commitments" in rep["checks"]
        assert rep["checks"]["book_commitments"]["status"] == chm.UNCHECKED
        assert not any(u["check"] == "book_commitments" for u in rep["unchecked"])

    def test_briefing_line(self):
        spec = importlib.util.spec_from_file_location("usb_book", _PROJECT_ROOT / "scripts" / "update_system_briefing.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert "нет в снимке" in mod.book_commitments_line({"checks": {}})
        line = mod.book_commitments_line({"checks": {"book_commitments": {"status": "HEALTHY", "detail": "коммит на 2026-09-08"}}})
        assert "**HEALTHY**" in line and "коммит на" in line
        src = (_PROJECT_ROOT / "scripts" / "update_system_briefing.py").read_text(encoding="utf-8")
        assert src.count("lines.append(book_commitments_line(snap))") == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
