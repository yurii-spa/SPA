"""Контроли на перепись власти пина (ADR-520).

Каждый тест воспроизводит НАСТОЯЩЕЕ состояние живого каталога 30.09 или порчу
того же состояния: сцена, на которой сторож обязан краснеть, и сцена, на которой
он обязан молчать. Сторож, никогда не видевший поломки, — украшение
(`.claude/rules/deployment.md`).

Литеральных дат и литеральных pid здесь нет вовсе: момент времени — ВХОД
(`now_fn`), а не окружение, поэтому сдвиг календаря на вердикт не влияет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import pin_identity_authority_census as C  # noqa: E402

#: Пины сцены. Значения — настоящие UUID живого каталога, чтобы сцена не была
#: абстрактной; сами по себе они ни на что не влияют, сверяется только равенство.
PIN_A = "aa70268e-4b52-42bf-a116-608b370f9501"
PIN_B = "ba68527f-8ec2-4c55-827a-8f4673ae047c"
PIN_C = "7da72d09-56ca-4ec5-a45f-59114353e487"
OTHER = "6f00d46b-8735-49ae-9ced-2a0fccc56ad0"

_FIXED_NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — момент подаётся входом now_fn и не читается у стенных часов


def _now():
    return _FIXED_NOW


class _Scene:
    """Одноразовый каталог data/ + подменённая таблица пинов."""

    def __init__(self, pins: dict, rows: list, positions: dict | None,
                 deployed: float | None = None):
        self._pins = pins
        self._rows = rows
        self._positions = positions
        self._deployed = deployed
        self._tmp = None

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        ddir = Path(self._tmp.name)
        (ddir / "adapter_orchestrator_status.json").write_text(
            json.dumps({"adapters": self._rows}), encoding="utf-8")
        if self._positions is not None:
            book = {"positions": self._positions}
            if self._deployed is not None:
                book["deployed_usd"] = self._deployed
            (ddir / "current_positions.json").write_text(
                json.dumps(book), encoding="utf-8")
        self._patch = mock.patch.dict(
            "spa_core.monitoring.adapter_status_generator._POOL_ID_LOOKUP",
            self._pins, clear=True)
        self._patch.start()
        return ddir

    def __exit__(self, *exc):
        self._patch.stop()
        self._tmp.cleanup()
        return False


def _row(key, pool, tvl=10_000_000.0, apy=4.0, src="live"):
    return {"protocol": key, "pool_id": pool, "tvl_usd": tvl,
            "apy_pct": apy, "tvl_source": src}


class HonoursAndBreaches(unittest.TestCase):
    """Положительный контроль в обе стороны на КАЖДЫЙ исход формы."""

    def test_pinned_pool_named_by_the_gate_is_honoured_and_silent(self):
        with _Scene({"k": PIN_A}, [_row("k", PIN_A)], {"k": 100.0}) as d:
            r = C.census(d, now_fn=_now)
        self.assertIsNone(r["unmeasured"])
        self.assertEqual(r["outcomes"]["honours"], ["k"])
        self.assertEqual(r["findings"], [])
        self.assertEqual(C.exit_code(r), 0)

    def test_a_different_pool_is_loud_and_names_both_pools(self):
        with _Scene({"k": PIN_A}, [_row("k", OTHER)], {"k": 100.0}) as d:
            r = C.census(d, now_fn=_now)
        self.assertEqual(r["outcomes"]["identity_mismatch"], ["k"])
        self.assertEqual(C.exit_code(r), 1)
        f = r["findings"][0]
        self.assertEqual(f["kind"], "identity_mismatch")
        # Обе личности названы ПОЛЯМИ, а не только прозой: вердикт, который
        # приходится вычитывать из строки, потребитель прочтёт по-своему.
        self.assertEqual(f["declared_pool"], PIN_A)
        self.assertEqual(f["gate_pool"], OTHER)

    def test_silent_pool_id_is_a_third_outcome_not_agreement_with_the_pin(self):
        """Ядро ADR-520: молчание о личности НЕ засчитывается как «пул тот же»."""
        for silent in (None, "", "   "):
            with self.subTest(silent=silent):
                with _Scene({"k": PIN_C}, [_row("k", silent)], {"k": 100.0}) as d:
                    r = C.census(d, now_fn=_now)
                self.assertEqual(r["outcomes"]["identity_unmeasured"], ["k"])
                self.assertEqual(r["outcomes"]["honours"], [])
                self.assertEqual(C.exit_code(r), 1)

    def test_key_absent_from_the_snapshot_is_not_a_mismatch(self):
        """Предмет соседа ADR-236 не считается находкой ДВАЖДЫ."""
        with _Scene({"k": PIN_A}, [_row("other", PIN_B)], {}) as d:
            r = C.census(d, now_fn=_now)
        self.assertEqual(r["outcomes"]["absent_from_gate"], ["k"])
        self.assertEqual(r["findings"], [])
        self.assertEqual(C.exit_code(r), 0)

    def test_outcome_form_is_closed_and_sums_to_the_population(self):
        pins = {"a": PIN_A, "b": PIN_B, "c": PIN_C, "d": PIN_A}
        rows = [_row("a", PIN_A), _row("b", OTHER), _row("c", None)]
        with _Scene(pins, rows, {}) as d:
            r = C.census(d, now_fn=_now)
        self.assertEqual(set(r["outcomes"]), set(C.OUTCOMES))
        self.assertEqual(sum(len(v) for v in r["outcomes"].values()),
                         r["population"])
        self.assertEqual(r["population"], 4)


class RefusalsAreNeverZero(unittest.TestCase):
    """Отказ обязан быть отличим от «нарушений нет» (инв. #17)."""

    def test_unreadable_snapshot_refuses_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                    "spa_core.monitoring.adapter_status_generator._POOL_ID_LOOKUP",
                    {"k": PIN_A}, clear=True):
                r = C.census(Path(tmp), now_fn=_now)
        self.assertTrue(r["unmeasured"])
        self.assertEqual(C.exit_code(r), 2)
        self.assertEqual(r["findings"], [])
        self.assertIn(C._UNMEASURED, "\n".join(C.report_lines(r)))

    def test_empty_snapshot_is_not_all_honoured(self):
        with _Scene({"k": PIN_A}, [], {"k": 100.0}) as d:
            r = C.census(d, now_fn=_now)
        self.assertTrue(r["unmeasured"])
        self.assertEqual(C.exit_code(r), 2)
        self.assertNotIn("✅", "\n".join(C.report_lines(r)))

    def test_rows_without_a_protocol_name_refuse(self):
        with _Scene({"k": PIN_A}, [{"pool_id": PIN_A}], {"k": 100.0}) as d:
            r = C.census(d, now_fn=_now)
        self.assertTrue(r["unmeasured"])
        self.assertEqual(C.exit_code(r), 2)

    def test_empty_pin_table_refuses_instead_of_reporting_a_clean_zero(self):
        with _Scene({}, [_row("k", PIN_A)], {"k": 100.0}) as d:
            r = C.census(d, now_fn=_now)
        self.assertTrue(r["unmeasured"])
        self.assertEqual(C.exit_code(r), 2)

    def test_missing_book_makes_money_unmeasured_not_zero(self):
        with _Scene({"k": PIN_A}, [_row("k", PIN_A)], None) as d:
            r = C.census(d, now_fn=_now)
        self.assertIsNone(r["unmeasured"])          # сверка личностей состоялась
        self.assertTrue(r["money"]["unmeasured"])   # а деньги — нет
        self.assertNotIn("held_by_outcome", r["money"])
        self.assertIn(C._UNMEASURED, "\n".join(C.report_lines(r)))

    def test_book_without_positions_section_is_unmeasured_money(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "adapter_orchestrator_status.json").write_text(
                json.dumps({"adapters": [_row("k", PIN_A)]}), encoding="utf-8")
            (d / "current_positions.json").write_text(
                json.dumps({"deployed_usd": 1.0}), encoding="utf-8")
            with mock.patch.dict(
                    "spa_core.monitoring.adapter_status_generator._POOL_ID_LOOKUP",
                    {"k": PIN_A}, clear=True):
                r = C.census(d, now_fn=_now)
        self.assertTrue(r["money"]["unmeasured"])


class MoneySplit(unittest.TestCase):
    """Доллары раскладываются по тем же исходам, и знаменатель честен."""

    def test_unpinned_dollars_count_in_the_denominator_not_in_authority(self):
        pins = {"good": PIN_A, "bad": PIN_B}
        rows = [_row("good", PIN_A), _row("bad", OTHER), _row("stranger", PIN_C)]
        book = {"good": 10.0, "bad": 20.0, "stranger": 70.0}
        with _Scene(pins, rows, book, deployed=100.0) as d:
            r = C.census(d, now_fn=_now)
        m = r["money"]
        self.assertEqual(m["held_by_outcome"]["honours"], 10.0)
        self.assertEqual(m["held_by_outcome"]["identity_mismatch"], 20.0)
        self.assertEqual(m["held_by_outcome"]["unpinned"], 70.0)
        # Власть — только доказанное тождество: 10 из 100, а не 10 из 30.
        self.assertAlmostEqual(m["authority_share"], 0.10)
        self.assertEqual(m["book_vs_deployed_gap_usd"], 0.0)

    def test_money_buckets_sum_to_the_book(self):
        pins = {"a": PIN_A, "b": PIN_B}
        rows = [_row("a", PIN_A), _row("b", None)]
        book = {"a": 1.5, "b": 2.5, "c": 3.0}
        with _Scene(pins, rows, book, deployed=7.0) as d:
            r = C.census(d, now_fn=_now)
        self.assertAlmostEqual(r["money"]["held_total_usd"], 7.0)

    def test_book_and_denominator_disagreement_is_named_not_hidden(self):
        with _Scene({"a": PIN_A}, [_row("a", PIN_A)], {"a": 5.0},
                    deployed=4.0) as d:
            r = C.census(d, now_fn=_now)
        self.assertEqual(r["money"]["book_vs_deployed_gap_usd"], 1.0)
        self.assertIn("расходятся", "\n".join(C.report_lines(r)))


class ReportHonesty(unittest.TestCase):
    """Зелёная галочка не печатается там, где есть находка или отказ."""

    def test_green_tick_only_when_every_named_key_is_honoured(self):
        with _Scene({"k": PIN_A}, [_row("k", PIN_A)], {"k": 1.0}) as d:
            clean = "\n".join(C.report_lines(C.census(d, now_fn=_now)))
        with _Scene({"k": PIN_A}, [_row("k", OTHER)], {"k": 1.0}) as d:
            dirty = "\n".join(C.report_lines(C.census(d, now_fn=_now)))
        self.assertIn("✅", clean)
        self.assertNotIn("✅", dirty)
        self.assertIn("CRITICAL", dirty)

    def test_exit_codes_are_three_distinct_outcomes(self):
        with _Scene({"k": PIN_A}, [_row("k", PIN_A)], {"k": 1.0}) as d:
            ok = C.exit_code(C.census(d, now_fn=_now))
        with _Scene({"k": PIN_A}, [_row("k", OTHER)], {"k": 1.0}) as d:
            loud = C.exit_code(C.census(d, now_fn=_now))
        with _Scene({}, [_row("k", PIN_A)], {"k": 1.0}) as d:
            blind = C.exit_code(C.census(d, now_fn=_now))
        self.assertEqual({ok, loud, blind}, {0, 1, 2})

    def test_generated_at_comes_from_the_injected_clock(self):
        with _Scene({"k": PIN_A}, [_row("k", PIN_A)], {"k": 1.0}) as d:
            r = C.census(d, now_fn=_now)
        self.assertEqual(r["generated_at"], _FIXED_NOW.isoformat())


class WiredIntoTheOfficeStep(unittest.TestCase):
    """Прибор, которого никто не читает, — та самая форма, что ловит ADR-208."""

    def test_office_step_imports_and_prints_this_census(self):
        src = (_REPO_ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn("pin_identity_authority_census", src)
        self.assertIn("власть пина у гейта финансирования", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
