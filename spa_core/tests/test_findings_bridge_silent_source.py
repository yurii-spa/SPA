"""Три гарантии дубля #125, перенесённые в ЖИВОЙ мост (ADR-070 п.5, решение владельца 07.08).

Владелец выбрал вариант 2 карточки `owner-decision-nochyu-odnu-zadachu-sdelali-dvazhdy-moya`:
живой контур остаётся, в него переносятся три гарантии сохранённого дубля.

| # | Гарантия | Где живёт | Была ли в живом контуре |
|---|---|---|---|
| 1 | молчащий источник НЕ закрывает карточки | `findings_bridge.closing_gate` | **нет — дефект** |
| 2 | названный отказ — не находка | `house_view_gap` (INFO вместо WARN) | да, закрепляется здесь |
| 3 | непрочитанный файл ≠ «отказ не назван» | `house_view_gap.compute_gaps` | **нет — дефект** |

**Почему гарантия 1 не имеет права быть грубой.** Мост закрывает карточку по исчезновению
находки, и это ХОРОШО ровно до тех пор, пока исчезновение означает починку. Цикл #235 назвал
обратную сторону дословно: ужми потолок свежести у источника — сверка офис↔книга замолчит
раньше, находки исчезнут, и мост закроет их карточки как решённые (fail-OPEN). Поэтому гарантия
проверяется здесь В ОБЕ СТОРОНЫ: молчание источника карточку не закрывает (тесты 1–3, 5), но
и живой источник, чья находка ДЕЙСТВИТЕЛЬНО исчезла, закрывает её как раньше (тесты 4, 6) —
иначе гарантия обменяла бы fail-OPEN на вечную очередь, которая ничем не лучше.

Время — вход: `now` инъектируется во ВСЕ прогоны, отметки отчётов считаются от той же
константы. Карточные операции инъектируются (`FakeQueue` из test_findings_bridge) — тест
НИКОГДА не трогает живой tracker.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import house_view_gap as hvg
from spa_core.tests.test_findings_bridge import FakeQueue

NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются


def _iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


# ── гарантия 1: молчащий источник НЕ закрывает карточки ──────────────────────

class SilentSourceDoesNotClose(unittest.TestCase):
    """Каждый тест — один способ для источника ЗАМОЛЧАТЬ, и ни один из них не починка."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        os.makedirs(os.path.join(self.root, "data"))
        self.tracker = os.path.join(self.root, "tracker")
        os.makedirs(self.tracker)
        self.q = FakeQueue(self.tracker)

    def tearDown(self):
        self.td.cleanup()

    # -- фикстуры источников -------------------------------------------------

    def write_source(self, name: str, payload: dict) -> None:
        path = os.path.join(self.root, "data", fb.SOURCES[name].split(os.sep)[-1])
        with open(os.path.join(os.path.dirname(path), os.path.basename(path)),
                  "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def conformance(self, findings, *, age_h: float = 0.0, stamped: bool = True,
                    unchecked=()) -> None:
        doc: dict = {"findings": list(findings), "unchecked": list(unchecked)}
        if stamped:
            doc["generated_at"] = _iso(age_h)
        self.write_source("architecture_conformance", doc)

    def gap(self, gaps, *, age_h: float = 0.0, unchecked=()) -> None:
        self.write_source("house_view_gap", {"generated_at": _iso(age_h),
                                             "gaps": list(gaps),
                                             "unchecked": list(unchecked)})

    def retro(self, findings=(), *, age_h: float = 0.0) -> None:
        self.write_source("loop_retro", {"generated_at": _iso(age_h),
                                         "findings": list(findings), "unchecked": []})

    def quiet_others(self) -> None:
        """Прочие источники — прочитаны, свежи и без находок (чтобы не мешали суду)."""
        self.gap([])
        self.retro([])

    def bridge(self, at: dt.datetime):
        return fb.run_bridge(self.root, now=at, create=self.q.create,
                             close=self.q._close, notify=self.q.notify,
                             retract=self.q.retract)

    WARN = {"key": "B1:reboot_unsafe:com.spa.x", "severity": "WARN",
            "check": "B1_fleet", "message": "агент не переживёт перезагрузку"}

    def carded(self) -> str:
        """Довести WARN-находку сторожа архитектуры до карточки (гистерезис = 2 прогона)."""
        self.conformance([self.WARN])
        self.quiet_others()
        self.bridge(NOW)
        r = self.bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(len(r["created"]), 1, "фикстура: карточка не родилась")
        return r["created"][0]["card"]

    # -- 1..3: три способа замолчать -----------------------------------------

    def test_vanished_report_does_not_close_its_cards(self):
        """Файл отчёта ИСЧЕЗ. Отсутствие отчёта ≠ отсутствие находки."""
        card = self.carded()
        os.remove(os.path.join(self.root, "data", "architecture_conformance.json"))
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "new")
        held = {h["key"]: h for h in r["closing_held_open"]}
        self.assertIn(self.WARN["key"], held)
        self.assertIn("НЕ ПРОЧИТАН", held[self.WARN["key"]]["reason"])

    def test_stale_report_does_not_close_its_cards(self):
        """Отчёт ЕСТЬ, но протух: сторож молчит, и его молчание не закрывает карточки."""
        card = self.carded()
        self.conformance([], age_h=fb.SOURCE_MAX_AGE_H + 1.0)
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "new")
        self.assertFalse(r["source_states"]["architecture_conformance"]["closing"])
        self.assertIn("протух", r["source_states"]["architecture_conformance"]["reason"])

    def test_report_without_generated_at_does_not_close(self):
        """Свежесть НЕ ИЗМЕРЕНА — значит не измерено и право закрывать."""
        card = self.carded()
        self.conformance([], stamped=False)
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "new")
        self.assertIn("generated_at",
                      r["source_states"]["architecture_conformance"]["reason"])

    # -- 4: обратный контроль ------------------------------------------------

    def test_live_source_still_closes_a_really_resolved_finding(self):
        """Гарантия НЕ ИМЕЕТ ПРАВА заклинить закрытие: живой источник закрывает как раньше."""
        card = self.carded()
        self.conformance([])                       # прочитан, свеж, находки нет
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual([c["card"] for c in r["closed"]], [card])
        self.assertEqual(fb.card_status(card), "done")
        self.assertEqual(r["closing_held_open"], [])

    # -- 5..6: отказ источника о ВХОДЕ находки (класс #235) ------------------

    GAP_WARN = {"key": "gap:opportunity_unnamed:moonwell_base", "severity": "WARN",
                "message": "возможность moonwell_base 10.74% доступна, отказ НЕ назван",
                "input_ages": {"chief_investment": {"age_s": 3600.0},
                               "current_positions": {"age_s": 3600.0},
                               "allocation_rationale": {"age_s": 3600.0}}}

    def gap_carded(self) -> str:
        self.conformance([])
        self.retro([])
        self.gap([self.GAP_WARN])
        self.bridge(NOW)
        r = self.bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(len(r["created"]), 1, "фикстура: карточка сверки не родилась")
        return r["created"][0]["card"]

    def test_refusal_about_the_findings_own_input_does_not_close(self):
        """АВАРИЯ #235 дословно: у источника ужали потолок свежести входа.

        Отчёт при этом СВЕЖИЙ и прочитанный — находка исчезла только потому, что сверка
        ОТКАЗАЛАСЬ судить о постуре офиса. Под старым правилом мост закрыл бы карточку
        как решённую, и безымянный простой капитала исчез бы из очереди молча.
        """
        card = self.gap_carded()
        self.gap([], unchecked=[{"input": "chief_investment",
                                 "reason": "снимок протух — сверка ОТКАЗЫВАЕТСЯ судить"}])
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "new")
        held = {h["key"]: h for h in r["closing_held_open"]}
        self.assertIn(self.GAP_WARN["key"], held)
        self.assertIn("chief_investment", held[self.GAP_WARN["key"]]["reason"])
        # источник при этом ПРОЧИТАН — гейт сработал именно на отказе о входе,
        # а не на молчании файла (иначе тест доказывал бы не то, что заявлено)
        self.assertTrue(r["source_states"]["house_view_gap"]["closing"])

    def test_refusal_about_an_unrelated_input_still_closes(self):
        """Точечность гейта: чужой отказ карточку не держит.

        Обратный контроль против грубого правила «в отчёте есть unchecked ⇒ не закрываем»:
        у `loop_retro` строки `unchecked` постоянны по построению, и грубое правило
        заклинило бы закрытие НАВСЕГДА — то есть обменяло бы fail-OPEN на вечную очередь.
        """
        card = self.gap_carded()
        self.gap([], unchecked=[{"input": "analyst:io_liquidity",
                                 "reason": "снимок аналитика протух"}])
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual([c["card"] for c in r["closed"]], [card])
        self.assertEqual(fb.card_status(card), "done")

    def test_state_entry_records_source_and_inputs(self):
        """Гейт держится на двух полях записи; без них он ушёл бы на легаси-путь."""
        self.gap_carded()
        state = json.load(open(os.path.join(self.root, fb.STATE_REL)))
        entry = state["findings"][self.GAP_WARN["key"]]
        self.assertEqual(entry["source"], "house_view_gap")
        self.assertIn("allocation_rationale", entry["depends_on"])

    def test_legacy_entry_without_source_needs_every_source_alive(self):
        """Запись без источника (сделана до гарантии / восстановлена из трекера).

        Кто обнулил такую находку — неизвестно, поэтому закрывать её вправе только
        прогон, в котором молчащих источников нет вовсе. Это fail-CLOSED, а не отказ:
        при живых источниках закрытие проходит.
        """
        card = self.carded()
        state_path = os.path.join(self.root, fb.STATE_REL)
        state = json.load(open(state_path))
        entry = state["findings"][self.WARN["key"]]
        entry.pop("source", None)
        entry.pop("depends_on", None)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)

        # один источник молчит (нет generated_at) ⇒ воздерживаемся
        self.conformance([])
        self.write_source("loop_retro", {"findings": []})
        r = self.bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "new")
        self.assertIn("loop_retro", r["closing_held_open"][0]["reason"])

        # все источники живы ⇒ то же закрытие происходит
        self.retro([])
        r2 = self.bridge(NOW + dt.timedelta(hours=18))
        self.assertEqual([c["card"] for c in r2["closed"]], [card])


# ── гарантия 2: названный отказ — не находка (и не карточка) ─────────────────

class NamedRefusalIsNotAFinding(unittest.TestCase):
    """Уже жило в контуре как INFO-маршрутизация; закрепляется НА УРОВНЕ КАРТОЧКИ.

    Сама степень INFO проверена в `test_findings_bridge`, но гарантия владельца
    сформулирована про очередь: «карточка не заводится, иначе очередь забивается
    бумагой про осознанные решения». Мост берёт только WARN/CRITICAL — значит
    проверять надо именно этот стык, а не одну степень.
    """

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        os.makedirs(os.path.join(self.root, "data"))
        self.tracker = os.path.join(self.root, "tracker")
        os.makedirs(self.tracker)
        self.q = FakeQueue(self.tracker)

    def tearDown(self):
        self.td.cleanup()

    def _write(self, rationale):
        chief = {"house_view": {"overall_posture": "YELLOW", "top_opportunities": [
            {"value": {"protocol": "maple", "apy_pct": 9.0}, "evidence_level": "L3"}]}}
        positions = {"positions": {"pendle": 10000.0}, "cash_usd": 15000.0,
                     "capital_usd": 100000.0}
        report = hvg.compute_gaps(chief, positions, rationale, {"pendle", "maple"}, {}, NOW)
        report["generated_at"] = NOW.isoformat()
        with open(os.path.join(self.root, "data", "house_view_gap.json"),
                  "w", encoding="utf-8") as f:
            json.dump(report, f)
        for name in ("architecture_conformance.json", "loop_retro.json"):
            with open(os.path.join(self.root, "data", name), "w", encoding="utf-8") as f:
                json.dump({"generated_at": NOW.isoformat(), "findings": [],
                           "unchecked": []}, f)

    def _two_runs(self):
        fb.run_bridge(self.root, now=NOW, create=self.q.create, close=self.q._close,
                      notify=self.q.notify, retract=self.q.retract)
        return fb.run_bridge(self.root, now=NOW + dt.timedelta(hours=6),
                             create=self.q.create, close=self.q._close,
                             notify=self.q.notify, retract=self.q.retract)

    def test_named_refusal_never_becomes_a_card(self):
        self._write({"below_median_cap": [{"protocol": "maple"}]})
        r = self._two_runs()
        self.assertEqual(r["created"], [])
        self.assertEqual(self.q.created, [])

    def test_unnamed_refusal_does_become_a_card(self):
        """Обратный контроль: гарантия 2 не глушит настоящий безымянный простой."""
        self._write({"below_median_cap": []})
        r = self._two_runs()
        self.assertEqual([c["key"] for c in r["created"]],
                         ["gap:opportunity_unnamed:maple"])


# ── гарантия 3: непрочитанный файл ≠ «отказ не назван» ───────────────────────

def _chief(protocol="maple"):
    return {"house_view": {"overall_posture": "YELLOW", "top_opportunities": [
        {"value": {"protocol": protocol, "apy_pct": 9.0}, "evidence_level": "L3"}]}}


def _book():
    return {"positions": {"pendle": 10000.0}, "cash_usd": 15000.0, "capital_usd": 100000.0}


class UnreadFileIsNotEvidence(unittest.TestCase):
    def test_unread_rationale_is_not_evidence_that_refusal_is_unnamed(self):
        """`None` = файл не прочитан ⇒ вопрос НЕ ИЗМЕРЕН, находка не объявляется.

        До этой правки `if rationale:` склеивал «файла нет» и «в файле отказов нет»,
        поэтому пропажа производителя rationale объявляла книгу виновной в безымянном
        простое — карточка на исправную систему (ложная тревога опаснее пропуска, #183).
        """
        r = hvg.compute_gaps(_chief(), _book(), None, {"pendle", "maple"}, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 0)
        self.assertEqual([g for g in r["gaps"] if g["severity"] == "WARN"], [])
        reasons = [u["reason"] for u in r["unchecked"] if u["input"] == "allocation_rationale"]
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in x for x in reasons), reasons)
        self.assertTrue(any("maple" in x for x in reasons), reasons)

    def test_read_but_silent_rationale_still_yields_warn(self):
        """Обратный контроль: `{}` — файл ПРОЧИТАН и отказов в нём нет. Это вердикт.

        Без этой стороны гарантия 3 выродилась бы в глушилку: достаточно было бы
        пустого rationale, чтобы безымянный простой капитала перестал называться.
        """
        r = hvg.compute_gaps(_chief(), _book(), {}, {"pendle", "maple"}, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 1)
        self.assertIn("отказ НЕ назван", r["gaps"][0]["message"])

    def test_unnamed_idle_finding_names_rationale_as_its_input(self):
        """Сцепка гарантий 3 и 1 — без неё гарантия 3 РОДИЛА БЫ fail-OPEN #235.

        Гарантия 3 гасит WARN, когда rationale не прочитан. Значит уже открытая карточка
        безымянного простоя в этот момент исчезает из отчёта — и мост закрыл бы её как
        решённую, если бы находка не называла `allocation_rationale` своим входом, а
        сверка — тем же именем в `unchecked`. Совпадение имён и есть замок.
        """
        warn = hvg.compute_gaps(_chief(), _book(), {}, {"pendle", "maple"}, {},
                                NOW)["gaps"][0]
        self.assertIn("allocation_rationale", fb.dependency_names(warn))

        silent = hvg.compute_gaps(_chief(), _book(), None, {"pendle", "maple"}, {}, NOW)
        self.assertIn("allocation_rationale", fb.refused_names(silent))

        entry = {"source": "house_view_gap", "depends_on": fb.dependency_names(warn)}
        states = {"house_view_gap": {"closing": True, "refused": fb.refused_names(silent)}}
        self.assertIsNotNone(fb.closing_gate(entry, states))


if __name__ == "__main__":
    unittest.main()
