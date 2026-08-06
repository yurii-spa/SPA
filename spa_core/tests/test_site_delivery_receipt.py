"""Доставка на сайт обязана оставлять след — иначе сторож отвечает не на тот вопрос.

Сторож соответствия (ADR-066) умеет спрашивать «продукт кто-то прочитал?» и «продукт
свежий?». Для сайта нужен третий вопрос — «продукт ДОШЁЛ до публики?».

Разница не теоретическая. 2026-08-06 замерено: `landing/src/data/track_snapshot.json`
имел возраст **23.1 часа при SLO 26** — то есть проходил проверку свежести и выглядел
здоровым по всем метрикам. При этом он **не был доставлен**: цикл пересобирал его
ежедневно, никто не пушил, и публичный сайт месяцами показывал вчерашние числа.
Проверка свежести измеряет момент СБОРКИ, а не момент публикации.

Ресит доставки закрывает именно этот разрыв, и пишется он ровно там, где доставка
происходит — в `safe_site_push`, единственном санкционированном пути для `landing/**`.

Обе стороны здесь одинаково важны. Ресит, записанный при НЕУДАЧНОМ пуше, страшнее
отсутствующего: он говорит «доставлено» о том, что не уехало, и сторож начинает
успокаивать вместо того, чтобы предупреждать.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import importlib.util

_REPO = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "safe_site_push", str(_REPO / "scripts" / "safe_site_push.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDeliveryReceipt(unittest.TestCase):

    def setUp(self):
        self.mod = _load_module()

    def _run_push(self, returncode: int, files: list):
        """Прогоняет путь доставки, подменив и гейт, и сам пуш."""
        written = []

        def _fake_receipt(artifact, consumer, root=None):
            written.append((artifact, consumer))

        with mock.patch.object(self.mod, "_run_guard", return_value=(0, {})), \
             mock.patch.object(self.mod.subprocess, "run",
                               return_value=mock.Mock(returncode=returncode)), \
             mock.patch.dict("sys.modules", {}):
            with mock.patch("spa_core.monitoring.consumption_receipts.write_receipt",
                            _fake_receipt):
                rc = self.mod.main(["--files", *files, "--message", "тест"])
        return rc, written

    def test_successful_delivery_writes_a_receipt(self):
        """Пуш прошёл ⇒ след остался, и сторож увидит «доставлено»."""
        rc, written = self._run_push(0, [str(_REPO / "landing" / "src" / "data" / "x.json")])
        self.assertEqual(rc, 0)
        self.assertTrue(any(a.startswith("landing/") and c == "site_delivery"
                            for a, c in written),
                        "успешная доставка обязана оставить ресит")

    def test_failed_push_writes_NO_receipt(self):
        """Сторона, где ошибка дороже: ресит после неудачи заставит сторожа успокаивать.

        «Доставлено» о том, что не уехало, хуже, чем отсутствие записи вовсе.
        """
        rc, written = self._run_push(1, [str(_REPO / "landing" / "src" / "data" / "x.json")])
        self.assertNotEqual(rc, 0)
        self.assertEqual(written, [], "после неудачного пуша ресита быть не должно")

    def test_non_site_files_do_not_get_a_site_receipt(self):
        """Ресит доставки — про публикацию, а не про любой успешный пуш."""
        rc, written = self._run_push(0, [str(_REPO / "spa_core" / "risk" / "policy.py")])
        self.assertEqual(rc, 0)
        self.assertEqual(written, [])

    def test_receipt_failure_does_not_undo_the_delivery(self):
        """Учёт не важнее доставки: пуш уже состоялся, код возврата не портим."""
        def _boom(*a, **k):
            raise RuntimeError("реситы недоступны")

        with mock.patch.object(self.mod, "_run_guard", return_value=(0, {})), \
             mock.patch.object(self.mod.subprocess, "run",
                               return_value=mock.Mock(returncode=0)):
            with mock.patch("spa_core.monitoring.consumption_receipts.write_receipt", _boom):
                rc = self.mod.main(["--files",
                                    str(_REPO / "landing" / "src" / "data" / "x.json"),
                                    "--message", "тест"])
        self.assertEqual(rc, 0)


class TestReceiptIsReadableByTheWatchdog(unittest.TestCase):
    """Формат ресита должен читаться тем самым сторожем, ради которого он пишется."""

    def test_watchdog_parses_what_we_write(self):
        from spa_core.monitoring.architecture_conformance import load_receipts

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "consumption_receipts.jsonl"
            path.write_text(json.dumps({
                "artifact": "landing/src/data/track_snapshot.json",
                "consumer": "site_delivery",
                "consumed_at": "2026-08-06T08:20:31Z",
            }) + "\n", encoding="utf-8")
            latest = load_receipts(str(path))
        self.assertIn("landing/src/data/track_snapshot.json", latest,
                      "сторож обязан видеть наш ресит — иначе он бесполезен")


if __name__ == "__main__":
    unittest.main()
