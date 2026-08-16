"""B2: бюджет свежести выводится из ФАКТОВ, а не из литерала (цикл #256).

Positive control у каждого теста — реальная авария 2026-08-16, измеренная по
`/tmp/spa_decision_loop.log` и `architecture/manifest.json`:

    `data/investment_os/outcomes.jsonl` пишется РАЗ В КАЛЕНДАРНЫЙ ДЕНЬ
    (идемпотентно по дате, день без evidenced-бара сознательно НЕ занимается),
    а производитель `com.spa.decision_loop` тикает раз в 6ч. Значит запись
    случается только на такте, и честный максимум разрыва — 24ч + 6ч = 30ч.
    Объявлено было `slo_hours: 26` ⇒ сторож давал WARN на ИСПРАВНОМ
    refusal-first производителе. Наблюдённая последовательность разрывов
    (по времени строк «outcomes: записан» в логе агента):

        08-08 07:02Z → 08-09 01:02Z   18ч
        08-09 01:02Z → 08-10 07:02Z   30ч   ← больше объявленных 26ч
        08-10 07:02Z → 08-11 07:03Z   24ч
        08-12 07:03Z → 08-13 01:03Z   18ч
        08-15 01:03Z → 08-16 07:03Z   30ч   ← и снова, на исправной системе

    Цикл #193 (10.08) видел тот же WARN и списал его на аварийную остановку
    прода — тогда это было верно, сегодня остановки нет, а WARN тот же. Симптом
    один, причины разные: поэтому проверяется ПРИЧИНА (бюджет), а не число.

Обратная сторона проверяется в каждом случае: сторож не смеет стать зеленее —
настоящее протухание обязано краснеть, а класс `agent_registry` (19 дней
молчаливого протухания) обязан сохраниться байт-в-байт.

Часы инъектируются (now=), литеральных дат нет (deployment.md: время — вход).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from spa_core.monitoring import architecture_conformance as ac

NOW = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются парой с отметками


def agent(label, schedule="interval:21600s"):
    return {"label": label, "intent": "active", "reboot_safe": True,
            "plist_source": "launch_agents", "schedule": schedule,
            "program": "x.sh", "layer": "product", "role": "monitoring",
            "produces": [], "consumes": [], "consumer_required": False,
            "governed_by": [], "curation": "partial", "notes": ""}


def artifact(path, producer, slo_hours, period_hours=None):
    art = {"path": path, "producer": producer, "consumers": [],
           "slo_hours": slo_hours, "status": "active", "notes": ""}
    if period_hours is not None:
        art["period_hours"] = period_hours
    return art


def run(agents, artifacts, ages_h):
    """Прогон только B2: флот НЕ измерен (B1 отключён), реситов нет."""
    m = {"schema_version": 1, "agents": list(agents), "artifacts": list(artifacts),
         "designed_architectures": []}
    ts = {p: NOW - dt.timedelta(hours=h) for p, h in ages_h.items()}
    return ac.run_checks(m, None, lambda p: ts.get(p), {}, NOW)


def keys(report, prefix):
    return [f["key"] for f in report["findings"] if f["key"].startswith(prefix)]


OUT = "data/investment_os/outcomes.jsonl"
LOOP = "com.spa.decision_loop"


class ProducerTick(unittest.TestCase):
    """Такт производителя читается из машинного словаря манифеста."""

    def test_interval_seconds_become_hours(self):
        self.assertEqual(ac.producer_tick_hours("interval:21600s"), 6.0)
        self.assertEqual(ac.producer_tick_hours("interval:3600s"), 1.0)

    def test_calendar_daily_and_weekly(self):
        self.assertEqual(ac.producer_tick_hours("calendar:08:00"), 24.0)
        self.assertEqual(ac.producer_tick_hours("calendar:wd0·09:30"), 168.0)

    def test_daemon_has_no_quantisation(self):
        self.assertEqual(ac.producer_tick_hours("daemon"), 0.0)

    def test_unschedulable_is_none_not_zero(self):
        """`manual`/`event`/пусто — такт НЕ ИЗМЕРЕН. Ноль был бы враньём:
        он объявил бы любой SLO выполнимым."""
        for s in ("manual", "event:watchpaths", "", None, "interval:хх"):
            self.assertIsNone(ac.producer_tick_hours(s), s)


class FreshnessFloor(unittest.TestCase):

    def test_floor_is_period_plus_tick(self):
        by = {LOOP: agent(LOOP)}
        f = ac.freshness_floor(artifact(OUT, LOOP, 31, period_hours=24), by)
        self.assertEqual(f["floor_h"], 30.0)
        self.assertEqual((f["period_h"], f["tick_h"]), (24.0, 6.0))

    def test_no_period_declared_means_written_every_tick(self):
        by = {LOOP: agent(LOOP)}
        f = ac.freshness_floor(artifact("data/x.json", LOOP, 7), by)
        self.assertEqual(f["floor_h"], 6.0)

    def test_unknown_producer_refuses_to_guess(self):
        f = ac.freshness_floor(artifact("data/x.json", None, 26), {})
        self.assertIsNone(f["floor_h"])
        self.assertIn("продюсер", f["reason"])
        f = ac.freshness_floor(artifact("data/x.json", "com.spa.ghost", 26), {})
        self.assertIsNone(f["floor_h"])


class TheRealIncident(unittest.TestCase):
    """2026-08-16: WARN на исправном производителе."""

    def test_healthy_30h_gap_is_not_stale(self):
        """Наблюдённый разрыв 30ч при бюджете 24+6 — исправная система."""
        r = run([agent(LOOP)], [artifact(OUT, LOOP, 31, period_hours=24)],
                {OUT: 30.0})
        self.assertEqual(keys(r, "B2:stale"), [],
                         "разрыв 30ч физически минимален — это НЕ протухание")

    def test_every_observed_gap_stays_silent(self):
        """Вся измеренная по логу последовательность разрывов — без единого WARN."""
        for gap in (18.0, 24.0, 30.0):
            r = run([agent(LOOP)], [artifact(OUT, LOOP, 31, period_hours=24)],
                    {OUT: gap})
            self.assertEqual(keys(r, "B2:stale"), [], f"разрыв {gap}ч")

    def test_unsatisfiable_slo_is_named_as_a_manifest_defect(self):
        """Старый литерал 26ч: краснеет НЕ производитель, а сам манифест."""
        r = run([agent(LOOP)], [artifact(OUT, LOOP, 26, period_hours=24)],
                {OUT: 27.3})
        self.assertEqual(keys(r, "B2:slo_unsatisfiable"),
                         [f"B2:slo_unsatisfiable:{OUT}"])
        self.assertEqual(keys(r, "B2:stale"), [],
                         "пока литерал невыполним, протухание считается по полу — "
                         "иначе сторож обвиняет исправного производителя")
        msg = [f["message"] for f in r["findings"]
               if f["key"].startswith("B2:slo_unsatisfiable")][0]
        for part in ("26", "30", "24", "6"):
            self.assertIn(part, msg, "находка обязана назвать слагаемые бюджета")

    def test_budget_is_shown_machine_readable(self):
        """Урок #235: бюджет обязан быть показательным, иначе спорить не с чем."""
        r = run([agent(LOOP)], [artifact(OUT, LOOP, 31, period_hours=24)],
                {OUT: 10.0})
        row = [b for b in r["slo_budgets"] if b["path"] == OUT][0]
        self.assertEqual((row["declared_h"], row["floor_h"], row["budget_h"]),
                         (31.0, 30.0, 31.0))
        self.assertEqual((row["period_h"], row["tick_h"]), (24.0, 6.0))
        self.assertIs(row["satisfiable"], True)


class NotGreenerThanBefore(unittest.TestCase):
    """Обратные контроли: сторож смеет перестать врать, но не смеет ослепнуть."""

    def test_genuine_staleness_still_fires(self):
        """Производитель встал: разрыв 40ч превышает даже честный пол."""
        r = run([agent(LOOP)], [artifact(OUT, LOOP, 31, period_hours=24)],
                {OUT: 40.0})
        self.assertEqual(keys(r, "B2:stale"), [f"B2:stale:{OUT}"])

    def test_agent_registry_class_survives_untouched(self):
        """19 дней молчаливого протухания (tick 1ч, SLO 26ч) — как было."""
        reg = "data/agent_registry.json"
        r = run([agent("com.spa.agent_health", "interval:3600s")],
                [artifact(reg, "com.spa.agent_health", 26)],
                {reg: 475.9})
        self.assertEqual(keys(r, "B2:stale"), [f"B2:stale:{reg}"])
        self.assertEqual(keys(r, "B2:slo_unsatisfiable"), [],
                         "26ч при такте 1ч выполнимо — это лень, а не дефект манифеста")

    def test_daily_producer_with_daily_artifact_still_fires_at_27h(self):
        """io_* класс: такт 24ч, SLO 26ч, период не объявлен ⇒ пол 24ч.
        Поведение обязано остаться прежним — иначе фикс тихо ослабил 11 аналитиков."""
        p = "data/investment_os/quant.json"
        r = run([agent("com.spa.io_quant", "interval:86400s")],
                [artifact(p, "com.spa.io_quant", 26)], {p: 27.0})
        self.assertEqual(keys(r, "B2:stale"), [f"B2:stale:{p}"])

    def test_missing_artifact_still_fires(self):
        r = run([agent(LOOP)], [artifact(OUT, LOOP, 31, period_hours=24)], {})
        self.assertEqual(keys(r, "B2:missing"), [f"B2:missing:{OUT}"])

    def test_unmeasurable_tick_does_not_widen_the_budget(self):
        """Продюсера нет ⇒ пол неизвестен ⇒ бюджет остаётся объявленным.
        Фикс не смеет превратить «не измерено» в «разрешено»."""
        p = "data/consumption_receipts.jsonl"
        r = run([], [artifact(p, None, 26)], {p: 27.0})
        self.assertEqual(keys(r, "B2:stale"), [f"B2:stale:{p}"])
        row = [b for b in r["slo_budgets"] if b["path"] == p][0]
        self.assertIsNone(row["floor_h"])
        self.assertIsNone(row["satisfiable"])


class RealManifestRatchet(unittest.TestCase):
    """Храповик: в конституции не должно быть невыполнимых SLO."""

    def setUp(self):
        path = os.path.join(ac.REPO_ROOT, "architecture", "manifest.json")
        if not os.path.exists(path):
            self.skipTest("architecture/manifest.json недоступен в этом дереве")
        self.m = json.load(open(path, encoding="utf-8"))
        self.by = {a["label"]: a for a in self.m.get("agents", [])
                   if a.get("label")}

    def test_no_active_artifact_declares_an_unsatisfiable_slo(self):
        bad = []
        for art in self.m.get("artifacts", []):
            if art.get("status") != "active":
                continue
            f = ac.freshness_floor(art, self.by)
            declared = float(art.get("slo_hours") or 0)
            if declared and f["floor_h"] is not None and declared < f["floor_h"]:
                bad.append(f"{art['path']}: SLO {declared:g}ч < пола {f['floor_h']:g}ч "
                           f"(период {f['period_h']:g}ч + такт {f['tick_h']:g}ч)")
        self.assertEqual(bad, [], "невыполнимый SLO краснеет на ИСПРАВНОЙ системе "
                                  "и учит не верить B2 — чинить литерал")

    def test_outcomes_declares_its_daily_period(self):
        """Именно необъявленный период и сделал литерал 26ч невидимо неверным."""
        art = [a for a in self.m["artifacts"] if a["path"] == OUT]
        self.assertEqual(len(art), 1)
        self.assertEqual(art[0].get("period_hours"), 24,
                         "строка на календарный день — это период, а не такт")

    def test_produces_block_agrees_with_artifacts_section(self):
        """Две независимые декларации одного SLO разъезжаются молча (builder
        сохраняет `artifacts` как есть) — сверяем их явно."""
        from_artifacts = {a["path"]: a.get("slo_hours")
                          for a in self.m.get("artifacts", [])}
        mismatched = []
        for ag in self.m.get("agents", []):
            for p in ag.get("produces") or []:
                path, slo = p.get("artifact"), p.get("slo_hours")
                if path in from_artifacts and from_artifacts[path] != slo:
                    mismatched.append(f"{path}: produces {slo}ч ≠ "
                                      f"artifacts {from_artifacts[path]}ч")
        self.assertEqual(mismatched, [])


if __name__ == "__main__":
    unittest.main()
