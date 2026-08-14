"""Секция Base Chain дневного отчёта — на ЖИВОМ пути (MP-460 / ADR-025 Phase 1).

Наследник `tests/test_daily_paper_report_base.py`, который проверял ту же секцию
в `scripts/daily_paper_report.py`. Тот скрипт списан 14.08 (цикл #227): его
launchd-агент отключён с 21.06 (`com.spa.daily-paper-report.plist.disabled`), ни
один plist/обёртка/CI его не звал, а сам класс отчётов схлопнут в ОДИН дневной
дайджест — это записано в `spa_core/telegram/reports/__init__.py` дословно, и
секция Base перенесена в `daily_telegram_report` («merged from the former
scripts/daily_paper_report.py»).

**Инвариант #16: проверка не ослаблена, а переставлена на живой путь.** Старый
файл проверял мёртвый скрипт (существует · есть секция · `--dry-run` не падает ·
в выводе есть «Base Chain»); те же четыре вопроса заданы здесь коду, который
действительно уезжает владельцу каждое утро (`spa_core/telegram/reports/daily.py`
импортирует ровно эти две функции). Обоснование — в журнале `docs/journal/2026-W33.md`.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.reporting.daily_telegram_report import (
    _BASE_ADAPTERS_REGISTRY,
    _collect_base_chain,
    build_report_data,
    format_daily_message,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


class TestBaseSectionLivesOnTheDeliveredPath(unittest.TestCase):
    """Раньше секция жила в скрипте, которого никто не звал. Теперь — в отчёте."""

    def test_the_retired_duplicate_is_gone(self):
        """Списанный дубль не должен вернуться: два утренних отчёта = два отчёта."""
        self.assertFalse(
            (_REPO_ROOT / "scripts" / "daily_paper_report.py").exists(),
            "scripts/daily_paper_report.py списан (цикл #227) — если он вернулся, "
            "вернулась и вторая утренняя рассылка с якорем трека 2026-06-12",
        )

    def test_the_live_digest_imports_the_merged_builders(self):
        """Проводка названа явно: дайджест владельца берёт ИМЕННО эти функции."""
        src = (_REPO_ROOT / "spa_core" / "telegram" / "reports" / "daily.py").read_text(
            encoding="utf-8")
        self.assertIn("from spa_core.reporting.daily_telegram_report import", src)
        self.assertIn("build_report_data", src)
        self.assertIn("format_daily_message", src)

    def test_registry_is_not_empty(self):
        """Реестр Base-адаптеров — то, из чего секция вообще складывается."""
        self.assertTrue(_BASE_ADAPTERS_REGISTRY, "реестр Base-адаптеров пуст")
        for adapter_id, meta in _BASE_ADAPTERS_REGISTRY.items():
            self.assertIn("tier", meta, adapter_id)
            self.assertIn("label", meta, adapter_id)
            self.assertIn("suspended", meta, adapter_id)


class TestItDoesNotCrashAndItPrintsTheSection(unittest.TestCase):
    """Прямые наследники `--dry-run`-проверок списанного скрипта."""

    def test_collect_degrades_instead_of_raising(self):
        """Отчёт не имеет права падать из-за отсутствующих данных."""
        out = _collect_base_chain(None, _REPO_ROOT / "data")
        self.assertIsInstance(out, dict)
        self.assertIn("gas", out)

    def test_message_contains_the_base_chain_section(self):
        """В отрисованном сообщении секция обязана быть — как в `--dry-run` раньше."""
        data = build_report_data(data_dir=_REPO_ROOT / "data")
        self.assertIn("base_chain", data)
        message = format_daily_message(data)
        self.assertIn("Base Chain", message)

    def test_suspended_adapter_is_labelled_not_priced(self):
        """SUSPENDED-адаптер не имеет права принести в отчёт доходность."""
        rows = _collect_base_chain({"adapters": {}}, _REPO_ROOT / "data")["adapters"]
        by_label = {r["label"]: r for r in rows}
        for meta in _BASE_ADAPTERS_REGISTRY.values():
            if meta["suspended"]:
                row = by_label.get(meta["label"])
                self.assertIsNotNone(row, meta["label"])
                self.assertTrue(row.get("suspended"))
                self.assertNotIn("apy", row)


class TestLiveAdapterStatus(unittest.TestCase):
    """Наследник `test_adapter_status_has_base` — данные, а не код."""

    def test_adapter_status_has_a_base_adapter(self):
        status_path = _REPO_ROOT / "data" / "adapter_status.json"
        if not status_path.exists():
            self.skipTest("data/adapter_status.json нет (чистый чекаут)")
        doc = json.loads(status_path.read_text(encoding="utf-8"))
        pool = doc.get("adapters") if isinstance(doc.get("adapters"), dict) else {}
        space = {**doc, **(pool or {})}
        base_items = [k for k, v in space.items()
                      if isinstance(v, dict) and v.get("chain") == "base"]
        self.assertGreater(len(base_items), 0,
                           "в adapter_status.json нет ни одного адаптера chain=base")


if __name__ == "__main__":
    unittest.main(verbosity=2)
