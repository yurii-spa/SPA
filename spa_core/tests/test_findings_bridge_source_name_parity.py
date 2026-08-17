"""Уровень 2 гарантии 1 моста ДОЛЖЕН срабатывать и на стороже архитектуры.

Гарантия (`findings_bridge.closing_gate`, ADR-070 п.5, второй уровень): отчёт свеж,
но источник САМ написал в `unchecked`, что о входе находки судить не может ⇒
исчезновение находки объясняется ОТКАЗОМ, а не решением, и карточка остаётся
открытой (класс fail-OPEN #235).

Замок держится на СОВПАДЕНИИ ИМЁН: `dependency_names(находка)` против
`refused_names(отчёт)`, оба — из полей `input`/`check`/`metric`. У `house_view_gap`
имена совпадали (`allocation_rationale` там и там) и это закреплено тестом
`test_findings_bridge_silent_source::test_unnamed_idle_finding_names_rationale_as_its_input`.
У `architecture_conformance` они лежали в РАЗНЫХ пространствах:

    находки  check ∈ {B1, B2, B3, B5, B6}
    отказы   check ∈ {B1_fleet, B5_manifest, B6_curation}
    пересечение — ПУСТО

то есть на этом источнике уровень 2 не срабатывал НИКОГДА, а положительный контроль
гарантии (`SilentSourceDoesNotClose.WARN`) использовал фикстуру `{"check": "B1_fleet"}`,
которой настоящий `_finding` не порождает ни разу — контроль проверял выдуманную
находку. Цена: ослепший сторож закрывает свои же карточки. Нет `launchctl` ⇒ B1-находок
нет ⇒ мост читает это как «агенты стали reboot-safe». Ровно две такие карточки
(`B1:reboot_unsafe:com.spa.artifact_freshness`, `…:com.spa.swarm_dwell`) в очереди уже
стоят закрытыми.

Обе стороны замка проверяются здесь: отказ ДЕРЖИТ карточку (1–3) и — обратный
контроль — чужой отказ и исправный источник её отпускают (4–6), иначе гарантия
обменяла бы fail-OPEN на вечную очередь.

Часы инъектируются: `run_checks` получает `now=NOW`, гейт часов не читает вовсе.
"""
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.monitoring import architecture_conformance as ac
from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import house_view_gap as hvg

NOW = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются

SRC = "architecture_conformance"
UNSAFE = {"label": "com.spa.artifact_freshness", "intent": "active", "reboot_safe": False,
          "plist_source": "repo:scripts/com.spa.artifact_freshness.plist",
          "schedule": "interval:300s", "program": "x.sh", "layer": "product",
          "role": "monitoring", "produces": [], "consumes": [],
          "consumer_required": False, "governed_by": [], "curation": "partial", "notes": ""}
DRIFT_REASON = ("com.spa.site_freshness: plist объявлен путём в репо "
                "(launchd/com.spa.site_freshness.plist), каталог в это дерево не синкается")


def _manifest(agents=()):
    return {"schema_version": 1, "agents": list(agents), "artifacts": [],
            "designed_architectures": []}


def _run(m, fleet, **kw):
    extra = {} if kw.get("unmeasurable") is None else {"drift_unmeasurable": kw["unmeasurable"]}
    return ac.run_checks(m, fleet, lambda p: None, {}, NOW,
                         drift_problems=kw.get("drift"),
                         drift_measured=kw.get("measured", True),
                         curation=kw.get("curation"), **extra)


def _entry(report, key):
    """Запись состояния моста ровно так, как её строит `run_bridge` из находки."""
    f = next(x for x in report["findings"] if x["key"] == key)
    return {"source": SRC, "status": "carded", "card": "c.md",
            "depends_on": fb.dependency_names(f)}


def _states(report, *, closing=True):
    return {SRC: {"closing": closing, "refused": fb.refused_names(report)}}


class RefusalHoldsTheCardOpen(unittest.TestCase):
    """Источник ослеп ⇒ находка исчезла ⇒ карточка ОБЯЗАНА остаться открытой."""

    def test_fleet_unmeasured_holds_a_b1_card(self):
        """Авария дословно: сторож переехал на хост без launchctl.

        B1-находки исчезают все разом, отчёт при этом свежий и прочитанный —
        под сломанным замком мост закрыл бы `B1:reboot_unsafe:*` как починенные.
        """
        alive = _run(_manifest([UNSAFE]), {"com.spa.artifact_freshness"})
        entry = _entry(alive, "B1:reboot_unsafe:com.spa.artifact_freshness")

        blind = _run(_manifest([UNSAFE]), None)          # launchctl недоступен
        self.assertEqual([f for f in blind["findings"] if f["check"] == "B1"], [])
        gate = fb.closing_gate(entry, _states(blind))
        self.assertIsNotNone(gate, "карточка B1 закрыта ослепшим сторожем (fail-OPEN #235)")
        self.assertIn("отказался судить", gate)

    def test_drift_unmeasured_holds_a_b5_card(self):
        """B5 не мерили ВООБЩЕ (хост без com.spa.*-plist'ов) — широкий отказ."""
        alive = _run(_manifest(), set(),
                     drift=ac.group_drift_by_agent(["com.spa.x: schedule 'interval:300s' → None"]))
        entry = _entry(alive, "B5:drift:com.spa.x")

        blind = _run(_manifest(), set(), measured=False)
        self.assertEqual([f for f in blind["findings"] if f["check"] == "B5"], [])
        self.assertIsNotNone(fb.closing_gate(entry, _states(blind)))

    def test_refusal_about_the_same_agent_holds_its_card(self):
        """Точечно: строка дрейфа уехала в `unmeasurable` — про ТОГО ЖЕ агента."""
        alive = _run(_manifest(), set(),
                     drift=ac.group_drift_by_agent(
                         ["com.spa.site_freshness: program 'agent_site_freshness.sh' → None"]))
        entry = _entry(alive, "B5:drift:com.spa.site_freshness")

        blind = _run(_manifest(), set(), drift=[], unmeasurable=[DRIFT_REASON])
        self.assertEqual([f for f in blind["findings"] if f["check"] == "B5"], [])
        gate = fb.closing_gate(entry, _states(blind))
        self.assertIsNotNone(gate)
        self.assertIn("com.spa.site_freshness", gate)


class TheLockStaysPointwise(unittest.TestCase):
    """Обратный контроль: замок не имеет права заклинить очередь навсегда."""

    def test_refusal_about_another_agent_releases_the_card(self):
        alive = _run(_manifest(), set(),
                     drift=ac.group_drift_by_agent(["com.spa.x: program 'a.sh' → None"]))
        entry = _entry(alive, "B5:drift:com.spa.x")
        other = _run(_manifest(), set(), drift=[], unmeasurable=[DRIFT_REASON])
        self.assertIsNone(fb.closing_gate(entry, _states(other)))

    def test_healthy_source_still_closes(self):
        alive = _run(_manifest([UNSAFE]), {"com.spa.artifact_freshness"})
        entry = _entry(alive, "B1:reboot_unsafe:com.spa.artifact_freshness")
        safe = dict(UNSAFE, reboot_safe=True, plist_source="launch_agents")
        healthy = _run(_manifest([safe]), {"com.spa.artifact_freshness"})
        self.assertEqual([f for f in healthy["findings"] if f["check"] == "B1"], [])
        self.assertEqual(healthy["unchecked"], [])
        self.assertIsNone(fb.closing_gate(entry, _states(healthy)))

    def test_b5_refusal_does_not_hold_a_b1_card(self):
        alive = _run(_manifest([UNSAFE]), {"com.spa.artifact_freshness"})
        entry = _entry(alive, "B1:reboot_unsafe:com.spa.artifact_freshness")
        b5_blind = _run(_manifest([UNSAFE]), {"com.spa.artifact_freshness"}, measured=False)
        self.assertIsNone(fb.closing_gate(entry, _states(b5_blind)))


class NamespacesMustIntersect(unittest.TestCase):
    """Храповик: имя отказа обязано быть тем же, каким находка зовёт свой вход.

    Без него правку легко откатить обратно «косметикой»: убрать одно поле — и
    поведенческие тесты выше покраснеют не назвав ПРИЧИНУ.
    """

    def test_every_refusal_names_a_check_id_the_findings_use(self):
        blind = _run(_manifest([UNSAFE]), None, measured=False,
                     curation={"measured": False, "ref": "origin/main", "reason": "нет ref"})
        refused = set(fb.refused_names(blind))
        for check_id in ("B1", "B5", "B6"):
            self.assertIn(check_id, refused,
                          f"отказ не назван именем {check_id!r}: {sorted(refused)}")

    def test_refusal_keeps_its_wide_human_name_too(self):
        """Прежнее имя не отнимаем: его читают и человек, и существующие тесты."""
        blind = _run(_manifest([UNSAFE]), None)
        self.assertTrue(any(u["check"] == "B1_fleet" for u in blind["unchecked"]))


class AnalystRefusalIsNotCalm(unittest.TestCase):
    """Второй ослепший источник: аналитик офиса, отказавшийся судить.

    `red_team` fail-closed'ится внутри себя: пропал `data/threat_reactor_status.json`
    ⇒ постура `UNKNOWN_CAUTIOUS` (`threat_data_missing_or_stale`). Для сверки это
    выглядело ТАК ЖЕ, как честное `NO_THREAT_OBSERVED`: находки нет, `unchecked`
    пуст — и мост закрывал карточку `gap:analyst_red:red_team` как починенную.
    Отличить «врага нет» от «разведка ослепла» читателю было нечем.
    """

    HVG = "house_view_gap"
    FRESH = {"age_s": 600.0}

    def _report(self, red):
        return hvg.compute_gaps(None, None, None, None, {"red_team": red}, NOW,
                                {"analyst:red_team": self.FRESH})

    def _entry(self):
        red = self._report({"posture": "CRITICAL",
                            "posture_reason": ["kill_switch_already_active"]})
        finding = next(g for g in red["gaps"] if g["key"] == "gap:analyst_red:red_team")
        return {"source": self.HVG, "status": "carded", "card": "c.md",
                "depends_on": fb.dependency_names(finding)}

    def _gate(self, report):
        return fb.closing_gate(self._entry(),
                               {self.HVG: {"closing": True,
                                           "refused": fb.refused_names(report)}})

    def test_blind_analyst_holds_its_card_open(self):
        blind = self._report({"status": "UNKNOWN", "posture": "UNKNOWN_CAUTIOUS",
                              "posture_reason": ["threat_data_missing_or_stale"]})
        self.assertEqual([g for g in blind["gaps"] if g["type"] == "analyst_red"], [])
        gate = self._gate(blind)
        self.assertIsNotNone(gate, "карточка закрыта ослепшей разведкой (fail-OPEN #29)")
        self.assertIn("analyst:red_team", gate)

    def test_calm_analyst_still_closes_its_card(self):
        """Обратный контроль: НАБЛЮДЁННОЕ спокойствие карточку по-прежнему закрывает."""
        calm = self._report({"status": "ok", "posture": "NO_THREAT_OBSERVED",
                             "posture_reason": []})
        self.assertNotIn("analyst:red_team", fb.refused_names(calm))
        self.assertIsNone(self._gate(calm))

    def test_red_analyst_is_still_a_finding_not_a_refusal(self):
        """Обратный контроль: красный аналитик — находка, а не отказ."""
        red = self._report({"posture": "CRITICAL",
                            "posture_reason": ["kill_switch_already_active"]})
        self.assertEqual([g["key"] for g in red["gaps"]], ["gap:analyst_red:red_team"])
        self.assertNotIn("analyst:red_team", fb.refused_names(red))


if __name__ == "__main__":
    unittest.main()
