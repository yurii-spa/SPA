"""test_cycle_inputs_archive_replay.py — task 3 of inbox «Целостность трека SPA»: the daily cycle
archives the accrual INPUTS (hash-chained, append-only) and the equity bars re-derive from them with
the cycle's own accrual function. Positive controls: a tampered archive breaks the chain; a tampered
curve makes the replay FAIL; an empty archive is UNCHECKED, never PASS; the archive hook in
cycle_runner has the form of a call and sits AFTER the bar upsert; the replay imports the cycle's
``_accrue_daily_yield`` (no fork).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.audit import cycle_inputs_archive as arc  # noqa: E402
from spa_core.audit import replay_equity  # noqa: E402
from spa_core.monitoring import cycle_health_monitor as chm  # noqa: E402
from spa_core.paper_trading.equity import _accrue_daily_yield  # noqa: E402

POS = {"aave_v3": 40000.0, "compound_v3": 40000.0}
APY = {"aave_v3": 3.65, "compound_v3": 7.30}  # 40000*3.65/100/365 = 4.0 ; 40000*7.30/100/365 = 8.0


def _write_day(tmp: Path, date: str, open_eq: float, curve: list) -> float:
    y = _accrue_daily_yield(POS, APY)
    close = open_eq + y
    arc.append_record(tmp, arc.build_record(cycle_date=date, run_ts=f"{date}T06:00:00+00:00", open_equity=open_eq, close_equity=close,
                                            daily_yield_usd=y, apy_today_pct=5.0, positions=POS, apy_map=APY, fallback_pools=[], accrual_source="live"),
                      ts=f"{date}T06:00:00+00:00")
    curve.append({"date": date, "open_equity": open_eq, "close_equity": round(close, 2), "positions": POS})
    return close


def _seed(tmp: Path, days: int = 3) -> None:
    curve: list = []
    eq = 100000.0
    for i in range(days):
        eq = _write_day(tmp, f"2026-09-1{i}", eq, curve)
    (tmp / "equity_curve_daily.json").write_text(json.dumps({"daily": curve}), encoding="utf-8")


class TestArchiveChain:
    def test_append_verify_and_tamper(self, tmp_path):
        _seed(tmp_path, 3)
        v = arc.verify(tmp_path)
        assert v["ok"] and v["entries"] == 3
        rows = arc.read_all(tmp_path)
        assert rows[1]["prev_hash"] == rows[0]["entry_hash"] and rows[0]["prev_hash"] == arc.GENESIS
        rows[1]["payload"]["close_equity"] += 1.0
        (tmp_path / arc.FILENAME).write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n")
        v = arc.verify(tmp_path)
        assert not v["ok"] and v["broken_at"] == 1 and "altered" in v["reason"]

    def test_record_keeps_apy_map_verbatim_including_junk(self, tmp_path):
        rec = arc.build_record(cycle_date="2026-09-10", run_ts="t", open_equity=1.0, close_equity=1.0, daily_yield_usd=0.0, apy_today_pct=0.0,
                               positions={"a": 1.0, "b": 2.0}, apy_map={"a": None, "b": 520.0, "c": 1.0}, fallback_pools=["b"], accrual_source="fallback")
        assert rec["apy_map"] == {"a": None, "b": 520.0} and rec["fallback_pools"] == ["b"]


class TestReplay:
    def test_pass_on_consistent_archive(self, tmp_path):
        _seed(tmp_path, 3)
        rep = replay_equity.replay(tmp_path)
        assert rep["status"] == "PASS" and rep["days"] == 3 and rep["max_abs_diff_usd"] == 0.0 and rep["chain"]["ok"]

    def test_tampered_curve_fails_and_names_the_day(self, tmp_path):
        _seed(tmp_path, 3)
        doc = json.loads((tmp_path / "equity_curve_daily.json").read_text())
        doc["daily"][2]["close_equity"] += 0.5
        (tmp_path / "equity_curve_daily.json").write_text(json.dumps(doc))
        rep = replay_equity.replay(tmp_path)
        assert rep["status"] == "FAIL" and [d["date"] for d in rep["diffs"]] == ["2026-09-12"]
        assert rep["diffs"][0]["problems"] == ["curve differs"] and abs(rep["max_abs_diff_usd"] - 0.5) < 0.01

    def test_empty_archive_is_unchecked_not_pass(self, tmp_path):
        rep = replay_equity.replay(tmp_path)
        assert rep["status"] == "UNCHECKED" and "no cycle_inputs.jsonl" in rep["reason"]

    def test_broken_chain_is_unchecked(self, tmp_path):
        _seed(tmp_path, 2)
        (tmp_path / arc.FILENAME).write_text("{not json\n")
        assert replay_equity.replay(tmp_path)["status"] == "UNCHECKED"

    def test_rerun_of_a_date_uses_the_last_record_and_is_reported(self, tmp_path):
        _seed(tmp_path, 1)
        doc = json.loads((tmp_path / "equity_curve_daily.json").read_text())
        curve: list = []
        close = _write_day(tmp_path, "2026-09-10", 100000.0, curve)  # second run of the same date
        doc["daily"][0]["close_equity"] = round(close, 2)
        (tmp_path / "equity_curve_daily.json").write_text(json.dumps(doc))
        rep = replay_equity.replay(tmp_path)
        assert rep["status"] == "PASS" and rep["reruns"] == {"2026-09-10": 2}

    def test_replay_uses_the_cycles_accrual_function_no_fork(self):
        src = Path(replay_equity.__file__).read_text(encoding="utf-8")
        assert "from spa_core.paper_trading.equity import _accrue_daily_yield" in src
        assert "/ 365" not in src.replace("/ 365.0", "")  # no second formula


class TestCycleRunnerHook:
    SRC = Path(_PROJECT_ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")

    def test_hook_is_a_call_after_the_bar_upsert(self):
        tree = ast.parse(self.SRC)
        names_in_order = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        f = sub.func
                        n = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                        if n in ("_upsert_equity_point", "append_record"):
                            names_in_order.append((sub.lineno, n))
        names_in_order.sort()
        seq = [n for _, n in names_in_order]
        assert "append_record" in seq, "archive hook missing"
        assert seq.index("append_record") > seq.index("_upsert_equity_point")

    def test_hook_is_wrapped_so_it_cannot_crash_the_cycle(self):
        i = self.SRC.index("_cia.append_record(")
        block = self.SRC[self.SRC.rfind("try:", 0, i):i + 900]
        assert "except Exception as _cia_exc" in block and "cycle continues" in block

    def test_artifact_is_declared_in_produces(self):
        from spa_core.paper_trading import cycle_runner
        assert "data/cycle_inputs.jsonl" in cycle_runner.PRODUCES


class TestMonitorAndBriefing:
    def test_monitor_third_outcome_and_advisory(self, tmp_path, monkeypatch):
        m = chm.CycleHealthMonitor()
        assert m.check_replay_from_inputs(str(tmp_path))["status"] == chm.UNCHECKED
        _seed(tmp_path, 2)
        assert m.check_replay_from_inputs(str(tmp_path))["status"] == "HEALTHY"
        doc = json.loads((tmp_path / "equity_curve_daily.json").read_text()); doc["daily"][0]["close_equity"] += 1.0
        (tmp_path / "equity_curve_daily.json").write_text(json.dumps(doc))
        chk = m.check_replay_from_inputs(str(tmp_path))
        assert chk["status"] == "WARNING" and chk["divergent_days"] == 1
        rep = m.run_all_checks(data_dir=str(tmp_path))
        assert "replay_from_inputs" in rep["checks"] and not any(u["check"] == "replay_from_inputs" for u in rep["unchecked"])

    def test_briefing_line(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("usb2", _PROJECT_ROOT / "scripts" / "update_system_briefing.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert "нет в снимке" in mod.replay_line({"checks": {}})
        assert "**HEALTHY**" in mod.replay_line({"checks": {"replay_from_inputs": {"status": "HEALTHY", "detail": "3 дн."}}})
