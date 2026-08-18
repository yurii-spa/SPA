"""Реестр кандидатов: «не смотрели» отделено от «кандидатов ноль» (цикл #283).

Пятая прядь одной ниточки. #276 отделил «не измерено» от нуля у активных
адаптеров, #277 — у множества покрытия. У САМИХ КАНДИДАТОВ отличия не было:
`_load_candidates` отдавал `[]` и при отсутствующем файле, и при пустом
реестре, а `run_alpha_scan` печатал `"candidates": []` — читатель обязан был
прочесть это как «посмотрели, ничего достойного не нашли».

Измерено 2026-08-18 на живом проде: `data/candidate_registry.json` не
существует вовсе (discovery запускают руками), то есть верное чтение
артефакта — «мы не смотрели НИ РАЗУ», и отличить его было нечем.

Каждый тест ниже — положительный контроль: на коде до починки он краснеет,
потому что `candidate_set` там нет вовсе, а `candidates_measured` не пишется.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.agents.alpha_agent import _load_candidates, candidate_set, run_alpha_scan


class TestCandidateSetHonesty(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ddir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, payload) -> None:
        (self.ddir / "candidate_registry.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    # ── «не смотрели» ────────────────────────────────────────────────────────

    def test_missing_file_is_not_measured(self):
        res = candidate_set(self.ddir)
        self.assertFalse(res["measured"])
        self.assertEqual(res["items"], [])
        self.assertIn("не найден", res["reason"])

    def test_unreadable_file_is_not_measured(self):
        (self.ddir / "candidate_registry.json").write_text("{не json", encoding="utf-8")
        res = candidate_set(self.ddir)
        self.assertFalse(res["measured"])
        self.assertIn("нечитаем", res["reason"])

    def test_wrong_shape_is_not_measured(self):
        self._write("строка вместо объекта")
        res = candidate_set(self.ddir)
        self.assertFalse(res["measured"])
        self.assertIn("не объект", res["reason"])

    def test_missing_key_is_not_measured(self):
        self._write({"generated_at": "…"})
        res = candidate_set(self.ddir)
        self.assertFalse(res["measured"])
        self.assertIn("нет ключа candidates", res["reason"])

    def test_candidates_not_a_list_is_not_measured(self):
        self._write({"candidates": {"aave": 1}})
        res = candidate_set(self.ddir)
        self.assertFalse(res["measured"])
        self.assertIn("не список", res["reason"])

    # ── измеренный ноль — ДРУГОЕ состояние ───────────────────────────────────

    def test_present_but_empty_registry_is_a_measured_zero(self):
        self._write({"candidates": []})
        res = candidate_set(self.ddir)
        self.assertTrue(res["measured"], "прочитанный пустой реестр — измеренный ноль")
        self.assertEqual(res["items"], [])
        self.assertEqual(res["reason"], "")

    def test_measured_candidates_are_returned(self):
        self._write({"candidates": [{"protocol": "gearbox_v4"}, "мусор", {"protocol": "x"}]})
        res = candidate_set(self.ddir)
        self.assertTrue(res["measured"])
        self.assertEqual([c["protocol"] for c in res["items"]], ["gearbox_v4", "x"])

    def test_bare_list_registry_is_measured(self):
        self._write([{"protocol": "gearbox_v4"}])
        res = candidate_set(self.ddir)
        self.assertTrue(res["measured"])
        self.assertEqual(len(res["items"]), 1)

    # ── совместимая обёртка ──────────────────────────────────────────────────

    def test_legacy_loader_still_returns_a_plain_list(self):
        self._write({"candidates": [{"protocol": "gearbox_v4"}]})
        self.assertEqual(_load_candidates(self.ddir), [{"protocol": "gearbox_v4"}])
        # и по-прежнему НЕ различает два состояния — потому и обёртка
        missing = Path(tempfile.mkdtemp())
        self.assertEqual(_load_candidates(missing), [])


class TestScanArtifactNamesTheHonesty(unittest.TestCase):
    """Артефакт обязан СКАЗАТЬ, смотрели ли мы вообще."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ddir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_registry_is_named_in_the_artifact(self):
        doc = run_alpha_scan(self.ddir)
        self.assertEqual(doc["candidates"], [])
        self.assertFalse(
            doc["candidates_measured"],
            "пустой список без этого поля читается как «искали и не нашли»",
        )
        self.assertIn("не найден", doc["candidates_reason"])

    def test_measured_zero_is_named_differently(self):
        (self.ddir / "candidate_registry.json").write_text(
            json.dumps({"candidates": []}), encoding="utf-8"
        )
        doc = run_alpha_scan(self.ddir)
        self.assertEqual(doc["candidates"], [])
        self.assertTrue(doc["candidates_measured"])
        self.assertEqual(doc["candidates_reason"], "")

    def test_written_file_carries_the_same_verdict(self):
        run_alpha_scan(self.ddir)
        doc = json.loads((self.ddir / "alpha_candidates.json").read_text(encoding="utf-8"))
        self.assertFalse(doc["candidates_measured"])
        self.assertIn("не найден", doc["candidates_reason"])


if __name__ == "__main__":
    unittest.main()
