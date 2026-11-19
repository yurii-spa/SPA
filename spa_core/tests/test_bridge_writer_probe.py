# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — якорь `_ANCHOR` ниже передаётся пробе входом
# `now=`, а ОБЕ отметки сцен выводятся из того же якоря (`_ANCHOR - timedelta`).
# Закреплены обе стороны сравнения, поэтому вердикт не зависит от календаря
# прогона (`.claude/rules/deployment.md`, § «Время в тестах», приём №1).
"""Контроль пробы `findings_bridge_has_a_live_writer` (ADR-1061).

Проба объявлена критерием карточки `inbox-most-nahodok-decision-loop-ne-ukladyvaet`
и обязана мерить ИСХОД: есть ли у моста находок живой писатель. Регистрировать
пробу без контроля в ОБЕ стороны запрещено (`.claude/rules/acceptance.md`, п. 3):
зелёная на целом контуре, красная на КАЖДОМ порванном звене — с НАЗВАННЫМ звеном.

Порванные звенья, каждое своей сценой: горизонт не объявлен (четыре РАЗНЫХ
состояния объявления) · отчёта нет · отчёт не разобран · отчёт без `generated_at` ·
отметка не разобрана · форма отчёта не словарь.

И отдельно — проба НЕ проходит подстрокой (ADR-333): документ, который лишь
СОДЕРЖИТ слова про свежесть, вердикта не покупает.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

#: Якорь сцены. Ни один вердикт ниже не зависит от календаря прогона: он уезжает
#: пробе входом `now=`, и из него же считаются ОТМЕТКИ отчётов.
_ANCHOR = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)

_REL = os.path.join("data", "findings_bridge_report.json")
#: Тот же горизонт, что объявлен артефакту в боевом манифесте. Сцена ОБЪЯВЛЯЕТ
#: его сама, а не читает боевое дерево: предмет здесь — проводка пробы, и
#: подглядывание в боевой манифест сделало бы тест зависимым от хоста.
_SLO_H = 9.28


class _Tree:
    """Одноразовое дерево: свой манифест и свой отчёт — обе двери под контролем."""

    def __init__(self, tmp: str):
        self.root = Path(tmp)
        (self.root / "architecture").mkdir(parents=True, exist_ok=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)

    def manifest(self, entry: dict | None, *, present: bool = True) -> None:
        if not present:
            return
        artifacts = [] if entry is None else [entry]
        (self.root / "architecture" / "manifest.json").write_text(
            json.dumps({"artifacts": artifacts}), encoding="utf-8")

    def declared_slo(self, hours=_SLO_H) -> None:
        entry = {"path": _REL, "producer": "com.spa.decision_loop"}
        if hours is not None:
            entry["slo_hours"] = hours
        self.manifest(entry)

    def report(self, text: str) -> None:
        (self.root / _REL).write_text(text, encoding="utf-8")

    def report_aged(self, hours: float) -> None:
        stamp = (_ANCHOR - timedelta(hours=hours)).isoformat()
        self.report(json.dumps({"generated_at": stamp, "created": [], "closed": []}))

    def ask(self) -> tuple[str, str]:
        saved = ca.REPO_ROOT
        try:
            ca.REPO_ROOT = str(self.root)
            return ca.PROBES["findings_bridge_has_a_live_writer"](None, now=_ANCHOR)
        finally:
            ca.REPO_ROOT = saved


class TheWholeContourIsGreen(unittest.TestCase):

    def test_a_report_inside_the_declared_horizon_satisfies(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report_aged(_SLO_H - 1.0)
            status, why = t.ask()
        self.assertEqual(status, ca.SATISFIED, why)
        self.assertIn("ЖИВ", why)
        # Оба числа названы: иначе «свежо» нечем поверить.
        self.assertIn("9.28", why)


class EachBrokenLinkIsRedAndNamed(unittest.TestCase):

    def test_a_report_older_than_the_horizon_is_the_cards_subject(self):
        """Звено: писателя НЕТ. Это `not_satisfied`, а не «не измерено»."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report_aged(497.8)
            status, why = t.ask()
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("НЕТ ПИСАТЕЛЯ", why)
        self.assertIn("497.8", why)

    def test_no_manifest_at_all_is_unmeasured(self):
        """Звено: реестра нет — сравнивать возраст НЕ С ЧЕМ."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.manifest(None, present=False)
            t.report_aged(1.0)
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("НЕ ОБЪЯВЛЕН", why)

    def test_artifact_absent_from_the_registry_is_unmeasured(self):
        """Звено: строки артефакта в реестре нет ни одной."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.manifest({"path": "data/other.json", "slo_hours": 5})
            t.report_aged(1.0)
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("НЕ ОБЪЯВЛЕН", why)

    def test_entry_without_slo_hours_is_unmeasured(self):
        """Звено: строка есть, срока в ней нет. НЕ ноль и НЕ умолчание."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo(hours=None)
            t.report_aged(1.0)
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("НЕ ОБЪЯВЛЕН", why)

    def test_a_nonpositive_slo_is_unmeasured_not_an_instant_failure(self):
        """Звено: срок есть, но срока 0ч не бывает — иначе всё было бы просрочено."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo(hours=0)
            t.report_aged(0.1)
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("НЕ ОБЪЯВЛЕН", why)

    def test_a_missing_report_is_unmeasured_not_no_writer(self):
        """Звено: отчёта нет. Отсутствие файла НЕ свидетельство об отсутствии писателя."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("замера НЕ БЫЛО", why)

    def test_an_unparsable_report_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report("{не json")
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("не разобран", why)

    def test_a_report_without_generated_at_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report(json.dumps({"created": [], "closed": []}))
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("generated_at", why)

    def test_an_unparsable_stamp_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report(json.dumps({"generated_at": "вчера вечером"}))
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("не разобран", why)

    def test_a_report_that_is_not_a_dict_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report(json.dumps(["generated_at"]))
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("форма", why)


class TheProbeDoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: вердикт стои́т на ИЗМЕРЕННОМ возрасте, а не на словах в документе."""

    def test_words_about_freshness_buy_no_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo()
            t.report(json.dumps({
                "note": "writer alive, fresh, свежий, ЖИВ, 9.28ч, satisfied",
                "status": "OK",
            }))
            status, why = t.ask()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("generated_at", why)

    def test_the_horizon_is_not_a_literal_of_this_probe(self):
        """Горизонт берётся ДВЕРЬЮ манифеста, а не константой пробы.

        Обратная половина: сдвинь объявление — сдвинется и вердикт. Иначе проба
        несла бы ВТОРУЮ копию правила свежести, и один файл считался бы
        просроченным по одной мерке и свежим по другой.
        """
        with tempfile.TemporaryDirectory() as tmp:
            t = _Tree(tmp)
            t.declared_slo(hours=1000.0)
            t.report_aged(497.8)        # старше 9.28ч, но внутри 1000ч
            status, why = t.ask()
        self.assertEqual(status, ca.SATISFIED, why)
        self.assertIn("1000", why)


if __name__ == "__main__":
    unittest.main()
