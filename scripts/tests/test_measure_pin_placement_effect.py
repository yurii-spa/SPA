#!/usr/bin/env python3
"""Сторож замера «сколько кэша размещает пин» (`scripts/measure_pin_placement_effect.py`).

КАЖДЫЙ тест здесь — положительный контроль: воспроизводит поломку, которая уже
случилась, и краснеет, если инструмент перестанет её ловить. Проверка, никогда не
видевшая настоящей аварии, — украшение (`.claude/rules/deployment.md`).

Разобранные аварии:
  * 05.09 17:44Z — `yields.llama.fi/pools` отдал HTTP 200 с телом `GET,HEAD`
    (8 байт). Записать это нулём значило бы отчитаться «пин ничего не размещает»,
    не измерив ничего. Цикл #494 из-за этого не смог исполнить шаг (3).
  * цикл #495 — первый прогон замера СОВРАЛ: `_adapter_class_gate()` создаёт
    настоящий адаптер, тот без `SPA_DATA_DIR` читает `data/` СВОЕГО дерева
    (в worktree — замороженный канон origin), и вердикт `gsm_not_confirmed`
    приехал из ЧУЖОГО снимка, а не из измеряемого. Класс описан в
    `spa_core/utils/data_dir.py`.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import measure_pin_placement_effect as mppe  # noqa: E402

EXIT_UNMEASURED = mppe.EXIT_UNMEASURED
Unmeasured = mppe.Unmeasured
load_feed = mppe.load_feed
main = mppe.main
measure = mppe.measure


class TestFeedIsNeverSilentlyZero(unittest.TestCase):
    """Фид не ответил ⇒ третий исход, а НЕ «нулевой эффект»."""

    def test_garbage_body_of_the_2026_09_05_outage_is_unmeasured(self):
        # Дословное тело аварии: HTTP 200, content-type json, тело `GET,HEAD`.
        path = Path(self.enterContext(_tmpdir())) / "feed.json"
        path.write_text(json.dumps("GET,HEAD"), encoding="utf-8")
        with self.assertRaises(Unmeasured) as ctx:
            load_feed(path)
        self.assertIn("НЕ «нулевой эффект пина»", str(ctx.exception))

    def test_empty_pool_list_is_unmeasured_not_zero(self):
        path = Path(self.enterContext(_tmpdir())) / "feed.json"
        path.write_text(json.dumps({"data": []}), encoding="utf-8")
        with self.assertRaises(Unmeasured):
            load_feed(path)

    def test_fetcher_returning_none_is_unmeasured(self):
        # Ровно то, что отдаёт _fetch_defillama при любой сетевой ошибке.
        with self.assertRaises(Unmeasured):
            load_feed(None, fetcher=lambda: None)

    def test_cli_exits_2_and_says_why(self):
        path = Path(self.enterContext(_tmpdir())) / "feed.json"
        path.write_text(json.dumps("GET,HEAD"), encoding="utf-8")
        rc = main(["--pin", "spark_susds", "--feed", str(path), "--json"])
        self.assertEqual(rc, EXIT_UNMEASURED)

    def test_a_healthy_feed_is_not_refused(self):
        """Обратный контроль: починка не должна начать звонить на верном входе."""
        path = Path(self.enterContext(_tmpdir())) / "feed.json"
        path.write_text(json.dumps({"data": [{"pool": "x"}]}), encoding="utf-8")
        self.assertEqual(load_feed(path), [{"pool": "x"}])


class TestUnmeasuredIsNeverADifference(unittest.TestCase):
    """«Сравнивать нечего» не имеет права выглядеть как «разницы нет»."""

    def test_unpinned_key_refuses_instead_of_reporting_zero(self):
        tmp = Path(self.enterContext(_tmpdir()))
        with self.assertRaises(Unmeasured) as ctx:
            measure(
                pin_key="ключ-которого-нет",
                source_data_dir=tmp / "src",
                sandbox_root=tmp / "sbx",
                pools=[{"pool": "x"}],
            )
        self.assertIn("не запинён", str(ctx.exception))

    def test_sandbox_inside_the_source_is_refused(self):
        """Песочница внутри источника писала бы в живое состояние (правило §4)."""
        tmp = Path(self.enterContext(_tmpdir()))
        src = tmp / "data"
        src.mkdir()
        with self.assertRaises(Unmeasured) as ctx:
            measure(
                pin_key="spark_susds",
                source_data_dir=src,
                sandbox_root=src / "sbx",
                pools=[{"pool": "x"}],
            )
        self.assertIn("живое состояние", str(ctx.exception))


class TestEveryReaderSeesTheSameSnapshot(unittest.TestCase):
    """Замер, часть читателей которого смотрит в ДРУГОЕ дерево, врёт (#495)."""

    def test_arm_pins_SPA_DATA_DIR_to_its_own_sandbox(self):
        """Проводка проверяется ФОРМОЙ: рука обязана выставить SPA_DATA_DIR.

        Без этой строки `_adapter_class_gate()` судит по `data/` своего дерева, и
        замер отвечает на вопрос о чужом снимке. Мутация — снять строку — обязана
        краснить, поэтому смотрим на исходник самой руки, а не на её результат:
        поймать это через результат можно только на машине, где два дерева
        расходятся, то есть не на CI.
        """
        src = Path(_REPO_ROOT / "scripts" / "measure_pin_placement_effect.py").read_text(
            encoding="utf-8"
        )
        run_arm = src.split("def _run_arm(")[1].split("\ndef ")[0]
        self.assertIn('os.environ["SPA_DATA_DIR"] = str(ddir)', run_arm)

    def test_arm_restores_the_ambient_env_afterwards(self):
        """Замер не имеет права оставить SPA_DATA_DIR за собой: следующий
        потребитель в том же процессе начал бы читать чужую песочницу."""
        src = Path(_REPO_ROOT / "scripts" / "measure_pin_placement_effect.py").read_text(
            encoding="utf-8"
        )
        run_arm = src.split("def _run_arm(")[1].split("\ndef ")[0]
        self.assertIn('os.environ.pop("SPA_DATA_DIR", None)', run_arm)
        self.assertIn("finally:", run_arm)

    def test_pin_table_is_restored_so_arms_cannot_leak_into_each_other(self):
        """Рука B удаляет пин из общей таблицы модуля. Не вернув его, следующий
        прогон в том же процессе мерил бы «без пина» против «без пина».

        Тест обязан ДОЙТИ до удаления: первая редакция этого контроля падала на
        отсутствующем источнике, то есть ДО `pop`, и оставалась зелёной, когда
        восстановление снимали (мутация M3 цикла #495). Поэтому источник здесь
        настоящий, `drop_pin` задан явно, а прогон ломается ПОСЛЕ удаления —
        на отсутствующем снимке оркестратора.
        """
        import spa_core.monitoring.adapter_status_generator as gen

        before = dict(gen._POOL_ID_LOOKUP)
        self.assertIn("spark_susds", before, "предпосылка теста: ключ запинён")

        tmp = Path(self.enterContext(_tmpdir()))
        src = tmp / "data"
        src.mkdir()
        # Достаточно, чтобы copytree и generate() прошли, а аллокатор — нет.
        (src / "adapter_registry.json").write_text(
            json.dumps({"adapters": {}}), encoding="utf-8"
        )
        with self.assertRaises(BaseException):
            mppe._run_arm(
                arm_name="without_pin",
                drop_pin="spark_susds",
                pools=[{"pool": "x", "project": "p", "chain": "Ethereum",
                        "symbol": "USDC", "tvlUsd": 1.0, "apy": 1.0}],
                source_data_dir=src,
                sandbox_root=tmp / "sbx",
                capital_usd=100_000.0,
            )
        self.assertEqual(
            gen._POOL_ID_LOOKUP, before,
            "таблица пинов не восстановлена — следующая рука мерила бы "
            "«без пина» против «без пина»",
        )


class TestMissingSourceIsRefusedLoudly(unittest.TestCase):
    def test_absent_source_data_dir_is_unmeasured(self):
        tmp = Path(self.enterContext(_tmpdir()))
        with self.assertRaises(Unmeasured) as ctx:
            measure(
                pin_key="spark_susds",
                source_data_dir=tmp / "нет-такого-каталога",
                sandbox_root=tmp / "sbx",
                pools=[{"pool": "x"}],
            )
        self.assertIn("песочница", str(ctx.exception))


class TestGateVisibilityIsWiredAtBirth(unittest.TestCase):
    """Дешёвый вопрос «пин вообще способен повлиять на финансирование?» обязан
    ЗВУЧАТЬ каждый цикл, иначе он повторит судьбу канала ADR-167: построен,
    покрыт тестами и не спрошен никем (ADR-235). Проводка — в обязательный
    шаг 0-офис.
    """

    def test_office_step_calls_the_check(self):
        src = (_REPO_ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("measure_pin_placement_effect", src)
        self.assertIn("pins_invisible_to_the_gate", src)
        self.assertIn("gate_visibility_report_lines", src)

    def test_absent_orchestrator_snapshot_is_unmeasured_not_empty(self):
        """Третий исход: «спрашивать нечем» ≠ «невидимых пинов нет»."""
        tmp = Path(self.enterContext(_tmpdir()))
        out = mppe.pins_invisible_to_the_gate(tmp)
        self.assertTrue(out["unmeasured"], "нечитаемый снимок объявлен чистым")
        self.assertEqual(out["invisible"], [])
        line = " ".join(mppe.gate_visibility_report_lines(out))
        self.assertIn("НЕ ИЗМЕРЕНО", line)

    def test_empty_orchestrator_snapshot_is_unmeasured_not_all_invisible(self):
        """Пустой снимок объявил бы КАЖДЫЙ пин невидимым — ложная тревога
        на сломанном производителе, а не находка."""
        tmp = Path(self.enterContext(_tmpdir()))
        (tmp / "adapter_orchestrator_status.json").write_text(
            json.dumps({"adapters": []}), encoding="utf-8"
        )
        out = mppe.pins_invisible_to_the_gate(tmp)
        self.assertTrue(out["unmeasured"])
        self.assertEqual(out["invisible"], [])

    def test_a_pinned_key_present_in_the_snapshot_is_not_reported(self):
        """Обратный контроль: сторож не звонит на верном состоянии."""
        import spa_core.monitoring.adapter_status_generator as gen

        tmp = Path(self.enterContext(_tmpdir()))
        (tmp / "adapter_orchestrator_status.json").write_text(
            json.dumps({"adapters": [{"protocol": k} for k in gen._POOL_ID_LOOKUP]}),
            encoding="utf-8",
        )
        out = mppe.pins_invisible_to_the_gate(tmp)
        self.assertIsNone(out["unmeasured"])
        self.assertEqual(out["invisible"], [])
        self.assertIn("✅", " ".join(mppe.gate_visibility_report_lines(out)))

    def test_the_2026_09_05_finding_is_reproduced(self):
        """Положительный контроль: spark_susds запинён и НЕ опрашивается."""
        import spa_core.monitoring.adapter_status_generator as gen

        tmp = Path(self.enterContext(_tmpdir()))
        (tmp / "adapter_orchestrator_status.json").write_text(
            json.dumps({"adapters": [{"protocol": "aave_v3"}, {"protocol": "maple"}]}),
            encoding="utf-8",
        )
        out = mppe.pins_invisible_to_the_gate(tmp)
        self.assertIn("spark_susds", out["invisible"])
        self.assertIn("spark_susds", " ".join(mppe.gate_visibility_report_lines(out)))
        self.assertIn("spark_susds", gen._POOL_ID_LOOKUP)


def _tmpdir():
    import tempfile

    return tempfile.TemporaryDirectory()


if __name__ == "__main__":
    unittest.main()
