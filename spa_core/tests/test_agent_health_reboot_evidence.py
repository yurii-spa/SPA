"""Перезагрузка Mac ≠ «критическая проблема» (ARB, тревога 15.10.2026 21:21:20Z).

Карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`. Mac загрузился в 21:17:57Z;
через 3 мин 22 с пульс насчитал 30 пунктов и прислал «Агенты: критическая проблема, 30».
Ни одна из 27 агентских строк не была сбоем: macOS чистит /tmp при загрузке, и пульс
судил о работе по ИСЧЕЗНУВШЕМУ логу — «нет лога» у агентов, чей первый срок ещё не
наступил, и «110.9 сут. без работы» по домиграционному logs/<x>.log (26.06), хотя
`hy_paper_trading.last_cycle_at` стоял 21:10:55Z.

Каждый тест — положительный контроль: на коде origin c7e3b6c0 он красный (нет
квитанции, нет времени загрузки — вердикт выносит старый журнал), на починке зелёный.
Обратная сторона закреплена тут же: настоящий пропуск планового запуска и процесс,
который давно работает без результата, по-прежнему краснят.

Время и момент загрузки — ВХОДЫ (`now=`, `boot_time=`); mtime журналов ставится от
того же якоря. Метки синтетические: обёртка судит и по `/tmp/spa_<имя>.log`, и метка
флота читала бы живой журнал хоста.

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW и BOOT передаются в check_agent(now=, boot_time=)
# и AgentHealthMonitor(now=, boot_time=); mtime журналов и квитанции выводятся из них же.
"""
from __future__ import annotations

import json
import os
import plistlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import agent_health_monitor as ahm

NOW = datetime(2026, 10, 15, 21, 21, 20, tzinfo=timezone.utc)
BOOT = datetime(2026, 10, 15, 21, 17, 57, tzinfo=timezone.utc)

HY = "com.spa.zz_arb_test_hy"          # почасовой, с квитанцией (как hy_cycle)
CAL = "com.spa.zz_arb_test_calendar"   # утренний календарный, без квитанции
RES = "com.spa.zz_arb_test_hourly"     # почасовой резидент без квитанции (как orchestrator)
RECEIPTS = {HY: ("book.json", "last_cycle_at")}


def _require_no_host_log(test: unittest.TestCase) -> None:
    for lbl in (HY, CAL, RES):
        p = f"/tmp/spa_{lbl[len('com.spa.'):]}.log"
        if os.path.exists(p):  # громкий отказ, а не скип: предпосылка не обеспечена
            test.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: на хосте существует {p}")


class _Scene(unittest.TestCase):
    """Одноразовое дерево: data/, logs/ и каталог логов launchd."""

    def setUp(self):
        _require_no_host_log(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.root / "logs").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def plist(self, label, **sched):
        short = label[len("com.spa."):]
        return dict(sched, StandardOutPath=str(self.root / f"{short}.launchd.out"),
                    StandardErrorPath=str(self.root / f"{short}.launchd.err"))

    def touch(self, path, at):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()
        os.utime(path, (at.timestamp(), at.timestamp()))

    def legacy_log(self, label, at):
        self.touch(self.root / "logs" / f"{label[len('com.spa.'):]}.log", at)

    def receipt(self, at, data=None):
        (data or self.data).joinpath("book.json").write_text(
            json.dumps({"last_cycle_at": at.isoformat().replace("+00:00", "Z")}),
            encoding="utf-8")

    def judge(self, label, plist, *, now=NOW, boot=BOOT, pid=0, data=None,
              receipts=RECEIPTS):
        lc = {label: {"pid": pid, "exit": 0}}
        return ahm.check_agent(label, plist, True, lc, now, project_root=self.root,
                               data_dir=data if data is not None else self.data,
                               boot_time=boot, receipts=receipts)

    @property
    def p_hy(self):
        return self.plist(HY, StartInterval=3600, RunAtLoad=False)

    @property
    def p_cal(self):
        return self.plist(CAL, StartCalendarInterval={"Hour": 9, "Minute": 0}, RunAtLoad=False)

    @property
    def p_res(self):
        return self.plist(RES, StartInterval=3600, RunAtLoad=False)


class RebootWithVanishedTmpLogs(_Scene):
    """Сцена 21:21:20Z: /tmp пуст, журнал logs/ — 26.06, квитанция — 21:10:55Z."""

    def setUp(self):
        super().setUp()
        self.legacy_log(HY, datetime(2026, 6, 26, 23, 21, 45, tzinfo=timezone.utc))
        self.receipt(datetime(2026, 10, 15, 21, 10, 55, tzinfo=timezone.utc))

    def test_fresh_receipt_is_not_critical(self):
        h = self.judge(HY, self.p_hy)
        self.assertEqual(h.status, ahm.OK, h.issue)
        self.assertEqual(h.evidence, ahm.EVIDENCE_RECEIPT)
        self.assertEqual(h.issue, "")

    def test_calendar_agent_waits_for_its_first_slot(self):
        h = self.judge(CAL, self.p_cal)
        self.assertEqual(h.status, ahm.OK, h.issue)
        self.assertEqual(h.evidence, ahm.EVIDENCE_AWAITING_FIRST_RUN)

    def test_hourly_resident_waits_for_its_first_interval(self):
        """На origin: «log missing (never ran?)» → CRITICAL (как orchestrator 21:21)."""
        h = self.judge(RES, self.p_res)
        self.assertEqual(h.status, ahm.OK, h.issue)
        self.assertEqual(h.evidence, ahm.EVIDENCE_AWAITING_FIRST_RUN)

    def test_report_is_not_critical_and_alert_is_not_sent(self):
        agents = [self.judge(HY, self.p_hy), self.judge(CAL, self.p_cal),
                  self.judge(RES, self.p_res)]
        rep = ahm.build_report(agents, {}, ahm.OK, [], NOW)
        self.assertNotEqual(rep["overall_status"], ahm.CRITICAL)
        self.assertEqual(rep["critical_count"], 0)


class OldFallbackWhileFreshResultExists(_Scene):
    def test_old_legacy_log_is_not_110_days_without_work(self):
        """Время загрузки НЕ измерено — поблажки нет, но решает квитанция."""
        self.legacy_log(HY, NOW - timedelta(days=110.9))
        self.receipt(NOW - timedelta(minutes=10))
        h = self.judge(HY, self.p_hy, boot=None)
        self.assertEqual(h.status, ahm.OK, h.issue)
        self.assertEqual(h.evidence, ahm.EVIDENCE_RECEIPT)
        self.assertGreater(h.log_age_min, 110 * 24 * 60)  # журнал честно старый
        self.assertNotIn("stale", h.issue)


class GenuinelyMissedRunStaysCritical(_Scene):
    def test_stale_receipt_past_the_window_is_critical(self):
        later = BOOT + timedelta(days=2)
        self.receipt(BOOT - timedelta(minutes=7))
        h = self.judge(HY, self.p_hy, now=later)
        self.assertEqual(h.status, ahm.CRITICAL)
        self.assertEqual(h.evidence, ahm.EVIDENCE_RECEIPT)

    def test_receipt_already_stale_at_boot_gets_no_reboot_grace(self):
        """Агент, мёртвый ДО перезагрузки, не отмывается ею."""
        self.receipt(BOOT - timedelta(days=3))
        h = self.judge(HY, self.p_hy)
        self.assertEqual(h.status, ahm.CRITICAL)

    def test_no_run_since_boot_past_the_window_is_critical(self):
        later = BOOT + timedelta(days=3)
        h = self.judge(CAL, self.p_cal, now=later)
        self.assertEqual(h.status, ahm.CRITICAL)
        self.assertTrue(h.issue.startswith("no run since reboot"), h.issue)

    def test_one_window_late_is_a_warning(self):
        late = BOOT + timedelta(hours=4)  # окно часового резидента — 3 ч
        h = self.judge(RES, self.p_res, now=late)
        self.assertEqual(h.status, ahm.WARNING)

    def test_log_written_after_boot_then_stale_keeps_the_old_path(self):
        late = BOOT + timedelta(days=2)
        self.touch(self.p_res["StandardOutPath"], BOOT + timedelta(hours=1))
        h = self.judge(RES, self.p_res, now=late)
        self.assertEqual(h.status, ahm.CRITICAL)
        self.assertTrue(h.issue.startswith("log stale"), h.issue)


class RunningWithoutResult(_Scene):
    def test_live_pid_and_fresh_log_are_not_success(self):
        at = BOOT + timedelta(days=1)
        self.touch(self.p_hy["StandardOutPath"], at - timedelta(minutes=1))
        self.receipt(at - timedelta(hours=5))
        h = self.judge(HY, self.p_hy, now=at, pid=4242)
        self.assertNotEqual(h.status, ahm.OK)
        self.assertTrue(h.issue.startswith("running (pid 4242) but no successful result"),
                        h.issue)


class NotVerifiedIsItsOwnOutcome(_Scene):
    def test_unreadable_receipt_is_neither_ok_nor_critical(self):
        h = self.judge(HY, self.p_hy)  # квитанции нет вовсе
        self.assertEqual(h.status, ahm.WARNING)
        self.assertEqual(h.evidence, ahm.EVIDENCE_NOT_VERIFIED)

    def test_future_receipt_is_not_verified(self):
        self.receipt(NOW + timedelta(hours=3))
        h = self.judge(HY, self.p_hy)
        self.assertEqual(h.status, ahm.WARNING)
        self.assertEqual(h.evidence, ahm.EVIDENCE_NOT_VERIFIED)

    def test_boot_unmeasured_keeps_the_fail_closed_path(self):
        """Нет времени загрузки — поблажки нет: резидент без лога CRITICAL, как раньше."""
        h = self.judge(RES, self.p_res, boot=None)
        self.assertEqual(h.status, ahm.CRITICAL)
        self.assertEqual(h.issue, "log missing (never ran?)")
        self.assertEqual(h.evidence, "")

    def test_boot_in_the_future_is_unmeasured(self):
        h = self.judge(RES, self.p_res, boot=NOW + timedelta(hours=1))
        self.assertEqual(h.status, ahm.CRITICAL)


class SeveralQueueTrees(_Scene):
    """Вердикт — о ТОМ дереве, о котором спросили: две копии data/ с разными
    квитанциями дают разные ответы, а дерево не названо ⇒ квитанция не читается вовсе
    (никакой подстановки хостового data/)."""

    def test_each_tree_is_judged_by_its_own_receipt(self):
        other = self.root / "other_tree" / "data"
        other.mkdir(parents=True)
        later = BOOT + timedelta(days=1)
        self.receipt(later - timedelta(minutes=5))
        self.receipt(later - timedelta(days=1), data=other)
        fresh = self.judge(HY, self.p_hy, now=later)
        stale = self.judge(HY, self.p_hy, now=later, data=other)
        self.assertEqual(fresh.status, ahm.OK)
        self.assertEqual(stale.status, ahm.CRITICAL)

    def test_unnamed_tree_reads_no_receipt(self):
        r = ahm.read_success_receipt(HY, None, NOW, RECEIPTS)
        self.assertEqual(r.state, ahm.RECEIPT_NONE)

    def test_declared_fleet_receipts_name_the_reboot_agents(self):
        for lbl in ("com.spa.hy_cycle", "com.spa.lp_cycle", "com.spa.mass_tournament",
                    "com.spa.tier1_governance", "com.spa.tournament_engine"):
            self.assertIn(lbl, ahm.SUCCESS_RECEIPTS)


class MonitorWiring(_Scene):
    def _scene_monitor(self, **kw):
        la = self.root / "LaunchAgents"
        la.mkdir()
        with open(la / f"{RES}.plist", "wb") as fh:
            plistlib.dump(self.p_res, fh)
        return ahm.AgentHealthMonitor(data_dir=self.data, launch_agents_dir=la,
                                      launchctl_output=f"-\t0\t{RES}\n", now=NOW, **kw)

    def test_boot_time_reaches_check_agent(self):
        rep = self._scene_monitor(boot_time=BOOT).collect()
        a = next(x for x in rep["agents"] if x["label"] == RES)
        self.assertEqual(a["evidence"], ahm.EVIDENCE_AWAITING_FIRST_RUN)
        self.assertEqual(rep["boot_time"], BOOT.isoformat())

    def test_hermetic_scene_does_not_measure_the_host_boot(self):
        rep = self._scene_monitor().collect()
        self.assertIsNone(rep["boot_time"])
        a = next(x for x in rep["agents"] if x["label"] == RES)
        self.assertEqual(a["status"], ahm.CRITICAL)

    def test_parse_boottime(self):
        self.assertEqual(ahm.parse_boottime("{ sec = 1792099077, usec = 439300 } Thu Oct 15"),
                         BOOT)
        self.assertIsNone(ahm.parse_boottime(""))
        self.assertIsNone(ahm.parse_boottime("garbage"))


class OwnerMessage(unittest.TestCase):
    def _agent(self, label, status, issue="", evidence=None):
        return {"label": label, "status": status, "issue": issue, "evidence": evidence}

    def _report(self, agents, sys_issues=()):
        return {"timestamp": NOW.isoformat(), "overall_status": ahm.CRITICAL,
                "agents": agents, "system_issues": list(sys_issues)}

    def test_counts_by_class_not_a_wall(self):
        agents = ([self._agent(f"com.spa.w{i}", ahm.OK, evidence=ahm.EVIDENCE_AWAITING_FIRST_RUN)
                   for i in range(20)]
                  + [self._agent("com.spa.dead", ahm.CRITICAL, "last_exit=1"),
                     self._agent("com.spa.old", ahm.WARNING,
                                 "retired_but_loaded — label is in RETIRED_LABELS"),
                     self._agent("com.spa.unk", ahm.WARNING,
                                 "success receipt unreadable (x) — NOT VERIFIED",
                                 evidence=ahm.EVIDENCE_NOT_VERIFIED)])
        text = ahm.format_alert(self._report(agents, ["fleet parity DRIFT"]))
        self.assertIn("• настоящие сбои: 1 (критично: 1)", text)
        self.assertIn("• не проверено (не хватает доказательств): 1", text)
        self.assertIn("• расхождение настройки (агент снят с учёта, но загружен): 1", text)
        self.assertIn("• системные пункты: 1", text)
        self.assertIn("• ждут первого планового запуска после перезагрузки: 20 — это не сбой",
                      text)
        self.assertIn("❌ com.spa.dead — last_exit=1", text)
        self.assertNotIn("com.spa.w0", text)        # ожидающие — числом, не строкой
        self.assertNotIn("com.spa.old —", text)     # предупреждения — числом
        self.assertIn("2026-10-15 23:21 Мадрид (CEST)", text)
        self.assertIn("Нужно ли твоё решение:</b> нет", text)

    def test_fingerprint_ignores_warning_churn_but_not_new_criticals(self):
        base = [self._agent("com.spa.dead", ahm.CRITICAL, "last_exit=1")]
        fp = ahm.alert_fingerprint(self._report(base))
        with_warn = base + [self._agent("com.spa.swarm_health", ahm.WARNING, "last_exit=1")]
        self.assertEqual(ahm.alert_fingerprint(self._report(with_warn)), fp)
        with_crit = base + [self._agent("com.spa.other", ahm.CRITICAL, "last_exit=2")]
        self.assertNotEqual(ahm.alert_fingerprint(self._report(with_crit)), fp)

    def test_unchanged_alert_is_not_resent(self):
        from unittest import mock
        from spa_core.telegram import push_policy
        sent = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(push_policy, "_send",
                                  lambda text: (sent.append(text), True)[1]):
            base = [self._agent("com.spa.dead", ahm.CRITICAL, "last_exit=1")]
            ahm._push_via_policy(self._report(base), data_dir=Path(d))
            churn = base + [self._agent("com.spa.site_freshness", ahm.WARNING, "last_exit=1")]
            ahm._push_via_policy(self._report(churn), data_dir=Path(d))
        self.assertEqual(len(sent), 1, "новое предупреждение не повод слать ту же тревогу")


if __name__ == "__main__":
    unittest.main()
