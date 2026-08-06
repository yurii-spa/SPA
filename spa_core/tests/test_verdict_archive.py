"""Архив вердиктов аналитиков (ADR-066) — каждый тест воспроизводит реальную дыру.

Дыра, из-за которой всё это написано: `<agent>_proof.jsonl` хранит хэш ФАКТА
выработки, а `<agent>.json` перезаписывается каждым прогоном. Значит на проде
навсегда терялось, ЧТО именно аналитик сказал вчера, и вопрос «говорит ли офис
дело» был не «плохим», а неизмеримым (находка `retro:verdict_archive_missing`,
подтверждена двумя прогонами ретро 2026-08-05).

Положительные контроли здесь — не украшение:
  • `test_emit_writes_verdict_line` краснеет, если снять хук из harness.emit —
    ровно то состояние, в котором прод жил до сегодня;
  • `test_no_archive_keeps_the_finding` фиксирует, что находка НЕ исчезает от
    того, что кто-то посмотрел в другую сторону (архива нет — находка есть);
  • `test_zero_lines_is_not_a_pass` — пустой архив не считается за архив;
  • `test_lagging_archive_is_its_own_finding` — молча сломавшийся архив опаснее
    отсутствующего: он выглядит рабочим;
  • `test_flip_rate_unchecked_below_two_days` — один день это НЕ «0 флипов»;
    подать его за стабильность было бы тем же fail-OPEN, от которого лечимся.

Время — вход: все отметки выведены из ОДНОГО `now`, литеральных дат нет
(правило `.claude/rules/deployment.md`, храповик `test_frozen_date_ratchet`).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.investment_os import verdict_archive as va
from spa_core.investment_os.harness import ProductAgent
from spa_core.monitoring import loop_retro as lr
from spa_core.tests._freshness import now_utc

NOW = now_utc()


def day(days_ago: int = 0) -> str:
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%d")


def at(days_ago: int = 0) -> dt.datetime:
    return NOW - dt.timedelta(days=days_ago)


def analyst_row(name: str, *, last_days_ago: int | None = 0, cadence: float = 1.0) -> dict:
    """Строка из analyze_proofs — ровно те поля, на которые смотрит archive-слой."""
    return {"analyst": name, "days_covered": 14, "window_days": 14, "cadence": cadence,
            "last_generated_at": at(last_days_ago).isoformat() if last_days_ago is not None else None,
            "stale_h": 1.0 if last_days_ago is not None else None}


def verdict_line(name: str, posture: str, days_ago: int, sha: str | None = None) -> dict:
    return {"agent": name, "date": day(days_ago), "generated_at": at(days_ago).isoformat(),
            "posture": posture, "fields": {}, "sizes": {}, "names": {},
            "content_sha256": sha or f"sha-{posture}"}


class Digest(unittest.TestCase):
    def test_posture_found_in_every_real_shape(self):
        """Три реальные формы прод-артефактов: chief, market_regime, _health."""
        self.assertEqual(va.digest({"house_view": {"posture": "YELLOW"}})["posture"], "YELLOW")
        self.assertEqual(va.digest({"combined_posture": "RED"})["posture"], "RED")
        self.assertEqual(va.digest({"overall": "HEALTHY"})["posture"], "HEALTHY")

    def test_content_hash_ignores_clock_but_not_opinion(self):
        """Смысл всей затеи: флип = смена мнения, а не ход часов."""
        base = {"combined_posture": "YELLOW", "coverage": {"n": 3}}
        a = dict(base, generated_at=at(1).isoformat(), as_of=at(1).isoformat())
        b = dict(base, generated_at=at(0).isoformat(), as_of=at(0).isoformat())
        self.assertEqual(va.content_sha256(a), va.content_sha256(b))
        changed = dict(b, combined_posture="RED")
        self.assertNotEqual(va.content_sha256(b), va.content_sha256(changed))

    def test_digest_is_bounded(self):
        """Архив живёт вечно — снимок обязан быть ограничен, а не копией payload."""
        payload = {f"k{i}": i for i in range(500)}
        payload["long"] = "x" * 10_000
        d = va.digest(payload)
        self.assertLessEqual(len(d["fields"]), va.MAX_FIELDS)
        self.assertTrue(all(not isinstance(v, str) or len(v) <= va.MAX_STR
                            for v in d["fields"].values()))

    def test_named_opportunities_survive(self):
        """Без имён потом не ответить «а сбылась ли ИМЕННО эта возможность»."""
        d = va.digest({"opportunities": [{"protocol": "pendle", "apy": 8.0},
                                         {"protocol": "aerodrome_usdc_lp", "apy": 8.5}]})
        self.assertEqual(d["sizes"]["opportunities"], 2)
        self.assertEqual(d["names"]["opportunities"], ["pendle", "aerodrome_usdc_lp"])

    def test_status_ok_is_not_a_posture(self):
        """Замер по проду: 8 из 12 аналитиков публикуют только `status: "ok"`.

        Принять его за постуру = получить метрику, которая ВСЕГДА показывает
        «мнение не менялось». Выглядит как измерение, измерением не является —
        ровно тот fail-OPEN, ради которого архив и заводится.
        """
        d = va.digest({"status": "ok", "yield_quality": {"evidence_level": "L4"}})
        self.assertIsNone(d["posture"])
        self.assertEqual(d["fields"]["status"], "ok", "status записан, просто он не постура")

    def test_posture_read_from_the_real_chief_shape(self):
        """У chief постура лежит в house_view.overall_posture, а не в status."""
        d = va.digest({"status": "ok", "house_view": {"overall_posture": "YELLOW",
                                                      "regime": "YELLOW"}})
        self.assertEqual(d["posture"], "YELLOW")

    def test_boilerplate_is_not_a_verdict(self):
        d = va.digest({"agent": "quant", "is_advisory": True, "note": "n" * 300,
                       "consumer_contract": "c", "status": "ok"})
        self.assertEqual(set(d["fields"]), {"status"})


class ArchiveWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_one_line_per_agent_per_day_and_chained(self):
        payload = {"combined_posture": "YELLOW"}
        self.assertTrue(va.append_verdict("quant", payload, data_dir=self.dir, now=at(1)))
        self.assertFalse(va.append_verdict("quant", payload, data_dir=self.dir, now=at(1)),
                         "второй прогон в тот же день не имеет права дублировать строку")
        self.assertTrue(va.append_verdict("quant", payload, data_dir=self.dir, now=at(0)))
        lines = va.read_verdicts("quant", self.dir)
        self.assertEqual([r["date"] for r in lines], [day(1), day(0)])
        self.assertEqual(lines[1]["prev_hash"], lines[0]["hash"])

    def test_agents_do_not_share_a_file(self):
        va.append_verdict("quant", {"status": "ok"}, data_dir=self.dir, now=NOW)
        va.append_verdict("onchain", {"status": "ok"}, data_dir=self.dir, now=NOW)
        self.assertEqual(len(va.read_verdicts("quant", self.dir)), 1)
        self.assertEqual(len(va.read_verdicts("onchain", self.dir)), 1)

    def test_broken_line_is_skipped_not_fatal(self):
        va.append_verdict("quant", {"status": "ok"}, data_dir=self.dir, now=NOW)
        with va.archive_path("quant", self.dir).open("a", encoding="utf-8") as fh:
            fh.write("{не json\n")
        self.assertEqual(len(va.read_verdicts("quant", self.dir)), 1)

    def test_missing_file_is_empty_not_error(self):
        self.assertEqual(va.read_verdicts("nobody", self.dir), [])


class Flip(unittest.TestCase):
    def test_flip_rate_unchecked_below_two_days(self):
        """Один день — не «0 флипов». Молчаливый ноль здесь и был бы ложью."""
        s = va.flip_stats([verdict_line("quant", "YELLOW", 0)])
        self.assertIsNone(s["flip_rate"])
        self.assertTrue(s["unchecked_reason"])

    def test_empty_archive_is_unchecked(self):
        self.assertIsNone(va.flip_stats([])["flip_rate"])

    def test_flip_rate_counts_posture_changes(self):
        s = va.flip_stats([verdict_line("q", "RED", 2), verdict_line("q", "RED", 1),
                           verdict_line("q", "GREEN", 0)])
        self.assertEqual(s["days"], 3)
        self.assertEqual(s["posture_flips"], 1)
        self.assertEqual(s["flip_rate"], 0.5)
        self.assertIsNone(s["unchecked_reason"])

    def test_no_posture_still_measures_content_flip(self):
        """Аналитик без постуры не остаётся неизмеренным — меряем содержание."""
        a = verdict_line("yield_quality", None, 1, sha="a")
        b = verdict_line("yield_quality", None, 0, sha="b")
        s = va.flip_stats([a, b])
        self.assertIsNone(s["flip_rate"], "постуры нет — выдумывать её нельзя")
        self.assertEqual(s["content_flips"], 1)
        self.assertEqual(s["content_flip_rate"], 1.0)
        self.assertIn("постуру", s["unchecked_reason"])

    def test_same_posture_different_content_is_seen(self):
        """Постура та же, содержание другое — это тоже движение мнения."""
        s = va.flip_stats([verdict_line("q", "YELLOW", 1, sha="a"),
                           verdict_line("q", "YELLOW", 0, sha="b")])
        self.assertEqual(s["posture_flips"], 0)
        self.assertEqual(s["content_flips"], 1)


class _Agent(ProductAgent):
    agent_key = "test_analyst"

    def analyze(self) -> dict:
        return {"status": "ok", "combined_posture": "YELLOW"}


class HarnessIntegration(unittest.TestCase):
    """ГЛАВНЫЙ положительный контроль: снять хук из emit — тест краснеет."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_emit_writes_verdict_line(self):
        _Agent(data_dir=self.dir, allow_llm=False).run(now=NOW)
        lines = va.read_verdicts("test_analyst", self.dir)
        self.assertEqual(len(lines), 1, "выработка без архивной строки = потерянный вердикт")
        self.assertEqual(lines[0]["posture"], "YELLOW")
        self.assertEqual(lines[0]["date"], day(0))

    def test_archive_line_matches_the_proof_line_day(self):
        """Архив и proof-цепочка обязаны сходиться 1:1 по дням."""
        _Agent(data_dir=self.dir, allow_llm=False).run(now=NOW)
        proof = [json.loads(x) for x in
                 open(os.path.join(self.dir, "test_analyst_proof.jsonl"), encoding="utf-8")]
        self.assertEqual([r["date"] for r in proof],
                         [r["date"] for r in va.read_verdicts("test_analyst", self.dir)])

    def test_broken_archive_never_costs_the_artifact(self):
        """Сторож не роняет то, что охраняет: упавший архив ≠ потерянный артефакт."""
        orig = va.append_verdict

        def boom(*a, **k):
            raise RuntimeError("диск кончился")

        va.append_verdict = boom
        try:
            artifact = _Agent(data_dir=self.dir, allow_llm=False).run(now=NOW)
        finally:
            va.append_verdict = orig
        self.assertTrue(os.path.exists(artifact))
        self.assertEqual(json.load(open(artifact))["combined_posture"], "YELLOW")


class RetroConsumesTheArchive(unittest.TestCase):
    def test_no_archive_keeps_the_finding(self):
        """Состояние прода ДО этой правки — находка обязана быть."""
        r = lr.build_report([analyst_row("quant")], None, None, NOW, verdicts=None)
        self.assertIn("retro:verdict_archive_missing", [f["key"] for f in r["findings"]])
        self.assertGreaterEqual(len(r["unchecked"]), 3)

    def test_zero_lines_is_not_a_pass(self):
        """Файлы завели, но в них пусто — это не «архив есть». Fail-CLOSED."""
        v = lr.analyze_verdicts({"quant": []}, [analyst_row("quant")])
        r = lr.build_report([analyst_row("quant")], None, None, NOW, verdicts=v)
        self.assertIn("retro:verdict_archive_missing", [f["key"] for f in r["findings"]])

    def test_live_archive_clears_the_finding_and_measures_flip(self):
        v = lr.analyze_verdicts(
            {"quant": [verdict_line("quant", "RED", 1), verdict_line("quant", "GREEN", 0)]},
            [analyst_row("quant")])
        r = lr.build_report([analyst_row("quant")], None, None, NOW, verdicts=v)
        keys = [f["key"] for f in r["findings"]]
        self.assertNotIn("retro:verdict_archive_missing", keys)
        self.assertNotIn("retro:verdict_archive_lagging", keys)
        arch = r["verdict_archive"]["analysts"][0]
        self.assertEqual(arch["flip_rate"], 1.0)
        self.assertEqual(arch["archived_days"], 2)
        # то, что и с архивом неизмеримо, обязано остаться названным
        self.assertTrue(r["unchecked"])
        self.assertTrue(all(u["reason"] for u in r["unchecked"]))
        self.assertFalse(any("нет архива вердиктов" in u["reason"] for u in r["unchecked"]),
                         "причина обязана меняться вместе с реальностью")

    def test_lagging_archive_is_its_own_finding(self):
        """Молча сломавшийся архив выглядит рабочим — отдельная находка."""
        v = lr.analyze_verdicts(
            {"quant": [verdict_line("quant", "RED", 3), verdict_line("quant", "RED", 2)]},
            [analyst_row("quant", last_days_ago=0)])
        r = lr.build_report([analyst_row("quant", last_days_ago=0)], None, None, NOW, verdicts=v)
        self.assertIn("retro:verdict_archive_lagging", [f["key"] for f in r["findings"]])
        self.assertEqual(v["lagging"], ["quant"])

    def test_silent_analyst_does_not_blame_the_archive(self):
        """У молчащего аналитика пустой архив — его молчание, а не поломка архива."""
        v = lr.analyze_verdicts({"quiet": [], "quant": [verdict_line("quant", "RED", 0)]},
                                [analyst_row("quiet", last_days_ago=None),
                                 analyst_row("quant", last_days_ago=0)])
        self.assertEqual(v["lagging"], [])

    def test_run_reads_the_archive_end_to_end(self):
        """Контроль ПРОВОДКИ: run() обязан сам найти архив, а не только уметь его читать."""
        with tempfile.TemporaryDirectory() as root:
            io_dir = os.path.join(root, "data", "investment_os")
            os.makedirs(io_dir)
            for d in (1, 0):
                with open(os.path.join(io_dir, "quant_proof.jsonl"), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"agent": "quant", "date": day(d),
                                         "generated_at": at(d).isoformat()}) + "\n")
                va.append_verdict("quant", {"combined_posture": "RED" if d else "GREEN"},
                                  data_dir=io_dir, now=at(d))
            r = lr.run(root=root, now=NOW)
            self.assertNotIn("retro:verdict_archive_missing", [f["key"] for f in r["findings"]])
            self.assertEqual(r["verdict_archive"]["total_lines"], 2)
            self.assertEqual(r["verdict_archive"]["analysts"][0]["flip_rate"], 1.0)
            self.assertTrue(os.path.exists(os.path.join(root, lr.RETRO_REL)))


if __name__ == "__main__":
    unittest.main()
