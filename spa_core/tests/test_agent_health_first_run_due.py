"""«Ждёт первого запуска» обязан иметь СРОК из расписания (ARB 16.10, п. 1).

Карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`. После перезагрузки 15.10
пульс честно назвал 15 агентов «ждут первого планового запуска» — но без даты, к
которой ожидание становится пропуском. Календарный агент к тому же получал БЮДЖЕТ
категории (26 ч у ежедневного), а не ближайшее плановое срабатывание: утренний
агент, загрузившийся в 21:17Z, мог молчать до 23:17Z следующего дня, не будучи
пропуском. Теперь у строки есть `due_by` (UTC ISO): StartInterval — загрузка + окно
интервала, StartCalendarInterval — ближайшее срабатывание после загрузки + запас.
До срока — OK/awaiting со сроком; после — WARNING с названным сроком; вдвое дальше
от загрузки — CRITICAL.

Положительные контроли (красные на origin 8f913113): `due_by` в строке и в отчёте;
календарный агент через минуту после срока (до 26-часового бюджета) — WARNING, а не
OK; CRITICAL на 2× от СРОКА календаря, а не от бюджета; экран /agents называет срок.

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW и BOOT передаются в check_agent(now=, boot_time=,
# calendar_tz=) и next_calendar_run(after=, tz=); сроки выводятся из них же.
"""
from __future__ import annotations

import os
import plistlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from spa_core.monitoring import agent_health_monitor as ahm

BOOT = datetime(2026, 10, 15, 21, 17, 57, tzinfo=timezone.utc)   # четверг
NOW = BOOT + timedelta(minutes=3, seconds=23)
UTC = timezone.utc

CAL = "com.spa.zz_due_test_calendar"
RES = "com.spa.zz_due_test_hourly"
HY = "com.spa.zz_due_test_receipt"


class _Scene(unittest.TestCase):
    def setUp(self):
        for lbl in (CAL, RES, HY):
            p = f"/tmp/spa_{lbl[len('com.spa.'):]}.log"
            if os.path.exists(p):  # громкий отказ: предпосылка не обеспечена
                self.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: на хосте существует {p}")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.root / "logs").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def plist(self, label, **sched):
        short = label[len("com.spa."):]
        return dict(sched, RunAtLoad=False,
                    StandardOutPath=str(self.root / f"{short}.launchd.out"),
                    StandardErrorPath=str(self.root / f"{short}.launchd.err"))

    def judge(self, label, plist, now, boot=BOOT, receipts=None):
        return ahm.check_agent(label, plist, True, {label: {"pid": 0, "exit": 0}}, now,
                               project_root=self.root, data_dir=self.data,
                               boot_time=boot, receipts=receipts or {},
                               calendar_tz=UTC)

    @property
    def p_cal(self):
        return self.plist(CAL, StartCalendarInterval={"Hour": 9, "Minute": 0})

    @property
    def p_res(self):
        return self.plist(RES, StartInterval=3600)


class CalendarDeadlineFromSchedule(_Scene):
    DUE = datetime(2026, 10, 16, 9, 15, tzinfo=UTC)   # 09:00 следующего утра + 15 мин

    def test_before_due_is_ok_awaiting_with_due_by(self):
        h = self.judge(CAL, self.p_cal, NOW)
        self.assertEqual(h.status, ahm.OK, h.issue)
        self.assertEqual(h.evidence, ahm.EVIDENCE_AWAITING_FIRST_RUN)
        self.assertEqual(h.due_by, "2026-10-16T09:15:00Z")
        self.assertEqual(h.to_dict()["due_by"], "2026-10-16T09:15:00Z")
        self.assertIn("срок 2026-10-16T09:15:00Z", h.note)

    def test_one_minute_before_due_still_waits(self):
        h = self.judge(CAL, self.p_cal, self.DUE - timedelta(minutes=1))
        self.assertEqual(h.status, ahm.OK, h.issue)

    def test_after_due_is_warning_naming_the_missed_time(self):
        """На origin: 09:16Z — ещё OK (бюджет 26 ч), пропуск утреннего запуска молчит."""
        h = self.judge(CAL, self.p_cal, self.DUE + timedelta(minutes=1))
        self.assertEqual(h.status, ahm.WARNING, h.issue)
        self.assertTrue(h.issue.startswith("no run since reboot"), h.issue)
        self.assertIn("missed first scheduled run due by 2026-10-16T09:15:00Z", h.issue)
        self.assertEqual(h.evidence, "")

    def test_past_twice_the_window_is_critical(self):
        window = self.DUE - BOOT
        self.assertEqual(self.judge(CAL, self.p_cal,
                                    BOOT + 2 * window - timedelta(minutes=1)).status,
                         ahm.WARNING)
        h = self.judge(CAL, self.p_cal, BOOT + 2 * window + timedelta(minutes=1))
        self.assertEqual(h.status, ahm.CRITICAL, h.issue)
        # критично РАНЬШЕ, чем 2× бюджета категории (52 ч) — срок из календаря
        self.assertLess(2 * window, timedelta(hours=52))

    def test_cause_code_is_stable_across_due_times(self):
        """Дата срока не дробит Problem: код причины строится из начала строки."""
        from spa_core.monitoring import problem_store as ps
        a = self.judge(CAL, self.p_cal, self.DUE + timedelta(minutes=1)).issue
        b = a.replace("2026-10-16T09:15:00Z", "2026-10-17T09:15:00Z")
        self.assertEqual(ps.cause_from_agent_issue(a), ps.cause_from_agent_issue(b))


class IntervalDeadline(_Scene):
    def test_interval_due_is_boot_plus_window(self):
        h = self.judge(RES, self.p_res, NOW)
        self.assertEqual(h.status, ahm.OK, h.issue)
        self.assertEqual(h.due_by, "2026-10-16T00:17:57Z")   # окно часового — 3 ч
        late = self.judge(RES, self.p_res, BOOT + timedelta(hours=3, minutes=1))
        self.assertEqual(late.status, ahm.WARNING)
        self.assertIn("due by 2026-10-16T00:17:57Z", late.issue)
        self.assertEqual(self.judge(RES, self.p_res,
                                    BOOT + timedelta(hours=6, minutes=1)).status,
                         ahm.CRITICAL)

    def test_boot_unmeasured_has_no_deadline(self):
        h = self.judge(RES, self.p_res, NOW, boot=None)
        self.assertEqual(h.due_by, "")
        self.assertIsNone(h.to_dict()["due_by"])
        self.assertEqual(h.status, ahm.CRITICAL)   # прежний fail-CLOSED путь

    def test_receipt_awaiting_carries_due_by(self):
        import json
        (self.data / "book.json").write_text(
            json.dumps({"last_cycle_at": (BOOT - timedelta(minutes=50)).isoformat()}),
            encoding="utf-8")
        p = self.plist(HY, StartInterval=3600)
        h = self.judge(HY, p, BOOT + timedelta(hours=2, minutes=30),
                       receipts={HY: ("book.json", "last_cycle_at")})
        self.assertEqual(h.evidence, ahm.EVIDENCE_AWAITING_FIRST_RUN, h.issue)
        self.assertEqual(h.due_by, "2026-10-16T00:17:57Z")


class NextCalendarRun(unittest.TestCase):
    def nxt(self, cal, after=BOOT, tz=UTC):
        return ahm.next_calendar_run({"StartCalendarInterval": cal}, after, tz)

    def test_daily(self):
        self.assertEqual(self.nxt({"Hour": 9, "Minute": 0}),
                         datetime(2026, 10, 16, 9, 0, tzinfo=UTC))

    def test_same_day_later_slot(self):
        self.assertEqual(self.nxt({"Hour": 23, "Minute": 5}),
                         datetime(2026, 10, 15, 23, 5, tzinfo=UTC))

    def test_hourly_by_minute(self):
        self.assertEqual(self.nxt({"Minute": 30}), datetime(2026, 10, 15, 21, 30, tzinfo=UTC))

    def test_weekly_sunday_both_spellings(self):
        want = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
        self.assertEqual(self.nxt({"Weekday": 0, "Hour": 10, "Minute": 0}), want)
        self.assertEqual(self.nxt({"Weekday": 7, "Hour": 10, "Minute": 0}), want)

    def test_array_takes_earliest_entry(self):
        cal = [{"Weekday": 2, "Hour": 3, "Minute": 0}, {"Weekday": 5, "Hour": 3, "Minute": 0}]
        self.assertEqual(self.nxt(cal), datetime(2026, 10, 16, 3, 0, tzinfo=UTC))

    def test_monthly(self):
        self.assertEqual(self.nxt({"Day": 1, "Hour": 4, "Minute": 0}),
                         datetime(2026, 11, 1, 4, 0, tzinfo=UTC))

    def test_calendar_is_local_time_of_the_host(self):
        from zoneinfo import ZoneInfo
        self.assertEqual(self.nxt({"Hour": 9, "Minute": 0}, tz=ZoneInfo("Europe/Madrid")),
                         datetime(2026, 10, 16, 7, 0, tzinfo=UTC))   # CEST = UTC+2

    def test_unreadable_schedule_is_none(self):
        self.assertIsNone(self.nxt({"Hour": "x"}))
        self.assertIsNone(ahm.next_calendar_run({}, BOOT, UTC))


class ReportAndScreen(_Scene):
    def test_due_by_reaches_the_report_row(self):
        la = self.root / "LaunchAgents"
        la.mkdir()
        with open(la / f"{RES}.plist", "wb") as fh:
            plistlib.dump(self.p_res, fh)
        mon = ahm.AgentHealthMonitor(data_dir=self.data, launch_agents_dir=la,
                                     launchctl_output=f"-\t0\t{RES}\n", now=NOW,
                                     boot_time=BOOT)
        a = next(x for x in mon.collect()["agents"] if x["label"] == RES)
        self.assertEqual(a["due_by"], "2026-10-16T00:17:57Z")

    def test_agents_screen_names_the_deadline(self):
        from spa_core.telegram.views import health
        rep = {"timestamp": NOW.isoformat(), "overall_status": "OK", "healthy_count": 1,
               "critical_count": 0, "total_agents": 1,
               "agents": [{"label": CAL, "status": "OK", "issue": "",
                           "evidence": ahm.EVIDENCE_AWAITING_FIRST_RUN,
                           "due_by": "2026-10-16T09:15:00Z"}]}
        with mock.patch.object(health, "_read_agent_health", return_value=rep):
            text, _ = health.render_agents(lang="ru")
        self.assertIn("⏳ zz_due_test_calendar — ждёт первого запуска после перезагрузки, "
                      "срок 2026-10-16 11:15 Мадрид (CEST)", text)
        self.assertNotIn("✅ zz_due_test_calendar", text)


if __name__ == "__main__":
    unittest.main()
