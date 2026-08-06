"""Тесты Фазы 4 ADR-066: loop_health + loop_retro + храповик unresolved.

Приёмка карточки Фазы 4 закреплена в LiveRetro: первый ретро-отчёт обязан
содержать честные UNCHECKED (несуществующий архив вердиктов не «прощается»,
а называется) и ≥1 обоснованный вывод-finding, уходящий в мост.

Храповик: множество unresolved-агентов манифеста == база БАЙТ-В-БАЙТ —
вырасти не может (новый агент рождается с решённым intent), а уменьшение
заставляет подтянуть базу (щелчок храповика, по образцу frozen_date).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from spa_core.monitoring import loop_health as lh
from spa_core.monitoring import loop_retro as lr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NOW = dt.datetime(2030, 5, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: часы инъектируются


def proof(days_ago_list, now=NOW):
    return [{"generated_at": (now - dt.timedelta(days=d, hours=1)).isoformat()}
            for d in days_ago_list]


class Retro(unittest.TestCase):
    def test_cadence_and_staleness_measured(self):
        analysts = lr.analyze_proofs(
            {"quant": proof(range(14)), "onchain": proof([10, 12, 13])}, NOW)
        by = {a["analyst"]: a for a in analysts}
        self.assertEqual(by["quant"]["days_covered"], 14)
        self.assertGreaterEqual(by["quant"]["cadence"], 0.99)
        self.assertEqual(by["onchain"]["days_covered"], 3)
        self.assertGreater(by["onchain"]["stale_h"], lr.STALE_H)

    def test_low_output_analyst_becomes_candidate_and_finding(self):
        r = lr.build_report(lr.analyze_proofs({"onchain": proof([10, 12])}, NOW),
                            None, 9, NOW)
        self.assertEqual(len(r["candidates"]), 1)
        self.assertIn("owner-gated", r["findings"][0]["message"])
        self.assertIn("R4", r["candidates"][0]["recommendation"])

    def test_healthy_analyst_is_not_a_candidate(self):
        r = lr.build_report(lr.analyze_proofs({"quant": proof(range(14))}, NOW),
                            None, 9, NOW)
        self.assertEqual(r["candidates"], [])

    def test_unmeasurable_is_unchecked_not_silence(self):
        """Ядро честности: hit-rate без архива вердиктов = UNCHECKED с причиной
        + обязательный вывод-finding «завести архив» (уходит в мост)."""
        r = lr.build_report([], None, None, NOW)
        self.assertGreaterEqual(len(r["unchecked"]), 3)
        self.assertTrue(all(u["reason"] for u in r["unchecked"]))
        keys = [f["key"] for f in r["findings"]]
        self.assertIn("retro:verdict_archive_missing", keys)


class Health(unittest.TestCase):
    def test_latency_fate_and_recurrence(self):
        t0 = NOW - dt.timedelta(hours=20)
        state = {"findings": {
            "k1": {"first_seen": t0.isoformat(),
                   "carded_at": (t0 + dt.timedelta(hours=6)).isoformat(),
                   "closed_at": (t0 + dt.timedelta(hours=18)).isoformat(),
                   "status": "closed", "card": "/x/c1.md", "recurrences": 2},
            "k2": {"first_seen": t0.isoformat(),
                   "carded_at": (t0 + dt.timedelta(hours=10)).isoformat(),
                   "status": "carded", "card": "/x/c2.md"},
            "k3": {"first_seen": t0.isoformat(), "status": "observed"},
        }}
        r = lh.compute(state, lambda p: "in-progress", NOW)
        self.assertEqual(r["latency_finding_to_card"], {"median_h": 8.0, "max_h": 10.0, "n": 2})
        self.assertEqual(r["latency_card_to_close"]["median_h"], 12.0)
        self.assertEqual(r["recurrences_total"], 2)
        self.assertEqual(r["open_cards"], 1)
        self.assertEqual(r["cards_fate"]["auto_closed"], 1)
        self.assertEqual(r["cards_fate"]["in_progress"], 1)

    def test_empty_state_is_honest_zero(self):
        r = lh.compute({}, lambda p: None, NOW)
        self.assertEqual(r["open_cards"], 0)
        self.assertEqual(r["latency_finding_to_card"]["n"], 0)


class UnresolvedRatchet(unittest.TestCase):
    """Храповик: unresolved-множество манифеста == база, расти не может."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.load(open(os.path.join(REPO_ROOT, "architecture", "manifest.json")))
        cls.baseline = json.load(open(os.path.join(REPO_ROOT, "architecture",
                                                   "unresolved_baseline.json")))

    def unresolved_now(self):
        return sorted(a["label"] for a in self.manifest["agents"]
                      if a["intent"] == "unresolved")

    def test_no_new_unresolved_agents(self):
        """Новый агент обязан рождаться с решённым intent — дрейф запрещён."""
        extra = set(self.unresolved_now()) - set(self.baseline["unresolved"])
        self.assertEqual(extra, set(),
                         f"НОВЫЕ unresolved-агенты запрещены (реши intent или карточку владельцу): {extra}")

    def test_baseline_shrinks_with_reality(self):
        """Решённый агент обязан покинуть базу — храповик щёлкает, назад пути нет."""
        gone = set(self.baseline["unresolved"]) - set(self.unresolved_now())
        self.assertEqual(gone, set(),
                         f"эти агенты больше не unresolved — УДАЛИТЬ из unresolved_baseline.json: {gone}")

    def test_baseline_sorted_unique(self):
        b = self.baseline["unresolved"]
        self.assertEqual(b, sorted(set(b)))


class LiveRetro(unittest.TestCase):
    """ПРИЁМКА: живой ретро-отчёт честен В ОБЕ СТОРОНЫ.

    ИЗМЕНЁН НАМЕРЕННО 2026-08-06 (инвариант #16, обоснование — docs/journal/2026-W32.md).
    Прежняя версия требовала, чтобы в живом отчёте ВСЕГДА стояла находка
    `retro:verdict_archive_missing`, то есть закрепляла состояние ИНЦИДЕНТА:
    она покраснела бы ровно в тот момент, когда дыру закрыли, и была бы зелёной
    всё то время, пока архив отсутствовал. Проверка не ослаблена, а УСИЛЕНА —
    теперь отчёт обязан соответствовать реальности в обе стороны:

      архива нет  ⇒ находка обязана БЫТЬ (старое требование сохранено целиком);
      архив есть  ⇒ находки быть НЕ должно, а сменяемость по каждому аналитику
                    обязана быть либо измерена, либо честно названа неизмеримой.

    Подделка в любую сторону краснеет: и «архив есть, а находка висит» (сторож
    кричит на исправное), и «архива нет, а находка исчезла» (сторож молчит на
    сломанном). Старая версия ловила ровно ноль из этих двух случаев.
    """

    def test_live_retro_report_matches_reality_both_ways(self):
        if not os.path.isdir(os.path.join(REPO_ROOT, "data", "investment_os")):
            self.skipTest("не прод-хост: нет data/investment_os")
        path = os.path.join(REPO_ROOT, "data", "loop_retro.json")
        if not os.path.exists(path):
            self.skipTest("ретро ещё не запускался на этом хосте")
        r = json.load(open(path))
        self.assertGreaterEqual(len(r["findings"]), 1)
        self.assertTrue(all(u["reason"] for u in r["unchecked"]),
                        "UNCHECKED без причины — это молчание, а не честность")
        if "verdict_archive" not in r:
            self.skipTest("отчёт старого формата — ретро ещё не перезапускалось после правки")

        arch = r["verdict_archive"]
        missing = any(f["key"] == "retro:verdict_archive_missing" for f in r["findings"])
        alive = bool(arch and arch.get("total_lines"))
        self.assertEqual(missing, not alive,
                         "находка «нет архива» обязана стоять тогда и только тогда, "
                         f"когда архива действительно нет (строк: {arch and arch.get('total_lines')})")
        if not alive:
            self.assertGreaterEqual(len(r["unchecked"]), 3)
            return
        for a in arch["analysts"]:
            self.assertTrue(a["flip_rate"] is not None or a["unchecked_reason"],
                            f"{a['analyst']}: ни измеренной сменяемости, ни причины — "
                            "молчаливый пропуск запрещён")


if __name__ == "__main__":
    unittest.main()
