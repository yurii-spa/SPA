"""Honesty regression tests for spa_core/monitoring/rules_watchdog.py.

The watchdog is a live agent (`com.spa.rules_watchdog`, every 300s) that tells the owner
whether SPA's policy rules hold. On origin it had **no dedicated tests** and it reported
"OK" about rules it had never evaluated:

  * `check_circuit_breaker` answered "No kill switch active, drawdown within limits" while
    reading a kill-switch file nobody writes and a `max_drawdown_pct` key nobody writes —
    on live data its OK verdict was 100% fabricated;
  * `check_adapter_status` swallowed a missing/unparseable `generated_at` and fell through
    to OK, publishing a freshness verdict it had not computed;
  * `check_position_limits` / `check_t1_concentration` invented a $100k denominator when
    `capital_usd` was absent, so percentages were measured against a number nobody wrote;
  * `check_llm_forbidden_violations` scanned `glob("*.py")` — top level only — and still
    claimed "No LLM usage in risk/execution/monitoring domains" although every subpackage
    of those three domains went unread;
  * `run_watchdog` folded SKIPPED ("not measured") into `overall: "OK"`.

Same fail-OPEN class as RISKWIRE (#29), `d2_connectivity` (#31) and the Tier-1 status
summary (#35). Every test here is hermetic: all module paths are redirected to `tmp_path`,
no live `data/` file is read or written, and no network/Telegram call is made.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import rules_watchdog as w


# ── fixtures ───────────────────────────────────────────────────────────────

def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _now_iso(hours_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect every state path the watchdog touches into tmp_path."""
    data = tmp_path / "data"
    data.mkdir()
    paths = {
        "_DATA_DIR": data,
        "_POSITIONS_PATH": data / "current_positions.json",
        "_ADAPTER_PATH": data / "adapter_status.json",
        "_GOLIVE_PATH": data / "golive_status.json",
        "_PAPER_PATH": data / "paper_trading_status.json",
        "_WATCHDOG_PATH": data / "watchdog_report.json",
        "_KILL_SWITCH_PATH": data / "kill_switch.json",
        # OWNER Variant A 2026-07-23 (ADR-056): the real cycle-written kill-switch state files.
        "_KILL_SWITCH_STATUS_PATH": data / "kill_switch_status.json",
        "_DERISK_STATUS_PATH": data / "derisk_status.json",
    }
    for name, value in paths.items():
        monkeypatch.setattr(w, name, value)
    return type("Sandbox", (), {**{k.lstrip("_").lower(): v for k, v in paths.items()},
                                "root": tmp_path})


def _t1_names(n: int = 4):
    from spa_core.risk.policy_enforcer import T1_ADAPTERS
    return list(T1_ADAPTERS)[:n]


def _healthy_adapters(hours_ago: float = 1.0):
    return {
        "generated_at": _now_iso(hours_ago),
        "adapters": {name: {"active": True, "apy": 4.0} for name in _t1_names(4)},
    }


# ── _read_doc: the primitive that tells "empty" from "unreadable" ───────────

class TestReadDoc:

    def test_missing_file_reports_missing(self, tmp_path):
        state, payload = w._read_doc(tmp_path / "nope.json")
        assert state == "missing"
        assert payload is None

    def test_unreadable_file_is_not_missing(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not json", encoding="utf-8")
        state, payload = w._read_doc(p)
        assert state == "unreadable", "corrupt JSON must not be indistinguishable from absent"
        assert isinstance(payload, str) and payload

    def test_empty_object_is_ok_not_missing(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("{}", encoding="utf-8")
        assert w._read_doc(p) == ("ok", {})

    def test_valid_document_round_trips(self, tmp_path):
        p = tmp_path / "d.json"
        _write(p, {"a": 1})
        assert w._read_doc(p) == ("ok", {"a": 1})

    def test_non_object_json_is_ok_with_payload(self, tmp_path):
        p = tmp_path / "list.json"
        _write(p, [1, 2])
        state, payload = w._read_doc(p)
        assert state == "ok" and payload == [1, 2]


class TestFiniteFloat:

    @pytest.mark.parametrize("raw", [None, "abc", {}, [], float("nan"), float("inf"),
                                     float("-inf"), True, False])
    def test_unusable_inputs_return_none(self, raw):
        assert w._finite_float(raw) is None, "{!r} must not become a measurement".format(raw)

    @pytest.mark.parametrize("raw,expected", [(0, 0.0), (0.0, 0.0), (-3.5, -3.5),
                                              ("2.5", 2.5), (7, 7.0)])
    def test_usable_inputs_convert(self, raw, expected):
        assert w._finite_float(raw) == expected

    def test_bool_is_rejected_not_coerced(self):
        # float(True) == 1.0 would silently turn a flag into a drawdown reading.
        assert w._finite_float(True) is None


# ── circuit breaker: the check whose live OK verdict was fabricated ─────────

class TestCircuitBreakerHonesty:
    """OWNER Variant A 2026-07-23 (ADR-056): rewritten from the old (dead) kill_switch.json +
    max_drawdown_pct model to the REAL cycle-written files kill_switch_status.json (`triggered`)
    and derisk_status.json (`active`/`tier`/`reason`) + a 26h freshness → missed-cycle rule.
    The fail-CLOSED honesty intent is preserved: unreadable/missing/stamp-less → NOT CHECKED,
    never 'off'; an active posture or a stale (blind) file → CRITICAL."""

    def _fresh(self, sandbox, ks=None, ds=None, hours_ago=1.0):
        _write(sandbox.kill_switch_status_path,
               {"generated_at": _now_iso(hours_ago), "triggered": False, **(ks or {})})
        _write(sandbox.derisk_status_path,
               {"generated_at": _now_iso(hours_ago), "active": False, **(ds or {})})

    def test_triggered_kill_switch_is_critical(self, sandbox):
        self._fresh(sandbox, ks={"triggered": True, "reason": "HARD_KILL drawdown 11%"})
        res = w.check_circuit_breaker()
        assert res.status == "CRITICAL" and res.is_critical
        assert "HARD_KILL" in res.message

    def test_active_derisk_is_critical_with_tier(self, sandbox):
        self._fresh(sandbox, ds={"active": True, "tier": "SOFT_DERISK", "reason": "drawdown 6%"})
        res = w.check_circuit_breaker()
        assert res.status == "CRITICAL"
        assert "SOFT_DERISK" in res.message

    def test_fresh_inactive_posture_is_ok(self, sandbox):
        self._fresh(sandbox)
        res = w.check_circuit_breaker()
        assert res.status == "OK"
        assert res.detail["kill_switch"] is False and res.detail["derisk_active"] is False

    def test_unreadable_kill_switch_status_never_reads_as_off(self, sandbox):
        self._fresh(sandbox)
        sandbox.kill_switch_status_path.write_text("{corrupt", encoding="utf-8")
        res = w.check_circuit_breaker()
        assert res.status == "SKIPPED", "a corrupt kill-switch file is not proof the switch is off"
        assert "kill_switch_status.json unreadable" in res.message

    def test_unreadable_derisk_status_never_reads_as_off(self, sandbox):
        self._fresh(sandbox)
        sandbox.derisk_status_path.write_text("{corrupt", encoding="utf-8")
        res = w.check_circuit_breaker()
        assert res.status == "SKIPPED"
        assert "derisk_status.json unreadable" in res.message

    def test_missing_status_files_are_not_within_limits(self, sandbox):
        res = w.check_circuit_breaker()
        assert res.status == "SKIPPED"
        assert res.is_unchecked

    def test_stale_status_file_is_missed_cycle_critical(self, sandbox):
        # 27h old → daily cycle likely did not run → posture BLIND → CRITICAL, NOT a silent skip.
        self._fresh(sandbox, hours_ago=27.0)
        res = w.check_circuit_breaker()
        assert res.status == "CRITICAL"
        assert "Missed cycle" in res.message
        assert res.detail["missed_cycle"] is True

    def test_fresh_boundary_just_under_26h_is_ok(self, sandbox):
        self._fresh(sandbox, hours_ago=25.5)
        assert w.check_circuit_breaker().status == "OK"

    def test_triggered_wins_over_unreadable_derisk(self, sandbox):
        _write(sandbox.kill_switch_status_path,
               {"generated_at": _now_iso(1.0), "triggered": True, "reason": "HARD_KILL"})
        sandbox.derisk_status_path.write_text("nope", encoding="utf-8")
        res = w.check_circuit_breaker()
        assert res.status == "CRITICAL", "a real trigger must not be downgraded to 'not measured'"

    def test_active_wins_over_staleness(self, sandbox):
        # an ACTIVE de-risk that is also stale must still page as CRITICAL-active, not be missed.
        _write(sandbox.kill_switch_status_path, {"generated_at": _now_iso(30.0), "triggered": False})
        _write(sandbox.derisk_status_path,
               {"generated_at": _now_iso(30.0), "active": True, "tier": "HARD_KILL", "reason": "x"})
        res = w.check_circuit_breaker()
        assert res.status == "CRITICAL"

    def test_stampless_status_file_is_unchecked_not_fresh(self, sandbox):
        # a status doc with no usable generated_at cannot be declared fresh.
        _write(sandbox.kill_switch_status_path, {"triggered": False})
        _write(sandbox.derisk_status_path, {"generated_at": _now_iso(1.0), "active": False})
        res = w.check_circuit_breaker()
        assert res.status == "SKIPPED"
        assert "generated_at" in res.message

    def test_non_object_status_file_is_unchecked(self, sandbox):
        _write(sandbox.kill_switch_status_path, [1, 2, 3])
        _write(sandbox.derisk_status_path, {"generated_at": _now_iso(1.0), "active": False})
        res = w.check_circuit_breaker()
        # a JSON list is state "ok" but not a dict → not triggered, and _doc_age_hours flags it.
        assert res.status == "SKIPPED"


# ── adapter status: freshness must not be claimed when not computed ─────────

class TestAdapterStatusHonesty:

    def test_missing_generated_at_does_not_pass_as_fresh(self, sandbox):
        doc = _healthy_adapters()
        doc.pop("generated_at")
        _write(sandbox.adapter_path, doc)
        res = w.check_adapter_status()
        assert res.status == "SKIPPED"
        assert "freshness NOT CHECKED" in res.message

    def test_unparseable_generated_at_does_not_pass_as_fresh(self, sandbox):
        doc = _healthy_adapters()
        doc["generated_at"] = "yesterday-ish"
        _write(sandbox.adapter_path, doc)
        res = w.check_adapter_status()
        assert res.status == "SKIPPED"
        assert "unparseable" in res.message

    def test_fresh_file_is_ok_and_publishes_age(self, sandbox):
        _write(sandbox.adapter_path, _healthy_adapters(hours_ago=2.0))
        res = w.check_adapter_status()
        assert res.status == "OK"
        assert 1.5 < res.detail["age_hours"] < 2.5

    def test_stale_file_still_warns(self, sandbox):
        _write(sandbox.adapter_path, _healthy_adapters(hours_ago=72.0))
        res = w.check_adapter_status()
        assert res.status == "WARNING"
        assert res.detail["age_hours"] > 48

    def test_unreadable_file_says_unreadable_not_missing(self, sandbox):
        sandbox.adapter_path.write_text("{", encoding="utf-8")
        res = w.check_adapter_status()
        assert res.status == "CRITICAL"
        assert "unreadable" in res.message

    def test_missing_file_is_critical(self, sandbox):
        res = w.check_adapter_status()
        assert res.status == "CRITICAL"
        assert "missing" in res.message

    def test_too_few_active_t1_is_critical(self, sandbox):
        names = _t1_names(4)
        doc = {"generated_at": _now_iso(), "adapters": {
            names[0]: {"active": True}, names[1]: {"active": False},
            names[2]: {"active": False}, names[3]: {"active": False}}}
        _write(sandbox.adapter_path, doc)
        res = w.check_adapter_status()
        assert res.status == "CRITICAL"

    def test_malformed_t1_entry_is_unchecked_not_silently_inactive(self, sandbox):
        doc = _healthy_adapters()
        doc["adapters"][_t1_names(1)[0]] = "active"  # a string, not an entry
        _write(sandbox.adapter_path, doc)
        res = w.check_adapter_status()
        assert res.status == "SKIPPED"
        assert "malformed" in res.message

    def test_non_object_adapters_is_critical(self, sandbox):
        _write(sandbox.adapter_path, {"generated_at": _now_iso(), "adapters": ["a", "b"]})
        res = w.check_adapter_status()
        assert res.status == "CRITICAL"

    def test_naive_timestamp_is_treated_as_utc_not_unparseable(self, sandbox):
        doc = _healthy_adapters()
        doc["generated_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        _write(sandbox.adapter_path, doc)
        res = w.check_adapter_status()
        assert res.status == "OK"


# ── position limits / T1: no invented denominator ───────────────────────────

class TestPositionLimitsHonesty:

    def test_missing_capital_does_not_pass_as_compliant(self, sandbox):
        _write(sandbox.positions_path, {"positions": {"aave": 50000.0, "morpho": 50000.0}})
        res = w.check_position_limits()
        assert res.status == "SKIPPED", (
            "with no capital_usd the per-protocol share is unknowable, not compliant")
        assert "capital_usd" in res.message

    def test_zero_capital_does_not_pass_as_compliant(self, sandbox):
        _write(sandbox.positions_path, {"capital_usd": 0, "positions": {"aave": 1.0}})
        assert w.check_position_limits().status == "SKIPPED"

    def test_protocol_count_breach_survives_missing_capital(self, sandbox):
        _write(sandbox.positions_path,
               {"positions": {"p{}".format(i): 1000.0 for i in range(9)}})
        res = w.check_position_limits()
        assert res.status == "CRITICAL", "a count breach needs no denominator"
        assert "too_many_protocols" in res.message

    def test_real_cap_breach_is_critical(self, sandbox):
        _write(sandbox.positions_path,
               {"capital_usd": 100000.0, "positions": {"aave": 90000.0, "morpho": 10000.0}})
        res = w.check_position_limits()
        assert res.status == "CRITICAL"
        assert "aave" in res.message

    def test_compliant_book_is_ok(self, sandbox):
        _write(sandbox.positions_path,
               {"capital_usd": 100000.0, "positions": {"aave": 30000.0, "morpho": 30000.0}})
        res = w.check_position_limits()
        assert res.status == "OK"
        assert res.detail["num_protocols"] == 2

    def test_unusable_position_size_is_not_counted_as_zero(self, sandbox):
        _write(sandbox.positions_path,
               {"capital_usd": 100000.0, "positions": {"aave": 30000.0, "morpho": "n/a"}})
        res = w.check_position_limits()
        assert res.status == "SKIPPED"
        assert "morpho" in res.message

    def test_unreadable_positions_file_says_so(self, sandbox):
        sandbox.positions_path.write_text("{", encoding="utf-8")
        res = w.check_position_limits()
        assert res.status == "CRITICAL"
        assert "unreadable" in res.message

    def test_missing_positions_file_is_critical(self, sandbox):
        res = w.check_position_limits()
        assert res.status == "CRITICAL"


class TestT1ConcentrationHonesty:

    def test_missing_capital_does_not_publish_a_percentage(self, sandbox):
        _write(sandbox.positions_path, {"positions": {_t1_names(1)[0]: 40000.0}})
        res = w.check_t1_concentration()
        assert res.status == "SKIPPED"
        assert "t1_pct" not in res.detail, "a share computed against an assumed $100k is invented"

    def test_valid_book_reports_a_real_share(self, sandbox):
        name = _t1_names(1)[0]
        _write(sandbox.positions_path,
               {"capital_usd": 100000.0, "positions": {name: 40000.0}})
        res = w.check_t1_concentration()
        assert res.status == "OK"
        assert res.detail["t1_pct"] == 40.0

    def test_unreadable_file_says_unreadable(self, sandbox):
        sandbox.positions_path.write_text("]", encoding="utf-8")
        res = w.check_t1_concentration()
        assert res.status == "CRITICAL"
        assert "unreadable" in res.message


# ── LLM-forbidden scan: coverage must match the claim ───────────────────────

class TestLlmForbiddenScan:

    @pytest.fixture
    def fake_repo(self, tmp_path, monkeypatch):
        for d in ("spa_core/risk", "spa_core/execution", "spa_core/monitoring"):
            (tmp_path / d).mkdir(parents=True)
        monkeypatch.setattr(w, "_REPO", tmp_path)
        return tmp_path

    def test_subpackages_are_scanned(self, fake_repo):
        """The origin scan was glob('*.py') — top level only — while claiming domain coverage."""
        nested = fake_repo / "spa_core" / "monitoring" / "sensors"
        nested.mkdir()
        (nested / "peg.py").write_text("import anthropic\n", encoding="utf-8")
        res = w.check_llm_forbidden_violations()
        assert res.status == "CRITICAL", "a violation one directory deep must be seen"
        assert any("peg.py" in v for v in res.detail["violations"])

    def test_top_level_violation_still_detected(self, fake_repo):
        (fake_repo / "spa_core" / "risk" / "policy.py").write_text(
            "from openai import OpenAI\n", encoding="utf-8")
        res = w.check_llm_forbidden_violations()
        assert res.status == "CRITICAL"

    def test_clean_tree_is_ok_and_reports_coverage(self, fake_repo):
        (fake_repo / "spa_core" / "risk" / "policy.py").write_text(
            "VALUE = 1\n", encoding="utf-8")
        (fake_repo / "spa_core" / "execution" / "sub").mkdir()
        (fake_repo / "spa_core" / "execution" / "sub" / "x.py").write_text(
            "VALUE = 2\n", encoding="utf-8")
        res = w.check_llm_forbidden_violations()
        assert res.status == "OK"
        assert res.detail["files_scanned"] == 2, "the OK claim must name what it covered"

    def test_missing_domain_directory_is_not_a_clean_bill(self, fake_repo):
        import shutil
        shutil.rmtree(fake_repo / "spa_core" / "execution")
        res = w.check_llm_forbidden_violations()
        assert res.status == "SKIPPED", "a domain that was never opened cannot be declared clean"
        assert "spa_core/execution" in res.message

    def test_pycache_is_not_counted(self, fake_repo):
        cache = fake_repo / "spa_core" / "risk" / "__pycache__"
        cache.mkdir()
        (cache / "stale.py").write_text("import anthropic\n", encoding="utf-8")
        res = w.check_llm_forbidden_violations()
        assert res.status == "OK"
        assert res.detail["files_scanned"] == 0

    def test_comment_mentions_do_not_trigger(self, fake_repo):
        (fake_repo / "spa_core" / "risk" / "notes.py").write_text(
            "# import anthropic is forbidden here\n", encoding="utf-8")
        assert w.check_llm_forbidden_violations().status == "OK"

    def test_real_repo_scan_covers_every_file_in_the_forbidden_domains(self):
        """Against the real tree: coverage must equal the domains, not just their top level."""
        repo = Path(w.__file__).resolve().parents[2]
        domains = ("spa_core/risk", "spa_core/execution", "spa_core/monitoring")
        expected, nested = set(), 0
        for d in domains:
            base = repo / d
            if not base.exists():
                pytest.skip("{} absent in this checkout".format(d))
            for p in base.rglob("*.py"):
                if "__pycache__" in p.parts or p.name == Path(w.__file__).name:
                    continue
                if p.name == "auto_fixer.py":  # documented exception in the module
                    continue
                expected.add(p)
                if p.parent != base:
                    nested += 1
        if nested == 0:
            pytest.skip("no subpackages in the forbidden domains — nothing to under-scan")
        res = w.check_llm_forbidden_violations()
        assert res.detail["files_scanned"] == len(expected), (
            "the top-level-only scan missed {} nested file(s); scanned={} expected={}".format(
                nested, res.detail["files_scanned"], len(expected)))


# ── aggregation: overall OK means every rule actually ran ───────────────────

class TestRunWatchdogAggregation:

    def _patch_checks(self, monkeypatch, results):
        monkeypatch.setattr(w, "RULES_TO_CHECK", [lambda r=r: r for r in results])

    def test_unchecked_rule_blocks_overall_ok(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [
            w.CheckResult("a", "OK", "fine"),
            w.CheckResult("b", "SKIPPED", "no input", {"unchecked_reason": "no input"}),
        ])
        w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert report["overall"] == "UNCHECKED", (
            "a rule that could not run must not be published as a clean bill of health")
        assert report["unchecked_count"] == 1
        assert report["unchecked"][0] == {"check": "b", "reason": "no input"}

    def test_all_checks_pass_gives_ok(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("a", "OK", "fine"),
                                         w.CheckResult("b", "OK", "fine")])
        rc = w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert report["overall"] == "OK"
        assert report["unchecked_count"] == 0 and report["unchecked"] == []
        assert rc == 0

    def test_warning_outranks_unchecked(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("a", "WARNING", "stale"),
                                         w.CheckResult("b", "SKIPPED", "no input")])
        w.run_watchdog(write=True, send_alert=False)
        assert json.loads(sandbox.watchdog_path.read_text())[-1]["overall"] == "WARNING"

    def test_critical_outranks_everything(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("a", "CRITICAL", "breach"),
                                         w.CheckResult("b", "SKIPPED", "no input"),
                                         w.CheckResult("c", "WARNING", "stale")])
        rc = w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert report["overall"] == "CRITICAL"
        assert report["critical_count"] == 1
        assert rc == 1, "exit code still means BREACH, not 'not measured'"

    def test_unchecked_alone_does_not_change_exit_code(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("b", "SKIPPED", "no input")])
        assert w.run_watchdog(write=True, send_alert=False) == 0, (
            "an unmeasured rule must not make launchd report a failed run")

    def test_unchecked_alone_sends_no_telegram(self, sandbox, monkeypatch):
        # NOTE 2026-08-05 (own-28 bonus): production _send_telegram grew an optional
        # dedup_key (per-incident rules_critical fingerprint); the stubs here and
        # below mirror the new signature. Assertions unchanged — not a weakening.
        sent = []
        monkeypatch.setattr(w, "_send_telegram", lambda msg, dedup_key=None: sent.append(msg) or True)
        self._patch_checks(monkeypatch, [w.CheckResult("b", "SKIPPED", "no input")])
        w.run_watchdog(write=True, send_alert=True)
        assert sent == [], "a 5-minute agent must not page the owner about an unmeasured rule"

    def test_critical_alert_also_lists_unchecked_rules(self, sandbox, monkeypatch):
        sent = []
        monkeypatch.setattr(w, "_send_telegram", lambda msg, dedup_key=None: sent.append(msg) or True)
        self._patch_checks(monkeypatch, [
            w.CheckResult("a", "CRITICAL", "breach"),
            w.CheckResult("b", "SKIPPED", "no drawdown", {"unchecked_reason": "no drawdown"}),
        ])
        w.run_watchdog(write=True, send_alert=True)
        assert len(sent) == 1
        assert "breach" in sent[0] and "no drawdown" in sent[0]

    def test_raising_check_becomes_critical_not_silence(self, sandbox, monkeypatch):
        def boom():
            raise RuntimeError("sensor exploded")
        monkeypatch.setattr(w, "RULES_TO_CHECK", [boom])
        rc = w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert report["overall"] == "CRITICAL"
        assert "sensor exploded" in report["checks"][0]["message"]
        assert rc == 1

    def test_history_is_a_capped_ring_and_appends(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("a", "OK", "fine")])
        monkeypatch.setattr(w, "_WATCHDOG_HISTORY_CAP", 3)
        for _ in range(5):
            w.run_watchdog(write=True, send_alert=False)
        history = json.loads(sandbox.watchdog_path.read_text())
        assert len(history) == 3

    def test_no_write_leaves_no_file(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("a", "OK", "fine")])
        w.run_watchdog(write=False, send_alert=False)
        assert not sandbox.watchdog_path.exists()

    def test_report_carries_every_check_verbatim(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("a", "OK", "fine", {"n": 1}),
                                         w.CheckResult("b", "SKIPPED", "why not")])
        w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert [c["check"] for c in report["checks"]] == ["a", "b"]
        assert report["checks"][0]["detail"] == {"n": 1}
        assert report["checks"][1]["message"] == "why not"

    def test_unchecked_reason_falls_back_to_message(self, sandbox, monkeypatch):
        self._patch_checks(monkeypatch, [w.CheckResult("b", "SKIPPED", "plain message")])
        w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert report["unchecked"][0]["reason"] == "plain message"


# ── end-to-end over the real check list, still hermetic ────────────────────

class TestEndToEndOnSandboxState:

    def test_empty_data_dir_never_reports_ok(self, sandbox, monkeypatch):
        monkeypatch.setattr(w, "_send_telegram", lambda msg, dedup_key=None: True)
        w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        assert report["overall"] != "OK", "an empty data dir is not a healthy system"

    def test_healthy_state_reports_ok(self, sandbox, monkeypatch):
        names = _t1_names(4)
        _write(sandbox.adapter_path, _healthy_adapters())
        _write(sandbox.positions_path, {
            "capital_usd": 100000.0,
            "positions": {names[0]: 30000.0, names[1]: 30000.0, names[2]: 20000.0},
        })
        _write(sandbox.paper_path, {"max_drawdown_pct": 0.4})
        # Variant A: circuit_breaker now reads the cycle-written kill/de-risk status files.
        _write(sandbox.kill_switch_status_path, {"generated_at": _now_iso(1.0), "triggered": False})
        _write(sandbox.derisk_status_path, {"generated_at": _now_iso(1.0), "active": False})
        w.run_watchdog(write=True, send_alert=False)
        report = json.loads(sandbox.watchdog_path.read_text())[-1]
        by_name = {c["check"]: c for c in report["checks"]}
        assert by_name["circuit_breaker"]["status"] == "OK"
        assert by_name["position_limits"]["status"] == "OK"
        assert by_name["adapter_status"]["status"] == "OK"
        # apy_coherence needs >= 3 priced positions in the adapter doc; llm scan runs on the
        # real tree. Both are covered by their own tests above.
        assert report["overall"] in ("OK", "UNCHECKED")

    def test_live_shaped_status_files_report_ok(self, sandbox):
        """Variant A: the real live-shaped kill/de-risk status files (fresh, inactive) → OK."""
        _write(sandbox.kill_switch_status_path, {
            "generated_at": _now_iso(2.0), "triggered": False,
            "reason": "", "allocation": {},
        })
        _write(sandbox.derisk_status_path, {
            "generated_at": _now_iso(2.0), "active": False, "tier": None,
            "reason": "", "policy": {},
        })
        res = w.check_circuit_breaker()
        assert res.status == "OK"
        assert res.detail["kill_switch"] is False


# ── S2 follow-up (own-28 bonus, 2026-08-05): rules_critical per-incident fingerprint ──
# Без dedup_key нарушение A оставляло класс rules_critical в 'bad' навсегда, и
# ПОЗЖЕ возникшее ДРУГОЕ нарушение B молча глоталось как «всё ещё bad» — тот же
# дефект, что и у core_agent_down (self_heal/watchdog/uptime уже несут отпечаток).
# Отпечаток = отсортированный набор имён нарушенных правил.

def test_send_telegram_forwards_dedup_key(monkeypatch):
    from spa_core.telegram import push_policy
    seen: dict = {}

    def _capture(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return True

    monkeypatch.setattr(push_policy, "push_critical", _capture)
    assert w._send_telegram("breach text", dedup_key="rule_a|rule_b") is True
    assert seen["kwargs"].get("dedup_key") == "rule_a|rule_b"
    # и это по-прежнему entry-путь, не resolve
    assert not seen["kwargs"].get("resolved")


def test_run_watchdog_fingerprints_alert_by_breach_set(monkeypatch):
    # Два CRITICAL-правила → dedup_key = их имена, отсортированные, через '|'.
    sent: dict = {}
    monkeypatch.setattr(
        w, "_send_telegram",
        lambda msg, dedup_key=None: sent.update(msg=msg, dedup_key=dedup_key) or True,
    )
    monkeypatch.setattr(w, "RULES_TO_CHECK", [
        lambda: w.CheckResult("zzz_rule", "CRITICAL", "breach z"),
        lambda: w.CheckResult("aaa_rule", "CRITICAL", "breach a"),
    ])
    exit_code = w.run_watchdog(write=False, send_alert=True)
    assert exit_code == 1
    assert sent["dedup_key"] == "aaa_rule|zzz_rule"   # сортировка = стабильность
    assert "zzz_rule" in sent["msg"] and "aaa_rule" in sent["msg"]
