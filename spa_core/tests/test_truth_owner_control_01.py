"""STUDIO-TRUTH-AND-OWNER-CONTROL-01 — правда о состоянии на поверхностях владельца.

Каждый тест — находка из QA_FINDINGS_MATRIX (F*/T*). Только одноразовые каталоги, сетевых вызовов
нет, живой трекер и живой ``data/`` не читаются и не пишутся.
"""
# FROZEN-DATE-OK: injected-clock — every judged moment is passed as `now=`; fixtures are relative to it
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import owner_view as ov
from spa_core.studio_os import trading_engines as te
from spa_core.trading_research import read_model as rm

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


def _earn_db(root: Path, mode: str, with_incident: bool):
    (root / "data").mkdir(parents=True)
    con = sqlite3.connect(root / "data" / "earn_defi.db")
    con.execute("CREATE TABLE system_state(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at_utc TEXT NOT NULL)")
    con.execute("CREATE TABLE incidents(id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, prev_hash TEXT NOT NULL, "
                "record_hash TEXT NOT NULL, payload TEXT NOT NULL, date TEXT, kc TEXT, state TEXT)")
    con.execute("INSERT INTO system_state VALUES ('system_mode', ?, ?)", (mode, (NOW - timedelta(days=46)).isoformat()))
    if with_incident:
        con.execute("INSERT INTO incidents(ts_utc, prev_hash, record_hash, payload, date, kc, state) VALUES (?,?,?,?,?,?,?)",
                    ((NOW - timedelta(days=46)).isoformat(), "", "h",
                     json.dumps({"kc": "KC-1", "date": "2026-09-18", "detail": "price source: 2.424% > 2.0%"}),
                     "2026-09-18", "KC-1", "OPEN"))
    con.commit()
    con.close()


class InvestmentAxis(unittest.TestCase):
    """F2/T01/T02: блокировка движка видна наверху, даже когда все службы здоровы."""

    def _section(self, mode, incident=True, present=True):
        with tempfile.TemporaryDirectory() as d:
            if present:
                _earn_db(Path(d), mode, incident)
            import os
            old = os.environ.get("EARN_DEFI_DIR")
            os.environ["EARN_DEFI_DIR"] = d
            try:
                return mc._investment_section(NOW)
            finally:
                if old is None:
                    os.environ.pop("EARN_DEFI_DIR", None)
                else:
                    os.environ["EARN_DEFI_DIR"] = old

    def test_incident_is_critical_with_reason_and_owner(self):
        sec = self._section("INCIDENT")
        self.assertEqual(sec["_meta"]["state"], "CRITICAL")
        eng = sec["engines"][0]
        self.assertTrue(eng["blocked"])
        self.assertEqual(eng["incident"]["kc"], "KC-1")
        self.assertTrue(eng["incident"]["latched"])
        self.assertIsNone(eng["incident"]["last_condition_check"])     # в фикстуре nav_daily нет ⇒ не измерено
        self.assertIn("владелец", eng["incident"]["clear_by"])

    def test_normal_mode_is_healthy(self):
        self.assertEqual(self._section("NORMAL", incident=False)["_meta"]["state"], "HEALTHY")

    def test_missing_ledger_is_not_measured_never_ok(self):
        sec = self._section("NORMAL", present=False)
        self.assertEqual(sec["_meta"]["state"], "NOT_MEASURED")

    def test_latch_text_names_the_daily_recheck(self):
        t = ov._latch_text({"latched": True, "last_condition_check": "2026-11-02", "later_triggers": 0})
        self.assertIn("02.11.2026", t)
        self.assertIn("новых срабатываний не дала", t)
        self.assertIn("ещё 2 раз", ov._latch_text({"latched": True, "last_condition_check": "2026-11-02", "later_triggers": 2}))
        self.assertIn("не измерена", ov._latch_text({"latched": True}))

    def test_overview_headline_cannot_say_all_is_well_under_incident(self):
        sec = self._section("INCIDENT")
        model = {"overview": {"system": {"state": "HEALTHY", "kill_switch": False},
                              "investment": {"state": sec["_meta"]["state"], "reason": sec["_meta"]["reason"],
                                             "blocked": [e for e in sec["engines"] if e["blocked"]]}}}
        h = ov.headline(model, {}, {"count": 2, "items": [{"title": "q", "subject": "X", "age_days": 1}]}, [], None)
        self.assertIn("заблокирован", h["main"])
        self.assertIn("ждут вашего решения: 2", h["next"])
        probs = ov._system_problems(model, {}, None)
        self.assertEqual(probs[0]["label"], "Инвестиционный движок заблокирован")
        self.assertIn("до ручного снятия", probs[0]["text"])     # актуальность не измерена — сказано словами


class RecordOutcomeIsNotSelfContradictory(unittest.TestCase):
    """F8: сделано · итог записан · проверка пройдена — разные факты."""

    BASE = {"status": "done", "verified_by_probe": "p", "acceptance_verdict": "satisfied"}

    def test_probe_with_bound_execution_is_verified(self):
        o = ov._record_outcome({**self.BASE, "preparation": {"execution": {"verified": True}}})
        self.assertEqual(o["kind"], "done_verified")

    def test_probe_recorded_but_execution_not_bound_is_not_verified(self):
        o = ov._record_outcome({**self.BASE, "preparation": {"execution": {"verified": False, "reason": "вручную"}}})
        self.assertEqual(o["kind"], "done_recorded_unverified")
        self.assertFalse(o["verified"])
        self.assertNotIn("проверено автоматической проверкой", o["text"])

    def test_done_without_probe(self):
        self.assertEqual(ov._record_outcome({"status": "done"})["kind"], "done_unverified")


class SignalEvents(unittest.TestCase):
    """F12/T06: сигнал ≠ виртуальное исполнение; ничего не выводится задним числом."""

    def _db(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE observations(seq INTEGER, candidate_id TEXT, asset TEXT, timeframe TEXT, "
                    "bar_open_time INT, bar_close_time INT, signal_ts_ms INT, position_before INT, target INT, "
                    "action TEXT, bar_close REAL, fill_price REAL, fill_cost REAL, equity REAL, position_held INT)")
        c = "s@v1:BTC:1D:spot_long:x"
        rows = [(1, c, "BTC", "1D", 0, 10, 10, 0, 1, "BUY", 100.0, None, 0, 1.0, 0),
                (2, c, "BTC", "1D", 10, 20, 20, 1, 1, "HOLD", 101.0, 100.0, 0.0015, 0.9985, 1),
                (3, c, "BTC", "1D", 20, 30, 30, 1, 0, "SELL", 99.0, None, 0, 0.98, 1)]
        con.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return con, c

    def test_buy_paired_with_its_fill_and_sell_pending(self):
        con, c = self._db()
        ev = rm.signal_events(con, [c], now_ms=40)
        self.assertEqual([e["signal"] for e in ev], ["SELL", "BUY"])
        sell, buy = ev
        self.assertEqual(sell["virtual_execution"], "PENDING")
        self.assertIsNone(sell["fill_price"])
        self.assertEqual(buy["virtual_execution"], "EXECUTED")
        self.assertEqual(buy["fill_price"], 100.0)
        self.assertFalse(buy["real_trade"])

    def test_hold_rows_are_not_events_and_unknown_candidates_empty(self):
        con, c = self._db()
        self.assertEqual(rm.signal_events(con, ["other"]), [])
        self.assertEqual(rm.signal_events(con, []), [])


class FreshnessAndTime(unittest.TestCase):
    """D1–D3/F3/F14/T08."""

    def test_short_ts_shows_the_date_when_not_today_and_flags_future(self):
        from spa_core.telegram.views._base import short_ts
        self.assertEqual(short_ts("2026-07-01T09:11:41Z", NOW), "01.07 11:11 Мадрид")      # CEST, другой день
        self.assertEqual(short_ts("2026-11-04T09:11:00Z", NOW), "10:11 Мадрид")            # CET, сегодня
        self.assertIn("позже текущего", short_ts("2026-11-04T11:00:00Z", NOW))

    def test_short_ts_dst_boundaries(self):
        from spa_core.telegram.views._base import short_ts
        spring = datetime(2026, 3, 29, 3, tzinfo=timezone.utc)
        self.assertEqual(short_ts("2026-03-29T00:30:00Z", spring), "01:30 Мадрид")
        self.assertEqual(short_ts("2026-03-29T01:30:00Z", spring), "03:30 Мадрид")
        autumn = datetime(2026, 10, 25, 3, tzinfo=timezone.utc)
        self.assertEqual(short_ts("2026-10-25T00:30:00Z", autumn), "02:30 Мадрид")
        self.assertEqual(short_ts("2026-10-25T01:30:00Z", autumn), "02:30 Мадрид")

    def test_fresh_snapshot_does_not_hide_a_stale_section(self):
        model = {"system": {"agents": {"_meta": mc._meta("HEALTHY", ["a"], NOW - timedelta(hours=5), NOW, 90)},
                            "services": {"_meta": mc._meta("HEALTHY", ["b"], NOW, NOW)}}}
        fr = mc.source_freshness(model, NOW)
        paths = {r["path"]: r for r in fr["stale_or_unmeasured"]}
        self.assertIn("system.agents", paths)
        self.assertEqual(paths["system.agents"]["state"], "STALE")
        allrows = {r["path"]: r for r in [*fr["stale_or_unmeasured"]]}
        self.assertNotIn("system.services", allrows)

    def test_incident_actuality_against_last_cycle(self):
        rec = {"state": "bad", "last_ts": "2026-10-19T06:29:44+00:00"}
        ok = mc.incident_row("cycle_failed", rec, {"last_cycle_ts": "2026-11-04T07:00:00+00:00", "last_cycle_status": "ok"})
        self.assertEqual(ok["actuality"], "NOT_CONFIRMED")
        bad = mc.incident_row("cycle_failed", rec, {"last_cycle_ts": "2026-11-04T07:00:00+00:00", "last_cycle_status": "error"})
        self.assertEqual(bad["actuality"], "ACTIVE")
        self.assertEqual(mc.incident_row("cycle_failed", rec, None)["actuality"], "UNKNOWN")
        self.assertEqual(mc.incident_row("peg_break", rec, {"last_cycle_status": "ok"})["actuality"], "UNKNOWN")


class StatusWords(unittest.TestCase):
    """E1/E3/F5/F11/T02/T12."""

    def test_golive_criteria_pass_is_not_live_permission(self):
        from spa_core.telegram.views.golive import golive_verdict
        v = golive_verdict({"ready": True, "go_live_state": "gate_passed_owner_decision_pending"}, "ru")
        self.assertIn("НЕ разрешён", v)
        self.assertIn("не распознано", golive_verdict({"ready": True, "go_live_state": "weird"}, "ru"))

    def test_fleet_warning_is_not_ok(self):
        from spa_core.telegram.views.home import fleet_line
        self.assertTrue(fleet_line({"overall_status": "WARNING", "warning_count": 1}, "ru").startswith("🟠"))
        self.assertTrue(fleet_line({"overall_status": "OK"}, "ru").startswith("✅"))
        self.assertTrue(fleet_line({}, "ru").startswith("❔"))
        self.assertTrue(fleet_line({"overall_status": "CRITICAL", "critical_count": 2}, "ru").startswith("⛔"))

    def test_known_codes_are_recognised(self):
        self.assertIn("HOLD", ov.ORACLE_STANCE_RU)
        self.assertIn("SHELF_NOT_DELIVERED", ov.PROBLEM_RU)
        self.assertIn("владельца", ov.PROBLEM_RU["SHELF_NOT_DELIVERED"][1])

    def test_ru_plural(self):
        from spa_core.utils.presentation import ru_plural
        f = lambda n: ru_plural(n, "бар", "бара", "баров")  # noqa: E731
        self.assertEqual([f(1), f(3), f(11), f(21), f(34), f(206), f(112)],
                         ["бар", "бара", "баров", "бар", "бара", "баров", "баров"])

    def test_annualised_rate_names_its_window(self):
        from spa_core.investment_cio.sources_summary import _ann_text, _window_days
        self.assertEqual(_window_days({"evidence_start": "2026-09-30", "as_of": "2026-11-04"}), 35)
        t = _ann_text(-0.4051, "ru", 35)
        self.assertIn("35 дн.", t)
        self.assertIn("не прогноз", t)
        self.assertIn("окно не записано", _ann_text(0.1, "ru", None))


class SiteWatchdogRepeats(unittest.TestCase):
    """T14: тот же набор FAIL-кодов не повторяется каждые 6 ч."""

    def setUp(self):
        import importlib.util
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("sfm_truth01", root / "scripts" / "site_freshness_monitor.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_unchanged_set_is_reminded_changed_set_goes_at_once(self):
        rep = {"fails": [{"code": "SHELF_NOT_DELIVERED", "severity": "FAIL", "detail": "at 05:03"}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "st.json"
            g = self.m._unchanged_gate(rep, frozenset(), now=NOW, path=p)
            self.assertFalse(g["skip"])
            self.m._unchanged_gate_commit(g)
            rep2 = {"fails": [{"code": "SHELF_NOT_DELIVERED", "severity": "FAIL", "detail": "at 11:03"}]}
            self.assertTrue(self.m._unchanged_gate(rep2, frozenset(), now=NOW + timedelta(hours=6), path=p)["skip"])
            later = self.m._unchanged_gate(rep2, frozenset(), now=NOW + timedelta(hours=25), path=p)
            self.assertFalse(later["skip"])
            self.assertIn("напоминание", later["prefix"])
            new = {"fails": rep2["fails"] + [{"code": "MISSING_ASOF", "severity": "FAIL"}]}
            self.assertFalse(self.m._unchanged_gate(new, frozenset(), now=NOW + timedelta(hours=6), path=p)["skip"])

    def test_no_state_path_means_no_dedup(self):
        g = self.m._unchanged_gate({"fails": []}, frozenset(), now=NOW, path=None)
        self.assertFalse(g["skip"])


class HealEditsTheOriginal(unittest.TestCase):
    """C4: кнопки прикрепляются к исходному сообщению; новое — только если правка не удалась."""

    def _run(self, edit_result):
        from spa_core.telegram import owner_decisions as od
        heal = od.Heal(pid="p1", card="c", text="t", keyboard={"inline_keyboard": []}, original_message_id=42)
        sent, edited, marked = [], [], []
        orig_bp, orig_mark = od.buttonless_pushes, od.mark_buttons_delivered
        od.buttonless_pushes = lambda **k: [heal]
        od.mark_buttons_delivered = lambda pid, **k: marked.append((pid, k.get("message_id"))) or True
        try:
            od.heal_buttonless(lambda t, k: sent.append(t) or {"message_id": 99},
                               edit=lambda mid, t, k: edited.append(mid) or edit_result)
        finally:
            od.buttonless_pushes, od.mark_buttons_delivered = orig_bp, orig_mark
        return sent, edited, marked

    def test_successful_edit_sends_nothing_new(self):
        sent, edited, marked = self._run({"message_id": 42})
        self.assertEqual((sent, edited), ([], [42]))
        self.assertEqual(marked, [("p1", 42)])

    def test_failed_edit_falls_back_to_a_new_message(self):
        sent, edited, marked = self._run(None)
        self.assertEqual(len(sent), 1)
        self.assertEqual(marked, [("p1", 99)])


class TradingCandidatesShownInFull(unittest.TestCase):
    """T07: Bridge /product (через director_report) показывает весь forward-набор."""

    def test_five_of_five(self):
        from spa_core.studio_os import director_report as dr
        fwd = [{"id": f"s{i}@v1:BTC:1D:spot_long:x", "oos_sharpe": 1.0, "forward_observations": 34,
                "forward_net": -0.04} for i in range(5)]
        out = dr.render_trading({"trading": {"candidates": 138, "backtest_qualified": 5, "forward_paper": 5,
                                             "robust": 0, "champions": 0, "live_capital_usd": 0, "observations": 1,
                                             "evidence_verified": True, "age_h": 0.1, "forward_candidates": fwd}})
        self.assertIn("(5 из 5;", "\n".join(out))
        self.assertEqual(sum(1 for line in out if line.startswith("• ")), 5)
        self.assertIn("за 34 бара", "\n".join(out))


if __name__ == "__main__":
    unittest.main()
