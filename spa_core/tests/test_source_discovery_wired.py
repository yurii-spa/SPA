"""Поиск источников доходности получил расписание И читателя — вариант A (ADR-142).

Карточка «Ручной инструмент поиска новых источников доходности никто не
запускает», решение владельца 2026-08-25.

Замер карточки: инструмент `scripts/find_defillama_sources.py` **рабочий и
покрыт 30 тестами**, но запускать его было некому — ни агента, ни шага цикла, —
а результат (`data/source_discovery.json`) **не читал НИКТО**. Единственный
документированный «потребитель» сам никем не вызывался.

Почему нельзя было просто повесить его шагом цикла: тогда мы завели бы файл,
который никто не читает — ровно то, что ловит наш же сторож соответствия
(ADR-066). Поэтому вариант A состоит из ДВУХ половин, и обе проверяются здесь:
**расписание** и **настоящий читатель**.

Установка агента — за владельцем (инв. #12).
"""
from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLIST = REPO / "launchd" / "com.spa.source_discovery.plist"
WRAPPER = REPO / "scripts" / "agent_source_discovery.sh"
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются ПАРОЙ
# с отметками: `now=NOW` уходит входом, а возраст файла ставится относительно
# того же NOW. Обе стороны закреплены, поэтому сдвиг календаря тест не трогает.


def _briefing():
    spec = importlib.util.spec_from_file_location(
        "update_system_briefing", REPO / "scripts" / "update_system_briefing.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TheFileFinallyHasAReader(unittest.TestCase):
    """Первая половина решения — и главная: у находок появился читатель."""

    def setUp(self):
        self.b = _briefing()

    def _doc(self, age_days: float, found=(("aave", 3), ("pendle", 1))):
        gen = (NOW - timedelta(days=age_days)).isoformat()
        return {
            "generated_at": gen,
            "summary": {n: {"found": c, "top_pool_id": f"{n}-pool"} for n, c in found},
        }

    def test_the_briefing_assembles_the_section(self):
        import inspect
        src = inspect.getsource(self.b.main)
        self.assertIn("build_source_discovery_section", src,
                      "раздел написан, но в сводку не попадает — файл снова без читателя")

    def test_fresh_findings_are_rendered_with_the_numbers(self):
        st = self.b.source_discovery_state(self._doc(1.0), now=NOW)
        self.assertEqual(st["state"], "fresh")
        self.assertEqual(st["found_total"], 4)
        self.assertEqual([p["name"] for p in st["protocols"]], ["aave", "pendle"])

    def test_missing_file_is_not_zero_candidates(self):
        """Инв. #17: «файла нет» ≠ «кандидатов не нашлось»."""
        st = self.b.source_discovery_state({}, now=NOW)
        self.assertEqual(st["state"], "missing")
        self.assertIsNone(st["found_total"])

    def test_stale_findings_are_named_with_the_age(self):
        st = self.b.source_discovery_state(self._doc(30.0), now=NOW)
        self.assertEqual(st["state"], "stale")
        self.assertAlmostEqual(st["age_days"], 30.0, places=1)

    def test_file_without_a_timestamp_is_unchecked_not_fresh(self):
        st = self.b.source_discovery_state(
            {"summary": {"aave": {"found": 1}}}, now=NOW)
        self.assertEqual(st["state"], "unchecked")

    def test_threshold_lets_one_missed_week_pass_and_catches_silence(self):
        self.assertEqual(self.b.source_discovery_state(self._doc(7.5), now=NOW)["state"],
                         "fresh")
        self.assertEqual(self.b.source_discovery_state(self._doc(9.0), now=NOW)["state"],
                         "stale")

    def test_section_text_says_missing_out_loud(self):
        rendered = self.b.source_discovery_state({}, now=NOW)
        self.assertEqual(rendered["state"], "missing")
        text = self.b.build_source_discovery_section()
        self.assertIn("Кандидаты в источники доходности", text)

    def test_section_never_raises_on_junk(self):
        for junk in (None, [], "text", {"summary": "not-a-dict"}):
            with self.subTest(junk=junk):
                st = self.b.source_discovery_state(junk, now=NOW)
                self.assertIn(st["state"], {"missing", "unchecked", "fresh", "stale"})


class TheScheduleIsPrepared(unittest.TestCase):
    """Вторая половина — расписание. Агент ПОДГОТОВЛЕН, не установлен."""

    def _plist(self):
        with PLIST.open("rb") as fh:
            return plistlib.load(fh)

    def test_weekly(self):
        self.assertEqual(self._plist()["StartInterval"], 604800)

    def test_launchd_runs_bash_not_python(self):
        args = self._plist()["ProgramArguments"]
        self.assertEqual(args[0], "/bin/bash")
        self.assertNotIn("miniconda", " ".join(args))

    def test_wrapper_is_executable_in_git(self):
        out = subprocess.run(
            ["git", "ls-files", "-s", "scripts/agent_source_discovery.sh"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.startswith("100755"), out)

    def test_logs_go_to_tmp(self):
        p = self._plist()
        for key in ("StandardOutPath", "StandardErrorPath"):
            with self.subTest(key=key):
                self.assertTrue(p[key].startswith("/tmp/"))

    def test_wrapper_targets_the_real_tool_with_save(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("find_defillama_sources.py", text)
        self.assertIn("--save", text,
                      "без --save инструмент ничего не запишет, и читателю нечего читать")

    def test_the_tool_it_names_exists(self):
        self.assertTrue((REPO / "scripts" / "find_defillama_sources.py").is_file())

    def test_it_is_not_a_long_liver(self):
        self.assertFalse(bool(self._plist().get("KeepAlive", False)))


class ManifestKnowsTheProducerAndDemandsAConsumer(unittest.TestCase):
    """Артефакт с читателем обязан быть объявлен как такой."""

    def test_entry_exists_and_requires_a_consumer(self):
        import json
        d = json.loads((REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next((a for a in d["agents"] if a["label"] == "com.spa.source_discovery"), None)
        self.assertIsNotNone(entry, "агент не объявлен в манифесте")
        self.assertTrue(entry["consumer_required"],
                        "артефакт объявлен без требования читателя — исходный дефект")
        self.assertEqual(entry["produces"][0]["artifact"], "data/source_discovery.json")


if __name__ == "__main__":
    unittest.main()
