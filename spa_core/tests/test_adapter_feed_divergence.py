"""Сверка двух артефактов адаптеров (ADR-060 D6) — сторож `adapter_feed_divergence`.

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на замер 2026-08-26 22:0xZ (цикл #389):
живые `data/adapter_status.json` и `data/adapter_orchestrator_status.json`, написанные
одним дневным циклом с разницей 0.6 с, говорили про `pendle` 8.0 пп / T2 / static-$500M
против 13.9673 пп / T3 / live-$6.15M. Проверка, никогда не видевшая настоящей поломки,
— украшение (`.claude/rules/deployment.md`), поэтому фикстуры ниже — это те самые байты,
а не выдуманный пример.

Время — ВХОД (`now=`) И отметки фикстур закреплены: обе стороны зафиксированы, тест не
может протухнуть от сдвига календаря.
"""
# FROZEN-DATE-OK: даты фикстур — сам предмет теста (воспроизводится авария 2026-08-26,
# где предметом является совпадение такта двух артефактов до долей секунды).
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import adapter_feed_divergence as afd

# Отметки живого замера 26.08 — оба артефакта одного цикла, разрыв 0.6 с.
TS_STATUS = "2026-08-26T20:47:01.804963+00:00"
TS_ORCH = "2026-08-26T20:47:02.415118+00:00"
NOW = dt.datetime(2026, 8, 26, 22, 19, 0, tzinfo=dt.timezone.utc)


def _status_doc(adapters: dict, ts: str = TS_STATUS) -> dict:
    return {"schema_version": 1, "generated_at": ts, "adapters": adapters}


def _orch_doc(adapters: list, ts: str = TS_ORCH) -> dict:
    return {"schema_version": 1, "generated_at": ts, "source": "adapter_orchestrator",
            "adapters": adapters}


#: `pendle` ДОСЛОВНО из data/adapter_status.json 26.08 20:47:01Z.
PENDLE_STATUS = {
    "display_name": "Pendle Finance (PT markets)", "apy": 8.0, "live_apy": None,
    "live_apy_as_of": None, "live_apy_fresh": False, "fallback_apy": 8.0,
    "tvl_usd": 500000000.0, "tvl_source": "static", "tier": 2, "chain": "ethereum",
    "per_protocol_cap": 0.2, "active": True,
}
#: `pendle` ДОСЛОВНО из data/adapter_orchestrator_status.json 26.08 20:47:02Z.
PENDLE_ORCH = {
    "protocol": "pendle", "adapter_class": "PendleAdapter", "tier": "T3",
    "apy_pct": 13.9673, "tvl_usd": 6151592.04118271, "status": "ok",
    "live_data": True, "tvl_source": "live", "health_score": 1.0,
}
#: `maple` — согласная пара того же замера (обе стороны живые, числа совпадают).
MAPLE_STATUS = {
    "apy": 4.8531, "live_apy": 4.8531, "live_apy_fresh": True, "fallback_apy": 5.0,
    "tvl_usd": 2770841620.0, "tvl_source": "live", "tier": 2,
}
MAPLE_ORCH = {
    "protocol": "maple", "tier": "T2", "apy_pct": 4.8531, "tvl_usd": 2770841620.0,
    "status": "ok", "live_data": True, "tvl_source": "live",
}


def _run(status_adapters, orch_adapters, *, now=NOW,
         ts_status=TS_STATUS, ts_orch=TS_ORCH) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        os.makedirs(data)
        if status_adapters is not None:
            with open(os.path.join(data, "adapter_status.json"), "w") as fh:
                json.dump(_status_doc(status_adapters, ts_status), fh)
        if orch_adapters is not None:
            with open(os.path.join(data, "adapter_orchestrator_status.json"), "w") as fh:
                json.dump(_orch_doc(orch_adapters, ts_orch), fh)
        return afd.run(root=tmp, now=now, data_dir=data)


def _kinds(report: dict) -> set:
    return {f["kind"] for f in report["findings"]}


class TestRealDivergence20260826(unittest.TestCase):
    """Авария, ради которой сторож заведён."""

    def test_pendle_literal_vs_live_is_named(self):
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH])
        self.assertIn("apy_literal_vs_live", _kinds(r))
        f = next(x for x in r["findings"] if x["kind"] == "apy_literal_vs_live")
        self.assertEqual(f["severity"], afd.WARN)
        self.assertEqual(f["live_side"], "orchestrator")
        self.assertEqual(f["live_apy"], 13.9673)
        self.assertEqual(f["literal_side"], "adapter_status")
        self.assertEqual(f["literal_apy"], 8.0)
        self.assertEqual(f["delta_pp"], 5.9673)

    def test_pendle_literal_vs_live_is_NOT_called_a_contradiction(self):
        """Уточнение карточки D6 нельзя потерять: вторая сторона не наблюдала ничего.

        Если сторож назовёт это спором двух наблюдений, починка поедет в «выбрать
        число», а верная починка — «дать фиду второй стороны дожить до pendle».
        """
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH])
        self.assertNotIn("apy_live_vs_live", _kinds(r))
        self.assertEqual(r["counts"]["critical"], 0)

    def test_pendle_tier_mismatch_is_a_separate_finding(self):
        """T2 против T3 — это два РАЗНЫХ потолка концентрации на один капитал."""
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH])
        f = next(x for x in r["findings"] if x["kind"] == "tier_mismatch")
        self.assertEqual(f["adapter_status_tier"], "T2")
        self.assertEqual(f["orchestrator_tier"], "T3")
        self.assertEqual(f["severity"], afd.WARN)

    def test_overall_and_exit_code_on_the_real_snapshot(self):
        r = _run({"pendle": PENDLE_STATUS, "maple": MAPLE_STATUS},
                 [PENDLE_ORCH, MAPLE_ORCH])
        self.assertEqual(r["overall"], afd.WARN)
        self.assertEqual(afd.exit_code(r), 1)
        self.assertEqual(sorted(r["compared_protocols"]), ["maple", "pendle"])

    def test_agreeing_pair_stays_silent(self):
        """Отрицательный контроль: `maple` сходится обеими сторонами ⇒ ни одной находки."""
        r = _run({"maple": MAPLE_STATUS}, [MAPLE_ORCH])
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["overall"], "OK")
        self.assertEqual(afd.exit_code(r), 0)


class TestInvariant2LiveVsLive(unittest.TestCase):
    """Единственный род, который поднимает fail-CLOSED инварианта 2."""

    def test_two_live_readings_that_disagree_are_CRITICAL(self):
        status = dict(MAPLE_STATUS, apy=4.8531, live_apy=4.8531)
        orch = dict(MAPLE_ORCH, apy_pct=9.1, live_data=True)
        r = _run({"maple": status}, [orch])
        f = next(x for x in r["findings"] if x["kind"] == "apy_live_vs_live")
        self.assertEqual(f["severity"], afd.CRITICAL)
        self.assertEqual(f["delta_pp"], 4.2469)
        self.assertEqual(afd.exit_code(r), 2)

    def test_rounding_noise_below_tolerance_is_not_a_finding(self):
        status = dict(MAPLE_STATUS, apy=4.8531, live_apy=4.8531)
        orch = dict(MAPLE_ORCH, apy_pct=4.8535)
        self.assertEqual(_run({"maple": status}, [orch])["findings"], [])

    def test_both_sides_live_tvl_that_disagree_are_CRITICAL(self):
        status = dict(MAPLE_STATUS, tvl_usd=2_770_841_620.0)
        orch = dict(MAPLE_ORCH, tvl_usd=1_000_000_000.0)
        r = _run({"maple": status}, [orch])
        self.assertIn("tvl_live_vs_live", _kinds(r))
        self.assertEqual(afd.exit_code(r), 2)


class TestNoiseControl(unittest.TestCase):
    """Сторож, который каждый день кричит о решённом, обучает себя игнорировать."""

    def test_static_vs_live_tvl_is_INFO_not_a_contradiction(self):
        """6 из 8 протоколов живого замера — ровно этот случай (ADR-053 уже решил)."""
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH])
        f = next(x for x in r["findings"] if x["kind"] == "tvl_provenance")
        self.assertEqual(f["severity"], afd.INFO)
        self.assertNotIn("tvl_live_vs_live", _kinds(r))

    def test_info_alone_keeps_the_verdict_OK(self):
        status = dict(MAPLE_STATUS, tvl_source="static", tvl_usd=2_000_000_000.0)
        r = _run({"maple": status}, [MAPLE_ORCH])
        self.assertEqual(_kinds(r), {"tvl_provenance"})
        self.assertEqual(r["overall"], "OK")
        self.assertEqual(afd.exit_code(r), 0)

    def test_both_literal_is_said_aloud(self):
        """Совпадение двух литералов — «одинаково выдумано», а не согласие измерений."""
        status = dict(PENDLE_STATUS, apy=8.0, live_apy=None)
        orch = dict(PENDLE_ORCH, apy_pct=8.0, live_data=False)
        r = _run({"pendle": status}, [orch])
        self.assertIn("apy_both_literal", _kinds(r))
        self.assertEqual(
            next(x for x in r["findings"] if x["kind"] == "apy_both_literal")["severity"],
            afd.INFO)

    def test_tier_int_and_string_are_the_same_tier(self):
        """`2` и `"T2"` — один тир; без нормализации расхождением была бы каждая пара."""
        r = _run({"maple": MAPLE_STATUS}, [MAPLE_ORCH])
        self.assertNotIn("tier_mismatch", _kinds(r))


class TestFailClosed(unittest.TestCase):
    """Молчаливого «всё в порядке» здесь быть не должно ни в одном исходе."""

    def test_missing_file_is_UNCHECKED_exit_2(self):
        r = _run(None, [PENDLE_ORCH])
        self.assertEqual(r["overall"], afd.UNCHECKED)
        self.assertEqual(afd.exit_code(r), 2)
        self.assertTrue(any("файла нет" in u for u in r["unchecked"]))

    def test_empty_overlap_is_CRITICAL_not_a_clean_pass(self):
        """«Сравнивать было нечего» обязано отличаться от «сравнил и не нашёл»."""
        r = _run({"maple": MAPLE_STATUS}, [dict(PENDLE_ORCH, protocol="something_else")])
        f = next(x for x in r["findings"] if x["kind"] == "no_overlap")
        self.assertEqual(f["severity"], afd.CRITICAL)
        self.assertEqual(afd.exit_code(r), 2)

    def test_snapshot_skew_refuses_to_judge(self):
        """Далеко разнесённые снимки — это два МОМЕНТА, а не два фида (урок #222)."""
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH],
                 ts_orch="2026-08-26T14:47:02+00:00")
        self.assertEqual(r["overall"], afd.UNCHECKED)
        self.assertTrue(any("snapshot_skew" in u for u in r["unchecked"]))
        self.assertEqual(r["findings"], [])
        self.assertEqual(afd.exit_code(r), 2)

    def test_stale_input_refuses_to_judge(self):
        late = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.timezone.utc)
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH], now=late)
        self.assertEqual(r["overall"], afd.UNCHECKED)
        self.assertTrue(any("stale_input" in u for u in r["unchecked"]))

    def test_missing_generated_at_is_said_not_assumed_fresh(self):
        r = _run({"pendle": PENDLE_STATUS}, [PENDLE_ORCH], ts_orch=None)
        self.assertEqual(r["overall"], afd.UNCHECKED)
        self.assertTrue(any("generated_at" in u for u in r["unchecked"]))

    def test_wrong_adapters_shape_is_UNCHECKED(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            with open(os.path.join(data, "adapter_status.json"), "w") as fh:
                json.dump({"generated_at": TS_STATUS, "adapters": ["not", "a", "dict"]}, fh)
            with open(os.path.join(data, "adapter_orchestrator_status.json"), "w") as fh:
                json.dump(_orch_doc([PENDLE_ORCH]), fh)
            r = afd.run(root=tmp, now=NOW, data_dir=data)
        self.assertEqual(r["overall"], afd.UNCHECKED)
        self.assertEqual(afd.exit_code(r), 2)


class TestWiring(unittest.TestCase):
    """Сторож, которого никто не зовёт и не читает, — украшение."""

    def test_report_is_written_atomically_to_its_declared_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            with open(os.path.join(data, "adapter_status.json"), "w") as fh:
                json.dump(_status_doc({"pendle": PENDLE_STATUS}), fh)
            with open(os.path.join(data, "adapter_orchestrator_status.json"), "w") as fh:
                json.dump(_orch_doc([PENDLE_ORCH]), fh)
            afd.run(root=tmp, now=NOW, data_dir=data)
            written = json.load(open(os.path.join(data, "adapter_feed_divergence.json")))
        self.assertEqual(written["overall"], afd.WARN)
        self.assertEqual(written["generated_at"], NOW.isoformat())

    def test_decision_loop_calls_the_guard(self):
        """Проводка мерится в ИСХОДНИКЕ вызывающего, а не в намерении автора."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(afd.__file__)))
        src = open(os.path.join(root, "spa_core", "monitoring", "findings_bridge.py"),
                   encoding="utf-8").read() if os.path.exists(
            os.path.join(root, "spa_core", "monitoring", "findings_bridge.py")) else open(
            os.path.join(os.path.dirname(os.path.abspath(afd.__file__)),
                         "findings_bridge.py"), encoding="utf-8").read()
        self.assertIn("adapter_feed_divergence", src)
        self.assertIn("adapter_feed_divergence.run(", src)

    def test_manifest_declares_the_artifact_with_its_real_producer(self):
        repo = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(afd.__file__))))
        manifest = json.load(open(os.path.join(repo, "architecture", "manifest.json"),
                                  encoding="utf-8"))
        art = next(a for a in manifest["artifacts"]
                   if a["path"] == "data/adapter_feed_divergence.json")
        self.assertEqual(art["status"], "active")
        self.assertIn("orchestrator_protocol", art["consumers"])
        producer = next(a for a in manifest["agents"] if a["label"] == art["producer"])
        self.assertIn("data/adapter_feed_divergence.json",
                      [p["artifact"] for p in producer["produces"]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestExitCodeNeverReadsAbsenceAsSuccess(unittest.TestCase):
    """Инвариант #17 в самом стороже — поймано храповиком в первом же полном прогоне.

    `report.get("counts") or {}` превращал «отчёта нет / отчёт не тот» в ноль находок,
    то есть в код возврата 0 «сошлось». Сторож, придуманный против коэрции отказа,
    содержал коэрцию отказа.
    """

    def test_report_without_counts_is_exit_2_not_0(self):
        self.assertEqual(afd.exit_code({}), 2)
        self.assertEqual(afd.exit_code({"overall": "OK"}), 2)

    def test_counts_of_the_wrong_shape_is_exit_2(self):
        self.assertEqual(afd.exit_code({"counts": None}), 2)
        self.assertEqual(afd.exit_code({"counts": []}), 2)

    def test_a_real_clean_report_is_still_exit_0(self):
        """Обратный контроль: fail-CLOSED не съел нормальный зелёный исход."""
        r = _run({"maple": MAPLE_STATUS}, [MAPLE_ORCH])
        self.assertEqual(afd.exit_code(r), 0)
