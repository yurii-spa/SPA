"""Контур подъёма T3→T2 замкнут: PROMOTE_CANDIDATE куратора → карточка → авто-закрытие.

# LLM_FORBIDDEN

Проба ПО ИСХОДУ, а не по структуре (разбор 11.09, `docs/TIER_LIFECYCLE_AUDIT_2026-09-11.md`
§8): у `data/tier_curator_report.json` не было ни одного читателя — вердикт
`PROMOTE_CANDIDATE` писался и умирал. Здесь спрашивается не «есть ли потребитель», а
«случилось ли то, ради чего отчёт пишется»: кандидат на подъём ⇒ карточка агенту
(собрать доказательства ADR-041, написать ADR); кандидат исчез ⇒ карточка закрыта
мостом сама. Порвись цепочка где угодно — краснеет.

Смена ЯРЛЫКА тира по этому пути НЕ происходит и не проверяется: ярлык — только ADR
(`docs/tier_criteria.md` §5). Замыкается контур ДО решения, не вместо него.

Время — вход (`now=`), отметки отчёта двигаются вместе с часами (ADR-266: наблюдение —
ЗАМЕР, а не прогон моста).
"""
# FROZEN-DATE-OK: injected-clock — NOW передаётся в run_bridge(now=) и в generated_at фикстуры
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import findings_bridge as fb
from spa_core.tests.test_findings_bridge import FakeQueue

NOW = dt.datetime(2026, 9, 12, 8, 0, tzinfo=dt.timezone.utc)
STEP = dt.timedelta(days=1)   # такт куратора — дневной цикл


def _promote(proto="susde", current="T3", target="T2"):
    return {"current_tier": current, "verdict": "PROMOTE_CANDIDATE",
            "reasons": ["stable_apy_14d+ · live TVL $31,000,000 ≥ 5.0×floor · tier_a clean · advisory only"],
            "evidence": {"tvl_usd": 31_000_000.0, "tvl_live": True, "apy_days": 21},
            "target_tier": target, "owner_gated": target == "T1"}


def _keep(proto="maple"):
    return {"current_tier": "T2", "verdict": "KEEP",
            "reasons": ["not_promotable: apy_history_short: 3 < 14 дней"], "evidence": {}}


class TierPromotionLoop(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        os.makedirs(os.path.join(self.root, "data"))
        self.tracker = os.path.join(self.root, "tracker")
        os.makedirs(self.tracker)
        self.q = FakeQueue(self.tracker)
        # Три существующих источника моста — пустые и читаемые.
        for name, doc in (("architecture_conformance.json", {"generated_at": NOW.isoformat(), "findings": []}),
                          ("house_view_gap.json", {"gaps": []}),
                          ("loop_retro.json", {"findings": []})):
            with open(os.path.join(self.root, "data", name), "w", encoding="utf-8") as f:
                json.dump(doc, f)

    def tearDown(self):
        self.td.cleanup()

    def put_curator(self, verdicts: dict, at: dt.datetime):
        doc = {"generated_at": at.isoformat(), "curator_version": "tier_curator_v1",
               "verdicts": verdicts,
               "summary": {"total": len(verdicts),
                           "promote_candidate": sum(1 for v in verdicts.values() if v["verdict"] == "PROMOTE_CANDIDATE"),
                           "held_flagged": []}}
        with open(os.path.join(self.root, "data", "tier_curator_report.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def run_bridge(self, at):
        # Замер соседних источников тоже двигается вместе с часами (ADR-266).
        with open(os.path.join(self.root, "data", "architecture_conformance.json"), "w", encoding="utf-8") as f:
            json.dump({"generated_at": at.isoformat(), "findings": []}, f)
        return fb.run_bridge(self.root, now=at, create=self.q.create, close=self.q._close,
                             notify=self.q.notify, retract=self.q.retract)

    # ── исход: кандидат ⇒ карточка ⇒ исчез ⇒ закрыта ──────────────────────
    def test_promote_candidate_becomes_a_card_and_closes_when_it_disappears(self):
        self.put_curator({"susde": _promote("susde"), "maple": _keep()}, NOW)
        r1 = self.run_bridge(NOW)                     # первое наблюдение — гистерезис
        self.assertEqual(r1["created"], [])
        self.assertIn("tier_promote:susde", r1["waiting_hysteresis"])
        self.put_curator({"susde": _promote("susde"), "maple": _keep()}, NOW + STEP)
        r2 = self.run_bridge(NOW + STEP)              # второй день подряд — карточка
        self.assertEqual(len(r2["created"]), 1)
        card = r2["created"][0]["card"]
        self.assertEqual(r2["created"][0]["key"], "tier_promote:susde")
        self.assertEqual(fb.card_status(card), "new")
        text = open(card, encoding="utf-8").read()
        self.assertIn("susde", text)
        self.assertIn("T3", text); self.assertIn("T2", text)
        self.assertIn("ADR-041", text)                 # карточка ведёт к критериям
        self.assertIn("НЕ ИЗМЕРЕНО", text)             # и честно называет, чего куратор не мерит
        # KEEP не рождает карточку — только кандидат.
        self.assertFalse(any("maple" in c["key"] for c in r2["created"]))
        r3 = self.put_curator({"susde": _promote("susde"), "maple": _keep()}, NOW + 2 * STEP) or self.run_bridge(NOW + 2 * STEP)
        self.assertEqual(r3["created"], [])            # держится — дубля нет
        self.assertEqual(r3["open_cards"], 1)
        # Кандидат исчез (условия перестали выполняться) — два молчаливых замера ⇒ закрыто.
        self.put_curator({"susde": _keep(), "maple": _keep()}, NOW + 3 * STEP)
        r4 = self.run_bridge(NOW + 3 * STEP)
        self.assertEqual(r4["closed"], [])
        self.put_curator({"susde": _keep(), "maple": _keep()}, NOW + 4 * STEP)
        r5 = self.run_bridge(NOW + 4 * STEP)
        self.assertEqual([c["card"] for c in r5["closed"]], [card])
        self.assertEqual(fb.card_status(card), "done")

    # ── контроли ──────────────────────────────────────────────────────────
    def test_no_candidate_no_finding(self):
        self.put_curator({"maple": _keep()}, NOW)
        findings, unread = fb.collect_findings(self.root)
        self.assertEqual([f for f in findings if f["source"] == "tier_curator"], [])
        self.assertNotIn(os.path.join("data", "tier_curator_report.json"), unread)

    def test_unreadable_report_is_named_not_silent(self):
        """Третий исход (инв. #17): «нечем прочитать» ≠ «кандидатов нет»."""
        with open(os.path.join(self.root, "data", "tier_curator_report.json"), "w") as f:
            f.write("{ not json")
        findings, unread = fb.collect_findings(self.root)
        self.assertIn(os.path.join("data", "tier_curator_report.json"), unread)
        self.assertEqual([f for f in findings if f["source"] == "tier_curator"], [])

    def test_missing_report_is_named_not_silent(self):
        findings, unread = fb.collect_findings(self.root)
        self.assertIn(os.path.join("data", "tier_curator_report.json"), unread)

    def test_t1_candidate_is_still_an_agent_card_never_an_owner_card(self):
        """Промоушен в T1 — решение владельца, но ЧЕРЕЗ ADR (ADR-285: не карточкой-вопросом).
        Кандидат в T1 рождает inbox-карточку агенту «собрать доказательства и написать ADR»,
        а не needs-owner. Severity WARN, не CRITICAL."""
        self.put_curator({"maple": _promote("maple", "T2", "T1")}, NOW)
        findings, _ = fb.collect_findings(self.root)
        f = [x for x in findings if x["key"] == "tier_promote:maple"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "WARN")
        self.assertIn("T1", f[0]["message"])

    def test_finding_carries_the_measurement_stamp(self):
        """Наблюдение = замер куратора, не прогон моста (ADR-266)."""
        self.put_curator({"susde": _promote()}, NOW)
        findings, _ = fb.collect_findings(self.root)
        f = [x for x in findings if x["source"] == "tier_curator"][0]
        self.assertEqual(f["measured_at"], NOW.isoformat())


if __name__ == "__main__":
    unittest.main()
